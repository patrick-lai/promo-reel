"""'Livestream' layout: app screen (>= 55 % of the frame) + Live2D hosts on one side + a chat strip (<= 4 lines).

Spec (show level, in promo.yaml):

    livestream:
      hosts_side: left            # left | right for the whole show (default left)
      move: {beat: 16, dur: 0.6}  # optional: ONE slide of the hosts to the other side, >= 0.5 s, starting on a shot
                                  # boundary beat. No second move, no instant flip (`promo check` fails on either).
      screen: {w: 1440}           # 16:9 app screen width in 1920-canvas px (area must stay >= 55 % of the frame)
      margin: 24
      keep_clear:                 # rectangles on the APP SCREEN (normalised 0..1 of the screen) that nothing may cover
        - {name: status-corner, box: [0.80, 0.0, 1.0, 0.14]}
      chat: {max_lines: 4, lines: [{t: 1.0, user: mika, text: "hi!"}]}       # t = global seconds
      title: "LIVE: ..."          # header in the host column (optional)
      hosts:
        - {id: a, model: hiyori, wav: media/host_a.wav, name: Hiyori, seed: 11}
        - {id: b, model: mao, wav: media/host_b.wav, name: Mao, seed: 22}

Geometry lives here (one function, `layout_at`) and is shared by the renderer (shots/livestream.py) and the QA
gate (`check`), so what is checked is what is drawn. All boxes are [x0, y0, x1, y1] in 1920x1080 canvas units.
"""
from __future__ import annotations

from .render import ease

FRAME_W, FRAME_H = 1920, 1080
MIN_SCREEN_FRAC = 0.55
MAX_CHAT_LINES = 4
MIN_MOVE_S = 0.5
HOST_W, HOST_H = 420, 500         # host layer size (canvas px): head-and-shoulders framing


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


def _side_pos(c, side):
    """Static boxes for hosts on `side` (left|right)."""
    margin = float(c.get("margin", 24))
    sw, sh = screen_size(c)
    hosts = c.get("hosts") or []
    col_w = FRAME_W - sw - 2 * margin
    if side == "left":
        sx0 = FRAME_W - margin - sw
        col0 = 0.0
    else:
        sx0 = margin
        col0 = sx0 + sw + margin
    screen = [sx0, margin, sx0 + sw, margin + sh]
    n = len(hosts)
    hb = []
    if n:
        # Staggered duo in the host column: host 0 upper, host 1 lower and in front (it may overlap host 0's chest,
        # never a face). Side-by-side busts do not fit next to a >= 55 % screen without the hosts covering each other's faces.
        top, bottom = 168.0, FRAME_H
        ys = [bottom - HOST_H] if n == 1 else [top + i * (bottom - HOST_H - top) / (n - 1) for i in range(n)]
        for i in range(n):
            x0 = (col_w - HOST_W) / 2 + (0 if n == 1 else (-12 + 24 * i / (n - 1)))
            if side == "right":
                x0 = FRAME_W - x0 - HOST_W            # mirror into the right-hand column
            hb.append([x0, ys[i], x0 + HOST_W, ys[i] + HOST_H])
    chat = [screen[0], screen[3] + 14, screen[2], FRAME_H - 14]
    hdr_x0 = col0 + 18 if side == "left" else col0 + 6
    header = [hdr_x0, margin, hdr_x0 + col_w - 24, margin + 150]
    return dict(screen=screen, hosts=hb, chat=chat, header=header)


def side_at(c, spec, t):
    """Hosts side as a float: 0 = start side, 1 = moved to the other side (eased during the single move)."""
    ms = moves(c)
    if not ms:
        return 0.0
    m = ms[0]
    t0 = spec.timeline.t(m["beat"])
    d = float(m.get("dur", 0.6))
    if t <= t0:
        return 0.0
    if d <= 0 or t >= t0 + d:
        return 1.0
    return ease((t - t0) / d)


def _lerp_box(a, b, u):
    return [a[i] + (b[i] - a[i]) * u for i in range(4)]


