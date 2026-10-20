"""Checks that hold every draft to what the person already asked for: a note becomes a check, every later draft is measured against it,
and the scoreboard says what each draft fixed, broke or left open.

    promo flow check add --what TEXT [--scene ID] [--story A] [--kind judge|gate|look] [--gate NAME] [--source feedback|council|agent] [--by NAME]
                         [--replaces c3,c7]     a hint that the new note supersedes older ones: the Stage offers the person to drop them
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


GATE_WORDS = {"vo-script": "voice-over against the script"}      # the person reads the line; the gate ids and reasons stay in `skipped`


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


def add(pd, what, scene=None, story=None, kind="judge", gate=None, source="agent", by=None, replaces=()):
    """A check from the person's note (`source` feedback, pin or assumption, kept for the round that takes it), the council or the agent.
    `replaces` names older checks the new one supersedes: only a hint, the person decides whether to drop them."""
    st = F.load(pd)
    replaces = [x for x in replaces or () if x]
    for x in replaces:
        if find(st, x).get("control"):
            raise F.FlowError(f"check {x} belongs to the flow and cannot be replaced")
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
                             round=round_key(r) if r else None, by=by, created=F.now(), control=False, retired=None,
                             **(dict(replaces=replaces) if replaces else {})))
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


def _last_measured(st, c, i):
    """(status, draft number) of check `c` on the latest draft before index `i` where it was measured; ("unmeasured", None) when no earlier
    draft measured it (a new note that passes now counts as fixed), ("none", None) on the first draft."""
    for k in range(i - 1, -1, -1):
        s = status(st, c, k)[0]
        if s != "unmeasured":
            return s, k + 1
    return ("unmeasured" if i else "none"), None


def scoreboard(st, n=None, against=None, control=False):
    """Draft n (default the latest) against draft `against`, or by default against each check's last measured draft (a draft nobody marked
    does not reset what an earlier one showed). `change` is fixed (now passes, did not before), broken (passed, now fails), failing (fails now),
    unchecked (not measured on this draft; `last` says what it was when it last was) or held (passes). `open` counts failing + unchecked."""
    n, _ = draft_of(st, n)
    i = n - 1
    j = (against - 1) if against else None
    rows = []
    later = {}
    for c in _active(st):
        for x in c.get("replaces") or []:
            later.setdefault(x, []).append(c["id"])
    for c in _active(st, control=control):
        now_, why = status(st, c, i)
        if j is None:
            prev, at = _last_measured(st, c, i)
        else:
            prev, at = (status(st, c, j)[0], j + 1) if j >= 0 else ("none", None)
        change = ("fixed" if now_ == "pass" and prev not in ("pass", "none") else "held" if now_ == "pass"
                  else "broken" if now_ == "fail" and prev == "pass" else "failing" if now_ == "fail" else "unchecked")
        last = dict(status=prev, draft=at) if at else None
        rows.append(dict(id=c["id"], what=c["what"], scene=c.get("scene"), kind=c["kind"], source=c["source"], round=c.get("round"), status=now_, prev=prev,
                         last=last, change=change, why=why, replaced_by=later.get(c["id"], [])))
    count = {k: sum(1 for r in rows if r["change"] == k) for k in ("fixed", "broken", "failing", "unchecked", "held")}
    count["open"] = count["failing"] + count["unchecked"]
    parts = [f"{count['fixed']} fixed", f"{count['broken']} broken", f"{count['failing']} failing", f"{count['unchecked']} not checked"]
    line = f"Draft {n}: " + ", ".join(parts) if rows else f"Draft {n}: no checks yet"
    void = sorted(void_families(st["drafts"][i], st))
    return dict(draft=n, against=against if against else None, rows=rows, line=line, void=void, **count, total=len(rows),
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


def parse_spot(text):
    """`--spot X,Y,W,H`: the area the note points at, as fractions of the frame from its top-left corner; `none` clears it."""
    if str(text).strip().lower() == "none":
        return None
    try:
        x, y, w, h = (round(float(v), 3) for v in str(text).split(","))
    except ValueError:
        raise F.FlowError("--spot is X,Y,W,H: fractions of the frame (0-1) from its top-left corner, or none") from None
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w and 0 < h and x + w <= 1.001 and y + h <= 1.001):
        raise F.FlowError("--spot must lie inside the frame: 0 <= X, Y < 1, W and H over 0, X + W and Y + H at most 1")
    return dict(x=x, y=y, w=w, h=h)


def spot_text(s):
    return f"x {s['x'] * 100:.0f}-{(s['x'] + s['w']) * 100:.0f}%, y {s['y'] * 100:.0f}-{(s['y'] + s['h']) * 100:.0f}% of the frame"


def _spot_still(pd, video, at_s, spot):
    """The draft's frame at the note's moment with its spot outlined, as a new file in flow/pins/ (_keep_still names it after its check)."""
    import subprocess

    from PIL import ImageDraw

    from .contact import _grab
    out = os.path.join(F.fdir(pd), "pins", "new.jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out[:-4] + ".grab.png"
    try:
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video]).decode())
        im = _grab(video, min(at_s, max(0.0, dur - 0.1)), tmp)          # a note on the very end: past the last frame ffmpeg writes nothing
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        raise F.FlowError(f"could not read the frame at {at_s:g} s of {os.path.basename(video)} to mark the note's spot") from None
    os.remove(tmp)
    W, H = im.size
    box = [spot["x"] * W, spot["y"] * H, (spot["x"] + spot["w"]) * W, (spot["y"] + spot["h"]) * H]
    k = max(2, W // 480)
    d = ImageDraw.Draw(im)
    d.rectangle([box[0] - k, box[1] - k, box[2] + k, box[3] + k], outline=(0, 0, 0), width=k)       # a dark edge keeps it visible on light frames
    d.rectangle(box, outline=(255, 64, 160), width=k)
    im.save(out, quality=88)
    return out


def _keep_still(pd, src, cid, move=True):
    """flow/pins/<check>.jpg: one marked frame per check, so a retired check keeps the picture it was about."""
    import shutil
    dest = os.path.join(F.fdir(pd), "pins", f"{cid}.jpg")
    if move:
        os.replace(src, dest)
    elif src != dest:
        shutil.copyfile(src, dest)
    return os.path.relpath(dest, F.fdir(pd))


def pin(pd, n, at_s, text, by, scene=None, story=None, spot=None):
    """The person's note on one moment of a draft: it becomes a check on that scene, for the round that takes it. `spot` (parse_spot) marks
    what on the frame the note is about: kept on the pin and its check, with the marked frame as flow/pins/<check>.jpg."""
    st = F.load(pd)
    n, d = draft_of(st, n)
    if at_s is None or at_s < 0:
        raise F.FlowError("--at is the moment in seconds (0 or more)")
    if not scene:
        story, scene = scene_at(pd, st, at_s, story)
    img = _spot_still(pd, d["file"], at_s, spot) if spot else None          # before the check: a frame that cannot be read leaves no half note
    cid = add(pd, text, scene=scene, story=story, source="pin", by=by)
    st = F.load(pd)
    c = find(st, cid)
    marked = dict(spot=spot, still=_keep_still(pd, img, cid)) if spot else {}
    c.update(marked)
    pid = f"n{len(st.setdefault('pins', [])) + 1}"
    st["pins"].append(dict(id=pid, draft=n, at_s=round(float(at_s), 2), scene=scene, story=story, text=c["what"], by=c["by"], check=cid,
                           round=c["round"], created=F.now(), **marked))
    F.save(pd, st)
    return pid, scene


def _live_pin(st, pid):
    p = next((x for x in st.get("pins") or [] if x["id"] == pid and not x.get("removed")), None)
    if p is None:
        raise F.FlowError(f"no pinned note {pid}: the Stage shows each note's id on the draft it is pinned to")
    return p


KEEP = "keep"


def pin_edit(pd, pid, by, text=None, at_s=None, spot=KEEP):
    """The person rewords, moves or re-marks a pinned note (`spot`: KEEP, None to clear, or a parse_spot area). A new wording, scene or spot
    retires the old note's check (its marks stay with it: "this" now means something else) and makes a new one for the round that takes it;
    a move inside the same scene keeps the check."""
    if text is None and at_s is None and spot == KEEP:
        raise F.FlowError("say what changes: --text, --at, --spot or several")
    if at_s is not None and at_s < 0:
        raise F.FlowError("--at is the moment in seconds (0 or more)")
    st = F.load(pd)
    p = _live_pin(st, pid)
    text = p["text"] if text is None else " ".join(text.split())
    story, scene = (p.get("story"), p.get("scene")) if at_s is None else scene_at(pd, st, at_s, p.get("story"))
    spot = p.get("spot") if spot == KEEP else spot
    at = p["at_s"] if at_s is None else round(float(at_s), 2)
    regrab = spot and (spot != p.get("spot") or at != p["at_s"] or not p.get("still"))
    img = _spot_still(pd, draft_of(st, p["draft"])[1]["file"], at, spot) if regrab else None
    old = p.get("still")
    cid = p["check"]
    if text != p["text"] or scene != p.get("scene") or spot != p.get("spot"):
        retire(pd, cid, f"the person changed pinned note {pid}", by)
        cid = add(pd, text, scene=scene, story=story, source="pin", by=by)
        st = F.load(pd)
        p = _live_pin(st, pid)
    c = find(st, cid)
    marked = dict(spot=spot, still=_keep_still(pd, img, cid) if img else _keep_still(pd, os.path.join(F.fdir(pd), old), cid, move=False)) if spot else {}
    for x in (c, p):
        x.pop("spot", None)
        x.pop("still", None)
        x.update(marked)
    p.update(at_s=at, scene=scene, story=story, text=c["what"], check=cid, round=c["round"], edited=F.now())
    F.log(st, f"pin {pid} edited")
    F.save(pd, st)
    return scene


def pin_remove(pd, pid, by):
    """The person takes a pinned note back: its check is retired and the note leaves the draft."""
    st = F.load(pd)
    p = _live_pin(st, pid)
    retire(pd, p["check"], f"the person removed pinned note {pid}", by)
    st = F.load(pd)
    _live_pin(st, pid)["removed"] = dict(by=F.human(by), at=F.now())
    F.log(st, f"pin {pid} removed")
    F.save(pd, st)


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
    line = f"Automatic checks on this file: {len(passed)} passed"
    line += f", {len(warned)} {'warning' if len(warned) == 1 else 'warnings'}" if warned else ""
    line += f", {len(failed)} failed" if failed else ""
    line += ". Not checked on this computer: " + ", ".join(GATE_WORDS.get(s["gate"], s["gate"].replace("-", " ")) for s in skipped) + "." if skipped else "."
    return dict(state="failed" if failed else "checked", line=line, passed=len(passed), warned=len(warned), failed=len(failed), skipped=skipped,
                failures=[dict(gate=r["gate"], msg=r["msg"]) for r in failed])


def board_text(sb):
    L = [sb["line"]]
    for r in sb["rows"]:
        was = f" (was {r['last']['status']} on draft {r['last']['draft']})" if r["change"] == "unchecked" and r.get("last") else ""
        by = f" (may be replaced by {', '.join(r['replaced_by'])})" if r.get("replaced_by") else ""
        L.append(f"  {r['id']:<4} {r['status']:<10} {r['change']:<9} {('scene ' + r['scene']) if r['scene'] else 'whole video':<12} {r['what']}  [{r['why']}]{was}{by}")
    if sb["void"]:
        L.append(f"  discarded: marks from {', '.join(sb['void'])} (called the control true)")
    return "\n".join(L)
