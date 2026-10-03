"""Talk-show layout: app screen (>= 55 % of the frame) + Live2D hosts on one side + a chat strip (<= 4 lines).

Spec (show level, in promo.yaml):

    livestream:
      hosts_side: left            # left | right for the whole show (default left). No slide by default.
      # move: {beat: 16, dur: 0.9}  # optional, discouraged: ONE side change, >= 0.5 s, starting on a shot boundary beat.
      #                             # Hosts slide OFF their frame edge, the screen crosses, hosts slide in from the other
      #                             # edge (never behind the screen). No second move, no instant flip (`promo check`).
      screen: {w: 1440}           # 16:9 app screen width in 1920-canvas px (area must stay >= 55 % of the frame)
      margin: 24
      slot_gap: 16                # min px between the stacked host panels (>= 12); widened to fit a hat breaking out
      keep_clear:                 # rectangles on the APP SCREEN (normalised 0..1 of the screen) that nothing may cover;
        - {name: status-corner, box: [0.80, 0.0, 1.0, 0.14]}   # outlines drawn only with `promo --debug`
      tag: "EP 1"                 # neutral episode tag in the header (no LIVE badges, no viewer counts: linted)
      title: "Building in public" # header title (optional)
      chat:                       # the hosts' own asides only; any other author needs `scripted_label` (shown on screen)
        max_lines: 4
        # scripted_label: "scripted chat"
        lines: [{t: 1.0, user: Hiyori, text: "screen share is up"}]          # t = global seconds
      hosts:
        - {id: a, model: hiyori, wav: media/host_a.wav, name: Hiyori, seed: 11}
        - {id: b, model: mao, wav: media/host_b.wav, name: Mao, seed: 22}

Hosts are framed by per-model head/chest anchors (promo.live2d.framing): same head height + scale, mid-chest crop.
Credits: a `live2d_credits` shot (end card) shows the full Live2D notice + model credits at body size (>= 28 px at
1080p) for >= 2 s at full opacity; `promo check` (livestream-licence) fails without it.

Geometry lives here (`layout_at`) and is shared by the renderer (shots/livestream.py) and the QA gate (`check`), so
what is checked is what is drawn. All boxes are [x0, y0, x1, y1] in 1920x1080 canvas units.
"""
from __future__ import annotations

import os
import re

import numpy as np

from .render import ease

FRAME_W, FRAME_H = 1920, 1080
MIN_SCREEN_FRAC = 0.55
MAX_CHAT_LINES = 4
MIN_MOVE_S = 0.5
MIN_SLOT_GAP = 12
HOST_W = 420                      # host layer width (canvas px); height follows the slot (head-and-shoulders framing)
CHROME_FONT_PX = 28               # EP tag + host name tags: font size giving >=20 px cap height at 1080p
HOSTS_TOP = 168                   # below the header
HOSTS_BOTTOM = FRAME_H - 14       # host panels end 14 px above the frame edge (same margin as the chat strip)
CREDIT_MIN_PX = 28
CREDIT_MIN_HOLD = 2.0
LIVE_RE = re.compile(r"\blive\b", re.I)
COUNT_RE = re.compile(r"\d[\d,.]*\s*[km]?\s*(viewers?|watching|watchers?|online|views?|subs|subscribers?|followers?)\b|👁", re.I)


def cfg(spec):
    return spec.raw.get("livestream") or {}


def moves(c):
    """Normalised list of declared moves (`move:` dict or `moves:` list; the check rejects more than one)."""
    m = []
    if c.get("move"):
        m.append(c["move"])
    m += list(c.get("moves") or [])
    return m


def has_chat(c):
    """A chat strip exists only if the spec declares chat lines (no asides = no strip at all)."""
    return bool(((c.get("chat") or {}).get("lines")))


def screen_size(c):
    """(w, h) of the app screen. 16:9 above a chat strip; with no chat strip it takes the full frame height
    (minus margins) unless `screen.h` is given. Clips are framed into it with an aspect-matched cam crop."""
    sc = c.get("screen") or {}
    w = float(sc.get("w", 1440))
    if sc.get("h"):
        return w, float(sc["h"])
    if not has_chat(c):
        return w, FRAME_H - 2 * float(c.get("margin", 24))
    return w, w * 9 / 16


def slot_gap(c):
    return float(c.get("slot_gap", 16))


BREAK_MARGIN = 6                  # px kept clear between a break-out silhouette (hat) and anything else
MIN_PANEL_H = 300
_HL_CACHE = {}


