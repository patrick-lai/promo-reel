"""`screen` shot type (style preset cinematic-story): a REAL UI recording shown on the monitor of a GENERATED plate.

The plate is a generated clip (see promo/genvideo.py) that shows a large, flat, evenly lit, pale monitor with a locked or slowly
drifting camera (the actress at her desk, over the shoulder). The monitor's quadrilateral is tracked frame by frame
(promo/screentrack.py) and the UI recording, camera-cropped exactly like a `cinema` / `clip` shot, is perspective-warped into it,
so the app appears on her screen. Team rule (AGENTS.md section 0.2): the UI is only RESAMPLED (crop + perspective warp, 1-2 px
antialias at the quad edge). It is never graded, blurred, tinted, sharpened or retouched; everything else (bezel fill, light
spill, grade, grain) is drawn on the PLATE, outside the quad.

Spec keys (per shot):
    id / beats / type: screen
    plate: <footage clip id>    the generated plate (also: an image-less video path). Registered with `promo footage add ... --generated`
    plate_t_in: 0.0             where in the plate the shot starts, seconds
    plate_speed: 1.0            plate seconds per output second (plates are short: 0.5 slows a 6 s plate to 12 s; the monitor tracker follows)
    source / t_in / speed / segs / cam    the REAL UI clip, exactly like `clip` / `cinema` (cam keys in output time; slow eased camera
                                only, the gates measure it). The crop is warped into the quad, so cam [0.5, 0.5, w] frames the UI
    fade_in / fade_out: s       from / to black (also fades the UI, like every cinema shot)
    lower_copy: [...]           cinema's sparse serif copy (same keys); it must clear the monitor (gate copy-clear uses the quad union)
    ui: true|false              default true
    screen:                     all optional
        thr: 0.62               luminance threshold = thr x the frame's 99.5th-percentile luminance (adaptive; lower = grow the region)
        sat_max: 0.45           max saturation of a screen pixel (the lit screen is pale)
        inset: 0.004            shrink the quad by this fraction of the frame width before placing the UI (kills bright / blurry edge px)
        smooth: 0.6             temporal smoothing (5-frame median + zero-lag forward-backward EMA, alpha = 1 - smooth); 0 = raw
        quad: [[x, y] x4]       MANUAL quad TL, TR, BR, BL, normalised to the plate frame: no detection at all (locked plates). May lie
                                outside 0..1 for a clipped monitor, but the gate screen-quad still FAILs when it touches the frame
        aspect: 1.7778          physical aspect of the screen = of the UI crop (the quad is the 16:9 screen in perspective)
        glow: {alpha: 0.30, blur: 0.04, lift: 1.5}    light spill of the warped UI onto the surroundings (screen blend, OUTSIDE the quad);
                                false = off. blur = fraction of the frame width, lift = brightness lift of the spill
        bezel: true             plate pixels between the inset quad and a hair outside the detected edge turn bezel-dark (else the blank screen's
                                bright ring would show around the UI)
        grade: true | {grade: {...}, grain: {...}, bloom: {...}, vignette: {...}}    warm grade / grain on the PLATE only, never inside
                                the quad (true = the cinematic-story grade + grain; bloom / vignette off). Bloom is computed from the
                                plate's own blank screen, so prefer `glow`
        det_w: 960              detection width in px (normalised coordinates; the render uses the full output size)
        min_area / min_fill / border_px   detection and gate tolerances (see promo/screentrack.py)

Example:
    - {id: "05", beats: [52, 66], type: screen, plate: ots-night, plate_t_in: 0.0, plate_speed: 0.5,
       source: shot-04p-4k, t_in: 0.5, speed: 1.0, cam: [[0, 0.5, 0.5, 0.9], [end, 0.5, 0.5, 0.8]], fade_in: 0.4,
       screen: {thr: 0.62, inset: 0.004, smooth: 0.6, glow: {alpha: 0.30, blur: 0.04, lift: 1.5}, grade: true}}

Gates (promo/style_check.py, preset cinematic-story): `screen-quad` FAILs when the monitor is cut off by the frame border (a corner
within 2 px of it) in more than 10 % of the frames or the detection fails in more than 15 %; `screen-ui` FAILs on any `screen:` key that
could touch the UI pixels and on a rendered interior that differs from the resampled UI. `promo screen-quad <plate>` prints the
tracked quads and writes a debug PNG. Shots of this type count as UI shots in ui-hold / ui-protect / text-edge / long-hold (the
generic viewport is the quad's bounding box).
"""
from __future__ import annotations

