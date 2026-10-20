"""Seedance and Grok Imagine video through OpenRouter, for NON-UI plates (AGENTS.md rule 1 carve-out): the catalogue, a price before every job, the job, a spend ledger.
Also hosted voices for VO lines (`speech()`, the `openrouter` engine of promo/vo.py; `promo vo voices` lists them), on the same key, caps and ledger.

    promo gen models [--json]                        the video models with what 4 s at 480p / 720p costs (catalogue is public, no key needed)
    promo gen video "prompt" --out F --provider openrouter [--model M --res 480p --seconds 4 --first-frame IMG --audio --max-usd 0.50 --dry-run]
    promo gen spend [--json]                          today's and all-time spend from the ledger

Edit models (FLUX Video Edit) take a source clip instead of a first frame (`input_references` of type `video_url`), for restyling a
generated take; promo/studio.py refuses anything that is not a generated plate (rules 1 and 2).

The key comes only from OPENROUTER_API_KEY; run under `commissionctl secret exec OPENROUTER_API_KEY -- promo ...` so it is never seen, logged or
written. Every job is priced from the catalogue first and refused when it costs more than `max_usd` or would take today's spend over the daily
cap (PROMO_GEN_DAILY_USD, default $2). The ledger (~/.promo-tools/openrouter-spend.jsonl) keeps the estimate and OpenRouter's real
`usage.cost` of every job side by side.
"""
from __future__ import annotations

import base64
import datetime
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://openrouter.ai/api/v1"
FAMILIES = ("bytedance/seedance", "x-ai/grok-imagine-video", "black-forest-labs/flux-video-edit")
EDIT_MODELS = ("black-forest-labs/flux-video-edit",)   # video in, video out: restyle a take; priced per output second
DEFAULT_MODEL = "bytedance/seedance-2.5"         # the newest Seedance (~$0.41 for 4 s at 480p); 1.5 Pro (~$0.05) stays in the list for cheap drafts
TEST_MODEL = "x-ai/grok-imagine-video-1.5-lite"  # 2 cents a second at 480p from 1 s: the cheapest way to prove the pipeline end to end
DEFAULT_RES = "480p"
DEFAULT_SECONDS = 4
DEFAULT_MAX_USD = 0.50           # one 4 s 480p take of the default model fits; anything dearer needs --max-usd
DEFAULT_DAILY_USD = 2.0
FPS = 24                       # Seedance renders 24 fps; OpenRouter bills it in video tokens of w*h*fps*s/1024
POLL_S = 5
TIMEOUT_S = 900
EDIT_MAX_MB = 20               # a source clip travels as a data URL inside the JSON body; a 4-10 s Studio take is 1-10 MB
CACHE_S = 24 * 3600
HOME = Path.home()


class OpenRouterError(RuntimeError):
    """A job could not run or failed; the message is safe to show (OpenRouter's own words, never the key)."""


def _tools_dir():
    return HOME / ".promo-tools"


def ledger_path():
    return _tools_dir() / "openrouter-spend.jsonl"


