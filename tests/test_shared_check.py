"""Shared gates (promo/shared_check.py): muted-hook and end-card-hold, incl. the per-skill minimum."""
from types import SimpleNamespace as NS

from promo import shared_check as SC


def _run(mp, items, primary=None):
    mp.setattr(SC, "_items", lambda spec, ctx: iter(items))
    raw = {"skills": {"primary": primary}} if primary else {}
    return {g: (st, m) for g, st, m in SC.gates(NS(raw=raw), None)}


def test_end_card_hold_default_and_cinetic(monkeypatch):
    box = (100, 400, 900, 500)
    items = [("HOOK", 0.5, 3.0, box), ("commission-ai", 28.5, 30.0, box)]  # 1.5 s card over moving footage
    r = _run(monkeypatch, items)
    assert r["muted-hook"][0] == "PASS" and r["end-card-hold"][0] == "PASS"
    assert _run(monkeypatch, items, primary="cinetic")["end-card-hold"][0] == "FAIL"  # cinetic wants 2.0 s
    late = [("LATE", 2.5, 3.0, box), ("A", 28.0, 30.0, box), ("B", 28.0, 29.2, (0, 0, 1, 1))]  # second box changes until 29.2
    r = _run(monkeypatch, late)
    assert r["muted-hook"][0] == "WARN" and r["end-card-hold"][0] == "FAIL"
