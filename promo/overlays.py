"""Overlay layers usable by any shot type: caption, pill, text, scrim, avatar.

Spec form (all optional keys have defaults):
    {type: caption, text: "...", style: dark|light, size: 32, cx/cy: (defaults to style.caption), t: [t0, t1],
     fade_in: 0.18, fade_out: 0.12}
    {type: pill,    text: "macOS alpha", style: light, cy: 690, size: 32, ...}       # free pill, not zone-checked
    {type: text,    text: "Product name", cy: 500, size: 132, weight: Bold, color: [255,255,255], shadow: true, ...}
    {type: scrim,   ellipse: [0.18, 0.22, 0.82, 0.70], fill: 120, blur: 120, color: [8, 10, 16]}  # always on unless `t` given
    {type: avatar,  source: <clip id>, t_in: 0.0, anchor: bottom-right, h: 0.26, margin: 0.03, radius: 0.16, label: "AI voice + face"}
`t` is shot-local output seconds (default [0, 99]); fades are `alpha_at` params. Role "caption" overlays are QA-checked
(safe zone + minimum hold); other roles are not.
"""
from __future__ import annotations

import weakref

from PIL import Image, ImageDraw, ImageFilter

from . import motion as M
from . import render as R


class Overlay:
    role = "overlay"

    def __init__(self, ctx, cfg, settle=False, delay=0.0):
        self.ctx, self.cfg = ctx, cfg
        self.t0, self.t1 = cfg.get("t", [0.0, 99.0])
        self.t0 += delay
        self.fin = cfg.get("fade_in", 0.18)
        self.fout = cfg.get("fade_out", 0.12)
        self.settle = settle
        self.layer = self.build()
        if settle:
            bb = self.layer.getbbox()
            self.bb = bb and (bb[0], max(bb[1] - 2, 0), bb[2], min(bb[3] + 2, self.layer.height))
            self.sprite = bb and self.layer.crop(self.bb)

    def build(self):
        raise NotImplementedError

    def alpha(self, t):
        if not self.settle:
            return R.alpha_at(t, self.t0, self.t1, self.fin, self.fout)
        if t < self.t0 or t > self.t1:
            return 0.0
        return min(M.smoothstep((t - self.t0) / self.fin) if self.fin else 1.0,
                   M.smoothstep((self.t1 - t) / self.fout) if self.fout else 1.0)

    def apply(self, out, t):
        a = self.alpha(t)
        if not self.settle or not self.bb or a <= 0:
            return R.over(out, self.layer, a)
        dy = M.OVERLAY_RISE * self.ctx.K * M.settle(t - self.t0)     # rise on entrance only: an exit just fades
        whole = int(dy)
        sprite = self.sprite if dy == whole else self.sprite.transform(self.sprite.size, Image.AFFINE, (1, 0, 0, 0, 1, whole - dy),
                                                                         Image.BICUBIC)
        return R.over(out, sprite, a, (self.bb[0], self.bb[1] + whole))

    def box(self):
        """Pill box in 1080-canvas units (1920x1080 space) or None."""
        return None


class Caption(Overlay):
    role = "caption"

    def _kw(self):
        c = self.cfg
        return dict(dark=c.get("style", "dark") == "dark", size=c.get("size"), cx=c.get("cx"), cy=c.get("cy"))

    def build(self):
        return R.pill_img(self.ctx, self.cfg["text"], **self._kw())

    def box(self):
        k = self._kw()
        ctx1 = self.ctx.with_scale(1)
        g = R.pill_geometry(ctx1, self.cfg["text"], k["size"], k["cx"], k["cy"])
        return [g["x0"], g["y0"], g["x0"] + g["w"], g["y0"] + g["h"]]


class Pill(Caption):
    role = "pill"


class Text(Overlay):
    role = "text"

    def build(self):
        c = self.cfg
        return R.text_img(self.ctx, c["text"], c["cy"], c["size"], weight=c.get("weight", "Bold"),
                          color=tuple(c.get("color", (255, 255, 255))), shadow=c.get("shadow", True))


class Scrim(Overlay):
    """Soft dark ellipse behind a title (port of the shot-01 scrim). Composited at full alpha unless `t` is given."""
    role = "scrim"

    def __init__(self, ctx, cfg, settle=False, delay=0.0):
        cfg = dict(cfg)
        self.always = "t" not in cfg
        super().__init__(ctx, cfg)

    def build(self):
        c, ctx = self.cfg, self.ctx
        e = c.get("ellipse", [0.18, 0.22, 0.82, 0.70])
        OW, OH = ctx.OW, ctx.OH
        scrim = Image.new("L", (OW, OH), 0)
        ImageDraw.Draw(scrim).ellipse([OW * e[0], OH * e[1], OW * e[2], OH * e[3]], fill=c.get("fill", 120))
        scrim = scrim.filter(ImageFilter.GaussianBlur(c.get("blur", 120) * ctx.K))
        dark = Image.new("RGBA", (OW, OH), tuple(c.get("color", (8, 10, 16))) + (255,))
        dark.putalpha(scrim)
        return dark

    def apply(self, out, t):
        if self.always:
            out = out.convert("RGBA") if out.mode != "RGBA" else out
            out.alpha_composite(self.layer)
            return out
        return super().apply(out, t)