def has_key():
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def _request(method, path, body=None, auth=True, raw=False, timeout=60, headers_out=None):
    """One API call; JSON back, or the raw bytes with `raw`. `headers_out` (a dict) is filled with the response headers."""
    headers = {"Content-Type": "application/json", "X-Title": "promo-reel"}
    if auth:
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise OpenRouterError("no OpenRouter key: run under `commissionctl secret exec OPENROUTER_API_KEY -- ...` (a missing key opens the secure box for the person; or `commissionctl secret request OPENROUTER_API_KEY --reason ...`)")
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(API + path, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if headers_out is not None:
                headers_out.update({k.lower(): v for k, v in r.headers.items()})
    except urllib.error.HTTPError as e:
        raise OpenRouterError(f"OpenRouter said {e.code}: {_message(e.read())}") from None
    except urllib.error.URLError as e:
        raise OpenRouterError(f"could not reach OpenRouter: {e.reason}") from None
    return data if raw else json.loads(data)


def _message(body):
    try:
        err = json.loads(body).get("error")
    except ValueError:
        return body[:200].decode(errors="replace").strip() or "no details"
    return (err.get("message") if isinstance(err, dict) else str(err or "")) or "no details"


def _catalogue(name, path, max_age):
    """Rows of a public OpenRouter catalogue, kept in ~/.promo-tools/<name> and fetched again when older than `max_age` seconds (None: any age)."""
    cache = _tools_dir() / name
    if cache.exists() and (max_age is None or time.time() - cache.stat().st_mtime < max_age):
        return json.loads(cache.read_text())
    rows = _request("GET", path, auth=False)["data"]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    return rows


def models(max_age=CACHE_S):
    """Seedance and Grok Imagine rows of OpenRouter's public video catalogue."""
    return [m for m in _catalogue("openrouter-models.json", "/videos/models", max_age) if m["id"].startswith(FAMILIES)]


def model(mid, catalogue=None):
    for m in catalogue if catalogue is not None else models():
        if m["id"] == mid:
            return m
    raise OpenRouterError(f"{mid} is not one of the video models promo-reel prices (Seedance, Grok Imagine, FLUX Video Edit); see `promo gen models`")


def is_edit(m):
    return m["id"] in EDIT_MODELS


def size_for(m, resolution, aspect):
    """(w, h) the model renders for this resolution and aspect: its sizes of that shape, smallest first, line up with its resolutions."""
    a, b = (int(x) for x in aspect.split(":"))
    shape = sorted((tuple(int(v) for v in s.split("x")) for s in m["supported_sizes"]), key=lambda wh: wh[0] * wh[1])
    shape = [wh for wh in shape if abs(wh[0] / wh[1] - a / b) <= 0.03 * a / b]
    if resolution not in m["supported_resolutions"] or len(shape) <= m["supported_resolutions"].index(resolution):
        raise OpenRouterError(f"{m['id']} has no {aspect} picture at {resolution}")
    return shape[m["supported_resolutions"].index(resolution)]


def estimate(m, seconds, resolution, aspect, audio=False, first_frame=False, video_input=False):
    """USD before the job, from the catalogue: Grok Imagine bills cents per output second (plus a fee per input image; `first_frame` is
    a flag or the number of frame images), FLUX Video Edit cents per output second whatever the size, Seedance per video token
    (`video_tokens_with_video_input` when a clip is sent as a reference). OpenRouter bills the real figure; the ledger keeps both."""
    sku = m["pricing_skus"]
    flat = sku.get("cents_per_second_output")
    if flat is not None:
        return round(max(float(flat) * seconds, float(sku.get("minimum_cents_per_generation", 0))) / 100, 4)
    per_s = sku.get(f"cents_per_video_output_second_{resolution}")
    if per_s is not None:
        return round((float(per_s) * seconds + float(sku.get("cents_per_image_input", 0)) * int(first_frame)) / 100, 4)
    price = None
    if video_input:
        price = sku.get({"1080p": "video_tokens_1080p_with_video_input", "4K": "video_tokens_4k_with_video_input"}.get(resolution, ""))
        price = price or sku.get("video_tokens_with_video_input")
    if price is None:
        price = sku.get({"1080p": "video_tokens_1080p", "4K": "video_tokens_4k"}.get(resolution, ""))
        if price is None:
            price = sku.get("video_tokens") if audio else sku.get("video_tokens_without_audio", sku.get("video_tokens"))
    if price is None:
        raise OpenRouterError(f"no price for {m['id']} at {resolution} in the catalogue")
    w, h = size_for(m, resolution, aspect)
    return round(w * h * FPS * seconds / 1024 * float(price), 4)


def check_params(m, seconds, resolution, aspect):
    if seconds not in m["supported_durations"]:
        raise OpenRouterError(f"{m['id']} makes {min(m['supported_durations'])}-{max(m['supported_durations'])} s clips, not {seconds:g} s")
    if aspect not in m["supported_aspect_ratios"]:
        raise OpenRouterError(f"{m['id']} has no {aspect} aspect")
    if resolution not in m["supported_resolutions"]:
        raise OpenRouterError(f"{m['id']} has no {resolution}")


def _ledger():
    p = ledger_path()
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def spend(today=None):
    """{today, total, jobs}: each job counts its real cost once OpenRouter reported it, its estimate until then (a job still running counts)."""
    today = today or datetime.date.today().isoformat()
    jobs = {}
    for row in _ledger():
        jobs.setdefault(row["job_id"], {}).update(row)
    cost = lambda j: j["cost"] if j.get("cost") is not None else (0 if j.get("status") == "failed" else j["estimate"])  # noqa: E731
    return dict(today=round(sum(cost(j) for j in jobs.values() if j["at"].startswith(today)), 4), total=round(sum(cost(j) for j in jobs.values()), 4),
                jobs=list(jobs.values()))


def daily_cap():
    return float(os.environ.get("PROMO_GEN_DAILY_USD") or DEFAULT_DAILY_USD)


def guard(price, max_usd):
    if price > max_usd:
        raise OpenRouterError(f"this job is about ${price:.2f}, over the ${max_usd:.2f} limit for one job; pass a higher --max-usd to allow it")
    used, cap = spend()["today"], daily_cap()
    if used + price > cap:
        raise OpenRouterError(f"today's OpenRouter spend is ${used:.2f}; this job (~${price:.2f}) would pass the ${cap:.2f} daily cap "
                              "(raise it with PROMO_GEN_DAILY_USD)")


def _log(row):
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row) + "\n")


