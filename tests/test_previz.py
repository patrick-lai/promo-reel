"""Previz (wireframe directing): scene compile from a thin designed plan, sync keeps overrides, stage order, gates, PIL strip, cinema mapping.

No browser: the strip uses the PIL engine (the Chrome test is skipped when no Chrome is installed).
"""
import copy
import json
import os
import sys
import tempfile
from types import SimpleNamespace as NS

import pytest
import yaml
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import check as CK  # noqa: E402
from promo import cli, designed, gapfill  # noqa: E402
from promo import flow as F  # noqa: E402
from promo import previz as PZ  # noqa: E402
from promo.spec import load_spec  # noqa: E402

PROMPT = "60s promo for my AI coding crew app. Go to bed, wake up to merged PRs."


def make_project(dialect=None, prompt=PROMPT):
    d = tempfile.mkdtemp()
    paths = []
    for name, size in (("board", (960, 540)), ("review", (960, 540)), ("phone", (300, 650))):
        p = os.path.join(d, f"{name}.png")
        Image.new("RGB", size, (30, 34, 48)).save(p)
        paths.append(p)
    kw = dict(dialect=dialect) if dialect else {}
    info = gapfill.apply(os.path.join(d, "p"), prompt, name="t", stills=paths, **kw)
    return os.path.dirname(info["path"]), info["path"]


def target(pd):
    return PZ.targets(pd)[0]


def read(path):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------- scene compile
def test_scene_compiles_from_a_thin_designed_plan():
    pd, path = make_project()
    t = target(pd)
    assert t.kind == "designed" and t.dir == os.path.join(pd, "previz")
    b = PZ.build(t)
    sc = read(t.scene_path)
    assert sc["schema"] == PZ.SCHEMA and os.path.isfile(b["viewer"])
    plan = yaml.safe_load(open(path))["plan"]["designed"]
    assert len(sc["shots"]) == len(plan["shots"])
    assert abs(sum(s["dur"] for s in sc["shots"]) - 60) < 0.1
    kinds = {p["kind"] for s in sc["shots"] for p in s.get("panels") or []}
    assert kinds <= set(PZ.PANEL_KINDS) and kinds
    for s in sc["shots"]:
        assert s["camera"]["keys"], s["id"]
        for pl in s.get("plates") or []:
            assert pl["ui"] is False
    errors, _ = PZ.problems(sc)
    assert errors == []


def test_ethereal_is_perspective_and_kinetic_is_orthographic():
    pe, _ = make_project("ethereal")
    pk, _ = make_project("kinetic")
    PZ.build(target(pe))
    PZ.build(target(pk))
    se, sk = read(target(pe).scene_path), read(target(pk).scene_path)
    assert {s["camera"].get("projection", se.get("projection")) for s in se["shots"]} & {"persp"}
    assert {s["camera"].get("projection", sk.get("projection")) for s in sk["shots"]} == {"ortho"}


def test_scene_hash_ignores_notes_and_follows_edits():
    pd, _ = make_project()
    t = target(pd)
    PZ.build(t)
    sc = read(t.scene_path)
    h = PZ.scene_hash(sc)
    sc2 = copy.deepcopy(sc)
    sc2["shots"][0]["notes"] = "something else"
    assert PZ.scene_hash(sc2) == h
    sc3 = copy.deepcopy(sc)
    sc3.setdefault("overrides", {}).setdefault("shots", {})[sc["shots"][0]["id"]] = {"dur": sc["shots"][0]["dur"] + 1}
    assert PZ.scene_hash(sc3) != h


def test_a_storyboard_compiles_to_a_scene(tmp_path):
    pd = str(tmp_path / "proj")
    os.makedirs(os.path.join(pd, "flow", "boards", "A"))
    still = os.path.join(pd, "flow", "boards", "A", "a.png")
    Image.new("RGB", (960, 540), (20, 20, 20)).save(still)
    board = dict(title="A", logline="x", scenes=[dict(id="s1", t=[0, 4], source="real", caption="Go to bed", camera="slow push in", action="open",
                                                      start=dict(image="a.png"))])
    with open(os.path.join(pd, "flow", "boards", "A", "board.json"), "w") as f:
        json.dump(board, f)
    with open(os.path.join(pd, "flow", "flow.json"), "w") as f:
        json.dump(dict(stage="storyboard", picks=["A"]), f)
    open(os.path.join(pd, "promo.yaml"), "w").write("output: {name: x, duration: 4, resolution: 1080, fps: 12}\n")
    ts = PZ.targets(pd)
    assert [x.kind for x in ts] == ["storyboard"] and ts[0].dir == os.path.join(pd, "previz", "A")
    PZ.build(ts[0])
    sc = read(ts[0].scene_path)
    assert sc["shots"] and PZ.camera_mode(sc["shots"][0]["camera"]["keys"]) in PZ.CAMERA_MODES


