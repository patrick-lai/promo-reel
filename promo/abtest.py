"""Blind A/B comparisons: for the person, a pick between two options without knowing which is which; for the agent, a judge that compares
the new draft with the one the person reviewed before it is shown to them.

    promo flow ab add --question Q --a FILE --b FILE [--label-a T] [--label-b T] [--scene ID]   a pick for the person (images, clips or sounds)
    promo flow ab pick ID --side left|right|same|unsure --by NAME                              their answer from the Stage
    promo flow ab drafts [--draft N] [--against M]     sheets of draft N and draft M in two orders (flow/ab/<id>/order-1.png, order-2.png)
    promo flow ab judge ID --order 1|2 --pick A|B|tie|insufficient [--defect TEXT] --family F    one fresh judge per order

Which option sits on the left comes from the project and the pair id, so it is fixed for a pair and unrelated to the order the options were
given in. A judge pair counts only where both orders agree: the same draft twice wins, two ties tie, anything else is "no agreement".
"Insufficient" is its own answer, never a tie. A round cannot close when both orders prefer the draft the person already reviewed.
"""
from __future__ import annotations

import hashlib
import os
import shutil

from . import flow as F

SIDES = ("left", "right", "same", "unsure")
PICKS = ("A", "B", "tie", "insufficient")
KIND = {".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".mp4": "video", ".mov": "video", ".webm": "video",
        ".mp3": "audio", ".wav": "audio", ".m4a": "audio"}
FRAMES = 8


def _flip(pd, pid):
    return int(hashlib.sha256(f"{F.project_id(pd)}:{pid}".encode()).hexdigest(), 16) % 2 == 1


def pair(st, pid):
    p = next((x for x in st.get("pairs") or [] if x["id"] == pid), None)
    if p is None:
        raise F.FlowError(f"no comparison {pid}: `promo flow ab list` shows them")
    return p


def add(pd, question, a, b, label_a=None, label_b=None, scene=None):
    st = F.load(pd)
    if not (question or "").strip():
        raise F.FlowError("a pick needs --question, the decision in the person's terms (\"Which opening?\")")
    for f in (a, b):
        if not os.path.isfile(f or ""):
            raise F.FlowError(f"no such file {f}")
    ext = {os.path.splitext(x)[1].lower() for x in (a, b)}
    if len(ext) != 1 or next(iter(ext)) not in KIND:
        raise F.FlowError("both options must be the same kind of file: images, clips (mp4/mov/webm) or sounds (mp3/wav/m4a)")
    pid = f"p{sum(1 for x in st.get('pairs') or [] if x['kind'] == 'person') + 1}"
    d = os.path.join(F.fdir(pd), "ab", pid)
    os.makedirs(d, exist_ok=True)
    left, right = (b, a) if _flip(pd, pid) else (a, b)
    e = next(iter(ext))
    shutil.copyfile(left, os.path.join(d, "left" + e))
    shutil.copyfile(right, os.path.join(d, "right" + e))
    st.setdefault("pairs", []).append(dict(id=pid, kind="person", question=" ".join(question.split()), scene=scene, media=KIND[e],
                                           a=dict(label=label_a or os.path.basename(a)), b=dict(label=label_b or os.path.basename(b)),
                                           left="b" if _flip(pd, pid) else "a", files=dict(left=f"ab/{pid}/left{e}", right=f"ab/{pid}/right{e}"),
                                           created=F.now(), picks=[]))
    F.log(st, f"comparison {pid}: {question}")
    F.save(pd, st)
    return pid


def pick(pd, pid, side, by):
    st = F.load(pd)
    by = F.human(by)
    p = pair(st, pid)
    if p["kind"] != "person":
        raise F.FlowError(f"{pid} is a judge comparison: `promo flow ab judge`")
    if side not in SIDES:
        raise F.FlowError(f"side is one of {', '.join(SIDES)}")
    right = "b" if p["left"] == "a" else "a"
    choice = {"left": p["left"], "right": right}.get(side, side)
    p["picks"].append(dict(side=side, choice=choice, by=by, at=F.now()))
    st["person"] = by
    if choice in ("a", "b"):
        lose = "b" if choice == "a" else "a"
        said = f"preferred {p[choice]['label']} over {p[lose]['label']} ({p['question']})"
    else:
        said = f"saw no difference worth choosing between {p['a']['label']} and {p['b']['label']} ({p['question']})" if choice == "same" else None
    F.log(st, f"{by} picked on {pid}: {choice}")
    F.save(pd, st)
    if said:
        from . import lessons as L
        L.record("pick", by, F._project(pd), said)
    return choice


