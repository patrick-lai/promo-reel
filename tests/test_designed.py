"""Designed-hero composition plan: thin prompt + stills -> framing / kinetic cards / plates, co-spec, no invention, kinetic type, stills as sources.

Plain asserts (pytest or `python tests/test_designed.py`). Stills are tiny synthetic PNGs: a plan never reads the pixels.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS

import numpy as np
import yaml
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import cospec, designed, designed_eval, gapfill  # noqa: E402
from promo import render as R  # noqa: E402
from promo import styles  # noqa: E402
from promo.shots import cinema as CN  # noqa: E402
from promo.spec import Shot, load_spec  # noqa: E402

PROMPT = "60s promo for my AI coding crew app. Go to bed, wake up to merged PRs."


def make_stills(d, specs=(("board", (960, 540)), ("review", (960, 540)), ("phone", (300, 650)))):
    paths = []
    for name, size in specs:
        p = os.path.join(d, f"{name}.png")
        Image.new("RGB", size, (30, 34, 48)).save(p)
        paths.append(p)
    return paths


def plan_of(prompt=PROMPT, stills=True, **kw):
    kw.setdefault("dialect", "kinetic")         # the kinetic-specific tests below; the ethereal default has its own section
    d = tempfile.mkdtemp()
    paths = make_stills(d) if stills is True else (stills or None)
    info = gapfill.apply(os.path.join(d, "p"), prompt, name="t", stills=paths, **kw)
    return info, d


# ---------------------------------------------------------------- the plan shape
def test_thin_prompt_with_stills_gets_a_designed_plan():
    info, _ = plan_of()
    plan, des = info["plan"], info["plan"]["designed"]
    assert plan["idea"] == "Go to bed, wake up to merged PRs" and plan["length"]["master_s"] == 60
    assert plan["filled"][-1] == "designed" and des["enabled"] and des["trigger"] == "thin+stills"
    for key in ("shots", "kinetic_cards", "plates", "length_band", "spine", "type_style", "framing_hierarchy", "montage", "needs", "stills"):
        assert des[key], key
    assert des["length_band"]["class"] == "standard" and des["length_band"]["recap_montage"] is True
    assert [s["name"] for s in des["spine"]][0] == "action hook" and des["spine"][-1]["s"][1] == 60.0
    assert des["type_style"]["size_pct_height"] == [8, 15] and des["type_style"]["vo_reads_onscreen"] is True
    assert des["loudness_lufs"] == -14.0
    assert {r["framing"] for r in des["shots"]} <= set(designed.FRAMINGS)
    assert abs(sum(r["seconds"] for r in des["shots"]) - 60) < 0.05
    assert {r["beat"] for r in des["shots"]} == set(designed.P.SHOT_BEATS)
    # one row per planned shot, in order, with the stills spread over them
    assert [r["n"] for r in des["shots"]] == list(range(1, len(des["shots"]) + 1))
    assert {r["ui_source"] for r in des["shots"] if r["ui_source"]} == {"board", "review", "phone"}


def test_floating_is_primary_and_fullscreen_needs_real_footage():
    info, d = plan_of()
    c = info["plan"]["designed"]["framing_hierarchy"]["counts"]
    assert c["fullscreen"] == 0, "a still is never fullscreen"
    assert c["floating"] > sum(c.values()) / 2
    assert c["device"] >= 1 and c["plate"] >= 2          # the phone-shaped still is device context; hook + end card sit on plates
    rows = info["plan"]["designed"]["shots"]
    assert all(r["framing"] == "device" for r in rows if r["ui_source"] == "phone")
    assert [r for r in rows if r["beat"] == "ask"][0]["framing"] == "plate"
    # a real clip may take the hook and one demo moment fullscreen, never more than a quarter of the UI shots
    clip = os.path.join(d, "run.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=1", "-pix_fmt", "yuv420p", clip], check=True)
    info2 = gapfill.apply(os.path.join(d, "q"), PROMPT, name="t", stills=[os.path.join(d, "board.png"), clip], dialect="kinetic")
    des = info2["plan"]["designed"]
    full = [r for r in des["shots"] if r["framing"] == "fullscreen"]
    ui = [r for r in des["shots"] if r["framing"] != "plate"]
    assert 1 <= len(full) <= len(ui) / 4 and all(r["ui_source"] == "run" for r in full)
    assert designed.gates is not None and des["framing_hierarchy"]["fullscreen_share"] <= 0.25


def test_recap_montage_accelerates_and_cuts_stay_readable():
    des = plan_of()[0]["plan"]["designed"]
    pay = [r["seconds"] for r in des["shots"] if r["beat"] == "payoff"]
    assert len(pay) >= 6 and pay[0] > pay[-1] and all(a >= b - 1e-6 for a, b in zip(pay, pay[1:]))
    assert min(pay) >= designed.MIN_SHOT_S - 1e-6 and abs(sum(pay) - 10) < 0.05
    assert des["montage"]["accelerates"] and des["montage"]["durations"] == pay
    short = plan_of("12s promo for my app. Go to bed.")[0]["plan"]["designed"]
    assert short["length_band"]["class"] == "short" and short["montage"]["enabled"] is False


def test_kinetic_cards_are_the_persons_words_and_snap_to_the_beat():
    des = plan_of()[0]["plan"]["designed"]
    cards = {c["id"]: c for c in des["kinetic_cards"]}
    ready = [c for c in cards.values() if c["status"] == "ready"]
    assert [c["text"] for c in ready] == ["Go to bed", "wake up to", "merged PRs"]
    assert [c["beat"] for c in ready] == ["hook", "payoff", "payoff"]
    assert all(len(c["text"].split()) <= designed.TYPE_STYLE["max_words_per_card"] for c in ready)
    assert all(c["vo"] == c["text"] for c in ready), "VO reads the card verbatim"
    g = designed.beat_grid(des["bpm"])
    assert all(abs(c["at"] / g - round(c["at"] / g)) < 1e-6 for c in ready)
    hook = [c for c in ready if c["beat"] == "hook"][0]
    assert hook["at"] == 0.0 and hook["shot"] == "01", "the promise is on screen at 0 s, before any logo"
    shots = {r["id"]: r for r in des["shots"]}
    assert all(shots[c["shot"]]["text_ok"] and shots[c["shot"]]["framing"] != "fullscreen" for c in ready)
    waiting = [c for c in cards.values() if c["status"] == "needs-copy"]
    assert {c["beat"] for c in waiting} == {"problem", "demo", "ask"} and all(c["text"] is None for c in waiting)
    assert {n["kind"] for n in des["needs"]} >= {"copy", "plates"}


def test_plates_are_ui_free_and_share_one_look():
    des = plan_of()[0]["plan"]["designed"]
    ids = [p["id"] for p in des["plates"]]
    assert ids == ["plate-a", "plate-b", "plate-end"]
    for p in des["plates"]:
        assert p["ui"] is False and designed.PLATE_GUARD in p["prompt"] and not any(ch.isdigit() for ch in p["prompt"])
        assert p["shots"] and p["world_source"] == "prompt"
    assert "night" in des["plates"][0]["prompt"].lower() and "dawn" in des["plates"][1]["prompt"].lower()
    neutral = plan_of("make a promo", stills=None)[0]["plan"]
    assert "designed" not in neutral, "no stills, no --designed: the plain plan is unchanged"
    forced = plan_of("make a promo", stills=None, designed=True)[0]["plan"]["designed"]
    assert forced["trigger"] == "flag" and forced["plates"][0]["world_source"] == "default"
    assert all(r["framing"] == "plate" for r in forced["shots"]) and any(n["kind"] == "ui" for n in forced["needs"])


def test_plates_are_written_as_broll_for_promo_gen_plan():
    info, d = plan_of()
    raw = yaml.safe_load(open(info["path"]).read())
    assert [b["id"] for b in raw["broll"]] == ["plate-a", "plate-b", "plate-end"] and raw["broll"][0]["kind"] == "image"
    again = gapfill.apply(os.path.join(d, "p"), PROMPT, name="t")
    assert open(again["path"]).read().count("# promo:designed BEGIN") == 1, "stills carry over; the block is not duplicated"
    assert again["plan"]["designed"]["stills"] == info["plan"]["designed"]["stills"]


# ---------------------------------------------------------------- refusing invention
def test_nothing_is_invented_for_a_blank_prompt():
    des = plan_of("make a promo", stills=True)[0]["plan"]["designed"]
    assert all(c["text"] is None for c in des["kinetic_cards"]) and all(c["status"] == "needs-copy" for c in des["kinetic_cards"])
    assert designed.check_no_invention(des, "make a promo") == []


def test_check_no_invention_refuses_made_up_words_urls_and_numbers():
    info, _ = plan_of()
    des = info["plan"]["designed"]
    assert designed.check_no_invention(des, PROMPT) == []
    for fake in ("10x faster reviews", "Join at crew.dev", "Works 24/7", "Go to bed and sleep"):
        bad = copy.deepcopy(des)
        bad["kinetic_cards"][0]["text"] = fake
        problems = designed.check_no_invention(bad, PROMPT)
        assert problems and "not words" in problems[0], fake
    bad = copy.deepcopy(des)
    bad["plates"][0]["prompt"] = "a dashboard with 3 agents"
    assert any("guard" in p for p in designed.check_no_invention(bad, PROMPT))
    bad = copy.deepcopy(des)
    bad["shots"][0]["framing"] = "fullscreen"
    assert any("fullscreen without a real source" in p for p in designed.check_no_invention(bad, PROMPT))
    # words the person wrote are fine, including a URL they gave
    ans = {"cta": "Join the waitlist at crew.example.com"}
    withcta = plan_of(answers=ans)[0]["plan"]["designed"]
    assert "crew.example.com" in " ".join(c["text"] for c in withcta["kinetic_cards"] if c["text"] and c["beat"] == "ask")
    assert designed.check_no_invention(withcta, PROMPT, ans) == []
    assert designed.check_no_invention(withcta, PROMPT, {}), "the same URL is invented once the answer is gone"


def test_must_not_blocks_a_card_and_a_claim_without_proof_never_becomes_one():
    ans = {"features": "Queue tasks; Review diffs", "must_keep": "Merges while you sleep | board still, column Merged; Works offline",
           "must_not": "offline"}
    des = plan_of(answers=ans)[0]["plan"]["designed"]
    texts = [c["text"] for c in des["kinetic_cards"] if c["text"]]
    assert "Queue tasks" in texts and "Review diffs" in texts and "Merges while you sleep" in texts
    assert not any("offline" in t.lower() for t in texts)
    assert designed.check_no_invention(des, PROMPT, ans) == []
    des2 = plan_of(answers={"must_keep": "Merges while you sleep"})[0]["plan"]["designed"]
    assert "Merges while you sleep" not in [c["text"] for c in des2["kinetic_cards"]]
    assert any(n["kind"] == "evidence" for n in des2["needs"])


def test_eval_cases_pass_and_a_tampered_plan_fails():
    cases = yaml.safe_load(open(designed_eval.DEFAULT_CASE))["cases"]
    assert len(cases) >= 2
    for case in cases:
        res = designed_eval.run_case(case)
        failed = [(n, m) for n, ok, m in res if not ok]
        assert not failed, (case["id"], failed)
    info, _ = plan_of()
    plan = copy.deepcopy(info["plan"])
    plan["designed"]["kinetic_cards"][0]["text"] = "Benchmarked 10x faster"
    plan["designed"]["framing_hierarchy"]["counts"] = {"floating": 1, "fullscreen": 5, "device": 0, "plate": 2}
    names = {n for n, ok, _ in designed_eval.check_case(plan, cases[0]) if not ok}
    assert {"no-invented-words", "floating-primary", "fullscreen-earned"} <= names


# ---------------------------------------------------------------- co-spec
def test_cospec_asks_at_most_three_in_priority_order_and_only_what_is_open():
    assert cospec.MAX_QUESTIONS == 3
    q = cospec.open_questions("make a promo", [dict(orientation="portrait")])
    assert [x["key"] for x in q] == ["cta", "audience", "world"], "one phrase = no promise question; the dialect is not ambiguous"
    assert all(x["saves"] and x["default"] for x in q)
    assert [x["key"] for x in cospec.open_questions(PROMPT, [])] == ["cta", "promise", "audience"]
    both = "A calm but punchy kinetic promo for my app. Go to bed, wake up to merged PRs."
    assert [x["key"] for x in cospec.open_questions(both, [])][0] == "dialect", "ethereal and kinetic words together are the one dialect question"
    assert "dialect" not in [x["key"] for x in cospec.open_questions(both, [], {"dialect": "kinetic"})]
    prompt = "Idea: Ship while you sleep\nfeatures: Queue; Review\ncta: Join the waitlist\naudience: indie devs"
    keys = [x["key"] for x in cospec.open_questions(prompt, [])]
    assert not {"features", "cta", "audience", "promise", "still_roles"} & set(keys)
    assert [x["key"] for x in cospec.open_questions("x", [], {"cta": "Name only", "audience": "devs", "world": "dusk"})] == ["features", "must_keep"]
    assert len(cospec.open_questions("x", [dict(orientation="square")], limit=99)) == 3
    try:
        cospec.parse_pairs(["colour=red"])
        raise AssertionError("an unknown key must be refused")
    except ValueError:
        pass
    try:
        cospec.parse_defaults(["audience=devs"])
        raise AssertionError("only the end card has a team default")
    except ValueError:
        pass


def test_cospec_answers_land_in_plan_and_replan():
    info, d = plan_of()
    dest = os.path.dirname(info["path"])
    out = subprocess.run([sys.executable, "-m", "promo", "cospec", "--dir", dest, "--json"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    open_keys = [q["key"] for q in json.loads(out.stdout)["cospec"]["open"]]
    assert open_keys == ["cta", "promise", "audience"]
    ans = subprocess.run([sys.executable, "-m", "promo", "cospec", "--dir", dest, "--json", "--answer", "cta=Join the waitlist",
                          "--answer", "promise=Wake up to merged PRs", "--answer", "audience=solo developers"], cwd=ROOT, capture_output=True, text=True)
    assert ans.returncode == 0, ans.stderr
    plan = yaml.safe_load(open(info["path"]).read())["plan"]
    assert plan["cospec"]["answers"]["cta"] == "Join the waitlist"
    assert [q["key"] for q in plan["cospec"]["open"]] == ["features", "must_keep", "still_roles"]
    texts = {}
    for c in plan["designed"]["kinetic_cards"]:
        if c["text"]:
            texts.setdefault(c["beat"], []).append(c["text"])
    assert texts["ask"] == ["Join the waitlist"] and " ".join(texts["payoff"]) == "Wake up to merged PRs" and texts["hook"] == ["Go to bed"]
    feats = subprocess.run([sys.executable, "-m", "promo", "cospec", "--dir", dest, "--json", "--answer", "features=Queue tasks; Review diffs",
                            "--answer", "still_roles=phone=desktop"], cwd=ROOT, capture_output=True, text=True)
    assert feats.returncode == 0, feats.stderr
    plan = yaml.safe_load(open(info["path"]).read())["plan"]
    demo = [c["text"] for c in plan["designed"]["kinetic_cards"] if c["beat"] == "demo" and c["text"]]
    assert demo[:2] == ["Queue tasks", "Review diffs"]
    bad = subprocess.run([sys.executable, "-m", "promo", "cospec", "--dir", dest, "--answer", "nonsense=1"], cwd=ROOT, capture_output=True, text=True)
    assert bad.returncode != 0 and "unknown answer" in (bad.stderr + bad.stdout)
    roles = cospec.apply_roles([dict(id="a", orientation="landscape"), dict(id="b", orientation="landscape")], {"still_roles": "b=phone"})
    assert roles[1]["orientation"] == "portrait" and roles[0]["orientation"] == "landscape"


def test_brief_sentence_is_not_the_idea():
    assert gapfill.one_idea(PROMPT)[0] == "Go to bed, wake up to merged PRs"
    assert gapfill.one_idea("make a promo")[1] == "default"
    assert gapfill.one_idea("anime opening of the board")[0] == "anime opening of the board"


# ---------------------------------------------------------------- build wiring
def test_apply_shots_writes_cinema_shots_the_spec_loads_and_gates_pass():
    info, d = plan_of()
    dest = os.path.dirname(info["path"])
    res = designed.apply_shots(info["path"])
    assert res["registered"] == ["board", "review", "phone"] and res["ready_plates"] == []
    text = open(info["path"]).read()
    assert text.count("# promo:designed-shots BEGIN") == 1 and "my-clip" not in text.split("designed-shots BEGIN")[1].split("designed-shots END")[0]
    assert "duration: 60.0" in text and "beats: 120" in text
    spec = load_spec(info["path"], plugins=False)
    assert len(spec.shots) == len(info["plan"]["designed"]["shots"]) and {s.type for s in spec.shots} == {"cinema"}
    gates = {g: (st, m) for g, st, m in designed.gates(spec)}
    assert set(gates) == {"designed-grounded", "designed-kinetic", "designed-clear", "designed-framing", "designed-camera", "designed-pace"}
    assert all(st == "PASS" for st, _ in gates.values()), gates
    phone = [s for s in spec.shots if s.cfg.get("source") == "phone"][0]
    assert 0.3 < CN.panel_aspect(CN.look_of(spec, phone)) < 0.6, "the portrait still gets a device-shaped panel"
    # re-running replaces, never duplicates; a hand-written shots: block is refused
    designed.apply_shots(info["path"])
    assert open(info["path"]).read().count("# promo:designed-shots BEGIN") == 1
    hand = os.path.join(d, "hand")
    gapfill.apply(hand, PROMPT, name="h", stills=make_stills(d))
    t = open(os.path.join(hand, "promo.yaml")).read().replace("my-clip", "mine")
    open(os.path.join(hand, "promo.yaml"), "w").write(t)
    try:
        designed.apply_shots(os.path.join(hand, "promo.yaml"))
        raise AssertionError("hand-written shots must be refused")
    except SystemExit as e:
        assert "--force" in str(e)
    assert dest


def test_gate_fails_text_nobody_wrote_and_type_over_ui():
    info, _ = plan_of()
    designed.apply_shots(info["path"])
    t = open(info["path"]).read().replace("text: Go to bed", "text: Works 24/7", 1)
    open(info["path"], "w").write(t)
    spec = load_spec(info["path"], plugins=False)
    g = {n: (s, m) for n, s, m in designed.gates(spec)}
    assert g["designed-grounded"][0] == "FAIL" and "WORKS 24/7" in g["designed-grounded"][1]
    info2, _ = plan_of()
    designed.apply_shots(info2["path"])
    spec2 = load_spec(info2["path"], plugins=False)
    shot = next(s for s in spec2.shots if s.cfg.get("source") == "board")
    shot.cfg["kinetic_copy"] = [dict(text="Go to bed", at=0.0, dur=2.0, size_pct=14, cy=0.4)]
    g2 = {n: (s, m) for n, s, m in designed.gates(spec2)}
    assert g2["designed-clear"][0] == "FAIL" and "overlaps the UI panel" in g2["designed-clear"][1]


def test_cli_plan_stills_to_quick_look():
    d = tempfile.mkdtemp()
    paths = make_stills(d, (("board", (960, 540)), ("review", (960, 540))))
    dest = os.path.join(d, "demo")
    r = subprocess.run([sys.executable, "-m", "promo", "plan", "demo", "--dir", dest, "--prompt", "10s promo for my app. Go to bed, wake up to merged PRs.",
                        "--stills", *paths], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "designed (thin+stills)" in r.stdout and "co-spec" in r.stdout
    p = os.path.join(dest, "promo.yaml")
    a = subprocess.run([sys.executable, "-m", "promo", "designed", "apply", "--dir", dest], cwd=ROOT, capture_output=True, text=True)
    assert a.returncode == 0, a.stderr
    b = subprocess.run([sys.executable, "-m", "promo", "-p", p, "build", "--look", "--scale", "0.5"], cwd=ROOT, capture_output=True, text=True)
    assert b.returncode == 0, b.stderr
    assert os.path.isfile(os.path.join(dest, "build", "thumbs", "strip.jpg")), "the storyboard strip of every scene exists before any full render"
    show = subprocess.run([sys.executable, "-m", "promo", "designed", "show", "--dir", dest, "--json"], cwd=ROOT, capture_output=True, text=True)
    assert json.loads(show.stdout)["designed"]["trigger"] == "thin+stills"


# ---------------------------------------------------------------- the renderer pieces
class _Ctx(R.RenderContext):
    OW, OH = 854, 480


def _spec(clip=None):
    st = styles.resolve(dict(style=dict(preset="hero", version=2)))
    return NS(style=st, raw={}, resolve=lambda p: p, footage_path=lambda cid: clip)


def _shot(cfg, n=24, fps=12):
    return Shot(id="01", b0=0, b1=n / fps * 2, t0=0.0, t1=n / fps, f0=0, n=n, fps=fps, cfg=cfg)


def test_kinetic_type_is_big_outlined_animated_and_stays_off_the_panel():
    spec = _spec()
    cfg = dict(ui=False, look=dict(backdrop="none"), kinetic_copy=[dict(text="Go to bed", at=0.0, dur=1.5, size_pct=14, anim="pop")])
    comp = CN.Composer(_Ctx(K=1, fps=12, font_path=R.DEFAULT_FONT, spec=spec, seg_dir="."), _shot(cfg), spec)
    before, mid, late, after = (np.asarray(comp.compose(None, None, t, i), np.int32) for i, t in enumerate((0.0, 0.2, 1.0, 1.9)))
    bright = lambda a: int((a.min(axis=2) > 235).sum())  # noqa: E731
    assert bright(before) == 0 and bright(after) == 0, "nothing before the card's time and after its exit"
    assert bright(late) > 1500, "white fill"
    ys = np.where((late.min(axis=2) > 235).any(axis=1))[0]
    assert 14 / 100.0 * 480 * 0.45 < ys.max() - ys.min() < 14 / 100.0 * 480 * 1.2, "cap height follows size_pct of the frame height"
    assert bright(mid) != bright(late), "the pop scales the line, it is not a static caption"
    box = CN.kinetic_box(spec, _shot(cfg), cfg["kinetic_copy"][0], (854, 480))
    assert box[0] > 0 and box[2] < 854, "a long line shrinks to fit the frame"
    # on a floating panel the type sits in the margin under it
    pcfg = dict(look=dict(panel=dict(w=0.66, cy=0.40)), source="x", kinetic_copy=[dict(text="Wake up to", at=0.0, dur=1.5)])
    pshot = _shot(pcfg)
    pb = CN.panel_box_of(spec, pshot, (1920, 1080))
    kb = CN.kinetic_box(spec, pshot, pcfg["kinetic_copy"][0], (1920, 1080))
    assert kb[1] >= pb[3] - 1 and kb[3] <= 1080


def test_a_still_is_a_source_that_holds():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.png")
        Image.new("RGB", (320, 180), (10, 200, 30)).save(p)
        w, h, fps, dur = R.probe(p)
        assert (w, h) == (320, 180) and fps == R.STILL_FPS and dur > 600
        src = R.Source(p, 0.0, 1.0)
        try:
            a, b = src.frame(0.1), src.frame(0.9)
        finally:
            src.close()
        assert a is not None and b is not None and np.asarray(a)[90, 160, 1] == 200 and np.asarray(b)[90, 160, 1] == 200


if __name__ == "__main__":
    fails = 0
    for k, v in list(globals().items()):
        if k.startswith("test_") and callable(v):
            try:
                v()
                print("ok  ", k)
            except Exception:  # noqa: BLE001
                fails += 1
                import traceback
                print("FAIL", k)
                traceback.print_exc()
    raise SystemExit(1 if fails else 0)


def test_panel_tag_sits_under_the_panels_bottom_left_and_scales_with_it():
    spec = _spec()
    tag = dict(text="Worktrees", at=0.0, dur=2.0, size_pct=6.0, anim="snap", anchor="panel-bl", gap=0.012, cx=0.9, cy=0.1)
    cfg = dict(look=dict(panel=dict(w=0.62, cy=0.42)), source="x", kinetic_copy=[tag])
    shot = _shot(cfg)
    pb = CN.panel_box_of(spec, shot, (1920, 1080))
    kb = CN.kinetic_box(spec, shot, tag, (1920, 1080))
    assert abs(kb[0] - pb[0]) < 1.0, "left-aligned to the panel's left edge (cx / cy ignored)"
    assert abs(kb[1] - (pb[3] + 0.012 * 1080)) < 1.0, "a small gap below the panel, never on the UI"
    # designed-clear still sees it as off the panel
    assert not (kb[0] < pb[2] and pb[0] < kb[2] and kb[1] < pb[3] and pb[1] < kb[3])
    # an unanchored line keeps its own cx
    free = dict(tag, anchor=None)
    assert abs((CN.kinetic_box(spec, shot, free, (1920, 1080))[0] + CN.kinetic_box(spec, shot, free, (1920, 1080))[2]) / 2 - 0.9 * 1920) < 1.0


def test_designed_apply_keeps_the_provenance_footage_add_recorded():
    from promo import footage as FT
    info, _ = plan_of()
    designed.apply_shots(info["path"])
    spec = load_spec(info["path"], plugins=False)
    st = info["plan"]["designed"]["stills"][0]
    FT.add(spec, st["path"], st["id"], commit="abc123", capture="demo=promo 60fps", demo=True, notes="real take")
    designed.apply_shots(info["path"])
    c = FT.load(load_spec(info["path"], plugins=False))[st["id"]]
    assert c["demo"] is True and c["app_commit"] == "abc123" and c["capture"] == "demo=promo 60fps" and c["notes"] == "real take"


def test_previz_reseats_a_panel_tag_when_the_panel_moves():
    from promo import previz as PV
    shot = dict(panels=[dict(id="ui-1", kind="floating", cx=0.5, cy=0.45, w=0.6, aspect=16 / 9)],
                type=[dict(id="t", text="Worktrees", size_pct=6.0, anchor="panel-bl", gap=0.012, cx=0.5, cy=0.5)])
    PV._anchor_types(shot, 16 / 9)
    tw, th = PV.type_size(shot["type"][0], 16 / 9)
    assert abs(shot["type"][0]["cx"] - tw / 2 - 0.2) < 1e-3 and abs(shot["type"][0]["cy"] - th / 2 - (0.75 + 0.012)) < 1e-3
