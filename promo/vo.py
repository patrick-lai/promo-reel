"""Kokoro TTS per VO line (port of make_vo.py). `promo vo`.

Spec: vo: {engine: kokoro, model_asset, voices_asset, voice, lang, speed, lines: [{shot, text, tts?, at, asr_aliases?}]}
Output: build/vo/vo-<shot>-<voice>.wav + build/vo/vo.json  (lines: shot, text, tts, file, dur, sr)
Each line is rendered separately; leading/trailing near-silence is trimmed exactly like the legacy script.

Pre-rendered VO (e.g. a two-host talk show voiced elsewhere):
  vo: {engine: files, asset: <assets.yaml id of kind vo (a directory)>, lines: [{id, shot, at, file, text, host?, sha256?}]}
  Each line's `file` is relative to the asset directory; its sha256 (when given) must match. Several lines may share
  a shot; events/mix/check key lines by `id` (default: shot). Nothing is re-synthesised.
  Optional per line: `trim: {end: <s>, fade: <s>}` cuts the WAV at `end` (chosen at a silence) with a linear fade-out;
  the trimmed copy is written to build/vo/<id>-trim.wav and used everywhere (mix, host lip-sync, ASR check). The
  line's `text` must then be what is still voiced (a prefix of the script line; the full line stays in `script_text`).
"""
from __future__ import annotations

import json
import os

import numpy as np
import soundfile as sf

from .assets import asset_path, load_manifest


def vo_json_path(spec):
    return os.path.join(spec.vo_dir, "vo.json")


def line_id(line):
    return str(line.get("id", line["shot"]))


def files_dir(spec, man=None):
    return asset_path(spec, spec.raw["vo"]["asset"], man)


_SHA = {}


def _sha(p):
    st = os.stat(p)
    k = (p, st.st_size, st.st_mtime_ns)
    if k not in _SHA:
        from .assets import sha256_file
        _SHA[k] = sha256_file(p)
    return _SHA[k]


def line_candidates(spec, line, man=None):
    """Where a line's WAV may be: `file`, any `alt_files`, then `superseded/<name>` or `superseded/<stem>.vN.wav` next
    to it (old takes are moved aside as re-voiced ones land)."""
    d = files_dir(spec, man)
    rels = [line["file"]] + list(line.get("alt_files") or [])
    sup = os.path.join(d, os.path.dirname(line["file"]), "superseded")
    stem = os.path.splitext(os.path.basename(line["file"]))[0]
    out = []
    for r in rels:
        p = os.path.join(d, r)
        if p not in out:
            out.append(p)
    if os.path.isdir(sup):                 # superseded/<name> or versioned superseded/<stem>.v1.wav, newest first
        for f in sorted(os.listdir(sup), reverse=True):
            if f == stem + ".wav" or (f.startswith(stem + ".") and f.endswith(".wav")):
                p = os.path.join(sup, f)
                if p not in out:
                    out.append(p)
    return out


def line_file(spec, line, man=None):
    """The line's WAV: the first candidate whose sha256 matches the pin (so a take moved to superseded/ mid-build is
    still found, and a new take landing under the same name is never used unpinned); without a pin, the first that exists."""
    cands = [p for p in line_candidates(spec, line, man) if os.path.exists(p)]
    if line.get("sha256"):
        for p in cands:
            if _sha(p) == line["sha256"]:
                return p
    return cands[0] if cands else line_candidates(spec, line, man)[0]


def line_audio(spec, line, man=None):
    """(mono float32, sr) of a files-engine line, with its optional trim + fade applied."""
    x, sr = sf.read(line_file(spec, line, man), dtype="float32", always_2d=True)
    x = x.mean(1)
    tr = line.get("trim")
    if tr:
        n = min(len(x), int(round(float(tr["end"]) * sr)))
        x = x[:n].copy()
        nf = min(n, int(round(float(tr.get("fade", 0.04)) * sr)))
        if nf > 0:
            x[n - nf:] *= np.linspace(1.0, 0.0, nf, dtype=np.float32)
    return x, sr


def silences(x, sr, min_len=0.12, win=0.01, db=-40.0):
    """[(start, end)] seconds of runs quieter than `db` (relative to the line's peak window RMS) lasting >= min_len."""
    hop = max(1, int(win * sr))
    n = len(x) // hop
    if n == 0:
        return []
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    q = 20 * np.log10(rms / rms.max())
    out, a = [], None
    for i, v in enumerate(q):
        if v < db and a is None:
            a = i
        elif v >= db and a is not None:
            if (i - a) * win >= min_len:
                out.append((a * win, i * win))
            a = None
    return out


def cut_after(x, sr, text, upto, fade=0.04):
    """Pick a cut right after the words `upto` (must end a prefix of `text`): the interior silence nearest to where
    that prefix ends if speech ran at an even pace. Returns dict(end, fade, silence, prefix) or None."""
    k = text.find(upto)
    if k < 0:
        return None
    prefix = text[: k + len(upto)]
    dur = len(x) / sr
    exp = dur * len(prefix) / max(1, len(text))
    sil = [s for s in silences(x, sr) if 0.2 < s[0] < dur - 0.2]
    if not sil:
        return None
    s0, s1 = min(sil, key=lambda s: abs((s[0] + s[1]) / 2 - exp))
    end = round(min(s1, s0 + 0.06) + fade, 3)          # just into the silence, then fade out over silence
    return dict(end=end, fade=fade, silence=[round(s0, 3), round(s1, 3)], prefix=prefix)


def run_files(spec):
    """Pre-rendered VO: verify each line's WAV (exists, sha256) and write build/vo/vo.json pointing at it."""
    from .assets import sha256_file
    cfg = spec.raw["vo"]
    man = load_manifest(spec)
    meta, bad = [], []
    for line in cfg["lines"]:
        p = line_file(spec, line, man)
        if not os.path.exists(p):
            bad.append(f"{line_id(line)}: missing {p}")
            continue
        if line.get("sha256") and sha256_file(p) != line["sha256"]:
            bad.append(f"{line_id(line)}: sha256 changed for {p} (VO re-rendered? regenerate the spec)")
            continue
        if line.get("trim"):
            x, sr = line_audio(spec, line, man)
            os.makedirs(spec.vo_dir, exist_ok=True)
            p = os.path.join(spec.vo_dir, f"{line_id(line)}-trim.wav")
            sf.write(p, x, sr, subtype="PCM_16")
            frames = len(x)
        else:
            info = sf.info(p)
            frames, sr = info.frames, info.samplerate
        meta.append(dict(id=line_id(line), shot=str(line["shot"]), host=line.get("host"), text=line["text"], file=p,
                         dur=round(frames / sr, 3), sr=sr, trim=line.get("trim")))
    if bad:
        raise RuntimeError("VO files gate failed:\n  - " + "\n  - ".join(bad))
    os.makedirs(spec.vo_dir, exist_ok=True)
    with open(vo_json_path(spec), "w") as f:
        json.dump(dict(engine="files", lines=meta), f, indent=1)
    return meta


def run(spec, force=False):
    cfg = spec.raw.get("vo")
    if not cfg:
        return None
    os.makedirs(spec.vo_dir, exist_ok=True)
    if cfg.get("engine") == "files":
        return run_files(spec)
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
