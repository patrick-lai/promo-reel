"""Dynamic widgets: panels the agent builds for the Stage when the fixed tabs cannot show what a job needs (a Blender render queue, a 3D turntable, a
spreadsheet of takes, a colour-grade comparison). The agent decides what goes inside the box and how the boxes are laid out.

    flow/widgets/<id>/content.json   kind `blocks`: {"blocks": [...]} from a fixed, safe set of block types the Stage draws itself
    flow/widgets/<id>/index.html     kind `html`: free-form HTML/CSS/JS the Stage runs in a sandboxed frame (no network, no access to the Stage)
    flow/widgets/<id>/files/NAME     attachments: images, audio and video are served like every other media file, text files (json, csv, obj ...) arrive inline
    flow.json  widgets: [{id, title, kind, place, span, height, order, summary, files, created, updated}]

Layout is data too: `place` is `workbench` (its own tab) or the tab the widget sits at the top of, `span` is 1-12 columns of a 12 column grid (narrow panes
stack everything), `height` is s|m|l|xl|auto, `order` sorts the grid. A widget is not a gate: nothing blocks on it, and it never shows footage as the product.
"""
from __future__ import annotations

import json
import os
import re
import shutil

from . import plandocs as PD

KINDS = ("blocks", "html")
PLACES = ("workbench", "scripts", "storyboard", "assets", "plan", "draft")
HEIGHTS = ("s", "m", "l", "xl", "auto")
MAX_HTML_BYTES = 400 * 1024
MAX_DATA_BYTES = 256 * 1024          # per attached text file
MAX_FILES = 40
MAX_BLOCKS = 60
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}
DATA_EXT = {".json", ".csv", ".tsv", ".txt", ".md", ".obj", ".mtl", ".svg", ".gltf", ".ply", ".stl"}
TONES = ("info", "ok", "warn", "bad")
# a resource the sandbox cannot load: say so at once instead of leaving the person a blank box
EXTERNAL_RE = re.compile(r"<(?:script|link|img|iframe|video|audio|source|embed|object)\b[^>]*?\b(?:src|href|data)\s*=\s*[\"']?\s*(?:https?:)?//", re.I | re.S)


class WidgetError(PD.DocError):
    pass


def kind_of_file(path):
    """`media` for what the host can serve (image, audio, video), `data` for text that arrives inline."""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT | VIDEO_EXT | AUDIO_EXT:
        return "media"
    if ext in DATA_EXT:
        return "data"
    raise WidgetError(f"{os.path.basename(path)}: the Stage can show images, audio, video and text files ({', '.join(sorted(DATA_EXT))}). For a 3D scene render a still or a turntable video, or export it as .obj / .gltf (JSON) text")


def media_type(name):
    ext = os.path.splitext(name)[1].lower()
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT else "data" if ext in DATA_EXT else None


def parse_attach(spec):
    """`NAME=PATH` or just `PATH` (the file's own name, lower-cased)."""
    name, sep, path = spec.partition("=")
    if not sep:
        name, path = os.path.basename(spec).lower(), spec
    if not NAME_RE.match(name):
        raise WidgetError(f"attachment name {name!r}: lower-case letters, digits, . - _ (up to 64), starting with a letter or digit")
    if not os.path.isfile(path):
        raise WidgetError(f"no such file to attach: {path}")
    kind_of_file(path)
    return name, path


def widget_dir(fd, wid):
    return os.path.join(fd, "widgets", wid)