def _data_url(path):
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


FILE = "file://"               # a stored request names its pictures and clips by path; the bytes are read again when it is resent


def _video_ref(source):
    mb = Path(source).stat().st_size / 1e6
    if mb > EDIT_MAX_MB:
        raise OpenRouterError(f"the source clip is {mb:.0f} MB; video references go up to {EDIT_MAX_MB} MB (trim or use a smaller take)")
    return dict(type="video_url", video_url=dict(url=FILE + str(Path(source).resolve())))


def body_for(m, prompt, seconds, resolution, aspect, first_frame=None, audio=False, seed=None, last_frame=None, video=None):
    """The job request as it is kept (pictures and clips named by `file://` path; `wire()` reads them in when it is sent). Sound and seed go
    only to models that take them (Grok Imagine takes neither), a last frame only to models that list one. `video` is a motion/edit
    reference (Seedance 2.x `input_references`)."""
    body = dict(model=m["id"], prompt=prompt, duration=int(seconds), resolution=resolution, aspect_ratio=aspect)
    if m.get("generate_audio"):
        body["generate_audio"] = bool(audio)
    if seed is not None and m.get("seed"):
        body["seed"] = int(seed)
    frames = [(first_frame, "first_frame"), (last_frame, "last_frame")]
    for path, kind in frames:
        if path and kind not in (m.get("supported_frame_images") or []):
            raise OpenRouterError(f"{m['id']} takes no {kind.replace('_', ' ')}")
    if first_frame or last_frame:
        body["frame_images"] = [dict(type="image_url", image_url=dict(url=FILE + str(Path(p).resolve())), frame_type=k) for p, k in frames if p]
    if video:
        body["input_references"] = [_video_ref(video)]
    return body


def edit_body(m, prompt, source, seed=None):
    """An edit job: the prompt says what changes, the source clip is the picture (FLUX Video Edit: model, prompt, input_references)."""
    body = dict(model=m["id"], prompt=prompt, input_references=[_video_ref(source)])
    if seed is not None and m.get("seed"):
        body["seed"] = int(seed)
    return body


def wire(body):
    """The body as sent: every `file://` reference becomes a data URL of that file."""
    out = dict(body)
    for key in ("frame_images", "input_references"):
        if key in out:
            out[key] = [_wired(e) for e in out[key]]
    return out


def _wired(entry):
    kind = entry["type"]                    # image_url | video_url
    url = entry[kind]["url"]
    if not url.startswith(FILE):
        return entry
    path = url[len(FILE):]
    if not os.path.isfile(path):
        raise OpenRouterError(f"the request names {path}, which is gone; pick the frame or take again")
    return dict(entry, **{kind: dict(entry[kind], url=_data_url(path))})


def price_of(m, body, seconds=None):
    """USD for a stored request; `seconds` is the source clip's length for an edit job (it has no duration of its own)."""
    if is_edit(m):
        return estimate(m, seconds, None, None)
    video_in = any(e.get("type") == "video_url" for e in body.get("input_references") or [])
    return estimate(m, body["duration"], body["resolution"], body["aspect_ratio"], body.get("generate_audio", False),
                    len(body.get("frame_images") or []), video_in)


def run(mid, prompt, out, seconds=DEFAULT_SECONDS, resolution=DEFAULT_RES, aspect="16:9", first_frame=None, audio=False, seed=None,
        max_usd=DEFAULT_MAX_USD, on_status=None, timeout=TIMEOUT_S, last_frame=None):
    """Price, guard, submit, poll, download to `out`. Returns {job_id, model, cost, estimate, request, ...}: `request` is the body exactly
    as sent with its pictures named by path, so `send(request)` makes the same job again. `on_status(status, job_id)` is told 'queued'
    once submitted and each new status after."""
    m = model(mid)
    if is_edit(m):
        raise OpenRouterError(f"{m['name']} edits a clip; restyle a take instead (promo flow studio restyle)")
    check_params(m, seconds, resolution, aspect)
    return send(body_for(m, prompt, seconds, resolution, aspect, first_frame, audio, seed, last_frame), out, max_usd, on_status, timeout)


