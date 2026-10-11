"""The Stage's Studio tab: Seedance and Grok Imagine takes through OpenRouter, laid out like Higgsfield (prompt, model, length, resolution, aspect, a camera move,
an optional storyboard frame to animate, the price on the button, a gallery of takes).

    promo flow studio run --prompt "..." [--model M --res 480p --seconds 4 --aspect 16:9 --audio --preset push --start STORY/SCENE/start|FILE]
    promo flow studio use --take t3 --asset ID      the take becomes that asset's sample (flow/samples.json)

Takes are planning samples of NON-UI plates (AGENTS.md rule 1): the plate guard leads every prompt, they never enter the footage manifest from
here, and a take reaches a cut only through `promo gen register` like any other generated plate.

    flow/studio/takes.json   [{id, prompt, preset, model, resolution, seconds, aspect, audio, start, status, job_id, estimate, cost, file, error, at, updated, used_for}]
"""
from __future__ import annotations

import datetime
import json
import os
import random

from . import assetplan as AP
from . import genvideo as GV
from . import openrouter as OR
from . import previews as PV

PRESETS = [("static", "Static", "Locked-off camera, no camera movement."),
           ("push", "Push in", "The camera pushes in slowly and steadily toward the centre of the frame."),
           ("pull", "Pull out", "The camera pulls back slowly, revealing more of the scene."),
           ("orbit", "Orbit", "The camera makes a smooth half orbit around the subject."),
           ("pan_left", "Pan left", "The camera pans slowly from right to left."),
           ("pan_right", "Pan right", "The camera pans slowly from left to right."),
           ("crane", "Crane up", "The camera cranes up while tilting down over the scene."),
           ("handheld", "Handheld", "Gentle handheld drift with natural micro-shake.")]
SENTENCE = {k: s for k, _, s in PRESETS}
STOPPED_S = OR.TIMEOUT_S + 120          # a take still "running" this long after its last update lost its process
GROK = "cli:grok"                       # the person's own grok login: video on their subscription, nothing billed per take


class StudioError(Exception):
    """A studio request that cannot run as asked; the message says why."""


def _dir(pd):
    return os.path.join(pd, "flow", "studio")


def _path(pd):
    return os.path.join(_dir(pd), "takes.json")


def load(pd):
    try:
        with open(_path(pd)) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _save(pd, takes):
    os.makedirs(_dir(pd), exist_ok=True)
    tmp = _path(pd) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(takes, f, indent=1)
    os.replace(tmp, _path(pd))


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _update(pd, tid, **kw):
    takes = load(pd)
    for t in takes:
        if t["id"] == tid:
            t.update(kw, updated=_now())
    _save(pd, takes)


def prompt_text(prompt, preset):
    if preset and preset not in SENTENCE:
        raise StudioError(f"no camera move {preset!r}; one of {', '.join(SENTENCE)}")
    return (prompt.strip() + (" " + SENTENCE[preset] if preset else "")).strip()


def run(pd, prompt, model=OR.DEFAULT_MODEL, resolution=OR.DEFAULT_RES, seconds=OR.DEFAULT_SECONDS, aspect="16:9", audio=False, preset=None,
        start=None, start_ref=None, max_usd=OR.DEFAULT_MAX_USD, seed=None, on_change=None):
    """Make one take. The take is in takes.json from the first moment (queued, then OpenRouter's statuses, then done or failed with the reason),
    and `on_change()` runs after every change so the Stage can follow it. `start` is the frame's file, `start_ref` what the person picked
    (a storyboard frame id), kept so "same settings" can pick it again. Every take has a seed: a final at a higher resolution reuses the
    draft's seed and prompt, the cheap-draft-then-final habit of Higgsfield-style studios (docs/reference-higgsfield-studio.md)."""
    if not prompt.strip():
        raise StudioError("a take needs a prompt")
    text = prompt_text(prompt, preset)
    if start and not os.path.isfile(start):
        raise StudioError(f"start frame not found: {start_ref or start}")
    takes = load(pd)
    tid = f"t{max((int(t['id'][1:]) for t in takes), default=0) + 1}"
    seed = random.randrange(2 ** 31) if seed is None else seed
    rel = os.path.join("flow", "studio", tid + ".mp4")
    now = _now()
    takes.append(dict(id=tid, prompt=prompt.strip(), preset=preset, model=model, resolution=resolution, seconds=seconds, aspect=aspect, audio=bool(audio), seed=seed,
                      start=os.path.relpath(start, pd) if start else None, start_ref=start_ref, status="queued", job_id=None, estimate=None, cost=None,
                      file=None, error=None, at=now, updated=now, used_for=[]))
    _save(pd, takes)
    ping = on_change or (lambda: None)
    ping()

    def status(s, jid):
        _update(pd, tid, status="generating" if s in ("pending", "in_progress") else s, job_id=jid)
        ping()
    if model == GROK:
        return _run_grok(pd, tid, rel, prompt_text(prompt, preset), seconds, aspect, resolution, start, ping)
    try:
        meta = GV.generate_openrouter(prompt_text(prompt, preset), os.path.join(pd, rel), seconds, aspect, model=model, resolution=resolution,
                                      first_frame=start, audio=audio, max_usd=max_usd, on_status=status, seed=seed)
    except OR.OpenRouterError as e:
        _update(pd, tid, status="failed", error=str(e))
        ping()
        raise
    _update(pd, tid, status="done", file=rel, cost=meta["cost_usd"], estimate=meta["estimate_usd"], job_id=meta["job_id"])
    ping()
    return next(t for t in load(pd) if t["id"] == tid)