def host_layout(c):
    """Panel geometry shared by every host. Each host is clipped by its panel at the sides and bottom (mid-chest crop),
    NOT at the top: a silhouette taller than the head (Mao's hat, anchor `top`) breaks out above the panel into the
    layer's `pad` px of headroom. The gap above panel i (gap 0 = under the header) is widened to fit host i's
    break-out (+ BREAK_MARGIN), i.e. the slot layout is nudged; only if the panels would then drop below MIN_PANEL_H
    does the COMMON head scale shrink (3 % steps), so all hosts stay matched. Returns {w, h (panel), pad, gaps[n] (gap above each panel; [0] = space
    under the header), y0s[n], head_frac, head_top_at, tops[n] (silhouette top, panel-relative px), frames[n]
    (render overrides)}."""
    import json
    from . import live2d as L2
    key = json.dumps([c.get(k) for k in ("hosts", "slot_gap", "margin", "head_frac", "head_top_at")], sort_keys=True, default=str)
    if key in _HL_CACHE:
        return _HL_CACHE[key]
    hosts = c.get("hosts") or []
    n = max(1, len(hosts))
    margin = float(c.get("margin", 24))
    hdr_bottom = margin + 120
    above0 = HOSTS_TOP - hdr_bottom                     # default space between the header box and the first panel
    avail = HOSTS_BOTTOM - hdr_bottom
    hf, ht = float(c.get("head_frac", L2.HEAD_FRAC)), float(c.get("head_top_at", L2.HEAD_TOP_AT))
    models = []
    for h in hosts:
        try:
            models.append(dict(L2.model_entry(h["model"]), id=h["model"]))
        except L2.Live2DError:
            models.append(None)
    for _ in range(40):
        ov = [dict(dict(head_frac=hf, head_top_at=ht), **(h.get("frame") or {})) for h in hosts]
        b = []
        for m, o in zip(models, ov):
            f = L2.framing(m, 1.0, {k: v for k, v in o.items() if k != "pad_top"}) if m else {}
            b.append(max(0.0, -(f.get("top_px") or 0.0)))   # break-out height as a fraction of the panel
        b = b or [0.0]
        # nudge the slot layout first: each gap grows to fit the break-out below it (gap 0 = under the header)
        P = (avail - above0 - slot_gap(c) * (n - 1)) / n
        for _ in range(30):
            gaps = [max(above0, b[0] * P + BREAK_MARGIN)] + [max(slot_gap(c), b[i] * P + BREAK_MARGIN) for i in range(1, n)]
            P = (avail - sum(gaps)) / n
        if n == 1:
            P = min(P, 600)
        P = int(P)
        if P >= MIN_PANEL_H or hf < 0.2:
            break
        hf *= 0.97                                      # ... and only then shrink the common head scale
    gaps = [int(np.ceil(max(above0, b[0] * P + BREAK_MARGIN)))] + [int(np.ceil(max(slot_gap(c), b[i] * P + BREAK_MARGIN))) for i in range(1, n)]
    y0s = [HOSTS_BOTTOM - (n - i) * P - sum(gaps[i + 1:]) for i in range(n)]   # last panel ends at HOSTS_BOTTOM
    gaps[0] = y0s[0] - hdr_bottom                                               # rounding slack goes under the header
    pad = int(np.ceil(max(b) * P + BREAK_MARGIN)) if max(b) > 0 else 0
    frames = [dict(dict(head_frac=hf, head_top_at=ht, pad_top=pad), **(h.get("frame") or {})) for h in hosts]
    tops = [-bb * P for bb in b]
    out = dict(w=HOST_W, h=P, pad=pad, pads=[int(f["pad_top"]) for f in frames], gaps=gaps, y0s=y0s, head_frac=hf, head_top_at=ht, tops=tops, frames=frames)
    _HL_CACHE[key] = out
    return out


def host_size(c):
    """(w, h) of every host PANEL (the rendered layer is `host_layout(c)['pad']` px taller, for break-out headroom)."""
    hl = host_layout(c)
    return hl["w"], hl["h"]


def _side_pos(c, side):
    """Static boxes for hosts on `side` (left|right)."""
    margin = float(c.get("margin", 24))
    sw, sh = screen_size(c)
    hosts = c.get("hosts") or []
    col_w = FRAME_W - sw - 2 * margin
    if side == "left":
        sx0, col0 = FRAME_W - margin - sw, 0.0
    else:
        sx0 = margin
        col0 = sx0 + sw + margin
    screen = [sx0, margin, sx0 + sw, margin + sh]
    n = len(hosts)
    hl = host_layout(c)
    hw, hh = hl["w"], hl["h"]
    hb = []
    # Stacked duo in the host column: equal panels with a `slot_gap` between them (no overlap); every host is cropped
    # by its own panel at mid-chest (same anchor framing, promo.live2d.framing). Side-by-side busts don't fit next to
    # a >= 55 % screen without covering each other's faces.
    for i in range(n):
        y0 = hl["y0s"][i]
        x0 = (col_w - hw) / 2
        if side == "right":
            x0 = FRAME_W - x0 - hw                      # mirror into the right-hand column
        hb.append([x0, y0, x0 + hw, y0 + hh])
    chat = [screen[0], screen[3] + 14, screen[2], FRAME_H - 14] if has_chat(c) else None
    hdr_x0 = col0 + 18 if side == "left" else col0 + 6
    header = [hdr_x0, margin, hdr_x0 + col_w - 24, margin + 120]
    return dict(screen=screen, hosts=hb, chat=chat, header=header)


