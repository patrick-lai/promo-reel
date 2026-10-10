"""Review rounds that hold every draft to what the person asked for: checks, the scoreboard, blind comparisons, restoring a version,
pinned notes, the look against the references, autopilot, and what carries over between videos."""
import datetime
import json
import os

import pytest
from PIL import Image

from promo import abtest as AB
from promo import autopilot as AU
from promo import flow as F
from promo import flowcheck as FC
from promo import genvideo as GV
from promo import lessons as LS
from promo import roundbrief as RB
from promo import scout as SC
from promo import second as SO
from promo import storyboard as SB
from promo import versions as VR
from promo import watch as W
from test_flow import board, img, review_draft, write


@pytest.fixture
def pd(tmp_path):
    d = str(tmp_path / "proj")
    F.init(d, "Make a 60s promo for Acme Tasks: tell it at night, wake up to merged PRs.")
    return d


def at_drafts(pd, tmp_path, n=1):
    st = F.load(pd)
    st["stage"], st["picks"] = "drafts", ["A"]
    F.save(pd, st)
    board(pd, "A")
    for _ in range(n):
        new_draft(pd, tmp_path)


def new_draft(pd, tmp_path):
    k = len(F.load(pd)["drafts"]) + 1
    p = str(tmp_path / f"d{k}.mp4")
    write(p, f"draft {k}")
    return F.add_draft(pd, p)


def close(pd, tmp_path, verdict="PARTIAL"):
    from promo import brief as BR
    c, r = str(tmp_path / "council.md"), str(tmp_path / "research.md")
    write(c, f"intent-check: intent_sha={BR.intent_sha(BR.load(pd))} verdict={verdict} intent=4 reference=4 lens=intent-reference\nquotes")
    write(r, "https://a.example/1 https://b.example/2 https://c.example/3")
    return F.round_close(pd, c, r)


def test_a_note_becomes_a_check_that_every_later_draft_is_held_to(pd, tmp_path, sheets):
    at_drafts(pd, tmp_path)
    F.round_start(pd, "the ticket count is unreadable", by="Pat")
    ticket = FC.add(pd, "The ticket count reads 8 at full size", scene="02", source="feedback", by="Pat")
    new_draft(pd, tmp_path)
    review_draft(pd)
    close(pd, tmp_path)
    d2 = F.snapshot(pd)["drafts"][1]
    assert d2["board"]["line"] == "Draft 2: 1 fixed, 0 broken, 0 open" and d2["board"]["rows"][0]["what"].startswith("The ticket count")
    assert all("Klingon" not in r["what"] and "periscope" not in r["what"] for d in F.snapshot(pd)["drafts"] for r in d["board"]["rows"])   # the control stays hidden

    F.round_start(pd, "warmer music please", by="Pat")
    FC.add(pd, "The music is warm, not cold synth", source="feedback", by="Pat")
    new_draft(pd, tmp_path)
    review_draft(pd)
    FC.mark(pd, ticket, None, "fail", "the count is cut off at 0:05", "claude")
    with pytest.raises(F.FlowError, match="breaks what the reviewed draft got right") as e:
        close(pd, tmp_path)
    assert "ticket count" in str(e.value)
    with pytest.raises(F.FlowError, match="agent"):
        FC.retire(pd, ticket, "we dropped that scene", "Claude")
    FC.retire(pd, ticket, "we dropped that scene", "Pat")
    assert close(pd, tmp_path)["closed"]


def test_a_reviewer_family_that_calls_the_control_true_does_not_count_until_it_looks_again(pd, tmp_path, sheets):
    at_drafts(pd, tmp_path)
    F.round_start(pd, "hook is slow")
    FC.add(pd, "The hook lands in the first three seconds", source="feedback")
    new_draft(pd, tmp_path)
    for c in FC.judge_checks(F.load(pd)):
        FC.mark(pd, c["id"], None, "pass", "looks fine", "claude")                  # rubber-stamped, the false control included
    sb = FC.scoreboard(F.load(pd))
    assert sb["void"] == ["claude"] and all(r["status"] == "unmeasured" for r in sb["rows"])
    review_draft(pd)                                                                   # the same family looks again, properly
    assert FC.scoreboard(F.load(pd))["void"] == [] and close(pd, tmp_path)["closed"]


