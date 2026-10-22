"""Cloned voices on this Mac (Chatterbox, MIT). Nothing here is committed.

Storage is ``~/.promo-reel/voices/<id>/`` (override with ``PROMO_VOICES_DIR``).
A host job passes its ``data_dir`` as ``call(..., root=)``. That job then reads
and writes ``<data_dir>/voices`` only, on its own thread, without changing the
process environment. With ``data_dir`` set, every returned ``{"$file": ...}``
is relative to it (``voices/<id>/sample.wav``) and must not escape it.
``sample_b64`` and ``wav_base64`` are unchanged.

Storage layout:

    voice.yaml          name, engine, created, moods, consent, default
    licence.yaml        model, MIT, source, watermark perth, likeness, consent
    script/*.wav        the guided reading (at least 30 s altogether)
    moods/{neutral,excited,calm,warm}.wav
    sample.wav          the last `promo voices sample`

Weights live beside that tree (``~/.promo-reel/models/chatterbox``, or ``<parent of PROMO_VOICES_DIR>/models/chatterbox``)
and download only when someone runs ``promo voices model download --yes``. Synthesis imports Chatterbox lazily.
Every take keeps Chatterbox's Perth watermark; nothing in this module strips it.
"""
from __future__ import annotations

import argparse
import base64
import contextvars
import datetime
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

import soundfile as sf
import yaml

MOODS = ("neutral", "excited", "calm", "warm")
MIN_SCRIPT_S = 30.0
SOURCE_URL = "https://github.com/resemble-ai/chatterbox"
MODEL_REPO = "ResembleAI/chatterbox"
WEIGHTS = ("ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt")
SIZE_LABEL = "~3 GB"
MODEL_BYTES = 3 * 1024 ** 3
CONSENT = "own voice, recorded by the speaker on this Mac"
# A natural read, phonetically varied, about 80 words across five short paragraphs (~30 s out loud).
SCRIPT = (
    "Hello, this is my voice, the one I use when I explain something carefully to a friend.",
    "The quick brown fox jumps by a quiet river, and unique voices carry every vowel and consonant.",
    "You give it a ticket, and a small team picks it up. One plans, one writes the code, and one reviews it.",
    "A clear sentence beats a clever one, and the picture on screen matches the words.",
    "That is enough for a clone. Thank you for listening.",
)
EMOTIONS = {
    "neutral": "This is my everyday voice, steady and plain.",
    "excited": "It shipped overnight, and the tests pass!",
    "calm": "Take a breath. We can look at this slowly.",
    "warm": "I am glad you are here. We will take good care of this.",
}
_NC = re.compile(r"non-?commercial|\bcc-?by-nc\b|\bby-nc\b|\bnc\b", re.I)
_MODEL = None
# Per call, not a process env var: jobs run concurrently, each with its own data_dir.
_DATA_DIR = contextvars.ContextVar("promo_voices_data_dir", default=None)


class VoicesError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def voices_root():
    """Voice tree for this call. A host ``data_dir`` wins over ``PROMO_VOICES_DIR``."""
    data = _DATA_DIR.get()
    if data:
        return os.path.join(data, "voices")
    return os.path.abspath(os.path.expanduser(os.environ.get("PROMO_VOICES_DIR") or "~/.promo-reel/voices"))


def model_dir():
    """Weights sit next to the voices tree, never inside a voice id, and never download on their own."""
    env = os.environ.get("PROMO_VOICES_DIR")
    if env:
        parent = os.path.dirname(os.path.abspath(os.path.expanduser(env)))
        return os.path.join(parent, "models", "chatterbox")
    return os.path.expanduser("~/.promo-reel/models/chatterbox")


def voice_dir(vid):
    return os.path.join(voices_root(), str(vid))


def asset_id(vid):
    return "vo-" + str(vid)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _read_yaml(path):
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _write_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def _ids():
    root = voices_root()
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root)):
        if name.startswith("."):
            continue
        if os.path.isfile(os.path.join(root, name, "voice.yaml")):
            out.append(name)
    return out


def default_id():
    p = os.path.join(voices_root(), "default")
    if not os.path.isfile(p):
        return None
    vid = open(p).read().strip()
    return vid if vid in set(_ids()) else None


def _set_flag(vid, on):
    p = os.path.join(voice_dir(vid), "voice.yaml")
    raw = _read_yaml(p)
    if not raw:
        return
    raw["default"] = bool(on)
    _write_yaml(p, raw)


