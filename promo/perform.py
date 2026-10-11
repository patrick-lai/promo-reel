"""Live2D performance layer: what makes a host look alive beyond blink, breath and a flapping mouth.

Everything is precomputed per frame in Python (deterministic, seeded) and handed to the renderer as per-parameter LAYERS
(`promo.live2d.host_tracks` -> live2d/page.html). A parameter's value each frame is

    base  = its `set` track (else the model's default)
    base  = base * (1 - w) + v * w     for each `blend` layer (exp3 Overwrite, model motions)
    base += v                          for each `add` layer (moods, gestures, emphasis, saccades)
    base *= v                          for each `mul` layer (exp3 Multiply, e.g. eyes wider)

Pieces (all optional per line of the script; a line is {t0, t1, mood, gesture, look, react} in global seconds):
  visemes   F1/F2 per frame (LPC) -> soft A/I/U/E/O weights (nearest speaker-normalised prototype, softmax) x the
            mouth-open envelope. Vowel rigs (Mao: ParamA..ParamO, model entry `mouth: {vowels: {A: ParamA, ...}}`) get
            the five shapes; rigs with ParamMouthForm get a form from the same weights (I/E wide, O/U round).
  moods     neutral happy laugh excited thinking surprised smug sad serious. A model's `moods:` map in
            live2d/assets.yaml names an exp3 file and/or parameter targets; otherwise GENERIC_MOODS on the standard
            Cubism IDs. Eased in ~0.3 s (an exp3's own FadeInTime), held through the line plus a tail.
  gestures  procedural nod, shake, tilt, lean_in, laugh_bounce, shrug, look_away; `motion:<name>` samples the model's
            own motion3 curves (linear / bezier / stepped / inverse-stepped) with fade weights.
  prosody   onset peaks of the voice raise the brows and drive small head beats.
  gaze      eye saccades (60 ms steps every 0.8-2.5 s), `look:` camera | partner | screen | away; eyes lead, the head
            follows; a listening host turns to the speaker and nods at their phrase ends.
  body      slow body Z sway, shoulder breath, a resting smile when not talking (scaled by the mood).
"""
from __future__ import annotations

import json
import os

import numpy as np

MOODS = ("neutral", "happy", "laugh", "excited", "thinking", "surprised", "smug", "sad", "serious")
GESTURES = ("nod", "shake", "tilt", "lean_in", "laugh_bounce", "shrug", "look_away")
LOOKS = ("camera", "partner", "screen", "away")
VOWELS = ("A", "I", "U", "E", "O")
# (F1, F2) Hz prototypes, a female-ish average (Japanese / English vowel charts); a speaker's own median shifts them
PROTO = {"A": (800.0, 1350.0), "I": (330.0, 2550.0), "U": (380.0, 1450.0), "E": (560.0, 2150.0), "O": (520.0, 920.0)}
FORM = {"A": 0.15, "I": 0.85, "U": -0.55, "E": 0.6, "O": -0.85}      # mouth form per vowel (+ wide, - round)
VOWEL_GAIN = {"A": 1.0, "I": 0.75, "U": 0.8, "E": 0.9, "O": 1.0}

# Generic mood targets on standard Cubism IDs: (id, mode, value). add = offset, mul = factor (eyes).
_SMILE_EYES = [("ParamEyeLSmile", "add", 1.0), ("ParamEyeRSmile", "add", 1.0)]


def _both(stem, mode, v, v2=None):
    return [(f"Param{stem.replace('*', 'L')}", mode, v), (f"Param{stem.replace('*', 'R')}", mode, v if v2 is None else v2)]


