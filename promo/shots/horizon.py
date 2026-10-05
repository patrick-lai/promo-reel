"""`horizon` and `dawn` shot types: the `horizon` style preset's renderer (style.preset: horizon).

The look (Anthropic's 20 s "Claude Opus 5.5" film): rapid cuts of varied surfaces, each framed so one real edge forms a
horizon across the frame, ONE serif sentence sitting on that line whose words change while the picture keeps cutting, and
a held sunrise end card. Footage is REAL screen recordings only: the "horizon" is any real edge in the footage (a panel
top edge, a skyline, a ground line, a card edge) that the camera places at a chosen output height. Nothing here edits the
app's pixels; the only drawn pixels are the optional flat `sky` gradient above the footage's top edge and the type.

Shot `horizon` (per shot):
    source / t_in / speed / segs    exactly like `clip` (segs may carry their own `source` and `anchor`)
    anchor: {src: [x, y], out_y: 0.58, out_x: 0.5, out_y_end: 0.58}
                                    put this normalised SOURCE point at this normalised OUTPUT position. The camera box
                                    is computed from it (promo.shots.horizon.anchor_to_cam), so the edge stays on
                                    `out_y` whatever the push-in. `out_y_end` lets the horizon drift over the shot.
    horizon_y: 0.58                 shorthand for anchor.out_y; with an explicit `cam: [[t, cx, cy, w], ...]` instead of
                                    `anchor` it just declares where the edge is (for the text baseline and the gates)
    w: 0.6 | [0.8, 0.6]             camera box width as a fraction of the source width (push-in w0 -> w1, eased)
    sky: true | {top: [r,g,b], bottom: [r,g,b]|auto}
                                    flat vertical gradient ABOVE the footage when the source edge sits so low that the
                                    box reaches above the top of the source (`bottom: auto` = the footage's top-row colour).
                                    Without `sky` the box is clamped to the source like `clip` (gate horizon-edge FAILs if
                                    that moves the edge off `out_y`)
    cut_in: hard | flash_dip        flash_dip = a 3-frame pale dip at the head; only if style.transitions.allowed lists it
    hold_to_beat: true | seconds    freeze source + camera for the last N s (true = 0.12 s) so the cut lands on a still
    blur: N                         shutter blur (frames averaged)

Show-level text layer (not per shot), composited over the whole timeline so words persist across cuts:
    horizon_text: [{words: "There's", beats: [a, b]}, ...]       (global beats; optional `y:` fixed baseline fraction)
  serif, ~10 % of the frame height (the reference film's words), no pill, the baseline kissing the horizon of the shot
  under it (gap 0.4 % of the height; fixed y when that shot has no horizon), 3-frame fade in / out, white or near-black by
  the luminance under the glyphs, and (white ink) a soft dark drop shadow so the words stay readable on bright textures.
  Style (fractions of the frame height), default in the preset, override in the spec:
    style: {horizon_text_style: {size_frac: 0.10, gap_frac: 0.004, shadow: {blur: 0.012, alpha: 0.55, dy: 0.002}}}
  (`shadow: false` switches it off; a bare number is the alpha.) Words may not overlap real app footage (a clip in the
  footage manifest without `generated:`) unless that shot sets `text_over_ui: true` (gate horizon-text-ui), and the first
  40 % of the burst stays wordless (WARN horizon-wordless-open).

Shot `dawn` (the held sunrise end card): a thin navy -> teal rim rising from the bottom edge (animated `rise_s`, 3 s,
`reach: [0.05, 0.22]`), turning amber only in the last 0.6 s (`amber_at` seconds, shot-local; `amber_s` ramp, default
0.45 s). Product `name` in serif (`name_frac` 0.065 at `name_y` 0.47). `wordmark` (small tracked) and `tagline` (fades in
at +1.0 s) are optional and have NO default text: omit them and only `name` renders.
    name, wordmark, tagline         texts; name_at (0.3), tagline_at (1.0), rise_s (3.0), name_frac, name_y, wordmark_y, tagline_y
    amber_at: 2.4                   seconds into the card where the amber starts (default: shot duration - 0.6)
    reach: [0.12, 0.80]             the old tall glow; with `amber_at: 0` and name_frac 0.11 / name_y 0.40 this restores the
                                    previous card exactly
    name_style: brand               animated brand lockup instead of the plain texts (promo/shots/brand.py documents its keys):
                                    `wordmark: [{text, color, weight}, ...]` (a list; parts on one line) or `name`, optional
                                    `emblem_path:` (project-relative PNG; no default, an emblem shows only when named), `mark: builtin`,
                                    `col_name`, `col_accent`, `col_glow`, `tagline`
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .. import render as R
from ..spec import resolve_cam_keys
from . import ShotType, shot_type
from .clip import segments

SERIF = ["/System/Library/Fonts/NewYork.ttf", "/System/Library/Fonts/Supplemental/Georgia.ttf", "/System/Library/Fonts/Times.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSerif.ttf"]
SANS = ["/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf", R.DEFAULT_FONT,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
_FONTS = {}
_NOISE = {}


def style_of(spec):
    """Resolved style dict with the horizon preset underneath (so the types work on a spec that sets only some keys)."""
    st = getattr(spec, "style", None) or {}
    if st.get("preset") != "horizon":
        from ..styles import PRESETS, deep_merge
        st = deep_merge(PRESETS["horizon"], st)
    return st


# ---------------------------------------------------------------- fonts
def font_candidates(st, kind):
    mine = (st.get("typography") or {}).get(kind) or []
    return list(mine if isinstance(mine, (list, tuple)) else [mine]) + (SERIF if kind == "serif" else SANS)


def load_font(cands, px):
    """First existing font of `cands` at `px`; PIL's built-in font as the last resort (graceful fallback off macOS)."""
    px = max(8, int(round(px)))
    key = (tuple(cands), px)
    if key not in _FONTS:
        f = None
        for p in cands:
            if p and os.path.exists(p):
                try:
                    f = ImageFont.truetype(p, px)
                    break
                except OSError:
                    continue
        if f is None:
            try:
                f = ImageFont.load_default(size=px)
            except TypeError:               # Pillow < 10.1: fixed-size bitmap font
                f = ImageFont.load_default()
        _FONTS[key] = f
    return _FONTS[key]


