"""VO per line (port of make_vo.py). `promo vo`.

Spec: vo: {engine: kokoro, model_asset, voices_asset, voice, lang, speed, takes?, max_usd?,
            lines: [{id?, shot, text, tts?, at, host?, voice?, asr_aliases?, takes?, take?}]}
Output: build/vo/vo-<line id>.wav + build/vo/vo.json  (lines: id, shot, host, text, tts, file, dur, sr, engine, voice, take, takes)
Each line is rendered separately (line id = `id`, default the shot). The cache (build/vo/.cache) keeps the engine's raw take,
float and untrimmed, keyed by what changes the audio, so re-voicing one line of a dialogue only synthesises that line and a
change to the trim never pays for a paid take again. `trim()` runs when vo-<id>.wav is written: near-silence is judged
relative to the line's own peak (a quiet take keeps its soft ending) and both edges get a short fade (no click).

Takes: `takes: N` (vo block or line) makes N takes of each line on an engine that varies (openrouter, voicestudio) and
scores them (promo/vo_score.py); a take that misreads its words or ends mid-sound is rejected. The line uses its `take: k`
(1-based, set with `promo vo takes <id> --pick k` after listening), else the first take that was not rejected. Kokoro and
`say` give the same audio every time, so they refuse takes > 1. Auditions: build/vo/takes/<id>-<k>.wav.

Voices per line (a dialogue): the vo block's engine/voice/speed/lang, then the line's host voice
(`podcast.hosts[].voice: {engine, voice, speed}`, the host matched by id, name or model), then the line's own
`voice:` (a dict, or a bare voice name). Engines:
  kokoro       Apache-2.0 Kokoro-82M (model_asset + voices_asset in assets.yaml). The default; fit to publish.
  say          macOS `say` (voice e.g. "Flo (English (UK))"). Drafts only: needs `asset:` naming an assets.yaml entry
               (Apple's terms: personal, non-commercial); `promo check` WARNs `draft-voice`.
  voicestudio  the local VoiceStudio app (http://127.0.0.1:3900, $PROMO_VOICESTUDIO): `profile` (profile id) or
               `instruct` (voice design), `seed`. Needs `asset:`; its model is CC-BY-NC, an open licence question.
  openrouter   a hosted voice through OpenRouter's speech API (promo/openrouter.py): `model` (default
               google/gemini-3.8-flash-tts; elevenlabs/eleven-v4 for hero lines), `voice` (`promo vo voices --model M`),
               `instructions` (delivery: Gemini, Fish). Needs `asset:` (the provider's terms). Paid: the whole run is priced
               before the first call and refused over `max_usd` (default $0.50) or the daily cap; run it under
               `commissionctl secret exec OPENROUTER_API_KEY -- promo vo`.
  mlx          a free local voice on Apple Silicon (promo/vo_mlx.py): Ming-3.0-tts-0.5B, MIT. `voice` (UK_Charlotte, US_James, ...;
               `promo vo voices --local`) or `instructions` (a voice designed from words), `seed`. One-time `promo vo setup`;
               needs `asset:`.
  clone        the person's own voice (promo/voices.py): Chatterbox, MIT, on this Mac. `voice` is an id from `promo voices`.
               Each line's `emotion` (neutral|excited|calm|warm) is that mood's reference clip; `intensity` 0-1 sets
               exaggeration (~0.25-1.0). Takes keep the Perth watermark (`watermark: perth` in vo.json). Weights download
               only with `promo voices model download --yes`. The licence entry is `vo-<id>` (or an explicit `asset:`).
  files       pre-rendered WAVs (below); the whole vo block only.

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


def rms_db(x, sr, win=0.01):
    """dB of each `win`-second window's RMS relative to the loudest window (empty when x is shorter than one window)."""
    hop = max(1, int(win * sr))
    n = len(x) // hop
    if n == 0:
        return np.zeros(0)
    rms = np.sqrt(np.mean(np.asarray(x[: n * hop], dtype=np.float64).reshape(n, hop) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms / rms.max())


def silences(x, sr, min_len=0.12, win=0.01, db=-40.0):
    """[(start, end)] seconds of runs quieter than `db` (relative to the line's peak window RMS) lasting >= min_len."""
    q = rms_db(x, sr, win)
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
            sf.write(p, x, sr, subtype="FLOAT")
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


ENGINES = ("kokoro", "say", "voicestudio", "openrouter", "mlx", "clone", "files")
DRAFT_ENGINES = ("say",)
VARYING_ENGINES = ("voicestudio", "openrouter", "mlx", "clone")  # a second take sounds different; kokoro and say repeat themselves exactly
SEEDED_ENGINES = ("voicestudio", "mlx")                # take k is seed + k (an OpenRouter call varies by itself; its API takes no seed)
VOICE_KEYS = ("engine", "voice", "speed", "lang", "asset", "profile", "instruct", "seed", "rate", "model", "instructions")
CACHE_VERSION = 2                                    # 2: the cache holds raw float takes (1 held trimmed PCM_16, which clipped)
TRIM_DB = -45.0                                      # a 10 ms window this far under the take's loudest counts as silence
# kept before / after the first / last loud window: 20 ms in keeps a soft onset (a breath, an "h") that sits just under TRIM_DB;
# 100 ms out is the legacy pad (2400 samples at 24 kHz) that podcast layouts were timed with
PAD_IN, PAD_OUT = 0.02, 0.1
FADE_IN, FADE_OUT = 0.005, 0.03


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
    if "asset" not in v and cfg.get("asset") and v["engine"] == cfg.get("engine"):
        v["asset"] = cfg["asset"]                    # the vo block's licence entry covers its own engine, not a host's or line's other engine
    if v["engine"] not in ENGINES or v["engine"] == "files":
        raise RuntimeError(f"VO line {line_id(line)}: engine {v['engine']!r} (have {', '.join(ENGINES[:-1])}; `files` is for the whole vo block)")
    if v["engine"] == "kokoro":
        v.setdefault("voice", "bf_emma")
        v.setdefault("lang", "en-gb" if str(v["voice"]).startswith("b") else "en-us")
    if v["engine"] == "openrouter":
        from .openrouter import DEFAULT_SPEECH_MODEL, DEFAULT_SPEECH_VOICE
        v.setdefault("model", DEFAULT_SPEECH_MODEL)
        if v["model"] == DEFAULT_SPEECH_MODEL:
            v.setdefault("voice", DEFAULT_SPEECH_VOICE)
    if v["engine"] == "mlx" and not v.get("instructions"):
        from .vo_mlx import DEFAULT_VOICE
        v.setdefault("voice", DEFAULT_VOICE)
    if v["engine"] == "clone":
        # emotion / intensity live on the line (and may be inherited from the vo block). Not validated here:
        # a bad value must not raise out of voice_of, or the assets gate would skip the line (it only swallows RuntimeError).
        v["emotion"] = line.get("emotion") if line.get("emotion") not in (None, "") else cfg.get("emotion") or "neutral"
        if line.get("intensity") is not None:
            v["intensity"] = line["intensity"]
        elif cfg.get("intensity") is not None:
            v["intensity"] = cfg["intensity"]
        else:
            v["intensity"] = 0.5
    return v


def voices_used(spec):
    """[(line id, voice dict)] for every synthesised line (empty for the files engine)."""
    cfg = spec.raw.get("vo") or {}
    if not cfg or cfg.get("engine") == "files":
        return []
    return [(line_id(ln), voice_of(spec, ln)) for ln in cfg.get("lines") or []]


def trim(s, sr):
    """A raw take without its leading/trailing near-silence, both edges faded. Silence is judged against the take's own loudest
    window: the old absolute floor (0.01) ate the soft endings of quiet takes, and a cut with no fade clicks."""
    s = np.asarray(s, dtype=np.float32)
    q = rms_db(s, sr)
    loud = np.where(q > TRIM_DB)[0]
    if not len(loud) or not np.any(s):
        return s
    hop = max(1, int(0.01 * sr))
    out = s[max(0, loud[0] * hop - int(PAD_IN * sr)): (loud[-1] + 1) * hop + int(PAD_OUT * sr)].copy()
    ramp = lambda n: (0.5 - 0.5 * np.cos(np.pi * np.arange(n) / n)).astype(np.float32)   # noqa: E731  raised cosine from 0
    n_in, n_out = min(int(FADE_IN * sr), len(out)), min(int(FADE_OUT * sr), len(out))
    out[:n_in] *= ramp(n_in)
    out[len(out) - n_out:] *= ramp(n_out)[::-1]
    return out


_KOKORO = {}


def synth(spec, v, text, man=None, max_usd=None):
    """(mono float32, sr) of one raw take in voice `v` (untrimmed: `trim()` it before use). `max_usd` caps one paid call."""
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
        return np.asarray(s, dtype=np.float32), sr
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
        return s.mean(1), sr
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
        return s.mean(1), sr
    if eng == "openrouter":
        from . import openrouter as OR
        return OR.speech(OR.speech_body(v, text), max_usd=OR.DEFAULT_SPEECH_MAX_USD if max_usd is None else max_usd)
    if eng == "mlx":
        from . import vo_mlx
        vo_mlx.check_voice(v)
        return vo_mlx.synth(v, text)
    if eng == "clone":
        from . import voices as V
        return V.synth_array(v.get("voice"), text, v.get("emotion") or "neutral", v.get("intensity", 0.5))
    raise RuntimeError(f"engine {eng!r}")


def take_key(spec, v, text, take=0):
    """What a take depends on (the cache key): the voice, the text, the take index and, for kokoro, mlx and clone, the model files /
    local install / mood clip. Take 0's key does not depend on how many takes the line asks for, so going from 1 to 3 takes reuses the first."""
    import hashlib
    extra = None
    if v["engine"] == "kokoro":
        from .cache import file_sig
        cfg = spec.raw.get("vo") or {}
        man = load_manifest(spec)
        extra = [file_sig(asset_path(spec, cfg[k], man)) for k in ("model_asset", "voices_asset")]
    if v["engine"] == "mlx":
        from . import vo_mlx
        extra = vo_mlx.signature()
    if v["engine"] == "clone":
        from .cache import file_sig
        from . import voices as V
        emo = str(v.get("emotion") or "neutral")
        mood = os.path.join(V.voice_dir(str(v.get("voice") or "")), "moods", emo + ".wav")
        extra = [file_sig(mood), emo, v.get("intensity")]
    return hashlib.sha256(json.dumps([v, text, extra, CACHE_VERSION, take], sort_keys=True, default=str).encode()).hexdigest()[:20]


def takes_of(cfg, line):
    return int(line.get("takes", cfg.get("takes", 1)))


def take_voice(v, k):
    """The voice of take k: seed + k on a seeded engine, the voice unchanged for take 0 and for OpenRouter."""
    return dict(v, seed=int(v.get("seed", 1)) + k) if k and v["engine"] in SEEDED_ENGINES else v


def _write_wav(path, x, sr):
    """Write a FLOAT WAV, leaving the file (and its mtime, which shot digests follow) alone when it already holds this audio. Samples are
    compared, not bytes: libsndfile stamps the time into a FLOAT WAV's PEAK chunk, so the same audio never writes the same bytes twice."""
    if os.path.exists(path):
        old, osr = sf.read(path, dtype="float32")
        if osr == sr and np.array_equal(old, x):
            return
    sf.write(path + ".tmp.wav", x, sr, subtype="FLOAT")
    os.replace(path + ".tmp.wav", path)


def _plan(spec, cfg):
    """[(line, voice, take keys)] with every line's takes and pick validated before anything is synthesised."""
    out = []
    for line in cfg["lines"]:
        lid, say = line_id(line), line.get("tts", line["text"])
        v = voice_of(spec, line)
        n = takes_of(cfg, line)
        if n < 1:
            raise RuntimeError(f"VO line {lid}: takes must be 1 or more")
        if n > 1 and v["engine"] not in VARYING_ENGINES:
            raise RuntimeError(f"VO line {lid}: {v['engine']} gives the same audio every time; takes: {n} needs engine {', '.join(VARYING_ENGINES)}")
        if line.get("take") is not None and not 1 <= int(line["take"]) <= n:
            raise RuntimeError(f"VO line {lid}: take {line['take']} picked, but the line has {n} take(s)")
        if v["engine"] == "mlx":
            from . import vo_mlx
            vo_mlx.check_voice(v)
            if not vo_mlx.ready():
                raise RuntimeError(f"VO line {lid}: the local voice (engine mlx) is not set up on this Mac: run `promo vo setup` once")
        if v["engine"] == "clone":
            from . import voices as V
            try:
                V.ensure_engine()
                V.require(v.get("voice"))
                v["emotion"] = V.check_emotion(v.get("emotion") or "neutral")
                v["intensity"] = V.check_intensity(0.5 if v.get("intensity") is None else v["intensity"])
            except V.VoicesError as e:
                raise RuntimeError(f"VO line {lid}: {e.code}: {e.message}") from e
        out.append((line, v, [take_key(spec, take_voice(v, k), say, k) for k in range(n)]))
    return out


def paid_todo(plan, cache, force=False):
    """[(voice, text)] of the paid (openrouter) takes this run still has to make: a cached take needs no key and costs nothing."""
    return [(v, line.get("tts", line["text"])) for line, v, keys in plan for key in keys
            if v["engine"] == "openrouter" and (force or not os.path.exists(os.path.join(cache, key + ".wav")))]


def run(spec, force=False, max_usd=None):
    cfg = spec.raw.get("vo")
    if not cfg:
        return None
    os.makedirs(spec.vo_dir, exist_ok=True)
    if cfg.get("engine") == "files":
        return run_files(spec)
    cache = os.path.join(spec.vo_dir, ".cache")
    os.makedirs(cache, exist_ok=True)
    plan = _plan(spec, cfg)
    todo = paid_todo(plan, cache, force)
    n_paid, cap = len(todo), None
    if n_paid:
        from . import openrouter as OR
        if not OR.has_key():
            raise OR.OpenRouterError(OR.NO_SPEECH_KEY)
        price = round(sum(OR.speech_estimate(OR.speech_model(v["model"]), say) for v, say in todo), 4)
        cap = float(max_usd if max_usd is not None else cfg.get("max_usd", OR.DEFAULT_SPEECH_MAX_USD))
        OR.guard(price, cap)
        print(f"vo openrouter: {n_paid} take(s) to make, about ${price:.3f} (limit ${cap:.2f})", flush=True)
    man = None
    meta, keep = [], set()
    for line, v, keys in plan:
        lid, txt = line_id(line), line["text"]
        say = line.get("tts", txt)
        if v["engine"] == "kokoro" and man is None:
            man = load_manifest(spec)
        for k, key in enumerate(keys):
            cp = os.path.join(cache, key + ".wav")
            if force or not os.path.exists(cp):
                s, sr = synth(spec, take_voice(v, k), say, man, max_usd=cap)
                sf.write(cp + ".tmp.wav", s, sr, subtype="FLOAT")
                os.replace(cp + ".tmp.wav", cp)
            keep.add(key)
        takes = None
        if len(keys) > 1:
            from . import vo_score
            os.makedirs(os.path.join(spec.vo_dir, "takes"), exist_ok=True)
            takes = []
            for k, key in enumerate(keys):
                x, sr = sf.read(os.path.join(cache, key + ".wav"), dtype="float32")
                aud = os.path.join("takes", f"{lid}-{k + 1}.wav")
                _write_wav(os.path.join(spec.vo_dir, aud), trim(x, sr), sr)
                takes.append(dict(take=k + 1, file=aud, **vo_score.score(spec, line, os.path.join(spec.vo_dir, aud), os.path.join(cache, key))))
        if line.get("take") is not None:
            pick = int(line["take"])
        else:                                            # the first take that passed; never the "best" score, which drifts to the flattest read
            pick = next((t["take"] for t in takes or [] if not t["rejected"]), 1)
        x, sr = sf.read(os.path.join(cache, keys[pick - 1] + ".wav"), dtype="float32")
        x = trim(x, sr)
        fn = f"vo-{lid}.wav"
        _write_wav(os.path.join(spec.vo_dir, fn), x, sr)
        row = dict(id=lid, shot=str(line["shot"]), host=line.get("host"), text=txt, tts=say, file=fn, dur=round(len(x) / sr, 3),
                   sr=sr, engine=v["engine"], voice=v.get("voice") or v.get("profile") or v.get("instruct") or v.get("instructions"),
                   take=pick, takes=takes)
        if v["engine"] == "clone":
            row["watermark"] = "perth"                 # Chatterbox Perth stays in the samples; never strip it
            row["emotion"] = v.get("emotion")
            row["intensity"] = v.get("intensity")
        meta.append(row)
        print("vo", lid, v["engine"], meta[-1]["voice"], round(meta[-1]["dur"], 2), txt, flush=True)
        if takes:
            print(vo_score.table(takes, pick), flush=True)
    if n_paid:
        from . import openrouter as OR
        settled, pending = OR.settle_costs()
        print(f"vo openrouter: billed cost in for {settled} take(s)" + (f"; {pending} still pending (their estimate counts until a later run)" if pending else ""),
              flush=True)
    old = sorted((os.path.getmtime(os.path.join(cache, f)), f) for f in os.listdir(cache) if f.endswith(".wav") and f[:-4] not in keep)
    for _, f in old[:max(0, len(old) - 200)]:           # keep up to 200 unused takes (an undo re-uses them), oldest go first
        os.remove(os.path.join(cache, f))
        if os.path.exists(os.path.join(cache, f[:-4] + ".score.json")):
            os.remove(os.path.join(cache, f[:-4] + ".score.json"))
    doc = dict(voice=cfg.get("voice"), lang=cfg.get("lang"), speed=cfg.get("speed"), lines=meta)
    if cfg.get("engine") == "clone" or any(x.get("watermark") == "perth" for x in meta):
        doc["watermark"] = "perth"
    with open(vo_json_path(spec), "w") as f:
        json.dump(doc, f, indent=1)
    return meta
