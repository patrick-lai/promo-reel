"""How far a draft's look is from the references, as a number: brightness, hue, colour palette, saturation, contrast and where the light sits
in the frame, compared as distributions between two stills. 0 = the same statistics, 1 = as far apart as it gets. No model call: the same
two stills always give the same number, so it can hold a draft to "no further from the references than the best draft so far".

    promo flow look [--draft N] [--story A]     each scene's middle frame of the draft against its nearest reference cut still
                                                 (reference/<id>/cuts/*.jpg), pair images in flow/look/d<N>/ (reference LEFT, draft RIGHT)
"""
from __future__ import annotations

import glob
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

WEIGHTS = dict(luma=0.25, hue=0.2, palette=0.3, saturation=0.1, contrast=0.05, rows=0.1)
SIZE = 256
BINS = 32
HUE_BINS = 24
ROWS = 32


def _arr(path):
    im = Image.open(path).convert("RGB")
    im.thumbnail((SIZE, SIZE))
    return np.asarray(im, dtype=np.float64) / 255.0


def _lab(rgb):
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    xyz = lin @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def _hist(x, bins, lo, hi, w=None):
    h, _ = np.histogram(x, bins=bins, range=(lo, hi), weights=w)
    s = h.sum()
    return h / s if s else np.full(bins, 1.0 / bins)


def _w1(p, q):
    """Wasserstein-1 between two histograms over the same bins, as a fraction of the range (0..1)."""
    return float(np.abs(np.cumsum(p - q)).sum() / len(p))


def _circular_w1(p, q):
    """Earth mover's distance on a circle (hue wraps around): the linear one minus the best constant shift, over half the circle."""
    c = np.cumsum(p - q)
    return float(np.abs(c - np.median(c)).sum() / len(p) / 0.5)


def stats(path):
    rgb = _arr(path)
    lab = _lab(rgb)
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.where(mx > 0, mx, 1), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    hue = (np.degrees(np.arctan2(np.sqrt(3) * (g - b), 2 * r - g - b)) + 360) % 360
    L = lab[..., 0] / 100.0
    rows = np.array([band.mean() for band in np.array_split(L, ROWS, axis=0)])
    return dict(luma=_hist(L, BINS, 0, 1), hue=_hist(hue, HUE_BINS, 0, 360, sat),
                a=_hist(lab[..., 1], BINS, -100, 100), b=_hist(lab[..., 2], BINS, -100, 100), saturation=_hist(sat, BINS, 0, 1), contrast=float(L.std()), rows=rows)


def distance(a, b):
    """Look distance between two stills (paths), 0..1, and its parts."""
    sa, sb = stats(a), stats(b)
    # Real footage keeps Lab a/b inside about a quarter of their range, so the palette distance is scaled by 4 to use the whole 0..1.
    parts = dict(luma=_w1(sa["luma"], sb["luma"]), hue=min(1.0, _circular_w1(sa["hue"], sb["hue"])),
                 palette=min(1.0, (_w1(sa["a"], sb["a"]) + _w1(sa["b"], sb["b"])) / 2 * 4), saturation=_w1(sa["saturation"], sb["saturation"]),
                 contrast=min(1.0, abs(sa["contrast"] - sb["contrast"]) / 0.5), rows=float(np.abs(sa["rows"] - sb["rows"]).mean()))
    return round(sum(WEIGHTS[k] * v for k, v in parts.items()), 4), {k: round(v, 4) for k, v in parts.items()}


def reference_stills(project_dir):
    return sorted(glob.glob(os.path.join(project_dir, "reference", "*", "cuts", "*.jpg")))


def nearest(still, refs):
    best = min(((distance(still, r)[0], r) for r in refs), key=lambda x: x[0])
    return best


def pair_image(ref, draft, out, h=270):
    a, b = Image.open(ref).convert("RGB"), Image.open(draft).convert("RGB")
    a = a.resize((max(1, a.width * h // a.height), h))
    b = b.resize((max(1, b.width * h // b.height), h))
    canvas = Image.new("RGB", (a.width + b.width + 8, h), (12, 12, 14))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (a.width + 8, 0))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    canvas.save(out, quality=88)
    return out


def measure_draft(video, scenes, refs, out_dir):
    """{scene id: {d, ref, pair}} and the mean for one draft: each scene's middle frame against its nearest reference still. A scene the
    draft is too short to reach has no frame and is left out; None when no frame could be read at all."""
    from . import watch as W
    per = {}
    with tempfile.TemporaryDirectory(prefix="look-") as tmp:
        for s in scenes:
            t = (float(s["t"][0]) + float(s["t"][1])) / 2
            still = Path(tmp) / f"{s['id']}.jpg"
            if not W.grab(Path(video), t, still, 640):
                continue
            d, ref = nearest(str(still), refs)
            per[str(s["id"])] = dict(d=d, ref=ref, t=round(t, 2), pair=pair_image(ref, str(still), os.path.join(out_dir, f"{s['id']}.jpg")))
    if not per:
        return None
    return dict(mean=round(sum(x["d"] for x in per.values()) / len(per), 4), scenes=per)
