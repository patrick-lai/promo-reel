import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from promo import genvideo as G


def test_detect_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "HOME", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    ps = {p["id"]: p for p in G.detect()}
    assert set(ps) == {"grok", "codex", "openai-api", "xai-api"}
    assert not ps["openai-api"]["available"]          # API adapter not wired: never auto-picked


def test_pick_prefers_verified_and_fails_cleanly(monkeypatch):
    fake = [dict(id="grok", kind=["image", "video"], available=True, verified=[]),
            dict(id="codex", kind=["image"], available=True, verified=["image"])]
    monkeypatch.setattr(G, "detect", lambda: fake)
    assert G.pick("image")["id"] == "codex"
    assert G.pick("video")["id"] == "grok"
    with pytest.raises(SystemExit):
        G.pick("video", "codex")


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
