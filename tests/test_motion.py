"""promo/motion.py: the spring camera, accent envelopes and settling overlays behind the opt-in `motion:` block."""
import math
import os
import sys
from types import SimpleNamespace as NS

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import motion as M  # noqa: E402
from promo import render as R  # noqa: E402
from promo.overlays import build_overlays  # noqa: E402

FPS = 30
SFNS = "/System/Library/Fonts/SFNS.ttf"


def speeds(cam, total):
    p = np.array([cam(i / FPS) for i in range(int(total * FPS) + 1)])
    return np.linalg.norm(np.diff(p[:, :2], axis=0), axis=1) * FPS, p


def test_spring_camera_glides_through_an_interior_key():
    keys = [(0, 0.3, 0.5, 0.8), (1.5, 0.5, 0.5, 0.8), (3.0, 0.7, 0.5, 0.8)]
    v, p = speeds(M.spring_cam(keys, 3.0, FPS), 3.0)
    classic, _ = speeds(lambda t: R.cam_at([k + ("smooth",) for k in keys], t), 3.0)
    at_key = int(1.5 * FPS)
    assert classic[at_key - 1:at_key + 1].min() < 0.01, "the classic camera stops dead at the waypoint"
    assert v[at_key - 1:at_key + 1].min() > 0.08, "the spring camera keeps moving through it"
    assert abs(p[at_key, 0] - 0.5) < 0.01, "and still passes the key on time"
    assert abs(p[-1, 0] - 0.7) < 0.005 and v[-1] < 0.02, "it comes to rest on the last key"


def test_spring_camera_holds_and_pushes_in_log_width():
    keys = [(0, 0.5, 0.5, 1.0), (1.0, 0.5, 0.5, 1.0), (3.0, 0.5, 0.5, 0.25)]
    cam = M.spring_cam(keys, 3.0, FPS)
    assert all(abs(cam(t)[2] - 1.0) < 1e-3 for t in (0.0, 0.4, 0.7)), "a hold between equal keys stays put"
    ws = [cam(i / FPS)[2] for i in range(int(3.0 * FPS) + 1)]
    assert max(ws) <= 1.0, "the settle never widens the box past the widest key"
    t_half = next(i for i, w in enumerate(ws) if w <= 0.5) / FPS
    assert abs(t_half - 2.0) < 0.1, "half the zoom (geometric mean width) lands mid-move, so the push keeps one rate"


def test_burst_attacks_then_decays():
    assert M.burst(0) == 0 and M.burst(-0.1) == 0
    assert M.burst(0.002) < 0.01, "zero slope at onset: no one-frame pop"
    assert M.burst(M.PUNCH_RISE) == 1
    assert M.burst(0.5) < 0.2


@pytest.mark.skipif(not os.path.exists(SFNS), reason="needs the macOS system font")
def test_settling_overlays_stagger_rise_and_exit_by_fading_only():
    ctx = R.RenderContext(K=1, fps=FPS, font_path=SFNS, spec=NS(raw={}), seg_dir="/tmp")
    cfgs = [dict(type="caption", text="Plans land on the board", t=[1.0, 3.0]),
            dict(type="caption", text="Second line", cy=900, t=[1.0, 3.0])]
    a, b = build_overlays(ctx, cfgs, {"overlay": "settle"})
    assert b.alpha(1.03) == 0 < a.alpha(1.03), "the second caption enters after the first"

    def top(o, t):
        rows = np.asarray(o.apply(R.canvas(ctx), t))[..., 3].max(axis=1)
        return np.nonzero(rows > rows.max() / 2)[0][0]
    assert top(a, 1.05) > top(a, 2.0), "a caption rises into place"
    exit_alpha = [a.alpha(2.85 + i / FPS) for i in range(6)]
    assert exit_alpha == sorted(exit_alpha, reverse=True) and top(a, 2.95) == top(a, 2.0), "an exit only fades"
    plain = build_overlays(ctx, cfgs[:1])[0]
    assert math.isclose(plain.alpha(1.09), R.alpha_at(1.09, 1.0, 3.0)), "no motion block: the old linear fade"
