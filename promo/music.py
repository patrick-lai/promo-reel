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
SILENCE_FADE = 0.03


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
        s0 = T(e["silence_from_beat"])
        nf = min(s0, int(SILENCE_FADE * SR))                        # a 30 ms fade into the silence: a hard drop to zero clicks
        out[s0 - nf:s0] *= (0.5 + 0.5 * np.cos(np.pi * np.arange(nf) / nf))[:, None]
        out[s0:] = 0
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


# ---------------------------------------------------------------- `promo music analyse`: the beat grid a style preset cuts on
def _fit_grid(env, env_t, tb0, span=0.02, steps=801):
    """Constant-tempo grid from the onset envelope: scan beat periods within +-span of the tracker's estimate `tb0` and take
    the one whose comb (sum of env * e^{-2 pi i t / tb}) is strongest; its angle gives the phase. Robust to the tracker's
    half-beat phase flips and dropped beats. Returns (offset_s of the first beat >= 0, beat_s)."""
    best = (-1.0, tb0, 0.0)
    for tb in np.linspace(tb0 * (1 - span), tb0 * (1 + span), steps):
        z = np.sum(env * np.exp(-2j * np.pi * env_t / tb))
        if abs(z) > best[0]:
            best = (abs(z), tb, np.angle(z))
    _, tb, ang = best
    off = ((-ang / (2 * np.pi)) % 1.0) * tb
    return float(off), float(tb)


def _beat_contrast(env, env_t, off, tb):
    """Mean onset strength on the grid's beats over the mean half a beat later. Clearly above 1 = the grid sits on the
    music; near or below 1 = it drifted onto the off-beats (try --bpm)."""
    ks = np.arange(np.ceil((env_t[0] - off) / tb), np.floor((env_t[-1] - off) / tb))
    g = off + ks * tb
    on, half = np.interp(g, env_t, env).mean(), np.interp(g + tb / 2, env_t, env).mean()
    return float(on / max(half, 1e-9))


def _downbeat_phase(env, env_t, off, tb, n, per_bar=4):
    """Which beat of the bar is beat 1: the phase whose beats carry the most low-band onset energy (kick / bass)."""
    score = [0.0] * per_bar
    for k in range(n):
        i = int(np.searchsorted(env_t, off + k * tb))
        if i < len(env):
            score[k % per_bar] += float(env[max(0, i - 1):i + 2].max())
    return int(np.argmax(score)), [round(s, 2) for s in score]


def _sections(rms_db, bar_t, per_phrase=4, jump_db=2.5):
    """Section markers on phrase starts where the loudness steps by >= jump_db: verse-like dips, lifts into a chorus.
    The loudest phrase that follows a lift is named `chorus`; the rest are `lift-<bar>` / `drop-<bar>`."""
    ph = [(i, float(np.mean(rms_db[i:i + per_phrase]))) for i in range(0, len(rms_db), per_phrase)]
    marks, lifts = {}, []
    for (i0, a), (i1, b) in zip(ph, ph[1:]):
        if b - a >= jump_db:
            lifts.append((b, i1))
            marks[f"lift-{i1 + 1}"] = round(bar_t[i1], 3)
        elif a - b >= jump_db:
            marks[f"drop-{i1 + 1}"] = round(bar_t[i1], 3)
    if lifts:
        _, i = max(lifts)
        marks["chorus"] = round(bar_t[i], 3)
    return marks


