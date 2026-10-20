"""Previz: the cheap directing step between the script / storyboard and the first keyframe or render (docs/previz.md).

    promo previz build            compile `previz/scene.json` from the designed plan (or the picked storyboards) + write the Three.js viewer
    promo previz sync             regenerate the scene from its source; manual camera / panel edits (`overrides`) survive
    promo previz show [--json]    the blocked-out shots, the scene hash and whether a strip exists for it
    promo previz strip            export the contact strip PNG (headless Chrome + the Three.js viewer; PIL wireframes when Chrome is missing)
    promo previz open             the viewer (scrub with the arrow keys, [ ] jumps shots, O toggles ortho / perspective)
    promo previz cam|panel|type|dur|projection|reset ...   one nudge into `overrides`; `--strip` re-exports the strip in seconds
    promo previz apply            write the previz camera / panel nudges into the cinema shots (`promo designed apply`)
    promo previz animatic         one `shots/<id>.previz.mp4` per shot on the music grid (only changed shots re-render) + the joined animatic
    promo previz shots            a promo.yaml `shots:` skeleton (beats + cam) from the scene: timing and camera, nothing visual

Sources, first that applies: the designed plan, the picked storyboards, a hand-written scene.json, the promo.yaml shot list (`promo new`).

The scene is JSON, the picture is wireframes. A frame is a unit-height world: the camera is a box `(cx, cy, w)` exactly like a cinema `cam`
key (w = visible width as a fraction of the frame, smaller = pushed in), so a shot can be directed here and carried to `promo.yaml`. Panels
(`floating | device | fullscreen`) are quads on z = 0, plates sit behind them (`ui: false`, always), type is a box standing in for a card.
Orthographic mode is pure 2D; perspective gives floating panels real parallax. Nothing here draws product UI: a panel is a labelled box,
and supplied stills may be textured on it at low opacity (`--stills`).

The gate: a strip must exist for the *current scene hash* (the scene with its overrides applied) before keyframes, a designed render
above the quick look, or a final. `scene_hash` changes with any camera, panel, type, plate or timing edit, so a stale strip never passes.
"""
from __future__ import annotations

import argparse
import base64
import copy
import functools
import hashlib
import io
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from .spec import SpecError

SCHEMA = "promo-previz@1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(ROOT, "templates", "previz")

FOV_DEG = 40.0                       # vertical field of view of the perspective camera
TAN = math.tan(math.radians(FOV_DEG) / 2.0)
PLATE_Z = -1.0                       # plates sit one frame-height behind the panels
PLATE_OVERSCAN = {"ortho": 1.15, "persp": (1.0 / (2 * TAN) + 1.0) / (1.0 / (2 * TAN))}
MAX_PANEL_Z = 0.3
CAM_W = (0.15, 1.0)                  # visible width, fraction of the frame: pulling back past the frame would show the edge of the plate
PANEL_KINDS = ("floating", "device", "fullscreen")
CAMERA_MODES = ("locked", "push", "pullback", "parallax")
PROJECTIONS = ("ortho", "persp")
VOLATILE = ("notes", "why", "label")                 # words about a shot, not what is in it: they do not move the hash
DEFAULT_N = 12
TILE_H = 270
KEEP_STRIPS = 1

BG = (20, 22, 27)
COLORS = dict(plate=(86, 104, 140), floating=(88, 200, 230), device=(176, 140, 240), fullscreen=(110, 220, 140), type=(240, 184, 64),
              crop=(255, 255, 255), guide=(150, 156, 170))


class PrevizError(SpecError):
    pass


# ---------------------------------------------------------------- small helpers
def _round(o, nd=4):
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v, nd) for v in o]
    return o