# ---------------------------------------------------------------- anchor -> camera (pure)
def box_for(anchor_src, out_pos, w, src_size, out_size=(16, 9)):
    """UNCLAMPED camera box (x0, y0, bw, bh) in source px that puts the normalised source point `anchor_src` at the
    normalised output position `out_pos`, for a box `w` x the source width wide with the output's aspect."""
    SW, SH = src_size
    bw = w * SW
    bh = bw * out_size[1] / out_size[0]
    return anchor_src[0] * SW - out_pos[0] * bw, anchor_src[1] * SH - out_pos[1] * bh, bw, bh


def anchor_to_cam(anchor_src, out_pos, w, src_size, out_size=(16, 9)):
    """(cx, cy, w) camera key (the `clip` contract) that realises the anchor."""
    x0, y0, bw, bh = box_for(anchor_src, out_pos, w, src_size, out_size)
    return (x0 + bw / 2) / src_size[0], (y0 + bh / 2) / src_size[1], w


def box_of_cam(cam, src_size, out_size=(16, 9)):
    cx, cy, w = cam[:3]
    SW, SH = src_size
    bw = w * SW
    bh = bw * out_size[1] / out_size[0]
    return cx * SW - bw / 2, cy * SH - bh / 2, bw, bh


def anchor_of(cfg, seg=None):
    """The anchor dict {src, out_y, [out_x, out_y_end]} of a shot (or one of its segs), or None."""
    a = (seg or {}).get("anchor") or cfg.get("anchor")
    if not a:
        return None
    if "src" not in a:
        raise ValueError("anchor needs src: [x, y] (normalised source point)")
    a = dict(a)
    if a.get("out_y") is None:
        a["out_y"] = cfg.get("horizon_y", 0.58)
    return a