def test_blind_comparison_counts_only_agreeing_orders_and_stops_a_worse_draft(pd, tmp_path, sheets):
    at_drafts(pd, tmp_path)
    F.round_start(pd, "make it calmer")
    FC.add(pd, "The pacing is calm", source="feedback")
    new_draft(pd, tmp_path)
    jid = review_draft(pd, new_wins=False)
    p = AB.pair(F.load(pd), jid)
    assert p["orders"]["1"] == dict(A=p["orders"]["2"]["B"], B=p["orders"]["2"]["A"])          # the second order swaps the sides
    with pytest.raises(F.FlowError, match="the new draft is worse"):
        close(pd, tmp_path)
    AB.judge(pd, jid, "2", "insufficient", family="claude")
    assert AB.result(AB.pair(F.load(pd), jid))["line"].startswith("The two orders")      # insufficient is not a tie and decides nothing
    assert close(pd, tmp_path)["closed"]


def test_the_persons_blind_pick_is_remembered_and_notes_that_come_back_lead(pd, tmp_path):
    a, b = str(tmp_path / "hook1.png"), str(tmp_path / "hook2.png")
    img(a, (200, 30, 30))
    img(b, (30, 30, 200))
    pid = AB.add(pd, "Which opening?", a, b, "Hook 1", "Hook 2")
    view = F.snapshot(pd)["pairs"][0]
    assert view["question"] == "Which opening?" and "Hook" not in json.dumps(view)          # labels never reach the person
    left_is_a = Image.open(view["left"]["$file"]).getpixel((0, 0))[0] == 200
    assert AB.pick(pd, pid, "left", "Pat") == ("a" if left_is_a else "b")
    assert any("preferred Hook" in x["text"] for x in LS.top("Pat"))
    LS.record("note", "Pat", "launch-video", "No speed lines over the app window")
    LS.record("note", "Pat", "october-video", "Please, no speed lines over the app")
    first = LS.top("Pat")[0]
    assert first["videos"] == 2 and first["line"].startswith("Pat, in 2 videos:")
    LS.forget(first["id"], "Pat")
    assert not any("speed lines" in x["text"] for x in LS.top("Pat"))                    # the whole group goes, not just its newest note
    assert LS.top(None) == [] and LS.top("Kim") == []                                     # one person's notes never reach another's Stage


SPEC = '''output: {name: acme}
shots:
  - id: "01"                       # opening hold
    beats: [0, 4]
    t_in: 0.0
  # --- burst
  - {id: "02", beats: [4, 5], t_in: 1.0}
'''


def test_restore_a_whole_draft_or_one_scene_and_undo_it(pd, tmp_path):
    at_drafts(pd, tmp_path, n=0)
    write(os.path.join(pd, "promo.yaml"), SPEC)
    new_draft(pd, tmp_path)
    bd = os.path.join(pd, "flow", "boards", "A")
    b = SB.load(bd)
    b["scenes"][1]["action"] = "a new idea"
    write(SB.board_path(bd), json.dumps(b))
    write(os.path.join(pd, "promo.yaml"), SPEC.replace("t_in: 1.0", "t_in: 9.5").replace("t_in: 0.0", "t_in: 3.0"))
    new_draft(pd, tmp_path)
    with pytest.raises(F.FlowError, match="agent"):
        VR.restore(pd, 1, scene="02", by="Claude")
    done, k = VR.restore(pd, 1, scene="02", by="Pat")
    spec = open(os.path.join(pd, "promo.yaml")).read()
    assert "scene 02" in done and "shot 02" in done
    assert SB.load(bd)["scenes"][1]["action"] == "something happens" and "t_in: 1.0" in spec
    assert "t_in: 3.0" in spec and "# opening hold" in spec and "# --- burst" in spec          # the other shot and the comments stay
    VR.restore(pd, undo=k, by="Pat")
    assert "t_in: 9.5" in open(os.path.join(pd, "promo.yaml")).read()
    write(os.path.join(pd, "shots.py"), "# added after draft 1\n")
    VR.restore(pd, 1, by="Pat")
    assert open(os.path.join(pd, "promo.yaml")).read() == SPEC and not os.path.exists(os.path.join(pd, "shots.py"))   # draft 1's plan had none
    assert any(x["text"].startswith("Restored") for x in LS.top("Pat", n=50))


