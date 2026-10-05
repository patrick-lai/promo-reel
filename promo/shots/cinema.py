"""`cinema` shot type: the cinematic-story style preset's renderer (style.preset: cinematic-story; look of a short film).

Real footage only. Each UI shot is a contained 16:9 panel (the real recording, camera-cropped, never touched) over a
heavily blurred + darkened copy of itself, so a screen recording reads as photographed with shallow depth of field. The
warm low-key grade, bloom, vignette and film grain are laid on the BACKDROP (and on non-UI footage such as scenery);
UI pixels are never graded (`look.protect_ui`, default true; see promo/grade.py). Team rule: never edit the app's UI.

Spec keys (per shot):
    source / t_in / speed / segs / cam   exactly like `clip` (cam keys in output time; slow eased camera only). `source` may be
                                omitted for a dark opening plate (title over dark).
    ui: true|false              does the frame show app UI? (default true). ui: false = scenery / dark plate: fully graded.
    look: {backdrop: dof|none|{...}, protect_ui, panel: {...}, dof: {...}, grade|vignette|bloom|grain: {...} | false}
                                deep-merged over the preset's look (defaults: promo/grade.py DEFAULT_LOOK)
    panel: {w, cy, ...}         per-shot shorthand for look.panel: run THIS shot's UI panel larger (or smaller) than the preset's
                                0.80 wide; w is clamped to 0.94 (ui-protect WARNs above it), cy = centre height (fraction)
    look.panel (depth of the contained panel; ALL of it is drawn outside the panel, the UI pixels are never edited; any block
    may be false):
        radius: 22              corner radius in 1920 canvas px (scales with the output), antialiased; 0 / false = square. The
                                interior of the rounded rect is byte-identical to the camera crop, only the 4 r x r corner blocks
                                blend with what is behind
        shadow: {layers: [{alpha, blur, dy, spread}, ...]}   two soft layers (tight + wide), fractions of the frame width
        rim: {alpha: 0.18, width: 1, color}                 1 px warm-white line just OUTSIDE the border
        glow: {alpha: 0.25, scale, blur, lift, warm}        light spill: a blurred, enlarged, lifted, warm copy of the panel behind it
        in: {dur: 0.35, from_scale: 0.97, fade: true}       entrance ease (off by default: cuts stay hard)
    look.backdrop: {plate, t, blur, dim, warm, parallax}    the world behind the panel. plate = a footage clip id (a still frame at t,
                                default 0) or an image / video path: a film-world plate (night sky, dawn, a scenic view), blurred and
                                graded, so panels float in the same world across the film. Without a plate: the dim blur of the
                                panel crop. `warm` = weight of the cool-indigo (top) to warm-amber (bottom) gradient lift (default
                                0.35 on the blurred copy, 0.12 on a plate; false = off). `parallax` (0.35) = fraction of the panel
                                camera's motion the backdrop follows (pan + zoom). blur defaults to look.dof; dim to look.dof on the blurred copy, 0.8 on a plate.
    look.backdrop: none + ui: true   full-bleed REAL footage with NO grading of the UI pixels: grade / bloom / grain / vignette are
                                skipped (protect_ui), only fade_in / fade_out touch the picture; lower_copy / scrim are not drawn on
                                it (gate copy-clear FAILs copy over full-bleed UI), so use it for a bare hero moment.
    fade_in / fade_out: s       from / to black (also fades the text); eased
    title_bloom: {text, at, dur, size, cy, color, fade}   opening title: glows in out of the dark (serif), then fades; ui: false
                                shots only. size = multiplier of the 132 px (1920 canvas) title, default 1.0, max 2.0; cy = centre
                                height as a fraction of the frame (0.5)
    lower_copy: [{text, at, dur, size, cy, x, color, align: left|center, scrim}]   sparse serif lower-third lines in the margin
                                under the panel. size = multiplier of the 38 px line, default 1.0, max 2.0 (a value > 4 is read
                                as the legacy absolute size in canvas px); cy = line centre in canvas px (default: middle of
                                the margin under the panel); color = [r, g, b]; scrim: true | {alpha: 0.5, height: 240} = a
                                soft dark gradient band (height in canvas px, centred on the line) drawn on the BACKDROP only,
                                restored over the UI panel box so UI pixels are never darkened, and not drawn at all on
                                full-bleed UI shots
    pullback: true | {w, cy, start, dim_to}   end wide hold: the panel shrinks (the world is revealed) while the camera
                                widens (set cam keys to end on w ~ 1.0)
    blur: N                     shutter blur (frames averaged), usually 1
Layout is resolution independent (all sizes are in 1920x1080 canvas units, scaled by OW / 1920).
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import claims as C
from .. import grade as G
from .. import render as R
from ..spec import resolve_cam_keys
from . import ShotType, shot_type
from .clip import Clip, segments

from ..styles import SERIF_FONTS  # noqa: E402

DEFAULT_CAM = [[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 0.95]]
COPY_PX, TITLE_PX = 38.0, 132.0           # base sizes in 1920x1080 canvas px; `size` is a multiplier of these
MAX_SIZE_MULT = 2.0                       # lower_copy / title_bloom size multiplier cap
LEGACY_PX_ABOVE = 4.0                     # a `size` above this is the old absolute canvas-px value
MAX_PANEL_W = 0.94                        # widest UI panel (fraction of the frame)
PLATE_DIM = 0.80                          # default brightness of a plate backdrop (a plate is already a dark film plate)
SCRIM_DEFAULT = dict(alpha=0.5, height=240.0)
TEXT_COLOR = (244, 236, 224)              # warm white
_FONTS = {}


# ---------------------------------------------------------------- look / geometry (pure, shared with the gates)
def style_look(spec):
    st = getattr(spec, "style", None) or {}
    return G.merge(G.DEFAULT_LOOK, st.get("look"))


def look_of(spec, shot):
    look = G.merge(style_look(spec), shot.get("look") if hasattr(shot, "get") else None)
    pn = shot.get("panel") if hasattr(shot, "get") else None
    if pn:                                           # per-shot `panel: {w, cy, ...}` shorthand wins over look.panel
        pn = {k: (float(v) if k in ("w", "cy") and v is not None else v) for k, v in pn.items() if v is not None or k not in ("w", "cy")}
        look["panel"] = G.merge(look["panel"], pn)
    return look


def is_ui(shot):
    return bool(shot.get("ui", True)) and bool(shot.get("source") or shot.get("segs") or shot.get("still"))


def backdrop_cfg(look):
    """Resolved `look.backdrop` (a string 'dof' / 'none' or a dict): {mode, plate, t, blur, dim, warm (alpha), parallax}."""
    b = look.get("backdrop", "dof")
    d = b if isinstance(b, dict) else {}
    mode = "none" if (b is False or b == "none" or d.get("mode") == "none") else "dof"
    plate = d.get("plate")
    warm = d.get("warm")
    warm = (0.12 if plate else 0.35) if warm is None or warm is True else (0.0 if warm is False else float(warm))
    return dict(mode=mode, plate=plate, t=float(d.get("t", 0.0) or 0.0), blur=d.get("blur"), dim=d.get("dim"), warm=warm,
                parallax=min(max(float(d.get("parallax", 0.35)), 0.0), 1.0))


def has_panel(look):
    return backdrop_cfg(look)["mode"] == "dof"


_PLATES = {}


def plate_path(spec, ref):
    """File of a backdrop plate: an existing path (as written, or resolved against the spec), else a footage clip id."""
    for cand in (ref, spec.resolve(ref) if hasattr(spec, "resolve") else None):
        if cand and os.path.exists(cand):
            return cand
    return spec.footage_path(ref)


def load_plate(spec, ref, t=0.0, max_w=1280):
    """One PIL RGB still of a plate (image file, or the frame of a video at t), downscaled to <= max_w; cached. None if
    it cannot be read (the composer then falls back to the blurred copy of the UI)."""
    try:
        path = plate_path(spec, ref)
    except Exception:  # noqa: BLE001
        return None
    k = (path, round(float(t), 3), max_w)
    if k not in _PLATES:
        im = None
        try:
            if os.path.splitext(path)[1].lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"):
                im = Image.open(path).convert("RGB")
            else:
                import io
                import subprocess
                raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{float(t):.3f}", "-i", path, "-frames:v", "1", "-vf",
                                      f"scale='min({max_w},iw)':-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                                     capture_output=True, timeout=60).stdout
                im = Image.open(io.BytesIO(raw)).convert("RGB") if raw else None
            if im is not None and im.width > max_w:
                im = im.resize((max_w, max(2, round(im.height * max_w / im.width))), Image.LANCZOS)
        except Exception:  # noqa: BLE001
            im = None
        _PLATES[k] = im
    return _PLATES[k]


def pullback_cfg(shot):
    pb = shot.get("pullback")
    if not pb:
        return None
    pb = {} if pb is True else dict(pb)
    return dict(w=pb.get("w", 0.62), cy=pb.get("cy", 0.5), start=pb.get("start", 0.15), dim_to=pb.get("dim_to"))


def panel_params(look, shot, t, dur):
    """(w_frac, cy_frac, dim) of the panel at shot-local time t (animated only by `pullback`)."""
    w, cy, dim = min(float(look["panel"]["w"]), MAX_PANEL_W), look["panel"]["cy"], look["dof"]["dim"]
    pb = pullback_cfg(shot)
    if pb:
        s = pb["start"] * dur
        p = R.ease((t - s) / max(dur - s, 1e-6))
        w, cy = w + (pb["w"] - w) * p, cy + (pb["cy"] - cy) * p
        dim = dim + ((pb["dim_to"] if pb["dim_to"] is not None else min(dim * 1.3, 1.0)) - dim) * p
    return w, cy, dim


def panel_box_of(spec, shot, size=(1920, 1080), t=0.0):
    """Panel box in output px at shot-local t (default: the start, where a pullback panel is largest). None = full-bleed."""
    look = look_of(spec, shot)
    if not has_panel(look) or not is_ui(shot):
        return None
    w, cy, _ = panel_params(look, shot, t, max(shot.dur, 1e-6) if hasattr(shot, "dur") else 1.0)
    return G.panel_box(size, w, cy)


def viewport(spec, shot, t=0.0):
    """Where the real footage is shown at shot-local t, in 1920x1080 canvas units (the panel, or the whole frame). This is the
    rect the generic text-edge gate samples, so a crop that cuts through a text row inside the panel is flagged (WARN)."""
    b = panel_box_of(spec, shot, t=t)
    return [float(v) for v in b] if b else [0.0, 0.0, 1920.0, 1080.0]


# ---------------------------------------------------------------- fonts
def serif_path(spec=None):
    cands = list((((getattr(spec, "style", None) or {}).get("typography") or {}).get("serif_fonts")) or []) + SERIF_FONTS
    for p in cands:
        p = spec.resolve(p) if spec is not None and hasattr(spec, "resolve") else p
        if os.path.exists(p):
            return p
    return None


def serif_font(spec, px, fallback=None):
    path = serif_path(spec) or fallback
    px = max(6, int(round(px)))
    k = (path, px)
    if k not in _FONTS:
        try:
            f = ImageFont.truetype(path, px) if path else ImageFont.load_default(size=px)
            try:        # variable fonts (New York): the default optical size is a hairline display cut; pick one for the size
                axes = f.get_variation_axes()
                f.set_variation_by_axes([min(max(px * 0.55, a["minimum"]), 72) if a["name"] == b"Optical Size" else a["default"] for a in axes])
            except Exception:  # noqa: BLE001
                pass
            _FONTS[k] = f
        except Exception:  # noqa: BLE001
            _FONTS[k] = ImageFont.load_default(size=px)
    return _FONTS[k]


def _text_size(font, text):
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font)
    return x1 - x0, y1 - y0, x0, y0


def size_px(item, base):
    """Font size in 1920x1080 canvas px of a lower_copy / title_bloom item: `size` is a multiplier of `base` (default 1.0,
    capped at MAX_SIZE_MULT); a value above LEGACY_PX_ABOVE is the old absolute px size and passes through unchanged."""
    v = item.get("size")
    if v is None:
        return base
    v = float(v)
    return v if v > LEGACY_PX_ABOVE else base * min(max(v, 0.1), MAX_SIZE_MULT)


def scrim_cfg(item):
    """{alpha, height} of an item's scrim (canvas px), or None."""
    sc = item.get("scrim")
    if not sc:
        return None
    sc = {**SCRIM_DEFAULT, **(sc if isinstance(sc, dict) else {})}
    return dict(alpha=min(max(float(sc["alpha"]), 0.0), 0.9), height=max(float(sc["height"]), 1.0))


