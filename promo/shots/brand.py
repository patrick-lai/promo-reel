"""Animated brand lockup for the dawn end card (`type: dawn`, `name_style: brand`).

Brand cues come from the product itself: the four-point star inside a ring is the web app's favicon (indigo / lavender,
`clients/web/public/favicon.svg`), the amber is the Workshop's lamp. The lockup is

    [star in ring]                       rotates in out of a 60 degree turn, scales up, blooms, then flares once
    commission - ai                      light high-optical-size serif; letters rise out of blur with a tightening tracking;
                                         "commission" warm white, the hyphen lamp-amber, "ai" brand lavender (a touch heavier)
    ------ hairline horizon ------       grows from the centre, fades at both ends
    + one diagonal sheen across the letters as the amber dawn arrives

Pure framing and typography on a generated gradient card: it never touches app footage. All sizes are fractions of the frame height, so it
renders identically at 540p, 1080p and 2160p. Per-shot overrides (all optional) are the keys in `DEFAULTS`.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

DEFAULTS = dict(
    name_style="brand",
    emblem_path=None,             # PNG of the current product emblem (transparent); else the favicon-style star-in-ring drawn here
    mark=True,                    # the star-in-ring above the name
    mark_frac=0.17,               # star diameter / frame height
    mark_y=0.265,                 # mark centre y (frame fraction)
    name_y=0.50,                  # name centre y (frame fraction)
    name_frac=0.175,              # name font size / frame height
    weight=330, ai_weight=480,    # serif weights (variable font); falls back to the font's default
    aura=0.20, sparkles=16,       # lavender aura behind the lockup (alpha), and drifting twinkles around it
    track=0.02, track_start=0.14,  # letter spacing in em: final, and where the reveal starts
    rule=True, rule_y=0.625, rule_half=0.20,
    tagline=None, tagline_frac=0.042, t_tagline=1.0, tagline_y=0.69,   # one small serif line under the rule (verifiable claims only)
    t_mark=0.15, t_name=0.45, t_rule=0.95, t_flare=1.35, t_sheen=1.9,
    col_name=(246, 242, 236), col_dash=(255, 188, 108), col_ai=(206, 200, 255), col_glow=(150, 138, 255),
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
        axes = f.get_variation_axes()
        vals = []
        for a in axes:
            nm = a["name"].decode() if isinstance(a["name"], bytes) else str(a["name"])
            v = min(opsz_cap, px) if "ptical" in nm else wght
            vals.append(min(max(v, a["minimum"]), a["maximum"]))
        f.set_variation_by_axes(vals)
    except Exception:           # static font, or Pillow built without FreeType variation support
        pass
    return f


def _bez(p0, p1, p2, n=14):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in [i / n for i in range(n + 1)]]


# the favicon's eight facets: (tip control point, tip) per quadrant side, lit and shaded halves (units of the 24-unit favicon box)
_FACETS = [
    ("lit", (-2.12, -2.12), (-0.85, -4.37), (0.0, -10.4)), ("shade", (2.12, -2.12), (0.85, -4.37), (0.0, -10.4)),
    ("lit", (2.12, -2.12), (4.37, -0.85), (10.4, 0.0)), ("shade", (2.12, 2.12), (4.37, 0.85), (10.4, 0.0)),
    ("lit", (2.12, 2.12), (0.85, 4.37), (0.0, 10.4)), ("shade", (-2.12, 2.12), (-0.85, 4.37), (0.0, 10.4)),
    ("lit", (-2.12, 2.12), (-4.37, 0.85), (-10.4, 0.0)), ("shade", (-2.12, -2.12), (-4.37, -0.85), (-10.4, 0.0)),
]


def mark_tile(S, ss=4):
    """RGBA tile (2.4 S square) with the favicon mark of diameter S, drawn at ss x and returned at that size (caller downsamples)."""
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
    # the ring is cut away around the star (the favicon masks it with a 1.6-unit stroke)
    knock = star_all.filter(ImageFilter.MaxFilter(max(3, int(1.6 * u) | 1)))
    ring = ImageChops.multiply(ring, ImageChops.invert(knock))
    out = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    out.paste(Image.new("RGBA", (T, T), (216, 212, 250, 255)), (0, 0), ring)       # ring: dark-mode favicon #d8d4fa
    out.paste(Image.new("RGBA", (T, T), (255, 255, 255, 255)), (0, 0), lit)         # lit facets #ffffff
    out.paste(Image.new("RGBA", (T, T), (156, 149, 216, 255)), (0, 0), shade)       # shade facets #9c95d8
    return out


def emblem_tile(path, S, ss=4):
    """RGBA tile (2.4 S square, at ss x) holding the product emblem PNG scaled to diameter S."""
    T = int(S * 2.4) * ss
    em = Image.open(path).convert("RGBA")
    bb = em.getbbox()
    if bb:
        em = em.crop(bb)
    d = int(S * ss)
    em = em.resize((d, int(d * em.height / em.width)), Image.LANCZOS)
    out = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    out.paste(em, ((T - em.width) // 2, (T - em.height) // 2), em)
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


def _layout(name, font_a, font_b, track_px):
    """[(char, font, colour_key, advance)] with the dash and the tail ('ai') styled apart from the head."""
    head, dash, tail = name, "", ""
    if "-" in name:
        i = name.rindex("-")
        head, dash, tail = name[:i], "-", name[i + 1:]
    seq = [(ch, font_a, "col_name") for ch in head] + [(ch, font_a, "col_dash") for ch in dash] + [(ch, font_b, "col_ai") for ch in tail]
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    return [(ch, f, col, d.textlength(ch, font=f)) for ch, f, col in seq]


def lockup(OW, OH, t, name, serif_paths, cfg=None):
    """RGBA full-frame layer of the brand lockup at card time t (seconds)."""
    c = {**DEFAULTS, **(cfg or {})}
    path = _pick(serif_paths)
    px = c["name_frac"] * OH
    fa, fb = _font(path, px, c["weight"]), _font(path, px, c["ai_weight"])
    out = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))

    # ---- aura: a soft lavender bloom the lockup sits in, breathing in with the mark
    ak = _ease((t - c["t_mark"]) / 1.8)
    if c["aura"] and ak > 0:
        key = ("aura", OW, OH)
        if key not in _CACHE:
            yy, xx = np.mgrid[0:OH, 0:OW].astype(np.float32)
            d = ((xx - OW / 2) / (0.42 * OW)) ** 2 + ((yy - 0.46 * OH) / (0.36 * OH)) ** 2
            _CACHE[key] = np.exp(-d * 1.6)
        al = (_CACHE[key] * c["aura"] * ak * 255).astype(np.uint8)
        au = Image.new("RGBA", (OW, OH), c["col_glow"] + (0,))
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
    chars = _layout(name, fa, fb, 0)
    track_px = tr * px
    total = sum(w for *_, w in chars) + track_px * (len(chars) - 1)
    x = OW / 2 - total / 2
    text = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    amask = Image.new("L", (OW, OH), 0)
    for i, (ch, f, ck, w) in enumerate(chars):
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
            col = Image.new("RGBA", tile.size, c[ck] + (255,))
            text.paste(col, (ox, oy), tile)
            amask.paste(ImageChops.lighter(amask.crop((ox, oy, ox + tile.width, oy + tile.height)), tile), (ox, oy))
        x += w + track_px
    g_all = _ease((t - t_name) / 1.2)
    if g_all > 0:
        out.alpha_composite(_glow(amask, 0.02 * OH, c["col_glow"], 0.9 * g_all))
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
            ld.text((x, c["tagline_y"] * OH), ch, font=tf, fill=c["col_name"] + (int(255 * tp * 0.92),), anchor="lm")
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
            line = Image.new("RGBA", (n, th), c["col_ai"] + (0,))
            line.putalpha(Image.fromarray(np.tile(al, (th, 1))))
            out.alpha_composite(line, (int(OW / 2 - n / 2), ry))

    # ---- the star-in-ring mark: spins in, blooms, flares once
    if c["mark"]:
        S = c["mark_frac"] * OH
        mp = _ease((t - c["t_mark"]) / 1.5)
        if mp > 0:
            key = ("mark", int(S), c["emblem_path"])
            if key not in _CACHE:
                _CACHE[key] = emblem_tile(c["emblem_path"], int(S)) if c["emblem_path"] else mark_tile(int(S))
            big = _CACHE[key]
            ang = (1 - mp) * 60.0
            sc = 0.55 + 0.45 * mp
            tile = big.rotate(ang, Image.BICUBIC) if ang > 0.2 else big
            side = int(big.width / 4 * sc)
            tile = tile.resize((max(2, side), max(2, side)), Image.LANCZOS)
            mx, my = OW / 2, c["mark_y"] * OH
            al = tile.split()[3]
            _paste(out, _glow(al.resize(tile.size), 0.035 * OH, c["col_glow"], 1.1 * mp), mx, my)
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