def load(vid):
    d = voice_dir(vid)
    raw = _read_yaml(os.path.join(d, "voice.yaml"))
    if not raw:
        raise VoicesError("voices.not_found", f"no voice {vid}")
    return {
        "id": str(vid),
        "dir": d,
        "name": raw.get("name") or str(vid),
        "engine": raw.get("engine") or "clone",
        "created": raw.get("created"),
        "moods": list(raw.get("moods") or MOODS),
        "consent": raw.get("consent") or "",
        "default": default_id() == str(vid),
        "licence": _read_yaml(os.path.join(d, "licence.yaml")),
        "raw": raw,
    }


def require(vid):
    if not vid or not str(vid).strip():
        raise VoicesError("voices.not_found", "voice id is empty")
    return load(str(vid).strip())


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return s or "voice"


def _fresh_id(name):
    base, have = _slug(name), set(_ids())
    if base not in have:
        return base
    n = 2
    while f"{base}-{n}" in have:
        n += 1
    return f"{base}-{n}"


def wav_seconds(path):
    info = sf.info(path)
    if not info.samplerate:
        return 0.0
    return info.frames / float(info.samplerate)


def _script_wavs(script_dir):
    if not os.path.isdir(script_dir):
        raise VoicesError("voices.bad_script", f"script dir not found: {script_dir}")
    files = []
    for name in sorted(os.listdir(script_dir)):
        p = os.path.join(script_dir, name)
        if name.lower().endswith(".wav") and os.path.isfile(p):
            files.append(p)
    return files


def _mood_files(moods_dir):
    found = {}
    if not os.path.isdir(moods_dir):
        return found
    for name in os.listdir(moods_dir):
        stem, ext = os.path.splitext(name)
        if ext.lower() == ".wav" and stem.lower() in MOODS and os.path.isfile(os.path.join(moods_dir, name)):
            found[stem.lower()] = os.path.join(moods_dir, name)
    return found


def check_emotion(emotion):
    if emotion is None or emotion == "":
        return "neutral"
    s = str(emotion).strip().lower()
    if s not in MOODS:
        raise VoicesError("voices.bad_emotion", f"emotion must be one of {', '.join(MOODS)} (got {emotion!r})")
    return s


def check_intensity(intensity):
    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
        raise VoicesError("voices.bad_intensity", f"intensity must be a number from 0 to 1 (got {intensity!r})")
    f = float(intensity)
    if f < 0.0 or f > 1.0:
        raise VoicesError("voices.bad_intensity", f"intensity must be from 0 to 1 (got {f})")
    return f


def exaggeration(intensity):
    """Chatterbox exaggeration: intensity 0 → 0.25, 1 → 1.0."""
    return 0.25 + check_intensity(intensity) * 0.75


def parse_vo(vo):
    """Validate a promo.yaml ``vo:`` block for engine clone. Does not look the voice up on disk."""
    if not isinstance(vo, dict):
        raise VoicesError("voices.bad_vo", "vo must be a map")
    if vo.get("engine") != "clone":
        raise VoicesError("voices.bad_vo", f"engine must be clone (got {vo.get('engine')!r})")
    vid = vo.get("voice")
    if not isinstance(vid, str) or not vid.strip():
        raise VoicesError("voices.bad_vo", "vo.voice is required for engine clone")
    lines = []
    for i, line in enumerate(vo.get("lines") or []):
        if not isinstance(line, dict):
            raise VoicesError("voices.bad_line", f"vo line {i} must be a map")
        if not str(line.get("text") or "").strip():
            raise VoicesError("voices.bad_line", f"vo line {line.get('id', i)} needs text")
        emo = check_emotion(line.get("emotion", "neutral"))
        if "intensity" in line and line.get("intensity") is not None:
            inten = check_intensity(line["intensity"])
        else:
            inten = 0.5
        lines.append({"id": line.get("id"), "shot": line.get("shot"), "at": line.get("at"), "text": line["text"],
                       "emotion": emo, "intensity": inten})
    return {"engine": "clone", "voice": vid.strip(), "lines": lines}


def vo_problems(raw):
    """Problem strings for ``spec.validate`` (empty when this spec is not a clone voice)."""
    vo = (raw or {}).get("vo") or {}
    if not isinstance(vo, dict) or vo.get("engine") != "clone":
        return []
    try:
        parsed = parse_vo(vo)
        require(parsed["voice"])
    except VoicesError as e:
        return [f"{e.code}: {e.message}"]
    return []