import dataclasses
import json
import os

import numpy as np
from PIL import Image

from .. import grade as G
from .. import render as R
from .. import screentrack as ST
from ..spec import resolve_cam_keys
from . import ShotType, shot_type
from . import cinema as CN
from .clip import Clip, segments

SIDECAR = ".screen.json"
GRADE_KEYS = ("grade", "grain", "bloom", "vignette")
FORBIDDEN_GRADE_KEYS = ("inside", "ui", "all", "everything", "quad")        # a grade that could reach UI pixels


# ---------------------------------------------------------------- spec helpers (pure; shared with the gates)
def plate_ref(shot):
    return shot.get("plate")


def plate_file(spec, shot):
    return CN.plate_path(spec, plate_ref(shot))


def out_aspect(spec):
    try:
        return float(spec.OW) / float(spec.OH)
    except Exception:  # noqa: BLE001
        return 16 / 9


def track_of(spec, shot):
    """The shot's Track (cached) or None when the plate cannot be read."""
    try:
        f = plate_file(spec, shot)
        if not os.path.exists(f):
            return None
        return ST.track_shot(spec, shot, f, out_aspect(spec))
    except Exception:  # noqa: BLE001
        return None


def viewport(spec, shot, t=0.0):
    """Quad bounding box at shot-local t in 1920x1080 canvas units (the rect the generic text-edge / empty-frame gates sample)."""
    tr = track_of(spec, shot)
    if tr is None or not tr.usable:
        return [0.0, 0.0, 1920.0, 1080.0]
    return tr.bbox_canvas(int(round(t * shot.fps)))


def union_box(spec, shot):
    """Bounding box of the monitor over the whole shot (canvas units), or None."""
    tr = track_of(spec, shot)
    return tr.bbox_canvas() if tr is not None and tr.usable else None


def plate_look(sc):
    """Resolved look dict for the PLATE-only grade, or None."""
    g = sc.get("grade")
    if not g:
        return None
    base = dict(grade=dict(G.DEFAULT_LOOK["grade"]), grain=dict(G.DEFAULT_LOOK["grain"]), bloom=False, vignette=False)
    if g is True:
        return base
    over = {}
    flat = {}
    for k, v in dict(g).items():
        (over if k in GRADE_KEYS else flat)[k] = v
    if flat:
        over["grade"] = {**(over.get("grade") if isinstance(over.get("grade"), dict) else {}), **flat}
    out = dict(base)
    for k, v in over.items():
        if v is False:
            out[k] = False
        elif isinstance(v, dict):
            out[k] = {**(out[k] if isinstance(out.get(k), dict) else dict(G.DEFAULT_LOOK[k])), **v}
    return out


def audit_screen_keys(shot):
    """Problems (strings) with the shot's `screen:` block that could touch UI pixels: unknown keys, grade keys that reach inside the quad."""
    sc = shot.get("screen")
    bad = []
    if sc is None:
        return bad
    if not isinstance(sc, dict):
        return [f"shot {shot.id}: screen must be a mapping"]
    for k in sc:
        if k not in ST.ALLOWED_KEYS:
            bad.append(f"shot {shot.id}: screen.{k} is not a screen key (allowed: {', '.join(sorted(ST.ALLOWED_KEYS))}); UI pixels inside the quad are only resampled, never edited")
    g = sc.get("grade")
    if isinstance(g, dict):
        for k in g:
            if k in FORBIDDEN_GRADE_KEYS:
                bad.append(f"shot {shot.id}: screen.grade.{k} (the grade is for the plate only, never inside the quad)")
    return bad


def text_shot(shot):
    """The shot as a text-only cinema shot (no UI, no panel): used for lower_copy placement / drawing, so cinema's copy code is reused."""
    cfg = {k: v for k, v in shot.cfg.items() if k not in ("source", "segs", "screen", "plate", "cam", "panel")}
    cfg.update(type="cinema", ui=False, look={"backdrop": "none"})
    return dataclasses.replace(shot, cfg=cfg)


