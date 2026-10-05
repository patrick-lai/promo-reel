"""Frame-level "look" functions for the cinematic-story preset (promo/shots/cinema.py): warm low-key grade, vignette,
highlight bloom, film grain, and the depth-of-field backdrop that makes a contained UI panel read as photographed.

TEAM RULE (AGENTS.md section 0.2): never edit the app's UI in post. Everything here is FRAMING and LIGHTING of the
space AROUND the UI, not an edit of it:

  * `dof_backdrop(frame, panel_box)` places the real UI frame, scaled to fit, over a heavily blurred + darkened copy of
    itself. The panel region of the result is exactly the (resampled) UI frame: no grade, no grain, no bloom, no shadow
    is ever composited inside `panel_box`. The optional edge shadow is drawn OUTSIDE the box only.
  * `dof_backdrop(..., panel=<look.panel>)` also gives the panel depth, all of it OUTSIDE the panel: antialiased rounded
    corners (the 4 corner blocks blend the real pixels with what is behind them; the interior is byte-identical to the
    resampled source), a layered soft drop shadow, a 1 px light rim just outside the border, and a faint light spill
    (a blurred, enlarged, lifted, warm copy of the panel behind it). The backdrop can be a film-world `plate` (night sky,
    dawn, the Workshop) instead of a blurred copy of the UI, always lifted with a cool-to-warm gradient so it is never flat
    black, and it drifts at a fraction (default 0.35) of the camera motion for parallax.
  * `protect_ui: true` (the default of the cinematic-story preset) means grade / bloom / grain / vignette are applied to
    the backdrop (and to non-UI footage such as scenery) only. The only things that may touch UI pixels are a fade to /
    from black and an OPTIONAL, capped, very light global vignette (`vignette.global`, default 0, gate-capped at
    `MAX_GLOBAL_VIGNETTE`). Text must stay legible.

All functions take and return PIL RGB images (numpy float32 in [0, 1] inside), are deterministic (grain is seeded by
`(seed, frame_index)`), and touch no global state, so any frame can be re-rendered on its own.
"""
from __future__ import annotations

import copy
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

MAX_GLOBAL_VIGNETTE = 0.15          # `promo check` FAILs a UI-protecting look above this

# Defaults of the `look:` block (preset cinematic-story starts from these; shot `look:` deep-merges over them).
# Each effect block may be `false` / `{on: false}` to switch it off.
DEFAULT_LOOK = dict(
    protect_ui=True,                # grade / bloom / grain / vignette only on the backdrop (and on ui: false footage)
    backdrop="dof",                 # dof = contained panel over a blurred copy of itself | none = full-bleed | a dict:
                                    # {plate: <clip id or path>, t, blur, dim, warm, parallax}, see backdrop_cfg()
    panel=dict(                     # panel width (fraction of the frame) and centre y (fraction of the height) + depth
        w=0.80, cy=0.455,
        radius=22,                  # corner radius in 1920x1080 canvas px (scales with the output); 0 / false = square
        shadow=dict(on=True, layers=[dict(alpha=0.50, blur=0.005, dy=0.004, spread=0.0),      # tight contact shadow
                                     dict(alpha=0.55, blur=0.034, dy=0.020, spread=0.004)]),  # wide soft shadow (fractions of the width)
        rim=dict(on=True, alpha=0.18, width=1.0, color=[255, 238, 214]),   # 1 canvas px light line just OUTSIDE the border
        glow=dict(on=True, alpha=0.25, scale=1.18, blur=0.045, lift=1.6, warm=[1.20, 1.0, 0.72]),   # light spill behind the panel
        **{"in": None}),            # entrance, e.g. {dur: 0.35, from_scale: 0.97, fade: true}; off by default (cuts stay hard)
    dof=dict(blur=0.022, dim=0.40, zoom=1.10, shadow=0.55, shadow_blur=0.018, shadow_dy=0.010),
    grade=dict(                     # warm low-key: lift / gamma / gain per channel + split tone (shadows cool, highlights amber)
        on=True, lift=[-0.012, -0.010, -0.004], gamma=[0.92, 0.96, 1.02], gain=[1.06, 1.00, 0.92],
        shadows=[-0.010, 0.004, 0.022], highlights=[0.060, 0.028, -0.030], split=1.0, saturation=0.94),
    vignette=dict(on=True, strength=0.55, radius=0.62, softness=0.55),     # backdrop vignette
    bloom=dict(on=True, threshold=0.55, radius=0.020, strength=0.45),      # radius = fraction of the frame width
    grain=dict(on=True, amount=0.030, size=1.0, seed=7),
)
DEFAULT_LOOK["vignette"]["global"] = 0.0     # optional very light vignette over everything (UI included); gate-capped


