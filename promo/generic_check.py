"""Generic `promo check` gates that run on EVERY project (with or without a style preset).

Folded in from the hero's per-project audits (projects/commission-ai-hero/tools/named_v5.py, claims_v5.py):
  named          (clip / plugin shots; anime shots keep style_check.named_gates, livestream shots livestream-named)
                 FAIL if text a caption / VO line names renders under min_px (18 px cap height at 1080p) or is not fully
                 in frame; `named-upscale` WARN above 1.0x. Same `named:` contract as anime shots (promo/named.py), with
                 `t` = one shot-local time or a list of them (the smallest measurement gates); `info: true` rows are
                 reported, never gated.
  claims         projects whose preset does not run the claims gate (no preset = the hero): promo.claims.audit on the
                 claim tables, every `text_from` resolves, and a literal caption that IS a claim-table row must be the
                 row the table selects (else FAIL: the caption outruns the legibility record).

New WARN rules (never FAIL; thresholds per preset in WARN_RULES, project overrides in `qa: {warn_rules: {...}}`):
  text-edge      text or cards clipped by the output frame / crop edge: `named` boxes that cross the footage viewport
                 edge, plus an edge-content heuristic on sampled output frames (glyph-sized ink runs touching the
                 viewport edge).
  empty-frame    a UI shot whose largest flat / empty canvas region exceeds max_frac of the footage viewport
                 (blurred block flatness, so dotted canvas counts as empty).
  caption-truth  a caption / card count claim ('8 TASKS', 'ALL LANDED', '3 AGENTS') that disagrees with, or is not
                 backed by, the claim table it selects from or the footage manifest notes of the clip on screen.
  long-hold      a static hold / freeze (footage viewport unchanged frame to frame) longer than max_s.
Frame sampling uses ffmpeg -threads 2 inside the caller's heavy lock (`promo check` holds it).
"""
from __future__ import annotations

import copy
import re
import subprocess

import numpy as np

from . import claims as C

# Per-preset WARN-rule defaults. None = the no-preset / hero defaults. Keys merge over `_default`.
WARN_RULES = {
    "_default": dict(
        text_edge=dict(on=True, samples=3, depth_px=2, band_px=48, contrast=48, min_run_px=7, max_run_px=44, min_glyph_runs=3,
                       glyph_span_px=90, min_hits=1),
        empty_frame=dict(on=True, max_frac=0.5, samples=3, block_px=24, blur_px=12, flat_std=2.0),
        caption_truth=dict(on=True, unsupported="WARN"),
        long_hold=dict(on=True, max_s=3.5, diff=0.35, width=192),
        # captures that show scenery, not app UI (the Workshop / Outside / Street views): not judged as UI shots by
        # empty-frame (a night sky is not empty canvas). Shots with an explicit `ui:` key use that instead.
        non_ui_capture=["view=workshop", "workshopHour=", "town="],
    ),
    "hero": {},
    "anime-opening": dict(
        empty_frame=dict(max_frac=0.35),          # kinetic opening: the footage viewport (above the band) should read full
        long_hold=dict(max_s=2.8),                # ~2 bars at 177 BPM; holds longer than that read as a stall
    ),
    "livestream": dict(
        long_hold=dict(max_s=6.0),                # talk show: long holds are the format; > 6 s of a frozen screen is dead air
    ),
}


def deep_merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def rules_for(spec):
    preset = (spec.style or {}).get("preset") or "hero"
    r = deep_merge(WARN_RULES["_default"], WARN_RULES.get(preset, {}))
    return deep_merge(r, (spec.qa or {}).get("warn_rules") or (spec.raw.get("qa") or {}).get("warn_rules") or {})


# ------------------------------------------------------------------ geometry helpers
def is_livestream(spec):
    return bool(spec.raw.get("livestream"))


def viewport(spec, s, t_global=None):
    """Output rect [x0, y0, x1, y1] (1920x1080 units) where the shot's footage is shown."""
    if s.type == "anime":
        from .shots.anime import viewport as avp
        return [float(v) for v in avp(spec, s)]
    if is_livestream(spec) and s.type == "livestream":
        try:
            from . import livestream as LS
            b = LS.layout_at(spec, s.t0 + s.dur / 2 if t_global is None else t_global)["screen"]
            return [float(v) for v in b[:4]]
        except Exception:  # noqa: BLE001
            pass
    return [0.0, 0.0, 1920.0, 1080.0]


