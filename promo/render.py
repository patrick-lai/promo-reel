"""Generic graphics / camera / source / writer primitives (port of the legacy hero render.py).

Everything that used to be a module global (scale K, OW/OH, fps, font path, caption zone) lives on `RenderContext`.
Camera regions are normalised to the source frame, so the same spec renders at 1080 (K=1) or 2160 (K=2); graphic
sizes are multiplied by K. The maths (PIL float-box Lanczos resampling, smootherstep easing, pill geometry,
shadows, x264 settings) is intentionally identical to the legacy code: do not "tidy" it without re-running
`promo compare` against a reference.
"""
from __future__ import annotations

import collections
import json
import os
import subprocess
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

DEFAULT_FONT = "/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf"


@dataclass
class RenderContext:
    K: int = 1
    fps: int = 30
    font_path: str = DEFAULT_FONT
    font_fallbacks: list = field(default_factory=list)
    caption: dict = field(default_factory=lambda: dict(cx=960, cy=905, size=32, max_w=608, zone=dict(x0=656, x1=1264, y0=860, y1=950)))
    spec: object = None                      # the Spec (for plates / path resolution), optional
    seg_dir: str = "."

    @property
    def OW(self):
        return 1920 * self.K

    @property
    def OH(self):
        return 1080 * self.K

    def with_scale(self, k):
        c = RenderContext(**{**self.__dict__})
        c.K = k
        return c

    @classmethod
    def from_spec(cls, spec):
        st = getattr(spec, "style", None) or spec.raw.get("style", {})
        fnt = st.get("font", {})
        cap = dict(cx=960, cy=905, size=32, max_w=608, zone=dict(x0=656, x1=1264, y0=860, y1=950))
        cap.update({k: v for k, v in st.get("caption", {}).items() if k != "zone"})
        if "zone" in st.get("caption", {}):
            cap["zone"] = st["caption"]["zone"]
        path = None
        for p in [fnt.get("path")] + list(fnt.get("fallbacks", [])):
            if p and os.path.exists(spec.resolve(p)):
                path = spec.resolve(p)
                break
        return cls(K=spec.scale, fps=spec.fps, font_path=path or spec.resolve(fnt.get("path") or DEFAULT_FONT),
                   font_fallbacks=fnt.get("fallbacks", []), caption=cap, spec=spec, seg_dir=spec.segs_dir)

    def font(self, size, weight=b"SemiBold"):
        if isinstance(weight, str):
            weight = weight.encode()
        f = ImageFont.truetype(self.font_path, int(size * self.K))
        f.set_variation_by_name(weight)
        return f


# ---------------- easing / camera ----------------
def ease(p, kind="smooth"):
    p = min(max(p, 0.0), 1.0)
    if kind == "linear":
        return p
    if kind == "out":
        return 1 - (1 - p) ** 3
    if kind == "in":
        return p ** 3
    return p * p * p * (p * (p * 6 - 15) + 10)          # smootherstep (zero velocity + acceleration at ends)


def cam_at(keys, t):
    """keys: [(t, cx, cy, w, ease)] with cx, cy, w normalised to source width/height (w = box width / source width)."""
    if t <= keys[0][0]:
        return keys[0][1:4]
    for (t0, *a), (t1, *b) in zip(keys, keys[1:]):
        if t <= t1:
            p = ease((t - t0) / max(t1 - t0, 1e-6), b[3] if len(b) > 3 else "smooth")
            return tuple(a[i] + (b[i] - a[i]) * p for i in range(3))
    return keys[-1][1:4]