# ---------------------------------------------------------------- sync keeps the agent's edits
def test_sync_preserves_overrides_and_reports_orphans():
    pd, path = make_project()
    t = target(pd)
    PZ.build(t)
    sc = read(t.scene_path)
    first = sc["shots"][0]["id"]
    sc.setdefault("overrides", {}).setdefault("shots", {})[first] = {"camera": {"keys": PZ.camera_preset("push", sc["shots"][0]["dur"], 0.1, 0.5, 0.5, 0.8)}}
    sc["overrides"]["shots"]["99"] = {"dur": 2.0}
    open(t.scene_path, "w").write(json.dumps(sc))
    res = PZ.sync(t)
    assert res["orphans"] == ["99"]
    again = read(t.scene_path)
    assert again["overrides"] == sc["overrides"]
    eff = PZ.effective(again)
    assert PZ.camera_mode(next(s for s in eff["shots"] if s["id"] == first)["camera"]["keys"]) == "push"
    assert res["created"] is False and res["diff"]["added"] == [] and res["diff"]["removed"] == []


def test_cli_nudges_write_overrides_and_a_nudge_changes_the_hash():
    pd, _ = make_project()
    t = target(pd)
    PZ.build(t)
    h0 = PZ.scene_hash(read(t.scene_path))
    first = read(t.scene_path)["shots"][0]["id"]
    assert PZ.main(["cam", first, "push", "--amount", "0.2"], project=pd) == 0
    sc = read(t.scene_path)
    assert sc["overrides"]["shots"][first]["camera"]["keys"] and PZ.scene_hash(sc) != h0
    assert PZ.main(["reset"], project=pd) == 0
    assert PZ.scene_hash(read(t.scene_path)) == h0


# ---------------------------------------------------------------- strip and gates
def test_strip_pil_writes_a_png_and_records_the_scene_hash():
    pd, _ = make_project()
    t = target(pd)
    meta = PZ.strip(t, engine="pil")
    im = Image.open(t.strip_png)
    assert im.size[0] > 300 and meta["engine"] == "pil" and meta["tiles"] >= 3
    assert read(t.strip_json)["scene_hash"] == PZ.scene_hash(read(t.scene_path))
    assert PZ.target_status(t)["strip"] == "ok"
    one = PZ.strip(t, shot=read(t.scene_path)["shots"][0]["id"], engine="pil")
    assert one["partial"] and os.path.basename(one["png"]).startswith("strip-shot-")
    assert PZ.target_status(t)["strip"] == "ok", "a cheap one-shot look never replaces the gate strip"


def test_editing_the_scene_makes_the_strip_stale():
    pd, _ = make_project()
    t = target(pd)
    PZ.strip(t, engine="pil")
    first = read(t.scene_path)["shots"][0]["id"]
    PZ.main(["dur", first, "9"], project=pd)
    st = PZ.status(pd)
    assert not st["ok"] and "older scene" in st["problems"][0]
    PZ.strip(t, engine="pil")
    assert PZ.status(pd)["ok"]


def test_the_build_refuses_a_designed_plan_without_a_strip_but_not_the_quick_look():
    pd, path = make_project()
    designed.apply_shots(path)
    spec = load_spec(path, plugins=False)
    with pytest.raises(PZ.PrevizError) as e:
        PZ.check_build(spec)
    assert "previz first" in str(e.value)
    assert PZ.check_build(spec, look_only=True) is None
    PZ.strip(target(pd), engine="pil")
    assert PZ.check_build(spec) is None