def test_a_pinned_note_lands_on_its_scene_and_goes_into_the_next_round(pd, tmp_path):
    at_drafts(pd, tmp_path)
    pid, scene = FC.pin(pd, 1, 5.0, "the logo is tiny here", "Pat")
    assert scene == "02"
    assert F.snapshot(pd)["drafts"][0]["pins"] == [dict(id=pid, at_s=5.0, scene="02", text="the logo is tiny here", by="Pat")]
    F.round_start(pd, "see my pinned note")
    st = F.load(pd)
    c = next(x for x in st["checks"] if x["source"] == "pin")
    assert c["round"] == "1.1" and c["scene"] == "02"
    brief = open(RB.brief_path(pd, F.open_round(st))).read()
    assert brief.index("see my pinned note") < brief.index("## Checks") and "Pinned at 5.0 s of draft 1, scene 02" in brief


def test_a_pinned_note_can_be_reworded_moved_and_taken_back(pd, tmp_path):
    at_drafts(pd, tmp_path)
    pid, _ = FC.pin(pd, 1, 5.0, "the logo is tiny here", "Pat")
    old = F.load(pd)["pins"][0]["check"]
    FC.pin_edit(pd, pid, "Pat", text="the logo should be twice as big", at_s=1.0)
    st = F.load(pd)
    assert next(c for c in st["checks"] if c["id"] == old)["retired"]
    new = next(c for c in st["checks"] if c["source"] == "pin" and not c["retired"])
    assert new["what"] == "the logo should be twice as big" and new["scene"] == "01"
    assert F.snapshot(pd)["drafts"][0]["pins"] == [dict(id=pid, at_s=1.0, scene="01", text="the logo should be twice as big", by="Pat")]
    FC.pin_remove(pd, pid, "Pat")
    assert F.snapshot(pd)["drafts"][0]["pins"] == []
    assert all(c["retired"] for c in F.load(pd)["checks"] if c["source"] == "pin")
    with pytest.raises(F.FlowError):
        FC.pin_edit(pd, pid, "Pat", text="again")


def report(tmp_path, shas, rows):
    p = str(tmp_path / "acme-1080-check.json")
    write(p, json.dumps(dict(ok=True, failed=False, results=rows, outputs=[dict(file="x", sha256=s) for s in shas])))
    return p


def test_a_check_report_attaches_only_to_the_file_it_measured(pd, tmp_path):
    at_drafts(pd, tmp_path)
    rows = [dict(gate="loudness", status="PASS", msg="-14.1 LUFS"), dict(gate="duration", status="PASS", msg="60 s"),
            dict(gate="caption-hold", status="WARN", msg="caption 3 held 1.9 s"), dict(gate="vo-script", status="WARN", msg="skipped: faster-whisper not installed")]
    with pytest.raises(F.FlowError, match="other files"):
        FC.verify(pd, 1, report(tmp_path, ["0" * 64], rows))
    other = str(tmp_path / "d2.mp4")
    write(other, "draft 2")
    with pytest.raises(F.FlowError, match="other files"):
        F.add_draft(pd, other, report=report(tmp_path, ["0" * 64], rows))
    assert len(F.load(pd)["drafts"]) == 1                                                 # refused before it was registered: a retry adds no duplicate
    write(str(tmp_path / "junk.json"), "not json")
    with pytest.raises(F.FlowError, match="not a `promo check` report"):
        FC.verify(pd, 1, str(tmp_path / "junk.json"))
    assert F.snapshot(pd)["drafts"][0]["verify"]["line"] == "Not checked on this file yet."
    line = FC.verify(pd, 1, report(tmp_path, [F.load(pd)["drafts"][0]["sha"]], rows))["line"]
    assert line == "Checked on this file: 2 passed, 1 warning. Not checked: vo-script (faster-whisper not installed)"
    FC.add(pd, "Loudness is on target", kind="gate", gate="loudness")
    FC.add(pd, "The voice-over reads back word for word", kind="gate", gate="vo-script")
    assert [r["status"] for r in FC.scoreboard(F.load(pd))["rows"]] == ["pass", "unmeasured"]       # a skipped gate is not a pass


def test_the_look_may_not_move_away_from_the_references(pd, tmp_path, monkeypatch):
    at_drafts(pd, tmp_path, n=2)
    img(os.path.join(pd, "reference", "r1", "cuts", "cut-001.jpg"), (20, 20, 60))
    tint = {"d1.mp4": (22, 22, 62), "d2.mp4": (240, 200, 120)}
    monkeypatch.setattr(W, "grab", lambda path, t, dst, width=960: (img(str(dst), tint[os.path.basename(str(path))]), True)[1])
    n, res = FC.look(pd, 1)
    assert res["mean"] < 0.05 and os.path.isfile(res["scenes"]["01"]["pair"])
    FC.look(pd, 2)
    row = next(r for r in FC.scoreboard(F.load(pd))["rows"] if r["kind"] == "look")
    assert row["status"] == "fail" and row["change"] == "broken" and "moved away" in row["why"]


