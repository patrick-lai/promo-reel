"""`promo check` gates contributed by the style preset (see promo/styles.py). Each gate -> (gate, status, msg)."""
from __future__ import annotations

import os
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
    if preset == "cinematic-story":
        out += cinema_gates(spec, st, checks)
    if preset == "horizon":
        out += horizon_gates(spec, st, checks)
    if "shot-hold" in checks and preset != "anime-opening":
        m = st.get("pacing", {}).get("min_shot_s")
        bad = [f"shot {s.id} {s.dur:.2f}s < {m}s" for s in spec.shots if m and s.dur < m - 1e-6]
        out.append(("shot-hold", "FAIL" if bad else "PASS", "; ".join(bad) or f"every shot holds >= {m}s"))
    if "no-fx" in checks:
        bad = [s.id for s in spec.shots if any(s.get(k) for k in ("fx_in", "fx_out", "flash", "speed_lines"))]
        out.append(("no-fx", "FAIL" if bad else "PASS", f"flash / speed-line fx not allowed in {preset}: shots {bad}" if bad else "no flashes or speed lines"))
    return out


def cinema_gates(spec, st, checks):
    """cinematic-story gates. FAIL (hard): non-cinema shots / pills, UI-protection, UI hold, copy hold / clear / claims.
    WARN (soft): cut-rate curve, camera speed, fades at both ends, serif font fallback, ineffective look keys."""
    import math

    from . import grade as GR
    from .shots import cinema as CN
    out = []
    pace = st["pacing"]
    fps = spec.fps
    fr = 1.0 / fps
    shots = spec.shots
    cs = [s for s in shots if s.type in ("cinema", "screen")]      # `screen` = the UI on a generated plate's monitor (promo/shots/screen.py)
    ss = [s for s in shots if s.type == "screen"]
    hold_min = float(pace.get("min_caption_hold_s", 2.0))
    ui_min = float(pace.get("ui_min_hold_s", 2.5))

    if "cinema-keys" in checks:
        bad = [f"shot {s.id}: type {s.type!r} (cinematic-story renders `cinema` and `screen` shots)" for s in shots if s.type not in ("cinema", "screen")]
        bad += [f"shot {s.id}: overlays / pills are not rendered on cinema shots (use lower_copy / title_bloom)" for s in cs if s.get("overlays")]
        bad += [f"shot {s.id}: type screen needs plate: <footage clip id of the generated plate> and a UI source" for s in ss
                if not s.get("plate") or not (s.get("source") or s.get("segs"))]
        bad += [f"shot {s.id}: title_bloom on a screen shot (the UI is on screen; use lower_copy)" for s in ss if s.get("title_bloom")]
        out.append(("cinema-keys", "FAIL" if bad else "PASS", "; ".join(bad) or
                    f"{len(cs)} cinema / screen shots ({len(ss)} screen), no pill overlays"))

    if "ui-hold" in checks:
        bad = [f"shot {s.id} shows UI for {s.dur:.2f}s < {ui_min}s (style.pacing.ui_min_hold_s)" for s in cs if CN.is_ui(s) and s.dur < ui_min - fr]
        n = sum(1 for s in cs if CN.is_ui(s))
        out.append(("ui-hold", "FAIL" if bad else "PASS", "; ".join(bad) or f"{n} UI shots hold >= {ui_min}s (style.pacing.ui_min_hold_s)"))

    if "ui-hold-short" in checks:                  # a short UI shot with a moving camera is unreadable: WARN
        short_s = float(pace.get("ui_short_hold_s", 2.0))
        mr = pace.get("max_camera_rate") or {}
        mz, mp = float(mr.get("zoom", 0.25)), float(mr.get("pan", 0.10))
        warn = []
        for s in cs:
            if not CN.is_ui(s) or s.dur >= short_s - fr:
                continue
            z, p = CN.camera_rates(s)
            if z > mz + 1e-9 or p > mp + 1e-9:
                warn.append(f"shot {s.id} shows UI for only {s.dur:.2f}s < {short_s:g}s while the camera moves (zoom {z:.2f}/s, pan {p:.2f}/s; max {mz:g} / {mp:g}): hold the camera still or lengthen the shot")
        out.append(("ui-hold-short", "WARN" if warn else "PASS", "; ".join(warn) or f"no UI shot under {short_s:g}s has a camera move over the slow limit"))

    if "ui-protect" in checks:
        bad, warn = [], []
        for s in cs:
            if not CN.is_ui(s):
                continue
            look = CN.look_of(spec, s)
            if not look.get("protect_ui", True):
                bad.append(f"shot {s.id}: look.protect_ui is false on a UI shot (grade / grain would touch UI pixels; never edit the app's UI)")
            vig = look.get("vignette")
            g = float(vig.get("global", 0) or 0) if isinstance(vig, dict) else 0.0
            if g > GR.MAX_GLOBAL_VIGNETTE + 1e-9:
                bad.append(f"shot {s.id}: global vignette {g:g} > {GR.MAX_GLOBAL_VIGNETTE} (it darkens UI pixels near the edges)")
            elif g > 0:
                warn.append(f"shot {s.id}: global vignette {g:g} also darkens UI pixels near the panel edges")
            if s.type == "screen":                 # no panel / backdrop: the plate is the world (screen-ui audits the rest)
                continue
            if not CN.has_panel(look):
                ign = [k for k in ("grade", "bloom", "grain") if G_enabled((s.get("look") or {}).get(k)) and (s.get("look") or {}).get(k) is not None]
                if ign and look.get("protect_ui", True):
                    warn.append(f"shot {s.id}: full-bleed UI shot, so look.{'/'.join(ign)} is ignored (protect_ui); use backdrop: dof")
            bc = CN.backdrop_cfg(look)
            if bc["plate"] and CN.has_panel(look) and CN.load_plate(spec, bc["plate"], bc["t"]) is None:
                warn.append(f"shot {s.id}: look.backdrop.plate {bc['plate']!r} cannot be read (not a clip id in the footage manifest or an image / video path); "
                            "falling back to the blurred copy of the UI")
            d = look["panel"]
            if not (0.3 <= float(d["w"]) <= CN.MAX_PANEL_W):
                warn.append(f"shot {s.id}: panel.w {d['w']} outside 0.30-{CN.MAX_PANEL_W} (rendered at most {CN.MAX_PANEL_W})")
        n = sum(1 for s in cs if CN.is_ui(s))
        out.append(("ui-protect", "FAIL" if bad else ("WARN" if warn else "PASS"), "; ".join(bad + warn) or
                    f"{n} UI shots: look on the backdrop only (UI pixels untouched; fades aside), global vignette <= {GR.MAX_GLOBAL_VIGNETTE}"))

    if ss and "screen-quad" in checks:
        out.append(_screen_quad_gate(spec, ss))
    if ss and "screen-ui" in checks:
        out.append(_screen_ui_gate(spec, ss, cs))

    items = []          # (shot, kind, text, t0, t1)
    for s in cs:
        tc = CN.title_cfg(s)
        if tc:
            items.append((s, "title", tc["text"], float(tc.get("at", 0.5)), float(tc.get("at", 0.5)) + float(tc.get("dur", 3.0)), tc))
        for c in CN.copy_items(s):
            items.append((s, "copy", CN.copy_text(spec, c), float(c.get("at", 0.0)), float(c.get("at", 0.0)) + float(c.get("dur", 3.0)), c))

    if "copy-hold" in checks:
        bad = []
        for s, kind, text, t0, t1, _ in items:
            vis = min(t1, s.dur) - t0
            if vis < hold_min - fr:
                bad.append(f"shot {s.id} {kind} {text!r} visible {vis:.2f}s < {hold_min}s")
        out.append(("copy-hold", "FAIL" if bad else "PASS", "; ".join(bad) or f"{len(items)} title / copy lines visible >= {hold_min}s"))

    if "copy-clear" in checks:
        bad = []
        for s, kind, text, t0, t1, c in items:
            if kind == "title":
                if CN.is_ui(s):
                    bad.append(f"shot {s.id} title {text!r} would sit on app UI (title_bloom belongs on a ui: false shot or dark plate)")
                continue
            if s.type == "screen":
                from .shots import screen as SCR
                box = CN.copy_box(spec, SCR.text_shot(s), c, (1920, 1080), text=text)
                if box[0] < 0 or box[2] > 1920 or box[1] < 0 or box[3] > 1080:
                    bad.append(f"shot {s.id} copy {text!r} leaves the frame {[round(v) for v in box]}")
                ub = SCR.union_box(spec, s)
                if ub and _overlap(box, ub):
                    bad.append(f"shot {s.id} copy {text!r} box {[round(v) for v in box]} overlaps the monitor {[round(v) for v in ub]} (the UI is on it)")
                continue
            box = CN.copy_box(spec, s, c, (1920, 1080), text=text)
            if box[0] < 0 or box[2] > 1920 or box[1] < 0 or box[3] > 1080:
                bad.append(f"shot {s.id} copy {text!r} leaves the frame {[round(v) for v in box]}")
            if CN.is_ui(s):
                pb = CN.panel_box_of(spec, s)
                if pb is None:
                    bad.append(f"shot {s.id} copy {text!r} over a full-bleed UI shot (use look.backdrop: dof so copy sits in the margin)")
                elif _overlap(box, pb):
                    bad.append(f"shot {s.id} copy {text!r} box {[round(v) for v in box]} overlaps the UI panel {list(pb)}")
        out.append(("copy-clear", "FAIL" if bad else "PASS", "; ".join(bad) or "no title / copy over app UI (copy sits in the margin under the panel)"))

    if "copy-size" in checks:
        warn = []
        for s, kind, text, t0, t1, c in items:
            v = c.get("size")
            if v is not None and CN.LEGACY_PX_ABOVE >= float(v) > CN.MAX_SIZE_MULT:
                warn.append(f"shot {s.id} {kind} {text!r} size {float(v):g} > {CN.MAX_SIZE_MULT:g} (multiplier, clamped to {CN.MAX_SIZE_MULT:g})")
        out.append(("copy-size", "WARN" if warn else "PASS", "; ".join(warn) or f"{len(items)} title / copy lines within the {CN.MAX_SIZE_MULT:g}x size cap"))

    if "claims" in checks:
        res = C.audit(spec.raw, spec.resolve)
        bad = [m for s_, m in res if s_ == "FAIL"]
        warn = [m for s_, m in res if s_ == "WARN"]
        info = [m for s_, m in res if s_ == "INFO"]
        for s, kind, text, t0, t1, c in items:
            if re.search(r"\d", text) and not c.get("text_from") and not c.get("evidence"):
                bad.append(f"shot {s.id} {kind} {text!r} has a number: use text_from: claims.<table> or cite evidence:")
            if c.get("text_from"):
                try:
                    C.resolve(spec.raw, c["text_from"])
                except C.ClaimError as e:
                    bad.append(f"shot {s.id}: {e}")
        out.append(("claims", "FAIL" if bad else ("WARN" if warn else "PASS"), "; ".join(bad + warn + info) or "no numeric claims"))

    if "cut-curve" in checks:
        cr = pace.get("cut_rate") or {}
        tg, tol = list(cr.get("thirds") or [0.3, 0.6, 0.3]), float(cr.get("tol", 0.2))
        total = shots[-1].t1 if shots else 0.0
        if len(shots) < 6 or total <= 0:
            out.append(("cut-curve", "PASS", f"{len(shots)} shots: too few for a cut-rate curve"))
        else:
            n = len(tg)
            cnt = [0] * n
            for s in shots[1:]:
                cnt[min(n - 1, int(s.t0 / total * n + 1e-9))] += 1
            rates = [c * n / total for c in cnt]
            off = [f"part {i + 1}/{n} {r:.2f} cuts/s (target {t:g} +-{tol:g})" for i, (r, t) in enumerate(zip(rates, tg)) if abs(r - t) > tol + 1e-9]
            out.append(("cut-curve", "WARN" if off else "PASS", "cut rate off the calm -> busier -> calm curve: " + "; ".join(off) if off else
                        "cut rate " + " -> ".join(f"{r:.2f}" for r in rates) + f" cuts/s (target {' -> '.join(f'{t:g}' for t in tg)})"))

    if "slow-camera" in checks:
        mr = pace.get("max_camera_rate") or {}
        mz, mp = float(mr.get("zoom", 0.25)), float(mr.get("pan", 0.10))
        warn = []
        for s in cs:
            if not (s.get("cam") or CN.DEFAULT_CAM):
                continue
            ks = CN.camera_keys(s)
            for (t0, x0, y0, w0, *_), (t1, x1, y1, w1, *_) in zip(ks, ks[1:]):
                dt = max(t1 - t0, 1e-6)
                z, p = abs(math.log(max(w1, 1e-6) / max(w0, 1e-6))) / dt, math.hypot(x1 - x0, y1 - y0) / dt
                if z > mz + 1e-9 or p > mp + 1e-9:
                    warn.append(f"shot {s.id} camera {t0:g}-{t1:g}s zoom {z:.2f}/s pan {p:.2f}/s (max {mz:g} / {mp:g}): not a slow move")
        out.append(("slow-camera", "WARN" if warn else "PASS", "; ".join(warn) or "camera moves are slow (zoom and pan rates within limits)"))

    if "fades" in checks:
        warn = []
        if cs and not float(cs[0].get("fade_in", 0) or 0):
            warn.append(f"first shot {cs[0].id} has no fade_in (cinematic-story opens from black)")
        if cs and not float(cs[-1].get("fade_out", 0) or 0):
            warn.append(f"last shot {cs[-1].id} has no fade_out (it ends to black)")
        warn += [f"shot {s.id} fade {max(float(s.get('fade_in', 0) or 0), float(s.get('fade_out', 0) or 0)):g}s longer than half the shot"
                 for s in cs if max(float(s.get("fade_in", 0) or 0), float(s.get("fade_out", 0) or 0)) > s.dur / 2 + 1e-9]
        out.append(("fades", "WARN" if warn else "PASS", "; ".join(warn) or "opens from black, ends to black"))

    if "serif-font" in checks:
        p = CN.serif_path(spec)
        need = bool(items)
        out.append(("serif-font", "WARN" if (need and not p) else "PASS",
                    "no serif font found (style.typography.serif_fonts); copy falls back to the UI font" if (need and not p) else
                    f"serif font: {p}" if p else "no title / copy"))
    return out


