"""Shot QA at `promo footage add`, before anyone edits (docs/PRODUCT-DEFAULTS.md).

Four checks on the source frame, same ideas as the render-time gates, reported on the clip as `shot_qa`:
  named          FAIL when named text measures under 18 px at 1080p, or its box is outside the frame
  empty-frame    WARN above 40% flat canvas, FAIL above 70% (a mostly-empty frame)
  caption-badge  WARN when a caption is the same text as a badge already on the shot (caption ≠ badge)
  text-edge      WARN when glyph-like ink touches the frame edge; FAIL when a named box is clipped
"""
from __future__ import annotations

import re

import numpy as np

MIN_PX = 18
EMPTY_FAIL = 0.70


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", str(text).casefold())).strip()


def assess(gray, captions=(), badges=(), named=()):
    """`gray` is a float frame (1080p-sized for the edge/empty detectors). `named` is [{name, px, inside}, ...]."""
    from . import generic_check as G
    rules = G.WARN_RULES["_default"]
    h, w = gray.shape[:2]
    vp = [0, 0, w, h]
    rows = []
    fails = [n for n in named if n.get("px") is not None and float(n["px"]) < MIN_PX]
    clipped = [n for n in named if n.get("inside") is False]
    missing = [n for n in named if n.get("px") is None]
    if not named:
        rows.append(dict(gate="named", status="PASS", msg="no named text on this clip"))
    elif fails or clipped:
        bits = []
        if fails:
            bits.append("; ".join(f"{n.get('name') or 'text'} {float(n['px']):.1f}px < {MIN_PX}" for n in fails))
        if clipped:
            bits.append("named box is not fully in frame")
        rows.append(dict(gate="named", status="FAIL", msg="; ".join(bits)))
    elif missing:
        rows.append(dict(gate="named", status="WARN", msg="named text not measurable on this frame"))
    else:
        rows.append(dict(gate="named", status="PASS", msg=f"named text >= {MIN_PX}px and inside the frame"))

    frac, _box = G.empty_fraction(gray, vp, rules["empty_frame"])
    if frac >= EMPTY_FAIL:
        est = "FAIL"
    elif frac > float(rules["empty_frame"]["max_frac"]):
        est = "WARN"
    else:
        est = "PASS"
    rows.append(dict(gate="empty-frame", status=est, msg=f"{frac * 100:.0f}% of the frame is one flat region"))

    hits = G.edge_hits(gray, vp, rules["text_edge"])
    if clipped:
        rows.append(dict(gate="text-edge", status="FAIL", msg="named text is clipped by the frame edge"))
    elif hits:
        rows.append(dict(gate="text-edge", status="WARN", msg="; ".join(h[2] for h in hits[:4])))
    else:
        rows.append(dict(gate="text-edge", status="PASS", msg="no edge-clipped text"))

    clash = []
    for cap in captions:
        nc = _norm(cap)
        if nc and any(nc == _norm(b) for b in badges):
            clash.append(cap)
    if clash:
        rows.append(dict(gate="caption-badge", status="WARN", msg=f"caption repeats a badge already on screen: {clash[0]!r}"))
    else:
        rows.append(dict(gate="caption-badge", status="PASS", msg="caption does not repeat a badge"))
    return rows


def _load_gray(path):
    from PIL import Image

    from . import named
    g, _w, _h = named.gray_frame(path, 0.0)
    im = Image.fromarray(np.asarray(g).astype(np.uint8), "L").resize((1920, 1080), Image.Resampling.BOX)
    return np.asarray(im).astype(np.float32)


def _measure(path, el):
    from . import named
    if not el.get("box"):
        return dict(name=el.get("name"), px=None, inside=None)
    frame = named.gray_frame(path, float(el.get("at") or 0))
    r = named.element_px(frame, (0.5, 0.5, 1.0), (1920, 1080), el["box"], src_px=el.get("src_px"), thr=float(el.get("thr", 110)))
    if r is None:
        return dict(name=el.get("name"), px=None, inside=None)
    return dict(name=el.get("name"), px=r["px"], inside=bool(r["inside"]))


def _collect(spec, shot_ids, notes):
    captions, badges, named_els = [], [], []
    want = {str(s) for s in (shot_ids or [])}
    for s in getattr(spec, "shots", []) or []:
        if want and str(s.id) not in want:
            continue
        for o in s.cfg.get("overlays") or []:
            if o.get("text"):
                captions.append(str(o["text"]))
        for el in s.cfg.get("named") or []:
            named_els.append(el)
            if el.get("name"):
                badges.append(str(el["name"]))
    for m in re.finditer(r"(?i)\bbadge:\s*([^;\n]+)", notes or ""):
        badges.append(m.group(1).strip())
    return captions, badges, named_els


def for_clip(spec, path, shot_ids=(), notes=""):
    gray = _load_gray(path)
    captions, badges, named_els = _collect(spec, shot_ids, notes)
    measured = []
    for el in named_els:
        try:
            measured.append(_measure(path, el))
        except Exception as e:  # noqa: BLE001
            measured.append(dict(name=el.get("name"), px=None, inside=None, msg=str(e)))
    return assess(gray, captions, badges, measured)
