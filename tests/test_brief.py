"""Locked brief: verbatim intent, references with `why`, conflicts, confirm, the three project-level gates, rubric v2 hard gates
(plain asserts; `python tests/test_brief.py` or pytest)."""
import os
import sys
import tempfile
from types import SimpleNamespace as NS

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from promo import brief as BR  # noqa: E402
from promo import cli  # noqa: E402
from promo import rubric as RB  # noqa: E402

INTENT = "Make it feel like this short film: two people, a real conversation, quiet piano. Not a UI montage."


def proj(intent=INTENT):
    d = os.path.join(tempfile.mkdtemp(), "projects", "p")
    BR.init(d, intent)
    return d


def st(rows, gate):
    return next(s for g, s, m in rows if g == gate)


def test_init_show_and_hash_cover_the_user_words():
    d = proj()
    b = BR.load(d)
    assert b["intent_verbatim"] == INTENT and b["confirmed"]["hash"] is None
    h1 = BR.content_hash(b)
    b["intent_verbatim"] += " "                      # whitespace at the edges is not an edit
    assert BR.content_hash(b) == h1
    b["intent_verbatim"] = INTENT.replace("quiet", "loud")
    assert BR.content_hash(b) != h1 and BR.intent_sha(b) != BR.intent_sha(BR.load(d))
    assert INTENT in BR.show_text(d) and "intent-check: intent_sha=" + BR.intent_sha(BR.load(d)) in BR.show_text(d)
    try:
        BR.init(d, "other")                          # never silently overwrite the user's words
        raise AssertionError("init overwrote")
    except BR.BriefError:
        pass
    assert cli.main(["brief", "show", "--project", d]) == 0


def test_check_fails_on_missing_empty_whyless_and_pending():
    d = tempfile.mkdtemp()
    assert BR.check(d)[0][1] == "FAIL"                                           # missing
    d = proj("")
    assert "intent_verbatim is empty" in BR.check(d)[0][2]
    d = proj()
    b = BR.load(d)
    b["references"] = [dict(id="short", url="https://example.org/v", why="")]
    BR.save(d, b)
    assert BR.check(d)[0][1] == "FAIL" and "`why` is empty" in BR.check(d)[0][2]
    b["references"][0]["why"] = "the user: 'this exact feeling, the two people at the table'"
    BR.save(d, b)
    assert BR.check(d)[0][1] == "WARN"                                           # structurally fine, unconfirmed
    n = BR.add_conflict(d, "reference has actors, team rule says real footage only", "AGENTS.md 0.1", ref="short")
    assert n == 1 and BR.check(d)[0][1] == "FAIL" and "pending" in BR.check(d)[0][2]
    BR.decide_conflict(d, 1, "use real screen recordings of people using the product; no actors", "Patrick")
    assert BR.check(d)[0][1] == "WARN"
    b = BR.load(d)
    b["conflicts"][0]["decided_by"] = None
    BR.save(d, b)
    assert "decided_by" in BR.check(d)[0][2]


def test_confirm_needs_matching_hash_and_a_human():
    d = proj()
    b = BR.load(d)
    b["references"] = [dict(id="r", url="https://example.org/v", why="their words")]
    BR.save(d, b)
    h = BR.content_hash(BR.load(d))
    for by, hh in (("claude", h), ("Patrick", "deadbeef"), ("Patrick", None), ("", h), ("my-agent", h)):
        try:
            BR.confirm(d, by, hh)
            raise AssertionError(f"confirmed with by={by!r} hash={hh!r}")
        except BR.BriefError:
            pass
    assert BR.check(d)[0][1] == "WARN"
    cf = BR.confirm(d, "Patrick", h)
    assert cf["hash"] == h and cf["by"] == "Patrick" and BR.check(d)[0][1] == "PASS"
    b = BR.load(d)
    b["must_not"] = ["no actors"]                                               # edited after confirmation
    BR.save(d, b)
    row = BR.check(d)[0]
    assert row[1] == "WARN" and "edited since" in row[2]
    # not confirmable while a structural FAIL exists
    BR.add_conflict(d, "x", "y")
    try:
        BR.confirm(d, "Patrick", BR.content_hash(BR.load(d)))
        raise AssertionError("confirmed with a pending conflict")
    except BR.BriefError as e:
        assert "pending" in str(e)


