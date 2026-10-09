import json
import os
import subprocess
import shutil

import pytest
from PIL import Image

from promo import abtest as AB
from promo import assetplan as AP
from promo import brief as BR
from promo import flow as F
from promo import flowcheck as FC
from promo import previews as PV
from promo import storyboard as SB

INTENT = "Make a 60s promo for Acme Tasks: tell it at night, wake up to merged PRs."


def img(p, c=(40, 40, 40)):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    Image.new("RGB", (320, 180), c).save(p)


def scene(i, t0, t1, **kw):
    s = dict(id=i, beat="Beat " + i, t=[t0, t1], action="something happens", source="real", proof="ticket list shows 8",
             start=dict(image=f"frames/{i}-s.png", prompt="p"), end=dict(image=f"frames/{i}-e.png", prompt="p"))
    s.update(kw)
    return s


@pytest.fixture
def pd(tmp_path):
    d = str(tmp_path / "proj")
    F.init(d, INTENT)
    return d


def write(p, txt):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(txt)


def board(pd, sid, make_imgs=True):
    d = os.path.join(pd, "flow", "boards", sid)
    b = dict(story=sid, title="T" + sid, logline="L", scenes=[scene("01", 0, 4), scene("02", 4, 9, caption="8 tasks")])
    write(os.path.join(d, "board.json"), json.dumps(b))
    if make_imgs:
        for s in b["scenes"]:
            img(os.path.join(d, s["start"]["image"]))
            img(os.path.join(d, s["end"]["image"]))
    return d


def review_draft(pd, new_wins=True, family="claude"):
    """What the council does before a round may close: every judge check marked on the new draft (the control as false) and the
    blind comparison with the reviewed draft judged in both orders."""
    for c in FC.judge_checks(F.load(pd)):
        FC.mark(pd, c["id"], None, "fail" if c.get("control") else "pass", "seen in the stills", family)
    jid, _ = AB.judge_pair(pd)
    p = AB.pair(F.load(pd), jid)
    want = p["draft"] if new_wins else p["against"]
    for k, o in p["orders"].items():
        AB.judge(pd, jid, k, "A" if o["A"] == want else "B", family=family)
    return jid


def test_init_locks_brief_and_cannot_skip(pd):
    assert BR.load(pd)["intent_verbatim"] == INTENT
    with pytest.raises(F.FlowError, match="cannot leave"):
        F.advance(pd)


def test_agent_cannot_approve(pd):
    with pytest.raises(F.FlowError, match="agent"):
        F.approve(pd, "scripts-picked", "Claude", ["A"])


def test_happy_path_and_gates(pd, tmp_path, sheets):
    F.discover(pd, "dialogue film", ["https://youtu.be/x"], False)
    assert F.advance(pd) == "scripts"
    sf = str(tmp_path / "s.md")
    write(sf, "script")
    for i in "AB":
        F.add_script(pd, i, "T" + i, "L", sf)
    assert not all(o for o, _ in F.checks(pd, F.load(pd)))          # only 2 scripts + no council
    F.add_script(pd, "C", "TC", "L", sf)
    cf = str(tmp_path / "c.md")
    write(cf, "x" * 300)
    F.add_council(pd, "scripts", cf)
    assert F.advance(pd) == "pick"
    with pytest.raises(F.FlowError):
        F.approve(pd, "scripts-picked", "Pat", ["Z"])
    F.approve(pd, "scripts-picked", "Pat", ["A"])
    assert F.advance(pd) == "storyboard"
    board(pd, "A", make_imgs=False)
    with pytest.raises(F.FlowError, match="START and END"):
        F.approve(pd, "storyboard-approved", "Pat")
    d = board(pd, "A")
    F.approve(pd, "storyboard-approved", "Pat")
    # editing the board after approval makes the approval stale
    b = json.load(open(SB.board_path(d)))
    b["title"] = "changed"
    json.dump(b, open(SB.board_path(d), "w"))
    assert not F.gate_ok(pd, F.load(pd), "storyboard-approved")
    F.approve(pd, "storyboard-approved", "Pat")
    assert F.advance(pd) == "assets"
    # assets: every scene needs one; UI must be real/mock; mocks block drafts, not planning
    rec = lambda **k: AP.save(os.path.join(pd, "flow"), AP.upsert(AP.load(os.path.join(pd, "flow")), k))  # noqa: E731
    rec(id="ui1", kind="recording", source="generated", scenes=["01"], how="x")
    assert any("generated UI" in p for p in AP.problems(AP.load(os.path.join(pd, "flow")), ["01", "02"], pd))
    rec(id="ui1", kind="recording", source="mock", scenes=["01", "02"], how="screen recording of the ticket list")
    with pytest.raises(F.FlowError, match="real preview"):
        F.approve(pd, "assets-approved", "Pat")                      # a plan nobody can look at is not approvable
    assert F.make_assets(pd, None, False, "auto") == 0
    F.approve(pd, "assets-approved", "Pat")
    assert F.advance(pd) == "keyframes"
    with pytest.raises(F.FlowError, match="real"):
        F.advance(pd)                                                # mock still blocks
    real = os.path.join(pd, "footage", "ui1.png")
    img(real)
    rec(id="ui1", kind="recording", source="real", scenes=["01", "02"], how="x", path="footage/ui1.png")
    assert F.advance(pd) == "confirm"
    with pytest.raises(F.FlowError):
        F.advance(pd)
    F.approve(pd, "final-confirmation", "Pat")
    assert F.advance(pd) == "drafts"
    dr = str(tmp_path / "d.mp4")
    write(dr, "v")
    F.add_draft(pd, dr)
    assert F.advance(pd) == "review"
    # round: needs new draft, >= 3 URLs, intent-check line
    F.round_start(pd, "the close up is rough")
    sha = BR.intent_sha(BR.load(pd))
    council = str(tmp_path / "co.md")
    research = str(tmp_path / "re.md")
    write(council, f"intent-check: intent_sha={sha} verdict=PARTIAL intent=3 reference=3 lens=intent-reference\nevidence")
    write(research, "see https://a.example/1 https://b.example/2")
    with pytest.raises(F.FlowError) as e:
        F.round_close(pd, council, research)
    assert "new draft" in str(e.value) and "3 distinct" in str(e.value) and "not a check yet" in str(e.value)
    write(research, "https://a.example/1 https://b.example/2 https://c.example/3")
    FC.add(pd, "The close-up of the ticket list is sharp", scene="02", source="feedback", by="Pat")
    F.add_draft(pd, dr, "v2")
    with pytest.raises(F.FlowError, match="not measured on the new draft"):
        F.round_close(pd, council, research)                         # a draft nobody looked at does not go to the person
    review_draft(pd)
    r = F.round_close(pd, council, research)
    assert r["closed"]["verdict"] == "PARTIAL"
    # wrong intent hash is refused
    F.round_start(pd, "again")
    FC.add(pd, "The hook lands in the first three seconds", source="feedback")
    F.add_draft(pd, dr, "v3")
    review_draft(pd)
    write(council, "intent-check: intent_sha=deadbeef0000 verdict=YES intent=5 reference=5 lens=x")
    with pytest.raises(F.FlowError, match="different text"):
        F.round_close(pd, council, research)
    write(council, f"intent-check: intent_sha={sha} verdict=YES intent=5 reference=5 lens=x")
    F.round_close(pd, council, research)
    F.approve(pd, "draft-approved", "Pat")
    assert F.advance(pd) == "final"
    F.add_final(pd, dr)
    # revise: new cycle, council again
    assert F.revise(pd, "make the hook faster") == 1
    assert F.load(pd)["stage"] == "review" and F.load(pd)["cycle"] == 2


def test_round_cap(pd):
    st = F.load(pd)
    st["stage"] = "review"
    st["drafts"] = [dict(file="/x", at="", cycle=1)]
    with pytest.raises(F.FlowError, match="after the final"):
        F.revise(pd, "too early")                                        # with rounds left, feedback is a round, not a new cycle
    for n in range(1, 6):
        st["rounds"].append(dict(cycle=1, n=n, feedback="f", started="", drafts_at_start=0, closed=dict(verdict="YES", dir="rounds/x")))
    F.save(pd, st)
    with pytest.raises(F.FlowError, match="5 rounds"):
        F.round_start(pd, "more")
    # the person restates the direction instead of approving: a new cycle opens from review, so a used-up review is never a dead end
    assert F.revise(pd, "slower, warmer, no music") == 1
    st = F.load(pd)
    r = F.open_round(st)
    assert st["stage"] == "review" and st["cycle"] == 2 and r and r["feedback"] == "slower, warmer, no music"
    assert F.snapshot(pd)["rounds_used"] == 1


