import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from promo import genvideo as G


def test_detect_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "HOME", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("XAI_API_KEY", "x")
    ps = {p["id"]: p for p in G.detect()}
    assert set(ps) == {"grok", "codex", "openrouter"}   # unwired API adapters are not advertised


def test_pick_prefers_verified_and_fails_cleanly(monkeypatch):
    fake = [dict(id="grok", kind=["image", "video"], available=True, verified=[]),
            dict(id="codex", kind=["image"], available=True, verified=["image"])]
    monkeypatch.setattr(G, "detect", lambda: fake)
    assert G.pick("image")["id"] == "codex"
    assert G.pick("video")["id"] == "grok"
    with pytest.raises(SystemExit):
        G.pick("video", "codex")


def test_stub_draws_a_placeholder_and_never_reaches_a_real_generator(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "HOME", tmp_path)
    monkeypatch.setenv("PROMO_GEN_STUB", "1")
    assert [p["id"] for p in G.providers("image")] == ["stub"]
    out = tmp_path / "frame.png"
    meta = G.generate("image", "a calm desk at night", str(out), guard=G.STORYBOARD)
    assert meta["provider"] == "stub" and out.is_file()


def test_prompt_forbids_ui_and_text():
    t = G.prompt_for("video", "macro of lace", Path("/x/a.mp4"), 4, "16:9")
    assert "no text" in t.lower() and "no user-interface" in t.lower() and "/x/a.mp4" in t


def test_generate_writes_sidecar(monkeypatch, tmp_path):
    out = tmp_path / "bg.mp4"
    monkeypatch.setattr(G, "HOME", tmp_path)
    monkeypatch.setattr(G, "detect", lambda: [dict(id="grok", kind=["image", "video"], available=True, verified=[])])

    def fake_run(argv, **kw):
        out.write_bytes(b"not really a video")
        return SimpleNamespace(returncode=0, stdout=str(out), stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(G, "probe_media", lambda p: {"width": 1920, "height": 1080, "duration": 4.0})
    meta = G.generate("video", "lace", str(out))
    side = json.loads(Path(str(out) + ".gen.json").read_text())
    assert side["generated"] and side["provider"] == "grok" and side["sha256"] == meta["sha256"]
    assert "video" in json.loads((tmp_path / ".promo-tools" / "gen-state.json").read_text())["grok"]["ok"]


def test_generate_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "HOME", tmp_path)
    monkeypatch.setattr(G, "detect", lambda: [dict(id="grok", kind=["video"], available=True, verified=[])])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    with pytest.raises(RuntimeError):
        G.generate("video", "x", str(tmp_path / "no.mp4"))


def test_register_marks_generated(tmp_path, monkeypatch):
    import yaml
    from promo import footage as FT
    from promo.spec import load_spec
    proj = tmp_path / "p"
    (proj / "footage").mkdir(parents=True)
    (proj / "promo.yaml").write_text("project: {name: t}\noutput: {name: t, resolution: 1080, fps: 30, duration: 1}\nfootage: footage/manifest.yaml\nshots: []\n")
    f = tmp_path / "bg.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(FT, "probe_media", lambda p: ("1920x1080", 24.0))
    spec = load_spec(str(proj / "promo.yaml"))
    FT.add(spec, str(f), "bg", generated={"provider": "grok"})
    clips = yaml.safe_load((proj / "footage" / "manifest.yaml").read_text())["clips"]
    assert clips[0]["generated"] == {"provider": "grok"}


def test_requests_and_register(tmp_path, monkeypatch):
    import yaml
    from promo import footage as FT
    from promo.spec import load_spec
    proj = tmp_path / "p"
    (proj / "footage").mkdir(parents=True)
    (proj / "promo.yaml").write_text("project: {name: t}\noutput: {name: t, resolution: 1080, fps: 30, duration: 1}\nfootage: footage/manifest.yaml\n"
                                     "broll: [{id: bg, kind: video, prompt: night sky, seconds: 3}]\nshots: []\n")
    spec = load_spec(str(proj / "promo.yaml"))
    rq = G.requests(spec)
    assert rq[0]["id"] == "bg" and not rq[0]["exists"] and "no text" in rq[0]["prompt"].lower()
    Path(rq[0]["out"]).parent.mkdir(parents=True, exist_ok=True)
    Path(rq[0]["out"]).write_bytes(b"x")
    monkeypatch.setattr(FT, "probe_media", lambda p: ("1920x1080", 24.0))
    monkeypatch.setattr(G, "probe_media", lambda p: {"width": 1920, "height": 1080, "duration": 3.0})
    m = G.register(spec, rq[0]["out"], "bg", provider="claude-agent", prompt="night sky", shots=["03"])
    assert m["registered"] == "bg"
    assert yaml.safe_load((proj / "footage" / "manifest.yaml").read_text())["clips"][0]["generated"]["provider"] == "claude-agent"