def copy_boxes(spec, shot):
    """[(text, box)] of the shot's lower_copy in canvas units (for the copy-clear gate)."""
    ts = text_shot(shot)
    look = CN.look_of(spec, ts)
    return [(CN.copy_text(spec, c), CN.copy_box(spec, ts, c, (1920, 1080), look=look)) for c in CN.copy_items(ts)]


def sidecar_path(spec, shot):
    return os.path.splitext(spec.seg_path(shot.id))[0] + SIDECAR


def read_sidecar(spec, shot):
    try:
        with open(sidecar_path(spec, shot)) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def ui_crop_size(track, ctx, shot, src_w):
    """Fixed (w, h) of the UI crop for the whole shot: about 1:1 with the quad (median of the longer top / bottom edge), never above the
    source crop's own pixel width, so the crop step never upscales."""
    W, H = ctx.OW, ctx.OH
    inset = float(ST.screen_cfg(shot)["inset"]) * W
    ws = []
    for q in track.quads:
        e = ST.edge_lengths(ST.inset_quad(q * np.array([W, H], float), inset))
        ws.append(max(e[0], e[2]))
    cw = float(np.median(ws))
    wmax = max(k[3] for k in CN.camera_keys(shot))
    cw = min(cw, max(64.0, src_w * wmax))
    cw = max(64, int(round(cw / 2)) * 2)
    asp = float(ST.screen_cfg(shot)["aspect"])
    ch = max(36, int(round(cw / asp / 2)) * 2)
    return cw, ch


# ---------------------------------------------------------------- the frame composer
class ScreenComposer:
    """compose(plate, ui_src, cam, t, i) -> RGB image (OW, OH). Pure given the images, so tests can run it without ffmpeg."""

    def __init__(self, ctx, shot, track, crop_size, spec=None):
        self.ctx, self.shot, self.track = ctx, shot, track
        self.spec = spec if spec is not None else ctx.spec
        self.W, self.H = ctx.OW, ctx.OH
        self.cfg = ST.screen_cfg(shot)
        self.crop = crop_size
        self.look = plate_look(self.cfg)
        self.text = CN.Composer(ctx, text_shot(shot), self.spec)
        self.dur = shot.dur
        self.fin, self.fout = float(shot.get("fade_in", 0) or 0), float(shot.get("fade_out", 0) or 0)
        self.residuals = []

    def quad_px(self, i):
        return self.track.quad(i) * np.array([self.W, self.H], float)

    def compose(self, plate, ui_src, cam, t, i, check=False):
        W, H = self.W, self.H
        pl = plate.convert("RGB")
        if pl.size != (W, H):
            pl = R.frame_cam(self.ctx, pl, 0.5, 0.5, 1.0)
        if self.look:
            pl = G.to_img(G.apply_look_arr(G.to_f(pl), self.look, i))
        ui = R.frame_cam(self.ctx, ui_src, *cam, out=self.crop)
        q = self.quad_px(i)
        res = ST.composite_screen(np.asarray(pl), ui, q, inset_px=float(self.cfg["inset"]) * W, glow=self.cfg["glow"],
                                  bezel=bool(self.cfg["bezel"]), return_parts=check)
        if check:
            res, warp, cov, reg = res
            self.residuals.append(ST.ui_residual(res, warp, cov, reg))
        out = Image.fromarray(res, "RGB")
        out = self.text._copy(out, t)
        b = CN.black_level(t, self.dur, self.fin, self.fout)
        if b > 0:
            out = G.to_img(G.to_f(out) * (1.0 - b))
        return out


