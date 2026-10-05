import json
import os

import pytest
from PIL import Image

from promo import assetplan as AP
from promo import brief as BR
from promo import flow as F
from promo import storyboard as SB

INTENT = "Make a 60s promo for commission-ai: tell it at night, wake up to merged PRs."


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
    st = F.load(pd)
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
