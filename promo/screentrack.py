"""Monitor tracking + perspective placement for the `screen` shot type (promo/shots/screen.py).

A GENERATED plate shows a big, flat, evenly lit pale monitor. This module finds the monitor's quadrilateral in every plate
frame and warps a REAL UI recording into it. Nothing here edits the app's UI (AGENTS.md rule 2): the UI is only resampled
(crop -> perspective warp), never graded, blurred, tinted or retouched; everything else (bezel fill, light spill, plate
grade) is drawn on the PLATE, outside the quad.

Pure numpy / scipy / PIL; no ffmpeg except `plate_frames` (which goes through render.Source).

    detect_quad(rgb, thr, sat_max, ...)  -> (corners (4, 2) px, info) | (None, info)    one frame; TL, TR, BR, BL
    track_quads(frames, cfg)             -> Track                                       whole shot: detect, hold/fill, smooth
    track_shot(spec, shot, ctx)          -> Track        cached in build/screen/ (what the renderer and the gates share)
    inset_quad(quad, d)                  edges moved inward by d px
    homography_coeffs / warp_region / quad_coverage / composite_screen   the warp + compositing (testable without ffmpeg)

Detection: luminance mask of the bright, low-saturation region (threshold = `thr` x the 99.5th-percentile luminance of the frame,
so it adapts to exposure), opened, largest connected component (scipy.ndimage.label), holes filled; initial corners = extreme
points of x+y / x-y; each side is then re-fitted (trimmed total-least-squares through the component's boundary pixels) and
adjacent lines are intersected, which gives sub-pixel corners and ignores rounded / blurred corners. A frame is a detection
FAILURE when the region is too small, not quad-shaped (fill ratio < min_fill) or the frame is too dark. Failed frames hold the
previous good quad (the first good one fills leading failures). Good quads get a 5-frame median (outliers) and a zero-lag
forward-backward EMA (`smooth`).

`touch` = the raw quad has a corner within `border_px` (1920-canvas px) of the frame border, i.e. the monitor is cut off by the
frame: the style gate `screen-quad` FAILs when that happens in more than 10 % of the frames.
"""
from __future__ import annotations

import hashlib
import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

CODE_VERSION = 3          # bump when detection / smoothing change (invalidates the track cache)

DEFAULTS = dict(
    thr=0.62,             # luminance threshold, fraction of the frame's 99.5th-percentile luminance
    sat_max=0.45,         # max HSV saturation of a screen pixel (the lit screen is pale / low-saturation)
    inset=0.004,          # shrink the quad by this fraction of the frame width before placing the UI (kills bright / blurred edge pixels)
    smooth=0.6,           # 0 = raw detections, -> 1 = very smooth (forward-backward EMA with alpha = 1 - smooth)
    quad=None,            # manual [[x, y] x4] (TL, TR, BR, BL), normalised to the plate frame: no detection at all
    min_area=0.02,        # detection fails below this fraction of the frame
    min_fill=0.80,        # ... or when region area / fitted quad area is below this (not a quad)
    det_w=960,            # detection width in px (decoded smaller than the render; coordinates are normalised)
    border_px=2.0,        # `touch`: a corner within this many 1920-canvas px of the frame border
    aspect=16 / 9,        # physical aspect of the screen = of the UI crop
    glow=dict(alpha=0.30, blur=0.04, lift=1.5),     # light spill outside the quad (False / alpha 0 = off)
    bezel=True,           # plate pixels between the inset quad and a hair outside the detected edge become bezel-dark (plate-only)
    grade=None,           # plate-only look: true | {grade|grain|bloom|vignette: {...} | false}; never applied inside the quad
)
ALLOWED_KEYS = set(DEFAULTS)
FAIL_FRAC_MAX = 0.15      # screen-quad: detection failures
TOUCH_FRAC_MAX = 0.10     # screen-quad: frames with the monitor cut off by the frame border


def screen_cfg(shot_or_cfg):
    """Resolved `screen:` block (defaults + the shot's keys; glow may be false)."""
    cfg = shot_or_cfg.cfg if hasattr(shot_or_cfg, "cfg") else shot_or_cfg
    sc = dict(cfg.get("screen") or {})
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k, v in sc.items():
        if k == "glow":
            out["glow"] = dict(DEFAULTS["glow"], **v) if isinstance(v, dict) else (dict(DEFAULTS["glow"]) if v is True else None)
        elif k in out:
            out[k] = v
    if not out["glow"] or float(out["glow"].get("alpha", 0) or 0) <= 0:
        out["glow"] = None
    return out


