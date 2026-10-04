"""`livestream` shot: app screen + Live2D hosts + chat strip, laid out by promo.livestream.layout_at.

Shot keys (per shot; the show-level layout, hosts and chat live in the spec's `livestream:` block):
    screen: {source: <footage clip id>, t_in: 0, speed: 1, cam: [cx, cy, w]}   real app footage (never edited)
    screen: {source: ..., hold_in: 0.8}                                        hold the clip's first frame 0.8 s, then play
    screen: {card: {title: "...", subtitle: "...", lines: ["..."]}}            generated title/end card on the stream screen
    screen: {placeholder: "APP FOOTAGE"}                                       grey placeholder for drafts / demos
    overlays: [...]                                                            usual overlays (QA'd against keep-clear)

`live2d_credits` shot (end card): the full Live2D notice + per-model credits from live2d/assets.yaml at body size.
    size: 30          # text px at 1080p (`promo check` requires >= 28)
    fade_in: 0.25     # the remaining shot duration (>= 2 s) is full opacity; no fade-out
    title: "Credits"

Host layers are rendered once for the whole show by `promo.live2d.render_host` (offline, deterministic, ProRes 4444
with alpha) into build/live2d/, stamped by a digest of the host config, WAV hashes and renderer code, and re-used by
every livestream shot. Layer frame = global frame index, so cuts between livestream shots stay in lip sync.
"""
from __future__ import annotations

import os
import textwrap

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .. import livestream as LS
from .. import render as R
from ..cache import Stamps, code_hash, digest
from ..overlays import apply_overlays, build_overlays
from . import ShotType, shot_type

L2D_CODE = ["live2d", "livestream"]


def host_layer_path(spec, hid):
    return os.path.join(spec.build, "live2d", f"host-{hid}-{spec.OW}.mov")


def gaze_track(spec):
    """Per-frame horizontal gaze toward the app screen for a listening host: +1 = screen on the right (hosts left)."""
    import numpy as np
    c = LS.cfg(spec)
    start = 1.0 if c.get("hosts_side", "left") == "left" else -1.0
    n = int(round(spec.duration * spec.fps))
    return np.array([start * (1 - 2 * LS.side_at(c, spec, f / spec.fps)) for f in range(n)])


def _host_match(line, h):
    who = str(line.get("host") or "").strip().lower()
    return bool(who) and who in {str(h.get("id", "")).lower(), str(h.get("name", "")).lower(), str(h.get("model", "")).lower()}


def host_track(spec, h, log=print):
    """Full-show mono track for host `h` built from the spec's VO lines (`vo.lines[].host` = host id/name/model),
    each placed at its event time. Written to build/live2d/host-<id>-vo.wav (deterministic). None if no lines."""
    import soundfile as sf
    from .. import vo as VO
    cfg = spec.raw.get("vo") or {}
    lines = [ln for ln in cfg.get("lines") or [] if _host_match(ln, h)]
    if not lines:
        return None
    sr = None
    buf = None
    for ln in lines:
        if cfg.get("engine") == "files":
            x, r = VO.line_audio(spec, ln)                 # same trim/fade as the mix
        else:
            x, r = sf.read(os.path.join(spec.vo_dir, ln["file"]), dtype="float32", always_2d=True)
            x = x.mean(1)
        if sr is None:
            sr = r
            buf = np.zeros(int(round(spec.duration * sr)) + 1, np.float32)
        elif r != sr:
            raise ValueError(f"VO line {ln.get('id')}: sample rate {r} != {sr}")
        a = int(round(spec.g(ln["shot"], ln.get("at", 0.0)) * sr))
        b = min(len(buf), a + len(x))
        buf[a:b] += x[: b - a]
    out = os.path.join(spec.build, "live2d", f"host-{h.get('id')}-vo.wav")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    import io
    bio = io.BytesIO()
    sf.write(bio, buf, sr, format="WAV", subtype="PCM_16")
    data = bio.getvalue()
    old = open(out, "rb").read() if os.path.exists(out) else None
    if old != data:                       # rewrite only on change: keeps the file (and every cache keyed on it) stable
        with open(out + ".tmp", "wb") as f:
            f.write(data)
        os.replace(out + ".tmp", out)
    return out