def scrim_profile(n, centre, height, alpha):
    """(n,) darkening 0..alpha: a smoothstep falloff centred on `centre`, zero beyond +-height/2 (a soft band, no hard edge)."""
    d = np.abs(np.arange(n, dtype=np.float32) + 0.5 - centre) / max(height / 2.0, 1e-6)
    u = np.clip(1.0 - d, 0.0, 1.0)
    return alpha * u * u * (3.0 - 2.0 * u)


def title_cfg(shot):
    t = shot.get("title_bloom")
    return dict(t) if t else None


def copy_items(shot):
    return [dict(c) for c in (shot.get("lower_copy") or [])]


def copy_text(spec, item):
    return C.text_of(spec.raw, item) if getattr(spec, "raw", None) is not None else item["text"]


def copy_box(spec, shot, item, size=(1920, 1080), look=None, text=None):
    """Lower-third copy box [x0, y0, x1, y1] in output px (measured with the real font; size is in canvas units)."""
    look = look or look_of(spec, shot)
    W, H = size
    sc = W / 1920.0
    font = serif_font(spec, size_px(item, COPY_PX) * sc)
    tw, th, ox, oy = _text_size(font, text if text is not None else copy_text(spec, item))
    pb = panel_box_of(spec, shot, size)
    if item.get("cy") is not None:
        cy = item["cy"] * sc
    elif pb:
        cy = (pb[3] + H) / 2.0
    else:
        cy = 0.90 * H
    align = item.get("align", "left")
    if item.get("x") is not None:
        x = item["x"] * sc
    elif align == "center":
        x = (W - tw) / 2.0
    else:
        x = pb[0] if pb else 0.0625 * W
    return [x, cy - th / 2.0, x + tw, cy + th / 2.0]


