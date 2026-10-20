"""Podcast / VTuber-style show: Live2D hosts talking over the real app, overlaid on the frame with NO box by default.

Show level (promo.yaml):

    podcast:
      title: "Shipping at night"
      tag: "EP 1"
      hosts:
        - {id: a, model: mao, name: Mao, color: "#7FD1FF", voice: {engine: kokoro, voice: af_bella}, seed: 11}
        - {id: b, model: hiyori, name: Hiyori, color: "#FFB86B", voice: {engine: kokoro, voice: bf_emma}, seed: 22}
      layout: overlay            # overlay (default) | boxed | two-shot | speaker
      place: {a: {anchor: bottom-left, size: l}, b: {anchor: bottom-right, size: l}}   # size s|m|l|xl or a height fraction; x / y offsets
      frame: none                # none (default, no box) | card | circle | soft
      edge: shadow               # shadow | glow | rim | none: drawn from the avatar's own alpha only
      backdrop: {gradient: [[12, 14, 30], [40, 26, 78]]}    # | {plate: <footage id, ui: false>} | {image: path} | {blur_screen: true}
      subtitles: {show: true, style: speaker}               # speaker-coloured rows from the VO lines: <= 35 chars, >= 2 s
      keep_clear: [{name: status, box: [0.8, 0.0, 1.0, 0.12], source: <clip id>}]   # on the app screen (0..1); `source` = only on that take
      names: auto                # name pills: auto = first podcast shot (always in boxed) | true | false
      script: [...]              # the source lines `promo podcast plan` turned into vo.lines + shots (kept for re-plans)

Per shot (`type: podcast`): layout, screen {source, t_in, speed, cam: [cx, cy, w] | card | placeholder} (full frame in
overlay, a window in the other layouts), focus: a | b | auto (speaker layout: cuts to whoever talks, at line starts),
place: {a: {...}} overrides, cam: [[t, k], ...] = a push on the hosts (k = 1.0 the placed size; "end" = shot end).

Each host is rendered ONCE per show at a master bust size (`master`) with break-out headroom; every layout scales and
places that layer per frame, so a layout change never re-renders Live2D. Overlay keeps the bust cut at the frame's
bottom edge (a VTuber over the stream, no panel). Per VO line (`vo.lines[]`): host, mood, gesture, look, react
(promo/perform.py) drive the performance.

Geometry lives here and is shared by the renderer (shots/podcast.py) and the QA gates (`check`), so what is checked
is what is drawn. Boxes are [x0, y0, x1, y1] in 1920x1080 canvas units.
"""
from __future__ import annotations

import json
import math
import os
import re

import numpy as np

FRAME_W, FRAME_H = 1920, 1080
SIZES = {"s": 0.42, "m": 0.52, "l": 0.62, "xl": 0.82}
LAYOUTS = ("overlay", "boxed", "two-shot", "speaker")
FRAMES = ("none", "card", "circle", "soft")
EDGES = ("shadow", "glow", "rim", "none")
ANCHOR_X = {"bottom-left": 0.17, "bottom-right": 0.83, "bottom-center": 0.5}
MASTER = dict(head_frac=0.40, head_top_at=0.10)       # bust crop of the master layer: head = 40 % of the panel, bottom ~ the waist
COLORS = ["#7FD1FF", "#FFB86B", "#B9F18C", "#F49AC2"]
SUB_MAX_CHARS = 35
SUB_MIN_HOLD = 2.0
SUB_SIZE = 32
SUB_ROWS_Y = (892, 950)                                # centre y of the upper / lower subtitle row
SUB_ZONE = dict(x0=560, x1=1360, y0=860, y1=984)
WINDOW = {"two-shot": [480, 56, 1440, 596]}
BOXED_SCREEN = [456, 135, 1896, 945]
BOXED_COL = (24, 432)
MARGIN = 6
LIVE_RE = re.compile(r"\blive\b", re.I)
COUNT_RE = re.compile(r"\d[\d,.]*\s*[km]?\s*(viewers?|watching|watchers?|online|views?|subs|subscribers?|followers?)\b|👁", re.I)
CLAIM_RE = re.compile(r"\d|%|\b(always|never|every|all|fastest|best|only|first|guarantee[sd]?|24/7|instantly|zero|no one|nobody|100)\b", re.I)


def cfg(spec):
    return spec.raw.get("podcast") or {}


def hosts(c):
    return list(c.get("hosts") or [])


def host_color(c, i):
    h = hosts(c)[i]
    return h.get("color") or COLORS[i % len(COLORS)]


def rgb(hexs):
    s = str(hexs).lstrip("#")
    return tuple(int(s[k:k + 2], 16) for k in (0, 2, 4))


def subtitles_on(c):
    """`subtitles: false | {show: false}` turns them off (YAML reads a bare `on:` key as true, so `{on: false}` works too)."""
    st = c.get("subtitles", True)
    if isinstance(st, dict):
        for k in ("show", "on", True):
            if k in st:
                return bool(st[k])
        return True
    return st is not False


def plain(obj):
    """The block with every key a string (YAML turns `on:` into the boolean true; a digest needs comparable keys)."""
    return json.loads(json.dumps(obj, default=str))


def podcast_shots(spec):
    return [s for s in spec.shots if s.type == "podcast"]


def _num(v, span):
    """An offset: |v| <= 1 is a fraction of the frame, else canvas px."""
    v = float(v or 0)
    return v * span if abs(v) <= 1 else v


def size_frac(v):
    if v is None:
        return SIZES["l"]
    if isinstance(v, str):
        if v not in SIZES:
            raise ValueError(f"size {v!r}: use s|m|l|xl or a height fraction")
        return SIZES[v]
    return float(v)


# ---------------------------------------------------------------- placement
def default_place(layout, i, n):
    if layout == "two-shot":
        return dict(anchor="bottom-left" if i == 0 else "bottom-right", size="xl")
    if n == 1:
        return dict(anchor="bottom-right", size="l")
    if n == 2:
        return dict(anchor="bottom-left" if i == 0 else "bottom-right", size="l")
    return dict(anchor=["bottom-left", "bottom-center", "bottom-right"][min(i, 2)] if n == 3 else ("bottom-left" if i % 2 == 0 else "bottom-right"), size="m")