def decision(d, n, text):
    os.makedirs(os.path.join(d, "rounds", str(n)), exist_ok=True)
    open(os.path.join(d, "rounds", str(n), "decision.md"), "w").write(text)


def test_intent_review_gate_on_the_newest_round():
    d = proj()
    sha = BR.intent_sha(BR.load(d))
    assert st(BR.intent_review(d), "intent-review") == "WARN"                    # no rounds yet
    decision(d, 1, f"# Round 1\nintent-check: intent_sha={sha} verdict=YES intent=4 reference=4 lens=intent-reference\n")
    assert st(BR.intent_review(d), "intent-review") == "PASS"
    decision(d, 2, "# Round 2\nmean 4.3\n")                                      # newest round lacks it, older one has it
    r = BR.intent_review(d)[0]
    assert r[1] == "FAIL" and "rounds/2" in r[2] and "no `intent-check:` line" in r[2]
    decision(d, 2, "intent-check: intent_sha=0123456789ab verdict=YES intent=5 reference=5\n")
    assert "different text" in BR.intent_review(d)[0][2]                          # lens read another text
    decision(d, 2, f"intent-check: intent_sha={sha}\n")
    assert "verdict" in BR.intent_review(d)[0][2]
    decision(d, 2, f"intent-check: intent_sha={sha} verdict=NO intent=2 reference=3\n")
    assert BR.intent_review(d)[0][1] == "FAIL"
    decision(d, 2, f"intent-check: intent_sha={sha} verdict=YES intent=3 reference=5\n")   # verdict says yes, score under hard_min
    assert BR.intent_review(d)[0][1] == "FAIL" and "intent 3 < 4" in BR.intent_review(d)[0][2]
    decision(d, 2, f"intent-check: intent_sha={sha} verdict=PARTIAL intent=4 reference=4\n")
    assert BR.intent_review(d)[0][1] == "WARN"
    decision(d, 10, f"- intent-check: intent_sha={sha[:10]} verdict=yes intent=5 reference=4\n")   # numeric order: 10 > 2; prefix + case ok
    assert BR.intent_review(d)[0][1] == "PASS" and "rounds/10" in BR.intent_review(d)[0][2]


def test_project_gate_missing_brief_warns_or_fails_when_required():
    from test_styles import GOOD, anime_project
    from promo.spec import load_spec
    p = anime_project(GOOD)
    rows = BR.gates(load_spec(p))
    assert [r[:2] for r in rows] == [("brief", "WARN")]
    raw = yaml.safe_load(open(p))
    raw["style"]["require_brief"] = True
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    s = load_spec(p)
    assert s.style["require_brief"] is True and BR.gates(s)[0][:2] == ("brief", "FAIL")
    BR.init(os.path.dirname(p), INTENT)                                          # present: brief + references + intent-review rows
    rows = BR.gates(s)
    assert [r[0] for r in rows] == ["brief", "references", "intent-review"]


def test_rubric_v2_hard_gates_cannot_be_averaged_away():
    r = RB.load()
    assert r["version"] >= 2 and r["pass"]["hard_min"] == {"intent": 4, "reference": 4}
    assert [c["key"] for c in r["criteria"]][:2] == ["intent", "reference"] and len(r["criteria"]) == 9
    base = dict(hook=5, legibility=5, story=5, pacing=5, calm=5, style=5, polish=5, truth="PASS")
    ok = RB.evaluate(r, dict(base, intent=4, reference=4))
    assert ok["ok"] and ok["verdict"] == "PASS" and not ok["not_evaluated"]
    low = RB.evaluate(r, dict(base, intent=5, reference=3))                       # average 4.78, reference 3 >= min_score 3
    assert low["average"] > 4.2 and not low["ok"] and low["verdict"] == "FAIL" and any("hard gate reference 3 < 4" in p for p in low["problems"])
    # a v1 file (seven scores): not evaluated, reported, never PASS
    v1 = RB.evaluate(r, dict(base))
    assert not v1["ok"] and v1["verdict"] == "INCOMPLETE" and v1["not_evaluated"] == ["intent", "reference"] and v1["average"] == 5.0
    assert any(p.startswith("not evaluated: intent, reference") for p in v1["problems"])
    leg = RB.evaluate(r, dict(base), legacy=True)                                 # archived v1 review
    assert leg["ok"] and leg["verdict"] == "PASS" and leg["not_evaluated"] == ["intent", "reference"]
    mixed = RB.evaluate(r, dict(base, polish=2))                                  # a real failure wins over INCOMPLETE
    assert mixed["verdict"] == "FAIL"


