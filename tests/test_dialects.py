"""The two craft dialects of the thin-prompt uplift: ethereal (default) and kinetic.

Selection from a thin prompt, the ethereal defaults, how kinetic differs, the team-default CTA, the commission-ai e2e recipe, the
compiled ethereal shots, the dialect-aware gates and the renderer's ethereal moves (snap, cascade, brackets, anchors, thumb, mosaic).
Plain asserts (pytest). Stills are tiny synthetic PNGs: a plan never reads the pixels.
"""
import copy
import os
import subprocess
import sys
import tempfile

import numpy as np
import yaml
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_designed import PROMPT, _Ctx, _shot, _spec, make_stills  # noqa: E402

from promo import cospec, designed, gapfill  # noqa: E402
from promo import render as R  # noqa: E402
from promo.shots import cinema as CN  # noqa: E402
from promo.spec import load_spec  # noqa: E402

E2E_PROMPT = "60s promo for my AI coding crew. Go to bed. Wake up to merged PRs."
E2E_STILLS = ("shot-01-v1-poster", "shot-06-still-board", "shot-12-ask-the-reviewer-v1-poster")
TEAM_CTA = "Your AI dev crew, on your Mac."


def e2e_plan(prompt=E2E_PROMPT, extra_stills=(), **kw):
    d = tempfile.mkdtemp()
    paths = make_stills(d, tuple((n, (1600, 900)) for n in E2E_STILLS)) + list(extra_stills)
    info = gapfill.apply(os.path.join(d, "p"), prompt, name="crew", stills=paths, **kw)
    return info, d


# ---------------------------------------------------------------- selection
def test_a_thin_prompt_with_no_style_words_is_ethereal_by_default():
    p = designed.pick_dialect(E2E_PROMPT)
    assert p == dict(name="ethereal", source="default", matched=[], ambiguous=False)
    assert designed.pick_dialect("make a promo")["name"] == "ethereal"
    assert designed.DEFAULT_DIALECT == "ethereal"


def test_words_flags_labels_and_answers_pick_the_dialect():
    k = designed.pick_dialect("45s punchy launch trailer for my game. Roll the dice.")
    assert k["name"] == "kinetic" and k["source"] == "prompt" and "punchy" in k["matched"] and not k["ambiguous"]
    e = designed.pick_dialect("A calm, airy promo for my notes app. It never forgets.")
    assert e["name"] == "ethereal" and e["source"] == "prompt" and {"calm", "airy"} <= set(e["matched"])
    assert designed.pick_dialect("Apple-style promo, minimal.")["name"] == "ethereal"
    assert designed.pick_dialect("Smash and clash energy: fast cuts, big type")["name"] == "kinetic"
    f = designed.pick_dialect("A calm promo.", flag="kinetic")
    assert f == dict(name="kinetic", source="flag", matched=[], ambiguous=False), "an explicit flag beats the words"
    assert designed.pick_dialect("Punchy promo.\ndialect: ethereal")["name"] == "ethereal"
    assert designed.pick_dialect("Punchy promo.", answers={"dialect": "ethereal"})["source"] == "answer"
    assert designed.pick_dialect("Punchy promo.\ndialect: kinetic", answers={"dialect": "ethereal"})["name"] == "ethereal", "an answer beats a label"
    try:
        designed.pick_dialect("x", flag="cinematic")
        raise AssertionError("an unknown dialect must be refused")
    except ValueError:
        pass