def resolve_place(c, shot_cfg, h, layout, i, n):
    """Placement of host h: layout default < show `place` (overlay / two-shot) < shot `place`."""
    p = default_place(layout, i, n)
    hid = str(h.get("id", i))
    if layout in ("overlay", "two-shot"):
        p.update((c.get("place") or {}).get(hid) or {})
    p.update(((shot_cfg or {}).get("place") or {}).get(hid) or {})
    return p


def shot_layout(c, shot_cfg):
    lay = (shot_cfg or {}).get("layout") or c.get("layout") or "overlay"
    if lay not in LAYOUTS:
        raise ValueError(f"podcast layout {lay!r}: use {' | '.join(LAYOUTS)}")
    return lay


def push_keys(shot):
    keys = []
    for k in shot.cfg.get("cam") or []:
        t = shot.dur if k[0] == "end" else float(k[0])
        keys.append((t, float(k[1])))
    return keys


def push_at(keys, t):
    if not keys:
        return 1.0
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, a), (t1, b) in zip(keys, keys[1:]):
        if t <= t1:
            u = (t - t0) / max(t1 - t0, 1e-6)
            return a + (b - a) * (0.5 - 0.5 * math.cos(math.pi * u))
    return keys[-1][1]


def max_display_height(spec):
    """Largest on-screen height (canvas px) any host layer reaches in any podcast shot (the master layer height)."""
    c = cfg(spec)
    hs = hosts(c)
    best = SIZES["l"] * FRAME_H
    for s in podcast_shots(spec):
        lay = shot_layout(c, s.cfg)
        push = max([k for _, k in push_keys(s)] + [1.0])
        if lay == "boxed":
            best = max(best, boxed_panels(len(hs))[0][3] - boxed_panels(len(hs))[0][1])
            continue
        for i, h in enumerate(hs):
            p = resolve_place(c, s.cfg, h, lay, i, len(hs))
            if lay == "speaker":
                p = dict(p, size=p.get("size") if ((s.cfg.get("place") or {}).get(str(h.get("id", i))) or {}).get("size") else "xl")
            best = max(best, size_frac(p.get("size")) * FRAME_H * push)
    return best


_M_CACHE = {}


def master(spec):
    """Master layer geometry shared by every host: H (canvas px at scale 1), a COMMON pad (break-out headroom so a hat
    is never clipped; same panel for every host = same head size), and per host: W, frame override (for
    live2d.framing / render_host), face / body boxes in layer px."""
    from . import live2d as L2
    c = cfg(spec)
    hs = hosts(c)
    key = json.dumps([hs, [s.cfg for s in podcast_shots(spec)], c.get("layout"), c.get("place")], sort_keys=True, default=str)
    if key in _M_CACHE:
        return _M_CACHE[key]
    MH = int(math.ceil(min(1400.0, max(300.0, max_display_height(spec))) / 8.0) * 8)
    models = []
    for h in hs:
        try:
            models.append(dict(L2.model_entry(h["model"]), id=h["model"]))
        except L2.Live2DError:
            models.append(None)
    hf, ht = MASTER["head_frac"], MASTER["head_top_at"]
    pad = 0.0
    for m in models:
        an = (m or {}).get("anchors")
        if not an:
            continue
        head = an["chin"] - an["head_top"]
        k = ht + (an.get("top", an["head_top"]) - an["head_top"]) * hf / head        # silhouette top / panel height
        pad = max(pad, (MARGIN - k * MH) / (1 - k))
    pad = int(math.ceil(max(0.0, pad)))
    P = MH - pad
    out = dict(H=MH, pad=pad, panel=P, hosts=[])
    for h, m in zip(hs, models):
        fr = dict(head_frac=hf, head_top_at=ht, pad_top=pad, **(h.get("frame") or {}))
        if m and m.get("anchors"):
            f = L2.framing(m, MH, fr)
            an = m["anchors"]
            mh_px = f["zoom"] * MH                                   # model height in layer px
            half = float(an.get("half_w", 0.2)) * mh_px
            W = int(math.ceil((2 * half * 1.15 + 24) / 8.0) * 8)
            head = f["chin_px"] - f["head_top_px"]
            cx = W / 2
            face = [cx - 0.48 * head, pad + f["head_top_px"], cx + 0.48 * head, pad + f["chin_px"]]
            body = [cx - half, pad + f["top_px"], cx + half, MH]
            out["hosts"].append(dict(id=str(h.get("id")), W=W, frame=fr, face=face, body=body, top=pad + f["top_px"], head=head,
                                     anchors=True, half=half))
        else:
            W = int(math.ceil(MH * 0.8 / 8.0) * 8)
            out["hosts"].append(dict(id=str(h.get("id")), W=W, frame=fr, face=[W * 0.3, MH * 0.1, W * 0.7, MH * 0.45], body=[0, 0, W, MH],
                                     top=0.0, head=MH * 0.35, anchors=False, half=W / 2))
    _M_CACHE[key] = out
    return out


SIL_STEP = 4                                       # rows per silhouette profile entry (master px)


def silhouette(spec, i):
    """The host's real outline in its master layer: per band of SIL_STEP rows, the [left, right] alpha extent (master
    px, widened by 4 % of the layer width for head turns and gestures), measured once from a render of the neutral pose
    and cached in build/live2d/. None when Live2D cannot render here (the gates fall back to the body box)."""
    from . import live2d as L2
    from .cache import digest
    M = master(spec)
    mh = M["hosts"][i]
    h = hosts(cfg(spec))[i]
    try:
        m = L2.model_entry(h["model"])
    except L2.Live2DError:
        return None
    from . import mesh_avatar
    key = digest(h["model"], m.get("anchors"), m.get("model3") or m.get("avatar"), mesh_avatar.signature(m), mh["frame"], mh["W"], M["H"], 1)
    p = os.path.join(spec.build, "live2d", f"podcast-{mh['id']}-silhouette.json")
    if os.path.exists(p):
        try:
            d = json.load(open(p))
            if d.get("key") == key:
                return d["rows"]
        except ValueError:
            pass
    try:
        fr, _ = L2.render_stills(h["model"], mh["W"], M["H"], {"ParamEyeLOpen": [1.0]}, frame=mh["frame"], warmup=30)
    except Exception:  # noqa: BLE001  (no node / Chromium / model files on this box)
        return None
    a = fr[0][..., 3] > 16
    grow = 0.04 * mh["W"]
    rows = []
    for y0 in range(0, M["H"], SIL_STEP):
        band = a[y0:y0 + SIL_STEP].any(0)
        xs = np.nonzero(band)[0]
        rows.append([float(xs[0] - grow), float(xs[-1] + grow)] if len(xs) else None)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(dict(key=key, step=SIL_STEP, rows=rows), f)
    return rows


