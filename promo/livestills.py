"""Stills of every shot while a build runs: the start, middle and end of each scene, so the person sees a scene before and while it renders,
not only after the whole draft is done.

The quick look draws just those three frames of every shot that will render (`run_shot` in sample mode, no encoding), all scenes in a minute or
two; the real render then replaces each with its own frame as it reaches it. Stills land in build/thumbs/<id>-a|b|c.jpg with an index
(stills.json), plus one filmstrip of every scene (build/thumbs/strip.jpg) that the Stage shows and the agent posts in the chat (`promo strip`).
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageEnhance

WHICH = (("a", "start"), ("b", "middle"), ("c", "end"))
THUMB_W = 480
INDEX = "stills.json"
STRIP = "strip.jpg"
TILE_W, GAP, PAD, HEAD = 256, 4, 16, 26
ONE_COLUMN_MAX = 6          # more scenes than this: two scenes side by side, so a 26-shot cut stays one readable image


def thumbs_dir(spec):
    return os.path.join(spec.build, "thumbs")


def still_path(spec, sid, which):
    return os.path.join(thumbs_dir(spec), f"{sid}-{which}.jpg")


def strip_path(spec):
    return os.path.join(thumbs_dir(spec), STRIP)


def picks(n):
    """{frame: a|b|c} of a shot of n frames: first, middle, last (a short shot keeps the earlier name of a shared frame)."""
    out = {}
    for i, w in ((0, "a"), (n // 2, "b"), (n - 1, "c")):
        out.setdefault(max(0, i), w)
    return out


def load_index(spec):
    p = os.path.join(thumbs_dir(spec), INDEX)
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return {}


def _save(path, write):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp" + os.path.splitext(path)[1]
    write(tmp)
    os.replace(tmp, path)            # the Stage or a chat post never reads half a file


def _post(shot, im, t):
    """The shot's grade and fade (applied to the finished segment by `apply_post`), so a still looks like the final picture."""
    from .cli import post_filter
    vf = post_filter({"grade": shot.cfg.get("grade")}, shot.dur)
    if vf:
        with tempfile.TemporaryDirectory() as td:
            a, b = os.path.join(td, "a.png"), os.path.join(td, "b.png")
            im.save(a)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a, "-vf", vf, b], check=True, capture_output=True)
            im = Image.open(b).convert("RGB")
    f = shot.cfg.get("fade") or {}
    k = 1.0
    if f.get("in"):
        k = min(k, t / float(f["in"]))
    if f.get("out"):
        k = min(k, (shot.dur - t) / float(f["out"]))
    return ImageEnhance.Brightness(im).enhance(max(0.0, k)) if k < 1 else im


