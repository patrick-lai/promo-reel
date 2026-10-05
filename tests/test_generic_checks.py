"""Generic `promo check` gates (promo/generic_check.py) + the rubric helper (promo/rubric.py).
Plain asserts; `<venv>/bin/python tests/test_generic_checks.py` or pytest. No ffmpeg: frames are synthetic arrays."""
import copy
import os
import sys
import tempfile
from types import SimpleNamespace as NS

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERO_FOOTAGE_MANIFEST", os.path.join(ROOT, "projects", "commission-ai-hero", "footage", "manifest.yaml"))

from promo import generic_check as G  # noqa: E402
from promo import rubric as RB  # noqa: E402

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
HERO = os.path.join(ROOT, "projects", "commission-ai-hero", "promo.yaml")
ANIME = os.path.join(ROOT, "projects", "commission-ai-anime", "promo.yaml")
ZEN_V9 = os.path.join(ROOT, "projects", "commission-ai-anime", "reviews", "zen-v9.md")


# ---------------------------------------------------------------- rubric
def test_rubric_file_is_versioned_and_complete():
    r = RB.load()
    assert r["version"] >= 2 and r["_path"].endswith(os.path.join("evals", "rubric.yaml"))
    assert [c["key"] for c in r["criteria"]] == ["intent", "reference", "hook", "legibility", "story", "pacing", "calm", "style", "polish"]
    assert r["pass"] == dict(r["pass"], min_average=4.2, min_score=3, truth="PASS", hard_min={"intent": 4, "reference": 4})
    assert r["scale"]["min"] == 1 and r["scale"]["max"] == 5


def test_rubric_pass_fail_rules():
    r = RB.load()
    good = dict(intent=4, reference=4, hook=4, legibility=5, story=4, pacing=5, calm=4, style=4, polish=4, truth="PASS")
    v = RB.evaluate(r, good)
    assert v["ok"] and v["average"] == 4.22 and v["verdict"] == "PASS"
    v1 = RB.evaluate(r, {k: x for k, x in good.items() if k not in ("intent", "reference")})     # a v1 file: gates not evaluated
    assert not v1["ok"] and v1["verdict"] == "INCOMPLETE" and v1["average"] == 4.29 and RB.evaluate(r, {k: x for k, x in good.items() if k not in ("intent", "reference")}, legacy=True)["ok"]
    assert not RB.evaluate(r, dict(good, truth="FAIL"))["ok"]                       # truth FAIL fails whatever the scores
    low = RB.evaluate(r, dict(good, polish=2, hook=5, story=5, calm=5, style=5))       # avg 4.33 but one score < 3
    assert not low["ok"] and any("under 3" in p for p in low["problems"]) and low["average"] >= 4.2
    avg = RB.evaluate(r, dict(intent=4, reference=4, hook=4, legibility=4, story=4, pacing=4, calm=4, style=4, polish=5, truth="PASS"))  # 4.11
    assert not avg["ok"] and any("average 4.11 < 4.2" in p for p in avg["problems"])
    edge = RB.evaluate(r, dict(intent=4, reference=4, hook=4, legibility=4, story=4, pacing=4, calm=5, style=4, polish=4.8, truth="PASS"))  # exactly 4.2
    assert edge["ok"], edge
    miss = RB.evaluate(r, {k: v for k, v in good.items() if k != "story"})
    assert not miss["ok"] and "missing score: story" in miss["problems"]
    names = RB.evaluate(r, {"Intent": 4, "Reference": 4, "Hook": 4, "Legibility": 5, "Story": 4, "Pacing": 5, "calm composition": 4, "Style fidelity": 4, "Polish": 4, "Truth": "pass"})
    assert names["ok"]                                                                 # BRIEF names / Zen's capitalisation


