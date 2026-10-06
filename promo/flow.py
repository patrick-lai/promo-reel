"""The gated production flow: the person stays in the loop at every step, the council checks intent at every round.

    discover -> scripts -> pick -> storyboard -> assets -> keyframes -> confirm -> drafts -> review (<= 5 rounds) -> final
                (3+, council   (human)  (start+end    (every asset    (the rest)   (human)   (first    (council: intent + web
                 spars 1-2x)            frames/scene)  shown, mocks ok)                        drafts)   research each round)

State lives in `<project>/flow/flow.json` (+ scripts/, boards/, council/, rounds/, assets.json, dashboard.html). Gates are HUMAN approvals
(`promo flow approve <gate> --by NAME`, an agent name is refused, same rule as `promo brief confirm`) and go stale when the thing approved
changes afterwards. `promo flow status --json` is what the session UI reads: the checklist, the blockers and an `ask` payload (question + options)
for the AskUserQuestion widget; `promo flow board` writes the dashboard page (stepper, scripts, storyboards, assets, drafts, rounds) to show.

    promo flow init <name> --intent TEXT          start (also creates the locked brief with the user's exact words)
    promo flow status [--json]                    where we are, what blocks, what to ask the person next
    promo flow discover --style TEXT [--ref URL ...] | --no-refs
    promo flow script add ID --title T --logline L --file F ;  promo flow council scripts|storyboard|assets --file F
    promo flow approve scripts-picked --picks A [B] --by NAME ; promo flow approve storyboard-approved|assets-approved|final-confirmation|draft-approved --by NAME
    promo flow asset add|list ;  promo flow needs          what to generate / capture next (missing frames and assets, with prompts)
    promo flow frames [--story B] [--scene ID]    MAKE the missing storyboard frames as real images (grok / codex CLI); a text slate is not a frame
    promo flow asset make [--id X ...]            MAKE a real sample of each planned asset (concept still, short clip, audio excerpt) to look at / listen to
    promo flow make                               frames, then asset samples: everything the person has to see before approving
    promo flow advance                            move on when the checks pass and the gate is approved
    promo flow draft add FILE ; promo flow round start --feedback TEXT ; promo flow round close --council F --research F
    promo flow final add FILE ; promo flow revise --feedback TEXT      after the final: more feedback, council again
    promo flow share detect                       is Atlassian Artifacts / Loom available to this twg user (the snapshot offers uploads only when it is)
    promo flow share draft|final [N] --to artifacts|loom --by NAME [--access private|open|shared]
                                                  the person's upload of draft N (default the latest) as <project>_draft_N, refreshed in place when edited;
                                                  a final as <project>_final_vN (every `final add` is the next version)
    promo flow board [--out F]                    write the dashboard HTML
    promo flow snapshot [--out F]                 the promo-flow mod state: `commissionctl mod publish promo-flow --file F` (mods/promo-flow/)
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys

from . import assetplan as AP
from . import brief as BR
from . import previews as PV
from . import share as SH
from . import storyboard as SB
from .home import resolve as _resolve

STAGES = ["discover", "scripts", "pick", "storyboard", "assets", "keyframes", "confirm", "drafts", "review", "final"]
LABEL = dict(discover="Style & references", scripts="Scripts", pick="Pick stories", storyboard="Storyboard", assets="Asset plan",
             keyframes="Keyframes", confirm="Final confirmation", drafts="First drafts", review="Review rounds", final="Final")
GATE_OF = dict(pick="scripts-picked", storyboard="storyboard-approved", assets="assets-approved", confirm="final-confirmation", review="draft-approved")
MAX_ROUNDS = 5
MIN_SCRIPTS = 3
URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
STYLES = [("Calm product hero", "A steady voice-over walks through the real app. Simple captions, cuts that land on the beat."), ("Dialogue film", "People talking, with the app on their screens. Real speech carries the story."),
          ("Horizon film", "Fast cuts of the real app building to one proof moment, ending on a calm dawn card."), ("Kinetic anime opening", "Bold title cards and quick, punchy cuts timed to the music.")]


class FlowError(Exception):
    pass


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def fdir(pd):
    return os.path.join(pd, "flow")


def _sha(*paths):
    h = hashlib.sha256()
    for p in paths:
        try:
            h.update(open(p, "rb").read())
        except OSError:
            h.update(b"-")
    return h.hexdigest()[:12]


def load(pd):
    p = os.path.join(fdir(pd), "flow.json")
    if not os.path.isfile(p):
        raise FlowError(f"no flow at {p}: `promo flow init <name> --intent \"...\"`")
    return json.load(open(p))


def save(pd, st):
    os.makedirs(fdir(pd), exist_ok=True)
    with open(os.path.join(fdir(pd), "flow.json"), "w") as f:
        json.dump(st, f, indent=2)


def log(st, what):
    st.setdefault("log", []).append(dict(at=now(), what=what))


NOTE_KINDS = ("capture", "render", "voice", "music", "check", "plan", "other")
ACTIVITY_MAX = 200


def note(pd, text, kind="other", done=False):
    """One plain line about what the agent is doing right now ("Rendering screenshots for scene 4"). Shown in the Stage and on the chat card
    while a stage is working; every note is one dot in the activity heatmap (`done` = a finished step, drawn solid)."""
    text = " ".join((text or "").split())
    if not text:
        raise FlowError("a note needs text, e.g. `promo flow note \"Taking snapshots of the real app\" --kind capture`")
    if kind not in NOTE_KINDS:
        raise FlowError(f"kind must be one of {', '.join(NOTE_KINDS)}")
    st = load(pd)
    st.setdefault("activity", []).append(dict(at=now(), text=_clip(text, 120), kind=kind, done=bool(done)))
    del st["activity"][:-ACTIVITY_MAX]
    save(pd, st)


def _note(pd, text, kind, done=False):
    """Best-effort note from inside a long step: never fails the step."""
    try:
        note(pd, text, kind, done)
    except (FlowError, OSError, ValueError):
        pass


def _activity(st):
    """History dots, oldest first: the agent's notes plus the flow's own milestones (stage moves, approvals, drafts, rounds)."""
    out = [dict(at=x["at"], text=x["what"], kind="milestone", done=True) for x in st.get("log") or [] if x["what"] != "init"]
    out += [dict(at=x["at"], text=x["text"], kind=x.get("kind", "other"), done=bool(x.get("done"))) for x in st.get("activity") or []]
    out.sort(key=lambda x: x["at"])
    return out[-ACTIVITY_MAX:]


def init(pd, intent, force=False):
    p = os.path.join(fdir(pd), "flow.json")
    if os.path.exists(p) and not force:
        raise FlowError(f"{p} exists (use --force)")
    if not intent.strip():
        raise FlowError("--intent is required: the person's request, pasted exactly")
    os.makedirs(pd, exist_ok=True)
    if not BR.exists(pd):
        BR.init(pd, intent=intent)
    st = dict(version=1, stage="discover", intent=intent, discover=None, scripts=[], councils={}, picks=[], gates={}, drafts=[], rounds=[],
              cycle=1, finals=[], log=[])
    log(st, "init")
    save(pd, st)
    return st


# ---- helpers -------------------------------------------------------------------------------------------------------------------------
def boards(pd, st):
    out = []
    for sid in st["picks"]:
        d = os.path.join(fdir(pd), "boards", sid)
        if os.path.isfile(SB.board_path(d)):
            out.append((sid, SB.load(d), d))
    return out


def scene_ids(pd, st):
    return [s["id"] for _, b, _ in boards(pd, st) for s in b.get("scenes", [])]


def gate_hash(pd, st, gate):
    f = fdir(pd)
    if gate == "scripts-picked":
        return hashlib.sha256(json.dumps(st["picks"]).encode()).hexdigest()[:12]
    bj = [SB.board_path(d) for _, _, d in boards(pd, st)]
    if gate == "storyboard-approved":
        return _sha(*bj)
    if gate == "assets-approved":
        return _sha(AP.plan_path(f))
    if gate == "final-confirmation":
        return _sha(*bj, AP.plan_path(f))
    if gate == "draft-approved":
        return hashlib.sha256(json.dumps(st["drafts"][-1:]).encode()).hexdigest()[:12]
    return ""


def gate_ok(pd, st, gate):
    g = st["gates"].get(gate)
    return bool(g) and g.get("hash") == gate_hash(pd, st, gate)


def human(name):
    if not name or BR.AGENT_NAMES.search(name):
        raise FlowError("`--by` must be the name of the person who decided this (an agent cannot approve or upload on its own behalf): ask them")
    return name


def open_round(st):
    r = st["rounds"][-1] if st["rounds"] else None
    return r if r and not r.get("closed") else None


def cycle_rounds(st):
    return [r for r in st["rounds"] if r["cycle"] == st["cycle"]]


def round_problems(pd, st, r, council, research):
    out = []
    if len(st["drafts"]) <= r["drafts_at_start"]:
        out.append("no new draft since the round started: register it with `promo flow draft add`")
    urls = set(URL_RE.findall(open(research).read())) if research and os.path.isfile(research) else set()
    if len(urls) < 3:
        out.append(f"research file needs >= 3 distinct source URLs (articles, example videos of the topic done well): has {len(urls)}")
    ic = None
    if council and os.path.isfile(council):
        ic = BR.parse_intent_check(open(council).read())
    if ic is None:
        out.append("council file has no `intent-check:` line from the Intent & Reference lens (evals/council-flow.md)")
    else:
        try:
            want = BR.intent_sha(BR.load(pd))
        except BR.BriefError as e:
            want = ""
            out.append(str(e))
        if want and not (ic["sha"] and (want.startswith(ic["sha"]) or ic["sha"].startswith(want))):
            out.append(f"intent-check quotes intent_sha={ic['sha']}, the brief's is {want}: the lens read a different text")
        if ic["verdict"] is None:
            out.append("intent-check has no verdict=YES|PARTIAL|NO")
    return out, ic


# ---- stage checks ----------------------------------------------------------------------------------------------------------------------
def checks(pd, st, stage=None):
    """[(ok, text)] for the stage: what must hold before `advance`."""
    stage = stage or st["stage"]
    f = fdir(pd)
    R = []
    if stage == "discover":
        d = st.get("discover")
        R.append((bool(d and d.get("style")), "style the person wants is recorded (`promo flow discover --style ...`)"))
        R.append((bool(d and (d.get("refs") or d.get("no_refs"))), "references recorded, or the person said they have none (`--ref URL` / `--no-refs`)"))
    elif stage == "scripts":
        sc = st["scripts"]
        R.append((len(sc) >= MIN_SCRIPTS, f"{len(sc)} scripts written (need >= {MIN_SCRIPTS}, genuinely different angles)"))
        R.append((all(os.path.isfile(os.path.join(f, s["file"])) for s in sc) and bool(sc), "every script file exists"))
        R.append((len(st["councils"].get("scripts", [])) >= 1, f"council sparred over the scripts ({len(st['councils'].get('scripts', []))} of 1-2 rounds recorded)"))
    elif stage == "pick":
        R.append((gate_ok(pd, st, "scripts-picked"), "the person picked the stories to progress (`approve scripts-picked --picks A [B] --by NAME`)"))
    elif stage == "storyboard":
        bs = boards(pd, st)
        R.append((len(bs) == len(st["picks"]) and bool(bs), "a board.json for every picked story"))
        for sid, b, d in bs:
            pr = SB.problems(b)
            R.append((not pr, f"board {sid} is well-formed" + (f": {pr[0]}" + (f" (+{len(pr) - 1} more)" if len(pr) > 1 else "") if pr else "")))
            mi = SB.missing(b, d, ("start", "end"))
            R.append((not mi, f"board {sid}: every scene has its START and END frame image" + (f" ({len(mi)} missing)" if mi else "")))
        R.append((gate_ok(pd, st, "storyboard-approved"), "the person approved the storyboard (`approve storyboard-approved --by NAME`)"))
    elif stage == "assets":
        plan = AP.load(f)
        pr = AP.problems(plan, scene_ids(pd, st), pd)
        R.append((not pr, "asset plan covers every scene" + (f": {pr[0]}" + (f" (+{len(pr) - 1} more)" if len(pr) > 1 else "") if pr else "")))
        nop = unpreviewed(pd)
        R.append((not nop, "every asset has a real preview to look at or play" + (f" ({len(nop)} without: `promo flow asset make`)" if nop else "")))
        R.append((gate_ok(pd, st, "assets-approved"), "the person reviewed every asset and approved the plan (`approve assets-approved --by NAME`)"))
    elif stage == "keyframes":
        mi = [m for sid, b, d in boards(pd, st) for m in SB.missing(b, d, ("start", "end", "frames"))]
        R.append((not mi, f"all keyframes generated ({len(mi)} missing)"))
        pr = AP.problems(AP.load(f), scene_ids(pd, st), pd, final=True)
        R.append((not pr, "every planned asset is real (no mocks / todos left)" + (f": {pr[0]}" if pr else "")))
    elif stage == "confirm":
        R.append((gate_ok(pd, st, "final-confirmation"), "final confirmation from the person (`approve final-confirmation --by NAME`)"))
    elif stage == "drafts":
        ds = st["drafts"]
        R.append((bool(ds) and all(os.path.isfile(d["file"]) for d in ds), "a first draft is registered and exists (`promo flow draft add FILE`)"))
    elif stage == "review":
        R.append((open_round(st) is None, "no round is open (close it with the council's intent-check + research)"))
        R.append((gate_ok(pd, st, "draft-approved"), "the person approved the draft (`approve draft-approved --by NAME`)"))
    elif stage == "final":
        R.append((bool(st["finals"]), "final output registered (`promo flow final add FILE`)"))
    return R


def advance(pd):
    st = load(pd)
    if st["stage"] == "final":
        raise FlowError("already final: `promo flow revise --feedback TEXT` for more iteration")
    bad = [t for ok, t in checks(pd, st) if not ok]
    if bad:
        raise FlowError("cannot leave `%s`:\n  - %s" % (st["stage"], "\n  - ".join(bad)))
    nxt = STAGES[STAGES.index(st["stage"]) + 1]
    st["stage"] = nxt
    log(st, f"advance -> {nxt}")
    save(pd, st)
    return nxt


def approve(pd, gate, by, picks=None, note=""):
    st = load(pd)
    by = human(by)
    if gate not in GATE_OF.values():
        raise FlowError(f"gate must be one of {', '.join(GATE_OF.values())}")
    stage = [s for s, g in GATE_OF.items() if g == gate][0]
    if STAGES.index(stage) > STAGES.index(st["stage"]):
        raise FlowError(f"gate `{gate}` belongs to stage `{stage}`; the flow is at `{st['stage']}`")
    if gate == "scripts-picked":
        ids = [s["id"] for s in st["scripts"]]
        if not picks or any(p not in ids for p in picks):
            raise FlowError(f"--picks must be one or more of {ids}")
        st["picks"] = list(picks)
    elif gate == "draft-approved":
        if open_round(st):
            raise FlowError("a round is open: close it first")
        if not st["drafts"]:
            raise FlowError("no draft yet")
    else:
        pre = [t for ok, t in checks(pd, st, stage) if not ok and "approved" not in t and "confirmation" not in t]
        if pre:
            raise FlowError("not ready for approval:\n  - " + "\n  - ".join(pre))
    st["gates"][gate] = dict(by=by, at=now(), hash=gate_hash(pd, st, gate), note=note)
    log(st, f"approved {gate} by {by}")
    save(pd, st)


def add_script(pd, sid, title, logline, file):
    st = load(pd)
    if not os.path.isfile(file):
        raise FlowError(f"no such file {file}")
    dest = os.path.join(fdir(pd), "scripts", f"{sid}.md")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(file, dest)
    st["scripts"] = [s for s in st["scripts"] if s["id"] != sid] + [dict(id=sid, title=title, logline=logline, file=f"scripts/{sid}.md")]
    log(st, f"script {sid}")
    save(pd, st)


def add_council(pd, kind, file, note=""):
    st = load(pd)
    if kind not in ("scripts", "storyboard", "assets"):
        raise FlowError("kind is scripts|storyboard|assets (rounds use `round close`)")
    if not os.path.isfile(file) or len(open(file).read().strip()) < 200:
        raise FlowError("council file missing or too thin (< 200 chars): record each lens's findings and what the editor changed")
    n = len(st["councils"].get(kind, [])) + 1
    dest = os.path.join(fdir(pd), "council", f"{kind}-{n}.md")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(file, dest)
    st["councils"].setdefault(kind, []).append(dict(n=n, file=f"council/{kind}-{n}.md", at=now(), note=note))
    log(st, f"council {kind} #{n}")
    save(pd, st)
    return n


def add_draft(pd, file, note=""):
    st = load(pd)
    if STAGES.index(st["stage"]) < STAGES.index("drafts"):
        raise FlowError("drafts start after the final confirmation")
    if not os.path.isfile(file):
        raise FlowError(f"no such file {file}")
    st["drafts"].append(dict(file=os.path.abspath(file), note=note, at=now(), cycle=st["cycle"]))
    st["gates"].pop("draft-approved", None)
    log(st, f"draft {os.path.basename(file)}")
    save(pd, st)


def round_start(pd, feedback):
    st = load(pd)
    if st["stage"] != "review":
        raise FlowError("rounds run in the `review` stage (advance from `drafts` first)")
    if open_round(st):
        raise FlowError("a round is already open")
    if not feedback.strip():
        raise FlowError("--feedback is required: the person's words, verbatim")
    n = len(cycle_rounds(st)) + 1
    if n > MAX_ROUNDS:
        raise FlowError(f"{MAX_ROUNDS} rounds used in this cycle: ask the person to approve the draft, or to restate the direction (`promo flow revise`)")
    st["rounds"].append(dict(cycle=st["cycle"], n=n, feedback=feedback, started=now(), drafts_at_start=len(st["drafts"])))
    st["gates"].pop("draft-approved", None)
    log(st, f"round {st['cycle']}.{n} start")
    save(pd, st)
    return n


def round_close(pd, council, research, note=""):
    st = load(pd)
    r = open_round(st)
    if not r:
        raise FlowError("no round is open")
    pr, ic = round_problems(pd, st, r, council, research)
    if pr:
        raise FlowError("round cannot close:\n  - " + "\n  - ".join(pr))
    d = os.path.join(fdir(pd), "rounds", f"{r['cycle']}-{r['n']}")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "feedback.md"), "w").write(r["feedback"] + "\n")
    shutil.copyfile(council, os.path.join(d, "council.md"))
    shutil.copyfile(research, os.path.join(d, "research.md"))
    r["closed"] = dict(at=now(), verdict=ic["verdict"], scores=ic.get("scores", {}), note=note, dir=os.path.relpath(d, pd))
    log(st, f"round {r['cycle']}.{r['n']} closed verdict={ic['verdict']}")
    save(pd, st)
    return r


def add_final(pd, file):
    st = load(pd)
    if st["stage"] != "final":
        raise FlowError("not at `final`: approve the draft and `advance`")
    if not os.path.isfile(file):
        raise FlowError(f"no such file {file}")
    st["finals"].append(dict(file=os.path.abspath(file), at=now()))
    log(st, "final " + os.path.basename(file))
    save(pd, st)


def _project(pd):
    return os.path.basename(os.path.normpath(pd))


def share_detect(pd, force=False):
    """Probe Artifacts and Loom for this twg user and keep the answer (an hour) in the flow; stays quiet until something is there to share."""
    st = load(pd)
    if (force or st["drafts"] or st["finals"]) and SH.refresh(st, now(), force):
        save(pd, st)
    return st


def share_upload(pd, kind, n, dest, by, access=None):
    """The person's upload of draft/final N (default the latest). Returns (n, record, created|updated|unchanged)."""
    st = load(pd)
    by = human(by)
    items = st["drafts"] if kind == "draft" else st["finals"]
    if not items:
        raise FlowError(f"no {kind} is registered yet")
    n = n or len(items)
    if not 1 <= n <= len(items):
        raise FlowError(f"no {kind} {n}: there {'is' if len(items) == 1 else 'are'} {len(items)}")
    item = items[n - 1]
    project = _project(pd)
    rec, what = SH.upload(st, project, kind, n, item["file"], dest, access, SH.describe(kind, n, project, st["intent"], item.get("note", "")), now())
    if what != "unchanged":
        rec["by"] = by
        log(st, f"{kind} {n} {what} on {SH.LABEL[dest]} by {by}")
        save(pd, st)
    return n, rec, what


