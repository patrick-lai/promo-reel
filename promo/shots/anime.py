"""`anime` shot type: the anime-opening style preset's renderer (style.preset: anime-opening).

Real footage (or a labelled placeholder slate) + kinetic title cards in ONE fixed lower-third band + beat flashes /
speed lines at the cuts. Nothing here edits the app's pixels: footage is only cropped/scaled by the camera.

Spec keys (per shot):
    ui: true|false              does the frame show app UI (text)? Drives hold rules, layout and where fx may draw.
    layout: band|full           band (default for ui shots): footage framed ABOVE the band, the band is solid, so a card
                                can never cover UI text. full (default for text-free shots): full-bleed, band is a soft
                                gradient; a full-bleed UI shot must list `ui_text` rects and cards must miss them.
    source: <clip id>           footage clip; t_in / speed / segs exactly like `clip`; or freeze: <source seconds>
    still: <clip id>            a still image from the footage manifest
    placeholder: {id, label, expects}   labelled slate for a shot that is not captured yet (swap = replace with source:)
    cam: [[t, cx, cy, w], ...]  camera keys (w = box width / source width); box aspect follows the viewport
    ui_text: [[x0, y0, x1, y1]] normalised SOURCE rects holding app text that cards must never cover (e.g. a notice)
    cards: [{row: title|sub|tag, text: "..." | text_from: claims.<table>, bars: [a, b] | t: [t0, t1], slam: true, fade_out: s}]
            bars are shot-local bar edges (1 bar = beats_per_bar beats of the grid); "end" = shot end
    fx_in / fx_out: {kind: flash|speed_lines, frames: N} (or a list)   at the head / tail of the shot, i.e. at a cut only
    blur: N                     shutter blur (frames averaged)
    fit: contain [+ aspect: w/h]   band layout only: pillarbox the footage above the band at 16:9 (or `aspect`)
    pillar_fill: band|brand     what fills the pillarbox: flat band colour (default) or the opening's brand background
    named: [{name, box: [x0, y0, x1, y1], src_px, t | at, min_px, thr}]   app text a card names (QA only, not rendered):
                                gate `named` FAILs under min_px (default 18 px cap height at 1080p), `named-upscale` WARNs
                                when its effective scale is > 1.0 (see promo/named.py; same contract as the talk show)
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import claims as C
from .. import render as R
from ..spec import resolve_cam_keys
from . import ShotType, shot_type
from .clip import segments

_FONTS = {}


def style_of(spec):
    st = getattr(spec, "style", None) or {}
    if st.get("preset") != "anime-opening" and "band" not in st:
        from ..styles import PRESETS, deep_merge
        st = deep_merge(PRESETS["anime-opening"], st)
    return st


def _font(path, px):
    k = (path, int(px))
    if k not in _FONTS:
        _FONTS[k] = ImageFont.truetype(path, int(px))
    return _FONTS[k]


def bar_s(spec):
    bpb = spec.grid.beats_per_bar if spec.grid else 4
    return bpb * spec.timeline.B


def card_times(spec, shot, card):
    """Shot-local (t0, t1) seconds of a card, clipped to the shot."""
    dur = shot.dur
    if "bars" in card:
        a, b = card["bars"]
        t0 = a * bar_s(spec)
        t1 = dur if b == "end" else b * bar_s(spec)
    else:
        a, b = card.get("t", [0.0, "end"])
        t0, t1 = float(a), (dur if b == "end" else float(b))
    return t0, min(t1, dur)


def card_text(spec, card):
    return C.text_of(spec.raw, card)


def card_geometry(spec, row, text, K=1):
    """Text layout of a card row: dict(font, size, x, y, w, h, box) with box in 1920x1080 canvas units."""
    st = style_of(spec)
    band, ty = st["band"], st["typography"]
    r = band["rows"][row]
    path = ty[f"{row}_font"]
    size = r["size"]
    stroke = ty.get("stroke", 6) if row != "tag" else 0
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    while True:
        f = _font(path, size * K)
        x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f, stroke_width=stroke * K)
        w = x1 - x0
        if w <= r["max_w"] * K or size <= 20:
            break
        size -= 2
    h = y1 - y0
    padx, pady = (18 * K, 8 * K) if row == "tag" else (28 * K, 6 * K)     # accent plate / pill padding
    cx = (band["x0"] + band["x1"]) / 2 * K
    cy = r["cy"] * K
    bx0, by0 = cx - w / 2 - padx, cy - h / 2 - pady
    bx1, by1 = cx + w / 2 + padx, cy + h / 2 + pady
    return dict(font=f, size=size, stroke=stroke * K, text_xy=(cx - w / 2 - x0, cy - h / 2 - y0), w=w, h=h,
                box=[bx0 / K, by0 / K, bx1 / K, by1 / K], plate=[bx0, by0, bx1, by1])


def viewport(spec, shot):
    """Output rect [x0, y0, x1, y1] (1080 units) where the footage is shown.
    band layout: the area above the band; `fit: contain` keeps a 16:9 camera box (pillarboxed above the band)."""
    st = style_of(spec)
    if layout_of(shot) == "band":
        h = st["band"]["y0"]
        if shot.get("fit") == "contain":       # pillarboxed above the band at 16:9, or at `aspect:` (w/h) to frame a panel
            w = h * float(shot.get("aspect", 16 / 9))
            return [(1920 - w) / 2, 0, (1920 + w) / 2, h]
        return [0, 0, 1920, h]
    return [0, 0, 1920, 1080]


def layout_of(shot):
    return shot.get("layout") or ("band" if shot.get("ui", True) else "full")


def src_rect_to_out(cam, src_size, vp, rect):
    """Map a normalised source rect through camera (cx, cy, w) into output coords (1080 units) of viewport vp."""
    cx, cy, w = cam
    SW, SH = src_size
    vw, vh = vp[2] - vp[0], vp[3] - vp[1]
    bw = w * SW
    bh = bw * vh / vw
    x0 = min(max(cx * SW - bw / 2, 0), SW - bw)
    y0 = min(max(cy * SH - bh / 2, 0), SH - bh)
    sx, sy = vw / bw, vh / bh
    return [vp[0] + (rect[0] * SW - x0) * sx, vp[1] + (rect[1] * SH - y0) * sy,
            vp[0] + (rect[2] * SW - x0) * sx, vp[1] + (rect[3] * SH - y0) * sy]


def cam_keys(shot):
    cam = shot.get("cam") or [[0, 0.5, 0.5, 1.0]]
    if cam and not isinstance(cam[0], list):
        cam = [[0] + list(cam)]
    return resolve_cam_keys(cam, shot.dur)


def source_at(spec, shot, t):
    """(path, source seconds) shown at shot-local output time t, or (None, None) for a placeholder slate."""
    cfg = shot.cfg
    if cfg.get("placeholder"):
        return None, None
    if cfg.get("still"):
        return spec.footage_path(cfg["still"]), 0.0
    if cfg.get("freeze") is not None:
        return spec.footage_path(cfg["source"]), float(cfg["freeze"])
    acc = 0.0
    segs = segments(shot)
    for k, s in enumerate(segs):
        if t <= acc + s["dur"] + 1e-6 or k == len(segs) - 1:
            u = min(1.0, max(0.0, (t - acc) / max(s["dur"], 1e-6)))
            return spec.footage_path(s.get("source", cfg.get("source"))), s["t_in"] + (s["t_out"] - s["t_in"]) * u
        acc += s["dur"]
    return None, None


def _src_to_out(shot, t_src):
    from . import get_type
    return get_type(shot.type).src_to_out(shot, t_src)


def measure_named(spec, shot, el, t=None):
    """Measure one `named:` element of an anime shot at shot-local time t (default: el `t`, else the time whose source
    frame is el `at`, else the shot middle). Returns dict(name, t, src_t, px, src, scale, inside, box_out, min_px, ok)
    with box_out in 1920x1080 canvas units, or dict(..., error) if it cannot be measured."""
    from .. import named as N
    from .. import render as R
    from ..spec import number
    name = el.get("name", "?")
    if t is None:
        if el.get("t") is not None:
            t = number(el["t"])
        elif el.get("at") is not None and shot.get("freeze") is None:
            t = _src_to_out(shot, float(el["at"]))
        t = shot.dur / 2 if t is None else t
    path, src_t = source_at(spec, shot, t)
    need = el.get("min_px", N.MIN_NAMED_PX)
    if path is None:
        return dict(name=name, t=round(t, 3), min_px=need, ok=False, error="placeholder slate: element not on screen")
    if el.get("at") is not None and shot.get("freeze") is None and el.get("t") is None:
        src_t = float(el["at"])
    if shot.type == "anime":
        vp, keys = viewport(spec, shot), cam_keys(shot)
    else:                       # clip / other full-frame camera shots
        vp, keys = [0, 0, 1920, 1080], resolve_cam_keys(shot.cfg.get("cam") or [[0, 0.5, 0.5, 1.0]], shot.dur)
    vw, vh = vp[2] - vp[0], vp[3] - vp[1]
    m = N.element_px(N.gray_frame(path, src_t), R.cam_at(keys, t), (vw, vh), el["box"], el.get("src_px"), el.get("thr", 110))
    if m is None:
        return dict(name=name, t=round(t, 3), src_t=round(src_t, 3), min_px=need, ok=False, error="no ink in its box")
    ob = m.pop("out_box")
    box_out = [round(ob[0] + vp[0], 1), round(ob[1] + vp[1], 1), round(ob[2] + vp[0], 1), round(ob[3] + vp[1], 1)]
    return dict(name=name, t=round(t, 3), src_t=round(src_t, 3), box_out=box_out, min_px=need,
                ok=bool(m["px"] >= need and m["inside"]), **m)


# ---------------------------------------------------------------- drawing
def slate(spec, shot, size):
    """Labelled placeholder slate (W, H) for a shot that is not captured yet. Clearly not app UI."""
    W, H = size
    p = shot["placeholder"]
    im = Image.new("RGB", (W, H), (34, 34, 40))
    d = ImageDraw.Draw(im)
    step = max(W, H) // 24
    for x in range(-H, W, step):
        d.line([(x, 0), (x + H, H)], fill=(44, 44, 52), width=max(2, step // 3))
    k = H / 1080
    big = _font(style_of(spec)["typography"]["title_font"], 96 * k)
    mid = _font(R.DEFAULT_FONT, 40 * k)
    sm = _font(R.DEFAULT_FONT, 30 * k)
    lines = [(f"PLACEHOLDER · {p.get('id', shot.id)}", big, (255, 210, 64)), (p.get("label", ""), mid, (235, 235, 240))]
    for e in (p.get("expects") or "").split("\n"):
        if e.strip():
            lines.append((e.strip(), sm, (170, 170, 185)))
    lines.append(("not captured yet: swap in the real take via promo.yaml (source:)", sm, (170, 170, 185)))
    hs = [d.textbbox((0, 0), t, font=f)[3] + 18 * k for t, f, _ in lines]
    y = (H - sum(hs)) / 2
    for (t, f, c), hh in zip(lines, hs):
        tw = d.textlength(t, font=f)
        d.text(((W - tw) / 2, y), t, font=f, fill=c)
        y += hh
    d.rectangle([6 * k, 6 * k, W - 6 * k, H - 6 * k], outline=(255, 210, 64), width=max(2, int(6 * k)))
    return im


PILLAR_FILLS = ("band", "brand")


def pillar_backdrop(ctx, spec, shot, VX, VW, VH):
    """Canvas behind the footage viewport. `pillar_fill: band` (default) = flat band colour; `brand` = the opening's
    night-sky brand background (vertical gradient + soft accent glow + a few fixed stars) so a pillarboxed crop reads as a
    deliberate panel. Graphic frame only: it never touches the footage pixels."""
    st = style_of(spec)
    kind = shot.get("pillar_fill", "band")
    if kind not in PILLAR_FILLS:
        raise ValueError(f"shot {shot.id}: pillar_fill {kind!r} not in {PILLAR_FILLS}")
    if kind == "band":
        return Image.new("RGBA", (ctx.OW, ctx.OH), tuple(st["band"]["fill"]) + (255,))
    bg = st["band"].get("brand_bg") or dict(top=[10, 8, 44], mid=[16, 24, 80], bottom=[14, 12, 34], stars=70, glow=0.18)
    top, mid, bot = (np.array(bg[k], float) for k in ("top", "mid", "bottom"))
    y = np.linspace(0, 1, ctx.OH)[:, None]
    col = np.where(y < 0.55, top + (mid - top) * (y / 0.55), mid + (bot - mid) * ((y - 0.55) / 0.45))
    arr = np.repeat(col[:, None, :], ctx.OW, axis=1)
    xs = np.linspace(-1, 1, ctx.OW)[None, :]
    glow = np.exp(-(xs ** 2) / 0.35) * np.exp(-((y - 0.45) ** 2) / 0.08)        # soft accent2 glow behind the panel
    arr = arr + float(bg.get("glow", 0.18)) * glow[:, :, None] * np.array(st["band"]["accent2"], float)[None, None, :] * 0.35
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    d = ImageDraw.Draw(im)
    K = ctx.K
    for i in range(int(bg.get("stars", 70))):                # fixed pseudo-random stars, only in the pillars
        sx = (i * 7919) % 1920 * K
        sy = (i * 104729) % int(st["band"]["y0"] - 20) * K
        if VX - 12 * K <= sx <= VX + VW + 12 * K:
            continue
        a = 70 + (i * 37) % 120
        r = K * (1 if i % 5 else 2)
        d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(220, 225, 255, a))
    return im


def band_layer(ctx, spec, shot):
    st = style_of(spec)
    b = st["band"]
    K = ctx.K
    im = Image.new("RGBA", (ctx.OW, ctx.OH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    y0 = int(b["y0"] * K)
    if layout_of(shot) == "band":
        d.rectangle([0, y0, ctx.OW, ctx.OH], fill=tuple(b["fill"]) + (255,))
        d.rectangle([0, y0, ctx.OW, y0 + 6 * K], fill=tuple(b["accent"]) + (255,))
    else:   # soft gradient so cards read on scenery; the scene itself stays visible
        g = Image.new("L", (1, ctx.OH - y0 + 80 * K))
        for i in range(g.height):
            g.putpixel((0, i), int(min(1.0, i / (140 * K)) * 170))
        g = g.resize((ctx.OW, g.height))
        dark = Image.new("RGBA", (ctx.OW, g.height), tuple(b["fill"]) + (255,))
        dark.putalpha(g)
        im.alpha_composite(dark, (0, y0 - 80 * K))
    return im


def card_layer(ctx, spec, row, text):
    st = style_of(spec)
    b, ty = st["band"], st["typography"]
    g = card_geometry(spec, row, text, ctx.K)
    im = Image.new("RGBA", (ctx.OW, ctx.OH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = g["plate"]
    if row == "title":
        sk = (y1 - y0) * 0.25            # skewed accent plate behind the title
        d.polygon([(x0 + sk, y0), (x1 + sk, y0), (x1 - sk, y1), (x0 - sk, y1)], fill=tuple(b["accent"]) + (235,))
        d.text(g["text_xy"], text, font=g["font"], fill=(255, 255, 255, 255), stroke_width=g["stroke"], stroke_fill=(10, 8, 24, 255))
    elif row == "sub":
        d.text(g["text_xy"], text, font=g["font"], fill=tuple(b["accent2"]) + (255,), stroke_width=g["stroke"] // 2, stroke_fill=(10, 8, 24, 255))
    else:
        d.rounded_rectangle([x0, y0, x1, y1], radius=(y1 - y0) / 2, fill=(255, 255, 255, 240))
        d.text(g["text_xy"], text, font=g["font"], fill=(17, 19, 24, 255))
    return im, g


def speed_lines(ctx, area, t, seed=0):
    im = Image.new("RGBA", (ctx.OW, ctx.OH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    K = ctx.K
    if area == "full":
        cx, cy = ctx.OW / 2, ctx.OH * 0.45
        n = 40
        for i in range(n):
            a = i * math.tau / n + seed * 0.37 + t * 2.0
            r0 = ctx.OH * (0.30 + 0.05 * ((i * 7) % 3))
            r1 = ctx.OH * 1.2
            w = K * (4 if i % 4 == 0 else 2)
            d.line([(cx + math.cos(a) * r0 * 1.6, cy + math.sin(a) * r0), (cx + math.cos(a) * r1 * 1.6, cy + math.sin(a) * r1)],
                   fill=(255, 255, 255, 220), width=w)
    else:   # horizontal streaks inside the band only
        x0, y0, x1, y1 = area
        for i in range(18):
            y = y0 + (y1 - y0) * ((i * 37 + seed * 11) % 100) / 100
            L = (x1 - x0) * (0.25 + ((i * 53) % 40) / 100)
            xs = x0 + ((i * 97 + int(t * 3000)) % int(max(1, x1 - x0)))
            d.line([(xs - L, y), (xs, y)], fill=(255, 255, 255, 170), width=K * (3 if i % 3 == 0 else 1))
    return im


def fx_area(ctx, spec, shot):
    """Where fx may draw: full frame on text-free shots, the band only on UI shots (never over UI text)."""
    if not shot.get("ui", True):
        return "full"
    b = style_of(spec)["band"]
    return (0, b["y0"] * ctx.K, ctx.OW, ctx.OH)


def fx_list(shot, key):
    v = shot.get(key)
    return [] if not v else (list(v) if isinstance(v, list) else [v])


def apply_fx(ctx, spec, shot, out, i):
    n = shot.n
    for key, k, fx in [(key, k, fx) for key, k in (("fx_in", i), ("fx_out", n - 1 - i)) for fx in fx_list(shot, key)]:
        tr = style_of(spec)["transitions"]
        frames = int(fx.get("frames", tr.get(fx["kind"], {}).get("frames", 3)))
        if k >= frames:
            continue
        p = 1 - k / frames
        area = fx_area(ctx, spec, shot)
        if fx["kind"] == "flash":
            a = float(fx.get("alpha", tr.get("flash", {}).get("alpha", 0.85))) * p
            lay = Image.new("RGBA", (ctx.OW, ctx.OH), (0, 0, 0, 0))
            box = (0, 0, ctx.OW, ctx.OH) if area == "full" else area
            ImageDraw.Draw(lay).rectangle(box, fill=tuple(fx.get("color", [255, 255, 255])) + (255,))
            out = R.over(out, lay, a)
        elif fx["kind"] == "speed_lines":
            a = float(fx.get("alpha", tr.get("speed_lines", {}).get("alpha", 0.7))) * (0.4 + 0.6 * p)
            out = R.over(out, speed_lines(ctx, area, k / ctx.fps, seed=hash(shot.id) % 7), a)
        else:
            raise ValueError(f"shot {shot.id}: unknown fx kind {fx['kind']!r}")
    return out


@shot_type("anime")
class Anime(ShotType):
    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        st = style_of(spec)
        K = ctx.K
        vp = viewport(spec, shot)
        VX, VW, VH = int(round(vp[0] * K)), int(round((vp[2] - vp[0]) * K)), int(round((vp[3] - vp[1]) * K))
        bg = cfg.get("bg") or {}

        def treat(im):           # background treatment for end cards (blur / dim the whole frame); never on UI shots
            if bg.get("blur"):
                im = im.filter(ImageFilter.GaussianBlur(bg["blur"] * K))
            if bg.get("dim") is not None:
                im = Image.blend(Image.new(im.mode, im.size, (0, 0, 0, 255) if im.mode == "RGBA" else (0, 0, 0)), im, bg["dim"])
            return im
        if bg and cfg.get("ui", True):
            raise ValueError(f"shot {shot.id}: bg blur/dim is only for text-free shots (never soften app UI)")
        keys = cam_keys(shot)
        srcs, frame_at, label = [], None, cfg.get("label", "")
        if cfg.get("placeholder"):
            plate = slate(spec, shot, (VW, VH)).convert("RGBA")
            frame_at = lambda t: plate          # noqa: E731
            label = label or f"PLACEHOLDER {cfg['placeholder'].get('id', shot.id)}"
        elif cfg.get("still") or cfg.get("freeze") is not None:
            if cfg.get("still"):
                im = R.still(spec.footage_path(cfg["still"]))
            else:
                im = R.grab_frame(spec.footage_path(cfg["source"]), float(cfg["freeze"]))
            frame_at = lambda t: treat(R.frame_cam(ctx, im, *R.cam_at(keys, t), out=(VW, VH)).convert("RGBA"))   # noqa: E731
        else:
            segs = segments(shot)
            srcs = [R.Source(spec.footage_path(s.get("source", cfg.get("source"))), s["t_in"], s["t_out"] + 0.1) for s in segs]
            bounds, acc = [], 0.0
            for s in segs:
                bounds.append((acc, acc + s["dur"]))
                acc += s["dur"]
            assert abs(acc - shot.dur) < 0.05, (shot.id, acc, shot.dur)
            blur = cfg.get("blur", 1)

            def frame_at(t):
                k = max(j for j, (a, _) in enumerate(bounds) if t >= a - 1e-6)
                a, b = bounds[k]
                s = segs[k]
                u = min(1.0, (t - a) / max(b - a, 1e-6))
                im = srcs[k].frame(s["t_in"] + (s["t_out"] - s["t_in"]) * u, blur=blur)
                return treat(R.frame_cam(ctx, im, *R.cam_at(keys, t), out=(VW, VH)).convert("RGBA"))
        band = band_layer(ctx, spec, shot)
        cards = []
        for c in cfg.get("cards") or []:
            text = card_text(spec, c)
            lay, g = card_layer(ctx, spec, c.get("row", "title"), text)
            t0, t1 = card_times(spec, shot, c)
            cards.append((lay, g, t0, t1, c, text))
        backdrop = pillar_backdrop(ctx, spec, shot, VX, VW, VH)
        if VX > 0:               # pillarbox sides: band colour + accent rules (graphic frame, not footage)
            dd = ImageDraw.Draw(backdrop)
            for x in (VX - 10 * K, VX + VW + 4 * K):
                dd.rectangle([x, 0, x + 6 * K, VH], fill=tuple(st["band"]["accent2"]) + (255,))
        ty = st["typography"]
        slam = ty.get("slam", {})
        fout = ty.get("fade_out", 0.08)

        def f(i, t):
            out = backdrop.copy()
            out.alpha_composite(frame_at(t), (VX, 0))
            out.alpha_composite(band)
            for lay, g, t0, t1, c, _ in cards:
                if not (t0 - 1e-6 <= t < t1):
                    continue
                fo = c.get("fade_out", fout)          # 0 = hold to the cut (a card carried across a cut)
                a = min(1.0, (t1 - t) / fo) if fo else 1.0
                if c.get("slam", c.get("row", "title") == "title") and t - t0 < slam.get("dur", 0.12):
                    p = (t - t0) / slam.get("dur", 0.12)
                    z = slam.get("scale", 1.22) - (slam.get("scale", 1.22) - 1) * R.ease(p, "out")
                    x0, y0, x1, y1 = g["plate"]
                    cxp, cyp = (x0 + x1) / 2, (y0 + y1) / 2
                    big = lay.resize((int(ctx.OW * z), int(ctx.OH * z)), Image.BILINEAR)
                    ox, oy = int(cxp * (z - 1)), int(cyp * (z - 1))      # scale about the plate centre
                    tmp = big.crop((ox, oy, ox + ctx.OW, oy + ctx.OH))
                    out = R.over(out, tmp, min(a, 0.35 + 0.65 * p))
                else:
                    out = R.over(out, lay, a)
            return apply_fx(ctx, spec, shot, out, i)

        try:
            R.run_shot(ctx, shot, f)
        finally:
            for s_ in srcs:
                s_.close()
        ws = [k_[3] for k_ in keys]
        src = "placeholder slate" if cfg.get("placeholder") else ("freeze %.2f s" % cfg["freeze"] if cfg.get("freeze") is not None else
                                                                   ("still" if cfg.get("still") else "; ".join(
                                                                       f"{s['t_in']:.2f}-{s['t_out']:.2f} s" for s in segments(shot))))
        return dict(src=label or cfg.get("source", ""), inout=src,
                    move=cfg.get("move", f"{layout_of(shot)} layout, box {max(ws):.2f} -> {min(ws):.2f} of source width"),
                    caption=" / ".join(f"'{x[5]}'" for x in cards) or "none", notes=cfg.get("notes", ""))

    def src_to_out(self, shot, t_src):
        if shot.get("placeholder") or shot.get("freeze") is not None or shot.get("still"):
            return None
        acc = 0
        for s in segments(shot):
            if s["t_in"] - 1e-6 <= t_src <= s["t_out"] + 1e-6:
                return acc + (t_src - s["t_in"]) / (s["t_out"] - s["t_in"]) * s["dur"]
            acc += s["dur"]
        return None

    def captions(self, ctx, shot):
        spec = ctx.spec
        res = []
        for c in shot.get("cards") or []:
            text = card_text(spec, c)
            t0, t1 = card_times(spec, shot, c)
            res.append(dict(text=text, role="card", box=card_geometry(spec, c.get("row", "title"), text)["box"], t0=t0, t1=t1))
        return res
