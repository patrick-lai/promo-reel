"""RenderContext.font finds a named weight whatever its spelling ('SemiBold' asked, 'Semibold' in the font): captions on the system font crashed the build."""
import os

import pytest
from PIL import ImageFont

from promo import render as R

SFNS = "/System/Library/Fonts/SFNS.ttf"


@pytest.mark.skipif(not os.path.exists(SFNS), reason="needs the macOS system font")
def test_a_weight_name_spelt_differently_still_resolves():
    ctx = R.RenderContext(K=1.0, fps=30, font_path=SFNS, font_fallbacks=[], caption={}, spec=None, seg_dir=".")
    semibold = ctx.font(32, b"SemiBold")
    assert isinstance(semibold, ImageFont.FreeTypeFont)
    assert ctx.font(32, "Semi Bold").getlength("Commission") == semibold.getlength("Commission")
    plain = ImageFont.truetype(SFNS, 32)
    plain.set_variation_by_name(b"Semibold")
    assert semibold.getlength("Commission") == plain.getlength("Commission")      # it picked the Semibold instance, not the default weight