def camera_keys(shot):
    return resolve_cam_keys(shot.get("cam") or DEFAULT_CAM, shot.dur)


def camera_rates(shot):
    """(max zoom rate |d ln w| / s, max pan rate |d centre| / s) over the shot's camera keys (what the slow-camera gates measure)."""
    import math
    ks = camera_keys(shot)
    z = p = 0.0
    for (t0, x0, y0, w0, *_), (t1, x1, y1, w1, *_) in zip(ks, ks[1:]):
        dt = max(t1 - t0, 1e-6)
        z = max(z, abs(math.log(max(w1, 1e-6) / max(w0, 1e-6))) / dt)
        p = max(p, math.hypot(x1 - x0, y1 - y0) / dt)
    return z, p


# ---------------------------------------------------------------- text layers
class _Glyphs:
    """A text mask cropped to its bbox + padding; composited per frame with an opacity (and, for the title, a blur)."""

    def __init__(self, font, text, pad):
        w, h, ox, oy = _text_size(font, text)
        self.pad = pad
        self.w, self.h = w + 2 * pad, h + 2 * pad
        m = Image.new("L", (self.w, self.h), 0)
        ImageDraw.Draw(m).text((pad - ox, pad - oy), text, font=font, fill=255)
        self.mask = m

    def paste_xy(self, x, y):
        return int(round(x)) - self.pad, int(round(y)) - self.pad


