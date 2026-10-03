"""Mix + duck + master (port of build_mix.py, generic). `promo mix`.

Inputs: build/audio/events.json, build/audio/music-edit.wav, SFX wavs (assets), VO stems (build/vo/vo.json).
Spec (mix:): sr, bus_db {music, sfx, vo}, vo_line_lufs, duck {db, attack, release, pre, post}, fade_out, masters [...]
SFX library entries may carry `duck_music: {db, dur}` (music dips under that SFX); `typing` entries use
{variants, gain_jitter [lo, hi], pan_jitter, seed} with ONE seeded rng consumed in event order (same as legacy).
Outputs: build/audio/mix-<master>.wav, build/audio/stems/{music,sfx,vo}.wav, build/audio/mix-report.json
"""
from __future__ import annotations

import json
import os

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.ndimage import minimum_filter1d
from scipy.signal import resample_poly

from .assets import asset_path, load_manifest
from .events import events_path
from .music import music_path


def db(v):
    return 10 ** (v / 20)


def load(p, sr_target):
    x, sr = sf.read(p, always_2d=True)
    x = x.astype(np.float64)
    if sr != sr_target:
        x = resample_poly(x, sr_target, sr, axis=0)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, 1)
    return x


def smooth(gain, att, rel, SR):
    out = np.zeros_like(gain)
    s = 0.0
    a = np.exp(-1 / (att * SR))
    r = np.exp(-1 / (rel * SR))
    for i in range(0, len(gain), 48):          # 1 ms control rate
        tgt = gain[i]
        c = a if tgt > s else r
        s = tgt + (s - tgt) * (c ** 48)
        out[i:i + 48] = s
    return out


def true_peak(x):
    up = resample_poly(x, 4, 1, axis=0)
    return 20 * np.log10(np.abs(up).max() + 1e-12)


def limiter(x, SR, ceil_db=-1.2, look=0.004, rel=0.08):
    """Look-ahead brickwall on a 4x-oversampled sidechain (true-peak aware)."""
    ceil = db(ceil_db)
    up = resample_poly(x, 4, 1, axis=0)
    pk = np.abs(up).max(1).reshape(-1, 4).max(1)[: len(x)]
    need = np.minimum(1.0, ceil / np.maximum(pk, 1e-9))
    L = int(look * SR)
    need = minimum_filter1d(need, size=2 * L + 1)                       # look-ahead window
    gain = np.ones_like(need)
    s = 1.0
    r = np.exp(-1 / (rel * SR))
    for i in range(len(need)):
        s = need[i] if need[i] < s else need[i] + (s - need[i]) * r
        gain[i] = s
    k = np.ones(L) / L                                                  # smooth attack (box filter over the look-ahead window)
    gain = np.minimum(gain, np.convolve(gain, k, mode="same"))
    return x * gain[:, None]


def master(x, SR, target, ceil=-1.2):
    m = pyln.Meter(SR)
    y = x.copy()
    for _ in range(12):
        L = m.integrated_loudness(y)
        y = y * db(target - L)
        y = limiter(y, SR, ceil)
        L2 = m.integrated_loudness(y)
        if abs(L2 - target) < 0.1 and true_peak(y) <= ceil + 0.15:
            break
    return y, m.integrated_loudness(y), true_peak(y)


def master_path(spec, name):
    return os.path.join(spec.audio_dir, f"mix-{name}.wav")