def _eased(cfg, t, dur, pair):
    if isinstance(pair, (list, tuple)):
        return pair[0] + (pair[1] - pair[0]) * R.ease(t / max(dur, 1e-6), cfg.get("ease", "smooth"))
    return pair


def width_at(cfg, t, dur):
    return _eased(cfg, t, dur, cfg.get("w", 1.0))


def horizon_at(cfg, t, dur, seg=None):
    """Output height (0..1) of the shot's horizon at shot-local time t, or None when the shot declares none."""
    a = anchor_of(cfg, seg)
    if a:
        y0 = float(a["out_y"])
        return _eased(cfg, t, dur, [y0, float(a["out_y_end"])] if a.get("out_y_end") is not None else y0)
    return cfg.get("horizon_y")


def cam_for(cfg, t, dur, src_size, out_size=(16, 9), seg=None):
    a = anchor_of(cfg, seg)
    if a:
        return anchor_to_cam(a["src"], (float(a.get("out_x", 0.5)), horizon_at(cfg, t, dur, seg)), width_at(cfg, t, dur), src_size, out_size)
    if cfg.get("cam"):
        return R.cam_at(resolve_cam_keys(cfg["cam"], dur), t)
    raise ValueError("horizon shot needs anchor: {src: [x, y], out_y: ...} or cam: [[t, cx, cy, w], ...]")


def hold_seconds(cfg):
    h = cfg.get("hold_to_beat")
    return 0.0 if not h else (0.12 if h is True else float(h))


# ---------------------------------------------------------------- framing with optional sky
def sky_of(st, cfg):
    s = cfg.get("sky")
    if not s:
        return None
    base = dict(st.get("sky") or {})
    base.update(s if isinstance(s, dict) else {})
    return base


def _dither(rows, cols):
    k = (rows, cols)
    if k not in _NOISE:
        _NOISE[k] = np.random.default_rng(11).integers(-1, 2, (rows, cols, 1)).astype(np.int16)
    return _NOISE[k]


def sky_image(ctx, rows, top, bottom):
    a = np.linspace(0, 1, rows)[:, None, None]
    arr = np.array(top, float)[None, None, :] * (1 - a) + np.array(bottom, float)[None, None, :] * a
    arr = np.repeat(arr, ctx.OW, axis=1) + _dither(rows, ctx.OW)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def frame_free(ctx, im, cam, sky=None):
    """Like R.frame_cam, but with `sky` the box may reach ABOVE the top of the source: the missing rows are a flat sky
    gradient (top colour -> `bottom`, `auto` = the footage's top-row mean) and the footage keeps its exact scale and
    position, so a source edge lands where the anchor asked. Without `sky` it is R.frame_cam (clamped)."""
    OW, OH = ctx.OW, ctx.OH
    SW, SH = im.size
    cx, cy, w = cam[:3]
    bw = w * SW
    bh = bw * OH / OW
    if sky is None or bh > SH:
        return R.frame_cam(ctx, im, cx, cy, w)
    x0 = min(max(cx * SW - bw / 2, 0), SW - bw)
    y0 = min(cy * SH - bh / 2, SH - bh)
    if y0 >= 0:
        return im.resize((OW, OH), Image.LANCZOS, box=(x0, y0, x0 + bw, y0 + bh))
    vis = bh + y0                                     # source rows shown
    rows = int(round(vis / bh * OH))
    if rows <= 0:
        return sky_image(ctx, OH, sky.get("top", [10, 14, 30]), sky.get("top", [10, 14, 30]))
    rows = min(rows, OH)
    part = im.resize((OW, rows), Image.LANCZOS, box=(x0, 0, x0 + bw, vis))
    top_rows = OH - rows
    out = Image.new("RGB", (OW, OH))
    out.paste(part, (0, top_rows))
    if top_rows > 0:
        bot = sky.get("bottom", "auto")
        if bot == "auto":
            bot = np.asarray(part.crop((0, 0, OW, min(3, rows)))).reshape(-1, 3).mean(0)
        top = sky.get("top", [10, 14, 30])
        if top == "auto":
            top = np.array(bot, float) * 0.5
        out.paste(sky_image(ctx, top_rows, top, bot), (0, 0))
    return out


