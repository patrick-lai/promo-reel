"""Real screens in the storyboard: before the person approves it, the agent opens the real product (the shared browser, a capture script) at
each state a scene shows and puts that screenshot in as the scene's frame, so the storyboard shows the product as it is. A scene whose screen
cannot be reached is recorded with the reason, so the capture session is not the first time anyone finds out.

    promo flow scout list [--json]                                              every app scene (source real): real screen, unreachable, or still drawn
    promo flow scout add --story A --scene 03 --file shot.png [--which start|end|both] [--url URL]
    promo flow scout miss --story A --scene 03 --why "needs an admin login we do not have"

A real screen carries a `.real.json` sidecar (where and when it was taken). It is planning material like every storyboard frame: the cut still
uses registered footage only (`promo footage add`).
"""
from __future__ import annotations

import json
import os

from PIL import Image

from . import boardedit as BE
from . import flow as F


def _scene(pd, story, scene):
    d, b = BE._load(F.fdir(pd), story)
    s = next((x for x in b.get("scenes") or [] if str(x["id"]) == str(scene)), None)
    if s is None:
        raise F.FlowError(f"no scene {scene} in story {story}")
    return d, b, s


def state(d, s):
    if s.get("source") != "real":
        return None
    imgs = [os.path.join(d, (s.get(w) or {}).get("image") or "") for w in ("start", "end")]
    if all(os.path.isfile(p + ".real.json") for p in imgs):
        return "real"
    if s.get("scout_miss"):
        return "missed"
    return "drawn"


def listing(pd):
    st = F.load(pd)
    out = []
    for sid, b, d in F.boards(pd, st):
        for s in b.get("scenes") or []:
            k = state(d, s)
            if k:
                out.append(dict(story=sid, scene=str(s["id"]), state=k, action=s.get("action", ""), why=(s.get("scout_miss") or {}).get("why")))
    return out


def add(pd, story, scene, file, which="both", url=None):
    if not os.path.isfile(file or ""):
        raise F.FlowError(f"no such file {file}")
    d, b, s = _scene(pd, story, scene)
    if s.get("source") != "real":
        raise F.FlowError(f"scene {scene} is not an app scene (source {s.get('source')}): real screens go on scenes that show the product")
    for w in (("start", "end") if which == "both" else (which,)):
        rel = f"frames/{scene}-real-{w}.png"
        dst = os.path.join(d, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with Image.open(file) as im:
            im.convert("RGB").save(dst)
        with open(dst + ".real.json", "w") as f:
            json.dump(dict(url=url, at=F.now(), from_file=os.path.basename(file)), f, indent=1)
        s.setdefault(w, {})["image"] = rel
    s.pop("scout_miss", None)
    BE._save(d, b)
    F.note(pd, f"Real screen for scene {scene}" + (f" from {url}" if url else ""), "capture", True)


def miss(pd, story, scene, why):
    if not (why or "").strip():
        raise F.FlowError("say why the screen cannot be reached (--why)")
    d, b, s = _scene(pd, story, scene)
    s["scout_miss"] = dict(why=" ".join(why.split()), at=F.now())
    BE._save(d, b)


def summary(items):
    return dict(app_scenes=len(items), real=sum(1 for x in items if x["state"] == "real"), missed=sum(1 for x in items if x["state"] == "missed"),
                drawn=sum(1 for x in items if x["state"] == "drawn"))
