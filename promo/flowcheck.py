"""Checks that hold every draft to what the person already asked for: a note becomes a check, every later draft is measured against it,
and the scoreboard says what each draft fixed, broke or left open.

    promo flow check add --what TEXT [--scene ID] [--story A] [--kind judge|gate|look] [--gate NAME] [--source feedback|council|agent] [--by NAME]
    promo flow check mark ID --draft N --pass|--fail --evidence TEXT --family claude|grok|... [--by LENS]
    promo flow check marks --file F --draft N --family F [--by LENS]     JSON lines {"id", "status": pass|fail, "evidence"} from one reviewer
    promo flow check retire ID --why TEXT --by NAME                       only the person drops a check that came from their words
    promo flow check list [--draft N] [--json]                            the scoreboard
    promo flow draft verify N --report out/<name>-<tag>-check.json       attach the `promo check` report made for exactly this file

Kinds: `judge` is a yes/no a reviewer answers by looking at the draft (stills, the video); `gate` reads a `promo check` gate of the draft's own
report; `look` is the reference look distance (`promo flow look`), which may not move away from the references. Unmeasured never counts as a pass.
Every round also carries one control check: a plainly false statement about a scene, hidden among the judge checks. A reviewer family that marks
it as passing has its marks on that draft discarded (it was not looking), and the round cannot close until the control is marked false.
"""
from __future__ import annotations

import hashlib
import json
import os

from . import flow as F

KINDS = ("judge", "gate", "look")
SOURCES = ("feedback", "pin", "council", "agent", "assumption", "harness")
PERSON_SOURCES = ("feedback", "pin", "assumption")
LOOK_TOL = 0.02
CONTROLS = ("A submarine periscope rises out of the desk", "The caption is written in Klingon", "A studio audience applauds on screen",
            "The end card gives the phone number of a pizza shop", "A cartoon dinosaur walks across the app window",
            "The voice-over is sung as an opera aria", "Snow falls inside the app window")


def _active(st, control=True):
    """Checks that count now. A control belongs to its round only: the next round gets a new one, so old ones never pile up on later drafts."""
    last = round_key(st["rounds"][-1]) if st["rounds"] else None
    return [c for c in st.get("checks") or [] if not c.get("retired") and (not c.get("control") or (control and c["round"] == last))]


def judge_checks(st):
    """What a reviewer marks on a draft, in creation order: every active judge check, the round's control among them."""
    return [c for c in _active(st) if c["kind"] == "judge"]


def find(st, cid):
    c = next((x for x in st.get("checks") or [] if x["id"] == cid), None)
    if c is None:
        raise F.FlowError(f"no check {cid}: `promo flow check list` shows them")
    return c


def draft_of(st, n):
    if not st["drafts"]:
        raise F.FlowError("no draft is registered yet (`promo flow draft add FILE`)")
    n = n or len(st["drafts"])
    if not 1 <= n <= len(st["drafts"]):
        raise F.FlowError(f"no draft {n}: there {'is' if len(st['drafts']) == 1 else 'are'} {len(st['drafts'])}")
    return n, st["drafts"][n - 1]


def round_key(r):
    return f"{r['cycle']}.{r['n']}"


def add(pd, what, scene=None, story=None, kind="judge", gate=None, source="agent", by=None):
    """A check from the person's note (`source` feedback, pin or assumption, kept for the round that takes it), the council or the agent."""
    st = F.load(pd)
    what = " ".join((what or "").split())
    if not what:
        raise F.FlowError("a check needs --what: the thing a reviewer can see is true or not on the draft")
    if kind not in KINDS:
        raise F.FlowError(f"kind is one of {', '.join(KINDS)}")
    if source not in SOURCES:
        raise F.FlowError(f"source is one of {', '.join(SOURCES)}")
    if kind == "gate" and not gate:
        raise F.FlowError("a gate check names the `promo check` gate it reads (`--gate caption-hold`)")
    if scene and str(scene) not in {str(x) for x in F.scene_ids(pd, st)}:
        raise F.FlowError(f"no scene {scene} in the picked storyboards")
    if source in PERSON_SOURCES and by:
        by = F.human(by)
        st["person"] = by
    r = F.open_round(st)
    cid = f"c{len(st.setdefault('checks', [])) + 1}"
    st["checks"].append(dict(id=cid, what=what, scene=str(scene) if scene else None, story=story, kind=kind, gate=gate, source=source,
                             round=round_key(r) if r else None, by=by, created=F.now(), control=False, retired=None))
    F.log(st, f"check {cid}: {what}")
    F.save(pd, st)
    if source in PERSON_SOURCES:
        from . import lessons as L
        L.record("note", by or st.get("person"), F._project(pd), what)
    return cid


