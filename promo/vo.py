"""VO per line (port of make_vo.py). `promo vo`.

Spec: vo: {engine: kokoro, model_asset, voices_asset, voice, lang, speed, lines: [{id?, shot, text, tts?, at, host?, voice?, asr_aliases?}]}
Output: build/vo/vo-<line id>.wav + build/vo/vo.json  (lines: id, shot, host, text, tts, file, dur, sr, engine, voice)
Each line is rendered separately (line id = `id`, default the shot); leading/trailing near-silence is trimmed exactly
like the legacy script. Takes are cached by what changes the audio (build/vo/.cache), so re-voicing one line of a
dialogue only synthesises that line.

Voices per line (a dialogue): the vo block's engine/voice/speed/lang, then the line's host voice
(`podcast.hosts[].voice: {engine, voice, speed}`, the host matched by id, name or model), then the line's own
`voice:` (a dict, or a bare voice name). Engines:
  kokoro       Apache-2.0 Kokoro-82M (model_asset + voices_asset in assets.yaml). The default; fit to publish.
  say          macOS `say` (voice e.g. "Flo (English (UK))"). Drafts only: needs `asset:` naming an assets.yaml entry
               (Apple's terms: personal, non-commercial); `promo check` WARNs `draft-voice`.
  voicestudio  the local VoiceStudio app (http://127.0.0.1:3900, $PROMO_VOICESTUDIO): `profile` (profile id) or
               `instruct` (voice design), `seed`. Needs `asset:`; its model is CC-BY-NC, an open licence question.
  files        pre-rendered WAVs (below); the whole vo block only.

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
                         dur=round(frames / sr, 3), sr=sr, trim=line.get("trim"), db=float(line.get("db", 0.0))))
    if bad:
        raise RuntimeError("VO files gate failed:\n  - " + "\n  - ".join(bad))
    os.makedirs(spec.vo_dir, exist_ok=True)
    with open(vo_json_path(spec), "w") as f:
        json.dump(dict(engine="files", lines=meta), f, indent=1)
    return meta


ENGINES = ("kokoro", "say", "voicestudio", "files")
DRAFT_ENGINES = ("say",)
VOICE_KEYS = ("engine", "voice", "speed", "lang", "asset", "profile", "instruct", "seed", "rate")


def _host_of(spec, line):
    who = str(line.get("host") or "").strip().lower()
    if not who:
        return None
    for h in (spec.raw.get("podcast") or {}).get("hosts") or []:
        if who in {str(h.get(k, "")).lower() for k in ("id", "name", "model")}:
            return h
    return None


def voice_of(spec, line):
    """The resolved voice of one line: vo-level defaults < the host's `voice:` < the line's own `voice:`."""
    cfg = spec.raw.get("vo") or {}
    v = {k: cfg[k] for k in VOICE_KEYS if k in cfg and k != "asset"}
    v.setdefault("engine", "kokoro")
    h = _host_of(spec, line)
    for src in ((h or {}).get("voice"), line.get("voice")):
        if isinstance(src, str):
            v["voice"] = src
        elif isinstance(src, dict):
            v.update({k: src[k] for k in VOICE_KEYS if k in src})
    if v["engine"] not in ENGINES or v["engine"] == "files":
        raise RuntimeError(f"VO line {line_id(line)}: engine {v['engine']!r} (have kokoro, say, voicestudio; `files` is for the whole vo block)")
    if v["engine"] == "kokoro":
        v.setdefault("voice", "bf_emma")
        v.setdefault("lang", "en-gb" if str(v["voice"]).startswith("b") else "en-us")
    return v


def voices_used(spec):
    """[(line id, voice dict)] for every synthesised line (empty for the files engine)."""
    cfg = spec.raw.get("vo") or {}
    if not cfg or cfg.get("engine") == "files":
        return []
    return [(line_id(ln), voice_of(spec, ln)) for ln in cfg.get("lines") or []]


def _trim(s, sr):
    s = np.asarray(s, dtype=np.float32)
    idx = np.where(np.abs(s) > 0.01)[0]
    if not len(idx):
        return s
    return s[max(0, idx[0] - int(0.01 * sr)): idx[-1] + int(0.1 * sr)]      # trim leading/trailing near-silence (legacy: 240 / 2400 at 24 kHz)


_KOKORO = {}


def synth(spec, v, text, man=None):
    """(mono float32, sr) of one take in voice `v`."""
    eng = v["engine"]
    if eng == "kokoro":
        try:
            from kokoro_onnx import Kokoro
        except ImportError as e:
            raise RuntimeError("`promo vo` needs the vo extra: pip install 'promo-reel[vo]' (kokoro-onnx)") from e
        cfg = spec.raw.get("vo") or {}
        man = man or load_manifest(spec)
        key = (asset_path(spec, cfg["model_asset"], man), asset_path(spec, cfg["voices_asset"], man))
        if key not in _KOKORO:
            _KOKORO[key] = Kokoro(*key)
        s, sr = _KOKORO[key].create(text, voice=v["voice"], speed=float(v.get("speed", 1.0)), lang=v.get("lang", "en-gb"))
        return _trim(s, sr), sr
    if eng == "say":
        import shutil
        import subprocess
        import tempfile
        if not shutil.which("say"):
            raise RuntimeError("engine `say` needs macOS `say`")
        d = tempfile.mkdtemp(prefix="vo-say-")
        out = os.path.join(d, "say.wav")
        cmd = ["say", "-o", out, "--file-format=WAVE", "--data-format=LEI16@24000", "-r", str(int(float(v.get("rate", 180)) * float(v.get("speed", 1.0))))]
        if v.get("voice"):
            cmd += ["-v", str(v["voice"])]
        subprocess.run(cmd + [text], check=True)
        s, sr = sf.read(out, dtype="float32", always_2d=True)
        import shutil as _sh
        _sh.rmtree(d, ignore_errors=True)
        return _trim(s.mean(1), sr), sr
    if eng == "voicestudio":
        import io
        import urllib.request
        import uuid
        url = os.environ.get("PROMO_VOICESTUDIO", "http://127.0.0.1:3900").rstrip("/") + "/generate"
        fields = dict(text=text, effect_preset="raw", speed=str(float(v.get("speed", 1.0))), seed=str(int(v.get("seed", 1))))
        if v.get("profile"):
            fields["profile_id"] = str(v["profile"])
        if v.get("instruct"):
            fields["instruct"] = str(v["instruct"])
        b = uuid.uuid4().hex
        body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{val}\r\n'.encode() for k, val in fields.items()) + f"--{b}--\r\n".encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = r.read()
        except OSError as e:
            raise RuntimeError(f"VoiceStudio not reachable at {url} ({e}); start the app or use engine kokoro") from e
        s, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        return _trim(s.mean(1), sr), sr
    raise RuntimeError(f"engine {eng!r}")


def take_key(spec, v, text):
    """What a take depends on (the cache key): the voice, the text and, for kokoro, the model files."""
    import hashlib
    extra = None
    if v["engine"] == "kokoro":
        from .cache import file_sig
        cfg = spec.raw.get("vo") or {}
        man = load_manifest(spec)
        extra = [file_sig(asset_path(spec, cfg[k], man)) for k in ("model_asset", "voices_asset")]
    return hashlib.sha256(json.dumps([v, text, extra], sort_keys=True, default=str).encode()).hexdigest()[:20]


def run(spec, force=False):
    cfg = spec.raw.get("vo")
    if not cfg:
        return None
    os.makedirs(spec.vo_dir, exist_ok=True)
    if cfg.get("engine") == "files":
        return run_files(spec)
    cache = os.path.join(spec.vo_dir, ".cache")
    os.makedirs(cache, exist_ok=True)
    man = None
    meta, keep = [], set()
    for line in cfg["lines"]:
        lid, txt = line_id(line), line["text"]
        say = line.get("tts", txt)
        v = voice_of(spec, line)
        if v["engine"] == "kokoro" and man is None:
            man = load_manifest(spec)
        key = take_key(spec, v, say)
        cp = os.path.join(cache, key + ".wav")
        if force or not os.path.exists(cp):
            s, sr = synth(spec, v, say, man)
            sf.write(cp + ".tmp.wav", s, sr)
            os.replace(cp + ".tmp.wav", cp)
        info = sf.info(cp)
        fn = f"vo-{lid}.wav"
        dst = os.path.join(spec.vo_dir, fn)
        if not os.path.exists(dst) or open(dst, "rb").read() != open(cp, "rb").read():
            import shutil
            shutil.copyfile(cp, dst + ".tmp")
            os.replace(dst + ".tmp", dst)
        keep.add(key)
        meta.append(dict(id=lid, shot=str(line["shot"]), host=line.get("host"), text=txt, tts=say, file=fn, dur=round(info.frames / info.samplerate, 3),
                         sr=info.samplerate, engine=v["engine"], voice=v.get("voice") or v.get("profile") or v.get("instruct")))
        print("vo", lid, v["engine"], meta[-1]["voice"], round(meta[-1]["dur"], 2), txt, flush=True)
    old = sorted((os.path.getmtime(os.path.join(cache, f)), f) for f in os.listdir(cache) if f.endswith(".wav") and f[:-4] not in keep)
    for _, f in old[:max(0, len(old) - 200)]:           # keep up to 200 unused takes (an undo re-uses them), oldest go first
        os.remove(os.path.join(cache, f))
    with open(vo_json_path(spec), "w") as f:
        json.dump(dict(voice=cfg.get("voice"), lang=cfg.get("lang"), speed=cfg.get("speed"), lines=meta), f, indent=1)
    return meta
