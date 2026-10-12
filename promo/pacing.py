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
    chosen_ids = {id(r) for r in chosen}
    for r in rows:
        if len(chosen) >= keep_n:
            break
        if id(r) not in chosen_ids:
            chosen.append(r)
            chosen_ids.add(id(r))
    index = {id(r): i for i, r in enumerate(rows)}
    chosen.sort(key=lambda r: index[id(r)])
    return chosen


def _windows_from_edges(edges, duration):
    edges = [float(x) for x in edges]
    edges[0] = 0.0
    edges[-1] = float(duration)
    return [(SHOT_BEATS[i], edges[i], edges[i + 1]) for i in range(len(SHOT_BEATS))]


def beat_windows(preset, duration, pace=None):
    """(beat, start_s, end_s) across the master.

    Hero keeps the lesson-3 slots (hook 0–4, problem 4–20, demo 20–42, payoff 42–52, ask from 52).
    Anime-opening follows the @2 peak window (early, then ~1 cut/s between 45–67%). Livestream
    follows the 5–7 s layout cadence, with the opening bit inside the first ~15 s.
    """
    duration = float(duration)
    pace = pace or {}
    if preset == "livestream":
        windows, _counts = _live_plan(duration, pace)
        return windows
    if preset == "anime-opening":
        return _anime_windows(duration, pace)
    return _hero_windows(duration)


def _hero_windows(duration):
    scale = float(duration) / 60.0
    edges = [0.0]
    for _beat, _a, b in HERO_WINDOWS:
        edges.append(b * scale)
    return _windows_from_edges(edges, duration)


def _anime_windows(duration, pace):
    """Five beats aligned to the peak cut-rate curve, not the hero slots.

    Hook and problem sit in the early section, demo is the peak window, payoff and ask come down after it.
    """
    cr = (pace or {}).get("cut_rate") or {}
    w0, w1 = [float(x) for x in (cr.get("peak_window") or [0.45, 0.67])]
    w0 = min(max(w0, 0.08), 0.8)
    w1 = min(max(w1, w0 + 0.05), 0.95)
    hook_end = w0 * 0.30
    payoff_end = w1 + (1.0 - w1) * 0.55
    return _windows_from_edges([0.0, hook_end * duration, w0 * duration, w1 * duration, payoff_end * duration, duration], duration)


