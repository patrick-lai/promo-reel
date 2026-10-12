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
        aspect: 0.46            width / height of the panel (default: the output's 16:9); a phone-shaped device panel. `w` stays the
                                width as a fraction of the frame width. Device bezel = a thick dark `rim` (the bezel is drawn outside
                                the UI pixels; nothing is drawn on them)
        radius: 22              corner radius in 1920 canvas px (scales with the output), antialiased; 0 / false = square. The
                                interior of the rounded rect is byte-identical to the camera crop, only the 4 r x r corner blocks
                                blend with what is behind
        shadow: {layers: [{alpha, blur, dy, spread}, ...]}   two soft layers (tight + wide), fractions of the frame width
        rim: {alpha: 0.18, width: 1, color}                 1 px warm-white line just OUTSIDE the border
        glow: {alpha: 0.25, scale, blur, lift, warm}        light spill: a blurred, enlarged, lifted, warm copy of the panel behind it
        halo: {alpha: 0.3, blur: 0.010, spread: 0.002, color}   a soft coloured edge OUTSIDE the silhouette (a dark UI on a pale plate); off by default
        in: {dur: 0.35, from_scale: 0.97, fade: true, ease: out, rise: 0.03}   entrance ease (off by default: cuts stay hard); `ease` out = cubic,
                                `rise` = floats up from that fraction of the height. The film's first shot gets one from `intro` (promo/bookends.py)
    look.plate_fill: {top, bottom} | [r, g, b]   the base of a shot with no source (default near-black): a designed placeholder world
    look.backdrop: {fill: {top, bottom}}   a flat or two-tone gradient world instead of the blurred copy (used until a plate exists)
    look.backdrop: {plate, t, blur, dim, warm, parallax}    the world behind the panel. plate = a footage clip id (a still frame at t,
                                default 0) or an image / video path: a film-world plate (night sky, dawn, a scenic view), blurred and
                                graded, so panels float in the same world across the film. Without a plate: the dim blur of the
                                panel crop. `warm` = weight of the cool-indigo (top) to warm-amber (bottom) gradient lift (default
                                0.35 on the blurred copy, 0.12 on a plate; false = off). `parallax` (0.35) = fraction of the panel
                                camera's motion the backdrop follows (pan + zoom). blur defaults to look.dof; dim to look.dof on the blurred copy, 0.8 on a plate.
    look.backdrop: none + ui: true   full-bleed REAL footage with NO grading of the UI pixels: grade / bloom / grain / vignette are
                                skipped (protect_ui), only fade_in / fade_out touch the picture; lower_copy / scrim are not drawn on
                                it (gate copy-clear FAILs copy over full-bleed UI), so use it for a bare hero moment.
    kinetic_copy: [{text, at, dur, size_pct, cx, cy, anim, from, in_s, uppercase, color, weight, outline, shadow, brackets, anchors, thumb}]
                                designed-promo type (promo/designed.py). Sized as a percentage of the frame HEIGHT (size_pct, default 11;
                                the designed gate WARNs outside the dialect's band) and drawn over the backdrop, never on the UI panel
                                (gate designed-clear). cx / cy = fractions of the frame (default: centred in the margin under the
                                panel, or the frame centre without one). Words come from the person (gate designed-grounded).
                                anim: pop | slide (from left|right|up|down) | scale   the kinetic dialect: scale / slide in over in_s
                                      snap    instantly on at full size, instantly off: zero blur, one frame (ethereal micro snap)
                                      cascade the words snap on one by one every step_s (0.18)
                                weight: Light | Regular | Medium | Bold | Black   a named instance of the UI font; unset = the heavy
                                      blocky fallback sans (kinetic). outline / shadow: false = a clean light face (ethereal).
                                brackets: true | {pad, len, width}   [ ] corner brackets round the text (typography as UI)
                                anchors: true   a hairline selection box with four square handles round the text
                                thumb: <clip id | image>   a small rounded real still inline before the text (its pixels only scaled)
    resolve: {kind: mosaic, dur: 0.9, steps: 6, from_blocks: 8, to_blocks: 96, tone: 0.05}   the BACKDROP / plate resolves from a coarse mosaic to
                                sharp in `steps` hard stages, drawn AFTER grade / bloom / grain so the blocks stay crisp (never the UI panel: its
                                pixels are only transformed geometrically). Columns go geometrically from_blocks -> to_blocks; `tone` = a per-block
                                brightness offset that fades out over the steps, so a smooth pastel world still reads as blocks
    fade_in / fade_out: s       from / to black (also fades the text); eased (smootherstep, or `fade_in_ease` / `fade_out_ease`: out | inout | in | linear).
                                With an `intro` / `outro` (promo/bookends.py, ethereal by default) the film's first shot floats in and its last shot
                                holds, then fades to black together with the music; an explicit key on the shot wins
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
    pullback: true | {w | scale, cy, start, until, ease, dim_to}   end wide hold: the panel shrinks (the world is revealed) while the camera
                                widens (set cam keys to end on w ~ 1.0). `w` = end width (fraction of the frame), `scale` = end width as a
                                fraction of the start (0.4 = 40 %), neither = 72 % of the start; reached `until` s before the shot ends
    blur: N                     shutter blur (frames averaged), usually 1
Layout is resolution independent (all sizes are in 1920x1080 canvas units, scaled by OW / 1920).
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import bookends as BK
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
    return dict(mode=mode, plate=plate, fill=d.get("fill"), t=float(d.get("t", 0.0) or 0.0), blur=d.get("blur"), dim=d.get("dim"), warm=warm,
                parallax=min(max(float(d.get("parallax", 0.35)), 0.0), 1.0))


def gradient_img(size, fill):
    """A vertical top-to-bottom gradient (`{top: [r, g, b], bottom: [r, g, b]}`) or a flat colour ([r, g, b]) as a PIL image."""
    W, H = size
    if isinstance(fill, dict):
        top = np.asarray(fill.get("top", fill.get("bottom", (8, 7, 9))), np.float32)
        bot = np.asarray(fill.get("bottom", fill.get("top", (8, 7, 9))), np.float32)
    else:
        top = bot = np.asarray(fill, np.float32)
    k = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None, None]
    col = top[None, None, :] * (1.0 - k) + bot[None, None, :] * k
    return Image.fromarray(np.clip(np.broadcast_to(col, (H, W, 3)), 0, 255).astype(np.uint8), "RGB")


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


def panel_aspect(look):
    """look.panel.aspect (width / height) for a device-shaped panel (a phone is ~0.46); None = the output's 16:9."""
    a = (look.get("panel") or {}).get("aspect")
    return min(max(float(a), 0.3), 2.4) if a else None


PULLBACK_DEFAULT_SHRINK = 0.72            # a pullback with no target ends at this fraction of the panel's own width
PULLBACK_KEYS = ("w", "scale", "cy", "start", "dim_to", "ease", "until")


def pullback_cfg(shot):
    """`pullback: true | {w | scale, cy, start, until, ease, dim_to}`. `w` = the panel's end width (fraction of the frame), `scale` = its end
    width as a fraction of the width it starts at (0.4 = shrinks to 40 %); neither = PULLBACK_DEFAULT_SHRINK. It starts at `start` (fraction
    of the shot), is there `until` seconds before the shot ends (the settle), and eases in-out unless `ease` says otherwise."""
    pb = shot.get("pullback")
    if not pb:
        return None
    pb = {} if pb is True else dict(pb)
    return dict(w=pb.get("w"), scale=pb.get("scale"), cy=pb.get("cy", 0.5), start=pb.get("start", 0.15), dim_to=pb.get("dim_to"),
                ease=pb.get("ease", "inout"), until=max(float(pb.get("until", 0.0) or 0.0), 0.0))


def pullback_target(pb, w0):
    """The panel's end width (fraction of the frame) of a pullback that starts at width w0."""
    if pb.get("w") is not None:
        return float(pb["w"])
    return float(w0) * (float(pb["scale"]) if pb.get("scale") is not None else PULLBACK_DEFAULT_SHRINK)


def panel_params(look, shot, t, dur):
    """(w_frac, cy_frac, dim) of the panel at shot-local time t (animated only by `pullback`)."""
    w, cy, dim = min(float(look["panel"]["w"]), MAX_PANEL_W), look["panel"]["cy"], look["dof"]["dim"]
    pb = pullback_cfg(shot)
    if pb:
        s = pb["start"] * dur
        p = BK.curve((t - s) / max(dur - pb["until"] - s, 1e-6), pb["ease"])
        w, cy = w + (pullback_target(pb, w) - w) * p, cy + (pb["cy"] - cy) * p
        dim = dim + ((pb["dim_to"] if pb["dim_to"] is not None else min(dim * 1.3, 1.0)) - dim) * p
    return w, cy, dim


def panel_box_of(spec, shot, size=(1920, 1080), t=0.0):
    """Panel box in output px at shot-local t (default: the start, where a pullback panel is largest). None = full-bleed."""
    look = look_of(spec, shot)
    if not has_panel(look) or not is_ui(shot):
        return None
    w, cy, _ = panel_params(look, shot, t, max(shot.dur, 1e-6) if hasattr(shot, "dur") else 1.0)
    return G.panel_box(size, w, cy, panel_aspect(look))


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


KINETIC_PCT, KINETIC_DEFAULT_PCT = (8.0, 15.0), 11.0
KINETIC_IN_S = 0.28
KINETIC_OUT_S = 0.15
KINETIC_STEP_S = 0.18
KINETIC_FILL, KINETIC_OUTLINE = (255, 255, 255), (12, 12, 28)
KINETIC_FONTS = [
    "/usr/share/fonts/truetype/google/Barlow Condensed/BarlowCondensed-Black.ttf",
    "/usr/share/fonts/truetype/sand-box/google/Barlow Condensed/BarlowCondensed-Black.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
KINETIC_ANIMS = ("pop", "slide", "scale", "snap", "cascade")
THUMB_GAP = 0.35


def kinetic_items(shot):
    return [dict(c) for c in (shot.get("kinetic_copy") or [])]


def kinetic_text(item):
    t = " ".join(str(item.get("text", "")).split())
    return t.upper() if item.get("uppercase", True) else t


def kinetic_pct(item):
    v = item.get("size_pct")
    return KINETIC_DEFAULT_PCT if v is None else min(max(float(v), 2.0), 30.0)


def kinetic_font(spec, px, fallback=None, weight=None):
    """The blocky fallback sans, or (with `weight`) a named instance of the UI font (Inter): Light / Regular / Medium / Bold / Black."""
    px = max(6, int(round(px)))
    k = ("kinetic", fallback if weight else None, weight, px)
    if weight is None:
        cands = list((((getattr(spec, "style", None) or {}).get("typography") or {}).get("kinetic_fonts")) or []) + KINETIC_FONTS
        path = None
        for p in cands:
            p = spec.resolve(p) if spec is not None and hasattr(spec, "resolve") else p
            if os.path.exists(p):
                path = p
                break
        path = path or fallback
        k = ("kinetic", path, None, px)
    else:
        path = fallback
    if k not in _FONTS:
        try:
            f = ImageFont.truetype(path, px) if path else ImageFont.load_default(size=px)
            names = [weight] if weight else [b"Black", b"ExtraBold", b"Bold"] if path == fallback else []
            for nm in names:
                nm = nm.encode() if isinstance(nm, str) else nm
                try:
                    f.set_variation_by_name(nm)
                    break
                except Exception:  # noqa: BLE001
                    continue
            _FONTS[k] = f
        except Exception:  # noqa: BLE001
            _FONTS[k] = ImageFont.load_default(size=px)
    return _FONTS[k]


def _kinetic_measure(spec, item, size, fallback):
    """(font, text w, text h, ox, oy, thumb image | None, total w, total h): the text shrunk to 92 % of the width, plus an inline thumb."""
    W, H = size
    px = kinetic_pct(item) / 100.0 * H
    text = kinetic_text(item)
    wt = item.get("weight")
    font = kinetic_font(spec, px, fallback, wt)
    tw, th, ox, oy = _text_size(font, text)
    thumb, extra = None, 0.0
    if item.get("thumb"):
        base = load_plate(spec, item["thumb"], 0.0, 640)
        if base is not None:
            h = max(2, int(round(th * 1.25)))
            thumb = base.resize((max(2, int(round(h * base.width / base.height))), h), Image.LANCZOS)
            extra = thumb.width + THUMB_GAP * th
    if tw + extra > 0.92 * W:
        k = 0.92 * W / (tw + extra)
        font = kinetic_font(spec, px * k, fallback, wt)
        tw, th, ox, oy = _text_size(font, text)
        if thumb is not None:
            thumb = thumb.resize((max(2, int(thumb.width * k)), max(2, int(thumb.height * k))), Image.LANCZOS)
            extra = thumb.width + THUMB_GAP * th
    return font, tw, th, ox, oy, thumb, tw + extra, max(th, thumb.height if thumb is not None else 0)


def kinetic_box(spec, shot, item, size=(1920, 1080), look=None, fallback=None):
    """Settled box [x0, y0, x1, y1] of a kinetic line (text and inline thumb) in output px, measured with the real font."""
    look = look or look_of(spec, shot)
    W, H = size
    _f, _tw, _th, _ox, _oy, _thumb, w, h = _kinetic_measure(spec, item, size, fallback)
    pb = panel_box_of(spec, shot, size)
    cx = float(item.get("cx", 0.5)) * W
    if item.get("cy") is not None:
        cy = float(item["cy"]) * H
    elif pb:
        cy = (pb[3] + H) / 2.0
    else:
        cy = 0.5 * H
    return [cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0]


def kinetic_pose(item, t):
    """(scale, alpha, dx, dy as fractions of the frame) of a kinetic line at shot-local t: the entrance curve then the exit fade.
    `snap` and `cascade` are hard cuts (alpha 0 -> 1 in one frame, no scale, no fade)."""
    at, dur = float(item.get("at", 0.0)), float(item.get("dur", 2.0))
    kind = item.get("anim", "pop")
    if kind in ("snap", "cascade"):
        return 1.0, (1.0 if at <= t < at + dur else 0.0), 0.0, 0.0
    ins = max(float(item.get("in_s", KINETIC_IN_S)), 1e-3)
    u = (t - at) / ins
    if u <= 0 or t > at + dur:
        return 1.0, 0.0, 0.0, 0.0
    e = R.ease(min(u, 1.0), "out")
    a = min(1.0, u * 3.0) * min(1.0, max(0.0, (at + dur - t) / KINETIC_OUT_S))
    if kind == "slide":
        d = item.get("from", "left")
        off = (1.0 - e) * 0.12
        dx, dy = {"left": (-off, 0.0), "right": (off, 0.0), "up": (0.0, off), "down": (0.0, -off)}.get(d, (-off, 0.0))
        return 1.0, a, dx, dy
    if kind == "scale":
        return 1.5 - 0.5 * e, a, 0.0, 0.0
    over = 1.12                                    # pop: grow past size, then settle
    s = 0.6 + (over - 0.6) * e if u < 1.0 else 1.0 + (over - 1.0) * max(0.0, 1.0 - R.ease((t - at - ins) / (ins * 0.8), "out"))
    return s, a, 0.0, 0.0


def cascade_words(item, t):
    """How many words of a `cascade` line are on at shot-local t (each snaps on `step_s` after the last)."""
    n = len(kinetic_text(item).split())
    step = max(float(item.get("step_s", KINETIC_STEP_S)), 1e-3)
    dt = t - float(item.get("at", 0.0))
    return 0 if dt < -1e-9 else max(0, min(n, int(dt / step + 1e-6) + 1))


MOSAIC_MAX_BLOCKS = 96                    # the last coarse stage still has this many columns, so every hard step reads as a step
MOSAIC_TONE = 0.05                        # per-block tone offset at the first stage (fraction of full scale), fading to 0: smooth worlds show their blocks


def mosaic_cfg(shot):
    r = shot.get("resolve") if hasattr(shot, "get") else None
    if not r:
        return None
    r = {} if r is True else dict(r)
    if r.get("kind", "mosaic") != "mosaic":
        return None
    steps, fb = max(int(r.get("steps", 6)), 2), max(int(r.get("from_blocks", 8)), 2)
    to = max(int(r.get("to_blocks", min(fb * 2 ** (steps - 1), MOSAIC_MAX_BLOCKS))), fb + 1)
    return dict(dur=max(float(r.get("dur", 0.9)), 0.05), steps=steps, from_blocks=fb, to_blocks=to, tone=max(float(r.get("tone", MOSAIC_TONE)), 0.0))


def mosaic_stage(cfg, t):
    """Hard stage 0..steps-1 of a mosaic resolve at shot-local t, or None once it is sharp."""
    u = t / cfg["dur"]
    if u >= 1.0:
        return None
    return max(0, int(u * cfg["steps"]))


def mosaic_cols(cfg, stage):
    """Block columns at a stage: geometric from `from_blocks` to `to_blocks`, so every step is a similar visible change (a doubling
    series spends its last steps on blocks too small to see)."""
    k = stage / max(cfg["steps"] - 1, 1)
    return max(2, int(round(cfg["from_blocks"] * (cfg["to_blocks"] / cfg["from_blocks"]) ** k)))


def mosaic(im, cfg, t):
    """The image pixelated to a hard stage of the resolve (nearest-neighbour blocks, no smoothing between them). Each block also gets a
    small fixed tone offset that fades out across the stages, so a smooth pastel world reads as blocks, not as a banded gradient."""
    st = mosaic_stage(cfg, t)
    if st is None:
        return im
    w, h = im.size
    cols = mosaic_cols(cfg, st)
    if cols >= w:
        return im
    rows = max(1, round(cols * h / w))
    small = im.convert("RGB").resize((cols, rows), Image.BOX)
    if cfg.get("tone"):
        yy, xx = np.mgrid[0:rows, 0:cols]
        n = (((xx * 73856093) ^ (yy * 19349663) ^ (cols * 83492791)) % 2048) / 1023.5 - 1.0         # fixed per block and stage, in [-1, 1]
        amp = cfg["tone"] * 255.0 * (1.0 - st / cfg["steps"])
        a = np.asarray(small, np.float32) + (n * amp)[..., None]
        small = Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8), "RGB")
    return small.resize((w, h), Image.NEAREST)


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


