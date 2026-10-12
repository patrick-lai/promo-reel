"""Film bookends: an eased intro (float-in) and an eased outro (settle, then picture and music fade out together).

    intro: {dur: 1.1, ease: out, rise: 0.03, from_scale: 0.94}   the first shot floats in: from black, its panel rising and growing into place
    outro: {hold_s: 1.5, fade_s: 1.8, ease: inout}               the last shot holds `hold_s` settled, then picture AND mix fade over `fade_s`

Where they come from, first match wins:
    promo.yaml  output: {intro: {...}, outro: {...}}            per project (false = none: a hard open / a hard end)
    promo.yaml  style: {bookends: {intro: ..., outro: ...}}     per preset (a style preset's own file)
    the craft dialect of `plan.designed`                        ethereal ships both (`ETHEREAL`); kinetic and plain specs have none

The picture (`cinema` shots, promo/shots/cinema.py) and the audio (promo/mix.py) read the SAME `fade_gain`, so a frame at time t is
as dark as the music is quiet at t. The audio fade needs audio under it: `extend_tail` holds the music's last bars until the film
ends so the fade is a fade, never a cut.
"""
from __future__ import annotations

import numpy as np

ETHEREAL = dict(intro=dict(dur=1.1, ease="out", rise=0.03, from_scale=0.94),
                outro=dict(hold_s=1.5, fade_s=1.8, ease="inout"))
BY_DIALECT = {"ethereal": ETHEREAL}
EASES = ("out", "inout", "in", "linear")
_ALIAS = {"smooth": "inout", "ease": "inout", "in-out": "inout", "ease-out": "out", "ease-in-out": "inout", "cubic": "out"}


def norm_ease(kind):
    k = str(kind or "inout").lower()
    k = _ALIAS.get(k, k)
    return k if k in EASES else "inout"


def curve(p, kind="inout"):
    """0..1 -> 0..1. `out` = ease-out cubic (fast start, soft landing), `inout` = smootherstep (zero velocity at both ends)."""
    p = min(max(float(p), 0.0), 1.0)
    k = norm_ease(kind)
    if k == "linear":
        return p
    if k == "out":
        return 1.0 - (1.0 - p) ** 3
    if k == "in":
        return p ** 3
    return p * p * p * (p * (p * 6.0 - 15.0) + 10.0)


def _block(v, default):
    if v is False or v == 0:
        return None
    d = dict(default)
    if isinstance(v, dict):
        d.update({k: x for k, x in v.items() if x is not None})
    return d


def resolve(raw):
    """{'intro': {...} | None, 'outro': {...} | None} for a spec's raw dict (`{}` / None: neither)."""
    raw = raw if isinstance(raw, dict) else {}
    out_cfg = raw.get("output") or {}
    st = (raw.get("style") or {}).get("bookends") or {}
    dn = (((raw.get("plan") or {}).get("designed") or {}).get("dialect") or {}).get("name")
    base = BY_DIALECT.get(dn) or {}
    res = {}
    for key in ("intro", "outro"):
        res[key] = dict(base[key]) if base.get(key) else None
        for src in (out_cfg.get(key), st.get(key)):
            if src is not None:
                res[key] = _block(src, base.get(key) or ETHEREAL[key])
                break
        b = res[key]
        if b:
            b["ease"] = norm_ease(b.get("ease", "out" if key == "intro" else "inout"))
    if res["intro"]:
        res["intro"]["dur"] = max(float(res["intro"]["dur"]), 0.05)
    if res["outro"]:
        res["outro"]["fade_s"] = max(float(res["outro"]["fade_s"]), 0.05)
        res["outro"]["hold_s"] = max(float(res["outro"].get("hold_s", 0.0)), 0.0)
    return res


def fade_gain(t, dur, fade, kind="inout"):
    """Brightness / amplitude (0..1) at film time t of a fade that reaches 0 at `dur` and starts `fade` s earlier."""
    if not fade:
        return 1.0
    return curve((dur - t) / fade, kind)


def fade_in_gain(t, fade, kind="out"):
    return 1.0 if not fade else curve(t / fade, kind)


def fade_out_array(n, sr, fade, kind="inout"):
    """Per-sample gain of length n: 1 until the last `fade` s, then `fade_gain` down to (almost) 0 at the end."""
    g = np.ones(n)
    k = min(n, int(round(fade * sr)))
    if k > 0:
        t_left = np.arange(k, 0, -1) / float(sr)
        g[n - k:] = [curve(x / fade, kind) for x in t_left]
    return g


def _xfade_append(a, b, xf):
    if xf < 2 or len(a) < xf or len(b) < xf:
        return np.vstack([a, b])
    w = np.linspace(0.0, np.pi / 2, xf)
    mid = a[-xf:] * np.cos(w)[:, None] + b[:xf] * np.sin(w)[:, None]
    return np.vstack([a[:-xf], mid, b[xf:]])


def extend_tail(x, sr, n, floor_db=-60.0, bars_s=2.0, xf_s=0.25):
    """Make a (len, 2) music bed cover n samples. When it goes silent early (a zeroed tail, a short track) the last `bars_s` of its
    audible material is repeated with equal-power crossfades until n is covered: the outro then has music to fade, not silence."""
    x = np.asarray(x, np.float64)
    if x.ndim == 1:
        x = x[:, None]
    thr = 10 ** (floor_db / 20.0)
    loud = np.nonzero(np.abs(x[:n]).max(axis=1) > thr)[0] if len(x) else np.array([], int)
    if len(loud) == 0:
        return np.vstack([x, np.zeros((max(0, n - len(x)), x.shape[1]))])[:n]
    end = int(loud[-1]) + 1
    if end >= n - int(0.05 * sr):
        return np.vstack([x, np.zeros((max(0, n - len(x)), x.shape[1]))])[:n]
    out = x[:end]
    loop = x[max(0, end - int(bars_s * sr)):end]
    xf = min(int(xf_s * sr), len(loop) // 2)
    while len(out) < n:
        out = _xfade_append(out, loop, xf)
    return out[:n]


def rms_db(x, floor=-120.0):
    x = np.asarray(x, np.float64)
    r = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
    return max(floor, 20.0 * np.log10(r + 1e-12))