def _blend(out, mask, xy, color, alpha, glow=None, shadow=0.0):
    """Composite a mask in `color` onto the RGB image `out` at xy (clipped to the frame). glow: blurred mask added (screen)."""
    W, H = out.size
    x, y = xy
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + mask.width), min(H, y + mask.height)
    if x1 <= x0 or y1 <= y0 or alpha <= 0:
        return out
    crop = (x0 - x, y0 - y, x1 - x, y1 - y)
    reg = G.to_f(out.crop((x0, y0, x1, y1)))
    m = np.asarray(mask.crop(crop), np.float32)[..., None] / 255.0
    col = np.asarray(color, np.float32).reshape(1, 1, 3) / 255.0
    if shadow:
        sh = np.asarray(mask.crop(crop).filter(ImageFilter.GaussianBlur(max(1.0, mask.height * 0.04))), np.float32)[..., None] / 255.0
        reg = reg * (1.0 - shadow * alpha * sh)
    if glow is not None:
        g = np.asarray(glow.crop(crop), np.float32)[..., None] / 255.0
        reg = 1.0 - (1.0 - reg) * (1.0 - np.clip(g * col * alpha, 0, 1))
    reg = reg * (1.0 - m * alpha) + col * m * alpha
    out.paste(G.to_img(reg), (x0, y0))
    return out