def add_control(pd, st, r):
    """The round's hidden control: a false statement about one scene, chosen from the project and round so the same round always gets the same one."""
    scenes = F.scene_ids(pd, st)
    h = int(hashlib.sha256(f"{F.project_id(pd)}:{round_key(r)}".encode()).hexdigest(), 16)
    cid = f"c{len(st.setdefault('checks', [])) + 1}"
    st["checks"].append(dict(id=cid, what=CONTROLS[h % len(CONTROLS)], scene=str(scenes[h % len(scenes)]) if scenes else None, story=None, kind="judge",
                             gate=None, source="harness", round=round_key(r), by=None, created=F.now(), control=True, retired=None))
    return cid


def mark(pd, cid, n, status, evidence, family, by=None):
    st = F.load(pd)
    _mark(st, cid, n, status, evidence, family, by)
    F.save(pd, st)


def _mark(st, cid, n, status, evidence, family, by):
    c = find(st, cid)
    if c.get("retired"):
        raise F.FlowError(f"check {cid} was retired")
    if c["kind"] != "judge":
        raise F.FlowError(f"check {cid} is measured, not marked: a `{c['kind']}` check reads the draft's {'check report' if c['kind'] == 'gate' else 'look distance'}")
    if status not in ("pass", "fail"):
        raise F.FlowError("status is pass or fail (leave a check you could not judge unmarked)")
    evidence = " ".join((evidence or "").split())
    if not evidence:
        raise F.FlowError("a mark needs --evidence: what on the draft shows it (a time, a still, a quote)")
    if not family:
        raise F.FlowError("a mark needs --family: the model family of the reviewer (claude, grok, ...), so two families can be told apart")
    n, d = draft_of(st, n)
    d.setdefault("marks", {}).setdefault(cid, []).append(dict(status=status, evidence=F._clip(evidence, 300), family=family, by=by, at=F.now()))
    F.log(st, f"check {cid} on draft {n}: {status} ({family})")


def marks(pd, path, n, family, by=None):
    """One reviewer's marks in one go: JSON lines {"id", "status", "evidence"}; a line it could not judge is left out."""
    st = F.load(pd)
    text = F._body(path)
    count = 0
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            m = json.loads(line)
        except json.JSONDecodeError as e:
            raise F.FlowError(f"line {i} is not JSON ({e.msg}): one object per line, {{\"id\": \"c3\", \"status\": \"pass\", \"evidence\": \"...\"}}") from None
        _mark(st, str(m.get("id")), n, m.get("status"), m.get("evidence"), family, by)
        count += 1
    F.save(pd, st)
    return count


def retire(pd, cid, why, by):
    st = F.load(pd)
    c = find(st, cid)
    if c.get("control"):
        raise F.FlowError(f"check {cid} belongs to the flow and cannot be retired")
    if not (why or "").strip():
        raise F.FlowError("say why the check no longer applies (--why), in the person's words")
    by = F.human(by)
    c["retired"] = dict(by=by, at=F.now(), why=" ".join(why.split()))
    F.log(st, f"check {cid} retired by {by}: {c['retired']['why']}")
    F.save(pd, st)


# ---- measuring a draft ---------------------------------------------------------------------------------------------------------------------
def _latest(d, cid):
    """Each family's latest mark on a check: a family that looks again replaces what it said before."""
    out = {}
    for m in (d.get("marks") or {}).get(cid, []):
        out[m["family"]] = m
    return list(out.values())


def void_families(d, st):
    """Reviewer families whose marks on this draft do not count: they called the round's control (a false statement) true."""
    ctl = {c["id"] for c in _active(st) if c.get("control")}
    return {m["family"] for cid in ctl for m in _latest(d, cid) if m["status"] == "pass"}


def _gate_status(d, gate):
    rows = [r for r in (d.get("verify") or {}).get("rows") or [] if r["gate"] == gate]
    if not rows:
        return "unmeasured", "no check report for this file names that gate"
    if any(r["status"] == "FAIL" for r in rows):
        return "fail", next(r["msg"] for r in rows if r["status"] == "FAIL")
    if all(r["msg"].startswith("skipped") for r in rows):
        return "unmeasured", rows[0]["msg"]
    return "pass", rows[0]["msg"]


def _look_status(st, i):
    mean = ((st["drafts"][i].get("look") or {}).get("mean"))
    if mean is None:
        return "unmeasured", "no look measurement for this draft (`promo flow look`)"
    best = min([x["look"]["mean"] for x in st["drafts"][:i] if (x.get("look") or {}).get("mean") is not None], default=None)
    if best is not None and mean > best + LOOK_TOL:
        return "fail", f"look distance {mean:.3f} moved away from the references (best so far {best:.3f})"
    return "pass", f"look distance {mean:.3f}" + (f" (best so far {best:.3f})" if best is not None else "")