def move_phase(c, spec, t):
    """(phase, u): phase 0 = before, 1 = hosts leaving, 2 = screen crossing, 3 = hosts entering, 4 = done; u = 0..1 eased."""
    ms = moves(c)
    if not ms:
        return 0, 0.0
    m = ms[0]
    t0 = spec.timeline.t(m["beat"])
    d = float(m.get("dur", 0.9))
    if t <= t0:
        return 0, 0.0
    if d <= 0 or t >= t0 + d:
        return 4, 1.0
    p = (t - t0) / (d / 3)
    k = int(p)
    return 1 + k, ease(p - k)


def side_at(c, spec, t):
    """Fraction of the way to the other side (0 = start side, 1 = other side), for gaze tracks."""
    ph, u = move_phase(c, spec, t)
    return {0: 0.0, 1: 0.0, 2: u, 3: 1.0, 4: 1.0}[ph] if ph != 2 else u


def _lerp_box(a, b, u):
    return [a[i] + (b[i] - a[i]) * u for i in range(4)]


def _shift(box, dx):
    return [box[0] + dx, box[1], box[2] + dx, box[3]]


def layout_at(spec, t):
    """Boxes at global time t: screen, hosts[], chat, header, keep_clear[] (frame coords).
    During the single (optional) move the hosts + header slide off their outer frame edge, the screen and chat cross,
    then hosts + header slide in from the other edge: they never pass behind or over the screen."""
    c = cfg(spec)
    start = c.get("hosts_side", "left")
    other = "right" if start == "left" else "left"
    A, B = _side_pos(c, start), _side_pos(c, other)
    ph, u = move_phase(c, spec, t)
    out_dx = -(max(b[2] for b in A["hosts"] + [A["header"]]) + 4) if start == "left" else FRAME_W - min(b[0] for b in A["hosts"] + [A["header"]]) + 4
    in_dx = FRAME_W - min(b[0] for b in B["hosts"] + [B["header"]]) + 4 if start == "left" else -(max(b[2] for b in B["hosts"] + [B["header"]]) + 4)
    if ph == 0:
        S, hosts, hdr = A, A["hosts"], A["header"]
    elif ph == 1:
        S, hosts, hdr = A, [_shift(b, out_dx * u) for b in A["hosts"]], _shift(A["header"], out_dx * u)
    elif ph == 2:
        S = dict(screen=_lerp_box(A["screen"], B["screen"], u), chat=_lerp_box(A["chat"], B["chat"], u) if A["chat"] else None)
        hosts, hdr = [_shift(b, out_dx) for b in A["hosts"]], _shift(A["header"], out_dx)
    elif ph == 3:
        S, hosts, hdr = B, [_shift(b, in_dx * (1 - u)) for b in B["hosts"]], _shift(B["header"], in_dx * (1 - u))
    else:
        S, hosts, hdr = B, B["hosts"], B["header"]
    L = dict(screen=S["screen"], chat=S["chat"], header=hdr, hosts=hosts, phase=ph)
    hl = host_layout(c)
    # layer = panel + `pad` headroom above it; break-out = the silhouette part above the panel top (e.g. a hat)
    L["layers"] = [[b[0], b[1] - pd, b[2], b[3]] for b, pd in zip(hosts, hl["pads"])]
    L["breakouts"] = [[b[0], b[1] + tp, b[2], b[1]] if tp < -0.5 else None for b, tp in zip(hosts, hl["tops"])]
    s = L["screen"]
    sw, sh = s[2] - s[0], s[3] - s[1]
    L["keep_clear"] = [dict(name=k.get("name", f"keep_clear_{i}"),
                            box=[s[0] + k["box"][0] * sw, s[1] + k["box"][1] * sh, s[0] + k["box"][2] * sw, s[1] + k["box"][3] * sh])
                       for i, k in enumerate(c.get("keep_clear") or [])]
    return L


def overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 0.5 and min(a[3], b[3]) - max(a[1], b[1]) > 0.5


def chat_lines_at(c, t):
    ch = c.get("chat") or {}
    n = min(int(ch.get("max_lines", MAX_CHAT_LINES)), MAX_CHAT_LINES)
    vis = [ln for ln in (ch.get("lines") or []) if float(ln["t"]) <= t]
    return vis[-n:] if n > 0 else []


def host_names(c):
    names = set()
    for h in c.get("hosts") or []:
        for k in ("id", "name"):
            if h.get(k):
                names.add(str(h[k]).strip().lower())
    return names