# ---------------------------------------------------------------- the show-level text layer
def text_words(spec):
    """horizon_text -> [{i, text, a, b, t0, t1, f0, f1, y}] with global frame numbers (round(t * fps), like Shot.f0)."""
    tl, fps = spec.timeline, spec.fps
    out = []
    for i, w in enumerate(spec.raw.get("horizon_text") or []):
        a, b = w["beats"]
        out.append(dict(i=i, text=str(w.get("words", w.get("text", ""))), a=a, b=b, t0=tl.t(a), t1=tl.t(b),
                        f0=round(tl.t(a) * fps), f1=round(tl.t(b) * fps), y=w.get("y")))
    return out


def word_alpha(f, f0, f1, fade=3):
    """Opacity of a word on global frame f: `fade`-frame ramp in at f0 and out before f1; 0 outside [f0, f1)."""
    if f < f0 or f >= f1:
        return 0.0
    return max(0.0, min(1.0, (f - f0 + 1) / fade, (f1 - f) / fade))


def text_style(st):
    """The horizon_text style dict: preset `horizon_text` with the spec's `horizon_text_style` laid over it
    (`shadow` dicts merge key by key; `shadow: false` / 0 turns the shadow off)."""
    hs = dict(st["horizon_text"])
    for k, v in (st.get("horizon_text_style") or {}).items():
        hs[k] = {**hs[k], **v} if k == "shadow" and isinstance(v, dict) and isinstance(hs.get(k), dict) else v
    return hs


def shadow_of(hs):
    """{blur, alpha, dy} (fractions of the frame height; alpha = peak opacity) of the word shadow, or None when off."""
    sh = hs.get("shadow")
    if not sh:
        return None
    sh = {"blur": 0.012, "alpha": float(sh), "dy": 0.002} if not isinstance(sh, dict) else {"blur": 0.012, "alpha": 0.55, "dy": 0.002, **sh}
    return sh if sh["alpha"] > 0 else None


def word_metrics(ctx, st, text):
    """(font, bbox, cap_px) of a horizon word: bbox relative to its left-baseline origin."""
    hs = text_style(st)
    f = load_font(font_candidates(st, "serif"), hs["size_frac"] * ctx.OH)
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    bb = d.textbbox((0, 0), text, font=f, anchor="ls")
    cap = -d.textbbox((0, 0), "H", font=f, anchor="ls")[1]
    return f, bb, cap


def baseline_y(ctx, hs, horizon_y, cap, y=None):
    """Baseline (px) of the horizon text: just above the horizon line, else the fixed fallback, kept inside the frame."""
    if y is not None:
        b = y * ctx.OH
    elif horizon_y is None:
        b = hs["fallback_y"] * ctx.OH
    else:
        b = (horizon_y - hs["gap_frac"]) * ctx.OH
    return min(max(b, hs["top_margin_frac"] * ctx.OH + cap), 0.96 * ctx.OH)


def _composite(out, layer, a, x, y):
    """Alpha-composite `layer` (scaled by a) at (x, y) with clipping to the frame."""
    W, H = out.size
    lx0, ly0 = max(0, -x), max(0, -y)
    lx1, ly1 = min(layer.width, W - x), min(layer.height, H - y)
    if lx1 <= lx0 or ly1 <= ly0 or a <= 0:
        return out
    part = layer.crop((lx0, ly0, lx1, ly1))
    if a < 1:
        part.putalpha(part.split()[3].point(lambda v: int(v * a)))
    out = out.convert("RGBA") if out.mode != "RGBA" else out
    out.alpha_composite(part, (x + lx0, y + ly0))
    return out