def revise(pd, feedback):
    st = load(pd)
    if st["stage"] != "final":
        raise FlowError("revise is for after the final")
    if not feedback.strip():
        raise FlowError("--feedback is required: the person's words, verbatim")
    st["cycle"] += 1
    st["stage"] = "review"
    st["gates"].pop("draft-approved", None)
    log(st, f"revise cycle {st['cycle']}")
    save(pd, st)
    return round_start(pd, feedback)


def discover(pd, style, refs, no_refs):
    st = load(pd)
    st["discover"] = dict(style=style, refs=refs or [], no_refs=bool(no_refs), at=now())
    b = None
    try:
        b = BR.load(pd)
    except BR.BriefError:
        pass
    if b is not None:
        have = {r.get("url") or r.get("path") for r in b.get("references", [])}
        for u in refs or []:
            if u not in have:
                b.setdefault("references", []).append(dict(id=re.sub(r"\W+", "-", u)[-24:].strip("-").lower() or "ref", url=u, why="(add the person's words about it)"))
        BR.save(pd, b)
    log(st, "discover")
    save(pd, st)


# ---- needs / ask / status ----------------------------------------------------------------------------------------------------------------
def unpreviewed(pd):
    """Planned assets the person cannot open or play yet (no real file and no sample)."""
    samples = PV.load_samples(fdir(pd))
    return [a for a in AP.load(fdir(pd)) if not PV.has_sample(a, pd, samples)]