# ---------------------------------------------------------------- geometry helpers
def poly_area(q):
    q = np.asarray(q, float)
    x, y = q[:, 0], q[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def order_quad(pts):
    """4 points -> TL, TR, BR, BL (clockwise in image coordinates, starting at the point with the smallest x+y)."""
    p = np.asarray(pts, float).reshape(4, 2)
    c = p.mean(0)
    ang = np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0])
    p = p[np.argsort(ang)]                       # clockwise on screen (y down)
    k = int(np.argmin(p[:, 0] + p[:, 1]))
    return np.roll(p, -k, axis=0)


def _line_isect(p0, d0, p1, d1):
    a = np.array([[d0[0], -d1[0]], [d0[1], -d1[1]]], float)
    if abs(np.linalg.det(a)) < 1e-9:
        return None
    t = np.linalg.solve(a, np.asarray(p1, float) - np.asarray(p0, float))
    return np.asarray(p0, float) + t[0] * np.asarray(d0, float)


def inset_quad(q, d):
    """Quad with every edge moved inward by d px (adjacent offset lines intersected); d < 0 moves them outward. d == 0 returns q."""
    q = np.asarray(q, float)
    if d == 0:
        return q.copy()
    c = q.mean(0)
    lines = []
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        v = b - a
        n = np.hypot(*v)
        if n < 1e-9:
            return q.copy()
        v = v / n
        nrm = np.array([-v[1], v[0]])
        if np.dot(c - a, nrm) < 0:
            nrm = -nrm
        lines.append((a + nrm * d, v))
    out = []
    for i in range(4):
        p = _line_isect(*lines[i - 1], *lines[i])
        out.append(p if p is not None else q[i])
    out = np.asarray(out)
    return out if poly_area(out) > 0 else q.copy()


def edge_lengths(q):
    q = np.asarray(q, float)
    return [float(np.hypot(*(q[(i + 1) % 4] - q[i]))) for i in range(4)]


def touches_border(q_norm, border_px=2.0, canvas=(1920.0, 1080.0)):
    """True when any corner of a normalised quad is within border_px (canvas px) of the frame border (or outside it)."""
    q = np.asarray(q_norm, float) * np.asarray(canvas)
    return bool((q[:, 0] <= border_px).any() or (q[:, 0] >= canvas[0] - border_px).any()
                or (q[:, 1] <= border_px).any() or (q[:, 1] >= canvas[1] - border_px).any())


# ---------------------------------------------------------------- detection (one frame)
def _fit_line(pts, trim=2):
    """Trimmed total-least-squares line through pts (N, 2) -> (centroid, unit direction, n_used)."""
    p = pts
    for _ in range(trim + 1):
        m = p.mean(0)
        u, s, vt = np.linalg.svd(p - m, full_matrices=False)
        d = vt[0]
        nrm = np.array([-d[1], d[0]])
        r = (p - m) @ nrm
        keep = np.abs(r) <= max(1.0, 2.5 * r.std())
        if keep.all() or keep.sum() < 8:
            break
        p = p[keep]
    return m, d, len(p)