def covers(g, box, sil):
    """Does host geometry g (its silhouette when known, else its body box) cover any part of `box`?"""
    if not overlap(g["body"], box):
        return False
    if not sil:
        return True
    s, x0, y0 = g["s"], g["layer"][0], g["layer"][1]
    for k, ext in enumerate(sil):
        if ext is None:
            continue
        ya, yb = y0 + k * SIL_STEP * s, y0 + (k + 1) * SIL_STEP * s
        if yb <= box[1] or ya >= box[3]:
            continue
        if x0 + ext[1] * s > box[0] and x0 + ext[0] * s < box[2]:
            return True
    return False


def boxed_panels(n):
    """Host panels in the left column of the boxed layout (livestream look)."""
    x0, x1 = BOXED_COL
    top, bottom, gap = 150, FRAME_H - 24, 16
    ph = min(470.0, (bottom - top - gap * (n - 1)) / max(1, n))
    y0 = bottom - n * ph - gap * (n - 1)
    return [[x0, y0 + i * (ph + gap), x1, y0 + i * (ph + gap) + ph] for i in range(n)]


def _scaled(b, s, ox, oy):
    return [ox + b[0] * s, oy + b[1] * s, ox + b[2] * s, oy + b[3] * s]


def host_geometry(M, i, place=None, push=1.0, panel=None):
    """Canvas boxes of host i: layer (where the scaled master layer goes), face, body (approx. silhouette), top (y of
    the silhouette top) and the scale s (display px per master px)."""
    mh = M["hosts"][i]
    MH, W = M["H"], mh["W"]
    if panel is not None:                    # boxed: the bust fills the panel height, face centred, bottom at the panel bottom
        Hd = (panel[3] - panel[1]) * push
        s = Hd / MH
        xc, yb = (panel[0] + panel[2]) / 2, panel[3]
    else:
        Hd = size_frac(place.get("size")) * FRAME_H * push
        s = Hd / MH
        xc = ANCHOR_X.get(place.get("anchor", "bottom-right"), 0.83) * FRAME_W + _num(place.get("x"), FRAME_W)
        yb = FRAME_H + _num(place.get("y"), FRAME_H)
    ox, oy = xc - W / 2 * s, yb - MH * s
    return dict(layer=[ox, oy, ox + W * s, oy + MH * s], s=s, face=_scaled(mh["face"], s, ox, oy), body=_scaled(mh["body"], s, ox, oy),
                top=oy + mh["top"] * s, xc=xc)


# ---------------------------------------------------------------- timing from the VO
def vo_meta(spec):
    from . import vo as VO
    p = VO.vo_json_path(spec)
    if not os.path.exists(p):
        return {}
    return {str(m.get("id", m["shot"])): m for m in json.load(open(p))["lines"]}


def line_host(c, line):
    who = str(line.get("host") or "").strip().lower()
    for i, h in enumerate(hosts(c)):
        if who and who in {str(h.get(k, "")).lower() for k in ("id", "name", "model")}:
            return i
    return None


def timed_lines(spec):
    """[{id, host (index), t0, t1, text, mood, gesture, gesture_at, look, react}] in global seconds, from vo.lines
    (+ vo.json durations; an estimate of 14 chars/s before `promo vo` ran). Muted lines are left out."""
    from . import vo as VO
    c = cfg(spec)
    meta = vo_meta(spec)
    out = []
    shot_ids = {s.id for s in spec.shots}
    for ln in (spec.raw.get("vo") or {}).get("lines") or []:
        if ln.get("mute") or str(ln.get("shot")) not in shot_ids:
            continue
        lid = VO.line_id(ln)
        t0 = spec.g(ln["shot"], float(ln.get("at", 0.0)))
        dur = float((meta.get(lid) or {}).get("dur") or max(0.6, len(str(ln.get("text", ""))) / 14.0))
        out.append(dict(id=lid, host=line_host(c, ln), t0=t0, t1=t0 + dur, text=str(ln.get("text", "")),
                        **{k: ln.get(k) for k in ("mood", "gesture", "gesture_at", "look", "react") if ln.get(k) is not None}))
    return sorted(out, key=lambda x: x["t0"])


def speaker_at(spec, t, lines=None):
    """Host index of whoever spoke last at global time t (the speaker cam's focus), or None before the first line."""
    cur = None
    for ln in lines if lines is not None else timed_lines(spec):
        if ln["t0"] - 0.05 <= t and ln["host"] is not None:
            cur = ln["host"]
    return cur


