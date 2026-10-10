"""A VO line may carry its own `db` offset on top of the global `mix.vo_line_lufs` levelling (quiet lines and loud lines)."""
from promo.mix import vo_line_gain_db


def test_vo_line_gain_levels_to_target_without_offset():
    assert vo_line_gain_db({}, {}, -20.0) == 4.0                      # default target -16 LUFS
    assert vo_line_gain_db({"vo_line_lufs": -18.0}, {}, -20.0) == 2.0


def test_vo_line_db_offsets_the_leveled_line():
    cfg = {"vo_line_lufs": -16.0}
    assert vo_line_gain_db(cfg, {"db": -6.0}, -20.0) == -2.0           # a quiet opening line: leveled, then 6 dB down
    assert vo_line_gain_db(cfg, {"db": 0}, -20.0) == 4.0
    assert vo_line_gain_db(cfg, {"db": 3}, -16.0) == 3.0
