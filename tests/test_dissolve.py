"""`cut_in: dissolve`: parsed and refused in promo/spec.py, blended frame by frame in the delivery encode (promo/assemble.py)."""
import os
import subprocess
import tempfile
from types import SimpleNamespace as NS

import numpy as np
import pytest

from promo import assemble as A
from promo.spec import Shot, SpecError, cuts


def film(*shots, fps=30):
    out, f0 = [], 0
    for i, (n, cfg) in enumerate(shots):
        out.append(Shot(id=f"0{i + 1}", b0=0, b1=0, t0=f0 / fps, t1=(f0 + n) / fps, f0=f0, n=n, fps=fps, cfg=cfg))
        f0 += n
    return NS(shots=out, fps=fps)


def test_cuts_centre_the_window_and_refuse_what_cannot_render():
    assert cuts(film((30, {}), (30, {"cut_in": "dissolve"}), (30, {"cut_in": {"kind": "dissolve", "dur": 0.4}}))) == [
        dict(shot="02", frame=30, a=4, b=5), dict(shot="03", frame=60, a=6, b=6)]
    assert cuts(film((30, {}), (30, {"cut_in": "flash_dip"}), (30, {"cut_in": "hard"}))) == []      # the shot renderer's own kinds
    for bad, why in [(film((30, {"cut_in": "dissolve"}), (30, {})), "first shot"),
                     (film((30, {}), (30, {"cut_in": {"kind": "dissolve", "dur": 0.5}})), "at most 0.4s"),
                     (film((30, {}), (30, {"cut_in": "wipe"})), "not hard or dissolve"),
                     (film((30, {}), (8, {"cut_in": "dissolve"}), (30, {"cut_in": "dissolve"})), "shot 02: its dissolves need 9 frames")]:
        with pytest.raises(SpecError, match=why):
            cuts(bad)


@pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0, reason="needs ffmpeg")
def test_final_video_blends_only_the_frames_around_the_cut():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "in.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=64x64:r=10:d=1", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=1",
                    "-filter_complex", "[0][1]concat=n=2,format=yuv420p", "-colorspace", "bt709", "-color_range", "tv", src], check=True)
    spec = NS(duration=2.0, segs_dir=d, raw={}, OW=64, OH=64, fps=10)
    out = A.final_video(spec, src, cut_list=[dict(shot="02", frame=10, a=2, b=2)])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    luma = np.frombuffer(raw, np.uint8).reshape(-1, 64, 64).mean(axis=(1, 2))
    assert len(luma) == 20                                                      # the film keeps every frame
    want = [255] * 8 + [204, 153, 102, 51] + [0] * 8                            # weights 1/5 .. 4/5 across the 4-frame window
    assert np.abs(luma - want).max() < 8, luma.round()