def test_rubric_reads_zen_review_markdown_and_cli():
    sc = RB.read_scores(ZEN_V9)
    assert sc["truth"] == "PASS" and sc["Hook"] == 4 and sc["Average"] == 4.29
    v = RB.evaluate(RB.load(), sc, legacy=True)                                        # zen-v9 is a v1 review: no intent/reference scores
    assert v["ok"] and v["average"] == 4.29 and v["not_evaluated"] == ["intent", "reference"]
    assert not RB.evaluate(RB.load(), sc)["ok"]
    d = tempfile.mkdtemp()
    p = os.path.join(d, "s.yaml")
    yaml.safe_dump(dict(scores=dict(intent=3, reference=3, hook=3, legibility=3, story=3, pacing=3, calm=3, style=3, polish=3, truth="PASS")), open(p, "w"))
    from promo import cli
    assert cli.main(["rubric", p]) == 1                                                # avg 3.0 -> FAIL exit 1
    assert cli.main(["rubric", ZEN_V9]) == 3                                           # v1 review: INCOMPLETE (exit 3)
    assert cli.main(["rubric", ZEN_V9, "--legacy"]) == 0


def test_critique_brief_reads_the_rubric_file():
    from promo import critique as CR
    r = RB.load()
    assert CR.RUBRIC == RB.criteria(r)
    d = tempfile.mkdtemp()
    alt = copy.deepcopy({k: v for k, v in r.items() if k != "_path"})
    alt["version"] = 99
    hook = next(c for c in alt["criteria"] if c["key"] == "hook")
    hook["question"] = "Does second one land?"
    alt["pass"]["min_average"] = 4.5
    alt["pass"]["text"] = "truth PASS, nothing under 3, average >= 4.5."
    p = os.path.join(d, "rubric.yaml")
    yaml.safe_dump(alt, open(p, "w"))
    os.environ["PROMO_RUBRIC"] = p
    try:
        from promo.spec import load_spec
        s = load_spec(HERO)
        md = CR.brief_md(s, "hero", "/x/t.mp4", [], dict(copy=[], footage=[], reviews=[]), dict(failed=False, results=[]),
                         True, False, False, [])
    finally:
        del os.environ["PROMO_RUBRIC"]
    assert "3. **hook**: Does second one land?" in md and "average >= 4.5" in md and "v99" in md
    assert RB.evaluate(RB.load(p), dict(intent=4, reference=4, hook=4, legibility=5, story=4, pacing=5, calm=4, style=4, polish=4, truth="PASS"))["verdict"] == "FAIL"


# ---------------------------------------------------------------- per-preset config
def test_warn_rules_per_preset_and_project_override():
    hero = NS(style={"preset": None}, qa={}, raw={})
    anime = NS(style={"preset": "anime-opening"}, qa={}, raw={})
    live = NS(style={"preset": "livestream"}, qa={}, raw={})
    assert G.rules_for(hero)["empty_frame"]["max_frac"] == 0.40 and G.rules_for(hero)["long_hold"]["max_s"] == 3.5
    assert G.rules_for(anime)["empty_frame"]["max_frac"] == 0.40 and G.rules_for(anime)["long_hold"]["max_s"] == 2.8
    assert G.rules_for(live)["long_hold"]["max_s"] == 6.0
    # a talk-show spec without a style preset (the framed preview) still gets the livestream rules
    assert G.rules_for(NS(style={}, qa={}, raw={"livestream": {"screen": {}}}))["long_hold"]["max_s"] == 6.0
    over = NS(style={"preset": None}, qa={"warn_rules": {"long_hold": {"max_s": 9}, "text_edge": {"on": False}}}, raw={})
    r = G.rules_for(over)
    assert r["long_hold"]["max_s"] == 9 and r["long_hold"]["pix_delta"] == G.WARN_RULES["_default"]["long_hold"]["pix_delta"] and not r["text_edge"]["on"]


# ---------------------------------------------------------------- text-edge heuristic
def _ui(W=1920, H=1080, bg=26):
    im = Image.new("L", (W, H), bg)
    return im, ImageDraw.Draw(im)


def _g(im):
    return np.asarray(im).astype(np.float32)


