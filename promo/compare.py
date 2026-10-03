"""`promo compare <ref.mp4>`: per-shot PSNR (ffmpeg psnr filter) + audio diff vs a reference render."""
from __future__ import annotations

import re
import subprocess

import numpy as np


def shot_psnr(ref, new, f0, n):
    """Average PSNR over frames [f0, f0+n) of two videos (inf = identical)."""
    fc = (f"[0:v]trim=start_frame={f0}:end_frame={f0 + n},setpts=PTS-STARTPTS[a];"
          f"[1:v]trim=start_frame={f0}:end_frame={f0 + n},setpts=PTS-STARTPTS[b];[a][b]psnr")
    r = subprocess.run(["ffmpeg", "-v", "info", "-threads", "2", "-i", ref, "-i", new, "-filter_complex", fc, "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"average:(\S+)", r.stderr)
    if not m:
        return None
    return float("inf") if m.group(1) == "inf" else float(m.group(1))


def decode_audio(path, sr=48000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-threads", "2", "-i", path, "-vn", "-f", "f32le", "-ac", "2", "-ar", str(sr), "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2)


def audio_diff(ref, new):
    """Return dict(max_abs, rms_db) of (new - ref) over the common length; -inf rms means identical decode."""
    a, b = decode_audio(ref), decode_audio(new)
    n = min(len(a), len(b))
    d = a[:n].astype(np.float64) - b[:n].astype(np.float64)
    rms = float(np.sqrt(np.mean(d ** 2)))
    ref_rms = float(np.sqrt(np.mean(a[:n].astype(np.float64) ** 2))) or 1e-12
    return dict(samples=n, len_ref=len(a), len_new=len(b), max_abs=float(np.abs(d).max()) if n else 0.0,
                rms_db=20 * np.log10(rms / ref_rms) if rms > 0 else float("-inf"))


def run(spec, ref, new=None, min_psnr=40.0):
    """Compare per shot + audio. Returns a JSON-friendly dict; ok = every shot identical (PSNR inf) or >= min_psnr dB."""
    new = new or spec.output_path(spec.masters[0].get("suffix", ""))
    shots = []
    for s in spec.shots:
        p = shot_psnr(ref, new, s.f0, s.n)
        shots.append(dict(id=s.id, frames=[s.f0, s.f0 + s.n], psnr=("inf" if p == float("inf") else p),
                          identical=p == float("inf"), ok=p is not None and p >= min_psnr))
    ad = audio_diff(ref, new)
    ad = dict(ad, rms_db=("-inf" if ad["rms_db"] == float("-inf") else ad["rms_db"]))
    return dict(ok=all(s["ok"] for s in shots), ref=ref, new=new, min_psnr=min_psnr, shots=shots, audio=ad)


def print_human(r):
    print(f"compare {r['new']} vs {r['ref']}")
    for s in r["shots"]:
        print(f"  shot {s['id']:>3}  frames {s['frames'][0]}-{s['frames'][1]}  PSNR {s['psnr']}")
    a = r["audio"]
    print(f"  audio: max|diff| {a['max_abs']:.6f}, diff RMS {a['rms_db']} dB re ref, lengths {a['len_ref']}/{a['len_new']}")