def status(st, c, i):
    """(pass|fail|unmeasured, why) of check `c` on draft index `i`."""
    d = st["drafts"][i]
    if c["kind"] == "gate":
        return _gate_status(d, c["gate"])
    if c["kind"] == "look":
        return _look_status(st, i)
    void = set() if c.get("control") else void_families(d, st)
    ms = [m for m in _latest(d, c["id"]) if m["family"] not in void]
    fails = [m for m in ms if m["status"] == "fail"]
    if fails:
        return "fail", fails[-1]["evidence"]
    if ms:
        return "pass", ms[-1]["evidence"]
    return "unmeasured", "nobody has looked yet"


def scoreboard(st, n=None, against=None, control=False):
    """Draft n (default the latest) against draft `against` (default the one before it): every active check with its status then and now.
    `change` is fixed (now passes, did not on the earlier draft), broken (passed, now fails), open (fails or is unmeasured now) or held (passed both times)."""
    n, _ = draft_of(st, n)
    i = n - 1
    j = (against - 1) if against else i - 1
    rows = []
    for c in _active(st, control=control):
        now_, why = status(st, c, i)
        prev = status(st, c, j)[0] if j >= 0 else "none"
        change = "fixed" if now_ == "pass" and prev not in ("pass", "none") else "broken" if prev == "pass" and now_ == "fail" else "held" if now_ == "pass" else "open"
        rows.append(dict(id=c["id"], what=c["what"], scene=c.get("scene"), kind=c["kind"], source=c["source"], round=c.get("round"), status=now_, prev=prev, change=change, why=why))
    count = {k: sum(1 for r in rows if r["change"] == k) for k in ("fixed", "broken", "open", "held")}
    parts = [f"{count['fixed']} fixed", f"{count['broken']} broken", f"{count['open']} open"]
    line = f"Draft {n}: " + ", ".join(parts) if rows else f"Draft {n}: no checks yet"
    void = sorted(void_families(st["drafts"][i], st))
    return dict(draft=n, against=j + 1 if j >= 0 else None, rows=rows, line=line, void=void, **count, total=len(rows),
                passing=sum(1 for r in rows if r["status"] == "pass"))


def control_problems(st, i):
    ctl = [c for c in _active(st) if c.get("control")]
    out = []
    for c in ctl:
        if status(st, c, i)[0] != "fail":
            out.append(f"control check {c['id']} is not marked false on the new draft: every reviewer family marks every check, the control included")
    fam = void_families(st["drafts"][i], st)
    if fam:
        out.append(f"reviewer family {', '.join(sorted(fam))} called a false statement true (control check): their marks on this draft do not count until they look again")
    return out


def round_problems(pd, st, r):
    """What a round's new draft must show before it can go to the person: their notes became checks, every check was measured, nothing that
    passed on the draft they reviewed is broken now, and the control was caught."""
    out = []
    key = round_key(r)
    if not any(c["round"] == key and c["source"] in PERSON_SOURCES for c in st.get("checks") or []):
        out.append("the person's feedback is not a check yet: `promo flow check add --what \"<what must be true>\" --scene ID --source feedback` for each note")
    if len(st["drafts"]) <= r["drafts_at_start"]:
        return out
    sb = scoreboard(st, len(st["drafts"]), r["drafts_at_start"] or None)
    un = [x["id"] for x in sb["rows"] if x["status"] == "unmeasured"]
    if un:
        out.append(f"checks not measured on the new draft: {', '.join(un)} (`promo flow check mark`, `draft verify`, `promo flow look`)")
    br = [f"{x['id']} ({x['what']})" for x in sb["rows"] if x["change"] == "broken"]
    if br and r["drafts_at_start"]:
        out.append(f"the new draft breaks what the reviewed draft got right: {'; '.join(br)}. Fix it, or `promo flow restore`")
    out += control_problems(st, len(st["drafts"]) - 1)
    return out


# ---- notes pinned to a moment of a draft ---------------------------------------------------------------------------------------------------
def scene_at(pd, st, t, story=None):
    for sid, b, _ in F.boards(pd, st):
        if story and sid != story:
            continue
        for s in b.get("scenes") or []:
            if float(s["t"][0]) <= t < float(s["t"][1]):
                return sid, str(s["id"])
    return story, None


def pin(pd, n, at_s, text, by, scene=None, story=None):
    """The person's note on one moment of a draft: it becomes a check on that scene, for the round that takes it."""
    st = F.load(pd)
    n, _ = draft_of(st, n)
    if at_s is None or at_s < 0:
        raise F.FlowError("--at is the moment in seconds (0 or more)")
    if not scene:
        story, scene = scene_at(pd, st, at_s, story)
    cid = add(pd, text, scene=scene, story=story, source="pin", by=by)
    st = F.load(pd)
    c = find(st, cid)
    pid = f"n{len(st.setdefault('pins', [])) + 1}"
    st["pins"].append(dict(id=pid, draft=n, at_s=round(float(at_s), 2), scene=scene, story=story, text=c["what"], by=c["by"], check=cid, round=c["round"], created=F.now()))
    F.save(pd, st)
    return pid, scene