def detect_quad(rgb, thr=0.62, sat_max=0.45, min_area=0.02, min_fill=0.80, min_support=0.70):
    """Find the bright, low-saturation, quad-shaped region of an RGB uint8 frame.
    Returns (corners (4, 2) float px in pixel-EDGE coordinates, TL TR BR BL, info) or (None, info). info = {ok, why, area, fill}."""
    from scipy import ndimage as ndi
    a = np.asarray(rgb)
    H, W = a.shape[:2]
    f = a.astype(np.float32) / 255.0
    lum = f @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    mx, mn = f.max(2), f.min(2)
    sat = (mx - mn) / np.maximum(mx, 1e-3)
    ref = float(np.percentile(lum[::2, ::2], 99.5))
    info = dict(ok=False, why="", area=0.0, fill=0.0, ref=ref)
    if ref < 0.15:
        info["why"] = f"frame too dark (99.5th-percentile luminance {ref:.2f})"
        return None, info
    mask = (lum > thr * ref) & (sat < sat_max)
    k = max(1, int(round(W / 320.0)))
    mask = ndi.binary_opening(mask, structure=np.ones((k, k), bool))
    lab, n = ndi.label(mask)
    if n == 0:
        info["why"] = "no bright low-saturation region"
        return None, info
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    comp = lab == int(sizes.argmax())
    comp = ndi.binary_fill_holes(comp)
    area = float(comp.sum())
    info["area"] = area / (W * H)
    if area < min_area * W * H:
        info["why"] = f"largest bright region is only {100 * area / (W * H):.1f}% of the frame"
        return None, info
    ys, xs = np.nonzero(comp)
    px, py = xs + 0.5, ys + 0.5
    s, dg = px + py, px - py
    c0 = np.array([[px[s.argmin()], py[s.argmin()]], [px[dg.argmax()], py[dg.argmax()]],
                   [px[s.argmax()], py[s.argmax()]], [px[dg.argmin()], py[dg.argmin()]]], float)
    if poly_area(c0) < 4:
        info["why"] = "degenerate region"
        return None, info
    # refine: fit each side through the component's boundary pixels, intersect adjacent lines
    edge = comp & ~ndi.binary_erosion(comp)
    ey, ex = np.nonzero(edge)
    bp = np.stack([ex + 0.5, ey + 0.5], 1).astype(float)
    cen = np.array([px.mean(), py.mean()])
    diag = math.hypot(W, H)
    lines = []
    for i in range(4):
        a_, b_ = c0[i], c0[(i + 1) % 4]
        v = b_ - a_
        L = float(np.hypot(*v))
        if L < 1e-6:
            lines.append(None)
            continue
        v = v / L
        nrm = np.array([-v[1], v[0]])
        rel = bp - a_
        t = (rel @ v) / L
        dist = rel @ nrm
        sel = (t > 0.08) & (t < 0.92) & (np.abs(dist) < max(3.0, 0.03 * diag))
        if sel.sum() < 12:
            lines.append((a_, v))
            continue
        m, d, _ = _fit_line(bp[sel])
        nm = np.array([-d[1], d[0]])
        if np.dot(m - cen, nm) < 0:
            nm = -nm
        lines.append((m + 0.5 * nm, d))                   # boundary pixels are the INSIDE ones: edge sits 0.5 px further out
    corners = []
    for i in range(4):
        p = _line_isect(*lines[i - 1], *lines[i]) if lines[i - 1] is not None and lines[i] is not None else None
        if p is None or np.hypot(*(p - c0[i])) > 0.08 * diag:
            p = c0[i]
        corners.append(p)
    q = np.asarray(corners)
    qa = poly_area(q)
    fill = area / qa if qa > 0 else 0.0
    info["fill"] = fill
    # support: the share of the region's boundary pixels lying within a couple of px of the fitted quad's outline (a disc, a face or a
    # hand-eaten region has far less than a monitor, whose boundary IS the four sides)
    seg_d = []
    for i in range(4):
        a_, b_ = q[i], q[(i + 1) % 4]
        v = b_ - a_
        L2 = float(v @ v)
        if L2 < 1e-9:
            seg_d.append(np.full(len(bp), 1e9))
            continue
        t = np.clip(((bp - a_) @ v) / L2, 0.0, 1.0)
        seg_d.append(np.hypot(*(bp - (a_ + t[:, None] * v)).T))
    support = float((np.min(seg_d, axis=0) <= max(2.5, 0.006 * diag)).mean())
    info["support"] = support
    if fill < min_fill or fill > 1.0 / min_fill or support < min_support:
        info["why"] = (f"region is not quad-shaped (fills {100 * fill:.0f}% of its fitted quad, {100 * support:.0f}% of its boundary on the quad's sides): not a monitor")
        return None, info
    info["ok"] = True
    return order_quad(q), info


