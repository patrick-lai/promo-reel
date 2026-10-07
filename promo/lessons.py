"""What carries over from one video to the next, kept beside the promo-reel config (`promo config`), never in a project:

- lessons.jsonl      the person's own notes, picks, restores and verdicts, per person. The ones that come back across videos lead every round
                     brief and the script stage ("Sam, in 3 videos: no speed lines over the app"). Built by rules, no model; `forget` drops one.
- recipe-stats.json  wins and losses of each technique in recipes/ (and a project's flow/recipes/): a recipe used in a round wins when its
                     own check passes on the draft the round closes with, and loses when that check fails or a blind judge preferred the earlier draft.
                     Two wins (and more wins than losses) promote it; three losses, at least twice the wins, retire it.
- calibration.jsonl  what the council predicted (its intent-check verdict at round close) against what the person then did (approved or
                     sent more feedback), so `promo flow calibration` can say whether "the council says ready" means they say yes.

    promo flow lessons [--who NAME] [--all] | --add TEXT --by NAME | --forget ID --by NAME
    promo flow recipe list [--style S] [--for TEXT] | use ID [--scene ID] | add --file F
    promo flow calibration
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re

import yaml

from . import home

REPO_RECIPES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")
STOP = set("a an the and or of to in on at for with is are be it this that than then not no as by from into over under your our their its "
           "should must make made more less too very".split())
TOP = 8


def _dir():
    return os.path.dirname(home.config_path())


def _path(name):
    return os.path.join(_dir(), name)


def _flow():
    from . import flow as F          # flow imports this module: a top-level import would be circular
    return F


def _now():
    return _flow().now()


def _append(name, rec):
    os.makedirs(_dir(), exist_ok=True)
    with open(_path(name), "a") as f:
        f.write(json.dumps(rec) + "\n")


def _read(name):
    p = _path(name)
    if not os.path.isfile(p):
        return []
    with open(p) as f:
        return [json.loads(x) for x in f if x.strip()]


# ---- lessons ---------------------------------------------------------------------------------------------------------------------------------
def record(kind, who, project, text):
    text = " ".join((text or "").split())
    if not text:
        return None
    lid = hashlib.sha1(f"{kind}:{who}:{project}:{text}".encode()).hexdigest()[:8]
    _append("lessons.jsonl", dict(id=lid, at=_now(), kind=kind, who=who, project=project, text=text))
    return lid


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2}


def _live():
    rows = _read("lessons.jsonl")
    gone = {r["id"] for r in rows if r["kind"] == "forget"}
    return [r for r in rows if r["kind"] != "forget" and r["id"] not in gone]


def _groups(rows):
    """One group per note that came back: the same person, two or more shared words, newest first."""
    groups = []
    for r in sorted(rows, key=lambda r: r["at"], reverse=True):
        tk = _tokens(r["text"])
        g = next((g for g in groups if g["who"] == r.get("who") and len(tk & g["tokens"]) >= 2), None)
        if g:
            g["projects"].add(r["project"])
            g["ids"].append(r["id"])
        else:
            groups.append(dict(text=r["text"], who=r.get("who"), kind=r["kind"], tokens=tk, projects={r["project"]}, ids=[r["id"]], at=r["at"]))
    return groups


def top(who, n=TOP, everyone=False):
    """This person's lessons worth repeating: notes that came back in other videos first, then the newest. Without a person nothing is
    shown (one person's notes never reach another's Stage); `everyone` is the agent's own `lessons --all` listing."""
    if not (who or everyone):
        return []
    groups = _groups([r for r in _live() if everyone or r.get("who") == who])
    groups.sort(key=lambda g: (len(g["projects"]), g["at"]), reverse=True)
    out = []
    for g in groups[:n]:
        k = len(g["projects"])
        lead = f"{g['who'] or 'The person'}, in {k} videos: " if k > 1 else f"{g['who'] or 'The person'}: "
        out.append(dict(id=g["ids"][0], ids=g["ids"], text=g["text"], line=lead + g["text"], videos=k, kind=g["kind"]))
    return out


