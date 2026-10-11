"""Physical motion for the camera and overlays: the opt-in `motion:` block of a spec (or of one shot).

    motion:
      camera: spring        # glide through camera keys instead of stopping dead at each one
      overlay: settle       # captions / text rise a few px and settle as they fade in, entrances staggered
      punch: 0.015          # per shot: a short scale accent on the cut (fraction of the box width)

Ideas taken from the anatomy skill's motion rules (github.com/wheresryan22/anatomy, MIT): parts follow their targets on
critically damped springs so velocity never jumps, accents are envelopes with a short attack and an exponential decay,
and pieces that arrive together are staggered. Without a `motion:` block every renderer keeps its closed-form easing.
"""
from __future__ import annotations

import math

import numpy as np

CAM_TAU = 0.08          # follower time constant (s): enough lag to round off the spline's knots, not enough to miss a key
CAM_ZETA = 0.9          # a hint of weight: a stop settles with a barely visible overshoot
SUBSTEPS = 4            # spring integration steps per output frame
OVERLAY_RISE = 8        # px (1080 canvas) a settling overlay travels up while it fades in
OVERLAY_TAU = 0.12
STAGGER = 0.05          # s between overlays that enter on the same frame
PUNCH_RISE, PUNCH_FALL = 0.04, 0.18


def resolve(spec, shot_cfg=None):
    """The motion settings in force for one shot: the shot's own `motion:` keys over the spec's."""
    return {**((spec.raw.get("motion") if spec else None) or {}), **((shot_cfg or {}).get("motion") or {})}


def smoothstep(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def burst(age, rise=PUNCH_RISE, fall=PUNCH_FALL):
    """Accent envelope: 0 before the event, a smoothstep attack (zero slope at onset) to 1 at `rise`, then exponential decay."""
    if age <= 0:
        return 0.0
    if age < rise:
        return smoothstep(age / rise)
    return math.exp(-(age - rise) / fall)


def settle(age, tau=OVERLAY_TAU):
    """Fraction of an offset still left `age` s after release on a critically damped spring (starts at rest, never overshoots)."""
    if age <= 0:
        return 1.0
    return (1 + age / tau) * math.exp(-age / tau)


def _tangents(t, y):
    """Monotone (Fritsch-Butland) slopes: continuous velocity through each key, zero at the ends and at holds or reversals."""
    h = np.diff(t)
    d = np.diff(y) / h
    m = np.zeros_like(y)
    for k in range(1, len(y) - 1):
        if d[k - 1] * d[k] > 0:
            m[k] = 3 * (h[k - 1] + h[k]) / ((2 * h[k] + h[k - 1]) / d[k - 1] + (h[k] + 2 * h[k - 1]) / d[k])
    return m


def _hermite(t, y, m, s):
    if s <= t[0]:
        return y[0]
    if s >= t[-1]:
        return y[-1]
    k = int(np.searchsorted(t, s, side="right")) - 1
    h = t[k + 1] - t[k]
    u = (s - t[k]) / h
    h00, h10 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u
    h01, h11 = -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
    return h00 * y[k] + h10 * h * m[k] + h01 * y[k + 1] + h11 * h * m[k + 1]


def spring_cam(keys, total, fps):
    """Camera function t -> (cx, cy, w) for keys [(t, cx, cy, w, ...)]: a monotone spline through the keys (zoom in log
    width, so a push-in keeps one rate as it tightens), followed by a critically damped spring that rounds its knots.
    The spline is read 2*zeta*tau ahead, the follower's lag on a steady move, so the camera still passes each key on time."""
    ks = sorted(keys, key=lambda k: k[0])
    t = np.array([k[0] for k in ks], float)
    y = np.array([(k[1], k[2], math.log(k[3])) for k in ks], float)
    if len(ks) == 1:
        return lambda _t: tuple(ks[0][1:4])
    m = np.stack([_tangents(t, y[:, c]) for c in range(3)], axis=1)
    w_max = max(k[3] for k in ks)
    dt = 1 / (fps * SUBSTEPS)
    omega, lead = 1 / CAM_TAU, 2 * CAM_ZETA * CAM_TAU
    n = int(math.ceil(total / dt)) + 1
    out = np.empty((n, 3))
    x, v = y[0].copy(), np.zeros(3)
    for i in range(n):
        out[i] = x
        target = _hermite(t, y, m, i * dt + lead)
        v += (omega * omega * (target - x) - 2 * CAM_ZETA * omega * v) * dt
        x = x + v * dt
    out[:, 2] = np.minimum(np.exp(out[:, 2]), w_max)     # the settle's overshoot must never widen the box past the widest key

    def at(s):
        r = out[min(max(int(round(s / dt)), 0), n - 1)]
        return float(r[0]), float(r[1]), float(r[2])
    return at