def clips_of(spec, s):
    from . import footage as FT
    return sorted(FT.referenced(spec, {s.id}))


def clip_at(s, t):
    """Clip id on screen at shot-local t for clip-like shots (segs with their own source, else the shot source)."""
    segs = s.cfg.get("segs")
    if segs:
        acc = 0.0
        for sg in segs:
            if t <= acc + float(sg.get("dur", 0)) + 1e-6:
                return sg.get("source", s.cfg.get("source"))
            acc += float(sg.get("dur", 0))
        return segs[-1].get("source", s.cfg.get("source"))
    sc = s.cfg.get("screen")
    if isinstance(sc, dict) and sc.get("source"):
        return sc["source"]
    return s.cfg.get("source") or s.cfg.get("still")


def is_ui_shot(spec, s, rules):
    if "ui" in s.cfg:
        return bool(s.cfg["ui"])
    if s.type in ("card", "live2d_credits") or s.cfg.get("placeholder"):
        return False
    from . import footage as FT
    try:
        man = FT.load(spec)
    except Exception:  # noqa: BLE001
        man = {}
    cid = clip_at(s, s.dur / 2)
    if not cid or cid not in man:
        return s.type != "card"
    cap = str(man[cid].get("capture") or "")
    return not any(m in cap for m in rules.get("non_ui_capture") or [])


# ------------------------------------------------------------------ folded: named (clip / plugin shots)
def _measure_clip_named(spec, s, el, t):
    from . import named as N
    from . import render as R
    from .shots.clip import segments
    from .spec import resolve_cam_keys
    total = s.n / spec.fps
    if s.cfg.get("type") == "float_window" or s.type == "float_window":
        ww, wh = s.cfg["window"]
        st = s.cfg["t_in"] + t
        cam = R.cam_at(s.cfg["camA"], t)
        fr = N.gray_frame(spec.footage_path(s.cfg["source"]), st)
        return N.element_px(fr, tuple(cam[:3]), (ww, wh), el["box"], src_px=el.get("src_px"), thr=el.get("thr", 110)), st
    segs = segments(s)
    keys = resolve_cam_keys(s.cfg["cam"], total)
    acc = 0.0
    sg = segs[-1]
    for x in segs:
        if t <= acc + x["dur"] + 1e-6:
            sg = x
            break
        acc += x["dur"]
    else:
        acc = total - sg["dur"]
    u = (t - acc) / max(sg["dur"], 1e-6)
    st = sg["t_in"] + (sg["t_out"] - sg["t_in"]) * u
    cam = R.cam_at(resolve_cam_keys(sg["cam"], sg["dur"]), t - acc) if sg.get("cam") else R.cam_at(keys, t)
    fr = N.gray_frame(spec.footage_path(sg.get("source", s.cfg.get("source"))), st)
    return N.element_px(fr, tuple(cam[:3]), (1920, 1080), el["box"], src_px=el.get("src_px"), thr=el.get("thr", 110)), st


