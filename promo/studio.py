"""The Stage's Studio tab: Seedance and Grok Imagine takes through OpenRouter, laid out like Higgsfield (prompt, model, length, resolution, aspect, a camera move,
an optional storyboard frame to animate, the price on the button, a gallery of takes).

    promo flow studio run --model local:depth --start STORY/SCENE/start [--preset orbit --res 1080p]   depth parallax of a generated frame, on this Mac
    promo flow studio run --prompt "..." [--model M --res 480p --seconds 4 --aspect 16:9 --audio --preset push --start STORY/SCENE/start|FILE --end ...]
    promo flow studio rerun --take t3 [--res 720p]  the take's stored request sent again (same prompt, frames and seed), at another resolution for a final
    promo flow studio restyle --take t3 --prompt "make it dusk"   FLUX Video Edit on a take (or a generated plate file); never a screen recording
    promo flow studio swap --take t3|FILE --prompt "a red-haired courier in a yellow raincoat"   replace the person in a clip (FLUX Video Edit);
                                                  any clip except the product's own screen recordings, through the provider's own content checks
    promo flow studio frame --frame STORY/SCENE/start            the picture's path, for the agent to look at
    promo flow studio suggest --frame STORY/SCENE/start --prompt "..."   the agent's description of that frame's setting, offered in the composer
    promo flow studio use --take t3 --asset ID      the take becomes that asset's sample (flow/samples.json)

Takes are planning samples of NON-UI plates (AGENTS.md rule 1): the plate guard leads every prompt, they never enter the footage manifest from
here, and a take reaches a cut only through `promo gen register` like any other generated plate.

    flow/studio/takes.json   [{id, kind, from, prompt, preset, model, resolution, seconds, aspect, audio, seed, start, start_ref, end, end_ref, start_plate,
                               request, status, progress, job_id, estimate, cost, file, error, at, updated, used_for}]
    flow/studio/suggest.json {frame, prompt, at}

`request` is the OpenRouter body exactly as it was sent, pictures named by path (openrouter.body_for): a rerun or a final sends it again
with only the resolution changed, rather than rebuilding it from the composer's choices (docs/reference-higgsfield-studio.md).
"""
from __future__ import annotations

import datetime
import json
import os
import random
import re

from . import assetplan as AP
from . import depth as D
from . import footage as FT
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
DEPTH = "local:depth"                   # depth parallax on this Mac (promo/depth.py): moves a generated frame, free, nothing sent anywhere
DEPTH_MOVE = {None: "push", "static": "static", "push": "push", "pull": "pull", "orbit": "orbit", "pan_left": "pan_left", "pan_right": "pan_right",
              "crane": "crane", "handheld": "handheld"}
HEIGHT = {"480p": 480, "720p": 720, "1080p": 1080}
EDIT = OR.EDIT_MODELS[0]
# a frame description is the setting only: the plate guard already rules out UI, text and logos, so naming them in the prompt invites them back
NOT_SETTING = re.compile(r"\b(ui|user[- ]interface|interface|screens?|apps?|application|dashboard|software|logos?|brand|text|captions?|letters|typography|words)\b", re.I)


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


def _new_take(pd, **fields):
    """Add a queued take to takes.json and return its id; it shows in the gallery from this moment."""
    takes = load(pd)
    tid = f"t{max((int(t['id'][1:]) for t in takes), default=0) + 1}"
    now = _now()
    takes.append(dict(dict(id=tid, kind="generate", prompt="", preset=None, resolution=None, seconds=None, aspect=None, audio=False, seed=None, start=None, start_ref=None,
                           end=None, end_ref=None, start_plate=False, request=None, progress=None), **fields, id=tid, status="queued", job_id=None, estimate=None, cost=None, file=None, error=None,
                      at=now, updated=now, used_for=[]))
    _save(pd, takes)
    return tid


