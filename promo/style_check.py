"""`promo check` gates contributed by the style preset (see promo/styles.py). Each gate -> (gate, status, msg)."""
from __future__ import annotations

import re

from . import claims as C


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _is_ui(shot):
    return bool(shot.get("ui", True))


def run(spec):
    st = spec.style or {}
    preset = st.get("preset")
    if not preset:
        return []
    checks = set(st.get("checks") or [])
    out = []
    if preset == "anime-opening":
        out += anime_gates(spec, st, checks)
    if "shot-hold" in checks and preset != "anime-opening":
        m = st.get("pacing", {}).get("min_shot_s")
        bad = [f"shot {s.id} {s.dur:.2f}s < {m}s" for s in spec.shots if m and s.dur < m - 1e-6]
        out.append(("shot-hold", "FAIL" if bad else "PASS", "; ".join(bad) or f"every shot holds >= {m}s"))
    if "no-fx" in checks:
        bad = [s.id for s in spec.shots if any(s.get(k) for k in ("fx_in", "fx_out", "flash", "speed_lines"))]
        out.append(("no-fx", "FAIL" if bad else "PASS", f"flash / speed-line fx not allowed in {preset}: shots {bad}" if bad else "no flashes or speed lines"))
    return out


def anime_gates(spec, st, checks):
    from .shots.anime import bar_s, card_geometry, card_text, card_times, cam_keys, fx_list, layout_of, src_rect_to_out, viewport
    from .render import cam_at
    out = []
    pace, band = st["pacing"], st["band"]
    grid = spec.grid
    fps = spec.fps
    BAR = bar_s(spec)
    fr = 1.0 / fps
    qa = spec.qa

    # grid
    if "grid" in checks:
        if not grid:
            out.append(("grid", "FAIL", "anime-opening needs timeline.grid: <music analysis JSON> (tempo, beats, bars, markers)"))
        else:
            drift = grid.max_drift()
            msg = f"{grid.bpm:g} BPM, {len(grid.beats)} beats, {len(grid.bars)} bars ({grid.beats_per_bar}/bar, 1 bar = {BAR:.3f}s); max grid drift {drift * 1000:.1f} ms"
            out.append(("grid", "FAIL" if drift > fr / 2 else "PASS", msg))
    if not grid:
        class _G:                                                     # 4/4 fallback so the other gates still run
            beats_per_bar, offset, markers = 4, 0, {}

            def is_bar(self, beat, frac=1.0, tol=1e-6):
                x = beat / (4 * frac)
                return abs(x - round(x)) < tol
        grid = _G()

    shots = spec.shots
    # bar-cuts: internal cuts on bar lines; half-bar only next to a text-free shot
    if "bar-cuts" in checks:
        bad = []
        for a, b in zip(shots, shots[1:]):
            beat = a.b1
            if grid.is_bar(beat):
                continue
            if grid.is_bar(beat, 0.5) and (not _is_ui(a) or not _is_ui(b)):
                continue
            bad.append(f"cut {a.id}|{b.id} at beat {beat} ({spec.timeline.t(beat):.3f}s) is not on a bar line"
                       + ("" if grid.is_bar(beat, 0.5) else " or half bar") + (" (half-bar cuts need a text-free neighbour)" if grid.is_bar(beat, 0.5) else ""))
        for s in shots:
            for c in s.get("cards") or []:
                t0, _ = card_times(spec, s, c)
                gb = s.b0 + t0 / spec.timeline.B
                if pace.get("card_start") == "bar" and not grid.is_bar(gb, tol=1e-3):
                    bad.append(f"shot {s.id} card {card_text(spec, c)!r} starts at beat {gb:.2f}, not on a bar line")
        out.append(("bar-cuts", "FAIL" if bad else "PASS", "; ".join(bad) or f"{len(shots) - 1} cuts on bar lines (half bars only beside text-free shots); cards start on bars"))

    # shot-hold
    if "shot-hold" in checks:
        bad = []
        for s in shots[:-1] if len(shots) > 1 else shots:
            need = (pace["ui_min_bars"] if _is_ui(s) else pace["textfree_min_bars"]) * BAR
            if s.dur < need - fr:
                bad.append(f"shot {s.id} ({'UI' if _is_ui(s) else 'text-free'}) {s.dur:.2f}s < {need:.2f}s")
        for s in shots:
            if "ui" not in s.cfg:
                bad.append(f"shot {s.id}: set ui: true|false (drives hold, layout and fx rules)")
        out.append(("shot-hold", "FAIL" if bad else "PASS", "; ".join(bad) or
                    f"UI shots >= {pace['ui_min_bars']:g} bar ({pace['ui_min_bars'] * BAR:.2f}s), text-free >= {pace['textfree_min_bars']:g} bar"))

    # card-hold
    cards = [(s, c, card_text(spec, c)) for s in shots for c in (s.get("cards") or [])]
    if "card-hold" in checks:
        bad = []
        need = max(pace["card_min_bars"] * BAR, pace.get("word_min_s", 0.6))
        for s, c, text in cards:
            t0, t1 = card_times(spec, s, c)
            if t1 - t0 < need - fr:
                bad.append(f"shot {s.id} card {text!r} visible {t1 - t0:.2f}s < {need:.2f}s (1 bar, words >= {pace.get('word_min_s', 0.6)}s)")
        out.append(("card-hold", "FAIL" if bad else "PASS", "; ".join(bad) or f"{len(cards)} cards held >= {need:.2f}s (every word >= {pace.get('word_min_s', 0.6)}s)"))

    # card-band: one fixed band, no per-card positioning
    if "card-band" in checks:
        bad = []
        for s, c, text in cards:
            for k in ("x", "y", "cx", "cy", "size", "band"):
                if k in c:
                    bad.append(f"shot {s.id} card {text!r}: per-card '{k}' not allowed (one fixed band for the whole opening)")
            row = c.get("row", "title")
            if row not in band["rows"]:
                bad.append(f"shot {s.id} card {text!r}: unknown row {row!r} (have {sorted(band['rows'])})")
                continue
            b = card_geometry(spec, row, text)["box"]
            if not (b[0] >= band["x0"] - 1e-6 and b[2] <= band["x1"] + 1e-6 and b[1] >= band["y0"] - 1e-6 and b[3] <= band["y1"] + 1e-6):
                bad.append(f"shot {s.id} card {text!r} box {[round(x) for x in b]} leaves the band {[band['x0'], band['y0'], band['x1'], band['y1']]}")
        for s in shots:
            if s.get("band") or s.get("overlays"):
                bad.append(f"shot {s.id}: per-shot band / free overlays not allowed in anime-opening (use cards)")
        out.append(("card-band", "FAIL" if bad else "PASS", "; ".join(bad) or f"all cards in the fixed band y {band['y0']}-{band['y1']}"))

    # card-ui-clear: a card never covers app UI text
    if "card-ui-clear" in checks:
        bad, notes = [], []
        for s in shots:
            vp = viewport(spec, s)
            rects = s.get("ui_text") or []
            scs = [c for c in (s.get("cards") or [])]
            if _is_ui(s) and layout_of(s) == "full" and scs and not rects:
                bad.append(f"shot {s.id}: full-bleed UI shot with cards must list ui_text rects (or use layout: band)")
            if not scs:
                continue
            keys = cam_keys(s)
            src_size = _src_size(spec, s)
            for c in scs:
                text = card_text(spec, c)
                box = card_geometry(spec, c.get("row", "title"), text)["box"]
                if layout_of(s) == "band" and box[1] < vp[3] - 1e-6:
                    bad.append(f"shot {s.id} card {text!r} reaches into the footage viewport")
                t0, t1 = card_times(spec, s, c)
                n = max(2, int((t1 - t0) * fps))
                for r in rects:
                    for k in range(n + 1):
                        t = t0 + (t1 - t0) * k / n
                        m = src_rect_to_out(cam_at(keys, t), src_size, vp, r)
                        m = [max(m[0], vp[0]), max(m[1], vp[1]), min(m[2], vp[2]), min(m[3], vp[3])]   # only the visible part
                        if m[0] < m[2] and m[1] < m[3] and _overlap(m, box):
                            bad.append(f"shot {s.id} card {text!r} covers ui_text {r} at t={t:.2f}s")
                            break
            if rects:
                notes.append(s.id)
        out.append(("card-ui-clear", "FAIL" if bad else "PASS", "; ".join(bad) or
                    f"no card over app UI text (UI shots framed above the band; ui_text rects checked on shots {notes or 'none'})"))

    # fx-between: flashes / speed lines only at cuts, only allowed kinds, never over UI text
    flashes = []
    if "fx-between" in checks:
        bad = []
        allowed = set(st["transitions"]["allowed"])
        for s in shots:
            for k in ("flash", "speed_lines", "fx"):
                if s.get(k):
                    bad.append(f"shot {s.id}: '{k}' inside a shot is not allowed; use fx_in / fx_out (at the cut)")
            for key, fx in [(k, f) for k in ("fx_in", "fx_out") for f in fx_list(s, k)]:
                if fx.get("kind") not in allowed:
                    bad.append(f"shot {s.id} {key}: kind {fx.get('kind')!r} not in {sorted(allowed)}")
                frames = int(fx.get("frames", st["transitions"].get(fx.get("kind"), {}).get("frames", 3)))
                if frames > pace["fx_max_frames"]:
                    bad.append(f"shot {s.id} {key}: {frames} frames > {pace['fx_max_frames']} (fx belong to the cut, not the shot)")
                if fx.get("area") == "full" and _is_ui(s):
                    bad.append(f"shot {s.id} {key}: full-frame fx on a UI shot (would cover UI text)")
                if fx.get("kind") == "flash":
                    flashes.append(s.t0 if key == "fx_in" else s.t1)
        out.append(("fx-between", "FAIL" if bad else "PASS", "; ".join(bad) or
                    "fx only at cuts (fx_in/fx_out); on UI shots they draw in the band only, never over UI text"))
    else:
        flashes = [s.t0 if k == "fx_in" else s.t1 for s in shots for k in ("fx_in", "fx_out") for f in fx_list(s, k) if f.get("kind") == "flash"]

    if "flash-rate" in checks:
        flashes.sort()
        mx = pace.get("max_flashes_per_s", 3)
        worst = max((sum(1 for y in flashes if x - 1e-6 <= y < x + 1.0) for x in flashes), default=0)
        out.append(("flash-rate", "FAIL" if worst > mx else "PASS", f"{len(flashes)} flashes, max {worst} in any 1 s window (limit {mx})"))

    # claims: config-driven numbers + no literal digits without evidence
    if "claims" in checks:
        res = C.audit(spec.raw, spec.resolve)
        bad = [m for s_, m in res if s_ == "FAIL"]
        warn = [m for s_, m in res if s_ == "WARN"]
        info = [m for s_, m in res if s_ == "INFO"]
        for s, c, text in cards:
            if re.search(r"\d", text) and not c.get("text_from") and not c.get("evidence"):
                bad.append(f"shot {s.id} card {text!r} has a number: use text_from: claims.<table> or cite evidence:")
            if c.get("text_from"):
                try:
                    C.resolve(spec.raw, c["text_from"])
                except C.ClaimError as e:
                    bad.append(f"shot {s.id}: {e}")
        status = "FAIL" if bad else ("WARN" if warn else "PASS")
        out.append(("claims", status, "; ".join(bad + warn + info) or "no numeric claims"))

    # markers on cuts
    if "markers" in checks:
        want = qa.get("cut_markers") or []
        cuts = [s.t0 for s in shots] + [shots[-1].t1] if shots else []
        bad = []
        for m in want:
            t = (grid.markers or {}).get(m)
            if t is None:
                bad.append(f"marker {m!r} not in the grid JSON")
            elif min(abs(t - c) for c in cuts) > fr + 1e-6:
                bad.append(f"marker {m} at {t:.3f}s has no cut within 1 frame (nearest {min(cuts, key=lambda c: abs(c - t)):.3f}s)")
        out.append(("markers", "FAIL" if bad else "PASS", "; ".join(bad) or (f"cuts on markers: {', '.join(want)}" if want else "no cut_markers listed")))

    if "named" in checks:
        out += named_gates(spec)

    if "placeholders" in checks:
        ph = [f"{s.id}={s['placeholder'].get('id', s.id)}" for s in shots if s.get("placeholder")]
        out.append(("placeholders", "WARN" if ph else "PASS", f"placeholder slates still waiting on footage: {', '.join(ph)}" if ph else "no placeholders"))
    return out


