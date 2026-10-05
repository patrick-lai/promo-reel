"""Synthesise UI SFX from scratch with numpy (no samples, no licence issues). 48 kHz stereo WAV. `promo sfx`.

Port of the legacy make_sfx.py. The single seeded rng (default_rng(7)) is consumed in a fixed order
(tick, tick2, whoosh_long, whoosh_short, key0..key5): do not reorder or the output changes.
Source: https://github.com/patrick-lai/promo-reel/blob/main/promo/sfx.py  (licence CC0-1.0, self-synthesised, no samples)
"""
from __future__ import annotations

import os

import numpy as np
import soundfile as sf

SR = 48000
NAMES = ["tick", "tick2", "chime", "whoosh_long", "whoosh_short", "swell"] + [f"key{i}" for i in range(6)] + ["riser", "impact", "rain_bed", "room_tone", "thud_soft", "click"]


def env_exp(n, tau):
    return np.exp(-np.arange(n) / (tau * SR))


def norm(x, peak=0.7):
    return x / (np.abs(x).max() + 1e-9) * peak


def lp(x, fc):  # one-pole low-pass
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.zeros_like(x)
    s = 0.0
    for i, v in enumerate(x):
        s = (1 - a) * v + a * s
        y[i] = s
    return y


def bp_sweep(x, f0, f1, q=2.0):  # state-variable band-pass with swept centre
    n = len(x)
    f = np.geomspace(f0, f1, n)
    lo = bp = 0.0
    y = np.zeros(n)
    for i in range(n):
        g = 2 * np.sin(np.pi * f[i] / SR)
        hp = x[i] - lo - bp / q
        bp += g * hp
        lo += g * bp
        y[i] = bp
    return y


def st(x, w=0.0):
    return np.stack([x * (1 - w), x * (1 + w)], 1)


def bell(f, dur=1.6):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for r, a, tau in [(1, 1, 0.9), (2.0, 0.35, 0.5), (2.76, 0.2, 0.3), (5.4, 0.08, 0.12)]:
        x += a * np.sin(2 * np.pi * f * r * t) * np.exp(-t / tau)
    att = np.minimum(1, t / 0.004)
    return x * att


def whoosh(rng, dur, f0, f1, peak_at=0.6):
    n = int(dur * SR)
    t = np.linspace(0, 1, n)
    e = np.where(t < peak_at, (t / peak_at) ** 2, ((1 - t) / (1 - peak_at)) ** 1.5)
    x = bp_sweep(rng.standard_normal(n), f0, f1, 1.4) * e
    xl = x
    xr = np.roll(x, 90)  # small stereo spread
    return np.stack([norm(xl, 0.6), norm(xr, 0.6)], 1)