def test_only_the_newest_drafts_carry_look_images_so_the_stage_stays_under_its_file_cap(pd, tmp_path, monkeypatch):
    at_drafts(pd, tmp_path, n=4)
    img(os.path.join(pd, "reference", "r1", "cuts", "cut-001.jpg"), (20, 20, 60))
    monkeypatch.setattr(W, "grab", lambda path, t, dst, width=960: (img(str(dst), (22, 22, 62)), True)[1])
    for n in range(1, 5):
        FC.look(pd, n)
    drafts = F.snapshot(pd)["drafts"]
    has_pair = [any(x["pair"] for x in d["look"]["scenes"]) for d in drafts]
    assert has_pair == [False, False, True, True]
    assert all(d["look"]["mean"] < 0.05 and d["look"]["scenes"] for d in drafts)          # the score and the scene list stay for every draft


class Clock:
    def __init__(self):
        self.t = datetime.datetime(2026, 10, 7, 9, 0, tzinfo=datetime.timezone.utc)

    def __call__(self):
        return self.t.isoformat(timespec="seconds")

    def go(self, minutes):
        self.t += datetime.timedelta(minutes=minutes)


def test_autopilot_works_inside_its_time_box_and_says_why_it_stopped(pd, tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(F, "now", clock)
    at_drafts(pd, tmp_path)
    with pytest.raises(F.FlowError, match="agent"):
        AU.start(pd, 30, "Claude")
    AU.start(pd, 30, "Pat")
    for _ in range(2):
        AU.begin(pd)
        clock.go(10)
        AU.end(pd)                                                          # two passes that fixed nothing
    with pytest.raises(F.FlowError, match="new plan"):
        AU.begin(pd)
    AU.replan(pd, "cut the intro instead of re-timing it")
    assert AU.begin(pd) is None                                            # 10 min left, a pass takes ~12.5
    v = AU.view(F.load(pd))
    assert v["state"] == "out_of_time" and "20 of 30 min" in v["line"] and "min are left" in v["line"]


def test_autopilot_is_done_when_every_check_passes_on_a_checked_draft(pd, tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(F, "now", clock)
    at_drafts(pd, tmp_path)
    cid = FC.add(pd, "The end card shows the URL")
    AU.start(pd, 60, "Pat")
    AU.control(pd, "pause")
    clock.go(30)
    AU.control(pd, "resume")                                                # paused time does not count
    AU.begin(pd)
    n = new_draft(pd, tmp_path)
    FC.verify(pd, n, report(tmp_path, [F.load(pd)["drafts"][-1]["sha"]], [dict(gate="duration", status="PASS", msg="60 s")]))
    FC.mark(pd, cid, n, "pass", "URL on the card at 0:58", "claude")
    clock.go(5)
    assert AU.end(pd)[0] == "done"
    assert AU.view(F.load(pd))["used_min"] == 5.0
    aid = AU.assume(pd, "Using the calm piano track; say so to swap")
    cid2 = AU.overturn(pd, aid, "use the upbeat guitar track", "Pat")
    c = FC.find(F.load(pd), cid2)
    assert c["source"] == "assumption" and "guitar" in c["what"] and F.snapshot(pd)["assumptions"][0]["overturned"]["by"] == "Pat"


def test_project_notes_keep_decisions_and_the_agents_own_notes(pd, tmp_path):
    at_drafts(pd, tmp_path)
    F.approve(pd, "draft-approved", "Pat")
    RB.add_note(pd, "Capture used the demo workspace")
    RB.write_notes(pd)
    text = open(RB.notes_path(pd)).read()
    assert "Pat approved draft approved" in text and "Capture used the demo workspace" in text and "Latest draft: 1" in text
    assert text.count("Capture used the demo workspace") == 1 and "none yet" not in text.split("## Agent notes")[1]


def test_recipes_are_credited_by_the_round_that_used_them_and_retire_after_losses(pd, tmp_path, sheets):
    at_drafts(pd, tmp_path)
    assert any(r["id"] == "hook.result-first" for r in LS.recipes(pd))
    F.round_start(pd, "the opening is slow")
    FC.add(pd, "The opening shows the result first", source="feedback")
    F.recipe_use(pd, "hook.result-first")
    assert "hook.result-first" in open(RB.write_brief(pd)).read()
    new_draft(pd, tmp_path)
    review_draft(pd)
    close(pd, tmp_path)
    assert next(r for r in LS.recipes(pd) if r["id"] == "hook.result-first")["w"] == 1
    for _ in range(3):
        LS.credit("pacing.cut-on-downbeat", False)
    assert next(r for r in LS.recipes(pd) if r["id"] == "pacing.cut-on-downbeat")["state"] == "retired"
    assert all(r["id"] != "pacing.cut-on-downbeat" for r in LS.retrieve(pd, None, "cuts land on the strong beats of the music"))


def test_calibration_compares_the_councils_verdict_with_what_the_person_did(pd, tmp_path, sheets):
    at_drafts(pd, tmp_path)
    F.round_start(pd, "tighter")
    FC.add(pd, "The cut is under 60 seconds", source="feedback")
    new_draft(pd, tmp_path)
    review_draft(pd)
    close(pd, tmp_path, verdict="YES")
    F.round_start(pd, "still too long")                                       # the council said YES, the person sent more feedback
    assert LS.calibration() == dict(n=1, agree=0, rate=0.0, table={"YES": dict(approved=0, feedback=1)})


def test_a_real_screen_in_the_storyboard_is_a_frame_never_a_slate(pd, tmp_path):
    at_drafts(pd, tmp_path, n=0)
    flat = str(tmp_path / "screen.png")
    from test_flow import slate
    slate(flat)                                                              # a sparse app screen looks as flat as a slate
    SC.add(pd, "A", "01", flat, url="https://app.acme.dev/tasks?demo=1")
    SC.miss(pd, "A", "02", "needs an admin login")
    sc = F.snapshot(pd)["boards"][0]["scenes"]
    assert sc[0]["scout"] == "real" and sc[0]["start"]["real"] and sc[0]["start"]["path"] and not sc[0]["start"]["slate"]
    assert sc[1]["scout"] == "missed" and sc[1]["scout_why"] == "needs an admin login"
    assert F.snapshot(pd)["scout"] == dict(app_scenes=2, real=1, missed=1, drawn=0)
    bd = os.path.join(pd, "flow", "boards", "A")
    assert SB.missing(SB.load(bd), bd) == []


def test_a_second_model_family_looks_too_and_its_fail_wins(pd, tmp_path, monkeypatch):
    at_drafts(pd, tmp_path)
    cid = FC.add(pd, "The ticket count reads 8")
    FC.mark(pd, cid, 1, "pass", "8 at 0:05", "claude")
    monkeypatch.setattr(W, "grab", lambda path, t, dst, width=960: (img(str(dst)), True)[1])
    monkeypatch.setattr(GV, "detect", lambda: [dict(id="grok", available=True)])
    said = 'thinking...\n{"id": "%s", "status": "fail", "evidence": "scene 02 still shows 7 tickets"}\n{"id": "c99", "status": "pass", "evidence": "x"}\n' % cid
    text, n = SO.run(pd, 1, ask=lambda provider, prompt: said)
    assert n == 1 and "scene-02.jpg" in text and "The ticket count reads 8" in text
    assert FC.status(F.load(pd), FC.find(F.load(pd), cid), 0) == ("fail", "scene 02 still shows 7 tickets")


def test_cli_reads_do_not_publish_and_changes_rewrite_the_brief(pd, tmp_path, monkeypatch, capsys):
    at_drafts(pd, tmp_path)
    assert F.main(["--project", pd, "round", "start", "--feedback", "the music is too loud", "--by", "Pat"]) == 0
    assert F.main(["--project", pd, "check", "add", "--what", "The voice sits above the music", "--source", "feedback", "--by", "Pat"]) == 0
    brief = open(RB.brief_path(pd, F.open_round(F.load(pd)))).read()
    assert "The voice sits above the music" in brief and "Pat" in brief
    from test_flow import fake_commissionctl
    log = fake_commissionctl(tmp_path, monkeypatch)
    assert F.main(["--project", pd, "check", "list"]) == 0 and not log.exists()
    assert "Draft 1:" in capsys.readouterr().out
    assert F.main(["--project", pd, "pin", "add", "--at", "1.0", "--text", "too loud here", "--by", "Pat"]) == 0 and log.exists()
    assert F.main(["--project", pd, "pin", "edit", "n1", "--at", "2.0", "--by", "Pat"]) == 0
    assert F.main(["--project", pd, "pin", "remove", "n1", "--by", "Pat"]) == 0 and F.snapshot(pd)["drafts"][0]["pins"] == []