def test_previz_ready_gate_warns_on_a_thin_preview_and_fails_above_it():
    pd, path = make_project()
    designed.apply_shots(path)
    spec = load_spec(path, plugins=False)
    spec.scale = 0.5
    (name, status, msg), = PZ.gates(spec)
    assert name == "previz-ready" and status == "WARN" and "540p" in msg
    spec.scale = 1.0
    assert PZ.gates(spec)[0][1] == "FAIL"
    spec.scale = 0.5
    PZ.strip(target(pd), engine="pil")
    assert PZ.gates(spec)[0][1] == "PASS"


def test_previz_ready_gate_fails_in_a_flow_at_keyframes():
    pd, path = make_project()
    designed.apply_shots(path)
    os.makedirs(os.path.join(pd, "flow"), exist_ok=True)
    json.dump(dict(stage="keyframes", picks=[]), open(os.path.join(pd, "flow", "flow.json"), "w"))
    spec = load_spec(path, plugins=False)
    spec.scale = 0.5
    assert PZ.gates(spec)[0][1] == "FAIL"


def test_skip_is_a_recorded_reason_not_a_silent_pass():
    pd, path = make_project()
    designed.apply_shots(path)
    t = open(path).read() + '\nprevis: {skip: "the person gave exact boxes"}\n'.replace("previs", "previz")
    open(path, "w").write(t)
    spec = load_spec(path, plugins=False)
    assert PZ.skipped(spec) == "the person gave exact boxes"
    assert PZ.check_build(spec) is None
    assert PZ.gates(spec)[0][:2] == ("previz-ready", "WARN")


def test_plain_hand_written_specs_are_untouched():
    spec = NS(root=tempfile.mkdtemp(), raw={"output": {}}, scale=1.0)
    assert PZ.needed(spec) is False and PZ.gates(spec) == [] and PZ.check_build(spec) is None


def test_check_module_runs_the_previz_gate():
    src = open(os.path.join(ROOT, "promo", "check.py")).read()
    assert "PZ.gates(spec)" in src and CK


# ---------------------------------------------------------------- flow stage
def test_previz_sits_between_storyboard_and_assets():
    i = F.STAGES.index
    assert i("storyboard") + 1 == i("previz") and i("previz") + 1 == i("assets") < i("keyframes")
    assert F.LABEL["previz"] == "Previz / wireframe"


# ---------------------------------------------------------------- previz -> cinema
def test_apply_carries_directed_camera_into_the_cinema_shots():
    pd, path = make_project()
    t = target(pd)
    PZ.build(t)
    first = read(t.scene_path)["shots"][0]["id"]
    PZ.main(["cam", first, "push", "--amount", "0.2"], project=pd)
    patches, _ = PZ.cinema_patches(pd)
    assert first in patches and patches[first].get("cam") or patches[first].get("panel")
    designed.apply_shots(path)
    spec = load_spec(path, plugins=False)
    shot = next(s for s in spec.shots if s.id == first)
    assert "directed in previz" in (shot.cfg.get("notes") or "")


def test_the_cli_routes_previz_with_and_without_a_project_flag():
    assert cli._previz_argv(["previz", "show"]) == (None, ["show"])
    assert cli._previz_argv(["-p", "demo", "previz", "strip", "--n", "4"]) == ("demo", ["strip", "--n", "4"])
    assert cli._previz_argv(["build"]) is None


# ---------------------------------------------------------------- the shipped sample + the real viewer
def test_the_sample_scene_loads_and_strips(tmp_path):
    sc = read(os.path.join(ROOT, "templates", "previz", "sample", "scene.json"))
    errors, _ = PZ.problems(sc)
    assert errors == []
    out = str(tmp_path / "s.png")
    res = PZ.render_pil(sc, PZ.pick_times(sc), out)
    assert Image.open(out).size == (res["width"], res["height"])
    html = PZ.viewer_html(sc)
    assert "THREE" in html and '"shots"' in html


@pytest.mark.skipif(PZ.find_chrome() is None, reason="no headless Chrome")
def test_chrome_draws_the_three_js_viewer(tmp_path):
    sc = read(os.path.join(ROOT, "templates", "previz", "sample", "scene.json"))
    viewer = str(tmp_path / "v.html")
    open(viewer, "w").write(PZ.viewer_html(sc))
    out = str(tmp_path / "c.png")
    res = PZ.render_chrome(viewer, sc, PZ.pick_times(sc), out)
    if res is None:
        pytest.skip("Chrome cannot draw WebGL here")
    assert res["engine"] == "chrome" and Image.open(out).size[0] > 300