def merge(base, over):
    """Deep merge a `look:` override onto defaults. `false` for an effect block means off."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if v is False and isinstance(out.get(k), dict):
            out[k]["on"] = False
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def enabled(block):
    return bool(block) and (not isinstance(block, dict) or block.get("on", True))


# ---------------------------------------------------------------- conversions
def to_f(img):
    return np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0


def to_img(arr):
    return Image.fromarray((np.clip(arr, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), "RGB")


def _luma(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def _v3(v, default):
    if v is None:
        v = default
    if isinstance(v, (int, float)):
        v = [v] * 3
    return np.asarray(v, np.float32).reshape(1, 1, 3)


# ---------------------------------------------------------------- colour grade
def grade_arr(a, lift=(0, 0, 0), gamma=(1, 1, 1), gain=(1, 1, 1), shadows=(0, 0, 0), highlights=(0, 0, 0), split=1.0,
              saturation=1.0, **_):
    """Lift / gamma / gain + split tone on a float array. out = (gain * (x + lift * (1 - x))) ** (1 / gamma); then
    `shadows` is added with weight (1 - luma)^2 and `highlights` with luma^2 (both scaled by `split`); then saturation."""
    x = np.clip(a, 0.0, 1.0)
    x = x + _v3(lift, 0.0) * (1.0 - x)
    x = np.clip(x * _v3(gain, 1.0), 0.0, 1.0)
    x = np.power(x, 1.0 / np.maximum(_v3(gamma, 1.0), 1e-3))
    lum = _luma(x)[..., None]
    x = x + split * ((1.0 - lum) ** 2 * _v3(shadows, 0.0) + lum ** 2 * _v3(highlights, 0.0))
    if saturation != 1.0:
        lum = _luma(x)[..., None]
        x = lum + (x - lum) * saturation
    return np.clip(x, 0.0, 1.0)


def grade(img, **params):
    return to_img(grade_arr(to_f(img), **params))


# ---------------------------------------------------------------- vignette
@lru_cache(maxsize=8)
def _vig_mask(w, h, radius, softness):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2) / np.sqrt(2.0)     # 0 centre .. 1 corner
    t = np.clip((r - radius) / max(softness, 1e-3), 0.0, 1.0)
    return (t * t * (3 - 2 * t)).astype(np.float32)                                              # smoothstep 0..1


def vignette_arr(a, strength=0.5, radius=0.62, softness=0.55, **_):
    h, w = a.shape[:2]
    return a * (1.0 - strength * _vig_mask(w, h, round(radius, 4), round(softness, 4)))[..., None]


def vignette(img, **params):
    return to_img(vignette_arr(to_f(img), **params))


# ---------------------------------------------------------------- highlight bloom
def bloom_arr(a, threshold=0.6, radius=0.02, strength=0.4, tint=(1.0, 0.93, 0.80), **_):
    """Threshold the highlights (soft knee), blur them (computed at 1/4 size) and screen-add them back warm-tinted.
    `radius` is a fraction of the frame width."""
    h, w = a.shape[:2]
    s = 4
    sw, sh = max(1, w // s), max(1, h // s)
    small = np.asarray(Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)).resize((sw, sh), Image.BILINEAR), np.float32) / 255.0
    bright = np.clip((_luma(small) - threshold) / max(1.0 - threshold, 1e-3), 0.0, 1.0)[..., None] * small
    sm = Image.fromarray((bright * 255 + 0.5).astype(np.uint8)).filter(ImageFilter.GaussianBlur(max(0.5, radius * w / s)))
    glow = np.asarray(sm.resize((w, h), Image.BILINEAR), np.float32) / 255.0
    glow = glow * np.asarray(tint, np.float32).reshape(1, 1, 3) * strength
    return 1.0 - (1.0 - np.clip(a, 0, 1)) * (1.0 - np.clip(glow, 0, 1))                          # screen blend


def bloom(img, **params):
    return to_img(bloom_arr(to_f(img), **params))


# ---------------------------------------------------------------- film grain
def grain_arr(a, frame=0, amount=0.03, size=1.0, seed=7, **_):
    """Luminance grain, strongest in the mid tones. Deterministic: the noise field depends only on (seed, frame)."""
    h, w = a.shape[:2]
    rng = np.random.default_rng([int(seed), int(frame)])
    gw, gh = max(1, int(round(w / max(size, 1.0)))), max(1, int(round(h / max(size, 1.0))))
    n = rng.standard_normal((gh, gw)).astype(np.float32)
    if (gw, gh) != (w, h):
        n = np.asarray(Image.fromarray(n, "F").resize((w, h), Image.BILINEAR), np.float32)
    lum = _luma(np.clip(a, 0, 1))
    resp = 1.0 - 0.6 * np.abs(2.0 * lum - 1.0)                       # fade out in pure black / pure white
    return np.clip(a + (n * amount * resp)[..., None], 0.0, 1.0)


def grain(img, frame=0, **params):
    return to_img(grain_arr(to_f(img), frame=frame, **params))


# ---------------------------------------------------------------- the look stack
def apply_look_arr(a, look, frame=0, soft=False, bloom_scale=1.0):
    """grade -> bloom -> vignette -> grain with a resolved `look` dict (see DEFAULT_LOOK). Returns a float array.
    soft=True (already-blurred content such as the DoF backdrop): grade / bloom / vignette run at half resolution and
    are scaled back up; the grain is always laid on at full resolution. `bloom_scale` scales the bloom threshold (the
    backdrop is dimmed, so its highlights sit lower)."""
    if soft:
        h, w = a.shape[:2]
        small = to_f(to_img(a).resize((max(2, w // 2), max(2, h // 2)), Image.BILINEAR))
        small = apply_look_arr(small, {**look, "grain": False}, frame, bloom_scale=bloom_scale)
        a = to_f(to_img(small).resize((w, h), Image.BICUBIC))
        gr = look.get("grain")
        return grain_arr(a, frame=frame, **{k: v_ for k, v_ in gr.items() if k != "on"}) if enabled(gr) else a
    g = look.get("grade")
    if enabled(g):
        a = grade_arr(a, **{k: v for k, v in g.items() if k != "on"})
    b = look.get("bloom")
    if enabled(b):
        bp = {k: v for k, v in b.items() if k != "on"}
        bp["threshold"] = bp.get("threshold", 0.6) * bloom_scale
        a = bloom_arr(a, **bp)
    v = look.get("vignette")
    if enabled(v):
        a = vignette_arr(a, **{k: v_ for k, v_ in v.items() if k not in ("on", "global")})
    gr = look.get("grain")
    if enabled(gr):
        a = grain_arr(a, frame=frame, **{k: v_ for k, v_ in gr.items() if k != "on"})
    return a


def apply_look(img, look, frame=0):
    return to_img(apply_look_arr(to_f(img), look, frame))


def global_vignette(img, strength):
    """Very light vignette over the whole frame (touches UI pixels near the edges; capped by the gate)."""
    if not strength:
        return img
    return to_img(vignette_arr(to_f(img), strength=min(float(strength), MAX_GLOBAL_VIGNETTE), radius=0.55, softness=0.7))


# ---------------------------------------------------------------- panel geometry + depth-of-field backdrop
def panel_box(out_size, w_frac=0.80, cy_frac=0.455, aspect=None):
    """Contained panel (x0, y0, x1, y1) in output px: `w_frac` of the width, the output's aspect (or `aspect`), centred
    horizontally, vertical centre at `cy_frac` of the height. Even sizes, so the panel crop encodes cleanly."""
    W, H = out_size
    aspect = aspect or (W / H)
    pw = int(round(W * w_frac / 2)) * 2
    ph = int(round(pw / aspect / 2)) * 2
    x0 = (W - pw) // 2
    y0 = int(round(H * cy_frac - ph / 2))
    y0 = max(0, min(y0, H - ph))
    return (x0, y0, x0 + pw, y0 + ph)


def make_backdrop(frame, out_size, blur=0.022, dim=0.40, zoom=1.10, view=None):
    """Heavily blurred, darkened, slightly zoomed copy of `frame`, cover-fitted to `out_size`. `blur` is a fraction of
    the output width (a number > 1 is read as pixels). `view` = (cx, cy, w) (normalised, like a camera) crops that box of
    `frame` instead of the centred cover+zoom box (used to drift a plate for parallax); the box keeps the output aspect and
    is clamped inside the frame."""
    W, H = out_size
    fw, fh = frame.size
    if view is not None:
        vcx, vcy, vw = view
        cw = min(fw, max(2.0, vw * fw))
        ch = cw * H / W
        if ch > fh:
            ch, cw = fh, fh * W / H
        x0 = min(max(vcx * fw - cw / 2, 0.0), fw - cw)
        y0 = min(max(vcy * fh - ch / 2, 0.0), fh - ch)
        box = (x0, y0, x0 + cw, y0 + ch)
    else:
        s = max(W / fw, H / fh) * max(zoom, 1.0)                       # cover + zoom
        cw, ch = min(fw, W / s), min(fh, H / s)
        box = ((fw - cw) / 2, (fh - ch) / 2, (fw + cw) / 2, (fh + ch) / 2)
    k = 4
    small = frame.convert("RGB").resize((max(2, W // k), max(2, H // k)), Image.LANCZOS, box=box)
    r = (blur if blur > 1 else blur * W) / k
    small = small.filter(ImageFilter.GaussianBlur(max(r, 0.5)))
    big = small.resize((W, H), Image.BICUBIC)
    return to_img(to_f(big) * float(dim))


def edge_shadow(backdrop, box, strength=0.55, blur=0.018, dy=0.010):
    """Soft contact shadow around the panel, drawn on the BACKDROP, and masked to zero inside `box` (the panel is pasted
    over that area anyway): a shadow can never reach a UI pixel."""
    if not strength:
        return backdrop
    W, H = backdrop.size
    x0, y0, x1, y1 = box
    k = 4                                                           # the shadow is soft: build the mask at 1/4 size
    sw, sh = max(2, W // k), max(2, H // k)
    m = Image.new("L", (sw, sh), 0)
    off = dy * W / k
    ImageDraw.Draw(m).rectangle([x0 / k, y0 / k + off, x1 / k - 1, y1 / k - 1 + off], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(max(1.0, blur * W / k))).resize((W, H), Image.BILINEAR)
    ImageDraw.Draw(m).rectangle([x0, y0, x1 - 1, y1 - 1], fill=0)    # never inside the panel
    a = to_f(backdrop) * (1.0 - strength * (np.asarray(m, np.float32) / 255.0))[..., None]
    return to_img(a)


# ---------------------------------------------------------------- backdrop lift + parallax (pure)
WARM_TOP = (0.10, 0.12, 0.30)       # cool indigo
WARM_BOTTOM = (0.80, 0.48, 0.20)    # warm amber


def warm_lift(a, alpha=0.35, top=WARM_TOP, bottom=WARM_BOTTOM, power=1.5):
    """Mix a vertical cool-to-warm gradient into a float backdrop (top indigo -> bottom amber, weight `alpha`), so the
    world behind the panel is never flat black. `power` > 1 keeps the amber near the bottom."""
    if not alpha:
        return a
    h = a.shape[0]
    t = (np.arange(h, dtype=np.float32) + 0.5) / h
    t = (t ** power)[:, None, None]
    grad = np.asarray(top, np.float32).reshape(1, 1, 3) * (1.0 - t) + np.asarray(bottom, np.float32).reshape(1, 1, 3) * t
    return a * (1.0 - alpha) + grad * alpha


def parallax_cam(cam, cam0, k=0.35):
    """Camera (cx, cy, w) the backdrop copy follows: it moves / scales by `k` of the panel's camera motion since `cam0`
    (pan linearly, zoom geometrically: w = w0 * (w / w0) ** k)."""
    (cx, cy, w), (cx0, cy0, w0) = cam[:3], cam0[:3]
    return (cx0 + k * (cx - cx0), cy0 + k * (cy - cy0), w0 * (w / w0) ** k)


def plate_view(cam, cam0, k=0.35, base=(0.5, 0.5, 0.86)):
    """Crop (cx, cy, w), normalised to the plate, for a plate backdrop: starts at `base` and drifts by `k` of the panel
    camera's motion (pan in the same normalised units, zoom geometric)."""
    (cx, cy, w), (cx0, cy0, w0) = cam[:3], cam0[:3]
    return (base[0] + k * (cx - cx0), base[1] + k * (cy - cy0), base[2] * (w / w0) ** k)