class HorizonText:
    """The persistent serif line. `apply(out, f, horizon_y)` draws every word live on global frame f."""

    def __init__(self, ctx, spec):
        self.ctx = ctx
        self.st = style_of(spec)
        self.hs = text_style(self.st)
        self.words = text_words(spec)
        self._layers = {}

    def _layer(self, w, f, dark):
        k = (w["text"], dark)
        if k not in self._layers:
            hs, ctx = self.hs, self.ctx
            font, bb, _ = word_metrics(ctx, self.st, w["text"])
            shd = shadow_of(hs)
            pad = int(round((0.02 + (3 * shd["blur"] + shd["dy"] if shd else 0.0)) * ctx.OH))
            lw, lh = bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad
            ox, oy = pad - bb[0], pad - bb[1]                     # left-baseline origin inside the layer
            col = tuple(hs["color_dark"] if dark else hs["color_light"])
            ink = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
            ImageDraw.Draw(ink).text((ox, oy), w["text"], font=font, fill=col + (255,), anchor="ls")
            lay = ink
            if not dark and shd:                                  # soft dark halo under white words (peak opacity = alpha)
                m = ImageChops.offset(ink.split()[3], 0, int(round(shd["dy"] * ctx.OH))).filter(ImageFilter.GaussianBlur(max(shd["blur"] * ctx.OH, 0.1)))
                peak = max(m.getextrema()[1], 1)
                sh = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
                sh.putalpha(m.point(lambda v: int(min(255, v * 255.0 / peak) * shd["alpha"])))
                lay = sh
                lay.alpha_composite(ink)
            self._layers[k] = (lay, ox, oy, bb)
        return self._layers[k]

    def apply(self, out, f, horizon_y):
        ctx, hs = self.ctx, self.hs
        for w in self.words:
            a = word_alpha(f, w["f0"], w["f1"], hs.get("fade_frames", 3))
            if a <= 0:
                continue
            _, bb, cap = word_metrics(ctx, self.st, w["text"])
            base = baseline_y(ctx, hs, horizon_y, cap, w["y"])
            x = ctx.OW * hs.get("x", 0.5) - (bb[2] - bb[0]) / 2 - bb[0]       # left-baseline origin x
            box = tuple(int(round(v)) for v in (x + bb[0], base + bb[1], x + bb[2], base + bb[3]))
            region = out.crop((max(0, box[0]), max(0, box[1]), min(ctx.OW, box[2]), min(ctx.OH, box[3])))
            lum = float(np.asarray(region.convert("L"), np.float32).mean()) / 255.0 if region.width and region.height else 0.0
            dark = lum > hs["lum_threshold"]
            lay, ox, oy, _ = self._layer(w, f, dark)
            out = _composite(out, lay, a, int(round(x - ox)), int(round(base - oy)))
        return out


# ---------------------------------------------------------------- shots
def src_size(spec, cid):
    """(w, h) of a footage clip from the manifest resolution (else probed); None if unknown."""
    from .. import footage as FT
    try:
        c = FT.load(spec).get(cid, {})
    except Exception:  # noqa: BLE001
        c = {}
    res = str(c.get("resolution", ""))
    if "x" in res:
        try:
            w, h = res.split("x")
            return int(w), int(h)
        except ValueError:
            pass
    p = c.get("path")
    if p and os.path.exists(p):
        try:
            w, h, _, _ = R.probe(p)
            return w, h
        except Exception:  # noqa: BLE001
            return None
    return None


def dip_alpha(st, cfg, i):
    """Opacity of the flash_dip at frame i of the shot (0 when cut_in is a hard cut)."""
    if cfg.get("cut_in", "hard") != "flash_dip":
        return 0.0, None
    fd = st["transitions"].get("flash_dip", {})
    n = int(cfg.get("dip_frames", fd.get("frames", 3)))
    return (float(fd.get("alpha", 0.7)) * (1 - i / n) if i < n else 0.0), tuple(fd.get("color", [255, 244, 224]))


