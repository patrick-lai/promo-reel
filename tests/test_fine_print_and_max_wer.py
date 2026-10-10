"""The dawn card's optional `fine_print` block (tiny dim text near the bottom, wrapped) and the per-line `max_wer` of the VO read-back gate."""
import os
import sys
from types import SimpleNamespace as NS

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import check  # noqa: E402
from promo.shots import get_type  # noqa: E402

TEXT = "Disclaimer. This is alpha software and all of the liability is yours. " * 10


def _ctx():
    return NS(OW=1920, OH=1080, spec=NS(style={}))


def test_fine_print_is_wrapped_small_and_near_the_bottom():
    dawn = get_type("dawn")
    layer, t_on = dawn._fine_print(_ctx(), NS(cfg=dict(fine_print=TEXT, fine_print_at=2.0)))
    assert t_on == 2.0 and layer.size == (1920, 1080)
    a = np.asarray(layer)[..., 3]
    ys, xs = np.nonzero(a)
    assert ys.size > 0
    assert xs.min() >= 0.09 * 1920 and xs.max() <= 0.91 * 1920            # wrapped to 80 % of the width, centred
    assert ys.min() >= 0.85 * 1080 and ys.max() <= 0.99 * 1080            # a block near the bottom
    rows = np.nonzero(a.max(axis=1))[0]
    assert (np.diff(rows) > 1).sum() >= 1                                  # more than one line
    assert ys.max() - ys.min() < 0.12 * 1080                               # and small: only a few lines of tiny type


def test_no_fine_print_key_means_no_layer():
    assert get_type("dawn")._fine_print(_ctx(), NS(cfg={})) is None


def test_a_vo_line_may_carry_its_own_max_wer():
    assert check.line_max_wer({"text": "x"}, 0.0) == 0.0
    assert check.line_max_wer({"text": "x", "max_wer": 0.7}, 0.0) == 0.7