# ---------------------------------------------------------------- tracking (whole shot)
class Track:
    """Per-frame monitor quads of one shot, normalised to the plate frame (output aspect).
    raw (n, 4, 2): detections with failures held; ok (n,): detection succeeded; touch (n,): monitor cut off by the frame border;
    quads (n, 4, 2): smoothed (what the renderer uses, before the inset)."""

    def __init__(self, raw, ok, quads, touch, size, manual=False, why=None):
        self.raw, self.ok, self.quads, self.touch = raw, ok, quads, touch
        self.size, self.manual = tuple(size), manual
        self.why = why or []

    @property
    def n(self):
        return len(self.ok)

    @property
    def fail_frac(self):
        return float((~self.ok).mean()) if self.n else 1.0

    @property
    def touch_frac(self):
        return float(self.touch.mean()) if self.n else 0.0

    @property
    def usable(self):
        return self.n > 0 and bool(self.ok.any())

    def quad(self, i):
        return self.quads[min(max(int(i), 0), self.n - 1)]

    def bbox_canvas(self, i=None):
        """[x0, y0, x1, y1] in 1920x1080 canvas units: at frame i, or the union over the whole shot."""
        q = self.quads if i is None else self.quad(i)[None]
        q = q.reshape(-1, 2) * np.array([1920.0, 1080.0])
        return [float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max())]

    def to_json(self):
        return dict(version=CODE_VERSION, raw=self.raw.tolist(), ok=self.ok.tolist(), quads=self.quads.tolist(),
                    touch=self.touch.tolist(), size=list(self.size), manual=self.manual, why=self.why)

    @classmethod
    def from_json(cls, d):
        return cls(np.array(d["raw"], float), np.array(d["ok"], bool), np.array(d["quads"], float), np.array(d["touch"], bool),
                   d["size"], d.get("manual", False), d.get("why"))


def _ema_zero_phase(x, alpha):
    """Forward-backward EMA along axis 0 with odd-reflection padding (a linear drift passes through unchanged, no end bias)."""
    n = len(x)
    if n < 3 or alpha >= 1.0:
        return x
    m = int(min(n - 1, math.ceil(6.0 / alpha)))
    head = 2 * x[0] - x[1:m + 1][::-1]
    tail = 2 * x[-1] - x[-m - 1:-1][::-1]
    y = np.concatenate([head, x, tail], 0)
    z = y.copy()
    for i in range(1, len(z)):
        z[i] = alpha * y[i] + (1 - alpha) * z[i - 1]
    w = z.copy()
    for i in range(len(w) - 2, -1, -1):
        w[i] = alpha * z[i] + (1 - alpha) * w[i + 1]
    return w[m:m + n]


def smooth_quads(raw, smooth):
    """5-frame temporal median, then a zero-lag forward-backward EMA (alpha = 1 - smooth). raw: (n, 4, 2)."""
    from scipy.ndimage import median_filter
    x = np.asarray(raw, float)
    if smooth <= 0:
        return x
    if len(x) >= 5:
        x = median_filter(x, size=(5, 1, 1), mode="nearest")
    return _ema_zero_phase(x, max(1.0 - float(smooth), 0.05))


def hold_fill(raw, ok):
    """Failed frames take the previous good quad; leading failures take the first good one. raw (n, 4, 2) with NaN allowed."""
    raw = np.array(raw, float)
    idx = np.nonzero(ok)[0]
    if len(idx) == 0:
        return raw
    last = None
    for i in range(len(raw)):
        if ok[i]:
            last = raw[i]
        elif last is not None:
            raw[i] = last
    first = idx[0]
    raw[:first] = raw[first]
    return raw


def track_quads(frames, cfg, n=None):
    """frames: iterable of RGB uint8 arrays (all the same size). cfg: a resolved screen_cfg(). -> Track (normalised coords)."""
    raws, oks, touch, why, size = [], [], [], [], None
    for fr in frames:
        a = np.asarray(fr)
        H, W = a.shape[:2]
        size = (W, H)
        if cfg.get("quad") is not None:
            q = np.asarray(cfg["quad"], float).reshape(4, 2)
            raws.append(q)
            oks.append(True)
            continue
        q, info = detect_quad(a, cfg["thr"], cfg["sat_max"], cfg["min_area"], cfg["min_fill"])
        if q is None:
            raws.append(np.full((4, 2), np.nan))
            oks.append(False)
            if info["why"] and info["why"] not in why:
                why.append(info["why"])
        else:
            raws.append(q / np.array([W, H], float))
            oks.append(True)
    ok = np.array(oks, bool)
    raw = hold_fill(np.array(raws, float), ok) if len(raws) else np.zeros((0, 4, 2))
    touch = np.array([touches_border(q, cfg["border_px"]) if np.isfinite(q).all() else False for q in raw], bool)
    if cfg.get("quad") is not None:
        quads = raw.copy()
    else:
        quads = smooth_quads(raw, cfg["smooth"]) if ok.any() else raw
    return Track(raw, ok, quads, touch, size or (0, 0), manual=cfg.get("quad") is not None, why=why)