def test_a_registered_draft_is_the_decision_with_approve_and_feedback(pd, tmp_path):
    """The buttons come with the video: at `drafts` with a draft on file the Stage asks approve / feedback, and either answer moves the flow into review."""
    st = F.load(pd)
    st["stage"] = "drafts"
    F.save(pd, st)
    assert F.snapshot(pd)["gate"] is None                                   # nothing to watch yet: no question
    dr = str(tmp_path / "d.mp4")
    write(dr, "v")
    F.add_draft(pd, dr)
    s = F.snapshot(pd)
    assert s["gate"]["kind"] == "draft" and s["gate"]["gate"] == "draft-approved" and s["gate"]["stage"] == "drafts"
    assert s["gate"]["approve_label"] == "Approve" and s["gate"]["changes_label"] == "Feedback and iterate"
    assert s["summary"]["badge"] == "waiting" and s["summary"]["primary"] == "Watch draft"
    assert F.round_start(pd, "the hook is slow") == 1 and F.load(pd)["stage"] == "review"      # feedback at drafts starts review
    st = F.load(pd)
    st["rounds"] = []
    st["stage"] = "drafts"
    F.save(pd, st)
    F.approve(pd, "draft-approved", "Pat")                                 # approval at drafts lands too
    st = F.load(pd)
    assert st["stage"] == "review" and F.gate_ok(pd, st, "draft-approved") and F.advance(pd) == "final"


def test_an_answer_that_arrives_one_stage_early_is_not_refused(pd, tmp_path):
    """The Stage shows the pick gate while the flow is still at `scripts`; the person's pick must land, not bounce with 'belongs to a later stage'."""
    F.discover(pd, "dialogue film", [], True)
    F.advance(pd)
    sf = str(tmp_path / "s.md")
    write(sf, "script")
    for i in "ABC":
        F.add_script(pd, i, "T" + i, "L", sf)
    with pytest.raises(F.FlowError, match="cannot leave it") as e:
        F.approve(pd, "scripts-picked", "Pat", ["A"])                   # the scripts stage is not ready (no council yet): say why
    assert "council" in str(e.value) and F.load(pd)["stage"] == "scripts"
    cf = str(tmp_path / "c.md")
    write(cf, "x" * 300)
    F.add_council(pd, "scripts", cf)
    assert F.snapshot(pd)["gate"]["gate"] == "scripts-picked"
    F.approve(pd, "scripts-picked", "Pat", ["A"])
    st = F.load(pd)
    assert st["stage"] == "pick" and st["picks"] == ["A"] and F.gate_ok(pd, st, "scripts-picked")
    assert F.advance(pd) == "storyboard"


def test_discover_asks_again_when_the_style_is_on_file_but_references_are_not(pd):
    F.discover(pd, "Horizon film", [], False)                            # style recorded, nothing said about references: not ready, and nothing for the agent to make
    s = F.snapshot(pd)
    assert s["gate"] and s["gate"]["kind"] == "style" and "Horizon film" in s["gate"]["question"] and "reference" in s["gate"]["question"]
    assert s["summary"]["badge"] == "waiting"
    F.discover(pd, "Horizon film", [], True)
    assert F.snapshot(pd)["gate"] is None and F.advance(pd) == "scripts"


def fake_commissionctl(tmp_path, monkeypatch, exit_code=0, say=""):
    """A `commissionctl` on PATH that records its arguments and answers like the daemon."""
    d = tmp_path / "bin"
    d.mkdir()
    log = tmp_path / "publish.log"
    exe = d / "commissionctl"
    exe.write_text(f"#!/bin/sh\necho \"$@\" >> '{log}'\n" + (f"echo '{say}'\n" if say else "") + f"exit {exit_code}\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    monkeypatch.setenv("COMMISSION_THREAD_TOKEN", "t")
    monkeypatch.delenv("PROMO_FLOW_PUBLISH")
    return log


def test_every_change_inside_a_commissionai_thread_reaches_the_stage(pd, monkeypatch, tmp_path, capsys):
    """The Stage once showed `pick`, unpicked, for hours after the pick: the agent changed the flow and never published. Now the command does it."""
    log = fake_commissionctl(tmp_path, monkeypatch, say="stored")
    assert F.main(["--project", pd, "note", "Drawing the storyboard", "--kind", "render"]) == 0
    assert F.main(["--project", pd, "discover", "--style", "Horizon film", "--no-refs"]) == 0
    calls = log.read_text().splitlines()
    state = os.path.join(pd, "flow", "state.json")
    assert calls == [f"mod publish promo-flow --file {state}"] * 2
    s = json.load(open(state))
    assert s["stage"] == "discover" and s["style"]["style"] == "Horizon film" and s["gate"] is None
    assert "Stage updated" in capsys.readouterr().err
    assert F.main(["--project", pd, "status"]) == 0 and len(log.read_text().splitlines()) == 2        # reading does not publish
    monkeypatch.setenv("PROMO_FLOW_PUBLISH", "0")
    assert F.main(["--project", pd, "advance"]) == 0 and len(log.read_text().splitlines()) == 2        # the opt-out for tests and the harness


def test_a_failed_publish_is_an_error_the_agent_sees(pd, monkeypatch, tmp_path, capsys):
    fake_commissionctl(tmp_path, monkeypatch, exit_code=3, say="mods.too_big: the state is over the limit")
    assert F.main(["--project", pd, "note", "x"]) == 1
    err = capsys.readouterr().err
    assert "Stage was not updated" in err and "over the limit" in err
    assert any(a["text"] == "x" for a in F.load(pd)["activity"])                       # the flow change itself stands; only the Stage is behind
    monkeypatch.delenv("COMMISSION_THREAD_TOKEN")
    assert F.main(["--project", pd, "note", "y"]) == 0                                  # outside a thread there is no Stage to update
    assert F.main(["--project", pd, "publish"]) == 1 and "not inside a CommissionAI thread" in capsys.readouterr().err


def test_mod_dev_host_refuses_the_same_files_as_the_daemon(tmp_path):
    """mod-dev/serve.py stands in for CommissionAI: a `$file` that is not an image, audio or video must fail there too, or a publish bug passes every local check."""
    import importlib
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "mod-dev"))
    serve = importlib.import_module("serve")
    md, png = tmp_path / "A.md", tmp_path / "a.png"
    md.write_text("# Script")
    img(str(png))
    out = serve.resolve({"a": {"$file": str(md)}, "b": {"$file": str(png)}})
    assert out["a"]["$media"] is None and "only images, audio and video" in out["a"]["$error"]
    assert out["b"]["$media"]["mime"] == "image/png"


def test_storyboard_problems_and_dashboard(pd):
    b = dict(title="x", logline="y", scenes=[scene("01", 0, 4, caption="c", proof=""), scene("02", 3, 5)])
    pr = SB.problems(b)
    assert any("caption without `proof`" in p for p in pr) and any("before the previous scene" in p for p in pr)
    d = board(pd, "A")
    st = F.load(pd)
    st["picks"] = ["A"]
    F.save(pd, st)
    AP.save(os.path.join(pd, "flow"), [dict(id="m1", kind="music", source="mock", scenes=["01"], how="licensed track")])
    out = F.dashboard(pd)
    html = open(out).read()
    assert "START" in html and "MOCK" in html and "Asset plan" in html


def test_status_json_has_ask(pd):
    s = F.status(pd)
    assert s["stage"] == "discover" and s["ask"]["header"] == "Style" and len(s["ask"]["options"]) >= 2


def test_ask_in_stage_when_the_pane_gate_carries_it(pd):
    s = F.status(pd)
    assert s["ask"] and s["ask_in_stage"] is True
    assert F.snapshot(pd)["gate"]["question"] == s["ask"]["question"]
    assert "do NOT also ask in chat" in F.status_text(s)


def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


def check_summary(s):
    sm = s["summary"]
    assert 0 < len(sm["title"]) <= 80 and 0 < len(sm["status"]) <= 140
    assert sm["badge"] in ("working", "waiting", "done", "attention")
    assert sm["progress"]["total"] == len(F.STAGES) and 0 <= sm["progress"]["done"] <= sm["progress"]["total"]
    assert len(sm.get("primary", "x")) <= 24
    assert (sm["badge"] == "waiting") == bool(sm.get("primary")) or sm["badge"] != "waiting"