def named_clip_gates(spec):
    from . import named as N
    rows, up, clipped = [], [], []
    for s in spec.shots:
        if s.type in ("anime", "livestream") or not s.cfg.get("named"):
            continue
        for el in s.cfg["named"]:
            ts = el.get("t", s.dur / 2)
            ts = ts if isinstance(ts, (list, tuple)) else [ts]
            mn = float(el.get("min_px", N.MIN_NAMED_PX))
            info = bool(el.get("info"))
            ms = []
            for t in ts:
                try:
                    r, st = _measure_clip_named(spec, s, el, float(t))
                except Exception as e:  # noqa: BLE001
                    rows.append(("!" if not info else "") + f"shot {s.id} {el.get('name')!r}: cannot measure ({e})")
                    ms = None
                    break
                ms.append((t, r))
            if ms is None:
                continue
            bad_ink = [t for t, r in ms if r is None]
            if bad_ink:
                rows.append(("" if info else "!") + f"shot {s.id} {el.get('name')!r}: no ink in the box at t={bad_ink} (box or thr wrong?)")
                continue
            t, r = min(ms, key=lambda x: x[1]["px"] if x[1]["inside"] else -1)
            ok = r["inside"] and r["px"] >= mn - 1e-6
            tag = "" if (ok or info) else "!"
            rows.append(tag + f"shot {s.id} {el.get('name')!r} @ {float(t):.2f}s: {r['src']} src px x{r['scale']:.2f} = {r['px']:.1f} px "
                        f"(min {mn:g}{', info' if info else ''})" + ("" if r["inside"] else ", NOT fully in frame"))
            if not r["inside"]:
                clipped.append(f"shot {s.id} {el.get('name')!r} @ {float(t):.2f}s crosses the crop edge (out box {r['out_box']})")
            if r["scale"] > 1.0 + 1e-6 and not info:
                up.append(f"shot {s.id} {el.get('name')!r} x{r['scale']:.2f}")
    if not rows:
        return [], []
    bad = [m for m in rows if m.startswith("!")]
    out = [("named", "FAIL" if bad else "PASS", "; ".join(m.lstrip("!") for m in rows)),
           ("named-upscale", "WARN" if up else "PASS", ("upscaled (effective scale > 1.0, soft text; prefer a DPR 2 take): " + "; ".join(up))
            if up else "every named element at effective scale <= 1.0")]
    return out, clipped


# ------------------------------------------------------------------ folded: claims for projects without the preset gate
def captions_of(spec, ctx=None):
    """[(shot, text, t0, t1, cfg)] for every caption (overlay) and anime card, shot-local times."""
    from .shots import get_type
    out = []
    for s in spec.shots:
        if s.type == "anime":
            from .shots.anime import card_text, card_times
            for c in s.cfg.get("cards") or []:
                t0, t1 = card_times(spec, s, c)
                out.append((s, card_text(spec, c), t0, t1, c))
            continue
        if ctx is not None:
            try:
                for c in get_type(s.type).captions(ctx, s):
                    if c.get("role") in ("caption", "label", "text") and c.get("text"):
                        src = next((o for o in s.cfg.get("overlays") or [] if o.get("text") == c["text"]), {})
                        out.append((s, c["text"], c["t0"], min(c["t1"], s.dur), src))
                continue
            except Exception:  # noqa: BLE001
                pass
        for o in s.cfg.get("overlays") or []:
            if o.get("type") in ("caption", "text", "pill") and (o.get("text") or o.get("text_from")):
                t = o.get("t") or [0, s.dur]
                out.append((s, C.text_of(spec.raw, o), float(t[0]), min(float(t[1]), s.dur), o))
    return out


def claims_gate(spec, ctx=None):
    st = spec.style or {}
    if "claims" in set(st.get("checks") or []) and st.get("preset"):
        return []                         # the preset's own claims gate already ran (style_check)
    raw = spec.raw
    if not raw.get("claims"):
        return []
    res = C.audit(raw, spec.resolve)
    bad = [m for s_, m in res if s_ == "FAIL"]
    warn = [m for s_, m in res if s_ == "WARN"]
    info = [m for s_, m in res if s_ == "INFO"]
    tables = (raw.get("claims") or {}).get("tables") or {}
    for s, text, t0, t1, cfg in captions_of(spec, ctx):
        if cfg.get("text_from"):
            try:
                C.resolve(raw, cfg["text_from"])
            except C.ClaimError as e:
                bad.append(f"shot {s.id}: {e}")
            continue
        for name, t in tables.items():
            texts = [r.get("text") for r in t.get("rows") or []]
            if text in texts:
                try:
                    sel = C.resolve(raw, name)[0]
                except C.ClaimError:
                    continue
                if sel != text:
                    bad.append(f"shot {s.id} caption {text!r} is a row of claim table {name} but the table selects {sel!r} "
                               f"(legibility record {C.legible_for(raw, t)}): use text_from: claims.{name}")
                else:
                    info.append(f"shot {s.id} caption {text!r} == claims.{name}")
    status = "FAIL" if bad else ("WARN" if warn else "PASS")
    return [("claims", status, "; ".join(bad + warn + info) or "no claim tables")]


