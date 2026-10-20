"""Scores for VO takes (`takes: N` in promo/vo.py) and the energy test behind the `vo-tail` gate.

A take is rejected when whisper hears different words (WER over the line's `max_wer` / `qa.vo_max_wer`) or when it ends
mid-sound. The survivors are not ranked: a pitch-variation number is shown to help the person listen, but picking by score
drifts to the flattest read, so the person picks by ear (`promo vo takes <id> --pick k`).
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import soundfile as sf

TAIL_CUT_DB = -35.0      # the 20 ms before the closing fade is this loud against the line's loudest window: the take was cut mid-sound


def tail_db(x, sr):
    """Loudness (dB against the loudest 10 ms) of the 20 ms just before the last 30 ms, where `vo.trim` fades out. A take that ends
    in its own silence sits far below TAIL_CUT_DB there; one cut mid-word does not, fade or no fade."""
    from .vo import rms_db
    q = rms_db(x, sr)
    if len(q) < 6:
        return float(q.max()) if len(q) else -120.0
    return float(q[-5:-3].max())


def pitch_st(x, sr):
    """Spread of the voiced pitch in semitones (std): a rough sign of a lively or a flat read."""
    import librosa
    f0, voiced, _ = librosa.pyin(np.asarray(x, dtype=np.float32), fmin=65, fmax=500, sr=sr)
    f0 = f0[voiced & np.isfinite(f0)]
    return round(float(np.std(12 * np.log2(f0 / np.median(f0)))), 2) if len(f0) > 5 else None


def score(spec, line, wav, key_base):
    """{wer, heard, tail_db, pitch_st, rejected} of one trimmed take; the slow parts (whisper, pitch) are kept in
    `<key_base>.score.json` and redone only when the take, the script text or the ASR model change."""
    from .check import heard_wer, line_max_wer, transcribe
    qa = spec.qa
    model = qa.get("asr_model", "small.en")
    data = open(wav, "rb").read()
    dig = hashlib.sha256(data + json.dumps([model, line["text"]]).encode()).hexdigest()
    sp = key_base + ".score.json"
    st = json.load(open(sp)) if os.path.exists(sp) else {}
    if st.get("digest") != dig:
        x, sr = sf.read(wav, dtype="float32")
        st = dict(digest=dig, heard=transcribe(wav, model), tail_db=round(tail_db(x, sr), 1), pitch_st=pitch_st(x, sr))
        with open(sp, "w") as f:
            json.dump(st, f)
    w = None if st["heard"] is None else round(heard_wer(line, st["heard"], qa), 3)
    why = []
    if w is not None and w > line_max_wer(line, qa.get("vo_max_wer", 0.0)):
        why.append(f"WER {w:.2f}")
    if st["tail_db"] > TAIL_CUT_DB:
        why.append(f"ends mid-sound ({st['tail_db']:.0f} dB)")
    return dict(wer=w, heard=st["heard"], tail_db=st["tail_db"], pitch_st=st["pitch_st"], rejected="; ".join(why) or None)


def table(takes, pick):
    """The takes of one line as text: which is used, WER, tail, pitch spread, why a take was rejected."""
    rows = [f"  {'':2}{'take':<5}{'WER':>6}{'tail dB':>9}{'pitch st':>10}  file"]
    for t in takes:
        wer = "-" if t["wer"] is None else f"{t['wer']:.2f}"
        pst = "-" if t["pitch_st"] is None else f"{t['pitch_st']:.2f}"
        rows.append(f"  {'>' if t['take'] == pick else ' ':2}{t['take']:<5}{wer:>6}{t['tail_db']:>9.1f}{pst:>10}  {t['file']}"
                    + (f"  REJECTED: {t['rejected']}" if t["rejected"] else ""))
    if all(t["wer"] is None for t in takes):
        rows.append("  (no WER: faster-whisper is not installed; pip install 'promo-reel[asr]')")
    return "\n".join(rows)
