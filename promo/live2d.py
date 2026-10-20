"""Offline, deterministic Live2D host renderer (prototype).

Pipeline (one host = one layer):
    WAV --(lip_track: 10 ms envelope, fast attack / eased close, zero-lag by construction)--> ParamMouthOpenY per frame
    seed --(idle_tracks: blink timer, breath, small head/body sway, optional listening nod)--> per-frame params
    nice -n 10 node live2d/render.mjs job.json  (headless Chromium + pixi.js + pixi-live2d-display + official
    Live2D Cubism Core; model clock advanced exactly 1/fps per frame)  | nice -n 10 ffmpeg -threads 2 -> ProRes 4444
    / VP9 alpha / PNG sequence

Models and the Cubism Core come from `live2d/assets.yaml` and are fetched from live2d.com (sha256-pinned) into
`live2d/media/` (gitignored, never redistributed). Only Live2D Original Characters are accepted. Renders take a
the box-wide heavy-work lock (promo.lock: a lock other heavy jobs on the machine can share; $PROMO_HEAVY_LOCK).

The lip envelope follows the vowel-level LipSync approach (LipSync: level vs a decaying peak,
smoothstep, attack/release) and viseme-timeline.ts (10 ms steps, centred look-ahead window, 20 ms close ease);
`lip_lag` is a port of lip-lag.ts.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

import numpy as np
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L2D_DIR = os.path.join(ROOT, "live2d")
REGISTRY = os.path.join(L2D_DIR, "assets.yaml")
STEP_S = 0.01                # envelope step (viseme-timeline STEP_S)
WINDOW_S = 0.043             # centred analysis window (viseme-timeline WINDOW_S)
ATTACK_S = 0.012             # fast attack
RELEASE_S = 0.060            # fall between syllables
CLOSE_S = 0.020              # gated silence: ease shut (viseme-timeline CLOSE_TAU_S)
CLOSE_DB = -46.0             # below this level the mouth is shut (LipSync closeDb)


class Live2DError(RuntimeError):
    pass


# ---------------------------------------------------------------- registry / fetch
SAMPLE_TYPES = ("original",)                     # Live2D Original Characters (the free sample models)
# AGENTS.md rule 1: the person's own likeness may appear only in an `avatar` overlay, so a host model drawn from them
# (`likeness: own`) renders for tests and stills but fails the show's licence gate.
OWN_LIKENESS_HOST = "is drawn from the person's own likeness: rule 1 allows that only in an `avatar` overlay, not as a show host"
BYO_TYPES = ("own", "commissioned", "original")  # bring-your-own models: drawn / commissioned / bought for this use
REFUSED_TYPES = ("collaboration", "external")


def user_registry_path():
    """Bring-your-own models (`promo live2d add`): <config dir>/live2d-models.yaml, next to the promo config."""
    from .home import config_path
    return os.environ.get("PROMO_LIVE2D_MODELS") or os.path.join(os.path.dirname(config_path()), "live2d-models.yaml")


def user_models(path=None):
    p = path or user_registry_path()
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return ((yaml.safe_load(f) or {}).get("models")) or {}


def registry(path=REGISTRY, user=True):
    """live2d/assets.yaml merged with the user's own models (theirs are marked `user: true`; a sample id cannot be replaced)."""
    with open(path) as f:
        reg = yaml.safe_load(f)
    if user:
        for k, m in user_models().items():
            if k not in reg["models"]:
                reg["models"][k] = dict(m, user=True)
    return reg


def model_entry(name, reg=None):
    reg = reg or registry()
    m = (reg.get("models") or {}).get(name)
    if not m:
        raise Live2DError(f"unknown Live2D model {name!r}; known: {sorted(reg.get('models') or {})}")
    ct = m.get("character_type")
    if m.get("user"):
        if ct not in BYO_TYPES:
            raise Live2DError(f"{name}: character_type={ct!r}. A model of your own must be own | commissioned | original (a collaboration or "
                              f"third-party character is refused: its terms do not cover a promo)")
        miss = [k for k in ("licence", "source_url") if not m.get(k)]
        if miss:
            raise Live2DError(f"{name}: your model needs {' and '.join(miss)} (what lets you use it, and where it came from): "
                              f"`promo live2d add ... --licence TEXT --source URL`")
        if m.get("likeness") == "own" and not str(m.get("consent") or "").strip():
            raise Live2DError(f"{name}: a model of the person's own likeness needs their consent on record: "
                              f"`promo live2d add ... --likeness own --consent TEXT`")
        return m
    if ct not in SAMPLE_TYPES:
        raise Live2DError(f"{name}: character_type={ct!r}. Only Live2D Original Characters may be used in a "
                          f"promo (Collaboration Characters are non-commercial only; external characters have third-party terms). {m.get('licence', '')}")
    return m


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(L2D_DIR, p)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _download(url, dest, want):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "promo-reel/0.1 (live2d fetch)"})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        for b in iter(lambda: r.read(1 << 20), b""):
            f.write(b)
    got = sha256_file(tmp)
    if want and got != want:
        os.remove(tmp)
        raise Live2DError(f"sha256 mismatch for {url}: got {got}, manifest {want} (Live2D may have updated the file: re-read the "
                          f"licence/notice on the download page before re-pinning)")
    os.replace(tmp, dest)


def model_dir(name):
    return os.path.join(L2D_DIR, "media", "models", name)


def fetch(names=None, force=False, log=print):
    """Download Cubism Core + the listed (default: all original-character) models, verify sha256, unpack."""
    reg = registry(user=False)
    rt = reg["runtime"]
    core = _abs(rt["path"])
    if force or not os.path.exists(core) or sha256_file(core) != rt["sha256"]:
        log(f"fetch {rt['id']}: {rt['fetch_url']}")
        _download(rt["fetch_url"], core, rt["sha256"])
    else:
        log(f"present {rt['id']}")
    names = names or [k for k, v in reg["models"].items() if v.get("character_type") == "original"]
    for n in names:
        m = model_entry(n, reg)
        arc = _abs(m["archive"])
        if force or not os.path.exists(arc) or sha256_file(arc) != m["sha256"]:
            log(f"fetch {n}: {m['fetch_url']}")
            _download(m["fetch_url"], arc, m["sha256"])
        d = model_dir(n)
        stamp = os.path.join(d, ".sha256")
        if force or not os.path.exists(stamp) or open(stamp).read().strip() != m["sha256"]:
            with zipfile.ZipFile(arc) as z:
                # only the runtime files are needed for rendering (skip the .cmo3/.can3 editor sources)
                members = [i for i in z.namelist() if "/runtime/" in "/" + i and not i.endswith("/")]
                for i in members:
                    tgt = os.path.normpath(os.path.join(d, i))
                    if not tgt.startswith(d + os.sep):
                        raise Live2DError(f"unsafe path in archive: {i}")
                    os.makedirs(os.path.dirname(tgt), exist_ok=True)
                    with z.open(i) as src, open(tgt, "wb") as dst:
                        dst.write(src.read())
            open(stamp, "w").write(m["sha256"])
            log(f"unpacked {n} -> {d}")
        else:
            log(f"present {n}")
    return core