def require_project(path):
    """Raise ``voices.not_found`` when this promo.yaml's clone voice is gone. Other engines return None."""
    raw = _read_yaml(path)
    vo = raw.get("vo") or {}
    if not isinstance(vo, dict) or vo.get("engine") != "clone":
        return None
    parsed = parse_vo(vo)
    return require(parsed["voice"])


def is_commercial(lic):
    if isinstance(lic, dict) and lic.get("commercial") is False:
        return False
    text = lic.get("licence") if isinstance(lic, dict) else str(lic or "")
    if _NC.search(str(text or "")):
        return False
    return True


def licence_to_asset(voice):
    """One assets.yaml entry for this voice. A non-commercial model is ``test_only: true``."""
    rec = voice if isinstance(voice, dict) and voice.get("licence") is not None and voice.get("id") and voice.get("dir") else require(voice)
    if "licence" not in rec or not rec.get("dir"):
        rec = require(rec.get("id") or voice)
    lic = rec.get("licence") or {}
    consent = lic.get("consent") or rec.get("consent") or CONSENT
    entry = {
        "id": asset_id(rec["id"]),
        "kind": "vo_model",
        "path": rec["dir"],
        "licence": lic.get("licence") or "MIT",
        "source_url": lic.get("source_url") or SOURCE_URL,
        "watermark": lic.get("watermark") or "perth",
        "generated": {"likeness": lic.get("likeness") or "own", "consent": consent},
    }
    if not is_commercial(lic):
        entry["test_only"] = True
    return entry


def script_text():
    words = len(re.findall(r"[A-Za-z0-9']+", " ".join(SCRIPT)))
    return {"paragraphs": list(SCRIPT), "words": words, "seconds": MIN_SCRIPT_S, "emotions": dict(EMOTIONS)}


def list_voices():
    rows = []
    for vid in _ids():
        rec = load(vid)
        sample = os.path.join(rec["dir"], "sample.wav")
        has = os.path.isfile(sample)
        row = {
            "id": vid,
            "name": rec["name"],
            "engine": rec["engine"],
            "moods": rec["moods"],
            "created": rec["created"],
            "sample": {"$file": sample} if has else None,
            "default": rec["default"],
            "consent": rec["consent"],
            "watermark": (rec.get("licence") or {}).get("watermark") or "perth",
            "licence": (rec.get("licence") or {}).get("licence") or "MIT",
        }
        if has and os.path.getsize(sample) <= 400_000:
            with open(sample, "rb") as f:
                row["sample_b64"] = base64.b64encode(f.read()).decode("ascii")
        rows.append(row)
    rows.sort(key=lambda r: (r.get("created") or "", r["id"]))
    return rows


def save(name, script_dir, moods_dir, consent=None):
    """Copy a reading and four moods in. Refuses a short reading or a missing mood before creating the voice."""
    if not str(name or "").strip():
        raise VoicesError("voices.bad_name", "a voice needs a name")
    files = _script_wavs(script_dir)
    total = sum(wav_seconds(p) for p in files)
    if total < MIN_SCRIPT_S:
        raise VoicesError("voices.too_short", f"script audio is {total:.3f} s; need at least {MIN_SCRIPT_S:.1f} s")
    moods = _mood_files(moods_dir)
    missing = [m for m in MOODS if m not in moods]
    if missing:
        raise VoicesError("voices.mood_missing", f"missing mood clips: {', '.join(missing)} (need {', '.join(MOODS)})")
    vid = _fresh_id(name)
    d = voice_dir(vid)
    os.makedirs(os.path.join(d, "script"), exist_ok=True)
    os.makedirs(os.path.join(d, "moods"), exist_ok=True)
    for p in files:
        shutil.copy2(p, os.path.join(d, "script", os.path.basename(p)))
    for emo, p in moods.items():
        shutil.copy2(p, os.path.join(d, "moods", emo + ".wav"))
    consent = (consent or CONSENT).strip() or CONSENT
    first = default_id() is None
    _write_yaml(os.path.join(d, "voice.yaml"), {
        "name": str(name).strip(),
        "engine": "clone",
        "created": _now(),
        "moods": list(MOODS),
        "consent": consent,
        "default": first,
    })
    _write_yaml(os.path.join(d, "licence.yaml"), {
        "model": "chatterbox",
        "licence": "MIT",
        "source_url": SOURCE_URL,
        "watermark": "perth",
        "commercial": True,
        "likeness": "own",
        "consent": consent,
    })
    if first:
        _write_default(vid)
    return {"id": vid, "name": str(name).strip(), "engine": "clone", "dir": d, "moods": list(MOODS),
            "default": first, "seconds": round(total, 3), "watermark": "perth"}