# ---------------------------------------------------------------- layout at a time
def layout_at(spec, shot, t, lines=None):
    """Everything placed on a podcast frame at shot-local time t: layout, screen box (full frame or a window),
    hosts [{i, id, visible, layer, s, face, body, top, panel}], frame / edge style, keep_clear boxes."""
    c = cfg(spec)
    hs = hosts(c)
    M = master(spec)
    lay = shot_layout(c, shot.cfg)
    tg = shot.t0 + t
    push = push_at(push_keys(shot), t)
    has_screen = bool(shot.cfg.get("screen"))
    frame = shot.cfg.get("frame") or c.get("frame") or "none"
    if lay == "boxed" and frame == "none" and not shot.cfg.get("frame"):
        frame = "card"                       # boxed IS the panel look (the livestream column); a shot may still say frame: none
    out = dict(layout=lay, frame=frame, edge=shot.cfg.get("edge") or c.get("edge") or "shadow", hosts=[])
    focus = None
    if lay == "speaker":
        f = shot.cfg.get("focus", "auto")
        if f == "auto":
            focus = speaker_at(spec, tg, lines)
            if focus is None:
                tl = [x for x in (lines if lines is not None else timed_lines(spec)) if shot.t0 <= x["t0"] < shot.t1 and x["host"] is not None]
                focus = tl[0]["host"] if tl else 0
        else:
            focus = next((i for i, h in enumerate(hs) if str(h.get("id")) == str(f)), 0)
    panels = boxed_panels(len(hs)) if lay == "boxed" else None
    for i, h in enumerate(hs):
        if lay == "boxed":
            g = host_geometry(M, i, push=push, panel=panels[i])
            g["panel"] = panels[i]
        else:
            p = resolve_place(c, shot.cfg, h, lay, i, len(hs))
            if lay == "speaker":
                side = p.get("anchor", "bottom-left")
                sp = ((shot.cfg.get("place") or {}).get(str(h.get("id", i))) or {})
                p = dict(p, size=sp.get("size", "xl"), anchor=sp.get("anchor", "bottom-left" if side == "bottom-left" else "bottom-right"),
                         x=sp.get("x", 0.10 if side == "bottom-left" else -0.10))
            g = host_geometry(M, i, p, push)
            g["panel"] = None
        g.update(i=i, id=str(h.get("id", i)), visible=(lay != "speaker" or i == focus))
        out["hosts"].append(g)
    # the app screen: the whole frame in overlay, a window elsewhere
    if not has_screen:
        out["screen"], out["screen_full"] = None, False
    elif lay == "overlay":
        out["screen"], out["screen_full"] = [0, 0, FRAME_W, FRAME_H], True
    elif lay == "boxed":
        out["screen"], out["screen_full"] = list(BOXED_SCREEN), False
    elif lay == "two-shot":
        out["screen"], out["screen_full"] = list(WINDOW["two-shot"]), False
    else:
        fh = out["hosts"][focus]
        left = fh["xc"] < FRAME_W / 2
        w, hgt = 920, 920 * 9 / 16
        x0 = FRAME_W - 32 - w if left else 32
        out["screen"], out["screen_full"] = [x0, 190, x0 + w, 190 + hgt], False
    s = out["screen"]
    out["keep_clear"] = []
    if s:
        sw, sh = s[2] - s[0], s[3] - s[1]
        src = (shot.cfg.get("screen") or {}).get("source")
        kc = [k for k in c.get("keep_clear") or [] if not k.get("source") or k["source"] == src] + list(shot.cfg.get("keep_clear") or [])
        out["keep_clear"] = [dict(name=k.get("name", f"keep_clear_{j}"), box=[s[0] + k["box"][0] * sw, s[1] + k["box"][1] * sh,
                                                                            s[0] + k["box"][2] * sw, s[1] + k["box"][3] * sh])
                             for j, k in enumerate(kc)]
    out["focus"] = focus
    return out


# ---------------------------------------------------------------- subtitles
def chunk_text(text, n=SUB_MAX_CHARS):
    """Split a line into rows of <= n characters at word boundaries, as even as the words allow (no one-word orphan
    row), preferring a break after punctuation."""
    words = []
    for w in str(text).split():
        while len(w) > n:                           # a single word longer than a row (a URL): hard split
            words.append(w[:n])
            w = w[n:]
        words.append(w)
    if not words:
        return []
    total = len(" ".join(words))
    k = max(1, math.ceil(total / n))
    while True:
        target = total / k
        rows, cur = [], ""
        for idx, w in enumerate(words):
            cand = (cur + " " + w).strip()
            left = len(words) - idx
            if cur and (len(cand) > n or (len(cur) >= target * 0.8 and (re.search(r"[,.;:!?]$", cur) or len(cand) > target * 1.15))
                        and len(rows) < k - 1 and left > 0):
                rows.append(cur)
                cur = w
            else:
                cur = cand
        rows.append(cur)
        if all(len(r) <= n for r in rows) or k > len(words):
            return rows
        k += 1


def subtitle_rows(spec, lines=None):
    """Subtitle rows on the global timeline: [{text, host, t0, t1}]. Each line's rows split its speaking time by
    characters; a row stays >= SUB_MIN_HOLD s (two rows can be on screen: the older one moves up); a row never starts
    before the row two back has had its hold."""
    c = cfg(spec)
    if not subtitles_on(c):
        return []
    lines = lines if lines is not None else timed_lines(spec)
    rows = []
    for ln in lines:
        parts = chunk_text(ln["text"])
        tot = sum(len(p) for p in parts) or 1
        t = ln["t0"]
        for k, p in enumerate(parts):
            dt = (ln["t1"] - ln["t0"]) * len(p) / tot
            rows.append(dict(text=p, host=ln["host"], line=ln["id"], t0=t, nat=t + dt, last=k == len(parts) - 1))
            t += dt
    for k, r in enumerate(rows):
        if k >= 2:
            r["t0"] = max(r["t0"], rows[k - 2]["t0"] + SUB_MIN_HOLD)
    for k, r in enumerate(rows):
        end = max(r["t0"] + SUB_MIN_HOLD, r["nat"] + (0.4 if r["last"] else 0.1))
        if k + 2 < len(rows):
            end = min(end, rows[k + 2]["t0"]) if rows[k + 2]["t0"] >= r["t0"] + SUB_MIN_HOLD else max(end, r["t0"] + SUB_MIN_HOLD)
        r["t1"] = max(end, r["t0"] + SUB_MIN_HOLD)
    return [dict(text=r["text"], host=r["host"], line=r["line"], t0=round(r["t0"], 3), t1=round(r["t1"], 3)) for r in rows]


def rows_at(rows, t):
    """Rows visible at global time t, oldest first (at most two)."""
    vis = [r for r in rows if r["t0"] <= t < r["t1"]]
    return vis[-2:]


def subtitle_box(text, slot, size=SUB_SIZE, char_w=0.56):
    """Approximate pill box of a row in slot 0 (upper) / 1 (lower), canvas units (QA; the renderer measures the font)."""
    w = min(len(text), SUB_MAX_CHARS + 4) * size * char_w + 44
    cy = SUB_ROWS_Y[slot]
    h = size + 18
    return [960 - w / 2, cy - h / 2, 960 + w / 2, cy + h / 2]


# ---------------------------------------------------------------- QA gates
def n_needed(spec):
    """Silhouettes are only worth a render when something could be covered: keep-clear boxes or 2+ visible hosts."""
    c = cfg(spec)
    return bool(c.get("keep_clear") or any(s.cfg.get("keep_clear") for s in podcast_shots(spec)) or len(hosts(c)) > 1)