# ---------------------------------------------------------------- rounded-rect coverage (analytic antialiasing)
@lru_cache(maxsize=16)
def _corner_cov(r):
    """(n, n) coverage of the top-left corner block of a rounded rect of radius r (r = a float key); n = ceil(r)."""
    n = int(np.ceil(r))
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    px, py = xx + 0.5, yy + 0.5
    d = np.hypot(r - px, r - py)
    c = np.clip(r - d + 0.5, 0.0, 1.0)
    c = np.where((px < r) & (py < r), c, 1.0).astype(np.float32)
    c.setflags(write=False)
    return c


def corner_radius_px(radius, out_w):
    """Panel corner radius in output px: `radius` is in 1920-wide canvas px; false / 0 = square."""
    if not radius:
        return 0.0
    return max(0.0, float(radius)) * out_w / 1920.0


def rr_cov(w, h, r):
    """(h, w) float32 coverage of a rounded rectangle filling w x h with corner radius r px: 1 inside, analytic
    antialiasing on the 4 corner arcs, exactly 1 everywhere else."""
    m = np.ones((h, w), np.float32)
    r = round(float(min(r, w / 2.0, h / 2.0)), 3)
    if r <= 0:
        return m
    c = _corner_cov(r)
    n = c.shape[0]
    m[:n, :n] = np.minimum(m[:n, :n], c)
    m[:n, w - n:] = np.minimum(m[:n, w - n:], c[:, ::-1])
    m[h - n:, :n] = np.minimum(m[h - n:, :n], c[::-1, :])
    m[h - n:, w - n:] = np.minimum(m[h - n:, w - n:], c[::-1, ::-1])
    return m


