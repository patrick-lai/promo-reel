"""Generic animated brand lockup for the dawn end card (`type: dawn`, `name_style: brand`).

Product-agnostic: the wordmark, colours and emblem all come from the shot's spec. The lockup is

    [emblem or builtin glyph]        optional; rotates in out of a small turn, scales up, blooms, then flares once
    wordmark                         light high-optical-size serif; letters rise out of blur with a tightening tracking.
                                     One part from `name`, or several parts with their own colour / weight
    ------ hairline horizon ------   grows from the centre, fades at both ends
    + one diagonal sheen across the letters

Pure framing and typography on a generated gradient card: it never touches app footage. All sizes are fractions of the frame height, so it
renders identically at 540p, 1080p and 2160p.

Per-shot keys (all optional; the keys of `DEFAULTS`):

    name: "Product"                      the wordmark text when no `wordmark:` parts are given (drawn in `col_name` / `weight`)
    wordmark: [{text, color, weight}]    parts laid out on one line, no gap between them (put spaces or hyphens inside `text`);
                                         `color` is [r,g,b] or "#rrggbb" (default `col_name`), `weight` the serif's variable weight (default `weight`)
    emblem_path: brand/emblem.png        project-relative transparent PNG shown above the wordmark; a sidecar `emblem.json` with
                                         {"centre": [x, y]} (normalised) says where its optical centre is (default: the box centre)
    mark: false | builtin                `builtin` draws a plain ring + four-point-star glyph when there is no emblem; false (default) draws none
    col_name, col_accent, col_glow       text colour, rule colour, aura/bloom colour ([r,g,b])
    tagline: "One verifiable line"       small serif line under the rule
    mark_frac, mark_y, name_y, name_frac, weight, aura, sparkles, track, track_start, rule, rule_y, rule_half,
    tagline_frac, t_tagline, tagline_y, t_mark, t_name, t_rule, t_flare, t_sheen, spin      sizes (frame fractions), weights and timings (s)
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

DEFAULTS = dict(
    name_style="brand",
    wordmark=None,                # [{text, color, weight}, ...]; default: one part from `name`
    emblem_path=None,             # transparent PNG shown as the mark (resolved by the caller, project-relative in specs)
    mark=False,                   # False: no glyph (an emblem_path still shows); "builtin": the generic ring + four-point-star glyph
    mark_frac=0.17,               # mark diameter / frame height
    mark_y=0.265,                 # mark centre y (frame fraction)
    name_y=0.50,                  # name centre y (frame fraction)
    name_frac=0.175,              # name font size / frame height
    weight=330,                   # serif weight (variable font); falls back to the font's default
    aura=0.20, sparkles=16,       # soft aura behind the lockup (alpha), and drifting twinkles around it
    track=0.02, track_start=0.14,  # letter spacing in em: final, and where the reveal starts
    rule=True, rule_y=0.625, rule_half=0.20,
    tagline=None, tagline_frac=0.042, t_tagline=1.0, tagline_y=0.69,   # one small serif line under the rule (verifiable claims only)
    t_mark=0.15, t_name=0.45, t_rule=0.95, t_flare=1.35, t_sheen=1.9,
    col_name=(236, 232, 223), col_accent=(200, 206, 226), col_glow=(130, 140, 205),
    spin=26.0,                    # degrees the mark turns through while it arrives
)

_CACHE = {}


def _ease(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


FALLBACK_SERIFS = ["/System/Library/Fonts/NewYork.ttf", "/System/Library/Fonts/Supplemental/Georgia.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"]


def _pick(paths):
    import os
    return next((p for p in list(paths or []) + FALLBACK_SERIFS if p and os.path.exists(p)), None)


def _font(path, px, wght, opsz_cap=60):
    px = max(8, int(round(px)))
    if path is None:                                   # no serif on this box: PIL's built-in font keeps the lockup renderable
        try:
            return ImageFont.load_default(size=px)
        except TypeError:
            return ImageFont.load_default()
    f = ImageFont.truetype(path, px)
    try:
        f.set_variation_by_axes(axis_values(f.get_variation_axes(), px, wght, opsz_cap))
    except Exception:           # static font, or Pillow built without FreeType variation support
        pass
    return f


def axis_values(axes, px, wght, opsz_cap=60):
    """Values for a variable font's axes, in axis order: the optical size follows the pixel size (capped), the Weight axis gets `wght`,
    and every other axis (e.g. the system serif's GRAD grade axis) keeps its default: setting those to the weight value pins them at
    their maximum and turns the lockup black-heavy."""
    vals = []
    for a in axes:
        nm = (a["name"].decode() if isinstance(a["name"], bytes) else str(a["name"])).lower()
        if "ptical" in nm or nm == "opsz":
            v = min(opsz_cap, px)
        elif "weight" in nm or nm == "wght":
            v = wght
        else:
            v = a["default"]
        vals.append(min(max(v, a["minimum"]), a["maximum"]))
    return vals


def _bez(p0, p1, p2, n=14):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in [i / n for i in range(n + 1)]]


# the builtin glyph's eight facets: (tip control point, tip) per quadrant side, lit and shaded halves (units of a 24-unit box)
_FACETS = [
    ("lit", (-2.12, -2.12), (-0.85, -4.37), (0.0, -10.4)), ("shade", (2.12, -2.12), (0.85, -4.37), (0.0, -10.4)),
    ("lit", (2.12, -2.12), (4.37, -0.85), (10.4, 0.0)), ("shade", (2.12, 2.12), (4.37, 0.85), (10.4, 0.0)),
    ("lit", (2.12, 2.12), (0.85, 4.37), (0.0, 10.4)), ("shade", (-2.12, 2.12), (-0.85, 4.37), (0.0, 10.4)),
    ("lit", (-2.12, 2.12), (-4.37, 0.85), (-10.4, 0.0)), ("shade", (-2.12, -2.12), (-4.37, -0.85), (-10.4, 0.0)),
]


GLYPH_COLS = dict(ring=(220, 224, 236), lit=(255, 255, 255), shade=(160, 168, 190))


def mark_tile(S, ss=4, cols=None):
    """RGBA tile (2.4 S square) with the builtin glyph (ring + four-point star) of diameter S, drawn at ss x and returned at that size
    (caller downsamples). `cols`: optional {ring, lit, shade} RGB overrides."""
    cols = {**GLYPH_COLS, **(cols or {})}
    T = int(S * 2.4) * ss
    u = S * ss / 21.0
    c = T / 2
    ring = Image.new("L", (T, T), 0)
    rd = ImageDraw.Draw(ring)
    rd.ellipse([c - 7.5 * u, c - 7.5 * u, c + 7.5 * u, c + 7.5 * u], fill=255)
    rd.ellipse([c - 6.0 * u, c - 6.0 * u, c + 6.0 * u, c + 6.0 * u], fill=0)
    star_all = Image.new("L", (T, T), 0)
    sd = ImageDraw.Draw(star_all)
    lit = Image.new("L", (T, T), 0)
    shade = Image.new("L", (T, T), 0)
    for kind, a, b, tip in _FACETS:
        pts = [(0, 0), a] + _bez(a, b, tip)
        poly = [(c + x * u, c + y * u) for x, y in pts]
        sd.polygon(poly, fill=255)
        (ImageDraw.Draw(lit) if kind == "lit" else ImageDraw.Draw(shade)).polygon(poly, fill=255)
    # the ring is cut away around the star (a 1.6-unit stroke)
    knock = star_all.filter(ImageFilter.MaxFilter(max(3, int(1.6 * u) | 1)))
    ring = ImageChops.multiply(ring, ImageChops.invert(knock))
    out = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    out.paste(Image.new("RGBA", (T, T), tuple(cols["ring"]) + (255,)), (0, 0), ring)
    out.paste(Image.new("RGBA", (T, T), tuple(cols["lit"]) + (255,)), (0, 0), lit)
    out.paste(Image.new("RGBA", (T, T), tuple(cols["shade"]) + (255,)), (0, 0), shade)
    return out


def emblem_tile(path, S, ss=4):
    """RGBA tile (2.4 S square, at ss x) with the emblem PNG scaled so its bounding box is S wide, centred on the emblem's own
    centre (the ring), read from emblem.json next to the PNG ({"centre": [x, y]} normalised; default the box centre)."""
    import json
    import os
    T = int(S * 2.4) * ss
    em = Image.open(path).convert("RGBA")
    W0, H0 = em.size
    cen = (0.5, 0.5)
    meta = os.path.splitext(path)[0] + ".json"
    if os.path.exists(meta):
        try:
            cen = tuple(json.load(open(meta))["centre"])
        except Exception:
            pass
    bb = em.getbbox() or (0, 0, W0, H0)
    k = S * ss / max(bb[2] - bb[0], 1)
    cx, cy = cen[0] * W0 - bb[0], cen[1] * H0 - bb[1]                  # emblem centre inside the cropped box
    em = em.crop(bb).resize((max(2, int((bb[2] - bb[0]) * k)), max(2, int((bb[3] - bb[1]) * k))), Image.LANCZOS)
    out = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    out.paste(em, (int(T / 2 - cx * k), int(T / 2 - cy * k)), em)
    return out


def _glow(alpha_img, radius, col, k):
    g = alpha_img.filter(ImageFilter.GaussianBlur(radius))
    g = g.point(lambda v: int(min(255, v * k)))
    lay = Image.new("RGBA", alpha_img.size, col + (0,))
    lay.putalpha(g)
    return lay


def _paste(out, layer, cx, cy, a=1.0):
    if a <= 0:
        return
    if a < 1:
        layer = layer.copy()
        layer.putalpha(layer.split()[3].point(lambda v: int(v * a)))
    x, y = int(round(cx - layer.width / 2)), int(round(cy - layer.height / 2))
    out.alpha_composite(layer, (x, y)) if (0 <= x and 0 <= y and x + layer.width <= out.width and y + layer.height <= out.height) else _clip_paste(out, layer, x, y)


def _clip_paste(out, layer, x, y):
    W, H = out.size
    lx0, ly0 = max(0, -x), max(0, -y)
    lx1, ly1 = min(layer.width, W - x), min(layer.height, H - y)
    if lx1 > lx0 and ly1 > ly0:
        out.alpha_composite(layer.crop((lx0, ly0, lx1, ly1)), (x + lx0, y + ly0))


def _rgb(v, default):
    """[r,g,b] / (r,g,b) / "#rrggbb" -> (r,g,b); anything else -> default."""
    if isinstance(v, str) and v.startswith("#") and len(v) == 7:
        try:
            return tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            return tuple(default)
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return tuple(int(x) for x in v[:3])
    return tuple(default)


def _parts(name, c):
    """The wordmark as [(text, rgb, weight)]: the `wordmark:` parts, else one part from `name`."""
    wm = c.get("wordmark")
    parts = []
    if isinstance(wm, (list, tuple)):
        for p in wm:
            if isinstance(p, str):
                p = {"text": p}
            if isinstance(p, dict) and str(p.get("text", "")) != "":
                parts.append((str(p["text"]), _rgb(p.get("color"), c["col_name"]), p.get("weight", c["weight"])))
    if not parts and name:
        parts = [(str(name), tuple(c["col_name"]), c["weight"])]
    return parts


def _layout(parts, fonts, track_px=0):
    """[(char, font, rgb, advance)] for the wordmark parts (`fonts`: weight -> font)."""
    seq = [(ch, fonts[w], col) for text, col, w in parts for ch in text]
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    return [(ch, f, col, d.textlength(ch, font=f)) for ch, f, col in seq]


def lockup(OW, OH, t, name, serif_paths, cfg=None):
    """RGBA full-frame layer of the brand lockup at card time t (seconds). `name` is the wordmark text unless cfg has `wordmark` parts."""
    c = {**DEFAULTS, **(cfg or {})}
    path = _pick(serif_paths)
    px = c["name_frac"] * OH
    parts = _parts(name, c)
    fonts = {w: _font(path, px, w) for w in {w for _, _, w in parts}}
    out = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))

    # ---- aura: a soft bloom the lockup sits in, breathing in with the mark
    ak = _ease((t - c["t_mark"]) / 1.8)
    if c["aura"] and ak > 0:
        key = ("aura", OW, OH)
        if key not in _CACHE:
            yy, xx = np.mgrid[0:OH, 0:OW].astype(np.float32)
            d = ((xx - OW / 2) / (0.42 * OW)) ** 2 + ((yy - 0.46 * OH) / (0.36 * OH)) ** 2
            _CACHE[key] = np.exp(-d * 1.6)
        al = (_CACHE[key] * c["aura"] * ak * 255).astype(np.uint8)
        au = Image.new("RGBA", (OW, OH), tuple(c["col_glow"]) + (0,))
        au.putalpha(Image.fromarray(al))
        out.alpha_composite(au)

    # ---- sparkles: tiny four-point twinkles drifting up around the lockup (seeded, so every render is identical)
    if c["sparkles"] and t > c["t_name"]:
        rng = np.random.default_rng(7)
        for i in range(int(c["sparkles"])):
            sx = OW * (0.5 + rng.uniform(-0.30, 0.30))
            sy0 = OH * rng.uniform(0.18, 0.72)
            ph, sp, sz = rng.uniform(0, 6.28), rng.uniform(0.9, 1.8), rng.uniform(0.004, 0.011) * OH
            tw = max(0.0, math.sin(sp * (t - c["t_name"]) * 2.2 + ph)) ** 3 * _ease((t - c["t_name"]) / 1.0)
            if tw < 0.02:
                continue
            sy = sy0 - 0.012 * OH * (t - c["t_name"])
            if c["tagline"] and abs(sy / OH - c["tagline_y"]) < 0.045 and abs(sx / OW - 0.5) < 0.30:
                continue                                    # keep the tagline clear of twinkles
            L = max(3, int(sz * (0.6 + 0.8 * tw) * 2))
            tile = Image.new("RGBA", (2 * L + 1, 2 * L + 1), (255, 255, 255, 0))
            prof = (np.clip(1 - np.abs(np.linspace(-1, 1, 2 * L + 1)), 0, 1) ** 2 * 255 * tw).astype(np.uint8)
            a = np.zeros((2 * L + 1, 2 * L + 1), np.uint8)
            a[L, :] = prof
            a[:, L] = np.maximum(a[:, L], prof)
            tile.putalpha(Image.fromarray(a))
            _paste(out, tile, sx, sy)

    # ---- letters
    cy = c["name_y"] * OH
    t_name = c["t_name"]
    tr = c["track"] + (c["track_start"] - c["track"]) * (1 - _ease((t - t_name) / 1.7))
    chars = _layout(parts, fonts)
    track_px = tr * px
    total = sum(w for *_, w in chars) + track_px * (len(chars) - 1)
    x = OW / 2 - total / 2
    text = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    amask = Image.new("L", (OW, OH), 0)
    for i, (ch, f, rgb, w) in enumerate(chars):
        p = _ease((t - t_name - i * 0.04) / 0.75)
        if p > 0 and ch.strip():
            pad = int(px * 0.5)
            tile = Image.new("L", (int(w) + 2 * pad, int(px * 1.6)), 0)
            ImageDraw.Draw(tile).text((pad, tile.height / 2), ch, font=f, fill=255, anchor="lm")
            blur = (1 - p) * 0.012 * OH
            if blur > 0.4:
                tile = tile.filter(ImageFilter.GaussianBlur(blur))
            tile = tile.point(lambda v, p=p: int(v * p))
            ox, oy = int(x - pad), int(cy - tile.height / 2 + (1 - p) * 0.014 * OH)
            col = Image.new("RGBA", tile.size, tuple(rgb) + (255,))
            text.paste(col, (ox, oy), tile)
            amask.paste(ImageChops.lighter(amask.crop((ox, oy, ox + tile.width, oy + tile.height)), tile), (ox, oy))
        x += w + track_px
    g_all = _ease((t - t_name) / 1.2)
    if g_all > 0:
        out.alpha_composite(_glow(amask, 0.02 * OH, tuple(c["col_glow"]), 0.9 * g_all))
    out.alpha_composite(text)

    # ---- sheen: one diagonal highlight sweeping across the letters
    ts = c["t_sheen"]
    if ts <= t <= ts + 1.0:
        bbox = amask.getbbox()
        if bbox:
            x0, y0, x1, y1 = bbox
            a = np.asarray(amask.crop(bbox), np.float32) / 255.0
            h, w = a.shape
            xs = np.arange(w)[None, :].astype(np.float32)
            ys = np.arange(h)[:, None].astype(np.float32)
            pos = -0.15 * w + 1.3 * w * _ease((t - ts) / 1.0)
            band = np.exp(-(((xs - pos) + 0.45 * ys) / (0.07 * w)) ** 2)
            al = (a * band * 0.95 * 255).astype(np.uint8)
            sh = Image.new("RGBA", (w, h), (255, 252, 244, 0))
            sh.putalpha(Image.fromarray(al))
            out.alpha_composite(sh, (x0, y0))

    # ---- tagline: small tracked serif, fades in under the rule
    if c["tagline"] and t > c["t_tagline"]:
        tp = _ease((t - c["t_tagline"]) / 0.8)
        tf = _font(path, c["tagline_frac"] * OH, 360) if path else _font(None, c["tagline_frac"] * OH, 360)
        d = ImageDraw.Draw(out)
        txt = c["tagline"]
        trk = 0.06 * c["tagline_frac"] * OH
        wsum = sum(d.textlength(ch, font=tf) for ch in txt) + trk * (len(txt) - 1)
        x = OW / 2 - wsum / 2
        layer = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for ch in txt:
            ld.text((x, c["tagline_y"] * OH), ch, font=tf, fill=tuple(c["col_name"]) + (int(255 * tp * 0.92),), anchor="lm")
            x += d.textlength(ch, font=tf) + trk
        out.alpha_composite(layer)

    # ---- hairline horizon under the name
    if c["rule"]:
        k = _ease((t - c["t_rule"]) / 1.3)
        if k > 0:
            half = k * c["rule_half"] * OW
            ry = int(c["rule_y"] * OH)
            n = max(2, int(half * 2))
            xs = np.linspace(-1, 1, n)
            al = (np.clip(1 - np.abs(xs), 0, 1) ** 0.7 * 0.9 * 255).astype(np.uint8)
            th = max(2, int(round(0.0035 * OH)))
            line = Image.new("RGBA", (n, th), tuple(c["col_accent"]) + (0,))
            line.putalpha(Image.fromarray(np.tile(al, (th, 1))))
            out.alpha_composite(line, (int(OW / 2 - n / 2), ry))

    # ---- the mark (emblem PNG, or the builtin glyph when `mark: builtin`): spins in, blooms, flares once
    if c["emblem_path"] or c["mark"]:
        S = c["mark_frac"] * OH
        mp = _ease((t - c["t_mark"]) / 1.5)
        if mp > 0:
            key = ("mark", int(S), c["emblem_path"])
            if key not in _CACHE:
                _CACHE[key] = emblem_tile(c["emblem_path"], int(S)) if c["emblem_path"] else mark_tile(int(S))
            big = _CACHE[key]
            ang = (1 - mp) * c["spin"]
            sc = 0.55 + 0.45 * mp
            tile = big.rotate(ang, Image.BICUBIC) if ang > 0.2 else big
            side = int(big.width / 4 * sc)
            tile = tile.resize((max(2, side), max(2, side)), Image.LANCZOS)
            mx, my = OW / 2, c["mark_y"] * OH
            al = tile.split()[3]
            _paste(out, _glow(al.resize(tile.size), 0.035 * OH, tuple(c["col_glow"]), 0.5 * mp), mx, my)
            _paste(out, tile, mx, my, mp)
            tf = t - c["t_flare"]
            if 0 <= tf <= 1.1:
                pk = math.sin(math.pi * tf / 1.1)
                L = int(0.11 * OW * (0.4 + 0.6 * _ease(tf / 0.7)))
                ray = Image.new("RGBA", (2 * L, max(2, int(0.003 * OH))), (255, 255, 255, 0))
                prof = (np.clip(1 - np.abs(np.linspace(-1, 1, 2 * L)), 0, 1) ** 2 * pk * 255).astype(np.uint8)
                ray.putalpha(Image.fromarray(np.tile(prof, (ray.height, 1))))
                _paste(out, ray, mx, my)
                _paste(out, ray.rotate(90, expand=True), mx, my)
    return out
