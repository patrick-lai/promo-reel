import json
import os
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from promo import prep as P

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is needed")


def triangle():
    return [np.array([[8.0, 8.0], [24.0, 8.0], [16.0, 24.0]], np.float32)]


def test_a_mesh_is_drawn_on_the_face_and_depth_people_cover_the_near_blob():
    rgb = np.zeros((32, 32, 3), np.uint8)
    rgb[:] = (10, 20, 30)
    out = P.draw_mesh(rgb, triangle())
    assert out[8, 8].sum() > 200 and (out[0, 0] == (10, 20, 30)).all()
    d = np.zeros((32, 32), np.float32)
    d[16:, 8:24] = 1
    mask = P.person_mask(d)
    assert mask[20, 16] and not mask[4, 16]
    comp = P.composite(rgb, d, mask)
    assert comp[20, 16, 0] > 200 and (comp[4, 4] == (10, 20, 30)).all()


def test_pitch_shift_raises_a_tone_and_keeps_the_length():
    sr, n = 8000, 8000
    t = np.arange(n) / sr
    y = np.sin(2 * np.pi * 220 * t).astype(np.float32)
    out = P.pitch_samples(y, sr, 12)
    assert len(out) == n
    spec = np.abs(np.fft.rfft(out * np.hanning(n)))
    peak = np.fft.rfftfreq(n, 1 / sr)[int(np.argmax(spec))]
    assert 400 < peak < 500


@needs_ffmpeg
def test_prepare_writes_a_clip_with_the_mesh_and_restore_puts_the_source_audio_back(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x36:d=1",
                           "-f", "lavfi", "-i", "sine=f=440:d=1", "-shortest", "-pix_fmt", "yuv420p", str(src)])
    seen = []
    out = P.prepare(src, tmp_path / "prep.mp4", "face_mesh", detect=lambda rgb: triangle(), on_progress=lambda i, n: seen.append(i))
    meta = json.loads(open(str(out) + ".prep.json").read())
    assert meta["mode"] == "face_mesh" and meta["frames"] >= 20 and meta["pitched"] and seen
    gen = tmp_path / "gen.mp4"
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x36:d=1", "-pix_fmt", "yuv420p", str(gen)])
    rest = P.restore_audio(gen, src, tmp_path / "rest.mp4")
    assert P._has_audio(rest)
    with pytest.raises(P.PrepError, match="no prep mode"):
        P.prepare(src, tmp_path / "x.mp4", "disguise")
