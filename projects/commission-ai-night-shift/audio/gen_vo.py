"""Night-shift VO: two Kokoro voices, one WAV per line (48 kHz mono, trimmed, -16 LUFS), plus vo/lines.json.
Run from the repo root:  .venv/bin/python projects/commission-ai-night-shift/audio/gen_vo.py
Models come from `promo -p projects/commission-ai-night-shift/promo.yaml fetch` (sha256-verified). Deterministic."""
import json, os, sys
import numpy as np, soundfile as sf, pyloudnorm as pyln
from scipy.signal import resample_poly
from kokoro_onnx import Kokoro
from promo.mix import master, true_peak

ROOT = "projects/commission-ai-night-shift"
OUT = f"{ROOT}/audio/vo"
VOICES = {  # role: (kokoro voice, lang, speed)
    "AGENT": ("af_heart", "en-us", 0.95),   # warm, calm (Kokoro grade A, median F0 ~209 Hz)
    "DEV":   ("am_michael", "en-us", 0.90), # lower, tired human (median F0 ~117 Hz)
}
LINES = [
    ("DEV-1", "DEV", "Ship the checkout revamp tonight. No broken builds."),
    ("AGENT-1", "AGENT", "Got it. Eight tickets, three waves. I'll check in when something needs your approval."),
    ("AGENT-2", "AGENT", "Good morning. One command needs your approval."),
    ("DEV-2", "DEV", "Allow once."),
    ("AGENT-3", "AGENT", "Pull request four thirty-two is open. The reviewer approved it."),
    ("AGENT-4", "AGENT", "And it's merged."),
    ("DEV-3", "DEV", "Amazing."),
]
SR, LUFS = 48000, -16.0


def trim(x, sr, db=-42.0, lead=0.04, tail=0.12, fade=0.03):
    a = np.abs(x)
    idx = np.where(a > a.max() * 10 ** (db / 20))[0]
    x = x[max(0, idx[0] - int(lead * sr)): idx[-1] + int(tail * sr)].copy()
    nf = int(fade * sr)
    x[-nf:] *= np.linspace(1, 0, nf, dtype=x.dtype)
    x[:int(0.005 * sr)] *= np.linspace(0, 1, int(0.005 * sr), dtype=x.dtype)
    return x


def main():
    M = f"{ROOT}/media/models/"
    k = Kokoro(M + "kokoro-v1.0.onnx", M + "voices-v1.0.bin")
    meta = []
    for lid, role, text in LINES:
        voice, lang, speed = VOICES[role]
        s, sr = k.create(text, voice=voice, speed=speed, lang=lang)
        s = np.asarray(s, dtype=np.float64)
        s = resample_poly(s, SR // sr, 1) if SR % sr == 0 else resample_poly(s, SR, sr)
        s = trim(s, SR)
        # loudness to -16 LUFS with the repo's true-peak-aware limiter (ceiling -1.2 dBTP): raw Kokoro speech is peaky
        s, L, tp = master(s[:, None], SR, LUFS, ceil=-1.2)
        s = s[:, 0]
        peak = np.abs(s).max()
        fn = f"{lid}.wav"
        sf.write(os.path.join(OUT, fn), s.astype(np.float32), SR, subtype="PCM_16")
        meta.append(dict(id=lid, role=role, path=f"audio/vo/{fn}", text=text, dur=round(len(s) / SR, 3), sr=SR,
                         voice=voice, speed=speed, lang=lang, lufs=round(float(L), 2),
                         peak_dbfs=round(float(20 * np.log10(peak)), 2), true_peak_dbtp=round(float(tp), 2)))
        print(meta[-1], flush=True)
    json.dump(dict(engine="kokoro-onnx", model="kokoro-v1.0", lufs=LUFS, sr=SR, lines=meta),
              open(os.path.join(OUT, "lines.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
