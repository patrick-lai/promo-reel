"""`podcast` shot: Live2D hosts over the real app, laid out by promo.podcast.layout_at (no box by default).

Shot keys (the show-level hosts, layout, placement, frame, edge, backdrop and subtitles live in the spec's `podcast:` block):
    layout: overlay | boxed | two-shot | speaker
    screen: {source: <footage clip id>, t_in: 0, speed: 1, cam: [cx, cy, w]}   real app footage (never edited): the whole frame
            in overlay, a window in the other layouts; or {card: {title, subtitle, lines}} | {placeholder: "..."}
    focus: a | b | auto            speaker layout: the host on camera (auto = whoever spoke last, cut at line starts)
    place: {a: {anchor, size, x, y}} per-shot placement
    cam: [[0, 1.0], [end, 1.06]]   a slow push on the hosts
    overlays: [...]                the usual overlays

Host layers are rendered once per show by `promo.live2d.render_host` (supersampled, deterministic, ProRes 4444 alpha)
into build/live2d/podcast-<id>-<W>.mov, stamped by a digest of the host, its VO track, the partner's, the script's
performance keys and the renderer code, and re-used by every podcast shot (layer frame = global frame index).
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .. import podcast as P
from .. import render as R
from ..cache import Stamps, code_hash, digest
from ..overlays import apply_overlays, build_overlays, caption_boxes
from . import ShotType, shot_type
from .livestream import LayerReader, comp, content_sig, framed, host_track, placeholder_screen, screen_card, src_time

# The host layers depend on these modules' code; everything else they use (geometry, line times, gaze sides, the VO takes) goes into their
# digest as data, so a subtitle or layout change never re-renders Live2D.
PODCAST_CODE = ["live2d", "perform", "mesh_avatar"]


def layer_path(spec, hid):
    return os.path.join(spec.build, "live2d", f"podcast-{hid}-{spec.OW}.mov")


def supersample(spec):
    v = P.cfg(spec).get("supersample")
    return int(v) if v else (2 if spec.scale >= 1 else 1)


def partner_dirs(spec, i):
    """Per-frame side (-1 left / +1 right) of the nearest other host, from each podcast shot's layout (a hidden partner
    in the speaker cam stays where the show layout has them)."""
    c = P.cfg(spec)
    n = int(round(spec.duration * spec.fps))
    out = np.zeros(n)
    hs = P.hosts(c)
    if len(hs) < 2:
        return np.full(n, -1.0 if i == 0 else 1.0)
    M = P.master(spec)
    base = [P.host_geometry(M, j, P.resolve_place(c, {}, h, "overlay", j, len(hs)))["xc"] for j, h in enumerate(hs)]
    default = np.sign(np.mean([b for j, b in enumerate(base) if j != i]) - base[i]) or 1.0
    out[:] = default
    for s in spec.shots:
        if s.type != "podcast":
            continue
        L = P.layout_at(spec, s, 0.0, [])
        me = L["hosts"][i]
        others = [g for g in L["hosts"] if g["i"] != i and g["visible"]]
        if others and me["visible"]:
            d = np.sign(min(others, key=lambda g: abs(g["xc"] - me["xc"]))["xc"] - me["xc"]) or default
            out[s.f0:s.f0 + s.n] = d
    return out


def _mix_partners(spec, wavs, i):
    """The other hosts' VO in one track (listening nods and gaze react to anyone talking)."""
    others = [w for j, w in enumerate(wavs) if j != i and w]
    if len(others) <= 1:
        return others[0] if others else None
    import soundfile as sf
    xs = [sf.read(w, dtype="float32", always_2d=True) for w in others]
    sr = xs[0][1]
    n = max(len(x) for x, _ in xs)
    buf = np.zeros(n, np.float32)
    for x, r in xs:
        buf[:len(x)] += x.mean(1)
    out = os.path.join(spec.build, "live2d", f"partners-{P.hosts(P.cfg(spec))[i].get('id')}.wav")
    sf.write(out, buf, sr, subtype="PCM_16")
    return out


