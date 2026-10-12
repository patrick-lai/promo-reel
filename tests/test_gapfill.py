"""Thin-prompt gap fill, preset @2 pacing, and the preview / --final review gate.

Plain asserts: `python tests/test_gapfill.py` or pytest. No local example project required.
"""
import copy
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import gapfill, pacing, reviewgate, shotqa, style_check, styles  # noqa: E402
from promo.generic_check import long_hold_offenders, rules_for  # noqa: E402
from promo.spec import load_spec  # noqa: E402
from promo.styles import StyleError  # noqa: E402

COLUMNS = ["beat", "on_screen", "notice", "caption", "seconds", "app_state"]
BEATS = ("hook", "problem", "demo", "payoff", "ask")


def _plan_body(path):
    text = open(path).read()
    return text.split("# promo:plan BEGIN", 1)[1].split("# promo:plan END", 1)[0]


def _sign(path, value="Ada"):
    text = open(path).read()
    text = re.sub(r"(?m)^signed-off:.*$", f"signed-off: {value}", text)
    open(path, "w").write(text)


class _Shot:
    def __init__(self, sid, t0, t1, cfg=None):
        self.id = sid
        self.t0 = float(t0)
        self.t1 = float(t1)
        self.dur = self.t1 - self.t0
        self.cfg = cfg or {}
        self.b0 = self.t0
        self.b1 = self.t1


class _Spec:
    def __init__(self, shots, style=None, raw=None, grid=None):
        self.shots = shots
        self.style = style or {}
        self.raw = raw or {}
        self.grid = grid
        self.qa = {}


def test_thin_prompt_fills_the_project_file():
    with tempfile.TemporaryDirectory() as d:
        info = gapfill.apply(d, "make a promo", name="demo")
        plan = info["plan"]
        text = open(info["path"]).read()
        assert len(plan["idea"].split()) <= 10
        assert "merged" not in plan["idea"].lower()
        assert "http" not in _plan_body(info["path"]).lower()
        assert "go to bed" not in _plan_body(info["path"]).lower()
        assert plan["preset"] == "hero" and plan["preset_version"] == 2
        assert re.search(r"(?m)^\s*version:\s*2\s*$", text)
        assert plan["prompt"] == "make a promo"
        for key in ("hook", "problem", "demo", "payoff", "cta"):
            assert str(plan["beats"][key]).strip()
        assert plan["length"]["master_s"] == 60
        assert plan["length"]["feed_s"] == 20 and plan["length"]["feature_s"] == 30
        assert plan["length"]["cuts"][0]["beats"] == ["hook", "demo", "payoff", "ask"]
        assert plan["length"]["cuts"][1]["beats"] == ["hook", "problem", "demo", "payoff", "ask"]
        assert plan["filled"] == ["idea", "preset", "beats", "length", "shot_list", "capture", "hook"]
        rows = plan["shot_list"]
        assert rows and all(list(r) == COLUMNS for r in rows)
        counts = {b: 0 for b in BEATS}
        for r in rows:
            counts[r["beat"]] += 1
            assert len(r["caption"]) <= 35
        assert all(counts[b] >= 1 for b in BEATS)
        cap = plan["capture"]
        assert cap["dpr"] == 2 and cap["capture_resolution"] == "3840x2160" and cap["never_paint_ui"] is True
        assert not re.search(r"(?m)^\s*paint_out\s*:", text)
        assert plan["hook"]["promise_by_s"] == 0.5 and plan["hook"]["logo_after_s"] == 8
        rnd = open(os.path.join(d, "reviews", "round-1.md")).read()
        for role in ("Marketing", "Zen", "Director"):
            assert f"## {role}" in rnd and "signed-off:" in rnd
        spec = load_spec(info["path"])
        assert spec.style["preset"] == "hero" and spec.style["version"] == 2
        # a second plan does not duplicate the block or retarget a written preset
        again = gapfill.apply(d, "make a promo", name="demo")
        assert open(again["path"]).read().count("# promo:plan BEGIN") == 1
        assert again["plan"]["preset"] == "hero"


def test_prompt_keywords_pick_the_preset():
    with tempfile.TemporaryDirectory() as d:
        anime = os.path.join(d, "anime")
        gapfill.apply(anime, "anime opening of the board", name="anime")
        text = open(os.path.join(anime, "promo.yaml")).read()
        assert re.search(r"(?m)^\s*preset:\s*anime-opening\b", text)
        assert yaml.safe_load(text)["plan"]["preset"] == "anime-opening"
        live = os.path.join(d, "live")
        gapfill.apply(live, "talk show about the desk", name="live")
        raw = yaml.safe_load(open(os.path.join(live, "promo.yaml")).read())
        assert raw["plan"]["preset"] == "livestream" and raw["style"]["preset"] == "livestream"