@shot_type("horizon")
class Horizon(ShotType):
    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        st = style_of(spec)
        total = shot.dur
        segs = segments(shot)
        srcs = [R.Source(spec.footage_path(s.get("source", cfg.get("source"))), s["t_in"], s["t_out"] + 0.1) for s in segs]
        bounds, acc = [], 0.0
        for s in segs:
            bounds.append((acc, acc + s["dur"]))
            acc += s["dur"]
        assert abs(acc - total) < 0.05, (shot.id, acc, total)
        blur = cfg.get("blur", 1)
        hold = hold_seconds(cfg)
        sky = sky_of(st, cfg)
        text = HorizonText(ctx, spec)
        aspect = (ctx.OW, ctx.OH)
        pane_cfg, pane_bg = None, None
        if cfg.get("pane"):
            from .. import pane3d as P3
            pane_cfg = dict(cfg["pane"]) if isinstance(cfg["pane"], dict) else {}
            pane_cfg.setdefault("enter", min(0.8, max(0.25, total * 0.5)))
            pane_bg = None
            bp = pane_cfg.pop("backdrop_plate", None)               # {id, t, dim, blur, mix}: the pane sits in the colour of its neighbouring specimen
            if bp:
                _src = R.Source(spec.footage_path(bp["id"]), bp.get("t", 0.5), bp.get("t", 0.5) + 0.2)
                try:
                    pane_bg = P3.plate_world(_src.frame(bp.get("t", 0.5), blur=0), ctx.OW, ctx.OH, bp.get("dim", 0.45), bp.get("blur", 0.035), bp.get("mix", 0.22))
                finally:
                    _src.close()

        def f(i, t):
            te = min(t, max(total - hold, 0.0)) if hold else t
            k = max(j for j, (a, _) in enumerate(bounds) if te >= a - 1e-6)
            a, b = bounds[k]
            s = segs[k]
            u = min(1.0, (te - a) / max(b - a, 1e-6))
            im = srcs[k].frame(s["t_in"] + (s["t_out"] - s["t_in"]) * u, blur=blur)
            cam = cam_for(cfg, te, total, im.size, aspect, s)
            if pane_cfg is not None:                        # real UI as a floating 3D pane (promo/pane3d.py): framing only, UI pixels just warped
                pw = int(ctx.OW * float(pane_cfg.get("w", P3.DEFAULTS["w"])) * 1.4)
                cr = pane_cfg.get("crop")
                if cr:                                      # an exact window of the recording (normalised cx, cy, w, h): whole elements, any aspect
                    SW, SH = im.size
                    bw, bh = cr["w"] * SW, cr["h"] * SH
                    x0 = min(max(cr["cx"] * SW - bw / 2, 0), SW - bw)
                    y0 = min(max(cr["cy"] * SH - bh / 2, 0), SH - bh)
                    crop = im.resize((pw, max(2, int(pw * bh / bw))), Image.LANCZOS, box=(x0, y0, x0 + bw, y0 + bh))
                else:
                    crop = R.frame_cam(ctx, im, cam[0], cam[1], cam[2], out=(pw, int(pw * ctx.OH / ctx.OW)))
                out = P3.compose(crop, pane_bg if pane_bg is not None else P3.world(ctx.OW, ctx.OH), t, total, pane_cfg,
                                 (ctx.OW, ctx.OH)).convert("RGBA")
            else:
                out = frame_free(ctx, im, cam, sky).convert("RGBA")
            out = text.apply(out, shot.f0 + i, horizon_at(cfg, te, total, s))
            da, col = dip_alpha(st, cfg, i)
            if da > 0:
                out = R.over(out, Image.new("RGBA", out.size, col + (255,)), da)
            return out

        try:
            R.run_shot(ctx, shot, f)
        finally:
            for s_ in srcs:
                s_.close()
        hy = horizon_at(cfg, 0.0, total)
        return dict(src=cfg.get("label", cfg.get("source", "")),
                    inout="; ".join(f"{s['t_in']:.2f}-{s['t_out']:.2f} s ({(s['t_out'] - s['t_in']) / s['dur']:.2f}x)" for s in segs),
                    move=cfg.get("move", f"horizon at {hy:.2f} of frame height" if hy is not None else "no horizon declared"),
                    caption=" / ".join(f"'{w['text']}'" for w in text.words if w["f0"] < shot.f0 + shot.n and w["f1"] > shot.f0) or "none",
                    notes=cfg.get("notes", ""))

    def src_to_out(self, shot, t_src):
        acc = 0
        for s in segments(shot):
            if s["t_in"] - 1e-6 <= t_src <= s["t_out"] + 1e-6:
                return acc + (t_src - s["t_in"]) / (s["t_out"] - s["t_in"]) * s["dur"]
            acc += s["dur"]
        return None

    def captions(self, ctx, shot):
        """QA records for the horizon words live in this shot (shot-local seconds)."""
        res = []
        for w in text_words(ctx.spec):
            t0, t1 = w["t0"] - shot.t0, w["t1"] - shot.t0
            if t1 > 1e-6 and t0 < shot.dur - 1e-6:
                res.append(dict(text=w["text"], role="text", box=None, t0=max(t0, 0.0), t1=min(t1, shot.dur)))
        return res


