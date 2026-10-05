"""Storyboards: one board per story, every scene with a START and an END frame, drawn as a neat self-contained HTML page.

    flow/boards/<story>/board.json         (schema below)
    flow/boards/<story>/frames/*.png|jpg   keyframes (generated or captured by the agent; promo-reel only specifies + ingests)

    {"story": "A", "title": "...", "logline": "...", "aspect": "16:9", "duration_s": 60,
     "scenes": [{"id": "01", "beat": "Hook", "t": [0, 4], "action": "what happens, one or two sentences",
                 "caption": "", "vo": "", "sound": "", "camera": "slow push-in", "proof": "evidence for any claim",
                 "source": "real|generated",          # real = screen recording of the product, generated = plate / people scene
                 "start": {"image": "frames/01-start.png", "prompt": "how this frame is made"},
                 "end":   {"image": "frames/01-end.png",   "prompt": "..."},
                 "frames": [{"t": 2.0, "image": "frames/01-mid.png", "prompt": "..."}]}]}   # extra keyframes (stage `keyframes`)

`problems()` lists structural faults, `missing(board, dir, which)` lists frame files not yet made (the agent's to-do, with prompts),
`render_html()` writes the page the session shows to the user (inline images, light/dark, phone-width safe).
"""
from __future__ import annotations

import base64
import html
import io
import json
import os

REQUIRED = ("id", "beat", "t", "action", "start", "end")
SLATE_SHARE = (0.9, 0.995)      # one colour covers 90..99.5 % of the frame: a slate with text on it (a fully flat image is a test pattern, not a slate)


def board_path(board_dir):
    return os.path.join(board_dir, "board.json")


def load(board_dir):
    with open(board_path(board_dir)) as f:
        return json.load(f)


def problems(b):
    out = []
    if not b.get("title"):
        out.append("board has no title")
    if not b.get("logline"):
        out.append("board has no logline")
    sc = b.get("scenes") or []
    if not sc:
        return out + ["board has no scenes"]
    seen = set()
    prev_end = None
    for s in sc:
        sid = s.get("id", "?")
        for k in REQUIRED:
            if not s.get(k):
                out.append(f"scene {sid}: missing `{k}`")
        if sid in seen:
            out.append(f"scene {sid}: duplicate id")
        seen.add(sid)
        t = s.get("t") or []
        if len(t) != 2 or not t[1] > t[0]:
            out.append(f"scene {sid}: `t` must be [start, end] with end > start")
        elif prev_end is not None and t[0] < prev_end - 1e-6:
            out.append(f"scene {sid}: starts at {t[0]} before the previous scene ends ({prev_end})")
        if len(t) == 2:
            prev_end = t[1]
        for w in ("start", "end"):
            f = s.get(w) or {}
            if not isinstance(f, dict) or not f.get("image"):
                out.append(f"scene {sid}: `{w}` needs an `image` path (and a `prompt` saying how it is made)")
            elif not f.get("prompt"):
                out.append(f"scene {sid}: `{w}` frame has no `prompt` (how it will be made / captured)")
        if s.get("source") not in (None, "real", "generated"):
            out.append(f"scene {sid}: source must be real|generated")
        if s.get("caption") and not s.get("proof") and s.get("source", "real") == "real":
            out.append(f"scene {sid}: caption without `proof` (what in the footage shows it)")
    return out


def is_slate(path):
    """A text slate: a flat-colour image with a little text on it, the stand-in an agent writes instead of a real frame. A file made by
    `promo flow frames` has a `.gen.json` sidecar and is never one; a captured screenshot is not flat enough."""
    if os.path.isfile(path + ".gen.json"):
        return False
    from collections import Counter
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((160, 90))
        px = list(im.getdata())
    share = Counter(px).most_common(1)[0][1] / len(px)
    return SLATE_SHARE[0] <= share < SLATE_SHARE[1]


def _frames(s, which):
    for w in which:
        if w in ("start", "end") and isinstance(s.get(w), dict):
            yield w, s[w]
        elif w == "frames":
            for i, f in enumerate(s.get("frames") or []):
                yield f"frames[{i}]", f


def missing(b, board_dir, which=("start", "end")):
    """[{scene, which, image, prompt, slate}] for frames that are specified but are not real images yet: the file does not exist, or it is a text slate."""
    out = []
    for s in b.get("scenes") or []:
        for w, f in _frames(s, which):
            img = f.get("image")
            if not img:
                continue
            p = os.path.join(board_dir, img)
            slate = os.path.isfile(p) and is_slate(p)
            if slate or not os.path.isfile(p):
                out.append(dict(scene=s.get("id"), which=w, image=p, prompt=f.get("prompt", ""), slate=slate))
    return out