def frame_cam(ctx, img, cx, cy, w, out=(None, None)):
    """Crop a box of the output's aspect centred (cx, cy) of normalised width w from img and resample to out size
    (float box). A crop that would be taller than the image shrinks to the full image height (`promo check`
    livestream-cam flags explicit cams that do this)."""
    ow, oh = out[0] or ctx.OW, out[1] or ctx.OH
    SW, SH = img.size
    bw = w * SW
    bh = bw * oh / ow
    if bh > SH:                     # output taller than 16:9 (e.g. the full-height livestream screen): widest crop that fits
        bh, bw = SH, SH * ow / oh
    x0 = cx * SW - bw / 2
    y0 = cy * SH - bh / 2
    x0 = min(max(x0, 0), SW - bw)
    y0 = min(max(y0, 0), SH - bh)
    return img.resize((ow, oh), Image.LANCZOS, box=(x0, y0, x0 + bw, y0 + bh))


def anchored(ctx, cam, src_size, nx, ny):
    """Map a normalised source point to output pixel coords for camera (cx, cy, w)."""
    cx, cy, w = cam
    SW, SH = src_size
    bw = w * SW
    bh = bw * ctx.OH / ctx.OW
    x0 = min(max(cx * SW - bw / 2, 0), SW - bw)
    y0 = min(max(cy * SH - bh / 2, 0), SH - bh)
    return ((nx * SW - x0) / bw * ctx.OW, (ny * SH - y0) / bh * ctx.OH)


# ---------------- source reading ----------------
def probe(path):
    o = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                                 "-show_entries", "format=duration", "-of", "json", path]).decode()
    j = json.loads(o)
    s = j["streams"][0]
    n, d = s["r_frame_rate"].split("/")
    return s["width"], s["height"], float(n) / float(d), float(j["format"]["duration"])