# ---------------------------------------------------------------- dawn end card
PRE_STOPS = [[0.0, [36, 116, 132]], [0.2, [30, 100, 118]], [0.45, [28, 92, 110]], [0.7, [14, 52, 78]], [1.0, [7, 10, 30]]]


def amber_level(t, cfg):
    """0 = navy -> teal rim only, 1 = full amber: ramps over `amber_s` from `amber_at` (None or 0 = amber from the start)."""
    at = cfg.get("amber_at")
    if at is None or float(at) <= 0:
        return 1.0
    return float(min(1.0, max(0.0, (t - float(at)) / max(float(cfg.get("amber_s", 0.45)), 1e-6))))


def dawn_array(OW, OH, t, cfg):
    """Sunrise gradient (H, W, 3 uint8) at card time t: a navy -> teal rim at the bottom edge that turns amber once
    `amber_at` is reached (amber_level); the lit height rises from `reach[0]` to `reach[1]` of the frame over `rise_s`
    seconds (ease-out), widest at the centre."""
    sw, sh = max(8, OW // 4), max(8, OH // 4)
    r0, r1 = cfg.get("reach", [0.12, 0.80])
    reach = r0 + (r1 - r0) * R.ease(t / max(float(cfg.get("rise_s", 3.0)), 1e-6), "out")
    yy = 1 - (np.arange(sh) + 0.5) / sh                                # height above the bottom edge, 0..1
    uu = (np.arange(sw) + 0.5) / sw
    local = reach * (0.65 + 0.35 * np.exp(-(((uu - 0.5) / 0.55) ** 2)))
    s = np.clip(yy[:, None] / local[None, :], 0, 1)
    stops, k_amber = cfg["stops"], amber_level(t, cfg)
    xs = [p for p, _ in stops]
    pre = cfg.get("pre_stops") or PRE_STOPS
    if k_amber < 1.0:
        pre_c = [np.interp(p, [q for q, _ in pre], [c[j] for _, c in pre]) for p in xs for j in range(3)]
        stops = [[p, [pre_c[3 * i + j] * (1 - k_amber) + c[j] * k_amber for j in range(3)]] for i, (p, c) in enumerate(stops)]
    ch = [np.interp(s, xs, [c[k] for _, c in stops]) for k in range(3)]
    small = Image.fromarray(np.stack(ch, -1).astype(np.uint8))
    arr = np.asarray(small.resize((OW, OH), Image.BILINEAR), np.int16) + _dither(OH, OW)
    return np.clip(arr, 0, 255).astype(np.uint8)


def _wm_text(wm):
    """The wordmark as plain text (a string, or the concatenated `text` of lockup parts)."""
    if isinstance(wm, (list, tuple)):
        return "".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in wm)
    return str(wm)


def _tracked(d, cx, cy, text, font, track, fill):
    widths = [d.textlength(ch, font=font) for ch in text]
    total = sum(widths) + track * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        d.text((x, cy), ch, font=font, fill=fill, anchor="lm")
        x += w + track