def synthesise():
    """Return {name: float array (n, 2)} for every SFX."""
    rng = np.random.default_rng(7)
    out = {}
    # tick: tiny woody click (soft) for status-chip changes
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    tick = (np.sin(2 * np.pi * 2350 * t) * 0.6 + np.sin(2 * np.pi * 3900 * t) * 0.25) * env_exp(n, 0.012)
    tick += lp(rng.standard_normal(n), 5000) * env_exp(n, 0.003) * 0.5
    out["tick"] = st(norm(tick, 0.5))
    # tick2: slightly lower variant so a run of ticks isn't machine-gun identical
    tick2 = (np.sin(2 * np.pi * 1950 * t) * 0.6 + np.sin(2 * np.pi * 3300 * t) * 0.25) * env_exp(n, 0.014) + lp(rng.standard_normal(n), 4500) * env_exp(n, 0.003) * 0.5
    out["tick2"] = st(norm(tick2, 0.5))
    # chime: two soft bell notes (E6 then B6), inharmonic partials, long decay
    c = np.zeros(int(1.9 * SR))
    b1 = bell(1318.5)
    b2 = bell(1975.5, 1.6)
    c[:len(b1)] += b1
    o = int(0.14 * SR)
    c[o:o + len(b2)] += b2 * 0.8
    out["chime"] = np.stack([norm(c, 0.6) * 0.95, norm(c, 0.6)], 1)
    # whoosh: band-passed noise sweeping up then down
    out["whoosh_long"] = whoosh(rng, 1.1, 250, 3500, 0.7)
    out["whoosh_short"] = whoosh(rng, 0.45, 600, 4500, 0.55)
    # swell: soft pad swell: detuned saw-ish chord low-passed, slow attack, short release
    n = int(1.6 * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for f in [523.25, 659.25, 783.99, 1046.5]:
        for d in (-0.15, 0.15):
            x += np.sin(2 * np.pi * (f * (1 + d / 100)) * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)
    e = np.clip(t / 1.1, 0, 1) ** 2 * np.clip((1.6 - t) / 0.5, 0, 1)
    out["swell"] = st(norm(lp(x * e, 2500), 0.5))
    # key: one soft keyboard tap (typing patter); randomised per hit at mix time
    for i in range(6):
        n = int(0.05 * SR)
        t = np.arange(n) / SR
        f = rng.uniform(1500, 2600)
        k = lp(rng.standard_normal(n), rng.uniform(3000, 6000)) * env_exp(n, 0.006) + 0.3 * np.sin(2 * np.pi * f * t) * env_exp(n, 0.008)
        k += 0.25 * np.sin(2 * np.pi * rng.uniform(180, 260) * t) * env_exp(n, 0.01)  # body thump
        out[f"key{i}"] = st(norm(k, 0.4))
    out.update(_scene_sounds())
    return out


def _scene_sounds():
    """Sound-design layer for film-style promos (a separate rng so the UI sounds above never change)."""
    rng = np.random.default_rng(11)
    out = {}
    # riser: band-passed noise sweeping up + a rising sine, amplitude ramping to a hard stop (lands on an impact)
    n = int(4.0 * SR)
    t = np.linspace(0, 1, n)
    nz = bp_sweep(rng.standard_normal(n), 300, 7000, 1.2) * (t ** 2.2)
    f = 180 * (6 ** t)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * (t ** 3) * 0.35
    x = norm(nz, 0.7) + tone
    out["riser"] = np.stack([norm(x, 0.7), norm(np.roll(x, 120), 0.7)], 1)
    # impact: sub boom that falls 95 -> 38 Hz, a noise burst and a dark tail
    n = int(3.2 * SR)
    t = np.arange(n) / SR
    fb = 38 + 57 * np.exp(-t * 9)
    boom = np.sin(2 * np.pi * np.cumsum(fb) / SR) * np.exp(-t / 0.9)
    burst = lp(rng.standard_normal(n), 3500) * np.exp(-t / 0.05) * 0.8
    tail = lp(rng.standard_normal(n), 700) * np.exp(-t / 0.9) * 0.25
    x = norm(boom + burst + tail, 0.8)
    out["impact"] = np.stack([x, np.roll(x, 60)], 1)
    # rain_bed: 12 s of soft high-passed noise with slow swell and a few drips (loop-safe ends)
    n = int(12.0 * SR)
    t = np.arange(n) / SR
    base = rng.standard_normal(n)
    rain = base - lp(base, 1800)
    rain = lp(rain, 9000) * (0.75 + 0.25 * np.sin(2 * np.pi * 0.11 * t))
    for _ in range(26):
        i = int(rng.uniform(0.2, 11.6) * SR)
        m = int(0.03 * SR)
        d = np.sin(2 * np.pi * rng.uniform(1800, 3200) * np.arange(m) / SR) * np.exp(-np.arange(m) / (0.006 * SR)) * 0.5
        rain[i:i + m] += d
    fade = np.minimum(1, np.minimum(t, 12 - t) / 0.4)
    x = norm(rain * fade, 0.35)
    out["rain_bed"] = np.stack([x, np.roll(x, 400)], 1)
    # room_tone: warm low hum + air, 8 s
    n = int(8.0 * SR)
    t = np.arange(n) / SR
    hum = 0.5 * np.sin(2 * np.pi * 60 * t) + 0.3 * np.sin(2 * np.pi * 120 * t) + 0.12 * np.sin(2 * np.pi * 180 * t)
    air = lp(rng.standard_normal(n), 600) * 0.6
    fade = np.minimum(1, np.minimum(t, 8 - t) / 0.5)
    x = norm((hum + air) * fade, 0.25)
    out["room_tone"] = np.stack([x, np.roll(x, 250)], 1)
    # thud_soft: laptop lid closing: soft low thump + a little plastic click
    n = int(0.4 * SR)
    t = np.arange(n) / SR
    th = np.sin(2 * np.pi * 85 * t) * np.exp(-t / 0.07) + lp(rng.standard_normal(n), 900) * np.exp(-t / 0.03) * 0.6
    th[: int(0.002 * SR)] *= 0.2
    th += np.roll(lp(rng.standard_normal(n), 4500) * np.exp(-t / 0.004) * 0.3, int(0.045 * SR))
    out["thud_soft"] = st(norm(th, 0.55))
    # click: a mouse / trackpad click
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    c = np.sin(2 * np.pi * 2100 * t) * np.exp(-t / 0.004) * 0.7 + lp(rng.standard_normal(n), 6000) * np.exp(-t / 0.002) * 0.5
    c += np.sin(2 * np.pi * 240 * t) * np.exp(-t / 0.01) * 0.3
    out["click"] = st(norm(c, 0.45))
    return out


def run(spec, force=False):
    """Write build/sfx/<name>.wav for every SFX (skips when all exist and not forced)."""
    os.makedirs(spec.sfx_dir, exist_ok=True)
    paths = {n: os.path.join(spec.sfx_dir, f"{n}.wav") for n in NAMES}
    if not force and all(os.path.exists(p) for p in paths.values()):
        return paths, False
    for name, x in synthesise().items():
        sf.write(paths[name], x.astype(np.float32), SR, subtype="FLOAT")
        print("sfx", name, round(len(x) / SR, 3), flush=True)
    return paths, True