def test_text_edge_flags_a_word_cut_at_the_right_edge_and_top():
    cfg = G.WARN_RULES["_default"]["text_edge"]
    f = ImageFont.truetype(FONT, 30)
    im, d = _ui()
    d.text((1700, 400), "Landed column", font=f, fill=230)        # runs off the right edge
    hits = G.edge_hits(_g(im), [0, 0, 1920, 1080], cfg)
    assert any(e == "right" and 390 <= y <= 450 for e, y, _ in hits), hits
    im, d = _ui()
    d.text((600, -14), "8 in this run · 8 landed", font=f, fill=230)   # cut by the top edge
    hits = G.edge_hits(_g(im), [0, 0, 1920, 1080], cfg)
    assert any(e == "top" for e, _, _ in hits), hits


def test_text_edge_ignores_clean_edges_lines_and_cards():
    cfg = G.WARN_RULES["_default"]["text_edge"]
    f = ImageFont.truetype(FONT, 30)
    im, d = _ui()
    d.text((800, 500), "PAY-103 Design tokens", font=f, fill=230)    # text well inside
    d.line([(0, 300), (1919, 300)], fill=200, width=1)                # a divider crossing both side edges
    d.rectangle([1700, 600, 1919, 900], fill=60)                      # a card panel running into the edge (no glyphs at the edge)
    d.rectangle([0, 0, 1919, 40], fill=45)                            # a header bar along the top
    assert G.edge_hits(_g(im), [0, 0, 1920, 1080], cfg) == []


def test_text_edge_uses_the_crop_viewport():
    cfg = G.WARN_RULES["_default"]["text_edge"]
    f = ImageFont.truetype(FONT, 30)
    im, d = _ui()
    d.text((700, 900), "Running checks", font=f, fill=230)         # crosses y = 918 (an anime band top)
    assert any(e == "bottom" for e, _, _ in G.edge_hits(_g(im), [0, 0, 1920, 918], cfg))
    assert not any(e == "bottom" for e, _, _ in G.edge_hits(_g(im), [0, 0, 1920, 1080], cfg))


def test_text_edge_needs_a_persistent_isolated_cut():
    cfg = G.WARN_RULES["_default"]["text_edge"]
    w = "x"
    one = [("right", 205, w), ("left", 600, w)]
    # same word on 2 of 3 samples (within pos_tol) -> kept; a one-off hit is noise
    assert G.persistent_edges([one, [("right", 210, w)], []], cfg) == [("right", 205, 2)]
    # scrolling text (moves > pos_tol between samples) does not persist
    assert G.persistent_edges([[("right", 100, w)], [("right", 160, w)], [("right", 220, w)]], cfg) == []
    # a push-in cropping a whole text column (many lines on one edge) is framing, not a cut word
    col = [("left", 100 + 40 * i, w) for i in range(6)]
    assert G.persistent_edges([col, col, col], cfg) == []
    # top / bottom stroke hits are off by default (panel scrolls); a project can opt in
    assert G.persistent_edges([[("top", 600, w)]] * 3, cfg) == []
    assert G.persistent_edges([[("top", 600, w)]] * 3, dict(cfg, edges=None)) == [("top", 600, 3)]


def test_text_edge_ignores_frame_corners():
    cfg = G.WARN_RULES["_default"]["text_edge"]
    f = ImageFont.truetype(FONT, 30)
    im, d = _ui()
    d.text((1880, 4), "Ab", font=f, fill=230)                     # ink in the top-right corner only (a rounded frame corner)
    assert [h for h in G.edge_hits(_g(im), [0, 0, 1920, 1080], cfg) if h[0] == "right"] == []