def _write_default(vid):
    os.makedirs(voices_root(), exist_ok=True)
    with open(os.path.join(voices_root(), "default"), "w") as f:
        f.write(str(vid) + "\n")
    for other in _ids():
        _set_flag(other, other == vid)


def rename(vid, name):
    if not str(name or "").strip():
        raise VoicesError("voices.bad_name", "a voice needs a name")
    rec = require(vid)
    raw = dict(rec["raw"])
    raw["name"] = str(name).strip()
    _write_yaml(os.path.join(rec["dir"], "voice.yaml"), raw)
    return {"id": rec["id"], "name": raw["name"]}


def delete(vid):
    rec = require(vid)
    shutil.rmtree(rec["dir"])
    if default_id() == rec["id"] or _read_default_raw() == rec["id"]:
        p = os.path.join(voices_root(), "default")
        if os.path.isfile(p):
            os.remove(p)
    return {"id": rec["id"], "deleted": True}


def _read_default_raw():
    p = os.path.join(voices_root(), "default")
    return open(p).read().strip() if os.path.isfile(p) else None


def set_default(vid):
    rec = require(vid)
    _write_default(rec["id"])
    return {"id": rec["id"], "default": True}


def _b64_write(path, data):
    raw = data.split(",", 1)[-1] if isinstance(data, str) else data
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(base64.b64decode(raw))