def overlap(a, b, m=0.5):
    return min(a[2], b[2]) - max(a[0], b[0]) > m and min(a[3], b[3]) - max(a[1], b[1]) > m


def sample_times(shot, step=0.5):
    n = max(1, int(shot.dur / step))
    return [min(shot.dur - 1e-3, k * step) for k in range(n + 1)]


def visible_texts(spec):
    c = cfg(spec)
    out = [("podcast.tag", str(c.get("tag", ""))), ("podcast.title", str(c.get("title", "")))]
    for h in hosts(c):
        out.append((f"host {h.get('id')} name", str(h.get("name", ""))))
    for ln in (spec.raw.get("vo") or {}).get("lines") or []:
        out.append((f"line {ln.get('id', ln.get('shot'))}", str(ln.get("text", ""))))
    for s in spec.shots:
        for j, o in enumerate(s.get("overlays") or []):
            if o.get("text"):
                out.append((f"shot {s.id} overlay[{j}]", str(o["text"])))
        sc = s.get("screen")
        if isinstance(sc, dict) and isinstance(sc.get("card"), dict):
            cd = sc["card"]
            for t in [cd.get("title"), cd.get("subtitle")] + list(cd.get("lines") or []):
                if t:
                    out.append((f"shot {s.id} screen.card", str(t)))
    return out


