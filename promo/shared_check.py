"""Shared gates for every project, whatever skill or platform (skills change the look, never the checks).

muted-hook     first on-screen text within 2.0 s (feeds autoplay muted)                       WARN
end-card-hold  the last caption / end card holds >= copy.end_card_min_s of the routed primary
               skill (default 1.5 s) with its text box unchanged; footage behind it may move FAIL
"""
import os

import yaml

HOOK_S, END_MIN_S = 2.0, 1.5


def end_card_min(spec):
    """copy.end_card_min_s from skills/<primary>/skill.yaml (skills.primary in promo.yaml), else 1.5 s."""
    pid = ((spec.raw.get("skills") or {}).get("primary") or "") if isinstance(spec.raw.get("skills"), dict) else ""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", str(pid), "skill.yaml")
    if pid and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            v = ((yaml.safe_load(f) or {}).get("copy") or {}).get("end_card_min_s")
        if v is not None:
            return pid, float(v)
    return pid or None, END_MIN_S


def _items(spec, ctx):
    """(text, global t0, global t1, box) per caption, clipped to its shot."""
    from .shots import get_type
    for s in spec.shots:
        for c in get_type(s.type).captions(ctx, s):
            if c["t0"] < s.dur:
                t1 = min(float(c.get("t1", s.dur)), s.dur)
                yield c["text"], s.t0 + c["t0"], s.t0 + t1, tuple(c["box"]) if c.get("box") is not None else None


def gates(spec, ctx):
    rows, items = [], list(_items(spec, ctx))
    first = min((t0 for _x, t0, _t1, _b in items), default=None)
    rows.append(("muted-hook", "PASS" if first is not None and first <= HOOK_S + 1e-9 else "WARN",
                 f"first on-screen text at {first:.2f}s (want <= {HOOK_S}s: feeds autoplay muted)" if first is not None else "no on-screen text at all"))
    pid, need = end_card_min(spec)
    if not items:
        rows.append(("end-card-hold", "FAIL", "no caption or end card"))
        return rows
    end = max(t1 for _x, _t0, t1, _b in items)
    text, t0, _t1, box = max(items, key=lambda i: (i[2], i[1]))
    # the hold starts at the latest moment the final text or its box changed (a different caption ending inside the hold)
    start = max([t0] + [b1 for x, _a, b1, b in items if b1 < end - 1e-6 and b1 > t0 and (x, b) != (text, box)])
    hold = end - start
    who = f" ({pid})" if pid else ""
    rows.append(("end-card-hold", "PASS" if hold >= need - 1e-6 else "FAIL",
                 f"final text {text!r} holds {hold:.2f}s unchanged to {end:.2f}s (want >= {need:g}s{who})"))
    return rows
