"""Paint-race glitch scan for screen captures.

A headless-browser screenshot taken before the compositor finished painting shows half-drawn layers: tiles of a panel's
background missing so whatever is behind it shows through, a header gone for one frame. In a recording that is a ONE-FRAME
glitch: the frame differs from both neighbours while the neighbours match each other. UI motion never looks like that
(a change persists, or the neighbours differ too), so the pattern is a reliable tell.

`scan(path)` finds such frames on a small grey proxy of the clip. `promo footage add` / `promo footage scan` report them and
`promo check` gates on them (`footage-glitch`) for every referenced capture. The fix is to re-record with the paint-safe
recorder (`capture/lib/recorder.mjs`); never paint over a frame (rule 2). A reviewed false positive is listed in the clip's
manifest entry as `glitch_ok: [frame, ...]`.
"""
from __future__ import annotations

import json
import os
import subprocess

import numpy as np

SCAN_W, SCAN_H = 480, 270
LEVEL = 12             # grey levels: a pixel "changed" above this (encoder noise and dithering stay below)
MIN_AREA = 0.004       # a glitch changes at least this fraction of the frame against both neighbours
NEIGHBOUR_RATIO = 4    # ... and the neighbours differ from each other at least this many times less
STILL_EXT = (".png", ".jpg", ".jpeg", ".webp")


def gray_frames(path, w=SCAN_W, h=SCAN_H):
    """(frames uint8 [n, h, w], fps) of a video, scaled down with area averaging."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    probe = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                                     "-of", "default=nw=1:nk=1", path]).decode().strip()
    n, d = probe.split("/")
    return np.frombuffer(out, np.uint8).reshape(-1, h, w), float(n) / float(d)


def find(frames, fps):
    """One-frame glitches in a [n, h, w] grey stack: [{frame, t, area, box}] with box = normalised [x0, y0, x1, y1]."""
    f = frames.astype(np.int16)
    h, w = f.shape[1:]
    hits = []
    for i in range(1, len(f) - 1):
        a = np.abs(f[i] - f[i - 1]) > LEVEL
        b = np.abs(f[i] - f[i + 1]) > LEVEL
        da, db = a.mean(), b.mean()
        if min(da, db) < MIN_AREA:
            continue
        dn = (np.abs(f[i - 1] - f[i + 1]) > LEVEL).mean()
        if dn * NEIGHBOUR_RATIO > min(da, db):
            continue
        ys, xs = np.nonzero(a & b)
        box = [round(xs.min() / w, 3), round(ys.min() / h, 3), round((xs.max() + 1) / w, 3), round((ys.max() + 1) / h, 3)] if len(xs) else None
        hits.append(dict(frame=i, t=round(i / fps, 3), area=round(float(min(da, db)), 4), box=box))
    return hits


def scan(path):
    """{frames, fps, glitches} for a video file; stills have nothing to scan."""
    if path.lower().endswith(STILL_EXT):
        return dict(frames=1, fps=None, glitches=[])
    frames, fps = gray_frames(path)
    return dict(frames=int(len(frames)), fps=round(fps, 3), glitches=find(frames, fps))


def describe(glitches, limit=6):
    """'frame 377 (12.57 s), frame 60 (2.00 s), ... (+4 more)'."""
    s = ", ".join(f"frame {g['frame']} ({g['t']:.2f} s)" for g in glitches[:limit])
    return s + (f" (+{len(glitches) - limit} more)" if len(glitches) > limit else "")


# ---------------------------------------------------------------- per-project cache + gate
def _cache_file(spec):
    return os.path.join(spec.build, "footage-glitch.json")


def cached_scan(spec, cid, path, sha, cache=None):
    """scan() result for a manifest clip, reused from build/footage-glitch.json while its sha256 is unchanged."""
    own = cache is None
    if own:
        try:
            cache = json.load(open(_cache_file(spec)))
        except (OSError, ValueError):
            cache = {}
    hit = cache.get(cid)
    if hit and hit.get("sha256") == sha:
        return hit
    res = dict(scan(path), sha256=sha)
    cache[cid] = res
    if own:
        save_cache(spec, cache)
    return res


def save_cache(spec, cache):
    os.makedirs(spec.build, exist_ok=True)
    with open(_cache_file(spec), "w") as f:
        json.dump(cache, f, indent=1, sort_keys=True)


def findings(spec, clip_ids=None):
    """['<id>: one-frame paint glitches at ...', ...] for referenced screen captures (generated plates are not captures)."""
    from . import footage as FT
    man = FT.load(spec)
    try:
        cache = json.load(open(_cache_file(spec)))
    except (OSError, ValueError):
        cache = {}
    out = []
    for cid in sorted(clip_ids if clip_ids is not None else FT.referenced(spec)):
        c = man.get(cid)
        if not c or c.get("generated"):
            continue
        path = FT.expand_env(c["path"])
        if not os.path.exists(path):
            continue                       # the footage gate reports missing files
        res = cached_scan(spec, cid, path, c.get("sha256"), cache)
        ok = {int(x) for x in (c.get("glitch_ok") or [])}
        bad = [g for g in res["glitches"] if g["frame"] not in ok]
        if bad:
            out.append(f"{cid}: {len(bad)} one-frame paint glitch{'es' if len(bad) > 1 else ''} at {describe(bad)}")
    save_cache(spec, cache)
    return out
