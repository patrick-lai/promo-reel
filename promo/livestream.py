"""Talk-show layout: app screen (>= 55 % of the frame) + Live2D hosts on one side + a chat strip (<= 4 lines).

Spec (show level, in promo.yaml):

    livestream:
      hosts_side: left            # left | right for the whole show (default left). No slide by default.
      # move: {beat: 16, dur: 0.9}  # optional, discouraged: ONE side change, >= 0.5 s, starting on a shot boundary beat.
      #                             # Hosts slide OFF their frame edge, the screen crosses, hosts slide in from the other
      #                             # edge (never behind the screen). No second move, no instant flip (`promo check`).
      screen: {w: 1440}           # 16:9 app screen width in 1920-canvas px (area must stay >= 55 % of the frame)
      margin: 24
      slot_gap: 16                # px between the stacked host slots (>= 12)
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

Credits: a `live2d_credits` shot (end card) shows the full Live2D notice + model credits at body size (>= 28 px at
1080p) for >= 2 s at full opacity; `promo check` (livestream-licence) fails without it.

Geometry lives here (`layout_at`) and is shared by the renderer (shots/livestream.py) and the QA gate (`check`), so
what is checked is what is drawn. All boxes are [x0, y0, x1, y1] in 1920x1080 canvas units.
"""
from __future__ import annotations

import re

from .render import ease

FRAME_W, FRAME_H = 1920, 1080
MIN_SCREEN_FRAC = 0.55
MAX_CHAT_LINES = 4
MIN_MOVE_S = 0.5
MIN_SLOT_GAP = 12
HOST_W = 420                      # host layer width (canvas px); height follows the slot (head-and-shoulders framing)
HOSTS_TOP = 168                   # below the header
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


def screen_size(c):
    w = float((c.get("screen") or {}).get("w", 1440))
    return w, w * 9 / 16


def slot_gap(c):
    return float(c.get("slot_gap", 16))


def host_size(c):
    """(w, h) of every host layer: equal stacked slots between HOSTS_TOP and the frame bottom, `slot_gap` apart."""
    n = max(1, len(c.get("hosts") or []))
    h = (FRAME_H - HOSTS_TOP - slot_gap(c) * (n - 1)) / n
    if n == 1:
        h = min(h, 600)
    return HOST_W, int(round(h))


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
    hw, hh = host_size(c)
    hb = []
    # Stacked duo in the host column: equal slots with a `slot_gap` between them (no overlap; the upper host fades
    # out at its slot bottom). Side-by-side busts don't fit next to a >= 55 % screen without covering each other's faces.
    for i in range(n):
        y0 = FRAME_H - hh if n == 1 else HOSTS_TOP + i * (hh + slot_gap(c))
        x0 = (col_w - hw) / 2 + (0 if n == 1 else (-12 + 24 * i / (n - 1)))
        if side == "right":
            x0 = FRAME_W - x0 - hw                      # mirror into the right-hand column
        hb.append([x0, y0, x0 + hw, y0 + hh])
    chat = [screen[0], screen[3] + 14, screen[2], FRAME_H - 14]
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
        S = dict(screen=_lerp_box(A["screen"], B["screen"], u), chat=_lerp_box(A["chat"], B["chat"], u))
        hosts, hdr = [_shift(b, out_dx) for b in A["hosts"]], _shift(A["header"], out_dx)
    elif ph == 3:
        S, hosts, hdr = B, [_shift(b, in_dx * (1 - u)) for b in B["hosts"]], _shift(B["header"], in_dx * (1 - u))
    else:
        S, hosts, hdr = B, B["hosts"], B["header"]
    L = dict(screen=S["screen"], chat=S["chat"], header=hdr, hosts=hosts, phase=ph)
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
    good = [s for s in cs if credit_hold(s) >= CREDIT_MIN_HOLD - 1e-9 and float(s.get("size", 30)) >= CREDIT_MIN_PX]
    if not cs:
        lic.append("no end-card credit: add a `live2d_credits` shot (full Live2D notice + model credits)")
    elif not good:
        lic.append("; ".join(f"credit shot {s.id}: text {float(s.get('size', 30)):.0f} px (min {CREDIT_MIN_PX}), fully visible "
                             f"{credit_hold(s):.2f} s (min {CREDIT_MIN_HOLD} s)" for s in cs))
    rows.append(("livestream-licence", "FAIL" if lic else "PASS",
                 "; ".join(lic) if lic else f"{len(c.get('hosts') or [])} Live2D Original Character host(s); end-card credit shot "
                 f"{good[0].id}: {float(good[0].get('size', 30)):.0f} px, {credit_hold(good[0]):.2f} s at full opacity"))
    # 1. screen share
    sw, sh = screen_size(c)
    frac = sw * sh / (FRAME_W * FRAME_H)
    rows.append(("livestream-screen", "FAIL" if frac < MIN_SCREEN_FRAC - 1e-9 else "PASS",
                 f"app screen {sw:.0f}x{sh:.0f} = {frac * 100:.1f}% of the frame (min {MIN_SCREEN_FRAC * 100:.0f}%)"))
    # 2. chat strip lines + truthfulness
    ch = c.get("chat") or {}
    ml = int(ch.get("max_lines", MAX_CHAT_LINES))
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
                 f"; slots {slot_gap(c):g} px apart"))
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
                items = [("chat strip", L["chat"]), ("header", L["header"])]
                items += [(f"host {h.get('id', i)}", b) for i, (h, b) in enumerate(zip(c.get("hosts") or [], L["hosts"]))]
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
    return rows


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