def test_snapshot_is_the_mod_state(pd):
    board(pd, "A")
    st = F.load(pd)
    st["picks"] = ["A"]
    st["stage"] = "storyboard"
    st["scripts"] = [dict(id="A", title="TA", logline="L", file="x")]
    F.save(pd, st)
    AP.save(os.path.join(pd, "flow"), [dict(id="m", kind="music", source="mock", scenes=["01"], how="h"), dict(id="t", kind="sfx", source="generated", scenes=["02"], how="whoosh")])
    s = F.snapshot(pd)
    json.dumps(s)
    check_summary(s)
    assert s["summary"]["badge"] == "waiting" and s["summary"]["primary"] == "Review storyboard"
    assert s["stage"] == "storyboard" and s["scripts"][0]["picked"] and s["gate"]["gate"] == "storyboard-approved"
    assert [x["id"] for x in s["steps"]] == F.STAGES
    assert [x["state"] for x in s["steps"]][:5] == ["done", "done", "done", "current", "todo"]
    sc = s["boards"][0]["scenes"][0]
    assert set(sc["start"]["path"]) == {"$file"} and sc["start"]["path"]["$file"].endswith("01-s.png") and os.path.isabs(sc["start"]["path"]["$file"])
    assert sc["end"]["path"]["$file"].endswith("01-e.png") and sc["start_s"] == 0.0
    assert s["assets"][0]["state"] == "mock" and s["assets"][0]["path"] is None
    assert [x["id"] for x in s["to_make"]] == ["t"] and s["to_make"][0]["kind"] == "asset"
    assert s["rounds_used"] == 0 and s["rounds_max"] == F.MAX_ROUNDS and s["approvals"] == {}


def test_snapshot_media_are_file_objects_and_approvals(pd, tmp_path):
    board(pd, "A")
    st = F.load(pd)
    st.update(picks=["A"], stage="storyboard", scripts=[dict(id="A", title="TA", logline="L", file="x")])
    F.save(pd, st)
    F.approve(pd, "storyboard-approved", "Pat")
    s = F.snapshot(pd)
    assert s["approvals"]["storyboard-approved"]["fresh"] is True and s["approvals"]["storyboard-approved"]["by"] == "Pat"
    assert s["gate"] is None and s["summary"]["badge"] == "working"
    files = [d["$file"] for d in walk(s) if "$file" in d]
    assert len(files) == 4 and all(os.path.isabs(f) and os.path.isfile(f) for f in files)
    for k in ("path",):
        assert not any(isinstance(d.get(k), str) for d in walk(s))


def test_snapshot_summary_over_stages(pd):
    s = F.snapshot(pd)
    check_summary(s)
    assert s["stage"] == "discover" and s["summary"]["badge"] == "waiting" and s["gate"]["kind"] == "style"
    assert s["steps"][0]["state"] == "current" and s["summary"]["progress"] == dict(done=0, total=10)
    st = F.load(pd)
    st.update(stage="pick", scripts=[dict(id=i, title="T" + i, logline="L", file="x") for i in "ABC"])
    F.save(pd, st)
    s = F.snapshot(pd)
    assert s["gate"]["gate"] == "scripts-picked" and s["gate"]["picks_max"] == 2 and s["summary"]["primary"] == "Pick scripts"
    st.update(stage="review", drafts=[dict(file="/x", at="", cycle=1)])
    for n in range(1, 6):
        st["rounds"].append(dict(cycle=1, n=n, feedback="f", started="", drafts_at_start=0, closed=dict(verdict="YES", dir="rounds/x")))
    F.save(pd, st)
    s = F.snapshot(pd)
    check_summary(s)
    assert s["rounds_used"] == 5 and s["summary"]["badge"] == "attention"
    assert len(s["summary"]["status"]) <= 140
    st.update(stage="final", finals=[dict(file=real_file(pd), at="")])
    F.save(pd, st)
    s = F.snapshot(pd)
    assert s["summary"]["badge"] == "done" and s["summary"]["progress"]["done"] == 10 and all(x["state"] == "done" for x in s["steps"])


def test_snapshot_clips_long_title(pd):
    st = F.load(pd)
    st["intent"] = "Make " + "a very long intent " * 12 + "end. second sentence"
    F.save(pd, st)
    s = F.snapshot(pd)
    assert len(s["summary"]["title"]) <= 80 and len(s["title"]) <= 80


def real_file(pd):
    p = os.path.join(pd, "out", "final.mp4")
    write(p, "v")
    return p


def at_storyboard(pd):
    d = board(pd, "A")
    st = F.load(pd)
    st.update(picks=["A"], stage="storyboard", scripts=[dict(id="A", title="TA", logline="L", file="x")])
    F.save(pd, st)
    return d


def test_stale_approval_is_not_done(pd):
    d = at_storyboard(pd)
    F.approve(pd, "storyboard-approved", "Pat")
    st = F.load(pd)
    st["stage"] = "assets"
    F.save(pd, st)
    AP.save(os.path.join(pd, "flow"), [dict(id="m", kind="music", source="real", scenes=["01", "02"], how="h")])
    assert F.snapshot(pd)["steps"][3]["state"] == "done"
    b = json.load(open(SB.board_path(d)))
    b["title"] = "edited after approval"
    json.dump(b, open(SB.board_path(d), "w"))
    s = F.snapshot(pd)
    assert s["steps"][3]["state"] == "stale" and s["steps"][3]["stale"] and [x["id"] for x in s["stale_steps"]] == ["storyboard"]
    assert s["gate"]["gate"] == "storyboard-approved" and s["gate"]["stale"] and s["gate"]["approve_label"] == "Approve again" and s["gate"]["stage"] == "storyboard"
    assert s["gate"]["question"] == "Storyboard changed after you approved it. Approve it again?"
    assert s["summary"]["badge"] == "waiting" and s["summary"]["primary"] == "Approve again"
    assert s["approvals"]["storyboard-approved"]["fresh"] is False
    st = F.load(pd)
    st.update(stage="final", finals=[dict(file=real_file(pd), at="")])
    F.save(pd, st)
    s = F.snapshot(pd)
    assert s["summary"]["badge"] != "done" and not all(x["state"] == "done" for x in s["steps"])
    F.approve(pd, "storyboard-approved", "Pat")
    assert F.snapshot(pd)["summary"]["badge"] == "done"


def test_scene_source_never_defaults_to_real(pd):
    d = board(pd, "A")
    b = json.load(open(SB.board_path(d)))
    b["scenes"][0].pop("source")
    b["scenes"][1]["source"] = "generated"
    json.dump(b, open(SB.board_path(d), "w"))
    st = F.load(pd)
    st.update(picks=["A"], stage="storyboard")
    F.save(pd, st)
    sc = F.snapshot(pd)["boards"][0]["scenes"]
    assert [x["source"] for x in sc] == ["other", "generated"]
    b["scenes"][0]["source"] = "real"
    json.dump(b, open(SB.board_path(d), "w"))
    assert F.snapshot(pd)["boards"][0]["scenes"][0]["source"] == "real"


def test_asset_scenes_validated_and_keyframe_labels(pd):
    d = at_storyboard(pd)
    b = json.load(open(SB.board_path(d)))
    b["scenes"][1]["frames"] = [dict(t=4.5, image="frames/02-mid.png", prompt="p")]
    json.dump(b, open(SB.board_path(d), "w"))
    AP.save(os.path.join(pd, "flow"), [dict(id="m", kind="music", source="real", scenes=["01", "99"], how="h")])
    st = F.load(pd)
    st["stage"] = "keyframes"
    F.save(pd, st)
    s = F.snapshot(pd)
    assert s["assets"][0]["scenes"] == ["01"]
    kf = [x for x in s["to_make"] if x["kind"] == "keyframe"]
    assert [x["label"] for x in kf] == ["Scene 02 · mid frame 1"] and kf[0]["at"] == "t=4.5 s" and kf[0]["scene"] == "02" and kf[0]["story"] == "A"
    assert not any("frames[" in x["label"] or "A/02" in x["label"] for x in s["to_make"])


