"""`livestream` shot: app screen + Live2D hosts + chat strip, laid out by promo.livestream.layout_at.

Shot keys (per shot; the show-level layout, hosts and chat live in the spec's `livestream:` block):
    screen: {source: <footage clip id>, t_in: 0, speed: 1, cam: [cx, cy, w]}   real app footage (never edited)
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
    hw, hh = LS.host_size(c)
    for i, h in enumerate(hosts):
        hid = str(h.get("id", i))
        p = host_layer_path(spec, hid)
        wav = spec.resolve(h["wav"]) if h.get("wav") else None
        partner = [spec.resolve(o["wav"]) for j, o in enumerate(hosts) if j != i and o.get("wav")]
        partner = partner[0] if partner else None
        gz = gaze_track(spec)
        dig = digest(h, file_sig(wav) if wav else None, file_sig(partner) if partner else None, spec.duration, spec.fps, spec.scale,
                     [round(float(g), 3) for g in gz], hw, hh, code_hash(*L2D_CODE, extra_files=extra))
        key = f"live2d_{hid}_{spec.OW}"
        if not st.is_fresh(key, dig, [p]):
            rep = L2.render_host(h["model"], p, wav=wav, partner_wav=partner if c.get("listening_nod", True) else None,
                                 duration=spec.duration, fps=spec.fps, width=hw * spec.scale, height=hh * spec.scale,
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
        tp = pill(ctx, tag, 20)
        im.alpha_composite(tp, (0, int(y)))
        y += tp.height + 14 * K
    if title:
        ft = ctx.font(26, "SemiBold")
        for ln in textwrap.wrap(title, 26)[:2]:
            d.text((0, y), ln, font=ft, fill=(240, 240, 245, 255))
            y += 32 * K
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
        from ..lock import heavy_lock
        with heavy_lock(f"livestream shot {shot.id}"):        # whole render holds /tmp/commission-ai-cargo.lock (re-entrant)
            return self._render(ctx, shot, c, hosts, K)

    def _render(self, ctx, shot, c, hosts, K):
        spec, cfg = ctx.spec, shot.cfg
        layers = ensure_host_layers(spec)
        hw, hh = LS.host_size(c)
        readers = [LayerReader(layers[str(h.get("id", i))], hw * K, hh * K, shot.f0, spec.fps) for i, h in enumerate(hosts)]
        tags = [name_tag(ctx, h.get("name", h["model"])) for h in hosts]
        # hosts whose layer ends above the frame bottom get a soft fade instead of a hard cut across the body
        L0 = LS.layout_at(spec, shot.t0)
        fades = []
        for b in L0["hosts"]:
            if b[3] < LS.FRAME_H - 1:
                hpx, fpx = hh * K, int(110 * K)
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
                hdr_cache[key] = header_panel(ctx, hb, c.get("title", ""), c.get("tag", "EP 1"))

            def draw_header():
                comp(out, hdr_cache[key], hb[0] * K, hb[1] * K)
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
            draw_header()          # hosts/header never overlap the screen (a move slides them off the frame edge)
            draw_hosts()
            ch = L["chat"]
            comp(out, chat_panel(ctx, ch, LS.chat_lines_at(c, tg), tg, label), ch[0] * K, ch[1] * K)
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


def credits_card(ctx, notice, models, size=30, title="Credits"):
    K = ctx.K
    out = stream_bg(ctx)
    d = ImageDraw.Draw(out)
    W = ctx.OW
    fb, fh, fn = ctx.font(size, "Medium"), ctx.font(size * 1.6, "Bold"), ctx.font(size, "Bold")
    lh = size * 1.45 * K
    x0 = 200 * K
    maxw = W - 2 * x0
    blocks = []
    if title:
        blocks.append([(title, fh, (255, 255, 255, 255), size * 2.4 * K)])

    def wrap(text, font, col):
        words, line, rows = text.split(), "", []
        for wd in words:
            cand = (line + " " + wd).strip()
            if d.textlength(cand, font=font) > maxw and line:
                rows.append((line, font, col, lh))
                line = wd
            else:
                line = cand
        if line:
            rows.append((line, font, col, lh))
        return rows
    blocks.append(wrap(notice, fb, (228, 230, 238, 255)))
    for name, cr in models:
        blocks.append(wrap(f"{name}: {cr}", fb, (228, 230, 238, 255)) if cr else wrap(name, fb, (228, 230, 238, 255)))
    blocks.append(wrap("Live2D sample models used under the Live2D Free Material License (Original Characters).", fb, (180, 184, 198, 255)))
    total = sum(r[3] for b in blocks for r in b) + 24 * K * (len(blocks) - 1)
    y = (ctx.OH - total) / 2
    for b in blocks:
        for text, font, col, adv in b:
            d.text((x0, y), text, font=font, fill=col)
            y += adv
        y += 24 * K
    return out


@shot_type("live2d_credits")
class Live2DCredits(ShotType):
    """End card with the full Live2D notice + model credits (body size, >= 2 s at full opacity)."""

    def render(self, ctx, shot):
        notice, models = credit_lines(ctx.spec)
        size = float(shot.get("size", 30))
        card = credits_card(ctx, notice, models, size=size, title=shot.get("title", "Credits"))
        bg = stream_bg(ctx)
        fin = float(shot.get("fade_in", 0.25))
        overlays = build_overlays(ctx, shot.cfg.get("overlays"))

        def f(i, t):
            a = 1.0 if fin <= 0 else min(1.0, t / fin)
            return apply_overlays(overlays, Image.blend(bg, card, a) if a < 1 else card.copy(), t)
        R.run_shot(ctx, shot, f)
        return dict(src="generated end card", inout="-", move="none", caption="none",
                    notes=f"Live2D notice + credits for {', '.join(n for n, _ in models)} at {size:.0f} px, "
                          f"{shot.dur - fin:.2f} s at full opacity")