# ------------------------------------------------------------------ caption-truth (new WARN)
CLAIM_NOUNS = {"cards": r"tasks?|cards?|tickets?|PRs?|pull\s+requests?", "logos": r"logos?", "agents": r"agents?",
               "landed": r"landed"}
EXTRA_COUNTS = {"cards": [r"plan\s+of\s+(\d+)", r"(\d+)\s+in\s+this\s+run\b", r"all\s+(\d+)\s+(?:\w+\s+)?cards?"]}


def caption_counts(text):
    """Count claims in a caption: {'cards': 8, 'landed': 'all', 'agents': 3, ...}."""
    out = {}
    for key, nouns in CLAIM_NOUNS.items():
        m = re.search(rf"\b(\d+)\s+(?:[A-Za-z]+\s+)?(?:{nouns})\b", text, flags=re.I)
        if m and key != "landed":
            out[key] = int(m.group(1))
    m = re.search(r"\b(\d+)\s+landed\b", text, flags=re.I)
    if m:
        out["landed"] = int(m.group(1))
    if re.search(r"\bALL\s+LANDED\b", text, flags=re.I):
        out["landed"] = "all"
    return out


def manifest_counts_text(txt):
    out = {}
    for k, rx in C.COUNT_WORDS.items():
        for mm in re.finditer(rx, txt or "", flags=re.I):
            out.setdefault(k, set()).add(int(next(g for g in mm.groups() if g is not None)))
    for k, rxs in EXTRA_COUNTS.items():
        for rx in rxs:
            for mm in re.finditer(rx, txt or "", flags=re.I):
                out.setdefault(k, set()).add(int(mm.group(1)))
    if "tasks" in out:
        out.setdefault("cards", set()).update(out.pop("tasks"))
    return out


def caption_truth_gate(spec, ctx=None, rules=None):
    from . import footage as FT
    rules = rules or rules_for(spec)
    if not rules["caption_truth"].get("on", True):
        return []
    try:
        man = FT.load(spec)
    except Exception:  # noqa: BLE001
        man = {}
    raw = spec.raw
    tables = (raw.get("claims") or {}).get("tables") or {}
    msgs, n = [], 0
    for s, text, t0, t1, cfg in captions_of(spec, ctx):
        claim = caption_counts(text)
        if not claim:
            continue
        n += 1
        ev, src = {}, []
        leg = None
        if cfg.get("text_from"):
            try:
                leg = C.resolve(raw, cfg["text_from"])[1]["legible"]
                src.append(cfg["text_from"])
            except C.ClaimError:
                pass
        else:
            for name, t in tables.items():
                if text in [r.get("text") for r in t.get("rows") or []]:
                    leg = C.legible_for(raw, t)
                    src.append(f"claims.{name}")
        for k, v in (leg or {}).items():
            if v is not None:
                ev.setdefault(k, set()).add(int(v))
        cids = {clip_at(s, t0 + (t1 - t0) * u) for u in (0.0, 0.5, 1.0)} - {None}
        if not cids:
            cids = set(clips_of(spec, s))
        mev = {}
        for cid in sorted(cids):
            c = man.get(cid) or {}
            for k, vs in manifest_counts_text(f"{c.get('notes', '')} {c.get('framing', '')}").items():
                mev.setdefault(k, set()).update(vs)
        if mev:
            src.append("manifest " + ",".join(sorted(cids)))
        problems = []
        for k, v in claim.items():
            if k == "landed" and v == "all":
                cards = (ev.get("cards") or mev.get("cards") or set())
                landed = (ev.get("landed") or mev.get("landed") or set())
                if not landed:
                    problems.append("'ALL LANDED' but no landed count in the claim table or manifest notes")
                elif cards and not (cards & landed):
                    problems.append(f"'ALL LANDED' but landed {sorted(landed)} != cards {sorted(cards)}")
                continue
            have = ev.get(k) or set()
            mhave = mev.get(k) or set()
            if k == "agents":
                have, mhave = have | (ev.get("logos") or set()), mhave | (mev.get("logos") or set())
            if have and v not in have:
                problems.append(f"{k} {v} but the claim table's legibility record says {sorted(have)}")
            elif mhave and v not in mhave and not have:
                problems.append(f"{k} {v} but the manifest notes of {', '.join(sorted(cids))} say {sorted(mhave)}")
            elif have and mhave and not (have & mhave):
                problems.append(f"{k}: claim table {sorted(have)} vs manifest notes {sorted(mhave)}")
            elif not have and not mhave:
                problems.append(f"{k} {v} is not backed by a claim table or the manifest notes of {', '.join(sorted(cids)) or 'its clip'}")
        if problems:
            msgs.append(f"shot {s.id} {text!r} @ {t0:.2f}-{t1:.2f}s: " + "; ".join(problems))
    if not n:
        return [("caption-truth", "PASS", "no count claims in captions / cards")]
    return [("caption-truth", "WARN" if msgs else "PASS", "; ".join(msgs) if msgs else f"{n} caption / card count claims agree with their claim tables / manifest notes")]


