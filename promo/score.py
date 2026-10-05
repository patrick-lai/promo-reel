"""Self-synthesised scores (no samples, no third-party audio): CC0, safe to ship with any promo.

    python -m promo.score dawn-shift  out.wav       # 100 BPM, 100 beats = 60 s  (cinematic-story: night -> dawn)
    python -m promo.score horizon-rise out.wav      # 96 BPM, 24 beats = 15 s    (horizon: held drone, plucked burst, big chord)

Everything is additive/FM synthesis + a noise-tail reverb, rendered at 48 kHz stereo, deterministic (seeded).
"""
from __future__ import annotations

import sys

import numpy as np
import soundfile as sf

SR = 48000


def mid(n):                           # midi -> Hz
    return 440.0 * 2 ** ((n - 69) / 12)


def env(n, a, d, s, r, total=None):
    """ADSR on n samples; s = sustain level; times in seconds."""
    t = np.arange(n) / SR
    e = np.minimum(t / max(a, 1e-4), 1.0)
    dd = np.clip((t - a) / max(d, 1e-4), 0, 1)
    e = e * (1 - dd * (1 - s))
    rel = np.clip((total or n / SR) - t, 0, r) / max(r, 1e-4) if r else 1.0
    return e * np.minimum(rel, 1.0)


def pluck(f, dur, bright=0.5, rng=None):
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = np.zeros(n)
    for k, a in enumerate([1.0, 0.5, 0.28, 0.16, 0.09, 0.05], 1):
        y += a * np.sin(2 * np.pi * f * k * t) * np.exp(-t * (3.0 + 2.5 * k * bright))
    y *= np.exp(-t * 1.2)
    y[: int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))
    return y


def pad(freqs, dur, gain=0.2, detune=0.004, a=1.2, r=1.5, seed=0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = np.zeros(n)
    for i, f in enumerate(freqs):
        for d in (-detune, 0, detune):
            ph = (hash((seed, i, d)) % 1000) / 1000 * 6.28
            ff = f * (1 + d)
            y += np.sin(2 * np.pi * ff * t + ph) + 0.35 * np.sin(2 * np.pi * 2 * ff * t + ph) + 0.12 * np.sin(2 * np.pi * 3 * ff * t)
    y /= max(len(freqs) * 3, 1)
    # slow tremolo/filter-like movement
    y *= 0.85 + 0.15 * np.sin(2 * np.pi * 0.17 * t + seed)
    return gain * y * env(n, a, 0.5, 1.0, r, dur)


def sub(f, dur, gain=0.3):
    n = int(dur * SR)
    t = np.arange(n) / SR
    return gain * np.sin(2 * np.pi * f * t) * env(n, 0.05, 0.3, 0.8, 0.4, dur)


def thump(gain=0.35):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 52 + 70 * np.exp(-t * 28)
    return gain * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)


def riser(dur, gain=0.18, seed=1):
    n = int(dur * SR)
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    # crude band sweep: one-pole low-pass whose cutoff rises
    out = np.zeros(n)
    y = 0.0
    t = np.linspace(0, 1, n)
    k = 0.01 + 0.16 * t ** 2
    # vectorised approximation: blocks
    blk = 512
    for b in range(0, n, blk):
        a = k[min(b, n - 1)]
        seg = x[b:b + blk]
        for j in range(len(seg)):
            y = y + a * (seg[j] - y)
            out[b + j] = y
    out /= np.abs(out).max() + 1e-9
    return gain * out * (t ** 1.5)


def reverb(x, tail=2.4, wet=0.28, seed=3):
    rng = np.random.default_rng(seed)
    n = int(tail * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal((2, n)) * np.exp(-t * 2.6)
    ir[:, : int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))
    # lowpass the IR so the tail is dark
    k = np.ones(24) / 24
    ir = np.stack([np.convolve(ir[0], k, "same"), np.convolve(ir[1], k, "same")])
    from scipy.signal import fftconvolve
    wetL = fftconvolve(x, ir[0])[: len(x)]
    wetR = fftconvolve(x, ir[1])[: len(x)]
    w = np.stack([wetL, wetR], axis=1)
    w /= np.abs(w).max() + 1e-9
    d = np.stack([x, x], axis=1)
    return d * (1 - wet) + w * wet * np.abs(x).max() * 1.6


class Track:
    def __init__(self, dur):
        self.n = int(dur * SR)
        self.y = np.zeros(self.n)

    def add(self, t, sig, gain=1.0):
        i = int(t * SR)
        if i >= self.n:
            return
        seg = sig[: self.n - i]
        self.y[i:i + len(seg)] += gain * seg


def fade_ends(y, a=0.05, r=0.6):
    n = len(y)
    y[: int(a * SR)] *= np.linspace(0, 1, int(a * SR))[:, None]
    y[n - int(r * SR):] *= np.linspace(1, 0, int(r * SR))[:, None]
    return y