def credit_shots(spec):
    return [s for s in spec.shots if s.type == "live2d_credits"]


def credit_hold(shot):
    """Seconds the credit text is fully visible (shot duration minus its fade-in)."""
    return shot.dur - float(shot.get("fade_in", 0.25))


def visible_texts(spec):
    """(where, text) for every on-screen string the spec declares (header, chat, overlays, credits title)."""
    c = cfg(spec)
    out = [("livestream.tag", str(c.get("tag", "EP 1"))), ("livestream.title", str(c.get("title", "")))]
    ch = c.get("chat") or {}
    if ch.get("scripted_label"):
        out.append(("chat.scripted_label", str(ch["scripted_label"])))
    for i, ln in enumerate(ch.get("lines") or []):
        out += [(f"chat.lines[{i}].user", str(ln.get("user", ""))), (f"chat.lines[{i}].text", str(ln.get("text", "")))]
    for h in c.get("hosts") or []:
        out.append((f"host {h.get('id')} name", str(h.get("name", ""))))
    for s in spec.shots:
        for j, o in enumerate(s.get("overlays") or []):
            if o.get("text"):
                out.append((f"shot {s.id} overlay[{j}]", str(o["text"])))
        for k in ("title", "screen"):
            v = s.get(k)
            if isinstance(v, str):
                out.append((f"shot {s.id} {k}", v))
            elif isinstance(v, dict) and isinstance(v.get("placeholder"), str):
                out.append((f"shot {s.id} screen.placeholder", v["placeholder"]))
            if isinstance(v, dict) and isinstance(v.get("card"), dict):
                cd = v["card"]
                for t in [cd.get("title"), cd.get("subtitle")] + list(cd.get("lines") or []):
                    if t:
                        out.append((f"shot {s.id} screen.card", str(t)))
    return out


