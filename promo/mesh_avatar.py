"""Mesh avatar hosts: a second renderer behind promo.live2d for characters made with Mesh Avatar Studio
(github.com/shinshin86/mesh-avatar-studio, MIT) from one illustration.

Opt-in per model: only a registry entry with `renderer: mesh` (`promo live2d add <studio project dir>`) takes this path;
every other host renders through Live2D exactly as before. The performance is the same: promo.perform builds layers on
standard Cubism parameter ids for a pseudo model (`MODEL`), they are flattened here (`perform.apply_layers`) and mapped
onto the runtime's parameters, and live2d/render.mjs drives live2d/mesh-page.html (npm `mesh-avatar`, a dependency in
live2d/package.json) frame by frame into the same RGBA pipe -> ffmpeg_out. Licence gate: promo.live2d.model_entry
(own | commissioned | original, licence + source, and `consent` for the person's own likeness).
"""
from __future__ import annotations

import json
import os

import numpy as np

from . import perform as PF
from .live2d import Live2DError

# Cubism ids promo.perform may drive on a mesh avatar, with the ranges Cubism would clamp them to.
RANGES = {
    "ParamAngleX": (-30, 30), "ParamAngleY": (-30, 30), "ParamAngleZ": (-30, 30),
    "ParamBodyAngleX": (-10, 10), "ParamBodyAngleZ": (-10, 10), "ParamBreath": (0, 1),
    "ParamEyeLOpen": (0, 1.25), "ParamEyeROpen": (0, 1.25), "ParamEyeLSmile": (0, 1), "ParamEyeRSmile": (0, 1),
    "ParamEyeBallX": (-1, 1), "ParamEyeBallY": (-1, 1),
    "ParamBrowLY": (-1, 1), "ParamBrowRY": (-1, 1), "ParamBrowLAngle": (-1, 1), "ParamBrowRAngle": (-1, 1),
    "ParamMouthOpenY": (0, 1), "ParamCheek": (0, 1),
    "ParamA": (0, 1), "ParamI": (0, 1), "ParamU": (0, 1), "ParamE": (0, 1), "ParamO": (0, 1),
}
DEFAULTS = {"ParamEyeLOpen": 1.0, "ParamEyeROpen": 1.0}
# The runtime's mouthForm is a vowel axis (-1 wide "i" .. 0 "a" .. +1 round "o"/"u"; sprites.js classifyVowel), not the
# Cubism smile axis, so it comes from perform's per-vowel weights only: mood smiles (ParamMouthForm / ParamMouthUp)
# would turn every syllable into an "i". Moods still show through eye smile, cheeks and brows.
VOWEL_FORM = {"A": 0.0, "I": -0.8, "U": 0.9, "E": -0.4, "O": 0.55}
# Pseudo model for promo.perform: what resolve_model gives a Live2D model, for the ids above.
MODEL = dict(param_ids=sorted(RANGES), groups={"EyeBlink": ["ParamEyeLOpen", "ParamEyeROpen"], "LipSync": ["ParamMouthOpenY"]},
             mouth={"open": ["ParamMouthOpenY"], "form": None, "vowels": {v: f"Param{v}" for v in PF.VOWELS}},
             expressions={}, motions={})
READBACK = {"ParamMouthOpenY": "mouthOpen"}


def is_avatar_dir(path):
    """A Mesh Avatar Studio project with built layers (rig.json + built/layers.json)."""
    p = os.path.abspath(os.path.expanduser(path))
    return os.path.isfile(os.path.join(p, "rig.json")) and os.path.isfile(os.path.join(p, "built", "layers.json"))


def build_ids(avatar):
    """Build stamps of the avatar's layers and drawn sprites: a rebuilt avatar changes them (cache keys)."""
    out = {"layers": json.load(open(os.path.join(avatar, "built", "layers.json"))).get("build")}
    sp = os.path.join(avatar, "built", "sprites", "sprites.json")
    if os.path.exists(sp):
        out["sprites"] = json.load(open(sp)).get("build")
    return out


# Once any drawn variant is imported the runtime stops moving the mesh eyelids and mouth (mesh-avatar 0.2.1,
# createMeshAvatar.js `sprites ? 1 : v`), so a partial set erases the eyes on every blink: all of these, or none.
DRAWINGS = ("eyes_closed", "eyes_half", "eyes_smile", "mouth_a", "mouth_a_half", "mouth_i", "mouth_o")