def test_plain_sentences(pd, tmp_path):
    st = F.load(pd)
    st.update(stage="scripts", scripts=[dict(id=i, title="T", logline="L", file="x") for i in "ABC"])
    F.save(pd, st)
    s = F.snapshot(pd)
    assert s["summary"]["status"] == "Three scripts are drafted and being reviewed"
    assert [c["text"] for c in s["checks"]] == ["Three scripts drafted", "Scripts not reviewed by the council yet"]
    st.update(stage="drafts")
    F.save(pd, st)
    assert F.snapshot(pd)["summary"]["status"] == "Waiting for the first draft."
    d = at_storyboard(pd)
    st = F.load(pd)
    st["stage"] = "keyframes"
    F.save(pd, st)
    os.remove(os.path.join(d, "frames", "01-e.png"))
    os.remove(os.path.join(d, "frames", "02-s.png"))
    AP.save(os.path.join(pd, "flow"), [dict(id="m", kind="music", source="mock", scenes=["01"], how="h")])
    s = F.snapshot(pd)
    assert s["summary"]["status"] == "All stories: 2 of 4 keyframes made, 2 left"
    assert s["checks"][1]["text"] == "Before the real run: 1 stand-in to swap for the real thing"
    st["stage"] = "storyboard"
    F.save(pd, st)
    s2 = F.snapshot(pd)
    assert s2["summary"]["status"] == "2 frames not made yet"
    for sn in (s, s2):
        txt = " ".join([sn["summary"]["status"]] + [c["text"] for c in sn["checks"]])
        for bad in ("registered and exists", "sparred", "(2 missing)", "all keyframes generated", "1-2 rounds", sn["stage_label"] + ":"):
            assert bad not in txt


def test_beats_and_draft_numbering(pd, tmp_path):
    sf = str(tmp_path / "s.md")
    write(sf, "# Script A\n\nIntro text.\n\n1. Night, the laptop is the only light\n2. One sentence typed\n3. third beat\n")
    F.add_script(pd, "A", "TA", "L", sf)
    assert F.snapshot(pd)["scripts"][0]["beats"] == ["Night, the laptop is the only light", "One sentence typed"]
    st = F.load(pd)
    st.update(stage="review", drafts=[dict(file="/x/draft-%d.mp4" % i, at="", cycle=1) for i in (1, 2, 3)])
    st["rounds"] = [dict(cycle=1, n=1, feedback="f", started="", drafts_at_start=1, closed=dict(verdict="YES", dir="rounds/x")),
                    dict(cycle=1, n=2, feedback="g", started="", drafts_at_start=2, closed=dict(verdict="YES", dir="rounds/y"))]
    F.save(pd, st)
    s = F.snapshot(pd)
    assert [d["after"] for d in s["drafts"]] == ["", "round 1", "round 2"]
    assert s["drafts"][2]["name"] == "draft-3.mp4" and s["stage_since"]
    assert "round" not in s["gate"]["question"].lower()


def test_asset_labels_are_human(pd):
    at_storyboard(pd)
    AP.save(os.path.join(pd, "flow"), [dict(id="ui-ticket-list", kind="screenshot", source="real", scenes=["01"], how="Full-resolution capture of the ticket list, DPR 2.", label="Ticket list"),
                                       dict(id="sfx_whoosh", kind="sfx", source="generated", scenes=["02"], how="x"),
                                       dict(id="music-bed", kind="music", source="mock", scenes=["01"], how="Calm ambient bed at 98 BPM. 60 s.")])
    labels = [a["label"] for a in F.snapshot(pd)["assets"]]
    assert labels[0] == "Ticket list" and labels[1] == "Sfx whoosh" and labels[2] == "Calm ambient bed at 98 BPM"
    assert all("-" not in x and "_" not in x for x in labels)


def story_buckets(s, story):
    """What the mod's one derived model shows for a selected story: asset rows used in it + that story's keyframes to make, split into exclusive buckets."""
    ids = {x["id"] for b in s["boards"] if b["id"] == story for x in b["scenes"]}
    rows = [a["state"] for a in s["assets"] if set(a["scenes"]) & ids or not a["scenes"]]
    rows += ["todo" for t in s["to_make"] if t["kind"] == "keyframe" and t["story"] == story]
    return {k: rows.count(k) for k in ("ready", "mock", "todo")}, len(rows), len(ids)


def test_counts_have_one_source_and_scene_refs_stay_in_the_story(pd):
    d = at_storyboard(pd)
    b2 = dict(story="B", title="TB", logline="L", scenes=[scene("11", 0, 3), scene("12", 3, 6)])
    d2 = os.path.join(pd, "flow", "boards", "B")
    write(os.path.join(d2, "board.json"), json.dumps(b2))
    for sc_ in b2["scenes"]:
        img(os.path.join(d2, sc_["start"]["image"]))
        img(os.path.join(d2, sc_["end"]["image"]))
    st = F.load(pd)
    st.update(picks=["A", "B"], stage="keyframes")
    F.save(pd, st)
    os.remove(os.path.join(d, "frames", "02-e.png"))
    AP.save(os.path.join(pd, "flow"), [dict(id="m", kind="music", source="mock", scenes=["01", "02", "11", "12", "99"], how="h"),
                                       dict(id="r", kind="screenshot", source="real", scenes=["11"], how="h", path="footage/r.png"),
                                       dict(id="t", kind="sfx", source="generated", scenes=["01"], how="h")])
    img(os.path.join(pd, "footage", "r.png"))
    s = F.snapshot(pd)
    valid = {x["id"] for b in s["boards"] for x in b["scenes"]}
    assert all(set(a["scenes"]) <= valid for a in s["assets"]) and "99" not in s["assets"][0]["scenes"]
    ba, na, ns = story_buckets(s, "A")
    bb, nb, ms = story_buckets(s, "B")
    assert (ns, ms) == (2, 2)
    assert sum(ba.values()) == na == 3 and ba == dict(ready=0, mock=1, todo=2)
    assert sum(bb.values()) == nb == 2 and bb == dict(ready=1, mock=1, todo=0)


def test_wording_has_no_soft_promises(pd):
    at_storyboard(pd)
    st = F.load(pd)
    st["stage"] = "keyframes"
    F.save(pd, st)
    img(os.path.join(pd, "footage", "r.png"))
    AP.save(os.path.join(pd, "flow"), [dict(id="r", kind="screenshot", source="real", scenes=["01"], how="h", path="footage/r.png")])
    s = F.snapshot(pd)
    assert s["checks"][1]["text"] == "Every planned asset has its file."
    st.update(stage="final", finals=[dict(file=real_file(pd), at="")])
    F.save(pd, st)
    s = F.snapshot(pd)
    assert s["summary"]["status"] == "Final delivered." and "any time" not in s["summary"]["status"]


def test_stage_since_is_the_last_log_time(pd):
    s = F.snapshot(pd)
    assert s["stage_since"] == F.load(pd)["log"][-1]["at"]


def test_a_final_whose_file_is_missing_is_not_done(pd):
    st = F.load(pd)
    st.update(stage="final", finals=[dict(file="/nowhere/final.mp4", at="")])
    F.save(pd, st)
    s = F.snapshot(pd)
    assert s["summary"]["badge"] != "done" and s["summary"]["progress"]["done"] == 9
    assert [x["state"] for x in s["steps"]][-1] == "current" and not all(x["state"] == "done" for x in s["steps"])
    assert s["checks"][0] == dict(ok=False, text="A final is registered, but its file is missing")
    st["finals"] = [dict(file=real_file(pd), at="")]
    F.save(pd, st)
    s = F.snapshot(pd)
    assert s["summary"]["badge"] == "done" and all(x["state"] == "done" for x in s["steps"])


