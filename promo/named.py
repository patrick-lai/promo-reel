"""Named on-screen elements: the app text a caption / card / VO line names must be readable in the cut.

Same contract and measurement as the talk show's livestream gate (live2d-renderer `promo/livestream.py`):
    named: [{name, box: [x0, y0, x1, y1], src_px, at, t, min_px, thr}]
  box     rect in a source frame `src_px` tall (default: the clip's own height; scaled to the clip)
  at      source seconds to measure at; or `t` = shot-local output seconds (mapped through the shot's segments)
  min_px  minimum rendered cap height at 1080p (default MIN_NAMED_PX = 18; 0 = only has to be fully in frame)
  thr     ink luminance (text brighter than thr; raise it for a white glyph on a coloured badge)
Height = ascender-top -> baseline of the ink inside the box (cap height for text). Effective scale = output px per
source px: > 1.0 means the element is upscaled (soft text; prefer a DPR 2 take).
"""
from __future__ import annotations

import subprocess

import numpy as np

MIN_NAMED_PX = 18     # named-element cap height at 1080p (UX review T1/T4), same as the talk show

_FRAMES = {}


def measure_text_rows(gray, x0, x1, y0, y1, win=2, thr=110):
    """Ascender-top -> baseline (top, base) source rows of one text line inside rows [y0, y1], columns x0..x1; ink =
    pixels brighter than `thr`. Top = first row with >= 5 % of the peak row ink, baseline = last row with >= 40 %
    (descenders are thin). None if there is no ink."""
    H = gray.shape[0]
    a, b = max(0, y0 - win), min(H, y1 + win + 1)
    x0, x1 = max(0, int(x0)), max(int(x0) + 1, int(x1))
    ink = (gray[a:b, x0:x1] > thr).sum(1)
    if ink.size == 0 or ink.max() <= 0:
        return None
    rows = np.nonzero(ink >= max(2, 0.05 * ink.max()))[0]
    heavy = np.nonzero(ink >= 0.4 * ink.max())[0]
    return a + int(rows[0]), a + int(heavy[-1])


def gray_frame(path, t):
    """(gray int array, W, H) of clip/still `path` at source seconds t (cached)."""
    k = (path, round(float(t), 3))
    if k not in _FRAMES:
        from . import render as R
        if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            from PIL import Image
            im = Image.open(path).convert("L")
            _FRAMES[k] = (np.asarray(im).astype(int), im.width, im.height)
        else:
            W, H = R.probe(path)[:2]
            raw = subprocess.check_output(["ffmpeg", "-v", "error", "-threads", "2", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                                           "-f", "rawvideo", "-pix_fmt", "gray", "-"])
            _FRAMES[k] = (np.frombuffer(raw, np.uint8).reshape(H, W).astype(int), W, H)
        if len(_FRAMES) > 64:
            _FRAMES.pop(next(iter(_FRAMES)))
    return _FRAMES[k]


def crop_rect(cam, W, H, vp_w, vp_h):
    """Source crop (x0, y0, bw, bh) of camera (cx, cy, w) shown in a vp_w x vp_h viewport (as render.frame_cam)."""
    cx, cy, cw = cam
    bw = cw * W
    bh = bw * vp_h / vp_w
    return min(max(cx * W - bw / 2, 0), W - bw), min(max(cy * H - bh / 2, 0), H - bh), bw, bh


def element_px(frame, cam, viewport, box, src_px=None, thr=110):
    """Rendered size of a named element. frame = (gray, W, H); cam = (cx, cy, w); viewport = (vp_w, vp_h) in 1080p
    canvas px; box = [x0, y0, x1, y1] in a `src_px`-tall frame. Returns dict(px, src, top, base, scale, inside, out_box)
    (out_box in viewport px) or None if there is no ink in the box."""
    g, W, H = frame
    vw, vh = viewport
    bx0, by0, bw, bh = crop_rect(cam, W, H, vw, vh)
    k = H / float(src_px or H)
    x0, y0, x1, y1 = [v * k for v in box]
    m = measure_text_rows(g, max(x0, bx0), min(x1, bx0 + bw), int(round(y0)), int(round(y1)), thr=thr)
    if m is None:
        return None
    top, base = m
    scale = vw / bw
    inside = bx0 - 0.5 <= x0 and x1 <= bx0 + bw + 0.5 and by0 - 0.5 <= y0 and y1 <= by0 + bh + 0.5
    ob = [(x0 - bx0) * scale, (y0 - by0) * scale, (x1 - bx0) * scale, (y1 - by0) * scale]
    return dict(px=round((base - top + 1) * scale, 2), src=base - top + 1, top=top, base=base, scale=round(scale, 4),
                inside=bool(inside), out_box=[round(v, 1) for v in ob])