def test_rubric_cli_and_v1_review_markdown_still_parse():
    zen = os.path.join(ROOT, "projects", "commission-ai-anime", "reviews", "zen-v9.md")
    if os.path.exists(zen):
        sc = RB.read_scores(zen)
        assert sc["truth"] == "PASS" and sc["Hook"] == 4
        assert cli.main(["rubric", zen]) == 3                                     # INCOMPLETE: intent/reference not scored
        assert cli.main(["rubric", zen, "--legacy"]) == 0
    d = tempfile.mkdtemp()
    p = os.path.join(d, "s.yaml")
    yaml.safe_dump(dict(scores=dict(intent=5, reference=5, hook=4, legibility=4, story=4, pacing=4, calm=4, style=4, polish=4, truth="PASS")), open(p, "w"))
    assert cli.main(["rubric", p]) == 0


def test_critique_pack_carries_intent_references_and_compare_as_hard_gates():
    from promo import critique as CR
    from promo import refs as RF
    d = proj()
    sha = BR.intent_sha(BR.load(d))
    b = BR.load(d)
    b["references"] = [dict(id="film", url="https://example.org/v", why="'exactly this kitchen scene'")]
    b["must_not"] = ["no UI montage"]
    BR.save(d, b)
    rd = RF.ref_dir(d, "film")
    os.makedirs(os.path.join(rd, "sheets"))
    for f, t in (("DOSSIER.md", "# d"), ("transcript.json", "{}"), ("sheets/sheet-01.png", "x")):
        open(os.path.join(rd, f), "w").write(t)
    os.makedirs(os.path.join(d, "out", "compare"))
    open(os.path.join(d, "out", "compare", "film-vs-draft.md"), "w").write("# c")
    spec = NS(root=d, masters=[{}], output_path=lambda suffix="": os.path.join(d, "out", "none.mp4"))
    root = tempfile.mkdtemp()
    info = CR.brief_inputs(spec, root)
    assert info["intent_sha"] == sha and info["compare"] == ["compare/film-vs-draft.md"]
    for f in ("brief/brief.yaml", "reference/film/DOSSIER.md", "reference/film/transcript.json", "reference/film/sheets/sheet-01.png",
              "compare/film-vs-draft.md"):
        assert os.path.isfile(os.path.join(root, f)), f
    md = "\n".join(CR.intent_section(RB.load(), info))
    for want in (INTENT, f"intent_sha `{sha}`", "intent >= 4", "reference >= 4", "cannot be averaged away", "no UI montage", "exactly this kitchen scene",
                 "intent-check: intent_sha=" + sha, "never a pass", "style summary an agent"):
        assert want in md, want
    none = "\n".join(CR.intent_section(RB.load(), None))
    assert "No `brief.yaml`" in none and "Score both 1" in none
    assert CR.brief_inputs(NS(root=tempfile.mkdtemp(), masters=[{}], output_path=lambda s="": ""), root) is None


def test_cli_roundtrip():
    d = os.path.join(tempfile.mkdtemp(), "projects", "q")
    assert cli.main(["brief", "init", "--project", d, "--intent", INTENT]) == 0
    assert cli.main(["brief", "check", "--project", d]) == 0                      # WARN only (no refs, unconfirmed, no rounds)
    assert cli.main(["brief", "conflict", "add", "--project", d, "--what", "w", "--rule", "r"]) == 0
    assert cli.main(["brief", "check", "--project", d]) == 1                      # pending conflict FAILs
    assert cli.main(["brief", "confirm", "--project", d, "--by", "claude", "--hash", "x"]) == 2
    assert cli.main(["brief", "conflict", "decide", "--project", d, "1", "--decision", "ok", "--by", "Patrick"]) == 0
    h = BR.content_hash(BR.load(d))
    assert cli.main(["brief", "confirm", "--project", d, "--by", "Patrick", "--hash", h]) == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
