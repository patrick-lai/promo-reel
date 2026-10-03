"""Live2D renderer + livestream layout tests (plain asserts; `python tests/test_live2d.py` or pytest).

The render test needs `promo live2d fetch` (Cubism Core + models), node + live2d/node_modules and a Chromium; it is
skipped when any of those are missing. Everything else is pure Python.
"""
import copy
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEMO = os.path.join(ROOT, "projects", "live2d-demo", "promo.yaml")

from promo import live2d as L2  # noqa: E402
from promo import livestream as LS  # noqa: E402
from promo.spec import Spec, expand_env  # noqa: E402


def _speechy(sr=24000, dur=4.0, seed=0):
    """Syllable-like bursts: 80-250 ms voiced tones with noise, 60-300 ms gaps."""
    rng = np.random.default_rng(seed)
    y = np.zeros(int(sr * dur), np.float32)
    t = 0.3
    while t < dur - 0.4:
        n = int(rng.uniform(0.08, 0.25) * sr)
        a = int(t * sr)
        k = np.arange(n) / sr
        env = np.sin(np.pi * np.arange(n) / n) ** 0.5
        y[a:a + n] += (0.3 * np.sin(2 * np.pi * rng.uniform(120, 220) * k) + 0.05 * rng.normal(size=n)) * env
        t += n / sr + rng.uniform(0.06, 0.3)
    return y, sr


def test_lip_track_zero_lag():
    for seed in range(3):
        y, sr = _speechy(seed=seed)
        n = int(len(y) / sr * 30)
        lt = L2.lip_track(y, sr, 30, n)
        lag = L2.lip_lag(lt["open"], y, sr, 30)
        assert abs(lag["frames"]) <= 0.5, lag            # well under a frame
        assert lag["peak"] > 0.6, lag
        assert lt["open"].min() >= 0 and lt["open"].max() <= 1
        assert lt["open"][:5].max() == 0                  # silent lead-in: mouth shut


def test_lip_lag_detects_late_mouth():
    y, sr = _speechy(seed=4)
    n = int(len(y) / sr * 30)
    m = L2.lip_track(y, sr, 30, n)["open"]
    late = np.concatenate([np.zeros(3), m[:-3]])          # 3 frames late
    assert 2.5 <= L2.lip_lag(late, y, sr, 30)["frames"] <= 3.5


def test_idle_tracks_deterministic_and_blink():
    a = L2.idle_tracks(300, 30, seed=7)
    b = L2.idle_tracks(300, 30, seed=7)
    c = L2.idle_tracks(300, 30, seed=8)
    assert all(np.array_equal(a[k], b[k]) for k in a)
    assert not np.array_equal(a["ParamAngleX"], c["ParamAngleX"])
    assert a["ParamEyeLOpen"].min() == 0.0                # at least one full blink in 10 s
    assert abs(a["ParamAngleX"]).max() < 12               # small sway only


def test_collaboration_characters_refused():
    try:
        L2.model_entry("natori")
    except L2.Live2DError as e:
        assert "Collaboration" in str(e)
    else:
        raise AssertionError("collaboration character accepted")
    reg = L2.registry()
    for k, m in reg["models"].items():
        if m.get("character_type") == "original":
            assert m["sha256"] and m["fetch_url"].startswith("https://cubism.live2d.com/"), k
    assert reg["runtime"]["fetch_url"].startswith("https://cubism.live2d.com/")
    assert "copyrighted by Live2D Inc." in reg["notice"]["short"]


def _spec(mut=None):
    raw = expand_env(yaml.safe_load(open(DEMO)))
    raw = copy.deepcopy(raw)
    if mut:
        mut(raw)
    return Spec(DEMO, raw)


def _gates(spec):
    return {g: (st, msg) for g, st, msg in LS.check(spec)}


def test_livestream_demo_passes():
    g = _gates(_spec())
    assert all(st == "PASS" for st, _ in g.values()), g