def save_params(params, progress=None):
    """``save`` from the worker: filesystem dirs, or base64 ``{name, base64}`` parts."""
    params = params or {}
    name = params.get("name")
    script, moods = params.get("script"), params.get("moods")
    if isinstance(script, str) and isinstance(moods, str):
        return save(name, script, moods, consent=params.get("consent"))
    if params.get("script_dir") and params.get("moods_dir"):
        return save(name, params["script_dir"], params["moods_dir"], consent=params.get("consent"))
    tmp = tempfile.mkdtemp(prefix="voices-")
    try:
        sd, md = os.path.join(tmp, "script"), os.path.join(tmp, "moods")
        os.makedirs(sd)
        os.makedirs(md)
        parts = script or []
        if isinstance(parts, dict):
            parts = [{"name": k, "base64": v.get("base64") if isinstance(v, dict) else v} for k, v in parts.items()]
        for i, part in enumerate(parts):
            if not isinstance(part, dict) or not part.get("base64"):
                continue
            _b64_write(os.path.join(sd, part.get("name") or f"{i:02d}.wav"), part["base64"])
        mood_map = moods or {}
        for emo in MOODS:
            item = mood_map.get(emo)
            if not item:
                continue
            blob = item.get("base64") if isinstance(item, dict) else item
            if blob:
                _b64_write(os.path.join(md, emo + ".wav"), blob)
        if progress:
            progress(0.4, "checking the recording")
        return save(name, sd, md, consent=params.get("consent"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def model_status():
    d = model_dir()
    files = {}
    weights = True
    for name in WEIGHTS:
        ok = os.path.isfile(os.path.join(d, name)) and os.path.getsize(os.path.join(d, name)) > 0
        files[name] = ok
        weights = weights and ok
    installed = importlib.util.find_spec("chatterbox") is not None
    return {"installed": installed, "weights": weights, "ready": installed and weights, "size": SIZE_LABEL,
            "bytes": MODEL_BYTES, "dir": d, "files": files, "model": "chatterbox", "licence": "MIT", "watermark": "perth"}


def ensure_engine():
    """Package and weights must both be present. Does not import Chatterbox and does not download."""
    st = model_status()
    if not st["installed"]:
        raise VoicesError("voices.engine_missing",
                          "Chatterbox is not installed. pip install 'promo-reel[clone]' (chatterbox-tts). Nothing was downloaded.")
    if not st["weights"]:
        raise VoicesError("voices.engine_missing",
                          f"Chatterbox weights are not on this Mac ({SIZE_LABEL}). Run `promo voices model download --yes`. Nothing was downloaded.")
    return st


def model_download(yes=False):
    """Download weights only when ``yes`` is true. The CLI prints the size before it calls this."""
    if not yes:
        raise VoicesError("voices.model_confirm",
                          f"Chatterbox weights are {SIZE_LABEL}. Re-run with --yes to download. Nothing was downloaded.")
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        raise VoicesError("voices.engine_missing",
                          "huggingface_hub is not installed (it comes with chatterbox-tts). Nothing was downloaded.") from e
    d = model_dir()
    os.makedirs(d, exist_ok=True)
    for name in WEIGHTS:
        hf_hub_download(repo_id=MODEL_REPO, filename=name, local_dir=d)
    return model_status()


def _load_model():
    """Import Chatterbox and load local weights. Never calls ``from_pretrained`` (that would download)."""
    global _MODEL
    ensure_engine()
    if _MODEL is not None:
        return _MODEL
    import inspect
    import torch
    from chatterbox.tts import ChatterboxTTS
    dev = "cpu"
    if torch.cuda.is_available():
        dev = "cuda"
    else:
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            dev = "mps"
    sig = inspect.signature(ChatterboxTTS.from_local)
    kw = {"device": dev} if "device" in sig.parameters else {}
    _MODEL = ChatterboxTTS.from_local(model_dir(), **kw)
    return _MODEL


def synth_array(voice_id, text, emotion="neutral", intensity=0.5):
    """(float32 mono, sample rate) of one Perth-watermarked take. Imports Chatterbox only here."""
    if not str(text or "").strip():
        raise VoicesError("voices.bad_line", "a line needs text")
    rec = require(voice_id)
    emo = check_emotion(emotion)
    inten = check_intensity(0.5 if intensity is None else intensity)
    prompt = os.path.join(rec["dir"], "moods", emo + ".wav")
    if not os.path.isfile(prompt):
        raise VoicesError("voices.mood_missing", f"mood {emo} is missing for voice {rec['id']}")
    import inspect
    import numpy as np
    model = _load_model()
    kw = {"audio_prompt_path": prompt, "exaggeration": exaggeration(inten)}
    sig = inspect.signature(model.generate)
    if "apply_watermark" in sig.parameters:
        kw["apply_watermark"] = True                       # a fork must not be asked to strip Perth
    wav = model.generate(str(text), **kw)
    if isinstance(wav, (tuple, list)):
        wav = wav[0]
    if hasattr(wav, "detach"):
        arr = wav.detach().float().cpu().numpy()
    else:
        arr = np.asarray(wav)
    arr = np.squeeze(np.asarray(arr, dtype="float32"))
    if arr.ndim > 1:
        arr = arr.reshape(-1)
    sr = int(getattr(model, "sr", 24000))
    return arr, sr


def _write_take(path, voice_id, text, emotion, intensity, progress=None):
    if progress:
        progress(0.15, "loading Chatterbox")
    arr, sr = synth_array(voice_id, text, emotion, intensity)
    if progress:
        progress(0.9, "writing")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, arr, sr)
    if progress:
        progress(1.0, "done")
    return path


def sample(vid, text, emotion="neutral", intensity=0.5, progress=None):
    rec = require(vid)
    path = os.path.join(rec["dir"], "sample.wav")
    _write_take(path, rec["id"], text, emotion, intensity, progress=progress)
    out = {"id": rec["id"], "file": path, "sample": {"$file": path}, "emotion": check_emotion(emotion),
           "intensity": check_intensity(0.5 if intensity is None else intensity), "watermark": "perth"}
    if os.path.getsize(path) <= 400_000:
        with open(path, "rb") as f:
            out["wav_base64"] = base64.b64encode(f.read()).decode("ascii")
    return out


def _load_lines(path):
    with open(path) as f:
        raw = f.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = yaml.safe_load(raw)
    lines = data.get("lines") if isinstance(data, dict) else data
    if not isinstance(lines, list):
        raise VoicesError("voices.bad_line", "lines file must be a list, or a map with lines:")
    return lines


def render(vid, lines_file, out_dir=None, progress=None):
    rec = require(vid)
    lines = _load_lines(lines_file)
    out = out_dir or os.path.join(rec["dir"], "renders")
    os.makedirs(out, exist_ok=True)
    made = []
    n = max(1, len(lines))
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            raise VoicesError("voices.bad_line", f"line {i} must be a map")
        emo = check_emotion(line.get("emotion", "neutral"))
        inten = check_intensity(line["intensity"]) if "intensity" in line and line.get("intensity") is not None else 0.5
        lid = str(line.get("id") or i + 1)
        path = os.path.join(out, f"vo-{lid}.wav")
        if progress:
            progress(i / n, f"line {lid}")
        _write_take(path, rec["id"], line.get("text"), emo, inten, progress=None)
        made.append({"id": lid, "file": path, "emotion": emo, "intensity": inten, "watermark": "perth"})
    if progress:
        progress(1.0, "done")
    return {"id": rec["id"], "lines": made, "watermark": "perth"}


def promo_start(params):
    """What the host needs to open a thread. This does not create the thread."""
    params = params or {}
    brief = str(params.get("brief") or "").strip()
    if not brief:
        raise VoicesError("voices.bad_brief", "Say what the video is for.")
    voice = params.get("voice") or None
    if voice in ("", "none", "None"):
        voice = None
    if voice:
        require(voice)
    return {"brief": brief, "voice": voice}


def _rel_file(path, data_dir):
    """Path of ``path`` relative to ``data_dir``, or an error if it escapes."""
    path = os.path.abspath(path)
    base = os.path.abspath(data_dir)
    try:
        common = os.path.commonpath([path, base])
    except ValueError as e:
        raise VoicesError("host.path_escape", "file is outside the host data folder") from e
    if common != base:
        raise VoicesError("host.path_escape", "file is outside the host data folder")
    rel = os.path.relpath(path, base).replace("\\", "/")
    if rel == ".." or rel.startswith("../") or rel.startswith("/") or ".." in rel.split("/"):
        raise VoicesError("host.path_escape", "file is outside the host data folder")
    return rel


def _rewrite_files(value, data_dir):
    """Turn ``{"$file": abs}`` into ``{"$file": rel}``. Leaves ``sample_b64`` / ``wav_base64`` alone."""
    if isinstance(value, dict):
        if set(value.keys()) == {"$file"} and isinstance(value.get("$file"), str):
            return {"$file": _rel_file(value["$file"], data_dir)}
        return {k: _rewrite_files(v, data_dir) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite_files(v, data_dir) for v in value]
    return value


def call(method, params=None, progress=None, root=None):
    """One worker / CLI method. ``progress(pct, note)`` is a 0..1 fraction.

    ``root`` is the host job's ``data_dir`` (absolute). Voices then live in
    ``<root>/voices`` for this call only. Omit it for the CLI default.
    """
    base = None
    token = None
    if isinstance(root, str) and root.strip():
        base = os.path.abspath(os.path.expanduser(root))
        token = _DATA_DIR.set(base)
    try:
        value = _call(method, params, progress)
        if base is not None:
            value = _rewrite_files(value, base)
        return value
    finally:
        if token is not None:
            _DATA_DIR.reset(token)


def _call(method, params=None, progress=None):
    """Dispatch one method against the current voice root. ``progress`` is 0..1."""
    params = params or {}
    if method == "voices.list":
        return list_voices()
    if method == "voices.save":
        return save_params(params, progress)
    if method == "voices.rename":
        return rename(params.get("id"), params.get("name"))
    if method == "voices.delete":
        return delete(params.get("id"))
    if method == "voices.sample":
        return sample(params.get("id"), params.get("text"), params.get("emotion") or "neutral",
                      0.5 if params.get("intensity") is None else params.get("intensity"), progress)
    if method == "voices.default":
        if params.get("id"):
            return set_default(params["id"])
        vid = default_id()
        return {"id": vid, "default": vid}
    if method == "voices.script":
        return script_text()
    if method == "voices.model.status":
        return model_status()
    if method == "voices.model.download":
        if not params.get("yes"):
            st = model_status()
            st["needs_yes"] = True
            st["message"] = f"Chatterbox weights are {SIZE_LABEL}. Pass yes to download. Nothing was downloaded."
            return st
        return model_download(yes=True)
    if method == "voices.render":
        return render(params.get("id"), params.get("lines"), params.get("out"), progress)
    if method == "promo.start":
        return promo_start(params)
    raise VoicesError("voices.bad_method", f"unknown method {method}")


def _emit(ok_payload, as_json, err=None):
    if err is not None:
        if as_json:
            print(json.dumps({"code": err.code, "message": err.message}))
        else:
            print(f"{err.code}: {err.message}", file=sys.stderr)
        return 1
    if as_json:
        body = {"ok": True}
        body.update(ok_payload)
        print(json.dumps(body, default=str))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="promo voices", description="Clone a voice on this Mac (Chatterbox, MIT). Recordings stay in ~/.promo-reel/voices.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def P(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("--json", action="store_true")
        return p

    P("list")
    p = P("save")
    p.add_argument("--name", required=True)
    p.add_argument("--script", required=True, help="directory of script WAVs (at least 30 s total)")
    p.add_argument("--moods", required=True, help="directory with neutral, excited, calm, warm WAVs")
    p.add_argument("--consent", default=None)
    p = P("rename")
    p.add_argument("id")
    p.add_argument("--name", required=True)
    P("delete").add_argument("id")
    p = P("sample")
    p.add_argument("id")
    p.add_argument("--text", required=True)
    p.add_argument("--emotion", default="neutral")
    p.add_argument("--intensity", type=float, default=0.5)
    p = P("render")
    p.add_argument("id")
    p.add_argument("--lines", required=True, help="YAML or JSON lines: [{id, text, emotion, intensity}]")
    p.add_argument("--out")
    p = P("default")
    p.add_argument("id", nargs="?")
    P("script", help="print the guided reading and one line per mood")
    p = P("model")
    p.add_argument("action", choices=["status", "download"])
    p.add_argument("--yes", action="store_true", help="download the weights (~3 GB); without this, nothing is downloaded")
    a = ap.parse_args(argv)
    js = a.json
    try:
        if a.cmd == "list":
            rows = list_voices()
            if js:
                return _emit({"voices": rows}, True)
            if not rows:
                print("no voices yet. `promo voices script` prints the reading; `promo voices save --name N --script DIR --moods DIR` keeps it.")
            for r in rows:
                mark = " default" if r["default"] else ""
                print(f"{r['id']:<24} {r['name']}{mark}")
            return 0
        if a.cmd == "save":
            rec = save(a.name, a.script, a.moods, a.consent)
            if js:
                return _emit(rec, True)
            print(f"saved {rec['id']} ({rec['seconds']} s) in {rec['dir']}")
            return 0
        if a.cmd == "rename":
            rec = rename(a.id, a.name)
            if js:
                return _emit(rec, True)
            print(f"{rec['id']} is now {rec['name']}")
            return 0
        if a.cmd == "delete":
            rec = delete(a.id)
            if js:
                return _emit(rec, True)
            print(f"deleted {rec['id']}")
            return 0
        if a.cmd == "sample":
            rec = sample(a.id, a.text, a.emotion, a.intensity)
            if js:
                return _emit({k: rec[k] for k in ("id", "file", "emotion", "intensity", "watermark")}, True)
            print(rec["file"])
            return 0
        if a.cmd == "render":
            rec = render(a.id, a.lines, a.out)
            if js:
                return _emit(rec, True)
            for line in rec["lines"]:
                print(f"{line['id']} {line['file']}")
            return 0
        if a.cmd == "default":
            rec = set_default(a.id) if a.id else {"id": default_id(), "default": default_id()}
            if js:
                return _emit(rec, True)
            print(rec["id"] or "(none)")
            return 0
        if a.cmd == "script":
            body = script_text()
            if js:
                return _emit(body, True)
            print("\n\n".join(body["paragraphs"]))
            print()
            for emo in MOODS:
                print(f"{emo}: {body['emotions'][emo]}")
            return 0
        if a.cmd == "model" and a.action == "status":
            st = model_status()
            if js:
                return _emit(st, True)
            print(f"Chatterbox (MIT): installed {'yes' if st['installed'] else 'no'}")
            print(f"weights: {'ready' if st['weights'] else 'missing'} ({st['size']})")
            print(f"dir: {st['dir']}")
            return 0
        if a.cmd == "model" and a.action == "download":
            print(f"Chatterbox weights: {SIZE_LABEL}", flush=True)
            if not a.yes:
                return _emit(None, js, VoicesError("voices.model_confirm", "Nothing was downloaded. Re-run with --yes to download the weights."))
            st = model_download(yes=True)
            if js:
                return _emit(st, True)
            print(f"downloaded to {st['dir']}")
            return 0
    except VoicesError as e:
        return _emit(None, js, e)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