# ---------------------------------------------------------------- the shot type
@shot_type("screen")
class Screen(ShotType):
    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        if not cfg.get("plate"):
            raise RuntimeError(f"shot {shot.id}: type screen needs plate: <footage clip id of the generated plate>")
        bad = audit_screen_keys(shot)
        if bad:
            raise RuntimeError("; ".join(bad))
        total = shot.n / ctx.fps
        pfile = plate_file(spec, shot)
        tr = ST.track_shot(spec, shot, pfile, ctx.OW / ctx.OH)
        if not tr.usable:
            raise RuntimeError(f"shot {shot.id}: could not find the monitor in {pfile} ({'; '.join(tr.why) or 'no detection'}); "
                               "tune screen.thr / screen.sat_max or give screen.quad (run `promo screen-quad` to see the tracker)")
        segs = segments(shot)
        srcs = [R.Source(spec.footage_path(s.get("source", cfg.get("source"))), s["t_in"], s["t_out"] + 0.1) for s in segs]
        bounds, acc = [], 0
        for s in segs:
            bounds.append((acc, acc + s["dur"]))
            acc += s["dur"]
        assert abs(acc - total) < 0.05, (shot.id, acc, total)
        keys = CN.camera_keys(shot)
        seg_keys = [resolve_cam_keys(s["cam"], s["dur"]) if s.get("cam") else None for s in segs]
        blur = cfg.get("blur", 1)
        pt0, pspeed = float(cfg.get("plate_t_in", 0.0)), float(cfg.get("plate_speed", 1.0))
        pw, ph, _, _ = R.probe(pfile)
        fit = abs((pw / ph) / (ctx.OW / ctx.OH) - 1) <= 0.01
        psrc = R.Source(pfile, pt0, pt0 + total * pspeed + 0.2, prescale=(ctx.OW, ctx.OH) if fit else None)
        comp = ScreenComposer(ctx, shot, tr, ui_crop_size(tr, ctx, shot, srcs[0].W))
        check_every = 6

        def f(i, t):
            plate = psrc.frame(pt0 + t * pspeed)
            if plate is None:
                raise RuntimeError(f"shot {shot.id}: no plate frames in {pfile}")
            k = max(j for j, (a, b) in enumerate(bounds) if t >= a - 1e-6)
            a, b = bounds[k]
            s = segs[k]
            u = min(1.0, (t - a) / max(b - a, 1e-6))
            im = srcs[k].frame(s["t_in"] + (s["t_out"] - s["t_in"]) * u, blur=blur)
            cam = R.cam_at(seg_keys[k], t - a) if seg_keys[k] else R.cam_at(keys, t)
            return comp.compose(plate, im, cam, t, i, check=(i % check_every == 0 or i == shot.n - 1))

        try:
            R.run_shot(ctx, shot, f)
        finally:
            psrc.close()
            for s_ in srcs:
                s_.close()
        try:
            with open(sidecar_path(spec, shot), "w") as fh:
                json.dump(dict(shot=shot.id, frames=shot.n, fps=shot.fps, plate=str(cfg.get("plate")), manual=tr.manual,
                               fail_frac=tr.fail_frac, touch_frac=tr.touch_frac, ui_residual_max=int(max(comp.residuals or [0])),
                               ui_residual_frames=len(comp.residuals), crop=list(comp.crop), quads=tr.quads.tolist()), fh)
        except OSError:
            pass
        ws = [k_[3] for k_ in keys]
        return dict(src=cfg.get("label", f"{cfg.get('source', '')} on plate {cfg.get('plate')}"),
                    inout="; ".join(f"{s['t_in']:.2f}-{s['t_out']:.2f} s ({(s['t_out'] - s['t_in']) / s['dur']:.2f}x)" for s in segs)
                    + f"; plate {pt0:.2f} s at {pspeed:g}x",
                    move=cfg.get("move", f"slow eased camera, box {max(ws):.2f} -> {min(ws):.2f} of frame width; UI warped into the tracked monitor"),
                    caption=" / ".join(f"'{CN.copy_text(spec, c)}'" for c in CN.copy_items(shot)) or "none",
                    notes=("UI on a generated plate's monitor: perspective-warped (resampled only), plate "
                           + ("graded" if comp.look else "ungraded") + f", monitor {'manual' if tr.manual else 'tracked'} "
                           f"(detection failed {100 * tr.fail_frac:.0f}%, cut off by the frame {100 * tr.touch_frac:.0f}%)")
                    + (f"; {cfg['notes']}" if cfg.get("notes") else ""))

    def src_to_out(self, shot, t_src):
        return Clip.src_to_out(self, shot, t_src)

    def captions(self, ctx, shot):
        return [dict(text=CN.copy_text(ctx.spec, it), role="label", box=None, t0=float(it.get("at", 0.0)),
                     t1=float(it.get("at", 0.0)) + float(it.get("dur", 3.0))) for it in CN.copy_items(shot)]
