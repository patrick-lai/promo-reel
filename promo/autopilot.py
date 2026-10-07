"""Let the agent keep improving a draft on its own, inside a time limit the person set, until every check passes, and say honestly when
it stops for any other reason. Small choices it makes on the way are cards the person can overturn, not questions that stall the work.

    promo flow autopilot start --minutes 60 --by NAME      the person's go (from the Stage); drafts or review stage only
    promo flow autopilot pass begin | pass end             around each internal pass (council, one batch, build, measure)
    promo flow autopilot replan --note TEXT                after two passes that fixed nothing: one written new plan, then one more try
    promo flow autopilot pause | resume | stop [--by NAME]
    promo flow autopilot status [--json]
    promo flow assume add TEXT [--scene ID]                a choice made without asking ("Using the calm piano track")
    promo flow assume overturn ID --text TEXT --by NAME    the person's answer: it becomes a check for the next round

States: running, paused, done (every check passes on the latest draft and its check report has no FAIL), blocked (no progress after a replan),
out_of_time (the next pass would not fit: a pass may start only when 1.25 x the average pass so far fits in the time left), stopped.
Paused time does not count. The person's 5 review rounds are not used: these passes happen before they see the next draft.
"""
from __future__ import annotations

import datetime

from . import flow as F
from . import flowcheck as FC

FIT = 1.25
STALL = 2


def _t(at):
    return datetime.datetime.fromisoformat(at).timestamp()


def _ap(st):
    a = st.get("autopilot")
    if not a:
        raise F.FlowError("no autopilot run: the person starts one from the Stage (`promo flow autopilot start --minutes M --by NAME`)")
    return a


def used_s(a):
    end = _t(F.now()) if a["state"] == "running" else _t(a.get("paused_at") or a.get("ended") or F.now())
    return max(0.0, end - _t(a["started"]) - a.get("paused_s", 0.0))


def start(pd, minutes, by):
    st = F.load(pd)
    by = F.human(by)
    if st["stage"] not in ("drafts", "review"):
        raise F.FlowError("autopilot works on drafts: it starts once the person has confirmed generation")
    if not 5 <= minutes <= 24 * 60:
        raise F.FlowError("minutes is between 5 and 1440")
    if (st.get("autopilot") or {}).get("state") in ("running", "paused"):
        raise F.FlowError("an autopilot run is already on: stop it first")
    st["autopilot"] = dict(by=by, minutes=minutes, started=F.now(), state="running", paused_s=0.0, paused_at=None, passes=[], replans=[], ended=None, why=None)
    F.log(st, f"autopilot {minutes} min started by {by}")
    F.save(pd, st)


def _end(a, state, why):
    a["state"], a["why"], a["ended"] = state, why, F.now()


def _goal(st):
    """(met, line): every check passes on the latest draft and its check report has no FAIL."""
    if not st["drafts"]:
        return False, "no draft yet"
    sb = FC.scoreboard(st)
    v = FC.verify_view(st["drafts"][-1])
    if v["state"] != "checked":
        return False, "the latest draft has no clean check report on its own file"
    if sb["total"] and sb["passing"] == sb["total"]:
        return True, f"all {sb['total']} checks pass on draft {sb['draft']}"
    return False, f"{sb['passing']} of {sb['total']} checks pass on draft {sb['draft']}"


def begin(pd):
    """Start a pass: its number, or None when the next pass would not fit in the time left (the run then ends as out of time, saved, so the
    Stage says so)."""
    st = F.load(pd)
    a = _ap(st)
    if a["state"] != "running":
        raise F.FlowError(f"autopilot is {a['state'].replace('_', ' ')}: no new pass")
    if a["passes"] and a["passes"][-1].get("end") is None:
        raise F.FlowError("the last pass has not ended: `promo flow autopilot pass end`")
    if a.get("needs_replan"):
        raise F.FlowError(f"{STALL} passes fixed nothing: write a new plan first (`promo flow autopilot replan --note \"...\"`)")
    done = [p for p in a["passes"] if p.get("end")]
    left = a["minutes"] * 60 - used_s(a)
    need = FIT * sum(_t(p["end"]) - _t(p["start"]) for p in done) / len(done) if done else 0
    if left <= 0 or need > left:
        _end(a, "out_of_time", f"the next pass needs about {need / 60:.0f} min and {max(left, 0) / 60:.0f} min are left" if done else "the time is used up")
        F.log(st, "autopilot out of time")
        F.save(pd, st)
        return None
    a["passes"].append(dict(start=F.now(), end=None, draft_at_start=len(st["drafts"])))
    F.save(pd, st)
    return len(a["passes"])


