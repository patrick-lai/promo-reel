"""Music edit on the beat grid (port of music_edit.py, generic). `promo music`.

Spec:
  music: {asset, bpm, track_beat, track_offset,
          edit: {segments: [[edit_beat, track_beat0, track_beat1], ...], crossfade: 0.030,
                 gains: [{beats: [b0, b1], db: 3.0, ramp: 0.3?}, ...], silence_from_beat: 97.6}}
Track beat k sits at track_offset + k*track_beat seconds in the source file; edit beat k at k*60/timeline.bpm.
Segments are cut with equal-power crossfades; gains multiply a per-sample gain curve in list order (`ramp` adds a
linear fade-in over the `ramp` seconds before b0); everything from silence_from_beat on is zeroed.
"""
from __future__ import annotations

import os

import numpy as np
import soundfile as sf

from .assets import asset_path

SR = 48000


def music_path(spec):
    return os.path.join(spec.audio_dir, "music-edit.wav")


def edit(spec, src_path):
    """Return the edited music as float64 (n, 2) at 48 kHz."""
    import librosa
    m = spec.raw["music"]
    e = m["edit"]
    B = spec.timeline.B
    TB, OFF = m["track_beat"], m["track_offset"]
    y, _ = librosa.load(src_path, sr=SR, mono=False)
    y = y.T  # (n, 2)

    def tr(k):
        return int(round((OFF + k * TB) * SR))

    def T(k):
        return int(round(k * B * SR))

    N = T(spec.timeline.beats)
    out = np.zeros((N, 2))
    segs = e["segments"]
    XF = int(e.get("crossfade", 0.030) * SR)
    for i, (t0, k0, k1) in enumerate(segs):
        a = tr(k0) - XF
        b = min(tr(k1) + XF, len(y))
        seg = y[max(a, 0):b].copy()
        if a < 0:
            seg = np.vstack([np.zeros((-a, 2)), seg])
        n = len(seg)
        w = np.ones(n)
        if i > 0:
            w[:2 * XF] = np.sin(np.linspace(0, np.pi / 2, 2 * XF))      # equal-power in
        if i < len(segs) - 1:
            w[-2 * XF:] = np.cos(np.linspace(0, np.pi / 2, 2 * XF))     # equal-power out
        s0 = T(t0) - XF
        end = min(s0 + n, N)
        st = max(0, -s0)
        out[max(s0, 0):end] += (seg * w[:, None])[st:end - s0]
    g = np.ones(N)
    for gn in e.get("gains", []):
        b0, b1 = gn["beats"]
        a, b = T(b0), T(b1)
        v = 10 ** (gn["db"] / 20)
        g[a:b] *= v
        if gn.get("ramp"):
            r = int(gn["ramp"] * SR)
            lo = max(a - r, 0)
            g[lo:a] *= np.linspace(1, v, r)[r - (a - lo):]            # fade INTO the region (clamped at the start of the track)
        if gn.get("ramp_out"):
            r = int(gn["ramp_out"] * SR)
            hi = min(b + r, N)
            g[b:hi] *= np.linspace(v, 1, r)[:hi - b]                  # fade back OUT of the region: a quiet open that rises into the bed
    out *= g[:, None]
    if e.get("silence_from_beat") is not None:
        out[T(e["silence_from_beat"]):] = 0
    return out


def run(spec, force=False):
    src = asset_path(spec, spec.raw["music"]["asset"])
    if not os.path.exists(src):
        raise FileNotFoundError(f"music file missing: {src} (run `promo fetch`)")
    out = edit(spec, src)
    os.makedirs(spec.audio_dir, exist_ok=True)
    sf.write(music_path(spec), out.astype(np.float32), SR, subtype="FLOAT")
    print("music edit", round(len(out) / SR, 3), "s", flush=True)
    return music_path(spec)