def resolve_model(name):
    reg = registry()
    m = model_entry(name, reg)
    if m.get("renderer") == "mesh":
        from . import mesh_avatar
        return mesh_avatar.resolve(name, m)
    core = _abs(reg["runtime"]["path"])
    if m.get("user"):
        p = os.path.expanduser(m["model3"])
        d = os.path.dirname(p)
        if not os.path.exists(p):
            raise Live2DError(f"{name}: model file {p} is missing (registered with `promo live2d add`; the files stay where they were)")
    else:
        d = model_dir(name)
        p = os.path.join(d, m["model3"])
        if not os.path.exists(p):
            raise Live2DError(f"{name}: model or Cubism Core not fetched; run `promo live2d fetch`")
    if not os.path.exists(core):
        raise Live2DError(f"{name}: model or Cubism Core not fetched; run `promo live2d fetch`")
    if sha256_file(core) != reg["runtime"]["sha256"]:
        raise Live2DError("Cubism Core sha256 differs from live2d/assets.yaml; run `promo live2d fetch --force`")
    return dict(m, id=name, dir=os.path.dirname(p), model3_path=p, core=core, notice=reg["notice"], **model3_info(p))


def model3_info(p):
    """What a model3.json offers: groups, expressions {name: path}, motions {name: path} (file stem and Group:i),
    param_ids (from the .cdi3 display info, or the motions / expressions when there is none; empty = unknown)."""
    with open(p) as f:
        m3 = json.load(f)
    d = os.path.dirname(p)
    fr = m3.get("FileReferences") or {}
    groups = {g["Name"]: g["Ids"] for g in m3.get("Groups", [])}
    exps = {e["Name"]: os.path.join(d, e["File"]) for e in fr.get("Expressions") or []}
    mots = {}
    for g, lst in (fr.get("Motions") or {}).items():
        for i, mo in enumerate(lst):
            path = os.path.join(d, mo["File"])
            mots[os.path.splitext(os.path.splitext(os.path.basename(mo["File"]))[0])[0]] = path
            mots[f"{g or 'Default'}:{i}"] = path
    ids = []
    if fr.get("DisplayInfo") and os.path.exists(os.path.join(d, fr["DisplayInfo"])):
        with open(os.path.join(d, fr["DisplayInfo"])) as f:
            ids = [x["Id"] for x in json.load(f).get("Parameters", [])]
    return dict(groups=groups, expressions=exps, motions=mots, param_ids=ids)


