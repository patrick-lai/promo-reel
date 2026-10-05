import numpy as np
from PIL import Image

from promo import pane3d as P


def _ui(w=640, h=360):
    rng = np.random.default_rng(1)
    a = rng.integers(0, 255, (h, w, 3), np.uint8)
    return Image.fromarray(a, "RGB")


def test_face_is_only_warped_never_painted_over():
    """Frontal pane (no tilt, no float, settled): the interior equals the resampled source (UI pixels untouched by light/shadow/rim)."""
    ui = Image.fromarray(np.tile(np.linspace(0, 255, 480, dtype=np.uint8)[None, :, None], (270, 1, 3)), "RGB")
    cfg = dict(yaw=0, pitch=0, float_yaw=0, float_pitch=0, float_shift=0, persp=1000, w=0.6, cy=0.5, enter=0.01, radius=0)
    bd = Image.new("RGB", (960, 540), (20, 20, 40))
    out = np.asarray(P.compose(ui, bd, 3.0, 5.0, cfg, (960, 540))).astype(int)
    pw = int(0.6 * 960)
    x0, y0 = (960 - pw) // 2, (540 - int(pw * 270 / 480)) // 2
    ref = np.asarray(ui.resize((pw, int(pw * 270 / 480)), Image.LANCZOS)).astype(int)
    inner = (slice(y0 + 8, y0 + ref.shape[0] - 8), slice(x0 + 8, x0 + pw - 8))
    got = out[inner]
    want = ref[8:-8, 8:-8]
    assert np.abs(got - want).mean() < 3.0


def test_reveal_progresses_and_is_deterministic():
    bd = Image.new("RGB", (480, 270), (12, 14, 40))
    ui = _ui()
    a0 = np.asarray(P.compose(ui, bd, 0.05, 3.0, None, (480, 270))).astype(int)
    a1 = np.asarray(P.compose(ui, bd, 2.5, 3.0, None, (480, 270))).astype(int)
    base = np.asarray(bd).astype(int)
    assert np.abs(a0 - base).sum() < np.abs(a1 - base).sum()          # more pane on screen once revealed
    again = np.asarray(P.compose(ui, bd, 2.5, 3.0, None, (480, 270))).astype(int)
    assert (a1 == again).all()


def test_quad_matches_perspective_and_world_cached():
    q = P.project(400, 225, 960, 540, 480, 270, -11, 3, 0, 2.8)
    assert len(q) == 4 and q[0][0] < q[1][0] and q[0][1] < q[3][1]
    w1 = P.world(480, 270)
    w2 = P.world(480, 270)
    assert w1.size == (480, 270) and np.asarray(w1).tobytes() == np.asarray(w2).tobytes()
