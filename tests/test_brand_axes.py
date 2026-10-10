"""The brand lockup sets a variable font's axes by name: weight only on the Weight axis, the others stay at their default."""
from promo.shots.brand import axis_values

NEW_YORK = [dict(name=b"Optical Size", minimum=12, default=256, maximum=256), dict(name=b"Weight", minimum=400, default=400, maximum=1000),
            dict(name=b"GRAD", minimum=0, default=0, maximum=1)]


def test_grade_axis_keeps_its_default_not_the_weight():
    assert axis_values(NEW_YORK, px=160, wght=330) == [60, 400, 0]       # weight 330 clamps to the axis minimum; GRAD stays 0 (was 1: heavy)
    assert axis_values(NEW_YORK, px=160, wght=480) == [60, 480, 0]


def test_optical_size_follows_pixel_size_up_to_the_cap():
    assert axis_values(NEW_YORK, px=24, wght=400)[0] == 24
    assert axis_values(NEW_YORK, px=300, wght=400)[0] == 60
    assert axis_values(NEW_YORK, px=300, wght=400, opsz_cap=100)[0] == 100


def test_wght_only_font():
    assert axis_values([dict(name=b"wght", minimum=100, default=400, maximum=900)], px=50, wght=330) == [330]
