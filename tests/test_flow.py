import json
import os

import pytest
from PIL import Image

from promo import assetplan as AP
from promo import brief as BR
from promo import flow as F
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


def test_init_locks_brief_and_cannot_skip(pd):
    assert BR.load(pd)["intent_verbatim"] == INTENT
    with pytest.raises(F.FlowError, match="cannot leave"):
        F.advance(pd)


def test_agent_cannot_approve(pd):
    with pytest.raises(F.FlowError, match="agent"):
        F.approve(pd, "scripts-picked", "Claude", ["A"])


def test_happy_path_and_gates(pd, tmp_path):
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
    assert "new draft" in str(e.value) and "3 distinct" in str(e.value)
    write(research, "https://a.example/1 https://b.example/2 https://c.example/3")
    F.add_draft(pd, dr, "v2")
    r = F.round_close(pd, council, research)
    assert r["closed"]["verdict"] == "PARTIAL"
    # wrong intent hash is refused
    F.round_start(pd, "again")
    F.add_draft(pd, dr, "v3")
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
    for n in range(1, 6):
        st["rounds"].append(dict(cycle=1, n=n, feedback="f", started="", drafts_at_start=0, closed=dict(verdict="YES")))
    F.save(pd, st)
    with pytest.raises(F.FlowError, match="5 rounds"):
        F.round_start(pd, "more")


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


def test_keyframes_asks_the_person_for_missing_recordings(pd):
    at_storyboard(pd)
    st = F.load(pd)
    st["stage"] = "keyframes"
    F.save(pd, st)
    AP.save(os.path.join(pd, "flow"), [dict(id="r", kind="recording", source="mock", scenes=["01"], how="h"), dict(id="m", kind="music", source="mock", scenes=["01"], how="h")])
    s = F.snapshot(pd)["summary"]
    assert s["badge"] == "waiting" and s["status"].startswith("Your turn: 1 recording to capture")
    AP.save(os.path.join(pd, "flow"), [dict(id="m", kind="music", source="mock", scenes=["01"], how="h")])
    assert F.snapshot(pd)["summary"]["badge"] == "working"