def end(pd):
    st = F.load(pd)
    a = _ap(st)
    p = a["passes"][-1] if a["passes"] else None
    if not p or p.get("end"):
        raise F.FlowError("no pass is running: `promo flow autopilot pass begin`")
    p["end"] = F.now()
    if a["state"] != "running":                   # stopped or paused while the pass ran: the person's stop stands, nothing is judged
        F.save(pd, st)
        return a["state"], f"pass ended after the run was {a['state']}"
    if len(st["drafts"]) > p["draft_at_start"]:
        sb = FC.scoreboard(st, len(st["drafts"]), p["draft_at_start"] or None)
        p.update(fixed=sb["fixed"], broken=sb["broken"], open=sb["open"])
    else:
        p.update(fixed=0, broken=0, open=None)
    met, line = _goal(st)
    if met:
        _end(a, "done", line)
    else:
        stalled = len(a["passes"]) >= STALL and all(not x.get("fixed") for x in a["passes"][-STALL:])
        if stalled and len(a["replans"]) >= 1 and not p.get("fixed"):
            _end(a, "blocked", f"no verified progress after a new plan ({line})")
        elif stalled and not a["replans"]:
            a["needs_replan"] = True
    F.log(st, f"autopilot pass {len(a['passes'])} ended: {line}")
    F.save(pd, st)
    return a["state"], line


def replan(pd, note):
    st = F.load(pd)
    a = _ap(st)
    if not (note or "").strip():
        raise F.FlowError("a new plan needs --note: what changes in the approach, not a retry of the same")
    a["replans"].append(dict(at=F.now(), note=" ".join(note.split())))
    a["needs_replan"] = False
    F.save(pd, st)


def control(pd, op, by=None):
    st = F.load(pd)
    a = _ap(st)
    if op == "pause" and a["state"] == "running":
        a["state"], a["paused_at"] = "paused", F.now()
    elif op == "resume" and a["state"] == "paused":
        a["paused_s"] += _t(F.now()) - _t(a["paused_at"])
        a["state"], a["paused_at"] = "running", None
    elif op == "stop" and a["state"] in ("running", "paused"):
        if a["state"] == "paused":
            a["paused_s"] += _t(F.now()) - _t(a["paused_at"])
            a["paused_at"] = None
        _end(a, "stopped", f"stopped by {F.human(by)}" if by else "stopped")
    else:
        raise F.FlowError(f"cannot {op} an autopilot run that is {a['state'].replace('_', ' ')}")
    F.log(st, f"autopilot {op}")
    F.save(pd, st)


def view(st):
    a = st.get("autopilot")
    if not a:
        return None
    used = used_s(a) / 60
    met, goal = _goal(st)
    label = dict(running="Working until every check passes", paused="Paused", done="Every check passes", blocked="Stopped: no progress",
                 out_of_time="Stopped: out of time", stopped="Stopped")[a["state"]]
    line = f"{label} · {min(used, a['minutes']):.0f} of {a['minutes']} min · {goal}"
    if a["state"] in ("blocked", "out_of_time", "stopped") and a.get("why"):
        line += f". {a['why'][0].upper()}{a['why'][1:]}"
    return dict(state=a["state"], minutes=a["minutes"], used_min=round(used, 1), left_min=round(max(0, a["minutes"] - used), 1), passes=len(a["passes"]),
                by=a["by"], line=F._clip(line, 200), goal_met=met)


# ---- assumptions ---------------------------------------------------------------------------------------------------------------------------
def assume(pd, text, scene=None):
    st = F.load(pd)
    text = " ".join((text or "").split())
    if not text:
        raise F.FlowError("say what you chose and how to change it (\"Using the calm piano track; say so to swap\")")
    aid = f"a{len(st.setdefault('assumptions', [])) + 1}"
    st["assumptions"].append(dict(id=aid, text=F._clip(text, 200), scene=scene, at=F.now(), overturned=None))
    F.log(st, f"assumption {aid}: {text}")
    F.save(pd, st)
    return aid


def overturn(pd, aid, text, by):
    st = F.load(pd)
    by = F.human(by)
    a = next((x for x in st.get("assumptions") or [] if x["id"] == aid), None)
    if a is None:
        raise F.FlowError(f"no assumption {aid}")
    if not (text or "").strip():
        raise F.FlowError("--text is what the person wants instead, in their words")
    a["overturned"] = dict(by=by, text=" ".join(text.split()), at=F.now())
    F.save(pd, st)
    return FC.add(pd, f"{text.strip()} (instead of: {a['text']})", scene=a.get("scene"), source="assumption", by=by)