def black_level(t, dur, fin, fout, fin_ease=None, fout_ease=None):
    """0 = picture, 1 = black: eased fade in from black over `fin` s, fade out to black over the last `fout` s. The eases are
    promo/bookends.py curves (`out` = ease-out cubic, `inout` = smootherstep); unset = the preset's smootherstep."""
    b = 0.0
    if fin:
        b = max(b, 1.0 - (BK.curve(t / fin, fin_ease) if fin_ease else R.ease(t / fin)))
    if fout:
        b = max(b, 1.0 - (BK.fade_gain(t, dur, fout, fout_ease) if fout_ease else R.ease((dur - t) / fout)))
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
        self.fin_ease, self.fout_ease = shot.get("fade_in_ease"), shot.get("fade_out_ease")
        bk = BK.resolve(getattr(self.spec, "raw", None))
        film = getattr(self.spec, "duration", None)
        if bk["intro"] and getattr(shot, "f0", None) == 0:                 # the film's first shot floats in; later cuts stay hard
            it = bk["intro"]
            self.fin, self.fin_ease = (self.fin, self.fin_ease) if self.fin else (min(it["dur"], self.dur), it["ease"])
            if self.entr is None and self.panel:
                self.entr = G.entrance_cfg(dict(**{"in": dict(dur=it["dur"], from_scale=it.get("from_scale", 0.94), fade=False,
                                                              ease=it["ease"], rise=it.get("rise", 0.0))}))
        if bk["outro"] and film and shot.t1 >= float(film) - 1e-6:           # the last shot settles, then picture and music fade together
            ot = bk["outro"]
            self.fout, self.fout_ease = (self.fout, self.fout_ease) if self.fout else (min(ot["fade_s"], self.dur), ot["ease"])
        self.gvig = float((self.look.get("vignette") or {}).get("global", 0.0) or 0.0) if isinstance(self.look.get("vignette"), dict) else 0.0
        fb = getattr(ctx, "font_path", None)
        self.copies, self.scrims = [], []
        for it in copy_items(shot):
            txt = copy_text(self.spec, it)
            font = serif_font(self.spec, size_px(it, COPY_PX) * self.sc, fb)
            box = copy_box(self.spec, shot, it, (self.W, self.H), self.look, txt)
            self.copies.append((it, _Glyphs(font, txt, 6), (box[0], box[1])))
            self.scrims.append((scrim_cfg(it), (box[1] + box[3]) / 2.0))
        self.kinetics = []
        self.mosaic = mosaic_cfg(shot)
        for it in kinetic_items(shot):
            box = kinetic_box(self.spec, shot, it, (self.W, self.H), self.look, fb)
            n = len(kinetic_text(it).split())
            layers = [self._kinetic_layer(it, upto=k) for k in range(1, n + 1)] if it.get("anim") == "cascade" else [self._kinetic_layer(it)]
            self.kinetics.append((it, layers, box))
        tc = title_cfg(shot)
        self.title = None
        if tc:
            font = serif_font(self.spec, size_px(tc, TITLE_PX) * self.sc, fb)
            g = _Glyphs(font, tc["text"], int(0.10 * self.W))
            cy = tc.get("cy", 0.5) * self.H
            tw, th, ox, oy = _text_size(font, tc["text"])
            self.title = (tc, g, ((self.W - tw) / 2.0, cy - th / 2.0))

    # -- pieces
    def _kinetic_layer(self, item, upto=None):
        """RGBA of one kinetic line at its settled size (`upto` = the first n words, drawn where the full line puts them)."""
        text = kinetic_text(item)
        font, tw, th, ox, oy, thumb, total_w, total_h = _kinetic_measure(self.spec, item, (self.W, self.H), getattr(self.ctx, "font_path", None))
        outline = item.get("outline", True) is not False
        shadow_on = item.get("shadow", True) is not False
        stroke = max(2, int(round(font.size * 0.07))) if outline else 0
        fp = font.size * 0.45 if (item.get("brackets") or item.get("anchors")) else 0.0
        pad = int(stroke * 3 + font.size * 0.12 + fp + 4)
        w, h = int(total_w) + 2 * pad, int(total_h) + 2 * pad
        fill = tuple(item.get("color", KINETIC_FILL))
        tx = pad + (total_w - tw)
        ty = pad + (total_h - th) / 2.0
        shown = " ".join(text.split()[:upto]) if upto else text
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if shadow_on:
            sm = Image.new("L", (w, h), 0)
            ImageDraw.Draw(sm).text((tx - ox, ty - oy), shown, font=font, fill=255, stroke_width=stroke)
            sm = sm.filter(ImageFilter.GaussianBlur(max(1.0, font.size * 0.05))).point(lambda v: int(v * 0.55))
            sh = Image.new("RGBA", (w, h), KINETIC_OUTLINE + (0,))
            sh.putalpha(sm.transform(sm.size, Image.AFFINE, (1, 0, 0, 0, 1, -max(2, font.size * 0.05)), Image.BILINEAR))
            layer = sh
        txt = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt)
        d.text((tx - ox, ty - oy), shown, font=font, fill=fill + (255,), stroke_width=stroke, stroke_fill=KINETIC_OUTLINE + (255,))
        if thumb is not None:
            m = Image.new("L", thumb.size, 0)
            ImageDraw.Draw(m).rounded_rectangle([0, 0, thumb.width - 1, thumb.height - 1], radius=max(2, int(thumb.height * 0.18)), fill=255)
            txt.paste(thumb, (pad, int(ty + (th - thumb.height) / 2.0)), m)
        if fp:
            l, r, tp, bt = pad - fp, pad + total_w + fp, ty - fp * 0.8, ty + th + fp * 0.8
            lw = max(2, int(round(font.size * 0.035)))
            if item.get("brackets"):
                bc = item["brackets"] if isinstance(item["brackets"], dict) else {}
                ln = float(bc.get("len", font.size * 0.35))
                lw = max(1, int(bc.get("width", lw)))
                for x, sgn in ((l, 1), (r, -1)):
                    d.line([(x, tp), (x, bt)], fill=fill + (255,), width=lw)
                    d.line([(x, tp), (x + sgn * ln, tp)], fill=fill + (255,), width=lw)
                    d.line([(x, bt), (x + sgn * ln, bt)], fill=fill + (255,), width=lw)
            if item.get("anchors"):
                d.rectangle([l, tp, r, bt], outline=fill + (255,), width=max(1, lw // 2))
                hs = max(3, int(font.size * 0.12))
                for x, y in ((l, tp), (r, tp), (l, bt), (r, bt)):
                    d.rectangle([x - hs, y - hs, x + hs, y + hs], fill=fill + (255,), outline=KINETIC_OUTLINE + (255,), width=1)
        return Image.alpha_composite(layer, txt)

    def _kinetic(self, out, t):
        for it, layers, box in self.kinetics:
            s, a, dx, dy = kinetic_pose(it, t)
            if a <= 0:
                continue
            layer = layers[min(len(layers), cascade_words(it, t)) - 1] if len(layers) > 1 else layers[0]
            if len(layers) > 1 and cascade_words(it, t) < 1:
                continue
            w, h = max(1, int(layer.width * s)), max(1, int(layer.height * s))
            im = layer if abs(s - 1.0) < 1e-3 else layer.resize((w, h), Image.BILINEAR)
            if a < 0.999:
                al = im.getchannel("A").point(lambda v, k=a: int(v * k))
                im = im.copy()
                im.putalpha(al)
            cx, cy = (box[0] + box[2]) / 2.0 + dx * self.W, (box[1] + box[3]) / 2.0 + dy * self.H
            out.paste(im.convert("RGB"), (int(round(cx - w / 2.0)), int(round(cy - h / 2.0))), im.getchannel("A"))
        return out

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
        return G.panel_box((self.W, self.H), wf * s, cyf + G.entrance_rise(self.entr, t), panel_aspect(self.look)), dim, op

    def _backdrop(self, src, cam, dim):
        """The world behind the panel: a plate (drifting at `parallax` of the camera) or a dim blurred copy of the UI crop
        (cropped at `parallax` of the camera's motion), lifted by the cool-to-warm gradient; the look is applied after."""
        W, H = self.W, self.H
        d, bc = self.look["dof"], self.bd
        blur = bc["blur"] if bc["blur"] is not None else d["blur"]
        k = bc["parallax"]
        if bc.get("fill"):                                # a designed placeholder world (no plate yet): a flat or two-tone gradient
            return gradient_img((W, H), bc["fill"])
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
            base = gradient_img((W, H), self.look["plate_fill"]) if self.look.get("plate_fill") else Image.new("RGB", (W, H), (8, 7, 9))
            out = G.to_img(G.apply_look_arr(G.to_f(base), self._plain_look(), self._i, soft=True))
            return mosaic(out, self.mosaic, t) if self.mosaic else out
        if self.panel and self.look["panel"].get("pane3d") not in (None, False):
            # look.panel.pane3d: {...}: the UI as a floating, tilted 3D pane (promo/pane3d.py); the backdrop gets the usual look
            from .. import pane3d as P3
            wf, cyf, dim = panel_params(self.look, self.shot, t, self.dur)
            box = G.panel_box((W, H), wf, cyf, panel_aspect(self.look))
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
            bd = self._backdrop(src, cam, dim)
            fx = self._backdrop_fx(dim)
            if self.mosaic:                                  # the world resolves from a mosaic AFTER the grade / bloom / grain (bloom would blur the
                fx0 = fx                                     # block edges away); the panel is pasted after, so its pixels are never pixelated
                fx = lambda b, f=fx0: mosaic(f(b), self.mosaic, t)   # noqa: E731
            return G.dof_backdrop(panel, box, (W, H), panel=self.look["panel"], backdrop=bd, fx=fx, opacity=op)
        im = R.frame_cam(self.ctx, src, *cam).convert("RGB")
        if self.protect:
            return im                                                  # full-bleed UI: no grade / bloom / grain at all
        out = G.to_img(G.apply_look_arr(G.to_f(im), self._plain_look(), self._i))
        return mosaic(out, self.mosaic, t) if self.mosaic and not self.ui else out

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
        out = self._kinetic(out, t)
        b = black_level(t, self.dur, self.fin, self.fout, self.fin_ease, self.fout_ease)
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
                                       + [f"'{copy_text(spec, c)}'" for c in copy_items(shot)]
                                       + [f"kinetic '{kinetic_text(c)}'" for c in kinetic_items(shot)]) or "none",
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
        for it in kinetic_items(shot):
            res.append(dict(text=kinetic_text(it), role="label", box=None, t0=float(it.get("at", 0.0)),
                            t1=float(it.get("at", 0.0)) + float(it.get("dur", 2.0))))
        for it in copy_items(shot):
            res.append(dict(text=copy_text(ctx.spec, it), role="label", box=None, t0=float(it.get("at", 0.0)),
                            t1=float(it.get("at", 0.0)) + float(it.get("dur", 3.0))))
        return res
