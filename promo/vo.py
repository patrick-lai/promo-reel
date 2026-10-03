"""Kokoro TTS per VO line (port of make_vo.py). `promo vo`.

Spec: vo: {engine: kokoro, model_asset, voices_asset, voice, lang, speed, lines: [{shot, text, tts?, at, asr_aliases?}]}
Output: build/vo/vo-<shot>-<voice>.wav + build/vo/vo.json  (lines: shot, text, tts, file, dur, sr)
Each line is rendered separately; leading/trailing near-silence is trimmed exactly like the legacy script.
"""
from __future__ import annotations

import json
import os

import numpy as np
import soundfile as sf

from .assets import asset_path, load_manifest


def vo_json_path(spec):
    return os.path.join(spec.vo_dir, "vo.json")


def run(spec, force=False):
    cfg = spec.raw.get("vo")
    if not cfg:
        return None
    os.makedirs(spec.vo_dir, exist_ok=True)
    voice, lang, speed = cfg.get("voice", "bf_emma"), cfg.get("lang", "en-gb"), float(cfg.get("speed", 1.0))
    try:
        from kokoro_onnx import Kokoro
    except ImportError as e:
        raise RuntimeError("`promo vo` needs the vo extra: pip install 'promo-reel[vo]' (kokoro-onnx)") from e
    man = load_manifest(spec)
    k = Kokoro(asset_path(spec, cfg["model_asset"], man), asset_path(spec, cfg["voices_asset"], man))
    meta = []
    for line in cfg["lines"]:
        sid, txt = str(line["shot"]), line["text"]
        say = line.get("tts", txt)
        s, sr = k.create(say, voice=voice, speed=speed, lang=lang)
        s = np.asarray(s, dtype=np.float32)
        a = np.abs(s)
        idx = np.where(a > 0.01)[0]
        s = s[max(0, idx[0] - 240): idx[-1] + 2400]          # trim leading/trailing near-silence
        fn = f"vo-{sid}-{voice}.wav"
        sf.write(os.path.join(spec.vo_dir, fn), s, sr)
        meta.append(dict(shot=sid, text=txt, tts=say, file=fn, dur=round(len(s) / sr, 3), sr=sr))
        print("vo", sid, round(len(s) / sr, 2), txt, flush=True)
    with open(vo_json_path(spec), "w") as f:
        json.dump(dict(voice=voice, lang=lang, speed=speed, lines=meta), f, indent=1)
    return meta