# ---------------------------------------------------------------- empty-frame
def test_empty_frame_measures_dotted_canvas_as_empty():
    cfg = G.WARN_RULES["_default"]["empty_frame"]
    im, d = _ui(bg=22)
    for y in range(0, 1080, 24):                                       # dotted board canvas
        for x in range(0, 1920, 24):
            d.point((x, y), fill=70)
    f = ImageFont.truetype(FONT, 28)
    for i in range(6):                                                 # a column of cards on the right third
        d.rectangle([1300, 60 + i * 160, 1880, 200 + i * 160], fill=48, outline=120)
        d.text((1320, 80 + i * 160), f"PAY-10{i} Card title text", font=f, fill=225)
    d.text((40, 40), "All done · Plan next   8 in this run · 8 landed", font=f, fill=225)
    frac, box = G.empty_fraction(_g(im), [0, 0, 1920, 1080], cfg)
    assert 0.5 < frac < 0.75, frac                                     # left ~2/3 below the header = one empty region
    im2, d2 = _ui(bg=22)
    for y in range(40, 1040, 60):                                      # a frame full of text lines
        d2.text((40, y), "Approved. The change matches the plan and the checks pass " * 2, font=f, fill=225)
    frac2, _ = G.empty_fraction(_g(im2), [0, 0, 1920, 1080], cfg)
    assert frac2 < 0.2, frac2


def test_ui_shot_needs_footage():
    s = NS(type="clip", cfg={}, dur=2.0, clip="", clips=[], id="10")
    assert G.is_ui_shot(NS(raw={}, footage_manifest=None), s, G.WARN_RULES["_default"]) is False


# ---------------------------------------------------------------- long-hold
def test_longest_static_run():
    d = [5, 5, 0.1, 0.1, 0.2, 0.1, 9, 0.1, 0.1]
    assert G.longest_static(d, 0.35) == (5, 2)                         # 4 sub-threshold diffs = 5 identical frames from frame 2
    assert G.longest_static([1, 2, 3], 0.35) == (0, 0)


def test_changed_fraction_sees_typing_but_not_noise():
    rng = np.random.default_rng(0)
    base = np.full((216, 384), 30, np.float32)
    noisy = np.stack([base + rng.uniform(-3, 3, base.shape) for _ in range(4)])     # encoder noise only
    assert (G.changed_fraction(noisy) <= 0.0005).all()
    typed = noisy.copy()
    typed[2:, 100:106, 200:216] = 220                                               # a typed word appears (96 px at 384 wide)
    d = G.changed_fraction(typed)
    assert d[1] > 0.0005 and d[0] <= 0.0005 and d[2] <= 0.0005                       # the old mean-abs metric missed this


# ---------------------------------------------------------------- caption-truth
def test_caption_counts():
    assert G.caption_counts("8 TASKS · ALL LANDED") == {"cards": 8, "landed": "all"}
    assert G.caption_counts("Split into 8 tasks.") == {"cards": 8}
    assert G.caption_counts("3 AGENTS. ONE PLAN.") == {"agents": 3}
    assert G.caption_counts("Reviewed, with the reason why.") == {}
    assert G.manifest_counts_text("header '8 in this run · 8 landed'; the promo plan of 8")["cards"] == {8}


def _hero(mut=None):
    from promo.render import RenderContext
    from promo.spec import load_spec
    s = load_spec(HERO)
    if mut:
        mut(s)
    return s, RenderContext.from_spec(s)


def _caption(s, sid, text):
    sh = next(x for x in s.shots if x.id == sid)
    for o in sh.cfg["overlays"]:
        if o.get("type") == "caption":
            o["text"] = text


def test_caption_truth_on_the_hero_and_its_negatives():
    s, ctx = _hero()
    assert G.caption_truth_gate(s, ctx)[0][1] == "PASS"
    s, ctx = _hero(lambda s: _caption(s, "04", "Split into 7 tasks."))
    g = G.caption_truth_gate(s, ctx)[0]
    assert g[1] == "WARN" and "shot 04" in g[2] and "cards 7" in g[2] and "8]" in g[2], g
    s, ctx = _hero(lambda s: _caption(s, "12", "3 agents reviewed it."))      # no record of 3 anywhere
    g = G.caption_truth_gate(s, ctx)[0]
    assert g[1] == "WARN" and "shot 12" in g[2] and "not backed" in g[2], g

    def legible7(s):
        s.raw["claims"]["legible"]["shot11_legible"]["landed"] = 7
    s, ctx = _hero(legible7)
    g = G.caption_truth_gate(s, ctx)[0]
    assert g[1] == "WARN" and "shot 11" in g[2], g