def run(spec, force=False):
    cfg = spec.raw.get("mix", {})
    SR = int(cfg.get("sr", 48000))
    dur = spec.duration
    N = int(dur * SR)
    ev = json.load(open(events_path(spec)))
    man = load_manifest(spec)

    def place(buf, x, t, gain_db=0.0, pan=0.0):
        i = int(round(t * SR))
        x = x * db(gain_db)
        if pan:
            x = x * np.array([1 - max(pan, 0), 1 + min(pan, 0)])
        j = min(N, i + len(x))
        buf[i:j] += x[: j - i]

    music = load(music_path(spec), SR)
    if len(music) != N:                      # equal for a well-formed spec; pad/trim so a rounded duration still mixes
        music = np.vstack([music, np.zeros((max(0, N - len(music)), 2))])[:N]
    sfx = np.zeros((N, 2))
    vo = np.zeros((N, 2))
    lib = spec.raw.get("sfx", {}).get("library", {})
    S = {name: load(asset_path(spec, e["asset"], man), SR) for name, e in lib.items() if e.get("asset")}
    typing = {name: e for name, e in lib.items() if e.get("variants")}
    rngs = {name: np.random.default_rng(e.get("seed", 0)) for name, e in typing.items()}
    log = []
    for e in ev["sfx"]:
        name, t, g = e["sfx"], e["t"], e.get("db", 0.0)
        if name in typing:
            ty, rng = typing[name], rngs[name]
            lo, hi = ty.get("gain_jitter", [-2.5, 1.0])
            pj = ty.get("pan_jitter", 0.15)
            variants = ty["variants"]
            for kt in e["times"]:
                place(sfx, S[variants[rng.integers(0, len(variants))]], kt, g + rng.uniform(lo, hi), pan=rng.uniform(-pj, pj))
            log.append((t, name, len(e["times"]), g))
            continue
        place(sfx, S[name], t, g, e.get("pan", 0.0))
        log.append((t, name, 1, g))
    # VO: level each line to vo_line_lufs, place at its event time
    vo_marks = []
    meta = json.load(open(os.path.join(spec.vo_dir, "vo.json"))) if os.path.exists(os.path.join(spec.vo_dir, "vo.json")) else dict(lines=[])
    for line in meta["lines"]:
        t = ev["vo"].get(line["shot"])
        if t is None:
            continue
        x = load(os.path.join(spec.vo_dir, line["file"]), SR)
        meter = pyln.Meter(SR)
        L = meter.integrated_loudness(x) if len(x) > SR * 0.5 else -20
        x = x * db(cfg.get("vo_line_lufs", -16.0) - L)
        place(vo, x, t)
        vo_marks.append((t, t + len(x) / SR, line["shot"], line["text"]))
    # music ducking under VO (and under SFX with duck_music)
    dk = cfg.get("duck", {})
    duck_db, att, rel = dk.get("db", 7.0), dk.get("attack", 0.12), dk.get("release", 0.35)
    pre, post = dk.get("pre", 0.12), dk.get("post", 0.1)
    g = np.zeros(N)
    for t0, t1, *_ in vo_marks:
        g[int(max(0, t0 - pre) * SR): int(min(dur, t1 + post) * SR)] = duck_db
    for e in ev["sfx"]:
        d = (lib.get(e["sfx"]) or {}).get("duck_music")
        if d:
            a, b = int(e["t"] * SR), int((e["t"] + d["dur"]) * SR)
            g[a:b] = np.maximum(g[a:b], d["db"])
    duck = smooth(g, att, rel, SR)
    music_d = music * db(-duck)[:, None]
    BUS = {"music": -5.0, "sfx": -8.0, "vo": 1.5}
    BUS.update(cfg.get("bus_db", {}))
    mix = music_d * db(BUS["music"]) + sfx * db(BUS["sfx"]) + vo * db(BUS["vo"])
    sd = os.path.join(spec.audio_dir, "stems")
    os.makedirs(sd, exist_ok=True)
    for nm, x in [("music", music_d), ("sfx", sfx * db(BUS["sfx"])), ("vo", vo * db(BUS["vo"]))]:
        sf.write(os.path.join(sd, f"{nm}.wav"), x.astype(np.float32), SR, subtype="FLOAT")
    out = {}
    fade = cfg.get("fade_out", 0.03)
    for m in spec.masters:
        y, L, tp = master(mix, SR, m["lufs"], m["ceiling"])
        f0 = int(round(dur - fade, 6) * SR)
        y[f0:] *= np.linspace(1, 0, N - f0)[:, None]
        sf.write(master_path(spec, m["name"]), y.astype(np.float32), SR, subtype="FLOAT")
        out[m["name"]] = dict(lufs=round(float(L), 2), dbtp=round(float(tp), 2))
        print("master", m["name"], out[m["name"]], flush=True)
    with open(os.path.join(spec.audio_dir, "mix-report.json"), "w") as f:
        json.dump(dict(master=out, sfx=log, vo=vo_marks, bus_db=BUS, duck_db=duck_db), f, indent=1)
    return out