# ---------------------------------------------------------------- audio -> lip track
def load_wav(path, sr=None):
    import soundfile as sf
    y, r = sf.read(path, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    if sr and r != sr:
        import librosa
        y = librosa.resample(y, orig_sr=r, target_sr=sr)
        r = sr
    return y, r


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def envelope(y, sr, step=STEP_S, window=WINDOW_S):
    """Per-step openness target 0..1 from a window CENTRED on each step instant (look-ahead = half window, so the
    target itself has no lag). Level is gated at CLOSE_DB and scaled against a slowly decaying peak (LipSync)."""
    n = int(np.ceil(len(y) / sr / step)) + 1
    half = int(round(window * sr / 2))
    pad = np.concatenate([np.zeros(half, np.float32), y, np.zeros(half + int(step * sr) + 1, np.float32)])
    c2 = np.concatenate([[0.0], np.cumsum(pad.astype(np.float64) ** 2)])
    centres = np.round(np.arange(n) * step * sr).astype(int) + half
    lo, hi = centres - half, centres + half
    rms = np.sqrt(np.maximum(c2[hi] - c2[lo], 0) / (hi - lo))
    db = np.where(rms > 1e-6, 20 * np.log10(np.maximum(rms, 1e-12)), -120.0)
    target = np.zeros(n)
    peak = -30.0
    for i in range(n):
        peak = max(db[i], peak - 4 * step, -30.0)
        if db[i] > CLOSE_DB:
            span = max(8.0, peak - 2 - CLOSE_DB)
            target[i] = _smoothstep(min(1.0, (db[i] - CLOSE_DB) / span))
    return target, db


def attack_release(target, step=STEP_S, attack=ATTACK_S, release=RELEASE_S, close=CLOSE_S):
    """One-pole follower: fast rise, slower fall within speech, quick eased close when the gate shuts."""
    out = np.zeros_like(target)
    v = 0.0
    ka, kr, kc = (1 - np.exp(-step / attack)), (1 - np.exp(-step / release)), (1 - np.exp(-step / close))
    for i, tg in enumerate(target):
        k = ka if tg > v else (kc if tg == 0 else kr)
        v += (tg - v) * k
        if tg == 0 and v < 0.01:
            v = 0.0
        out[i] = v
    return out


def _xcorr_lag(a, b, max_lag):
    """Lag (in samples, fractional via parabola) maximising sum a[i] * b[i + lag]; positive = b is late."""
    def norm(x):
        x = np.asarray(x, float) - np.mean(x)
        return x / (np.sqrt(np.sum(x * x)) or 1.0)
    a, b = norm(a), norm(b)

    def corr(l):
        if l >= 0:
            return float(np.dot(a[: len(a) - l], b[l:]))
        return float(np.dot(a[-l:], b[: len(b) + l]))
    lags = list(range(-max_lag, max_lag + 1))
    cs = [corr(l) for l in lags]
    k = int(np.argmax(cs))
    best = lags[k]
    if 0 < k < len(cs) - 1:
        l_, c_, r_ = cs[k - 1], cs[k], cs[k + 1]
        den = l_ - 2 * c_ + r_
        frac = 0.5 * (l_ - r_) / den if den else 0.0
    else:
        frac, c_ = 0.0, cs[k]
    return best + frac, c_


def lip_track(y, sr, fps, n_frames, form=True):
    """Per-frame mouth open (0..1) and optional mouth form (-1..1) for frames i = 0..n-1.

    Zero lag by construction: the envelope target uses a centred window; the follower's own delay is measured
    against that target (cross-correlation at 10 ms steps) and taken back out by shifting the follower output
    earlier by that amount; frame i samples the envelope at the centre of its display interval, (i + 0.5) / fps,
    which is the same instant the per-frame RMS used by `lip_lag` describes."""
    target, db = envelope(y, sr)
    sm = attack_release(target)
    lag_steps, _ = _xcorr_lag(target, sm, 10)
    lead = max(0.0, lag_steps) * STEP_S
    ts = np.arange(len(sm)) * STEP_S - lead
    t_frames = (np.arange(n_frames) + 0.5) / fps
    mouth = np.clip(np.interp(t_frames, ts, sm, left=0.0, right=0.0), 0, 1)
    out = dict(open=mouth, lead_s=lead)
    if form:
        # brighter spectrum (more high-frequency energy, e.g. /i/ /e/ /s/) -> wider mouth; dark (/o/ /u/) -> rounder
        hop = int(sr / fps)
        f = np.zeros(n_frames)
        for i in range(n_frames):
            a = int(i * sr / fps)
            seg = y[a: a + max(hop, 512)]
            if len(seg) < 64 or np.sqrt(np.mean(seg ** 2)) < 1e-3:
                continue
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
            fr = np.fft.rfftfreq(len(seg), 1 / sr)
            cen = float(np.sum(spec * fr) / (np.sum(spec) + 1e-9))
            f[i] = np.clip((cen - 1400) / 1600, -0.6, 0.8)
        k = 1 - np.exp(-(1 / fps) / 0.06)
        g = np.zeros(n_frames)
        v = 0.0
        for i in range(n_frames):
            v += (f[i] - v) * k
            g[i] = v
        out["form"] = g * np.minimum(1.0, mouth * 3)       # only shape the mouth while it is open
    return out


def frame_envelope(y, sr, fps, n):
    """RMS of the audio over each frame's interval [i/fps, (i+1)/fps) (lip-lag.ts)."""
    per = sr / fps
    env = np.zeros(n)
    for i in range(n):
        a, b = int(round(i * per)), min(len(y), int(round((i + 1) * per)))
        if b > a:
            env[i] = np.sqrt(np.mean(y[a:b] ** 2))
    return env


def lip_lag(mouth, y, sr, fps, max_lag=10):
    """Cross-correlation of a per-frame mouth-open track against the voice's per-frame RMS envelope; positive = the
    mouth is late. Port of ai-interview-host src/audio/lip-lag.ts."""
    env = frame_envelope(y, sr, fps, len(mouth))
    if env.max() < 1e-4 or np.std(mouth) < 1e-6:
        return None                     # silent stretch: no lag to measure
    frames, peak = _xcorr_lag(env, mouth, max_lag)
    return dict(frames=round(frames, 2), ms=round(frames * 1000 / fps, 1), peak=round(peak, 3))


# ---------------------------------------------------------------- idle / blink / breath / nod
def _smooth_noise(rng, n, fps, period_s, k=4):
    """Sum of k sinusoids with seeded random periods around `period_s` and random phases, normalised to ~[-1, 1]."""
    t = np.arange(n) / fps
    out = np.zeros(n)
    for _ in range(k):
        p = period_s * rng.uniform(0.6, 1.7)
        out += np.sin(2 * np.pi * t / p + rng.uniform(0, 2 * np.pi)) * rng.uniform(0.5, 1.0)
    return out / k * 1.6


def activity(mouth, fps, tau=0.35):
    """Smoothed 'is talking' 0..1 from a mouth track (for nods / gaze)."""
    on = (np.asarray(mouth) > 0.08).astype(float)
    k = 1 - np.exp(-(1 / fps) / tau)
    out = np.zeros_like(on)
    v = 0.0
    for i, x in enumerate(on):
        v += (x - v) * k
        out[i] = v
    return np.clip(out * 1.4, 0, 1)


def idle_tracks(n, fps, seed, mouth=None, partner_mouth=None, gaze=0.0, eyes=("ParamEyeLOpen", "ParamEyeROpen")):
    """Blink (seeded timer), breath, small head/body sway, talk emphasis and an optional listening nod.
    `gaze` = horizontal direction a LISTENING host turns to (-1 = left, +1 = right; scalar or per-frame array), e.g.
    toward the app screen; the talking host faces the camera."""
    rng = np.random.default_rng(seed)
    gaze = np.broadcast_to(np.asarray(gaze, float), (n,)) if np.ndim(gaze) == 0 else np.asarray(gaze, float)[:n]
    t = np.arange(n) / fps
    tr = {}
    # blink: closes over 70 ms, holds 30 ms, opens over 110 ms; 2.4-5.5 s apart; ~12 % double blinks
    eye = np.ones(n)
    nxt = rng.uniform(0.6, 2.5)
    while nxt < n / fps:
        for start in ([nxt, nxt + 0.32] if rng.uniform() < 0.12 else [nxt]):
            for i in range(n):
                d = t[i] - start
                if 0 <= d < 0.07:
                    eye[i] = min(eye[i], 1 - d / 0.07)
                elif 0.07 <= d < 0.10:
                    eye[i] = 0.0
                elif 0.10 <= d < 0.21:
                    eye[i] = min(eye[i], (d - 0.10) / 0.11)
        nxt += rng.uniform(2.4, 5.5)
    for e in eyes:
        tr[e] = eye
    tr["ParamBreath"] = 0.5 + 0.5 * np.sin(2 * np.pi * t / 3.4 + rng.uniform(0, 6.28))
    talk = activity(mouth, fps) if mouth is not None else np.zeros(n)
    listen = activity(partner_mouth, fps) * (1 - talk) if partner_mouth is not None else np.zeros(n)
    ax = 5.0 * _smooth_noise(rng, n, fps, 7.0)
    ay = 2.5 * _smooth_noise(rng, n, fps, 5.0)
    az = 3.0 * _smooth_noise(rng, n, fps, 9.0)
    bx = 2.0 * _smooth_noise(rng, n, fps, 11.0)
    if mouth is not None:   # small emphasis bob that follows the voice (about 3 deg), slower than the mouth
        k = 1 - np.exp(-(1 / fps) / 0.12)
        e = np.zeros(n)
        v = 0.0
        for i, m in enumerate(mouth):
            v += (m - v) * k
            e[i] = v
        ay = ay + 6.0 * (e - 0.25) * talk
    if partner_mouth is not None:   # listening: gentle nods (~0.8 Hz) while the partner talks, turned toward them
        ay = ay + 4.0 * np.sin(2 * np.pi * 0.8 * t) * listen
        ax = ax + 8.0 * gaze * listen
    tr["ParamAngleX"], tr["ParamAngleY"], tr["ParamAngleZ"], tr["ParamBodyAngleX"] = ax, ay, az, bx
    tr["ParamEyeBallX"] = np.clip(0.15 * _smooth_noise(rng, n, fps, 4.0) + gaze * 0.6 * listen, -1, 1)
    tr["ParamEyeBallY"] = np.clip(0.08 * _smooth_noise(rng, n, fps, 6.0), -1, 1)
    return tr


def host_tracks(model, n, fps, seed, wav=None, partner_wav=None, gaze=0.0, sr=None, lines=None, partner_lines=None, screen_dir=(0.5, 0.35),
                energy=1.0):
    """All per-frame parameter LAYERS for one host (promo.perform): blink / breath / sway from `idle_tracks`, then
    visemes, moods, gestures, gaze, prosody beats and listening nods. `gaze` = the side a listening host turns to (the
    partner or, in the livestream column, the app screen): -1 left, +1 right, a scalar or a per-frame array. `lines` /
    `partner_lines` = script lines in global seconds ({t0, t1, mood, gesture, look, react}). Returns (layers, info, mouth)."""
    from . import perform as PF
    mouth = partner = y = r = y2 = r2 = None
    info = {}
    if wav:
        y, r = load_wav(wav)
        lt = lip_track(y, r, fps, n, form=False)
        mouth = lt["open"]
        info.update(lead_s=lt["lead_s"], lag=lip_lag(mouth, y, r, fps))
    if partner_wav:
        y2, r2 = load_wav(partner_wav)
        partner = lip_track(y2, r2, fps, n, form=False)["open"]
    eyes = tuple(model["groups"].get("EyeBlink") or ("ParamEyeLOpen", "ParamEyeROpen"))
    base = idle_tracks(n, fps, seed, None, None, 0.0, eyes)
    g = np.broadcast_to(np.asarray(gaze, float), (n,)) if np.ndim(gaze) == 0 else np.asarray(gaze, float)[:n]
    layers, pinfo = PF.perform(model, n, fps, seed, base, mouth=mouth, y=y, sr=r, lines=lines or [], partner_lines=partner_lines or [],
                               partner_mouth=partner, partner_y=y2, partner_sr=r2, partner_dir=g, screen_dir=screen_dir, energy=energy)
    info.update(pinfo)
    m = mouth if mouth is not None else np.zeros(n)
    return layers, info, m


# ---------------------------------------------------------------- render
def render_lock(log=print):
    """The shared heavy-work lock (see promo.lock); replaces the old live2d-only lock."""
    from .lock import heavy_lock
    return heavy_lock("live2d host render", log=lambda *a: log(*a))


def ffmpeg_out(out, W, H, fps, fmt=None, bg=None, src=None):
    """Encoder args for an RGBA rawvideo pipe -> transparent layer (or green screen with bg='green'). `src` = (w, h) of
    a supersampled, PREMULTIPLIED input: scaled down to W x H with lanczos, then un-premultiplied (no dark fringes)."""
    fmt = fmt or {".mov": "prores4444", ".webm": "vp9", ".png": "png"}.get(os.path.splitext(out)[1].lower(), "prores4444")
    iw, ih = src or (W, H)
    cmd = ["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{iw}x{ih}", "-r", str(fps), "-i", "-", "-threads", "2"]
    down = f"format=gbrap,scale={W}:{H}:flags=lanczos,unpremultiply=inplace=1" if src else None
    if bg:
        col = {"green": "0x00b140"}.get(bg, bg)
        cmd = ["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s={W}x{H}:r={fps}",
               "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{iw}x{ih}", "-r", str(fps), "-i", "-", "-threads", "2",
               "-filter_complex", (f"[1]{down}[fg];[0][fg]" if down else "[0][1]") + "overlay=shortest=1:format=auto"]
        return cmd + ["-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", out]
    if down:
        cmd += ["-vf", down]
    if fmt == "prores4444":
        return cmd + ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16", "-vendor", "apl0", out]
    if fmt == "vp9":
        return cmd + ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4", out]
    if fmt == "png":
        os.makedirs(out if os.path.isdir(out) or not out.endswith(".png") else os.path.dirname(out), exist_ok=True)
        pattern = out if "%" in out else os.path.join(out if not out.endswith(".png") else os.path.dirname(out), "%05d.png")
        return cmd + ["-c:v", "png", "-f", "image2", pattern]
    raise Live2DError(f"unknown format {fmt}")


def _scaled_frame(model, frame, H, k):
    """Framing override for a render k times larger (px keys scale; fractions do not)."""
    if not frame or k == 1:
        return frame
    return {key: (v * k if key == "pad_top" else v) for key, v in frame.items()}


def render_host(model_name, out, *, wav=None, partner_wav=None, duration=None, fps=30, width=640, height=720, seed=1,
                gaze=0.0, fmt=None, bg=None, frame=None, log=print, warmup=45, lines=None, partner_lines=None, screen_dir=(0.5, 0.35),
                supersample=1, energy=1.0):
    """Render one host layer. `supersample` = 2 renders at 2x and scales down (lanczos, premultiplied) for crisp line
    art; 1 = draft. Returns a report dict (frames, secs, s per output second, lip lag, performance info, files)."""
    model = resolve_model(model_name)
    if duration is None:
        if not wav:
            raise Live2DError("need --wav or --duration")
        import soundfile as sf
        duration = sf.info(wav).duration
    n = int(round(duration * fps))
    tracks, info, mouth = host_tracks(model, n, fps, seed, wav, partner_wav, gaze, lines=lines, partner_lines=partner_lines,
                                      screen_dir=screen_dir, energy=energy)
    from .perform import job_tracks
    k = max(1, int(supersample))
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    side = os.path.splitext(out)[0]
    fj = frame_job(model, _scaled_frame(model, frame, height, k), height * k)
    chromium = os.environ.get("PROMO_CHROMIUM") or _default_chromium()
    if model.get("renderer") == "mesh":
        from . import mesh_avatar
        job = mesh_avatar.job(model, width=width * k, height=height * k, fps=fps, frames=n, seed=seed, warmup=warmup, frame=fj, layers=tracks,
                              readback_path=side + ".readback.json", premultiplied=k > 1, chromium=chromium)
    else:
        job = dict(modelDir=model["dir"], model3=os.path.relpath(model["model3_path"], model["dir"]), core=model["core"], width=width * k,
                   height=height * k, fps=fps, frames=n, seed=seed, warmup=warmup, frame=fj, tracks=job_tracks(tracks),
                   readback=info["mouth_ids"][:1], readbackPath=side + ".readback.json", premultiplied=k > 1, chromium=chromium)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(job, f)
        jpath = f.name
    node = os.environ.get("PROMO_NODE", "node")
    t0 = time.time()
    with render_lock(log):
        log(f"live2d render {model_name}: {n} frames {width}x{height}" + (f" (x{k} supersampled)" if k > 1 else "") + f" @ {fps} fps -> {out}")
        p1 = subprocess.Popen(["nice", "-n", "10", node, os.path.join(L2D_DIR, "render.mjs"), jpath], stdout=subprocess.PIPE, cwd=L2D_DIR)
        p2 = subprocess.Popen(ffmpeg_out(out, width, height, fps, fmt, bg, src=(width * k, height * k) if k > 1 else None), stdin=p1.stdout)
        p1.stdout.close()
        rc2 = p2.wait()
        rc1 = p1.wait()
    os.unlink(jpath)
    if rc1 or rc2:
        raise Live2DError(f"render failed (node rc={rc1}, ffmpeg rc={rc2})")
    secs = time.time() - t0
    rb = json.load(open(job["readbackPath"]))
    applied = np.array([fr.get(job["readback"][0], 0.0) for fr in rb["frames"]]) if job["readback"] else mouth
    rep = dict(model=model_name, out=os.path.abspath(out), frames=n, fps=fps, size=[width, height], supersample=k, seed=seed, secs=round(secs, 1),
               s_per_output_s=round(secs / (n / fps), 2), lead_s=info.get("lead_s"), lip_lag_track=info.get("lag"),
               notice=model["notice"]["short"], credit=model.get("credit"), missing_params=(rb.get("info") or {}).get("missing"),
               perform={k_: info.get(k_) for k_ in ("moods", "gestures", "peaks", "nods", "vowels")})
    if wav:
        y, r = load_wav(wav)
        rep["lip_lag_applied"] = lip_lag(applied, y, r, fps)     # what the renderer actually set, frame by frame
        rep["mouth_offset_frames"] = int(np.argmax(np.correlate(applied - applied.mean(), mouth - mouth.mean(), "full")) - (n - 1))
    np.save(side + ".mouth.npy", mouth)
    inf = rb.get("info") or {}
    aspect = (inf.get("width") or 1) / (inf.get("height") or 1)
    at = mouth_probe_at(model, width, height, aspect, frame)
    fr_px = framing(model, height, frame)
    rep["framing"] = {k_: (round(v, 3) if isinstance(v, float) else v) for k_, v in fr_px.items()}
    if wav and at and fmt in (None, "prores4444") and out.endswith(".mov") and not bg:
        pix = pixel_mouth(out, width, height, at)
        rep["lip_lag_pixels"] = lip_lag(pix, y, r, fps)
        rep["pixel_vs_track_corr"] = round(float(np.corrcoef(pix, mouth)[0, 1]), 3)
    with open(side + ".report.json", "w") as f:
        json.dump(rep, f, indent=1)
    return rep


# Shared bust framing for every host (fractions of the layer height): the head (head_top -> chin anchors) is HEAD_FRAC
# of the layer tall and its top sits at HEAD_TOP_AT, face centre on the vertical centre line. With anime proportions
# (mid-chest ~1.7 heads below the skull top) the layer bottom lands at mid-chest, and a hat gets ~0.8 heads of room.
HEAD_FRAC = 0.48
HEAD_TOP_AT = 0.14


def framing(model, H, override=None):
    """Bust framing from the model's anchors for a layer of height H. The layer = `pad_top` px of break-out headroom
    (override key, default 0) above a PANEL of height H - pad_top; fractions (head_frac, head_top_at) are of the panel.
    Returns {zoom, at_x, at_y (layer terms, for page.html), head_top_px, chin_px, chest_px, top_px (panel-relative px;
    top_px < 0 = the silhouette breaks out above the panel), top_layer_px (>= 0 = not clipped), head_px, panel_h}.
    Same rule for every model, so heads land at the same height and scale. A legacy {zoom, cy, dx} override returns
    the px fields as None."""
    o = dict(override or {})
    an = model.get("anchors")
    if "zoom" in o or not an:
        f = dict(model.get("frame") or {"zoom": 1.0, "cy": 0.5}, **o)
        return dict(f, head_top_px=None, chin_px=None, chest_px=None, head_px=None, top_px=None, top_layer_px=None, panel_h=H)
    hf, ht = float(o.get("head_frac", HEAD_FRAC)), float(o.get("head_top_at", HEAD_TOP_AT))
    pad = float(o.get("pad_top", 0))
    P = H - pad
    head = an["chin"] - an["head_top"]
    top = an.get("top", an["head_top"])
    if head <= 0 or not (top <= an["head_top"] < an["chin"] < an["chest"]):
        raise Live2DError(f"{model.get('id')}: anchors must satisfy top <= head_top < chin < chest (got {an})")
    zp = hf / head                                      # model height in PANEL heights
    if model.get("cut_bottom"):
        # a bust picture cut flat at its bottom edge (a mesh avatar) never floats above the panel bottom: same head
        # size as every host, set lower in the panel until the cut sits on the panel's bottom edge
        ht = max(ht, 1.0 - (1.0 - an["head_top"]) * zp)
    px = lambda y: (ht + (y - an["head_top"]) * zp) * P
    return dict(zoom=zp * P / H, at_x=[an.get("cx", 0.5), 0.5], at_y=[an["head_top"], (pad + ht * P) / H],
                head_top_px=px(an["head_top"]), chin_px=px(an["chin"]), chest_px=px(an["chest"]), top_px=px(top),
                top_layer_px=pad + px(top), head_px=hf * P, panel_h=P, has_top="top" in an)


def frame_job(model, override=None, H=None):
    f = framing(model, H or 1, override)
    return {k: f[k] for k in ("zoom", "at_x", "at_y", "cy", "dx") if k in f}


def mouth_probe_at(model, W, H, aspect, override=None):
    """Normalised layer coords of the mouth anchor under `framing` (aspect = model width / height in model units)."""
    an = model.get("anchors") or {}
    if "mouth" not in an or (override and "zoom" in override):
        return (model.get("frame") or {}).get("mouth_at")
    f = framing(model, H, override)
    mx, my = an["mouth"]
    x = 0.5 + (mx - f["at_x"][0]) * f["zoom"] * H * aspect / W
    y = f["at_y"][1] + (my - f["at_y"][0]) * f["zoom"]
    return [x, y]


def _track_len(v):
    if isinstance(v, dict):
        return max([len(v[k]) for k in ("set", "add", "mul") if v.get(k) is not None] + [len(b[0]) for b in v.get("blend") or []] + [1])
    return len(v)


def render_stills(model_name, width, height, tracks, *, frame=None, warmup=60, seed=1, fps=30, supersample=1, describe=False, readback=()):
    """Render one still per track frame with constant / stepped parameter tracks (no audio). `tracks` = {id: values}
    or performance layers ({id: {set, blend, add, mul}}). Returns (frames uint8 [n, H, W, 4] straight alpha, info
    {width, height: model units, missing, ranges (describe=True): [[id, min, max, default], ...]}). `supersample` = k
    renders k times larger and box-filters the premultiplied pixels down. `readback` = parameter ids whose applied value per frame
    goes into info["readback"] (what the renderer really set). Used by `probe_face`, portraits and tests."""
    from .perform import job_tracks
    model = resolve_model(model_name)
    n = max(_track_len(v) for v in tracks.values())
    k = max(1, int(supersample))
    d = tempfile.mkdtemp(prefix="l2d-still-")
    layers = {key: (v if isinstance(v, dict) else {"set": np.asarray(v, float)}) for key, v in tracks.items()}
    fj = frame_job(model, _scaled_frame(model, frame, height, k), height * k)
    chromium = os.environ.get("PROMO_CHROMIUM") or _default_chromium()
    if model.get("renderer") == "mesh":
        from . import mesh_avatar
        job = mesh_avatar.job(model, width=width * k, height=height * k, fps=fps, frames=n, seed=seed, warmup=warmup, frame=fj, layers=layers,
                              readback_path=os.path.join(d, "rb.json"), premultiplied=k > 1, chromium=chromium, settle=0.25)
    else:
        job = dict(modelDir=model["dir"], model3=os.path.relpath(model["model3_path"], model["dir"]), core=model["core"], width=width * k,
                   height=height * k, fps=fps, frames=n, seed=seed, warmup=warmup, frame=fj, tracks=job_tracks(layers), readback=list(readback),
                   readbackPath=os.path.join(d, "rb.json"), premultiplied=k > 1, describe=describe, chromium=chromium)
    jpath = os.path.join(d, "job.json")
    json.dump(job, open(jpath, "w"))
    with render_lock(lambda *a: None):
        raw = subprocess.run(["nice", "-n", "10", os.environ.get("PROMO_NODE", "node"), os.path.join(L2D_DIR, "render.mjs"), jpath],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=L2D_DIR, check=True).stdout
    rbj = json.load(open(job["readbackPath"]))
    info = dict(rbj.get("info", {}), readback=rbj.get("frames"))
    shutil.rmtree(d, ignore_errors=True)
    fr = np.frombuffer(raw, np.uint8).reshape(n, height * k, width * k, 4)
    if k > 1:
        f = fr.reshape(n, height, k, width, k, 4).astype(np.float32).mean((2, 4))     # premultiplied box filter
        a = f[..., 3:4]
        rgb = np.where(a > 0, f[..., :3] * 255.0 / np.maximum(a, 1e-6), 0)
        fr = np.concatenate([np.clip(rgb, 0, 255), a], -1).round().astype(np.uint8)
    return fr, info


def _diff_centroid(a, b, thr=24):
    d = np.abs(a[..., :3].astype(np.int16) - b[..., :3].astype(np.int16)).max(-1) + np.abs(a[..., 3].astype(np.int16) - b[..., 3].astype(np.int16))
    ys, xs = np.nonzero(d > thr)
    if len(ys) < 10:
        return None
    return dict(x=float(np.median(xs)), y=float(np.median(ys)), box=[int(np.percentile(xs, 2)), int(np.percentile(ys, 2)),
                                                                  int(np.percentile(xs, 98)), int(np.percentile(ys, 98))])


def probe_face(model_name, width, height, frame=None):
    """Locate the eyes and the mouth in RENDERED pixels, model-agnostically: diff a frame with eyes open vs closed,
    and mouth shut vs open. Returns {eyes: {x, y, box}, mouth: {...}, eye_mouth_px} in layer pixels."""
    model = resolve_model(model_name)
    mo = (model.get("mouth") or {}).get("open") or ["ParamMouthOpenY"]
    tr = {"ParamEyeLOpen": [1, 0, 1], "ParamEyeROpen": [1, 0, 1]}
    for m in mo:
        tr[m] = [0, 0, 1]
    fr, info = render_stills(model_name, width, height, tr, frame=frame)
    eyes, mouth = _diff_centroid(fr[0], fr[1]), _diff_centroid(fr[0], fr[2])
    return dict(eyes=eyes, mouth=mouth, eye_mouth_px=(mouth["y"] - eyes["y"]) if eyes and mouth else None, info=info, frame0=fr[0])


def _default_chromium():
    """Prefer Playwright's headless shell if it is installed on the box; else Playwright's default."""
    base = os.path.expanduser("~/.cache/ms-playwright")
    if os.path.isdir(base):
        for d in sorted(os.listdir(base), reverse=True):
            p = os.path.join(base, d, "chrome-headless-shell-linux64", "chrome-headless-shell")
            if d.startswith("chromium_headless_shell") and os.path.exists(p):
                return p
    return None


def read_layer(path, W, H):
    """Iterate RGBA frames (numpy HxWx4 uint8) of a rendered layer (ProRes 4444 / VP9 alpha / png pattern)."""
    cmd = ["ffmpeg", "-v", "error", "-threads", "2"]
    if path.endswith(".webm"):
        cmd += ["-c:v", "libvpx-vp9"]
    cmd += ["-i", path, "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 8)
    size = W * H * 4
    try:
        while True:
            b = p.stdout.read(size)
            if len(b) < size:
                break
            yield np.frombuffer(b, np.uint8).reshape(H, W, 4)
    finally:
        p.stdout.close()
        p.kill()
        p.wait()


def pixel_mouth(layer, W, H, at, half=(22, 12)):
    """Mouth openness measured from the RENDERED pixels: mean darkness in a small box around the mouth (`at` =
    normalised layer coords for the registry framing). Independent of the parameter track, so its lag against the
    audio checks the whole render path (frame indexing, encode, decode)."""
    cx, cy = int(at[0] * W), int(at[1] * H)
    vals = []
    for f in read_layer(layer, W, H):
        roi = f[cy - half[1]: cy + half[1], cx - half[0]: cx + half[0]].astype(np.float32)
        a = roi[..., 3:4] / 255.0
        lum = (roi[..., :3].mean(-1, keepdims=True) * a + 255 * (1 - a))[..., 0]
        vals.append(float((255 - lum).mean()))
    v = np.array(vals)
    return v - v.min()


# ---------------------------------------------------------------- portraits / mood sheet
SHEET_FONTS = ["/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf", "/System/Library/Fonts/SFNS.ttf",
               "/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def sheet_font(size):
    from PIL import ImageFont
    for p in SHEET_FONTS:
        if os.path.exists(p):
            return ImageFont.truetype(p, int(size))
    return ImageFont.load_default()


PORTRAIT = dict(head_frac=0.42, head_top_at=0.16)       # bust portrait framing (head = 42 % of the tile)


def portrait_frame(model, H, base=PORTRAIT, margin=6):
    """Portrait framing with room above the head for a hat / ahoge (the silhouette top never touches the tile edge)."""
    if not model.get("anchors"):
        return None
    f = framing(model, H, base)
    if f["top_px"] is not None and f["top_px"] < margin:
        pad = margin - f["top_px"]
        return dict(base, pad_top=pad)
    return dict(base)


def mood_stills(model_name, moods=None, size=(360, 420), supersample=2, talk=0.0):
    """One bust still per mood (neutral first), the mood held at full weight. Returns [(mood, RGBA image)]."""
    from PIL import Image
    from . import perform as PF
    model = resolve_model(model_name)
    moods = list(moods or PF.MOODS)
    if "neutral" in moods:
        moods.remove("neutral")
    moods = ["neutral"] + moods
    n = len(moods)
    eyes = tuple(model["groups"].get("EyeBlink") or ("ParamEyeLOpen", "ParamEyeROpen"))
    L = {e: {"set": np.ones(n)} for e in eyes}
    mo = model.get("mouth") or {}
    if talk:
        for pid in (list((mo.get("vowels") or {}).values())[:1] or list(mo.get("open") or [])):
            L[pid] = {"set": np.full(n, float(talk))}
    smile = mo.get("form") or ("ParamMouthUp" if "ParamMouthUp" in (model.get("param_ids") or []) else None)
    for i, m in enumerate(moods):
        w = np.zeros(n)
        w[i] = 1.0
        if m != "neutral":
            targets, _, _ = PF.mood_targets(model, m)
            ids = set(model.get("param_ids") or [])
            PF.apply_targets(L, [t for t in targets if not ids or t[0] in ids], w)
        if smile and not talk:
            PF.add(L, smile, w * float(model.get("rest_smile", 0.35)) * PF.REST_SMILE.get(m, 1.0))
    W, H = size
    fr, _ = render_stills(model_name, W, H, L, frame=portrait_frame(model, H), supersample=supersample, warmup=40)
    return [(m, Image.fromarray(fr[i], "RGBA")) for i, m in enumerate(moods)]


def mood_sheet(model_name, out, moods=None, size=(360, 420), cols=5, bg=(30, 32, 44)):
    """Portrait sheet PNG: one tile per mood with its name under it (real renders of the model)."""
    from PIL import Image, ImageDraw
    tiles = mood_stills(model_name, moods, size)
    W, H = size
    lab = 44
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * W, rows * (H + lab)), bg)
    d = ImageDraw.Draw(sheet)
    f = sheet_font(24)
    for k, (m, im) in enumerate(tiles):
        x, y = (k % cols) * W, (k // cols) * (H + lab)
        tile = Image.new("RGBA", (W, H), bg + (255,))
        tile.alpha_composite(im)
        sheet.paste(tile.convert("RGB"), (x, y))
        tw = d.textlength(m, font=f)
        d.text((x + (W - tw) / 2, y + H + 8), m, font=f, fill=(220, 222, 235))
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    sheet.save(out)
    return out


# ---------------------------------------------------------------- bring your own model
def find_model3(path):
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path):
        if not path.endswith(".model3.json"):
            raise Live2DError(f"{path}: expected a .model3.json (Cubism 3+ model) or the folder holding one")
        return path
    if not os.path.isdir(path):
        raise Live2DError(f"{path}: no such file or folder")
    found = []
    for root, _, files in os.walk(path):
        found += [os.path.join(root, f) for f in files if f.endswith(".model3.json")]
    if not found:
        raise Live2DError(f"{path}: no .model3.json inside (Cubism 2 .model.json models are not supported)")
    return sorted(found, key=lambda p: (p.count(os.sep), p))[0]


# eye / mouth lines -> head top, chin, chest, from the two sample rigs' measured anchors (anime proportions):
# head_top = eyes - HT * (mouth - eyes); chin = mouth + CH * (mouth - eyes); chest = chin + CS * (chin - head_top)
ANCHOR_RULE = dict(HT=2.4, CH=0.25, CS=0.7)


def measure_anchors(model_name, H=1400):
    """Framing anchors of a model from real renders: alpha bounding box of a full-body still (silhouette top, face
    centre), eye and mouth lines from `probe_face` (eyes open vs shut, mouth shut vs open); head top, chin and chest
    follow from those by ANCHOR_RULE. Returns (anchors in model units, report)."""
    full = {"zoom": 1.0, "cy": 0.5}
    W = H
    r = probe_face(model_name, W, H, frame=full)
    info = r["info"]
    mw = info["width"] / info["height"] * H                     # model width in px at zoom 1
    x0 = W / 2 - mw / 2
    a = r["frame0"][..., 3]
    rows = np.nonzero(a.max(1) > 8)[0]
    if not len(rows) or not r["eyes"] or not r["mouth"]:
        raise Live2DError(f"{model_name}: could not find the eyes / mouth by blinking and opening the mouth (no EyeBlink / LipSync "
                          f"parameters?); write the anchors by hand in {user_registry_path()}")
    e, mo = r["eyes"]["y"] / H, r["mouth"]["y"] / H
    d = max(mo - e, 0.01)
    k = ANCHOR_RULE
    head_top = e - k["HT"] * d
    chin = mo + k["CH"] * d
    chest = chin + k["CS"] * (chin - head_top)
    top = max(0.0, rows[0] / H - 0.003)
    ex = (r["eyes"]["box"][0] + r["eyes"]["box"][2]) / 2       # midpoint of the two eyes (the blink pixels' median leans to the busier eye)
    cx = (ex - x0) / mw
    # widest point of the bust (down to ~2.6 heads under the head top: the deepest podcast crop), from the face centre
    bust = a[int(top * H): int(min(1.0, head_top + 2.6 * (chin - head_top)) * H)]
    xs = np.nonzero(bust.max(0) > 8)[0]
    half_w = max(ex - xs.min(), xs.max() - ex) / H if len(xs) else 0.2
    an = dict(top=round(min(top, head_top), 3), head_top=round(head_top, 3), chin=round(chin, 3), chest=round(chest, 3), cx=round(cx, 3),
              mouth=[round((r["mouth"]["x"] - x0) / mw, 3), round(mo, 3)], half_w=round(half_w + 0.004, 3))
    return an, dict(eyes_y=round(e, 4), mouth_y=round(mo, 4), silhouette_top=round(rows[0] / H, 4), size=[W, H])


def add_model(path, mid, name, licence, source_url, ctype, credit=None, force=False, measure=True, log=print, likeness=None, consent=None):
    """Register a model the person owns / commissioned / bought (`promo live2d add`). The files stay where they are
    (never copied, never committed). Licence gate: own | commissioned | original only, with a licence and a source; a
    model of the person's own likeness (`likeness="own"`) also needs their consent. `path` = a Live2D model (.model3.json
    or its folder) or a Mesh Avatar Studio project (rig.json + built/), which renders through promo.mesh_avatar."""
    from . import mesh_avatar
    from . import perform as PF
    if ctype in REFUSED_TYPES:
        raise Live2DError(f"character type {ctype!r} is refused: a collaboration or third-party character's terms do not cover a promo")
    if ctype not in BYO_TYPES:
        raise Live2DError(f"--type must be one of {', '.join(BYO_TYPES)}")
    if not licence or not source_url:
        raise Live2DError("a model of your own needs --licence (what lets you use it) and --source (where it came from: the artist, the store page)")
    if likeness not in (None, "own"):
        raise Live2DError("--likeness can only be own: never register anyone else's face or voice")
    if likeness == "own" and not str(consent or "").strip():
        raise Live2DError("a model of the person's own likeness needs --consent (who agreed, when, for what use)")
    if not mid or not mid.replace("-", "").replace("_", "").isalnum():
        raise Live2DError("--id must be letters, digits, - or _")
    if mid in registry(user=False)["models"]:
        raise Live2DError(f"{mid!r} is a sample model id; pick another")
    reg_p = user_registry_path()
    have = user_models(reg_p)
    if mid in have and not force:
        raise Live2DError(f"{mid!r} is already registered ({have[mid].get('model3') or have[mid].get('avatar')}); --force replaces it")
    if mesh_avatar.is_avatar_dir(path):
        entry = dict(mesh_avatar.entry(path, name or mid, licence, source_url, ctype, credit, likeness, consent), added=time.strftime("%Y-%m-%d"))
        missing = mesh_avatar.missing_drawings(entry["avatar"])
        if missing:
            log(f"warning: {mid} has some drawn eyes / mouths but not {', '.join(missing)}: with a partial set the runtime erases "
                f"the eyes on every blink. Import all of {', '.join(mesh_avatar.DRAWINGS)} in the studio, or none")
        return _register(reg_p, mid, entry, measure, log)
    p3 = find_model3(path)
    inf = model3_info(p3)
    ids = set(inf["param_ids"])
    vow = {v: f"Param{v}" for v in PF.VOWELS} if all(f"Param{v}" in ids for v in PF.VOWELS) else None
    lip = inf["groups"].get("LipSync") or ([x for x in ("ParamMouthOpenY", "ParamA") if x in ids][:1] if ids else ["ParamMouthOpenY"])
    mouth = dict(open=list(lip)[:1], form="ParamMouthForm" if (not ids or "ParamMouthForm" in ids) else None)
    if vow:
        mouth["vowels"] = vow
    entry = dict(name=name or mid, character_type=ctype, model3=p3, licence=licence, source_url=source_url, credit=credit or "",
                 mouth=mouth, moods=PF.auto_moods(list(inf["expressions"])), rest_smile=0.35,
                 expressions=sorted(inf["expressions"]), motions=sorted(k for k in inf["motions"] if ":" not in k),
                 added=time.strftime("%Y-%m-%d"))
    if likeness:
        entry.update(likeness=likeness, consent=consent)
    return _register(reg_p, mid, entry, measure, log)


def _register(reg_p, mid, entry, measure, log):
    """Write a user model, then measure its framing anchors from real renders (any renderer)."""
    _write_user(reg_p, mid, entry)
    if measure:
        try:
            an, rep = measure_anchors(mid)
            entry["anchors"] = an
            entry["measured"] = rep
            _write_user(reg_p, mid, entry)
        except (Live2DError, subprocess.CalledProcessError) as e:
            log(f"anchors not measured ({e}); framing falls back to a whole-model view until you add `anchors:`")
    return dict(id=mid, registry=reg_p, **json.loads(json.dumps(entry, default=float)))


def _write_user(path, mid, entry):
    data = {"models": user_models(path)}
    data["models"][mid] = json.loads(json.dumps(entry, default=float))     # measured anchors are numpy floats: plain numbers in the YAML
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("# Your own Live2D models (`promo live2d add`). The files stay where they are and are never committed.\n")
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    os.replace(tmp, path)


def main(argv=None):
    """`promo live2d fetch|models|add|stills|render|lag` (no promo.yaml needed)."""
    import argparse
    ap = argparse.ArgumentParser(prog="promo live2d", description="offline Live2D host renderer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download Cubism Core + sample models from live2d.com (sha256-verified)")
    f.add_argument("models", nargs="*")
    f.add_argument("--force", action="store_true")
    m = sub.add_parser("models", help="list models (samples + your own) with licence, moods, expressions and motions")
    m.add_argument("--json", action="store_true")
    ad = sub.add_parser("add", help="register a model you own / commissioned / bought (files stay where they are)")
    ad.add_argument("path", help=".model3.json or the folder holding it, or a Mesh Avatar Studio project (rig.json + built/)")
    ad.add_argument("--id", required=True)
    ad.add_argument("--name")
    ad.add_argument("--licence", required=True, help="what lets you use it (e.g. 'commissioned from X, commercial use, contract 2026-09')")
    ad.add_argument("--source", required=True, help="where it came from (artist page, store page, contract URL)")
    ad.add_argument("--type", required=True, choices=list(BYO_TYPES) + list(REFUSED_TYPES), dest="ctype")
    ad.add_argument("--credit", help="credit line for the end card (e.g. 'Illustration: X; Rigging: Y')")
    ad.add_argument("--likeness", choices=["own"], help="own = the character is drawn from the person themselves (needs --consent)")
    ad.add_argument("--consent", help="the person's consent for their own likeness: who agreed, when, for what use")
    ad.add_argument("--force", action="store_true")
    ad.add_argument("--no-measure", action="store_true", help="skip the anchor measurement renders")
    ad.add_argument("--json", action="store_true")
    sl = sub.add_parser("stills", help="real portrait renders: one still, or a mood sheet (--moods)")
    sl.add_argument("--model", required=True)
    sl.add_argument("--moods", nargs="?", const="all", help="all, or a comma list (happy,laugh,...)")
    sl.add_argument("--out", required=True, help="PNG")
    sl.add_argument("--size", default="360x420")
    r = sub.add_parser("render", help="render one host layer")
    r.add_argument("--model", required=True)
    r.add_argument("--wav")
    r.add_argument("--partner-wav", help="the other host's WAV (listening nods)")
    r.add_argument("--out", required=True, help=".mov = ProRes 4444 alpha, .webm = VP9 alpha, dir or %05d.png = PNG sequence")
    r.add_argument("--duration", type=float)
    r.add_argument("--fps", type=int, default=30)
    r.add_argument("--size", default="640x720")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--gaze", type=float, default=0.0, help="listening host turns: -1 = left, +1 = right (e.g. toward the app screen)")
    r.add_argument("--lines", help="JSON/YAML file of script lines in seconds [{t0, t1, mood, gesture, look}] for this host")
    r.add_argument("--supersample", type=int, default=2, help="2 = render at 2x and scale down (crisp); 1 = draft")
    r.add_argument("--bg", help="green (or a colour) = opaque green-screen H.264 instead of alpha")
    r.add_argument("--json", action="store_true")
    g = sub.add_parser("lag", help="lip lag of a mouth track (.npy) against a WAV")
    g.add_argument("mouth")
    g.add_argument("wav")
    g.add_argument("--fps", type=int, default=30)
    a = ap.parse_args(argv)
    log = (lambda *x: print(*x, file=sys.stderr)) if getattr(a, "json", False) else print
    try:
        if a.cmd == "fetch":
            fetch(a.models or None, a.force)
        elif a.cmd == "models":
            reg = registry()
            rows = []
            for k, mm in reg["models"].items():
                row = dict(id=k, name=mm.get("name"), type=mm.get("character_type"), own=bool(mm.get("user")), licence=mm.get("licence"),
                           source_url=mm.get("source_url"), credit=mm.get("credit"))
                try:
                    rm = resolve_model(k)
                    from .perform import MOODS
                    row.update(ready=True, expressions=sorted(rm["expressions"]), motions=sorted(x for x in rm["motions"] if ":" not in x),
                               moods={md: ((mm.get("moods") or {}).get(md) or "generic") for md in MOODS if md != "neutral"},
                               vowels=bool((mm.get("mouth") or {}).get("vowels")))
                except Live2DError as e:
                    row.update(ready=False, why=str(e))
                rows.append(row)
            if a.json:
                print(json.dumps(dict(ok=True, models=rows, notice=reg["notice"]["long"]), indent=1))
            else:
                for row in rows:
                    print(f"{row['id']:<10} {row['type'] or '-':<13} {'own ' if row['own'] else ''}{row['name']}  {row['source_url']}")
                    if row.get("ready"):
                        print(f"{'':<10} expressions: {', '.join(row['expressions']) or '-'}; motions: {', '.join(row['motions']) or '-'}; "
                              f"mouth: {'A/I/U/E/O vowels' if row['vowels'] else 'open + form'}")
                    elif row["type"] == "original" or row["own"]:
                        print(f"{'':<10} not ready: {row['why']}")
                print("notice:", reg["notice"]["long"])
        elif a.cmd == "add":
            rep = add_model(a.path, a.id, a.name, a.licence, a.source, a.ctype, a.credit, a.force, not a.no_measure, log=log,
                            likeness=a.likeness, consent=a.consent)
            if a.json:
                print(json.dumps(dict(ok=True, **rep), indent=1, default=str))
            else:
                kind = "mesh avatar" if rep.get("renderer") == "mesh" else "Live2D"
                print(f"registered {rep['id']} ({kind}, {rep['character_type']}) in {rep['registry']}: {rep.get('model3') or rep.get('avatar')}")
                print(f"  moods mapped from expressions: {rep['moods'] or 'none (generic moods on the standard parameters)'}")
                print(f"  anchors: {rep.get('anchors') or 'not measured'}")
                print(f"  check it: promo live2d stills --model {rep['id']} --moods --out /tmp/{rep['id']}-moods.png")
        elif a.cmd == "stills":
            W, H = (int(x) for x in a.size.lower().split("x"))
            if a.moods:
                from .perform import MOODS
                ms = None if a.moods == "all" else [x.strip() for x in a.moods.split(",") if x.strip()]
                bad = [x for x in ms or [] if x not in MOODS]
                if bad:
                    raise Live2DError(f"unknown mood(s) {bad}; have {', '.join(MOODS)}")
                print(mood_sheet(a.model, a.out, ms, (W, H)))
            else:
                (_, im), = mood_stills(a.model, ["neutral"], (W, H))
                os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
                im.save(a.out)
                print(a.out)
        elif a.cmd == "render":
            W, H = (int(x) for x in a.size.lower().split("x"))
            lines = None
            if a.lines:
                with open(a.lines) as fh:
                    lines = yaml.safe_load(fh)
            rep = render_host(a.model, a.out, wav=a.wav, partner_wav=a.partner_wav, duration=a.duration, fps=a.fps, width=W, height=H,
                              seed=a.seed, gaze=a.gaze, bg=a.bg, log=log, lines=lines, supersample=a.supersample)
            print(json.dumps(rep, indent=1) if a.json else f"wrote {rep['out']}: {rep['frames']} frames, {rep['s_per_output_s']} s per output second, "
                  f"lip lag {rep.get('lip_lag_applied')}")
        elif a.cmd == "lag":
            y, r = load_wav(a.wav)
            print(json.dumps(lip_lag(np.load(a.mouth), y, r, a.fps)))
    except Live2DError as e:
        if getattr(a, "json", False):
            print(json.dumps(dict(ok=False, error=str(e))))
        print(f"promo live2d: error: {e}", file=sys.stderr)
        return 2
    return 0