def _screen_quad_gate(spec, ss):
    """screen-quad: FAIL when the tracked monitor is cut off by the frame border (a corner within 2 px of it) in more than 10 % of a
    shot's frames, or when the detection fails in more than 15 %; WARN when frames were held or the screen is small."""
    from . import screentrack as ST
    from .shots import screen as SCR
    bad, warn, ok = [], [], []
    for s in ss:
        if not s.get("plate"):
            continue
        tr = SCR.track_of(spec, s)
        if tr is None:
            warn.append(f"shot {s.id}: plate {s.get('plate')!r} cannot be read, so the monitor was not tracked")
            continue
        if not tr.usable:
            bad.append(f"shot {s.id}: no monitor found in the plate ({'; '.join(tr.why) or 'no detection'}); tune screen.thr / screen.sat_max or set screen.quad")
            continue
        if tr.fail_frac > ST.FAIL_FRAC_MAX + 1e-9:
            bad.append(f"shot {s.id}: monitor detection failed on {100 * tr.fail_frac:.0f}% of the frames (max {int(ST.FAIL_FRAC_MAX * 100)}%): "
                       f"{'; '.join(tr.why) or 'no detection'}; tune screen.thr / screen.sat_max or set screen.quad")
        elif tr.fail_frac > 0:
            warn.append(f"shot {s.id}: monitor detection failed on {100 * tr.fail_frac:.0f}% of the frames (the previous quad is held)")
        if tr.touch_frac > ST.TOUCH_FRAC_MAX + 1e-9:
            bad.append(f"shot {s.id}: the monitor touches the frame border on {100 * tr.touch_frac:.0f}% of the frames (max {int(ST.TOUCH_FRAC_MAX * 100)}%): "
                       "it is cut off by the frame, so the UI would be cropped; regenerate the plate with the whole monitor in frame")
        w = float(np_median_width(tr))
        if w < 0.30:
            warn.append(f"shot {s.id}: the monitor is only {100 * w:.0f}% of the frame wide: the UI will be small (legibility)")
        ok.append(f"{s.id} {100 * tr.fail_frac:.0f}% failed / {100 * tr.touch_frac:.0f}% cut off")
    return ("screen-quad", "FAIL" if bad else ("WARN" if warn else "PASS"),
            "; ".join(bad + warn) or f"{len(ss)} screen shots: monitor tracked inside the frame (" + ", ".join(ok) + ")")