def check(spec, ctx=None):
    """Rows (gate, status, msg) for `promo check`. Empty without a podcast block."""
    c = cfg(spec)
    if not c:
        return []
    from . import live2d as L2
    from . import livestream as LS
    rows = []
    hs = hosts(c)
    # licence: every model allowed (samples = Original Characters; your own = own | commissioned | original with licence
    # + source); a credit card when a sample or a credited model is in the show
    lic, need_card = [], False
    for h in hs:
        try:
            m = L2.model_entry(h["model"])
            if m.get("likeness") == "own":
                lic.append(f"{h['model']} {L2.OWN_LIKENESS_HOST}")
            if not m.get("user"):
                need_card = True
                if not m.get("credit") or not m.get("source_url"):
                    lic.append(f"{h['model']}: missing credit/source_url in live2d/assets.yaml")
            elif m.get("credit"):
                need_card = True
        except (L2.Live2DError, KeyError) as e:
            lic.append(str(e))
    cs = LS.credit_shots(spec)
    good = [s for s in cs if LS.credit_hold(s) >= LS.CREDIT_MIN_HOLD - 1e-9 and float(s.get("size", 30)) >= LS.CREDIT_MIN_PX]
    if need_card and not good:
        lic.append("no end-card credit: add a `live2d_credits` shot (Live2D notice + model credits, >= 28 px, >= 2 s)" if not cs else
                   "; ".join(f"credit shot {s.id}: {float(s.get('size', 30)):.0f} px (min {LS.CREDIT_MIN_PX}), fully visible "
                             f"{LS.credit_hold(s):.2f} s (min {LS.CREDIT_MIN_HOLD} s)" for s in cs))
    rows.append(("podcast-licence", "FAIL" if lic else "PASS", "; ".join(lic) if lic else
                 f"{len(hs)} host model(s) allowed" + (f"; credits on {good[0].id}" if good else "; no credit needed (your own uncredited models)")))

    # framing: heads never clipped at the top, no host covers another's face, hosts and subtitles stay off keep-clear
    probs, n_s = [], 0
    try:
        M = master(spec)
    except Exception as e:  # noqa: BLE001
        M = None
        probs.append(f"cannot place the hosts: {e}")
    lines = timed_lines(spec)
    rws = subtitle_rows(spec, lines)
    for h, mh in zip(hs, (M or {}).get("hosts") or []):
        if not mh["anchors"]:
            probs.append(f"host {h.get('id')} ({h['model']}): no framing anchors in the model entry (run `promo live2d add` or add them)")
    seen = set()
    sils = [silhouette(spec, i) for i in range(len(hs))] if M and n_needed(spec) else [None] * len(hs)
    for s in podcast_shots(spec) if M else []:
        for t in sample_times(s):
            L = layout_at(spec, s, t, lines)
            n_s += 1
            vis = [g for g in L["hosts"] if g["visible"]]
            for g in vis:
                if g["panel"] is None and g["top"] < -0.5 and ("clip", s.id, g["id"]) not in seen:
                    seen.add(("clip", s.id, g["id"]))
                    probs.append(f"shot {s.id} at {t:.1f}s: host {g['id']} clipped at the top of the frame by {-g['top']:.0f} px (smaller size or y offset)")
                for o in vis:
                    if o is not g and covers(o, g["face"], sils[o["i"]]) and ("face", s.id, g["id"], o["id"]) not in seen:
                        # only a host drawn in front can cover a face: later hosts are drawn over earlier ones
                        if o["i"] > g["i"]:
                            seen.add(("face", s.id, g["id"], o["id"]))
                            probs.append(f"shot {s.id} at {t:.1f}s: host {o['id']} covers host {g['id']}'s face")
                for k in L["keep_clear"]:
                    if g["panel"] is None and covers(g, k["box"], sils[g["i"]]) and ("kc", s.id, g["id"], k["name"]) not in seen:
                        seen.add(("kc", s.id, g["id"], k["name"]))
                        probs.append(f"shot {s.id} at {t:.1f}s: host {g['id']} covers keep-clear '{k['name']}'")
            vr = rows_at(rws, s.t0 + t)
            for slot, r in enumerate(vr[-2:] if len(vr) == 2 else [None] + vr):
                if r is None:
                    continue
                b = subtitle_box(r["text"], slot)
                for g in vis:
                    if overlap(b, g["face"]) and ("sub", s.id, g["id"]) not in seen:
                        seen.add(("sub", s.id, g["id"]))
                        probs.append(f"shot {s.id} at {t:.1f}s: a subtitle covers host {g['id']}'s face")
                for k in L["keep_clear"]:
                    if overlap(b, k["box"]) and ("subkc", s.id, k["name"]) not in seen:
                        seen.add(("subkc", s.id, k["name"]))
                        probs.append(f"shot {s.id} at {t:.1f}s: a subtitle covers keep-clear '{k['name']}'")
    rows.append(("podcast-framing", "FAIL" if probs else "PASS", "; ".join(probs[:12]) + (f" (+{len(probs) - 12} more)" if len(probs) > 12 else "") if probs else
                 f"{n_s} sampled frames: no head clipped, no face covered, keep-clear clear" + (f"; master layer {M['H']} px, headroom {M['pad']} px" if M else "")))

    # subtitles: rows <= 35 chars, held >= 2 s, inside the subtitle zone
    bad = []
    for r in rws:
        if len(r["text"]) > SUB_MAX_CHARS:
            bad.append(f"{r['line']}: row {r['text']!r} is {len(r['text'])} chars (max {SUB_MAX_CHARS})")
        if r["t1"] - r["t0"] < SUB_MIN_HOLD - 1e-6:
            bad.append(f"{r['line']}: row {r['text']!r} held {r['t1'] - r['t0']:.2f}s (min {SUB_MIN_HOLD})")
        for slot in (0, 1):
            b = subtitle_box(r["text"], slot)
            z = SUB_ZONE
            if not (b[0] >= z["x0"] and b[2] <= z["x1"] and b[1] >= z["y0"] and b[3] <= z["y1"]):
                bad.append(f"{r['line']}: row {r['text']!r} outside the subtitle zone")
                break
    if rws or bad:
        rows.append(("podcast-subtitles", "FAIL" if bad else "PASS", "; ".join(bad[:10]) if bad else
                     f"{len(rws)} subtitle rows, all <= {SUB_MAX_CHARS} chars, held >= {SUB_MIN_HOLD:g}s, inside the zone"))

    # lint: a recorded show has no LIVE badge and no viewer counts
    lint = [f"{w}: {t!r}" for w, t in visible_texts(spec) if LIVE_RE.search(t) or COUNT_RE.search(t)]
    rows.append(("podcast-lint", "FAIL" if lint else "PASS", ("no 'LIVE' text or viewer counts (this is a recorded promo): " + "; ".join(lint)) if lint
                 else "no 'LIVE' text or viewer counts"))

    # voices: every voice has a licence entry; `say` is a draft voice; VoiceStudio's model licence is an open question
    from . import assets as A
    from . import vo as VO
    try:
        man = A.load_manifest(spec)
    except A.AssetError as e:
        man = {}
        rows.append(("podcast-voice-licence", "FAIL", str(e)))
    else:
        vb, draft, nc = [], [], []
        try:
            used = VO.voices_used(spec)
        except RuntimeError as e:
            used = []
            vb.append(str(e))
        engines = sorted({v["engine"] for _, v in used})
        for lid, v in used:
            ids = [(spec.raw.get("vo") or {}).get(k) for k in ("model_asset", "voices_asset")] if v["engine"] == "kokoro" else [v.get("asset")]
            for aid in ids:
                if not aid:
                    vb.append(f"line {lid}: {v['engine']} voice has no assets.yaml entry (`asset:`)")
                elif aid not in man or not str(man[aid].get("licence") or "").strip():
                    vb.append(f"line {lid}: voice asset {aid!r} missing from assets.yaml or has no licence")
            if v["engine"] in VO.DRAFT_ENGINES:
                draft.append(lid)
            if v["engine"] == "voicestudio":
                nc.append(lid)
        vb = sorted(set(vb))
        rows.append(("podcast-voice-licence", "FAIL" if vb else "PASS", "; ".join(vb[:8]) if vb else f"voices: {', '.join(engines) or 'none'}; every voice has a licence entry"))
        if draft:
            rows.append(("draft-voice", "WARN", f"{len(draft)} line(s) voiced with macOS `say` ({', '.join(draft[:6])}{'...' if len(draft) > 6 else ''}): drafts only, "
                         "re-voice with kokoro before publishing"))
        if nc:
            rows.append(("voice-licence-open", "WARN", f"{len(nc)} line(s) voiced with VoiceStudio (OmniVoice model, CC-BY-NC): confirm the licence covers this use before publishing"))

    ov = overlaps(spec, lines)
    if ov:
        rows.append(("podcast-overlap", "WARN", "takes run into the next line (re-voiced or retimed?): " + ", ".join(f"{a} into {b} by {d:.2f}s" for a, b, d in ov[:8])
                     + "; `promo podcast plan --force` lays the lines out again"))

    # truth: a line with a number or an absolute claim names its evidence (`evidence:` on the VO line or the script line)
    script_ev = {str(x.get("id")): x for x in c.get("script") or [] if x.get("id")}
    miss = []
    for ln in (spec.raw.get("vo") or {}).get("lines") or []:
        lid = VO.line_id(ln)
        if ln.get("claim") is False:
            continue
        if ln.get("claim") or CLAIM_RE.search(str(ln.get("text", ""))):
            if not (ln.get("evidence") or (script_ev.get(lid) or {}).get("evidence")):
                miss.append(f"{lid}: {str(ln.get('text', ''))[:60]!r}")
    rows.append(("podcast-truth", "FAIL" if miss else "PASS", ("lines that make a claim (a number or an absolute) need `evidence:` (commit, run, "
                 "screenshot), or `claim: false` for banter: " + "; ".join(miss[:8])) if miss else "every claim-like line names its evidence"))
    return rows


# ---------------------------------------------------------------- script -> plan
SCRIPT_KEYS = ("id", "host", "text", "tts", "mood", "gesture", "gesture_at", "look", "react", "pause", "evidence", "claim", "scene", "voice")


def validate_script(c, script):
    """Problems with a script (list of line dicts) for this show's hosts."""
    from . import perform as PF
    out = []
    ids = set()
    for k, ln in enumerate(script):
        where = f"line {k + 1}"
        if not isinstance(ln, dict):
            out.append(f"{where}: must be a mapping {{host, text, ...}}")
            continue
        unknown = [x for x in ln if x not in SCRIPT_KEYS]
        if unknown:
            out.append(f"{where}: unknown keys {unknown} (have {', '.join(SCRIPT_KEYS)})")
        if not str(ln.get("text") or "").strip():
            out.append(f"{where}: no text")
        if line_host(c, ln) is None:
            out.append(f"{where}: host {ln.get('host')!r} is not one of the show's hosts ({', '.join(str(h.get('id')) for h in hosts(c))})")
        if ln.get("mood") and PF.mood_name(ln["mood"])[0] not in PF.MOODS:
            out.append(f"{where}: mood {ln['mood']!r} (have {', '.join(PF.MOODS)})")
        if ln.get("react") and PF.mood_name(ln["react"])[0] not in PF.MOODS:
            out.append(f"{where}: react {ln['react']!r} (have {', '.join(PF.MOODS)})")
        g = ln.get("gesture")
        if g and g not in PF.GESTURES and not str(g).startswith("motion:"):
            out.append(f"{where}: gesture {g!r} (have {', '.join(PF.GESTURES)} or motion:<name>)")
        if ln.get("look") and ln["look"] not in PF.LOOKS:
            out.append(f"{where}: look {ln['look']!r} (have {', '.join(PF.LOOKS)})")
        if ln.get("id"):
            if ln["id"] in ids:
                out.append(f"{where}: duplicate id {ln['id']!r}")
            ids.add(ln["id"])
    return out