def _run_grok(pd, tid, rel, text, seconds, aspect, resolution, start, ping):
    _update(pd, tid, status="generating", estimate=0, cost=0)
    ping()
    try:
        GV.generate("video", text, os.path.join(pd, rel), seconds, aspect, provider="grok", first_frame=start, resolution=resolution)
    except (RuntimeError, SystemExit, OSError) as e:          # SystemExit: grok is not logged in here (`promo gen detect`)
        _update(pd, tid, status="failed", error=f"grok made no video: {str(e)[:300]}")
        ping()
        raise StudioError(f"grok made no video: {str(e)[:300]}") from None
    _update(pd, tid, status="done", file=rel)
    ping()
    return next(t for t in load(pd) if t["id"] == tid)


def _subscriptions():
    """Video generators on the person's own logins, as Studio models. Only grok: the codex CLI has an image tool and no video tool."""
    if not next(p for p in GV.detect() if p["id"] == "grok")["available"]:
        return []
    aspects, res = ["16:9", "9:16", "1:1", "3:2", "2:3"], ["480p", "720p"]
    return [dict(id=GROK, name="Grok (your subscription)", seconds=[1, 15], resolutions=res, aspects=aspects, first_frame=True, audio=False,
                 price_4s={r: 0 for r in res}, image_input=0, per_second={f"{r}|{a}|0": 0 for r in res for a in aspects}, subscription=True)]


def use(pd, tid, asset_id):
    """Record a finished take as the sample of a generated video asset; the asset itself (and its state) is untouched."""
    take = next((t for t in load(pd) if t["id"] == tid), None)
    if not take or take["status"] != "done":
        raise StudioError(f"take {tid} is not a finished take")
    flow_dir = os.path.join(pd, "flow")
    a = next((x for x in AP.load(flow_dir) if x["id"] == asset_id), None)
    if not a:
        raise StudioError(f"no asset {asset_id} in the plan")
    if a["kind"] != "video" or a["source"] != "generated":
        raise StudioError(f"asset {asset_id} is a {a['source']} {a['kind']}; a Studio take can only stand in for a generated video plate")
    samples = PV.load_samples(flow_dir)
    cost = f"${take['cost']:.2f}" if take.get("cost") is not None else "cost not reported"
    samples[asset_id] = dict(path=take["file"], at=_now(), take=tid,
                             note=f"Studio take {tid} ({take['model'].split('/')[-1]}, {take['resolution']}, {take['seconds']} s, {cost})")
    with open(PV.samples_path(flow_dir), "w") as f:
        json.dump(samples, f, indent=2)
    _update(pd, tid, used_for=sorted(set(take["used_for"]) | {asset_id}))
    return samples[asset_id]


def _per_second(m):
    """{"480p|16:9|0": USD per second} for every resolution / aspect / audio choice the model has, so the Stage prices any take exactly."""
    out = {}
    for r in m["supported_resolutions"]:
        for a in m["supported_aspect_ratios"]:
            for audio in (False, True) if m.get("generate_audio") else (False,):
                try:
                    out[f"{r}|{a}|{int(audio)}"] = OR.estimate(m, 1000, r, a, audio) / 1000
                except OR.OpenRouterError:
                    continue                # a shape the model does not render at this resolution: the Stage does not offer it
    return out


def view(pd, media, frames, now=None):
    """The `studio` block of the Stage state: the composer's choices, the takes (newest first) and the spend so far."""
    now = now or datetime.datetime.now().astimezone()
    try:
        cat, models_error = OR.models(max_age=None), None           # prices barely move; publishing must not wait on the network
    except OR.OpenRouterError as e:
        cat, models_error = [], str(e)
    per_s = {m["id"]: _per_second(m) for m in cat}
    subs = _subscriptions()
    models = subs + [dict(r, per_second=per_s[r["id"]]) for r in OR.price_table(cat)]
    labels = {f["id"]: f["label"] for f in frames}
    takes = []
    for t in reversed(load(pd)):
        t = dict(t)
        idle = (now - datetime.datetime.fromisoformat(t["updated"])).total_seconds()
        if t["status"] not in ("done", "failed") and idle > STOPPED_S:
            t["status"], t["error"] = "stopped", "The run that made this take stopped before the clip came back."
        t["video"] = media(os.path.join(pd, t["file"])) if t.get("file") else None
        t["start_label"] = labels.get(t["start_ref"], os.path.basename(t["start"])) if t.get("start") else None
        takes.append(t)
    plates = [dict(id=a["id"], label=a.get("label") or a["id"]) for a in AP.load(os.path.join(pd, "flow")) if a["kind"] == "video" and a["source"] == "generated"]
    sp = OR.spend()
    return dict(models=models, models_error=models_error, default_model=GROK if subs else OR.DEFAULT_MODEL, guard=GV.NEG, presets=[dict(id=k, label=lb, sentence=s) for k, lb, s in PRESETS],
                max_usd=OR.DEFAULT_MAX_USD, account="ready" if "video" in next(p for p in GV.detect() if p["id"] == "openrouter")["verified"] else "unchecked",
                spend=dict(today=sp["today"], total=sp["total"], cap=OR.daily_cap()), takes=takes, frames=frames, plates=plates)
