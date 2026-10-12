"""Preset @2 pacing targets (docs/PRODUCT-DEFAULTS.md).

v1 presets stay in promo/styles.py unchanged. Version 2 deep-merges the targets below and adds the
gates in this module. Phrase sync is the default; a per-beat lock is `pacing.strict_beat: true`.
One shot may set `hold: planned` (7–12 s, max one per video) and is then exempt from the long-hold WARN.
"""
from __future__ import annotations

BEATS = ("hook", "problem", "demo", "payoff", "cta")
SHOT_BEATS = ("hook", "problem", "demo", "payoff", "ask")

# 60 s hero windows (lesson 3). Scaled to the master length by the planner.
HERO_WINDOWS = (
    ("hook", 0, 4),
    ("problem", 4, 20),
    ("demo", 20, 42),
    ("payoff", 42, 52),
    ("ask", 52, 60),
)

PLANNED_HOLD = dict(min_s=7.0, max_s=12.0, max_count=1)


def _pace(st):
    return (st or {}).get("pacing") or {}


def _window(pace):
    w = pace.get("planned_hold") or PLANNED_HOLD
    return float(w.get("min_s", 7)), float(w.get("max_s", 12)), int(w.get("max_count", 1))


def marked_holds(spec):
    return [s for s in spec.shots if (s.cfg or {}).get("hold") == "planned"]


def exempt_hold_ids(spec):
    """Shot ids whose `hold: planned` is the single in-window hold, so long-hold does not WARN them."""
    lo, hi, cap = _window(_pace(getattr(spec, "style", None)))
    marked = marked_holds(spec)
    if len(marked) > cap:
        return set()
    return {s.id for s in marked if lo - 1e-6 <= float(s.dur) <= hi + 1e-6}


def planned_hold_gate(spec, st):
    lo, hi, cap = _window(_pace(st))
    marked = marked_holds(spec)
    bad, warn = [], []
    if len(marked) > cap:
        bad.append(f"{len(marked)} shots marked hold: planned (max {cap} per video)")
    for s in marked:
        if float(s.dur) < lo - 1e-6 or float(s.dur) > hi + 1e-6:
            warn.append(f"shot {s.id} planned hold {float(s.dur):.2f}s outside {lo:g}–{hi:g}s (not exempt from long-hold)")
    status = "FAIL" if bad else ("WARN" if warn else "PASS")
    if marked and not bad and not warn:
        msg = f"shot {marked[0].id} hold: planned {float(marked[0].dur):.2f}s (exempt from long-hold)"
    else:
        msg = "; ".join(bad + warn) or "no planned hold"
    return ("planned-hold", status, msg)


def _rate(cuts, a, b):
    if b <= a + 1e-9:
        return 0.0
    return sum(1 for t in cuts if a - 1e-9 <= t < b) / (b - a)