def judge_pair(pd, n=None, against=None):
    """Two orders of the same comparison: the new draft and the reviewed one as frame rows A and B, then swapped."""
    from . import compare_ref as CR
    st = F.load(pd)
    if not st["drafts"]:
        raise F.FlowError("no draft yet")
    n = n or len(st["drafts"])
    r = F.open_round(st)
    against = against or (r["drafts_at_start"] if r else n - 1)
    if not (1 <= against < n <= len(st["drafts"])):
        raise F.FlowError(f"cannot compare draft {n} with draft {against}: there are {len(st['drafts'])} drafts")
    jid = f"j{sum(1 for x in st.get('pairs') or [] if x['kind'] == 'judge') + 1}"
    d = os.path.join(F.fdir(pd), "ab", jid)
    os.makedirs(d, exist_ok=True)
    first = (against, n) if _flip(pd, jid) else (n, against)
    orders = {"1": dict(A=first[0], B=first[1]), "2": dict(A=first[1], B=first[0])}
    for k, o in orders.items():
        CR.sheet(st["drafts"][o["A"] - 1]["file"], st["drafts"][o["B"] - 1]["file"], os.path.join(d, f"order-{k}.png"), FRAMES, ref_label="A", draft_label="B")
    feedback = r["feedback"] if r else ""
    with open(os.path.join(d, "QUESTION.md"), "w") as f:
        f.write("# Which cut serves the request better?\n\nThe person asked, in their words:\n\n> " + st["intent"].replace("\n", "\n> ") + "\n\n"
                + (f"Their latest notes on the earlier cut:\n\n> {feedback}\n\n" if feedback else "")
                + "Each picture shows two cuts of the same promo as rows of frames at the same moments: row A on top, row B below.\n"
                "Look at ONE order file only (you are told which). Answer with exactly one of A, B, tie or insufficient (when the frames do not\n"
                "show enough to decide), then the decisive defect of the cut you did not pick, in one line. Judge what is on screen, nothing else.\n")
    st.setdefault("pairs", []).append(dict(id=jid, kind="judge", draft=n, against=against, orders=orders, dir=f"ab/{jid}", created=F.now(), answers=[]))
    F.log(st, f"blind comparison {jid}: draft {n} vs draft {against}")
    F.save(pd, st)
    return jid, d


def judge(pd, jid, order, choice, defect=None, family=None):
    st = F.load(pd)
    p = pair(st, jid)
    if p["kind"] != "judge":
        raise F.FlowError(f"{jid} is the person's pick, not a judge comparison")
    if str(order) not in p["orders"]:
        raise F.FlowError("order is 1 or 2")
    if choice not in PICKS:
        raise F.FlowError(f"pick is one of {', '.join(PICKS)}")
    if not family:
        raise F.FlowError("--family is the judge's model family (claude, grok, ...)")
    p["answers"] = [x for x in p["answers"] if x["order"] != str(order)] + [dict(order=str(order), pick=choice, defect=defect, family=family, at=F.now())]
    F.log(st, f"blind comparison {jid} order {order}: {choice}")
    F.save(pd, st)
    return result(p)


def result(p):
    """{winner: draft number | None, tie, done, line}: only agreeing orders count."""
    got = {}
    for a in p["answers"]:
        o = p["orders"][a["order"]]
        got[a["order"]] = o.get(a["pick"]) if a["pick"] in ("A", "B") else a["pick"]
    done = set(got) == {"1", "2"}
    vals = list(got.values())
    if not done:
        line = f"Blind comparison of draft {p['draft']} with draft {p['against']}: {len(got)} of 2 orders judged"
        return dict(done=False, winner=None, tie=False, line=line)
    if vals[0] == vals[1] and isinstance(vals[0], int):
        return dict(done=True, winner=vals[0], tie=False, line=f"A blind judge preferred draft {vals[0]} in both orders")
    if vals == ["tie", "tie"]:
        return dict(done=True, winner=None, tie=True, line=f"A blind judge saw drafts {p['draft']} and {p['against']} as equal in both orders")
    return dict(done=True, winner=None, tie=False, line="The two orders of the blind comparison disagree, so it decides nothing")


def latest_judged(st, n, against):
    return next((p for p in reversed(st.get("pairs") or []) if p["kind"] == "judge" and p["draft"] == n and p["against"] == against), None)


def round_problems(st, r):
    if len(st["drafts"]) <= r["drafts_at_start"]:
        return []
    n, m = len(st["drafts"]), r["drafts_at_start"]
    p = latest_judged(st, n, m)
    if p is None or not result(p)["done"]:
        return [f"the new draft has not been compared blind with draft {m}, the one the person reviewed: `promo flow ab drafts`, then one fresh judge per order"]
    res = result(p)
    if res["winner"] == m:
        return [f"{res['line']}, the one the person already reviewed: the new draft is worse. Fix it, or `promo flow restore`"]
    return []


def person_view(pd, p):
    ans = p["picks"][-1] if p["picks"] else None
    return dict(id=p["id"], question=p["question"], scene=p.get("scene"), media=p["media"],
                left=F._media(os.path.join(F.fdir(pd), p["files"]["left"])), right=F._media(os.path.join(F.fdir(pd), p["files"]["right"])),
                answered=dict(side=ans["side"], by=ans["by"], at=ans["at"]) if ans else None)
