"""The asset plan: EVERYTHING the cut will use, shown to the person before any keyframe or draft is made.

    flow/assets.json   [{id, kind, scenes: ["01", ...], source, how, path?, licence?, note?}]

    kind     screenshot | image | recording | video | music | voice | sfx
    source   real       a real capture of the product (screenshot, screen recording)
             generated  made by the agent's own image/video/voice tools (non-UI plates, people scenes, VO)
             licensed   third-party (music, sfx, fonts): needs `licence`
             mock       a stand-in so the plan can be reviewed before the real thing exists (shown as MOCK; must be replaced before drafts)
    how      one line: how it will be captured / generated / sourced (prompt, command, who records it)
    path     the file (relative to the project dir); absent for a mock that has no stand-in yet

`problems(plan, scenes)` lists faults (scene with no asset, UI shot fed by generated media, licensed without licence, ...),
`section()` renders the gallery the session shows: images as thumbnails, videos as a poster frame, audio as a player (small files) or a labelled tile,
mocks as a striped MOCK tile. Same team rules as AGENTS.md: real footage only for UI; generated assets only for non-UI plates, people scenes
the person approved (brief conflicts), voices and music.
"""
from __future__ import annotations

import base64
import html
import json
import os
import subprocess

KINDS = ("screenshot", "image", "recording", "video", "music", "voice", "sfx")
SOURCES = ("real", "generated", "licensed", "mock")
UI_KINDS = ("screenshot", "recording")
IMG = (".png", ".jpg", ".jpeg", ".webp")
VID = (".mp4", ".mov", ".webm", ".m4v")
AUD = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac")


def plan_path(flow_dir):
    return os.path.join(flow_dir, "assets.json")


def load(flow_dir):
    try:
        return json.load(open(plan_path(flow_dir)))
    except (OSError, ValueError):
        return []


def save(flow_dir, plan):
    os.makedirs(flow_dir, exist_ok=True)
    with open(plan_path(flow_dir), "w") as f:
        json.dump(plan, f, indent=2)


def upsert(plan, a):
    plan = [x for x in plan if x["id"] != a["id"]]
    plan.append(a)
    return sorted(plan, key=lambda x: (x.get("scenes") or ["~"])[0] + x["id"])


def state(a, project_dir):
    p = a.get("path")
    if p and os.path.isfile(os.path.join(project_dir, p)):
        return "mock" if a.get("source") == "mock" else "ready"
    return "mock" if a.get("source") == "mock" else "todo"


def problems(plan, scene_ids, project_dir, final=False):
    """final=True (before drafts): mocks and todos are faults; otherwise they are the open to-do list."""
    out = []
    if not plan:
        return ["no assets planned: add them with `promo flow asset add`"]
    seen = set()
    cov = set()
    for a in plan:
        i = a.get("id", "?")
        if i in seen:
            out.append(f"asset {i}: duplicate id")
        seen.add(i)
        if a.get("kind") not in KINDS:
            out.append(f"asset {i}: kind must be one of {'|'.join(KINDS)}")
        if a.get("source") not in SOURCES:
            out.append(f"asset {i}: source must be one of {'|'.join(SOURCES)}")
        if not a.get("how"):
            out.append(f"asset {i}: needs `how` (how it is captured / generated / sourced)")
        if not a.get("scenes"):
            out.append(f"asset {i}: needs scenes it is used in")
        for s in a.get("scenes") or []:
            cov.add(s)
            if s not in scene_ids:
                out.append(f"asset {i}: scene {s} is not in the storyboard")
        if a.get("kind") in UI_KINDS and a.get("source") not in ("real", "mock"):
            out.append(f"asset {i}: a {a['kind']} of the product must be real (or a labelled mock until it is captured); generated UI is not allowed")
        if a.get("source") == "licensed" and not a.get("licence"):
            out.append(f"asset {i}: licensed asset needs `licence` (and a source URL in `note`)")
        st = state(a, project_dir)
        if final and st != "ready":
            out.append(f"asset {i}: still {st}: replace it with the real file before drafts")
    for s in scene_ids:
        if s not in cov:
            out.append(f"scene {s}: no asset planned for it")
    return out