def attach(fd, wid, specs):
    """Copy the attachments in; the {name: relative path} of what was added."""
    added = {}
    for spec in specs or []:
        name, path = parse_attach(spec)
        if kind_of_file(path) == "data" and os.path.getsize(path) > MAX_DATA_BYTES:
            raise WidgetError(f"{name} is over {MAX_DATA_BYTES // 1024} KB: text files arrive inside the Stage's state, so trim it or summarise it")
        dest = os.path.join(widget_dir(fd, wid), "files", name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(path, dest)
        added[name] = os.path.relpath(dest, fd)
    return added


def _text(v, what, n=4000, empty=False):
    if not isinstance(v, str) or (not empty and not v.strip()):
        raise WidgetError(f"{what} must be text" + ("" if empty else ", not empty"))
    if len(v) > n:
        raise WidgetError(f"{what} is {len(v)} characters; the limit is {n}")
    return v


def _num(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise WidgetError(f"{what} must be a number")
    return v


def _items(b, key, what, n, one):
    items = b.get(key)
    if not isinstance(items, list) or not items:
        raise WidgetError(f"{what}: `{key}` is a non-empty list")
    if len(items) > n:
        raise WidgetError(f"{what}: at most {n} entries in `{key}`, got {len(items)}")
    return [one(x, f"{what} {key}[{i}]") for i, x in enumerate(items)]


def _obj(x, what, keys):
    if not isinstance(x, dict):
        raise WidgetError(f"{what} must be an object with {', '.join(keys)}")
    return x


def _cell(v, what):
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        raise WidgetError(f"{what} must be text or a number")
    return _text(str(v), what, 300, empty=True)


def _file(b, key, want, files, what):
    name = b.get(key)
    if name not in files:
        raise WidgetError(f"{what}: `{key}` {name!r} is not an attached file (attached: {', '.join(sorted(files)) or 'none'}): add it with --attach NAME=PATH")
    if media_type(name) not in want:
        raise WidgetError(f"{what}: {name} is a {media_type(name)} file, this block needs {' or '.join(want)}")
    return name


def check_block(b, i, files):
    where = f"block {i + 1}"
    if not isinstance(b, dict):
        raise WidgetError(f"{where} must be an object like {{\"type\": \"text\", \"text\": \"...\"}}")
    t = b.get("type")
    where = f"block {i + 1} ({t})"
    out = {"type": t}
    if b.get("title") is not None:
        out["title"] = _text(b["title"], f"{where} title", 80)
    if t == "text":
        out["text"] = _text(b.get("text"), f"{where} text", 12000)
    elif t == "callout":
        out["text"] = _text(b.get("text"), f"{where} text", 600)
        out["tone"] = b.get("tone", "info")
        if out["tone"] not in TONES:
            raise WidgetError(f"{where}: tone is one of {', '.join(TONES)}")
    elif t == "stats":
        out["items"] = _items(b, "items", where, 8, lambda x, w: {
            "label": _text(_obj(x, w, ("label", "value")).get("label"), w + " label", 60), "value": _cell(x.get("value"), w + " value"),
            "hint": _text(x["hint"], w + " hint", 80) if x.get("hint") else None})
    elif t == "kv":
        out["items"] = _items(b, "items", where, 40, lambda x, w: {"key": _text(_obj(x, w, ("key", "value")).get("key"), w + " key", 80), "value": _cell(x.get("value"), w + " value")})
    elif t in ("list", "checklist"):
        if t == "list":
            out["ordered"] = bool(b.get("ordered"))
            out["items"] = _items(b, "items", where, 100, lambda x, w: _text(x, w, 400))
        else:
            out["items"] = _items(b, "items", where, 100, lambda x, w: {"text": _text(_obj(x, w, ("text", "done")).get("text"), w + " text", 400), "done": bool(x.get("done"))})
    elif t == "table":
        cols = _items(b, "columns", where, 12, lambda x, w: _text(x, w, 60))
        out["columns"] = cols
        rows = b.get("rows")
        if not isinstance(rows, list) or len(rows) > 200:
            raise WidgetError(f"{where}: `rows` is a list of up to 200 rows")
        out["rows"] = []
        for r, row in enumerate(rows):
            if not isinstance(row, list) or len(row) > len(cols):
                raise WidgetError(f"{where}: row {r + 1} is a list of at most {len(cols)} cells (one per column)")
            out["rows"].append([_cell(c, f"{where} row {r + 1}") for c in row])
    elif t == "bars":
        out["unit"] = _text(b["unit"], f"{where} unit", 12) if b.get("unit") else ""
        out["items"] = _items(b, "items", where, 30, lambda x, w: {"label": _text(_obj(x, w, ("label", "value")).get("label"), w + " label", 60), "value": _num(x.get("value"), w + " value")})
    elif t == "progress":
        out["label"] = _text(b.get("label"), f"{where} label", 80)
        v = _num(b.get("value"), f"{where} value")
        if not 0 <= v <= 1:
            raise WidgetError(f"{where}: value is a fraction from 0 to 1")
        out["value"] = v
    elif t == "code":
        out["text"] = _text(b.get("text"), f"{where} text", 12000)
    elif t in ("image", "video", "audio"):
        out["file"] = _file(b, "file", (t,), files, where)
        if b.get("caption"):
            out["caption"] = _text(b["caption"], f"{where} caption", 200)
    elif t == "gallery":
        out["files"] = _items(b, "files", where, 24, lambda x, w: _file({"f": x}, "f", ("image", "video"), files, w))
    else:
        raise WidgetError(f"{where}: unknown block type; one of {', '.join(BLOCK_TYPES)}")
    return out


BLOCK_TYPES = ("text", "callout", "stats", "kv", "list", "checklist", "table", "bars", "progress", "code", "image", "video", "audio", "gallery")


def parse_blocks(raw, files):
    """The cleaned `blocks` of a widget from its JSON (`{"blocks": [...]}` or the bare list). Anything the Stage cannot draw is refused here, in words the agent can act on."""
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise WidgetError(f"the blocks are not valid JSON ({e})") from None
    blocks = data.get("blocks") if isinstance(data, dict) else data
    if not isinstance(blocks, list) or not blocks:
        raise WidgetError("blocks: a non-empty list like [{\"type\": \"stats\", \"items\": [{\"label\": \"Frames\", \"value\": \"240\"}]}]")
    if len(blocks) > MAX_BLOCKS:
        raise WidgetError(f"at most {MAX_BLOCKS} blocks in one widget, got {len(blocks)}: make a second widget")
    return [check_block(b, i, files) for i, b in enumerate(blocks)]


def check_html(text):
    if not isinstance(text, str) or not text.strip():
        raise WidgetError("the widget HTML is empty")
    if len(text.encode()) > MAX_HTML_BYTES:
        raise WidgetError(f"the widget HTML is over {MAX_HTML_BYTES // 1024} KB: inline less (attach images and video instead), or split it in two widgets")
    m = EXTERNAL_RE.search(text)
    if m:
        raise WidgetError("the widget runs without network: it cannot load " + m.group(0)[:80].strip() + "... Inline the script and styles, and attach images with --attach")
    return text


def check_layout(place=None, span=None, height=None, order=None):
    if place is not None and place not in PLACES:
        raise WidgetError(f"--place is one of {', '.join(PLACES)}")
    if span is not None and not (isinstance(span, int) and 1 <= span <= 12):
        raise WidgetError("--span is 1 to 12 (of a 12 column grid; 12 is the full width, 6 half, 4 a third)")
    if height is not None and height not in HEIGHTS:
        raise WidgetError(f"--height is one of {', '.join(HEIGHTS)}")
    if order is not None and not isinstance(order, int):
        raise WidgetError("--order is a whole number")


def write_content(fd, wid, kind, text, files):
    """Validate and store the content; the stored text. Raises before anything is written."""
    if kind == "blocks":
        blocks = parse_blocks(text, files)
        body, name = json.dumps({"blocks": blocks}, indent=1), "content.json"
    else:
        body, name = check_html(text), "index.html"
    d = widget_dir(fd, wid)
    os.makedirs(d, exist_ok=True)
    for other in ("content.json", "index.html"):
        if other != name and os.path.isfile(os.path.join(d, other)):
            os.remove(os.path.join(d, other))
    with open(os.path.join(d, name), "w") as f:
        f.write(body if body.endswith("\n") else body + "\n")
    return body


def remove(fd, wid):
    shutil.rmtree(widget_dir(fd, wid), ignore_errors=True)


def _resolve_files(blocks, media):
    """Block file names become `{"$file": ...}` so the host serves them."""
    for b in blocks:
        if "file" in b:
            b["file"] = media(b["file"])
        if "files" in b:
            b["files"] = [media(x) for x in b["files"]]
    return blocks


def view(fd, rec, media):
    """One widget for the Stage. `media` turns an absolute path into the host's file object (flow._media)."""
    d = widget_dir(fd, rec["id"])
    paths = {n: os.path.join(fd, rel) for n, rel in (rec.get("files") or {}).items()}
    present = {n: p for n, p in paths.items() if os.path.isfile(p)}
    out = dict(id=rec["id"], title=rec["title"], kind=rec["kind"], place=rec["place"], span=rec["span"], height=rec["height"], order=rec["order"],
               summary=rec.get("summary") or "", updated=rec.get("updated"), blocks=None, html=None, files={}, data={}, note=None)
    for n, p in present.items():
        if media_type(n) == "data":
            with open(p, errors="replace") as f:
                out["data"][n] = f.read()
        else:
            out["files"][n] = media(p)
    try:
        if rec["kind"] == "blocks":
            with open(os.path.join(d, "content.json")) as f:
                out["blocks"] = _resolve_files(json.load(f)["blocks"], lambda n: out["files"].get(n))
        else:
            with open(os.path.join(d, "index.html")) as f:
                out["html"] = f.read()
    except (OSError, ValueError, KeyError):
        out["note"] = "The widget's content is missing. Ask the agent to add it again."
    return out


def sort_key(w):
    return (w["place"], w["order"], w["updated"] or "")


def starter(kind):
    """What `promo flow widget example blocks|html` prints. An image, video or audio block names an attachment (`--attach NAME=PATH`): {"type": "image", "file": "frame.png", "caption": "..."}."""
    if kind == "blocks":
        return json.dumps({"blocks": [
            {"type": "stats", "items": [{"label": "Frames", "value": "240", "hint": "24 fps, 10 s"}, {"label": "Samples", "value": "128"}, {"label": "Render time", "value": "6 min"}]},
            {"type": "progress", "label": "Render queue", "value": 0.4},
            {"type": "table", "columns": ["Shot", "Engine", "Status"], "rows": [["01 Orbit", "Cycles", "done"], ["02 Dolly", "Cycles", "rendering"], ["03 Macro", "Eevee", "queued"]]},
            {"type": "callout", "tone": "warn", "text": "Shot 03 still needs the final HDRI."}]}, indent=1)
    return """<div id="stage"><canvas id="c" width="480" height="260"></canvas><label>Spin <input id="speed" type="range" min="0" max="4" step="0.1" value="1"></label>
<button id="ask">Tell the agent</button></div>
<style>#stage{padding:12px;display:grid;gap:8px;justify-items:center}canvas{max-width:100%;background:var(--pf-well);border-radius:8px}</style>
<script>
// promo.data holds the attached text files, promo.file(NAME) a Promise of an attached image or video as a Blob, promo.theme the Stage colours.
// promo.tell(text) offers the person a button that sends the text to the agent; nothing is sent until they click it.
promo.ready(() => {
  const c = document.getElementById("c").getContext("2d"), speed = document.getElementById("speed");
  let a = 0;
  (function frame() {
    a += +speed.value * 0.02;
    c.clearRect(0, 0, 480, 260);
    c.fillStyle = promo.theme.accent;
    c.fillRect(240 + Math.cos(a) * 80 - 20, 130 + Math.sin(a) * 40 - 20, 40, 40);
    requestAnimationFrame(frame);
  })();
  document.getElementById("ask").onclick = () => promo.tell("Render this at spin " + speed.value);
});
</script>
"""