def cut_rate_gate(spec, st):
    """WARN when a @2 cut-rate curve is missed. Fewer than 6 shots is not a curve yet (PASS)."""
    cr = _pace(st).get("cut_rate") or {}
    shots = list(spec.shots)
    if len(shots) < 6:
        return ("cut-rate", "PASS", f"{len(shots)} shots: too few for a cut-rate curve")
    t0 = float(shots[0].t0)
    total = float(shots[-1].t1) - t0
    if total <= 0:
        return ("cut-rate", "PASS", "no duration")
    cuts = [float(s.t0) for s in shots[1:]]
    msgs = []
    if "overall" in cr:
        lo, hi = (float(x) for x in cr["overall"])
        overall = (len(shots) - 1) / total
        if overall < lo - 1e-9 or overall > hi + 1e-9:
            msgs.append(f"overall {overall:.2f} cuts/s outside {lo:g}–{hi:g}")
        win = cr.get("montage_window") or [0.70, 0.87]
        mlo, mhi = (float(x) for x in (cr.get("montage") or [0.6, 0.8]))
        a, b = t0 + total * float(win[0]), t0 + total * float(win[1])
        mr = _rate(cuts, a, b)
        if mr + 1e-9 < mlo or mr > mhi + 1e-9:
            msgs.append(f"montage {mr:.2f} cuts/s outside {mlo:g}–{mhi:g} ({float(win[0]):.0%}–{float(win[1]):.0%} of runtime)")
    elif "peak" in cr:
        early = float(cr.get("early", 0.3))
        peak = float(cr.get("peak", 1.0))
        tol = float(cr.get("tol", 0.35))
        w = cr.get("peak_window") or [0.45, 0.67]
        er = _rate(cuts, t0, t0 + total * float(w[0]))
        pr = _rate(cuts, t0 + total * float(w[0]), t0 + total * float(w[1]))
        if abs(er - early) > tol + 1e-9:
            msgs.append(f"early {er:.2f} cuts/s off {early:g} ±{tol:g}")
        if abs(pr - peak) > tol + 1e-9:
            msgs.append(f"peak {pr:.2f} cuts/s off {peak:g} ±{tol:g} between {float(w[0]):.0%}–{float(w[1]):.0%}")
        med = cr.get("median_shot_s")
        if med:
            durs = sorted(float(s.dur) for s in shots)
            mid = durs[len(durs) // 2]
            if mid < float(med[0]) - 1e-9 or mid > float(med[1]) + 1e-9:
                msgs.append(f"median shot {mid:.2f}s outside {float(med[0]):g}–{float(med[1]):g}s")
        target = float(_pace(st).get("loudness_lufs", -14))
        web = next((m for m in ((getattr(spec, "raw", None) or {}).get("mix") or {}).get("masters") or [] if m.get("name") == "web"), None)
        if web is not None and abs(float(web.get("lufs", target)) - target) > 0.05:
            msgs.append(f"web master {web.get('lufs')} LUFS, target {target:g}")
    else:
        return ("cut-rate", "PASS", "no @2 cut-rate target on this preset")
    return ("cut-rate", "WARN" if msgs else "PASS", "; ".join(msgs) or "cut-rate curve inside the preset band")


def phrase_sync_gate(spec, st):
    """Phrase alignment is the default. With no phrase grid yet, that is a PASS (per-beat lock stays optional)."""
    pace = _pace(st)
    grid = getattr(spec, "grid", None)
    starts = list(grid.phrase_starts()) if grid is not None and hasattr(grid, "phrase_starts") else []
    loose = "per-beat lock is off" if pace.get("strict_beat") is False else "set pacing.strict_beat: true for a per-beat lock"
    if not starts:
        return ("phrase-sync", "PASS", f"phrase sync is the default; {loose}; no phrase grid yet")
    tol = float(grid.B) * 0.5
    cuts = [float(s.t0) for s in spec.shots]
    hit = [t for t in cuts if any(abs(t - p) <= tol + 1e-6 for p in starts)]
    if len(cuts) > 2 and len(hit) <= 1:
        return ("phrase-sync", "WARN", "no cut lands on a musical phrase (phrase sync is the default)")
    return ("phrase-sync", "PASS", f"{len(hit)} cuts on a phrase; {loose}")


def _overlay_texts(spec):
    out = []
    for s in spec.shots:
        for o in s.cfg.get("overlays") or []:
            if o.get("type") in ("caption", "text", "pill") and o.get("text"):
                t = float(s.t0) + float((o.get("t") or [0])[0])
                out.append((t, o.get("type"), o.get("size"), str(o["text"]), s.id))
        for c in s.cfg.get("cards") or []:
            if c.get("text"):
                out.append((float(s.t0), "card", c.get("size"), str(c["text"]), s.id))
    return out


def hero_open_gate(spec, st):
    pace = _pace(st)
    promise = float(pace.get("promise_by_s", 0.5))
    logo_at = float(pace.get("logo_after_s", 8))
    end_min = float(pace.get("end_card_min_s", 6))
    max_caps = int(pace.get("max_captions", 5))
    frac = pace.get("hero_word_frac") or [0.08, 0.15]
    warns = []
    for s in spec.shots:
        if s.cfg.get("logo") and float(s.t0) < logo_at - 1e-6:
            warns.append(f"shot {s.id} logo at {float(s.t0):.2f}s (logo may wait until {logo_at:g}s)")
    texts = _overlay_texts(spec)
    if texts:
        first = min(texts, key=lambda x: x[0])
        if first[0] > promise + 1e-6:
            warns.append(f"first on-screen text at {first[0]:.2f}s (promise by {promise:g}s)")
    else:
        warns.append(f"no on-screen promise by {promise:g}s")
    caps = [t for t in texts if t[1] == "caption"]
    if len(caps) > max_caps:
        warns.append(f"{len(caps)} captions (max {max_caps})")
    for _t, role, size, text, sid in texts:
        if role == "text" and size:
            f = float(size) / 1080.0
            if f < float(frac[0]) - 1e-9 or f > float(frac[1]) + 1e-9:
                warns.append(f"shot {sid} hero word {text!r} is {f:.0%} of the frame (want {float(frac[0]):.0%}–{float(frac[1]):.0%})")
    if spec.shots and float(spec.shots[-1].dur) + 1e-6 < end_min:
        warns.append(f"end card {float(spec.shots[-1].dur):.2f}s < {end_min:g}s")
    return ("hero-open", "WARN" if warns else "PASS", "; ".join(warns) or f"promise by {promise:g}s, logo may wait until {logo_at:g}s, end card >= {end_min:g}s")


def talk_pace_gate(spec, st):
    pace = _pace(st)
    every = pace.get("layout_every_s") or [5, 7]
    turn = float(pace.get("speaker_turn_max_s", 12))
    hold = pace.get("caption_hold_s") or [2.0, 4.5]
    lo, hi = float(every[0]), float(every[1])
    warns = []
    for s in spec.shots:
        if float(s.dur) < lo - 1e-6 or float(s.dur) > hi + 1e-6:
            warns.append(f"shot {s.id} {float(s.dur):.2f}s outside a {lo:g}–{hi:g}s layout change")
        sp = s.cfg.get("speaker_s")
        if sp is not None and float(sp) > turn + 1e-6:
            warns.append(f"shot {s.id} speaker turn {float(sp):.1f}s > {turn:g}s")
        for o in s.cfg.get("overlays") or []:
            if o.get("type") == "caption" and isinstance(o.get("t"), (list, tuple)) and len(o["t"]) >= 2:
                h = float(o["t"][1]) - float(o["t"][0])
                if h > 0 and (h < float(hold[0]) - 1e-6 or h > float(hold[1]) + 1e-6):
                    warns.append(f"shot {s.id} caption {h:.2f}s outside {float(hold[0]):g}–{float(hold[1]):g}s")
    wpm = pace.get("wpm") or [165, 180]
    jokes = pace.get("jokes_per_100s") or [4, 5]
    base = f"layouts every {lo:g}–{hi:g}s, speaker turns <= {turn:g}s, captions {float(hold[0]):g}–{float(hold[1]):g}s"
    targets = f" (targets, not measured here: {wpm[0]:g}–{wpm[1]:g} wpm, {jokes[0]:g}–{jokes[1]:g} jokes/100s, demo cue within {float(pace.get('demo_cue_s', 1)):g}s)"
    return ("talk-pace", "WARN" if warns else "PASS", ("; ".join(warns) + targets) if warns else base + targets)


def max_shots(preset, duration, pace):
    """Upper bound on shot-list rows from the @2 cut-rate curve. At least one row per beat."""
    cr = (pace or {}).get("cut_rate") or {}
    if preset == "livestream":
        every = float(((pace or {}).get("layout_every_s") or [5, 7])[0])
        rate = 1.0 / every if every else 0.2
    elif "overall" in cr:
        rate = float(cr["overall"][1])
    elif "peak" in cr:
        rate = float(cr["peak"])
    else:
        rate = 0.45
    return max(len(SHOT_BEATS), int(float(duration) * rate) + 1)


def cap_rows(rows, cap):
    """Keep at least one row of every beat, then extra rows up to `cap` (cap never drops a beat)."""
    if not rows:
        return []
    order = []
    for r in rows:
        if r["beat"] not in order:
            order.append(r["beat"])
    keep_n = max(int(cap), len(order))
    chosen = []
    seen = set()
    for r in rows:
        if r["beat"] not in seen:
            chosen.append(r)
            seen.add(r["beat"])
    for r in rows:
        if len(chosen) >= keep_n:
            break
        if r not in chosen:
            chosen.append(r)
    index = {id(r): i for i, r in enumerate(rows)}
    chosen.sort(key=lambda r: index[id(r)])
    return chosen
