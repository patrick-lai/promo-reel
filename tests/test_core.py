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


# ---------------------------------------------------------------- capture/commission-ai helpers (mk_manifest.py, register.py)
CAPTURE = os.path.join(ROOT, "capture", "commission-ai")


def _capmod(name):
    import importlib.util
    sys.path.insert(0, CAPTURE)
    spec = importlib.util.spec_from_file_location(f"cap_{name}", os.path.join(CAPTURE, f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _cap_fixture(tmp):
    """Footage dir with 2 fake clips (+1 missing): 'a' has a meta.json (HIDE_MONEY + overlay), 'b' relies on notes.json inject."""
    fdir = os.path.join(tmp, "v1-1080")
    os.makedirs(fdir)
    for f in ("a", "b"):
        open(os.path.join(fdir, f + ".mov"), "wb").write(b"x")
    json.dump({"hash": "h", "params": {"css": ["HIDE_MONEY"], "cursorOverlay": True}}, open(os.path.join(fdir, "a.meta.json"), "w"))
    open(os.path.join(fdir, "capture-log.jsonl"), "w").write(json.dumps({"at": "2026-10-03T00:00:00Z", "shot": "b"}) + "\n")
    clip = dict(url="`?demo=promo`", beat="beat `x`", framing="DPR2 clip", notes="n", dpr=2)
    notes = {"header": ["- head"], "stills": [], "footer": [], "clips": [
        dict(clip, shot="A", file="a", id="a-v1080", shots=["01"]),
        dict(clip, shot="B", file="b", id="b-v1080", shots=["02"], inject={"css": ["NO_TOASTS"], "cursor_overlay": False}),
        dict(clip, shot="C", file="missing", id="c-v1080", shots=["03"], inject={"css": []})]}
    np = os.path.join(tmp, "notes.json")
    json.dump(notes, open(np, "w"))
    return fdir, notes, np


def test_capture_notes_record_injected_css_and_cursor():
    cm = _capmod("capmeta")
    notes = cm.load_notes()
    assert "capture/commission-ai/" in " ".join(notes["header"]) and "capture/v1-1080/" not in " ".join(notes["header"])
    by = {c["file"]: c for c in notes["clips"]}
    for c in notes["clips"]:
        assert set(c["inject"]["css"]) <= set(cm.CSS_DESC), c["file"]
    assert {f for f, c in by.items() if c["inject"]["cursor_overlay"]} == {"shot-10", "shot-10-dpr2"}
    assert by["shot-14b-dusk"]["inject"]["css"] == ["HIDE_MONEY"] and by["shot-12"]["inject"]["css"] == ["NO_TOASTS"]
    assert cm.REPO == ROOT   # derived from __file__, not hardcoded


def test_capture_mk_manifest_build_and_splice():
    mk = _capmod("mk_manifest")
    with tempfile.TemporaryDirectory() as tmp:
        fdir, notes, np = _cap_fixture(tmp)
        sec, loc, n = mk.build(notes, fdir, probe=lambda f: "1920x1080 @ 60 fps, 60 frames", dur=lambda f: 1.0, sha=lambda f: "s" * 64)
        assert n == 2 and sec[0] == mk.BEGIN and sec[-2] == mk.END
        rows = [l for l in sec if l.startswith("| A ") or l.startswith("| B ")]
        assert "HIDE_MONEY" in rows[0] and "capture-overlay arrow" in rows[0]
        assert "NO_TOASTS" in rows[1] and "cursor overlay: none" in rows[1] and "missing" not in "\n".join(sec)
        assert any("**Capture:** injected CSS" in l for l in loc)
        md = "top\n" + mk.BEGIN + "\nold\n" + mk.END + "\nbottom\n"
        out = mk.splice(md, "\n".join(sec))
        assert out.startswith("top\n") and out.endswith("bottom\n") and "old" not in out and out.count(mk.BEGIN) == 1
        assert mk.splice("x\n", "B").startswith("B\nx")
        # main(): CLI paths only, writes <footage>/manifest.md and --manifest-md
        mk.probe, mk.dur = (lambda f: "1920x1080 @ 60 fps, 60 frames"), (lambda f: 1.0)
        mdp = os.path.join(tmp, "manifest.md")
        open(mdp, "w").write(md)
        assert mk.main(["--footage-dir", fdir, "--notes", np, "--manifest-md", mdp]) == 0
        assert "| B |" in open(mdp).read() and os.path.exists(os.path.join(fdir, "manifest.md"))


def test_capture_register_dry_run_writes_nothing():
    import contextlib
    import io
    reg = _capmod("register")
    with tempfile.TemporaryDirectory() as tmp:
        fdir, notes, np = _cap_fixture(tmp)
        before = sorted(os.listdir(tmp)) + sorted(os.listdir(fdir))
        man = os.path.join(ROOT, "projects", "commission-ai-hero", "footage", "manifest.yaml")
        mt = os.path.getmtime(man)
        orig, reg.subprocess.run = reg.subprocess.run, lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran a command in --dry-run"))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = reg.main(["--dry-run", "--footage-dir", fdir, "--notes", np, "--python", "PY"])
        finally:
            reg.subprocess.run = orig
        out = buf.getvalue()
        assert rc == 0 and "2 clip(s); nothing written" in out and "c-v1080" not in out
        assert sorted(os.listdir(tmp)) + sorted(os.listdir(fdir)) == before and os.path.getmtime(man) == mt
        cmds = dict(reg.build_commands(notes, fdir, "PY", (), reg.read_log(fdir)))
        a, b = cmds["a-v1080"], cmds["b-v1080"]
        cap, fr = a[a.index("--capture") + 1], a[a.index("--framing") + 1]
        assert "HIDE_MONEY" in cap and "capture-overlay" in cap and "HIDE_MONEY" in fr and "capture-overlay cursor" in fr
        assert "NO_TOASTS" in b[b.index("--capture") + 1] and b[b.index("--framing") + 1] == "DPR2 clip"
        assert b[-2:] == ["--captured-at", "2026-10-03T00:00:00Z"] and "--captured-at" not in a
        only = reg.build_commands(notes, fdir, "PY", ["b-v1080"])
        assert [c for c, _ in only] == ["b-v1080"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