def test_words_pointing_both_ways_are_ambiguous_default_ethereal_and_cost_one_question():
    prompt = "A calm but punchy kinetic promo for my app. Go to bed, wake up to merged PRs."
    p = designed.pick_dialect(prompt)
    assert p["ambiguous"] and p["name"] == "ethereal" and p["source"] == "default"
    qs = cospec.open_questions(prompt, [])
    assert [q["key"] for q in qs][0] == "dialect" and len(qs) == 3
    assert [q["key"] for q in cospec.open_questions("A calm promo. Go to bed.", [])].count("dialect") == 0
    answered = cospec.open_questions(prompt, [], {"dialect": "kinetic"})
    assert "dialect" not in [q["key"] for q in answered]
    info, _ = e2e_plan(prompt)
    assert info["plan"]["designed"]["dialect"]["ambiguous"] and info["plan"]["cospec"]["open"][0]["key"] == "dialect"
    info, _ = e2e_plan(prompt, answers={"dialect": "kinetic"})
    assert info["plan"]["designed"]["dialect"]["name"] == "kinetic" and info["plan"]["designed"]["dialect"]["source"] == "answer"


def test_the_word_kinetic_names_the_dialect_not_the_anime_preset_when_stills_are_given():
    info, _ = e2e_plan("45s kinetic promo for my crew. Go to bed. Wake up to merged PRs.")
    assert info["plan"]["preset"] == "hero" and info["plan"]["designed"]["dialect"]["name"] == "kinetic"
    assert gapfill.pick_preset("a kinetic promo")[0] == "anime-opening", "without stills the old keyword still works"


def test_vertical_short_keeps_its_shell_and_is_not_switched_to_the_16x9_designed_plan():
    info, _ = e2e_plan("preset: vertical-short\n" + E2E_PROMPT)
    plan = info["plan"]
    assert plan["preset"] == "vertical-short" and plan["preset_version"] == 1 and "designed" not in plan
    forced, _ = e2e_plan("preset: vertical-short\n" + E2E_PROMPT, designed=True)
    assert forced["plan"]["preset"] == "vertical-short" and forced["plan"]["designed"]["dialect"]["name"] == "ethereal", "--designed still forces it"
    assert e2e_plan()[0]["plan"]["preset"] == "hero" and "designed" in e2e_plan()[0]["plan"]


