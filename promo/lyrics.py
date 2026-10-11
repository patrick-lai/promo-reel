"""Lyrics for music videos (style preset `anime-mv`): import, align to the sung vocal, lay out (horizontal or vertical
Japanese), animate per character, and gate. `promo lyrics import|align|show`.

Spec (show-level, global output seconds; `beats: [a, b]` instead of `t` works too):
    lyrics:
      font: [<path>, ...]                 first existing file wins (default: Hiragino Mincho ProN, then Noto Serif JP)
      style: {layout: band, size: 34, color: [44, 58, 74], tracking: 0.32, y: 1012, anim: fade, fade_s: 0.12}
      lines:
        - {t: [3.10, 6.20], text: 浮つく甘い街の喧騒, sung: [3.12, 5.90]}
        - {t: [6.3, 9.0], text: 故に感情線は渋滞, layout: vertical, x: 1500, y: 220, anim: type}
Layouts:
    band       one small tracked line centred at `y` (the reference: in the cream bar under a letterboxed picture)
    center     larger, centred on the picture, white with a soft shadow
    vertical   tategaki column (top-down, right-to-left), top at (`x`, `y`); 、。「」ー etc. use their vertical forms
    big        one or two huge characters (a kinetic kanji over the picture), white, at (`x`, `y`)
Anims (`anim`):
    fade       the whole line fades in / out over `fade_s`
    type       characters appear one by one across the first 60 % of the sung span (min 0.04 s each), then hold
    ink        per character: fade + 4 px rise + blur-to-sharp, staggered like `type`
    none       hard on / off
`sung: [a, b]` is what `promo lyrics align` measured on the vocal; `t` defaults to it. Lines it could not place carry
`unsynced: true` (gate lyrics-sync WARNs).

Gates (`promo check`, preset anime-mv): lyrics-glyphs (FAIL: a character the font cannot draw, no tofu), lyrics-safe
(FAIL: a line outside title-safe), lyrics-hold (FAIL: on screen < 0.8 s), lyrics-overlap (WARN: two band lines at once),
lyrics-sync (WARN: a start > 0.25 s from the sung vocal, or unsynced lines).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

JP_FONTS = ["/System/Library/Fonts/ヒラギノ明朝 ProN.ttc", "/Library/Fonts/NotoSerifJP-Regular.otf",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"]
DEFAULT_STYLE = dict(layout="band", size=34, color=[44, 58, 74], tracking=0.32, y=1012, anim="fade", fade_s=0.12,
                     center=dict(size=58, color=[255, 255, 255], y=540, shadow=0.55),
                     vertical=dict(size=52, color=[255, 255, 255], x=1560, y=200, shadow=0.55, tracking=0.12),
                     big=dict(size=260, color=[255, 255, 255], x=960, y=540, shadow=0.35))
SAFE = (0.05, 0.05)                          # title-safe margins (fraction of width / height)
SAFE_BAND = (0.05, 0.035)                    # the band line sits in the letterbox under the picture: action-safe (the reference's ink reaches y 1028 of 1080)
MIN_HOLD_S = 0.8
SYNC_TOL_S = 0.25
VERTICAL_FORMS = {"、": "︑", "。": "︒", "「": "﹁", "」": "﹂", "『": "﹃", "』": "﹄", "（": "︵", "）": "︶", "(": "︵", ")": "︶",
                  "…": "︙", "‥": "︰", "！": "︕", "？": "︖", "〜": "︴"}
ROTATE = set("ー-—～~=＝→←")                 # drawn rotated 90 degrees in a vertical column
SMALL = set("ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ")


class LyricsError(Exception):
    pass


# ---------------------------------------------------------------- import
def _ts(s):
    s = s.strip().replace(",", ".")
    parts = [float(p) for p in s.split(":")]
    v = 0.0
    for p in parts:
        v = v * 60 + p
    return v


def parse(text, fmt=None):
    """Lines [{t: [a, b] | None, text}] from .srt, .lrc or plain text (one line per lyric line, no times)."""
    fmt = fmt or ("srt" if re.search(r"\d\d:\d\d:\d\d[,.]\d+\s*-->", text) else "lrc" if re.search(r"^\[\d+:\d", text, re.M) else "txt")
    out = []
    if fmt == "srt":
        for block in re.split(r"\n\s*\n", text.strip()):
            m = re.search(r"([\d:,.]+)\s*-->\s*([\d:,.]+)\s*\n(.+)", block, re.S)
            if m:
                body = " ".join(l.strip() for l in m.group(3).splitlines() if l.strip())
                out.append(dict(t=[round(_ts(m.group(1)), 3), round(_ts(m.group(2)), 3)], text=body))
    elif fmt == "lrc":
        rows = []
        for l in text.splitlines():
            m = re.match(r"\[(\d+:\d+(?:\.\d+)?)\](.*)", l.strip())
            if m:
                rows.append((_ts(m.group(1)), m.group(2).strip()))
        rows.sort()
        for i, (t, body) in enumerate(rows):
            if body:
                end = rows[i + 1][0] if i + 1 < len(rows) else t + 3.0
                out.append(dict(t=[round(t, 3), round(end, 3)], text=body))
    else:
        out = [dict(t=None, text=l.strip()) for l in text.splitlines() if l.strip()]
    for l in out:
        l["text"] = re.sub(r"\s{2,}", "\u3000", l["text"])
    return out


def track_to_edit(spec, t):
    """Map a time in the music SOURCE file to output time through music.edit.segments (None = cut out of the edit)."""
    m = (spec.raw.get("music") or {}) if spec is not None else {}
    segs = (m.get("edit") or {}).get("segments")
    if not segs:
        return t
    TB, OFF, B = m["track_beat"], m["track_offset"], spec.timeline.B
    for e0, k0, k1 in segs:
        a, b = OFF + k0 * TB, OFF + k1 * TB
        if a - 1e-6 <= t <= b + 1e-6:
            return e0 * B + (t - a) * (B / TB)
    return None


def import_lines(spec, text, fmt=None, track_time=True):
    """Parsed lines mapped into output time (lines outside the music edit are dropped). Plain text lines get no times."""
    res = []
    for l in parse(text, fmt):
        if l["t"] is None:
            res.append(dict(text=l["text"], unsynced=True))
            continue
        a, b = l["t"]
        if track_time:
            a, b = track_to_edit(spec, a), track_to_edit(spec, b)
            if a is None and b is None:
                continue
            a = 0.0 if a is None else a
            b = spec.duration if b is None else b
        res.append(dict(t=[round(a, 3), round(b, 3)], text=l["text"]))
    return res


# ---------------------------------------------------------------- align
def _norm(s):
    """Comparable characters: NFKC, katakana -> hiragana, no spaces / punctuation."""
    s = unicodedata.normalize("NFKC", s)
    out = []
    for ch in s:
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:
            ch = chr(o - 0x60)
        if unicodedata.category(ch)[0] in "LN":
            out.append(ch)
    return "".join(out)


def asr_chars(words):
    """[(char, start, end)] from ASR words [{w, start, end}], each word's span shared evenly over its characters."""
    res = []
    for w in words:
        cs = _norm(w["w"])
        if not cs:
            continue
        d = (w["end"] - w["start"]) / len(cs)
        for i, c in enumerate(cs):
            res.append((c, w["start"] + i * d, w["start"] + (i + 1) * d))
    return res


