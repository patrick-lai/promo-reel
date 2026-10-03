"""`livestream` shot: app screen + Live2D hosts + chat strip, laid out by promo.livestream.layout_at.

Shot keys (per shot; the show-level layout, hosts and chat live in the spec's `livestream:` block):
    screen: {source: <footage clip id>, t_in: 0, speed: 1, cam: [cx, cy, w]}   real app footage (never edited)
    screen: {placeholder: "APP FOOTAGE"}                                       grey placeholder for drafts / demos
    overlays: [...]                                                            usual overlays (QA'd against keep-clear)

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
from ..cache import Stamps, code_hash, digest, file_sig
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


def ensure_host_layers(spec, log=print):
    """Render (or reuse) one alpha layer per host covering the whole show. Returns {host id: path}."""
    from .. import live2d as L2
    c = LS.cfg(spec)
    hosts = c.get("hosts") or []
    st = Stamps(spec.build)
    out = {}
    here = os.path.dirname(L2.__file__)
    extra = [os.path.join(L2.L2D_DIR, f) for f in ("render.mjs", "page.html", "assets.yaml")]
    for i, h in enumerate(hosts):
        hid = str(h.get("id", i))
        p = host_layer_path(spec, hid)
        wav = spec.resolve(h["wav"]) if h.get("wav") else None
        partner = [spec.resolve(o["wav"]) for j, o in enumerate(hosts) if j != i and o.get("wav")]
        partner = partner[0] if partner else None
        gz = gaze_track(spec)
        dig = digest(h, file_sig(wav) if wav else None, file_sig(partner) if partner else None, spec.duration, spec.fps, spec.scale,
                     [round(float(g), 3) for g in gz], LS.HOST_W, LS.HOST_H, code_hash(*L2D_CODE, extra_files=extra))
        key = f"live2d_{hid}_{spec.OW}"
        if not st.is_fresh(key, dig, [p]):
            rep = L2.render_host(h["model"], p, wav=wav, partner_wav=partner if c.get("listening_nod", True) else None,
                                 duration=spec.duration, fps=spec.fps, width=LS.HOST_W * spec.scale, height=LS.HOST_H * spec.scale,
                                 seed=int(h.get("seed", 1 + i)), gaze=gz, frame=h.get("frame"), log=log)
            st.write(key, dig, report=rep)
        out[hid] = p
    return out


# ---------------------------------------------------------------- drawing helpers
def stream_bg(ctx):
    w, h = ctx.OW, ctx.OH
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.array([9, 10, 16], np.float32)
    glow = np.array([30, 26, 58], np.float32)
    r = np.sqrt(((x - w * 0.25) / (w * 0.6)) ** 2 + ((y - h * 0.9) / (h * 0.8)) ** 2)
    g = np.clip(1 - r, 0, 1) ** 1.8
    arr = base + (glow - base) * g[..., None]
    arr += np.random.default_rng(3).normal(0, 1.0, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")


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
    tw = d.textlength(label, font=f)
    d.text(((w - tw) / 2, h / 2 - 24 * ctx.K), label, font=f, fill=(150, 154, 168, 255))
    f2 = ctx.font(22)
    sub = "placeholder: real app footage goes here"
    d.text(((w - d.textlength(sub, font=f2)) / 2, h / 2 + 32 * ctx.K), sub, font=f2, fill=(110, 114, 128, 255))
    return im


def framed(ctx, im, radius=14):
    """Rounded corners + soft shadow around the app screen (no change to the UI pixels themselves)."""
    w, h = im.size
    im = im.convert("RGBA")
    im.putalpha(R.rounded_mask(w, h, int(radius * ctx.K)))
    return R.soft_shadow_layer(ctx, im, blur=22, alpha=170, pad=40)


def dashed_rect(d, box, K, col=(255, 210, 80, 230)):
    x0, y0, x1, y1 = box
    dash = 12 * K
    for a, b, horiz, fixed in ((x0, x1, True, y0), (x0, x1, True, y1), (y0, y1, False, x0), (y0, y1, False, x1)):
        p = a
        while p < b:
            q = min(p + dash, b)
            d.line([(p, fixed), (q, fixed)] if horiz else [(fixed, p), (fixed, q)], fill=col, width=max(2, int(2 * K)))
            p += 2 * dash


def chat_panel(ctx, box, lines, t):
    K = ctx.K
    w, h = int((box[2] - box[0]) * K), int((box[3] - box[1]) * K)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(12 * K), fill=(16, 17, 24, 200))
    fu, ft = ctx.font(24, "Bold"), ctx.font(24, "Medium")
    lh = (h - 24 * K) / LS.MAX_CHAT_LINES
    cols = [(255, 138, 101), (129, 199, 255), (178, 235, 120), (240, 160, 255), (255, 214, 102)]
    n = len(lines)
    for j, ln in enumerate(lines):
        slot = LS.MAX_CHAT_LINES - n + j           # newest at the bottom
        a = min(1.0, max(0.0, (t - float(ln["t"])) / 0.25))
        y = 12 * K + slot * lh + (1 - a) * 10 * K
        x = 20 * K
        user = str(ln.get("user", "viewer"))
        col = cols[sum(map(ord, user)) % len(cols)]
        d.text((x, y), user, font=fu, fill=col + (int(255 * a),))
        x += d.textlength(user + "  ", font=fu)
        d.text((x, y), str(ln["text"]), font=ft, fill=(232, 234, 240, int(255 * a)))
    return im


def header_panel(ctx, box, title, notice):
    K = ctx.K
    w, h = int((box[2] - box[0]) * K), int((box[3] - box[1]) * K)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fl = ctx.font(22, "Bold")
    lw = d.textlength("LIVE", font=fl)
    d.rounded_rectangle([0, 6 * K, lw + 46 * K, 44 * K], radius=int(8 * K), fill=(229, 57, 53, 255))
    d.ellipse([12 * K, 19 * K, 24 * K, 31 * K], fill=(255, 255, 255, 255))
    d.text((32 * K, 11 * K), "LIVE", font=fl, fill=(255, 255, 255, 255))
    y = 58 * K
    if title:
        ft = ctx.font(26, "SemiBold")
        for ln in textwrap.wrap(title, 26)[:2]:
            d.text((0, y), ln, font=ft, fill=(240, 240, 245, 255))
            y += 32 * K
    fn = ctx.font(13, "Medium")
    y = max(y + 4 * K, h - 3 * 17 * K)
    for ln in textwrap.wrap(notice, 52)[:3]:
        d.text((0, y), ln, font=fn, fill=(170, 172, 186, 255))
        y += 17 * K
    return im


def name_tag(ctx, text):
    f = ctx.font(20, "SemiBold")
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    tw = d.textlength(text, font=f)
    w, h = int(tw + 28 * ctx.K), int(34 * ctx.K)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=(16, 17, 24, 215))
    dd.text((14 * ctx.K, 5 * ctx.K), text, font=f, fill=(255, 255, 255, 255))
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
        layers = ensure_host_layers(spec)
        readers = [LayerReader(layers[str(h.get("id", i))], LS.HOST_W * K, LS.HOST_H * K, shot.f0, spec.fps) for i, h in enumerate(hosts)]
        tags = [name_tag(ctx, h.get("name", h["model"])) for h in hosts]
        # hosts whose layer ends above the frame bottom get a soft fade instead of a hard cut across the body
        L0 = LS.layout_at(spec, shot.t0)
        fades = []
        for b in L0["hosts"]:
            if b[3] < LS.FRAME_H - 1:
                hpx, fpx = LS.HOST_H * K, int(110 * K)
                g = np.ones(hpx, np.float32)
                g[hpx - fpx:] = np.linspace(1, 0, fpx) ** 1.5
                fades.append(g[:, None])
            else:
                fades.append(None)
        bg = stream_bg(ctx)
        sc = cfg.get("screen") or {"placeholder": "APP FOOTAGE"}
        sw, sh = LS.screen_size(c)
        SW, SH = int(round(sw * K)), int(round(sh * K))
        src = None
        if sc.get("source"):
            total = shot.n / ctx.fps
            src = R.Source(spec.footage_path(sc["source"]), sc.get("t_in", 0.0), sc.get("t_in", 0.0) + total * sc.get("speed", 1.0) + 0.1)
            still = None
        else:
            still = framed(ctx, placeholder_screen(ctx, SW, SH, sc.get("placeholder", "APP FOOTAGE")))
        from .. import live2d as L2
        notice = L2.registry()["notice"]["short"]
        hdr_cache = {}
        overlays = build_overlays(ctx, cfg.get("overlays"))
        show_kc = bool(c.get("show_keep_clear")) and src is None       # outline only on placeholders, never on real UI

        def f(i, t):
            tg = shot.t0 + t
            L = LS.layout_at(spec, tg)
            out = bg.copy()
            frames = []
            for r, g in zip(readers, fades):
                fr = r.next()
                if fr is not None and g is not None:
                    a = np.asarray(fr).copy()
                    a[..., 3] = (a[..., 3] * g).astype(np.uint8)
                    fr = Image.fromarray(a, "RGBA")
                frames.append(fr)

            def draw_hosts():
                for k, (fr, b) in enumerate(zip(frames, L["hosts"])):
                    if fr is not None:
                        comp(out, fr, b[0] * K, b[1] * K)
                for k, (tg_, b) in enumerate(zip(tags, L["hosts"])):
                    x = int(round(((b[0] + b[2]) / 2) * K - tg_.width / 2))
                    comp(out, tg_, x, (b[3] - 44) * K)
            hb = L["header"]
            key = tuple(round(v, 1) for v in hb)
            if key not in hdr_cache:
                hdr_cache.clear()
                hdr_cache[key] = header_panel(ctx, hb, c.get("title", ""), notice)

            def draw_header():
                comp(out, hdr_cache[key], hb[0] * K, hb[1] * K)
            if L["hosts_z"] == "below":
                draw_header()
                draw_hosts()
            if src is not None:
                im = src.frame(sc.get("t_in", 0.0) + t * sc.get("speed", 1.0))
                cam = sc.get("cam", (0.5, 0.5, 1.0))
                lay, pad = framed(ctx, R.frame_cam(ctx, im, *cam, out=(SW, SH)))
            else:
                lay, pad = still
            s = L["screen"]
            comp(out, lay, s[0] * K - pad, s[1] * K - pad)
            if show_kc:
                d = ImageDraw.Draw(out)
                for kc in L["keep_clear"]:
                    dashed_rect(d, [v * K for v in kc["box"]], K)
            if L["hosts_z"] == "above":
                draw_header()
                draw_hosts()
            ch = L["chat"]
            comp(out, chat_panel(ctx, ch, LS.chat_lines_at(c, tg), tg), ch[0] * K, ch[1] * K)
            return apply_overlays(overlays, out, t)

        try:
            R.run_shot(ctx, shot, f)
        finally:
            for r in readers:
                r.close()
            if src is not None:
                src.close()
        return dict(src=sc.get("source") or "placeholder screen", inout=f"global frames {shot.f0}-{shot.f0 + shot.n - 1}",
                    move=f"livestream layout, hosts {c.get('hosts_side', 'left')}" + (", one slide" if LS.moves(c) else ""),
                    caption=" / ".join(f"'{o.cfg['text']}'" for o in overlays if o.role == "caption") or "none",
                    notes=f"Live2D hosts: {', '.join(h['model'] for h in hosts)}; notice: {notice}")