def line_ids(c, script):
    """Stable ids: the line's own `id`, else <host id><n> (a1, b1, a2, ...)."""
    cnt, out = {}, []
    taken = {str(x["id"]) for x in script if x.get("id")}
    for ln in script:
        if ln.get("id"):
            out.append(str(ln["id"]))
            continue
        hid = str(hosts(c)[line_host(c, ln)].get("id"))
        while True:
            cnt[hid] = cnt.get(hid, 0) + 1
            cand = f"{hid}{cnt[hid]}"
            if cand not in taken:
                break
        taken.add(cand)
        out.append(cand)
    return out


def lay_out(script, durs, bpm=120.0, lead_in=0.75, tail=0.8, same_pause=0.35, swap_pause=0.15, credits_s=3.0):
    """Lines back to back: each starts after its `pause` (default: a short gap when the speaker changes, a longer one
    when the same host goes on), snapped up to the half-beat grid. Returns ([(start_s, start_halfbeats)], end_s, total_halfbeats)."""
    hb = 30.0 / bpm                                       # half a beat in seconds
    t = lead_in
    out, prev = [], None
    for ln, d in zip(script, durs):
        p = ln.get("pause")
        gap = float(p) if p is not None else (same_pause if prev == ln.get("host") else swap_pause)
        t = t + (gap if out else 0.0)
        k = int(math.ceil(t / hb - 1e-9))
        out.append((k * hb, k))
        t = k * hb + d
        prev = ln.get("host")
    end = t + tail
    k_end = int(math.ceil(end / hb - 1e-9))
    k_total = k_end + int(math.ceil(credits_s / hb - 1e-9))
    return out, k_end * hb, k_total


REACTIONS = {"laugh", "surprised", "excited"}


def _scene_cfg(sc, cur, screens, si):
    """A script line's `scene:` marker -> (shot cfg, screen index). A bare layout name keeps the screen; `screen:` names
    a clip (or {source, t_in, cam}); `next_screen: true` moves to the next planned screen."""
    if isinstance(sc, str):
        sc = {"layout": sc} if sc in LAYOUTS else {"screen": sc}
    nxt = dict(layout=sc.get("layout", cur["layout"]), screen=cur.get("screen"))
    if sc.get("screen"):
        v = sc["screen"]
        nxt["screen"] = dict(v) if isinstance(v, dict) else dict(source=v, t_in=0.0)
    elif sc.get("next_screen") and screens:
        si += 1
        nxt["screen"] = dict(screens[si % len(screens)])
    return nxt, si


def plan_shots(c, script, ids, starts, durs, k_end, k_total, screens, layout=None, min_shot_s=3.0, bpm=120.0, reaction_hold_s=4.0):
    """Generated shots: the show layout on the first screen, a new shot at each `scene:` marker, a speaker cam (focus
    auto) from a short reaction line (laugh / surprised / excited) held >= reaction_hold_s, then the credits card.
    Cuts sit on line starts (the half-beat grid); a cut that would leave a shot under min_shot_s waits for the next
    line. Footage keeps playing across cuts on the same clip. Returns (shots, vo_lines)."""
    from . import perform as PF
    hb = 30.0 / bpm
    base = dict(layout=layout or c.get("layout") or "overlay", screen=dict(screens[0]) if screens else None)
    plan = [[0, dict(base)]]                       # [start half-beat, cfg]
    si, pending = 0, None
    for k in range(1, len(script)):
        ln = script[k]
        kk = starts[k][1]
        cur_start, cur = plan[-1]
        long_enough = (kk - cur_start) * hb >= min_shot_s - 1e-9
        if ln.get("scene"):
            base, si = _scene_cfg(ln["scene"], base, screens, si)
            pending = dict(base)
        reaction = PF.mood_name(ln.get("mood"))[0] in REACTIONS and durs[k] < 2.8 and base["layout"] != "speaker"
        if reaction and long_enough and cur["layout"] != "speaker":
            plan.append([kk, dict(base, layout="speaker", focus="auto")])
            pending = None if pending == base else pending
            continue
        if cur.get("focus") == "auto" and cur["layout"] == "speaker" and base["layout"] != "speaker" and (kk - cur_start) * hb >= reaction_hold_s - 1e-9:
            pending = dict(base)
        if pending is not None and long_enough and pending != cur:
            plan.append([kk, pending])
            pending = None
    spans = [[a, plan[j + 1][0] if j + 1 < len(plan) else k_end, cfg_] for j, (a, cfg_) in enumerate(plan)]
    if len(spans) > 1 and (spans[-1][1] - spans[-1][0]) * hb < min_shot_s:
        spans[-2][1] = spans[-1][1]
        spans.pop()
    shots, playhead = [], {}
    for j, (a, b, sc) in enumerate(spans):
        s = dict(id=f"{j + 1:02d}", type="podcast", beats=[a / 2, b / 2], layout=sc["layout"])
        if sc.get("screen"):
            scr = dict(sc["screen"])
            src = scr.get("source")
            if src and src in playhead and playhead[src][0] == scr.get("t_in", 0.0):
                scr["t_in"] = round(playhead[src][1], 3)              # the same take carries on where the last shot left it
            if src:
                playhead[src] = (sc["screen"].get("t_in", 0.0), float(scr.get("t_in", 0.0)) + (b - a) * hb * float(scr.get("speed", 1.0)))
            s["screen"] = scr
        if sc["layout"] == "speaker":
            s["focus"] = sc.get("focus", "auto")
        shots.append(s)
    shots.append(dict(id=f"{len(shots) + 1:02d}", type="live2d_credits", beats=[k_end / 2, k_total / 2], size=30, fade_in=0.25, title="Credits"))
    vo_lines = []
    for k, ln in enumerate(script):
        kk = starts[k][1]
        s = next(x for x in shots if x["beats"][0] * 2 <= kk < x["beats"][1] * 2)
        line = dict(id=ids[k], shot=s["id"], at=round((kk - s["beats"][0] * 2) * hb, 4), host=ln["host"], text=ln["text"])
        for key in ("tts", "mood", "gesture", "gesture_at", "look", "react", "evidence", "claim", "voice"):
            if ln.get(key) is not None:
                line[key] = ln[key]
        vo_lines.append(line)
    return shots, vo_lines