def np_median_width(tr):
    import numpy as np
    q = tr.quads
    return float(np.median((q[:, 1, 0] - q[:, 0, 0] + q[:, 2, 0] - q[:, 3, 0]) / 2.0)) if len(q) else 0.0


def _screen_ui_gate(spec, ss, cs):
    """screen-ui: the UI inside the monitor quad is only RESAMPLED. FAIL on a `screen:` key that could edit it, on look.protect_ui false, and
    on a rendered interior that differs from the resampled UI (the renderer measures it on pre-encode frames into <seg>.screen.json)."""
    from .shots import cinema as CN
    from .shots import screen as SCR
    bad, rendered, missing = [], [], []
    for s in ss:
        bad += SCR.audit_screen_keys(s)
        if not CN.look_of(spec, s).get("protect_ui", True):
            bad.append(f"shot {s.id}: look.protect_ui is false on a screen shot")
        sc = SCR.read_sidecar(spec, s)
        if sc is None:
            missing.append(s.id)
        elif int(sc.get("ui_residual_max", 0)) > 0:
            bad.append(f"shot {s.id}: the rendered monitor interior differs from the resampled UI by up to {sc['ui_residual_max']} levels "
                       f"({sc.get('ui_residual_frames', 0)} frames checked): the UI must only be resampled")
        else:
            rendered.append(f"{s.id} ({sc.get('ui_residual_frames', 0)} frames)")
    msg = (f"{len(ss)} screen shots: UI inside the monitor only resampled (crop + perspective warp); grade / grain / bezel / spill on the plate only"
           + (f"; rendered interior == resampled UI on {', '.join(rendered)}" if rendered else "")
           + (f"; not rendered yet: {', '.join(missing)}" if missing else ""))
    return ("screen-ui", "FAIL" if bad else "PASS", "; ".join(bad) or msg)