def content_sig(path):
    """sha256 of a file's bytes (host tracks are a few MB; a size+mtime signature would churn on every rewrite)."""
    import hashlib
    if not path or not os.path.exists(path):
        return "missing"
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def ensure_host_layers(spec, log=print):
    """Render (or reuse) one alpha layer per host covering the whole show. Returns {host id: path}."""
    from .. import live2d as L2
    c = LS.cfg(spec)
    hosts = c.get("hosts") or []
    st = Stamps(spec.build)
    out = {}
    here = os.path.dirname(L2.__file__)
    extra = [os.path.join(L2.L2D_DIR, f) for f in ("render.mjs", "page.html", "assets.yaml")]
    hl = LS.host_layout(c)
    hw, hh = hl["w"], hl["h"]
    for i, h in enumerate(hosts):
        fr_ov, lh = hl["frames"][i], hh + hl["pads"][i]          # layer = panel + break-out headroom above it
        hid = str(h.get("id", i))
        p = host_layer_path(spec, hid)
        wavs = [spec.resolve(o["wav"]) if o.get("wav") else host_track(spec, o, log) for o in hosts]
        wav = wavs[i]
        partner = [w for j, w in enumerate(wavs) if j != i and w]
        partner = partner[0] if partner else None
        gz = gaze_track(spec)
        dig = digest(h, content_sig(wav) if wav else None, content_sig(partner) if partner else None, spec.duration, spec.fps, spec.scale,
                     [round(float(g), 3) for g in gz], hw, lh, fr_ov, code_hash(*L2D_CODE, extra_files=extra))
        key = f"live2d_{hid}_{spec.OW}"
        if not st.is_fresh(key, dig, [p]):
            rep = L2.render_host(h["model"], p, wav=wav, partner_wav=partner if c.get("listening_nod", True) else None,
                                 duration=spec.duration, fps=spec.fps, width=hw * spec.scale, height=lh * spec.scale,
                                 seed=int(h.get("seed", 1 + i)), gaze=gz, frame=dict(fr_ov, pad_top=fr_ov["pad_top"] * spec.scale), log=log)
            st.write(key, dig, report=rep)
        out[hid] = p
    return out


# ---------------------------------------------------------------- drawing helpers
def _style(ctx):
    return LS.style(LS.cfg(ctx.spec))


