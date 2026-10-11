"""`mv` shot type: the `anime-mv` style preset's renderer (style.preset: anime-mv). Always `ui: false`: an MV shot shows
generated or drawn illustration plates, never product UI (AGENTS.md rule 1 carve-out; gate generated-plates).

The look (measured on Eve "心海", promo/styles.py anime-mv): a 2.35:1 picture band on a cream page (y 131-949 of 1080),
one small tracked Mincho lyric line in the cream under it, flat-cel characters over painted backgrounds, drawings held on
2s, petals / bubbles drifting through, whiteouts and ink wipes on the big cuts.

Shot keys:
    source: <clip id> + t_in / speed      a generated video plate (footage manifest, `generated:`)
    still: <clip id | path>               or one image (camera moves over it)
    fill: [r, g, b]                       or a flat colour (title cards, graphic beats)
    cam: [[t, cx, cy, w], ...]            normalised camera keys over the plate (w = box width / plate width), eased;
                                          default: a still pushes in 1.00 -> 0.92, a video holds w 1.0
    frame_step: 2 | 3                     hold each drawing for N output frames (animation on 2s / 3s); camera stays on 1s
    frame: band | full                    the cream-letterbox picture band (preset default) or full bleed
    look: {grade, bloom, vignette, grain} merged over the preset look (promo/grade.py), picture only (never the lyrics)
    particles: {kind: petals|bubbles|motes|snow|rain, n: 40, seed: 1, color: [r,g,b], dir: [dx, dy], speed: 1.0, size: 1.0}
    fx_in / fx_out: whiteout|flash|ink|iris|smear|rgb    cut effects over `fx_frames` (default 6) at the head / tail
    words: [{text, t: [a, b], layout: big|center|vertical, ...}]   shot-local extra type (a title, a kinetic kanji),
                                          drawn by the lyric layer with the same layouts / anims as `lyrics.lines`
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .. import grade as G
from .. import lyrics as L
from .. import render as R
from . import ShotType, shot_type

FX = ("whiteout", "flash", "ink", "iris", "smear", "rgb")
PARTICLES = ("petals", "bubbles", "motes", "snow", "rain")


def style_of(spec):
    st = getattr(spec, "style", None) or {}
    if st.get("preset") != "anime-mv":
        from ..styles import PRESETS, deep_merge
        st = deep_merge(PRESETS["anime-mv"], st)
    return st


def picture_box(st, cfg, K=1.0):
    """(x0, y0, x1, y1) of the picture in output px."""
    if cfg.get("frame", st["frame"].get("mode", "band")) == "full":
        return 0, 0, int(1920 * K), int(1080 * K)
    fr = st["frame"]
    return 0, int(round(fr["top"] * K)), int(1920 * K), int(round(fr["bottom"] * K))


def cam_keys(cfg, still):
    if cfg.get("cam"):
        return [tuple(k) for k in cfg["cam"]]
    return [(0.0, 0.5, 0.5, 1.0), (999.0, 0.5, 0.5, 0.92)] if still else [(0.0, 0.5, 0.5, 1.0)]


def cam_for(keys, t, dur):
    """Camera at shot-local t; a key time of 999 means 'the end of the shot'."""
    ks = [(dur if k[0] >= 999 else k[0], *k[1:]) for k in keys]
    return R.cam_at(ks, t)


def held_time(i, fps, step):
    """Shot-local time of the drawing shown at frame i when animating on `step`s."""
    step = max(1, int(step or 1))
    return (i // step) * step / fps


# ---------------------------------------------------------------- particles (seeded, pure functions of time)
def particle_state(cfg, t, size):
    """[(x, y, r, phase)] in picture px for the particle field at shot-local t. Same cfg + t = same field."""
    W, H = size
    n = int(cfg.get("n", 40))
    rng = np.random.default_rng(int(cfg.get("seed", 1)))
    x0, y0 = rng.random(n) * W, rng.random(n) * H
    depth = 0.4 + 0.6 * rng.random(n)                       # far particles are smaller and slower
    kind = cfg.get("kind", "petals")
    d = cfg.get("dir") or {"petals": [-0.35, 0.25], "bubbles": [0.02, -0.18], "motes": [0.05, -0.04], "snow": [0.03, 0.12],
                           "rain": [-0.08, 1.6]}[kind]
    sp = float(cfg.get("speed", 1.0))
    vx, vy = d[0] * W * sp * depth, d[1] * H * sp * depth
    wob = np.sin(t * (1.3 + rng.random(n)) + rng.random(n) * 6.28) * H * 0.012 if kind in ("petals", "snow", "bubbles") else 0
    xs = (x0 + vx * t + wob) % (W + 80) - 40
    ys = (y0 + vy * t) % (H + 80) - 40
    base = {"petals": 0.011, "bubbles": 0.010, "motes": 0.004, "snow": 0.004, "rain": 0.0015}[kind] * W * float(cfg.get("size", 1.0))
    rs = base * depth
    ph = rng.random(n) * 6.28 + t * (2.0 + 2 * rng.random(n))
    return list(zip(xs, ys, rs, ph, depth))


_PETAL = {}


def petal_sprite(r, col, angle, squash):
    """An antialiased cherry-petal shape (rounded teardrop with a notch, lighter heart), rotated and squashed edge-on."""
    k = (int(r * 4), col, int(angle) // 15 * 15, round(squash, 1))
    if k not in _PETAL:
        S = max(8, int(r * 4)) * 4                         # drawn 4x, downsampled = antialiased
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        top, bot = [], []
        for j in range(33):                                # along the petal: pointed base (x=-1) -> wide notched tip (x=+1)
            x = -1 + 2 * j / 32
            w = 0.5 * math.sqrt(max(0.0, 1 - x * x)) ** 0.8 * (0.45 + 0.55 * (x + 1) / 2)
            top.append((S / 2 + x * S * 0.46, S / 2 - w * S * 0.46))
            bot.append((S / 2 + x * S * 0.46, S / 2 + w * S * 0.46))
        notch = (S / 2 + 0.80 * S * 0.46, S / 2)
        ImageDraw.Draw(im).polygon(top + [notch] + bot[::-1], fill=col + (255,))
        im = im.resize((S // 4, max(1, int(S // 4 * max(squash, 0.12)))), Image.LANCZOS).rotate(k[2], expand=True, resample=Image.BICUBIC)
        _PETAL[k] = im
    return _PETAL[k]


def _paste(dst, src, x, y):
    """alpha_composite that clips at the edges (Pillow refuses a negative destination)."""
    cx0, cy0 = max(0, -x), max(0, -y)
    cx1, cy1 = min(src.width, dst.width - x), min(src.height, dst.height - y)
    if cx1 > cx0 and cy1 > cy0:
        dst.alpha_composite(src.crop((cx0, cy0, cx1, cy1)), (x + cx0, y + cy0))


def draw_particles(img, cfg, t, K=1.0):
    """Particles over the picture (RGBA in, RGBA out)."""
    kind = cfg.get("kind", "petals")
    col = tuple(cfg.get("color") or {"petals": [244, 160, 140], "bubbles": [235, 250, 250], "motes": [255, 244, 214],
                                     "snow": [255, 255, 255], "rain": [210, 228, 236]}[kind])
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for x, y, r, ph, dep in particle_state(cfg, t, img.size):
        a = int(255 * (0.55 + 0.45 * dep))
        if kind == "petals":                                  # tumbling: the petal turns edge-on and back while it spins
            sp = petal_sprite(r, col, math.degrees(ph * 0.7) % 360, 0.35 + 0.65 * abs(math.cos(ph)))
            if a < 255:
                sp = sp.copy()
                sp.putalpha(sp.split()[3].point(lambda v, a_=a: v * a_ // 255))
            _paste(lay, sp, int(x - sp.width / 2), int(y - sp.height / 2))
        elif kind == "bubbles":
            w_ = max(1, int(r * 0.18))
            d.ellipse((x - r, y - r, x + r, y + r), outline=col + (int(a * 0.8),), width=w_)
            d.ellipse((x - r * 0.45, y - r * 0.6, x - r * 0.1, y - r * 0.25), fill=(255, 255, 255, a))
        elif kind == "rain":
            d.line((x, y, x - r * 6, y - r * 40), fill=col + (int(a * 0.6),), width=max(1, int(r)))
        else:
            d.ellipse((x - r, y - r, x + r, y + r), fill=col + (a,))
    if kind == "motes":
        glow = lay.filter(ImageFilter.GaussianBlur(4 * K))
        lay = Image.alpha_composite(glow, lay)
    img.alpha_composite(lay)
    return img


# ---------------------------------------------------------------- cut effects
_NOISE = {}


def _noise(size, seed=3):
    k = (size, seed)
    if k not in _NOISE:
        w, h = size
        rng = np.random.default_rng(seed)
        small = Image.fromarray((rng.random((max(2, h // 24), max(2, w // 24))) * 255).astype(np.uint8))
        n = np.asarray(small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(w / 160)), np.float32) / 255.0
        n = (n - n.min()) / max(n.max() - n.min(), 1e-6)
        _NOISE[k] = n
    return _NOISE[k]


def fx_amount(cfg, i, n, fps):
    """(kind, p) of the cut effect at frame i: p = 1 at the cut, 0 when it has cleared. (None, 0) outside the windows."""
    k = int(cfg.get("fx_frames", 6))
    if cfg.get("fx_in") and i < k:
        return cfg["fx_in"], 1 - i / k
    if cfg.get("fx_out") and i >= n - k:
        return cfg["fx_out"], (i - (n - k) + 1) / k
    return None, 0.0


def apply_fx(pic, kind, p, paper):
    """Cut effect on the picture (RGB): p in [0, 1] = strength."""
    if not kind or p <= 0:
        return pic
    if kind == "whiteout":
        return Image.blend(pic, Image.new("RGB", pic.size, tuple(paper)), min(1.0, p))
    if kind == "flash":
        return Image.blend(pic, Image.new("RGB", pic.size, (255, 255, 255)), 0.85 if p > 0.5 else 0.0)
    if kind == "ink":                                        # organic blobs eat the picture (noise threshold), paper behind
        m = (_noise(pic.size) < p).astype(np.uint8) * 255
        mask = Image.fromarray(m).filter(ImageFilter.GaussianBlur(1.5))
        return Image.composite(Image.new("RGB", pic.size, tuple(paper)), pic, mask)
    if kind == "iris":                                       # circle closes to the centre
        w, h = pic.size
        r = math.hypot(w, h) / 2 * (1 - p)
        mask = Image.new("L", pic.size, 255)
        ImageDraw.Draw(mask).ellipse((w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r), fill=0)
        return Image.composite(Image.new("RGB", pic.size, (20, 30, 44)), pic, mask)
    if kind == "smear":                                      # horizontal motion smear
        a = np.asarray(pic, np.float32)
        k = max(1, int(p * pic.size[0] * 0.04))
        c = np.cumsum(np.pad(a, ((0, 0), (k, 0), (0, 0)), mode="edge"), axis=1)
        a = (c[:, k:] - c[:, :-k]) / k
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if kind == "rgb":
        a = np.asarray(pic)
        s = max(1, int(p * pic.size[0] * 0.008))
        out = a.copy()
        out[:, s:, 0] = a[:, :-s, 0]
        out[:, :-s, 2] = a[:, s:, 2]
        return Image.fromarray(out)
    return pic


# ---------------------------------------------------------------- the shot
class _Plate:
    def __init__(self, spec, cfg, fps):
        self.src = self.img = None
        self.fill = None                    # a flat colour only when there is no take yet (it is the placeholder until one lands)
        if not (cfg.get("source") or cfg.get("still")):
            self.fill = cfg.get("fill")
        if cfg.get("source"):
            t_in = float(cfg.get("t_in", 0.0))
            self.speed = float(cfg.get("speed", 1.0))
            self.t_in = t_in
            self.src = R.Source(spec.footage_path(cfg["source"]), t_in, t_in + 60.0)
        elif cfg.get("still"):
            s = str(cfg["still"])
            from .. import footage as FT
            p = spec.footage_path(s) if s in FT.load(spec) else spec.resolve(s)       # a take id from the manifest, or a project-relative image
            self.img = R.still(p)

    def at(self, t):
        if self.src is not None:
            fr = self.src.frame(self.t_in + t * self.speed)
            if fr is not None:
                self.img = fr
        return self.img

    def close(self):
        if self.src is not None:
            self.src.close()


@shot_type("mv")
class MV(ShotType):
    draws_lyrics = True

    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        st = style_of(spec)
        K, fps = ctx.K, ctx.fps
        x0, y0, x1, y1 = picture_box(st, cfg, K)
        pw, ph = x1 - x0, y1 - y0
        paper = tuple(st["frame"]["color"])
        look = G.merge(st.get("look") or {}, cfg.get("look") or {})
        step = int(cfg.get("frame_step", st["pacing"].get("frame_step", 2)))
        plate = _Plate(spec, cfg, fps)
        keys = cam_keys(cfg, still=plate.src is None)
        parts = cfg.get("particles")
        if isinstance(parts, str):
            parts = {"kind": parts}
        lyr = L.LyricLayer(ctx, spec)
        words = _ShotWords(ctx, spec, shot) if cfg.get("words") else None
        total = shot.dur

        cache = {}

        def picture(i, t):
            th = held_time(i, fps, step)
            cam = None if plate.fill is not None else tuple(round(v, 5) for v in cam_for(keys, t, total))
            if cache.get("key") == (th, cam):             # a held drawing under a still camera: the same graded picture (grain boils on 2s too)
                return cache["pic"]
            if plate.fill is not None:
                pic = Image.new("RGB", (pw, ph), tuple(plate.fill))
            else:
                im = plate.at(th)
                if im is None:
                    raise RuntimeError(f"shot {shot.id}: no plate (source / still / fill)")
                pic = R.frame_cam(ctx, im, cam[0], cam[1], cam[2], out=(pw, ph))
            if G.enabled(look.get("grade")) or G.enabled(look.get("bloom")) or G.enabled(look.get("grain")):
                pic = G.to_img(G.apply_look_arr(G.to_f(pic), look, frame=shot.f0 + int(round(th * fps))))
            cache.update(key=(th, cam), pic=pic)
            return pic

        def f(i, t):
            pic = picture(i, t)
            kind, p = fx_amount(cfg, i, shot.n, fps)
            pic = apply_fx(pic, kind, p, paper)
            pic = pic.convert("RGBA")
            if parts:
                pic = draw_particles(pic, parts, held_time(i, fps, step), K)
            out = Image.new("RGBA", (ctx.OW, ctx.OH), paper + (255,))
            out.alpha_composite(pic, (x0, y0))
            out = lyr.apply(out, shot.f0 + i)
            if words is not None:
                out = words.apply(out, shot.f0 + i)
            return out

        try:
            R.run_shot(ctx, shot, f)
        finally:
            plate.close()
        live = lyr.overlaps(shot.f0 / fps, (shot.f0 + shot.n) / fps)
        return dict(src=cfg.get("label", cfg.get("source") or cfg.get("still") or "fill"),
                    inout=f"t_in {cfg.get('t_in', 0)} x{cfg.get('speed', 1.0)}, drawings on {step}s",
                    move=cfg.get("move", f"cam {keys[0][1:]} -> {keys[-1][1:]}"),
                    caption=" / ".join(l["text"] for l in live) or "none", notes=cfg.get("notes", ""))

    def captions(self, ctx, shot):
        return []


class _ShotWords(L.LyricLayer):
    """A shot's own `words:` (shot-local times) drawn with the lyric layouts."""

    def __init__(self, ctx, spec, shot):
        self.ctx, self.spec = ctx, spec
        st = L.style_of(spec)
        t0 = shot.f0 / spec.fps
        self.lines = []
        for i, w in enumerate(shot.cfg.get("words") or []):
            lay = w.get("layout", "big")
            base = dict(size=st["size"], color=st["color"], tracking=st["tracking"], y=st["y"], x=960, shadow=0.0)
            base.update(st.get(lay) or {})
            base.update({k: w[k] for k in ("size", "color", "tracking", "x", "y", "shadow") if w.get(k) is not None})
            a, b = w.get("t") or [0.0, shot.dur]
            self.lines.append(dict(base, i=1000 + i, text=str(w["text"]), a=t0 + a, b=t0 + b, layout=lay, anim=w.get("anim", "ink"),
                                   fade_s=float(w.get("fade_s", 0.2)), sung=None, unsynced=False))
        self.fpath = L.font_path(spec) if self.lines else None
        self._lay, self._spr = {}, {}