# ---------------------------------------------------------------- small spec edits (`promo podcast set`, the Stage's editor)
PLACE_KEYS = ("anchor", "size", "x", "y")
HOST_KEYS = ("name", "color", "model", "seed", "energy")
VOICE_KEYS = ("engine", "voice", "speed", "profile", "instruct", "asset")


def _val(v):
    try:
        return int(v) if re.fullmatch(r"-?\d+", v) else float(v) if re.fullmatch(r"-?\d*\.\d+|-?\d+\.\d*", v) else v
    except ValueError:
        return v


def find_host(c, hid):
    for h in hosts(c):
        if hid.lower() in {str(h.get(k, "")).lower() for k in ("id", "name")}:
            return h
    raise ValueError(f"no host {hid!r} (have {', '.join(str(h.get('id')) for h in hosts(c))})")


def set_host(raw, hid, kv):
    """host <id> place=bottom-right|anchor=.. size=xl x=.. y=.. frame=none edge=glow name=.. color=.. model=.. voice=.. engine=.. speed=..
    Placement goes to podcast.place.<id>; frame / edge are the show's (one look for every host)."""
    c = raw.setdefault("podcast", {})
    h = find_host(c, hid)
    pid = str(h.get("id"))
    for k, v in kv.items():
        v = _val(v)
        if k in ("place", "anchor"):
            if v not in ANCHOR_X:
                raise ValueError(f"place {v!r}: use {' | '.join(ANCHOR_X)}")
            c.setdefault("place", {}).setdefault(pid, {})["anchor"] = v
        elif k == "size":
            if not (v in SIZES or isinstance(v, (int, float)) and 0.2 <= float(v) <= 1.3):
                raise ValueError(f"size {v!r}: use s | m | l | xl or a height fraction 0.2-1.3")
            c.setdefault("place", {}).setdefault(pid, {})["size"] = v
        elif k in ("x", "y"):
            c.setdefault("place", {}).setdefault(pid, {})[k] = float(v)
        elif k == "frame":
            set_show(raw, "frame", str(v))
        elif k == "edge":
            set_show(raw, "edge", str(v))
        elif k in HOST_KEYS:
            if k == "model":
                from . import live2d as L2
                L2.model_entry(str(v))               # refuses unknown / not allowed models
            h[k] = v
        elif k in VOICE_KEYS:
            vv = h.get("voice") if isinstance(h.get("voice"), dict) else ({"voice": h["voice"]} if h.get("voice") else {})
            vv[k] = v
            h["voice"] = vv
        else:
            raise ValueError(f"host: unknown key {k!r} (have place, size, x, y, frame, edge, {', '.join(HOST_KEYS + VOICE_KEYS)})")
    return raw


def set_show(raw, key, value, shot=None):
    """layout | frame | edge | subtitles | names | backdrop for the show, or (layout, frame, edge, focus) for one shot."""
    c = raw.setdefault("podcast", {})
    allowed = dict(layout=LAYOUTS, frame=FRAMES, edge=EDGES)
    if key in allowed and value not in allowed[key]:
        raise ValueError(f"{key} {value!r}: use {' | '.join(allowed[key])}")
    if shot is not None:
        s = next((x for x in raw.get("shots") or [] if str(x.get("id")) == str(shot)), None)
        if s is None:
            raise ValueError(f"no shot {shot!r}")
        if s.get("type") != "podcast":
            raise ValueError(f"shot {shot} is a {s.get('type')} shot, not a podcast shot")
        if key not in ("layout", "frame", "edge", "focus"):
            raise ValueError(f"per shot: layout, frame, edge or focus (not {key})")
        s[key] = value
        if key == "layout" and value == "speaker":
            s.setdefault("focus", "auto")
        if key == "layout" and value != "speaker":
            s.pop("focus", None)
        return raw
    if key == "subtitles":
        st = {k: v for k, v in (c.get("subtitles") if isinstance(c.get("subtitles"), dict) else {}).items() if k not in ("on", True)}
        c["subtitles"] = dict(st, show=str(value).lower() in ("on", "true", "1", "yes", "show"))
    elif key == "names":
        v = str(value).lower()
        c["names"] = "auto" if v == "auto" else v in ("on", "true", "1", "yes")
    elif key == "backdrop":
        v = str(value)
        if v in ("blur", "blur_screen"):
            c["backdrop"] = {"blur_screen": True}
        elif v.startswith("plate="):
            c["backdrop"] = {"plate": v.split("=", 1)[1]}
        elif v.startswith("image="):
            c["backdrop"] = {"image": v.split("=", 1)[1]}
        elif v.startswith("gradient"):
            cols = [rgb(x) for x in v.split("=", 1)[1].split(",")] if "=" in v else [[12, 14, 30], [46, 30, 84]]
            c["backdrop"] = {"gradient": [list(x) for x in cols]}
        else:
            raise ValueError("backdrop: gradient[=#hex,#hex] | blur | plate=<footage id> | image=<path>")
    elif key in ("layout", "frame", "edge"):
        c[key] = value
    else:
        raise ValueError(f"unknown setting {key!r} (have layout, frame, edge, subtitles, names, backdrop, host)")
    return raw


def overlaps(spec, lines=None):
    """Lines whose take runs into the next line (two hosts talking over each other), [(id, next id, seconds)]."""
    tl = lines if lines is not None else timed_lines(spec)
    return [(a["id"], b["id"], round(a["t1"] - b["t0"], 2)) for a, b in zip(tl, tl[1:]) if a["t1"] - b["t0"] > 0.08]