def _canon(o):
    return json.dumps(_round(o), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(o):
    return hashlib.sha256(_canon(o).encode()).hexdigest()[:12]


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _write_json(path, doc):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")


def _read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- camera
def cam_keys(shot):
    """[(t, cx, cy, w, ease)] of a shot's camera, sorted, always at least one key."""
    ks = (shot.get("camera") or {}).get("keys") or [dict(t=0.0, cx=0.5, cy=0.5, w=1.0)]
    out = [(_num(k.get("t")), _num(k.get("cx"), 0.5), _num(k.get("cy"), 0.5), _num(k.get("w"), 1.0), k.get("ease") or "smooth") for k in ks]
    return sorted(out, key=lambda k: k[0])


def _ease(p, kind):
    p = min(max(p, 0.0), 1.0)
    return p if kind == "linear" else p * p * (3.0 - 2.0 * p)


def cam_at(shot, t):
    """(cx, cy, w) of the camera at shot-local time t."""
    ks = cam_keys(shot)
    if t <= ks[0][0]:
        return ks[0][1:4]
    for a, b in zip(ks, ks[1:]):
        if t <= b[0]:
            p = _ease((t - a[0]) / max(b[0] - a[0], 1e-9), b[4])
            return tuple(a[i] + (b[i] - a[i]) * p for i in (1, 2, 3))
    return ks[-1][1:4]


def camera_mode(keys):
    """locked | push | pullback | parallax from camera keys (the label a human reads in `show`)."""
    if len(keys) < 2:
        return "locked"
    a, b = keys[0], keys[-1]
    dw = _num(b.get("w"), 1.0) - _num(a.get("w"), 1.0)
    dc = math.hypot(_num(b.get("cx"), .5) - _num(a.get("cx"), .5), _num(b.get("cy"), .5) - _num(a.get("cy"), .5))
    if abs(dw) < 1e-4 and dc < 1e-4:
        return "locked"
    if dc > 0.01 and abs(dw) < 0.02:
        return "parallax"
    return "push" if dw < 0 else "pullback"


def camera_preset(mode, dur, amount=0.06, cx=0.5, cy=0.5, w=None, drift=0.04, ease="smooth"):
    """Camera keys for a named move: locked | push (in by `amount`) | pullback | parallax (a slow lateral drift, wants perspective)."""
    if mode not in CAMERA_MODES:
        raise PrevizError(f"camera mode must be one of {', '.join(CAMERA_MODES)}")
    dur = max(float(dur), 1e-3)
    if mode == "locked":
        return [dict(t=0.0, cx=cx, cy=cy, w=1.0 if w is None else w)]
    if mode == "push":
        w0 = 1.0 if w is None else w
        return [dict(t=0.0, cx=cx, cy=cy, w=w0), dict(t=dur, cx=cx, cy=cy, w=round(w0 - amount, 4), ease=ease)]
    if mode == "pullback":
        w1 = 1.0 if w is None else w
        return [dict(t=0.0, cx=cx, cy=cy, w=round(w1 - amount, 4)), dict(t=dur, cx=cx, cy=cy, w=w1, ease=ease)]
    w0 = 0.92 if w is None else w
    return [dict(t=0.0, cx=round(cx - drift, 4), cy=cy, w=w0), dict(t=dur, cx=round(cx + drift, 4), cy=cy, w=w0, ease=ease)]


def _dist(w):
    return w / (2.0 * TAN)


def project(cam, proj, cx, cy, w, h, z=0.0):
    """Normalised screen rect (u0, v0, u1, v1) of a quad whose centre is (cx, cy) of the frame (0..1, y down) and whose size is
    (w, h) of the frame. `cam` = (cx, cy, w). One formula for both projections; perspective scales a plane at depth z by D / (D - z)."""
    ccx, ccy, cw = cam
    k = 1.0 / cw
    if proj == "persp" and z:
        d = _dist(cw)
        k *= d / (d - z)
    u, v = 0.5 + (cx - ccx) * k, 0.5 + (cy - ccy) * k
    return (u - w * k / 2.0, v - h * k / 2.0, u + w * k / 2.0, v + h * k / 2.0)


def type_size(item, aspect):
    """(w, h) of a type placeholder in frame fractions: the box a card of this size and length occupies (not its final typography)."""
    h = max(_num(item.get("size_pct"), 6.0), 1.0) / 100.0 * 1.25
    chars = max(len(str(item.get("text") or "")), 4)
    return min(chars * h * 0.5 / aspect, 0.92), h


def aspect_of(scene):
    a = scene["frame"]["aspect"]
    return float(a[0]) / float(a[1])


def panel_hw(panel, aspect):
    """Panel height as a fraction of the frame height from its width (fraction of frame width) and content aspect."""
    if panel.get("kind") == "fullscreen":
        return 1.0
    return _num(panel.get("w"), 0.5) * aspect / max(_num(panel.get("aspect"), aspect), 0.05)


def layout(scene, t):
    """What a frame at film time t looks like: (shot, local t, proj, cam, [item]) with items in draw order, each
    {kind, id, label, rect}, rect normalised to the frame. The PIL strip draws this; viewer.js does the same maths in Three.js."""
    e = scene if scene.get("_effective") else effective(scene)
    shots = e["shots"]
    shot = next((s for s in shots if s["t0"] <= t < s["t0"] + s["dur"]), shots[-1])
    return layout_shot(e, shot, min(max(t - shot["t0"], 0.0), shot["dur"]))


def layout_shot(e, shot, lt):
    """layout() of one shot at shot-local time lt (the animatic renders each shot on its own, so a gap never borrows the last shot)."""
    proj = (shot.get("camera") or {}).get("projection") or e["projection"]
    cam = cam_at(shot, lt)
    A = aspect_of(e)
    items = []
    plate = shot.get("plate")
    if plate:
        over = PLATE_OVERSCAN[proj]
        items.append(dict(kind="plate", id=plate.get("id") or "plate", label=f"{plate.get('id') or 'plate'}  ui:false",
                          rect=project(cam, proj, 0.5, 0.5, over, over, PLATE_Z if proj == "persp" else 0.0)))
    panels = sorted(shot.get("panels") or [], key=lambda p: _num(p.get("z")))
    for p in panels:
        if p.get("kind") == "fullscreen":
            w = h = 1.0
        else:
            w, h = _num(p.get("w"), 0.5), panel_hw(p, A)
        rect = project(cam, proj, _num(p.get("cx"), 0.5), _num(p.get("cy"), 0.5), w, h, _num(p.get("z")))
        items.append(dict(kind=p.get("kind", "floating"), id=p["id"], label=f"{p['id']}  {p.get('kind', 'floating')}" + (f"  {p['source']}" if p.get("source") else ""), rect=rect))
        if p.get("crop"):
            ccx, ccy, cw = cam_at(dict(camera=dict(keys=p["crop"])), lt)
            if cw < 0.995 or abs(ccx - 0.5) > 1e-3 or abs(ccy - 0.5) > 1e-3:
                pw, ph = rect[2] - rect[0], rect[3] - rect[1]
                items.append(dict(kind="crop", id=p["id"] + "/crop", label=f"crop {cw:.2f}",
                                  rect=(rect[0] + (ccx - cw / 2) * pw, rect[1] + (ccy - cw / 2) * ph, rect[0] + (ccx + cw / 2) * pw, rect[1] + (ccy + cw / 2) * ph)))
    for c in shot.get("type") or []:
        if not (_num(c.get("at")) <= lt < _num(c.get("at")) + _num(c.get("dur"), 2.0) or c.get("always")):
            continue
        w, h = type_size(c, A)
        items.append(dict(kind="type", id=c["id"], label=str(c.get("text") or "(needs copy)"),
                          rect=project(cam, proj, _num(c.get("cx"), 0.5), _num(c.get("cy"), 0.5), w, h, 0.02)))
    return shot, lt, proj, cam, items


# ---------------------------------------------------------------- scene model: generated shots + overrides
def _merge_list(items, patch, key="id"):
    """items = [{id, ...}], patch = {id: {...} | None}: merge by id, None removes, an unknown id adds."""
    out = [copy.deepcopy(i) for i in items]
    for pid, ov in (patch or {}).items():
        at = next((n for n, i in enumerate(out) if i.get(key) == pid), None)
        if ov is None:
            if at is not None:
                del out[at]
        elif at is None:
            out.append(dict({key: pid}, **copy.deepcopy(ov)))
        else:
            out[at].update(copy.deepcopy(ov))
    return out


def _apply_shot(shot, ov):
    s = copy.deepcopy(shot)
    for k, v in (ov or {}).items():
        if k == "panels":
            s["panels"] = _merge_list(s.get("panels") or [], v)
        elif k == "type":
            s["type"] = _merge_list(s.get("type") or [], v)
        elif k == "camera":
            cam = dict(s.get("camera") or {})
            cam.update(copy.deepcopy(v))
            if "keys" in v:
                cam["mode"] = camera_mode(cam["keys"])
            s["camera"] = cam
        elif k == "plate":
            s["plate"] = None if v is None else dict(s.get("plate") or {}, **v)
        else:
            s[k] = copy.deepcopy(v)
    if shot.get("dur") and _num(s.get("dur")) != _num(shot["dur"]) and "keys" not in ((ov or {}).get("camera") or {}):
        k = _num(s["dur"]) / _num(shot["dur"])      # a retimed shot keeps its move, played over the new length
        s["camera"] = dict(s.get("camera") or {}, keys=[dict(kk, t=round(_num(kk.get("t")) * k, 4)) for kk in (s.get("camera") or {}).get("keys") or []])
    return s


def _anchor_types(shot, A):
    """Re-seat `anchor: panel-bl` type under its panel's bottom-left corner after panel edits (the tag is grouped with the panel)."""
    pb = next((p for p in shot.get("panels") or [] if p.get("kind") != "fullscreen"), None)
    for c in shot.get("type") or []:
        if c.get("anchor") == "panel-bl" and pb:
            tw, th = type_size(c, A)
            c["cx"] = round(_num(pb.get("cx"), 0.5) - _num(pb.get("w"), 0.5) / 2 + tw / 2, 4)
            c["cy"] = round(_num(pb.get("cy"), 0.5) + panel_hw(pb, A) / 2 + _num(c.get("gap"), 0.012) + th / 2, 4)


def effective(scene):
    """The scene as it plays: generated shots with `overrides` applied, durations cascaded into start times. Does not mutate `scene`."""
    ov = scene.get("overrides") or {}
    sc = ov.get("scene") or {}
    shots, shift = [], 0.0
    for s in scene["shots"]:
        e = _apply_shot(s, (ov.get("shots") or {}).get(s["id"]))
        _anchor_types(e, aspect_of(scene))
        e["t0"] = round(_num(s["t0"]) + shift, 4)
        shift += _num(e["dur"]) - _num(s["dur"])
        shots.append(e)
    out = dict(scene, shots=shots, projection=sc.get("projection") or scene.get("projection") or "ortho", _effective=True)
    out["duration_s"] = round(max((s["t0"] + s["dur"] for s in shots), default=0.0), 4)
    return out


def scene_hash(scene):
    """12 hex chars over what a strip shows: frame, projection, and every shot's timing, camera, plate, panels and type."""
    e = scene if scene.get("_effective") else effective(scene)
    core = dict(frame=e["frame"], projection=e["projection"],
                shots=[{k: v for k, v in s.items() if k not in VOLATILE} for s in e["shots"]])
    for s in core["shots"]:
        for sub in ("panels", "type"):
            s[sub] = [{k: v for k, v in x.items() if k not in VOLATILE} for x in s.get(sub) or []]
        if s.get("camera"):
            s["camera"] = {k: v for k, v in s["camera"].items() if k != "mode"}
    return _hash(core)


def generated_hash(scene):
    return _hash(dict(frame=scene["frame"], projection=scene.get("projection"), shots=[{k: v for k, v in s.items() if k not in VOLATILE} for s in scene["shots"]]))


def problems(scene):
    """(errors, warnings) for a scene. Errors make `build` refuse; warnings are directing notes."""
    err, warn = [], []
    if scene.get("schema") != SCHEMA:
        err.append(f"schema must be {SCHEMA}")
    if not scene.get("shots"):
        return err + ["scene has no shots"], warn
    e = effective(scene)
    A = aspect_of(e)
    lim = scene.get("limits") or {}
    seen = set()
    for s in e["shots"]:
        sid = s.get("id", "?")
        if sid in seen:
            err.append(f"shot {sid}: duplicate id")
        seen.add(sid)
        if not _num(s.get("dur")) > 0:
            err.append(f"shot {sid}: dur must be > 0")
        ks = cam_keys(s)
        if ks[-1][0] > _num(s["dur"]) + 1e-6:
            err.append(f"shot {sid}: camera key at {ks[-1][0]:g}s is after the shot ends ({_num(s['dur']):g}s)")
        for k in ks:
            if not CAM_W[0] - 1e-9 <= k[3] <= CAM_W[1] + 1e-9:
                err.append(f"shot {sid}: camera w {k[3]:g} outside {CAM_W[0]}-{CAM_W[1]} (w > 1 shows past the plate, a push below {CAM_W[0]} is a different shot)")
        if (s.get("camera") or {}).get("projection") not in (None,) + PROJECTIONS:
            err.append(f"shot {sid}: camera.projection must be ortho or persp")
        if s.get("plate") and s["plate"].get("ui"):
            err.append(f"shot {sid}: a plate is `ui: false` always (AGENTS.md rule 1): product UI goes in a panel")
        for p in s.get("panels") or []:
            pid = p.get("id", "?")
            if p.get("kind") not in PANEL_KINDS:
                err.append(f"shot {sid} panel {pid}: kind must be one of {', '.join(PANEL_KINDS)}")
            if p.get("drawn") or p.get("generated") or p.get("ui_draw"):
                err.append(f"shot {sid} panel {pid}: previz never draws or generates product UI (wire boxes and supplied stills only)")
            if p.get("source") and p["source"] not in (scene.get("stills") or {}):
                err.append(f"shot {sid} panel {pid}: source {p['source']!r} is not a supplied still (see scene.stills)")
            if _num(p.get("z")) > MAX_PANEL_Z:
                err.append(f"shot {sid} panel {pid}: z {p.get('z')} > {MAX_PANEL_Z} (the camera would be inside the panel)")
            if not 0.03 <= _num(p.get("w"), 0.5) <= 1.0 + 1e-9:
                err.append(f"shot {sid} panel {pid}: w {p.get('w')} outside 0.03-1.0")
            hh = panel_hw(p, A)
            x0, y0 = _num(p.get("cx"), 0.5) - _num(p.get("w"), 0.5) / 2, _num(p.get("cy"), 0.5) - hh / 2
            if p.get("kind") != "fullscreen" and (x0 < -0.02 or y0 < -0.02 or x0 + _num(p.get("w"), 0.5) > 1.02 or y0 + hh > 1.02):
                warn.append(f"shot {sid} panel {pid}: leaves the frame (box {x0:.2f},{y0:.2f} to {x0 + _num(p.get('w'), 0.5):.2f},{y0 + hh:.2f})")
        panels = [p for p in s.get("panels") or [] if p.get("kind") != "fullscreen"]
        for c in s.get("type") or []:
            w, h = type_size(c, A)
            cx, cy = _num(c.get("cx"), 0.5), _num(c.get("cy"), 0.5)
            tb = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            for p in panels:
                ph = panel_hw(p, A)
                pb = (_num(p.get("cx"), .5) - _num(p.get("w"), .5) / 2, _num(p.get("cy"), .5) - ph / 2, _num(p.get("cx"), .5) + _num(p.get("w"), .5) / 2, _num(p.get("cy"), .5) + ph / 2)
                if tb[0] < pb[2] and pb[0] < tb[2] and tb[1] < pb[3] and pb[1] < tb[3]:
                    warn.append(f"shot {sid}: type {c.get('id')} sits over panel {p['id']} (designed-clear FAILs type on app UI: move it to the margin)")
            if tb[0] < 0 or tb[2] > 1 or tb[1] < 0 or tb[3] > 1:
                warn.append(f"shot {sid}: type {c.get('id')} leaves the frame")
        if lim:
            pan = zoom = 0.0
            for a, b in zip(ks, ks[1:]):
                dt = max(b[0] - a[0], 1e-6)
                pan, zoom = max(pan, math.hypot(b[1] - a[1], b[2] - a[2]) / dt), max(zoom, abs(b[3] - a[3]) / dt)
            if pan > lim.get("pan_per_s", 9) + 1e-9 or zoom > lim.get("zoom_per_s", 9) + 1e-9:
                warn.append(f"shot {sid}: camera moves {pan:.3f} pan/s, {zoom:.3f} zoom/s; the {lim.get('dialect', 'dialect')} limit is {lim.get('pan_per_s'):g} / {lim.get('zoom_per_s'):g} "
                            "(`designed-camera` will " + ("FAIL" if lim.get("strict") else "WARN") + ")")
    ids = {s["id"] for s in scene["shots"]}
    for sid in (scene.get("overrides") or {}).get("shots") or {}:
        if sid not in ids:
            warn.append(f"override for shot {sid} matches no shot of the source (orphaned: kept, ignored until the shot exists again)")
    return err, warn


# ---------------------------------------------------------------- sources: the designed plan, the storyboard
def _yaml_plan(pd):
    path = os.path.join(pd, "promo.yaml")
    if not os.path.isfile(path):
        return {}, {}
    import yaml

    from . import gapfill
    text = open(path).read()
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        raw = {}
    return raw, gapfill.existing_plan(text)


def _frame_of(raw):
    from . import styles
    try:
        w, h = styles.frame_size(styles.resolve(raw), 1)
    except Exception:  # noqa: BLE001
        w, h = 1920, 1080
    fps = int(((raw or {}).get("output") or {}).get("fps") or 30)
    return dict(aspect=[w, h], fps=fps)


def _rel(path, pd):
    try:
        return os.path.relpath(path, pd)
    except ValueError:
        return path


def from_designed(raw, plan, pd):
    """Scene from `plan.designed`: the camera, panel and type geometry come from the same `compile_shots` the preview renders, so previz
    shows what `promo designed apply` will build, then the agent directs it."""
    from . import designed as D
    des = plan["designed"]
    dn = (des.get("dialect") or {}).get("name") or "kinetic"
    frame = _frame_of(raw)
    A = frame["aspect"][0] / frame["aspect"][1]
    cin = {s["id"]: s for s in D.compile_shots(des)}
    stills = {s["id"]: dict(path=s.get("path"), kind=s.get("kind"), w=s.get("width"), h=s.get("height"), exists=bool(s.get("exists")))
              for s in des.get("stills") or [] if s.get("id")}
    cards = {c["id"]: c for c in des.get("kinetic_cards") or []}
    shots = []
    for r in des["shots"]:
        c = cin[r["id"]]
        dur = round(_num(r["seconds"]), 4)
        keys = []
        for k in c.get("cam") or [[0, 0.5, 0.5, 1.0]]:
            t = dur if k[0] == "end" else _num(k[0])
            key = dict(t=round(t, 4), cx=_num(k[1]), cy=_num(k[2]), w=_num(k[3]))
            if len(k) > 4:
                key["ease"] = str(k[4])
            keys.append(key)
        panels, fr = [], r["framing"]
        pnl = ((c.get("look") or {}).get("panel")) or {}
        if fr == "fullscreen":
            panels.append(dict(id="ui-1", kind="fullscreen", source=r.get("ui_source"), cx=0.5, cy=0.5, w=1.0, aspect=round(A, 4), z=0.0))
        elif fr in ("floating", "device") and pnl:
            asp = pnl.get("aspect") or A
            panel = dict(id="ui-1", kind=fr, source=r.get("ui_source"), cx=0.5, cy=_num(pnl.get("cy"), 0.42), w=_num(pnl.get("w"), 0.55), aspect=round(float(asp), 4),
                         z=0.0, label=f"{r.get('ui_source') or 'supplied still'} (real UI, never drawn)")
            fx = (r.get("motion") or {}).get("focus")
            if fx:
                panel["focus"] = fx
            panels.append(panel)
        plate = None
        if r.get("plate") or fr == "plate":
            plate = dict(id=r.get("plate") or "plate", ui=False)
        boxed = [p for p in panels if p["kind"] != "fullscreen"]
        if boxed:
            # cinema's `cam` on a panel shot crops the SOURCE inside a fixed panel; it is not a camera over the frame. Keep it as the panel's
            # crop and start the world camera locked: previz makes a still-frame composition visible, and moving it is the director's call.
            boxed[0]["crop"] = keys
            keys = [dict(t=0.0, cx=0.5, cy=0.5, w=1.0)]
        kin = []
        items = iter(c.get("kinetic_copy") or [])
        for cid in r.get("cards") or []:
            cd = cards.get(cid) or {}
            item = next(items) if cd.get("text") else dict(at=cd.get("at"), dur=cd.get("dur"), size_pct=cd.get("size_pct"))   # a card still waiting for the person's words
            ty = dict(id=cid, text=item.get("text") or "", at=_num(item.get("at")), dur=_num(item.get("dur"), 2.0), size_pct=_num(item.get("size_pct"), 6.0),
                      cx=_num(item.get("cx"), 0.5), anim=item.get("anim") or cd.get("anim"))
            if cd.get("brackets") or item.get("brackets"):
                ty["brackets"] = True
            if item.get("anchor") == "panel-bl" and panels and panels[0]["kind"] != "fullscreen":
                pb = panels[0]                    # grouped with the panel: under its bottom-left corner, as cinema draws it
                tw, th = type_size(ty, A)
                ty.update(anchor="panel-bl", gap=_num(item.get("gap"), 0.012), cx=round(pb["cx"] - pb["w"] / 2 + tw / 2, 4),
                          cy=round(pb["cy"] + panel_hw(pb, A) / 2 + _num(item.get("gap"), 0.012) + th / 2, 4))
            elif item.get("cy") is not None:
                ty["cy"] = _num(item["cy"])
            elif panels and panels[0]["kind"] != "fullscreen":
                pb = panels[0]
                ty["cy"] = round(min((pb["cy"] + panel_hw(pb, A) / 2 + 1.0) / 2.0, 0.93), 4)
            else:
                ty["cy"] = 0.5 if fr == "plate" else 0.9
            kin.append(ty)
        shots.append(dict(id=r["id"], beat=r["beat"], t0=round(_num(r["t0"]), 4), dur=dur, framing=fr, ui=fr != "plate",
                          camera=dict(mode=camera_mode(keys), keys=keys), plate=plate, panels=panels, type=kin, notes=r.get("why", "")))
    prof = D.profile(dn)["camera"]["max_drift"]
    return dict(schema=SCHEMA, source=dict(kind="designed", ref="promo.yaml plan.designed", dialect=dn), frame=frame,
                projection="persp" if dn == "ethereal" else "ortho", shots=shots, stills=stills,
                limits=dict(dialect=dn, strict=dn == "ethereal", pan_per_s=prof["pan_per_s"], zoom_per_s=prof["zoom_per_s"]))


CAMERA_WORDS = (("parallax", ("parallax", "dolly", "drift", "pan", "track", "slide")), ("pullback", ("pull back", "pull-back", "pullback", "pull out", "zoom out", "reveal")),
                ("push", ("push", "zoom in", "zoom-in", "closer", "move in", "punch")))


def _words_mode(text):
    t = (text or "").lower()
    for mode, words in CAMERA_WORDS:
        if any(w in t for w in words):
            return mode
    return "locked"


def from_storyboard(story, board, bdir, pd):
    """Scene from one storyboard: a shot per scene (its `t`), the scene's `camera` words become a camera move, the caption a type box.
    A real scene gets one floating panel (its start frame, a real screen, shown only with `--stills`), a generated one a plate."""
    raw, plan = _yaml_plan(pd)
    frame = _frame_of(raw)
    if board.get("aspect") and re.fullmatch(r"\d+(\.\d+)?:\d+(\.\d+)?", str(board["aspect"])) and not raw:
        a, b = (float(x) for x in str(board["aspect"]).split(":"))
        frame = dict(aspect=[round(a * 1000), round(b * 1000)], fps=30)
    A = frame["aspect"][0] / frame["aspect"][1]
    stills, shots = {}, []
    for s in board.get("scenes") or []:
        t0, t1 = _num(s["t"][0]), _num(s["t"][1])
        dur = round(t1 - t0, 4)
        mode = _words_mode(s.get("camera"))
        keys = camera_preset(mode, dur)
        real = s.get("source", "real") == "real"
        panels, plate = [], None
        img = (s.get("start") or {}).get("image")
        sid = f"frame-{s['id']}"
        if img:
            stills[sid] = dict(path=os.path.join(bdir, img), kind="image", w=None, h=None, exists=os.path.isfile(os.path.join(bdir, img)))
        if real:
            panels.append(dict(id="ui-1", kind="floating", source=sid if img else None, cx=0.5, cy=0.44, w=0.62, aspect=round(A, 4), z=0.0,
                               label="real screen of the product (storyboard start frame)"))
        plate = dict(id=f"plate-{s['id']}", ui=False)
        kin = []
        if s.get("caption"):
            kin.append(dict(id="c1", text=s["caption"], at=0.0, dur=dur, size_pct=6.0, cx=0.5, cy=0.9 if real else 0.5))
        shots.append(dict(id=str(s["id"]), beat=s.get("beat", ""), t0=round(t0, 4), dur=dur, framing="floating" if real else "plate", ui=real,
                          camera=dict(mode=camera_mode(keys), keys=keys), plate=plate, panels=panels, type=kin, notes=s.get("action", "")))
    return dict(schema=SCHEMA, source=dict(kind="storyboard", ref=f"flow/boards/{story}/board.json", story=story), frame=frame, projection="ortho",
                shots=shots, stills=stills, limits={})


# ---------------------------------------------------------------- per-style defaults: animatic required? 2D or 3D?
# The film-directing styles direct in the animatic before anything is generated; the rest may opt in. 3D (perspective) only where depth is
# the look: cinematic-story's contained panel over its blurred backdrop. Not in styles.PRESETS: those are locked per version.
PREVIZ_DEFAULTS = {"horizon": dict(animatic=True, projection="ortho"), "cinematic-story": dict(animatic=True, projection="persp"),
                   "anime-mv": dict(animatic=True, projection="ortho")}
OPT_IN = dict(animatic=False, projection="ortho")
SETTING_KEYS = ("animatic", "projection")


def _preset_of(pd):
    raw, _ = _yaml_plan(pd)
    name = ((raw or {}).get("style") or {}).get("preset")
    if name:
        from . import styles
        return styles.split_preset(str(name))[0]
    label = ((_read_json(os.path.join(pd, "flow", "flow.json"), {}) or {}).get("discover") or {}).get("style")
    if label:
        from . import flow as F
        return F.style_preset(label)
    return None


def settings(pd):
    """{preset, animatic, projection}: the style's default, then promo.yaml `previz:`, then previz/settings.json (`animatic --require`)."""
    preset = _preset_of(pd)
    out = dict(PREVIZ_DEFAULTS.get(preset, OPT_IN), preset=preset)
    raw, _ = _yaml_plan(pd)
    own = (raw or {}).get("previz") or {}
    out.update({k: own[k] for k in SETTING_KEYS if k in own})
    out.update({k: v for k, v in (_read_json(os.path.join(pd, "previz", "settings.json"), {}) or {}).items() if k in SETTING_KEYS})
    if out["projection"] not in PROJECTIONS:
        raise PrevizError(f"previz projection must be ortho or persp, not {out['projection']!r}")
    return out


# ---------------------------------------------------------------- source: a promo.yaml shot list (`promo new`, hand-written specs)
def _has_spec_shots(pd):
    raw, _ = _yaml_plan(pd)
    return bool((raw or {}).get("shots"))


def _frac(v, size, default):
    """A spec position: pixels at scale 1 when > 1, else already a fraction of the frame."""
    if v is None:
        return default
    v = _num(v, default * size)
    return v / size if v > 1.0 else v


def _spec_type(c, dur, W, H, zone):
    """Type boxes of one spec shot: captions in the caption zone, `text` cards where they sit, cinema `lower_copy` and `title_bloom`."""
    out = []

    def add(text, at, until, cx, cy, size_pct, **kw):
        at = min(max(_num(at), 0.0), dur)
        out.append(dict(id=f"t{len(out) + 1}", text=str(text or ""), at=round(at, 4), dur=round(max(min(_num(until, dur), dur) - at, 0.05), 4),
                        size_pct=round(size_pct, 3), cx=round(cx, 4), cy=round(cy, 4), **kw))
    zcx, zcy = ((zone[0] + zone[2]) / 2, (zone[1] + zone[3]) / 2) if zone else (0.5, 0.84)
    for o in c.get("overlays") or []:
        t = o.get("t") or [0, dur]
        if o.get("type") == "caption":
            add(o.get("text"), t[0], t[1], zcx, zcy, _num(o.get("size"), 32) / H * 100, zone="caption")
        elif o.get("type") == "text":
            add(o.get("text"), t[0], t[1], _frac(o.get("cx"), W, 0.5), _frac(o.get("cy"), H, 0.5), _num(o.get("size"), 64) / H * 100)
    for o in c.get("lower_copy") or []:
        add(o.get("text"), o.get("at"), _num(o.get("at")) + _num(o.get("dur"), 2.0), 0.5, _frac(o.get("cy"), H, 0.86), 4.0)
    tb = c.get("title_bloom")
    if isinstance(tb, dict):
        add(tb.get("text"), tb.get("at"), _num(tb.get("at")) + _num(tb.get("dur"), 2.0), 0.5, _frac(tb.get("cy"), H, 0.5), 8.0)
    return out


def from_spec(pd):
    """Scene from promo.yaml `shots:`: each shot at its beats (frame-exact, as the build cuts it), its `cam` as the camera box over the
    recording, captions / text / lower_copy / title_bloom as type boxes. A UI shot is one fullscreen stand-in for the recording (cinema UI
    shots a floating panel with `cam` as its crop, as cinema draws them); a `ui: false` or card shot is a plate. Gaps between shots are kept
    as gaps: the animatic shows them, the spec's `timeline` gate still fails them."""
    from .render import RenderContext
    from .spec import load_spec, resolve_cam_keys
    spec = load_spec(os.path.join(pd, "promo.yaml"), plugins=False)
    raw = spec.raw
    frame = _frame_of(raw)
    W, H = frame["aspect"]
    A = W / H
    z = RenderContext.from_spec(spec).caption.get("zone") or {}
    zone = [round(_num(z.get("x0")) / W, 4), round(_num(z.get("y0")) / H, 4), round(_num(z.get("x1")) / W, 4), round(_num(z.get("y1")) / H, 4)] if z else None
    shots = []
    for s in spec.shots:
        c = s.cfg
        dur = round(s.n / spec.fps, 4)
        ui = bool(c["ui"]) if "ui" in c else s.type != "card" and bool(c.get("source") or c.get("segs"))
        keys = []
        for k in resolve_cam_keys(c.get("cam") or [[0, 0.5, 0.5, 1.0]], dur):
            key = dict(t=round(min(max(_num(k[0]), 0.0), dur), 4), cx=_num(k[1], 0.5), cy=_num(k[2], 0.5), w=round(min(max(_num(k[3], 1.0), CAM_W[0]), CAM_W[1]), 4))
            if len(k) > 4 and k[4] == "linear":
                key["ease"] = "linear"
            keys.append(key)
        panels, plate = [], None
        if ui and s.type == "cinema":
            pnl = (c.get("look") or {}).get("panel") or {}
            panels.append(dict(id="ui-1", kind="floating", source=None, cx=0.5, cy=_num(pnl.get("cy"), 0.44), w=_num(pnl.get("w"), 0.62),
                               aspect=round(_num(pnl.get("aspect"), A), 4), z=0.0, crop=keys, label=f"{c.get('source') or 'recording'} (real UI, never drawn)"))
            keys = [dict(t=0.0, cx=0.5, cy=0.5, w=1.0)]
            plate = dict(id=f"backdrop-{s.id}", ui=False)
        elif ui:
            panels.append(dict(id="ui-1", kind="fullscreen", source=None, cx=0.5, cy=0.5, w=1.0, aspect=round(A, 4), z=0.0,
                               label=f"{c.get('source') or 'recording'} (real UI, never drawn)"))
        else:
            plate = dict(id=f"plate-{s.id}", ui=False)
        shots.append(dict(id=s.id, beat=f"beats {s.b0:g}-{s.b1:g}", beats=[s.b0, s.b1], t0=round(s.f0 / spec.fps, 4), dur=dur,
                          framing=panels[0]["kind"] if panels else "plate", ui=ui, type_of=s.type,
                          camera=dict(mode=camera_mode(keys), keys=keys), plate=plate, panels=panels, type=_spec_type(c, dur, W, H, zone), notes=c.get("notes", "")))
    tl = spec.timeline
    return dict(schema=SCHEMA, source=dict(kind="spec", ref="promo.yaml shots"), frame=frame, projection=settings(pd)["projection"], shots=shots,
                stills={}, limits={}, grid=dict(bpm=tl.bpm, beat_s=round(tl.B, 6), beats=tl.beats), caption_zone=zone)


# ---------------------------------------------------------------- targets: where the scene and strip of a project live
class Target:
    def __init__(self, pd, key, kind, dir_):
        self.pd, self.key, self.kind, self.dir = pd, key, kind, dir_
        self.scene_path = os.path.join(dir_, "scene.json")
        self.viewer_path = os.path.join(dir_, "viewer.html")
        self.strip_json = os.path.join(dir_, "strip.json")
        self.strip_png = os.path.join(dir_, "strip.png")

    @property
    def label(self):
        return f"story {self.key}" if self.key else "the project"

    def compile(self):
        if self.kind == "designed":
            raw, plan = _yaml_plan(self.pd)
            return from_designed(raw, plan, self.pd)
        if self.kind == "storyboard":
            d = os.path.join(self.pd, "flow", "boards", self.key)
            from . import storyboard as SB
            return from_storyboard(self.key, SB.load(d), d, self.pd)
        if self.kind == "spec":
            return from_spec(self.pd)
        raise PrevizError(f"{self.dir}: a hand-written scene has no source to sync from (edit scene.json)")

    def load(self):
        sc = _read_json(self.scene_path)
        if sc is None:
            raise PrevizError(f"no {self.scene_path}: run `promo previz build`")
        return sc


def _boards(pd, stories=None):
    flow = _read_json(os.path.join(pd, "flow", "flow.json"), {})
    picks = [s for s in (stories if stories is not None else flow.get("picks") or [])]
    return [s for s in picks if os.path.isfile(os.path.join(pd, "flow", "boards", s, "board.json"))]


def _scene_kind(path):
    return ((_read_json(path, {}) or {}).get("source") or {}).get("kind")


def targets(pd, stories=None, source=None):
    """Targets of a project: the designed plan (one scene) unless `source=storyboard`, else one per picked storyboard, else a hand-written
    scene, else the promo.yaml shot list (`source=spec`)."""
    pd = os.path.abspath(pd)
    base = os.path.join(pd, "previz")
    _, plan = _yaml_plan(pd)
    if source in (None, "designed", "auto") and (plan or {}).get("designed"):
        return [Target(pd, "", "designed", base)]
    if source in (None, "storyboard", "auto"):
        bs = _boards(pd, stories)
        if bs:
            return [Target(pd, s, "storyboard", os.path.join(base, s)) for s in bs]
    scene = os.path.join(base, "scene.json")
    if source in (None, "auto") and os.path.isfile(scene) and _scene_kind(scene) != "spec":
        return [Target(pd, "", "manual", base)]
    if source in (None, "auto", "spec") and _has_spec_shots(pd):
        return [Target(pd, "", "spec", base)]
    if source == "designed":
        raise PrevizError("no plan.designed in promo.yaml: run `promo plan <name> --prompt ... --stills ...` first")
    if source == "storyboard":
        raise PrevizError("no storyboard to block out: `promo flow story` / `scene add` first")
    if source == "spec":
        raise PrevizError("no `shots:` in promo.yaml to block out (`promo new NAME` writes a starter list)")
    raise PrevizError("nothing to block out: no plan.designed or shots in promo.yaml, no picked storyboard in flow/, no previz/scene.json")


# ---------------------------------------------------------------- build / sync
def _diff(old, new):
    o, n = {s["id"]: s for s in old.get("shots") or []}, {s["id"]: s for s in new["shots"]}
    return dict(added=[i for i in n if i not in o], removed=[i for i in o if i not in n],
                changed=[i for i in n if i in o and _canon({k: v for k, v in n[i].items() if k not in VOLATILE}) != _canon({k: v for k, v in o[i].items() if k not in VOLATILE})])


def sync(target):
    """Regenerate `shots` from the source. `overrides` (the agent's camera / panel / type / timing edits) are kept as written."""
    new = target.compile()
    old = _read_json(target.scene_path, {})
    new["overrides"] = old.get("overrides") or {}
    if not old and target.kind == "storyboard":
        proj = settings(target.pd)["projection"]        # the style's 2D / 3D default, as a nudge: `promo previz projection` changes it
        if proj != new["projection"]:
            new["overrides"]["scene"] = dict(projection=proj)
    new["source"]["hash"] = generated_hash(new)
    new["source"]["synced_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    err, warn = problems(new)
    if err:
        raise PrevizError(f"{target.label}: previz scene has errors:\n  " + "\n  ".join(err))
    d = _diff(old, new) if old else dict(added=[s["id"] for s in new["shots"]], removed=[], changed=[])
    _write_json(target.scene_path, new)
    orphans = sorted(set((new["overrides"].get("shots") or {})) - {s["id"] for s in new["shots"]})
    return dict(scene=new, diff=d, orphans=orphans, warnings=warn, hash=scene_hash(new), created=not old)


def stale_source(target):
    """True when the stored scene is behind its source (the plan or storyboard changed since the last sync)."""
    if target.kind == "manual":
        return False
    sc = _read_json(target.scene_path)
    if sc is None:
        return True
    try:
        return generated_hash(target.compile()) != (sc.get("source") or {}).get("hash")
    except (PrevizError, OSError, KeyError, ValueError):
        return False


def _thumb_uri(path, width=480):
    from PIL import Image
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            if im.width > width:
                im = im.resize((width, max(1, round(im.height * width / im.width))))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return ""


def _tmpl(name):
    with open(os.path.join(TEMPLATE_DIR, name)) as f:
        return f.read()


def viewer_html(scene, title="previz", stills=False):
    """One self-contained page: Three.js (vendored, MIT), the viewer and the effective scene inline, so it opens from a file with no server."""
    e = effective(scene)
    e.pop("_effective", None)
    e["hash"] = scene_hash(scene)
    thumbs = {}
    if stills:
        for sid, st in (scene.get("stills") or {}).items():
            if st.get("exists") and st.get("path") and os.path.isfile(st["path"]) and str(st.get("kind", "image")) == "image":
                uri = _thumb_uri(st["path"])
                if uri:
                    thumbs[sid] = uri
    def js(o):
        return json.dumps(o, ensure_ascii=False).replace("</", "<\\/")
    with open(os.path.join(TEMPLATE_DIR, "vendor", "three.min.js")) as f:
        three = f.read().replace("</script", "<\\/script")
    html = _tmpl("viewer.html")
    for marker, val in (("/*PREVIZ_TITLE*/", re.sub(r"[<>&]", "", title)), ("/*THREE*/", three), ("/*VIEWER*/", _tmpl("viewer.js")),
                        ("/*SCENE*/", "window.PREVIZ_SCENE=" + js(e) + ";window.PREVIZ_STILLS=" + js(thumbs) + ";")):
        html = html.replace(marker, val)
    return html


def build(target, stills=False, force_sync=False):
    """Compile (or keep) the scene and write the viewer. A scene already there is only re-synced when its source moved or `force_sync`."""
    info = None
    if not os.path.isfile(target.scene_path) or force_sync or stale_source(target):
        if target.kind != "manual":
            info = sync(target)
    sc = target.load()
    err, warn = problems(sc)
    if err:
        raise PrevizError(f"{target.label}: previz scene has errors:\n  " + "\n  ".join(err))
    os.makedirs(target.dir, exist_ok=True)
    with open(target.viewer_path, "w") as f:
        f.write(viewer_html(sc, title=f"previz {os.path.basename(target.pd)} {target.key}".strip(), stills=stills))
    return dict(scene=sc, hash=scene_hash(sc), viewer=target.viewer_path, synced=info, warnings=warn)


# ---------------------------------------------------------------- strip export
def pick_times(scene, n=None, at=None, shot=None, ends=False):
    """Film times (s) to draw. `at` explicit; `shot` = its start / middle / end; `ends` = start and end of every shot (shows the camera
    move); else the middle of every shot (at most DEFAULT_N, evenly thinned) or `n` evenly spaced times."""
    e = scene if scene.get("_effective") else effective(scene)
    eps = 0.02
    if at:
        return [round(float(t), 3) for t in at]
    if shot:
        s = next((x for x in e["shots"] if x["id"] == str(shot)), None)
        if not s:
            raise PrevizError(f"no shot {shot}: {', '.join(x['id'] for x in e['shots'])}")
        return [round(s["t0"] + eps, 3), round(s["t0"] + s["dur"] / 2, 3), round(s["t0"] + s["dur"] - eps, 3)]
    total = e["duration_s"]
    if n:
        return [round(total * (i + 0.5) / n, 3) for i in range(int(n))]
    if ends:
        return [round(t, 3) for s in e["shots"] for t in (s["t0"] + eps, s["t0"] + s["dur"] - eps)]
    mids = [round(s["t0"] + s["dur"] / 2, 3) for s in e["shots"]]
    if len(mids) > DEFAULT_N:
        mids = [mids[int(i * len(mids) / DEFAULT_N)] for i in range(DEFAULT_N)]
    return mids


def strip_geometry(aspect, n):
    th = TILE_H if aspect >= 1 else 400
    tw = int(round(th * aspect))
    cols = min(n, 4 if aspect >= 1 else 6) or 1
    rows = -(-n // cols)
    lh, gap, pad = 22, 8, 8
    return dict(tile_w=tw, tile_h=th, label_h=lh, cols=cols, rows=rows, gap=gap, pad=pad,
                width=pad + cols * (tw + gap), height=pad + rows * (th + lh + gap))


def tile_label(e, t):
    shot, lt, proj, cam, _ = layout(e, t)
    return f"{shot['id']}  {t:.1f}s  {shot.get('framing', '')}  {camera_mode((shot.get('camera') or {}).get('keys') or [])}  {proj}"


@functools.lru_cache(maxsize=32)
def _font(px):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        if os.path.isfile(p):
            return ImageFont.truetype(p, px)
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def draw_items(tile, items, f_small, f_lbl, stand_in=False):
    """Draw layout() items onto an RGBA tile and return it. `stand_in` marks every panel as a stand-in for a real recording (animatic)."""
    from PIL import Image, ImageDraw
    W, H = tile.size
    for it in items:
        layer = Image.new("RGBA", tile.size, (0, 0, 0, 0))          # ImageDraw writes RGBA rather than blending it: one layer per item
        td = ImageDraw.Draw(layer)
        u0, v0, u1, v1 = it["rect"]
        box = [u0 * W, v0 * H, u1 * W, v1 * H]
        c = COLORS.get(it["kind"], COLORS["floating"])
        if it["kind"] == "crop":
            td.rectangle(box, outline=c + (150,), width=1)
            td.text((box[0] + 4, box[3] - 14), it["label"], fill=c + (170,), font=f_small)
            tile = Image.alpha_composite(tile, layer)
            continue
        td.rectangle(box, fill=c + ((40 if it["kind"] == "plate" else 30 if it["kind"] != "type" else 22),), outline=c + (255,), width=2 if it["kind"] != "plate" else 1)
        if it["kind"] == "type":
            fy = getattr(f_lbl, "size", 12)
            td.text((box[0] + 4, (box[1] + box[3]) / 2 - fy / 2 - 1), it["label"][:60], fill=c + (255,), font=f_lbl)
        else:
            td.line([box[0], box[1], box[2], box[3]], fill=c + (56,))
            td.line([box[0], box[3], box[2], box[1]], fill=c + (56,))
            x, y = max(box[0], 0) + 5, max(box[1], 0) + 4
            td.text((x, y), it["label"][:48], fill=c + (255,), font=f_small)
            if stand_in and it["kind"] in PANEL_KINDS:
                td.text((x, y + getattr(f_small, "size", 11) + 4), "UI STAND-IN: real recording needed", fill=c + (255,), font=f_small)
        tile = Image.alpha_composite(tile, layer)
    return tile


def render_pil(scene, times, out):
    """The strip with PIL: the same layout() the viewer draws, flat. The fallback when there is no Chrome; also what the tests exercise."""
    from PIL import Image, ImageDraw
    e = effective(scene)
    A = aspect_of(e)
    g = strip_geometry(A, len(times))
    im = Image.new("RGB", (g["width"], g["height"]), BG)
    d = ImageDraw.Draw(im)
    f_small, f_lbl = _font(11), _font(12)
    for i, t in enumerate(times):
        col, row = i % g["cols"], i // g["cols"]
        x0 = g["pad"] + col * (g["tile_w"] + g["gap"])
        y0 = g["pad"] + row * (g["tile_h"] + g["label_h"] + g["gap"])
        tile = Image.new("RGBA", (g["tile_w"], g["tile_h"]), BG + (255,))
        *_, items = layout(e, t)
        tile = draw_items(tile, items, f_small, f_lbl)
        ImageDraw.Draw(tile).rectangle([0, 0, g["tile_w"] - 1, g["tile_h"] - 1], outline=COLORS["guide"] + (255,))
        im.paste(tile.convert("RGB"), (x0, y0))
        d.text((x0, y0 + g["tile_h"] + 3), tile_label(e, t), fill=(200, 205, 215), font=f_small)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    im.save(out)
    return dict(engine="pil", width=g["width"], height=g["height"])


def find_chrome():
    cands = [os.environ.get("PROMO_CHROME", "")] + [shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")]
    cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def render_chrome(target_viewer, scene, times, out, chrome=None, timeout=45):
    """The strip through the Three.js viewer in headless Chrome (software WebGL), one launch for every tile. Returns None when the
    page could not draw (no WebGL): the viewer paints the page red, which is how this is told apart from a real strip."""
    from PIL import Image
    chrome = chrome or find_chrome()
    if not chrome:
        return None
    e = effective(scene)
    g = strip_geometry(aspect_of(e), len(times))
    q = "strip=1&times=" + ",".join(f"{t:g}" for t in times) + "&geo=" + ",".join(str(g[k]) for k in ("tile_w", "tile_h", "label_h", "cols", "gap", "pad", "width", "height"))
    url = "file://" + os.path.abspath(target_viewer) + "?" + q
    tmp = tempfile.mkdtemp(prefix="previz-chrome-")
    shot = os.path.join(tmp, "shot.png")
    try:
        # headless=new reserves browser chrome in --window-size: ask for taller than the page and crop to it
        cmd = [chrome, "--headless=new", "--no-sandbox", "--disable-gpu-sandbox", "--use-angle=swiftshader", "--use-gl=angle", "--enable-unsafe-swiftshader",
               "--ignore-gpu-blocklist", "--disable-dev-shm-usage", "--disable-background-networking", "--hide-scrollbars", "--force-device-scale-factor=1", "--no-first-run", "--disable-extensions", f"--user-data-dir={tmp}/profile",
               f"--window-size={g['width']},{g['height'] + 140}", "--virtual-time-budget=6000", f"--screenshot={shot}", url]
        # Chrome writes the PNG after about a second and then sits there: wait for the file, then stop the whole process group
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            deadline, last = time.time() + timeout, -1
            while time.time() < deadline:
                size = os.path.getsize(shot) if os.path.isfile(shot) else 0
                if size and size == last:
                    break
                last = size
                if proc.poll() is not None and not size:
                    return None
                time.sleep(0.25)
            else:
                return None
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()
        with Image.open(shot) as im:
            im = im.convert("RGB")
            if im.width < g["width"] or im.height < g["height"]:
                return None
            im = im.crop((0, 0, g["width"], g["height"]))
            if im.getpixel((2, 2)) == (122, 31, 31) or im.getpixel((g["width"] - 3, g["height"] - 3)) == (122, 31, 31):
                return None
            os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
            im.save(out)
        return dict(engine="chrome", width=g["width"], height=g["height"])
    except OSError:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def strip(target, n=None, at=None, shot=None, ends=False, engine="auto", out=None, stills=False):
    """Export the strip PNG for the current scene. A full strip (not `shot`) is what the gates look for: it records the scene hash in
    strip.json. A strip of one shot is a cheap look while directing it and never satisfies a gate."""
    b = build(target, stills=stills)
    sc = b["scene"]
    times = pick_times(sc, n, at, shot, ends)
    partial = bool(shot or at)
    png = out or (os.path.join(target.dir, f"strip-shot-{shot}.png") if shot else os.path.join(target.dir, "strip-at.png") if at else target.strip_png)
    t0 = time.time()
    res = None
    if engine in ("auto", "chrome"):
        res = render_chrome(target.viewer_path, sc, times, png)
        if res is None and engine == "chrome":
            raise PrevizError("headless Chrome could not draw the Three.js viewer (no Chrome, or no WebGL): use --engine pil, or set PROMO_CHROME to a Chrome / Chromium binary")
    if res is None:
        res = render_pil(sc, times, png)
    meta = dict(scene_hash=b["hash"], png=os.path.abspath(png), engine=res["engine"], times=times, tiles=len(times), width=res["width"], height=res["height"],
                at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), seconds=round(time.time() - t0, 2), partial=partial)
    if not partial and not out:
        _write_json(target.strip_json, meta)
    return dict(meta, warnings=b["warnings"], viewer=target.viewer_path)


# ---------------------------------------------------------------- animatic: one clip per shot on the music grid, then one video
# (idea from CodeVideoModel inference/render.py: a code scene encoded frame by frame, its camera kept beside it; templates/previz/vendor/codevideomodel/)
ANIMATIC_FPS = 15
ANIMATIC_H = 540
NOT_FOOTAGE = "promo-reel previz: a wireframe blockout for timing and camera, NOT FOOTAGE and never product UI"
CLICK_SR = 48000
_CODE = None


def _code():
    """Hash of this module: a change to how a shot is drawn rebuilds every shot once."""
    global _CODE
    if _CODE is None:
        with open(os.path.abspath(__file__), "rb") as f:
            _CODE = hashlib.sha256(f.read()).hexdigest()[:12]
    return _CODE


def animatic_paths(target):
    name = os.path.basename(target.pd) + (f"-{target.key}" if target.key else "")
    return dict(dir=os.path.join(target.dir, "shots"), video=os.path.join(target.dir, f"{name}.previz-animatic.mp4"),
                meta=os.path.join(target.dir, "animatic.previz.json"))


ASSUMED_BPM = 120.0


def _grid(target, scene):
    """{bpm, beat_s, beats?, assumed?} of the music grid the animatic plays against: the scene's own (spec), else promo.yaml `timeline`,
    else the board's `bpm`, else `animatic --bpm` (previz/settings.json), else 120 bpm marked assumed (the track is picked later)."""
    if scene.get("grid"):
        return scene["grid"]
    raw, _ = _yaml_plan(target.pd)
    board = _read_json(os.path.join(target.pd, "flow", "boards", target.key, "board.json"), {}) if target.kind == "storyboard" else {}
    for bpm in (((raw or {}).get("timeline") or {}).get("bpm"), (board or {}).get("bpm"), _read_json(os.path.join(target.pd, "previz", "settings.json"), {}).get("bpm")):
        if bpm:
            return dict(bpm=float(bpm), beat_s=round(60.0 / float(bpm), 6))
    return dict(bpm=ASSUMED_BPM, beat_s=round(60.0 / ASSUMED_BPM, 6), assumed=True)


def _size(arg, aspect):
    if arg:
        m = re.fullmatch(r"(\d+)x(\d+)", str(arg))
        if not m:
            raise PrevizError(f"--size must be WxH (e.g. 960x540), not {arg!r}")
        w, h = int(m.group(1)), int(m.group(2))
    else:
        h = ANIMATIC_H if aspect >= 1 else 960
        w = round(h * aspect)
    if w < 64 or h < 64:
        raise PrevizError(f"--size {w}x{h} is too small to read")
    return w + w % 2, h + h % 2


def timeline_of(e, fps, end=None):
    """[(kind, shot | None, t0, t1, f0, f1)] in film order: every shot and every gap (also before the first shot and up to `end`).
    Overlapping shots raise: a shot that starts before the last one ended has no single picture to show."""
    shots = sorted(e["shots"], key=lambda s: s["t0"])
    for a, b in zip(shots, shots[1:]):
        if b["t0"] < a["t0"] + a["dur"] - 1e-6:
            raise PrevizError(f"shots {a['id']} and {b['id']} overlap ({a['id']} ends at {a['t0'] + a['dur']:g}s, {b['id']} starts at {b['t0']:g}s): "
                              "fix their beats; nothing was rebuilt")
    out, t = [], 0.0
    for s in shots + [None]:
        t_next = s["t0"] if s else max(end or 0.0, t)
        if t_next - t > 0.5 / fps:
            out.append(("gap", None, t, t_next, round(t * fps), round(t_next * fps)))
        if s:
            t1 = s["t0"] + s["dur"]
            out.append(("shot", s, s["t0"], t1, round(s["t0"] * fps), max(round(t1 * fps), round(s["t0"] * fps) + 1)))
            t = t1
    return out


def shot_digest(e, shot, n, size, fps, grid):
    """What a shot's clip shows, and nothing about where it sits: its own content, frame count, size, the beat phase its ticks fall on, the
    caption zone and this module's code. A shot that only moved in time keeps its clip (`shifted`)."""
    core = {k: v for k, v in shot.items() if k not in VOLATILE + ("t0",)}
    for sub in ("panels", "type"):
        core[sub] = [{k: v for k, v in x.items() if k not in VOLATILE} for x in core.get(sub) or []]
    if core.get("camera"):
        core["camera"] = {k: v for k, v in core["camera"].items() if k != "mode"}
    phase = round((shot["t0"] / grid["beat_s"]) % 4, 3) if grid else None
    return _hash(dict(shot=core, n=n, size=list(size), fps=fps, proj=(shot.get("camera") or {}).get("projection") or e["projection"],
                      frame=e["frame"], zone=e.get("caption_zone"), beat_s=(grid or {}).get("beat_s"), assumed=bool((grid or {}).get("assumed")), phase=phase, code=_code()))


def _encode(frames, n, size, fps, out, title):
    """Pipe n RGB frames into one libx264 pass, written beside `out` and moved over it when complete."""
    tmp = out + ".part.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "pipe:0",
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-threads", "2", "-g", str(fps),
           "-metadata", f"title={title}", "-metadata", f"comment={NOT_FOOTAGE}", tmp]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(n):
            proc.stdin.write(frames(i).tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise PrevizError(f"ffmpeg could not encode {out}: {err.strip()[-300:]}")
    except BrokenPipeError:
        proc.wait()
        raise PrevizError(f"ffmpeg stopped while encoding {out}: {proc.stderr.read().decode(errors='replace').strip()[-300:]}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    os.replace(tmp, out)


def _beats_in(shot, grid):
    """[(local t, beat index)] of the grid's beats inside a shot, from its phase (so the ticks do not depend on where the shot sits)."""
    if not grid:
        return []
    bs = grid["beat_s"]
    ph = (shot["t0"] / bs) % 4
    out, k = [], math.ceil(ph - 1e-6)
    while (k - ph) * bs <= shot["dur"] + 1e-6:
        out.append(((k - ph) * bs, k % 4))
        k += 1
    return out


def animatic_frame(e, shot, lt, size, grid):
    """One animatic frame of a shot: the wireframes, the caption zone, the camera box on a minimap, beat ticks and the previz label."""
    from PIL import Image, ImageDraw
    W, H = size
    k = H / 540.0
    f_small, f_head = _font(max(10, round(12 * k))), _font(max(12, round(16 * k)))
    _, _, proj, cam, items = layout_shot(e, shot, lt)
    tile = Image.new("RGBA", size, BG + (255,))
    for it in items:
        if it["kind"] == "type":
            it["font"] = _font(max(10, min(64, round((it["rect"][3] - it["rect"][1]) * H * 0.55))))
    for it in items:                                      # type at its own size; the rest with the label font
        tile = draw_items(tile, [it], f_small, it.get("font") or f_small, stand_in=bool(shot.get("ui")))
    d = ImageDraw.Draw(tile)
    g = COLORS["guide"]
    if e.get("caption_zone"):
        x0, y0, x1, y1 = (e["caption_zone"][0] * W, e["caption_zone"][1] * H, e["caption_zone"][2] * W, e["caption_zone"][3] * H)
        for x in range(int(x0), int(x1), 12):
            d.line([x, y0, min(x + 6, x1), y0], fill=g + (255,)); d.line([x, y1, min(x + 6, x1), y1], fill=g + (255,))
        for y in range(int(y0), int(y1), 12):
            d.line([x0, y, x0, min(y + 6, y1)], fill=g + (255,)); d.line([x1, y, x1, min(y + 6, y1)], fill=g + (255,))
        d.text((x0 + 3, y0 - 14 * k), "caption zone", fill=g + (255,), font=f_small)
    mw = round(W * 0.16)                                  # minimap: the recording / frame, and the box the camera frames of it (cinema `cam`)
    mh = round(mw * H / W)
    mx, my = W - mw - round(10 * k), round(10 * k)
    d.rectangle([mx, my, mx + mw, my + mh], fill=(44, 48, 58, 255), outline=g + (255,))
    keys = _composed_cam(shot)
    cx, cy, cw = cam_at(dict(camera=dict(keys=[dict(t=q[0], cx=q[1], cy=q[2], w=q[3]) for q in keys])), lt)
    d.rectangle([mx + (cx - cw / 2) * mw, my + (cy - cw / 2) * mh, mx + (cx + cw / 2) * mw - 1, my + (cy + cw / 2) * mh - 1], outline=COLORS["type"] + (255,), width=2)
    d.text((mx, my + mh + 3), f"camera box w {cw:.2f}", fill=g + (255,), font=f_small)
    head = f"{shot['id']}  {shot['dur']:.2f}s  {camera_mode([dict(t=q[0], cx=q[1], cy=q[2], w=q[3]) for q in keys])}  {'3D' if proj == 'persp' else '2D'}"
    if grid:
        head += f"  {shot['dur'] / grid['beat_s']:.4g} beats @ {grid['bpm']:g} bpm" + (" (assumed)" if grid.get("assumed") else "")
    sub = str(shot.get("beat") or "")[:80]
    d.rectangle([0, 0, max(d.textlength(head, font=f_head), d.textlength(sub, font=f_small)) + 20 * k, (48 if sub else 30) * k], fill=BG + (235,))
    d.text((round(10 * k), round(6 * k)), head, fill=(230, 232, 238, 255), font=f_head)
    if sub:
        d.text((round(10 * k), round(28 * k)), sub, fill=g + (255,), font=f_small)
    by = H - round(16 * k)                                # beat ticks: long on the downbeat, a flash as each beat lands
    d.line([0, by, W, by], fill=g + (120,))
    for bt, n in _beats_in(shot, grid):
        x = bt / max(shot["dur"], 1e-6) * (W - 1)
        d.line([x, by - (10 if n == 0 else 5) * k, x, by], fill=(COLORS["type"] if n == 0 else g) + (255,), width=2 if n == 0 else 1)
        if 0 <= lt - bt < 0.12:
            r = (9 if n == 0 else 6) * k
            d.ellipse([W - 40 * k - r, by - 30 * k - r, W - 40 * k + r, by - 30 * k + r], fill=(COLORS["type"] if n == 0 else (230, 232, 238)) + (255,))
    d.rectangle([0, by + 2, lt / max(shot["dur"], 1e-6) * W, by + 4], fill=COLORS["crop"] + (200,))
    d.text((round(10 * k), by - round(22 * k)), "PREVIZ · NOT FOOTAGE", fill=(255, 120, 120, 255), font=f_small)
    return tile.convert("RGB")


def gap_frame(t0, t1, size):
    from PIL import Image, ImageDraw
    W, H = size
    k = H / 540.0
    im = Image.new("RGB", size, (60, 18, 18))
    d = ImageDraw.Draw(im)
    d.text((round(20 * k), H / 2 - 20 * k), f"GAP  {t0:.2f}-{t1:.2f}s: no shot here (fix the beats)", fill=(255, 200, 200), font=_font(max(12, round(20 * k))))
    d.text((round(20 * k), H - round(38 * k)), "PREVIZ · NOT FOOTAGE", fill=(255, 120, 120), font=_font(max(10, round(12 * k))))
    return im


def click_track(path, total_s, beat_s):
    """A beat click for the whole animatic (accented downbeat every 4 beats), 48 kHz stereo 16-bit."""
    import wave

    import numpy as np
    n = max(1, int(round(total_s * CLICK_SR)))
    y = np.zeros(n, dtype=np.float32)
    L = int(0.03 * CLICK_SR)
    k = 0
    while k * beat_s < total_s:
        i = int(round(k * beat_s * CLICK_SR))
        t = np.arange(min(L, n - i)) / CLICK_SR
        y[i:i + len(t)] += (0.5 if k % 4 == 0 else 0.3) * np.sin(2 * np.pi * (1760 if k % 4 == 0 else 1100) * t) * np.exp(-t * 120)
        k += 1
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(CLICK_SR)
        w.writeframes(np.repeat(pcm, 2).tobytes())
    return path


def _music_bed(target):
    if target.kind not in ("spec", "designed"):
        return None
    from . import music
    from .spec import load_spec
    p = music.music_path(load_spec(os.path.join(target.pd, "promo.yaml"), plugins=False))
    return p if os.path.isfile(p) else None


def animatic(target, only=None, fps=ANIMATIC_FPS, size=None, audio="auto", force=False):
    """Render the animatic: a silent `shots/<id>.previz.mp4` per shot, rebuilt only when that shot's own content changed, then one
    `<name>.previz-animatic.mp4` (every shot and gap, with a beat click or the built music bed) and `animatic.previz.json`. `only` re-renders
    those shots even when unchanged. Returns {rebuilt, kept, shifted, gaps, video, meta, ...}. The strip is refreshed too (PIL)."""
    b = build(target)
    sc = b["scene"]
    e = effective(sc)
    ids = [s["id"] for s in e["shots"]]
    bad = [i for i in only or [] if i not in ids]
    if bad:
        raise PrevizError(f"no shot {', '.join(bad)}: {', '.join(ids)}")
    grid = _grid(target, sc)
    end = grid["beats"] * grid["beat_s"] if grid and grid.get("beats") else None
    tl = timeline_of(e, fps, end)
    size = _size(size, aspect_of(e))
    P = animatic_paths(target)
    os.makedirs(P["dir"], exist_ok=True)
    from .cache import Stamps
    stamps = Stamps(P["dir"])
    prev = {s["id"]: s for s in (_read_json(P["meta"], {}) or {}).get("shots") or []}
    rep = dict(rebuilt=[], kept=[], shifted=[], gaps=[], warnings=b["warnings"])
    parts, rows = [], []
    t_start = time.time()
    for kind, s, t0, t1, f0, f1 in tl:
        n = f1 - f0
        if kind == "gap":
            path = os.path.join(P["dir"], f"gap-{f0}-{f1}.previz.mp4")
            dig = _hash(dict(gap=[f0, f1], size=list(size), fps=fps, code=_code()))
            if force or not stamps.is_fresh(os.path.basename(path), dig, [path]):
                im = gap_frame(t0, t1, size)
                _encode(lambda i: im, n, size, fps, path, f"previz gap {t0:.2f}-{t1:.2f}s")
                stamps.write(os.path.basename(path), dig)
            rep["gaps"].append(dict(t0=round(t0, 3), t1=round(t1, 3)))
            parts.append(path)
            continue
        sid = s["id"]
        path = os.path.join(P["dir"], f"{sid}.previz.mp4")
        dig = shot_digest(e, s, n, size, fps, grid)
        if force or sid in (only or []) or not stamps.is_fresh(sid, dig, [path]):
            _encode(lambda i, s=s: animatic_frame(e, s, i / fps, size, grid), n, size, fps, path, f"previz shot {sid}")
            stamps.write(sid, dig, frames=n)
            rep["rebuilt"].append(sid)
        elif sid in prev and abs(_num(prev[sid].get("t0")) - s["t0"]) > 1e-6:
            rep["shifted"].append(sid)
        else:
            rep["kept"].append(sid)
        parts.append(path)
        rows.append(dict(id=sid, t0=round(t0, 4), dur=round(s["dur"], 4), frames=n, digest=dig, file=os.path.relpath(path, target.dir)))
    total = tl[-1][5] if tl else 0
    dur = total / fps
    tmp = tempfile.mkdtemp(prefix="previz-animatic-")
    try:
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        bed, used = (_music_bed(target) if audio in ("auto", "music") else None), "music"
        if audio == "music" and not bed:
            raise PrevizError("--audio music: no built music bed (`promo build` writes build/audio/music-edit.wav); use --audio click")
        if audio == "click" or (audio == "auto" and not bed):
            bed, used = (click_track(os.path.join(tmp, "click.wav"), dur, grid["beat_s"]) if grid else None), "click"
        if audio == "none" or not bed:
            used = "none"
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst]
        if used != "none":
            cmd += ["-i", bed, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "128k", "-af", f"apad,atrim=0:{dur:.6f}"]
        cmd += ["-frames:v", str(total), "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-threads", "2",
                "-movflags", "+faststart", "-metadata", f"title=previz animatic {os.path.basename(target.pd)} {target.key}".strip(),
                "-metadata", f"comment={NOT_FOOTAGE}", P["video"] + ".part.mp4"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise PrevizError(f"ffmpeg could not join the animatic: {r.stderr.strip()[-300:]}")
        os.replace(P["video"] + ".part.mp4", P["video"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    meta = dict(kind="previz", schema="promo-previz-animatic@1", not_footage=True, note=NOT_FOOTAGE, scene_hash=b["hash"], source=sc.get("source"),
                bpm=(grid or {}).get("bpm"), bpm_assumed=bool((grid or {}).get("assumed")), beat_s=(grid or {}).get("beat_s"), fps=fps, size=list(size), frames=total, duration_s=round(dur, 4),
                audio=used, video=os.path.relpath(P["video"], target.dir), shots=rows, gaps=rep["gaps"], trajectory=timing_camera(target),
                at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    _write_json(P["meta"], meta)
    st = strip(target, engine="pil")
    return dict(rep, video=P["video"], meta=P["meta"], frames=total, duration_s=round(dur, 4), audio=used, seconds=round(time.time() - t_start, 2),
                strip=st["png"], end_s=end, grid=grid)


def animatic_status(target):
    """ok | missing | stale: is there an animatic of the current scene?"""
    P = animatic_paths(target)
    m = _read_json(P["meta"])
    if not m or not os.path.isfile(P["video"]):
        return "missing"
    sc = _read_json(target.scene_path)
    try:
        return "ok" if sc and m.get("scene_hash") == scene_hash(sc) and not stale_source(target) else "stale"
    except (KeyError, TypeError, ValueError):
        return "stale"


# ---------------------------------------------------------------- handoff: timing and camera only, never the picture
def timing_camera(target):
    """[{id, t0, dur, cam: [[t, cx, cy, w], ...]}] of the scene as it plays: when each shot runs and the box the camera frames (on a panel
    shot folded into the panel's crop, as `cinema` keys it). Keyframes and drafts read this; nothing visual is handed on."""
    sc = _read_json(target.scene_path)
    if not sc:
        return []
    return [dict(id=s["id"], t0=round(s["t0"], 4), dur=round(s["dur"], 4), cam=[k[:4] for k in _composed_cam(s)]) for s in effective(sc)["shots"]]


def blocking(pd, stories=None):
    """{story: {shot id: {t0, dur, start: (cx, cy, w), end: (cx, cy, w)}}} for the keyframes: where each frame's camera box sits."""
    out = {}
    try:
        ts = targets(pd, stories)
    except PrevizError:
        return out
    for t in ts:
        rows = {}
        for r in timing_camera(t):
            world = dict(camera=dict(keys=[dict(t=k[0], cx=k[1], cy=k[2], w=k[3]) for k in r["cam"]]))
            rows[r["id"]] = dict(t0=r["t0"], dur=r["dur"], start=tuple(round(v, 3) for v in cam_at(world, 0.0)), end=tuple(round(v, 3) for v in cam_at(world, r["dur"])))
        out[t.key] = rows
    return out


def blocking_text(b, which):
    """One line for a keyframe prompt / to-do from a blocking row (`which` = start | end; a mid frame gets none)."""
    if which not in ("start", "end"):
        return ""
    cx, cy, w = b["end"] if which == "end" else b["start"]
    t = b["t0"] + (b["dur"] if which == "end" else 0.0)
    return f"Framing from the approved previz (timing and camera only): at {t:.1f}s the camera frames a box centred ({cx:.2f}, {cy:.2f}), {w:.2f} of the frame wide."


def shots_skeleton(target, bpm=None):
    """A promo.yaml `shots:` skeleton (id, beats from t via the bpm, cam) for drafts: timing and camera, nothing else."""
    sc = target.load()
    grid = _grid(target, sc)
    bpm = float(bpm or (grid or {}).get("bpm") or 0)
    if bpm <= 0:
        raise PrevizError("no music grid to put the shots on: pass --bpm")
    bs = 60.0 / bpm
    out = []
    for r in timing_camera(target):
        cam = [[("end" if abs(k[0] - r["dur"]) < 1e-6 and i else round(k[0], 3)), round(k[1], 4), round(k[2], 4), round(k[3], 4)] for i, k in enumerate(r["cam"])]
        out.append(dict(id=r["id"], beats=[round(r["t0"] / bs, 2), round((r["t0"] + r["dur"]) / bs, 2)], cam=cam))
    return dict(timeline=dict(bpm=bpm, beats=round(max((s["beats"][1] for s in out), default=0), 2)), shots=out)


# ---------------------------------------------------------------- status and gates
def target_status(target):
    """{scene, hash, behind, strip: ok|missing|stale|no-scene, problems: [...]} for one target."""
    out = dict(key=target.key, kind=target.kind, dir=target.dir, scene=os.path.isfile(target.scene_path), hash=None, behind=False, strip="no-scene",
               png=None, engine=None, errors=[], warnings=[])
    if not out["scene"]:
        return out
    sc = _read_json(target.scene_path, {})
    try:
        out["hash"] = scene_hash(sc)
        out["errors"], out["warnings"] = problems(sc)
    except (KeyError, TypeError, ValueError) as e:
        out["errors"] = [f"scene.json is malformed: {e}"]
        return out
    out["behind"] = stale_source(target)
    sj = _read_json(target.strip_json)
    if not sj or not os.path.isfile(sj.get("png", "")):
        out["strip"] = "missing"
    else:
        out["png"], out["engine"] = sj["png"], sj.get("engine")
        out["strip"] = "ok" if sj.get("scene_hash") == out["hash"] else "stale"
    return out


def status(pd, stories=None, source=None):
    try:
        ts = targets(pd, stories, source)
    except PrevizError as e:
        return dict(ok=False, targets=[], problems=[str(e)])
    rows = [target_status(t) for t in ts]
    probs = []
    for r, t in zip(rows, ts):
        if not r["scene"]:
            probs.append(f"{t.label}: no previz scene (`promo previz build`)")
        elif r["errors"]:
            probs.append(f"{t.label}: " + r["errors"][0])
        elif r["behind"]:
            probs.append(f"{t.label}: the scene is behind its source (`promo previz sync`, then `promo previz strip`)")
        elif r["strip"] == "missing":
            probs.append(f"{t.label}: no previz strip yet (`promo previz strip`)")
        elif r["strip"] == "stale":
            probs.append(f"{t.label}: the strip is of an older scene (`promo previz strip`)")
    return dict(ok=not probs, targets=rows, problems=probs)


def plan_hash(pd, stories=None):
    """What the person's plan approval covers of the previz: the scene hashes ('' when there is no scene, so older approvals stay valid)."""
    try:
        ts = targets(pd, stories)
    except PrevizError:
        return ""
    hs = []
    for t in ts:
        sc = _read_json(t.scene_path)
        if sc:
            try:
                hs.append(f"{t.key}:{scene_hash(sc)}")
            except (KeyError, TypeError, ValueError):
                pass
    return "|".join(hs)


def _raw(spec):
    raw = getattr(spec, "raw", None)
    return raw if isinstance(raw, dict) else {}


def _flow_stage(root):
    return (_read_json(os.path.join(root, "flow", "flow.json"), {}) or {}).get("stage")


def skipped(spec):
    """The reason a person recorded for working without previz (`previz: {skip: "..."}` in promo.yaml), or ''."""
    return str(((_raw(spec).get("previz")) or {}).get("skip") or "").strip()


def needed(spec):
    """Previz applies to a designed plan, a flow project, or a project that has started a hand-written previz scene. Plain hand-written
    specs are untouched, also once they have an animatic of their shot list (it is a look at the spec, not a step it must pass)."""
    plan = _raw(spec).get("plan") or {}
    scene = os.path.join(spec.root, "previz", "scene.json")
    return bool(plan.get("designed")) or (os.path.isfile(scene) and _scene_kind(scene) != "spec") or bool(_flow_stage(spec.root))


def gates(spec):
    """[(gate, status, msg)] for `promo check`: `previz-ready`. WARN on a 540p preview with no strip for the current scene, FAIL above
    540p, in a flow at keyframes or later, and for a designed plan the strip of another scene covers."""
    if not needed(spec):
        return []
    skip = skipped(spec)
    st = status(spec.root, source="designed" if (_raw(spec).get("plan") or {}).get("designed") else None)
    if skip:
        return [("previz-ready", "WARN", f"previz skipped: {skip}")]
    if st["ok"]:
        t = st["targets"][0] if st["targets"] else {}
        return [("previz-ready", "PASS", f"previz strip current for scene {t.get('hash')} ({t.get('engine')}): {os.path.relpath(t.get('png') or '', spec.root)}")]
    from . import flow as F
    stage = _flow_stage(spec.root)
    late = bool(stage) and stage in F.STAGES and F.STAGES.index(stage) >= F.STAGES.index("keyframes")
    hard = late or float(spec.scale) > 0.5 + 1e-9
    return [("previz-ready", "FAIL" if hard else "WARN", "; ".join(st["problems"]) + ("" if hard else " (a 540p preview only warns; a final or anything above 540p fails)"))]


def check_build(spec, look_only=False):
    """Raise when a designed plan is about to be rendered (beyond the quick look) without a previz strip of its current scene."""
    plan = _raw(spec).get("plan") or {}
    if look_only or not plan.get("designed") or skipped(spec):
        return None
    st = status(spec.root, source="designed")
    if not st["ok"]:
        raise PrevizError("previz first: block out the camera, panels and type before rendering.\n  " + "\n  ".join(st["problems"])
                          + "\n  `promo previz build && promo previz strip`, look at the strip, nudge with `promo previz cam|panel|type`; "
                            "`promo build --look` (the quick look) needs no strip")
    return None


# ---------------------------------------------------------------- previz -> cinema shots (`promo designed apply`)
def _composed_cam(shot):
    """Cinema `cam` keys [[t, cx, cy, w], ...] for a shot: the world camera alone on a plate / fullscreen shot, and on a panel shot the world
    camera folded into the panel's source crop (cinema has no camera over a panel: a push of the whole frame becomes a push of the content)."""
    boxed = next((p for p in shot.get("panels") or [] if p.get("kind") != "fullscreen"), None)
    world = dict(camera=dict(keys=(shot.get("camera") or {}).get("keys") or []))
    if not boxed:
        return [[k[0], k[1], k[2], k[3]] + ([k[4]] if k[4] == "linear" else []) for k in cam_keys(world)]
    crop = dict(camera=dict(keys=boxed.get("crop") or [dict(t=0.0, cx=0.5, cy=0.5, w=1.0)]))
    times = sorted({k[0] for k in cam_keys(world)} | {k[0] for k in cam_keys(crop)})
    lin = any(k[4] == "linear" for k in cam_keys(world) + cam_keys(crop))
    out = []
    for t in times:
        wx, wy, ww = cam_at(world, t)
        cx, cy, cw = cam_at(crop, t)
        out.append([round(t, 4), round(cx + (wx - 0.5), 4), round(cy + (wy - 0.5), 4), round(min(cw * ww, 1.0), 4)] + (["linear"] if lin and t > times[0] else []))
    return out


def cinema_patches(pd):
    """({shot id: {cam, panel}}, notes) for the shots the agent directed in previz (only shots with an override). The camera box (folded
    into the panel crop on a panel shot) becomes the cinema `cam` key list; the first panel's w / cy / aspect become `look.panel`. Panel cx is
    not mappable (cinema panels are centred); a parallax move has no cinema equivalent. Both are reported in the notes."""
    sc = _read_json(os.path.join(pd, "previz", "scene.json"))
    if not sc or (sc.get("source") or {}).get("kind") != "designed":
        return {}, []
    e = effective(sc)
    ov = (sc.get("overrides") or {}).get("shots") or {}
    out, notes = {}, []
    for s in e["shots"]:
        o = ov.get(s["id"])
        if not o:
            continue
        patch = {}
        boxed = next((p for p in s.get("panels") or [] if p.get("kind") != "fullscreen"), None)
        if (o.get("camera") or {}).get("keys") or any("crop" in (v or {}) for v in (o.get("panels") or {}).values()):
            keys = _composed_cam(s)
            if keys:
                patch["cam"] = [[("end" if abs(k[0] - s["dur"]) < 1e-6 and n else k[0])] + k[1:] for n, k in enumerate(keys)]
            if camera_mode(s["camera"]["keys"]) == "parallax":
                notes.append(f"shot {s['id']}: parallax has no cinema equivalent; the lateral move is written as a pan of the content")
            elif boxed and camera_mode(s["camera"]["keys"]) != "locked":
                notes.append(f"shot {s['id']}: cinema has no camera over a panel, the move is applied to the content inside the panel")
        if "panels" in o and boxed:
            patch["panel"] = dict(w=round(_num(boxed.get("w"), 0.5), 4), cy=round(_num(boxed.get("cy"), 0.42), 4), aspect=round(_num(boxed.get("aspect"), 1.7778), 4))
            if abs(_num(boxed.get("cx"), 0.5) - 0.5) > 1e-3:
                notes.append(f"shot {s['id']}: panel cx {boxed['cx']} ignored (cinema panels are centred)")
        if patch:
            out[s["id"]] = patch
    return out, notes


def merge_cinema(shots, pd):
    """Apply `cinema_patches` to compiled cinema shots (in place). Returns the notes to print."""
    patches, notes = cinema_patches(pd)
    for s in shots:
        p = patches.get(s["id"])
        if not p:
            continue
        if "cam" in p:
            s["cam"] = p["cam"]
        if "panel" in p and (s.get("look") or {}).get("panel") is not None:
            s["look"]["panel"].update(p["panel"])
        s["notes"] = (s.get("notes", "") + "; directed in previz").lstrip("; ")
    return notes


# ---------------------------------------------------------------- CLI
def _ovr(scene, shot_id):
    return scene.setdefault("overrides", {}).setdefault("shots", {}).setdefault(str(shot_id), {})


def _shot(scene, shot_id):
    s = next((x for x in effective(scene)["shots"] if x["id"] == str(shot_id)), None)
    if not s:
        raise PrevizError(f"no shot {shot_id}: {', '.join(x['id'] for x in scene['shots'])}")
    return s


def _save_checked(target, scene):
    err, warn = problems(scene)
    if err:
        raise PrevizError("refused, the edit would break the scene:\n  " + "\n  ".join(err))
    _write_json(target.scene_path, scene)
    return warn


def _set_fields(d, args, names):
    for n in names:
        v = getattr(args, n, None)
        if v is not None:
            d[n] = v
    return d


def edit(target, args):
    """One nudge into overrides, from the `cam | panel | type | dur | projection | reset` subcommands. Returns the message to print."""
    sc = target.load()
    c = args.cmd
    if target.kind == "spec":
        raise PrevizError("this scene is compiled from promo.yaml: change the shot there (beats, cam, overlays), then re-run `promo previz animatic` "
                          "(it rebuilds only the shots that changed); a nudge here would be lost at the next sync")
    if c == "reset":
        o = sc.setdefault("overrides", {})
        if args.shot:
            (o.get("shots") or {}).pop(str(args.shot), None)
        else:
            o.clear()
        msg = f"cleared overrides of shot {args.shot}" if args.shot else "cleared every override"
    elif c == "projection":
        if args.shot:
            _shot(sc, args.shot)
            cam = _ovr(sc, args.shot).setdefault("camera", {})
            cam["projection"] = args.mode
        else:
            sc.setdefault("overrides", {}).setdefault("scene", {})["projection"] = args.mode
        msg = f"{'shot ' + args.shot if args.shot else 'scene'} projection -> {args.mode}"
    else:
        s = _shot(sc, args.shot)
        o = _ovr(sc, args.shot)
        if c == "cam":
            keys = cam_keys(s)
            cx = args.cx if args.cx is not None else keys[0][1]
            cy = args.cy if args.cy is not None else keys[0][2]
            if args.mode == "locked" and args.w is None:
                args.w = keys[0][3]
            ks = camera_preset(args.mode, s["dur"], args.amount, cx, cy, args.w, args.drift, args.ease)
            o["camera"] = dict(o.get("camera") or {}, keys=ks)
            if args.mode == "parallax" and not args.keep_projection:
                o["camera"]["projection"] = "persp"
            msg = f"shot {args.shot} camera -> {args.mode}"
        elif c == "panel":
            patch = o.setdefault("panels", {})
            if args.remove:
                patch[args.id] = None
            else:
                cur = dict(patch.get(args.id) or {})
                if args.id not in {p["id"] for p in s.get("panels") or []}:
                    cur = dict(dict(kind="floating", cx=0.5, cy=0.44, w=0.5, z=0.0, aspect=round(aspect_of(effective(sc)), 4)), **cur)
                _set_fields(cur, args, ("cx", "cy", "w", "z", "aspect", "kind"))
                if args.still:
                    cur["source"] = args.still
                patch[args.id] = cur
            msg = f"shot {args.shot} panel {args.id} {'removed' if args.remove else 'nudged'}"
        elif c == "type":
            patch = o.setdefault("type", {})
            if args.remove:
                patch[args.id] = None
            else:
                cur = dict(patch.get(args.id) or {})
                if args.id not in {p["id"] for p in s.get("type") or []}:
                    cur = dict(dict(text="", at=0.0, dur=s["dur"], size_pct=6.0, cx=0.5, cy=0.5), **cur)
                _set_fields(cur, args, ("cx", "cy", "at", "dur", "text"))
                if args.size is not None:
                    cur["size_pct"] = args.size
                patch[args.id] = cur
            msg = f"shot {args.shot} type {args.id} {'removed' if args.remove else 'nudged'}"
        elif c == "dur":
            o["dur"] = round(float(args.seconds), 4)
            msg = f"shot {args.shot} duration -> {o['dur']:g}s (later shots shift; promo.yaml timing is not changed)"
    warn = _save_checked(target, sc)
    return msg, warn


def _pd_of(project):
    from . import home
    p = project or os.getcwd()
    p = home.resolve(p) if project else p
    if os.path.isfile(p):
        p = os.path.dirname(os.path.abspath(p))
    return os.path.abspath(p)


def _pick_target(pd, args):
    ts = targets(pd, source=getattr(args, "source", None))
    want = getattr(args, "story", None)
    if want:
        ts = [t for t in ts if t.key == want]
        if not ts:
            raise PrevizError(f"no story {want} to block out")
    elif len(ts) > 1 and args.cmd not in ("show", "status", "build", "sync", "strip", "animatic"):
        raise PrevizError(f"{len(ts)} stories are picked: say which with --story ({', '.join(t.key for t in ts)})")
    return ts


def _print_show(pd, ts):
    for t in ts:
        st = target_status(t)
        if not st["scene"]:
            print(f"{t.label}: no scene yet: promo previz build")
            continue
        sc = t.load()
        e = effective(sc)
        print(f"previz of {t.label} ({sc['source']['kind']}): {len(e['shots'])} shots, {e['duration_s']:g}s, {e['projection']}, hash {st['hash']}")
        print(f"  {'shot':<5}{'t':>13}  {'framing':<10}{'camera':<10}{'proj':<6}panels / type")
        for s in e["shots"]:
            proj = (s.get("camera") or {}).get("projection") or e["projection"]
            pn = ", ".join(f"{p['id']}:{p['kind']} w{_num(p.get('w')):g}" + (f" crop {cam_keys(dict(camera=dict(keys=p['crop'])))[-1][3]:g}" if p.get("crop") else "") for p in s.get("panels") or []) or "-"
            ty = ", ".join(f"{c['id']} {str(c.get('text') or '(needs copy)')[:18]!r}" for c in s.get("type") or []) or "-"
            print(f"  {s['id']:<5}{s['t0']:>6.1f}-{s['t0'] + s['dur']:<6.1f} {s.get('framing', ''):<10}{camera_mode((s.get('camera') or {}).get('keys') or []):<10}{proj:<6}{pn}; {ty}")
        for w in st["warnings"]:
            print(f"  note: {w}")
        ov = sc.get("overrides") or {}
        n_ov = len(ov.get("shots") or {})
        print(f"  overrides: {n_ov} shot{'s' if n_ov != 1 else ''}" + (f", scene {ov['scene']}" if ov.get("scene") else ""))
        verdict = dict(ok=f"strip current ({st['engine']}): {st['png']}", missing="NO STRIP: promo previz strip", stale="strip is of an older scene: promo previz strip",
                       **{"no-scene": ""}).get(st["strip"], "")
        print(f"  {verdict}" + ("  (scene is behind its source: promo previz sync)" if st["behind"] else ""))


def main(argv=None, project=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="promo previz", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--project", default=project, help="project dir, promo.yaml or bare name (default: the cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def P(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("-p", "--project", default=argparse.SUPPRESS)
        p.add_argument("--story", help="the storyboard to block out when several are picked")
        p.add_argument("--from", dest="source", choices=("designed", "storyboard", "spec"),
                       help="force the source (default: the designed plan, else the picked storyboards, else a scene.json, else promo.yaml shots)")
        return p

    p = P("build", help="compile the scene (when missing or behind its source) and write the viewer")
    p.add_argument("--stills", action="store_true", help="texture the supplied stills onto the panels at low opacity")
    p.add_argument("--sync", action="store_true", help="re-sync from the source even if it did not change")
    P("sync", help="regenerate shots from the source, keep overrides")
    p = P("show", help="the blocked-out shots, hash, strip status"); p.add_argument("--json", action="store_true")
    p = P("strip", help="export the contact strip PNG")
    p.add_argument("--n", type=int, help="N evenly spaced frames instead of one per shot")
    p.add_argument("--at", type=float, nargs="+", help="these film times (s); a cheap look, never satisfies the gate")
    p.add_argument("--shot", help="start / middle / end of this shot; a cheap look, never satisfies the gate")
    p.add_argument("--ends", action="store_true", help="start and end of every shot (shows the camera move)")
    p.add_argument("--engine", choices=("auto", "chrome", "pil"), default="auto", help="auto: headless Chrome + Three.js, PIL wireframes when Chrome cannot draw")
    p.add_argument("--out", help="write the PNG here (does not record a gate strip)")
    p.add_argument("--stills", action="store_true")
    p.add_argument("--json", action="store_true")
    p = P("open", help="open the viewer in the browser"); p.add_argument("--print", dest="print_only", action="store_true"); p.add_argument("--stills", action="store_true")
    for name, hlp in (("cam", "set a shot's camera: locked | push | pullback | parallax"), ("panel", "nudge or add a panel"), ("type", "nudge or add a type box"),
                      ("dur", "change a shot's duration"), ("projection", "ortho | persp for the scene or one shot"), ("reset", "drop overrides (of one shot, or all)")):
        q = P(name, help=hlp)
        if name in ("cam", "panel", "type", "dur"):
            q.add_argument("shot")
        if name == "cam":
            q.add_argument("mode", choices=CAMERA_MODES)
            q.add_argument("--amount", type=float, default=0.06, help="push / pullback size as a fraction of the frame width")
            q.add_argument("--cx", type=float); q.add_argument("--cy", type=float); q.add_argument("--w", type=float)
            q.add_argument("--drift", type=float, default=0.04, help="parallax: lateral travel each way (fraction of the frame)")
            q.add_argument("--ease", choices=("smooth", "linear"), default="smooth")
            q.add_argument("--keep-projection", action="store_true", help="parallax normally switches the shot to perspective")
        elif name == "panel":
            q.add_argument("id"); q.add_argument("--cx", type=float); q.add_argument("--cy", type=float); q.add_argument("--w", type=float)
            q.add_argument("--z", type=float); q.add_argument("--aspect", type=float); q.add_argument("--kind", choices=PANEL_KINDS)
            q.add_argument("--still", help="a supplied still id from scene.stills"); q.add_argument("--remove", action="store_true")
        elif name == "type":
            q.add_argument("id"); q.add_argument("--cx", type=float); q.add_argument("--cy", type=float); q.add_argument("--size", type=float)
            q.add_argument("--at", type=float); q.add_argument("--dur", type=float); q.add_argument("--text"); q.add_argument("--remove", action="store_true")
        elif name == "dur":
            q.add_argument("seconds", type=float)
        elif name == "projection":
            q.add_argument("mode", choices=PROJECTIONS); q.add_argument("--shot", dest="shot")
        elif name == "reset":
            q.add_argument("shot", nargs="?")
        if name in ("cam", "panel", "type", "dur", "projection", "reset"):
            q.add_argument("--strip", dest="restrip", action="store_true", help="re-export the strip right after the edit")
    p = P("apply", help="write previz camera / panel nudges into the cinema shots (runs `promo designed apply`)")
    p.add_argument("--force", action="store_true")
    p = P("animatic", help="one clip per shot on the music grid + the joined animatic (only changed shots are rebuilt)")
    p.add_argument("--shot", nargs="+", help="re-render these shots even if unchanged")
    p.add_argument("--fps", type=int, default=ANIMATIC_FPS)
    p.add_argument("--size", help=f"WxH (default {ANIMATIC_H}p at the film's aspect)")
    p.add_argument("--audio", choices=("auto", "click", "music", "none"), default="auto", help="auto: the built music bed, else a beat click")
    p.add_argument("--force", action="store_true", help="re-render every shot")
    p.add_argument("--require", choices=("on", "off"), help="record whether this project's flow needs a current animatic (previz/settings.json), then render")
    p.add_argument("--bpm", type=float, help="record the tempo to cut against when there is no promo.yaml timeline yet (previz/settings.json)")
    p.add_argument("--json", action="store_true")
    p = P("shots", help="print a promo.yaml shots: skeleton (beats + cam) from the scene: timing and camera only")
    p.add_argument("--bpm", type=float)
    a = ap.parse_args(argv)
    pd = _pd_of(a.project)
    try:
        if a.cmd == "apply":
            from . import designed as D
            res = D.apply_shots(os.path.join(pd, "promo.yaml"), force=a.force)
            patches, notes = cinema_patches(pd)
            print(f"wrote {len(res['shots'])} cinema shots; directed in previz: {', '.join(sorted(patches)) or 'none (no overrides)'}")
            for n in notes:
                print(f"  note: {n}")
            return 0
        ts = _pick_target(pd, a)
        if a.cmd == "build":
            for t in ts:
                r = build(t, stills=a.stills, force_sync=a.sync)
                print(f"previz of {t.label}: {len(r['scene']['shots'])} shots, hash {r['hash']}\n  scene  {t.scene_path}\n  viewer {r['viewer']}")
                for w in r["warnings"]:
                    print(f"  note: {w}")
            print("next: promo previz strip   (then look at it; nudge with promo previz cam|panel|type ... --strip)")
        elif a.cmd == "sync":
            for t in ts:
                r = sync(t)
                d = r["diff"]
                print(f"synced {t.label}: +{len(d['added'])} -{len(d['removed'])} ~{len(d['changed'])} shots, hash {r['hash']}; overrides kept"
                      + (f"; orphaned overrides: {', '.join(r['orphans'])}" if r["orphans"] else ""))
                for w in r["warnings"]:
                    print(f"  note: {w}")
        elif a.cmd == "show":
            if a.json:
                print(json.dumps(status(pd, source=a.source), indent=1, default=str))
            else:
                _print_show(pd, ts)
        elif a.cmd == "strip":
            out = []
            for t in ts:
                r = strip(t, a.n, a.at, a.shot, a.ends, a.engine, a.out, a.stills)
                out.append(r)
                if not a.json:
                    print(f"strip of {t.label}: {r['png'] if 'png' in r else ''}  ({r['tiles']} tiles, {r['engine']}, {r['seconds']}s, scene {r['scene_hash']})"
                          + ("  [partial look: the gate still wants a full strip]" if r["partial"] or a.out else ""))
                    for w in r["warnings"]:
                        print(f"  note: {w}")
            if a.json:
                print(json.dumps(dict(ok=True, strips=out), indent=1))
        elif a.cmd == "animatic":
            if a.require or a.bpm:
                if a.bpm is not None and not 30 <= a.bpm <= 300:
                    raise PrevizError(f"--bpm {a.bpm:g} is outside 30-300")
                cur = _read_json(os.path.join(pd, "previz", "settings.json"), {}) or {}
                cur.update({k: v for k, v in (("animatic", a.require == "on" if a.require else None), ("bpm", a.bpm)) if v is not None})
                _write_json(os.path.join(pd, "previz", "settings.json"), cur)
            out = []
            for t in ts:
                r = animatic(t, a.shot, a.fps, a.size, a.audio, a.force)
                out.append(dict(r, story=t.key))
                if a.json:
                    continue
                print(f"animatic of {t.label}: {r['video']}  ({r['frames']} frames, {r['duration_s']:g}s, audio {r['audio']}, {r['seconds']}s)")
                print(f"  rebuilt: {' '.join(r['rebuilt']) or '-'}")
                print(f"  kept:    {' '.join(r['kept']) or '-'}" + (f"\n  shifted (kept, only moved in time): {' '.join(r['shifted'])}" if r["shifted"] else ""))
                for g in r["gaps"]:
                    print(f"  GAP {g['t0']:g}-{g['t1']:g}s: no shot covers it (a slate fills it; `promo check` timeline fails until the beats meet)")
                if r["grid"].get("assumed"):
                    print(f"  note: no tempo yet, cut against an assumed {ASSUMED_BPM:g} bpm (`--bpm N` records one; promo.yaml timeline.bpm wins)")
                if r["end_s"] is not None and abs(r["duration_s"] - r["end_s"]) > 1e-3:
                    print(f"  note: the animatic is {r['duration_s']:g}s, the timeline {r['end_s']:g}s")
                for w in r["warnings"]:
                    print(f"  note: {w}")
                print(f"  clips {os.path.dirname(r['video'])}/shots/   strip {r['strip']}   meta {r['meta']}")
            if a.json:
                print(json.dumps(dict(ok=True, animatics=out), indent=1))
            print("previz is a blockout, never footage: UI shots still need real recordings", file=sys.stderr)
        elif a.cmd == "shots":
            import yaml
            print(yaml.safe_dump(shots_skeleton(ts[0], a.bpm), sort_keys=False, default_flow_style=None).rstrip())
        elif a.cmd == "open":
            for t in ts:
                build(t, stills=a.stills)
                url = "file://" + os.path.abspath(t.viewer_path)
                print(url)
                if not a.print_only:
                    import webbrowser
                    if not webbrowser.open(url):
                        print("(no browser here: open the file on a machine that has one; Space plays, arrows scrub, [ ] jump shots, O toggles ortho / perspective)", file=sys.stderr)
        else:
            t = ts[0]
            msg, warn = edit(t, a)
            print(msg)
            for w in warn:
                print(f"  note: {w}")
            if getattr(a, "restrip", False):
                r = strip(t)
                print(f"strip: {r['png']} ({r['engine']}, {r['seconds']}s)")
            else:
                print("scene changed: the strip is stale until `promo previz strip` (or add --strip)")
    except (PrevizError, SpecError) as e:
        print(f"promo previz: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