def test_labelled_empty_beat_stays_empty():
    with tempfile.TemporaryDirectory() as d:
        info = gapfill.apply(d, "make a promo\nproblem:\n", name="demo")
        assert info["plan"]["beats"]["problem"] == ""
        spec = load_spec(info["path"])
        try:
            reviewgate.check_build(spec, final=True)
            raise AssertionError("empty beats should refuse --final")
        except reviewgate.ReviewError as e:
            assert "empty beats" in str(e) and "problem" in str(e)


def test_cap_rows_keeps_every_beat():
    base = [{"beat": b, "i": 0} for b in pacing.SHOT_BEATS]
    assert len(pacing.cap_rows(base, 3)) == 5
    extras = base + [{"beat": "demo", "i": 1}, {"beat": "demo", "i": 2}, {"beat": "hook", "i": 1}, {"beat": "hook", "i": 2}]
    capped = pacing.cap_rows(extras, 8)
    assert len(capped) <= 8
    assert {r["beat"] for r in capped} >= set(pacing.SHOT_BEATS)


def test_v1_presets_stay_locked_and_v2_carries_targets():
    assert styles.PRESETS["hero"]["pacing"]["snap"] == "beat"
    assert "strict_beat" not in styles.PRESETS["hero"]["pacing"]
    before = copy.deepcopy(styles.PRESETS["hero"])
    v1 = styles.resolve({"style": {"preset": "hero"}})
    assert v1["version"] == 1 and v1["pacing"]["snap"] == "beat" and "strict_beat" not in v1["pacing"]
    v2 = styles.resolve({"style": {"preset": "hero@2"}})
    assert v2["version"] == 2 and v2["pacing"]["snap"] == "phrase" and v2["pacing"]["strict_beat"] is False
    assert v2["pacing"]["cut_rate"]["overall"] == [0.35, 0.45]
    assert "cut-rate" in v2["checks"] and "caption-hold" in v2["checks"]
    assert styles.PRESETS["hero"] == before
    anime = styles.resolve({"style": {"preset": "anime-opening", "version": 2}})
    assert anime["pacing"]["snap"] == "bar" and anime["pacing"].get("strict_beat") is not False
    assert anime["pacing"]["cut_rate"]["early"] == 0.3 and anime["pacing"]["cut_rate"]["peak"] == 1.0
    assert anime["pacing"]["median_shot_s"] == [1.2, 1.5]
    assert anime["pacing"]["loudness_lufs"] == -14.0 and anime["pacing"]["planned_hold"]["min_s"] == 7
    live = styles.resolve({"style": {"preset": "livestream@2"}})
    assert live["pacing"]["layout_every_s"] == [5.0, 7.0]
    assert live["pacing"]["speaker_turn_max_s"] == 12.0 and live["pacing"]["wpm"] == [165, 180]
    assert live["pacing"]["strict_beat"] is False
    for raw in ({"style": {"preset": "hero@3"}}, {"style": {"preset": "cinematic-story", "version": 2}}):
        try:
            styles.resolve(raw)
            raise AssertionError(raw)
        except StyleError:
            pass
    assert rules_for(_Spec([], style={"preset": "hero"}))["long_hold"]["max_s"] == 3.5


def test_cut_rate_and_phrase_sync_gates():
    shots = [_Shot(f"{i:02d}", i, i + 1) for i in range(10)]
    st = styles.resolve({"style": {"preset": "hero", "version": 2}})
    _g, status, msg = pacing.cut_rate_gate(_Spec(shots), st)
    assert status == "WARN" and "overall" in msg
    few = pacing.cut_rate_gate(_Spec(shots[:3]), st)
    assert few[1] == "PASS" and "too few" in few[2]

    class Grid:
        B = 0.5

        def phrase_starts(self):
            return [0.0, 4.0]

    missed = [_Shot(f"{i:02d}", t, t + 0.4) for i, t in enumerate((1.0, 2.0, 3.0, 3.5))]
    g = pacing.phrase_sync_gate(_Spec(missed, grid=Grid()), st)
    assert g[1] == "WARN" and "phrase" in g[2]
    assert pacing.phrase_sync_gate(_Spec(missed), st)[1] == "PASS"


def test_planned_hold_is_one_exemption():
    held = _Shot("01", 0, 8, {"hold": "planned"})
    other = _Shot("02", 8, 12, {})
    spec = _Spec([held, other])
    assert pacing.exempt_hold_ids(spec) == {"01"}
    two = _Spec([held, _Shot("02", 8, 16, {"hold": "planned"})])
    assert pacing.exempt_hold_ids(two) == set()
    gate = pacing.planned_hold_gate(two, {"pacing": {}})
    assert gate[1] == "FAIL"
    outside = _Spec([_Shot("01", 0, 4, {"hold": "planned"})])
    assert pacing.exempt_hold_ids(outside) == set()
    long_, exempt = long_hold_offenders({"01": (8.0, 0.0), "02": (4.0, 1.0)}, spec, 3.5)
    assert exempt == {"01"} and all(sid != "01" for sid, _d, _t in long_)


