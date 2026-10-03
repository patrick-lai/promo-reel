"""Offline, deterministic Live2D host renderer (prototype).

Pipeline (one host = one layer):
    WAV --(lip_track: 10 ms envelope, fast attack / eased close, zero-lag by construction)--> ParamMouthOpenY per frame
    seed --(idle_tracks: blink timer, breath, small head/body sway, optional listening nod)--> per-frame params
    nice -n 10 node live2d/render.mjs job.json  (headless Chromium + pixi.js + pixi-live2d-display + official
    Live2D Cubism Core; model clock advanced exactly 1/fps per frame)  | nice -n 10 ffmpeg -threads 2 -> ProRes 4444
    / VP9 alpha / PNG sequence

Models and the Cubism Core come from `live2d/assets.yaml` and are fetched from live2d.com (sha256-pinned) into
`live2d/media/` (gitignored, never redistributed). Only Live2D Original Characters are accepted. Renders take a
the box-wide heavy-work lock (/tmp/commission-ai-cargo.lock, shared with Commission-ai's cargo test gates).

The lip envelope follows /workspace/ai-interview-host/src/audio/vowel.ts (LipSync: level vs a decaying peak,
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
def registry(path=REGISTRY):
    with open(path) as f:
        return yaml.safe_load(f)


def model_entry(name, reg=None):
    reg = reg or registry()
    m = (reg.get("models") or {}).get(name)
    if not m:
        raise Live2DError(f"unknown Live2D model {name!r}; known: {sorted(reg.get('models') or {})}")
    if m.get("character_type") != "original":
        raise Live2DError(f"{name}: character_type={m.get('character_type')!r}. Only Live2D Original Characters may be used in a "
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
    reg = registry()
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
    d = model_dir(name)
    p = os.path.join(d, m["model3"])
    core = _abs(reg["runtime"]["path"])
    if not os.path.exists(p) or not os.path.exists(core):
        raise Live2DError(f"{name}: model or Cubism Core not fetched; run `promo live2d fetch`")
    if sha256_file(core) != reg["runtime"]["sha256"]:
        raise Live2DError("Cubism Core sha256 differs from live2d/assets.yaml; run `promo live2d fetch --force`")
    with open(p) as f:
        m3 = json.load(f)
    groups = {g["Name"]: g["Ids"] for g in m3.get("Groups", [])}
    return dict(m, id=name, dir=d, model3_path=p, core=core, groups=groups, notice=reg["notice"])


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


def host_tracks(model, n, fps, seed, wav=None, partner_wav=None, gaze=0.0, sr=None):
    """All per-frame parameter tracks for one host. Returns (tracks {ParamId: np.array}, info)."""
    mouth = partner = None
    info = {}
    if wav:
        y, r = load_wav(wav)
        lt = lip_track(y, r, fps, n, form=bool(model["mouth"].get("form")))
        mouth = lt["open"]
        info.update(lead_s=lt["lead_s"], lag=lip_lag(mouth, y, r, fps))
    if partner_wav:
        y2, r2 = load_wav(partner_wav)
        partner = lip_track(y2, r2, fps, n, form=False)["open"]
    eyes = tuple(model["groups"].get("EyeBlink") or ("ParamEyeLOpen", "ParamEyeROpen"))
    tr = idle_tracks(n, fps, seed, mouth, partner, gaze, eyes)
    open_ids = list(dict.fromkeys(list(model["groups"].get("LipSync") or []) + list(model["mouth"].get("open") or [])))
    m = mouth if mouth is not None else np.zeros(n)
    for pid in open_ids:
        tr[pid] = m
    if model["mouth"].get("form") and mouth is not None:
        tr[model["mouth"]["form"]] = lt["form"]
    info["mouth_ids"] = open_ids
    return tr, info, m


# ---------------------------------------------------------------- render
def render_lock(log=print):
    """The shared heavy-work lock (/tmp/commission-ai-cargo.lock, see promo.lock); replaces the old live2d-only lock."""
    from .lock import heavy_lock
    return heavy_lock("live2d host render", log=lambda *a: log(*a))


def ffmpeg_out(out, W, H, fps, fmt=None, bg=None):
    """Encoder args for an RGBA rawvideo pipe -> transparent layer (or green screen with bg='green')."""
    fmt = fmt or {".mov": "prores4444", ".webm": "vp9", ".png": "png"}.get(os.path.splitext(out)[1].lower(), "prores4444")
    cmd = ["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-threads", "2"]
    if bg:
        col = {"green": "0x00b140"}.get(bg, bg)
        cmd = ["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s={W}x{H}:r={fps}",
               "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-threads", "2",
               "-filter_complex", "[0][1]overlay=shortest=1:format=auto"]
        return cmd + ["-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", out]
    if fmt == "prores4444":
        return cmd + ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16", "-vendor", "apl0", out]
    if fmt == "vp9":
        return cmd + ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4", out]
    if fmt == "png":
        os.makedirs(out if os.path.isdir(out) or not out.endswith(".png") else os.path.dirname(out), exist_ok=True)
        pattern = out if "%" in out else os.path.join(out if not out.endswith(".png") else os.path.dirname(out), "%05d.png")
        return cmd + ["-c:v", "png", "-f", "image2", pattern]
    raise Live2DError(f"unknown format {fmt}")


def render_host(model_name, out, *, wav=None, partner_wav=None, duration=None, fps=30, width=640, height=720, seed=1,
                gaze=0.0, fmt=None, bg=None, frame=None, log=print, warmup=45):
    """Render one host layer. Returns a report dict (frames, secs, s per output second, lip lag, files)."""
    model = resolve_model(model_name)
    if duration is None:
        if not wav:
            raise Live2DError("need --wav or --duration")
        import soundfile as sf
        duration = sf.info(wav).duration
    n = int(round(duration * fps))
    tracks, info, mouth = host_tracks(model, n, fps, seed, wav, partner_wav, gaze)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    side = os.path.splitext(out)[0]
    job = dict(modelDir=model["dir"], model3=os.path.relpath(model["model3_path"], model["dir"]), core=model["core"], width=width, height=height,
               fps=fps, frames=n, seed=seed, warmup=warmup, frame=frame_job(model, frame, height),
               tracks={k: dict(v=[round(float(x), 4) for x in v], mode="set") for k, v in tracks.items()},
               readback=info["mouth_ids"][:1], readbackPath=side + ".readback.json",
               chromium=os.environ.get("PROMO_CHROMIUM") or _default_chromium())
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(job, f)
        jpath = f.name
    node = os.environ.get("PROMO_NODE", "node")
    t0 = time.time()
    with render_lock(log):
        log(f"live2d render {model_name}: {n} frames {width}x{height} @ {fps} fps -> {out}")
        p1 = subprocess.Popen(["nice", "-n", "10", node, os.path.join(L2D_DIR, "render.mjs"), jpath], stdout=subprocess.PIPE, cwd=L2D_DIR)
        p2 = subprocess.Popen(ffmpeg_out(out, width, height, fps, fmt, bg), stdin=p1.stdout)
        p1.stdout.close()
        rc2 = p2.wait()
        rc1 = p1.wait()
    os.unlink(jpath)
    if rc1 or rc2:
        raise Live2DError(f"render failed (node rc={rc1}, ffmpeg rc={rc2})")
    secs = time.time() - t0
    rb = json.load(open(job["readbackPath"]))
    applied = np.array([fr.get(job["readback"][0], 0.0) for fr in rb["frames"]]) if job["readback"] else mouth
    rep = dict(model=model_name, out=os.path.abspath(out), frames=n, fps=fps, size=[width, height], seed=seed, secs=round(secs, 1),
               s_per_output_s=round(secs / (n / fps), 2), lead_s=info.get("lead_s"), lip_lag_track=info.get("lag"),
               notice=model["notice"]["short"], credit=model.get("credit"))
    if wav:
        y, r = load_wav(wav)
        rep["lip_lag_applied"] = lip_lag(applied, y, r, fps)     # what the renderer actually set, frame by frame
        rep["mouth_offset_frames"] = int(np.argmax(np.correlate(applied - applied.mean(), mouth - mouth.mean(), "full")) - (n - 1))
    np.save(side + ".mouth.npy", mouth)
    inf = rb.get("info") or {}
    aspect = (inf.get("width") or 1) / (inf.get("height") or 1)
    at = mouth_probe_at(model, width, height, aspect, frame)
    fr_px = framing(model, height, frame)
    rep["framing"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in fr_px.items()}
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
HEAD_FRAC = 0.38
HEAD_TOP_AT = 0.30


def framing(model, H, override=None):
    """Bust framing from the model's anchors: {zoom, at_x, at_y, head_top_px, chin_px, chest_px, head_px} for a layer
    of height H. Same rule for every model, so heads land at the same height and scale. `override` (host `frame:`)
    may set head_frac / head_top_at, or a legacy {zoom, cy, dx} (then the px fields are None)."""
    o = dict(override or {})
    an = model.get("anchors")
    if "zoom" in o or not an:
        f = dict(model.get("frame") or {"zoom": 1.0, "cy": 0.5}, **o)
        return dict(f, head_top_px=None, chin_px=None, chest_px=None, head_px=None)
    hf, ht = float(o.get("head_frac", HEAD_FRAC)), float(o.get("head_top_at", HEAD_TOP_AT))
    head = an["chin"] - an["head_top"]
    if head <= 0 or not (an["head_top"] < an["chin"] < an["chest"]):
        raise Live2DError(f"{model.get('id')}: anchors must satisfy head_top < chin < chest (got {an})")
    zoom = hf / head                                    # model height in layer heights
    px = lambda y: (ht + (y - an["head_top"]) * zoom) * H
    return dict(zoom=zoom, at_x=[an.get("cx", 0.5), 0.5], at_y=[an["head_top"], ht],
                head_top_px=px(an["head_top"]), chin_px=px(an["chin"]), chest_px=px(an["chest"]), head_px=hf * H)


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


def render_stills(model_name, width, height, tracks, *, frame=None, warmup=60, seed=1, fps=30):
    """Render len(track) still frames with constant/stepped parameter tracks (no audio). Returns (frames uint8
    [n, H, W, 4], info {width, height: model units, ...}). Used by `probe_face` and the framing tests."""
    model = resolve_model(model_name)
    n = max(len(v) for v in tracks.values())
    d = tempfile.mkdtemp(prefix="l2d-still-")
    job = dict(modelDir=model["dir"], model3=os.path.relpath(model["model3_path"], model["dir"]), core=model["core"], width=width,
               height=height, fps=fps, frames=n, seed=seed, warmup=warmup, frame=frame_job(model, frame, height),
               tracks={k: dict(v=[float(x) for x in v], mode="set") for k, v in tracks.items()}, readback=[],
               readbackPath=os.path.join(d, "rb.json"), chromium=os.environ.get("PROMO_CHROMIUM") or _default_chromium())
    jpath = os.path.join(d, "job.json")
    json.dump(job, open(jpath, "w"))
    with render_lock(lambda *a: None):
        raw = subprocess.run(["nice", "-n", "10", os.environ.get("PROMO_NODE", "node"), os.path.join(L2D_DIR, "render.mjs"), jpath],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=L2D_DIR, check=True).stdout
    info = json.load(open(job["readbackPath"])).get("info", {})
    shutil.rmtree(d, ignore_errors=True)
    return np.frombuffer(raw, np.uint8).reshape(n, height, width, 4), info


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


def main(argv=None):
    """`promo live2d fetch|render|models|lag` (no promo.yaml needed)."""
    import argparse
    ap = argparse.ArgumentParser(prog="promo live2d", description="offline Live2D host renderer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download Cubism Core + sample models from live2d.com (sha256-verified)")
    f.add_argument("models", nargs="*")
    f.add_argument("--force", action="store_true")
    sub.add_parser("models", help="list models with licence + notices")
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
            for k, m in reg["models"].items():
                print(f"{k:<8} {m.get('character_type'):<13} {m.get('name')}  {m.get('source_url')}")
            print("notice:", reg["notice"]["long"])
        elif a.cmd == "render":
            W, H = (int(x) for x in a.size.lower().split("x"))
            rep = render_host(a.model, a.out, wav=a.wav, partner_wav=a.partner_wav, duration=a.duration, fps=a.fps, width=W, height=H,
                              seed=a.seed, gaze=a.gaze, bg=a.bg, log=log)
            print(json.dumps(rep, indent=1) if a.json else f"wrote {rep['out']}: {rep['frames']} frames, {rep['s_per_output_s']} s per output second, "
                  f"lip lag {rep.get('lip_lag_applied')}")
        elif a.cmd == "lag":
            y, r = load_wav(a.wav)
            print(json.dumps(lip_lag(np.load(a.mouth), y, r, a.fps)))
    except Live2DError as e:
        print(f"promo live2d: error: {e}", file=sys.stderr)
        return 2
    return 0