class Stills:
    """Set as `render.PREVIEW` while shots render. `on_change(now)` gets {id, label, frac, which, still, strip, look} after every still and
    {id, label, frac} about once a second of picture; it must not block (the build's job only records it, its heartbeat publishes)."""

    def __init__(self, spec, sample=False, ids=None, on_change=None):
        self.spec, self.sample, self.ids, self.on_change = spec, sample, ids, on_change
        self.index = load_index(spec)

    def picks(self, n):
        return picks(n)

    def still(self, shot, i, im):
        which = picks(shot.n)[i]
        t = i / shot.fps
        small = im.convert("RGB")
        small = small.resize((THUMB_W, max(2, round(small.height * THUMB_W / small.width))), Image.LANCZOS)
        small = _post(shot, small, t)
        path = still_path(self.spec, shot.id, which)
        _save(path, lambda p: small.save(p, quality=85))
        ent = self.index.setdefault(shot.id, {})
        ent["look"] = self.sample                     # a real render's first frame turns the row from "quick look" into the real thing
        ent[which] = dict(t=round(t, 2), at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
        _save(os.path.join(thumbs_dir(self.spec), INDEX), lambda p: json.dump(self.index, open(p, "w"), indent=1))
        frac = 0.0 if self.sample else (i + 1) / shot.n
        sp = compose(self.spec, self.ids, active=None if self.sample else (shot.id, frac), index=self.index)
        if self.on_change:
            self.on_change(dict(id=shot.id, label="Shot " + shot.id, frac=round(frac, 3), which=which, still=path, strip=sp, look=self.sample))

    def progress(self, shot, i):
        if self.on_change:
            self.on_change(dict(id=shot.id, label="Shot " + shot.id, frac=round((i + 1) / shot.n, 3)))


def _font(size):
    from .contact import _font as f
    return f(size)


def compose(spec, ids=None, active=None, out=None, index=None):
    """One image of every scene with stills (rows of start / middle / end), the scene `active` = (id, frac) outlined with its progress.
    Returns the path written (default build/thumbs/strip.jpg), or None when no scene has a still yet."""
    index = load_index(spec) if index is None else index
    shots = [s for s in spec.shots if (ids is None or s.id in ids) and any(os.path.isfile(still_path(spec, s.id, w)) for w, _ in WHICH)]
    if not shots:
        return None
    th = round(TILE_W * spec.OH / spec.OW)
    bw, bh = 3 * TILE_W + 2 * GAP, HEAD + th
    cols = 1 if len(shots) <= ONE_COLUMN_MAX else 2
    rows = -(-len(shots) // cols)
    W, H = PAD + cols * (bw + PAD), PAD + rows * (bh + PAD)
    sheet = Image.new("RGB", (W, H), (22, 23, 31))
    d = ImageDraw.Draw(sheet)
    f, fs = _font(16), _font(13)
    for k, s in enumerate(shots):
        x, y = PAD + (k % cols) * (bw + PAD), PAD + (k // cols) * (bh + PAD)
        ent = index.get(s.id) or {}
        live = active is not None and active[0] == s.id
        tag = f"rendering {round(active[1] * 100)}%" if live else "quick look" if ent.get("look") else "rendered"
        d.text((x, y + 3), f"Shot {s.id}", fill=(240, 240, 240), font=f)
        d.text((x + 90, y + 6), f"{s.t0:.1f}-{s.t1:.1f}s  ·  {tag}", fill=(255, 176, 70) if live else (150, 154, 170), font=fs)
        for j, (w, _) in enumerate(WHICH):
            tx, ty = x + j * (TILE_W + GAP), y + HEAD
            p = still_path(spec, s.id, w)
            if os.path.isfile(p):
                sheet.paste(Image.open(p).convert("RGB").resize((TILE_W, th), Image.LANCZOS), (tx, ty))
            else:
                d.rectangle([tx, ty, tx + TILE_W - 1, ty + th - 1], fill=(38, 40, 52))
                d.text((tx + TILE_W // 2 - 4, ty + th // 2 - 8), "…", fill=(120, 124, 140), font=f)
        if live:
            d.rectangle([x - 3, y - 3, x + bw + 2, y + bh + 2], outline=(255, 176, 70), width=2)
    out = out or strip_path(spec)
    _save(out, lambda p: sheet.save(p, quality=88) if p.lower().endswith((".jpg", ".jpeg")) else sheet.save(p))
    return out


def quick_look(spec, shots, ids=None, on_change=None, log=None):
    """Draw the start / middle / end of each shot (no encoding) and the filmstrip. A shot that cannot be sampled (its hosts are not rendered yet,
    or it raised) is listed in `skipped` with the reason and the build carries on. Returns {made, skipped, strip}."""
    from . import render as R
    from .shots import get_type
    log = log or (lambda m: print(m, file=sys.stderr, flush=True))
    ctx = R.RenderContext.from_spec(spec)
    pv = Stills(spec, sample=True, ids=ids, on_change=on_change)
    made, skipped = [], []
    prev = R.PREVIEW
    with tempfile.TemporaryDirectory() as td:
        ctx.seg_dir = td                     # a shot type that writes beside its segment never touches the real segs/
        R.PREVIEW = pv
        try:
            for shot in shots:
                try:
                    get_type(shot.type).render(ctx, shot)
                except R.Sampled:
                    made.append(shot.id)
                    continue
                except R.NotYet as e:
                    skipped.append(dict(id=shot.id, why=str(e)))
                except Exception as e:  # noqa: BLE001  (a quick look never stops the build; the real render reports the error)
                    skipped.append(dict(id=shot.id, why=f"{type(e).__name__}: {e}"[:200]))
                else:
                    skipped.append(dict(id=shot.id, why="it draws no frames of its own"))
                log(f"  no quick look of shot {shot.id}: {skipped[-1]['why']}")
        finally:
            R.PREVIEW = prev
    return dict(made=made, skipped=skipped, strip=compose(spec, ids, index=pv.index))