# ------------------------------------------------------------------ frame sampling
def grab(path, t, W=1920, H=1080):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-threads", "2", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-frames:v", "1",
                                   "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-"])
    return np.frombuffer(raw, np.uint8).reshape(H, W).astype(np.float32)


def sample_times(s, k):
    """k shot-local times away from the cuts (skips the first/last 6 frames: fx and dissolves)."""
    pad = min(0.2, s.dur / 4)
    return [pad + (s.dur - 2 * pad) * (i + 0.5) / k for i in range(k)]


# ------------------------------------------------------------------ text-edge (new WARN)
def _runs(mask):
    """[(start, length)] of True runs in a 1-D bool array."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    return list(zip(st.tolist(), (en - st).tolist()))


def _clusters(idx, gap):
    """Group sorted indices into [(first, last)] clusters whose members are <= gap apart."""
    out = []
    for i in idx:
        if out and i - out[-1][1] <= gap:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [tuple(c) for c in out]


def edge_hits(gray, vp, cfg):
    """Text-like ink touching the viewport edges. gray = 1080p frame (float). Returns [(edge, pos_px, why)].
    Ink = pixels >= `contrast` from the local background (the median of each line across a `band_px` band at the edge,
    so a panel or card running into the edge is background, not ink).
    left / right: rows with ink in the outermost depth_px columns, clustered; a cluster min_run..max_run px tall
                  (a glyph's height) whose ink does not run the whole band inward (a divider line or a bar does).
    top / bottom: columns with ink in the outermost depth_px rows; >= min_glyph_runs stroke runs (<= 24 px wide)
                  within glyph_span px (a line of letters cut through)."""
    x0, y0, x1, y1 = [int(round(v)) for v in vp]
    H, W = gray.shape
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    D, d, c = int(cfg.get("band_px", 48)), max(1, int(cfg["depth_px"])), float(cfg["contrast"])
    if x1 - x0 < 2 * D or y1 - y0 < 2 * D:
        return []
    bands = {"left": gray[y0:y1, x0:x0 + D], "right": gray[y0:y1, x1 - D:x1][:, ::-1],
             "top": gray[y0:y0 + D, x0:x1].T, "bottom": gray[y1 - D:y1, x0:x1][::-1, :].T}
    hits = []
    for edge, band in bands.items():        # band: rows = positions along the edge, cols = depth from the edge (0 = edge)
        bg = np.median(band, axis=1, keepdims=True)
        ink = np.abs(band - bg) >= c
        at_edge = ink[:, :d].any(1)
        base = y0 if edge in ("left", "right") else x0
        if edge in ("left", "right"):
            near = ink[:, :8].any(1)                            # glyph pieces within 8 px of the edge give its height
            near_cl = _clusters(np.nonzero(near)[0].tolist(), 2)
            seen = set()
            for a, b in _clusters(np.nonzero(at_edge)[0].tolist(), 2):
                a2, b2 = next(((p, q) for p, q in near_cl if p <= a and b <= q), (a, b))
                if (a2, b2) in seen:
                    continue
                seen.add((a2, b2))
                h = b2 - a2 + 1
                if not cfg["min_run_px"] <= h <= cfg["max_run_px"]:
                    continue
                if ink[a2:b2 + 1].all(1).mean() > 0.5:          # ink straight across the band on most rows = a bar / line
                    continue
                hits.append((edge, int(base + (a2 + b2) // 2), f"{h}px glyph-height ink at the edge"))
        else:
            runs = [(a, b - a + 1) for a, b in _clusters(np.nonzero(at_edge)[0].tolist(), 1) if b - a + 1 <= 24]
            i = 0
            while i < len(runs):
                j = i
                while j + 1 < len(runs) and runs[j + 1][0] - runs[i][0] <= cfg["glyph_span_px"]:
                    j += 1
                if j - i + 1 >= cfg["min_glyph_runs"]:
                    hits.append((edge, int(base + runs[i][0]), f"{j - i + 1} glyph strokes at the edge"))
                    i = j + 1
                else:
                    i += 1
    return hits


# ------------------------------------------------------------------ empty-frame (new WARN)
def empty_fraction(gray, vp, cfg):
    """Largest 4-connected region of flat blocks, as a fraction of the viewport area. Blocks are judged on a box-blurred
    frame (blur_px), so dotted / gridded canvas reads as flat while text, cards and photos do not."""
    from scipy.ndimage import label, uniform_filter
    x0, y0, x1, y1 = [int(round(v)) for v in vp]
    g = gray[max(0, y0):y1, max(0, x0):x1]
    if g.size == 0:
        return 0.0, None
    b = uniform_filter(g, size=int(cfg["blur_px"]))
    B = int(cfg["block_px"])
    h, w = (g.shape[0] // B) * B, (g.shape[1] // B) * B
    blk = b[:h, :w].reshape(h // B, B, w // B, B)
    flat = blk.std(axis=(1, 3)) <= cfg["flat_std"]
    lab, n = label(flat)
    if n == 0:
        return 0.0, None
    sizes = np.bincount(lab.ravel())[1:]
    k = int(np.argmax(sizes)) + 1
    ys, xs = np.nonzero(lab == k)
    box = [int(x0 + xs.min() * B), int(y0 + ys.min() * B), int(x0 + (xs.max() + 1) * B), int(y0 + (ys.max() + 1) * B)]
    return float(sizes.max()) / flat.size, box


# ------------------------------------------------------------------ long-hold (new WARN)
def longest_static(diffs, thr):
    """diffs[i] = mean abs change frame i -> i+1. Returns (frames in the longest static run, its first frame index);
    a run of k sub-threshold diffs spans k + 1 identical-looking frames."""
    best, start, cur, cs = 0, 0, 0, 0
    for i, v in enumerate(diffs):
        if v < thr:
            if cur == 0:
                cs = i
            cur += 1
            if cur > best:
                best, start = cur, cs
        else:
            cur = 0
    return (best + 1 if best else 0), start


def static_runs(path, spec, rects, width=192, diff=0.35):
    """Per shot: longest run (s) where the footage viewport does not change frame to frame.
    Decodes the output once at width x width*9/16 gray (ffmpeg -threads 2)."""
    W, H = int(width), int(round(width * 9 / 16))
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-threads", "2", "-i", path, "-an", "-vf", f"scale={W}:{H}:flags=area",
                                   "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    fr = np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)
    k = W / 1920.0
    out = {}
    for s in spec.shots:
        f0, f1 = int(round(s.t0 * spec.fps)), min(len(fr), int(round(s.t1 * spec.fps)))
        x0, y0, x1, y1 = rects.get(s.id, (0, 0, 1920, 1080))
        xa, ya, xb, yb = int(x0 * k), int(y0 * k), max(int(x0 * k) + 2, int(x1 * k)), max(int(y0 * k) + 2, int(y1 * k))
        if f1 - f0 < 2:
            out[s.id] = (0.0, s.t0)
            continue
        seg = fr[f0:f1, ya:yb, xa:xb]
        d = np.abs(np.diff(seg, axis=0)).mean(axis=(1, 2))
        n, i0 = longest_static(d, diff)
        out[s.id] = (n / spec.fps, (f0 + i0) / spec.fps)
    return out


# ------------------------------------------------------------------ gate runner
def frame_gates(spec, rules=None, clipped_named=()):
    """text-edge, empty-frame, long-hold on the rendered primary master. WARN-only."""
    import os
    rules = rules or rules_for(spec)
    out = spec.output_path(spec.masters[0].get("suffix", "")) if spec.masters else None
    res = []
    if not out or not os.path.exists(out):
        for g in ("text-edge", "empty-frame", "long-hold"):
            res.append((g, "PASS", "skipped: no rendered output to sample (run `promo build`)"))
        return res
    te, ef, lh = rules["text_edge"], rules["empty_frame"], rules["long_hold"]
    edge_msgs, empty_msgs, rects = list(clipped_named), [], {}
    measured = []
    for s in spec.shots:
        if s.cfg.get("placeholder"):
            continue
        vp = viewport(spec, s)
        rects[s.id] = vp
        footage = s.type not in ("card", "live2d_credits")
        if not footage:
            continue
        k = max(int(te.get("samples", 3)), int(ef.get("samples", 3)))
        hits, fracs = [], []
        for t in sample_times(s, k):
            g = grab(out, s.t0 + t)
            vpt = viewport(spec, s, s.t0 + t)
            if te.get("on", True):
                hits += [(t,) + h for h in edge_hits(g, vpt, te)]
            if ef.get("on", True) and is_ui_shot(spec, s, rules):
                fracs.append((t,) + empty_fraction(g, vpt, ef))
        if hits:
            by_edge = {}
            for t, e, pos, kind in hits:
                by_edge.setdefault(e, []).append((t, pos, kind))
            # a real cut glyph persists: require the same edge on >= half the samples (or a static shot)
            strong = {e: v for e, v in by_edge.items() if len({round(x[0], 2) for x in v}) >= max(int(te.get("min_hits", 1)), (k + 1) // 2)}
            for e, v in strong.items():
                pos = sorted({x[1] for x in v})
                edge_msgs.append(f"shot {s.id} {e} edge: text-like ink cut by the {'crop' if vp != [0, 0, 1920, 1080] else 'frame'} edge "
                                 f"on {len({round(x[0], 2) for x in v})}/{k} sampled frames at {'y' if e in ('left', 'right') else 'x'} "
                                 f"{', '.join(str(p) for p in pos[:4])}{' ...' if len(pos) > 4 else ''}")
        if fracs:
            med = sorted(f for _, f, _ in fracs)[len(fracs) // 2]
            box = max(fracs, key=lambda x: x[1])[2]
            measured.append((s.id, med))
            if med > ef["max_frac"]:
                empty_msgs.append(f"shot {s.id}: {med * 100:.0f}% of the picture is one flat / empty region (max {ef['max_frac'] * 100:.0f}%; largest at {box})")
    if te.get("on", True):
        res.append(("text-edge", "WARN" if edge_msgs else "PASS", "; ".join(edge_msgs) if edge_msgs else
                    "no text-like ink cut by a frame / crop edge on the sampled frames; no named box crosses the crop"))
    if ef.get("on", True):
        top = ", ".join(f"{sid} {f * 100:.0f}%" for sid, f in sorted(measured, key=lambda x: -x[1])[:3])
        res.append(("empty-frame", "WARN" if empty_msgs else "PASS", "; ".join(empty_msgs) if empty_msgs else
                    f"no UI shot over {ef['max_frac'] * 100:.0f}% empty canvas (largest: {top or 'n/a'})"))
    if lh.get("on", True):
        runs = static_runs(out, spec, rects, width=lh.get("width", 192), diff=lh.get("diff", 0.35))
        long_ = [(sid, d, t) for sid, (d, t) in runs.items() if d > lh["max_s"] + 1e-6]
        top = max(runs.items(), key=lambda x: x[1][0]) if runs else None
        res.append(("long-hold", "WARN" if long_ else "PASS",
                    "; ".join(f"shot {sid}: footage static for {d:.2f}s from {t:.2f}s (max {lh['max_s']:g}s)" for sid, d, t in long_) if long_
                    else f"no static hold over {lh['max_s']:g}s (longest: shot {top[0]} {top[1][0]:.2f}s)" if top else "no shots"))
    return res


def run(spec, ctx=None):
    """All generic gates -> [(gate, status, msg)]."""
    rules = rules_for(spec)
    res = []
    named, clipped = named_clip_gates(spec)
    res += named
    res += claims_gate(spec, ctx)
    res += caption_truth_gate(spec, ctx, rules)
    res += frame_gates(spec, rules, clipped)
    return res