class Avatar(Overlay):
    """A generated talking head of the person themself in a rounded corner card (team rule 1, own-likeness carve-out).
    The clip plays from its `t_in` at shot time 0, so consecutive shots pass on the same take by advancing t_in.
    `promo check` (genvideo.plate_gate) only lets a clip registered with `generated.likeness: own` and a consent note in here."""
    role = "avatar"

    def build(self):
        c, ctx = self.cfg, self.ctx
        side = int(round(ctx.OH * c.get("h", 0.26)))
        margin = int(round(ctx.OH * c.get("margin", 0.03)))
        vert, horiz = c.get("anchor", "bottom-right").split("-")
        self.pos = (ctx.OW - margin - side if horiz == "right" else margin, ctx.OH - margin - side if vert == "bottom" else margin)
        self.side, self.src = side, None
        self.mask = R.rounded_mask(side, side, int(side * c.get("radius", 0.16)))
        card = Image.new("RGBA", (side, side), (0, 0, 0, 255))
        card.putalpha(self.mask)
        self.shadow, self.pad = R.soft_shadow_layer(ctx, card, blur=18, alpha=150, pad=40)
        self.rim = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        ImageDraw.Draw(self.rim).rounded_rectangle([0, 0, side - 1, side - 1], int(side * c.get("radius", 0.16)),
                                                   outline=(255, 255, 255, 70), width=max(1, int(1.5 * ctx.K)))
        self.label = R.label_img(ctx, c["label"], size=c.get("label_size", 15))[0] if c.get("label") else None
        return None

    def _frame(self, t):
        c, t_in = self.cfg, float(self.cfg.get("t_in", 0.0))
        if self.src is None:
            self.src = R.Source(self.ctx.spec.footage_path(c["source"]), t_in, t_in + self.t1, prescale=(self.side, self.side))
            # an overlay has no close hook: stop the ffmpeg reader when the shot drops its overlays
            weakref.finalize(self, self.src.close)
        im = self.src.frame(t_in + t)
        if im is None:
            raise ValueError(f"avatar overlay: no frames in {c['source']} from {t_in:.2f} s")
        return im

    def apply(self, out, t):
        a = self.alpha(t)
        if a <= 0:
            return out
        side = self.side
        frame = self._frame(t).convert("RGBA")
        frame.putalpha(self.mask)
        frame.alpha_composite(self.rim)
        if self.label is not None:
            frame.alpha_composite(self.label, (int(side * 0.06), side - self.label.height - int(side * 0.05)))
        layer = R.canvas(self.ctx)
        layer.alpha_composite(self.shadow, (self.pos[0] - self.pad, self.pos[1] - self.pad))
        layer.alpha_composite(frame, self.pos)
        return R.over(out, layer, a)


TYPES = {"caption": Caption, "pill": Pill, "text": Text, "scrim": Scrim, "avatar": Avatar}


def build_overlays(ctx, cfgs, motion=None):
    """`motion` is the shot's resolved motion block (promo.motion.resolve); `overlay: settle` makes overlays that enter
    on the same frame arrive STAGGER s apart, in list order, each rising into place."""
    settle = (motion or {}).get("overlay") == "settle"
    out, entering = [], {}
    for c in cfgs or []:
        if c["type"] not in TYPES:
            raise ValueError(f"unknown overlay type {c['type']!r} (have {sorted(TYPES)})")
        delay = 0.0
        if settle and c["type"] != "scrim":
            t0 = round(c.get("t", [0.0])[0], 3)
            delay = M.STAGGER * entering.get(t0, 0)
            entering[t0] = entering.get(t0, 0) + 1
        out.append(TYPES[c["type"]](ctx, c, settle and c["type"] != "scrim", delay))
    return out


def apply_overlays(overlays, out, t):
    for o in overlays:
        out = o.apply(out, t)
    return out


def caption_boxes(ctx, shot):
    """QA records for every caption-role overlay in a shot's `overlays:` list."""
    res = []
    for c in shot.get("overlays", []) or []:
        if c["type"] == "caption":
            t0, t1 = c.get("t", [0.0, 99.0])
            k = dict(size=c.get("size"), cx=c.get("cx"), cy=c.get("cy"))
            g = R.pill_geometry(ctx.with_scale(1), c["text"], k["size"], k["cx"], k["cy"])
            res.append(dict(text=c["text"], role="caption", box=[g["x0"], g["y0"], g["x0"] + g["w"], g["y0"] + g["h"]],
                            t0=t0, t1=t1, min_hold=c.get("min_hold")))
    return res