GENERIC_MOODS = {
    "neutral": [],
    "happy": _both("Eye*Smile", "add", 0.6) + _both("Eye*Open", "mul", 0.85) + [("ParamMouthForm", "add", 1.0), ("ParamMouthUp", "add", 0.7),
                                                                              ("ParamCheek", "add", 0.35)] + _both("Brow*Y", "add", 0.3),
    # a laugh: closed smiling eyes (^^) and an open mouth on top of the lip sync
    "laugh": _both("Eye*Smile", "add", 1.0) + _both("Eye*Open", "mul", 0.0) + [("ParamMouthForm", "add", 1.0), ("ParamMouthUp", "add", 1.0),
                                                                               ("ParamMouthOpenY", "add", 0.35), ("ParamA", "add", 0.3),
                                                                               ("ParamCheek", "add", 0.6)] + _both("Brow*Y", "add", 0.4),
    "excited": _both("Eye*Open", "mul", 1.15) + _both("Eye*Smile", "add", 0.25) + _both("Brow*Y", "add", 0.6)
    + [("ParamMouthForm", "add", 0.6), ("ParamMouthUp", "add", 0.5), ("ParamCheek", "add", 0.3)],
    "thinking": [("ParamBrowLY", "add", 0.35), ("ParamBrowRY", "add", -0.15)] + _both("Brow*Form", "add", -0.3)
    + [("ParamMouthForm", "add", -0.35), ("ParamMouthDown", "add", 0.25)] + _both("Eye*Open", "mul", 0.9),
    "surprised": _both("Eye*Open", "mul", 1.25) + _both("Brow*Y", "add", 0.85) + _both("Brow*Form", "add", 0.45)
    + [("ParamMouthForm", "add", -0.4), ("ParamEyeBallForm", "add", -0.4)],
    "smug": _both("Eye*Open", "mul", 0.72) + _both("Eye*Smile", "add", 0.35) + [("ParamMouthForm", "add", 0.6), ("ParamMouthUp", "add", 0.5),
                                                                              ("ParamBrowLY", "add", 0.3), ("ParamBrowRY", "add", -0.1)],
    "sad": _both("Brow*Angle", "add", -0.7) + _both("Brow*Form", "add", -0.7) + _both("Brow*Y", "add", -0.15)
    + [("ParamMouthForm", "add", -0.8), ("ParamMouthDown", "add", 0.7), ("ParamMouthUp", "add", -0.4)] + _both("Eye*Open", "mul", 0.85),
    "serious": _both("Brow*Form", "add", -0.5) + _both("Brow*Y", "add", -0.25) + _both("Brow*Angle", "add", 0.35)
    + [("ParamMouthForm", "add", -0.3), ("ParamMouthUp", "add", -0.3)] + _both("Eye*Open", "mul", 0.92),
}
REST_SMILE = {"neutral": 1.0, "happy": 1.0, "laugh": 1.0, "excited": 1.0, "smug": 1.0, "thinking": 0.4, "surprised": 0.0, "sad": 0.0, "serious": 0.2}
MIRROR = {"laugh": ("happy", 0.55), "happy": ("happy", 0.45), "excited": ("happy", 0.35), "surprised": ("surprised", 0.3)}
# which expressions a `promo live2d add` maps to which mood, by words in the expression's name
MOOD_WORDS = {"happy": ("smile", "happy", "joy", "glad"), "laugh": ("laugh", "lol"), "excited": ("excite", "sparkle", "star", "kira"),
              "surprised": ("surprise", "shock", "odoroki"), "sad": ("sad", "cry", "tear", "worr", "trouble"),
              "serious": ("angry", "anger", "serious", "pout", "mad"), "smug": ("smug", "doya", "proud", "wink"),
              "thinking": ("think", "hmm", "ponder", "confus")}


class PerformError(ValueError):
    pass


# ---------------------------------------------------------------- layers
def new_layers():
    return {}


def _layer(L, pid, mode, n):
    d = L.setdefault(pid, {})
    if mode in ("add",):
        return d.setdefault("add", np.zeros(n))
    if mode == "mul":
        return d.setdefault("mul", np.ones(n))
    raise PerformError(mode)


def add(L, pid, arr):
    a = _layer(L, pid, "add", len(arr))
    a += arr


def mul(L, pid, arr):
    a = _layer(L, pid, "mul", len(arr))
    a *= arr


def setv(L, pid, arr):
    L.setdefault(pid, {})["set"] = np.asarray(arr, float)


def blend(L, pid, v, w):
    L.setdefault(pid, {}).setdefault("blend", []).append((np.asarray(v, float), np.asarray(w, float)))


def apply_layers(d, n=None, default=0.0, lo=None, hi=None):
    """Final per-frame values of one parameter from its layer dict, exactly as live2d/page.html applies them
    (set -> blend -> add -> mul; clamped after every step when the range is known, as Cubism does)."""
    clip = (lambda x: np.clip(x, lo, hi)) if lo is not None and hi is not None else (lambda x: x)
    if n is None:
        n = max(len(v) if not isinstance(v, list) else len(v[0][0]) for v in d.values())
    x = clip(np.asarray(d["set"], float).copy()) if d.get("set") is not None else np.full(n, float(default))
    for v, w in d.get("blend") or []:
        x = clip(x * (1 - w) + v * w)
    if d.get("add") is not None:
        x = clip(x + d["add"])
    if d.get("mul") is not None:
        x = clip(x * d["mul"])
    return x


def job_tracks(L, nd=4):
    """Layers -> the renderer's job format: {id: [{mode, v[, w]}, ...]} (order set, blend, add, mul)."""
    r = lambda a: [round(float(x), nd) for x in a]
    out = {}
    for pid, d in L.items():
        if isinstance(d, np.ndarray):
            d = {"set": d}
        ls = []
        if d.get("set") is not None:
            ls.append(dict(mode="set", v=r(d["set"])))
        for v, w in d.get("blend") or []:
            ls.append(dict(mode="blend", v=r(v), w=r(w)))
        if d.get("add") is not None and np.any(np.abs(d["add"]) > 1e-6):
            ls.append(dict(mode="add", v=r(d["add"])))
        if d.get("mul") is not None and np.any(np.abs(d["mul"] - 1) > 1e-6):
            ls.append(dict(mode="mul", v=r(d["mul"])))
        if ls:
            out[pid] = ls
    return out