def test_claims_gate_folded_for_projects_without_a_preset():
    s, ctx = _hero()
    g = G.claims_gate(s, ctx)
    assert g and g[0][0] == "claims" and g[0][1] == "PASS" and "== claims.landed_count" in g[0][2]

    def legible7(s):
        s.raw["claims"]["legible"]["shot11_legible"]["landed"] = 7    # table now selects 'LANDED.' -> literal caption outruns it
    s, ctx = _hero(legible7)
    g = G.claims_gate(s, ctx)[0]
    assert g[1] == "FAIL" and "selects 'LANDED.'" in g[2], g
    from promo.spec import load_spec
    assert G.claims_gate(load_spec(ANIME)) == []                       # anime-opening runs its own claims gate


# ---------------------------------------------------------------- named (folded) on clip shots
def test_named_gate_on_a_clip_shot_still():
    d = tempfile.mkdtemp()
    im = Image.new("L", (1920, 1080), 24)
    dr = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, 14)                                   # ~10 px cap height at 1.0x
    dr.text((900, 500), "Needs you", font=f, fill=230)
    png = os.path.join(d, "ui.png")
    im.save(png)

    def spec_with(cam_w, box=(895, 495, 1010, 520), info=False):
        cfg = dict(source="x", t_in=0.0, cam=[[0, 0.5, 0.48, cam_w], ["end", 0.5, 0.48, cam_w]],
                   named=[dict(name="chip 'Needs you'", box=list(box), t=[0.5, 1.0], min_px=18, info=info)])
        sh = NS(id="10", type="clip", cfg=cfg, n=60, fps=30, dur=2.0, t0=0, t1=2.0)
        return NS(shots=[sh], fps=30, footage_path=lambda cid: png)
    small = G.named_clip_gates(spec_with(1.0))[0]
    assert small[0][0] == "named" and small[0][1] == "FAIL" and "(min 18)" in small[0][2], small
    big = G.named_clip_gates(spec_with(0.45))[0]                       # 2.2x push-in: ~22 px, upscaled
    assert big[0][1] == "PASS" and big[1] == ("named-upscale", "WARN", big[1][2]) and "x2.22" in big[1][2], big
    info = G.named_clip_gates(spec_with(1.0, info=True))[0]
    assert info[0][1] == "PASS" and ", info" in info[0][2]
    edge, clipped = G.named_clip_gates(spec_with(0.45, box=(895, 495, 1400, 520)))   # box runs past the crop
    assert edge[0][1] == "FAIL" and "NOT fully in frame" in edge[0][2] and clipped and "crosses the crop edge" in clipped[0]


def test_hero_named_rows_live_in_the_spec_as_qa_only_keys():
    from promo import cli
    from promo.spec import load_spec
    s = load_spec(HERO)
    rows = [(x.id, e["name"]) for x in s.shots for e in x.cfg.get("named") or []]
    assert ("11", "header '8 in this run · 8 landed' (r2)") in rows and ("16", "PR badge 'Merged' (tighter)") in rows
    assert len(rows) == 12
    # QA-only: adding / removing `named:` never changes a shot digest (no re-render of the locked cut)
    sh = next(x for x in s.shots if x.id == "11")
    dg = cli.shot_digest(s, sh)
    ev = next(x for x in cli.plan(s) if x["name"] == "events")["dig"]()
    sh.cfg = {k: v for k, v in sh.cfg.items() if k != "named"}
    assert cli.shot_digest(s, sh) == dg
    for r in s.raw["shots"]:                                   # ... nor the events step (it hashes the raw shots)
        r.pop("named", None)
    assert next(x for x in cli.plan(s) if x["name"] == "events")["dig"]() == ev


if __name__ == "__main__":
    fails = 0
    for k, v in list(globals().items()):
        if k.startswith("test_") and callable(v):
            try:
                v()
                print("ok  ", k)
            except Exception as e:  # noqa: BLE001
                fails += 1
                import traceback
                traceback.print_exc()
                print("FAIL", k, e)
    sys.exit(1 if fails else 0)