def G_enabled(block):
    from . import grade as GR
    return GR.enabled(block)


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
            g = card_geometry(spec, row, text)
            b = g["box"]
            cap = g["font"].getbbox("H")[3] - g["font"].getbbox("H")[1]
            if cap < band.get("min_cap_px", 18):
                bad.append(f"shot {s.id} card {text!r} ({row}) cap height {cap} px < {band.get('min_cap_px', 18)} px")
            if not (b[0] >= band["x0"] - 1e-6 and b[2] <= band["x1"] + 1e-6 and b[1] >= band["y0"] - 1e-6 and b[3] <= band["y1"] + 1e-6):
                bad.append(f"shot {s.id} card {text!r} box {[round(x) for x in b]} leaves the band {[band['x0'], band['y0'], band['x1'], band['y1']]}")
        for s in shots:
            if s.get("band") or s.get("overlays"):
                bad.append(f"shot {s.id}: per-shot band / free overlays not allowed in anime-opening (use cards)")
        out.append(("card-band", "FAIL" if bad else "PASS", "; ".join(bad) or f"all cards in the fixed band y {band['y0']}-{band['y1']} ({1080 - band['y0']} px = {(1080 - band['y0']) / 10.8:.0f}% of the frame), cap height >= {band.get('min_cap_px', 18)} px"))

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
            m = errs[0] if errs else min(ms, key=lambda x: x["px"] if (x["inside"] and not x.get("under_band")) else -1)
            nm = m["name"]
            if m.get("error"):
                if s.get("placeholder"):
                    continue                 # measured once the real take replaces the slate
                res.append(f"!shot {s.id} {nm!r}: cannot measure ({m['error']})")
                continue
            res.append(("" if m["ok"] else "!") + f"shot {s.id} {nm!r} @ {m['t']:.2f}s: {m['src']} src px x{m['scale']:.2f} = {m['px']:.1f} px (min {m['min_px']})"
                       + (", hidden by the caption band" if m.get("under_band") else "")
                       + ("" if m["inside"] or m.get("under_band") else ", NOT fully in frame"))
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


