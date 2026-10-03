"""Labelled contact sheet (one frame per shot) + peek / segpeek / mpeek helpers. All peek output goes to build/peek/."""
from __future__ import annotations

import json
import os
import subprocess
import time

from PIL import Image, ImageDraw, ImageFont

BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font(size):
    try:
        return ImageFont.truetype(BOLD, size)
    except OSError:
        return ImageFont.load_default(size)


def contact_paths(spec):
    base = os.path.join(spec.out, f"{spec.name}-{spec.tag}-contact")
    return base + ".png", base + ".json"


def run(spec, force=False):
    """Extract a frame per shot from the primary master (mid-shot at 60%, or the shot's `contact_at`)."""
    src = spec.output_path(spec.masters[0].get("suffix", ""))
    if not os.path.exists(src):
        raise FileNotFoundError(f"output not found: {src} (run `promo assemble`)")
    tiles, TW, TH = [], 640, 360
    tmp = os.path.join(spec.build, "peek", "cs.png")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    for s in spec.shots:
        off = s.get("contact_at", (s.t1 - s.t0) * 0.6)
        t = s.t0 + off
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", tmp], check=True)
        im = Image.open(tmp).convert("RGB").resize((TW, TH), Image.LANCZOS)
        dr = ImageDraw.Draw(im)
        dr.rectangle([0, 0, 330, 26], fill=(0, 0, 0))
        dr.text((8, 5), f"S{s.id}  {s.t0:05.2f}-{s.t1:05.2f}s  @{t:.2f}", fill=(255, 230, 90), font=_font(15))
        tiles.append(im)
    cols = 5
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * TW + (cols + 1) * 8, rows * TH + (rows + 1) * 8 + 40), (20, 20, 24))
    ImageDraw.Draw(sheet).text((10, 10), f"{spec.title} ({spec.tag}p draft) — one frame per shot", fill=(230, 230, 230), font=_font(20))
    for i, im in enumerate(tiles):
        sheet.paste(im, (8 + (i % cols) * (TW + 8), 48 + (i // cols) * (TH + 8)))
    png, js = contact_paths(spec)
    sheet.save(png)
    json.dump(dict(tiles=len(tiles), cols=cols, rows=rows, size=list(sheet.size), shots=[s.id for s in spec.shots]), open(js, "w"))
    print("wrote", png, flush=True)
    return png


# ---------------------------------------------------------------- peek helpers
def _peek_dir(spec):
    d = os.path.join(spec.build, "peek")
    os.makedirs(d, exist_ok=True)
    return d


def _grid(im, box, step, f, label_every=1):
    d = ImageDraw.Draw(im)
    n = int(round(1 / step))
    for i in range(1, n):
        v = i * step
        col = (255, 0, 255) if i % 2 == 0 else (0, 160, 255)
        if box[0] < v < box[2]:
            x = (v - box[0]) / (box[2] - box[0]) * im.width
            d.line([(x, 0), (x, im.height)], fill=col, width=1)
            d.text((x + 2, 2), f"{v:.2f}", fill=(255, 255, 0), font=f)
        if box[1] < v < box[3]:
            y = (v - box[1]) / (box[3] - box[1]) * im.height
            d.line([(0, y), (im.width, y)], fill=col, width=1)
            d.text((2, y + 2), f"{v:.2f}", fill=(255, 255, 0), font=f)


def _grab(path, t, tmp):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", tmp], check=True)
    return Image.open(tmp).convert("RGB")


def peek(spec, src, t, box=None):
    """promo peek <src> <t> [x0 y0 x1 y1]: frame (or normalised crop) with a 0.05 grid -> build/peek/<name>-<t>.png"""
    path = spec.footage_path(src)
    box = list(box) if box else [0, 0, 1, 1]
    tmp = os.path.join(_peek_dir(spec), "_peek.png")
    im = _grab(path, t, tmp)
    W, H = im.size
    im = im.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)))
    s = 1600 / im.width
    im = im.resize((1600, int(im.height * s)), Image.LANCZOS)
    _grid(im, box, 0.05, ImageFont.load_default(18))
    name = os.path.basename(path).rsplit(".", 1)[0]
    out = os.path.join(_peek_dir(spec), f"{name}-{t:.2f}" + ("" if box == [0, 0, 1, 1] else "-c") + ".png")
    im.save(out)
    return out


def segpeek(spec, sid, times=None):
    """promo segpeek <id> [t...]: tiles of a rendered segment (2 cols, 960 wide), times in segment seconds."""
    p = spec.seg_path(sid)
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]))
    ts = list(times) or [0.05, dur * 0.35, dur * 0.7, dur - 0.05]
    tmp = os.path.join(_peek_dir(spec), "_sp.png")
    tiles = []
    for t in ts:
        im = _grab(p, t, tmp).resize((960, 540), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 120, 18], fill=(0, 0, 0))
        d.text((4, 3), f"{sid} @{t:.2f}", fill=(255, 255, 0))
        tiles.append(im)
    g = Image.new("RGB", (1920, 540 * ((len(tiles) + 1) // 2)))
    for i, t in enumerate(tiles):
        g.paste(t, ((i % 2) * 960, (i // 2) * 540))
    out = os.path.join(_peek_dir(spec), f"seg-{sid}-{int(time.time()) % 100000}.png")
    g.save(out)
    return out, dur


def mpeek(spec, out_name, specs):
    """promo mpeek <out.png> src:t[:x0,y0,x1,y1] ...: grid (2 cols) of frames with a 0.025 grid -> build/peek/<out.png>"""
    tmp = os.path.join(_peek_dir(spec), "_mp.png")
    tiles = []
    f = ImageFont.load_default(13)
    for sp in specs:
        parts = sp.split(":")
        t = float(parts[1])
        box = list(map(float, parts[2].split(","))) if len(parts) > 2 else [0, 0, 1, 1]
        im = _grab(spec.footage_path(parts[0]), t, tmp)
        W, H = im.size
        im = im.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)))
        im = im.resize((960, max(1, int(im.height * 960 / im.width))), Image.LANCZOS)
        if not os.environ.get("NOGRID"):
            _grid(im, box, 0.025, f)
        d = ImageDraw.Draw(im)
        d.rectangle([0, im.height - 18, 400, im.height], fill=(0, 0, 0))
        d.text((4, im.height - 16), os.path.basename(sp), fill=(255, 255, 255), font=f)
        tiles.append(im)
    cols = 2 if len(tiles) > 1 else 1
    rows = []
    for i in range(0, len(tiles), cols):
        r = tiles[i:i + cols]
        h = max(t.height for t in r)
        row = Image.new("RGB", (960 * cols, h))
        for j, t in enumerate(r):
            row.paste(t, (j * 960, 0))
        rows.append(row)
    g = Image.new("RGB", (960 * cols, sum(r.height for r in rows)))
    y = 0
    for r in rows:
        g.paste(r, (0, y))
        y += r.height
    out = os.path.join(_peek_dir(spec), os.path.basename(out_name))
    g.save(out)
    return out, g.size