def needs(pd, st=None):
    st = st or load(pd)
    out = []
    for sid, b, d in boards(pd, st):
        which = ("start", "end") if STAGES.index(st["stage"]) <= STAGES.index("storyboard") else ("start", "end", "frames")
        for m in SB.missing(b, d, which):
            out.append(dict(kind="keyframe", story=sid, scene=m["scene"], which=m["which"], out=m["image"], prompt=m["prompt"]))
    for a in AP.load(fdir(pd)):
        s = AP.state(a, pd)
        if s == "todo" or (s == "mock" and STAGES.index(st["stage"]) >= STAGES.index("keyframes")):
            out.append(dict(kind="asset", id=a["id"], asset_kind=a["kind"], source=a["source"], how=a["how"], out=os.path.join(pd, a.get("path") or a["id"])))
    for a in unpreviewed(pd):
        out.append(dict(kind="preview", id=a["id"], asset_kind=a["kind"], source=a["source"], how=a["how"], then=f"promo flow asset make --id {a['id']}"))
    return out


def ask(pd, st):
    """The question the session should put to the person next (AskUserQuestion payload), or None when the agent has work to do first."""
    stage = st["stage"]
    ok = all(o for o, _ in checks(pd, st))
    if stage == "discover" and not (st.get("discover") or {}).get("style"):
        return dict(header="Style", multiSelect=False, question="What style of content do you want?",
                    options=[dict(label=a, description=b) for a, b in STYLES[:4]])
    if stage == "scripts" and ok:
        return dict(header="Scripts", multiSelect=True, question="Which script(s) should go to storyboards?",
                    options=[dict(label=f"{s['id']}: {s['title']}", description=s["logline"]) for s in st["scripts"][:4]])
    if stage == "storyboard" and ok is False and all(o for o, t in checks(pd, st) if "approved" not in t):
        return dict(header="Storyboard", multiSelect=False, question="Happy with the storyboard (each scene's start and end frame), or want changes?",
                    options=[dict(label="Approve storyboard", description="go on to the asset plan"), dict(label="Changes", description="say what to change per scene")])
    if stage == "assets" and all(o for o, t in checks(pd, st) if "approved" not in t):
        return dict(header="Assets", multiSelect=False, question="Looked at and listened to every asset sample (pictures, clips, music, voice, sounds)? Approve the plan?",
                    options=[dict(label="Approve asset plan", description="generate the remaining keyframes"), dict(label="Changes", description="swap, add or drop assets")])
    if stage == "confirm":
        return dict(header="Go?", multiSelect=False, question="Generate the first drafts now?",
                    options=[dict(label="Yes, generate drafts", description="all keyframes and assets are real"), dict(label="Not yet", description="more changes first")])
    if stage == "review" and open_round(st) is None:
        n = len(cycle_rounds(st))
        q = f"All {MAX_ROUNDS} rounds are used. Approve the draft, or restate the direction." if n >= MAX_ROUNDS else "Watched the draft? Approve it, or send feedback."
        return dict(header="Draft", multiSelect=False, question=q,
                    options=[dict(label="Approve", description="submit as final"), dict(label="Feedback", description="tell me what to change; the council checks intent first")])
    if stage == "final":
        return dict(header="Final", multiSelect=False, question="Final is in. Want more changes?", options=[dict(label="Done", description="stop here"), dict(label="More feedback", description="council reviews again")])
    return None


