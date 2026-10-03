"""Generic `card` shot: end card / title card over a blurred, darkened background frame (port of s17 without debubble).

Spec keys:
    bg: {source: clip, t: seconds} | {still: image}      background frame (footage clip ids)
    cam: [cx, cy, w]                                      framing of the background
    blur: 14   brightness: 0.30   plate_blend: 0.35       blur radius (1080 px), brightness factor, blend with dark_plate (0 = none)
    push: 0.03                                            slow push-in over the shot
    overlays: [...]                                       wordmark / line / pill ...
"""
from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter

from .. import render as R
from ..overlays import apply_overlays, build_overlays
from . import ShotType, shot_type


@shot_type("card")
class Card(ShotType):
    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        bg = cfg["bg"]
        if "still" in bg:
            im = R.still(spec.footage_path(bg["still"]))
        else:
            im = R.grab_frame(spec.footage_path(bg["source"]), bg["t"])
        base = R.frame_cam(ctx, im, *cfg.get("cam", (0.5, 0.5, 1.0))).filter(ImageFilter.GaussianBlur(cfg.get("blur", 14) * ctx.K))
        base = ImageEnhance.Brightness(base).enhance(cfg.get("brightness", 0.30))
        pb = cfg.get("plate_blend", 0.35)
        if pb:
            base = Image.blend(base, R.dark_plate(ctx), pb)
        base = base.convert("RGBA")
        overlays = build_overlays(ctx, cfg.get("overlays"))
        OW, OH, n, push = ctx.OW, ctx.OH, shot.n, cfg.get("push", 0.03)

        def f(i, t):
            z = 1.0 + push * R.ease(t / (n / ctx.fps))
            bw, bh = OW / z, OH / z
            out = base.resize((OW, OH), Image.LANCZOS, box=((OW - bw) / 2, (OH - bh) / 2, (OW + bw) / 2, (OH + bh) / 2)).convert("RGBA")
            return apply_overlays(overlays, out, t)

        R.run_shot(ctx, shot, f)
        return dict(src=cfg.get("label", str(bg)), inout="frame held",
                    move=f"background blurred ({cfg.get('blur', 14)} px) + darkened to {int(cfg.get('brightness', 0.30) * 100)}%; {push * 100:.0f}% slow push",
                    caption=" / ".join(f"'{o.cfg['text']}'" for o in overlays if o.role in ('text', 'pill', 'caption')) or "none",
                    notes=cfg.get("notes", ""))