# ---------------------------------------------------------------- QA gate
def check(spec, ctx=None):
    """Rows (gate, status, msg) for `promo check`. Empty if the spec has no livestream block."""
    c = cfg(spec)
    if not c:
        return []
    rows = []
    # 0. Live2D licence: Original Characters only + an end-card credit (full notice + model credits, >= 28 px, >= 2 s)
    from . import live2d as L2
    lic = []
    for h in c.get("hosts") or []:
        try:
            m = L2.model_entry(h["model"])
            if not m.get("credit") or not m.get("source_url"):
                lic.append(f"{h['model']}: missing credit/source_url in live2d/assets.yaml")
        except L2.Live2DError as e:
            lic.append(str(e))
    cs = credit_shots(spec)
    ok = lambda s: credit_hold(s) >= CREDIT_MIN_HOLD - 1e-9 and float(s.get("size", 30)) >= CREDIT_MIN_PX
    desc = lambda s: f"{s.id}: {float(s.get('size', 30)):.0f} px, {credit_hold(s):.2f} s at full opacity"
    whole = [s for s in cs if s.get("part") is None and ok(s)]
    parts = {p: [s for s in cs if s.get("part") == p and ok(s)] for p in (1, 2)}   # a split credit: part 1 notice + part 2 models
    good = whole[:1] or (parts[1][:1] + parts[2][:1] if parts[1] and parts[2] else [])
    if not cs:
        lic.append("no end-card credit: add a `live2d_credits` shot (full Live2D notice + model credits)")
    elif not good:
        miss = [f"part {p} missing" for p in (1, 2) if not parts[p]] if any(s.get("part") for s in cs) else []
        lic.append("; ".join(miss + [f"credit shot {s.id}{' part ' + str(s.get('part')) if s.get('part') else ''}: text "
                                     f"{float(s.get('size', 30)):.0f} px (min {CREDIT_MIN_PX}), fully visible "
                                     f"{credit_hold(s):.2f} s (min {CREDIT_MIN_HOLD} s)" for s in cs]))
    rows.append(("livestream-licence", "FAIL" if lic else "PASS",
                 "; ".join(lic) if lic else f"{len(c.get('hosts') or [])} Live2D Original Character host(s); end-card credit shot"
                 f"{'s' if len(good) > 1 else ''} " + " + ".join(desc(s) for s in good)))
    # 0b. framing: every host cropped by the same anchor rule (same head height + scale, panel bottom at mid-chest);
    # the full silhouette (anchor `top`, e.g. a hat) is never clipped at the top and its break-out above the panel
    # never covers the header, another host, the screen, the chat strip or a keep-clear rectangle.
    fr_rows, probs = [], []
    hl = host_layout(c)
    hh = hl["h"]
    L0 = layout_at(spec, spec.shots[0].t0 if spec.shots else 0.0)
    for i, h in enumerate(c.get("hosts") or []):
        try:
            m = L2.model_entry(h["model"])
        except L2.Live2DError:
            continue
        pad = hl["pads"][i]
        f = L2.framing(dict(m, id=h["model"]), hh + pad, hl["frames"][i])
        if f["head_px"] is None:
            probs.append(f"host {h.get('id')}: no framing anchors (legacy zoom/cy framing)")
            continue
        if not f.get("has_top"):
            probs.append(f"host {h.get('id')} ({h['model']}): no `top` anchor (top of the full silhouette incl. hat) in live2d/assets.yaml")
        fr_rows.append((h.get("id"), f))
        if f["top_layer_px"] < -0.5:
            probs.append(f"host {h.get('id')}: silhouette clipped at the top by {-f['top_layer_px']:.0f} px (layer headroom {pad} px)")
        if not (0.85 * hh <= f["chest_px"] <= 1.08 * hh):
            probs.append(f"host {h.get('id')}: mid-chest at {f['chest_px']:.0f} px of a {hh} px panel (want 0.85-1.08)")
        bo = L0["breakouts"][i]
        if bo:
            others = [("header", L0["header"]), ("app screen", L0["screen"])] + ([("chat strip", L0["chat"])] if L0["chat"] else [])
            others += [(f"host {o.get('id')} panel", L0["hosts"][j]) for j, o in enumerate(c.get("hosts") or []) if j != i]
            others += [(f"host {o.get('id')} break-out", L0["breakouts"][j]) for j, o in enumerate(c.get("hosts") or []) if j != i and L0["breakouts"][j]]
            others += [(f"keep-clear '{k['name']}'", k["box"]) for k in L0["keep_clear"]]
            for nm, ob in others:
                if overlap(bo, ob):
                    probs.append(f"host {h.get('id')}: silhouette break-out {[round(v) for v in bo]} overlaps the {nm}")
    if len(fr_rows) > 1:
        tops = [f["head_top_px"] for _, f in fr_rows]
        heads = [f["head_px"] for _, f in fr_rows]
        if max(tops) - min(tops) > 0.05 * hh or max(heads) > 1.05 * min(heads):
            probs.append("hosts framed differently: head tops " + ", ".join(f"{t:.0f}" for t in tops) + " px, head heights "
                         + ", ".join(f"{x:.0f}" for x in heads) + " px")
    rows.append(("livestream-framing", "FAIL" if probs else "PASS", "; ".join(probs) if probs else
                 f"head scale {hl['head_frac']:.3f} of a {hh} px panel; " +
                 "; ".join(f"host {i}: head {f['head_top_px']:.0f}-{f['chin_px']:.0f} px, mid-chest {f['chest_px']:.0f}, silhouette top "
                           f"{f['top_px']:.0f} px" + (" (breaks out above the panel, clear)" if f['top_px'] < -0.5 else "")
                           for i, f in fr_rows)))
    # 1. screen share
    sw, sh = screen_size(c)
    frac = sw * sh / (FRAME_W * FRAME_H)
    rows.append(("livestream-screen", "FAIL" if frac < MIN_SCREEN_FRAC - 1e-9 else "PASS",
                 f"app screen {sw:.0f}x{sh:.0f} = {frac * 100:.1f}% of the frame (min {MIN_SCREEN_FRAC * 100:.0f}%)"))
    # 2. chat strip lines + truthfulness
    ch = c.get("chat") or {}
    ml = int(ch.get("max_lines", MAX_CHAT_LINES))
    if not has_chat(c):
        rows.append(("livestream-chat", "PASS", "no chat asides: no chat strip (0 lines allowed); the app screen takes the band"))
    else:
        rows.append(("livestream-chat", "FAIL" if ml > MAX_CHAT_LINES else "PASS", f"chat strip max_lines={ml} (max {MAX_CHAT_LINES})"))
    hosts = host_names(c)
    strangers = sorted({str(ln.get("user", "")) for ln in ch.get("lines") or [] if str(ln.get("user", "")).strip().lower() not in hosts})
    label = str(ch.get("scripted_label") or "").strip()
    if strangers and not label:
        rows.append(("livestream-chat-truth", "FAIL", f"chat authors {strangers} are not hosts: the strip would fake an audience. "
                     f"Use host asides only, or set chat.scripted_label (shown on screen)"))
    else:
        rows.append(("livestream-chat-truth", "PASS", f"chat carries visible label {label!r}" if strangers else
                     f"{len(ch.get('lines') or [])} chat line(s), all host asides"))
    # 2b. lint: no LIVE badge text, no viewer counts anywhere on screen
    bad = [f"{w}: {t!r}" for w, t in visible_texts(spec) if LIVE_RE.search(t) or COUNT_RE.search(t)]
    rows.append(("livestream-lint", "FAIL" if bad else "PASS",
                 ("no 'LIVE' text or viewer counts allowed (this is a recorded promo): " + "; ".join(bad)) if bad else
                 "no 'LIVE' text or viewer counts on screen"))
    # 3. side + moves + slot gap
    probs = []
    side = c.get("hosts_side", "left")
    if side not in ("left", "right"):
        probs.append(f"hosts_side must be left|right (got {side!r})")
    if slot_gap(c) < MIN_SLOT_GAP:
        probs.append(f"slot_gap {slot_gap(c):g} px < {MIN_SLOT_GAP} px")
    ms = moves(c)
    if len(ms) > 1:
        probs.append(f"{len(ms)} host moves declared; at most one slide per show")
    boundaries = {s.b0 for s in spec.shots[1:]}
    for m in ms:
        d = float(m.get("dur", 0))
        if d < MIN_MOVE_S - 1e-9:
            probs.append(f"move at beat {m.get('beat')}: {d:.2f}s is an instant flip; a side move must slide for >= {MIN_MOVE_S}s")
        if m.get("beat") not in boundaries:
            probs.append(f"move at beat {m.get('beat')} is not on a beat change (shot boundaries: {sorted(boundaries)})")
        elif spec.timeline.t(m["beat"]) + d > spec.duration + 1e-9:
            probs.append(f"move at beat {m['beat']} runs past the end of the show")
    for s in spec.shots:
        hs = s.get("hosts_side")
        if hs is None:
            continue
        u = side_at(c, spec, s.t0 + 1e-6)
        cur = side if u < 0.5 else ("right" if side == "left" else "left")
        if hs != cur:
            probs.append(f"shot {s.id}: hosts_side {hs!r} flips the hosts instantly (show has them {cur!r}); use the single `move:` slide")
    rows.append(("livestream-side", "FAIL" if probs else "PASS",
                 "; ".join(probs) if probs else f"hosts {side} for the whole show" +
                 (f", one {float(ms[0].get('dur', 0)):.2f}s off-edge slide at beat {ms[0]['beat']}" if ms else ", no slide") +
                 f"; panels {', '.join(str(g) for g in host_layout(c)['gaps'][1:]) or '-'} px apart (min {slot_gap(c):g})"))
    # 4. keep-clear: every livestream frame, nothing drawn may intersect a keep-clear rectangle on the app screen
    hits = {}
    kc = c.get("keep_clear") or []
    for k in kc:
        b = k.get("box") or []
        if len(b) != 4 or not (0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1):
            hits.setdefault("spec", []).append(f"keep_clear {k.get('name')}: box must be [x0,y0,x1,y1] within 0..1 of the screen")
    if kc and not hits:
        over = _overlay_boxes(spec, ctx)
        ls_shots = [s for s in spec.shots if s.type == "livestream"]
        for s in ls_shots:
            for f in range(s.n):
                t = s.t0 + f / spec.fps
                L = layout_at(spec, t)
                items = ([("chat strip", L["chat"])] if L["chat"] else []) + [("header", L["header"])]
                items += [(f"host {h.get('id', i)}", b) for i, (h, b) in enumerate(zip(c.get("hosts") or [], L["hosts"]))]
                items += [(f"host {h.get('id', i)} break-out", b) for i, (h, b) in enumerate(zip(c.get("hosts") or [], L["breakouts"])) if b]
                items += [(nm, b) for (nm, b, t0, t1) in over if t0 <= t < t1]
                for k in L["keep_clear"]:
                    for nm, b in items:
                        if overlap(b, k["box"]):
                            hits.setdefault(f"{nm} covers keep-clear '{k['name']}'", []).append(t)
    if hits:
        msg = "; ".join(f"{k} ({len(v)} frames, first at {v[0]:.2f}s)" if v and isinstance(v[0], float) else f"{k}: {v}" for k, v in hits.items())
        rows.append(("livestream-keep-clear", "FAIL", msg))
    else:
        rows.append(("livestream-keep-clear", "PASS", f"{len(kc)} keep-clear rect(s) uncovered on every frame" if kc else "no keep-clear rectangles declared"))
    rows += text_size_rows(spec, c)
    rows += named_rows(spec, c)
    rows += cam_rows(spec, c)
    return rows