def missing_drawings(avatar):
    """Drawn variants a partial set lacks ([] = none imported, or all of them)."""
    sp = os.path.join(avatar, "built", "sprites", "sprites.json")
    if not os.path.exists(sp):
        return []
    have = {k.rsplit("_", 1)[0] if k.startswith("eyes_") else k for k in json.load(open(sp)).get("layers", {})}
    return [d for d in DRAWINGS if d not in have]


def signature(entry):
    """Cache-key part for a registry entry: the avatar's current build stamps for a mesh avatar (rebuilt in the
    studio = new layers), None for a Live2D model or a missing avatar (the render step reports that)."""
    if not entry or entry.get("renderer") != "mesh" or not is_avatar_dir(entry.get("avatar", "")):
        return None
    return build_ids(os.path.abspath(os.path.expanduser(entry["avatar"])))


def resolve(name, entry):
    """The model dict promo.live2d / promo.perform use, for a registered mesh avatar."""
    avatar = os.path.abspath(os.path.expanduser(entry["avatar"]))
    if not is_avatar_dir(avatar):
        raise Live2DError(f"{name}: mesh avatar {avatar} is missing or has no built layers (rig.json + built/layers.json); "
                              f"rebuild it in Mesh Avatar Studio")
    rig = json.load(open(os.path.join(avatar, "rig.json")))
    return dict(entry, id=name, dir=avatar, renderer="mesh", image=[rig["image"]["width"], rig["image"]["height"]],
                build=build_ids(avatar), notice={"short": "", "long": ""}, **json.loads(json.dumps(MODEL)))


def values(layers, n):
    """perform layers (Cubism ids) -> {runtime parameter: per-frame list}. Left / right follow the runtime: its eye 0 is
    image-left, driven by eyeROpen / eyeSmile, as Cubism's R is the character's right."""
    v = {pid: PF.apply_layers(layers[pid], n, DEFAULTS.get(pid, 0.0), *RANGES[pid]) if pid in layers else np.full(n, DEFAULTS.get(pid, 0.0))
         for pid in RANGES}
    w = np.stack([v[f"Param{x}"] for x in PF.VOWELS])
    form = (np.array([VOWEL_FORM[x] for x in PF.VOWELS])[:, None] * w).sum(0) / np.maximum(w.sum(0), 1e-6)
    out = dict(angleX=v["ParamAngleX"], angleY=v["ParamAngleY"], angleZ=v["ParamAngleZ"], bodyAngleX=v["ParamBodyAngleX"],
               bodyAngleZ=v["ParamBodyAngleZ"], breath=v["ParamBreath"], eyeLOpen=v["ParamEyeLOpen"], eyeROpen=v["ParamEyeROpen"],
               eyeSmile=v["ParamEyeRSmile"], eyeSmileL=v["ParamEyeLSmile"], gazeX=v["ParamEyeBallX"], gazeY=v["ParamEyeBallY"],
               browY=(v["ParamBrowLY"] + v["ParamBrowRY"]) / 2, browAngle=(v["ParamBrowLAngle"] + v["ParamBrowRAngle"]) / 2,
               mouthOpen=v["ParamMouthOpenY"], mouthForm=np.where(w.sum(0) > 1e-3, form, 0.0), blush=v["ParamCheek"])
    return {k: [round(float(x), 4) for x in a] for k, a in out.items()}


def job(model, *, width, height, fps, frames, seed, warmup, frame, layers, readback_path, premultiplied, chromium, settle=0.0):
    """The render.mjs job for a mesh avatar (same frame / readback contract as a Live2D job). `settle` = extra seconds
    each frame is held before capture: stills jump pose every frame, and the runtime cross-fades drawn eyes / mouths."""
    return dict(page="mesh-page.html", avatarDir=model["dir"], width=width, height=height, fps=fps, frames=frames, seed=seed, warmup=warmup,
                frame=frame, values=values(layers, frames), readback=list(READBACK), readbackMap=READBACK, readbackPath=readback_path,
                premultiplied=premultiplied, chromium=chromium, settle=settle)


def entry(path, name, licence, source_url, ctype, credit=None, likeness=None, consent=None):
    """Registry entry for `promo live2d add` on a Mesh Avatar Studio project (anchors are measured afterwards)."""
    from PIL import Image
    avatar = os.path.abspath(os.path.expanduser(path))
    alpha = np.asarray(Image.open(os.path.join(avatar, "built", "base.png")).convert("RGBA"))[..., 3]
    e = dict(name=name, renderer="mesh", character_type=ctype, avatar=avatar, licence=licence, source_url=source_url, credit=credit or "",
             mouth=MODEL["mouth"], moods={}, rest_smile=0.0, cut_bottom=bool((alpha[-1] > 128).any()))
    if likeness:
        e.update(likeness=likeness, consent=consent or "")
    return e