def plate_frames(path, t_in, speed, n, fps, det_w, out_aspect):
    """Yield n RGB uint8 arrays of the plate at the shot's frame times (nearest plate frame), cover-cropped to the output aspect
    and downscaled to det_w px wide. Uses render.Source (same time mapping as the renderer)."""
    from . import render as R
    W, H, pfps, dur = R.probe(path)
    dw = int(min(det_w, W))
    dh = max(2, int(round(dw * H / W)))
    src = R.Source(path, t_in, t_in + n / fps * speed + 0.2, prescale=(dw, dh))
    ow, oh = dw, max(2, int(round(dw / out_aspect)))
    try:
        last = None
        for i in range(n):
            im = src.frame(t_in + i / fps * speed)
            if im is None:
                im = last
            if im is None:
                raise RuntimeError(f"plate {path}: no frames at {t_in:.2f}s")
            last = im
            if abs((dw / dh) / out_aspect - 1) > 0.01:
                from . import render as R2
                im = R2.frame_cam(None, im, 0.5, 0.5, 1.0, out=(ow, oh))
            yield np.asarray(im)
    finally:
        src.close()


def _track_key(path, st, shot_cfg, n, fps, aspect, cfg):
    sig = dict(v=CODE_VERSION, size=st.st_size, mtime=st.st_mtime_ns, t_in=shot_cfg.get("plate_t_in", 0.0), speed=shot_cfg.get("plate_speed", 1.0),
               n=n, fps=fps, aspect=round(aspect, 5), cfg={k: cfg[k] for k in ("thr", "sat_max", "smooth", "quad", "min_area", "min_fill", "det_w", "border_px")})
    return hashlib.sha1(json.dumps(sig, sort_keys=True, default=str).encode()).hexdigest()[:16]


_MEMO = {}


def track_shot(spec, shot, plate_file, out_aspect=16 / 9, use_cache=True):
    """Track the shot's plate (shot.cfg plate_t_in / plate_speed, screen cfg). Cached on disk in <spec.build>/screen/ and in memory."""
    cfg = screen_cfg(shot)
    fps = shot.fps
    n = shot.n
    t_in = float(shot.cfg.get("plate_t_in", 0.0))
    speed = float(shot.cfg.get("plate_speed", 1.0))
    if cfg["quad"] is not None:
        return track_quads((np.zeros((2, 2, 3), np.uint8) for _ in range(n)), cfg)
    st = os.stat(plate_file)
    key = _track_key(plate_file, st, shot.cfg, n, fps, out_aspect, cfg)
    if use_cache and key in _MEMO:
        return _MEMO[key]
    bdir = getattr(spec, "build", None)
    cache = os.path.join(bdir, "screen", f"{shot.id}-{key}.json") if bdir else None
    if use_cache and cache and os.path.exists(cache):
        try:
            tr = Track.from_json(json.load(open(cache)))
            _MEMO[key] = tr
            return tr
        except Exception:  # noqa: BLE001
            pass
    tr = track_quads(plate_frames(plate_file, t_in, speed, n, fps, cfg["det_w"], out_aspect), cfg)
    if cache and tr.n:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w") as f:
            json.dump(tr.to_json(), f)
    _MEMO[key] = tr
    return tr


# ---------------------------------------------------------------- perspective warp (UI -> quad)
def homography_coeffs(dst, src):
    """PIL PERSPECTIVE coefficients (a..h) mapping OUTPUT (dst) points to INPUT (src) points:
    x_in = (aX + bY + c) / (gX + hY + 1), y_in = (dX + eY + f) / (gX + hY + 1). Points are continuous coordinates (pixel i spans
    [i, i+1]), which is what Pillow samples with."""
    A, b = [], []
    for (X, Y), (x, y) in zip(np.asarray(dst, float), np.asarray(src, float)):
        A.append([X, Y, 1, 0, 0, 0, -X * x, -Y * x])
        b.append(x)
        A.append([0, 0, 0, X, Y, 1, -X * y, -Y * y])
        b.append(y)
    return tuple(float(v) for v in np.linalg.solve(np.array(A, float), np.array(b, float)))