# ---- the look against the references ---------------------------------------------------------------------------------------------------------
LOOK_CHECK = "The look stays as close to the references as the best draft so far"


def look(pd, n=None, story=None):
    from . import look as LK
    st = F.load(pd)
    n, d = draft_of(st, n)
    refs = LK.reference_stills(pd)
    if not refs:
        raise F.FlowError("no reference cut stills (reference/<id>/cuts/*.jpg): study the references first (`promo refs add`)")
    scenes = [s for sid, b, _ in F.boards(pd, st) if not story or sid == story for s in b.get("scenes") or []]
    if not scenes:
        raise F.FlowError("no storyboard scenes to measure the draft at")
    res = LK.measure_draft(d["file"], scenes, refs, os.path.join(F.fdir(pd), "look", f"d{n}"))
    if res is None:
        raise F.FlowError(f"no frame could be read from draft {n}")
    st = F.load(pd)
    st["drafts"][n - 1]["look"] = res
    if not any(c["kind"] == "look" and not c.get("retired") for c in st.get("checks") or []):
        st.setdefault("checks", []).append(dict(id=f"c{len(st['checks']) + 1}", what=LOOK_CHECK, scene=None, story=story, kind="look", gate=None,
                                                source="harness", round=None, by=None, created=F.now(), control=False, retired=None))
    F.log(st, f"draft {n} look {res['mean']:.3f}")
    F.save(pd, st)
    return n, res


# ---- the draft's own check report ------------------------------------------------------------------------------------------------------------
def report_rows(report, sha, label):
    """The rows of a `promo check` report, only when the report measured the file with this sha256 (it lists its outputs by content)."""
    if not os.path.isfile(report or ""):
        raise F.FlowError("no check report there: run `promo check` and pass its out/<name>-<tag>-check.json")
    try:
        with open(report) as f:
            rep = json.load(f)
        rows, shas = rep["results"], {o["sha256"] for o in rep.get("outputs") or []}
        if not all({"gate", "status", "msg"} <= set(r) for r in rows):
            raise KeyError("rows")
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        raise F.FlowError("that file is not a `promo check` report (out/<name>-<tag>-check.json)") from None
    if not sha:
        raise F.FlowError(f"{label} was registered before drafts kept their fingerprint: register the file again with `promo flow draft add`")
    if sha not in shas:
        raise F.FlowError(f"that check report measured other files than {label}: run `promo check` on the build this draft is, "
                          "or register the checked output itself as the draft")
    return rows


def verify(pd, n, report):
    """Attach `promo check`'s report to draft n, only when the report measured this very file."""
    st = F.load(pd)
    n, d = draft_of(st, n)
    d["verify"] = dict(at=F.now(), report=os.path.abspath(report), rows=report_rows(report, d.get("sha"), f"draft {n}"))
    F.log(st, f"draft {n} checked")
    F.save(pd, st)
    return verify_view(d)


def verify_view(d):
    """What was checked on this exact file, in a line the person reads; skipped gates are named with their reason, never counted as passed."""
    v = d.get("verify")
    if not v:
        return dict(state="not_checked", line="Not checked on this file yet.", passed=0, warned=0, failed=0, skipped=[])
    rows = v["rows"]
    skipped = [dict(gate=r["gate"], why=r["msg"][len("skipped"):].lstrip(": ")) for r in rows if r["msg"].startswith("skipped")]
    failed = [r for r in rows if r["status"] == "FAIL"]
    warned = [r for r in rows if r["status"] == "WARN" and not r["msg"].startswith("skipped")]
    passed = [r for r in rows if r["status"] == "PASS"]
    line = f"Checked on this file: {len(passed)} passed"
    line += f", {len(warned)} {'warning' if len(warned) == 1 else 'warnings'}" if warned else ""
    line += f", {len(failed)} failed" if failed else ""
    line += ". Not checked: " + "; ".join(f"{s['gate']} ({s['why']})" for s in skipped) if skipped else "."
    return dict(state="failed" if failed else "checked", line=line, passed=len(passed), warned=len(warned), failed=len(failed), skipped=skipped,
                failures=[dict(gate=r["gate"], msg=r["msg"]) for r in failed])


def board_text(sb):
    L = [sb["line"]]
    for r in sb["rows"]:
        L.append(f"  {r['id']:<4} {r['status']:<10} {r['change']:<6} {('scene ' + r['scene']) if r['scene'] else 'whole video':<12} {r['what']}  [{r['why']}]")
    if sb["void"]:
        L.append(f"  discarded: marks from {', '.join(sb['void'])} (called the control true)")
    return "\n".join(L)
