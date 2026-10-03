"""Fast unit tests (plain asserts; run `python tests/test_core.py` or pytest).

Reference-data tests (events == legacy events.json) are skipped when the legacy file is not on this machine.
"""
import copy
import json
import os
import sys
import tempfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
EXAMPLE = os.path.join(ROOT, "projects", "commission-ai-hero", "promo.yaml")
LEGACY_EVENTS = "/workspace/videos/commission-ai-promo/audio/mix/events.json"

from promo import assets as A  # noqa: E402
from promo.events import compute_events  # noqa: E402
from promo.spec import Spec, SpecError, expand_env, load_spec  # noqa: E402


def test_timeline_frames_sum_to_1800():
    spec = load_spec(EXAMPLE)
    assert spec.total_frames() == 1800
    assert spec.validate() == []
    assert spec.timeline.frames(0, 98) == 1800
    assert [s.n for s in spec.shots][:3] == [73, 74, 147]


def test_events_match_legacy():
    if not os.path.exists(LEGACY_EVENTS):
        return
    ev = compute_events(load_spec(EXAMPLE))
    assert ev == json.load(open(LEGACY_EVENTS))


def _raw():
    return yaml.safe_load(open(EXAMPLE))


def test_lint_rejects_ui_editing_keys():
    for key in ("debubble", "paint_out", "inpaint", "ui_edit"):
        raw = _raw()
        raw["shots"][0][key] = True
        try:
            Spec(EXAMPLE, expand_env(raw))
        except SpecError as e:
            assert "never edit the app's UI in post" in str(e)
        else:
            raise AssertionError(f"{key} was accepted")
    raw = _raw()
    raw["shots"][3]["overlays"].append({"type": "caption", "text": "x", "inpaint": 1})   # nested keys too
    try:
        Spec(EXAMPLE, expand_env(raw))
    except SpecError:
        pass
    else:
        raise AssertionError("nested inpaint accepted")


def test_env_expansion_and_paths():
    os.environ.pop("PROMO_TEST_X", None)
    assert expand_env("${PROMO_TEST_X:-fallback}/a") == "fallback/a"
    os.environ["PROMO_TEST_X"] = "set"
    assert expand_env("${PROMO_TEST_X:-fallback}/a") == "set/a"
    spec = load_spec(EXAMPLE)
    assert spec.build.startswith(spec.root)
    assert os.path.isabs(spec.clip_path("shot-10-v1080"))


def test_manifest_missing_licence_fails():
    spec = load_spec(EXAMPLE, plugins=False)
    man = A.load_manifest(spec)
    assert A.validate(spec, man) == []
    bad = copy.deepcopy(man)
    bad["music-491119"]["licence"] = ""
    assert any("music-491119: missing licence" in p for p in A.validate(spec, bad))
    bad = copy.deepcopy(man)
    bad["sfx-tick"]["source_url"] = ""
    assert any("sfx-tick: missing source_url" in p for p in A.validate(spec, bad))
    bad = copy.deepcopy(man)
    del bad["kokoro-model"]
    assert any("kokoro-model" in p and "not in the assets manifest" in p for p in A.validate(spec, bad))


def test_caption_geometry_inside_zone():
    from promo.render import RenderContext
    from promo.shots import get_type
    spec = load_spec(EXAMPLE)
    ctx = RenderContext.from_spec(spec)
    z = ctx.caption["zone"]
    n = 0
    for s in spec.shots:
        for c in get_type(s.type).captions(ctx, s):
            if c["role"] == "caption":
                b = c["box"]
                n += 1
                assert b[0] >= z["x0"] and b[2] <= z["x1"] and b[1] >= z["y0"] and b[3] <= z["y1"], (s.id, b)
    assert n == 9


def test_examples_symlink_still_works():
    link = os.path.join(ROOT, "examples", "commission-ai-hero")
    assert os.path.islink(link) and os.path.realpath(link) == os.path.join(ROOT, "projects", "commission-ai-hero")
    assert load_spec(os.path.join(link, "promo.yaml"), plugins=False).total_frames() == 1800