def measure_text_rows(gray, x0, x1, y0, y1, win=2, thr=110):
    """Ascender-top -> baseline height (px) of one text line in a grey frame: rows [y0, y1] are the declared line;
    ink = pixels brighter than `thr` between columns x0..x1. Top = first row with >= 5 % of the peak ink in the window, baseline = last row
    carrying >= 40 % of the peak row ink (descenders are thin). Returns (top, base) in source rows, or None."""
    import numpy as np
    H = gray.shape[0]
    a, b = max(0, y0 - win), min(H, y1 + win + 1)
    ink = (gray[a:b, x0:x1] > thr).sum(1)
    if ink.max() <= 0:
        return None
    rows = np.nonzero(ink >= max(2, 0.05 * ink.max()))[0]      # ignore 1-px rules / carets
    heavy = np.nonzero(ink >= 0.4 * ink.max())[0]
    return a + int(rows[0]), a + int(heavy[-1])


def _gray_frame(path, t):
    import subprocess

    from . import render as R
    W, H = R.probe(path)[:2]
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-threads", "2", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                                   "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    return np.frombuffer(raw, np.uint8).reshape(H, W).astype(int), W, H


def cam_crop(cam, W, H, screen):
    """Source crop (x0, y0, bw, bh) of cam (cx, cy, w) for a screen (w, h) (a bare number = 16:9), as render.frame_cam."""
    sw, sh = (screen, screen * 9 / 16) if isinstance(screen, (int, float)) else screen
    cx, cy, cw = cam
    bw = cw * W
    bh = bw * sh / sw
    if bh > H:                      # as render.frame_cam: shrink to the full image height
        bh, bw = H, H * sw / sh
    return min(max(cx * W - bw / 2, 0), W - bw), min(max(cy * H - bh / 2, 0), H - bh), bw, bh