def stream_bg(ctx):
    """Static stream background (no motion). plain: dark radial glow; framed-glow: diagonal navy -> violet gradient
    with faint grain and a very faint grid."""
    st = _style(ctx)
    w, h = ctx.OW, ctx.OH
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    rng = np.random.default_rng(3)
    if st["bg"] == "diagonal":
        u = np.clip((x / w + y / h) / 2.0, 0, 1)[..., None]
        arr = np.array(st["bg_from"], np.float32) * (1 - u) + np.array(st["bg_to"], np.float32) * u
        g = int(st.get("bg_grid", 0) * ctx.K)
        if g > 0:
            grid = ((x.astype(int) % g) == 0) | ((y.astype(int) % g) == 0)
            arr += grid[..., None] * 3.0                       # very faint grid (+3/255)
        arr += rng.normal(0, float(st.get("bg_grain", 1.0)), arr.shape)
    else:
        base = np.array([9, 10, 16], np.float32)
        glow = np.array([30, 26, 58], np.float32)
        r = np.sqrt(((x - w * 0.25) / (w * 0.6)) ** 2 + ((y - h * 0.9) / (h * 0.8)) ** 2)
        gg = np.clip(1 - r, 0, 1) ** 1.8
        arr = base + (glow - base) * gg[..., None]
        arr += rng.normal(0, 1.0, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")


def ring_layer(w, h, r, b, color, alpha=255):
    """A b-px rounded border drawn OUTSIDE a w x h box (radius r): layer of (w + 2b, h + 2b); never covers the box."""
    outer = np.asarray(R.rounded_mask(w + 2 * b, h + 2 * b, r + b)).astype(np.float32)
    inner = np.zeros_like(outer)
    inner[b:b + h, b:b + w] = np.asarray(R.rounded_mask(w, h, r)).astype(np.float32)
    a = np.clip(outer - inner, 0, 255) * (alpha / 255.0)
    im = Image.new("RGBA", (w + 2 * b, h + 2 * b), tuple(color) + (0,))
    im.putalpha(Image.fromarray(a.astype(np.uint8)))
    return im


def apply_matte(im, matte, K=1):
    """Promo matte over cut-off UI at the screen edges (NOT a UI edit: it covers the crop edge, like a letterbox). `matte`
    = {left|right|top|bottom: px (output)}. Each band is filled with the panel's own background colour: per row
    (column) the median of the 40 px just inside the band, median-smoothed so thin text rows don't streak, with a
    6 px feather on the inner edge."""
    if not matte:
        return im
    a = np.asarray(im.convert("RGB")).astype(np.float32).copy()
    H, W = a.shape[:2]

    def smooth(prof, k=15):
        pad = np.pad(prof, ((k, k), (0, 0)), mode="edge")
        return np.stack([np.median(pad[i:i + 2 * k + 1], axis=0) for i in range(len(prof))])
    fe = int(6 * K)
    for side, px in matte.items():
        n = int(round(float(px) * K))
        if n <= 0:
            continue
        if side in ("left", "right"):
            strip = a[:, n:n + 40 * K] if side == "left" else a[:, W - n - 40 * K:W - n]
            col = smooth(np.median(strip, axis=1))                       # (H, 3)
            al = np.ones(n) if fe == 0 else np.clip(((n - 1 - np.arange(n)) if side == "left" else np.arange(n)) / fe, 0, 1)
            sl = slice(0, n) if side == "left" else slice(W - n, W)
            a[:, sl] = a[:, sl] * (1 - al[None, :, None]) + col[:, None, :] * al[None, :, None]
        else:
            strip = a[n:n + 40 * K] if side == "top" else a[H - n - 40 * K:H - n]
            col = smooth(np.median(strip, axis=0))                       # (W, 3)
            al = np.clip(((n - 1 - np.arange(n)) if side == "top" else np.arange(n)) / max(1, fe), 0, 1) if fe else np.ones(n)
            sl = slice(0, n) if side == "top" else slice(H - n, H)
            a[sl] = a[sl] * (1 - al[:, None, None]) + col[None, :, :] * al[:, None, None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def placeholder_screen(ctx, w, h, label):
    im = Image.new("RGBA", (w, h), (38, 40, 48, 255))
    d = ImageDraw.Draw(im)
    step = int(48 * ctx.K)
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=(46, 48, 58, 255), width=1)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=(46, 48, 58, 255), width=1)
    d.rectangle([0, 0, w, int(36 * ctx.K)], fill=(28, 30, 36, 255))
    for i, col in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
        cx = int((22 + i * 22) * ctx.K)
        d.ellipse([cx - 6 * ctx.K, 12 * ctx.K, cx + 6 * ctx.K, 24 * ctx.K], fill=col)
    f = ctx.font(40, "SemiBold")
    rows = label.split("\n")                  # multi-line labels: first row bold, centred block
    y = h / 2 - 24 * ctx.K - (len(rows) - 1) * 54 * ctx.K
    for k, row in enumerate(rows):
        fk = f if k == 0 else ctx.font(34)
        d.text(((w - d.textlength(row, font=fk)) / 2, y), row, font=fk, fill=(232, 200, 120, 255) if (k == 0 and len(rows) > 1) else (150, 154, 168, 255))
        y += 54 * ctx.K
    f2 = ctx.font(22)
    sub = "placeholder: real app footage goes here"
    d.text(((w - d.textlength(sub, font=f2)) / 2, y + 8 * ctx.K), sub, font=f2, fill=(110, 114, 128, 255))
    return im