def _follow(pd, tid, ping, send):
    """Run `send(out, on_status)` for take `tid`, keeping takes.json and the Stage in step; a failure stays in the gallery with its reason."""
    rel = os.path.join("flow", "studio", tid + ".mp4")

    def status(s, jid):
        _update(pd, tid, status="generating" if s in ("pending", "in_progress") else s, job_id=jid)
        ping()
    try:
        meta = send(os.path.join(pd, rel), status)
    except OR.OpenRouterError as e:
        _update(pd, tid, status="failed", error=str(e))
        ping()
        raise
    _update(pd, tid, status="done", file=rel, cost=meta["cost_usd"], estimate=meta["estimate_usd"], job_id=meta["job_id"], request=meta["request"])
    ping()
    return take(pd, tid)


def take(pd, tid):
    t = next((t for t in load(pd) if t["id"] == tid), None)
    if not t:
        raise StudioError(f"no take {tid}")
    return t


def run(pd, prompt, model=OR.DEFAULT_MODEL, resolution=OR.DEFAULT_RES, seconds=OR.DEFAULT_SECONDS, aspect="16:9", audio=False, preset=None,
        start=None, start_ref=None, max_usd=OR.DEFAULT_MAX_USD, seed=None, on_change=None, end=None, end_ref=None, start_plate=False):
    """Make one take. The take is in takes.json from the first moment (queued, then OpenRouter's statuses, then done or failed with the reason),
    and `on_change()` runs after every change so the Stage can follow it. `start` / `end` are the first and last frames' files, `start_ref` /
    `end_ref` what the person picked (storyboard frame ids), kept so "same settings" can pick them again. Every take has a seed and keeps
    the request it sent, so a final at a higher resolution is the same job again (`rerun`). `start_plate`: the start frame is known to be
    a generated plate (a storyboard frame of a generated scene), which depth parallax needs."""
    if model == DEPTH and not start:
        raise StudioError("depth parallax moves a still: pick a start frame")
    if not prompt.strip() and model != DEPTH:
        raise StudioError("a take needs a prompt")
    for path, ref, which in ((start, start_ref, "start"), (end, end_ref, "end")):
        if path and not os.path.isfile(path):
            raise StudioError(f"{which} frame not found: {ref or path}")
    if end and model in (GROK, DEPTH):
        raise StudioError("this model takes a start frame only; pick a model that lists an end frame")
    seed = random.randrange(2 ** 31) if seed is None else seed
    tid = _new_take(pd, prompt=prompt.strip(), preset=preset, model=model, resolution=resolution, seconds=seconds, aspect=aspect, audio=bool(audio), seed=seed,
                    start=os.path.relpath(start, pd) if start else None, start_ref=start_ref, end=os.path.relpath(end, pd) if end else None, end_ref=end_ref,
                    start_plate=bool(start_plate))
    ping = on_change or (lambda: None)
    ping()
    if model == DEPTH:
        return _run_depth(pd, tid, start, preset, resolution, aspect, seconds, start_plate, ping)
    if model == GROK:
        return _run_grok(pd, tid, os.path.join("flow", "studio", tid + ".mp4"), prompt_text(prompt, preset), seconds, aspect, resolution, start, ping)
    return _follow(pd, tid, ping, lambda out, status: GV.generate_openrouter(prompt_text(prompt, preset), out, seconds, aspect, model=model, resolution=resolution,
                                                                             first_frame=start, audio=audio, max_usd=max_usd, on_status=status, seed=seed,
                                                                             last_frame=end))