def send(body, out, max_usd=DEFAULT_MAX_USD, on_status=None, timeout=TIMEOUT_S, seconds=None):
    """Price, guard, submit and follow one stored request (from `body_for`, `edit_body` or an earlier take's `request`)."""
    m = model(body["model"])
    price = price_of(m, body, seconds)
    guard(price, max_usd)
    job = _request("POST", "/videos", wire(body))
    jid = job["id"]
    mid = m["id"]
    row = dict(at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"), job_id=jid, model=mid, resolution=body.get("resolution"),
               seconds=body.get("duration", seconds), aspect=body.get("aspect_ratio"), audio=bool(body.get("generate_audio")),
               first_frame=bool(body.get("frame_images")), estimate=price, cost=None, status="queued", out=str(out))
    _log(row)
    if on_status:
        on_status("queued", jid)
    last, t0 = "queued", time.monotonic()
    while True:
        job = _request("GET", f"/videos/{jid}")
        status = job.get("status", "pending")
        if status != last and on_status:
            on_status(status, jid)
        last = status
        if status in ("completed", "failed", "cancelled", "expired"):
            break
        if time.monotonic() - t0 > timeout:
            _log(dict(row, status="timeout"))
            raise OpenRouterError(f"job {jid} still {status} after {timeout // 60} min; it may still finish on OpenRouter (and be billed)")
        time.sleep(POLL_S)
    cost = (job.get("usage") or {}).get("cost")
    if status != "completed":
        _log(dict(row, status="failed", cost=cost))
        raise OpenRouterError(f"{m['name']} job {status}: {job.get('error') or 'no reason given'}")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(_request("GET", f"/videos/{jid}/content?index=0", raw=True, timeout=300))
    done = dict(row, status="completed", cost=cost)
    _log(done)
    return dict(done, request=body)


def price_table(catalogue=None):
    """One row per video model: durations, resolutions, what 4 s costs at each resolution (16:9, no audio) and the fee for a start image,
    cheapest first."""
    rows = []
    for m in catalogue if catalogue is not None else models():
        if is_edit(m):
            continue
        prices = {}
        for r in m["supported_resolutions"]:
            try:
                prices[r] = estimate(m, DEFAULT_SECONDS, r, "16:9")
            except OpenRouterError:
                continue
        rows.append(dict(id=m["id"], name=m["name"].split(": ", 1)[-1], seconds=[min(m["supported_durations"]), max(m["supported_durations"])],
                         resolutions=m["supported_resolutions"], aspects=m["supported_aspect_ratios"], first_frame="first_frame" in (m.get("supported_frame_images") or []),
                         last_frame="last_frame" in (m.get("supported_frame_images") or []),
                         audio=bool(m.get("generate_audio")), price_4s=prices,
                         image_input=float(m["pricing_skus"].get("cents_per_image_input", 0)) / 100))
    return sorted(rows, key=lambda r: r["price_4s"].get(DEFAULT_RES, 9e9))


# ---------------------------------------------------------------- speech: VO lines (promo/vo.py engine `openrouter`)
DEFAULT_SPEECH_MODEL = "google/gemini-3.8-flash-tts"   # #3 on the Speech Arena (Oct 2026) and the cheapest of the top five
DEFAULT_SPEECH_VOICE = "Kore"
DEFAULT_SPEECH_MAX_USD = 0.50
AUDIO_TOKENS_PER_S = 25        # Gemini bills speech per output token, 25 of them per second of audio
NO_SPEECH_KEY = ("hosted voices need the board's OpenRouter key: run under `commissionctl secret exec OPENROUTER_API_KEY -- promo vo` (a "
                 "missing key opens the secure box for the person). No key? The free local voice: `engine: mlx` after `promo vo setup`")
CHARS_PER_S = 10              # slower than real speech (a 21-character Gemini line ran 2.1 s), so a line not yet made is priced high, not low


def speech_models(max_age=CACHE_S):
    """OpenRouter's public speech catalogue (id, pricing, supported_voices, ...)."""
    return _catalogue("openrouter-speech-models.json", "/models?output_modalities=speech", max_age)


def speech_model(mid, catalogue=None):
    rows = catalogue if catalogue is not None else speech_models()
    for m in rows:
        if m["id"] == mid:
            return m
    raise OpenRouterError(f"{mid} is not an OpenRouter speech model; see `promo vo voices` (e.g. {', '.join(sorted(r['id'] for r in rows)[:6])})")