def test_mod_logic_unit_tests_pass():
    """mods/promo-flow/logic.js (scene status, count buckets, gate rules, final rule) has node --test unit tests; they must pass."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([node, "--test", os.path.join(root, "mods", "promo-flow", "test", "logic.test.js")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]


def test_mod_interaction_checks_pass():
    """The Plan tab reader (paging, contents, find, escaping, requests) and the storyboard cadence control, driven in headless Chrome (mod-dev/shoot.py --check)."""
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.exists("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") or not __import__("shutil").which("ffmpeg"):
        pytest.skip("headless Chrome and ffmpeg are needed")
    r = subprocess.run([sys.executable, os.path.join(root, "mod-dev", "shoot.py"), "--check"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]


def slate(p):
    """What an agent wrote in place of a frame: a flat dark image with a few lines of text."""
    from PIL import ImageDraw
    os.makedirs(os.path.dirname(p), exist_ok=True)
    im = Image.new("RGB", (320, 180), (34, 34, 38))
    ImageDraw.Draw(im).rectangle((10, 10, 120, 24), fill=(230, 130, 70))
    im.save(p)


def test_text_slate_is_not_a_frame(pd):
    d = board(pd, "A")
    assert SB.missing(SB.load(d), d) == []
    slate(os.path.join(d, "frames", "01-s.png"))
    miss = SB.missing(SB.load(d), d)
    assert [(m["scene"], m["which"], m["slate"]) for m in miss] == [("01", "start", True)]
    open(os.path.join(d, "frames", "01-s.png.gen.json"), "w").write("{}")          # what `promo flow frames` writes beside a real image
    assert SB.missing(SB.load(d), d) == []


def test_snapshot_shows_samples_and_hides_slates(pd):
    d = board(pd, "A")
    slate(os.path.join(d, "frames", "01-e.png"))
    st = F.load(pd)
    st["picks"] = ["A"]
    F.save(pd, st)
    AP.save(os.path.join(pd, "flow"), [dict(id="m1", kind="music", source="licensed", scenes=["01"], how="track", path="media/m1.wav")])
    import numpy as np
    import soundfile as sf
    os.makedirs(os.path.join(pd, "media"))
    sf.write(os.path.join(pd, "media", "m1.wav"), np.sin(np.arange(48000 * 30) * 0.05) * 0.2, 48000)
    snap = F.snapshot(pd)
    sc = snap["boards"][0]["scenes"][0]
    assert sc["end"]["slate"] and sc["end"]["path"] is None and sc["start"]["path"]
    assert snap["assets"][0]["sample"] is None                               # a real file is the preview itself
    AP.save(os.path.join(pd, "flow"), [dict(id="m1", kind="music", source="licensed", scenes=["01"], how="track", licence="CC0")])
    assert [n["id"] for n in F.needs(pd) if n["kind"] == "preview"] == ["m1"]
    AP.save(os.path.join(pd, "flow"), [dict(id="m1", kind="music", source="licensed", scenes=["01"], how="track", licence="CC0", path="media/m1.wav")])
    PV.make_samples(AP.load(os.path.join(pd, "flow")), pd, F.boards(pd, F.load(pd)), force=True)
    sample = F.snapshot(pd)["assets"][0]["sample"]
    assert sample and os.path.isfile(sample["$file"])
    dur = float(__import__("subprocess").run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", sample["$file"]], capture_output=True, text=True).stdout)
    assert 15 < dur <= 21                                                    # an excerpt, not the whole 30 s track


def test_make_frames_replaces_slates_and_reports_failures(pd, monkeypatch):
    d = board(pd, "A")
    slate(os.path.join(d, "frames", "01-s.png"))
    slate(os.path.join(d, "frames", "02-e.png"))
    os.remove(os.path.join(d, "frames", "02-s.png"))

    def fake_generate(kind, prompt, out, provider="auto", guard=None, **kw):
        if "Scene 02" in prompt:
            raise RuntimeError("grok produced no file")
        img(out, (200, 120, 60))
        open(out + ".gen.json", "w").write("{}")
        return dict(provider="codex", prompt=prompt, at="now")
    monkeypatch.setattr(PV.G, "generate", fake_generate)
    made, failed = PV.make_frames(F.boards(pd, dict(F.load(pd), picks=["A"])), say=lambda *_: None)
    assert made == ["A/01/start"]
    assert sorted(f[0] for f in failed) == ["A/02/end", "A/02/start"] and "no file" in failed[0][1]
    assert not SB.is_slate(os.path.join(d, "frames", "01-s.png"))               # a real image now, with its sidecar
    assert [(m["scene"], m["which"]) for m in SB.missing(SB.load(d), d)] == [("02", "start"), ("02", "end")]


def test_keyframes_agent_records_missing_recordings_not_the_person(pd):
    at_storyboard(pd)
    st = F.load(pd)
    st["stage"] = "keyframes"
    F.save(pd, st)
    AP.save(os.path.join(pd, "flow"), [dict(id="r", kind="recording", source="mock", scenes=["01"], how="h"), dict(id="m", kind="music", source="mock", scenes=["01"], how="h")])
    s = F.snapshot(pd)["summary"]
    assert s["badge"] == "working" and s["status"].startswith("Recording 1 clip from the real app") and "Your turn" not in s["status"]
    AP.save(os.path.join(pd, "flow"), [dict(id="m", kind="music", source="mock", scenes=["01"], how="h")])
    assert F.snapshot(pd)["summary"]["badge"] == "working"


def to_drafts(pd):
    st = F.load(pd)
    st["stage"] = "drafts"
    F.save(pd, st)


def test_notes_are_history_dots_and_drive_the_working_status(pd):
    to_drafts(pd)
    before = F.snapshot(pd)["summary"]["status"]
    F.note(pd, "Taking snapshots of the real app", "capture", True)
    F.note(pd, "Rendering screenshots for scene 4", "render")
    snap = F.snapshot(pd)
    dots = [a for a in snap["activity"] if a["kind"] != "milestone"]
    assert [(a["text"], a["kind"], a["done"]) for a in dots] == [("Taking snapshots of the real app", "capture", True), ("Rendering screenshots for scene 4", "render", False)]
    assert snap["summary"]["badge"] == "working" and snap["summary"]["status"] == "Now: Rendering screenshots for scene 4" != before
    F.note(pd, "Rendered scene 4", "render", True)
    assert F.snapshot(pd)["summary"]["status"] == "Done: Rendered scene 4"
    with pytest.raises(F.FlowError):
        F.note(pd, "  ")
    with pytest.raises(F.FlowError):
        F.note(pd, "x", "nonsense")


def test_a_note_older_than_the_last_stage_move_is_not_the_status(pd):
    to_drafts(pd)
    F.note(pd, "Old news", "plan")
    st = F.load(pd)
    st["activity"][-1]["at"] = "2000-01-01T00:00:00+00:00"
    F.log(st, "advance -> scripts")
    F.save(pd, st)
    assert "Old news" not in F.snapshot(pd)["summary"]["status"]


def test_activity_is_capped(pd):
    for i in range(F.ACTIVITY_MAX + 20):
        F.note(pd, f"step {i}")
    assert len(F.load(pd)["activity"]) == F.ACTIVITY_MAX


def test_samples_are_made_in_parallel_and_all_recorded(pd, monkeypatch):
    import threading
    seen, gate = set(), threading.Barrier(3, timeout=5)

    def fake(a, pd_, bds, provider):
        gate.wait()                       # only passes when three run at once
        seen.add(a["id"])
        return dict(path=f"samples/{a['id']}.png", note="")
    monkeypatch.setattr(PV, "make_sample", fake)
    plan = [dict(id=f"a{i}", kind="still", source="real", scenes=[], how="x") for i in range(3)]
    made, failed = PV.make_samples(plan, pd, [], jobs=3, say=lambda *_: None)
    assert sorted(made) == ["a0", "a1", "a2"] and not failed and seen == {"a0", "a1", "a2"}
    assert sorted(PV.load_samples(os.path.join(pd, "flow"))) == ["a0", "a1", "a2"]


# ---- long scripts, planning documents, storyboard density ------------------------------------------------------------------------------------
from promo import boardedit as BE  # noqa: E402
from promo import plandocs as PD  # noqa: E402


def test_a_script_of_any_length_is_added_in_parts_and_snapshotted_as_a_file(pd, tmp_path):
    part = "## Act\n\n" + ("word " * 400 + "\n\n") * 5
    f = tmp_path / "s.md"
    f.write_text("# Full script\n\n" + part)
    F.add_script(pd, "A", "Alpha", "log", str(f))
    n = F.add_script(pd, "A", None, None, text=part, append=True)
    assert n > 4000
    sc = F.snapshot(pd)["scripts"][0]
    assert sc["words"] == n and sc["title"] == "Alpha" and sc["headings"][0]["title"] == "Full script"
    assert sc["body"] == open(os.path.join(pd, "flow", "scripts", "A.md")).read() and sc["body_note"] is None     # the host copies only media files: text goes inline
    assert not any("$file" in d and d["$file"].endswith(".md") for d in walk(F.snapshot(pd)))
    with pytest.raises(F.FlowError, match="no script"):
        F.add_script(pd, "Z", None, None, text="x", append=True)
    with pytest.raises(F.FlowError, match="--title"):
        F.add_script(pd, "B", None, None, text="x")


def test_a_scene_comment_blocks_storyboard_approval_until_answered_and_never_stales_it(pd):
    st = F.load(pd)
    st.update(picks=["A"], stage="storyboard", scripts=[dict(id="A", title="TA", logline="L", file="x")])
    F.save(pd, st)
    board(pd, "A")
    F.approve(pd, "storyboard-approved", "Sam")
    nid = F.scene_note(pd, "A", "02", "  Show it\n typed, not sent. ", "Sam")
    assert F.gate_ok(pd, F.load(pd), "storyboard-approved")
    notes = next(s for b in F.snapshot(pd)["boards"] for s in b["scenes"] if s["id"] == "02")["notes"]
    assert notes == [dict(id=nid, text="Show it typed, not sent.", by="Sam", answer=None)]
    assert any(not ok and "1 scene comment still open" in t for ok, t in F.checks(pd, F.load(pd)))
    with pytest.raises(F.FlowError, match="no scene 99"):
        F.scene_note(pd, "A", "99", "x", "Sam")
    with pytest.raises(F.FlowError, match="--by"):
        F.scene_note(pd, "A", "02", "x", "claude")
    F.scene_resolve(pd, nid, "Redrew the start frame.")
    assert not any(not ok and "scene comment" in t for ok, t in F.checks(pd, F.load(pd)))


def test_the_recommended_script_is_flagged_with_its_reason_and_marked_in_the_question(pd):
    for i in "ABC":
        F.add_script(pd, i, "T" + i, "L", text="x")
    assert all(s["recommended"] is None for s in F.snapshot(pd)["scripts"])
    F.recommend(pd, "B", "It is the only one we can capture today.")
    F.recommend(pd, "C", "  Shortest to make,\n and every claim is on screen.  ")
    recs = {s["id"]: s["recommended"] for s in F.snapshot(pd)["scripts"]}
    assert recs == {"A": None, "B": None, "C": "Shortest to make, and every claim is on screen."}
    assert [o["label"] for o in F.ask(pd, dict(F.load(pd), stage="scripts", councils={"scripts": [1]}))["options"]][2].endswith("(Recommended)")
    with pytest.raises(F.FlowError, match="no script Z"):
        F.recommend(pd, "Z", "A reason that is long enough.")
    with pytest.raises(F.FlowError, match="--why"):
        F.recommend(pd, "A", "too short")


def test_planning_documents_are_added_replaced_appended_and_removed(pd):
    assert F.doc_put(pd, "full-script", kind="script", text="# The full script\n\nOne.\n") == 4
    with pytest.raises(F.FlowError, match="exists"):
        F.doc_put(pd, "full-script", text="again")
    F.doc_put(pd, "full-script", text="Two.", append=True)
    assert F.doc_put(pd, "full-script", text="# Replaced\n\nThree.\n", force=True) == 2
    d = F.snapshot(pd)["docs"]
    assert [x["id"] for x in d] == ["full-script"]
    assert d[0]["title"] == "The full script" and d[0]["kind_label"] == "Script" and d[0]["group"] == "Script" and d[0]["words"] == 2
    assert open(os.path.join(pd, "flow", "docs", "full-script.md")).read().startswith("# Replaced")
    with pytest.raises(F.FlowError, match="kind is one of"):
        F.doc_put(pd, "x", kind="poem", text="a")
    with pytest.raises(F.FlowError, match="lower-case"):
        F.doc_put(pd, "Bad Id", text="a")
    with pytest.raises(PD.DocError, match="empty"):
        F.doc_put(pd, "e", text="  ")
    F.doc_rm(pd, "full-script")
    assert F.snapshot(pd)["docs"] == [] and not os.path.exists(os.path.join(pd, "flow", "docs", "full-script.md"))
    assert any(a["text"] == "Removed from the plan: full-script" for a in F.snapshot(pd)["activity"])


def test_doc_groups_are_ordered_and_state_stays_inside_the_mod_limit_for_huge_documents(pd):
    F.doc_put(pd, "z-notes", kind="notes", text="# N\n\nx")
    F.doc_put(pd, "a-shots", kind="shotlist", text="# S\n\nx")
    F.doc_put(pd, "b-script", kind="script", text="# " + "w " * 10 + "\n\n" + ("lorem ipsum dolor " * 30 + "\n\n") * 4000)       # ~ 1 MB of text
    snap = F.snapshot(pd)
    assert [d["group"] for d in snap["docs"]] == ["Script", "Direction", "Notes"]
    assert len(json.dumps(snap).encode()) <= F.state_budget() < 1024 * 1024        # mod.json state_limit_kb: a publish must never be refused for size
    big, small = snap["docs"][0], snap["docs"][1]
    assert big["words"] > 100_000 and big["body"] is None and "Too long" in big["body_note"] and "split" in big["body_note"]
    assert small["body"].startswith("# S") and small["body_note"] is None           # only the biggest body goes; the rest still read in the Stage


def test_templates_are_built_from_the_real_board_and_assets(pd):
    board(pd, "A")
    st = F.load(pd)
    st["picks"] = ["A"]
    F.save(pd, st)
    AP.save(os.path.join(pd, "flow"), [dict(id="vo-main", kind="voice", source="generated", scenes=["02"], how="Calm read", licence="Kokoro Apache-2.0"), dict(id="rec-a", kind="recording", source="real", scenes=["01"], how="Record the board")])
    did, n = F.doc_new(pd, "shotlist", story="A")
    assert did == "shotlist" and n > 40
    text = open(os.path.join(pd, "flow", "docs", "shotlist.md")).read()
    assert "| 01 | 0–4 s | Beat 01 |" in text and "8 tasks" in text and "ticket list shows 8" in text
    F.doc_new(pd, "capture")
    assert "Record the board" in open(os.path.join(pd, "flow", "docs", "capture.md")).read()
    F.doc_new(pd, "audio")
    assert "Calm read" in open(os.path.join(pd, "flow", "docs", "audio.md")).read()
    with pytest.raises(F.FlowError, match="no storyboard Q"):
        F.doc_new(pd, "shotlist", story="Q")
    with pytest.raises(PD.DocError, match="no template"):
        F.doc_new(pd, "poem")


def test_plan_pack_builds_everything_once_and_per_story(pd):
    board(pd, "A")
    board(pd, "B")
    st = F.load(pd)
    st["picks"] = ["A", "B"]
    F.save(pd, st)
    made, kept = F.plan_pack(pd)
    ids = set(made)
    assert {"treatment-a", "treatment-b", "shotlist-a", "shotlist-b", "edit-b", "audio-a", "direction", "deliverables", "schedule"} <= ids and not kept
    made2, kept2 = F.plan_pack(pd)
    assert not made2 and set(kept2) == ids
    assert F.plan_pack(pd, force=True)[0]
    docs = {d["id"]: d for d in F.snapshot(pd)["docs"]}
    assert docs["shotlist-a"]["story"] == "A" and docs["direction"]["story"] is None


def test_density_puts_frames_on_the_time_grid_and_the_gate_needs_them(pd):
    d = board(pd, "A")
    st = F.load(pd)
    st["picks"] = ["A"]
    F.save(pd, st)
    bds = F.boards(pd, st)
    msg = BE.density(os.path.join(pd, "flow"), bds, every=2)
    b = SB.load(d)
    ts = [f["t"] for s in b["scenes"] for f in s.get("frames", [])]
    assert ts == [2.0, 6.0, 8.0] and b["density"] == {"every_s": 2} and "3 added" in msg      # 4 is the cut between the scenes: START/END frames cover it
    assert all(f["auto"] and f["image"] and f["prompt"] for s in b["scenes"] for f in s["frames"])
    assert SB.problems(b) == []
    assert len(SB.missing(b, d, ("start", "end"))) == 3                       # the dense frames now count even at the storyboard stage
    assert sum(1 for n in F.needs(pd) if n["kind"] == "keyframe") == 3
    snap = F.snapshot(pd)["boards"][0]
    assert snap["density"] == 2 and [x["t"] for x in snap["scenes"][1]["frames"]] == [6.0, 8.0] and snap["scenes"][1]["frames"][0]["auto"]
    # a new cadence replaces the auto frames, keeps the ones already on the grid, and never touches hand-made frames
    b["scenes"][0]["frames"].append(dict(t=1.0, image="frames/hand.png", prompt="hand made"))
    BE._save(d, b)
    img(os.path.join(d, "frames", "01-t0020.png"))
    BE.density(os.path.join(pd, "flow"), F.boards(pd, F.load(pd)), every=4)
    b = SB.load(d)
    assert [(f["t"], bool(f.get("auto"))) for f in b["scenes"][0]["frames"]] == [(1.0, False)]
    assert [f["t"] for f in b["scenes"][1]["frames"]] == [8.0]
    assert not os.path.exists(os.path.join(d, "frames", "01-t0020.png"))     # an auto frame that left the grid is removed from disk
    BE.density(os.path.join(pd, "flow"), F.boards(pd, F.load(pd)), clear=True)
    b = SB.load(d)
    assert "density" not in b and b["scenes"][0]["frames"][0]["t"] == 1.0 and "frames" not in b["scenes"][1]
    with pytest.raises(BE.BoardError, match="--every"):
        BE.density(os.path.join(pd, "flow"), F.boards(pd, F.load(pd)), every=0.1)
    with pytest.raises(BE.BoardError, match="limit"):
        BE.density(os.path.join(pd, "flow"), [("A", dict(scenes=[dict(id="01", t=[0, 600])], story="A"), d)], every=1)


def test_storyboard_density_blocks_approval_until_frames_exist(pd, monkeypatch):
    d = board(pd, "A")
    st = F.load(pd)
    st.update(picks=["A"], stage="storyboard")
    F.save(pd, st)
    BE.density(os.path.join(pd, "flow"), F.boards(pd, st), every=2)
    ok = {t: o for o, t in F.checks(pd, F.load(pd))}
    assert not [o for t, o in ok.items() if "START and END" in t and o]
    made = []
    monkeypatch.setattr(PV, "_make_one", lambda prompt, final, provider, size=PV.FRAME_SIZE: (img(final, (9, 9, 9)), made.append(final)))
    monkeypatch.setattr(SB, "is_slate", lambda p: False)
    assert F.make_frames(pd, None, None, ("start", "end"), False, "auto", 2) == 0
    assert len(made) == 3 and not SB.missing(SB.load(d), d, ("start", "end"))


def test_scene_editing_without_json(pd):
    fd = os.path.join(pd, "flow")
    assert "0 scenes" in BE.story_set(fd, "C", "Story C", "Line")
    BE.scene_add(fd, "C", "01", [0, 5], "Hook", "A desk at night", caption="Hi", source="generated")
    BE.scene_add(fd, "C", "03", [10, 15], "Payoff", "Merged")
    BE.scene_add(fd, "C", "02", [5, 10], "Middle", "Work happens", after="01")
    b = SB.load(os.path.join(fd, "boards", "C"))
    assert [s["id"] for s in b["scenes"]] == ["01", "02", "03"] and b["scenes"][0]["start"]["image"] == "frames/01-start.png"
    assert "Start of Hook" in b["scenes"][0]["start"]["prompt"]
    for s in b["scenes"]:
        for w in ("start", "end"):
            img(os.path.join(fd, "boards", "C", s[w]["image"]))
    BE.scene_set(fd, "C", "02", t=[5, 11], action="It gets busy", redraw="start")
    b = SB.load(os.path.join(fd, "boards", "C"))
    assert b["scenes"][1]["t"] == [5.0, 11.0] and b["scenes"][1]["action"] == "It gets busy"
    assert not os.path.exists(os.path.join(fd, "boards", "C", "frames", "02-start.png")) and os.path.exists(os.path.join(fd, "boards", "C", "frames", "02-end.png"))
    BE.scene_rm(fd, "C", "03")
    assert [s["id"] for s in SB.load(os.path.join(fd, "boards", "C"))["scenes"]] == ["01", "02"]
    for bad, msg in ((lambda: BE.scene_add(fd, "C", "01", [0, 1], "x", "y"), "already exists"), (lambda: BE.scene_add(fd, "C", "09", [3, 2], "x", "y"), "END after START"),
                     (lambda: BE.scene_set(fd, "C", "01"), "nothing to change"), (lambda: BE.scene_set(fd, "C", "77", beat="x"), "no scene 77"),
                     (lambda: BE.scene_add(fd, "C", "09", [0, 1], "x", "y", source="mock"), "real|generated"), (lambda: BE.story_set(fd, "N", title="only"), "needs --title")):
        with pytest.raises(BE.BoardError, match=msg):
            bad()


def test_cli_commands_for_documents_scenes_and_density(pd, capsys):
    base = ["--project", pd]
    assert F.main(base + ["story", "A", "--title", "T", "--logline", "L"]) == 0
    assert F.main(base + ["scene", "add", "A", "01", "--t", "0", "12", "--beat", "Hook", "--action", "A desk"]) == 0
    assert F.main(base + ["scene", "add", "A", "02", "--t", "12", "24", "--beat", "Mid", "--action", "A board", "--caption", "Hi"]) == 0
    assert F.main(base + ["scene", "set", "A", "02", "--caption", "Hello", "--redraw", "all"]) == 0
    st = F.load(pd)
    st["picks"] = ["A"]
    F.save(pd, st)
    assert F.main(base + ["density", "--every", "5", "--story", "A"]) == 0
    assert F.main(base + ["doc", "add", "notes", "--kind", "notes", "--text", "# Hi\nthere"]) == 0
    assert F.main(base + ["doc", "append", "notes", "--text", "more"]) == 0
    assert F.main(base + ["doc", "new", "shotlist", "--story", "A"]) == 0
    assert F.main(base + ["plan", "pack"]) == 0
    assert F.main(base + ["doc", "list"]) == 0
    out = capsys.readouterr().out
    assert "shotlist " in out and "notes" in out and "kept shotlist" in out
    assert F.main(base + ["scene", "add", "A", "09"]) == 1                      # missing --t/--beat/--action
    assert F.main(base + ["scene", "list", "A"]) == 0
    assert F.main(base + ["doc", "rm", "notes"]) == 0
    assert F.main(base + ["doc", "rm", "notes"]) == 1
    assert "Hello" in json.dumps(SB.load(os.path.join(pd, "flow", "boards", "A")))


def test_retiming_or_adding_a_scene_keeps_the_frame_grid_and_per_scene_density_keeps_the_board_marker(pd):
    fd = os.path.join(pd, "flow")
    BE.story_set(fd, "C", "Story C", "Line")
    BE.scene_add(fd, "C", "01", [0, 10], "Hook", "A desk")
    BE.scene_add(fd, "C", "02", [10, 20], "Next", "A board")
    d = os.path.join(fd, "boards", "C")
    BE.density(fd, [("C", SB.load(d), d)], every=5)
    assert [f["t"] for f in SB.load(d)["scenes"][0]["frames"]] == [5.0]
    img(os.path.join(d, "frames", "01-t0050.png"))
    msg = BE.scene_set(fd, "C", "01", t=[0, 4])                                   # the 5 s frame is now outside the scene
    b = SB.load(d)
    assert "frames" not in b["scenes"][0] and SB.problems(b) == [] and not os.path.exists(os.path.join(d, "frames", "01-t0050.png")), msg
    BE.scene_set(fd, "C", "02", t=[10, 31])                                       # longer scene: the grid grows with it
    assert [f["t"] for f in SB.load(d)["scenes"][1]["frames"]] == [15.0, 20.0, 25.0, 30.0]
    BE.scene_add(fd, "C", "03", [31, 42], "End", "Merged")                         # a new scene joins the grid
    assert [f["t"] for f in SB.load(d)["scenes"][2]["frames"]] == [35.0, 40.0]
    BE.density(fd, [("C", SB.load(d), d)], every=2, scene="03")                    # one scene at a finer grid
    assert SB.load(d)["density"] == {"every_s": 5}
    with pytest.raises(BE.BoardError, match="no scene 99"):
        BE.density(fd, [("C", SB.load(d), d)], every=5, scene="99")

def test_flow_init_without_a_name_saves_to_the_chosen_place_not_the_current_repo(tmp_path, monkeypatch):
    from promo import home
    monkeypatch.setenv("PROMO_CONFIG", str(tmp_path / "c.yaml"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PROMO_PROJECTS", raising=False)
    shop = tmp_path / "shop"
    shop.mkdir()
    subprocess.run(["git", "init", "-q", str(shop)], check=True)
    monkeypatch.chdir(shop)
    home.main(["output", "home"])
    assert F.main(["init", "--intent", INTENT]) == 0
    assert F.main(["init", "--intent", INTENT]) == 0
    saved = sorted(os.listdir(tmp_path / "home" / ".promo-reel" / "shop"))
    assert saved == ["make-a-60s-promo-for-acme-tasks-tell-it", "make-a-60s-promo-for-acme-tasks-tell-it-2"]
    assert os.listdir(shop) == [".git"]
    monkeypatch.chdir(tmp_path / "home" / ".promo-reel" / "shop" / saved[0])
    out = F.snapshot(os.getcwd())["settings"]
    assert out["output"]["project"] == "shop" and out["output"]["mode"] == "home"
    assert out["saved_in"].endswith(saved[0])


def test_flow_init_says_when_the_save_location_is_unreachable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROMO_CONFIG", str(tmp_path / "c.yaml"))
    monkeypatch.setenv("PROMO_PROJECTS", str(tmp_path / "file" / "drive"))
    (tmp_path / "file").write_text("not a folder")
    monkeypatch.chdir(tmp_path)
    assert F.main(["init", "clip", "--intent", INTENT]) == 1
    assert "save location" in capsys.readouterr().err

def _last_active(pd, at):
    st = F.load(pd)
    for x in st["log"]:
        x["at"] = at
    F.save(pd, st)


def test_picker_lists_every_flow_most_recent_first(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    monkeypatch.setenv("PROMO_PROJECTS", str(base))
    old, new = str(base / "old-launch"), str(tmp_path / "elsewhere" / "night-teaser")
    F.init(old, "Launch film for Acme. Calm.")
    F.init(new, "Night teaser for Acme. Punchy.")                      # outside the projects dir: found because init remembered it
    _last_active(old, "2026-09-01T10:00:00+00:00")
    _last_active(new, "2026-10-01T10:00:00+00:00")
    write(str(base / "half-copied" / "flow" / "flow.json"), "{ not json")
    os.makedirs(base / "not-a-flow")
    pk = F.picker("teaser")
    assert [c["name"] for c in pk["projects"]] == ["night-teaser", "old-launch", "half-copied"]
    assert pk["projects"][2]["error"] and pk["query"] == "teaser" and pk["pickable"] is True
    card = pk["projects"][0]
    assert card["title"] == "Night teaser for Acme" and card["stage_label"] == "Style & references" and card["question"]
    shutil.rmtree(new)
    assert [c["name"] for c in F.picker()["projects"]] == ["old-launch", "half-copied"]


def test_resume_by_id_closes_the_picker(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_PROJECTS", str(tmp_path / "projects"))
    pd = str(tmp_path / "projects" / "acme")
    F.init(pd, INTENT)
    pid = F.picker()["projects"][0]["id"]
    assert F.main(["resume", pid]) == 0
    assert F.load(pd)["activity"][-1]["text"] == "Picked up again in a new thread"
    pk = F.picker(resumed=pid)
    assert pk["pickable"] is False and pk["resumed"]["id"] == pid and pk["summary"]["badge"] == "done"
    assert F.main(["resume", "no-such-project"]) == 1


# ---- live progress of long preview runs ------------------------------------------------------------------------------------------------------
def recording_commissionctl(tmp_path, monkeypatch):
    """A `commissionctl` on PATH that keeps every published state, in order, like the host's version history."""
    bindir, out = tmp_path / "bin", tmp_path / "published"
    bindir.mkdir()
    out.mkdir()
    exe = bindir / "commissionctl"
    exe.write_text(f'#!/bin/sh\nn=$(ls "{out}" | wc -l | tr -d " ")\ncp "$5" "{out}/$(printf %03d $n).json"\n')
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("COMMISSION_THREAD_TOKEN", "t")
    monkeypatch.delenv("PROMO_FLOW_PUBLISH", raising=False)
    return lambda: [json.load(open(out / f)) for f in sorted(os.listdir(out))]