@shot_type("dawn")
class Dawn(ShotType):
    def _cfg(self, spec, shot):
        base = style_of(spec)["dawn"]
        cfg = {**base, **{k: v for k, v in shot.cfg.items() if k in base or k in ("amber_at", "amber_s", "pre_stops")}}
        if cfg.get("amber_at") is None:
            cfg["amber_at"] = max(0.0, shot.dur - 0.6)             # the amber arrives in the last 0.6 s
        return cfg

    def _texts(self, ctx, shot, cfg):
        """[(layer RGBA, t_on)] for name, wordmark, tagline (each a full-frame transparent layer)."""
        st = style_of(ctx.spec)
        OW, OH = ctx.OW, ctx.OH
        serif, sans = font_candidates(st, "serif"), font_candidates(st, "sans")
        out = []

        def put(draw_fn, t_on):
            im = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
            draw_fn(ImageDraw.Draw(im))
            out.append((im, t_on))
        if shot.cfg.get("name"):
            f = load_font(serif, cfg["name_frac"] * OH)
            put(lambda d: d.text((OW / 2, cfg["name_y"] * OH), shot.cfg["name"], font=f, fill=(244, 241, 234, 255), anchor="mm"), cfg["name_at"])
        if shot.cfg.get("wordmark"):
            wm = _wm_text(shot.cfg["wordmark"])         # lockup parts without `name_style: brand` draw as plain text
            f = load_font(sans, cfg["wordmark_frac"] * OH)
            put(lambda d: _tracked(d, OW / 2, cfg["wordmark_y"] * OH, wm, f, cfg["wordmark_frac"] * OH * 0.45, (214, 219, 228, 255)), cfg["name_at"])
        if shot.cfg.get("tagline"):
            f = load_font(serif, cfg["tagline_frac"] * OH)
            put(lambda d: d.text((OW / 2, cfg["tagline_y"] * OH), shot.cfg["tagline"], font=f, fill=(226, 228, 232, 255), anchor="mm"), cfg["tagline_at"])
        return out

    def render(self, ctx, shot):
        spec = ctx.spec
        cfg = self._cfg(spec, shot)
        wm_parts = isinstance(shot.cfg.get("wordmark"), (list, tuple))      # `wordmark:` as a list of {text, color, weight} = brand lockup parts
        brand = shot.cfg.get("name_style") == "brand" and (shot.cfg.get("name") or wm_parts)
        layers = [] if brand else self._texts(ctx, shot, cfg)
        fade = float(cfg.get("fade_s", 0.7))
        if brand:
            from . import brand as BR
            bcfg = {k: shot.cfg[k] for k in BR.DEFAULTS if k in shot.cfg}
            import os as _os
            em_rel = shot.cfg.get("emblem_path") or shot.cfg.get("emblem")      # no default: an emblem shows only when the spec names one
            bcfg.pop("emblem_path", None)
            if em_rel:
                em = ctx.spec.resolve(em_rel)
                if _os.path.exists(em):
                    bcfg["emblem_path"] = em                # project-relative transparent PNG (+ optional emblem.json centre)
            serif = font_candidates(style_of(ctx.spec), "serif")

        def f(i, t):
            out = Image.fromarray(dawn_array(ctx.OW, ctx.OH, t, cfg)).convert("RGBA")
            if brand:                                       # animated brand lockup (promo/shots/brand.py)
                out.alpha_composite(BR.lockup(ctx.OW, ctx.OH, t, shot.cfg.get("name"), serif, bcfg))
            for lay, t_on in layers:
                a = R.ease((t - t_on) / fade, "out") if t > t_on else 0.0
                out = _composite(out, lay, a, 0, 0)
            return out

        R.run_shot(ctx, shot, f)
        return dict(src="dawn gradient", inout="generated",
                    move=f"sunrise rim rises over {cfg['rise_s']:g} s (navy -> teal; amber from {cfg['amber_at']:.2f} s)",
                    caption=" / ".join(f"'{_wm_text(shot.cfg[k]) if k == 'wordmark' else shot.cfg[k]}'" for k in ("name", "wordmark", "tagline") if shot.cfg.get(k)) or "none",
                    notes=shot.cfg.get("notes", ""))

    def captions(self, ctx, shot):
        cfg = self._cfg(ctx.spec, shot)
        return [dict(text=shot.cfg[k], role="text", box=None, t0=cfg[at], t1=shot.dur)
                for k, at in (("name", "name_at"), ("tagline", "tagline_at")) if shot.cfg.get(k)]