def ensure_podcast_layers(spec, log=print):
    """Render (or reuse) one alpha master layer per host covering the whole show. Returns {host id: path}."""
    from .. import live2d as L2
    from .. import mesh_avatar as MA
    c = P.cfg(spec)
    hs = P.hosts(c)
    M = P.master(spec)
    st = Stamps(spec.build)
    lines = P.timed_lines(spec)
    wavs = [host_track(spec, h, log) for h in hs]
    extra = [os.path.join(L2.L2D_DIR, f) for f in ("render.mjs", "page.html", "mesh-page.html", "assets.yaml")]
    ss = supersample(spec)
    out = {}
    for i, h in enumerate(hs):
        hid = str(h.get("id", i))
        mh = M["hosts"][i]
        p = layer_path(spec, hid)
        partner = _mix_partners(spec, wavs, i)
        own = [dict(ln) for ln in lines if ln["host"] == i]
        others = [dict(ln) for ln in lines if ln["host"] != i]
        pd = partner_dirs(spec, i)
        g0 = P.host_geometry(M, i, P.resolve_place(c, {}, h, "overlay", i, len(hs)))
        sd = (0.45 * (1.0 if g0["xc"] < P.FRAME_W / 2 else -1.0), 0.35)          # the screen is behind and above: look up and inward
        try:
            umodel = L2.model_entry(h["model"])
        except L2.Live2DError:
            umodel = None
        wav = wavs[i]
        dig = digest(P.plain(h), content_sig(wav) if wav else None, content_sig(partner) if partner else None, spec.duration, spec.fps, spec.scale,
                     [round(float(x), 2) for x in pd[:: max(1, spec.fps // 2)]], mh["W"], M["H"], mh["frame"], own, others, sd, ss, P.plain(umodel),
                     MA.signature(umodel), code_hash(*PODCAST_CODE, extra_files=extra))
        key = f"podcast_{hid}_{spec.OW}"
        if not st.is_fresh(key, dig, [p]):
            if R.sampling():
                raise R.NotYet("the hosts are not rendered yet")
            K = spec.scale
            rep = L2.render_host(h["model"], p, wav=wav, partner_wav=partner, duration=spec.duration, fps=spec.fps,
                                 width=int(round(mh["W"] * K)), height=int(round(M["H"] * K)), seed=int(h.get("seed", 11 * (i + 1))), gaze=pd,
                                 frame=dict(mh["frame"], pad_top=mh["frame"]["pad_top"] * K), log=log, lines=own, partner_lines=others,
                                 screen_dir=sd, supersample=ss, energy=float(h.get("energy", 1.0)))
            st.write(key, dig, report=rep)
        out[hid] = p
    return out


# ---------------------------------------------------------------- drawing
def backdrop_still(ctx, bd):
    """A static backdrop: gradient (default) or an image."""
    W, H = ctx.OW, ctx.OH
    if bd.get("image"):
        im = Image.open(ctx.spec.resolve(bd["image"])).convert("RGB")
        return R.frame_cam(ctx, im, 0.5, 0.5, 1.0).convert("RGBA")
    g = bd.get("gradient") or [[12, 14, 30], [46, 30, 84]]
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    u = np.clip((x / W * 0.6 + y / H * 0.4), 0, 1)[..., None]
    arr = np.array(g[0], np.float32) * (1 - u) + np.array(g[-1], np.float32) * u
    r = np.sqrt(((x - W * 0.5) / (W * 0.6)) ** 2 + ((y - H * 0.35) / (H * 0.7)) ** 2)
    arr += (np.clip(1 - r, 0, 1) ** 2)[..., None] * 18
    arr += np.random.default_rng(5).normal(0, 1.1, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")


def scale_layer(fr, w, h):
    """Resize an RGBA layer with premultiplied alpha (no dark fringes)."""
    if fr.size == (w, h):
        return fr
    return fr.convert("RGBa").resize((max(1, w), max(1, h)), Image.LANCZOS).convert("RGBA")


def edge_layer(im, edge, color, K):
    """Decoration from the avatar's own alpha only (never a box): soft drop shadow, coloured glow or a thin rim."""
    a = im.getchannel("A")
    if edge == "shadow":
        sh = a.filter(ImageFilter.GaussianBlur(10 * K)).point(lambda v: int(v * 0.42))
        lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        lay.putalpha(sh)
        out = Image.new("RGBA", im.size, (0, 0, 0, 0))
        out.alpha_composite(lay, (int(7 * K), int(9 * K)))
        return out
    if edge == "glow":
        g = a.filter(ImageFilter.GaussianBlur(14 * K)).point(lambda v: min(255, int(v * 0.75)))
        lay = Image.new("RGBA", im.size, tuple(color) + (0,))
        lay.putalpha(g)
        return lay
    if edge == "rim":
        k = max(3, int(round(3 * K)) | 1)
        ring = ImageChops.subtract(a.filter(ImageFilter.MaxFilter(k)), a).filter(ImageFilter.GaussianBlur(0.6 * K))
        lay = Image.new("RGBA", im.size, tuple(color) + (0,))
        lay.putalpha(ring)
        return lay
    return None


def soft_mask(w, h, bottom=0.22, sides=0.10):
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    my = np.clip((1 - y) / bottom, 0, 1)
    mx = np.clip(np.minimum(x, 1 - x) / sides, 0, 1)
    return Image.fromarray((np.minimum(my, mx) * 255).astype(np.uint8), "L")


def card_box(g):
    """The card behind a host in overlay / two-shot / speaker (`frame: card`): around the bust, open to the frame bottom."""
    fx0, fy0, fx1, fy1 = g["face"]
    head = fy1 - fy0
    cx = (fx0 + fx1) / 2
    return [cx - 1.55 * head, fy0 - 0.55 * head, cx + 1.55 * head, min(P.FRAME_H, g["layer"][3])]


def framed_host(ctx, im, g, frame, color, K):
    """(image, x, y) of a host drawn with its frame style: none (as is), card (rounded panel, clipped at its sides and
    bottom, the hat may break out on top), circle (round badge with a ring), soft (feathered bottom and sides)."""
    x, y = g["layer"][0] * K, g["layer"][1] * K
    if frame == "soft":
        a = np.asarray(im.getchannel("A")).astype(np.float32) * (np.asarray(soft_mask(im.width, im.height)).astype(np.float32) / 255.0)
        im = im.copy()
        im.putalpha(Image.fromarray(a.astype(np.uint8)))
        return [(im, x, y)]
    if frame in ("card", "circle"):
        box = g["panel"] or card_box(g)
        bx0, by0, bx1, by1 = [int(round(v * K)) for v in box]
        bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)
        if frame == "circle":
            fx0, fy0, fx1, fy1 = g["face"]
            head = fy1 - fy0
            cx, cy, r = (fx0 + fx1) / 2, fy0 + 0.75 * head, 1.25 * head
            bx0, by0 = int((cx - r) * K), int((cy - r) * K)
            bw = bh = int(2 * r * K)
            mask = Image.new("L", (bw, bh), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, bw - 1, bh - 1], fill=255)
            bg = Image.new("RGBA", (bw, bh), (16, 17, 26, 0))
            bg.putalpha(mask.point(lambda v: int(v * 0.86)))
        else:
            r = int(16 * K)
            mask = R.rounded_mask(bw, bh, r)
            bg = Image.new("RGBA", (bw, bh), (26, 27, 38, 0))
            bg.putalpha(mask.point(lambda v: int(v * 0.84)))
        # clip the host to the panel (a card keeps its top open so a hat can break out)
        a = np.asarray(im.getchannel("A")).astype(np.float32)
        clip = Image.new("L", im.size, 0)
        clip.paste(mask, (int(bx0 - x), int(by0 - y)))
        cl = np.asarray(clip).astype(np.float32) / 255.0
        if frame == "card":
            top = int(by0 - y) + bh // 2
            cl[: max(0, top)] = np.maximum(cl[: max(0, top)], ((np.arange(im.width) >= bx0 - x) & (np.arange(im.width) < bx0 - x + bw))[None, :] * 1.0)
        im = im.copy()
        im.putalpha(Image.fromarray((a * cl).astype(np.uint8)))
        parts = [(bg, bx0, by0), (im, x, y)]
        if frame == "circle":
            ring = Image.new("RGBA", (bw + 8, bh + 8), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse([2, 2, bw + 5, bh + 5], outline=tuple(color) + (255,), width=max(2, int(3 * K)))
            parts.append((ring, bx0 - 4, by0 - 4))
        return parts
    return [(im, x, y)]


def pill(ctx, text, color, size=P.SUB_SIZE, alpha=1.0, weight="SemiBold"):
    """Subtitle / name pill: dark translucent, a bar in the speaker's colour, white text."""
    K = ctx.K
    f = ctx.font(size, weight)
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    tw = d.textlength(text, font=f)
    bar, padx = int(6 * K), int(18 * K)
    h = int((size + 18) * K)
    w = int(tw + bar + 2 * padx + 6 * K)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(12 * K), fill=(14, 15, 26, int(212 * alpha)))
    dd.rounded_rectangle([int(9 * K), int(h * 0.2), int(9 * K) + bar, int(h * 0.8)], radius=bar // 2, fill=tuple(color) + (int(255 * alpha),))
    bb = dd.textbbox((0, 0), text, font=f)
    dd.text((int(9 * K) + bar + padx - bb[0], (h - (bb[3] + bb[1])) / 2), text, font=f, fill=(255, 255, 255, int(255 * alpha)))
    return im


def names_on(c, shot, spec, layout):
    v = c.get("names", "auto")
    if v is True or layout == "boxed":
        return True
    if v is False:
        return False
    first = next((s for s in spec.shots if s.type == "podcast"), None)
    return first is not None and first.id == shot.id


class Composer:
    """Draws one podcast frame from the host master frames, the app screen frame and the show's layout. The shot
    renderer and `promo podcast preview` share it, so a preview still is what the render will look like."""

    def __init__(self, ctx, shot, lines=None):
        spec = ctx.spec
        self.ctx, self.shot, self.spec = ctx, shot, spec
        c = self.c = P.cfg(spec)
        self.hs = P.hosts(c)
        self.lines = P.timed_lines(spec) if lines is None else lines
        self.rows = P.subtitle_rows(spec, self.lines)
        self.colors = [P.rgb(P.host_color(c, i)) for i in range(len(self.hs))]
        self.sc = shot.cfg.get("screen") or {}
        self.bd = dict(c.get("backdrop") or {})
        self.L0 = P.layout_at(spec, shot, 0.0, self.lines)
        if not self.bd and self.sc.get("source") and not self.L0["screen_full"]:
            self.bd = {"blur_screen": True}
        self.still_bg = None if (self.bd.get("plate") or self.bd.get("blur_screen")) else backdrop_still(ctx, self.bd)
        self.overlays = build_overlays(ctx, shot.cfg.get("overlays"))
        self.show_names = names_on(c, shot, spec, self.L0["layout"])
        self.name_pills = [pill(ctx, str(h.get("name") or h["model"]), self.colors[i], size=24, weight="Bold") for i, h in enumerate(self.hs)]
        title = " · ".join(x for x in (str(c.get("tag") or ""), str(c.get("title") or "")) if x)
        first = next((s for s in spec.shots if s.type == "podcast"), None)
        self.title_pill = pill(ctx, title, (139, 124, 255), size=24, weight="SemiBold") if title and first is not None and first.id == shot.id else None
        self.card_cache, self.sub_cache = {}, {}

    def screen_image(self, im, size):
        """The screen at `size`: the footage frame through the shot's cam, else the generated card / placeholder."""
        ctx, sc = self.ctx, self.sc
        if sc.get("source"):
            return R.frame_cam(ctx, im, *sc.get("cam", (0.5, 0.5, 1.0)), out=size) if im is not None else None
        if size not in self.card_cache:
            self.card_cache[size] = (screen_card(ctx, *size, sc["card"]) if sc.get("card") else
                                     placeholder_screen(ctx, *size, sc.get("placeholder", "APP FOOTAGE"))).convert("RGB")
        return self.card_cache[size]

    def frame(self, t, frames, screen_frame=None, plate_frame=None):
        ctx, K, shot, bd = self.ctx, self.ctx.K, self.shot, self.bd
        tg = shot.t0 + t
        L = P.layout_at(self.spec, shot, t, self.lines)
        s = L["screen"]
        if L["screen_full"]:
            im = self.screen_image(screen_frame, (ctx.OW, ctx.OH))
            out = im.convert("RGBA") if im is not None else backdrop_still(ctx, {})
        else:
            win = self.screen_image(screen_frame, (int(round((s[2] - s[0]) * K)), int(round((s[3] - s[1]) * K)))) if s else None
            if plate_frame is not None:
                out = R.frame_cam(ctx, plate_frame, 0.5, 0.5, 1.0).convert("RGBA")
            elif bd.get("blur_screen") and win is not None:
                big = win.resize((ctx.OW, ctx.OH), Image.BILINEAR).filter(ImageFilter.GaussianBlur(26 * K))
                out = Image.blend(big, Image.new("RGB", big.size, (8, 9, 16)), 0.45).convert("RGBA")
            else:
                out = (self.still_bg or backdrop_still(ctx, {})).copy()
            if win is not None:
                lay, pad = framed(ctx, win)
                comp(out, lay, s[0] * K - pad, s[1] * K - pad)
        if self.title_pill is not None:
            comp(out, self.title_pill, 32 * K, 28 * K)
        for g, fr in zip(L["hosts"], frames):
            if not g["visible"] or fr is None:
                continue
            w, h = int(round((g["layer"][2] - g["layer"][0]) * K)), int(round((g["layer"][3] - g["layer"][1]) * K))
            im = scale_layer(fr, w, h)
            parts = framed_host(ctx, im, g, L["frame"], self.colors[g["i"]], K)
            if L["edge"] != "none" and L["frame"] in ("none", "soft"):
                e = edge_layer(parts[-1][0], L["edge"], self.colors[g["i"]], K)
                if e is not None:
                    parts = [(e, parts[-1][1], parts[-1][2])] + parts
            for p_im, px, py in parts:
                comp(out, p_im, px, py)
            if self.show_names:
                tag = self.name_pills[g["i"]]
                if g["panel"] is not None:
                    comp(out, tag, (g["panel"][0] + 14) * K, g["panel"][3] * K - tag.height - 14 * K)
                else:
                    comp(out, tag, g["xc"] * K - tag.width / 2, min(P.FRAME_H, g["layer"][3]) * K - tag.height - 22 * K)
        vis = P.rows_at(self.rows, tg)
        for slot, r in zip((0, 1) if len(vis) == 2 else (1,), vis):
            key = (r["text"], r["host"], slot)
            if key not in self.sub_cache:
                col = self.colors[r["host"]] if r["host"] is not None else (200, 200, 210)
                self.sub_cache[key] = pill(ctx, r["text"], col, alpha=0.82 if slot == 0 else 1.0)
            pm = self.sub_cache[key]
            a = min(1.0, (tg - r["t0"]) / 0.12)
            if a < 1:
                pm = pm.copy()
                pm.putalpha(pm.getchannel("A").point(lambda v: int(v * a)))
            comp(out, pm, 960 * K - pm.width / 2, P.SUB_ROWS_Y[slot] * K - pm.height / 2)
        return apply_overlays(self.overlays, out, t)


@shot_type("podcast")
class Podcast(ShotType):
    def render(self, ctx, shot):
        if not P.cfg(ctx.spec):
            raise ValueError("podcast shot needs a show-level `podcast:` block in promo.yaml")
        from ..lock import heavy_lock
        with heavy_lock(f"podcast shot {shot.id}"):
            return self._render(ctx, shot)

    def captions(self, ctx, shot):
        """Overlay captions (generic gates) + the subtitle rows of this shot (role `subtitle`: the podcast-subtitles gate
        judges them on the show's timeline, so a row that runs across a cut is not cut short)."""
        out = caption_boxes(ctx, shot)
        spec = ctx.spec
        for r in P.subtitle_rows(spec):
            if shot.t0 <= r["t0"] < shot.t1:
                out.append(dict(text=r["text"], role="subtitle", box=P.subtitle_box(r["text"], 1), t0=r["t0"] - shot.t0, t1=r["t1"] - shot.t0))
        return out

    def _render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        c = P.cfg(spec)
        hs = P.hosts(c)
        K = ctx.K
        layers = ensure_podcast_layers(spec)
        M = P.master(spec)
        readers = [LayerReader(layers[str(h.get("id", i))], int(round(M["hosts"][i]["W"] * K)), int(round(M["H"] * K)), shot.f0, spec.fps)
                   for i, h in enumerate(hs)]
        sc = cfg.get("screen") or {}
        src = None
        if sc.get("source"):
            src = R.Source(spec.footage_path(sc["source"]), sc.get("t_in", 0.0), sc.get("t_in", 0.0) + shot.dur * sc.get("speed", 1.0) + 0.1)
        hold_in = float(sc.get("hold_in", 0.0))
        comp_ = Composer(ctx, shot)
        plate = None
        if comp_.bd.get("plate"):
            t_in = float(comp_.bd.get("t_in", 0.0))
            plate = R.Source(spec.footage_path(comp_.bd["plate"]), t_in, t_in + shot.dur + 0.2)

        def f(i, t):
            frames = [r.at(i) for r in readers]
            im = src.frame(src_time(sc, t, hold_in)) if src is not None else None
            pl = plate.frame(float(comp_.bd.get("t_in", 0.0)) + t) if plate is not None else None
            return comp_.frame(t, frames, im, pl)
        L0 = comp_.L0
        overlays = comp_.overlays
        try:
            R.run_shot(ctx, shot, f)
        finally:
            for r in readers:
                r.close()
            for x in (src, plate):
                if x is not None:
                    x.close()
        hs = P.hosts(P.cfg(spec))
        return dict(src=sc.get("source") or ("generated card" if sc.get("card") else "no screen"), inout=f"global frames {shot.f0}-{shot.f0 + shot.n - 1}",
                    move=f"podcast {L0['layout']}" + (f", focus {cfg.get('focus', 'auto')}" if L0["layout"] == "speaker" else "") + f", frame {L0['frame']}",
                    caption=" / ".join(f"'{o.cfg['text']}'" for o in overlays if o.role == "caption") or "subtitles",
                    notes=f"Live2D hosts: {', '.join(h['model'] for h in hs)}; credit on the live2d_credits end card")