# ---------------------------------------------------------------- ethereal defaults from a thin prompt
def test_ethereal_defaults_from_a_thin_prompt():
    info, d = e2e_plan(extra_stills=[])
    clip = os.path.join(d, "run.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=1", "-pix_fmt", "yuv420p", clip], check=True)
    info = gapfill.apply(os.path.join(d, "q"), E2E_PROMPT, name="crew", stills=[os.path.join(d, f"{n}.png") for n in E2E_STILLS] + [clip])
    des = info["plan"]["designed"]
    assert des["dialect"]["name"] == "ethereal" and des["dialect"]["source"] == "default"
    rows = des["shots"]
    assert not [r for r in rows if r["framing"] == "fullscreen"], "no fullscreen chrome, even with real footage on offer"
    assert abs(sum(r["seconds"] for r in rows) - 60) < 0.05
    secs = sorted(r["seconds"] for r in rows)
    assert secs[len(secs) // 2] >= 4.0 and len(rows) <= 14, "breathable holds, not rapid cuts"
    assert rows[-1]["beat"] == "ask" and rows[-1]["seconds"] >= 6.0, "a held end card"
    assert rows[0]["framing"] == "plate", "quiet open: a plate and the first words"
    pay = [r["seconds"] for r in rows if r["beat"] == "payoff"]
    assert pay == sorted(pay, reverse=True) and (len(pay) < 2 or pay[0] - pay[-1] <= 1.0), "the payoff holds; there is no accelerating burst"
    assert des["montage"]["enabled"] is False and des["montage"]["accelerates"] is False
    ts = des["type_style"]
    assert ts["uppercase"] is False and ts["outline"] is None and ts["shadow"] is False and ts["vo_reads_onscreen"] is False
    cards = [c for c in des["kinetic_cards"] if c["text"]]
    assert cards and all(c["anim"] in ("snap", "cascade") and c["vo"] is None and c["weight"] in ("Light", "Medium") for c in cards)
    assert all(len(c["text"].split()) <= ts["max_words_per_card"] for c in cards)
    assert des["audio"]["music_led"] is True and des["audio"]["vo"] is False and des["audio"]["quiet_until_cta"] is True
    assert {"mosaic-resolve", "cascade", "hard-cut"} == {t["kind"] for t in des["dialect"]["transitions"]}
    assert des["dialect"]["camera"]["forbidden"] == ["whip pan", "shake", "heavy motion blur"]
    assert des["dialect"]["ui"]["fullscreen"] is False
    for p in des["plates"]:
        assert p["ui"] is False and designed.PLATE_GUARD in p["prompt"] and "pastel" in p["prompt"].lower() and p["seconds"] == 6
        assert not any(ch.isdigit() for ch in p["prompt"])
    assert any(n["kind"] == "audio" for n in des["needs"]), "the licensed bed is listed as waiting, never invented"
    conflict = [c for c in des["conflicts"] if c["id"] == "abstracted-ui-vs-rule-1"]
    assert conflict and "pending" in conflict[0]["decision"] and "rule 1" in conflict[0]["ask"]


def test_kinetic_differs_where_the_dialects_differ():
    eth = e2e_plan()[0]["plan"]["designed"]
    kin = e2e_plan(dialect="kinetic")[0]["plan"]["designed"]
    assert kin["dialect"]["name"] == "kinetic" and kin["dialect"]["source"] == "flag"
    assert len(kin["shots"]) > 2 * len(eth["shots"]), "denser cuts"
    assert kin["montage"]["accelerates"] is True and kin["type_style"]["uppercase"] is True and kin["type_style"]["outline"]
    assert kin["audio"]["vo"] is True and not kin["conflicts"]
    cards = [c for c in kin["kinetic_cards"] if c["text"]]
    assert all(c["vo"] == c["text"] and c["anim"] in ("pop", "slide", "scale") for c in cards)
    assert kin["plates"][0]["seconds"] == 4 and "pastel" not in kin["plates"][0]["prompt"].lower()
    assert not any(n["kind"] == "audio" for n in kin["needs"])


# ---------------------------------------------------------------- the e2e recipe and the team-default CTA
def test_commission_ai_e2e_recipe_asks_three_questions_and_uses_the_team_cta():
    info, _ = e2e_plan(defaults=cospec.parse_defaults([f"cta={TEAM_CTA}"]))
    plan = info["plan"]
    des = plan["designed"]
    assert [q["key"] for q in plan["cospec"]["open"]] == ["cta", "promise", "audience"], "audience, one promise, end card GitHub vs landing"
    assert "GitHub" in plan["cospec"]["open"][0]["question"] and "landing page" in plan["cospec"]["open"][0]["question"]
    assert plan["cospec"]["max_questions"] == 3 and plan["cospec"]["defaults"] == {"cta": TEAM_CTA}
    cards = [(c["beat"], c["text"], c["source"]) for c in des["kinetic_cards"]]
    assert cards == [("hook", "Go to bed", "prompt"), ("payoff", "Wake up to merged PRs", "prompt"), ("ask", TEAM_CTA, "team-default")]
    text = " ".join(c[1] for c in cards)
    assert not any(ch.isdigit() for ch in text) and "badge" not in text.lower(), "no invented counts or badges"
    confirm = [n for n in des["needs"] if n["kind"] == "confirm"]
    assert len(confirm) == 1 and confirm[0]["text"] == TEAM_CTA
    assert des["dialect"]["name"] == "ethereal"
    assert [s["id"] for s in des["stills"]] == list(E2E_STILLS)
    assert designed.check_no_invention(des, plan["prompt"], {}, {"cta": TEAM_CTA}) == []
    assert any("not words the prompt" in b for b in designed.check_no_invention(des, plan["prompt"], {}, {})), \
        "the default is a source only because the person passed it"


def test_the_team_default_never_leaks_and_is_outranked_by_the_persons_own_cta():
    plain = e2e_plan()[0]["plan"]["designed"]
    assert [c["beat"] for c in plain["kinetic_cards"] if c["text"]] == ["hook", "payoff"] and plain["kinetic_cards"][-1]["status"] == "needs-copy"
    assert not any(TEAM_CTA.split(",")[0] in str(c.get("text")) for c in plain["kinetic_cards"]), "no default unless it was passed for this product"
    d = {"cta": TEAM_CTA}
    ans = e2e_plan(defaults=d, answers={"cta": "Star it on GitHub"})[0]["plan"]["designed"]
    assert [c["text"] for c in ans["kinetic_cards"] if c["beat"] == "ask"] == ["Star it on GitHub"] and not any(n["kind"] == "confirm" for n in ans["needs"])
    lab = e2e_plan(E2E_PROMPT + "\ncta: Meet the crew", defaults=d)[0]["plan"]["designed"]
    assert [c["text"] for c in lab["kinetic_cards"] if c["beat"] == "ask"] == ["Meet the crew"]
    info, dd = e2e_plan(defaults=d)
    again = gapfill.apply(os.path.join(dd, "p"), E2E_PROMPT, name="crew")
    assert again["plan"]["cospec"]["defaults"] == d, "stills, answers and defaults carry over a re-plan"
    for line in ("audience=devs", "cta=", "nonsense"):
        try:
            cospec.parse_defaults([line])
            raise AssertionError(line)
        except ValueError:
            pass


def test_cli_dialect_and_default_flags_end_to_end():
    d = tempfile.mkdtemp()
    paths = make_stills(d, tuple((n, (1600, 900)) for n in E2E_STILLS))
    dest = os.path.join(d, "crew")
    run = lambda *a: subprocess.run([sys.executable, "-m", "promo", *a], cwd=ROOT, capture_output=True, text=True)  # noqa: E731
    r = run("plan", "--dir", dest, "--prompt", E2E_PROMPT, "--stills", *paths, "--default", f"cta={TEAM_CTA}")
    assert r.returncode == 0, r.stderr
    assert "co-spec (3 of max 3" in r.stdout and "cta | promise | audience" in r.stdout
    plan = yaml.safe_load(open(os.path.join(dest, "promo.yaml")).read())["plan"]
    assert plan["designed"]["dialect"]["name"] == "ethereal"
    r = run("designed", "apply", "--dir", dest)
    assert r.returncode == 0, r.stderr
    spec = load_spec(os.path.join(dest, "promo.yaml"), plugins=False)
    gates = {g: s for g, s, _m in designed.gates(spec)}
    assert gates["designed-grounded"] == "PASS" and "FAIL" not in gates.values(), gates
    assert "ethereal: breathable holds" in open(os.path.join(dest, "promo.yaml")).read()
    r = run("plan", "--dir", dest, "--prompt", E2E_PROMPT, "--dialect", "kinetic")
    assert r.returncode == 0, r.stderr
    assert yaml.safe_load(open(os.path.join(dest, "promo.yaml")).read())["plan"]["designed"]["dialect"]["name"] == "kinetic"
    r = run("designed", "apply", "--dir", dest)
    assert r.returncode == 0 and "ethereal: breathable holds" not in open(os.path.join(dest, "promo.yaml")).read()
    bad = run("plan", "--dir", dest, "--prompt", E2E_PROMPT, "--default", "audience=devs")
    assert bad.returncode != 0 and "unknown default" in bad.stderr


# ---------------------------------------------------------------- compile + gates
def _applied(**kw):
    info, d = e2e_plan(defaults={"cta": TEAM_CTA}, **kw)
    designed.apply_shots(info["path"])
    return info, load_spec(info["path"], plugins=False)


def test_ethereal_shots_compile_slow_eased_pastel_with_resolves_and_no_fullscreen():
    info, spec = _applied()
    des = info["plan"]["designed"]
    shots = designed.compile_shots(des, sfx={"tick", "whoosh"})
    assert {s["type"] for s in shots} == {"cinema"}
    for s in shots:
        for k in ("shake", "whip", "blur", "flash", "speed_lines"):
            assert k not in s
        if "cam" in s:
            assert all(len(k) == 5 and k[4] == "smooth" for k in s["cam"][1:]), "slow eased moves only (a settle, a held push), never a constant-rate drift"
        if s["look"].get("backdrop") != "none" or "plate_fill" in s["look"]:
            assert s["look"]["grade"]["saturation"] < 0.9 and s["look"]["vignette"] is False, "soft pastel grade"
        for it in s.get("kinetic_copy", []):
            assert it["uppercase"] is False and it["outline"] is False and it["shadow"] is False and it["anim"] in ("snap", "cascade")
    firsts = {}
    for r, s in zip(des["shots"], shots):
        firsts.setdefault(r["beat"], s)
    assert all(s.get("resolve", {}).get("kind") == "mosaic" for s in firsts.values()), "mosaic resolve on the first shot of each beat"
    assert sum(1 for s in shots if "resolve" in s) == len(firsts) == 5, "and nowhere else"
    ask = shots[-1]["kinetic_copy"][0]
    assert ask["thumb"] == "shot-01-v1-poster" and ask["brackets"] is True and ask["text"] == TEAM_CTA, "inline thumb of a real still"
    assert any(e["sfx"] == "tick" for s in shots for e in s.get("sfx", [])) and any(e["sfx"] == "whoosh" for s in shots for e in s.get("sfx", []))
    quiet = designed.compile_shots(des, sfx=())
    assert not any("sfx" in s for s in quiet), "sfx only when the project's library has them"
    assert all(abs(s["cam"][-1][3] - s["cam"][0][3]) <= designed.ETHEREAL_MAX_DRIFT["zoom_per_s"] * 0.8 * (r["seconds"]) + 1e-6
               for r, s in zip(des["shots"], shots) if "cam" in s), "a floaty dolly under the zoom cap"
    assert not designed.check_no_invention(des, des and info["plan"]["prompt"], {}, {"cta": TEAM_CTA})
    assert {g: s for g, s, _ in designed.gates(spec)} == dict.fromkeys(
        ["designed-grounded", "designed-kinetic", "designed-clear", "designed-framing", "designed-camera", "designed-pace"], "PASS")


def test_ethereal_gates_fail_whips_blur_fullscreen_and_fast_drift_and_warn_on_rapid_cuts():
    info, spec = _applied()
    base = {g: (s, m) for g, s, m in designed.gates(spec)}
    assert base["designed-camera"][0] == "PASS"

    def gates_of(mutate):
        raw = yaml.safe_load(open(info["path"]).read())
        mutate(raw["shots"])
        path = os.path.join(os.path.dirname(info["path"]), "mut.yaml")
        yaml.safe_dump(raw, open(path, "w"), sort_keys=False)
        return {g: (s, m) for g, s, m in designed.gates(load_spec(path, plugins=False))}

    g = gates_of(lambda shots: shots[1].update(shake=True))
    assert g["designed-camera"][0] == "FAIL" and "shake" in g["designed-camera"][1]
    g = gates_of(lambda shots: shots[1].update(blur=4))
    assert g["designed-camera"][0] == "FAIL" and "blur" in g["designed-camera"][1]
    g = gates_of(lambda shots: shots[1].update(cam=[[0, 0.3, 0.5, 1.0], ["end", 0.7, 0.5, 0.6]]))
    assert g["designed-camera"][0] == "FAIL" and "pan/s" in g["designed-camera"][1]
    g = gates_of(lambda shots: shots[1].update(look={"backdrop": "none"}, source=shots[1]["source"]))
    assert g["designed-framing"][0] == "FAIL" and "never goes fullscreen" in g["designed-framing"][1]
    kin = e2e_plan(dialect="kinetic")[0]
    designed.apply_shots(kin["path"])
    kg = {g_: (s, m) for g_, s, m in designed.gates(load_spec(kin["path"], plugins=False))}
    assert kg["designed-camera"][0] == "PASS" and kg["designed-pace"][0] == "PASS"


def test_a_kinetic_cut_scores_as_rapid_under_the_ethereal_pace_gate():
    info, _ = e2e_plan(dialect="kinetic")
    des = copy.deepcopy(info["plan"]["designed"])
    des["dialect"] = dict(des["dialect"], name="ethereal")
    des["type_style"] = designed.TYPE_STYLE_ETHEREAL
    path = info["path"]
    designed.apply_shots(path)
    raw = yaml.safe_load(open(path).read())
    raw["plan"]["designed"] = des
    mut = os.path.join(os.path.dirname(path), "pace.yaml")
    yaml.safe_dump(raw, open(mut, "w"), sort_keys=False)
    g = {g_: (s, m) for g_, s, m in designed.gates(load_spec(mut, plugins=False))}
    assert g["designed-pace"][0] == "WARN" and "cuts/s" in g["designed-pace"][1]


# ---------------------------------------------------------------- the renderer's ethereal moves
PASTEL = dict(top=[236, 238, 246], bottom=[246, 238, 232])
INK = [34, 38, 56]


def _comp(items, spec=None, **look):
    spec = spec or _spec()
    cfg = dict(ui=False, look=dict(backdrop="none", plate_fill=PASTEL, grade=False, bloom=False, vignette=False, grain=False, **look), kinetic_copy=items)
    return CN.Composer(_Ctx(K=1, fps=12, font_path=R.DEFAULT_FONT, spec=spec, seg_dir="."), _shot(cfg), spec)


def _frame(comp, t, i=0):
    return np.asarray(comp.compose(None, None, t, i), np.int32)


def _ink(a):
    return int(((a.sum(axis=2) < 3 * 130)).sum())


def _item(**kw):
    return dict(text="Wake up to merged PRs", at=0.5, dur=1.2, size_pct=7, uppercase=False, outline=False, shadow=False, color=INK, weight="Light", **kw)


def test_snap_is_one_frame_on_and_one_frame_off_with_no_in_between():
    comp = _comp([_item(anim="snap")])
    empty, on, still_on, off = (_frame(comp, t, i) for i, t in enumerate((0.45, 0.5, 1.2, 1.75)))
    assert _ink(empty) == 0 and _ink(off) == 0, "nothing before, nothing after"
    assert _ink(on) > 200 and np.array_equal(on, still_on), "full size, full opacity from the first frame to the last: no fade, no scale"
    assert _ink(_frame(comp, 0.499)) == 0 and _ink(_frame(comp, 0.501)) == _ink(on)


def test_ethereal_type_has_no_outline_or_shadow_and_ink_colour():
    clean = _frame(_comp([_item(anim="snap")]), 1.0)
    ys, xs = np.where(clean.sum(axis=2) < 3 * 130)
    assert ys.size and clean[ys, xs].mean(axis=0).max() < 120, "ink-coloured strokes"
    heavy = _comp([dict(_item(anim="snap"), outline=True, shadow=True)])
    assert _ink(_frame(heavy, 1.0)) > _ink(clean), "the outline and shadow flags add dark pixels; clean type does not"


def test_cascade_snaps_words_on_one_by_one():
    item = _item(anim="cascade")
    assert [CN.cascade_words(item, t) for t in (0.49, 0.5, 0.5 + 0.18, 0.5 + 0.36, 3.0)] == [0, 1, 2, 3, 5]
    comp = _comp([item])
    counts = [_ink(_frame(comp, t)) for t in (0.5, 0.5 + 0.18, 0.5 + 0.54, 0.5 + 0.9)]
    assert counts == sorted(counts) and counts[0] < counts[-1] and len(set(counts)) >= 3, counts


def test_brackets_anchors_and_an_inline_thumb_are_typography_as_ui():
    plain = _ink(_frame(_comp([_item(anim="snap")]), 1.0))
    brackets = _frame(_comp([_item(anim="snap", brackets=True)]), 1.0)
    anchors = _frame(_comp([_item(anim="snap", anchors=True)]), 1.0)
    assert _ink(brackets) > plain and _ink(anchors) > plain
    with tempfile.TemporaryDirectory() as d:
        th = os.path.join(d, "thumb.png")
        Image.new("RGB", (160, 90), (200, 20, 20)).save(th)
        spec = _spec(clip=th)
        thumb = _frame(_comp([_item(anim="snap", thumb="clip-id")], spec=spec), 1.0)
        red = lambda a: int(((a[..., 0] > 150) & (a[..., 1] < 80)).sum())  # noqa: E731
        assert red(thumb) > 100 and red(_frame(_comp([_item(anim="snap")], spec=spec), 1.0)) == 0, "the still's own pixels, scaled, inline"
    assert CN.kinetic_font(_spec(), 40, fallback=R.DEFAULT_FONT, weight="Light") is not None


def test_mosaic_resolve_steps_from_coarse_blocks_to_sharp_and_never_touches_the_panel_pixels():
    cfg = CN.mosaic_cfg(dict(resolve=dict(kind="mosaic", dur=0.9, steps=6, from_blocks=8)))
    assert (cfg["dur"], cfg["steps"], cfg["from_blocks"]) == (0.9, 6, 8) and cfg["to_blocks"] == 96 and CN.mosaic_cfg(dict()) is None
    assert [CN.mosaic_stage(cfg, t) for t in (0.0, 0.16, 0.5, 0.89, 0.9, 2.0)] == [0, 1, 3, 5, None, None]
    rng = np.random.default_rng(3)
    im = Image.fromarray(rng.integers(0, 255, (180, 320, 3), dtype=np.uint8))
    coarse, fine, sharp = CN.mosaic(im, cfg, 0.0), CN.mosaic(im, cfg, 0.7), CN.mosaic(im, cfg, 1.0)
    uniq = lambda x: len({tuple(p) for p in np.asarray(x).reshape(-1, 3)})  # noqa: E731
    assert uniq(coarse) <= 8 * 5 and uniq(coarse) < uniq(fine) < uniq(sharp) and sharp is im
    # a panel shot: the UI pixels in the panel box are the same at every stage of the resolve
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ui.png")
        Image.fromarray(rng.integers(0, 255, (270, 480, 3), dtype=np.uint8)).save(p)
        spec = _spec(clip=p)
        shot = dict(source="x", look=dict(panel=dict(w=0.5, cy=0.45)), resolve=dict(kind="mosaic", dur=0.9, steps=6, from_blocks=8))
        comp = CN.Composer(_Ctx(K=1, fps=12, font_path=R.DEFAULT_FONT, spec=spec, seg_dir="."), _shot(shot), spec)
        a, b = _frame(comp, 0.0), _frame(comp, 1.5)
        box = CN.panel_box_of(spec, _shot(shot), (854, 480))
        x0, y0, x1, y1 = (int(v) for v in box)
        inner = (slice(y0 + 12, y1 - 12), slice(x0 + 12, x1 - 12))
        assert np.array_equal(a[inner], b[inner]) or np.abs(a[inner] - b[inner]).mean() < 6, "the UI pixels are not pixelated by the resolve"


if __name__ == "__main__":
    fails = 0
    for k, v in list(globals().items()):
        if k.startswith("test_") and callable(v):
            try:
                v()
                print("ok  ", k)
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                print("FAIL", k)
                fails += 1
    raise SystemExit(1 if fails else 0)
