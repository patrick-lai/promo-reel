"""commission-ai project plugin: bespoke shot types ported from the legacy build_hero.py.

    composer      (s03)  UI composer cropped + masked, floating over a plate; typing time-remap
    rail_labels   (s05)  camera push with lower-third labels anchored to rail rows
    tilt_card     (s06)  stills: fake-3D tilted card over a blurred board
    float_window  (s15)  floating rounded window with a two-camera dissolve over a plate
    tiles         (s16)  three rounded tiles sliding in
    clip_tx       (s02)  generic clip whose shutter blur is only a short transition window (hero v2, Zen: blur < 0.4 s)

They only use the public promo.render / promo.overlays APIs; the maths is identical to the legacy code.
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from promo import render as R
from promo.overlays import apply_overlays, build_overlays
from promo.shots import ShotType, shot_type
from promo.spec import number, resolve_cam_keys


# ---------------------------------------------------------------- composer (s03)
def composer_layer(ctx, img, box, out_w):
    """Crop the composer from a UI frame, mask to its rounded rect, scale to out_w (output px)."""
    SW, SH = img.size
    x0, y0, x1, y1 = box[0] * SW, box[1] * SH, box[2] * SW, box[3] * SH
    # the composer grows upward when the 2nd line is typed: find its top border (bright line above the dark outer frame)
    col = np.asarray(img.convert("L"), dtype=np.int16)[:, int(0.26 * SW)]
    ys = [y for y in range(int(y1 - 0.03 * SH), int(0.84 * SH), -1) if col[y] > 70 and col[y - int(0.0028 * SH)] < 45]
    if ys:
        y0 = ys[0] - 0.0009 * SH
    oh = int(out_w * (y1 - y0) / (x1 - x0))
    c = img.resize((out_w, oh), Image.LANCZOS, box=(x0, y0, x1, y1)).convert("RGBA")
    c.putalpha(R.rounded_mask(out_w, oh, int(0.12 * oh)))
    return R.soft_shadow_layer(ctx, c)


@shot_type("composer")
class Composer(ShotType):
    """Spec: source, src_range [in, out], box [x0,y0,x1,y1], tmap {src0, span, dur, end_src}, width, scale_up, y, plate, overlays.
    Output time t < tmap.dur maps to source src0 + t*(span/dur); afterwards the source holds at end_src."""

    @staticmethod
    def _tm(shot):
        m = shot["tmap"]
        return m["src0"], m["span"], m["dur"], m["end_src"]

    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        src0, span, tdur, end_src = self._tm(shot)
        n = shot.n
        src = R.Source(spec.footage_path(cfg["source"]), *cfg["src_range"])
        box = cfg["box"]
        bg = R.plate(ctx, cfg.get("plate", "night"))
        overlays = build_overlays(ctx, cfg.get("overlays"))

        def tmap(t):   # hold the empty composer, type src0..src0+span in `dur` s, hold the finished ask
            return src0 + t * (span / tdur) if t < tdur else end_src

        def f(i, t):
            ui = src.frame(tmap(t))
            (lay, pad) = composer_layer(ctx, ui, box, int(cfg.get("width", 1380) * ctx.K * (1.0 + cfg.get("scale_up", 0.05) * R.ease(t / (n / ctx.fps)))))
            out = bg.convert("RGBA")
            out.alpha_composite(lay, (int((ctx.OW - lay.width) / 2), int(ctx.OH * cfg.get("y", 0.50) - lay.height)))
            return apply_overlays(overlays, out, t)

        try:
            R.run_shot(ctx, shot, f)
        finally:
            src.close()
        return dict(src=cfg.get("label", cfg["source"]), inout=f"type {src0:.2f}-{src0 + span:.2f} s src in {tdur} s, then hold",
                    move="composer masked to its rounded rect, floating over the plate with a slow scale-up", caption="none (typed text is the caption)",
                    notes=cfg.get("notes", ""))

    def src_to_out(self, shot, t_src):
        src0, span, tdur, _ = self._tm(shot)
        if not (src0 <= t_src <= src0 + span):
            return None
        return (t_src - src0) / (span / tdur)


# ---------------------------------------------------------------- rail_labels (s05)
@shot_type("rail_labels")
class RailLabels(ShotType):
    """Spec: source, t_in, cam, rows [{name, x, y, t}] (x,y normalised source point; t = pop time, output s), label_size, label_hold,
    overlays. Labels are right-aligned to the row end and track the camera."""

    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        t_in = cfg["t_in"]
        src = R.Source(spec.footage_path(cfg["source"]), t_in, t_in + shot.n / ctx.fps + 0.1)
        keys = resolve_cam_keys(cfg["cam"], shot.dur)
        rows = cfg["rows"]
        size, hold = cfg.get("label_size", 30), cfg.get("label_hold", 1.9)
        labels = {r["name"]: R.label_img(ctx, r["name"], size) for r in rows}
        overlays = build_overlays(ctx, cfg.get("overlays"))

        def f(i, t):
            im = src.frame(t_in + t)
            cam = R.cam_at(keys, t)
            out = R.frame_cam(ctx, im, *cam).convert("RGBA")
            for r in rows:
                t0 = r["t"]
                a = R.alpha_at(t, t0, t0 + hold, 0.2, 0.25)
                if a <= 0:
                    continue
                x, y = R.anchored(ctx, cam, im.size, r["x"], r["y"])
                slide = (1 - R.ease(min(1, (t - t0) / 0.35), "out")) * 18 * ctx.K
                img, cyo = labels[r["name"]]
                out = R.over(out, img, a, (int(x + slide - img.width), int(y - cyo)))   # right-aligned to the row's end
            return apply_overlays(overlays, out, t)

        try:
            R.run_shot(ctx, shot, f)
        finally:
            src.close()
        return dict(src=cfg.get("label", cfg["source"]), inout=f"{t_in:.2f}-{t_in + shot.n / ctx.fps:.2f} s (1x)",
                    move=f"eased push {keys[0][3]:.2f} -> {keys[-1][3]:.2f} of frame width",
                    caption="lower thirds " + " / ".join(r["name"] for r in rows), notes=cfg.get("notes", ""))

    def src_to_out(self, shot, t_src):
        return t_src - shot["t_in"]

    def captions(self, ctx, shot):
        hold = shot.get("label_hold", 1.9)
        res = [dict(text=r["name"], role="label", box=None, t0=r["t"], t1=r["t"] + hold) for r in shot["rows"]]
        from promo.overlays import caption_boxes
        return res + caption_boxes(ctx, shot)


# ---------------------------------------------------------------- tilt_card (s06)
def persp_coeffs(src_pts, dst_pts):
    A, B = [], []
    for (x, y), (u, v) in zip(dst_pts, src_pts):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        B += [u, v]
    return np.linalg.solve(np.array(A, float), np.array(B, float)).tolist()


def tilt_card(ctx, card, ang, scale):
    """Fake 3D rotateY(ang deg) of a card image (perspective), scaled; returns RGBA on a transparent canvas."""
    w, h = card.size
    W2, H2 = int(w * scale), int(h * scale)
    f = 2.2 * W2
    a = math.radians(ang)
    pts = []
    for x, y in [(-W2 / 2, -H2 / 2), (W2 / 2, -H2 / 2), (W2 / 2, H2 / 2), (-W2 / 2, H2 / 2)]:
        X = x * math.cos(a)
        Z = x * math.sin(a)
        s = f / (f + Z)
        pts.append((X * s, y * s))
    pad = 40 * ctx.K
    cw, ch = W2 + 2 * pad, H2 + 2 * pad
    dst = [(px + cw / 2, py + ch / 2) for px, py in pts]
    c = persp_coeffs([(0, 0), (w, 0), (w, h), (0, h)], dst)
    return card.transform((cw, ch), Image.PERSPECTIVE, c, Image.BICUBIC)


@shot_type("tilt_card")
class TiltCard(ShotType):
    """Spec: node (still), board (still), board_cam, board_blur 10, board_dim 0.45, scale [s0, s1], tilt [deg0, deg1], y 0.42, overlays."""

    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        K, dur = ctx.K, shot.n / ctx.fps
        s0, s1 = cfg["scale"]
        a0, a1 = cfg.get("tilt", [16, -2])
        bg = R.frame_cam(ctx, R.still(spec.footage_path(cfg["board"])), *cfg.get("board_cam", (0.5, 0.5, 1.0))).filter(ImageFilter.GaussianBlur(cfg.get("board_blur", 10) * K))
        bg = ImageEnhance.Brightness(bg).enhance(cfg.get("board_dim", 0.45)).convert("RGBA")
        card = R.still(spec.footage_path(cfg["node"])).convert("RGBA")
        card.putalpha(R.rounded_mask(card.width, card.height, int(card.height * 0.06)))
        overlays = build_overlays(ctx, cfg.get("overlays"))

        def f(i, t):
            p = R.ease(t / dur)
            ang = a0 * (1 - p) + a1 * p
            sc = (s0 + (s1 - s0) * p) * K
            c = R.soft_shadow(ctx, tilt_card(ctx, card, ang, sc), 22, 160, 16)
            out = bg.copy()
            out.alpha_composite(c, (int((ctx.OW - c.width) / 2), int(ctx.OH * cfg.get("y", 0.42) - c.height / 2)))
            return apply_overlays(overlays, out, t)

        R.run_shot(ctx, shot, f)
        return dict(src=cfg.get("label", cfg["node"]), inout="stills", move=f"3D tilt rotateY {a0}° -> {a1}° with scale {s0} -> {s1}",
                    caption=" / ".join(f"'{o.cfg['text']}'" for o in overlays if o.role == "caption") or "none", notes=cfg.get("notes", ""))


# ---------------------------------------------------------------- float_window (s15)
def float_window(ctx, img_crop, ww, wh, r=22):
    K = ctx.K
    c = img_crop.resize((ww, wh), Image.LANCZOS) if img_crop.size != (ww, wh) else img_crop
    c = c.convert("RGBA")
    c.putalpha(R.rounded_mask(ww, wh, r * K))
    b = Image.new("RGBA", (ww, wh), (0, 0, 0, 0))   # hairline border
    ImageDraw.Draw(b).rounded_rectangle([0, 0, ww - 1, wh - 1], radius=r * K, outline=(255, 255, 255, 40), width=max(1, K))
    c.alpha_composite(b)
    return R.soft_shadow_layer(ctx, c, 30, 170, 70)


@shot_type("float_window")
class FloatWindow(ShotType):
    """Spec: source, t_in, window [w, h], y, plate, camA, camB, dissolve [d0, d1], overlays.
    Camera A fades into camera B between d0 and d1 (both inside the same rounded window)."""

    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        K, t_in = ctx.K, cfg["t_in"]
        src = R.Source(spec.footage_path(cfg["source"]), t_in, t_in + shot.n / ctx.fps + 0.1)
        bg = R.plate(ctx, cfg.get("plate", "morning"))
        ww, wh = cfg["window"][0] * K, cfg["window"][1] * K
        ka, kb = cfg["camA"], cfg["camB"]
        d0, d1 = cfg["dissolve"]
        overlays = build_overlays(ctx, cfg.get("overlays"))

        def f(i, t):
            im = src.frame(t_in + t)
            a = R.frame_cam(ctx, im, *R.cam_at(ka, t), out=(ww, wh)) if t < d1 else None
            b = R.frame_cam(ctx, im, *R.cam_at(kb, t), out=(ww, wh)) if t >= d0 else None
            crop = a if b is None else (b if a is None else Image.blend(a, b, R.ease((t - d0) / (d1 - d0))))
            (lay, pad) = float_window(ctx, crop, ww, wh)
            out = bg.convert("RGBA")
            out.alpha_composite(lay, (int((ctx.OW - lay.width) / 2), int(cfg.get("y", 470) * K - lay.height / 2)))
            return apply_overlays(overlays, out, t)

        try:
            R.run_shot(ctx, shot, f)
        finally:
            src.close()
        return dict(src=cfg.get("label", cfg["source"]), inout=f"{t_in:.2f}-{t_in + shot.n / ctx.fps:.2f} s (1x)",
                    move=f"floating window ({cfg['window'][0]}x{cfg['window'][1]}) over the plate; camera A dissolves to B at {d0}-{d1} s",
                    caption=" / ".join(f"'{o.cfg['text']}'" for o in overlays if o.role == "caption") or "none", notes=cfg.get("notes", ""))

    def src_to_out(self, shot, t_src):
        return t_src - shot["t_in"]


# ---------------------------------------------------------------- tiles (s16)
@shot_type("tiles")
class Tiles(ShotType):
    """Spec: tiles [{source, t, box, label}], tile [560, 760], gap 40, bg [11,12,16], stagger 0.12, slide 0.55, push 0.06, offsets, overlays."""

    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        K, dur = ctx.K, shot.n / ctx.fps
        bg = Image.new("RGB", (ctx.OW, ctx.OH), tuple(cfg.get("bg", (11, 12, 16)))).convert("RGBA")
        tw, th = cfg.get("tile", [560, 760])
        tw, th, gap = tw * K, th * K, cfg.get("gap", 40) * K
        x0 = (ctx.OW - 3 * tw - 2 * gap) // 2
        y0 = (ctx.OH - th) // 2 - 10 * K
        stagger, slide, push = cfg.get("stagger", 0.12), cfg.get("slide", 0.55), cfg.get("push", 0.06)
        tiles = []
        for t_ in cfg["tiles"]:
            im = R.grab_frame(spec.footage_path(t_["source"]), t_["t"])
            xa, ya, xb, yb = t_["box"]
            SW, SH = im.size
            tiles.append(im.crop((int(xa * SW), int(ya * SH), int(xb * SW), int(yb * SH))))
        overlays = build_overlays(ctx, cfg.get("overlays"))

        def f(i, t):
            out = bg.copy()
            for k, c in enumerate(tiles):
                p = R.ease((t - stagger * k) / slide, "out")
                dx = (1 - p) * (-180 if k == 0 else (180 if k == 2 else 0)) * K
                dy = (1 - p) * (120 if k == 1 else 0) * K
                z = 1.0 + push * R.ease(t / dur)                       # slow push inside each tile
                cw, ch = c.size
                bw = cw / z
                bh = bw * th / tw
                if bh > ch / z:
                    bh = ch / z
                    bw = bh * tw / th
                cx, cy = cw / 2, ch / 2
                img = c.resize((tw, th), Image.LANCZOS, box=(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)).convert("RGBA")
                img.putalpha(Image.eval(R.rounded_mask(tw, th, 20 * K), lambda v: int(v * max(0, min(1, p * 1.4)))))
                out.alpha_composite(img, (int(x0 + k * (tw + gap) + dx), int(y0 + dy)))
            return apply_overlays(overlays, out, t)

        R.run_shot(ctx, shot, f)
        return dict(src="; ".join(t_.get("label", t_["source"]) for t_ in cfg["tiles"]), inout=f"{len(tiles)} stills",
                    move="3 equal rounded tiles slide in (staggered, ease-out) + slow push inside each", caption="none", notes=cfg.get("notes", ""))


# ---------------------------------------------------------------- clip_tx (s02, hero v2)
@shot_type("clip_tx")
class ClipTx(ShotType):
    """Same as the built-in `clip` (source, t_in/speed or segs, cam, overlays) but the shutter blur is a transition:
    `blur_tx: {at: [t0, t1], max: N}` ramps the blur from 1 frame to N source frames inside [t0, t1] (shot-local output s,
    t1 may be "end") and leaves the rest of the shot sharp. Hero v2: Zen's note "shot 2's blur becomes a transition < 0.4 s"."""

    def render(self, ctx, shot):
        from promo.shots.clip import segments
        spec, cfg = ctx.spec, shot.cfg
        total = shot.n / ctx.fps
        segs = segments(shot)
        srcs = [R.Source(spec.footage_path(s.get("source", cfg.get("source"))), s["t_in"], s["t_out"] + 0.1) for s in segs]
        bounds, acc = [], 0
        for s in segs:
            bounds.append((acc, acc + s["dur"]))
            acc += s["dur"]
        assert abs(acc - total) < 0.05, (shot.id, acc, total)
        keys = resolve_cam_keys(cfg["cam"], total)
        tx = cfg.get("blur_tx") or {}
        a0, a1 = tx.get("at", [total, total])
        a1 = total if a1 == "end" else float(a1)
        a0 = float(a0)
        nmax = int(tx.get("max", 1))
        assert a1 - a0 < 0.4 + 1e-6, "blur transition must stay under 0.4 s"
        overlays = build_overlays(ctx, cfg.get("overlays"))

        def blur_at(t):
            if nmax <= 1 or t < a0 or t > a1:
                return 1
            u = (t - a0) / max(a1 - a0, 1e-6)
            return max(1, int(round(1 + (nmax - 1) * R.ease(u))))

        def f(i, t):
            k = max(j for j, (a, b) in enumerate(bounds) if t >= a - 1e-6)
            a, b = bounds[k]
            s = segs[k]
            u = min(1.0, (t - a) / max(b - a, 1e-6))
            st = s["t_in"] + (s["t_out"] - s["t_in"]) * u
            im = srcs[k].frame(st, blur=blur_at(t))
            out = R.frame_cam(ctx, im, *R.cam_at(keys, t)).convert("RGBA")
            return apply_overlays(overlays, out, t)

        try:
            R.run_shot(ctx, shot, f)
        finally:
            for s_ in srcs:
                s_.close()
        ws = [k_[3] for k_ in keys]
        return dict(src=cfg.get("label", cfg.get("source", "")),
                    inout="; ".join(f"{s['t_in']:.2f}-{s['t_out']:.2f} s ({(s['t_out'] - s['t_in']) / s['dur']:.2f}x)" for s in segs),
                    move=f"eased camera {1 / max(ws):.2f}x -> {1 / min(ws):.2f}x; shutter blur only {a0:.2f}-{a1:.2f} s (1 -> {nmax} frames)",
                    caption=" / ".join(f"'{o.cfg['text']}'" for o in overlays if o.role == "caption") or "none",
                    notes=cfg.get("notes", ""))

    def src_to_out(self, shot, t_src):
        from promo.shots.clip import Clip
        return Clip.src_to_out(self, shot, t_src)