def screen_card(ctx, w, h, card):
    """Generated card on the stream screen (intro sting / end card): title, subtitle, small lines, centred."""
    im = Image.new("RGBA", (w, h), (24, 25, 34, 255))
    y_, x_ = np.mgrid[0:h, 0:w].astype(np.float32)
    g = np.clip(1 - np.sqrt(((x_ - w * 0.5) / (w * 0.7)) ** 2 + ((y_ - h * 0.45) / (h * 0.8)) ** 2), 0, 1) ** 1.6
    arr = np.array([24, 25, 34], np.float32) + (np.array([58, 50, 110], np.float32) - [24, 25, 34]) * g[..., None]
    im = Image.fromarray(arr.astype(np.uint8)).convert("RGBA")
    d = ImageDraw.Draw(im)
    rows = []
    if card.get("title"):
        rows.append((card["title"], ctx.font(64, "Bold"), (255, 255, 255, 255), 86))
    if card.get("subtitle"):
        rows.append((card["subtitle"], ctx.font(36, "Medium"), (210, 212, 230, 255), 60))
    for ln in card.get("lines") or []:
        rows.append((ln, ctx.font(28, "Medium"), (170, 174, 196, 255), 42))
    K = ctx.K
    total = sum(r[3] for r in rows) * K
    y = (h - total) / 2
    for text, f, col, adv in rows:
        d.text(((w - d.textlength(text, font=f)) / 2, y), text, font=f, fill=col)
        y += adv * K
    return im


def framed(ctx, im, radius=None):
    """Rounded corners + soft shadow around the app screen, plus (style) an accent border and soft outer glow, all
    drawn OUTSIDE the screen box: no change to the UI pixels themselves. Returns (layer, pad). The decoration is built
    once per size and reused every frame."""
    st = _style(ctx)
    K = ctx.K
    w, h = im.size
    r = int((radius if radius is not None else st["panel_radius"]) * K)
    b = int(st.get("panel_border", 0) * K)
    gl = int(st.get("panel_glow", 0) * K)
    key = ("framed", w, h, r, b, gl, st["preset"])
    cache = ctx.__dict__.setdefault("_frame_cache", {})
    if key not in cache:
        pad = 40 * K
        W2, H2 = w + 2 * pad, h + 2 * pad
        shape = Image.new("L", (W2, H2), 0)
        shape.paste(R.rounded_mask(w + 2 * b, h + 2 * b, r + b), (pad - b, pad - b))
        sh = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        sh.putalpha(shape.point(lambda v: v * 170 // 255).filter(ImageFilter.GaussianBlur(22 * K)))
        under = _shift_img(sh, int(14 * K))                    # soft drop shadow (as before)
        if gl > 0:
            glow = Image.new("RGBA", (W2, H2), tuple(st["accent"]) + (0,))
            glow.putalpha(shape.point(lambda v: int(v * st.get("panel_glow_alpha", 0.25))).filter(ImageFilter.GaussianBlur(gl / 2)))
            under.alpha_composite(glow)
        ring = ring_layer(w, h, r, b, st["accent"]) if b > 0 else None
        cache[key] = (under, ring, R.rounded_mask(w, h, r), pad)
    under, ring, mask, pad = cache[key]
    out = under.copy()
    fg = im.convert("RGBA")
    fg.putalpha(mask)
    out.alpha_composite(fg, (pad, pad))
    if ring is not None:
        out.alpha_composite(ring, (pad - b, pad - b))
    return out, pad


def _shift_img(im, dy):
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.alpha_composite(im, (0, dy))
    return out


def dashed_rect(d, box, K, col=(255, 210, 80, 230)):
    x0, y0, x1, y1 = box
    dash = 12 * K
    for a, b, horiz, fixed in ((x0, x1, True, y0), (x0, x1, True, y1), (y0, y1, False, x0), (y0, y1, False, x1)):
        p = a
        while p < b:
            q = min(p + dash, b)
            d.line([(p, fixed), (q, fixed)] if horiz else [(fixed, p), (fixed, q)], fill=col, width=max(2, int(2 * K)))
            p += 2 * dash


def pill(ctx, text, size=20, fill=(70, 74, 88, 235), fg=(235, 237, 245, 255), weight="Bold"):
    f = ctx.font(size, weight)
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    tw = d.textlength(text, font=f)
    w, h = int(tw + 28 * ctx.K), int((size + 16) * ctx.K)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(8 * ctx.K), fill=fill)
    dd.text((14 * ctx.K, 6 * ctx.K), text, font=f, fill=fg)
    return im


def chat_panel(ctx, box, lines, t, label=None):
    """Chat strip. Lines are the hosts' own asides; `label` (e.g. "scripted chat") is drawn top-right, always visible."""
    K = ctx.K
    w, h = int((box[2] - box[0]) * K), int((box[3] - box[1]) * K)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(12 * K), fill=(16, 17, 24, 200))
    if label:
        lp = pill(ctx, label, 18, fill=(60, 64, 78, 240), weight="SemiBold")
        im.alpha_composite(lp, (int(w - lp.width - 12 * K), int(10 * K)))
    fu, ft = ctx.font(24, "Bold"), ctx.font(24, "Medium")
    lh = (h - 24 * K) / LS.MAX_CHAT_LINES
    cols = [(255, 138, 101), (129, 199, 255), (178, 235, 120), (240, 160, 255), (255, 214, 102)]
    n = len(lines)
    for j, ln in enumerate(lines):
        slot = LS.MAX_CHAT_LINES - n + j           # newest at the bottom
        a = min(1.0, max(0.0, (t - float(ln["t"])) / 0.25))
        y = 12 * K + slot * lh + (1 - a) * 10 * K
        x = 20 * K
        user = str(ln.get("user", ""))
        col = cols[sum(map(ord, user)) % len(cols)]
        d.text((x, y), user, font=fu, fill=col + (int(255 * a),))
        x += d.textlength(user + "  ", font=fu)
        d.text((x, y), str(ln["text"]), font=ft, fill=(232, 234, 240, int(255 * a)))
    return im


