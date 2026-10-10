"""Two files the flow writes from its own state, so nothing the person said or decided lives only in a chat window:

- flow/rounds/<cycle>-<n>/BRIEF.md   the round's contract, rewritten whenever the round's inputs change. Every maker and reviewer sub-agent reads it
                                     first: the person's words on top (they win over everything below), the checks with how each draft did, the
                                     drafts that lost and why, the look against the references, what this person said in earlier videos, and
                                     the recipes that fit what is still open.
- NOTES.md (project root)            the video's living memory: the pitch, every decision with who made it and when, where it stands now, and the
                                     agent's own notes (`promo flow notes add TEXT`, kept across rewrites). Read it first when picking a video up again.
"""
from __future__ import annotations

import os

from . import abtest as AB
from . import autopilot as AU
from . import brief as BR
from . import flow as F
from . import flowcheck as FC
from . import lessons as L

NOTES_HEAD = "## Agent notes"
NO_NOTES = "- none yet"
LAST_DRAFTS = 3


def brief_path(pd, r):
    return os.path.join(F.fdir(pd), "rounds", f"{r['cycle']}-{r['n']}", "BRIEF.md")


def _scoreboard_lines(st):
    if not st["drafts"]:
        return ["No draft yet."]
    # the round's control sits among the other rows with the same columns: a reviewer must not be able to tell it apart
    sb = FC.scoreboard(st, control=True)
    L_ = [FC.scoreboard(st)["line"] + ".", "", "| check | scene | last draft | change | evidence |", "|---|---|---|---|---|"]
    for x in sb["rows"]:
        L_.append(f"| {x['id']} {x['what']} | {x['scene'] or 'all'} | {x['status']} | {x['change']} | {F._clip(x['why'], 90)} |")
    L_ += ["", "Mark every judge check on the new draft (`promo flow check mark` / `check marks`), pass or fail with evidence. Unmeasured is not a pass.",
           "Keep what got fixed; restore what broke. A draft that breaks what the reviewed draft got right cannot go to the person."]
    return L_


def _history(pd, st):
    out = []
    first = max(0, len(st["drafts"]) - LAST_DRAFTS)
    for i, d in enumerate(st["drafts"][first:], first + 1):
        line = f"- Draft {i}" + (f" ({d['note']})" if d.get("note") else "")
        if i > 1:
            sb = FC.scoreboard(st, i)
            line += f": {sb['fixed']} fixed, {sb['broken']} broken, {sb['open']} open"
            broke = [x["what"] for x in sb["rows"] if x["change"] == "broken"]
            if broke:
                line += f". It broke: {'; '.join(broke)}"
        for p in st.get("pairs") or []:
            if p["kind"] == "judge" and p["draft"] == i:
                res = AB.result(p)
                if res["done"]:
                    line += f". {res['line']}" + (" (it LOST: do not repeat it)" if res["winner"] == p["against"] else "")
        r = next((x for x in st["rounds"] if x.get("closed") and x["drafts_at_start"] == i), None)
        if r:
            line += f". The person then said: \"{F._clip(r['feedback'], 160)}\""
        out.append(line)
    for x in (st.get("restores") or [])[-3:]:
        out.append(f"- {x['what']} ({x['by']}, {x['at'][:16]})")
    return out or ["- none yet"]


def _look(st):
    for i in range(len(st["drafts"]) - 1, -1, -1):
        lk = st["drafts"][i].get("look")
        if lk:
            L_ = [f"Draft {i + 1}: mean distance {lk['mean']:.3f} to the nearest reference stills (0 = same look; it may not grow by more than {FC.LOOK_TOL})."]
            for sid, x in sorted(lk["scenes"].items(), key=lambda kv: -kv[1]["d"])[:5]:
                L_.append(f"- scene {sid}: {x['d']:.3f}, pair image (reference LEFT, draft RIGHT): {x['pair']}")
            return L_
    return ["Not measured yet (`promo flow look` once a draft exists and the references have cut stills)."]


def write_brief(pd):
    """Rewrite the open round's BRIEF.md; None when no round is open."""
    st = F.load(pd)
    r = F.open_round(st)
    if not r:
        return None
    key = FC.round_key(r)
    pins = [p for p in st.get("pins") or [] if p.get("round") == key and not p.get("removed")]
    over = [a for a in st.get("assumptions") or [] if a.get("overturned")]
    try:
        b = BR.load(pd)
    except BR.BriefError:
        b = {}
    open_text = " ".join(x["what"] for x in (FC.scoreboard(st)["rows"] if st["drafts"] else []) if x["status"] != "pass")
    style = (st.get("discover") or {}).get("style")
    recs = L.retrieve(pd, style, open_text + " " + r["feedback"])
    used = r.get("recipes") or []
    who = st.get("person")
    lessons = L.top(who)
    out = [f"# Round {r['n']} of {F.MAX_ROUNDS}" + (f" (cycle {r['cycle']})" if r["cycle"] > 1 else "") + f": {F._project(pd)}", "",
           "Read this first. The person's words below win over everything else in this file.", "",
           "## The person's words (obey these over everything below)", "", "> " + r["feedback"].replace("\n", "\n> "), ""]
    for p in pins:
        out.append(f"- Pinned at {p['at_s']:.1f} s of draft {p['draft']}" + (f", scene {p['scene']}" if p.get("scene") else "") + f": \"{p['text']}\" ({p['by']})")
    for a in over:
        out.append(f"- Instead of \"{a['text']}\": \"{a['overturned']['text']}\" ({a['overturned']['by']})")
    out += ["", "What they asked for in the first place:", "", "> " + st["intent"].replace("\n", "\n> ")]
    if b.get("must_have") or b.get("must_not"):
        out += [""] + [f"- must have: {x}" for x in b.get("must_have") or []] + [f"- must not: {x}" for x in b.get("must_not") or []]
    out += ["", "## Checks", ""] + _scoreboard_lines(st)
    out += ["", "## Earlier drafts (build on what was kept; do not repeat what lost)", ""] + _history(pd, st)
    out += ["", "## Look against the references", ""] + _look(st)
    out += ["", "## What this person said before" + (f" ({who})" if who else ""), ""]
    out += [f"- {x['line']}" for x in lessons] or ["- nothing recorded yet"]
    out += ["", "## Recipes that fit what is still open", ""]
    out += [f"- {x['id']} ({x['kind']}, {x['w']} won / {x['l']} lost, {x['state']}): {x['intent']} How: {x['how']}" for x in recs] or ["- none match"]
    if used:
        out.append(f"- used this round: {', '.join(used)}")
    out += ["", "Mark a recipe you apply with `promo flow recipe use ID`; its record moves with this round's result.", "",
            "## Before the round closes", "",
            "- every note above is a check (`promo flow check add --source feedback`)",
            "- every check is measured on the new draft, and nothing the reviewed draft got right is broken",
            "- the new draft was compared blind with the reviewed one (`promo flow ab drafts`, one fresh judge per order) and did not lose",
            "- council (intent-check line) and research (>= 3 URLs) as in evals/council-flow.md"]
    p = brief_path(pd, r)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("\n".join(out) + "\n")
    return p