# ---------------------------------------------------------------- horizon
def burst_window(spec, st):
    """(beat0, beat1, [shot, ...]) of the burst: `style.burst: [beat0, beat1]` (shots fully inside) or, auto, the longest
    run of >= burst_min_shots consecutive horizon shots each shorter than pacing.burst_below_s. None when there is none."""
    pace = st["pacing"]
    shots = spec.shots
    b = st.get("burst")
    if b:
        b = b.get("beats", b) if isinstance(b, dict) else b
        inside = [s for s in shots if s.b0 >= b[0] - 1e-9 and s.b1 <= b[1] + 1e-9]
        return (b[0], b[1], inside) if inside else None
    best, run = [], []
    for s in shots:
        if s.type == "horizon" and s.dur < pace["burst_below_s"] - 1e-9:
            run.append(s)
            if len(run) > len(best):
                best = list(run)
        else:
            run = []
    return (best[0].b0, best[-1].b1, best) if len(best) >= pace.get("burst_min_shots", 3) else None


def _real_clip_ids(spec):
    """Clip ids of the footage manifest that are real app recordings (no `generated:` block). Empty if the manifest is unreadable."""
    from . import footage as FT
    try:
        return {cid for cid, c in FT.load(spec).items() if not (c or {}).get("generated")}
    except Exception:  # noqa: BLE001
        return set()


def _st(msgs_bad, msgs_warn, ok_msg):
    return ("FAIL" if msgs_bad else ("WARN" if msgs_warn else "PASS")), "; ".join(msgs_bad + msgs_warn) or ok_msg