def test_needs_lists_capture_and_generate(tmp_path):
    from promo import needs
    from promo.spec import load_spec
    proj = tmp_path / "p"
    (proj / "footage").mkdir(parents=True)
    (proj / "promo.yaml").write_text("project: {name: t}\noutput: {name: t, resolution: 1080, fps: 30, duration: 1}\nfootage: footage/manifest.yaml\n"
                                     "broll: [{id: bg, kind: video, prompt: night sky}]\n"
                                     "shots: []\n")
    n = needs.collect(load_spec(str(proj / "promo.yaml")))
    assert [x["kind"] for x in n] == ["generate"] and "gen register" in n[0]["then"]


def test_plate_backdrop_behind_ui_panel_is_allowed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from promo import genvideo as GV, footage as FT
    shot_ui = SimpleNamespace(id="01", type="cinema", get=lambda k, d=None: {"ui": True, "source": "real", "look": {"backdrop": {"plate": "scene"}}}.get(k, d),
                              cfg={"source": "real", "look": {"backdrop": {"plate": "scene"}}})
    shot_plate_on_ui = SimpleNamespace(id="02", type="cinema", get=lambda k, d=None: {"ui": True, "source": "scene"}.get(k, d), cfg={"source": "scene"})
    spec = SimpleNamespace(shots=[shot_ui])
    monkeypatch.setattr(FT, "load", lambda sp: {"scene": {"generated": {"provider": "grok"}, "path": "x"}, "real": {"path": "y"}})
    monkeypatch.setattr(FT, "referenced", lambda sp: {"scene": ["01"], "real": ["01"]})
    out = GV.plate_gate(spec)
    assert out[0][1] == "PASS"
    spec2 = SimpleNamespace(shots=[shot_plate_on_ui])
    monkeypatch.setattr(FT, "referenced", lambda sp: {"scene": ["02"]})
    assert GV.plate_gate(spec2)[0][1] == "FAIL"


def test_own_likeness_only_in_avatar_overlay_with_consent(monkeypatch):
    from types import SimpleNamespace
    from promo import genvideo as GV, footage as FT

    def shot(sid, cfg):
        return SimpleNamespace(id=sid, type="clip", cfg=cfg, get=cfg.get)

    def gate(clips, *shots):
        monkeypatch.setattr(FT, "load", lambda sp: clips)
        return {g: st for g, st, _ in GV.plate_gate(SimpleNamespace(shots=list(shots), raw={}))}

    avatar = shot("01", {"source": "real", "overlays": [{"type": "avatar", "source": "me"}]})
    me = {"generated": {"provider": "ditto", "likeness": "own", "consent": "Pat, chat 11 Oct 2026"}, "path": "x"}
    real = {"path": "y"}
    assert gate({"me": me, "real": real}, avatar) == {"generated-plates": "PASS", "generated-review": "WARN"}
    no_consent = {**me, "generated": {"provider": "ditto", "likeness": "own"}}
    assert gate({"me": no_consent, "real": real}, avatar)["generated-plates"] == "FAIL"
    plate = {"generated": {"provider": "grok"}, "path": "x"}
    assert gate({"me": plate, "real": real}, avatar)["generated-plates"] == "FAIL"
    as_picture = shot("02", {"source": "me", "ui": False})
    assert gate({"me": me}, as_picture)["generated-plates"] == "FAIL"


