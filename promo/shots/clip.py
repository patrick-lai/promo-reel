"""Generic `clip` shot: eased camera over source footage (port of ui_shot + s01/s02/s14b/s10 ...).

Spec keys:
    source: footage clip id (footage manifest)          (or per-seg `source`)
    t_in / speed:  one segment from t_in at `speed` x (source seconds per output second)
    segs: [{t_in, t_out, dur, [source], [cam]}]        segments played back to back (speed = src/out); seg `cam` keys are seg-local
    cam: [[t, cx, cy, w(, ease)], ...]                 keys in OUTPUT shot time; t may be "end" (= shot duration)
    blur: N                                            shutter blur: average of the last N source frames
    overlays: [...]                                    see promo.overlays
"""
from __future__ import annotations

from .. import render as R
from ..overlays import apply_overlays, build_overlays
from ..spec import resolve_cam_keys
from . import ShotType, shot_type


def segments(shot):
    """Normalised segment list [{t_in, t_out, dur, source?, cam?}] (legacy ui_shot defaults)."""
    total = shot.n / shot.fps
    cfg = shot.cfg
    if cfg.get("segs"):
        return [dict(s) for s in cfg["segs"]]
    return [dict(t_in=cfg.get("t_in", 0.0), t_out=cfg.get("t_in", 0.0) + total * cfg.get("speed", 1.0), dur=total)]


@shot_type("clip")
class Clip(ShotType):
    def render(self, ctx, shot):
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
        seg_keys = [resolve_cam_keys(s["cam"], s["dur"]) if s.get("cam") else None for s in segs]
        blur = cfg.get("blur", 1)
        overlays = build_overlays(ctx, cfg.get("overlays"))

        def f(i, t):
            k = max(j for j, (a, b) in enumerate(bounds) if t >= a - 1e-6)
            a, b = bounds[k]
            s = segs[k]
            u = min(1.0, (t - a) / max(b - a, 1e-6))
            st = s["t_in"] + (s["t_out"] - s["t_in"]) * u
            im = srcs[k].frame(st, blur=blur)
            cam = R.cam_at(seg_keys[k], t - a) if seg_keys[k] else R.cam_at(keys, t)
            out = R.frame_cam(ctx, im, *cam).convert("RGBA")
            return apply_overlays(overlays, out, t)

        try:
            R.run_shot(ctx, shot, f)
        finally:
            for s_ in srcs:
                s_.close()
        ws = [k_[3] for k_ in keys]
        return dict(src=cfg.get("label", cfg.get("source", "")),
                    inout="; ".join(f"{s['t_in']:.2f}-{s['t_out']:.2f} s ({(s['t_out'] - s['t_in']) / s['dur']:.2f}x)" for s in segs),
                    move=cfg.get("move", f"eased camera, box {max(ws):.2f} -> {min(ws):.2f} of frame width ({1 / max(ws):.1f}x -> {1 / min(ws):.1f}x)"),
                    caption=" / ".join(f"'{o.cfg['text']}'" for o in overlays if o.role == "caption") or "none",
                    notes=cfg.get("notes", ""))

    def src_to_out(self, shot, t_src):
        """Legacy src2out: walk the segments, mapping source time linearly to output time (1e-6 tolerance)."""
        acc = 0
        for s in segments(shot):
            if s["t_in"] - 1e-6 <= t_src <= s["t_out"] + 1e-6:
                return acc + (t_src - s["t_in"]) / (s["t_out"] - s["t_in"]) * s["dur"]
            acc += s["dur"]
        return None