def test_frame_run_publishes_a_rising_count_with_each_picture(pd, tmp_path, monkeypatch):
    board(pd, "A", make_imgs=False)
    st = F.load(pd)
    st.update(picks=["A"], stage="storyboard")
    F.save(pd, st)
    published = recording_commissionctl(tmp_path, monkeypatch)

    def make_one(prompt, final, provider, size=PV.FRAME_SIZE):
        if "Scene 02" in prompt and final.endswith("-e.png"):
            raise RuntimeError("grok produced no file")
        img(final)
    monkeypatch.setattr(PV, "_make_one", make_one)
    assert F.main(["--project", pd, "frames", "--jobs", "1"]) == 1
    states = published()
    assert [s["summary"]["status"] for s in states[:4]] == [
        "Generating storyboard images: 0 of 4 images done. Now: Scene 01 \u00b7 start frame.", "Generating storyboard images: 1 of 4 images done. Now: Scene 01 \u00b7 end frame.",
        "Generating storyboard images: 2 of 4 images done. Now: Scene 02 \u00b7 start frame.", "Generating storyboard images: 3 of 4 images done. Now: Scene 02 \u00b7 end frame."]
    assert {s["summary"]["badge"] for s in states[:4]} == {"working"}
    assert [s["summary"]["progress"] for s in states[:2]] == [dict(done=0, total=4), dict(done=1, total=4)]
    first = states[1]["job"]
    assert first["state"] == "running" and first["items"][0]["label"] == "Scene 01 · start frame" and first["items"][0]["path"]["$file"].endswith("01-s.png")
    assert [a["label"] for a in first["active"]] == ["Scene 01 · end frame"]
    last = F.snapshot(pd)["job"]
    assert (last["state"], last["done"], last["failed"], last["active"]) == ("done", 3, 1, [])
    assert [x["ok"] for x in last["items"]][-1] is False and "no file" in last["items"][-1]["error"]