def test_hero_v2_scaffold_gates_do_not_raise():
    with tempfile.TemporaryDirectory() as d:
        info = gapfill.apply(d, "make a promo", name="demo")
        gates = {g: (st, msg) for g, st, msg in style_check.run(load_spec(info["path"]))}
        assert gates["cut-rate"][0] == "PASS" and "too few" in gates["cut-rate"][1]
        assert gates["phrase-sync"][0] == "PASS"
        assert gates["hero-open"][0] == "WARN" and "end card" in gates["hero-open"][1]


def test_review_gate_ignores_a_spec_without_a_plan():
    from types import SimpleNamespace
    spec = SimpleNamespace(scale=1)
    assert reviewgate.review_on(spec) is False
    assert reviewgate.check_build(spec, final=False, scale=1) is None


def test_review_gate_signoff_scale_and_three_rounds():
    with tempfile.TemporaryDirectory() as d:
        info = gapfill.apply(d, "make a promo", name="demo")
        spec = load_spec(info["path"])
        try:
            reviewgate.check_build(spec, final=True, scale=1)
            raise AssertionError("unsigned final")
        except reviewgate.ReviewError as e:
            assert "signed off" in str(e)
        try:
            reviewgate.check_build(spec, final=False, scale=1)
            raise AssertionError("above 540p")
        except reviewgate.ReviewError as e:
            assert "540p" in str(e)
        assert reviewgate.check_build(spec, final=False, scale=0.5) is None
        _sign(os.path.join(d, "reviews", "round-1.md"))
        assert reviewgate.check_build(spec, final=True, scale=1) is None
        open(os.path.join(d, "reviews", "round-4.md"), "w").write(reviewgate.feedback_template(4))
        try:
            reviewgate.check_build(spec, final=True, scale=1)
            raise AssertionError("fourth round")
        except reviewgate.ReviewError as e:
            assert "Patrick" in str(e)


def test_shot_qa_and_footage_add():
    gray = np.full((1080, 1920), 40.0, np.float32)
    rows = {r["gate"]: r for r in shotqa.assess(gray, captions=["Tasks"], badges=["Tasks"],
                                                 named=[dict(name="Tasks", px=12, inside=True)])}
    assert rows["empty-frame"]["status"] == "FAIL"
    assert rows["caption-badge"]["status"] == "WARN"
    assert rows["named"]["status"] == "FAIL"
    ok = {r["gate"]: r for r in shotqa.assess(gray, named=[dict(name="Tasks", px=22, inside=True)])}
    assert ok["named"]["status"] == "PASS"

    from PIL import Image

    from promo import footage as FT

    with tempfile.TemporaryDirectory() as d:
        info = gapfill.apply(d, "make a promo", name="demo")
        spec = load_spec(info["path"], plugins=False)
        spec.raw["footage"] = os.path.join(d, "footage", "manifest.yaml")
        spec._footage = None
        png = os.path.join(d, "dark.png")
        Image.new("RGB", (64, 36), (9, 9, 9)).save(png)
        entry = FT.add(spec, png, "dark", shots=["01"], commit="a" * 40, capture="clean", dpr=2, demo=True)
        qa = {r["gate"]: r for r in entry["shot_qa"]}
        assert qa["empty-frame"]["status"] == "FAIL"


def test_cli_plan_preview_and_final():
    env = dict(os.environ)
    with tempfile.TemporaryDirectory() as d:
        dest = os.path.join(d, "demo")
        plan = subprocess.run([sys.executable, "-m", "promo", "plan", "demo", "--dir", dest, "--prompt", "make a promo"],
                              cwd=ROOT, capture_output=True, text=True, env=env)
        assert plan.returncode == 0, plan.stderr
        assert os.path.isfile(os.path.join(dest, "promo.yaml"))
        preview = subprocess.run([sys.executable, "-m", "promo", "preview", "--scale", "1", "-p", os.path.join(dest, "promo.yaml")],
                                 cwd=ROOT, capture_output=True, text=True, env=env)
        assert preview.returncode != 0 and "540p" in (preview.stderr + preview.stdout)
        final = subprocess.run([sys.executable, "-m", "promo", "-p", os.path.join(dest, "promo.yaml"), "build", "--final"],
                               cwd=ROOT, capture_output=True, text=True, env=env)
        assert final.returncode != 0 and "signed off" in (final.stderr + final.stdout)


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
                print("FAIL", k)
                traceback.print_exc()
    raise SystemExit(1 if fails else 0)