class Source:
    """Sequential frame reader for a clip: frame(t) returns the PIL image at source time t (nearest frame), or the
    average of `blur` consecutive frames (shutter blur for sped-up moves). Times must be non-decreasing."""

    def __init__(self, path, t_in, t_out, prescale=None):
        if not os.path.exists(path):
            raise FileNotFoundError(f"source footage not found: {path}")
        self.path = path
        W, H, self.fps, self.dur = probe(path)
        self.t_in = max(0.0, t_in)
        self.t_out = min(t_out, self.dur)
        vf = []
        self.W, self.H = W, H
        if prescale:
            vf = [f"scale={prescale[0]}:{prescale[1]}:flags=lanczos"]
            self.W, self.H = prescale
        cmd = ["ffmpeg", "-v", "error", "-threads", "2", "-ss", f"{self.t_in:.4f}", "-i", path, "-t", f"{self.t_out - self.t_in + 0.05:.4f}"]
        if vf:
            cmd += ["-vf", ",".join(vf)]
        cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 8)
        self.idx = -1
        self.cur = None
        self.hist = collections.deque(maxlen=8)
        self.fsize = self.W * self.H * 3
        self.ended = False

    def _next(self):
        if self.ended:
            return False
        b = self.p.stdout.read(self.fsize)
        if len(b) < self.fsize:
            self.ended = True
            return False
        self.cur = np.frombuffer(b, np.uint8).reshape(self.H, self.W, 3)
        self.idx += 1
        return True

    def frame(self, t, blur=1):
        target = int(round((min(t, self.t_out) - self.t_in) * self.fps))
        while self.idx < target:
            if not self._next():
                break
            self.hist.append(self.cur)
        if self.cur is None:
            return None
        if blur > 1 and len(self.hist) > 1:
            fr = list(self.hist)[-blur:]
            return Image.fromarray((np.sum([f.astype(np.uint16) for f in fr], axis=0) // len(fr)).astype(np.uint8))
        return Image.fromarray(self.cur.copy())

    def close(self):
        try:
            self.p.stdout.close()
            self.p.kill()
            self.p.wait()
        except Exception:
            pass


def still(path):
    return Image.open(path).convert("RGB")


def grab_frame(path, t):
    """One frame of a clip at source time t (legacy: Source(path, t, t + 0.1).frame(t))."""
    s = Source(path, t, t + 0.1)
    try:
        return s.frame(t)
    finally:
        s.close()


# ---------------- graphics ----------------
def canvas(ctx):
    return Image.new("RGBA", (ctx.OW, ctx.OH), (0, 0, 0, 0))


def soft_shadow(ctx, img, blur=12, alpha=120, dy=6):
    a = img.split()[3].point(lambda v: v * alpha // 255)
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sh.putalpha(a)
    sh = sh.filter(ImageFilter.GaussianBlur(blur * ctx.K))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.alpha_composite(sh, (0, int(dy * ctx.K)))
    out.alpha_composite(img)
    return out


def soft_shadow_layer(ctx, c, blur=24, alpha=150, pad=60):
    """Pad `c` and give it a drop shadow; returns (layer, pad_px)."""
    pad = pad * ctx.K
    big = Image.new("RGBA", (c.width + 2 * pad, c.height + 2 * pad), (0, 0, 0, 0))
    big.alpha_composite(c, (pad, pad))
    return soft_shadow(ctx, big, blur, alpha, 14), pad


def pill_geometry(ctx, text, size=None, cx=None, cy=None, anchor="c", segs=None):
    """Pill box in OUTPUT px: returns dict(x0, y0, w, h, padx, pady, font, widths, segs). Shared by the renderer and the QA safe-zone check."""
    size = ctx.caption["size"] if size is None else size
    cx = ctx.caption["cx"] if cx is None else cx
    cy = ctx.caption["cy"] if cy is None else cy
    K = ctx.K
    f = ctx.font(size)
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    segs = segs or [(text, None)]
    widths = [d.textlength(s, font=f) for s, _ in segs]
    tw = sum(widths)
    asc, desc = f.getmetrics()
    th = asc + desc
    padx, pady = size * 0.7 * K, size * 0.42 * K
    w, h = tw + 2 * padx, th + 2 * pady
    x0 = cx * K - w / 2 if anchor == "c" else cx * K
    y0 = cy * K - h / 2
    return dict(x0=x0, y0=y0, w=w, h=h, padx=padx, pady=pady, font=f, widths=widths, segs=segs)


def pill_img(ctx, text, dark=True, cx=None, cy=None, size=None, anchor="c", safe=True, segs=None):
    size = ctx.caption["size"] if size is None else size
    g = pill_geometry(ctx, text, size, cx, cy, anchor, segs)
    im = canvas(ctx)
    d = ImageDraw.Draw(im)
    x0, y0, w, h, padx, pady, f = g["x0"], g["y0"], g["w"], g["h"], g["padx"], g["pady"], g["font"]
    if anchor == "c" and safe:
        assert w <= ctx.caption["max_w"] * ctx.K, (text, w / ctx.K)
    fill = (16, 17, 20, 205) if dark else (255, 255, 255, 240)
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=h / 2, fill=fill)
    x = x0 + padx
    for (s, col), sw in zip(g["segs"], g["widths"]):
        c = col or ((255, 255, 255, 255) if dark else (17, 19, 24, 255))
        d.text((x, y0 + pady), s, font=f, fill=c)
        x += sw
    return soft_shadow(ctx, im, 10, 90 if dark else 110)


def label_img(ctx, text, size=30, dark=True):
    """Compact pill (cropped to its own bbox + shadow margin) for anchored lower thirds."""
    big = pill_img(ctx, text, dark=dark, cx=60, cy=60 + size, size=size, anchor="l", safe=False)
    bb = big.getbbox()
    return big.crop((0, bb[1], bb[2] + 4, bb[3])), (60 + size) * ctx.K - bb[1]


def text_img(ctx, text, cy, size, weight=b"Bold", color=(255, 255, 255), shadow=True):
    f = ctx.font(size, weight)
    im = canvas(ctx)
    d = ImageDraw.Draw(im)
    tw = d.textlength(text, font=f)
    asc, desc = f.getmetrics()
    d.text(((ctx.OW - tw) / 2, cy * ctx.K - (asc + desc) / 2), text, font=f, fill=tuple(color) + (255,))
    return soft_shadow(ctx, im, 14, 150, 4) if shadow else im


def rounded_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    return m


def vgrad(ctx, top, bottom, size=None):
    w, h = size or (ctx.OW, ctx.OH)
    a = np.linspace(0, 1, h)[:, None, None]
    arr = (np.array(top)[None, None, :] * (1 - a) + np.array(bottom)[None, None, :] * a).repeat(w, 1)
    return Image.fromarray(arr.astype(np.uint8))


def dark_plate(ctx):
    """Tasteful dark gradient plate (fallback when no Workshop plate was captured): deep navy with a soft radial glow."""
    w, h = ctx.OW, ctx.OH
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.array([10, 12, 18], np.float32)
    glow = np.array([38, 48, 78], np.float32)
    r = np.sqrt(((x - w * 0.5) / (w * 0.55)) ** 2 + ((y - h * 0.42) / (h * 0.6)) ** 2)
    g = np.clip(1 - r, 0, 1) ** 1.6
    arr = base[None, None] + (glow - base)[None, None] * g[..., None]
    arr += np.random.default_rng(1).normal(0, 1.2, arr.shape)   # fine dither, no banding
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def plate(ctx, kind):
    """Optional background plate from spec `plates: {<kind>: {source: clip id, t, cam, dim, blur}}`; dark_plate() when not captured."""
    p = (ctx.spec.raw.get("plates") or {}).get(kind) if ctx.spec else None
    if p and p.get("source"):
        path = ctx.spec.clip_path(p["source"])
        t = p.get("t", 1.0)
        im = still(path) if path.endswith(".png") else grab_frame(path, t)
        im = frame_cam(ctx, im, *p.get("cam", (0.5, 0.5, 1.0)))
        if p.get("dim"):
            im = ImageEnhance.Brightness(im).enhance(p["dim"])
        return im.filter(ImageFilter.GaussianBlur(p.get("blur", 0) * ctx.K)) if p.get("blur") else im
    return dark_plate(ctx)


# ---------------- writer ----------------
class Writer:
    """Raw-frame pipe into x264 (libx264 slow crf16 high yuv420p, g60 bf2, bt709 tags, 2 threads, nice 10)."""

    def __init__(self, ctx, path, n):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.ctx, self.path, self.n, self.k = ctx, path, n, 0
        self.tmp = path[:-4] + ".partial.mp4"
        self.p = subprocess.Popen(["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ctx.OW}x{ctx.OH}",
                                   "-r", str(ctx.fps), "-i", "-", "-threads", "2", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                                   "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", "60", "-bf", "2",
                                   "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", self.tmp], stdin=subprocess.PIPE)

    def write(self, img):
        if img.mode != "RGB":
            img = img.convert("RGB")
        assert img.size == (self.ctx.OW, self.ctx.OH), (img.size, self.ctx.OW, self.ctx.OH)
        self.p.stdin.write(img.tobytes())
        self.k += 1

    def close(self):
        self.p.stdin.close()
        rc = self.p.wait()
        if rc != 0 or self.k != self.n:
            raise RuntimeError(f"writer failed rc={rc} frames={self.k}/{self.n}")
        os.replace(self.tmp, self.path)
        print("wrote", self.path, self.k, "frames", flush=True)


def run_shot(ctx, shot, frame_fn):
    """Render `shot.n` frames: frame_fn(i, t) -> PIL image, t = i / fps (shot-local seconds)."""
    w = Writer(ctx, os.path.join(ctx.seg_dir, f"{shot.id}.mp4"), shot.n)
    for i in range(shot.n):
        w.write(frame_fn(i, i / ctx.fps))
    w.close()


def alpha_at(t, t0, t1, fin=0.18, fout=0.12):
    if t < t0 or t > t1:
        return 0.0
    return min(1.0, (t - t0) / fin if fin else 1, (t1 - t) / fout if fout else 1)


def over(base, layer, a=1.0, pos=(0, 0)):
    if a <= 0:
        return base
    if a < 1:
        layer = layer.copy()
        layer.putalpha(layer.split()[3].point(lambda v: int(v * a)))
    base = base.convert("RGBA")
    base.alpha_composite(layer, pos)
    return base