def layout_at(spec, t):
    """Boxes at global time t: screen, hosts[], chat, header, keep_clear[] (frame coords), hosts_z ('above'|'below').
    During the single side move the hosts and the header slide BEHIND the app screen (hosts_z = 'below'), so they never
    cover it; the chat strip travels with the screen."""
    c = cfg(spec)
    start = c.get("hosts_side", "left")
    other = "right" if start == "left" else "left"
    u = side_at(c, spec, t)
    A, B = _side_pos(c, start), _side_pos(c, other)
    L = dict(screen=_lerp_box(A["screen"], B["screen"], u), chat=_lerp_box(A["chat"], B["chat"], u),
             header=_lerp_box(A["header"], B["header"], u),
             hosts=[_lerp_box(a, b, u) for a, b in zip(A["hosts"], B["hosts"])],
             hosts_z="below" if 0.0 < u < 1.0 else "above", u=u)
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


# ---------------------------------------------------------------- QA gate
def check(spec, ctx=None):
    """Rows (gate, status, msg) for `promo check`. Empty if the spec has no livestream block."""
    c = cfg(spec)
    if not c:
        return []
    rows = []
    # 0. Live2D licence: only Live2D Original Characters, each with a recorded copyright notice; credit drawn in-frame
    from . import live2d as L2
    lic = []
    for h in c.get("hosts") or []:
        try:
            m = L2.model_entry(h["model"])
            if not m.get("credit") or not m.get("source_url"):
                lic.append(f"{h['model']}: missing credit/source_url in live2d/assets.yaml")
        except L2.Live2DError as e:
            lic.append(str(e))
    rows.append(("livestream-licence", "FAIL" if lic else "PASS",
                 "; ".join(lic) if lic else f"{len(c.get('hosts') or [])} Live2D Original Character host(s); notice drawn in the header; "
                 f"put the long notice in the video description (docs/live2d-licences.md)"))
    # 1. screen share
    sw, sh = screen_size(c)
    frac = sw * sh / (FRAME_W * FRAME_H)
    rows.append(("livestream-screen", "FAIL" if frac < MIN_SCREEN_FRAC - 1e-9 else "PASS",
                 f"app screen {sw:.0f}x{sh:.0f} = {frac * 100:.1f}% of the frame (min {MIN_SCREEN_FRAC * 100:.0f}%)"))
    # 2. chat strip lines
    ch = c.get("chat") or {}
    ml = int(ch.get("max_lines", MAX_CHAT_LINES))
    rows.append(("livestream-chat", "FAIL" if ml > MAX_CHAT_LINES else "PASS",
                 f"chat strip max_lines={ml} (max {MAX_CHAT_LINES})"))
    # 3. side + moves
    probs = []
    side = c.get("hosts_side", "left")
    if side not in ("left", "right"):
        probs.append(f"hosts_side must be left|right (got {side!r})")
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
    # per-shot side overrides are instant flips unless they agree with the show-level side at that moment
    for s in spec.shots:
        hs = s.get("hosts_side")
        if hs is None:
            continue
        u = side_at(c, spec, s.t0 + 1e-6)
        cur = side if u < 0.5 else ("right" if side == "left" else "left")
        if hs != cur:
            probs.append(f"shot {s.id}: hosts_side {hs!r} flips the hosts instantly (show has them {cur!r}); use the single `move:` slide")
    rows.append(("livestream-side", "FAIL" if probs else "PASS",
                 "; ".join(probs) if probs else f"hosts {side} for the whole show" + (f", one {float(ms[0].get('dur', 0)):.2f}s slide at beat {ms[0]['beat']}" if ms else "")))
    # 4. keep-clear: every frame, nothing drawn above the screen may intersect a keep-clear rectangle
    hits = {}
    kc = c.get("keep_clear") or []
    for k in kc:
        b = k.get("box") or []
        if len(b) != 4 or not (0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1):
            hits.setdefault("spec", []).append(f"keep_clear {k.get('name')}: box must be [x0,y0,x1,y1] within 0..1 of the screen")
    if kc and not hits:
        over = _overlay_boxes(spec, ctx)
        for f in range(int(round(spec.duration * spec.fps))):
            t = f / spec.fps
            L = layout_at(spec, t)
            items = [("chat strip", L["chat"])]
            if L["hosts_z"] == "above":         # during the slide hosts + header pass BEHIND the screen
                items += [("header", L["header"])]
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
