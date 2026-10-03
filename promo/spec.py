"""Spec loading: promo.yaml -> validated, env-expanded, path-resolved `Spec` + `Timeline`.

Everything project-specific lives in the spec. All paths are resolved relative to the spec file's directory and
support ``${VAR:-default}`` expansion. The spec is linted for forbidden UI-editing keys (team rule: never edit the
app's UI in post; reshoot instead).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from fractions import Fraction

import yaml

FORBIDDEN_KEYS = {"debubble", "paint_out", "inpaint", "ui_edit"}
FORBIDDEN_MSG = ("key '{key}' at {where}: painting out / inpainting / editing the app's UI in post is not supported. "
                 "Team rule: never edit the app's UI in post; reshoot the footage instead.")


class SpecError(Exception):
    pass


# ---------------------------------------------------------------- env expansion / lint
_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(obj):
    """Recursively expand ``${VAR}`` / ``${VAR:-default}`` in every string of a YAML tree."""
    if isinstance(obj, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1)) or (m.group(2) if m.group(2) is not None else ""), obj)
    if isinstance(obj, list):
        return [expand_env(v) for v in obj]
    if isinstance(obj, dict):
        return {k: expand_env(v) for k, v in obj.items()}
    return obj


def lint(obj, where="spec"):
    """Reject forbidden keys anywhere in the tree (debubble / paint_out / inpaint / ui_edit)."""
    problems = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_KEYS:
                problems.append(FORBIDDEN_MSG.format(key=k, where=where))
            problems += lint(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            problems += lint(v, f"{where}[{i}]")
    return problems


def number(v):
    """Accept floats/ints or simple fractions like ``"1/6"`` / ``"8.25/3.9"`` in the spec."""
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str) and re.fullmatch(r"\s*[-+0-9.eE]+\s*(/\s*[-+0-9.eE]+\s*)?", v):
        if "/" in v:
            a, b = v.split("/")
            return float(a) / float(b)          # same float expression as the legacy `a / b`
        return float(v)
    raise SpecError(f"not a number: {v!r}")


def stable_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------- timeline
class Timeline:
    """Beat grid. t(beat) = beat * 60 / bpm; frames(b0, b1) = round(t(b1)*fps) - round(t(b0)*fps) (legacy formula)."""

    def __init__(self, bpm, beats, fps):
        self.bpm, self.beats, self.fps = bpm, beats, fps
        self.B = 60.0 / bpm            # seconds per beat, same expression as the legacy `B = 60.0 / 98.0`

    def t(self, beat):
        return beat * self.B

    def frames(self, b0, b1):
        return round(self.t(b1) * self.fps) - round(self.t(b0) * self.fps)


@dataclass
class Shot:
    """One shot on the timeline. `cfg` is the raw spec dict; times are global seconds / frame counts."""
    id: str
    b0: float
    b1: float
    t0: float
    t1: float
    f0: int
    n: int
    fps: int
    cfg: dict = field(repr=False)

    @property
    def dur(self):
        """Shot duration in seconds as used by every legacy renderer: n / FPS."""
        return self.n / self.fps

    @property
    def type(self):
        return self.cfg.get("type", "clip")

    def get(self, key, default=None):
        return self.cfg.get(key, default)

    def __getitem__(self, key):
        return self.cfg[key]


# ---------------------------------------------------------------- spec
class Spec:
    def __init__(self, path, raw, scale=None):
        self.path = os.path.abspath(path)
        self.root = os.path.dirname(self.path)
        self.raw = raw
        problems = lint(raw)
        if problems:
            raise SpecError("; ".join(problems))
        self.name = raw.get("output", {}).get("name") or raw.get("project", {}).get("name", "promo")
        self.title = raw.get("project", {}).get("title", self.name)
        out = raw.get("output", {})
        self.fps = int(out.get("fps", 30))
        self.duration = float(out.get("duration", 60.0))
        env_scale = os.environ.get("PROMO_SCALE")
        res_scale = {1080: 1, 2160: 2}.get(int(out.get("resolution", 1080)))
        if res_scale is None:
            raise SpecError("output.resolution must be 1080 or 2160")
        self.scale = int(scale or env_scale or res_scale)
        if self.scale not in (1, 2):
            raise SpecError("scale must be 1 or 2")
        self.OW, self.OH = 1920 * self.scale, 1080 * self.scale
        paths = raw.get("paths", {})
        self.build = self.resolve(paths.get("build", "build"))
        self.out = self.resolve(paths.get("out", "out"))
        tl = raw.get("timeline", {})
        self.timeline = Timeline(tl.get("bpm", 98), tl.get("beats", 98), self.fps)
        self.shots = self._build_shots()
        self.plugins = [self.resolve(p) for p in raw.get("plugins", [])]
        self._plugins_loaded = False

    # -- paths
    def resolve(self, p):
        p = os.path.expanduser(str(p))
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.root, p))

    def clip_path(self, clip_id):
        """Absolute path of a footage clip, resolved through footage/manifest.yaml by clip id (unknown id = error)."""
        from . import footage
        return footage.clip_path(self, clip_id)

    footage_path = clip_path        # name used by project plugins

    @property
    def tag(self):
        return str(self.OH)

    @property
    def res_dir(self):
        return os.path.join(self.build, f"{self.OW}x{self.OH}")

    @property
    def segs_dir(self):
        return os.path.join(self.res_dir, "segs")

    @property
    def audio_dir(self):
        return os.path.join(self.build, "audio")

    @property
    def vo_dir(self):
        return os.path.join(self.build, "vo")

    @property
    def sfx_dir(self):
        return os.path.join(self.build, "sfx")

    def seg_path(self, sid):
        return os.path.join(self.segs_dir, f"{sid}.mp4")

    def output_path(self, suffix=""):
        return os.path.join(self.out, f"{self.name}-{self.tag}{suffix}.mp4")

    @property
    def masters(self):
        ms = self.raw.get("mix", {}).get("masters") or [{"name": "web", "suffix": "", "lufs": -14.0, "ceiling": -1.2, "max_true_peak": -1.0}]
        return ms

    # -- shots / timeline
    def _build_shots(self):
        shots, seen = [], set()
        for s in self.raw.get("shots", []):
            sid = str(s["id"])
            if sid in seen:
                raise SpecError(f"duplicate shot id {sid}")
            seen.add(sid)
            b0, b1 = s["beats"]
            tl = self.timeline
            shots.append(Shot(id=sid, b0=b0, b1=b1, t0=tl.t(b0), t1=tl.t(b1), f0=round(tl.t(b0) * self.fps),
                              n=tl.frames(b0, b1), fps=self.fps, cfg=s))
        return shots

    def shot(self, sid):
        for s in self.shots:
            if s.id == str(sid):
                return s
        raise SpecError(f"unknown shot {sid}")

    def g(self, sid, t_out):
        """Global time of shot-local output time: round(t0 + t_out, 3) (legacy `g`)."""
        return round(self.shot(sid).t0 + t_out, 3)

    def total_frames(self):
        return sum(s.n for s in self.shots)

    def validate(self):
        """Structural checks that do not need media: contiguity, beat range, known shot types."""
        errs = []
        shots = self.shots
        if not shots:
            errs.append("no shots")
        else:
            if shots[0].b0 != 0:
                errs.append("first shot must start at beat 0")
            for a, b in zip(shots, shots[1:]):
                if a.b1 != b.b0:
                    errs.append(f"shots {a.id} and {b.id} are not contiguous ({a.b1} != {b.b0})")
            if shots[-1].b1 != self.timeline.beats:
                errs.append(f"last shot ends at beat {shots[-1].b1}, timeline has {self.timeline.beats}")
        return errs

    # -- subtree hashing (for stamps)
    def subtree(self, *keys):
        return {k: self.raw.get(k) for k in keys}

    # -- plugins
    def load_plugins(self):
        """Import project plugin files (they register shot types via @shot_type)."""
        if self._plugins_loaded:
            return
        for i, p in enumerate(self.plugins):
            if not os.path.exists(p):
                raise SpecError(f"plugin not found: {p}")
            name = f"promo_plugin_{i}_{os.path.splitext(os.path.basename(p))[0]}"
            mod_spec = importlib.util.spec_from_file_location(name, p)
            mod = importlib.util.module_from_spec(mod_spec)
            sys.modules[name] = mod
            mod_spec.loader.exec_module(mod)
        self._plugins_loaded = True


def load_spec(path="promo.yaml", scale=None, plugins=True) -> Spec:
    if not os.path.exists(path):
        raise SpecError(f"spec not found: {path}")
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    raw = expand_env(raw)
    spec = Spec(path, raw, scale=scale)
    if plugins:
        spec.load_plugins()
    return spec


def resolve_cam_keys(keys, dur):
    """Camera keys [[t, cx, cy, w(, ease)], ...] with the literal "end" meaning the shot duration."""
    out = []
    for k in keys:
        k = list(k)
        if k[0] == "end":
            k[0] = dur
        out.append(tuple(k))
    return out