def corner_blocks(pw, ph, r):
    """The 4 corner blocks of a panel as numpy slices (rows, cols) into a (ph, pw) array: where the rounding lives."""
    n = int(np.ceil(round(min(r, pw / 2.0, ph / 2.0), 3))) if r > 0 else 0
    if n <= 0:
        return []
    return [(slice(0, n), slice(0, n)), (slice(0, n), slice(pw - n, pw)),
            (slice(ph - n, ph), slice(0, n)), (slice(ph - n, ph), slice(pw - n, pw))]


def _blurred_rr(region, box, r, blur_px, dy_px=0.0, spread_px=0.0, k=None):
    """Blurred rounded-rect mask over `region` = (rx0, ry0, rx1, ry1) in frame px: the panel `box` grown by `spread_px`,
    pushed down by `dy_px`, Gaussian blurred (sigma `blur_px`). Built at 1/k size. Returns float32 (rh, rw) in 0..1."""
    rx0, ry0, rx1, ry1 = region
    rw, rh = rx1 - rx0, ry1 - ry0
    if k is None:
        k = int(min(4, max(1, blur_px // 3)))
    x0, y0, x1, y1 = box
    gx0, gy0 = x0 - spread_px - rx0, y0 - spread_px - ry0 + dy_px
    gw, gh = (x1 - x0) + 2 * spread_px, (y1 - y0) + 2 * spread_px
    sw, sh = max(2, int(np.ceil(rw / k)) + 1), max(2, int(np.ceil(rh / k)) + 1)
    cov = rr_cov(max(2, int(round(gw / k))), max(2, int(round(gh / k))), (r + spread_px) / k)
    big = np.zeros((sh, sw), np.float32)
    ox, oy = int(round(gx0 / k)), int(round(gy0 / k))
    # paste with clipping
    sx0, sy0 = max(ox, 0), max(oy, 0)
    sx1, sy1 = min(ox + cov.shape[1], sw), min(oy + cov.shape[0], sh)
    if sx1 > sx0 and sy1 > sy0:
        big[sy0:sy1, sx0:sx1] = cov[sy0 - oy:sy1 - oy, sx0 - ox:sx1 - ox]
    m = Image.fromarray((big * 255 + 0.5).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(max(0.6, blur_px / k)))
    m = m.resize((sw * k, sh * k), Image.BILINEAR).crop((0, 0, rw, rh))
    return np.asarray(m, np.float32) / 255.0


def _region(box, pad, size):
    x0, y0, x1, y1 = box
    W, H = size
    return (max(0, int(x0 - pad)), max(0, int(y0 - pad)), min(W, int(x1 + pad)), min(H, int(y1 + pad)))


def panel_fx_cfg(panel):
    """Normalise a resolved `look.panel` dict: {radius, shadow|None, rim|None, glow|None, entrance|None, w, cy}."""
    p = panel or {}

    def blk(k):
        v = p.get(k)
        return dict(v) if enabled(v) and isinstance(v, dict) else None
    sh = blk("shadow")
    return dict(radius=float(p.get("radius") or 0.0), shadow=sh, rim=blk("rim"), glow=blk("glow"), entrance=entrance_cfg(p))


def entrance_cfg(panel):
    e = (panel or {}).get("in")
    if not e:
        return None
    e = {} if e is True else dict(e)
    return dict(dur=max(float(e.get("dur", 0.35)), 1e-3), from_scale=min(max(float(e.get("from_scale", 0.97)), 0.5), 1.0),
                fade=bool(e.get("fade", True)))


def entrance_at(cfg, t, ease=None):
    """(scale, opacity) of the panel at shot-local t for an `in` config (None -> (1, 1)). Smoothstep ease."""
    if not cfg:
        return 1.0, 1.0
    u = min(max(t / cfg["dur"], 0.0), 1.0)
    e = u * u * (3 - 2 * u) if ease is None else ease(u)
    return cfg["from_scale"] + (1.0 - cfg["from_scale"]) * e, (e if cfg["fade"] else 1.0)


def _shadow_layers(a, box, r, cfg, W):
    for ly in cfg.get("layers") or []:
        blur_px, dy_px = float(ly.get("blur", 0.02)) * W, float(ly.get("dy", 0.01)) * W
        spread = float(ly.get("spread", 0.0)) * W
        reg = _region(box, 3 * blur_px + abs(dy_px) + spread + 2, (W, a.shape[0]))
        m = _blurred_rr(reg, box, r, blur_px, dy_px, spread)
        sl = a[reg[1]:reg[3], reg[0]:reg[2]]
        sl *= (1.0 - float(ly.get("alpha", 0.5)) * m)[..., None]


def _glow(a, panel_arr, box, r, cfg, W):
    """Light spill: a blurred, enlarged, brightness-lifted, warm-tinted copy of the panel composited BEHIND it."""
    H = a.shape[0]
    x0, y0, x1, y1 = box
    pw, ph = x1 - x0, y1 - y0
    sc, blur_px = float(cfg.get("scale", 1.18)), float(cfg.get("blur", 0.045)) * W
    gw, gh = pw * sc, ph * sc
    reg = _region((x0 - (gw - pw) / 2, y0 - (gh - ph) / 2, x1 + (gw - pw) / 2, y1 + (gh - ph) / 2), 3 * blur_px + 2, (W, H))
    rx0, ry0, rx1, ry1 = reg
    k = 8
    sw, sh = max(2, (rx1 - rx0) // k + 1), max(2, (ry1 - ry0) // k + 1)
    gsw, gsh = max(2, int(round(gw / k))), max(2, int(round(gh / k)))
    mean = panel_arr.reshape(-1, 3).mean(0)
    tiny = np.asarray(Image.fromarray(np.clip(panel_arr * 255 + 0.5, 0, 255).astype(np.uint8)).resize((gsw, gsh), Image.BILINEAR), np.float32) / 255.0
    col = (0.5 * tiny + 0.5 * mean) * float(cfg.get("lift", 1.6)) * np.asarray(cfg.get("warm", (1.2, 1.0, 0.72)), np.float32)
    col = np.clip(col, 0.0, 1.0)
    cov = rr_cov(gsw, gsh, (r * sc) / k)
    ox, oy = int(round(((x0 + x1) / 2 - gw / 2 - rx0) / k)), int(round(((y0 + y1) / 2 - gh / 2 - ry0) / k))
    pm = np.zeros((sh, sw, 3), np.float32)
    mm = np.zeros((sh, sw), np.float32)
    sx0, sy0, sx1, sy1 = max(ox, 0), max(oy, 0), min(ox + gsw, sw), min(oy + gsh, sh)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    cc = cov[sy0 - oy:sy1 - oy, sx0 - ox:sx1 - ox]
    mm[sy0:sy1, sx0:sx1] = cc
    pm[sy0:sy1, sx0:sx1] = col[sy0 - oy:sy1 - oy, sx0 - ox:sx1 - ox] * cc[..., None]
    rad = max(0.6, blur_px / k)
    mb = Image.fromarray((mm * 255 + 0.5).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(rad))
    pb = Image.fromarray((pm * 255 + 0.5).astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(rad))
    up = lambda im: np.asarray(im.resize((sw * k, sh * k), Image.BILINEAR).crop((0, 0, rx1 - rx0, ry1 - ry0)), np.float32) / 255.0   # noqa: E731
    m, p = up(mb)[..., None], up(pb)
    al = float(cfg.get("alpha", 0.25))
    sl = a[ry0:ry1, rx0:rx1]
    sl[...] = sl * (1.0 - al * m) + al * p


def _rim(a, box, r, cfg, d):
    """1 px light line immediately OUTSIDE the panel border (the ring between the box grown by d and the box)."""
    x0, y0, x1, y1 = box
    pw, ph = x1 - x0, y1 - y0
    H, W = a.shape[:2]
    outer = rr_cov(pw + 2 * d, ph + 2 * d, r + d)
    inner = np.zeros_like(outer)
    inner[d:d + ph, d:d + pw] = rr_cov(pw, ph, r)
    ring = np.clip(outer - inner, 0.0, 1.0)
    ax0, ay0, ax1, ay1 = x0 - d, y0 - d, x1 + d, y1 + d
    cx0, cy0, cx1, cy1 = max(ax0, 0), max(ay0, 0), min(ax1, W), min(ay1, H)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    ring = ring[cy0 - ay0:cy1 - ay0, cx0 - ax0:cx1 - ax0]
    col = np.asarray(cfg.get("color", (255, 238, 214)), np.float32).reshape(1, 1, 3) / 255.0
    w = (float(cfg.get("alpha", 0.18)) * ring)[..., None]
    sl = a[cy0:cy1, cx0:cx1]
    sl[...] = sl * (1.0 - w) + col * w


def dof_backdrop(frame, panel_box_, out_size=None, blur=0.022, dim=0.40, zoom=1.10, shadow=0.55, shadow_blur=0.018,
                 shadow_dy=0.010, fx=None, panel=None, backdrop=None, opacity=1.0):
    """Place `frame` (the real UI frame), scaled to fit `panel_box_`, over a blurred + darkened copy of itself.

    Returns an RGB image of `out_size` (default: the frame size). Pixels inside `panel_box_` are the frame resampled to
    the box size and NOTHING else: the backdrop effects (`fx(backdrop) -> backdrop`, e.g. grade / grain) and every depth
    effect are applied to the backdrop BEFORE the panel is pasted, and they only ever exist outside the box.

    `backdrop`: a ready RGB backdrop image of `out_size` (a plate, a drifted copy ...) instead of `make_backdrop(frame)`.
    `panel`: a resolved `look.panel` dict (see DEFAULT_LOOK). When given, the legacy rectangular `edge_shadow` is replaced by
    the layered shadow / rim / light spill, and the corners are rounded (`panel.radius`): the interior of the rounded
    rectangle is byte-identical to the resampled frame; only the four r x r corner blocks blend the frame with what is
    behind it (antialiasing). `opacity` < 1 (panel entrance fade) mixes the whole panel with the backdrop.
    """
    out_size = out_size or frame.size
    x0, y0, x1, y1 = (int(v) for v in panel_box_)
    pw, ph = x1 - x0, y1 - y0
    W, H = out_size
    bd = backdrop if backdrop is not None else make_backdrop(frame, out_size, blur, dim, zoom)
    if fx is not None:
        bd = fx(bd)
    pan = frame.convert("RGB")
    if pan.size != (pw, ph):
        pan = pan.resize((pw, ph), Image.LANCZOS)
    if panel is None:                                                  # legacy: square panel, rectangular edge shadow
        bd = edge_shadow(bd, (x0, y0, x1, y1), shadow, shadow_blur, shadow_dy)
        bd.paste(pan, (x0, y0))
        return bd
    cfg = panel_fx_cfg(panel)
    r = min(corner_radius_px(cfg["radius"], W), pw / 2.0, ph / 2.0)
    a = to_f(bd)
    box = (x0, y0, x1, y1)
    if cfg["shadow"]:
        _shadow_layers(a, box, r, cfg["shadow"], W)
    pan_arr = np.asarray(pan, np.float32) / 255.0
    if cfg["glow"]:
        _glow(a, pan_arr, box, r, cfg["glow"], W)
    if cfg["rim"]:
        d = max(1, int(round(float(cfg["rim"].get("width", 1.0)) * W / 1920.0)))
        _rim(a, box, r, cfg["rim"], d)
    out = np.array(to_img(a))                                          # uint8 backdrop with depth, panel not yet pasted
    sub = out[y0:y1, x0:x1]
    p8 = np.asarray(pan)
    if opacity >= 1.0 - 1e-6:
        behind = {i: sub[sl].astype(np.float32) for i, sl in enumerate(corner_blocks(pw, ph, r))}
        sub[...] = p8                                                  # interior: byte-identical to the resampled frame
        cov = rr_cov(pw, ph, r) if r > 0 else None
        for i, sl in enumerate(corner_blocks(pw, ph, r)):
            c = cov[sl][..., None]
            sub[sl] = np.clip(p8[sl].astype(np.float32) * c + behind[i] * (1.0 - c) + 0.5, 0, 255).astype(np.uint8)
    else:
        c = (rr_cov(pw, ph, r) * float(min(max(opacity, 0.0), 1.0)))[..., None]
        sub[...] = np.clip(p8.astype(np.float32) * c + sub.astype(np.float32) * (1.0 - c) + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")