def region_of(q, size, pad=3):
    """Integer bbox (x0, y0, x1, y1) of quad q, grown by pad and clamped to the frame (W, H)."""
    q = np.asarray(q, float)
    x0 = max(0, int(math.floor(q[:, 0].min())) - pad)
    y0 = max(0, int(math.floor(q[:, 1].min())) - pad)
    x1 = min(int(size[0]), int(math.ceil(q[:, 0].max())) + pad)
    y1 = min(int(size[1]), int(math.ceil(q[:, 1].max())) + pad)
    return x0, y0, max(x0 + 1, x1), max(y0 + 1, y1)


def warp_region(ui, quad, region, edge_pad=3):
    """Perspective-warp the UI image ui (PIL RGB or uint8 array, h x w) so that its rectangle lands on quad (4, 2) px (frame
    coordinates). Returns the uint8 RGB array of `region` (x0, y0, x1, y1) of the frame. The UI is edge-padded by edge_pad px
    so the bicubic taps at the border never see black. Pure resampling: no colour operation."""
    a = np.asarray(ui.convert("RGB") if hasattr(ui, "convert") else ui)
    h, w = a.shape[:2]
    p = edge_pad
    padded = np.pad(a, ((p, p), (p, p), (0, 0)), mode="edge").astype(np.float32)
    x0, y0, x1, y1 = region
    dst = np.asarray(quad, float) - np.array([x0, y0], float)
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], float) + p
    co = homography_coeffs(dst, src)
    # one float ('F') transform per channel, then round: Pillow's 8-bit bicubic TRUNCATES (a pixel-aligned warp would lose a level)
    out = np.empty((y1 - y0, x1 - x0, 3), np.float32)
    for c in range(3):
        out[..., c] = np.asarray(Image.fromarray(padded[..., c], "F").transform((x1 - x0, y1 - y0), Image.PERSPECTIVE, co, resample=Image.BICUBIC))
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def quad_coverage(quad, region, ss=4):
    """(rh, rw) float32 antialiased coverage of a quad over `region` (supersampled polygon fill, box-filtered)."""
    x0, y0, x1, y1 = region
    rw, rh = x1 - x0, y1 - y0
    m = Image.new("L", (rw * ss, rh * ss), 0)
    pts = [((float(x) - x0) * ss, (float(y) - y0) * ss) for x, y in np.asarray(quad, float)]
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return np.asarray(m.resize((rw, rh), Image.BOX), np.float32) / 255.0