# ---- NOTES.md ------------------------------------------------------------------------------------------------------------------------------
def notes_path(pd):
    return os.path.join(pd, "NOTES.md")


def _agent_notes(pd):
    p = notes_path(pd)
    if not os.path.isfile(p):
        return []
    text = open(p).read()
    if NOTES_HEAD not in text:
        return []
    return [x for x in text.split(NOTES_HEAD, 1)[1].strip().splitlines() if x.strip() and x.strip() != NO_NOTES]


def add_note(pd, text):
    text = " ".join((text or "").split())
    if not text:
        raise F.FlowError("a note needs text")
    lines = _agent_notes(pd) + [f"- {F.now()[:16]} {text}"]
    write_notes(pd, lines)


def write_notes(pd, agent_lines=None):
    st = F.load(pd)
    agent_lines = _agent_notes(pd) if agent_lines is None else agent_lines
    picked = [s for s in st["scripts"] if s["id"] in st["picks"]]
    out = [f"# {F._clip(picked[0]['title'] if picked else st['intent'].split('.')[0], 80)}", "",
           "_The living memory of this video, written by `promo flow` from its state; read it first when you pick the video up again._", "",
           "## Pitch", "", "> " + st["intent"].replace("\n", "\n> "), ""]
    out += [f"- Story {s['id']}: {s['title']}: {s['logline']}" for s in picked]
    if (st.get("discover") or {}).get("style"):
        out.append(f"- Style: {st['discover']['style']}")
    out += ["", "## Decisions", ""]
    dec = []
    for g, v in st["gates"].items():
        dec.append((v["at"], f"{v['by']} approved {g.replace('-', ' ')}" + ("" if F.gate_ok(pd, st, g) else " (changed since: needs approving again)")))
    try:
        for c in BR.load(pd).get("conflicts") or []:
            if c.get("decision") and c["decision"] != "pending":
                dec.append(("", f"{c.get('decided_by') or 'The person'} decided on {c.get('what')}: {c['decision']}"))
    except BR.BriefError:
        pass
    for p in st.get("pairs") or []:
        for k in p.get("picks") or []:
            dec.append((k["at"], f"{k['by']} picked {'the ' + p[k['choice']]['label'] if k['choice'] in ('a', 'b') else k['choice']} for \"{p['question']}\""))
    for a in st.get("assumptions") or []:
        if a.get("overturned"):
            dec.append((a["overturned"]["at"], f"{a['overturned']['by']} overturned \"{a['text']}\": {a['overturned']['text']}"))
    for c in st.get("checks") or []:
        if c.get("retired"):
            dec.append((c["retired"]["at"], f"{c['retired']['by']} dropped the check \"{c['what']}\": {c['retired']['why']}"))
    for x in st.get("restores") or []:
        dec.append((x["at"], f"{x['by']}: {x['what']}"))
    out += [f"- {at[:16]} {t}" if at else f"- {t}" for at, t in sorted(dec)] or [NO_NOTES]
    out += ["", "## Current state", "", f"- Stage: {F.LABEL[st['stage']]}" + (f", review round {len(F.cycle_rounds(st))} of {F.MAX_ROUNDS}" if st["stage"] == "review" else "")]
    if st["drafts"]:
        n = len(st["drafts"])
        out.append(f"- Latest draft: {n}, {os.path.basename(st['drafts'][-1]['file'])}. {FC.verify_view(st['drafts'][-1])['line']}")
        sb = FC.scoreboard(st)
        out.append(f"- {sb['line']}")
        out += [f"  - open: {x['what']}" + (f" (scene {x['scene']})" if x["scene"] else "") for x in sb["rows"] if x["status"] != "pass"]
    ap = AU.view(st)
    if ap:
        out.append(f"- Autopilot: {ap['line']}")
    if st["finals"]:
        out.append(f"- Final: {os.path.basename(st['finals'][-1]['file'])}")
    out += ["", NOTES_HEAD, ""] + (agent_lines or [NO_NOTES])
    with open(notes_path(pd), "w") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")
    return notes_path(pd)