def test_livestream_gates_fail():
    cases = {
        "livestream-screen": lambda r: r["livestream"].__setitem__("screen", {"w": 1280}),             # 44 % of the frame
        "livestream-chat": lambda r: r["livestream"]["chat"].__setitem__("max_lines", 5),
    }
    for gate, mut in cases.items():
        assert _gates(_spec(mut))[gate][0] == "FAIL", gate

    def instant(r):
        r["livestream"]["move"]["dur"] = 0.0
    assert "instant flip" in _gates(_spec(instant))["livestream-side"][1]

    def second(r):
        r["livestream"]["moves"] = [{"beat": 12, "dur": 0.6}]
    assert "at most one" in _gates(_spec(second))["livestream-side"][1]

    def off_beat_change(r):
        r["livestream"]["move"]["beat"] = 5               # not a shot boundary
    assert _gates(_spec(off_beat_change))["livestream-side"][0] == "FAIL"

    def shot_flip(r):
        del r["livestream"]["move"]
        r["shots"][1]["hosts_side"] = "right"              # per-shot switch = instant flip
    assert "flips the hosts instantly" in _gates(_spec(shot_flip))["livestream-side"][1]

    def ok_right(r):
        del r["livestream"]["move"]
        r["livestream"]["hosts_side"] = "right"
    assert _gates(_spec(ok_right))["livestream-side"][0] == "PASS"


def test_keep_clear_overlap_fails():
    def corner_pill(r):
        r["shots"][0]["overlays"] = [{"type": "pill", "text": "NEW", "cx": 1760, "cy": 60, "t": [0, 3]}]
    g = _gates(_spec(corner_pill))["livestream-keep-clear"]
    assert g[0] == "FAIL" and "pill" in g[1], g

    def wide_hosts(r):                                      # keep-clear on the screen's left edge, next to the hosts
        r["livestream"]["keep_clear"] = [{"name": "left-edge", "box": [0.0, 0.3, 0.05, 0.9]}]
        r["livestream"]["screen"] = {"w": 1500}
    g = _gates(_spec(wide_hosts))["livestream-keep-clear"]
    assert g[0] == "FAIL" and "host" in g[1], g


def test_layout_geometry():
    s = _spec()
    L = LS.layout_at(s, 0.0)
    sc = L["screen"]
    assert (sc[2] - sc[0]) * (sc[3] - sc[1]) >= 0.55 * 1920 * 1080
    for h in L["hosts"]:
        assert h[2] <= sc[0], (h, sc)                       # hosts left of the screen
    R_ = LS.layout_at(s, s.duration - 0.01)
    for h in R_["hosts"]:
        assert h[0] >= R_["screen"][2], (h, R_["screen"])  # after the single move: right of the screen
    mid = LS.layout_at(s, s.timeline.t(12) + 0.4)
    assert mid["hosts_z"] == "below"                       # sliding hosts pass behind the screen


def _render_ready():
    try:
        L2.resolve_model("hiyori")
    except L2.Live2DError:
        return False
    return shutil.which("node") and os.path.isdir(os.path.join(L2.L2D_DIR, "node_modules", "pixi-live2d-display"))


def test_render_deterministic():
    if not _render_ready():
        print("skip test_render_deterministic (run `promo live2d fetch` + npm install in live2d/)")
        return
    y, sr = _speechy(dur=1.0, seed=2)
    d = tempfile.mkdtemp()
    import soundfile as sf
    wav = os.path.join(d, "v.wav")
    sf.write(wav, y, sr)
    hashes = []
    for k in range(2):
        out = os.path.join(d, f"r{k}.mov")
        rep = L2.render_host("hiyori", out, wav=wav, duration=0.5, width=160, height=200, seed=3, warmup=5, log=lambda *a: None)
        assert rep["frames"] == 15 and rep["mouth_offset_frames"] == 0
        raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", out, "-f", "rawvideo", "-pix_fmt", "rgba", "-"])
        assert len(raw) == 15 * 160 * 200 * 4
        hashes.append(hashlib.sha256(raw).hexdigest())
    assert hashes[0] == hashes[1], hashes
    shutil.rmtree(d)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