def header_panel(ctx, box, title, tag="EP 1"):
    """Neutral episode tag (grey pill, no LIVE badge) + title. The Live2D credit lives on the end card, not here."""
    K = ctx.K
    w, h = int((box[2] - box[0]) * K), int((box[3] - box[1]) * K)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    y = 6 * K
    if tag:
        tp = pill(ctx, tag, LS.CHROME_FONT_PX)  # ~20 px cap height (UX review T6: was 14 px)
        im.alpha_composite(tp, (0, int(y)))
        y += tp.height + 14 * K
    if title:
        ft = ctx.font(26, "SemiBold")
        for ln in textwrap.wrap(title, 26)[:2]:
            d.text((0, y), ln, font=ft, fill=(240, 240, 245, 255))
            y += 32 * K
    return im


def nameplate(ctx, text, st):
    """Lower-third host nameplate: UPPERCASE name (cap height >= nameplate_px), translucent dark pill, accent bar."""
    K = ctx.K
    size = st.get("nameplate_px", 22) / 0.727                 # Inter cap height ~0.727 em
    f = ctx.font(size, "Bold")
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    t = text.upper()
    tw = d.textlength(t, font=f)
    bar, padx, h = int(5 * K), int(14 * K), int((size + 18) * K)
    w = int(tw + bar + 2 * padx)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=(14, 15, 26, 200))
    dd.rounded_rectangle([int(10 * K), int(h * 0.22), int(10 * K) + bar, int(h * 0.78)], radius=bar // 2, fill=tuple(st["accent"]) + (255,))
    bb = dd.textbbox((0, 0), t, font=f)
    dd.text((int(10 * K) + bar + padx - bb[0] * 0, (h - (bb[3] + bb[1])) / 2), t, font=f, fill=(255, 255, 255, 255))
    return im


def name_tag(ctx, text):
    f = ctx.font(LS.CHROME_FONT_PX, "SemiBold")  # ~20 px cap height (UX review T6: was 14 px)
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    tw = d.textlength(text, font=f)
    w, h = int(tw + 28 * ctx.K), int((LS.CHROME_FONT_PX + 16) * ctx.K)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=(16, 17, 24, 215))
    dd.text((14 * ctx.K, 6 * ctx.K), text, font=f, fill=(255, 255, 255, 255))
    return im


def comp(out, im, x, y):
    """alpha_composite that tolerates layers hanging off the frame edges (crops the visible part)."""
    x, y = int(round(x)), int(round(y))
    x0, y0 = max(0, -x), max(0, -y)
    x1, y1 = min(im.width, out.width - x), min(im.height, out.height - y)
    if x1 <= x0 or y1 <= y0:
        return
    out.alpha_composite(im.crop((x0, y0, x1, y1)) if (x0, y0, x1, y1) != (0, 0, im.width, im.height) else im, (x + x0, y + y0))