def test_footage_manifest_covers_spec_and_verifies():
    from promo import footage as FT
    spec = load_spec(EXAMPLE)
    refs = FT.referenced(spec)
    assert {"shot-10-v1080", "shot-06-still-node", "shot-17-v1", "shot-14b"} <= set(refs)
    assert set(refs["shot-14b"]) == {"14b", "16"}
    res = FT.verify(spec)
    assert res and all(r["ok"] for r in res), [r["error"] for r in res if not r["ok"]]


def _spec_with_clip(**over):
    spec = load_spec(EXAMPLE, plugins=False)
    man = {k: dict(v) for k, v in __import__("promo.footage", fromlist=["x"]).load(spec).items()}
    man["shot-06-still-node"].update(over)          # small png: cheap to hash
    spec._footage = man
    return spec


def test_footage_sha_mismatch_fails_clearly():
    from promo import footage as FT
    spec = _spec_with_clip(sha256="0" * 64)
    try:
        FT.gate(spec, {"06"})
    except FT.FootageError as e:
        m = str(e)
        assert "shot-06-still-node" in m and "shots 06" in m and "expected " + "0" * 64 in m and "actual " in m
        assert "promo footage add" in m
    else:
        raise AssertionError("sha mismatch accepted")


def test_footage_missing_file_and_unknown_id_fail():
    from promo import footage as FT
    spec = _spec_with_clip(path="/nonexistent/clip.png")
    try:
        FT.gate(spec, {"06"})
    except FT.FootageError as e:
        assert "file not found" in str(e) and "shot-06-still-node" in str(e)
    else:
        raise AssertionError("missing file accepted")
    spec = load_spec(EXAMPLE, plugins=False)
    spec.shot("09").cfg["source"] = "no-such-clip"
    try:
        FT.gate(spec, {"09"})
    except FT.FootageError as e:
        assert "no-such-clip" in str(e) and "not in the footage manifest" in str(e)
    else:
        raise AssertionError("unknown clip id accepted")
    try:
        spec.clip_path("no-such-clip")
    except FT.FootageError:
        pass
    else:
        raise AssertionError("clip_path resolved an unknown id")


def test_footage_add_roundtrip():
    from promo import footage as FT
    with tempfile.TemporaryDirectory() as d:
        spec = load_spec(EXAMPLE, plugins=False)
        spec.raw["footage"] = os.path.join(d, "footage", "manifest.yaml")
        spec._footage = None
        png = os.path.join(d, "x.png")
        from PIL import Image
        Image.new("RGB", (64, 36), (9, 9, 9)).save(png)
        e = FT.add(spec, png, "x", shots=["01"], commit="a" * 40, capture="?demo=promo", dpr=2, demo=True)
        assert e["resolution"] == "64x36" and e["fps"] is None and len(e["sha256"]) == 64 and e["app_commit"] == "a" * 40
        assert FT.load(spec)["x"]["dpr"] == 2
        assert "| x |" in open(os.path.join(d, "footage", "manifest.md")).read()


def test_dpr_and_demo_warnings():
    from promo import footage as FT
    spec = load_spec(EXAMPLE, plugins=False)
    dpr_w, demo = FT.qa_findings(spec)
    assert any(w.startswith("shot 10:") for w in dpr_w) and not any(w.startswith("shot 09:") for w in dpr_w)
    assert "shot-10-v1080" in demo


def _cli_json(*argv):
    import contextlib
    import io
    from promo import cli
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["-p", EXAMPLE, *argv])
    return rc, json.loads(buf.getvalue())


def test_status_and_other_json_parse():
    rc, st = _cli_json("status", "--json")
    assert isinstance(st["ok"], bool) and {s["step"] for s in st["steps"]} >= {"assets", "footage", "sfx", "music", "shot 01", "events", "mix", "assemble", "contact"}
    assert all(s["status"] in ("up-to-date", "stale", "missing") for s in st["steps"])
    rc, tl = _cli_json("timeline", "--json")
    assert tl["ok"] and tl["total_frames"] == 1800 and rc == 0
    rc, a = _cli_json("assets", "--json")
    assert a["ok"] and rc == 0 and all("licence" in r for r in a["assets"])
    rc, f = _cli_json("footage", "verify", "--json")
    assert f["ok"] and rc == 0
    rc, f = _cli_json("footage", "list", "--json")
    assert f["ok"] and len(f["clips"]) == 16


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