def rerun(pd, tid, resolution=None, max_usd=OR.DEFAULT_MAX_USD, on_change=None):
    """The same job as take `tid` again: its stored request, with only the resolution changed when one is given (the paid final after a
    cheap draft). A take made on the person's grok subscription has no request; it runs again from its settings and seed."""
    t = take(pd, tid)
    if t.get("kind") in ("restyle", "swap"):
        raise StudioError(f"take {tid} is a {t['kind']}; make it again from its source instead")
    res = resolution or t["resolution"]
    if not t.get("request"):
        start, end = (os.path.join(pd, t[k]) if t.get(k) else None for k in ("start", "end"))
        return run(pd, t["prompt"], t["model"], res, t["seconds"], t["aspect"], t["audio"], t["preset"], start, t["start_ref"], max_usd, t["seed"], on_change,
                   end, t.get("end_ref"), t.get("start_plate", False))
    m = OR.model(t["model"])
    OR.check_params(m, t["request"]["duration"], res, t["request"]["aspect_ratio"])
    body = dict(t["request"], resolution=res)
    nid = _new_take(pd, **{k: t.get(k) for k in ("prompt", "preset", "model", "seconds", "aspect", "audio", "seed", "start", "start_ref", "end", "end_ref")},
                    kind="rerun", resolution=res, request=body, **{"from": tid})
    ping = on_change or (lambda: None)
    ping()
    return _follow(pd, nid, ping, lambda out, status: GV.openrouter_send(body, out, max_usd, status, prompt=t["prompt"]))


def _plate_source(pd, source):
    """The clip a restyle starts from: a finished Studio take, or a file whose sidecar says it is a generated plate. A screen recording is
    refused: restyling it would edit the app's UI (rules 1 and 2)."""
    if re.fullmatch(r"t\d+", source):
        t = take(pd, source)
        if t["status"] != "done":
            raise StudioError(f"take {source} is not finished")
        return os.path.join(pd, t["file"]), source
    path = os.path.abspath(source)
    if not D.is_generated(path):
        raise StudioError(f"{source} is not a generated plate (no .gen.json sidecar saying so); only Studio takes and generated plates can be "
                          "restyled, never a screen recording (AGENTS.md rules 1 and 2)")
    return path, os.path.basename(path)


def restyle(pd, source, prompt, model=EDIT, max_usd=OR.DEFAULT_MAX_USD, on_change=None):
    """Video to video (FLUX Video Edit): the prompt says what changes in a generated plate; the plate guard still leads it."""
    if not prompt.strip():
        raise StudioError("a restyle needs a prompt that says what changes")
    path, label = _plate_source(pd, source)
    m = OR.model(model)
    if not OR.is_edit(m):
        raise StudioError(f"{model} makes clips from a prompt; a restyle needs an edit model ({', '.join(OR.EDIT_MODELS)})")
    seconds = GV.probe_media(path)["duration"]
    body = OR.edit_body(m, GV.NEG + prompt.strip(), path)
    src = take(pd, source) if re.fullmatch(r"t\d+", source) else {}
    tid = _new_take(pd, kind="restyle", prompt=prompt.strip(), model=model, seconds=round(seconds, 2), aspect=src.get("aspect"), resolution=src.get("resolution"),
                    request=body, **{"from": label})
    ping = on_change or (lambda: None)
    ping()
    return _follow(pd, tid, ping, lambda out, status: GV.openrouter_send(body, out, max_usd, status, prompt=prompt, seconds=seconds, source=path))


SWAP = ("Replace the person in this clip with {who}. Keep the camera move, the timing of their motion, the framing, the light and the "
        "background exactly as they are.")


def _product_capture(pd, path):
    """True when `path` is one of this project's real recordings of the product: a footage-manifest clip without `generated:` or a
    real asset of the plan. Swapping a person into those would edit the app's footage (AGENTS.md rule 2)."""
    sha = GV.sha256(path)
    clips = FT.load_raw(os.path.join(pd, "footage", "manifest.yaml"))
    if any(c.get("sha256") == sha and not c.get("generated") for c in clips):
        return True
    real = [os.path.realpath(os.path.join(pd, a["path"])) for a in AP.load(os.path.join(pd, "flow")) if a.get("source") == "real" and a.get("path")]
    return os.path.realpath(path) in real