class LayerReader:
    """Sequential RGBA reader of a host layer from global frame f0 (intra-only ProRes: -ss is frame accurate)."""

    def __init__(self, path, W, H, f0, fps):
        import subprocess
        self.W, self.H = W, H
        self.p = subprocess.Popen(["ffmpeg", "-v", "error", "-threads", "2", "-ss", f"{f0 / fps:.6f}", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 8)
        self.last = None

    def next(self):
        b = self.p.stdout.read(self.W * self.H * 4)
        if len(b) == self.W * self.H * 4:
            self.last = Image.frombuffer("RGBA", (self.W, self.H), b, "raw", "RGBA", 0, 1)
        return self.last

    def close(self):
        self.p.stdout.close()
        self.p.kill()
        self.p.wait()


@shot_type("livestream")
class Livestream(ShotType):
    def render(self, ctx, shot):
        spec, cfg = ctx.spec, shot.cfg
        c = LS.cfg(spec)
        if not c:
            raise ValueError("livestream shot needs a show-level `livestream:` block in promo.yaml")
        K = ctx.K
        hosts = c.get("hosts") or []
        from ..lock import heavy_lock
        with heavy_lock(f"livestream shot {shot.id}"):        # whole render holds /tmp/commission-ai-cargo.lock (re-entrant)
            return self._render(ctx, shot, c, hosts, K)

    def _render(self, ctx, shot, c, hosts, K):
        spec, cfg = ctx.spec, shot.cfg
        layers = ensure_host_layers(spec)
        hl = LS.host_layout(c)
        hw, hh = hl["w"], hl["h"]
        readers = [LayerReader(layers[str(h.get("id", i))], hw * K, (hh + hl["pads"][i]) * K, shot.f0, spec.fps) for i, h in enumerate(hosts)]
        st = _style(ctx)
        lower = st.get("nameplate") == "lower-third"
        tags = [(nameplate(ctx, h.get("name", h["model"]), st) if lower else name_tag(ctx, h.get("name", h["model"]))) for h in hosts]
        hbb = int(st.get("host_border", 0) * K)
        hring = ring_layer(hw * K, hh * K, int(16 * K), hbb, st["accent"]) if hbb > 0 else None
        # every host sits in its own panel (rounded card, same size). The host is clipped by the panel's sides and
        # bottom (mid-chest crop, rounded bottom corners) but NOT its top: a hat breaks out above the panel into the
        # layer's headroom (`promo check` livestream-framing keeps that break-out clear of everything else)
        R16 = int(16 * K)
        panel = Image.new("RGBA", (hw * K, hh * K), (0, 0, 0, 0))
        ImageDraw.Draw(panel).rounded_rectangle([0, 0, hw * K - 1, hh * K - 1], radius=R16, fill=(26, 27, 38, 215))
        pm = np.asarray(R.rounded_mask(hw * K, hh * K, R16)).astype(np.float32) / 255.0
        pm[: hh * K // 2] = 1.0                                   # only the bottom corners round off
        fades = [np.concatenate([np.ones((hl["pads"][i] * K, hw * K), np.float32), pm]) for i in range(len(hosts))]
        bg = stream_bg(ctx)
        sc = cfg.get("screen") or {"placeholder": "APP FOOTAGE"}
        sw, sh = LS.screen_size(c)
        SW, SH = int(round(sw * K)), int(round(sh * K))
        src = None
        hold_in = float(sc.get("hold_in", 0.0))
        if sc.get("source"):
            total = shot.n / ctx.fps
            src = R.Source(spec.footage_path(sc["source"]), sc.get("t_in", 0.0), sc.get("t_in", 0.0) + total * sc.get("speed", 1.0) + 0.1)
            still = None
        elif sc.get("card"):
            still = framed(ctx, screen_card(ctx, SW, SH, sc["card"]))
        else:
            still = framed(ctx, placeholder_screen(ctx, SW, SH, sc.get("placeholder", "APP FOOTAGE")))
        # dissolves over a hard cut INSIDE the take (e.g. a time-of-day snap: dusk -> day, UX review T5): around source
        # time `at`, blend the last frame before the cut (held) into the frames from the cut on (2nd reader, held first)
        diss = []
        for dv in (sc.get("dissolve") or []) if src is not None else []:
            at, dd = float(dv["at"]), float(dv.get("dur", 0.4))
            diss.append((at, dd, R.Source(spec.footage_path(sc["source"]), at, at + dd / 2 + 0.2)))
        hdr_cache = {}
        overlays = build_overlays(ctx, cfg.get("overlays"))
        show_kc = os.environ.get("PROMO_DEBUG") == "1"        # keep-clear outlines: `promo --debug` only, never in normal output
        label = (c.get("chat") or {}).get("scripted_label")

        def f(i, t):
            tg = shot.t0 + t
            L = LS.layout_at(spec, tg)
            out = bg.copy()
            frames = []
            for r, g in zip(readers, fades):
                fr = r.next()
                if fr is not None and g is not None:
                    a = np.asarray(fr).copy()
                    a[..., 3] = (a[..., 3] * g).astype(np.uint8)          # clip to the rounded panel
                    fr = Image.fromarray(a, "RGBA")
                frames.append(fr)

            def draw_hosts():
                for b in L["hosts"]:
                    if hring is not None:            # thin accent border around each host tile (outside the tile)
                        comp(out, hring, b[0] * K - hbb, b[1] * K - hbb)
                    comp(out, panel, b[0] * K, b[1] * K)
                for fr, lb in zip(frames, L["layers"]):
                    if fr is not None:
                        comp(out, fr, lb[0] * K, lb[1] * K)
                for k, (tg_, b) in enumerate(zip(tags, L["hosts"])):
                    if lower:                        # lower-third: bottom-left of the tile
                        comp(out, tg_, (b[0] + 14) * K, b[3] * K - tg_.height - 14 * K)
                    else:
                        x = int(round(((b[0] + b[2]) / 2) * K - tg_.width / 2))
                        comp(out, tg_, x, (b[3] - LS.CHROME_FONT_PX - 26) * K)
            hb = L["header"]
            key = tuple(round(v, 1) for v in hb)
            if key not in hdr_cache:
                hdr_cache.clear()
                hdr_cache[key] = header_panel(ctx, hb, c.get("title", ""), c.get("tag", "EP 1"))

            def draw_header():
                comp(out, hdr_cache[key], hb[0] * K, hb[1] * K)
            if src is not None:
                st = sc.get("t_in", 0.0) + max(0.0, t - hold_in) * sc.get("speed", 1.0)
                im = None
                for at, dd, bsrc in diss:
                    if at - dd / 2 <= st < at + dd / 2:
                        a = (st - (at - dd / 2)) / dd
                        A, B = src.frame(min(st, at - 1.0 / src.fps)), bsrc.frame(max(st, at))
                        im = Image.blend(A, B, a) if A is not None and B is not None else (B or A)
                        break
                if im is None:
                    im = src.frame(st)
                cam = sc.get("cam", (0.5, 0.5, 1.0))
                lay, pad = framed(ctx, apply_matte(R.frame_cam(ctx, im, *cam, out=(SW, SH)), sc.get("matte"), K))
            else:
                lay, pad = still
            s = L["screen"]
            comp(out, lay, s[0] * K - pad, s[1] * K - pad)
            if show_kc:
                d = ImageDraw.Draw(out)
                for kc in L["keep_clear"]:
                    dashed_rect(d, [v * K for v in kc["box"]], K)
            draw_header()          # hosts/header never overlap the screen (a move slides them off the frame edge)
            draw_hosts()
            ch = L["chat"]
            if ch is not None:     # no asides -> no chat strip at all (UX review T2/T3)
                comp(out, chat_panel(ctx, ch, LS.chat_lines_at(c, tg), tg, label), ch[0] * K, ch[1] * K)
            return apply_overlays(overlays, out, t)

        try:
            R.run_shot(ctx, shot, f)
        finally:
            for r in readers:
                r.close()
            if src is not None:
                src.close()
            for _, _, bsrc in diss:
                bsrc.close()
        return dict(src=sc.get("source") or ("generated card" if sc.get("card") else "placeholder screen"), inout=f"global frames {shot.f0}-{shot.f0 + shot.n - 1}",
                    move=f"livestream layout, hosts {c.get('hosts_side', 'left')}" + (", one slide" if LS.moves(c) else ""),
                    caption=" / ".join(f"'{o.cfg['text']}'" for o in overlays if o.role == "caption") or "none",
                    notes=f"Live2D hosts: {', '.join(h['model'] for h in hosts)}; credit on the live2d_credits end card")


def credit_lines(spec):
    """(notice, [(model name, credit)]) for every Live2D model used by the show's hosts."""
    from .. import live2d as L2
    reg = L2.registry()
    seen, models = set(), []
    for h in LS.cfg(spec).get("hosts") or []:
        if h["model"] in seen:
            continue
        seen.add(h["model"])
        m = reg["models"][h["model"]]
        models.append((m["name"], m.get("credit", "")))
    return reg["notice"]["long"], models


LICENCE_LINE = "Live2D sample models used under the Live2D Free Material License Agreement (Original Characters)."


def credits_card(ctx, notice, models, size=30, title="Credits", part=None):
    """Centred credit block (horizontally + vertically, centred lines): title, the official notice, the licence line
    on its own line under it (same size/weight/colour), then one line per model credit. `part` splits it over two
    cards (UX review T6: ~55 words in 3 s can't be read): 1 = title + notice + licence line, 2 = the model credits."""
    K = ctx.K
    out = stream_bg(ctx)
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    W, H = ctx.OW, ctx.OH
    fb, fh = ctx.font(size, "Medium"), ctx.font(size * 1.6, "Bold")
    body = (228, 230, 238, 255)
    lh = size * 1.45 * K
    maxw = W - 2 * 200 * K

    def wrap(text, font, col, adv):
        words, line, rows = text.split(), "", []
        for wd in words:
            cand = (line + " " + wd).strip()
            if d.textlength(cand, font=font) > maxw and line:
                rows.append((line, font, col, adv))
                line = wd
            else:
                line = cand
        if line:
            rows.append((line, font, col, adv))
        return rows
    blocks = []
    if title:
        blocks.append(wrap(title, fh, (255, 255, 255, 255), size * 2.4 * K))
    if part in (None, 1):
        blocks.append(wrap(notice, fb, body, lh) + wrap(LICENCE_LINE, fb, body, lh))  # licence line right under the notice
    if part in (None, 2):
        blocks.append([r for name, cr in models for r in wrap(f"{name}: {cr}" if cr else name, fb, body, lh)])
    gap = 28 * K
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    y = 0
    for b in blocks:
        for text, font, col, adv in b:
            tw = dl.textlength(text, font=font)
            dl.text(((W - tw) / 2, y), text, font=font, fill=col)       # each line centred
            y += adv
        y += gap
    x0, y0, x1, y1 = layer.getbbox()                                    # centre the INK of the whole block
    comp(out, layer, (W - (x1 - x0)) / 2 - x0, (H - (y1 - y0)) / 2 - y0)
    return out


@shot_type("live2d_credits")
class Live2DCredits(ShotType):
    """End card with the full Live2D notice + model credits (body size, >= 2 s at full opacity)."""

    def render(self, ctx, shot):
        notice, models = credit_lines(ctx.spec)
        size = float(shot.get("size", 30))
        part = shot.get("part")
        card = credits_card(ctx, notice, models, size=size, title=shot.get("title", "Credits" if part in (None, 1) else "Models"),
                            part=part)
        bg = stream_bg(ctx)
        fin = float(shot.get("fade_in", 0.25))
        overlays = build_overlays(ctx, shot.cfg.get("overlays"))

        def f(i, t):
            a = 1.0 if fin <= 0 else min(1.0, t / fin)
            return apply_overlays(overlays, Image.blend(bg, card, a) if a < 1 else card.copy(), t)
        R.run_shot(ctx, shot, f)
        return dict(src="generated end card", inout="-", move="none", caption="none",
                    notes=f"Live2D {dict([(1, 'notice + licence line'), (2, 'model credits')]).get(part, 'notice + credits')} for {', '.join(n for n, _ in models)} at {size:.0f} px, "
                          f"{shot.dur - fin:.2f} s at full opacity")