def black_level(t, dur, fin, fout):
    """0 = picture, 1 = black: eased fade in from black over `fin` s, fade out to black over the last `fout` s."""
    b = 0.0
    if fin:
        b = max(b, 1.0 - R.ease(t / fin))
    if fout:
        b = max(b, 1.0 - R.ease((dur - t) / fout))
    return b


# ---------------------------------------------------------------- the frame composer (pure given a source image)
class Composer:
    """Builds one output frame from an optional source image. All the look logic lives here so it can be tested without
    ffmpeg: compose(src_im, cam, t, i) -> RGB image of (OW, OH)."""

    def __init__(self, ctx, shot, spec=None):
        self.ctx, self.shot = ctx, shot
        self.spec = spec if spec is not None else ctx.spec
        self.W, self.H = ctx.OW, ctx.OH
        self.sc = self.W / 1920.0
        self.look = look_of(self.spec, shot)
        self.ui = is_ui(shot)
        self.protect = bool(self.look.get("protect_ui", True)) and self.ui
        self.panel = has_panel(self.look) and self.ui
        self.bd = backdrop_cfg(self.look)
        self.entr = G.entrance_cfg(self.look.get("panel")) if self.panel else None
        self.cam0 = tuple(camera_keys(shot)[0][1:4]) if self.panel else None
        self.plate = load_plate(self.spec, self.bd["plate"], self.bd["t"]) if (self.panel and self.bd["plate"]) else None
        if self.bd["plate"] and self.plate is None:                      # unreadable plate: the plain blurred-copy backdrop (the gate WARNs)
            b0 = self.look.get("backdrop")
            self.bd = backdrop_cfg({**self.look, "backdrop": {**(b0 if isinstance(b0, dict) else {}), "plate": None}})
        self.dur = shot.dur
        self.fin, self.fout = float(shot.get("fade_in", 0) or 0), float(shot.get("fade_out", 0) or 0)
        self.gvig = float((self.look.get("vignette") or {}).get("global", 0.0) or 0.0) if isinstance(self.look.get("vignette"), dict) else 0.0
        fb = getattr(ctx, "font_path", None)
        self.copies, self.scrims = [], []
        for it in copy_items(shot):
            txt = copy_text(self.spec, it)
            font = serif_font(self.spec, size_px(it, COPY_PX) * self.sc, fb)
            box = copy_box(self.spec, shot, it, (self.W, self.H), self.look, txt)
            self.copies.append((it, _Glyphs(font, txt, 6), (box[0], box[1])))
            self.scrims.append((scrim_cfg(it), (box[1] + box[3]) / 2.0))
        tc = title_cfg(shot)
        self.title = None
        if tc:
            font = serif_font(self.spec, size_px(tc, TITLE_PX) * self.sc, fb)
            g = _Glyphs(font, tc["text"], int(0.10 * self.W))
            cy = tc.get("cy", 0.5) * self.H
            tw, th, ox, oy = _text_size(font, tc["text"])
            self.title = (tc, g, ((self.W - tw) / 2.0, cy - th / 2.0))

    # -- pieces
    def _plain_look(self):
        """The resolved look without the global-vignette key (that one is applied separately, over everything)."""
        look = dict(self.look)
        if isinstance(look.get("vignette"), dict):
            look["vignette"] = {k: v for k, v in look["vignette"].items() if k != "global"}
        return look

    def _backdrop_fx(self, dim):
        look = self._plain_look()
        frame_no = self._i

        def fx(bd):
            return G.to_img(G.apply_look_arr(G.to_f(bd), look, frame_no, soft=True, bloom_scale=max(dim, 0.05)))
        return fx

    def _box(self, t):
        """(panel box in output px, backdrop dim, opacity) at shot-local t: the settled/pullback geometry times the entrance ease."""
        wf, cyf, dim = panel_params(self.look, self.shot, t, self.dur)
        s, op = G.entrance_at(self.entr, t, R.ease)
        return G.panel_box((self.W, self.H), wf * s, cyf), dim, op

    def _backdrop(self, src, cam, dim):
        """The world behind the panel: a plate (drifting at `parallax` of the camera) or a dim blurred copy of the UI crop
        (cropped at `parallax` of the camera's motion), lifted by the cool-to-warm gradient; the look is applied after."""
        W, H = self.W, self.H
        d, bc = self.look["dof"], self.bd
        blur = bc["blur"] if bc["blur"] is not None else d["blur"]
        k = bc["parallax"]
        if self.plate is not None:
            dm = (PLATE_DIM if bc["dim"] is None else bc["dim"]) * dim / max(d["dim"], 1e-6)       # pullback lifts via dim
            bd = G.make_backdrop(self.plate, (W, H), blur, dm, d["zoom"], view=G.plate_view(cam, self.cam0, k, (0.5, 0.5, 1.0 / max(d["zoom"], 1.0))))
        else:
            dm = dim if bc["dim"] is None else bc["dim"] * dim / max(d["dim"], 1e-6)
            small = R.frame_cam(self.ctx, src, *G.parallax_cam(cam, self.cam0, k), out=(max(2, W // 4), max(2, H // 4)))
            bd = G.make_backdrop(small, (W, H), blur, dm, d["zoom"])
        if bc["warm"]:
            bd = G.to_img(G.warm_lift(G.to_f(bd), bc["warm"]))
        return bd

    def _picture(self, src, cam, t):
        W, H = self.W, self.H
        if src is None:                                                # dark opening plate (no footage)
            return G.to_img(G.apply_look_arr(G.to_f(Image.new("RGB", (W, H), (8, 7, 9))), self._plain_look(), self._i, soft=True))
        if self.panel and self.look["panel"].get("pane3d") not in (None, False):
            # look.panel.pane3d: {...}: the UI as a floating, tilted 3D pane (promo/pane3d.py); the backdrop gets the usual look
            from .. import pane3d as P3
            wf, cyf, dim = panel_params(self.look, self.shot, t, self.dur)
            box = G.panel_box((W, H), wf, cyf)
            pw, ph = box[2] - box[0], box[3] - box[1]
            panel = R.frame_cam(self.ctx, src, *cam, out=(int(pw * 1.4), int(ph * 1.4)))
            bd = self._backdrop_fx(dim)(self._backdrop(src, cam, dim))
            p3 = self.look["panel"]["pane3d"]
            p3 = {**(p3 if isinstance(p3, dict) else {}), "w": pw / W, "cy": (box[1] + box[3]) / 2.0 / H}
            return P3.compose(panel, bd, t, self.dur, p3, (W, H))
        if self.panel:
            box, dim, op = self._box(t)
            pw, ph = box[2] - box[0], box[3] - box[1]
            panel = R.frame_cam(self.ctx, src, *cam, out=(pw, ph))
            return G.dof_backdrop(panel, box, (W, H), panel=self.look["panel"], backdrop=self._backdrop(src, cam, dim),
                                  fx=self._backdrop_fx(dim), opacity=op)
        im = R.frame_cam(self.ctx, src, *cam).convert("RGB")
        if self.protect:
            return im                                                  # full-bleed UI: no grade / bloom / grain at all
        return G.to_img(G.apply_look_arr(G.to_f(im), self._plain_look(), self._i))

    def _title(self, out, t):
        if not self.title:
            return out
        tc, g, (x, y) = self.title
        at, dur, fade = float(tc.get("at", 0.5)), float(tc.get("dur", 3.0)), float(tc.get("fade", 1.4))
        a = R.ease((t - at) / fade) * R.ease((at + dur - t) / max(tc.get("fade_out", 0.9), 1e-6))
        if a <= 0:
            return out
        r = (0.05 * (1.0 - R.ease((t - at) / fade)) + 0.012) * self.W          # wide soft glow that resolves into the title
        glow = g.mask.filter(ImageFilter.GaussianBlur(max(r, 1.0)))
        return _blend(out, g.mask, g.paste_xy(x, y), tuple(tc.get("color", TEXT_COLOR)), a, glow=glow)

    def _scrim(self, out, sc, cy, a, t):
        """Darken a soft band around row `cy` (px) by sc.alpha * a on the backdrop only: the UI panel box is restored from
        the undarkened frame, and a full-bleed UI shot gets no scrim at all."""
        if self.ui and not self.panel:
            return out
        W, H = out.size
        h = sc["height"] * self.sc
        y0, y1 = max(0, int(cy - h / 2.0)), min(H, int(cy + h / 2.0) + 1)
        if y1 <= y0:
            return out
        prof = scrim_profile(H, cy, h, sc["alpha"] * a)[y0:y1]
        band = out.crop((0, y0, W, y1))
        dark = G.to_img(G.to_f(band) * (1.0 - prof)[:, None, None])
        if self.panel:
            bx = self._box(t)[0]
            ix0, ix1, iy0, iy1 = max(0, bx[0]), min(W, bx[2]), max(y0, bx[1]), min(y1, bx[3])
            if ix1 > ix0 and iy1 > iy0:
                dark.paste(band.crop((ix0, iy0 - y0, ix1, iy1 - y0)), (ix0, iy0 - y0))
        out.paste(dark, (0, y0))
        return out

    def _copy(self, out, t):
        for (it, g, (x, y)), (sc, cy) in zip(self.copies, self.scrims):
            at, dur = float(it.get("at", 0.0)), float(it.get("dur", 3.0))
            f = float(it.get("fade", 0.6))
            a = min(R.ease((t - at) / f), R.ease((at + dur - t) / f))
            if a > 0:
                if sc:
                    out = self._scrim(out, sc, cy, a, t)
                out = _blend(out, g.mask, g.paste_xy(x, y), tuple(it.get("color", TEXT_COLOR)), a, shadow=0.5)
        return out

    def compose(self, src, cam, t, i):
        self._i = i
        out = self._picture(src, cam, t)
        if self.gvig:
            out = G.global_vignette(out, self.gvig)
        out = self._title(out, t)
        out = self._copy(out, t)
        b = black_level(t, self.dur, self.fin, self.fout)
        if b > 0:
            out = G.to_img(G.to_f(out) * (1.0 - b))
        return out


# ---------------------------------------------------------------- the shot type
@shot_type("cinema")
class Cinema(ShotType):
    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        total = shot.n / ctx.fps
        has_src = bool(cfg.get("source") or cfg.get("segs"))
        segs = segments(shot) if has_src else []
        srcs = [R.Source(spec.footage_path(s.get("source", cfg.get("source"))), s["t_in"], s["t_out"] + 0.1) for s in segs]
        bounds, acc = [], 0
        for s in segs:
            bounds.append((acc, acc + s["dur"]))
            acc += s["dur"]
        assert not segs or abs(acc - total) < 0.05, (shot.id, acc, total)
        keys = camera_keys(shot)
        seg_keys = [resolve_cam_keys(s["cam"], s["dur"]) if s.get("cam") else None for s in segs]
        blur = cfg.get("blur", 1)
        comp = Composer(ctx, shot)

        def f(i, t):
            if not segs:
                return comp.compose(None, None, t, i)
            k = max(j for j, (a, b) in enumerate(bounds) if t >= a - 1e-6)
            a, b = bounds[k]
            s = segs[k]
            u = min(1.0, (t - a) / max(b - a, 1e-6))
            im = srcs[k].frame(s["t_in"] + (s["t_out"] - s["t_in"]) * u, blur=blur)
            cam = R.cam_at(seg_keys[k], t - a) if seg_keys[k] else R.cam_at(keys, t)
            return comp.compose(im, cam, t, i)

        try:
            R.run_shot(ctx, shot, f)
        finally:
            for s_ in srcs:
                s_.close()
        ws = [k_[3] for k_ in keys]
        look = comp.look
        fx = [n for n in ("grade", "bloom", "vignette", "grain") if G.enabled(look.get(n))]
        return dict(src=cfg.get("label", cfg.get("source", "dark plate")),
                    inout="; ".join(f"{s['t_in']:.2f}-{s['t_out']:.2f} s ({(s['t_out'] - s['t_in']) / s['dur']:.2f}x)" for s in segs) or "none",
                    move=cfg.get("move", f"slow eased camera, box {max(ws):.2f} -> {min(ws):.2f} of frame width"
                                 + ("; pull-back" if pullback_cfg(shot) else "")),
                    caption=" / ".join(([f"title '{title_cfg(shot)['text']}'"] if title_cfg(shot) else [])
                                       + [f"'{copy_text(spec, c)}'" for c in copy_items(shot)]) or "none",
                    notes=(f"{'DoF panel' if comp.panel else 'full-bleed'}; look on {'backdrop only' if comp.protect else 'whole frame'}: "
                           + ", ".join(fx)) + (f"; {cfg['notes']}" if cfg.get("notes") else ""))

    def src_to_out(self, shot, t_src):
        return Clip.src_to_out(self, shot, t_src)

    def captions(self, ctx, shot):
        res = []
        tc = title_cfg(shot)
        if tc:
            res.append(dict(text=tc["text"], role="label", box=None, t0=float(tc.get("at", 0.5)),
                            t1=float(tc.get("at", 0.5)) + float(tc.get("dur", 3.0))))
        for it in copy_items(shot):
            res.append(dict(text=copy_text(ctx.spec, it), role="label", box=None, t0=float(it.get("at", 0.0)),
                            t1=float(it.get("at", 0.0)) + float(it.get("dur", 3.0))))
        return res