# ---------------------------------------------------------------- smoothing / envelopes
def follow(x, fps, tau):
    """One-pole smoother (time constant tau s)."""
    k = 1 - np.exp(-(1 / fps) / max(tau, 1e-6))
    out = np.empty(len(x))
    v = float(x[0]) if len(x) else 0.0
    for i, s in enumerate(x):
        v += (s - v) * k
        out[i] = v
    return out


def _ease(u):
    u = np.clip(u, 0, 1)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def window(n, fps, t0, t1, fade_in=0.3, fade_out=0.4):
    """0..1 weight: eased in over fade_in from t0, 1 until t1, eased out over fade_out after t1."""
    t = np.arange(n) / fps
    a = _ease((t - t0) / fade_in) if fade_in > 0 else (t >= t0).astype(float)
    b = 1 - _ease((t - t1) / fade_out) if fade_out > 0 else (t < t1).astype(float)
    return np.minimum(a, b)


def merge_spans(spans, gap=0.25):
    """Merge [t0, t1] spans closer than `gap` s (two lines of the same mood stay in it across a short pause)."""
    out = []
    for a, b in sorted(spans):
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


# ---------------------------------------------------------------- visemes
def _lpc(x, order):
    """LPC coefficients by the autocorrelation method (Levinson-Durbin). Returns a (1, a1..ap) or None."""
    r = np.correlate(x, x, "full")[len(x) - 1: len(x) + order]
    if r[0] <= 1e-10:
        return None
    a = np.zeros(order + 1)
    a[0] = 1.0
    e = r[0]
    for i in range(1, order + 1):
        k = -(r[i] + np.dot(a[1:i], r[i - 1:0:-1])) / e
        a[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a[i] = k
        e *= 1 - k * k
        if e <= 0:
            return None
    return a


def formants(seg, sr):
    """(F1, F2) of a voiced segment (any sr; analysed at ~10 kHz), or None."""
    if len(seg) < 64 or np.sqrt(np.mean(seg ** 2)) < 1e-3:
        return None
    if sr > 12000:
        from scipy.signal import resample_poly
        f = 10000
        g = np.gcd(int(sr), f)
        seg = resample_poly(seg, f // g, int(sr) // g)
        sr = f
    x = np.append(seg[0], seg[1:] - 0.63 * seg[:-1]) * np.hamming(len(seg))
    a = _lpc(x, 10)
    if a is None:
        return None
    roots = [r for r in np.roots(a) if np.imag(r) > 0]
    cand = []
    for r in roots:
        f = np.angle(r) * sr / (2 * np.pi)
        bw = -sr / np.pi * np.log(max(abs(r), 1e-9))
        if 150 < f < 3800 and bw < 500:
            cand.append(f)
    cand.sort()
    f1 = next((f for f in cand if 200 <= f <= 1100), None)
    if f1 is None:
        return None
    f2 = next((f for f in cand if f >= f1 + 180 and f <= 3200), None)
    return (f1, f2) if f2 else None


def vowel_weights(f1, f2, proto=PROTO, temp=0.35):
    """Soft A/I/U/E/O weights from (F1, F2): softmax of -distance (log2 space) to each prototype."""
    d = np.array([((np.log2(f1) - np.log2(p[0])) / 0.45) ** 2 + ((np.log2(f2) - np.log2(p[1])) / 0.55) ** 2 for p in (proto[v] for v in VOWELS)])
    w = np.exp(-(d - d.min()) / temp)
    return dict(zip(VOWELS, w / w.sum()))


def speaker_proto(fs):
    """Prototypes shifted to a speaker: the ratio of the speaker's median F1 / F2 to the prototype geometric means."""
    if len(fs) < 8:
        return PROTO
    f1m, f2m = np.median([f[0] for f in fs]), np.median([f[1] for f in fs])
    g1 = np.exp(np.mean([np.log(p[0]) for p in PROTO.values()]))
    g2 = np.exp(np.mean([np.log(p[1]) for p in PROTO.values()]))
    k1, k2 = np.clip(f1m / g1, 0.75, 1.3), np.clip(f2m / g2, 0.75, 1.3)
    return {v: (p[0] * k1, p[1] * k2) for v, p in PROTO.items()}


def visemes(y, sr, fps, n, open_track, win_s=0.03):
    """Per-frame vowel weights (each x the mouth-open envelope) and a mouth form, from the voice.
    Returns {"A".."O": arrays (sum = open), "form": array, "weights": (n, 5) raw weights}."""
    half = int(win_s * sr / 2)
    fs = [None] * n
    for i in range(n):
        if open_track[i] < 0.04:
            continue
        c = int((i + 0.5) / fps * sr)
        seg = y[max(0, c - half): c + half]
        fs[i] = formants(seg.astype(np.float64), sr)
    proto = speaker_proto([f for f in fs if f])
    W = np.zeros((n, 5))
    last = np.array([0.6, 0.1, 0.1, 0.1, 0.1])            # unvoiced / unknown frames hold the last shape (start: A-ish)
    for i in range(n):
        if fs[i]:
            last = np.array([vowel_weights(*fs[i], proto=proto)[v] for v in VOWELS])
        W[i] = last
    for k in range(5):                                     # 40 ms smoothing so shapes glide, never flicker
        W[:, k] = follow(W[:, k], fps, 0.04)
    W /= W.sum(1, keepdims=True)
    out = {v: W[:, k] * open_track * VOWEL_GAIN[v] for k, v in enumerate(VOWELS)}
    form = (W * np.array([FORM[v] for v in VOWELS])).sum(1) * np.minimum(1.0, open_track * 3)
    out.update(form=form, weights=W)
    return out


# ---------------------------------------------------------------- exp3 / motion3
def load_exp3(path):
    with open(path) as f:
        d = json.load(f)
    return dict(fade_in=float(d.get("FadeInTime", 1.0)), fade_out=float(d.get("FadeOutTime", 1.0)),
                params=[(p["Id"], p.get("Blend", "Add"), float(p["Value"])) for p in d.get("Parameters", [])])


def exp3_targets(exp):
    """exp3 parameters -> (id, mode, value) with mode add | mul | set (Overwrite)."""
    m = {"Add": "add", "Multiply": "mul", "Overwrite": "set"}
    return [(pid, m.get(b, "add"), v) for pid, b, v in exp["params"]]


def apply_targets(L, targets, w, scale=1.0):
    """Mood / expression targets at per-frame weight w (exp3 maths): add v*w, multiply 1 + (v - 1) w, overwrite blend."""
    for pid, mode, v in targets:
        if mode == "add":
            if abs(v) > 1e-9:
                add(L, pid, v * scale * w)
        elif mode == "mul":
            if abs(v - 1) > 1e-9:
                mul(L, pid, 1 + (v - 1) * scale * w)
        elif mode == "set":
            blend(L, pid, np.full(len(w), v), np.clip(w * scale, 0, 1))


def _bezier(p0, p1, p2, p3, t):
    """Value of a motion3 bezier segment at time t (de Casteljau on the time-normalised parameter)."""
    u = (t - p0[0]) / (p3[0] - p0[0]) if p3[0] != p0[0] else 0.0
    u = min(max(u, 0.0), 1.0)
    a = [p0[1] + (p1[1] - p0[1]) * u, p1[1] + (p2[1] - p1[1]) * u, p2[1] + (p3[1] - p2[1]) * u]
    b = [a[0] + (a[1] - a[0]) * u, a[1] + (a[2] - a[1]) * u]
    return b[0] + (b[1] - b[0]) * u


def parse_segments(seg):
    """motion3 `Segments` -> list of (kind, points) with points as (t, v) tuples, kind 0 linear 1 bezier 2 stepped 3 inverse stepped."""
    out = []
    p = (seg[0], seg[1])
    i = 2
    while i < len(seg):
        k = int(seg[i])
        if k == 1:
            pts = [p, (seg[i + 1], seg[i + 2]), (seg[i + 3], seg[i + 4]), (seg[i + 5], seg[i + 6])]
            i += 7
        else:
            pts = [p, (seg[i + 1], seg[i + 2])]
            i += 3
        out.append((k, pts))
        p = pts[-1]
    return out, (seg[0], seg[1])


def eval_curve(parsed, t):
    segs, first = parsed
    if not segs or t <= segs[0][1][0][0]:
        return first[1] if not segs else segs[0][1][0][1]
    for k, pts in segs:
        if t <= pts[-1][0]:
            if k == 0:
                (t0, v0), (t1, v1) = pts
                return v0 + (v1 - v0) * ((t - t0) / (t1 - t0) if t1 != t0 else 1.0)
            if k == 1:
                return _bezier(*pts, t)
            if k == 2:
                return pts[0][1]
            return pts[1][1]
    return segs[-1][1][-1][1]


def load_motion3(path):
    with open(path) as f:
        d = json.load(f)
    m = d["Meta"]
    curves = {c["Id"]: parse_segments(c["Segments"]) for c in d["Curves"] if c.get("Target") == "Parameter"}
    return dict(duration=float(m["Duration"]), loop=bool(m.get("Loop")), fade_in=float(m.get("FadeInTime", 0.5) or 0.5),
                fade_out=float(m.get("FadeOutTime", 0.5) or 0.5), curves=curves)


# parameters a model motion never drives (lip sync, the blink timer and the gaze layer own these)
MOTION_SKIP = ("ParamMouthOpenY", "ParamA", "ParamI", "ParamU", "ParamE", "ParamO", "ParamEyeLOpen", "ParamEyeROpen")


def motion_layers(L, mot, n, fps, t0, dur, skip=MOTION_SKIP, weight=1.0):
    """Blend a motion3's curves in from t0 for `dur` s (looping if the motion loops and is shorter) with its fades."""
    t = np.arange(n) / fps
    w = window(n, fps, t0, t0 + dur, mot["fade_in"], mot["fade_out"]) * weight
    on = w > 1e-4
    if not on.any():
        return
    tl = t[on] - t0
    if mot["loop"] and mot["duration"] > 0:
        tl = np.mod(np.maximum(tl, 0), mot["duration"])
    for pid, parsed in mot["curves"].items():
        if pid in skip:
            continue
        v = np.zeros(n)
        v[on] = [eval_curve(parsed, x) for x in tl]
        blend(L, pid, v, w)


# ---------------------------------------------------------------- gestures
def _pulse(t, c, width):
    """Smooth 0..1..0 bump centred at c, total width `width` s."""
    u = (t - (c - width / 2)) / width
    return np.where((u > 0) & (u < 1), np.sin(np.pi * np.clip(u, 0, 1)) ** 2, 0.0)


def gesture(L, kind, n, fps, t0, dur, toward=1.0, shoulders=("ParamShoulder", "ParamLeftShoulderUp", "ParamRightShoulderUp")):
    """Procedural gesture as add layers. `toward` = +1 / -1: the side the partner is on (lean / shrug tilt)."""
    t = np.arange(n) / fps
    z = np.zeros(n)
    if kind == "nod":
        y = -9 * _pulse(t, t0 + 0.25, 0.5) - 5 * _pulse(t, t0 + 0.75, 0.42)
        add(L, "ParamAngleY", y)
        add(L, "ParamBodyAngleY", y * 0.25)
    elif kind == "shake":
        env = window(n, fps, t0, t0 + 0.9, 0.12, 0.25)
        add(L, "ParamAngleX", 11 * np.sin(2 * np.pi * 2.4 * (t - t0)) * env)
        add(L, "ParamAngleY", -2.5 * env)
    elif kind == "tilt":
        env = window(n, fps, t0, t0 + max(1.0, dur), 0.35, 0.5)
        add(L, "ParamAngleZ", 13 * toward * env)
        add(L, "ParamBodyAngleZ", 3 * toward * env)
        add(L, "ParamAngleY", 3 * env)
    elif kind == "lean_in":
        env = window(n, fps, t0, t0 + max(1.2, dur), 0.45, 0.6)
        add(L, "ParamBodyAngleY", 8 * env)
        add(L, "ParamAngleY", -4 * env)
        add(L, "ParamBodyAngleX", 6 * toward * env)
        add(L, "ParamAngleX", 5 * toward * env)
    elif kind == "laugh_bounce":
        env = window(n, fps, t0, t0 + min(max(dur, 0.8), 1.6), 0.08, 0.5)
        b = np.abs(np.sin(2 * np.pi * 3.2 * (t - t0))) * env
        add(L, "ParamAngleY", 7 * b - 3 * env)
        add(L, "ParamBodyAngleY", 4 * b)
        add(L, "ParamAngleZ", 4 * toward * env)
        for s in shoulders:
            add(L, s, 0.35 * b)
        for e in ("ParamEyeLSmile", "ParamEyeRSmile"):
            add(L, e, 0.6 * env)
    elif kind == "shrug":
        p = _pulse(t, t0 + 0.55, 1.1)
        for s in shoulders:
            add(L, s, 0.9 * p)
        add(L, "ParamAngleZ", -7 * toward * p)
        add(L, "ParamAngleY", 2 * p)
        for b in ("ParamBrowLY", "ParamBrowRY"):
            add(L, b, 0.5 * p)
        add(L, "ParamMouthForm", -0.3 * p)
    elif kind == "look_away":
        env = window(n, fps, t0, t0 + min(max(dur * 0.6, 1.2), 2.4), 0.25, 0.45)
        add(L, "ParamEyeBallX", -0.7 * toward * env)
        add(L, "ParamEyeBallY", 0.55 * env)
        add(L, "ParamAngleX", -12 * toward * env)
        add(L, "ParamAngleY", 7 * env)
        add(L, "ParamAngleZ", -4 * toward * env)
    else:
        raise PerformError(f"unknown gesture {kind!r} (have {', '.join(GESTURES)} or motion:<name>)")
    return z


# ---------------------------------------------------------------- prosody / gaze
def loudness_db(y, sr, fps, n):
    per = sr / fps
    out = np.full(n, -90.0)
    for i in range(n):
        a, b = int(round(i * per)), min(len(y), int(round((i + 1) * per)))
        if b > a:
            r = np.sqrt(np.mean(y[a:b] ** 2))
            out[i] = 20 * np.log10(max(r, 1e-6))
    return out


def emphasis_peaks(y, sr, fps, n, min_gap=0.35):
    """Frames of stressed syllables: onset strength (rise of the smoothed loudness) above the 80th percentile of the
    voiced rises and >= 3 dB, at least `min_gap` s apart. Returns [(frame, strength 0..1)]."""
    db = follow(loudness_db(y, sr, fps, n), fps, 0.03)
    rise = np.maximum(0, np.diff(db, prepend=db[0]))
    voiced = rise[db > -45]
    if len(voiced) < 4:
        return []
    thr = max(3.0, float(np.percentile(voiced, 80)))
    out, last = [], -10 ** 9
    for i in range(1, n - 1):
        if rise[i] >= thr and rise[i] >= rise[i - 1] and rise[i] >= rise[i + 1] and db[i] > -40 and (i - last) / fps >= min_gap:
            out.append((i, float(min(1.0, rise[i] / (2 * thr)))))
            last = i
    return out


def phrase_ends(talk, fps, min_len=1.0):
    """Frames where a speaker stops after talking >= min_len s (activity falls under 0.3 after being over 0.6)."""
    out, start, on = [], None, False
    for i, v in enumerate(talk):
        if not on and v > 0.6:
            on, start = True, i
        elif on and v < 0.3:
            on = False
            if (i - start) / fps >= min_len:
                out.append(i)
    return out


def saccades(rng, n, fps, amp=(0.18, 0.1)):
    """Small fixational eye jumps: a new offset every 0.8-2.5 s, reached in ~60 ms. Returns (dx, dy)."""
    tx, ty = np.zeros(n), np.zeros(n)
    t, cur = 0.0, (0.0, 0.0)
    while t < n / fps:
        nxt = t + rng.uniform(0.8, 2.5)
        cur = (rng.uniform(-1, 1) * amp[0], rng.uniform(-1, 1) * amp[1])
        a, b = int(t * fps), min(n, int(nxt * fps))
        tx[a:b], ty[a:b] = cur
        t = nxt
    return follow(tx, fps, 0.02), follow(ty, fps, 0.02)


def _look_vec(look, partner_dir, screen_dir):
    if look == "partner":
        return (0.85 * partner_dir, -0.05)
    if look == "screen":
        return tuple(screen_dir)
    if look == "away":
        return (-0.6 * partner_dir, 0.45)
    return (0.0, 0.0)


# ---------------------------------------------------------------- moods
def mood_name(m):
    """'happy' | 'happy:0.6' | {name, amount} -> (name, amount)."""
    if not m:
        return "neutral", 1.0
    if isinstance(m, dict):
        return str(m.get("name", "neutral")), float(m.get("amount", 1.0))
    s = str(m)
    if ":" in s:
        a, b = s.split(":", 1)
        return a.strip(), float(b)
    return s.strip(), 1.0


def mood_targets(model, mood):
    """(targets, fade_in, fade_out) for a mood on this model: its `moods:` entry (exp3 file and/or params) else generic."""
    entry = (model.get("moods") or {}).get(mood)
    if entry is None:
        if mood not in GENERIC_MOODS:
            raise PerformError(f"unknown mood {mood!r} (have {', '.join(MOODS)})")
        return list(GENERIC_MOODS[mood]), 0.3, 0.4
    targets, fi, fo = [], 0.3, 0.4
    if isinstance(entry, str):
        entry = {"exp": entry}
    if entry.get("exp"):
        p = (model.get("expressions") or {}).get(entry["exp"])
        if not p or not os.path.exists(p):
            raise PerformError(f"{model.get('id')}: mood {mood}: expression {entry['exp']!r} not in the model (have {sorted(model.get('expressions') or {})})")
        e = load_exp3(p)
        sc = float(entry.get("weight", 1.0))
        for pid, mode, v in exp3_targets(e):
            targets.append((pid, mode, v * sc if mode == "add" else (1 + (v - 1) * sc if mode == "mul" else v)))
        fi, fo = min(e["fade_in"], 0.5), min(e["fade_out"], 0.6)
    if entry.get("generic"):
        targets += GENERIC_MOODS.get(entry["generic"], [])
    for pid, v in (entry.get("params") or {}).items():
        if isinstance(v, (list, tuple)):
            targets.append((pid, v[0], float(v[1])))
        else:
            targets.append((pid, "add", float(v)))
    return targets, fi, fo


def auto_moods(expression_names):
    """Map moods to expressions by words in their names (for `promo live2d add`)."""
    out = {}
    for mood, words in MOOD_WORDS.items():
        for e in expression_names:
            if any(w in e.lower() for w in words):
                out[mood] = {"exp": e}
                break
    return out


# ---------------------------------------------------------------- the performance
def _filter(L, ids):
    """Drop layers on parameters the model does not have (when its parameter list is known)."""
    if not ids:
        return L
    return {k: v for k, v in L.items() if k in ids}


def perform(model, n, fps, seed, base, *, mouth=None, y=None, sr=None, lines=(), partner_lines=(), partner_mouth=None,
            partner_y=None, partner_sr=None, partner_dir=1.0, screen_dir=(0.5, 0.35), energy=1.0):
    """All layers for one host. `base` = idle tracks {id: array} (blink, breath, sway) from live2d.idle_tracks with no
    mouth / partner (so its seeded stream is unchanged); `mouth` = the zero-lag mouth-open track; `lines` = this host's
    script lines in global seconds, `partner_lines` = everyone else's. Returns (layers, info)."""
    from .live2d import activity
    rng = np.random.default_rng(seed * 7919 + 17)
    t = np.arange(n) / fps
    L = {}
    ids = set(model.get("param_ids") or [])
    has = (lambda pid: pid in ids) if ids else (lambda pid: True)
    m = np.zeros(n) if mouth is None else np.asarray(mouth, float)
    talk = activity(m, fps) if mouth is not None else np.zeros(n)
    ptalk = activity(partner_mouth, fps) if partner_mouth is not None else np.zeros(n)
    listen = ptalk * (1 - talk)
    info = dict(moods=[], gestures=[], peaks=0, nods=0)

    # base: blink, breath, idle sway (set)
    for pid, arr in base.items():
        setv(L, pid, arr)

    # mouth: vowels or open + form
    mo = model.get("mouth") or {}
    vow = mo.get("vowels") or {}
    if mouth is not None and y is not None and (vow or mo.get("form")):
        vs = visemes(y, sr, fps, n, m)
        info["vowels"] = {v: round(float(vs[v].sum() / max(1e-9, m.sum())), 3) for v in VOWELS}
        if vow:
            for v, pid in vow.items():
                setv(L, pid, np.clip(vs[v] * 1.15, 0, 1))
        if mo.get("form"):
            setv(L, mo["form"], np.clip(vs["form"], -1, 1))
    open_ids = [p for p in list(dict.fromkeys(list((model.get("groups") or {}).get("LipSync") or []) + list(mo.get("open") or []))) if p not in vow.values()]
    for pid in open_ids:
        setv(L, pid, m)
    info["mouth_ids"] = list(vow.values()) or open_ids

    # gaze target: camera by default; while listening the speaker; per-line `look`
    gx, gy = np.zeros(n), np.zeros(n)
    want = np.zeros(n)                                  # weight of the explicit target vs camera
    for ln in lines:
        look = ln.get("look") or "camera"
        if look not in LOOKS:
            raise PerformError(f"line {ln.get('id')}: look {look!r} (have {', '.join(LOOKS)})")
        w = window(n, fps, ln["t0"] - 0.15, ln["t1"], 0.25, 0.4)
        vx, vy = _look_vec(look, partner_dir, screen_dir)
        if look == "camera" and rng.uniform() < 0.45 and ln["t1"] - ln["t0"] > 1.6:
            # a talker often glances away while starting a thought, then comes back to the camera
            ga = window(n, fps, ln["t0"], ln["t0"] + rng.uniform(0.5, 0.9), 0.15, 0.3)
            side = -partner_dir if rng.uniform() < 0.6 else partner_dir
            gx += ga * 0.35 * side
            gy += ga * rng.uniform(0.15, 0.4)
        gx += w * vx
        gy += w * vy
        want = np.maximum(want, w)
    pdx, pdy = _look_vec("partner", partner_dir, screen_dir)
    gx += listen * pdx * (1 - want)
    gy += listen * pdy * (1 - want)
    sx, sy = saccades(rng, n, fps)
    eye_x = follow(gx, fps, 0.05)
    eye_y = follow(gy, fps, 0.05)
    head_x = follow(gx, fps, 0.28)
    head_y = follow(gy, fps, 0.28)
    add(L, "ParamEyeBallX", np.clip(0.75 * eye_x + sx, -1, 1))
    add(L, "ParamEyeBallY", np.clip(0.6 * eye_y + sy, -1, 1))
    add(L, "ParamAngleX", 16 * head_x)
    add(L, "ParamAngleY", 9 * head_y)
    add(L, "ParamBodyAngleX", 4 * head_x)

    # talking: livelier head (more sway while speaking) and prosody beats on stressed syllables
    if mouth is not None:
        lively = follow(talk, fps, 0.4) * energy
        add(L, "ParamAngleZ", 2.5 * lively * np.sin(2 * np.pi * t / 2.3 + rng.uniform(0, 6.28)))
        add(L, "ParamAngleX", 2.0 * lively * np.sin(2 * np.pi * t / 3.1 + rng.uniform(0, 6.28)))
        if y is not None:
            pk = emphasis_peaks(y, sr, fps, n)
            info["peaks"] = len(pk)
            br, hy, hx = np.zeros(n), np.zeros(n), np.zeros(n)
            sgn = 1.0
            for i, s in pk:
                c = i / fps
                br += 0.45 * s * _pulse(t, c + 0.12, 0.5)
                hy += -4.5 * s * _pulse(t, c + 0.1, 0.36)
                sgn = -sgn if rng.uniform() < 0.6 else sgn
                hx += 2.2 * s * sgn * _pulse(t, c + 0.15, 0.5)
            for b in ("ParamBrowLY", "ParamBrowRY"):
                add(L, b, br * energy)
            add(L, "ParamAngleY", hy * energy)
            add(L, "ParamAngleX", hx * energy)

    # listening: nod at the speaker's phrase ends (backchannel) and, now and then, on their stresses
    nods = np.zeros(n)
    if partner_mouth is not None:
        for i in phrase_ends(ptalk, fps):
            if rng.uniform() < 0.75 and talk[min(n - 1, i)] < 0.3:
                c = i / fps + rng.uniform(0.05, 0.25)
                nods += -7 * _pulse(t, c + 0.2, 0.42) - 3.5 * _pulse(t, c + 0.6, 0.36)
                info["nods"] += 1
        if partner_y is not None:
            for i, s in emphasis_peaks(partner_y, partner_sr, fps, n, min_gap=1.2):
                if rng.uniform() < 0.3 and listen[i] > 0.5:
                    nods += -3.5 * s * _pulse(t, i / fps + 0.18, 0.45)
                    info["nods"] += 1
        add(L, "ParamAngleY", nods)
        add(L, "ParamBodyAngleY", 0.3 * nods)

    # body: slow Z sway and shoulder breath
    add(L, "ParamBodyAngleZ", 2.2 * np.sin(2 * np.pi * t / 8.5 + rng.uniform(0, 6.28)) + 1.2 * np.sin(2 * np.pi * t / 13.0 + rng.uniform(0, 6.28)))
    br = base.get("ParamBreath")
    if br is not None:
        for s in ("ParamShoulder", "ParamLeftShoulderUp", "ParamRightShoulderUp"):
            if has(s):
                add(L, s, 0.12 * (np.asarray(br) - 0.5))

    # moods: own lines; listening reactions (`react:` on the speaker's line, else a lighter mirror of their mood)
    spans = {}
    for ln in lines:
        nm, amt = mood_name(ln.get("mood"))
        if nm != "neutral":
            spans.setdefault(nm, []).append((ln["t0"] - 0.1, ln["t1"] + 0.35, amt))
    for ln in partner_lines:
        r = ln.get("react")
        if r:
            nm, amt = mood_name(r)
            amt *= 0.85
        else:
            nm0, a0 = mood_name(ln.get("mood"))
            if nm0 not in MIRROR:
                continue
            nm, amt = MIRROR[nm0][0], MIRROR[nm0][1] * a0
        if nm != "neutral":
            spans.setdefault(nm, []).append((ln["t0"] + 0.25, ln["t1"] + 0.5, amt))
    rest = np.ones(n)
    for nm, sp in sorted(spans.items()):
        targets, fi, fo = mood_targets(model, nm)
        w = np.zeros(n)
        for a, b, amt in sp:
            w = np.maximum(w, window(n, fps, a, b, fi, fo) * min(1.5, amt))
        if has_any(targets, has):
            apply_targets(L, [x for x in targets if has(x[0])], np.clip(w, 0, 1.5))
        rest = np.minimum(rest, 1 - w * (1 - REST_SMILE.get(nm, 1.0)))
        info["moods"].append(dict(mood=nm, frames=int((w > 0.5).sum())))

    # resting smile: when not talking, scaled by the mood
    rs = float(model.get("rest_smile", 0.35))
    smile_id = mo.get("form") or ("ParamMouthUp" if has("ParamMouthUp") else None)
    if smile_id and rs:
        add(L, smile_id, rs * (1 - follow(talk, fps, 0.25)) * np.clip(rest, 0, 1))

    # gestures (procedural or the model's own motions)
    for ln in lines:
        g = ln.get("gesture")
        if not g:
            continue
        at = ln["t0"] + float(ln.get("gesture_at", 0.0))
        dur = ln["t1"] - at
        if str(g).startswith("motion:"):
            name = str(g).split(":", 1)[1]
            p = (model.get("motions") or {}).get(name)
            if not p:
                raise PerformError(f"{model.get('id')}: line {ln.get('id')}: motion {name!r} not in the model (have {sorted(model.get('motions') or {})})")
            motion_layers(L, load_motion3(p), n, fps, at, max(dur, 1.0))
        else:
            gesture(L, g, n, fps, at, dur, toward=partner_dir)
        info["gestures"].append(dict(line=ln.get("id"), gesture=g, at=round(at, 2)))
    return _filter(L, ids), info


def has_any(targets, has):
    return any(has(t[0]) for t in targets)