def dawn_shift():
    bpm, beats = 100, 100
    bt = 60 / bpm
    dur = beats * bt + 3.0
    T = Track(dur)
    # progression, 4 beats per chord: Am9 - Fmaj7 - C - G (lifts), later D-major-ish lift for dawn
    prog = [[57, 60, 64, 71], [53, 57, 60, 64], [48, 55, 60, 64], [55, 59, 62, 66]]
    dawn = [[50, 57, 62, 66], [55, 59, 62, 69], [52, 59, 64, 68], [57, 61, 64, 71]]
    for bar in range(0, beats, 4):
        ch = prog[(bar // 4) % 4] if bar < 76 else dawn[(bar // 4) % 4]
        lvl = 0.5 if bar < 16 else 0.9 if bar < 72 else 1.2
        T.add(bar * bt, pad([mid(n) for n in ch], 4 * bt + 1.5, gain=0.22 * lvl, seed=bar))
        T.add(bar * bt, sub(mid(ch[0] - 12), 4 * bt, gain=0.22 * lvl))
        if bar >= 16:                                  # felt-piano arpeggio, eighth notes
            order = [0, 1, 2, 3, 2, 1, 2, 1] if bar < 76 else [3, 2, 1, 2, 3, 2, 1, 0]
            for i, k in enumerate(order):
                T.add(bar * bt + i * bt / 2, pluck(mid(ch[k] + 12), 1.6, bright=0.4), gain=0.16 * (1.3 if bar >= 76 else 1.0))
        if bar >= 40:                                  # heartbeat thump on every beat
            for b in range(4):
                T.add((bar + b) * bt, thump(), gain=0.5 if bar < 72 else 0.65)
    T.add(64 * bt, riser(12 * bt, gain=0.16))
    # dawn bell on the lift at beat 76
    for i, n_ in enumerate([86, 90, 93, 98]):
        T.add(76 * bt + i * bt * 0.5, pluck(mid(n_), 3.0, bright=0.25), gain=0.14)
    y = reverb(T.y, tail=2.6, wet=0.30)
    y = fade_ends(y, 0.05, 1.8)
    return y / np.abs(y).max() * 0.85


def horizon_rise(beats=32, burst=(4, 26)):
    bpm = 96
    bt = 60 / bpm
    dur = beats * bt + 3.0
    b0, b1 = burst
    T = Track(dur)
    # 0..b0: held drone + shimmer (dawn horizon)
    T.add(0, pad([mid(38), mid(45), mid(50)], b0 * bt + 0.8, gain=0.35, a=1.8), 1.0)
    T.add(0, pad([mid(74), mid(81)], b0 * bt + 0.8, gain=0.06, a=2.0, seed=5), 1.0)
    # burst: plucked arpeggio on the half-beat grid, pitch climbing in steps, noise riser underneath
    scale = [62, 66, 69, 74, 69, 66, 74, 78, 81, 78, 74, 81, 86, 81, 78, 86]
    i = 0
    h = b0 * 2
    while h < b1 * 2:
        t = (h / 2) * bt
        step = int(((h / 2) - b0) / max(b1 - b0, 1) * 5)           # climbs a tone-ish every fifth of the burst
        T.add(t, pluck(mid(scale[i % len(scale)] + step), 0.7, bright=0.6), gain=0.28)
        T.add(t, np.sin(2 * np.pi * 2200 * np.arange(int(0.012 * SR)) / SR) * np.exp(-np.arange(int(0.012 * SR)) / SR * 400), gain=0.05)
        i += 1
        h += 1
    T.add(b0 * bt, pad([mid(38), mid(45), mid(50)], (b1 - b0) * bt, gain=0.30, a=0.3), 1.0)
    T.add(b0 * bt, riser((b1 - b0) * bt, gain=0.20, seed=2))
    # b1: the lift, big warm chord held to the end, bells
    big = [38, 45, 50, 54, 57, 62, 66]
    T.add(b1 * bt, pad([mid(n) for n in big], (beats - b1) * bt + 2, gain=0.5, a=0.15, r=2.5, seed=9), 1.0)
    T.add(b1 * bt, thump(), gain=0.9)
    for k, n_ in enumerate([86, 90, 93, 98]):
        T.add(b1 * bt + 0.9 + k * 0.5, pluck(mid(n_), 3.0, bright=0.2), gain=0.15)
    y = reverb(T.y, tail=3.0, wet=0.34)
    y = fade_ends(y, 0.03, 2.2)
    return y / np.abs(y).max() * 0.85


SCORES = {"dawn-shift": dawn_shift, "horizon-rise": horizon_rise}


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if len(a) != 2 or a[0] not in SCORES:
        raise SystemExit(f"usage: python -m promo.score {{{'|'.join(SCORES)}}} out.wav")
    sf.write(a[1], SCORES[a[0]]().astype(np.float32), SR)
    print(a[1])


if __name__ == "__main__":
    main()
