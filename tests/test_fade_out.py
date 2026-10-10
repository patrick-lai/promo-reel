"""`output.fade_out` fades the picture to black over the last N seconds of the assembled film."""
import os
import subprocess
import tempfile

import numpy as np
import pytest

from promo import assemble as A


def test_fade_filter_window():
    assert A.fade_out_filter(45.0, 0) is None
    assert A.fade_out_filter(45.0, None) is None
    assert A.fade_out_filter(47.0, 1.8) == "fade=t=out:st=45.200:d=1.800:color=black"
    assert A.fade_out_filter(1.0, 5.0) == "fade=t=out:st=0.000:d=1.000:color=black"     # never longer than the film


@pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0, reason="needs ffmpeg")
def test_last_frame_is_black_and_first_is_not():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "in.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=64x64:r=10:d=4", "-pix_fmt", "yuv420p", src], check=True)

    class Spec:
        duration = 4.0
        segs_dir = d
        raw = {"output": {"fade_out": 1.5}}
    out = A.fade_out_video(Spec, src)
    def luma(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", out, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
        return float(np.frombuffer(raw, np.uint8).mean())
    assert luma(0.0) > 200 and luma(2.0) > 200          # untouched before the fade starts
    assert luma(3.0) < luma(2.0)                          # fading
    assert luma(3.9) < 30                                 # (almost) black at the end
    Spec.raw = {"output": {}}
    assert A.fade_out_video(Spec, src) == src             # no option: stream copy path unchanged