def horizon_gates(spec, st, checks):
    """horizon preset gates. FAIL: shot < 0.3 s, cuts off whole beats outside the burst (half beats inside it), burst not
    followed by a hold >= 3 s, a horizon word spanning < 2 shots and < 1.2 s (or < 0.5 s), words overlapping / off the
    timeline / over non-horizon shots, per-shot overlays, text too wide, an edge that cannot be placed (box leaves the
    source), non-cut transitions that are not allowed, a dawn card held < 3 s, a word over real app footage (horizon-text-ui;
    `text_over_ui: true` on the shot opts out). WARN: shot < 0.4 s, no horizon_text / no horizon declared / no dawn end
    card, horizon outside 0.25-0.9 of the frame, a word inside the first 40 % of the burst (horizon-wordless-open), the
    flat sky covering more than 8 % of the frame height (horizon-sky)."""
    from types import SimpleNamespace

    from .shots import horizon as HZ
    out = []
    pace, shots, fr = st["pacing"], spec.shots, 1.0 / spec.fps
    hz = [s for s in shots if s.type == "horizon"]
    bw = burst_window(spec, st)

    if "horizon-shot-hold" in checks:
        hard = [f"shot {s.id} {s.dur:.2f}s < {pace['min_shot_s']}s" for s in shots if s.dur < pace["min_shot_s"] - fr / 2]
        soft = [f"shot {s.id} {s.dur:.2f}s < {pace['soft_min_shot_s']}s" for s in shots if pace["min_shot_s"] - fr / 2 <= s.dur < pace["soft_min_shot_s"] - fr / 2]
        s_, m = _st(hard, soft, f"every shot holds >= {pace['soft_min_shot_s']}s ({len(shots)} shots)")
        out.append(("horizon-shot-hold", s_, m))

    if "horizon-cuts" in checks:
        bad = []
        for a, b in zip(shots, shots[1:]):
            beat = a.b1
            if abs(beat - round(beat)) < 1e-6:
                continue
            half = abs(beat * 2 - round(beat * 2)) < 1e-6
            if half and bw and bw[0] - 1e-9 <= beat <= bw[1] + 1e-9:
                continue
            bad.append(f"cut {a.id}|{b.id} at beat {beat:g} is " + ("a half beat outside the burst window" if half else "off the beat grid"))
        win = f"burst beats {bw[0]:g}-{bw[1]:g} ({len(bw[2])} shots)" if bw else "no burst window"
        out.append(("horizon-cuts", "FAIL" if bad else "PASS", "; ".join(bad) or f"{len(shots) - 1} cuts on whole beats, half beats only inside the burst ({win})"))

    if "horizon-burst-hold" in checks:
        bad = []
        if bw:
            last = bw[2][-1]
            k = shots.index(last)
            if k + 1 >= len(shots):
                bad.append(f"the burst ends the film (last shot {last.id}): follow it with a hold >= {pace['hold_after_burst_s']}s")
            elif shots[k + 1].dur < pace["hold_after_burst_s"] - fr / 2:
                bad.append(f"burst (shots {bw[2][0].id}-{last.id}) is followed by shot {shots[k + 1].id} held only {shots[k + 1].dur:.2f}s < {pace['hold_after_burst_s']}s")
        out.append(("horizon-burst-hold", "FAIL" if bad else "PASS", "; ".join(bad) or
                    (f"burst {bw[2][0].id}-{bw[2][-1].id} ({sum(s.dur for s in bw[2]):.1f}s) followed by a hold >= {pace['hold_after_burst_s']}s" if bw
                     else f"no burst (needs >= {pace.get('burst_min_shots', 3)} consecutive shots under {pace['burst_below_s']}s)")))

    words = HZ.text_words(spec)
    if "horizon-text" in checks:
        bad, warn = [], []
        if hz and not words:
            warn.append("no horizon_text: the preset's ONE serif line on the horizon is missing")
        prev = None
        for w in words:
            tag = f"word {w['text']!r} (beats {w['a']:g}-{w['b']:g})"
            dur = w["t1"] - w["t0"]
            if prev is not None and w["f0"] < prev["f1"]:
                bad.append(f"{tag} overlaps {prev['text']!r}: one line, one word at a time")
            if w["b"] > spec.timeline.beats + 1e-9 or w["a"] < -1e-9 or w["b"] <= w["a"]:
                bad.append(f"{tag} is outside the timeline 0-{spec.timeline.beats:g} beats")
            if dur < pace["word_min_s"] - fr / 2:
                bad.append(f"{tag} visible only {dur:.2f}s < {pace['word_min_s']}s")
            over = [s for s in shots if s.f0 < w["f1"] and s.f0 + s.n > w["f0"]]
            n_h = sum(1 for s in over if s.type == "horizon")
            if any(s.type != "horizon" and min(w["f1"], s.f0 + s.n) - max(w["f0"], s.f0) > 1 for s in over):
                bad.append(f"{tag} runs over a non-horizon shot ({[s.id for s in over if s.type != 'horizon']}); only horizon shots draw the line")
            if n_h < pace["text_min_shots"] and dur < pace["text_min_s"] - fr / 2:
                bad.append(f"{tag} spans {n_h} shot and {dur:.2f}s: text must persist across >= {pace['text_min_shots']} shots or >= {pace['text_min_s']}s")
            prev = w
        for s in shots:
            for k in ("overlays", "cards", "caption", "captions"):
                if s.get(k):
                    bad.append(f"shot {s.id}: per-shot '{k}' not allowed in horizon (the line is the show-level horizon_text)")
        if sum(len(w["text"].split()) for w in words) > pace.get("max_words", st["horizon_text"].get("max_words", 12)):
            warn.append("more than 12 words: the preset is ONE short sentence")
        s_, m = _st(bad, warn, f"{len(words)} words, each across >= {pace['text_min_shots']} shots or >= {pace['text_min_s']}s, never overlapping" if words else "no horizon shots")
        out.append(("horizon-text", s_, m))

    if "horizon-text-fit" in checks:
        bad, warn = [], []
        ctx = SimpleNamespace(OW=1920, OH=1080)
        hs = HZ.text_style(st)
        for w in words:
            f, bb, cap = HZ.word_metrics(ctx, st, w["text"])
            if bb[2] - bb[0] > hs["max_w_frac"] * 1920:
                bad.append(f"word {w['text']!r} is {bb[2] - bb[0]} px wide > {hs['max_w_frac'] * 1920:.0f} px")
        if words and not getattr(f, "path", None):
            warn.append("no serif TTF found: PIL's built-in font is used (install NewYork.ttf / a serif; set style.typography.serif)")
        elif words:
            msg_font = os.path.basename(f.path)
        s_, m = _st(bad, warn, (f"all words fit in {hs['max_w_frac'] * 100:.0f}% of the width; serif {msg_font}, {round(hs['size_frac'] * 1080)} px ({hs['size_frac'] * 100:g}% of frame height)") if words else "no words")
        out.append(("horizon-text-fit", s_, m))

    if "horizon-edge" in checks:
        bad, warn, n_ok, unknown = [], [], 0, set()
        sky_max = (st.get("sky") or {}).get("max_frac", 0.6)
        for s in hz:
            if s.get("horizon_y") is None and not s.get("anchor"):
                warn.append(f"shot {s.id}: no horizon declared (anchor: or horizon_y:); the text falls back to y {st['horizon_text']['fallback_y']}")
            segs = HZ.segments(s)
            for t in (0.0, s.dur / 2, s.dur):
                acc, seg = 0.0, segs[-1]
                for x in segs:
                    if t <= acc + x["dur"] + 1e-6:
                        seg = x
                        break
                    acc += x["dur"]
                cid = seg.get("source", s.get("source"))
                size = HZ.src_size(spec, cid)
                if size is None:
                    unknown.add(s.id)
                    continue
                try:
                    hy = HZ.horizon_at(s.cfg, t, s.dur, seg)
                    cam = HZ.cam_for(s.cfg, t, s.dur, size, (16, 9), seg)
                except Exception as e:  # noqa: BLE001
                    bad.append(f"shot {s.id}: {e}")
                    break
                x0, y0, bw_, bh = HZ.box_of_cam(cam, size)
                tag = f"shot {s.id} @{t:.2f}s"
                if hy is not None and not 0.25 <= hy <= 0.9:
                    warn.append(f"{tag}: horizon at {hy:.2f} of the frame height (keep it within 0.25-0.9)")
                if x0 < -0.5 or x0 + bw_ > size[0] + 0.5:
                    bad.append(f"{tag}: camera box leaves the source horizontally (anchor out_x / w); the edge cannot sit where asked")
                elif y0 + bh > size[1] + 0.5:
                    bad.append(f"{tag}: camera box leaves the source at the bottom (lower out_y or the anchor y / narrow w)")
                elif y0 < -0.5:
                    sky = s.get("sky")
                    if not sky:
                        bad.append(f"{tag}: camera box reaches {-y0 / bh * 100:.0f}% above the source top: add sky: true (flat gradient) or move the anchor")
                    elif -y0 / bh > sky_max:
                        bad.append(f"{tag}: sky fills {-y0 / bh * 100:.0f}% of the frame > {sky_max * 100:.0f}% (the footage is the picture, not the gradient)")
                    else:
                        n_ok += 1
                else:
                    n_ok += 1
        if unknown:
            warn.append(f"source size unknown for shots {sorted(unknown)}: horizon placement not verified (footage manifest resolution / file)")
        s_, m = _st(bad, warn, f"{len(hz)} horizon shots: edge placed at its output height, camera box inside the source (sky only above the top edge)")
        out.append(("horizon-edge", s_, m))

    if "horizon-text-ui" in checks:
        bad = []
        real = _real_clip_ids(spec)
        for w in words:
            for s in shots:
                if s.type != "horizon" or s.get("text_over_ui") or min(w["f1"], s.f0 + s.n) - max(w["f0"], s.f0) <= 1:
                    continue
                srcs = {s.get("source")} | {g.get("source") for g in (s.get("segs") or [])}
                hit = sorted(c for c in srcs if c in real)
                if hit:
                    bad.append(f"word {w['text']!r} runs over shot {s.id} (real app footage {hit}): move the word, or set text_over_ui: true on the shot")
        out.append(("horizon-text-ui", "FAIL" if bad else "PASS", "; ".join(bad) or
                    f"no horizon word over real app footage ({len(real)} real clips in the manifest)"))

    if "horizon-wordless-open" in checks:
        warn = []
        frac = float(pace.get("wordless_open_frac", 0.40))
        if bw and words:
            t0, t1 = spec.timeline.t(bw[0]), spec.timeline.t(bw[1])
            limit = t0 + frac * (t1 - t0)
            warn = [f"word {w['text']!r} starts at {w['t0']:.2f}s, inside the first {frac * 100:.0f}% of the burst ({t0:.2f}-{limit:.2f}s): keep the open wordless"
                    for w in words if w["t0"] < limit - fr / 2]
        out.append(("horizon-wordless-open", "WARN" if warn else "PASS", "; ".join(warn) or
                    ("no burst or no words" if not (bw and words) else f"no word in the first {frac * 100:.0f}% of the burst")))

    if "horizon-sky" in checks:
        warn, worst = [], 0.0
        warn_frac = float((st.get("sky") or {}).get("warn_frac", 0.08))
        for s in hz:
            if not s.get("sky"):
                continue
            segs = HZ.segments(s)
            for t in (0.0, s.dur / 2, s.dur):
                acc, seg = 0.0, segs[-1]
                for x in segs:
                    if t <= acc + x["dur"] + 1e-6:
                        seg = x
                        break
                    acc += x["dur"]
                size = HZ.src_size(spec, seg.get("source", s.get("source")))
                if size is None:
                    continue
                try:
                    x0, y0, bw_, bh = HZ.box_of_cam(HZ.cam_for(s.cfg, t, s.dur, size, (16, 9), seg), size)
                except Exception:  # noqa: BLE001
                    continue
                fill = max(0.0, -y0 / bh)
                worst = max(worst, fill)
                if fill > warn_frac + 1e-9:
                    warn.append(f"shot {s.id} @{t:.2f}s: flat sky fills {fill * 100:.0f}% of the frame height > {warn_frac * 100:.0f}% (the footage should be the picture; lower the anchor out_y or use a narrower w)")
                    break
        out.append(("horizon-sky", "WARN" if warn else "PASS", "; ".join(warn) or
                    f"flat sky fills at most {worst * 100:.0f}% of the frame height (limit {warn_frac * 100:.0f}%)"))

    if "horizon-transitions" in checks:
        bad = []
        allowed = set(st["transitions"]["allowed"])
        dips = []
        for s in shots:
            if s.type not in ("horizon", "dawn"):
                bad.append(f"shot {s.id}: type {s.type!r} (the horizon preset renders `horizon` and `dawn` shots)")
            for k in ("flash", "speed_lines", "fx_in", "fx_out", "fx"):
                if s.get(k):
                    bad.append(f"shot {s.id}: '{k}' is an anime-opening effect; horizon cuts are cut (or cut_in: flash_dip when allowed)")
            ci = s.get("cut_in", "hard")
            if ci not in ("hard", "flash_dip"):
                bad.append(f"shot {s.id}: cut_in {ci!r} not in [hard, flash_dip]")
            elif ci == "flash_dip":
                dips.append(s.t0)
                if "flash_dip" not in allowed:
                    bad.append(f"shot {s.id}: cut_in flash_dip but style.transitions.allowed is {sorted(allowed)}")
        mx = pace.get("max_dips_per_s", 3)
        worst = max((sum(1 for y in dips if x - 1e-6 <= y < x + 1.0) for x in dips), default=0)
        if worst > mx:
            bad.append(f"{worst} flash dips in 1 s > {mx}")
        out.append(("horizon-transitions", "FAIL" if bad else "PASS", "; ".join(bad) or f"cuts only ({len(dips)} flash dips; allowed {sorted(allowed)})"))

    if "horizon-dawn" in checks:
        bad, warn = [], []
        dn = [s for s in shots if s.type == "dawn"]
        need = st["dawn"].get("min_hold_s", 3.0)
        for s in dn:
            if s.dur < need - fr / 2:
                bad.append(f"dawn card {s.id} held {s.dur:.2f}s < {need}s")
            if not s.get("name"):
                bad.append(f"dawn card {s.id}: name: is required")
            if s.get("tagline") and s.dur < st["dawn"]["tagline_at"] + 1.5:
                warn.append(f"dawn card {s.id}: tagline is readable only {s.dur - st['dawn']['tagline_at']:.1f}s")
        if not dn:
            warn.append("no dawn end card (type: dawn)")
        elif shots[-1].type != "dawn":
            warn.append(f"last shot {shots[-1].id} is not the dawn card")
        s_, m = _st(bad, warn, f"dawn end card held {dn[-1].dur:.1f}s >= {need}s" if dn else "")
        out.append(("horizon-dawn", s_, m))
    return out