def element_px(path, t, cam, screen, box, src_px=None, frame=None, thr=110):
    """Rendered size of a named on-screen element of clip `path` at source time `t`, seen through `cam` on `screen`
    ((w, h) px, or a width = 16:9). `box` = [x0, y0, x1, y1] (or [top, base] = full crop width) in a frame `src_px`
    tall (scaled to the clip). Height = ascender-top -> baseline of the ink inside the box (cap height for text, glyph
    height for an icon; `thr` = ink luminance, raise it to measure a white glyph on a coloured badge). Returns dict(px, src, top, base, scale, inside) or None if there is no ink there.
    `scale` = output px per source px (the effective scale: > 1.0 means the element is upscaled = soft)."""
    g, W, H = frame if frame is not None else _gray_frame(path, t)
    bx0, by0, bw, bh = cam_crop(cam, W, H, screen)
    k = H / float(src_px or H)
    if len(box) == 4:
        x0, y0, x1, y1 = [v * k for v in box]
    else:
        x0, x1, y0, y1 = bx0, bx0 + bw, box[0] * k, box[1] * k
    m = measure_text_rows(g, int(max(x0, bx0)), int(min(x1, bx0 + bw)) or 1, int(round(y0)), int(round(y1)), thr=thr)
    if m is None:
        return None
    top, base = m
    scale = (screen if isinstance(screen, (int, float)) else screen[0]) / bw
    inside = by0 <= top and base <= by0 + bh and (len(box) == 2 or (bx0 <= x0 and x1 <= bx0 + bw and by0 <= y0 and y1 <= by0 + bh))
    return dict(px=(base - top + 1) * scale, src=base - top + 1, top=top, base=base, scale=scale, inside=inside)


def text_height(path, t, cam, screen, box, src_px=None):
    """Rendered height (output px) of one text line: `box` = [top, base] rows (or [x0, y0, x1, y1]) in a `src_px`-tall
    frame. `screen` = (w, h) or a width (16:9). See element_px."""
    return element_px(path, t, cam, screen, box, src_px)


def cam_rows(spec, c):
    """Gate livestream-cam: a screen cam crop (cx, cy, w at the screen's aspect) must fit inside its source frame
    (a crop taller than the clip would be stretched/padded). With the full-height screen, 16:9 sources need w <= ~0.785."""
    from . import render as R
    bad, n = [], 0
    for s in [s for s in spec.shots if s.type == "livestream"]:
        sc = s.cfg.get("screen") or {}
        if not sc.get("source") or not sc.get("cam"):
            continue
        try:
            path = spec.footage_path(sc["source"])
        except Exception:  # noqa: BLE001
            continue
        if not path or not os.path.exists(path):
            continue
        W, H = R.probe(path)[:2]
        sw, sh = screen_size(c)
        bw = sc["cam"][2] * W
        n += 1
        if bw > W + 0.5 or bw * sh / sw > H + 0.5:
            bad.append(f"shot {s.id}: cam w={sc['cam'][2]} needs a {bw:.0f}x{bw * sh / sw:.0f} crop of a {W}x{H} clip "
                       f"(max w {min(1.0, H * sw / sh / W):.3f})")
    if not n:
        return []
    return [("livestream-cam", "FAIL" if bad else "PASS", "; ".join(bad) if bad else f"{n} screen cams fit their sources")]


MIN_NAMED_PX = 18     # named-element cap height at 1080p (UX review T1/T4)