def align_lines(lines, words, per_char_s=0.16):
    """Set `sung: [a, b]` on each line from ASR word timestamps (fuzzy character match over the whole song, so ASR kanji
    mistakes only cost the characters they touch). A line keeps its imported `t` when nothing matched; with no `t` either it
    is marked unsynced. Returns (matched_fraction, lines)."""
    chars = asr_chars(words)
    hyp = "".join(c for c, _, _ in chars)
    ref, owner = [], []
    for li, l in enumerate(lines):
        for c in _norm(l["text"]):
            ref.append(c)
            owner.append(li)
    sm = difflib.SequenceMatcher(None, "".join(ref), hyp, autojunk=False)
    hit = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            hit[a + k] = b + k
    pos = 0
    total = 0
    for li, l in enumerate(lines):
        n = len(_norm(l["text"]))
        idx = [hit[pos + k] for k in range(n) if (pos + k) in hit]
        firsts = [k for k in range(n) if (pos + k) in hit]
        pos += n
        if len(idx) >= max(1, n // 3):
            a = chars[idx[0]][1] - firsts[0] * per_char_s
            b = chars[idx[-1]][2] + (n - 1 - firsts[-1]) * per_char_s
            l["sung"] = [round(max(a, 0.0), 3), round(b, 3)]
            l.pop("unsynced", None)
            total += len(idx)
        elif not l.get("t"):
            l["unsynced"] = True
    return (total / max(len(ref), 1)), lines


def transcribe(wav_path, t0=0.0, t1=None, model="large-v3"):
    """Japanese word timestamps for [t0, t1] of a file, in that file's time. Audio goes in as an array (PyAV-free)."""
    import soundfile as sf
    from faster_whisper import WhisperModel
    y, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    a, b = int(t0 * sr), int((t1 or len(y) / sr) * sr)
    y = y[a:b]
    if sr != 16000:
        import librosa
        y = librosa.resample(y, orig_sr=sr, target_sr=16000)
    m = WhisperModel(model, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(y, language="ja", word_timestamps=True, vad_filter=False, beam_size=5, condition_on_previous_text=False)
    return [dict(w=w.word, start=round(float(w.start) + t0, 3), end=round(float(w.end) + t0, 3)) for s in segs for w in (s.words or [])]


def refine_starts(words, voice, t0=0.0, min_word_s=0.4):
    """Whisper puts the breath before a sung phrase into its first word (the word starts where the last one ended). On the separated
    voice, a long word's real onset is the rise after the quietest point (the breath) inside it. `voice` is (samples, rate) starting at
    music-file time t0; words are music-file times. Words without a clear dip (< 8 dB) keep their start."""
    y, sr = voice
    y = y.mean(axis=1) if y.ndim > 1 else y
    hop = int(sr * 0.01)
    n = max(0, (len(y) - 2 * hop) // hop)
    frames = np.lib.stride_tricks.sliding_window_view(y, 2 * hop)[::hop][:n]
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)
    out = []
    for w in words:
        w = dict(w)
        if w["end"] - w["start"] >= min_word_s:
            i0, i1 = int((w["start"] - t0) / 0.01), int((w["end"] - t0) / 0.01)
            seg = db[max(0, i0):max(0, i1) + 1]
            k = int(np.argmin(seg)) if len(seg) >= 5 else 0
            # a breath: a dip of >= 8 dB in the first 70 % of the word with >= 0.15 s of singing after it (a dip at the end is the next breath)
            if len(seg) >= 5 and k < 0.7 * len(seg) and seg[k:].max() - seg[k] >= 8:
                j = k + int(np.argmax(seg[k:] > seg[k] + 0.5 * (seg[k:].max() - seg[k])))
                if len(seg) - j >= 15:
                    w["start"] = round(t0 + (max(0, i0) + j) * 0.01, 3)
        out.append(w)
    return out


def separate_vocals(src, t0, t1, out):
    """The sung voice alone (HTDemucs) for [t0, t1] of `src`, written to `out` (44.1 kHz stereo). Whisper's word starts on a full
    mix drift 0.5-0.7 s on sung vocals; on the separated voice they land within a few hundredths of the singing."""
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
    except ImportError as e:
        raise LyricsError("--separate needs demucs and torch (`pip install demucs`, e.g. into a --target dir on PYTHONPATH)") from e
    import librosa
    import soundfile as sf
    y, sr = sf.read(str(src), dtype="float32", always_2d=True)
    y = y[int(t0 * sr):int(t1 * sr) if t1 else None]
    model = get_model("htdemucs")
    model.eval()
    if sr != model.samplerate:
        y = librosa.resample(y.T, orig_sr=sr, target_sr=model.samplerate).T
    if y.shape[1] == 1:
        y = np.repeat(y, 2, axis=1)
    x = torch.from_numpy(np.ascontiguousarray(y.T))
    ref = x.mean(0)
    with torch.no_grad():
        stems = apply_model(model, ((x - ref.mean()) / ref.std())[None], device="cpu", split=True, overlap=0.25, progress=False)[0]
    voc = (stems[model.sources.index("vocals")] * ref.std() + ref.mean()).numpy().T
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sf.write(out, voc, model.samplerate)
    return out


# ---------------------------------------------------------------- spec side
def block(spec):
    return (spec.raw.get("lyrics") or {}) if spec is not None else {}


def style_of(spec):
    from .styles import deep_merge
    st = (getattr(spec, "style", None) or {}).get("lyrics") or {}
    return deep_merge(deep_merge(DEFAULT_STYLE, st), block(spec).get("style") or {})


def line_times(spec, l):
    """(a, b) output seconds of a line: `t`, else `beats`, else `sung`; None when it has no time yet."""
    if l.get("t"):
        return float(l["t"][0]), float(l["t"][1])
    if l.get("beats"):
        return spec.timeline.t(l["beats"][0]), spec.timeline.t(l["beats"][1])
    if l.get("sung"):
        return float(l["sung"][0]), float(l["sung"][1])
    return None


def lines(spec):
    """Timed lines with resolved style keys: dicts(text, a, b, layout, anim, size, color, x, y, tracking, shadow, fade_s, i)."""
    st = style_of(spec)
    res = []
    for i, l in enumerate(block(spec).get("lines") or []):
        tt = line_times(spec, l)
        if not tt or not str(l.get("text", "")).strip():
            continue
        lay = l.get("layout", st["layout"])
        base = dict(size=st["size"], color=st["color"], tracking=st["tracking"], y=st["y"], x=960, shadow=0.0)
        if lay in ("center", "vertical", "big"):
            base.update(st.get(lay) or {})
        for k in ("size", "color", "tracking", "x", "y", "shadow"):
            if l.get(k) is not None:
                base[k] = l[k]
        res.append(dict(base, i=i, text=str(l["text"]), a=tt[0], b=tt[1], layout=lay, anim=l.get("anim", st["anim"]),
                        fade_s=float(l.get("fade_s", st["fade_s"])), sung=l.get("sung"), unsynced=bool(l.get("unsynced"))))
    return res


def font_path(spec):
    cands = block(spec).get("font") or (style_of(spec).get("font"))
    cands = ([cands] if isinstance(cands, str) else list(cands or [])) + JP_FONTS
    for p in cands:
        p = spec.resolve(p) if spec is not None and p and not os.path.isabs(os.path.expanduser(p)) else os.path.expanduser(p or "")
        if p and os.path.exists(p):
            return p
    raise LyricsError("no Japanese font found; set lyrics.font to a .ttf/.otf/.ttc (e.g. Noto Serif JP)")


_FONTS = {}


def load_font(path, px):
    k = (path, int(px))
    if k not in _FONTS:
        _FONTS[k] = ImageFont.truetype(path, max(6, int(px)))
    return _FONTS[k]


def missing_glyphs(path, text):
    """Characters the font draws as its .notdef box (tofu). Compares each glyph's bitmap with an unassigned code point's."""
    f = load_font(path, 48)

    def bitmap(ch):
        im = Image.new("L", (96, 96))
        ImageDraw.Draw(im).text((8, 8), ch, font=f, fill=255)
        return im.tobytes()
    tofu = bitmap("\U0010FFFD")
    return [ch for ch in dict.fromkeys(text) if not ch.isspace() and bitmap(ch) == tofu]


# ---------------------------------------------------------------- layout + render
def layout(line, fpath, K=1.0):
    """[(char, x, y, rotate)] glyph origins (top-left, output px at scale K) and the line's bounding box (x0, y0, x1, y1)."""
    px = line["size"] * K
    f = load_font(fpath, px)
    chars = list(line["text"])
    pos = []
    if line["layout"] == "vertical":
        step = px * (1 + line["tracking"])
        x, y = line["x"] * K - px / 2, line["y"] * K
        col_h = 0.0
        for ch in chars:
            if ch in (" ", "\u3000"):
                y += step * 0.6
                continue
            g = VERTICAL_FORMS.get(ch, ch)
            dx = px * 0.12 if ch in SMALL else 0.0
            dy = -px * 0.12 if ch in SMALL else 0.0
            pos.append((g, x + dx, y + dy, ch in ROTATE))
            y += step
            col_h = y - line["y"] * K
        box = (x, line["y"] * K, x + px, line["y"] * K + col_h)
    else:
        adv = [(f.getlength(ch) if ch not in (" ", "\u3000") else px * 0.5) for ch in chars]
        track = px * line["tracking"]
        width = sum(adv) + track * max(len(chars) - 1, 0)
        x = line["x"] * K - width / 2
        asc, desc = f.getmetrics()
        y = line["y"] * K - (asc + desc) / 2
        top, bot = [], []
        for ch, a in zip(chars, adv):
            if ch not in (" ", "\u3000"):
                pos.append((ch, x, y, False))
                bb = f.getbbox(ch)
                top.append(y + bb[1])
                bot.append(y + bb[3])
            x += a + track
        box = (line["x"] * K - width / 2, min(top, default=y), line["x"] * K + width / 2, max(bot, default=y + asc + desc))     # the ink, not the line box
    return pos, box


def char_alpha(line, k, n, t):
    """Opacity and rise (0..1) of character k of n at output time t."""
    a, b = line["a"], line["b"]
    if t < a or t >= b:
        return 0.0, 0.0
    fo = min(1.0, (b - t) / line["fade_s"]) if line["anim"] != "none" and line["fade_s"] > 0 else 1.0
    if line["anim"] in ("type", "ink"):
        span = max(min((b - a) * 0.6, 0.09 * n), 0.04 * n)
        t_k = a + span * k / max(n, 1)
        if t < t_k:
            return 0.0, 0.0
        p = min(1.0, (t - t_k) / 0.12)
        return p * fo, (1 - p)
    if line["anim"] == "none":
        return 1.0, 0.0
    fi = min(1.0, (t - a) / line["fade_s"]) if line["fade_s"] > 0 else 1.0
    return min(fi, fo), 0.0


class LyricLayer:
    """Draws every lyric line live on output frame f (global). Glyph sprites are cached per (char, size, colour, rotate)."""

    def __init__(self, ctx, spec):
        self.ctx, self.spec = ctx, spec
        self.lines = lines(spec)
        self.fpath = font_path(spec) if self.lines else None
        self._lay = {}
        self._spr = {}

    def _sprite(self, ch, line, rot, blur=0):
        K = self.ctx.K
        key = (ch, line["size"], tuple(line["color"]), rot, line["shadow"], blur)
        if key not in self._spr:
            px = line["size"] * K
            f = load_font(self.fpath, px)
            pad = int(px * 0.5)
            im = Image.new("RGBA", (int(px * 1.6) + 2 * pad, int(px * 1.6) + 2 * pad), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((pad, pad), ch, font=f, fill=tuple(line["color"]) + (255,))
            if rot:
                im = im.rotate(-90, resample=Image.BICUBIC, center=(pad + px / 2, pad + px / 2))
            if blur:
                im = im.filter(ImageFilter.GaussianBlur(blur))
            if line["shadow"]:
                m = im.split()[3].filter(ImageFilter.GaussianBlur(max(px * 0.08, 1)))
                sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
                sh.putalpha(m.point(lambda v: int(v * float(line["shadow"]))))
                sh.alpha_composite(im)
                im = sh
            self._spr[key] = (im, pad)
        return self._spr[key]

    def apply(self, out, f):
        if not self.lines:
            return out
        t = f / self.ctx.fps
        for line in self.lines:
            if not (line["a"] <= t < line["b"]):
                continue
            if line["i"] not in self._lay:
                self._lay[line["i"]] = layout(line, self.fpath, self.ctx.K)
            pos, box = self._lay[line["i"]]
            out = out.convert("RGBA") if out.mode != "RGBA" else out
            if line["layout"] == "band" and line.get("auto_contrast", True):
                line = self._contrast(out, line, box)
            for k, (ch, x, y, rot) in enumerate(pos):
                al, rise = char_alpha(line, k, len(pos), t)
                if al <= 0:
                    continue
                blur = int(round(rise * 3)) if line["anim"] == "ink" else 0
                spr, pad = self._sprite(ch, line, rot, blur)
                if al < 1:
                    spr = spr.copy()
                    spr.putalpha(spr.split()[3].point(lambda v, a_=al: int(v * a_)))
                dy = rise * 4 * self.ctx.K if line["anim"] == "ink" else 0
                out.alpha_composite(spr, (int(round(x - pad)), int(round(y - pad + dy))))
        return out

    def _contrast(self, out, line, box):
        """A band line over a dark picture (full-bleed shots) flips to the page colour so it stays readable."""
        x0, y0, x1, y1 = (int(max(0, v)) for v in box)
        reg = out.crop((x0, y0, max(x0 + 1, x1), max(y0 + 1, y1))).convert("L")
        if float(np.asarray(reg, np.float32).mean()) / 255.0 >= 0.45:
            return line
        return dict(line, color=[255, 253, 249], shadow=max(float(line["shadow"] or 0), 0.35))

    def overlaps(self, t0, t1):
        return [l for l in self.lines if l["a"] < t1 and l["b"] > t0]


def digest_part(spec, shot):
    """What a shot's picture needs from the lyrics: the lines live during it + style + font (so an edit re-renders only them)."""
    b = block(spec)
    if not b:
        return None
    t0, t1 = shot.f0 / spec.fps, (shot.f0 + shot.n) / spec.fps
    live = [l for l in lines(spec) if l["a"] < t1 and l["b"] > t0]
    try:
        fp = font_path(spec)
    except LyricsError:
        fp = None
    return dict(lines=live, style=style_of(spec), font=fp)


# ---------------------------------------------------------------- gates
def gates(spec):
    b = block(spec)
    if not b.get("lines"):
        return [("lyrics", "WARN", "no lyrics: a music video normally carries the sung words (`promo lyrics import`)")]
    out = []
    ls = lines(spec)
    try:
        fp = font_path(spec)
        miss = missing_glyphs(fp, "".join(l["text"] for l in ls))
        out.append(("lyrics-glyphs", "FAIL" if miss else "PASS",
                    f"{os.path.basename(fp)} cannot draw {''.join(miss)!r} (tofu); pick a font that covers them" if miss
                    else f"every character drawable in {os.path.basename(fp)}"))
    except LyricsError as e:
        out.append(("lyrics-glyphs", "FAIL", str(e)))
        fp = None
    if fp:
        W, H = 1920, 1080
        bad = []
        for l in ls:
            m = SAFE_BAND if l["layout"] == "band" else SAFE
            x0, y0, x1, y1 = W * m[0], H * m[1], W * (1 - m[0]), H * (1 - m[1])
            _, bx = layout(l, fp, 1.0)
            if bx[0] < x0 - 0.5 or bx[1] < y0 - 0.5 or bx[2] > x1 + 0.5 or bx[3] > y1 + 0.5:
                bad.append(f"line {l['i'] + 1} {l['text'][:12]!r} box {tuple(int(v) for v in bx)}")
        out.append(("lyrics-safe", "FAIL" if bad else "PASS", "; ".join(bad) or "every lyric line inside title-safe"))
    short = [f"line {l['i'] + 1} {l['b'] - l['a']:.2f}s" for l in ls if l["b"] - l["a"] < MIN_HOLD_S - 1e-6]
    out.append(("lyrics-hold", "FAIL" if short else "PASS", "; ".join(short) or f"every line on screen >= {MIN_HOLD_S}s"))
    band = sorted((l for l in ls if l["layout"] == "band"), key=lambda l: l["a"])
    ov = [f"lines {p['i'] + 1}/{q['i'] + 1}" for p, q in zip(band, band[1:]) if q["a"] < p["b"] - 1e-3]
    out.append(("lyrics-overlap", "WARN" if ov else "PASS", ("two band lines at once: " + ", ".join(ov)) if ov else "band lines never overlap"))
    raw = b.get("lines") or []
    uns = [str(i + 1) for i, l in enumerate(raw) if l.get("unsynced")]
    off = []
    for l in ls:
        if l["sung"] and abs(l["a"] - float(l["sung"][0])) > SYNC_TOL_S:
            off.append(f"line {l['i'] + 1} starts {l['a'] - float(l['sung'][0]):+.2f}s from the vocal")
    msg = "; ".join(([f"unsynced lines {', '.join(uns)}"] if uns else []) + off)
    out.append(("lyrics-sync", "WARN" if msg else "PASS", msg or f"every line within {SYNC_TOL_S}s of the sung vocal"))
    return out


# ---------------------------------------------------------------- CLI
def _write(spec, new_lines, style=None):
    """Replace lyrics.lines in promo.yaml, keeping every other key and comment (editor.write_text)."""
    import copy

    import yaml

    from . import editor
    text = open(spec.path, encoding="utf-8").read()
    old = yaml.safe_load(text) or {}
    new = copy.deepcopy(old)
    blk = dict(new.get("lyrics") or {})
    blk["lines"] = new_lines
    if style and not blk.get("style"):
        blk["style"] = style
    new["lyrics"] = blk
    open(spec.path, "w", encoding="utf-8").write(editor.write_text(text, old, new))


def main(argv):
    import argparse
    from .spec import load_spec
    ap = argparse.ArgumentParser(prog="promo lyrics", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("import", "align", "show"):
        p = sub.add_parser(n)
        p.add_argument("-p", "--project", default="promo.yaml")
        if n == "import":
            p.add_argument("file", help=".srt / .lrc / .txt (one line per lyric line)")
            p.add_argument("--edit-time", action="store_true", help="the file's times are already output times (default: music-file times, mapped through music.edit)")
        if n == "align":
            p.add_argument("--audio", help="audio to transcribe (default: the music asset, mapped through music.edit)")
            p.add_argument("--words", help="reuse an ASR word list JSON [{w, start, end}] (music-file time) instead of running whisper")
            p.add_argument("--snap", action="store_true", help="also move each line's `t` to what was sung")
            p.add_argument("--separate", action="store_true", help="transcribe the separated voice (HTDemucs) instead of the full mix: far tighter word starts on singing")
        if n == "show":
            p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    spec = load_spec(a.project, plugins=False)
    if a.cmd == "import":
        ls = import_lines(spec, open(a.file, encoding="utf-8").read(), track_time=not a.edit_time)
        _write(spec, ls, style={"layout": "band"})
        print(f"{len(ls)} lines into {spec.path} (lyrics.lines); next: `promo lyrics align -p {a.project}`")
        return 0
    if a.cmd == "align":
        from .assets import asset_path
        if a.words:
            words = json.load(open(a.words))
        else:
            src = a.audio or asset_path(spec, spec.raw["music"]["asset"])
            m = spec.raw.get("music") or {}
            segs = (m.get("edit") or {}).get("segments") or []
            t0 = min((m["track_offset"] + s[1] * m["track_beat"] for s in segs), default=0.0)
            t1 = max((m["track_offset"] + s[2] * m["track_beat"] for s in segs), default=None)
            a0, a1 = max(0.0, t0 - 1), (t1 + 1) if t1 else None
            if a.separate:
                import soundfile as sf
                stem = separate_vocals(src, a0, a1, os.path.join(spec.build, "lyrics-vocals.wav"))
                words = [dict(w, start=round(w["start"] + a0, 3), end=round(w["end"] + a0, 3)) for w in transcribe(stem)]
                words = refine_starts(words, sf.read(stem, dtype="float32"), a0)
            else:
                words = transcribe(src, a0, a1)
            os.makedirs(spec.build, exist_ok=True)
            json.dump(words, open(os.path.join(spec.build, "lyrics-asr.json"), "w"), ensure_ascii=False, indent=0)
        mapped = []
        for w in words:
            s, e = track_to_edit(spec, w["start"]), track_to_edit(spec, w["end"])
            if s is not None and e is not None:
                mapped.append(dict(w=w["w"], start=s, end=e))
        raw = [dict(l) for l in (block(spec).get("lines") or [])]
        frac, raw = align_lines(raw, mapped)
        if a.snap:
            for l in raw:
                if l.get("sung"):
                    l["t"] = [l["sung"][0], max(l["sung"][1], l["sung"][0] + MIN_HOLD_S)]
        _write(spec, raw)
        print(f"aligned {frac:.0%} of the lyric characters to the sung vocal; "
              f"{sum(1 for l in raw if l.get('unsynced'))} unsynced; `promo check` lyrics-sync shows lines off by > {SYNC_TOL_S}s")
        return 0
    rows = lines(spec)
    if a.json:
        print(json.dumps(dict(ok=True, lines=rows), ensure_ascii=False))
    else:
        for l in rows:
            print(f"{l['a']:7.2f}-{l['b']:6.2f}  {l['layout']:8} {l['anim']:5} {l['text']}" + ("  (unsynced)" if l["unsynced"] else ""))
    return 0
