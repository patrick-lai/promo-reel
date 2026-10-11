"""One-frame paint-glitch scan (promo/glitch.py) and its footage add / check wiring."""
import json
import subprocess

import numpy as np
import yaml

from promo import footage as FT
from promo import glitch as GL
from promo.spec import load_spec

H, W = 90, 160


def _stack(n=12):
    f = np.full((n, H, W), 40, np.uint8)
    f[:, 10:30, 10:150] = 200                       # a static header bar
    return f


def test_one_frame_hole_is_a_glitch():
    f = _stack()
    f[6, 50:90, 0:160] = 0                          # half the panel missing for one frame (layer behind shows through)
    hits = GL.find(f, 30.0)
    assert [h["frame"] for h in hits] == [6]
    assert hits[0]["t"] == 0.2 and hits[0]["box"][1] >= 0.5


def test_ui_changes_that_persist_or_move_are_not_glitches():
    f = _stack(20)
    f[8:, 50:70, 20:60] = 230                       # a badge appears and stays
    for i in range(20):                             # a block sliding across, every frame different
        f[i, 75:85, 5 * i:5 * i + 20] = 255
    assert GL.find(f, 30.0) == []


def _encode(frames, path):
    n, h, w = frames.shape
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", "30", "-i", "-",
                    "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(path)], input=frames.tobytes(), check=True)


def _project(tmp_path):
    proj = tmp_path / "p"
    (proj / "footage").mkdir(parents=True)
    (proj / "promo.yaml").write_text("project: {name: t}\noutput: {name: t, resolution: 1080, fps: 30, duration: 1}\nfootage: footage/manifest.yaml\nshots: []\n")
    return load_spec(str(proj / "promo.yaml"))


def test_scan_reads_an_encoded_clip(tmp_path):
    f = np.repeat(_stack(30), 4, axis=1).repeat(4, axis=2)
    f[17, 200:360, :] = 0
    _encode(f, tmp_path / "take.mov")
    r = GL.scan(str(tmp_path / "take.mov"))
    assert r["frames"] == 30 and r["fps"] == 30.0
    assert [g["frame"] for g in r["glitches"]] == [17]


def test_add_records_glitches_and_check_findings_honour_glitch_ok(tmp_path):
    f = np.repeat(_stack(30), 4, axis=1).repeat(4, axis=2)
    f[17, 200:360, :] = 0
    _encode(f, tmp_path / "take.mov")
    spec = _project(tmp_path)
    e = FT.add(spec, str(tmp_path / "take.mov"), "cap", commit="a" * 40, dpr=2)
    assert e["glitches"] == [17]
    msgs = GL.findings(spec, ["cap"])
    assert len(msgs) == 1 and msgs[0].startswith("cap: 1 one-frame paint glitch at frame 17 (0.57 s)")
    cache = json.load(open(spec.build + "/footage-glitch.json"))
    assert cache["cap"]["sha256"] == e["sha256"]          # scanned once, reused while the bytes are unchanged

    man = yaml.safe_load(open(FT.manifest_path(spec)))
    man["clips"][0]["glitch_ok"] = [17]                   # reviewed: a real one-frame flash in the product
    yaml.safe_dump(man, open(FT.manifest_path(spec), "w"))
    spec._footage = None
    assert GL.findings(spec, ["cap"]) == []
    e2 = FT.add(spec, str(tmp_path / "take.mov"), "cap", commit="a" * 40, dpr=2)
    assert e2["glitch_ok"] == [17]                        # same bytes re-added: the review stands


def test_generated_plates_are_not_scanned(tmp_path, monkeypatch):
    spec = _project(tmp_path)
    f = tmp_path / "bg.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(FT, "probe_media", lambda p: ("1920x1080", 24.0))
    monkeypatch.setattr(GL, "scan", lambda p: (_ for _ in ()).throw(AssertionError("scanned a generated plate")))
    FT.add(spec, str(f), "bg", generated={"provider": "grok"})
    assert GL.findings(spec, ["bg"]) == []