def hints(pd, st):
    s = st["stage"]
    return dict(
        discover="Ask the person (AskUserQuestion) what style they want and for any reference videos/material; record with `promo flow discover`. Study references with `promo refs add`.",
        scripts=f"Write {MIN_SCRIPTS}+ scripts with different angles; run the council (evals/council-flow.md, scripts lens set) 1-2 rounds and record with `promo flow council scripts`; `promo flow script add`. Then ask which to progress.",
        pick="Ask which script(s) to progress (multi-select); record the answer with `approve scripts-picked --picks ... --by NAME`.",
        storyboard="Per picked story write flow/boards/<id>/board.json, then `promo flow frames` MAKES every scene's START and END frame as a real image (a text slate does not count), `promo flow board`, SHOW the page, iterate until they approve.",
        assets="List every asset (screenshots, pictures, recordings, music, voice, sfx) with `promo flow asset add`, then `promo flow asset make` so each has a real sample to look at or hear (a placeholder is not a preview), publish, plan it out with the person.",
        keyframes="Make the remaining keyframes (`promo flow make`) and replace every mock and sample with the real file (`promo flow needs`), then advance.",
        confirm="Show the final summary (board + assets) and get the explicit go for drafts.",
        drafts="Build the first drafts (promo build, draft encode), register with `promo flow draft add`, advance, SHOW them.",
        review="Take the person's feedback verbatim: `round start`; run the council (lens 0 intent + web research of the topic and examples of good videos); apply one batch; build one draft; `round close`. Max %d rounds." % MAX_ROUNDS,
        final="Deliver; keep iterating on feedback with `promo flow revise` (council again).")[s]


def status(pd):
    st = load(pd)
    ch = checks(pd, st)
    return dict(stage=st["stage"], label=LABEL[st["stage"]], cycle=st["cycle"], rounds_used=len(cycle_rounds(st)), rounds_max=MAX_ROUNDS,
                checks=[dict(ok=o, text=t) for o, t in ch], ready=all(o for o, _ in ch), next=hints(pd, st), ask=ask(pd, st),
                needs=needs(pd, st), picks=st["picks"], gates={k: dict(by=v["by"], at=v["at"], fresh=gate_ok(pd, st, k)) for k, v in st["gates"].items()},
                dashboard=os.path.join(fdir(pd), "dashboard.html"))


GATE_PRIMARY = dict(style="Choose style", pick="Pick scripts", approve="Review", confirm="Confirm go", draft="Watch draft")
GATE_CARD = {"storyboard-approved": "Review storyboard", "assets-approved": "Review assets"}
MAX_PICKS = 2
NUM = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine"}
BEAT_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)")


def _stale(pd, st):
    """Stages whose gate was approved earlier but the thing approved changed since (and which the flow has reached)."""
    cur = STAGES.index(st["stage"])
    return [dict(id=sg, gate=g, label=LABEL[sg]) for sg, g in GATE_OF.items() if STAGES.index(sg) <= cur and g in st["gates"] and not gate_ok(pd, st, g)]


def _gate(pd, st):
    a = ask(pd, st)
    stage = st["stage"]
    stale = _stale(pd, st)
    past = [x for x in stale if x["id"] != stage]
    if past:
        x = past[0]
        return dict(gate=x["gate"], kind="approve", question=f"{x['label']} changed after you approved it. Approve it again?", approve_label="Approve again",
                    changes_label="Send changes", options=[], stale=True, stage=x["id"])
    if stage == "pick" and a is None and st["scripts"] and not gate_ok(pd, st, "scripts-picked"):
        a = dict(question="Which script(s) should go to storyboards?", options=[dict(label=f"{s['id']}: {s['title']}", description=s["logline"]) for s in st["scripts"][:4]])
    if stage in ("scripts", "pick") and a is not None:
        return dict(gate="scripts-picked", kind="pick", question=a["question"], approve_label="Continue", changes_label="Send changes", options=a["options"],
                    picks_min=1, picks_max=MAX_PICKS, stage=stage)
    kinds = dict(discover=("style", "style"), storyboard=("storyboard-approved", "approve"), assets=("assets-approved", "approve"),
                 confirm=("final-confirmation", "confirm"), review=("draft-approved", "draft"))
    if a is None or stage not in kinds:
        return None
    labels = dict(style=("Use this style", "Describe another"), approve=("Approve", "Send changes"), confirm=("Generate drafts", "Not yet"), draft=("Approve draft", "Send feedback"))
    g, k = kinds[stage]
    out = dict(gate=g, kind=k, question=a["question"], approve_label=labels[k][0], changes_label=labels[k][1], options=a["options"] if k == "style" else [], stage=stage)
    if any(x["id"] == stage for x in stale):
        out["stale"] = True
        if k in ("approve", "confirm"):
            out["approve_label"] = "Approve again"
    return out