def _live_plan(duration, pace):
    """(windows, per-beat shot counts) on the layout cadence. Fast end of the 5–7 s band, toward the cap."""
    lo, hi = [float(x) for x in ((pace or {}).get("layout_every_s") or [5.0, 7.0])]
    lo = max(lo, 0.1)
    hi = max(hi, lo)
    bit = float((pace or {}).get("bit_by_s") or 15.0)
    n_beats = len(SHOT_BEATS)
    if duration < lo * n_beats - 1e-9:
        span = duration / n_beats
        windows, t = [], 0.0
        for beat in SHOT_BEATS:
            windows.append((beat, t, t + span))
            t += span
        windows[-1] = (windows[-1][0], windows[-1][1], float(duration))
        return windows, [1] * n_beats
    n = max(n_beats, int(duration // lo))
    while duration / n > hi + 1e-6:
        n += 1
    step = duration / n
    hook_n = int(round(min(bit, duration) / step)) if step else 1
    hook_n = max(1, min(hook_n, n - (n_beats - 1)))
    rest = n - hook_n
    slots = n_beats - 1
    base, extra = divmod(rest, slots)
    counts = [hook_n] + [base + (1 if i < extra else 0) for i in range(slots)]
    windows, t = [], 0.0
    for beat, c in zip(SHOT_BEATS, counts):
        windows.append((beat, t, t + step * c))
        t += step * c
    windows[-1] = (windows[-1][0], windows[-1][1], float(duration))
    return windows, counts


def _rate_count(span, rate, min_s):
    """How many shots of about `1/rate` seconds fit in `span`, each at least `min_s`."""
    if span <= 1e-9:
        return 1
    target = 1.0 / rate if rate > 1e-9 else span
    n = max(1, int(span / target + 0.5))
    if min_s > 1e-9:
        n = min(n, max(1, int(span / min_s + 1e-9)))
    return max(1, n)


def _hero_counts(windows, pace):
    """Shot counts inside the hero slots. Overall band at its fast edge; montage on the payoff; end card held."""
    cr = (pace or {}).get("cut_rate") or {}
    overall = float((cr.get("overall") or [0.35, 0.45])[1])
    montage = float((cr.get("montage") or [0.6, 0.8])[1])
    end_min = float((pace or {}).get("end_card_min_s") or 6.0)
    card_min = float(((pace or {}).get("card_hold_s") or [2.0, 3.0])[0])
    montage_min = 1.0 / montage if montage else card_min
    counts = []
    for beat, a, b in windows:
        span = b - a
        if beat == "ask":
            n = 1 if span < end_min * 2 - 1e-9 else max(1, int(span // end_min))
        elif beat == "payoff":
            n = _rate_count(span, montage, montage_min)
        else:
            n = _rate_count(span, overall, card_min)
        counts.append(n)
    return counts


def _anime_counts(windows, duration, pace):
    """Early ~0.3 cuts/s, peak ~1.0 inside the peak window, early again after it."""
    cr = (pace or {}).get("cut_rate") or {}
    early = float(cr.get("early", 0.3))
    peak = float(cr.get("peak", 1.0))
    w0, w1 = [float(x) for x in (cr.get("peak_window") or [0.45, 0.67])]
    counts = []
    for _beat, a, b in windows:
        mid = ((a + b) / 2.0) / duration if duration else 0.0
        rate = peak if w0 - 1e-9 <= mid < w1 else early
        target = 1.0 / rate if rate else (b - a)
        # A little under the target still counts: rounding a short tail up by one shot
        # lands just below 1/rate and should not be clipped back to a much longer hold.
        counts.append(_rate_count(b - a, rate, target * 0.75))
    return counts


def _min_shot_s(preset, beat, pace):
    """Shortest shot the expander may create while pushing a filled beat toward the cap."""
    pace = pace or {}
    if preset == "livestream":
        return float((pace.get("layout_every_s") or [5.0, 7.0])[0])
    if preset == "anime-opening":
        cr = pace.get("cut_rate") or {}
        # demo is the peak window (see _anime_windows); the other beats stay on the early rate
        rate = float(cr.get("peak", 1.0) if beat == "demo" else cr.get("early", 0.3))
        if rate <= 0:
            return 0.5
        return 1.0 / rate
    if beat == "ask":
        return float(pace.get("end_card_min_s") or 6.0)
    if beat == "payoff":
        montage = float(((pace.get("cut_rate") or {}).get("montage") or [0.6, 0.8])[1])
        return 1.0 / montage if montage else 1.0
    return float((pace.get("card_hold_s") or [2.0, 3.0])[0])


def _expand_toward_cap(preset, windows, counts, duration, pace, filled):
    """Add shots on filled beats until the cap or the preset's shortest legal shot. Never split an empty beat."""
    cap = max_shots(preset, float(duration), pace)
    counts = list(counts)
    beats = [b for b, _a, _b in windows]
    spans = [b - a for _beat, a, b in windows]
    filled = set(filled)
    guard = 0
    while sum(counts) < cap and guard < 80:
        guard += 1
        best = None
        for i, n in enumerate(counts):
            if beats[i] not in filled or n < 1:
                continue
            nxt = spans[i] / (n + 1)
            if nxt + 1e-9 < _min_shot_s(preset, beats[i], pace):
                continue
            cur = spans[i] / n
            if best is None or cur > best[0]:
                best = (cur, i)
        if best is None:
            break
        counts[best[1]] += 1
    while sum(counts) > cap:
        i = max(range(len(counts)), key=lambda k: (counts[k], spans[k]))
        if counts[i] <= 1:
            break
        counts[i] -= 1
    return counts


def _split_span(span, n):
    n = max(1, int(n))
    if n == 1:
        return [float(span)]
    each = float(span) / n
    return [each] * n


def _round_parts(lengths, total):
    """Round each part to 0.01 s so the parts sum to `total` (largest remainder, cents)."""
    if not lengths:
        return []
    cents = int(round(round(float(total), 2) * 100))
    raw = [max(0.0, float(s)) for s in lengths]
    whole = sum(raw)
    if whole <= 1e-9:
        base, rem = divmod(cents, len(raw))
        return [(base + (1 if i < rem else 0)) / 100.0 for i in range(len(raw))]
    exact = [s / whole * cents for s in raw]
    alloc = [int(x) for x in exact]
    left = cents - sum(alloc)
    order = sorted(range(len(raw)), key=lambda i: (exact[i] - alloc[i], -i), reverse=True)
    for i in order[:max(0, left)]:
        alloc[i] += 1
    return [a / 100.0 for a in alloc]


def _retotal(pairs, duration):
    """Round each row to 0.01 s so the rows still sum to the master."""
    if not pairs:
        return []
    lengths = _round_parts([s for _b, s in pairs], duration)
    return [(b, s) for (b, _s), s in zip(pairs, lengths)]


def plan_shots(preset, duration, pace, filled):
    """(skeleton, expanded) as lists of (beat, seconds).

    The skeleton is one row per beat (the five-beat structure). Filled beats are then split toward the
    preset's @2 cut-rate cap, down to that preset's shot-length floor. An empty labelled beat stays one
    row so the beat line, not this list, is what blocks `--final`.
    """
    duration = float(duration)
    pace = pace or {}
    filled = set(filled if filled is not None else SHOT_BEATS)
    if preset == "livestream":
        windows, counts = _live_plan(duration, pace)
    elif preset == "anime-opening":
        windows = _anime_windows(duration, pace)
        counts = _anime_counts(windows, duration, pace)
    else:
        windows = _hero_windows(duration)
        counts = _hero_counts(windows, pace)
    counts = [1 if beat not in filled else n for (beat, _a, _b), n in zip(windows, counts)]
    counts = _expand_toward_cap(preset, windows, counts, duration, pace, filled)
    skeleton = _retotal([(beat, b - a) for beat, a, b in windows], duration)
    expanded = []
    for (beat, seconds), n in zip(skeleton, counts):
        expanded.extend((beat, length) for length in _round_parts(_split_span(seconds, n), seconds))
    return skeleton, expanded