def named_rows(spec, c):
    """Gates for elements a VO line names (`named: [{name, box: [x0, y0, x1, y1], src_px, at, min_px}]` on a livestream
    shot; `at` = source time, default the shot's first displayed frame):
      livestream-named  FAIL if an element renders under min_px (default 18; 0 = a container that only has to be fully
                        in frame, e.g. the whole card) or is not fully inside the screen crop;
      named-upscale     WARN if an element's effective scale (output px / source px) is above 1.0 = upscaled, soft text
                        (prefer a DPR 2 / 4K take)."""
    out, up = [], []
    for s in [s for s in spec.shots if s.type == "livestream" and s.cfg.get("named")]:
        sc = s.cfg.get("screen") or {}
        src = sc.get("source")
        try:
            path = spec.footage_path(src) if src else None
        except Exception as e:  # noqa: BLE001
            out.append(f"!shot {s.id}: cannot measure ({e})"); continue
        if not path or not os.path.exists(path):
            out.append(f"!shot {s.id}: cannot measure, footage {src!r} missing"); continue
        cam = sc.get("cam", (0.5, 0.5, 1.0))
        frames = {}
        for el in s.cfg["named"]:
            t = float(el.get("at", float(sc.get("t_in", 0.0)) + 0.05))
            if t not in frames:
                frames[t] = _gray_frame(path, t)
            m = element_px(path, t, cam, screen_size(c), el["box"], el.get("src_px"), frame=frames[t], thr=el.get("thr", 110))
            nm = el.get("name", "?")
            if m is None:
                out.append(f"!shot {s.id} {nm!r}: no ink in its box at {t:.2f} s"); continue
            need = el.get("min_px", MIN_NAMED_PX)
            ok = m["px"] >= need and m["inside"]
            out.append(("" if ok else "!") + f"shot {s.id} {nm!r}: {m['src']} src px x{m['scale']:.2f} = {m['px']:.1f} px (min {need})"
                       + ("" if m["inside"] else ", NOT fully in the screen crop"))
            if m["scale"] > 1.0 + 1e-6:
                up.append(f"shot {s.id} {nm!r} x{m['scale']:.2f} ({src})")
    rows = []
    if out:
        bad = [m for m in out if m.startswith("!")]
        rows.append(("livestream-named", "FAIL" if bad else "PASS", "; ".join(m.lstrip("!") for m in out)))
        rows.append(("named-upscale", "WARN" if up else "PASS",
                     ("upscaled (effective scale > 1.0, soft text; prefer a DPR 2 / 4K take): " + "; ".join(up)) if up
                     else "every named element at effective scale <= 1.0"))
    return rows


def text_size_rows(spec, c):
    """Gate livestream-text-size: shots with `text_check: {box: [top, base], src_px: H, min_px: N}` (the key text line's
    ascender-top / baseline rows in an H-px-tall source frame) must render that line >= N px tall inside the screen.
    Measured on the real source frame at the shot's first displayed time, through the shot's cam and screen size."""
    out = []
    for s in [s for s in spec.shots if s.type == "livestream" and s.cfg.get("text_check")]:
        tc, sc = s.cfg["text_check"], s.cfg.get("screen") or {}
        src = sc.get("source")
        if not src:
            out.append(f"!shot {s.id}: text_check without a screen source"); continue
        try:
            path = spec.footage_path(src)
        except Exception as e:  # noqa: BLE001
            out.append(f"!shot {s.id}: cannot measure ({e})"); continue
        if not path or not os.path.exists(path):
            out.append(f"!shot {s.id}: cannot measure, footage {src!r} missing"); continue
        m = text_height(path, float(sc.get("t_in", 0.0)) + 0.05, sc.get("cam", (0.5, 0.5, 1.0)), screen_size(c), tc["box"], tc.get("src_px"))
        if m is None:
            out.append(f"!shot {s.id}: no text ink near rows {tc['box']} of {src}"); continue
        need = tc.get("min_px", 24)
        ok = m["px"] >= need and m["inside"]
        out.append(("" if ok else "!") + f"shot {s.id}: text line rows {m['top']}-{m['base']} of {src} ({m['base'] - m['top'] + 1} px) "
                   f"x{m['scale']:.2f} = {m['px']:.1f} px (min {need})" + ("" if m["inside"] else ", OUTSIDE the screen crop"))
    if not out:
        return []
    bad = [m for m in out if m.startswith("!")]
    return [("livestream-text-size", "FAIL" if bad else "PASS", "; ".join(m.lstrip("!") for m in out))]


def _overlay_boxes(spec, ctx):
    """(name, box, t0_global, t1_global) for every overlay of every shot (alpha bbox of the built layer)."""
    from .overlays import build_overlays
    from .render import RenderContext
    ctx1 = (ctx or RenderContext.from_spec(spec)).with_scale(1)
    out = []
    for s in spec.shots:
        for o in build_overlays(ctx1, s.get("overlays")):
            bb = o.layer.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
            if bb:
                t0, t1 = (0.0, s.dur) if getattr(o, "always", False) else (o.t0, min(o.t1, s.dur))
                out.append((f"shot {s.id} {o.role} {o.cfg.get('text', '')!r}", list(bb), s.t0 + t0, s.t0 + t1))
    return out