def _staged(tmp_path):
    import yaml
    from promo.spec import load_spec
    proj = tmp_path / "p"
    (proj / "footage").mkdir(parents=True)
    raw = dict(project=dict(name="t"), output=dict(name="t", resolution=1080, fps=30, duration=1), footage="footage/manifest.yaml",
               broll=[
                   dict(id="hero", stage="character", kind="image", prompt="a woman in a striped sweater"),
                   dict(id="phone", stage="prop", kind="image", prompt="a burgundy phone with a triple camera"),
                   dict(id="plaza", stage="location", kind="image", prompt="a pale granite plaza with a glass cube"),
                   dict(id="walk", stage="shot", kind="video", seconds=8, aspect="4:3",
                        prompt="she strides across the empty plaza, phone in both hands, never breaking pace",
                        refs=[dict(id="hero", scope="identity"), dict(id="phone", scope="product"), dict(id="plaza", scope="geography")],
                        beats=["0.0-1.6s tight on the phone, already walking", "1.6-8.0s full figure, pace unchanged"],
                        camera="one backward dolly at chest height", optics="47 degree field of view, normal lens, zero distortion"),
               ], shots=[])
    (proj / "promo.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_spec(str(proj / "promo.yaml"))


def test_terse_shot_expands_into_one_skeleton():
    raw = "she strides across the empty plaza, phone in both hands, never breaking pace"
    after = G.compose(raw, stage="shot", seconds=8, aspect="4:3", refs=[
        "identity=hero:early-20s woman in a striped sweater",
        "product=phone:a burgundy phone with a triple camera",
        "geography=plaza:a pale granite plaza with a glass cube",
    ], beats=["0.0-1.6s tight on the phone, already walking", "1.6-8.0s full figure, pace unchanged"],
                      camera="one backward dolly at chest height", optics="47 degree field of view, normal lens, zero distortion",
                      audio="footsteps on stone, no music")
    assert after.index("SCENE CONTEXT") < after.index(raw)
    assert "IDENTITY ONLY" in after and "100% matches the reference" in after
    assert "never the studio lighting" in after and "Geography and materials only" in after and "PRODUCT ONLY" in after
    assert "never reset" in after.lower() and "order of beats is fixed" in after.lower()
    assert after.index("0.0-1.6s") < after.index("1.6-8.0s")
    assert "footsteps on stone, no music" in after
    for header in ("ACTIVE REFERENCES", "THE ACTION", "OPTICS", "CAMERA", "HARD RULES", "POSITIVE CONSTRAINTS", "NEGATIVE", "AUDIO"):
        assert header in after
    assert after.count("ACTIVE REFERENCES") == 1
    assert "loafers" not in after and "pearl" not in after


def test_terse_character_sheet_does_not_invent_a_wardrobe():
    after = G.compose("a woman in a striped sweater", stage="character")
    assert "EXACTLY FOUR PANELS" in after and "PANEL 1" in after and "striped sweater" in after
    assert "100% matches the reference" in after and "no text" in after.lower()
    assert "loafers" not in after and "navy" not in after and "pearl" not in after


def test_a_rich_shot_prompt_is_not_wrapped_again():
    rich = ("SCENE CONTEXT\n\nhello\n\nACTIVE REFERENCES\n\n@a — IDENTITY ONLY: a woman. 100% matches the reference.\n\n"
            "NEGATIVE\n\nnone")
    after = G.compose(rich, stage="shot", refs=["identity=a:a woman"])
    assert after.count("ACTIVE REFERENCES") == 1
    assert after.count("100% matches the reference") == 1


def test_plain_plate_is_not_expanded_into_the_skeleton():
    t = G.prompt_for("video", "night sky", Path("/x/a.mp4"), 4, "16:9")
    assert "ACTIVE REFERENCES" not in t and "SCENE CONTEXT" not in t and "no text" in t.lower()


def test_stages_lock_references_before_a_shot_and_keep_their_words(tmp_path, monkeypatch):
    from promo import footage as FT
    from promo import needs
    spec = _staged(tmp_path)
    rq = {r["id"]: r for r in G.requests(spec)}
    assert rq["hero"]["blocked"] is None and rq["walk"]["blocked"]
    assert "approve hero" in rq["walk"]["blocked"]
    prompt = rq["walk"]["prompt"]
    assert rq["walk"]["raw_prompt"] in prompt
    assert "a woman in a striped sweater" in prompt and "a burgundy phone with a triple camera" in prompt
    assert "a pale granite plaza with a glass cube" in prompt
    walk_need = next(x for x in needs.collect(spec) if x["id"] == "walk")
    assert "approve hero" in walk_need["then"] and "--id walk" not in walk_need["then"]
    phone = next(b for b in G.broll_entries(spec) if b["id"] == "phone")
    phone["refs"] = [dict(id="plaza", scope="geography")]
    assert "earlier stages" in G.block_reason(spec, phone, {})
    walk = next(b for b in G.broll_entries(spec) if b["id"] == "walk")
    tagged = dict(walk, refs=[dict(id="hero", scope="product")])
    assert "as product" in G.block_reason(spec, tagged, {})

    made = []

    def fake_generate(kind, prompt, out, *a, **k):
        made.append(k.get("stage"))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"x")
        return dict(provider="stub", kind=kind)

    monkeypatch.setattr(G, "generate", fake_generate)
    ran = {r["id"]: r for r in G.plan(spec, run=True)}
    assert ran["hero"]["ran"] is True and made == ["character"]
    assert ran["phone"]["ran"] is False and "approve hero" in ran["phone"]["error"]
    assert ran["plaza"]["ran"] is False and ran["walk"]["ran"] is False and ran["walk"]["error"]

    monkeypatch.setattr(FT, "probe_media", lambda p: ("64x36", None))
    monkeypatch.setattr(G, "probe_media", lambda p: {"width": 64, "height": 36})
    for cid, stage in (("hero", "character"), ("phone", "prop"), ("plaza", "location")):
        src = tmp_path / f"{cid}.png"
        src.write_bytes(b"png")
        G.register(spec, str(src), cid, prompt=rq[cid]["raw_prompt"], kind="image", stage=stage)
        assert G.block_reason(spec, walk)  # still short of an approval
        G.approve(spec, cid)
    assert G.block_reason(spec, walk) is None
    ready = {r["id"]: r for r in G.requests(spec)}["walk"]["prompt"]
    assert "Reference file:" in ready and "100% matches the reference" in ready

    sent = {}

    def fake_shot(kind, prompt, out, *a, **k):
        sent["prompt"] = prompt
        sent.update(k)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"x")
        return dict(provider="stub", kind=kind)

    monkeypatch.setattr(G, "generate", fake_shot)
    assert {r["id"]: r["ran"] for r in G.plan(spec, run=True)}["walk"] is True
    assert sent["descriptions"]["hero"] == "a woman in a striped sweater"
    assert sent["files"]["hero"].endswith("hero.png")