def _uri(path, mime, limit=None):
    try:
        if limit and os.path.getsize(path) > limit:
            return ""
        return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()
    except OSError:
        return ""


def _thumb(path, w=520):
    try:
        import io
        from PIL import Image
        im = Image.open(path).convert("RGB")
        if im.width > w:
            im = im.resize((w, round(im.height * w / im.width)))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return ""


def _poster(path):
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", path, "-frames:v", "1", "-vf", "scale=520:-2", "-f", "image2pipe",
                            "-vcodec", "mjpeg", "-"], capture_output=True, timeout=30)
        return "data:image/jpeg;base64," + base64.b64encode(r.stdout).decode() if r.stdout else ""
    except Exception:  # noqa: BLE001
        return ""


CSS = """
.assets{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;margin:10px 0}
.as{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.as .pv{aspect-ratio:16/10;background:var(--ph);display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden}
.as .pv img{width:100%;height:100%;object-fit:cover}.as .pv audio{width:92%}
.as .pv.mock{background:repeating-linear-gradient(45deg,var(--ph),var(--ph) 10px,var(--line) 10px,var(--line) 20px);color:var(--mute);font-weight:600;font-size:13px;letter-spacing:.08em}
.as .pv.todo{color:var(--mute);font-size:12px;text-align:center;padding:8px}
.as .bd{padding:9px 11px;font-size:13px}.as .bd b{font-size:14px}.as .k{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0}
.chip{font-size:11px;border:1px solid var(--line);border-radius:10px;padding:0 7px;color:var(--mute)}
.chip.ready{color:var(--ok);border-color:var(--ok)}.chip.mock,.chip.todo{color:var(--warn);border-color:var(--warn)}
.as .how{color:var(--mute)}
"""


def section(plan, project_dir):
    esc = html.escape
    cards = []
    for a in plan:
        st = state(a, project_dir)
        p = os.path.join(project_dir, a["path"]) if a.get("path") else ""
        ext = os.path.splitext(p)[1].lower()
        pv, cls = "", ""
        if st == "mock":
            cls = "mock"
            uri = _thumb(p) if p and ext in IMG else ""
            pv = f'<img src="{uri}" alt=""><span style="position:absolute;right:8px;top:8px;background:rgba(0,0,0,.65);color:#fff;font-size:11px;padding:1px 7px;border-radius:4px">MOCK</span>' if uri else "MOCK"
        elif st == "todo":
            cls = "todo"
            pv = "not made yet"
        elif ext in IMG:
            pv = f'<img src="{_thumb(p)}" alt="">'
        elif ext in VID:
            pv = f'<img src="{_poster(p)}" alt="">'
        elif ext in AUD:
            uri = _uri(p, "audio/mpeg" if ext == ".mp3" else "audio/wav", 2_500_000)
            pv = f'<audio controls src="{uri}"></audio>' if uri else f"{esc(os.path.basename(p))} ({os.path.getsize(p) // 1024} KB)"
        scenes = ", ".join(a.get("scenes") or [])
        cards.append(
            f'<div class="as"><div class="pv {cls}">{pv}</div><div class="bd"><b>{esc(a["id"])}</b>'
            f'<div class="k"><span class="chip">{esc(a.get("kind", ""))}</span><span class="chip">{esc(a.get("source", ""))}</span>'
            f'<span class="chip {st}">{st}</span><span class="chip">scenes {esc(scenes)}</span></div>'
            f'<div class="how">{esc(a.get("how", ""))}</div>'
            + (f'<div class="how">licence: {esc(a["licence"])}</div>' if a.get("licence") else "") + "</div></div>")
    n = {k: sum(1 for a in plan if state(a, project_dir) == k) for k in ("ready", "mock", "todo")}
    return (f'<h2>Asset plan</h2><div class="meta">{len(plan)} assets · {n["ready"]} ready · {n["mock"]} mock · {n["todo"]} to make</div>'
            f'<style>{CSS}</style><div class="assets">{"".join(cards)}</div>')
