"""Seedance and Grok Imagine video through OpenRouter, for NON-UI plates (AGENTS.md rule 1 carve-out): the catalogue, a price before every job, the job, a spend ledger.

    promo gen models [--json]                        the video models with what 4 s at 480p / 720p costs (catalogue is public, no key needed)
    promo gen video "prompt" --out F --provider openrouter [--model M --res 480p --seconds 4 --first-frame IMG --audio --max-usd 0.40 --dry-run]
    promo gen spend [--json]                          today's and all-time spend from the ledger

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
FAMILIES = ("bytedance/seedance", "x-ai/grok-imagine-video")
DEFAULT_MODEL = "bytedance/seedance-1-5-pro"     # the cheapest 4 s clip on OpenRouter: drafts first, a dearer model once the idea works
TEST_MODEL = "x-ai/grok-imagine-video-1.5-lite"  # 2 cents a second at 480p from 1 s: the cheapest way to prove the pipeline end to end
DEFAULT_RES = "480p"
DEFAULT_SECONDS = 4
DEFAULT_MAX_USD = 0.40
DEFAULT_DAILY_USD = 2.0
FPS = 24                       # Seedance renders 24 fps; OpenRouter bills it in video tokens of w*h*fps*s/1024
POLL_S = 5
TIMEOUT_S = 900
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


def _request(method, path, body=None, auth=True, raw=False, timeout=60):
    headers = {"Content-Type": "application/json", "X-Title": "promo-reel"}
    if auth:
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise OpenRouterError("no OpenRouter key: run under `commissionctl secret exec OPENROUTER_API_KEY -- ...`")
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(API + path, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
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


def models(max_age=CACHE_S):
    """Seedance and Grok Imagine rows of OpenRouter's public video catalogue, fetched again when the cached copy is older than `max_age` seconds (None: any age)."""
    cache = _tools_dir() / "openrouter-models.json"
    if cache.exists() and (max_age is None or time.time() - cache.stat().st_mtime < max_age):
        rows = json.loads(cache.read_text())
    else:
        rows = _request("GET", "/videos/models", auth=False)["data"]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows))
    return [m for m in rows if m["id"].startswith(FAMILIES)]


def model(mid, catalogue=None):
    for m in catalogue if catalogue is not None else models():
        if m["id"] == mid:
            return m
    raise OpenRouterError(f"{mid} is not one of the video models promo-reel prices (Seedance, Grok Imagine); see `promo gen models`")


def size_for(m, resolution, aspect):
    """(w, h) the model renders for this resolution and aspect: its sizes of that shape, smallest first, line up with its resolutions."""
    a, b = (int(x) for x in aspect.split(":"))
    shape = sorted((tuple(int(v) for v in s.split("x")) for s in m["supported_sizes"]), key=lambda wh: wh[0] * wh[1])
    shape = [wh for wh in shape if abs(wh[0] / wh[1] - a / b) <= 0.03 * a / b]
    if resolution not in m["supported_resolutions"] or len(shape) <= m["supported_resolutions"].index(resolution):
        raise OpenRouterError(f"{m['id']} has no {aspect} picture at {resolution}")
    return shape[m["supported_resolutions"].index(resolution)]


def estimate(m, seconds, resolution, aspect, audio=False, first_frame=False):
    """USD before the job, from the catalogue: Grok Imagine bills cents per output second (plus a fee for an input image), Seedance per
    video token. OpenRouter bills the real figure; the ledger keeps both."""
    sku = m["pricing_skus"]
    per_s = sku.get(f"cents_per_video_output_second_{resolution}")
    if per_s is not None:
        return round((float(per_s) * seconds + (float(sku.get("cents_per_image_input", 0)) if first_frame else 0)) / 100, 4)
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


def body_for(m, prompt, seconds, resolution, aspect, first_frame=None, audio=False, seed=None):
    """The job request; sound and seed are sent only to models that take them (Grok Imagine takes neither)."""
    body = dict(model=m["id"], prompt=prompt, duration=int(seconds), resolution=resolution, aspect_ratio=aspect)
    if m.get("generate_audio"):
        body["generate_audio"] = bool(audio)
    if seed is not None and m.get("seed"):
        body["seed"] = int(seed)
    if first_frame:
        body["frame_images"] = [dict(type="image_url", image_url=dict(url=_data_url(first_frame)), frame_type="first_frame")]
    return body


def run(mid, prompt, out, seconds=DEFAULT_SECONDS, resolution=DEFAULT_RES, aspect="16:9", first_frame=None, audio=False, seed=None,
        max_usd=DEFAULT_MAX_USD, on_status=None, timeout=TIMEOUT_S):
    """Price, guard, submit, poll, download to `out`. Returns {job_id, model, cost, estimate, ...}. `on_status(status, job_id)` is told
    'queued' once submitted and each new status after."""
    m = model(mid)
    check_params(m, seconds, resolution, aspect)
    price = estimate(m, seconds, resolution, aspect, audio, bool(first_frame))
    guard(price, max_usd)
    job = _request("POST", "/videos", body_for(m, prompt, seconds, resolution, aspect, first_frame, audio, seed))
    jid = job["id"]
    row = dict(at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"), job_id=jid, model=mid, resolution=resolution, seconds=seconds,
               aspect=aspect, audio=bool(audio), first_frame=bool(first_frame), estimate=price, cost=None, status="queued", out=str(out))
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
    return done


def price_table(catalogue=None):
    """One row per video model: durations, resolutions, what 4 s costs at each resolution (16:9, no audio) and the fee for a start image,
    cheapest first."""
    rows = []
    for m in catalogue if catalogue is not None else models():
        prices = {}
        for r in m["supported_resolutions"]:
            try:
                prices[r] = estimate(m, DEFAULT_SECONDS, r, "16:9")
            except OpenRouterError:
                continue
        rows.append(dict(id=m["id"], name=m["name"].split(": ", 1)[-1], seconds=[min(m["supported_durations"]), max(m["supported_durations"])],
                         resolutions=m["supported_resolutions"], aspects=m["supported_aspect_ratios"], first_frame="first_frame" in m.get("supported_frame_images", []),
                         audio=bool(m.get("generate_audio")), price_4s=prices,
                         image_input=float(m["pricing_skus"].get("cents_per_image_input", 0)) / 100))
    return sorted(rows, key=lambda r: r["price_4s"].get(DEFAULT_RES, 9e9))