def speech_estimate(m, text):
    """USD for one take before it is made. Most voices bill per input character (`pricing.prompt`); Gemini adds output audio tokens
    and completion-only models (Seed Audio) bill per second (`pricing.completion`), so the seconds are guessed from the text."""
    p = m.get("pricing") or {}
    if p.get("prompt") is None and p.get("completion") is None:
        raise OpenRouterError(f"no price for {m['id']} in the catalogue")
    prompt, comp = float(p.get("prompt") or 0), float(p.get("completion") or 0)
    per_s = comp if prompt == 0 else comp * AUDIO_TOKENS_PER_S
    return round(len(text) * prompt + len(text) / CHARS_PER_S * per_s, 5)


def speech_body(v, text):
    """The /audio/speech request for one VO line in voice `v` (engine openrouter: model, voice, instructions, speed)."""
    body = dict(model=v["model"], input=text)
    for k in ("voice", "instructions"):
        if v.get(k):
            body[k] = str(v[k])
    if v.get("speed") is not None:
        body["speed"] = float(v["speed"])
    return body


SETTLE_S = 60                  # a speech generation's billing record was still missing 10 s after its audio in real runs


def settle_costs(timeout=SETTLE_S):
    """Fill in OpenRouter's billed cost of every speech take whose ledger row still has none (one appended row per take; spend() keeps
    the latest). Returns (settled, still pending). A record not there yet answers 404, so lookups repeat until `timeout`; whatever is
    still pending keeps counting its estimate and is settled by a later run."""
    last = {}
    for row in _ledger():
        last[row["job_id"]] = row
    pending = {j: r for j, r in last.items() if r.get("kind") == "speech" and r.get("cost") is None and j.startswith("gen-")}
    settled, t0 = 0, time.monotonic()
    while pending:
        for gid, row in list(pending.items()):
            try:
                cost = float(_request("GET", f"/generation?id={gid}")["data"]["total_cost"])
            except OpenRouterError:
                continue
            _log(dict(row, cost=cost))
            settled += 1
            del pending[gid]
        if not pending or time.monotonic() - t0 > timeout:
            break
        time.sleep(POLL_S)
    return settled, len(pending)


def speech(body, max_usd=DEFAULT_SPEECH_MAX_USD):
    """Price, guard and make one take: (mono float32 samples, sample rate). Every call gets a ledger row with its estimate; its billed
    cost follows from settle_costs()."""
    import io
    import uuid

    import numpy as np
    import soundfile as sf
    if not has_key():
        raise OpenRouterError(NO_SPEECH_KEY)
    m = speech_model(body["model"])
    voices = m.get("supported_voices") or []
    if voices and body.get("voice") not in voices:
        raise OpenRouterError(f"{m['id']} has no voice {body.get('voice')!r}; it has {', '.join(voices[:10])}{' ...' if len(voices) > 10 else ''} "
                              f"(`promo vo voices --model {m['id']}`)")
    price = speech_estimate(m, body["input"])
    guard(price, max_usd)
    hdr = {}
    # pcm, not mp3: lossless, and Gemini sends nothing else. The rate rides on the Content-Type (audio/pcm;rate=24000;channels=1).
    data = _request("POST", "/audio/speech", dict(body, response_format="pcm"), raw=True, timeout=300, headers_out=hdr)
    gid = hdr.get("x-generation-id")
    _log(dict(at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"), job_id=gid or f"speech-{uuid.uuid4().hex[:12]}", kind="speech",
              model=m["id"], chars=len(body["input"]), estimate=price, cost=None, status="completed"))
    if data[:4] == b"RIFF":
        x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        return x.mean(1), sr
    params = dict(p.strip().split("=", 1) for p in hdr.get("content-type", "").split(";")[1:] if "=" in p)
    if "rate" not in params:
        raise OpenRouterError(f"{m['id']} sent raw audio without its sample rate (Content-Type {hdr.get('content-type')!r}); try another model")
    ch = int(params.get("channels", 1))
    x = np.frombuffer(data[: len(data) // (2 * ch) * 2 * ch], "<i2").astype(np.float32) / 32768.0
    return x.reshape(-1, ch).mean(1), int(params["rate"])


def speech_table(catalogue=None):
    """One row per speech model: what 1,000 characters cost (Gemini's audio tokens guessed from the text) and its voices, cheapest first."""
    rows = []
    for m in catalogue if catalogue is not None else speech_models():
        try:
            usd = speech_estimate(m, "x" * 1000)
        except OpenRouterError:
            continue
        rows.append(dict(id=m["id"], name=m.get("name", m["id"]), usd_per_1k_chars=usd, voices=m.get("supported_voices") or []))
    return sorted(rows, key=lambda r: r["usd_per_1k_chars"])
