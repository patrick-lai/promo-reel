"""Depth for generated still plates, on this Mac: Depth Anything V2 Small (ONNX through onnxruntime, Apache-2.0) and a 2.5D
parallax clip made from it, the depth pass of the Higgsfield-style studios (docs/reference-higgsfield-studio.md).

    promo depth map IMG [--out IMG.depth.png]                    the depth map as a grey PNG (white = near)
    promo depth parallax IMG --out CLIP.mp4 [--seconds 4 --move push --amount 1 --focus 0.5 --blur 0 --size 1920x1080 --fps 30]

Moves: static, push, pull, orbit, pan_left, pan_right, crane, handheld (the Studio's camera presets). Near pixels move more than far
ones; `focus` (0 = far, 1 = near) is the depth that stays put and, with `--blur N`, the depth that stays sharp.

Only generated plates: an image whose `.gen.json` sidecar says `generated: true` (callers that already know a picture is a generated
plate, such as the Studio's storyboard frames of generated scenes, pass `trusted=True`). Moving a screenshot's pixels by depth would
edit the app's UI (AGENTS.md rules 1 and 2). The clip gets its own sidecar (generated, provider local:depth-parallax, its source), so
`promo gen register` and the generated-plates gate treat it like any other generated plate. Nothing is sent anywhere; the model
(~100 MB) is downloaded once from Hugging Face into its usual cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO = "onnx-community/depth-anything-v2-small"
REVISION = "4472b7362082ad9968fee890ca0f1e5aca36b93d"     # pinned: the same weights every run
MODEL_FILE = "onnx/model.onnx"
SIDE = 518                     # the processor's working size: the side whose scale is nearest 1 goes to 518, both to multiples of 14
MEAN, STD = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)
MOVES = ("static", "push", "pull", "orbit", "pan_left", "pan_right", "crane", "handheld")
OVERSCAN = 1.06                # every move stays inside the picture: no edge is ever pulled into view
_session = None


class DepthError(RuntimeError):
    """The depth pass cannot run as asked; the message says why."""


def available():
    try:
        import huggingface_hub  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _model():
    global _session
    if _session is None:
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
        except ImportError as e:
            raise DepthError("the depth pass needs onnxruntime and huggingface_hub (`pip install -e .[depth]`)") from e
        path = hf_hub_download(REPO, MODEL_FILE, revision=REVISION)
        _session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    return _session


def _work_size(w, h):
    """(w, h) the model sees: keep the aspect, the side whose scale is nearer 1 lands on SIDE, both rounded to multiples of 14."""
    s = SIDE / h if abs(1 - SIDE / h) < abs(1 - SIDE / w) else SIDE / w
    return max(14, round(w * s / 14) * 14), max(14, round(h * s / 14) * 14)


def estimate(img):
    """Relative depth of a PIL image as float32 HxW in [0, 1], 1 = nearest (2nd-98th percentile stretched)."""
    sess = _model()
    w, h = img.size
    x = np.asarray(img.convert("RGB").resize(_work_size(w, h), Image.BICUBIC), np.float32) / 255.0
    x = ((x - MEAN) / STD).transpose(2, 0, 1)[None]
    pred = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]
    d = np.asarray(Image.fromarray(pred.astype(np.float32)).resize((w, h), Image.BILINEAR))
    lo, hi = np.percentile(d, [2, 98])
    return np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1).astype(np.float32)


def is_generated(path):
    try:
        with open(str(path) + ".gen.json") as f:
            return json.load(f).get("generated") is True
    except (FileNotFoundError, ValueError):
        return False


def _check_source(path, trusted):
    if not os.path.isfile(path):
        raise DepthError(f"no picture at {path}")
    if not (trusted or is_generated(path)):
        raise DepthError(f"{path} is not a generated plate (no .gen.json sidecar saying so); the depth pass moves only generated plates, never a "
                         "screenshot of the app (AGENTS.md rules 1 and 2)")


def depth_map(src, out=None, trusted=False):
    _check_source(src, trusted)
    out = out or str(Path(src).with_suffix("")) + ".depth.png"
    Image.fromarray((estimate(Image.open(src)) * 255).astype(np.uint8)).save(out)
    return out


def path_at(move, s, amount):
    """(tx, ty, zoom, dolly) at s in [0, 1]: tx / ty shift the picture per unit of depth away from the focus plane (fractions of its
    width), zoom scales it all, dolly scales near pixels more than far ones."""
    a = amount
    e = 0.5 - 0.5 * math.cos(math.pi * s)                     # eased: a camera that starts and lands gently
    if move == "push":
        return 0.0, 0.0, 1 + 0.04 * a * e, 0.10 * a * e
    if move == "pull":
        return path_at("push", 1 - s, amount)
    if move in ("pan_left", "pan_right"):
        k = 1 if move == "pan_left" else -1
        return k * 0.05 * a * (e - 0.5), 0.0, 1.0, 0.0
    if move == "orbit":
        return 0.06 * a * math.sin(math.pi * (e - 0.5)), 0.0, 1 + 0.02 * a, 0.03 * a * math.sin(math.pi * e)
    if move == "crane":
        return 0.0, -0.04 * a * (e - 0.5), 1 + 0.02 * a * e, 0.02 * a * e
    if move == "handheld":
        t = s * 4
        return (0.006 * a * (math.sin(2.1 * t) + 0.5 * math.sin(5.3 * t + 1)), 0.005 * a * (math.sin(1.7 * t + 2) + 0.5 * math.sin(4.1 * t)),
                1 + 0.01 * a, 0.0)
    if move == "static":
        return 0.0, 0.0, 1.0, 0.0
    raise DepthError(f"no move {move!r}; one of {', '.join(MOVES)}")


def _sample(img, sx, sy):
    """Bilinear lookup of img (HxWxC float32) at float pixel coordinates, clamped to the picture."""
    h, w = img.shape[:2]
    sx, sy = np.clip(sx, 0, w - 1.001), np.clip(sy, 0, h - 1.001)
    x0, y0 = sx.astype(np.int32), sy.astype(np.int32)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    top = img[y0, x0] * (1 - fx) + img[y0, x0 + 1] * fx
    bot = img[y0 + 1, x0] * (1 - fx) + img[y0 + 1, x0 + 1] * fx
    return top * (1 - fy) + bot * fy


def _cover(img, w, h):
    """The picture scaled to cover w x h and centre-cropped, so a 16:9 frame can make a 9:16 clip."""
    s = max(w / img.width, h / img.height)
    big = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    x, y = (big.width - w) // 2, (big.height - h) // 2
    return big.crop((x, y, x + w, y + h))


def frames(img, depth, n, move="push", amount=1.0, focus=0.5, blur=0.0):
    """Yield n RGB uint8 frames of the parallax move over `img` (PIL, already at the output size) with `depth` (HxW in [0, 1])."""
    from scipy import ndimage
    w, h = img.size
    # a softened, slightly grown depth keeps foreground edges together instead of tearing them along the outline
    d = ndimage.gaussian_filter(ndimage.grey_dilation(depth, size=(5, 5)), 1.5) - focus
    sharp = np.asarray(img.convert("RGB"), np.float32)
    soft = np.asarray(img.convert("RGB").filter(ImageFilter.GaussianBlur(blur)), np.float32) if blur > 0 else None
    mix = np.clip(np.abs(d) * 2.2, 0, 1)[..., None] if blur > 0 else None
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = (xx - w / 2) / w, (yy - h / 2) / w                   # centred, in fractions of the width
    for i in range(n):
        tx, ty, zoom, dolly = path_at(move, i / max(n - 1, 1), amount)
        scale = OVERSCAN * zoom * (1 + dolly * d)
        sx = (u / scale - tx * d + w / 2 / w) * w
        sy = (v / scale - ty * d + h / 2 / w) * w
        out = _sample(sharp, sx, sy)
        if soft is not None:
            out = out * (1 - mix) + _sample(soft, sx, sy) * mix
        yield np.clip(out + 0.5, 0, 255).astype(np.uint8)


def parallax(src, out, seconds=4.0, move="push", amount=1.0, focus=0.5, blur=0.0, size=(1920, 1080), fps=30, trusted=False, depth=None, on_progress=None):
    """Render the parallax clip to `out` (H.264) with its `.gen.json` sidecar; returns the sidecar. `depth` (HxW in [0, 1] at `size`)
    skips the model, for callers that already have one. `on_progress(done, total)` runs every few frames."""
    from . import genvideo as GV
    from .lock import heavy_lock
    _check_source(src, trusted)
    path_at(move, 0, amount)                # an unknown move is refused before the model or ffmpeg start
    w, h = (int(v) // 2 * 2 for v in size)
    img = _cover(Image.open(src).convert("RGB"), w, h)
    depth = estimate(img) if depth is None else depth
    n = max(2, round(seconds * fps))
    out_p = Path(out).expanduser().resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with heavy_lock("promo depth parallax"):
        enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                                "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart", str(out_p)],
                               stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for i, fr in enumerate(frames(img, depth, n, move, amount, focus, blur)):
                enc.stdin.write(fr.tobytes())
                if on_progress and (i % 10 == 0 or i == n - 1):
                    on_progress(i + 1, n)
            enc.stdin.close()
        except BrokenPipeError:
            enc.wait()
            raise DepthError(f"ffmpeg stopped reading frames for {out_p.name}: {enc.stderr.read().decode(errors='replace')[-300:]}") from None
        if enc.wait() != 0:
            raise DepthError(f"ffmpeg could not write {out_p.name}: {enc.stderr.read().decode(errors='replace')[-300:]}")
    meta = dict(generated=True, kind="video", provider="local:depth-parallax", model=f"{REPO}@{REVISION[:8]}", source=str(Path(src).resolve()),
                source_sha256=hashlib.sha256(Path(src).read_bytes()).hexdigest(), move=move, amount=amount, focus=focus, blur=blur, seconds=n / fps,
                fps=fps, cost_usd=0, sha256=GV.sha256(out_p), at=time.strftime("%Y-%m-%dT%H:%M:%S"), **GV.probe_media(out_p))
    Path(str(out_p) + ".gen.json").write_text(json.dumps(meta, indent=1))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(prog="promo depth", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map", help="the depth map of a generated plate as a grey PNG (white = near)")
    m.add_argument("src")
    m.add_argument("--out")
    p = sub.add_parser("parallax", help="a 2.5D camera move over a generated still plate, as an mp4 with a generated sidecar")
    p.add_argument("src")
    p.add_argument("--out", required=True)
    p.add_argument("--seconds", type=float, default=4.0)
    p.add_argument("--move", choices=MOVES, default="push")
    p.add_argument("--amount", type=float, default=1.0, help="how far the camera travels (1 = the preset's own; 0.5 calmer, 2 bolder)")
    p.add_argument("--focus", type=float, default=0.5, help="the depth that stays put and sharp: 0 far, 1 near")
    p.add_argument("--blur", type=float, default=0.0, help="depth of field: blur radius in px away from the focus (0 = all sharp)")
    p.add_argument("--size", default="1920x1080")
    p.add_argument("--fps", type=int, default=30)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "map":
            print(depth_map(a.src, a.out))
            return 0
        meta = parallax(a.src, a.out, a.seconds, a.move, a.amount, a.focus, a.blur, tuple(int(v) for v in a.size.lower().split("x")), a.fps,
                        on_progress=lambda i, n: print(f"  frame {i}/{n}", file=sys.stderr))
    except DepthError as e:
        raise SystemExit(f"promo depth: {e}") from None
    print(f"{a.out}: {meta['width']}x{meta['height']}, {meta['seconds']:.2f} s, {a.move} (sidecar {a.out}.gen.json)")
    return 0