def test_an_interrupted_run_reads_stopped_not_still_working(pd, monkeypatch):
    board(pd, "A", make_imgs=False)
    st = F.load(pd)
    st.update(picks=["A"], stage="storyboard")
    F.save(pd, st)
    calls = []

    def make_one(prompt, final, provider, size=PV.FRAME_SIZE):
        calls.append(final)
        if len(calls) == 2:
            raise KeyboardInterrupt
        img(final)
    monkeypatch.setattr(PV, "_make_one", make_one)
    with pytest.raises(KeyboardInterrupt):
        F.make_frames(pd, None, None, ("start", "end"), False, "auto", 1)
    snap = F.snapshot(pd)
    assert snap["job"]["state"] == "stopped" and snap["job"]["done"] == 1
    assert snap["summary"]["status"].startswith("Stopped after 1 of 4 images") and snap["summary"]["badge"] == "attention"


def test_a_build_reports_each_step_and_the_one_that_failed(pd, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from promo import assets as A
    from promo import cli
    from promo import footage as FT
    published = recording_commissionctl(tmp_path, monkeypatch)
    build = str(tmp_path / "build")
    spec = SimpleNamespace(root=pd, path=os.path.join(pd, "promo.yaml"), build=build, scale=1, validate=lambda: [])

    def step(name, fail=False):
        def run(a):
            if fail:
                raise RuntimeError("ffmpeg exited 1")
        return dict(name=name, key=name.replace(" ", "_"), dig=lambda: "d", outputs=[os.path.join(build, name + ".out")] if name.startswith("shot") else [], run=run, deps=[])
    steps = [step("sfx"), step("vo"), step("shot 01"), step("mix", fail=True), step("assemble")]
    monkeypatch.setattr(cli, "plan", lambda spec_: steps)
    monkeypatch.setattr(A, "gate", lambda spec_: None)
    monkeypatch.setattr(FT, "gate", lambda spec_, ids=None: None)
    cli.Stamps(build).write("sfx", "d")                      # unchanged since the last build
    with pytest.raises(RuntimeError):
        cli.dispatch(spec, SimpleNamespace(cmd="build", shots=None, force=False))
    statuses = [s["summary"]["status"].split(". Also open")[0] for s in published()]
    assert statuses == ["Building the video: 0 of 6 steps done. Now: Checking licences and footage", "Building the video: 1 of 6 steps done. Now: Sound effects",
                        "Building the video: 2 of 6 steps done. Now: Voice-over", "Building the video: 3 of 6 steps done. Now: Shot 01",
                        "Building the video: 4 of 6 steps done. Now: Mixing and mastering", "Stopped after 4 of 6 steps. Ask the agent to carry on"]
    job = F.snapshot(pd)["job"]
    assert (job["state"], job["done"], job["failed"], job["total"]) == ("stopped", 4, 1, 6)
    assert [(x["label"], x["ok"], x["skipped"]) for x in job["items"]] == [
        ("Checking licences and footage", True, False), ("Sound effects", True, True), ("Voice-over", True, False), ("Shot 01", True, False), ("Mixing and mastering", False, False)]
    assert job["resume"] == f"promo -p {spec.path} build"
    assert F.snapshot(pd)["summary"]["status"].startswith("Stopped after 4 of 6 steps")
