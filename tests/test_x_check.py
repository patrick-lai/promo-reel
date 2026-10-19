"""Opt-in X platform gates (promo/x_check.py). No ffmpeg: probes and boxes are stubbed."""
import os
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from promo import check as CK  # noqa: E402
from promo import x_check as X  # noqa: E402


def _spec(tmp, platform="x", scale=0.5):
    out = os.path.join(tmp, "o.mp4")
    open(out, "w").close()
    return NS(raw={"platform": platform}, scale=scale, masters=[{}], audio_dir=tmp, output_path=lambda _s: out)


def _stub(mp, items, h=540, codec="h264", lufs=-14.2, windows=(-30.0, -20.0)):
    mp.setattr(X, "_boxes", lambda spec, ctx: iter(items))
    mp.setattr(CK, "ffprobe_json", lambda *a: {"streams": [dict(codec_type="video", width=h * 16 // 9, height=h, codec_name=codec, pix_fmt="yuv420p"),
                                                          dict(codec_type="audio", codec_name="aac")]})
    mp.setattr(CK, "loudness", lambda p: (lufs, -1.5))
    w = iter(windows)
    mp.setattr(X, "mean_lufs", lambda *a: next(w))


def test_disabled_without_platform(tmp_path):
    assert X.gates(_spec(str(tmp_path), platform=None), None) == []


def test_x_gates_pass_and_fail(tmp_path, monkeypatch):
    s = NS(id="01")
    _stub(monkeypatch, [(s, "HOOK", 0.4, [100, 400, 900, 500])])
    r = {g: st for g, st, _m in X.gates(_spec(str(tmp_path)), None)}
    assert r == {"x-safe-zone": "PASS", "x-export": "PASS", "x-soft-open": "PASS"}
    _stub(monkeypatch, [(s, "LATE", 2.5, [100, 900, 900, 1000])], h=720, lufs=-18.0, windows=(-20.0, -19.0))
    r = {g: st for g, st, _m in X.gates(_spec(str(tmp_path), scale=1), None)}
    assert r == {"x-safe-zone": "FAIL", "x-export": "FAIL", "x-soft-open": "WARN"}