def analyse(path, t_from=None, t_to=None, bpm_hint=None, per_bar=4, phrase_bars=4, marks=None):
    """Analyse a music file into a beat grid. Without --from/--to the grid covers the whole track; with them the excerpt is
    snapped to downbeats and the grid is in EDIT time (bar 1 at 0.0 s), with the `music:` block that cuts that excerpt."""
    import librosa
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    dur = len(y) / sr
    kw = {"start_bpm": float(bpm_hint)} if bpm_hint else {}
    _, frames = librosa.beat.beat_track(y=y, sr=sr, **kw)
    bt = librosa.frames_to_time(frames, sr=sr)
    if len(bt) < 8:
        raise SystemExit(f"{path}: only {len(bt)} beats detected; is this music?")
    hop = 256
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    env_t = librosa.times_like(env, sr=sr, hop_length=hop)
    lo_t, hi_t = (float(t_from) - 4, float(t_to if t_to is not None else dur) + 4) if t_from is not None else (0.0, dur)
    win = (env_t >= lo_t) & (env_t <= hi_t)         # fit where the edit is: a tempo drift elsewhere in the song does not matter
    off, tb = _fit_grid(env[win], env_t[win], float(np.median(np.diff(bt))))
    contrast = _beat_contrast(env[win], env_t[win], off, tb)
    low = librosa.onset.onset_strength(y=y, sr=sr, fmax=250, n_mels=32, hop_length=hop)
    n_all = int((dur - off) / tb)
    phase, scores = _downbeat_phase(low, env_t, off, tb, n_all, per_bar)
    first_down = phase                                   # track beat index of the first downbeat
    bars_track = list(range(first_down, n_all, per_bar))
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    rms_t = librosa.times_like(rms, sr=sr, hop_length=hop)

    def bar_db(k):
        a, b = off + k * tb, off + (k + per_bar) * tb
        m = (rms_t >= a) & (rms_t < b)
        return float(20 * np.log10(max(rms[m].mean() if m.any() else 1e-9, 1e-9)))

    if t_from is None:
        k0, k1 = 0, n_all
    else:
        near = lambda t: min(bars_track, key=lambda k: abs(off + k * tb - t))       # noqa: E731
        k0 = near(float(t_from))
        k1 = near(float(t_to)) if t_to is not None else bars_track[-1]
        if k1 <= k0:
            raise SystemExit(f"--to {t_to} is not after --from {t_from} on the bar grid")
    base = off + k0 * tb if t_from is not None else 0.0
    beats, bars = [], []
    for k in range(k0, k1 + 1):
        i = k - k0 if t_from is not None else k
        t = (off + k * tb) - base
        down = (k - first_down) % per_bar == 0
        beats.append(dict(i=i, t=round(t, 4), downbeat=down))
    bar_ks = [k for k in range(k0, k1) if (k - first_down) % per_bar == 0]
    for n, k in enumerate(bar_ks):
        bars.append(dict(bar=n + 1, t=round(off + k * tb - base, 4), phrase_start=n % phrase_bars == 0, db=round(bar_db(k), 1)))
    found = _sections([b["db"] for b in bars], [b["t"] for b in bars], phrase_bars) if bars else {}
    if marks:                                          # named by ear / from the lyrics (music-file seconds): they replace the guesses
        found = {}
        for name, t in marks.items():
            et = float(t) - base
            if bars and -1e-6 <= et <= bars[-1]["t"] + per_bar * tb:
                found[name] = min((b["t"] for b in bars), key=lambda bt: abs(bt - et))
    marks = found
    bpm = 60.0 / tb
    out = dict(source=str(path), tempo_bpm=round(bpm, 4), beat_s=round(tb, 6), time_signature=f"{per_bar}/4",
               beat_contrast=round(contrast, 2), downbeat_scores=scores,
               track=dict(offset_s=round(off, 4), beat_s=round(tb, 6), first_downbeat=first_down, duration_s=round(dur, 3)),
               beats=beats, bars=bars, markers=marks, duration_s=round((k1 - k0) * tb if t_from is not None else dur, 4))
    if t_from is not None:
        out["excerpt"] = dict(track_beat0=k0, track_beat1=k1, from_s=round(off + k0 * tb, 3), to_s=round(off + k1 * tb, 3))
        out["music_block"] = dict(bpm=round(bpm, 4), track_beat=round(tb, 6), track_offset=round(off, 4),
                                  edit=dict(segments=[[0, k0, k1]], crossfade=0.03))
        out["timeline_beats"] = k1 - k0
    return out


def main_analyse(argv):
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="promo music analyse", description="Beat grid of a music file: tempo, beats, downbeats, bars, "
                                 "phrase starts, section markers (lift / drop / chorus). Writes the JSON `timeline.grid` reads.")
    ap.add_argument("file")
    ap.add_argument("--from", dest="t_from", type=float, help="excerpt start (s, snapped to the nearest downbeat)")
    ap.add_argument("--to", dest="t_to", type=float, help="excerpt end (s, snapped to the nearest downbeat)")
    ap.add_argument("--bpm", type=float, help="tempo hint when the detector picks half / double time")
    ap.add_argument("--mark", action="append", default=[], metavar="NAME=SECONDS",
                    help="name a section by ear (music-file seconds, snapped to the nearest bar line), e.g. --mark chorus=79.0; replaces the loudness guesses")
    ap.add_argument("--out", help="write the grid JSON here (default: print a summary only)")
    a = ap.parse_args(argv)
    marks = dict((m.split("=", 1)[0], float(m.split("=", 1)[1])) for m in a.mark)
    g = analyse(a.file, a.t_from, a.t_to, a.bpm, marks=marks)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(g, f, indent=1, ensure_ascii=False)
    print(f"{g['tempo_bpm']:.2f} BPM (beat contrast {g['beat_contrast']}: onsets on the beat / half a beat later), {len(g['bars'])} bars, "
          f"first downbeat = track beat {g['track']['first_downbeat']}, markers {g['markers']}")
    if g.get("excerpt"):
        e = g["excerpt"]
        print(f"excerpt {e['from_s']:.2f}-{e['to_s']:.2f} s = track beats {e['track_beat0']}-{e['track_beat1']} "
              f"({g['timeline_beats']} beats); spec: timeline: {{grid: {a.out or '<grid.json>'}, beats: {g['timeline_beats']}}} "
              f"music: {json.dumps(g['music_block'])}")
    if a.out:
        print(a.out)
    return 0
