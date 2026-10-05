"""Product panes as floating, lit, 3D-ish glass panes (promo-reel's answer to flat UI rectangles).

    compose(ui, backdrop, t, dur, cfg=None, size=None) -> RGB image

`ui` is the real screen recording, already camera-cropped (any size, ideally ~1.4x the pane's pixel size for crisp text);
`backdrop` is the world behind it (a plate, a graded blur, `world()` ...). What happens to the pane:

  pose      yaw / pitch tilt in perspective with a slow float (a few tenths of a degree and a few px), settling from a
            wider tilt while the pane reveals
  reveal    tilt-in + rise + fade + a soft left-to-right wipe over `enter` seconds (and an optional `leave`)
  depth     extruded edge (thickness, darker toward the back), a bevelled rim light, layered contact + ambient shadow,
            a floor reflection that fades out, and a lavender aura behind the pane

TEAM RULE 2 (never edit the app's UI): the UI pixels are only transformed geometrically (perspective warp, scale, rounded
corners, the reveal's alpha). Every light, shadow, wall, rim and reflection is drawn OUTSIDE the pane's silhouette or behind it:
nothing is graded, glossed, blurred or painted over the UI. Keep |yaw| <= 14 deg so text stays legible.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

DEFAULTS = dict(
    w=0.72, cx=0.5, cy=0.47,                    # pane width (fraction of the frame width) and centre
    yaw=-11.0, pitch=3.0, roll=0.0,             # degrees (negative yaw turns the right edge toward the camera)
    persp=2.8,                                  # camera distance in pane widths (smaller = stronger perspective)
    float_yaw=1.4, float_pitch=0.7, float_shift=0.006, float_period=7.0,
    enter=0.95, from_yaw=24.0, from_scale=0.90, rise=0.045, wipe=0.22, fade=0.12,
    leave=0.0,                                  # seconds of exit at the end of the shot (0 = hard cut)
    flash=None,                                 # {at, dur, alpha, color}: a coloured pulse of the aura (OUTSIDE the pane) at shot time `at`, e.g. green on Merged
    radius=20,                                  # corner radius in 1920 canvas px
    thickness=0.011,                            # extruded edge, fraction of the frame width
    wall=((120, 112, 214), (24, 22, 64)),       # wall colour near the face -> far
    rim_alpha=0.80, rim_width=2.2,              # bevel light just outside the face
    shadow=dict(alpha=0.70, blur=0.030, dx=0.008, dy=0.032), contact=dict(alpha=0.60, blur=0.0055, dy=0.006),
    reflection=dict(alpha=0.16, length=0.07, gap=0.008, blur=3.6),
    aura=dict(alpha=0.28, blur=0.055, color=(150, 138, 255)),
)

_NOISE = {}


def merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        elif v is False and isinstance(out.get(k), dict):
            out[k] = dict(out[k], alpha=0.0)
        else:
            out[k] = v
    return out


def ease(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def ease_back(x, s=1.2):
    x = min(1.0, max(0.0, x))
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def _persp_coeffs(dst, src):
    """PIL PERSPECTIVE coefficients mapping OUTPUT (dst quad) -> INPUT (src quad)."""
    A, B = [], []
    for (x, y), (X, Y) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y])
        A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
        B += [X, Y]
    return np.linalg.lstsq(np.asarray(A, np.float64), np.asarray(B, np.float64), rcond=None)[0].tolist()


def project(pw, ph, W, H, cx, cy, yaw, pitch, roll, persp, shift=(0.0, 0.0)):
    """Screen corners (TL, TR, BR, BL) of a pw x ph pane centred at (cx, cy), rotated and viewed in perspective."""
    ya, pa, ra = math.radians(yaw), math.radians(pitch), math.radians(roll)
    D = persp * pw
    pts = []
    for x, y in ((-pw / 2, -ph / 2), (pw / 2, -ph / 2), (pw / 2, ph / 2), (-pw / 2, ph / 2)):
        x, y = x * math.cos(ra) - y * math.sin(ra), x * math.sin(ra) + y * math.cos(ra)
        z = 0.0
        x, z = x * math.cos(ya) + z * math.sin(ya), -x * math.sin(ya) + z * math.cos(ya)
        y, z = y * math.cos(pa) - z * math.sin(pa), y * math.sin(pa) + z * math.cos(pa)
        s = D / (D - z)
        pts.append((cx + shift[0] + x * s, cy + shift[1] + y * s))
    return pts


def _rr_mask(w, h, r):
    ss = 3
    m = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius=max(0, r * ss), fill=255)
    return m.resize((w, h), Image.LANCZOS)


def _shift(L, dx, dy):
    """Shift an L image by (dx, dy) px (no wrap)."""
    out = Image.new("L", L.size, 0)
    out.paste(L, (int(round(dx)), int(round(dy))))
    return out


def _blur(L, r):
    return L.filter(ImageFilter.GaussianBlur(max(0.4, r)))


def _over(base, rgb, alpha):
    """base float (H, W, 3) 0..255; rgb (3,) or (H, W, 3); alpha (H, W) float 0..1."""
    a = alpha[..., None]
    return base * (1 - a) + np.asarray(rgb, np.float32) * a


def _soft(L, radius):
    """Gaussian blur of an L image computed at 1/3 resolution (the shadows / aura / reflection are all soft)."""
    f = 3
    w, h = L.size
    if radius < 2.5 or w < 12 or h < 12:
        return _blur(L, radius)
    small = L.resize((max(2, w // f), max(2, h // f)), Image.BILINEAR)
    return _blur(small, radius / f).resize((w, h), Image.BILINEAR)


def compose(ui, backdrop, t, dur, cfg=None, size=None, frame=0):
    c = merge(DEFAULTS, cfg)
    W, H = size or backdrop.size
    k = W / 1920.0
    backdrop = backdrop.convert("RGB")
    if backdrop.size != (W, H):
        backdrop = backdrop.resize((W, H), Image.BILINEAR)
    # ---- pose
    enter = max(c["enter"], 1e-6)
    pe = ease(t / enter)
    pb = ease_back(t / enter, 0.9)
    leave = c["leave"]
    pl = 1.0 - ease((t - (dur - leave)) / leave) if leave > 0 and t > dur - leave else 1.0
    ph_ = 2 * math.pi * t / c["float_period"]
    wide = -1.0 if c["yaw"] <= 0 else 1.0                       # the entrance starts tilted further the same way
    yaw = c["yaw"] + (1 - pb) * c["from_yaw"] * wide + c["float_yaw"] * math.sin(ph_)
    pitch = c["pitch"] + c["float_pitch"] * math.sin(ph_ + 1.1) - (1 - pe) * 2.0
    scale = (c["from_scale"] + (1 - c["from_scale"]) * pb) * (0.97 + 0.03 * pl)
    alpha_g = min(1.0, t / max(c["fade"], 1e-3)) * pl                 # opaque within `fade` s: no ghost pane, no bleed-through
    pw = c["w"] * W * scale
    ar = ui.height / ui.width
    ph = pw * ar
    sx = c["float_shift"] * W * math.sin(ph_ + 0.4)
    sy = (1 - pe) * c["rise"] * H + c["float_shift"] * 0.6 * W * math.sin(ph_ + 2.0)
    quad = project(pw, ph, W, H, c["cx"] * W, c["cy"] * H, yaw, pitch, c["roll"], c["persp"], (sx, sy))
    xs, ys = [p[0] for p in quad], [p[1] for p in quad]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    # ---- region of interest: the pane plus its shadow / aura / reflection
    rf = c["reflection"]
    pad = int(0.20 * W)
    rx0, ry0 = int(max(0, x0 - pad)), int(max(0, y0 - 0.55 * pad))
    rx1, ry1 = int(min(W, x1 + pad)), int(min(H, y1 + rf["length"] * H + 0.5 * pad))
    rw, rh = rx1 - rx0, ry1 - ry0
    quad_r = [(x - rx0, y - ry0) for x, y in quad]
    # ---- warp the UI (RGB) and a rounded-rect mask with the same transform, straight into the region
    sw = int(min(max(ui.width, 2), 2.0 * pw))
    shh = int(round(sw * ar))
    src = ui.convert("RGB")
    if src.size != (sw, shh):
        src = src.resize((sw, shh), Image.LANCZOS)
    mask = _rr_mask(sw, shh, int(c["radius"] * k * sw / max(pw, 1)))
    coeffs = _persp_coeffs(quad_r, [(0, 0), (sw, 0), (sw, shh), (0, shh)])
    P = src.transform((rw, rh), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    A = mask.transform((rw, rh), Image.PERSPECTIVE, coeffs, Image.BILINEAR)
    # ---- reveal wipe (alpha only): a soft edge travelling left to right across the pane
    if c["wipe"] > 0 and pe < 1.0:
        soft = c["wipe"] * (x1 - x0)
        edge = (x0 - rx0) - soft + (x1 - x0 + 2 * soft) * ease(t / (enter * 0.85))
        ramp = np.clip((edge - np.arange(rw, dtype=np.float32)) / max(soft, 1.0), 0, 1)
        A = ImageChops.multiply(A, Image.fromarray((np.tile(ramp, (rh, 1)) * 255).astype(np.uint8)))
    if alpha_g < 1.0:
        A = A.point(lambda v: int(v * alpha_g))
    Af = np.asarray(A, np.float32) / 255.0
    full = np.asarray(backdrop, np.uint8).copy()
    out = full[ry0:ry1, rx0:rx1].astype(np.float32)
    # ---- aura (behind everything); it leads the reveal softly
    feather = np.minimum(np.minimum(np.arange(rw)[None, :], rw - 1 - np.arange(rw)[None, :]),
                         np.minimum(np.arange(rh)[:, None], rh - 1 - np.arange(rh)[:, None])).astype(np.float32)
    feather = np.clip(feather / max(0.07 * W, 1.0), 0, 1) ** 1.5            # glows fade to 0 before the region's border (no boxed halo)
    au = c["aura"]
    if au["alpha"] > 0:
        g = np.asarray(_soft(A, au["blur"] * W), np.float32) / 255.0
        out = _over(out, au["color"], np.clip(g * au["alpha"] * 1.5, 0, 1) * feather)
    fl = c.get("flash")
    if fl:
        tf = t - float(fl.get("at", 0.0))
        if 0.0 <= tf <= float(fl.get("dur", 0.7)):
            env = (1 - tf / float(fl.get("dur", 0.7))) ** 2
            gw = np.asarray(_soft(A, 0.075 * W), np.float32) / 255.0
            out = _over(out, tuple(fl.get("color", (110, 255, 170))), np.clip(gw * float(fl.get("alpha", 0.55)) * env * 1.6, 0, 1) * feather)
    # ---- floor reflection (fades out downward)
    if rf["alpha"] > 0 and alpha_g > 0.05:
        plane = (y1 - ry0) + rf["gap"] * H
        rgba = Image.merge("RGBA", (*P.split(), A))
        fl = rgba.transpose(Image.FLIP_TOP_BOTTOM)
        layer = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
        layer.paste(fl, (0, int(round(2 * plane - rh))))
        ra = np.asarray(layer.split()[3], np.float32) / 255.0
        yy = (np.arange(rh, dtype=np.float32) - plane) / max(rf["length"] * H, 1.0)
        fade = np.clip(1 - yy, 0, 1) ** 1.8 * (yy >= 0)
        ra = ra * fade[:, None] * rf["alpha"]
        rr = np.asarray(layer.convert("RGB").filter(ImageFilter.GaussianBlur(rf["blur"] * k)), np.float32)
        out = _over(out, rr, ra)
    # ---- shadows (ambient + contact)
    s = c["shadow"]
    sa = _soft(_shift(A, s["dx"] * W, s["dy"] * H), s["blur"] * W)
    out = _over(out, (4, 5, 16), np.asarray(sa, np.float32) / 255.0 * s["alpha"])
    s2 = c["contact"]
    sc = _blur(_shift(A, 0, s2["dy"] * H), s2["blur"] * W)
    out = _over(out, (2, 3, 10), np.asarray(sc, np.float32) / 255.0 * s2["alpha"])
    # ---- extruded edge: one depth pass (the nearest shifted copy wins), coloured near -> far
    T = c["thickness"] * W
    n = 9
    wdx = -math.sin(math.radians(yaw)) * T
    wdy = (0.55 + 0.25 * math.sin(math.radians(abs(pitch)))) * T
    depth = np.zeros((rh, rw), np.uint8)
    for i in range(1, n + 1):
        Ai = np.asarray(_shift(A, wdx * i / n, wdy * i / n))
        depth[(Ai > 100) & (depth == 0)] = i
    inside = np.asarray(A) > 100
    wall = (depth > 0) & ~inside
    if wall.any():
        near, far = (np.asarray(c["wall"][0], np.float32), np.asarray(c["wall"][1], np.float32))
        f = (depth.astype(np.float32) / n)[..., None]
        col = near * (1 - f) + far * f
        out = _over(out, col, wall.astype(np.float32) * np.clip(Af.max() if False else 1.0, 0, 1) * np.minimum(1.0, alpha_g + 0.0))
    # ---- bevel rim light just outside the face: brighter along the top / left, fading around
    if c["rim_alpha"] > 0:
        d = max(3, int(round(2 * c["rim_width"] * k)) | 1)
        ring = ImageChops.subtract(A.filter(ImageFilter.MaxFilter(d)), A)
        ring_f = np.asarray(ring, np.float32) / 255.0
        yy, xx = np.mgrid[0:rh, 0:rw].astype(np.float32)
        light = np.clip(1.0 - (0.55 * (xx - (x0 - rx0)) / max(x1 - x0, 1) + 0.75 * (yy - (y0 - ry0)) / max(y1 - y0, 1)), 0.12, 1.0)
        out = _over(out, (226, 222, 255), ring_f * light * c["rim_alpha"])
    # ---- the face: the real UI, only warped
    out = out * (1 - Af[..., None]) + np.asarray(P, np.float32) * Af[..., None]
    full[ry0:ry1, rx0:rx1] = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(full, "RGB")


# ---------------------------------------------------------------- a default world for panes that have no plate
def world(W, H, t=0.0, horizon=0.80, seed=3, rim=True):
    """Night-navy backdrop with a faint curved dawn-limb glow low in the frame and a little star dust (the end card's world)."""
    key = ("world", W, H, round(horizon, 3), seed, rim)
    if key not in _NOISE:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        v = yy / H
        top = np.array([7, 9, 26], np.float32)
        mid = np.array([14, 18, 46], np.float32)
        a = (np.clip(v / 0.9, 0, 1) ** 1.3)[..., None]
        base = top * (1 - a) + mid * a
        cxn = (xx / W - 0.5)
        limb = horizon + 0.07 * cxn ** 2 * 4 - 0.0           # slightly curved
        d = (yy / H - limb)
        glow = np.exp(-(np.clip(d, 0, None) / 0.07) ** 2) * (d >= 0) + np.exp(-(np.clip(-d, 0, None) / 0.12) ** 2) * (d < 0) * 0.55
        teal = np.array([36, 116, 132], np.float32)
        amber = np.array([255, 170, 96], np.float32)
        mixc = teal * 0.75 + amber * 0.25
        base = base + (glow[..., None] * mixc * (0.55 if rim else 0.0))
        aura = np.exp(-(((xx / W - 0.5) / 0.45) ** 2 + ((yy / H - 0.45) / 0.38) ** 2) * 1.6)[..., None] * np.array([40, 34, 90], np.float32) * 0.5
        base = base + aura
        rng = np.random.default_rng(seed)
        stars = np.zeros((H, W), np.float32)
        for _ in range(140):
            x, y = rng.integers(0, W), rng.integers(0, int(H * horizon))
            stars[y, x] = rng.uniform(0.3, 1.0)
        stars = np.asarray(Image.fromarray((stars * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.9)), np.float32)
        base = base + stars[..., None] * 3.2 * np.array([200, 196, 255], np.float32) / 255.0
        dr = np.random.default_rng(seed + 100)
        base = base + (dr.random((H, W, 1), dtype=np.float32) + dr.random((H, W, 1), dtype=np.float32) - 1.0) * 1.6      # triangular dither
        _NOISE[key] = np.clip(base, 0, 255).astype(np.uint8)
    return Image.fromarray(_NOISE[key], "RGB")


def plate_world(img, W, H, dim=0.45, blur=0.035, mix_world=0.22, seed=3):
    """A pane's backdrop from a specimen plate: the plate (cover-fit), heavily blurred and dimmed, with a little of the navy dawn world on top,
    so the pane sits in the colour of the cut it belongs to instead of one identical starfield."""
    im = img.convert("RGB")
    sc = max(W / im.width, H / im.height)
    im = im.resize((max(W, int(im.width * sc)), max(H, int(im.height * sc))), Image.BILINEAR)
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x0, y0, x0 + W, y0 + H))
    small = im.resize((max(8, W // 8), max(8, H // 8)), Image.BILINEAR).filter(ImageFilter.GaussianBlur(max(1.0, blur * W / 8)))
    bg = np.asarray(small.resize((W, H), Image.BICUBIC), np.float32) * dim
    w = np.asarray(world(W, H, seed=seed), np.float32)
    out = bg * (1 - mix_world) + w * mix_world * 1.2
    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    out = out * (0.85 + 0.15 * (1 - np.abs(yy - 0.5) * 2))                        # soft vertical falloff
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