def forget(lid, by):
    """Forget the lesson `lid` stands for: every note in its group, or it would come back as a smaller lesson."""
    live = _live()
    g = next((g for g in _groups(live) if lid in g["ids"]), None)
    if g is None:
        raise _flow().FlowError(f"no lesson {lid}: `promo flow lessons --all` lists them")
    for r in [r for r in live if r["id"] in g["ids"]]:
        _append("lessons.jsonl", dict(id=r["id"], at=_now(), kind="forget", who=by, project=r["project"], text=r["text"]))


# ---- recipes ---------------------------------------------------------------------------------------------------------------------------------
def recipes(project_dir=None):
    out = []
    for d, scope in ((REPO_RECIPES, "shared"), (os.path.join(project_dir, "flow", "recipes") if project_dir else None, "project")):
        for p in sorted(glob.glob(os.path.join(d, "*.yaml"))) if d else []:
            r = yaml.safe_load(open(p)) or {}
            r["scope"] = scope
            out.append(r)
    stats = _stats()
    for r in out:
        s = stats.get(r["id"], dict(w=0, l=0))
        r["w"], r["l"] = s["w"], s["l"]
        r["state"] = "retired" if s["l"] >= 3 and s["l"] >= 2 * s["w"] else "promoted" if s["w"] >= 2 and s["w"] > s["l"] else "trial"
    return out


RECIPE_KEYS = ("id", "kind", "styles", "intent", "how", "check")


def validate(r):
    miss = [k for k in RECIPE_KEYS if not r.get(k)]
    if miss:
        raise _flow().FlowError(f"a recipe needs {', '.join(miss)} (see recipes/README.md)")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", r["id"]):
        raise _flow().FlowError("a recipe id is lower-case words joined by - or . (e.g. hook.result-first)")


def retrieve(project_dir, style=None, text="", n=3):
    """Recipes that fit: the style matches (or the recipe is for any style) and it shares two words with what is still open, best record first."""
    tk = _tokens(text or "")
    out = []
    for r in recipes(project_dir):
        if r["state"] == "retired":
            continue
        styles = [s.lower() for s in r.get("styles") or []]
        if style and styles and "any" not in styles and not any(s in style.lower() for s in styles):
            continue
        overlap = len(tk & _tokens(" ".join(str(r.get(k, "")) for k in ("id", "intent", "check", "kind"))))
        if tk and overlap < 2:
            continue
        score = (overlap + (r["w"] - r["l"])) * (1.5 if r["state"] == "promoted" else 1.0)
        out.append((score, r))
    out.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in out[:n]]


def _stats():
    p = _path("recipe-stats.json")
    return json.load(open(p)) if os.path.isfile(p) else {}


def credit(rid, won):
    st = _stats()
    s = st.setdefault(rid, dict(w=0, l=0))
    s["w" if won else "l"] += 1
    os.makedirs(_dir(), exist_ok=True)
    with open(_path("recipe-stats.json"), "w") as f:
        json.dump(st, f, indent=1)


# ---- calibration -----------------------------------------------------------------------------------------------------------------------------
def calibrate(project, predicted, actual):
    _append("calibration.jsonl", dict(at=_now(), project=project, predicted=predicted, actual=actual))


def calibration():
    """{n, agree, rate, table{predicted: {approved, feedback}}}: YES should be followed by an approval, PARTIAL or NO by more feedback."""
    rows = [r for r in _read("calibration.jsonl") if r.get("predicted")]
    table = {}
    for r in rows:
        table.setdefault(r["predicted"], dict(approved=0, feedback=0))[r["actual"]] += 1
    agree = sum(1 for r in rows if (r["predicted"] == "YES") == (r["actual"] == "approved"))
    return dict(n=len(rows), agree=agree, rate=round(agree / len(rows), 2) if rows else None, table=table)
