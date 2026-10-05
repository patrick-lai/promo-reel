import numpy as np
from PIL import Image

from promo.shots import brand as B


def test_mark_tile_has_lit_shade_and_ring_pixels():
    t = B.mark_tile(60)
    a = np.asarray(t)
    cols = {tuple(p[:3]) for p in a.reshape(-1, 4)[::97] if p[3] > 250}
    assert (255, 255, 255) in cols and (156, 149, 216) in cols and (216, 212, 250) in cols


def test_lockup_animates_and_is_resolution_independent():
    for W, H in ((480, 270), (960, 540)):
        early = B.lockup(W, H, 0.5, "commission-ai", [])
        late = B.lockup(W, H, 3.3, "commission-ai", [])
        assert early.size == (W, H) == late.size
        ea, la = np.asarray(early.split()[3]).sum(), np.asarray(late.split()[3]).sum()
        assert la > ea > 0                                  # mark first, then the letters, aura and rule fill in
    # the settled name sits centred horizontally (within 3% of the width)
    a = np.asarray(late.split()[3]).astype(float)
    cols = np.where(a[int(0.45 * H):int(0.58 * H)].sum(axis=0) > 40)[0]
    assert abs((cols.min() + cols.max()) / 2 / W - 0.5) < 0.03


def test_lockup_is_deterministic():
    a = np.asarray(B.lockup(480, 270, 1.4, "commission-ai", []))
    b = np.asarray(B.lockup(480, 270, 1.4, "commission-ai", []))
    assert (a == b).all()