def _media(path):
    """A file the mod can show: `{"$file": <absolute path>}` (the host resolves it to an upload), or None when there is no such file."""
    return {"$file": os.path.abspath(path)} if path and os.path.isfile(path) else None


def _clip(text, n):
    text = " ".join(str(text).split())
    if len(text) <= n:
        return text
    cut = text[:n - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut[n // 2:] else cut).rstrip(" ,;:") + "…"      # at a word boundary: "shell chips read AI…" cut mid-word is unreadable


def _all_frames(pd, st, which):
    tot = miss = 0
    for _, b, d in boards(pd, st):
        for s in b.get("scenes") or []:
            tot += len(list(SB._frames(s, which)))
        miss += len(SB.missing(b, d, which))
    return tot, miss


def plain_checks(pd, st, stage=None):
    """[(ok, sentence)]: the same conditions as `checks()`, worded for the person (what is true or still open), no commands, no counts of internals."""
    stage = stage or st["stage"]
    f = fdir(pd)
    R = []
    n = len(st["scripts"])
    if stage == "discover":
        d = st.get("discover") or {}
        R += [(bool(d.get("style")), "Style chosen"), (bool(d.get("refs") or d.get("no_refs")), "References added, or none to add")]
    elif stage == "scripts":
        k = len(st["councils"].get("scripts", []))
        R += [(n >= MIN_SCRIPTS, f"{n} of {MIN_SCRIPTS} scripts drafted" if n < MIN_SCRIPTS else f"{NUM.get(n, n)} scripts drafted"),
              (k >= 1, "Scripts reviewed by the council" if k else "Scripts not reviewed by the council yet")]
    elif stage == "pick":
        R.append((gate_ok(pd, st, "scripts-picked"), "You picked the stories to take forward" if gate_ok(pd, st, "scripts-picked") else "You pick the stories to take forward"))
    elif stage == "storyboard":
        bs = boards(pd, st)
        R.append((len(bs) == len(st["picks"]) and bool(bs), "A storyboard for every picked story"))
        for sid, b, d in bs:
            pr = SB.problems(b)
            R.append((not pr, f"Story {sid} is complete" if not pr else f"Story {sid}: {pr[0]}"))
        _, miss = _all_frames(pd, st, ("start", "end"))
        R.append((not miss, "Every scene has its start and end frame" if not miss else f"{miss} {'frame' if miss == 1 else 'frames'} not made yet"))
        R.append((gate_ok(pd, st, "storyboard-approved"), "You approved the storyboard" if gate_ok(pd, st, "storyboard-approved") else "You approve the storyboard"))
    elif stage == "assets":
        pr = AP.problems(AP.load(f), scene_ids(pd, st), pd)
        R.append((not pr, "Every scene has its assets planned" if not pr else pr[0][0].upper() + pr[0][1:]))
        nop = unpreviewed(pd)
        R.append((not nop, "Every asset has a preview you can open or play" if not nop else f"{len(nop)} {'asset has' if len(nop) == 1 else 'assets have'} no preview yet"))
        R.append((gate_ok(pd, st, "assets-approved"), "You approved the asset plan" if gate_ok(pd, st, "assets-approved") else "You review every asset and approve the plan"))
    elif stage == "keyframes":
        tot, miss = _all_frames(pd, st, ("start", "end", "frames"))
        R.append((not miss, f"All stories: all {tot} keyframes made" if not miss else f"All stories: {tot - miss} of {tot} keyframes made, {miss} left"))
        sts = [AP.state(x, pd) for x in AP.load(f)]
        m, t = sts.count("mock"), sts.count("todo")
        left = [x for x in (f"{m} {'stand-in' if m == 1 else 'stand-ins'} to swap for the real thing" if m else "", f"{t} still to make" if t else "") if x]
        R.append((not (m or t), "Every planned asset has its file." if not (m or t) else "Before the real run: " + ", ".join(left)))
    elif stage == "confirm":
        R.append((gate_ok(pd, st, "final-confirmation"), "You confirmed generation" if gate_ok(pd, st, "final-confirmation") else "You confirm generation"))
    elif stage == "drafts":
        ok = bool(st["drafts"]) and all(os.path.isfile(x["file"]) for x in st["drafts"])
        R.append((ok, "First draft is ready" if ok else "Waiting for the first draft"))
    elif stage == "review":
        R += [(open_round(st) is None, "No round is in progress" if open_round(st) is None else "A round is in progress"),
              (gate_ok(pd, st, "draft-approved"), "You approved the draft" if gate_ok(pd, st, "draft-approved") else "You approve the draft")]
    elif stage == "final":
        fin_ok = bool(st["finals"]) and all(os.path.isfile(x["file"]) for x in st["finals"])
        R.append((fin_ok, "Final file delivered" if fin_ok else "A final is registered, but its file is missing" if st["finals"] else "Waiting for the final file"))
    return R


def _status(pd, st, pc):
    stage = st["stage"]
    if stage == "scripts":
        n = len(st["scripts"])
        return f"Writing scripts: {n} of {MIN_SCRIPTS} drafted" if n < MIN_SCRIPTS else f"{NUM.get(n, n)} scripts are drafted and being reviewed"
    if stage == "drafts":
        return "Waiting for the first draft." if not st["drafts"] else "First draft is ready. Moving on."
    r = open_round(st)
    if stage == "review" and r:
        return f"Round {r['n']} is in progress: applying your feedback."
    bad = [t for ok, t in pc if not ok]
    return bad[0] if bad else f"{LABEL[stage]} is done. Moving on."


def _finished(st, stale):
    """Delivered = at the final stage, a final is registered, every registered file is on disk, and no approval is stale."""
    return st["stage"] == "final" and bool(st["finals"]) and all(os.path.isfile(x["file"]) for x in st["finals"]) and not stale


def _summary(pd, st, gate, pc, rounds_used):
    stage = st["stage"]
    cur = STAGES.index(stage)
    stale = _stale(pd, st)
    finished = _finished(st, stale)
    prog = dict(done=len(STAGES) if finished else cur, total=len(STAGES))
    picked = [x["title"] for x in st["scripts"] if x["id"] in st["picks"]]
    title = _clip(("Promo: " + picked[0]) if picked else ((st["intent"].split(".")[0] or "Production").strip() or "Production"), 40)
    primary = None
    if finished:
        status, badge = "Final delivered.", "done"
    elif gate:
        status = _clip(gate["question"], 140)
        badge = "attention" if stage == "review" and rounds_used >= MAX_ROUNDS else "waiting"
        primary = "Approve again" if gate.get("stale") else GATE_CARD.get(gate["gate"]) or GATE_PRIMARY.get(gate["kind"])
    else:
        status, badge = _clip(_status(pd, st, pc), 140), "working"
        last = (st.get("activity") or [{}])[-1]
        if last.get("text") and last["at"] >= (st.get("log") or [{}])[-1].get("at", ""):
            status = _clip(("Done: " if last.get("done") else "Now: ") + last["text"], 140)
        cap = [x for x in AP.load(os.path.join(pd, "flow")) if x.get("kind") in ("recording", "screenshot") and AP.state(x, pd) in ("mock", "todo")] if stage == "keyframes" else []
        if cap:
            status, badge = f"Your turn: {len(cap)} {'recording' if len(cap) == 1 else 'recordings'} to capture from the real app. See the Assets tab, then send them to the agent.", "waiting"
    return dict(title=title, status=status, badge=badge, progress=prog, **({"primary": primary[:24]} if primary else {}))


def _beats(path):
    out = []
    try:
        for line in open(path).read().splitlines():
            m = BEAT_RE.match(line)
            if m:
                out.append(_clip(m.group(1), 140))
            if len(out) == 2:
                break
    except OSError:
        pass
    return out


def _keyframe_label(boards_, n):
    """('Scene 03 \u00b7 mid frame 1', 't=14.5 s' | '')"""
    for sid, b, _ in boards_:
        if sid != n["story"]:
            continue
        for s in b.get("scenes") or []:
            if s["id"] != n["scene"]:
                continue
            w = n["which"]
            if w in ("start", "end"):
                return f"Scene {s['id']} \u00b7 {w} frame", ""
            i = int(w[w.index("[") + 1:-1])
            t = (s.get("frames") or [])[i].get("t")
            return f"Scene {s['id']} \u00b7 mid frame {i + 1}", (f"t={t:g} s" if isinstance(t, (int, float)) else "")
    return f"Scene {n['scene']} \u00b7 {n['which']}", ""


KIND_PREFIX = dict(rec="", ui="", vo="Voice", sfx="Sound effect", plate="Plate", card="Card", music="Music")


def _asset_label(a):
    """A human title for an asset: its explicit `label`, else the first clause of `how` when that reads as a title, else its id made readable
    (`rec-ticket-form` -> "Ticket form"). A stub clause ("Capture ?demo=1", a cut-off parenthesis) is shared by several assets, so it is no title."""
    if a.get("label"):
        return _clip(a["label"], 48)
    first = re.split(r"[.:;\u2014]|, ", a.get("how") or "", maxsplit=1)[0].strip()
    if 12 <= len(first) <= 60 and first.count("(") == first.count(")") and not re.search(r"[?=]", first):
        return first[0].upper() + first[1:]
    head, _, rest = a["id"].partition("-")
    if rest and head in KIND_PREFIX:
        words = " ".join(x for x in (KIND_PREFIX[head], re.sub(r"[-_]+", " ", rest)) if x)
        return words[0].upper() + words[1:]
    return re.sub(r"[-_]+", " ", a["id"]).strip().capitalize()


def snapshot(pd):
    """The mod state of `mods/promo-flow` (`commissionctl mod publish promo-flow --file F`): `summary` for the chat card, `steps`, the gate, and every
    media file as a `{"$file": abs path}` object the host turns into an upload. Schema: mods/promo-flow/README.md."""
    st = load(pd)
    f = fdir(pd)
    picks = set(st["picks"])
    scripts = [dict(id=s["id"], title=s["title"], logline=s["logline"], picked=s["id"] in picks, verdict=None, beats=_beats(os.path.join(f, s["file"]))) for s in st["scripts"]]
    bl = []
    bds = boards(pd, st)
    for sid, b, d in bds:
        sc = []
        for s in b.get("scenes", []):
            def fr(label, x):
                x = x or {}
                p = os.path.join(d, x["image"]) if x.get("image") else ""
                slate = os.path.isfile(p) and SB.is_slate(p)
                return dict(label=label, path=None if slate else _media(p), slate=slate, prompt=x.get("prompt"))
            src = s.get("source")
            sc.append(dict(id=s["id"], beat=s.get("beat", ""), start_s=float(s["t"][0]), end_s=float(s["t"][1]), action=s.get("action", ""), caption=s.get("caption") or None,
                           voice=s.get("vo") or None, sound=s.get("sound") or None, camera=s.get("camera") or None, proof=s.get("proof") or None,
                           source=src if src in ("real", "generated", "mock") else "other", generated=src == "generated", start=fr("start", s.get("start")), end=fr("end", s.get("end")),
                           frames=[fr(f"t={x.get('t', '?')}s", x) for x in s.get("frames") or []]))
        bl.append(dict(id=sid, title=b.get("title", sid), logline=b.get("logline", ""), aspect=b.get("aspect", "16:9"),
                       duration_s=float(max((s["end_s"] for s in sc), default=0)), scenes=sc))
    valid = {s["id"] for b in bl for s in b["scenes"]}
    assets = []
    samples = PV.load_samples(f)
    for a in AP.load(f):
        sm = samples.get(a["id"]) or {}
        assets.append(dict(id=a["id"], label=_asset_label(a), kind=a["kind"], source=a["source"], state=AP.state(a, pd), scenes=[x for x in a.get("scenes", []) if x in valid], how=a.get("how", ""),
                           licence=a.get("licence"), note=a.get("note"), path=_media(os.path.join(pd, a["path"])) if a.get("path") else None,
                           sample=_media(os.path.join(pd, sm["path"])) if sm.get("path") else None, sample_note=sm.get("note")))
    rounds = []
    for r in st["rounds"]:
        c = r.get("closed")
        research = []
        if c:
            rp = os.path.join(pd, c["dir"], "research.md")
            research = sorted(set(URL_RE.findall(open(rp).read()))) if os.path.isfile(rp) else []
        rounds.append(dict(cycle=r["cycle"], n=r["n"], feedback=r["feedback"], verdict=(c or {}).get("verdict", "").lower() or None, open=not c,
                           scores=(c or {}).get("scores") or {}, research=research, drafts_at_start=r.get("drafts_at_start", 0)))
    after = {}
    for r in rounds:
        after.setdefault(r["drafts_at_start"], f"round {r['n']}" if r["cycle"] == 1 else f"round {r['cycle']}.{r['n']}")
    rel = lambda p: os.path.relpath(p, pd) if p.startswith(pd) else os.path.basename(p)  # noqa: E731
    proj = _project(pd)
    drafts = [dict(id=f"d{i + 1}", label=f"Draft {i + 1}", note=d.get("note") or None, path=_media(d["file"]), name=os.path.basename(d["file"]), rel=rel(d["file"]),
                   after=after.get(i, ""), **SH.view(st, proj, "draft", i + 1, d["file"])) for i, d in enumerate(st["drafts"])]
    finals = [dict(id=f"f{i + 1}", label=f"Final {i + 1}", path=_media(x["file"]), name=os.path.basename(x["file"]), rel=rel(x["file"]),
                   **SH.view(st, proj, "final", i + 1, x["file"])) for i, x in enumerate(st["finals"])]
    councils = {k: _clip(open(os.path.join(f, v[-1]["file"])).read(), 900) for k, v in st["councils"].items() if v and os.path.isfile(os.path.join(f, v[-1]["file"]))}
    pc = plain_checks(pd, st)
    gate = _gate(pd, st)
    nd = needs(pd, st)
    to_make = []
    for n in nd:
        if n["kind"] == "keyframe":
            label, at = _keyframe_label(bds, n)
            to_make.append(dict(kind="keyframe", id=f"{n['story']}/{n['scene']}/{n['which']}", story=n["story"], scene=n["scene"], which=n["which"],
                                label=label, at=at, detail=n.get("prompt") or ""))
        elif n["kind"] == "asset":
            to_make.append(dict(kind="asset", id=n["id"], label=n["id"], detail=n.get("how") or "", asset_kind=n.get("asset_kind"), source=n.get("source")))
    used = len(cycle_rounds(st))
    cur = STAGES.index(st["stage"])
    stale = _stale(pd, st)
    stale_ids = {x["id"] for x in stale}
    finished = _finished(st, stale)
    steps = []
    for i, sg in enumerate(STAGES):
        state = "current" if i == cur and not finished else "done" if (i < cur or finished) else "todo"
        if sg in stale_ids and i < cur:
            state = "stale"
        steps.append(dict(id=sg, label=LABEL[sg], state=state, stale=sg in stale_ids))
    since = (st.get("log") or [{}])[-1].get("at")
    return dict(summary=_summary(pd, st, gate, pc, used), title=_clip((st["intent"].split(".")[0] or "Production"), 80), intent=st["intent"],
                stage=st["stage"], stage_label=LABEL[st["stage"]], stage_since=since, cycle=st["cycle"], rounds_used=used, rounds_max=MAX_ROUNDS, steps=steps,
                stale_steps=stale,
                style=(st.get("discover") or {}) and dict(style=st["discover"].get("style"), refs=st["discover"].get("refs", []), no_refs=st["discover"].get("no_refs", False)) or None,
                scripts=scripts, councils=councils, boards=bl, assets=assets, to_make=to_make, drafts=drafts, finals=finals, rounds=rounds,
                share=dict(destinations=[dict(id=d, label=SH.LABEL[d], note=SH.NOTE[d], in_place=d == "artifacts") for d in SH.available(st)]),
                checks=[dict(ok=o, text=t) for o, t in pc], gate=gate, activity=_activity(st),
                approvals={k: dict(by=v["by"], at=v["at"], fresh=gate_ok(pd, st, k)) for k, v in st["gates"].items()})


def status_text(s):
    L = [f"stage: {s['label']}  ({s['stage']})   cycle {s['cycle']}   rounds {s['rounds_used']}/{s['rounds_max']}"]
    L += [f"  [{'x' if c['ok'] else ' '}] {c['text']}" for c in s["checks"]]
    L.append(f"next: {s['next']}")
    if s["needs"]:
        L.append(f"to make: {len(s['needs'])} (promo flow needs)")
    if s["ready"]:
        L.append("ready: `promo flow advance`")
    if s["ask"]:
        L.append(f"ask the person: {s['ask']['question']}  [{' | '.join(o['label'] for o in s['ask']['options'])}]")
    return "\n".join(L)


# ---- real previews ---------------------------------------------------------------------------------------------------------------------
def _report(what, made, failed):
    print(f"{what}: {len(made)} made, {len(failed)} failed")
    for label, why in failed:
        print(f"  {label}: {why}", file=sys.stderr)
    return 1 if failed else 0


def make_frames(pd, story, scene, which, force, provider, jobs, limit=None):
    st = load(pd)
    bds = [b for b in boards(pd, st) if not story or b[0] == story]
    if not bds:
        raise FlowError(f"no board{' ' + story if story else ''} to make frames for")
    look = (st.get("discover") or {}).get("style") or ""
    n = len(PV.frame_targets(bds, scene, which, force)[:limit])
    print(f"making {n} frames with the generator CLI ({jobs} at a time, ~25 s each)")
    _note(pd, f"Drawing {n} storyboard frames" + (f" for scene {scene}" if scene else ""), "render")
    made, failed = PV.make_frames(bds, look, scene, which, force, provider, jobs, limit)
    _note(pd, f"Drew {len(made)} storyboard frames" + (f", {len(failed)} failed" if failed else ""), "render", True)
    return _report("frames", made, failed)


def make_assets(pd, ids, force, provider, jobs=3):
    st = load(pd)
    plan = AP.load(fdir(pd))
    if ids and (unknown := set(ids) - {x["id"] for x in plan}):
        raise FlowError(f"no such asset: {', '.join(sorted(unknown))}")
    _note(pd, "Making a sample of every asset: stills, short clips, voices, music", "voice")
    made, failed = PV.make_samples(plan, pd, boards(pd, st), ids, force, provider, jobs=jobs)
    _note(pd, f"Made {len(made)} asset samples" + (f", {len(failed)} failed" if failed else ""), "voice", True)
    return _report("asset samples", made, failed)


# ---- dashboard -------------------------------------------------------------------------------------------------------------------------
def dashboard(pd, out=None):
    import html as H
    st = load(pd)
    esc = H.escape
    cur = STAGES.index(st["stage"])
    steps = "".join(f'<li class="{"done" if i < cur else "cur" if i == cur else ""}"><span>{i + 1}</span>{esc(LABEL[s])}</li>' for i, s in enumerate(STAGES))
    scripts = "".join(
        f'<div class="sc{" pk" if s["id"] in st["picks"] else ""}"><b>{esc(s["id"])}: {esc(s["title"])}</b>{"<i>picked</i>" if s["id"] in st["picks"] else ""}<p>{esc(s["logline"])}</p></div>'
        for s in st["scripts"])
    drafts = "".join(f"<li>{esc(os.path.basename(d['file']))} <span class='meta'>{esc(d.get('note', ''))}</span></li>" for d in st["drafts"])
    rounds = "".join(
        f"<tr><td>{r['cycle']}.{r['n']}</td><td>{esc(r['feedback'][:140])}</td><td>{esc((r.get('closed') or {}).get('verdict', 'open'))}</td></tr>" for r in st["rounds"])
    extra = (f'<h2>Scripts</h2><div class="scs">{scripts}</div>' if scripts else "")
    extra_css = ("""
.steps{display:flex;gap:4px;list-style:none;padding:0;margin:14px 0;flex-wrap:wrap}.steps li{font-size:12px;border:1px solid var(--line);border-radius:14px;padding:2px 10px 2px 4px;color:var(--mute);display:flex;gap:6px;align-items:center}
.steps li span{background:var(--line);border-radius:50%;width:18px;height:18px;display:inline-flex;align-items:center;justify-content:center;font-size:11px}
.steps li.done{color:var(--ok);border-color:var(--ok)}.steps li.done span{background:var(--ok);color:#fff}.steps li.cur{color:var(--ink);border-color:var(--acc);font-weight:600}.steps li.cur span{background:var(--acc);color:#fff}
.scs{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}.sc{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}.sc.pk{border-color:var(--acc)}.sc i{font-size:11px;color:var(--acc);margin-left:8px}.sc p{margin:4px 0 0;color:var(--mute);font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px}td{border-top:1px solid var(--line);padding:5px 8px;vertical-align:top}""")
    bsec = "".join(SB.board_section(b, d) for _, b, d in boards(pd, st))
    asec = AP.section(AP.load(fdir(pd)), pd) if AP.load(fdir(pd)) else ""
    tail = (f"<h2>Drafts</h2><ul>{drafts}</ul>" if drafts else "") + (f"<h2>Rounds</h2><table>{rounds}</table>" if rounds else "")
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Promo Flow</title>'
           f'<style>{SB.CSS}{extra_css}</style></head><body><div class="wrap"><h1>Promo flow</h1><p class="log">{esc(st["intent"][:300])}</p><ol class="steps">{steps}</ol>'
           f"{extra}{bsec}{asec}{tail}</div></body></html>")
    out = out or os.path.join(fdir(pd), "dashboard.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, "w").write(doc)
    return out


# ---- CLI ---------------------------------------------------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog="promo flow", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=_resolve, default=None, help="project dir or bare name (default: the cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def P(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("--project", type=_resolve, default=argparse.SUPPRESS)
        return p
    p = P("init"); p.add_argument("name", nargs="?"); p.add_argument("--intent", required=True); p.add_argument("--force", action="store_true")
    p = P("status"); p.add_argument("--json", action="store_true")
    P("advance")
    P("needs").add_argument("--json", action="store_true")
    p = P("discover"); p.add_argument("--style", default=""); p.add_argument("--ref", action="append"); p.add_argument("--no-refs", action="store_true")
    p = P("script"); p.add_argument("action", choices=["add"]); p.add_argument("id"); p.add_argument("--title", required=True); p.add_argument("--logline", required=True); p.add_argument("--file", required=True)
    p = P("council"); p.add_argument("kind"); p.add_argument("--file", required=True); p.add_argument("--note", default="")
    p = P("approve"); p.add_argument("gate"); p.add_argument("--by", required=True); p.add_argument("--picks", nargs="*"); p.add_argument("--note", default="")
    p = P("asset"); p.add_argument("action", choices=["add", "list", "make"]); p.add_argument("--id", action="append"); p.add_argument("--kind"); p.add_argument("--scenes", default="")
    p.add_argument("--source"); p.add_argument("--how", default=""); p.add_argument("--path"); p.add_argument("--licence"); p.add_argument("--note"); p.add_argument("--label")
    p.add_argument("--fetch-url"); p.add_argument("--sha256"); p.add_argument("--force", action="store_true"); p.add_argument("--provider", default="auto"); p.add_argument("--jobs", type=int, default=3)
    p = P("frames"); p.add_argument("--story"); p.add_argument("--scene"); p.add_argument("--which", nargs="+", default=["start", "end"], choices=["start", "end", "frames"])
    p.add_argument("--force", action="store_true"); p.add_argument("--jobs", type=int, default=3); p.add_argument("--provider", default="auto"); p.add_argument("--limit", type=int)
    p = P("make"); p.add_argument("--which", nargs="+", default=["start", "end"], choices=["start", "end", "frames"]); p.add_argument("--jobs", type=int, default=3)
    p.add_argument("--force", action="store_true"); p.add_argument("--provider", default="auto")
    p = P("draft"); p.add_argument("action", choices=["add"]); p.add_argument("file"); p.add_argument("--note", default="")
    p = P("round"); p.add_argument("action", choices=["start", "close"]); p.add_argument("--feedback", default=""); p.add_argument("--council"); p.add_argument("--research"); p.add_argument("--note", default="")
    p = P("final"); p.add_argument("action", choices=["add"]); p.add_argument("file")
    P("revise").add_argument("--feedback", required=True)
    p = P("note"); p.add_argument("text"); p.add_argument("--kind", default="other", choices=NOTE_KINDS); p.add_argument("--done", action="store_true")
    p = P("board"); p.add_argument("--out")
    p = P("snapshot"); p.add_argument("--out")
    p = P("share"); p.add_argument("what", choices=["detect", "draft", "final"]); p.add_argument("n", nargs="?", type=int)
    p.add_argument("--to", choices=SH.DESTS); p.add_argument("--by"); p.add_argument("--access", choices=SH.ACCESS)
    a = ap.parse_args(argv)
    pd = a.project or os.getcwd()
    if a.cmd == "init" and a.name and not a.project:
        from . import home
        pd = os.path.join(home.projects_dir(), a.name) if os.sep not in a.name else a.name
    try:
        if a.cmd == "init":
            init(pd, a.intent, a.force)
            print(f"flow started in {pd}/flow ; brief locked with the exact words.\n" + status_text(status(pd)))
        elif a.cmd == "status":
            s = status(pd)
            print(json.dumps(s, indent=2) if a.json else status_text(s))
        elif a.cmd == "advance":
            print("stage ->", advance(pd))
        elif a.cmd == "needs":
            n = needs(pd)
            print(json.dumps(n, indent=2) if a.json else "\n".join(f"{x['kind']}: {x.get('scene') or x.get('id')} {x.get('which', x.get('asset_kind', ''))} -> {x['out']}\n    {x.get('prompt') or x.get('how')}" for x in n) or "nothing to make")
        elif a.cmd == "discover":
            discover(pd, a.style, a.ref, a.no_refs)
        elif a.cmd == "script":
            add_script(pd, a.id, a.title, a.logline, a.file)
        elif a.cmd == "council":
            print(f"council {a.kind} #{add_council(pd, a.kind, a.file, a.note)} recorded")
        elif a.cmd == "approve":
            approve(pd, a.gate, a.by, a.picks, a.note)
            print(f"{a.gate} approved by {a.by}")
        elif a.cmd == "asset":
            if a.action == "list":
                for x in AP.load(fdir(pd)):
                    print(f"{x['id']:<20} {x['kind']:<10} {x['source']:<9} {AP.state(x, pd):<6} scenes {','.join(x['scenes'])}  {x['how']}")
            elif a.action == "make":
                return make_assets(pd, a.id, a.force, a.provider, a.jobs)
            else:
                if not (a.id and len(a.id) == 1 and a.kind and a.source):
                    raise FlowError("asset add needs one --id and --kind --source --scenes --how")
                st = load(pd)
                rec = dict(id=a.id[0], kind=a.kind, source=a.source, scenes=[s for s in a.scenes.split(",") if s], how=a.how)
                for k in ("path", "licence", "note", "label", "fetch_url", "sha256"):
                    if getattr(a, k):
                        rec[k] = getattr(a, k)
                AP.save(fdir(pd), AP.upsert(AP.load(fdir(pd)), rec))
                st["gates"].pop("assets-approved", None)
                save(pd, st)
        elif a.cmd == "frames":
            return make_frames(pd, a.story, a.scene, tuple(a.which), a.force, a.provider, a.jobs, a.limit)
        elif a.cmd == "make":
            frames_rc = make_frames(pd, None, None, tuple(a.which), a.force, a.provider, a.jobs)
            return make_assets(pd, None, a.force, a.provider, a.jobs) or frames_rc          # a failed frame must not stop the audio samples
        elif a.cmd == "draft":
            add_draft(pd, a.file, a.note)
        elif a.cmd == "round":
            if a.action == "start":
                print(f"round {round_start(pd, a.feedback)} of {MAX_ROUNDS} open")
            else:
                r = round_close(pd, a.council, a.research, a.note)
                print(f"round closed: intent verdict {r['closed']['verdict']}")
        elif a.cmd == "final":
            add_final(pd, a.file)
        elif a.cmd == "revise":
            print(f"cycle {load(pd)['cycle'] + 1}: round {revise(pd, a.feedback)} open")
        elif a.cmd == "share":
            if a.what == "detect":
                for dest, r in SH.detected(share_detect(pd, force=True)).items():
                    print(f"{dest}: " + ("available" if r["ok"] else f"not available ({r['why']})"))
            else:
                if not (a.to and a.by):
                    raise FlowError("share needs --to artifacts|loom and --by NAME (the person who asked for the upload)")
                n, rec, what = share_upload(pd, a.what, a.n, a.to, a.by, a.access)
                print(f"{a.what} {n} {what} on {SH.LABEL[a.to]} as {rec['name']}" + (f": {rec['url']}" if rec.get("url") else ""))
        elif a.cmd == "snapshot":
            share_detect(pd)
            doc = json.dumps(snapshot(pd), indent=2)
            if a.out:
                os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
                open(a.out, "w").write(doc)
                print(a.out)
            else:
                print(doc)
        elif a.cmd == "note":
            note(pd, a.text, a.kind, a.done)
        elif a.cmd == "board":
            print(dashboard(pd, a.out))
    except (FlowError, BR.BriefError, SH.ShareError) as e:
        print(f"promo flow: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