def swap(pd, source, who, model=EDIT, max_usd=OR.DEFAULT_MAX_USD, on_change=None):
    """Character swap (carve-out of 11 Oct 2026, AGENTS.md rule 1): the person in a clip becomes `who`, by FLUX Video Edit. The source is
    a finished take or any clip the person brought, except the product's own recordings. The provider's content checks apply as they are;
    a refusal stays on the take with OpenRouter's reason."""
    if not who.strip():
        raise StudioError("say who goes into the clip")
    if re.fullmatch(r"t\d+", source):
        path, label = _plate_source(pd, source)
    else:
        path, label = os.path.abspath(source), os.path.basename(source)
        if not os.path.isfile(path):
            raise StudioError(f"no clip {label}")
        if _product_capture(pd, path):
            raise StudioError(f"{label} is a recording of the product; a character swap never edits the app's own footage (AGENTS.md rule 2)")
    m = OR.model(model)
    if not OR.is_edit(m):
        raise StudioError(f"{model} makes clips from a prompt; a swap needs an edit model ({', '.join(OR.EDIT_MODELS)})")
    seconds = GV.probe_media(path)["duration"]
    body = OR.edit_body(m, GV.NEG_PEOPLE + SWAP.format(who=who.strip()), path)
    src = take(pd, source) if re.fullmatch(r"t\d+", source) else {}
    tid = _new_take(pd, kind="swap", prompt=who.strip(), model=model, seconds=round(seconds, 2), aspect=src.get("aspect"), resolution=src.get("resolution"),
                    request=body, **{"from": label})
    ping = on_change or (lambda: None)
    ping()
    return _follow(pd, tid, ping, lambda out, status: GV.openrouter_send(body, out, max_usd, status, prompt=who, seconds=seconds, source=path))


def _suggest_path(pd):
    return os.path.join(_dir(pd), "suggest.json")


def suggest(pd, frame, prompt):
    """The agent's description of a storyboard frame's setting (light, place, lens, mood), offered in the composer. Nothing is billed."""
    prompt = " ".join(prompt.split())
    if not prompt:
        raise StudioError("the suggestion is empty")
    if NOT_SETTING.search(prompt):
        raise StudioError(f"describe the setting only (light, place, lens, mood); {NOT_SETTING.search(prompt).group(0)!r} names what the plate guard "
                          "keeps out (rule 1), and naming it invites it back")
    os.makedirs(_dir(pd), exist_ok=True)
    with open(_suggest_path(pd), "w") as f:
        json.dump(dict(frame=frame, prompt=prompt, at=_now()), f, indent=1)


def suggestion(pd):
    try:
        with open(_suggest_path(pd)) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _size(resolution, aspect):
    a, b = (int(x) for x in aspect.split(":"))
    short = HEIGHT.get(resolution, 720)
    return (round(short * a / b), short) if a >= b else (short, round(short * b / a))


def _run_depth(pd, tid, start, preset, resolution, aspect, seconds, start_plate, ping):
    """A depth parallax take: the start frame moved by its own depth with the camera preset, on this Mac, nothing billed. The take
    shows how far the render is (`progress`), so a 30 s render never looks stuck."""
    rel = os.path.join("flow", "studio", tid + ".mp4")
    _update(pd, tid, status="generating", estimate=0, cost=0, progress=0)
    ping()

    def progress(i, n):
        _update(pd, tid, progress=round(i / n, 2))
        ping()
    try:
        D.parallax(start, os.path.join(pd, rel), seconds, DEPTH_MOVE[preset], size=_size(resolution, aspect), trusted=start_plate, on_progress=progress)
    except D.DepthError as e:
        _update(pd, tid, status="failed", error=str(e))
        ping()
        raise StudioError(str(e)) from None
    _update(pd, tid, status="done", file=rel, progress=None)
    ping()
    return take(pd, tid)


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
    """Video makers that bill nothing per take, as Studio models: grok on the person's own login (the codex CLI has an image tool and no
    video tool) and depth parallax on this Mac (`needs_frame`: it moves a picked frame; `prompt: False`: it reads no prompt)."""
    out = []
    if next(p for p in GV.detect() if p["id"] == "grok")["available"]:
        aspects, res = ["16:9", "9:16", "1:1", "3:2", "2:3"], ["480p", "720p"]
        out.append(dict(id=GROK, name="Grok (your subscription)", seconds=[1, 15], resolutions=res, aspects=aspects, first_frame=True, audio=False,
                        price_4s={r: 0 for r in res}, image_input=0, per_second={f"{r}|{a}|0": 0 for r in res for a in aspects}, subscription=True))
    if D.available():
        aspects, res = ["16:9", "9:16", "1:1"], ["720p", "1080p"]
        out.append(dict(id=DEPTH, name="Depth parallax (this Mac, free)", seconds=[2, 10], resolutions=res, aspects=aspects, first_frame=True, audio=False,
                        price_4s={r: 0 for r in res}, image_input=0, per_second={f"{r}|{a}|0": 0 for r in res for a in aspects}, subscription=True,
                        local=True, needs_frame=True, prompt=False))
    return out