def named_gates(spec):
    """named: FAIL if an element a card names renders under min_px (18 px cap height at 1080p) or is not fully in frame;
    named-upscale: WARN if its effective scale (output px / source px) is > 1.0 (soft text: use the DPR 2 take)."""
    from .shots.anime import measure_named
    res, up = [], []
    for s in spec.shots:
        if s.type != "anime":
            continue
        for el in s.get("named") or []:
            if el.get("t") is not None or el.get("at") is not None:
                ms = [measure_named(spec, s, el)]
            else:                    # no time given: the smallest it gets on screen (head, middle, last frame)
                ms = [measure_named(spec, s, el, t=t) for t in (0.0, s.dur / 2, s.dur - 1.0 / spec.fps)]
            errs = [x for x in ms if x.get("error")]
            m = errs[0] if errs else min(ms, key=lambda x: x["px"] if x["inside"] else -1)
            nm = m["name"]
            if m.get("error"):
                if s.get("placeholder"):
                    continue                 # measured once the real take replaces the slate
                res.append(f"!shot {s.id} {nm!r}: cannot measure ({m['error']})")
                continue
            res.append(("" if m["ok"] else "!") + f"shot {s.id} {nm!r} @ {m['t']:.2f}s: {m['src']} src px x{m['scale']:.2f} = {m['px']:.1f} px (min {m['min_px']})"
                       + ("" if m["inside"] else ", NOT fully in frame"))
            if m["scale"] > 1.0 + 1e-6:
                up.append(f"shot {s.id} {nm!r} x{m['scale']:.2f} ({s.get('source') or s.get('still')})")
    if not res:
        return [("named", "PASS", "no named elements listed")]
    bad = [m for m in res if m.startswith("!")]
    return [("named", "FAIL" if bad else "PASS", "; ".join(m.lstrip("!") for m in res)),
            ("named-upscale", "WARN" if up else "PASS",
             ("upscaled (effective scale > 1.0, soft text; swap in the DPR 2 take): " + "; ".join(up)) if up
             else "every named element at effective scale <= 1.0")]


def _src_size(spec, shot):
    from .shots.anime import viewport
    if shot.get("placeholder"):
        vp = viewport(spec, shot)
        return (vp[2] - vp[0], vp[3] - vp[1])        # slate is drawn at viewport size, camera = identity
    from . import footage as FT
    cid = shot.get("source") or shot.get("still")
    try:
        man = FT.load(spec)
        res = man[cid].get("resolution", "1920x1080")
        w, h = (int(x) for x in str(res).split("x"))
        return (w, h)
    except Exception:  # noqa: BLE001
        return (1920, 1080)
