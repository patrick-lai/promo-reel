"""Overlay layers usable by any shot type: caption, pill, text, scrim.

Spec form (all optional keys have defaults):
    {type: caption, text: "...", style: dark|light, size: 32, cx/cy: (defaults to style.caption), t: [t0, t1],
     fade_in: 0.18, fade_out: 0.12}
    {type: pill,    text: "macOS alpha", style: light, cy: 690, size: 32, ...}       # free pill, not zone-checked
    {type: text,    text: "Product name", cy: 500, size: 132, weight: Bold, color: [255,255,255], shadow: true, ...}
    {type: scrim,   ellipse: [0.18, 0.22, 0.82, 0.70], fill: 120, blur: 120, color: [8, 10, 16]}  # always on unless `t` given
`t` is shot-local output seconds (default [0, 99]); fades are `alpha_at` params. Role "caption" overlays are QA-checked
(safe zone + minimum hold); other roles are not.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from . import render as R


class Overlay:
    role = "overlay"

    def __init__(self, ctx, cfg):
        self.ctx, self.cfg = ctx, cfg
        self.t0, self.t1 = cfg.get("t", [0.0, 99.0])
        self.fin = cfg.get("fade_in", 0.18)
        self.fout = cfg.get("fade_out", 0.12)
        self.layer = self.build()

    def build(self):
        raise NotImplementedError

    def alpha(self, t):
        return R.alpha_at(t, self.t0, self.t1, self.fin, self.fout)

    def apply(self, out, t):
        return R.over(out, self.layer, self.alpha(t))

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

    def __init__(self, ctx, cfg):
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


TYPES = {"caption": Caption, "pill": Pill, "text": Text, "scrim": Scrim}


def build_overlays(ctx, cfgs):
    out = []
    for c in cfgs or []:
        if c["type"] not in TYPES:
            raise ValueError(f"unknown overlay type {c['type']!r} (have {sorted(TYPES)})")
        out.append(TYPES[c["type"]](ctx, c))
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