def bezel_color(plate, quad, off=4.0, samples=24):
    """Median plate colour just outside the quad's edges (the monitor's own bezel), float (3,) in 0..1."""
    H, W = plate.shape[:2]
    q = np.asarray(quad, float)
    c = q.mean(0)
    pts = []
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        v = b - a
        n = float(np.hypot(*v))
        if n < 1e-6:
            continue
        nrm = np.array([-v[1], v[0]]) / n
        if np.dot(a - c, nrm) < 0:
            nrm = -nrm
        for t in np.linspace(0.15, 0.85, samples // 4):
            pts.append(a + v * t + nrm * off)
    pts = np.array(pts)
    ok = (pts[:, 0] >= 0) & (pts[:, 0] < W) & (pts[:, 1] >= 0) & (pts[:, 1] < H)
    if not ok.any():
        return np.array([0.03, 0.03, 0.035])
    px = plate[pts[ok][:, 1].astype(int), pts[ok][:, 0].astype(int)].astype(np.float32) / 255.0
    return np.median(px, axis=0)


def _spill(ui_arr, quad, region, blur_px, lift, k=4):
    """Light spill of the warped UI over `region` (1/k resolution, blurred, lifted): float (rh, rw, 3) in 0..1."""
    x0, y0, x1, y1 = region
    rw, rh = x1 - x0, y1 - y0
    sw, sh = max(2, rw // k), max(2, rh // k)
    small_region = (0, 0, sw, sh)
    q = (np.asarray(quad, float) - np.array([x0, y0], float)) * np.array([sw / rw, sh / rh])
    h, w = ui_arr.shape[:2]
    ui_small = np.asarray(Image.fromarray(ui_arr, "RGB").resize((max(2, w // k), max(2, h // k)), Image.BOX))
    warped = warp_region(ui_small, q, small_region).astype(np.float32) / 255.0
    cov = quad_coverage(q, small_region, ss=2)
    img = Image.fromarray(np.clip(warped * cov[..., None] * 255.0 + 0.5, 0, 255).astype(np.uint8), "RGB")
    img = img.filter(ImageFilter.GaussianBlur(max(blur_px / k, 0.5)))
    big = np.asarray(img.resize((rw, rh), Image.BICUBIC), np.float32) / 255.0
    return np.clip(big * float(lift), 0.0, 1.0)


def composite_screen(plate, ui, quad, inset_px=0.0, glow=None, bezel=True, return_parts=False):
    """Place the UI image into the plate frame.

    plate: uint8 (H, W, 3) (already graded if the spec asks for it); ui: PIL RGB / uint8 array (the camera crop of the real UI);
    quad: (4, 2) px, the detected monitor (TL TR BR BL); inset_px: shrink for the UI placement.
    Inside the inset quad the output is the perspective-resampled UI and nothing else (antialiased over the 1-2 px edge).
    Outside: the plate, with (bezel) the ring between the detected edge and the inset quad turned bezel-dark, and (glow
    {alpha, blur (fraction of W), lift}) a soft screen-blend light spill of the warped UI. Returns the uint8 frame
    (and, with return_parts, the pure warp region + its coverage + region for the tests / gate)."""
    H, W = plate.shape[:2]
    inner = inset_quad(quad, inset_px) if inset_px > 0 else np.asarray(quad, float)
    out = plate.astype(np.float32) / 255.0
    ua = np.asarray(ui.convert("RGB") if hasattr(ui, "convert") else ui)
    reg = region_of(quad, (W, H), pad=3)
    x0, y0, x1, y1 = reg
    if glow:
        br = float(glow.get("blur", 0.04)) * W
        gx0, gy0 = max(0, int(x0 - 3 * br)), max(0, int(y0 - 3 * br))
        gx1, gy1 = min(W, int(x1 + 3 * br)), min(H, int(y1 + 3 * br))
        sp = _spill(ua, inner, (gx0, gy0, gx1, gy1), br, glow.get("lift", 1.5))
        a = float(glow.get("alpha", 0.3))
        sub = out[gy0:gy1, gx0:gx1]
        out[gy0:gy1, gx0:gx1] = 1.0 - (1.0 - sub) * (1.0 - a * sp)
    cov_in = quad_coverage(inner, reg)
    if bezel:
        # the detected edge sits at the 62 % level of the screen -> bezel transition, so a 1-2 px fringe of the blank screen's pale glow
        # still lies just OUTSIDE it: the ring runs from the inset quad to a slightly grown quad
        grow = max(1.0, 0.0012 * W)
        cov_out = quad_coverage(inset_quad(quad, -grow), reg)
        ring = np.clip(cov_out - cov_in, 0.0, 1.0)[..., None]
        col = bezel_color(plate, inset_quad(quad, -grow))
        sub = out[y0:y1, x0:x1]
        out[y0:y1, x0:x1] = sub * (1.0 - ring) + col.reshape(1, 1, 3) * ring
    warp = warp_region(ua, inner, reg)
    sub = out[y0:y1, x0:x1]
    c = cov_in[..., None]
    out[y0:y1, x0:x1] = sub * (1.0 - c) + (warp.astype(np.float32) / 255.0) * c
    res = np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)
    # byte-exact interior: where the coverage is 1 the output is the warp itself (no float round-trip)
    full = cov_in >= 1.0 - 1e-6
    res[y0:y1, x0:x1][full] = warp[full]
    return (res, warp, cov_in, reg) if return_parts else res


def ui_residual(frame, warp, cov, region, erode=2):
    """Max |frame - warp| over the quad interior (coverage 1, eroded by `erode` px): must be 0 (the UI is only resampled)."""
    from scipy.ndimage import binary_erosion
    x0, y0, x1, y1 = region
    inner = binary_erosion(cov >= 1.0 - 1e-6, iterations=erode)
    if not inner.any():
        return 0
    d = np.abs(frame[y0:y1, x0:x1].astype(int) - warp.astype(int))
    return int(d[inner].max())


# ---------------------------------------------------------------- debug drawing + CLI
def draw_quad(im, q_norm, color=(255, 40, 40), inset_q=None, width=3):
    d = ImageDraw.Draw(im)
    W, H = im.size
    pts = [(float(x) * W, float(y) * H) for x, y in np.asarray(q_norm, float)]
    d.line(pts + [pts[0]], fill=color, width=width)
    for i, (x, y) in enumerate(pts):
        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(255, 255, 0), width=2)
        d.text((x + 8, y + 6), "TL TR BR BL".split()[i], fill=(255, 255, 0))
    if inset_q is not None:
        p2 = [(float(x), float(y)) for x, y in np.asarray(inset_q, float)]
        d.line(p2 + [p2[0]], fill=(60, 255, 120), width=2)
    return im


def report_track(tr, fps, every=1.0):
    """Printable lines: per-`every`-second quads in 1920x1080 canvas px + summary."""
    lines = []
    step = max(1, int(round(every * fps)))
    for i in list(range(0, tr.n, step)) + ([tr.n - 1] if (tr.n - 1) % step else []):
        q = tr.quad(i) * np.array([1920.0, 1080.0])
        pts = " ".join(f"({x:.0f},{y:.0f})" for x, y in q)
        lines.append(f"t={i / fps:5.2f}s  TL TR BR BL = {pts}  {'ok' if tr.ok[i] else 'FAILED (held)'}{'  TOUCHES FRAME BORDER' if tr.touch[i] else ''}")
    lines.append(f"{tr.n} frames: detection failed on {100 * tr.fail_frac:.0f}%, monitor touches the frame border on {100 * tr.touch_frac:.0f}% "
                 f"(screen-quad FAILs above {int(FAIL_FRAC_MAX * 100)}% / {int(TOUCH_FRAC_MAX * 100)}%)")
    return lines


def main(argv):
    """`promo screen-quad <plate-clip-id|file> [-p promo.yaml] [--t-in S] [--dur S] [--fps N] [--speed X] [--thr F] [--quad JSON] [--out PNG]`"""
    import argparse
    ap = argparse.ArgumentParser(prog="promo screen-quad", description=main.__doc__)
    ap.add_argument("plate", help="footage clip id (needs -p) or a video file")
    ap.add_argument("-p", "--project", default=None, help="promo.yaml (to resolve a clip id)")
    ap.add_argument("--t-in", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=None, help="seconds to track (default: the whole plate)")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--thr", type=float, default=None)
    ap.add_argument("--sat-max", type=float, default=None)
    ap.add_argument("--smooth", type=float, default=None)
    ap.add_argument("--inset", type=float, default=None)
    ap.add_argument("--quad", default=None, help="manual quad JSON [[x,y]x4] normalised")
    ap.add_argument("--out", default=None, help="debug PNG (default build/screen-quad.png)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    from . import render as R
    path = a.plate
    if not os.path.exists(path):
        if not a.project:
            raise SystemExit(f"{a.plate!r} is not a file; pass -p promo.yaml to resolve it as a footage clip id")
        from .spec import load_spec
        path = load_spec(a.project, plugins=False).footage_path(a.plate)
    W, H, pfps, pdur = R.probe(path)
    dur = a.dur if a.dur is not None else max(0.1, (pdur - a.t_in) / a.speed)
    n = max(1, int(round(dur * a.fps)))
    cfg = screen_cfg({})
    for k, v in (("thr", a.thr), ("sat_max", a.sat_max), ("smooth", a.smooth), ("inset", a.inset)):
        if v is not None:
            cfg[k] = v
    if a.quad:
        cfg["quad"] = json.loads(a.quad)
    frames = list(plate_frames(path, a.t_in, a.speed, n, a.fps, cfg["det_w"], 16 / 9))
    tr = track_quads(frames, cfg)
    for line in report_track(tr, a.fps):
        print(line)
    out = a.out or os.path.join("build", "screen-quad.png")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    picks = sorted({min(n - 1, int(round(s * a.fps))) for s in np.arange(0, dur, max(dur / 6, 0.5))} | {n - 1})[:8]
    tiles = []
    for i in picks:
        fh, fw = frames[i].shape[:2]
        inner = inset_quad(tr.quad(i) * np.array([fw, fh], float), cfg["inset"] * fw)
        im = draw_quad(Image.fromarray(frames[i]).convert("RGB"), tr.quad(i), inset_q=inner)
        im = im.resize((640, int(640 * im.height / im.width)))
        ImageDraw.Draw(im).text((8, 8), f"t={i / a.fps:.2f}s {'ok' if tr.ok[i] else 'FAILED'}", fill=(255, 255, 255))
        tiles.append(im)
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (640 * cols, tiles[0].height * rows), (20, 20, 20))
    for k, im in enumerate(tiles):
        sheet.paste(im, ((k % cols) * 640, (k // cols) * tiles[0].height))
    sheet.save(out)
    print("debug sheet:", out)
    if a.json:
        print(json.dumps(tr.to_json()))
    return 0