def _data_uri(path, w=720):
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        if im.width > w:
            im = im.resize((w, round(im.height * w / im.width)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return ""


CSS = """
:root{--bg:#f6f4ef;--card:#fff;--ink:#1d1b18;--mute:#6f6a60;--line:#e2ded4;--acc:#b4531f;--ok:#2c7a4b;--warn:#a6761a;--ph:#ece8dd}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15130f;--card:#1e1b16;--ink:#efeae0;--mute:#9a9486;--line:#332f27;--acc:#e08a52;--ok:#5fb884;--warn:#d9a441;--ph:#2a261f}}
:root[data-theme=dark]{--bg:#15130f;--card:#1e1b16;--ink:#efeae0;--mute:#9a9486;--line:#332f27;--acc:#e08a52;--ok:#5fb884;--warn:#d9a441;--ph:#2a261f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:24px 16px 56px}
h1{font:600 26px/1.2 Georgia,serif;margin:0 0 4px}h2{font:600 18px Georgia,serif;margin:28px 0 6px}
.log{color:var(--mute);margin:0 0 16px}.meta{font-size:13px;color:var(--mute)}
.bar{display:flex;gap:2px;height:26px;margin:14px 0 6px;border-radius:6px;overflow:hidden}
.bar div{background:var(--acc);opacity:.85;font-size:11px;color:#fff;display:flex;align-items:center;justify-content:center;white-space:nowrap;overflow:hidden}
.bar div:nth-child(even){opacity:.6}
.scene{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:14px 0}
.hd{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.n{font:600 13px ui-monospace,Menlo,monospace;background:var(--acc);color:#fff;border-radius:5px;padding:1px 7px}
.beat{font-weight:600}.tt{font-size:13px;color:var(--mute);margin-left:auto}
.frames{display:grid;grid-template-columns:1fr 28px 1fr;gap:6px;align-items:center;margin:10px 0}
.fr{position:relative;border-radius:8px;overflow:hidden;background:var(--ph);aspect-ratio:16/9;border:1px solid var(--line)}
.fr img{width:100%;height:100%;object-fit:cover;display:block}.fr .ph{height:100%;display:flex;align-items:center;justify-content:center;color:var(--mute);font-size:12px;text-align:center;padding:8px}
.lbl{position:absolute;left:6px;top:6px;font-size:11px;font-weight:600;background:rgba(0,0,0,.6);color:#fff;border-radius:4px;padding:1px 6px}
.arrow{text-align:center;color:var(--mute);font-size:20px}
.mid{display:flex;gap:6px;margin:0 0 8px;overflow-x:auto}.mid .fr{flex:0 0 140px}
dl{display:grid;grid-template-columns:84px 1fr;gap:3px 10px;margin:8px 0 0;font-size:14px}dt{color:var(--mute)}dd{margin:0}
.tag{font-size:11px;border:1px solid var(--line);border-radius:10px;padding:0 7px;color:var(--mute)}.tag.gen{color:var(--warn);border-color:var(--warn)}.tag.real{color:var(--ok);border-color:var(--ok)}
@media (max-width:560px){.frames{grid-template-columns:1fr}.arrow{transform:rotate(90deg)}dl{grid-template-columns:1fr}}
"""


def _fr(label, f, bdir):
    img = (f or {}).get("image")
    p = os.path.join(bdir, img) if img else ""
    uri = _data_uri(p) if p and os.path.isfile(p) and not is_slate(p) else ""
    inner = f'<img src="{uri}" alt="{html.escape(label)}">' if uri else f'<div class="ph">not made yet<br>{html.escape((f or {}).get("prompt", "")[:90])}</div>'
    return f'<div class="fr"><span class="lbl">{html.escape(label)}</span>{inner}</div>'


def board_section(b, bdir):
    esc = html.escape
    total = max((s["t"][1] for s in b.get("scenes", []) if len(s.get("t", [])) == 2), default=1)
    bar = "".join(f'<div style="flex:{max(s["t"][1] - s["t"][0], .1):g}" title="{esc(s.get("beat", ""))}">{esc(s["id"])}</div>' for s in b.get("scenes", []) if len(s.get("t", [])) == 2)
    cards = []
    for s in b.get("scenes", []):
        t = s.get("t") or [0, 0]
        src = s.get("source", "real")
        rows = [("Happens", s.get("action")), ("Caption", s.get("caption")), ("Voice", s.get("vo")), ("Sound", s.get("sound")),
                ("Camera", s.get("camera")), ("Proof", s.get("proof"))]
        dl = "".join(f"<dt>{k}</dt><dd>{esc(str(v))}</dd>" for k, v in rows if v)
        mids = "".join(_fr(f't={f.get("t", "?")}s', f, bdir) for f in s.get("frames") or [])
        cards.append(
            f'<div class="scene"><div class="hd"><span class="n">{esc(str(s.get("id")))}</span><span class="beat">{esc(s.get("beat", ""))}</span>'
            f'<span class="tag {src}">{"real footage" if src == "real" else "generated"}</span><span class="tt">{t[0]:g}s to {t[1]:g}s</span></div>'
            f'<div class="frames">{_fr("START", s.get("start"), bdir)}<div class="arrow">&rarr;</div>{_fr("END", s.get("end"), bdir)}</div>'
            + (f'<div class="mid">{mids}</div>' if mids else "") + f"<dl>{dl}</dl></div>")
    return (f'<h2>{esc(b.get("title", b.get("story", "")))}</h2><p class="log">{esc(b.get("logline", ""))}</p>'
            f'<div class="meta">{len(b.get("scenes", []))} scenes · {total:g}s · {esc(b.get("aspect", "16:9"))}</div><div class="bar">{bar}</div>' + "".join(cards))


def render_html(boards, title="Storyboard", subtitle="", out=None):
    """boards = [(board_dict, board_dir)] -> one HTML string (and file if out)."""
    body = "".join(board_section(b, d) for b, d in boards)
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class=\"wrap\"><h1>{html.escape(title)}</h1>"
           f'<p class="log">{html.escape(subtitle)}</p>{body}</div></body></html>')
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w") as f:
            f.write(doc)
    return doc