def use(pd, tid, asset_id):
    """Record a finished take as the sample of a generated video asset; the asset itself (and its state) is untouched."""
    t = next((t for t in load(pd) if t["id"] == tid), None)
    if not t or t["status"] != "done":
        raise StudioError(f"take {tid} is not a finished take")
    flow_dir = os.path.join(pd, "flow")
    a = next((x for x in AP.load(flow_dir) if x["id"] == asset_id), None)
    if not a:
        raise StudioError(f"no asset {asset_id} in the plan")
    if a["kind"] != "video" or a["source"] != "generated":
        raise StudioError(f"asset {asset_id} is a {a['source']} {a['kind']}; a Studio take can only stand in for a generated video plate")
    samples = PV.load_samples(flow_dir)
    cost = f"${t['cost']:.2f}" if t.get("cost") is not None else "cost not reported"
    samples[asset_id] = dict(path=t["file"], at=_now(), take=tid,
                             note=f"Studio take {tid} ({t['model'].split('/')[-1]}, {t['resolution'] or 'source size'}, {t['seconds']} s, {cost})")
    with open(PV.samples_path(flow_dir), "w") as f:
        json.dump(samples, f, indent=2)
    _update(pd, tid, used_for=sorted(set(t["used_for"]) | {asset_id}))
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
    per_s = {m["id"]: _per_second(m) for m in cat if not OR.is_edit(m)}
    subs = _subscriptions()
    models = subs + [dict(r, per_second=per_s[r["id"]]) for r in OR.price_table(cat)]
    edit = next((dict(id=m["id"], name=m["name"].split(": ", 1)[-1], per_second=OR.estimate(m, 1000, None, None) / 1000,
                      minimum=float(m["pricing_skus"].get("minimum_cents_per_generation", 0)) / 100) for m in cat if OR.is_edit(m)), None)
    labels = {f["id"]: f["label"] for f in frames}
    takes = []
    for t in reversed(load(pd)):
        t = dict(t)
        idle = (now - datetime.datetime.fromisoformat(t["updated"])).total_seconds()
        if t["status"] not in ("done", "failed") and idle > STOPPED_S:
            t["status"], t["error"] = "stopped", "The run that made this take stopped before the clip came back."
        t["video"] = media(os.path.join(pd, t["file"])) if t.get("file") else None
        t["start_label"] = labels.get(t["start_ref"], os.path.basename(t["start"])) if t.get("start") else None
        t["end_label"] = labels.get(t.get("end_ref"), os.path.basename(t["end"])) if t.get("end") else None
        t.pop("request", None)              # it names files on this box; the Stage never needs it
        takes.append(t)
    plates = [dict(id=a["id"], label=a.get("label") or a["id"]) for a in AP.load(os.path.join(pd, "flow")) if a["kind"] == "video" and a["source"] == "generated"]
    sp = OR.spend()
    return dict(models=models, models_error=models_error, default_model=GROK if any(m["id"] == GROK for m in subs) else OR.DEFAULT_MODEL, guard=GV.NEG, presets=[dict(id=k, label=lb, sentence=s) for k, lb, s in PRESETS],
                max_usd=OR.DEFAULT_MAX_USD, account="ready" if "video" in next(p for p in GV.detect() if p["id"] == "openrouter")["verified"] else "unchecked",
                spend=dict(today=sp["today"], total=sp["total"], cap=OR.daily_cap()), takes=takes, frames=frames, plates=plates, edit=edit, suggestion=suggestion(pd))
