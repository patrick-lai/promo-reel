"""Canned promo-flow states for the mod harness: a believable flow project built in a temp dir (real PNG frames, WAV, MP4), driven through the real
`promo.flow` state machine, with `promo flow snapshot` captured at every stage. `build()` returns {name: snapshot} in display order.

    .venv/bin/python mod-dev/fixtures.py [--keep DIR] [--dump DIR]   print the stage list; keep the project in DIR; write <stage>.json snapshots (with `$file` paths) to DIR
"""
from __future__ import annotations

import copy
import datetime
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUNCIL_NOTE = ("Script A is the strongest hook and the easiest to film from real footage. Script B is short enough for a social cut but leans on one chime "
                "for its payoff. Script C shows the most of the product but needs three captures nobody has recorded yet.")
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from promo import abtest as AB  # noqa: E402
from promo import assetplan as AP  # noqa: E402
from promo import autopilot as AU  # noqa: E402
from promo import boardedit as BE  # noqa: E402
from promo import brief as BR  # noqa: E402
from promo import flow as F  # noqa: E402
from promo import flowcheck as FC  # noqa: E402
from promo import flowjob as FJ  # noqa: E402
from promo import home  # noqa: E402
from promo import previews as PV  # noqa: E402
from promo import scout as SC  # noqa: E402
from promo import share as SH  # noqa: E402

INTENT = "Make a 60 second promo for Acme Tasks: tell it what you want at night, wake up to merged pull requests. Calm, real product footage, no hype."
FONTS = ["/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf"]
HUES = [(26, 38, 80), (60, 40, 90), (20, 70, 90), (90, 50, 40), (30, 80, 70), (80, 60, 30), (40, 40, 70), (100, 50, 70)]


def uploaded(pd, kind, n, dest, edited=False):
    """Pretend the person's earlier upload of draft/final N to `dest`: stored the way `promo flow share` does, so the snapshot reads it back."""
    st = F.load(pd)
    path = (st["drafts"] if kind == "draft" else st["finals"])[n - 1]["file"]
    rid = f"{kind}{n}-{dest}"
    url = f"https://acme.atlassian.net/artifacts/{rid}" if dest == "artifacts" else f"https://www.loom.com/share/{rid.replace('-', '')}"
    st.setdefault("shares", {}).setdefault(f"{kind}-{n}", {})[dest] = dict(id=rid, url=url, name=SH.canonical(pd, kind, n), sha="edited-since" if edited else SH.file_sha(path),
                                                                           at=F.now(), access="private", by="Sam")
    F.save(pd, st)


def twg_available(pd, **dests):
    st = F.load(pd)
    st["share"] = dict(detected=dict(at=F.now(), dests={d: dict(ok=ok, why="" if ok else "not available") for d, ok in dests.items()}))
    F.save(pd, st)


def font(size):
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def frame(path, no, which, beat, tint, size=(960, 540)):
    """A distinct, labelled keyframe: a sky that darkens/brightens, a sun that rises, a few UI-ish blocks that fill in from START to END."""
    w, h = size
    os.makedirs(os.path.dirname(path), exist_ok=True)
    k = 0.0 if which == "START" else 1.0 if which == "END" else 0.5
    top = tuple(int(c * (0.5 + 0.9 * k)) for c in tint)
    bot = tuple(min(255, int(c * (1.1 + 1.3 * k))) for c in tint)
    im = Image.new("RGB", size)
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3)))
    sx, sy = int(w * (0.22 + 0.56 * k)), int(h * (0.78 - 0.5 * k))
    d.ellipse([sx - 54, sy - 54, sx + 54, sy + 54], fill=(255, int(200 + 40 * k), int(120 + 90 * k)))
    d.rectangle([0, int(h * 0.8), w, h], fill=(12, 12, 16))
    bx = 70 + (no % 3) * 22
    for i in range(3):
        wd = int((w - 2 * bx) / 3 - 14)
        x0 = bx + i * (wd + 14)
        d.rounded_rectangle([x0, int(h * 0.58), x0 + wd, int(h * 0.58) + 78], 10, fill=(255, 255, 255, 0) if False else (22 + 30 * (i <= round(2 * k)), 26 + 30 * (i <= round(2 * k)), 38 + 40 * (i <= round(2 * k))), outline=(255, 255, 255))
        d.rectangle([x0 + 12, int(h * 0.58) + 14, x0 + 12 + int(wd * (0.3 + 0.5 * k)), int(h * 0.58) + 22], fill=(255, 255, 255))
    d.text((w - 34, 20), f"{no:02d}", font=font(96), fill=(255, 255, 255), anchor="ra")
    im.save(path)


def still(path, text, tint, size=(960, 540)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im = Image.new("RGB", size, tint)
    d = ImageDraw.Draw(im)
    for i in range(0, size[0], 60):
        d.line([(i, 0), (i, size[1])], fill=tuple(min(255, c + 14) for c in tint))
    for j in range(0, size[1], 60):
        d.line([(0, j), (size[0], j)], fill=tuple(min(255, c + 14) for c in tint))
    d.rounded_rectangle([60, 70, size[0] - 60, 130], 12, fill=(255, 255, 255))
    for r in range(5):
        d.rounded_rectangle([60, 160 + r * 62, size[0] - 60, 210 + r * 62], 10, fill=(255, 255, 255) if r % 2 == 0 else (235, 238, 245))
    d.text((80, 80), text, font=font(34), fill=(20, 20, 30))
    im.save(path)


def wav(path, hz, seconds=2.0, rate=22050):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(rate * seconds)
        w.writeframes(b"".join(int(9000 * math.sin(2 * math.pi * hz * i / rate) * (1 - i / n)).to_bytes(2, "little", signed=True) for i in range(n)))


def mp4(path, src="testsrc2", seconds=3, size="640x360"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=size={size}:rate=25", "-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", path], check=True)


def write(p, txt):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(txt)


def sc(i, t0, t1, beat, action, **kw):
    s = dict(id=i, beat=beat, t=[t0, t1], action=action, source="real", proof="ticket list on screen shows the run",
             start=dict(image=f"frames/{i}-start.png", prompt=f"Start of {beat}: {action}"), end=dict(image=f"frames/{i}-end.png", prompt=f"End of {beat}: the same scene a few seconds later"))
    s.update(kw)
    if s.get("source") is None:
        s.pop("source", None)
    return s


BOARD_A = dict(story="A", title="Wake up to merged PRs", logline="One request at night, and by morning the work is merged: calm, real footage, no hype.", aspect="16:9", scenes=[
    sc("01", 0, 5, "It's night", "A quiet desk at 11:48 pm. The laptop is the only light in the room.", source="generated", proof="", caption="", camera="slow push-in", sound="room tone, a distant fan"),
    sc("02", 5, 11, "Tell it", "The person types one sentence into Acme Tasks and presses return.", caption="Tell it what you want", vo="Before bed, I tell it what I want built.", sound="soft key clicks", camera="static, over the shoulder",
       proof="Footage take 02: composer with the request typed"),
    sc("03", 11, 18, "Agents spin up", "The board fills with tickets as agents pick them up, one by one.", caption="8 tasks, 3 agents", vo="It splits the work and gets going.", sound="gentle rise", camera="push-in to the board",
       proof="Footage take 03: 8 tickets, 3 agent chips visible", frames=[dict(t=14.5, image="frames/03-mid.png", prompt="Mid frame: half the tickets claimed"), dict(t=16.5, image="frames/03-mid2.png", prompt="Mid frame: all tickets claimed")]),
    sc("04", 18, 27, "While you sleep", "Time-lapse of the window going dark, then the first light at the edge of the blinds. The agent log keeps scrolling in the corner.",
       source="generated", proof="", camera="locked off, time-lapse", sound="a slow pad swells"),
    sc("05", 27, 33, "Morning", "Dawn. The same desk, warm light, a cup of coffee, the laptop wakes.", source="generated", proof="", camera="slow pull-back", sound="birds, very low"),
    sc("06", 33, 42, "Merged", "Pull requests list: eight merged, all checks green. A cursor hovers over the last one.", caption="Merged while you slept", vo="By morning it is merged.", sound="a single chime",
       camera="push-in to the merged column", proof="Footage take 06: PR list, 8 merged"),
    sc("07", 42, 52, "Proof", "A pull request diff with a short plain-language summary of what changed and why, then the review thread.", caption="Every change is reviewable", vo="Every change is there to read.",
       camera="static", proof="Footage take 07: diff view and summary"),
    sc("08", 52, 60, "End card", "Product name, one-line promise and the requirements. Dawn sky behind.", source="generated", proof="", caption="", sound="music resolves", camera="static"),
])
BOARD_B = dict(story="B", title="Ten second teaser", logline="A short cut for social: only the night, the tickets and the merge.", aspect="16:9", scenes=[
    sc("11", 0, 3, "Night", "A dark room, one lit laptop.", source="generated", proof=""),
    sc("12", 3, 6, "Request", "One sentence, return.", caption="Tell it at night", proof="Footage take 02"),
    sc("13", 6, 8, "Work", "Tickets move across the board.", caption="Agents get to work", proof="Footage take 03", source=None),
    sc("14", 8, 10, "Merged", "Eight merged PRs.", caption="Wake up to merged PRs", proof="Footage take 06"),
])

SCRIPTS = [
    ("A", "Wake up to merged PRs", "Night to dawn: the person gives one instruction before bed and the morning shows the merged work, told in plain, calm footage."),
    ("B", "The ten second teaser", "A tight vertical-friendly cut: the request, the board filling, the merge. No voice, one line of text, one chime."),
    ("C", "A day in the life of a ticket", "Follow one ticket from a sentence to a merged pull request: each agent hand-off shown on the real board."),
]
BEATS = {
    "A": ["A quiet desk at 11:48 pm, the laptop is the only light", "One sentence typed, return pressed, the lid closes", "Time-lapse to dawn while the agent log scrolls", "Eight merged pull requests on the screen"],
    "B": ["Night, one lit laptop", "The request typed in a single line", "Tickets move across the board", "Eight merged, one chime"],
    "C": ["A ticket is created from one sentence", "An agent claims it and opens a branch", "Review comments resolve one by one", "The pull request merges"],
}
STYLE_REFS = ["https://www.youtube.com/watch?v=Zq1JhZq6q0k"]


BANK = ["The room is quiet and the only light is the laptop.", "One sentence is typed, and nothing else is needed.", "The board fills with tickets, each claimed by an agent.",
        "A progress line moves along the bottom of the screen, and nobody touches it.", "The first pull request opens, with a short note on what it changes and why.", "Checks run in the background and turn green one by one.",
        "A reviewer comment is answered by the agent, and the thread resolves.", "The window goes dark and the clock moves past midnight.", "At the edge of the blinds the first grey light arrives.",
        "The merged column grows by one, then another, then six more.", "Nothing here is staged: every number on screen is the number from the real run.", "The person reads the summary and scrolls to the diff."]


def long_script_md(title, acts=6, words=9000):
    """A believable long script (headings, picture / voice / sound lines, a timing table, checklists, a quote), about `words` words."""
    out = [f"# {title}", "", "> One request at night. By morning the work is merged. Calm, real footage, no hype.", "", "**Length:** 60 s master · **Format:** 16:9 · **Voice:** warm, unhurried", ""]
    per = words // (acts * 6)
    n = 0
    for a in range(acts):
        out += [f"## Act {a + 1}: " + ["The night", "The request", "The work", "The long dark", "Morning", "Proof"][a % 6], ""]
        for sc in range(6):
            n += 1
            body = " ".join(BANK[(n * 3 + i) % len(BANK)] for i in range(max(2, per // 14)))
            out += [f"### Scene {n:02d}", "", f"**Picture:** {body}", f"**Voice:** \"{BANK[(n * 5) % len(BANK)]}\"", f"**Sound:** soft room tone, a single key click at {n % 9 + 1} s", ""]
            if sc == 2:
                out += ["| Beat | Time | Proof |", "|---|---|---|", f"| Request typed | {n % 9 + 1} s | footage take 02 |", f"| Tickets claimed | {n % 9 + 5} s | footage take 03 |", ""]
            if sc == 4:
                out += ["- [x] Evidence checked against the real run", "- [ ] Caption held for 2 s", f"- Timing note: see [the style reference](https://example.com/ref-{n})", ""]
        out += ["---", ""]
    return "\n".join(out)


def gen_boards(pd, which=("A", "B")):
    for sid, b in (("A", BOARD_A), ("B", BOARD_B)):
        if sid not in which:
            continue
        d = os.path.join(pd, "flow", "boards", sid)
        write(os.path.join(d, "board.json"), json.dumps(b, indent=2))
        for n, s in enumerate(b["scenes"]):
            tint = HUES[(n + (3 if sid == "B" else 0)) % len(HUES)]
            frame(os.path.join(d, s["start"]["image"]), int(s["id"]), "START", s["beat"], tint)
            frame(os.path.join(d, s["end"]["image"]), int(s["id"]), "END", s["beat"], tint)


def running_job(pd, made, stopped=False):
    """A storyboard image run part way through, as `promo flow frames` leaves it: `made` frames landed (one failed), started minutes ago.
    Running means this process is alive, which holds while the harness serves the snapshot."""
    st = F.load(pd)
    bds = F.boards(pd, st)
    queue = [dict(id=t[0], label=F._keyframe_label(bds, dict(zip(("story", "scene", "which"), t[0].split("/", 2))))[0], story=t[0].split("/")[0], scene=t[0].split("/")[1], path=t[4])
             for t in PV.frame_targets(bds, force=True)]
    job = FJ.Job(os.path.join(pd, "flow"), "frames", "Generating storyboard images", [{k: v for k, v in q.items() if k != "path"} for q in queue], 3)
    t0 = datetime.datetime.now().astimezone() - datetime.timedelta(seconds=25 * made + 40)
    for i, q in enumerate(queue[:made]):
        job.item(q["id"], q["path"], "grok produced no file" if i == 4 else None)
        job.d["items"][-1]["at"] = (t0 + datetime.timedelta(seconds=25 * (i + 1))).isoformat(timespec="seconds")
    job.d["started"] = t0.isoformat(timespec="seconds")
    if stopped:
        job.close(stopped=True)
    else:
        with job.lock:
            job._write()


def building_job(pd):
    """`promo build` part way through, as the CLI leaves it in a flow project: checks and unchanged sound effects done, voice and music made,
    three shots rendered (the storyboard frames stand in for their thumbnails), shot 04 rendering now."""
    from promo import cli
    d = os.path.join(pd, "flow", "boards", "A", "frames")
    names = ["checks", "sfx", "vo", "music"] + [f"shot {i:02d}" for i in range(1, 9)] + ["events", "mix", "assemble", "contact"]
    job = FJ.Job(os.path.join(pd, "flow"), "build", "Building the video", [cli._step_meta(n) for n in names], 1, resume=f"promo -p {pd}/promo.yaml build")
    t0 = datetime.datetime.now().astimezone() - datetime.timedelta(minutes=6)
    for i, n in enumerate(names[:7]):
        job.item(n, os.path.join(d, f"{n[5:]}-start.png") if n.startswith("shot") else None, None, skipped=n == "sfx")
        job.d["items"][-1]["at"] = (t0 + datetime.timedelta(seconds=50 * (i + 1))).isoformat(timespec="seconds")
    job.d["started"] = t0.isoformat(timespec="seconds")
    with job.lock:
        job._write()


def gen_mids(pd):
    d = os.path.join(pd, "flow", "boards", "A")
    for name, which in (("03-mid.png", "MID"), ("03-mid2.png", "MID")):
        frame(os.path.join(d, "frames", name), 3, which, "Agents spin up", HUES[2])


ASSETS = [
    dict(id="music-bed", label="Ambient music bed", kind="music", source="licensed", scenes=["01", "02", "03", "04", "05", "06", "07", "08", "11", "12", "13", "14"], how="Calm ambient bed at 98 BPM, 60 s.", path="audio/bed.wav", licence="Pixabay Content Licence (no standalone redistribution)", note="https://pixabay.com/music/calm-ambient-bed/"),
    dict(id="vo-main", label="Narration", kind="voice", source="generated", scenes=["02", "03", "06", "07"], how="Warm, unhurried voice reading the four lines from the locked script.", path="audio/vo.wav"),
    dict(id="ui-ticket-list", label="Ticket list screenshot", kind="screenshot", source="real", scenes=["02", "03", "12", "13"], how="Full-resolution capture of the ticket list from the demo project, DPR 2.", path="footage/ticket-list.png"),
    dict(id="ui-pr-merged", label="Merged pull requests screenshot", kind="screenshot", source="real", scenes=["06", "07", "14"], how="Pull request list with eight merged PRs; cursor away from any avatar.", path="footage/pr-merged.png"),
    dict(id="rec-night-run", label="Night run recording", kind="recording", source="real", scenes=["03", "04"], how="Screen recording of the real run from request to the last ticket claimed, 60 fps.", path="footage/night-run.mp4"),
    dict(id="plate-night-desk", label="Night desk plate", kind="image", source="generated", scenes=["01", "05", "11"], how="Quiet desk at night, one laptop glowing, shallow depth of field, warm lamp off. No screens, text or logos readable.", path="assets/night-desk.png"),
    dict(id="sfx-chime", label="Merge chime", kind="sfx", source="licensed", scenes=["06"], how="Single soft chime on the merged column.", path="audio/chime.wav", licence="CC0", note="https://freesound.org/s/chime/"),
    dict(id="rec-agents-grid", label="Agents grid close-up", kind="recording", source="mock", scenes=["03"], how="Close recording of the agents grid while three agents work. Not captured yet."),
    dict(id="title-card", label="End card", kind="image", source="mock", scenes=["08"], how="End card with the product name on the dawn plate.", path="assets/title-mock.png"),
    dict(id="sfx-keyboard", label="Keyboard sound", kind="sfx", source="generated", scenes=["02"], how="Soft mechanical keyboard, four seconds, no loud transients."),
    dict(id="plate-dawn", label="Dawn light plate", kind="video", source="generated", scenes=["04", "08"], how="Generated dawn light through blinds, 4 s, 16:9, no people or text."),
]


def gen_assets(pd, stage):
    p = lambda *a: os.path.join(pd, *a)  # noqa: E731
    still(p("footage", "ticket-list.png"), "Tickets (8)", (232, 236, 244))
    still(p("footage", "pr-merged.png"), "Merged pull requests (8)", (226, 240, 232))
    mp4(p("footage", "night-run.mp4"), "testsrc2", 3)
    frame(p("assets", "night-desk.png"), 1, "START", "Night desk plate", HUES[0])
    wav(p("audio", "bed.wav"), 196, 3.0)
    wav(p("audio", "vo.wav"), 330, 2.0)
    wav(p("audio", "chime.wav"), 880, 1.0)
    still(p("assets", "title-mock.png"), "Acme Tasks (mock title)", (240, 214, 190))
    plan = copy.deepcopy(ASSETS)
    if stage == "ready":
        for a in plan:
            if a["source"] == "mock":
                a["source"] = "real"
        by = {a["id"]: a for a in plan}
        by["rec-agents-grid"]["path"] = "footage/night-run.mp4"
        by["title-card"]["source"] = "generated"
        by["sfx-keyboard"]["path"] = "audio/chime.wav"
        mp4(p("assets", "dawn.mp4"), "smptebars", 3)
        by["plate-dawn"]["path"] = "assets/dawn.mp4"
    AP.save(os.path.join(pd, "flow"), plan)
    samples = {}
    for a in plan:
        if not a.get("path"):
            rel = os.path.join("flow", "previews", a["id"] + (".wav" if a["kind"] == "sfx" else ".mp4"))
            (wav(p(rel), 520, 1.5) if a["kind"] == "sfx" else mp4(p(rel), "testsrc2", 2))
            samples[a["id"]] = dict(path=rel, note="Fixture sample standing in for the asset.", at=F.now())
    write(p("flow", "samples.json"), json.dumps(samples))


VIEWER_HTML = r"""<canvas id="c" aria-label="3D model, drag to turn"></canvas>
<div class="bar"><label>Spin <input id="spin" type="range" min="0" max="3" step="0.1" value="0.6"></label><span id="info"></span><button id="ask">Render this angle</button></div>
<style>#c{display:block;width:100%;height:calc(100% - 44px);cursor:grab;touch-action:none}.bar{display:flex;gap:12px;align-items:center;padding:8px 14px;border-top:1px solid var(--pf-line)}
#info{flex:1;color:var(--pf-dim);font-size:12px}button{font:inherit;padding:5px 12px;border-radius:8px;border:1px solid var(--pf-line);background:var(--pf-raised);color:var(--pf-ink)}html,body{height:100%}input{accent-color:var(--pf-accent)}</style>
<script>
promo.ready(() => {
  const V = [], E = new Set();
  for (const l of promo.data["model.obj"].split("\n")) {
    const p = l.trim().split(/\s+/);
    if (p[0] === "v") V.push(p.slice(1).map(Number));
    if (p[0] === "f") { const f = p.slice(1).map((x) => +x.split("/")[0] - 1); f.forEach((a, i) => { const b = f[(i + 1) % f.length]; E.add(a < b ? a + "," + b : b + "," + a); }); }
  }
  const edges = [...E].map((k) => k.split(",").map(Number));
  const cv = document.getElementById("c"), cx = cv.getContext("2d"), spin = document.getElementById("spin");
  let ay = 0.4, ax = 0.5, drag = null;
  document.getElementById("info").textContent = V.length + " vertices, " + edges.length + " edges";
  cv.addEventListener("pointerdown", (e) => { drag = [e.clientX, e.clientY]; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener("pointermove", (e) => { if (!drag) return; ay += (e.clientX - drag[0]) * 0.01; ax += (e.clientY - drag[1]) * 0.01; drag = [e.clientX, e.clientY]; });
  cv.addEventListener("pointerup", () => { drag = null; });
  document.getElementById("ask").onclick = () => promo.tell("Render the torus from this angle: yaw " + (ay % 6.283).toFixed(2) + ", pitch " + ax.toFixed(2));
  (function frame() {
    const w = cv.width = cv.clientWidth * 2, h = cv.height = cv.clientHeight * 2;
    ay += +spin.value * 0.01;
    const sy = Math.sin(ay), cy = Math.cos(ay), sx = Math.sin(ax), cxx = Math.cos(ax), k = Math.min(w, h) * 0.3;
    const P = V.map(([x, y, z]) => { const x1 = x * cy + z * sy, z1 = -x * sy + z * cy, y1 = y * cxx - z1 * sx, z2 = y * sx + z1 * cxx; return [w / 2 + x1 * k, h / 2 + y1 * k, z2]; });
    cx.clearRect(0, 0, w, h);
    cx.strokeStyle = promo.theme.accent; cx.lineWidth = 1.5;
    cx.beginPath();
    for (const [a, b] of edges) { cx.moveTo(P[a][0], P[a][1]); cx.lineTo(P[b][0], P[b][1]); }
    cx.stroke();
    requestAnimationFrame(frame);
  })();
});
</script>"""


PROBE_HTML = r"""<p id="p" style="margin:0;padding:6px 14px 14px">Loading the still...</p>
<script>
promo.ready(() => promo.file("probe.png").then((b) => {
  document.getElementById("p").textContent = "The widget read its attached still: " + b.type + ", " + b.size + " bytes. Theme is " + (promo.theme.dark ? "dark" : "light") + ".";
  promo.tell("Use this still as the title card background");
}));
</script>"""


def torus_obj(major=12, minor=8):
    L = []
    for i in range(major):
        for j in range(minor):
            u, v = 2 * math.pi * i / major, 2 * math.pi * j / minor
            L.append(f"v {(1.1 + 0.45 * math.cos(v)) * math.cos(u):.4f} {0.45 * math.sin(v):.4f} {(1.1 + 0.45 * math.cos(v)) * math.sin(u):.4f}")
    for i in range(major):
        for j in range(minor):
            a, b = i * minor + j + 1, ((i + 1) % major) * minor + j + 1
            c, d = ((i + 1) % major) * minor + (j + 1) % minor + 1, i * minor + (j + 1) % minor + 1
            L.append(f"f {a} {b} {c} {d}")
    return "\n".join(L) + "\n"


def add_widgets(tmp, pd):
    """What an agent builds for a job the fixed tabs do not cover: a Blender render queue, a model viewer and a grade comparison."""
    obj = os.path.join(tmp, "model.obj")
    write(obj, torus_obj())
    shots = []
    for name, tint in (("turntable-120.png", (226, 214, 238)), ("grade-a.png", (238, 226, 206)), ("grade-b.png", (206, 222, 238))):
        p = os.path.join(tmp, name)
        still(p, name.split(".")[0], tint, (640, 360))
        shots.append(p)
    blocks = [
        {"type": "stats", "items": [{"label": "Frames", "value": "240", "hint": "24 fps, 10 s"}, {"label": "Samples", "value": "128"}, {"label": "Per frame", "value": "1.5 min"}]},
        {"type": "progress", "label": "Render queue: 3 of 5 shots", "value": 0.6},
        {"type": "table", "title": "Shots", "columns": ["Shot", "Engine", "Frames", "Status"],
         "rows": [["01 Orbit", "Cycles", "96", "done"], ["02 Dolly", "Cycles", "72", "done"], ["03 Macro", "Cycles", "48", "rendering"], ["04 Reveal", "Eevee", "24", "queued"]]},
        {"type": "bars", "title": "Minutes per shot", "unit": "min", "items": [{"label": "01 Orbit", "value": 144}, {"label": "02 Dolly", "value": 108}, {"label": "03 Macro", "value": 31}]},
        {"type": "callout", "tone": "warn", "text": "Shot 04 still needs the final HDRI before it can render."},
        {"type": "checklist", "items": [{"text": "Bake the cloth sim", "done": True}, {"text": "Denoise pass", "done": True}, {"text": "Colour-managed export", "done": False}]},
        {"type": "image", "file": "turntable-120.png", "caption": "Frame 120 of the turntable"}]
    F.widget_put(pd, "render-queue", "Blender render queue", text=json.dumps(blocks), attach=[shots[0]], summary="Live from the scene file", span=12, order=1)
    F.widget_put(pd, "model", "Model viewer", text=VIEWER_HTML, attach=[f"model.obj={obj}"], summary="Drag to turn it", span=8, height="l", order=2)
    F.widget_put(pd, "settings", "Scene settings", text=json.dumps([
        {"type": "kv", "items": [{"key": "Engine", "value": "Cycles"}, {"key": "Resolution", "value": "3840 x 2160"}, {"key": "Denoiser", "value": "OpenImageDenoise"}, {"key": "Colour", "value": "AgX"}]},
        {"type": "list", "title": "Add-ons", "items": ["Hard Ops", "Node Wrangler", "Animation Nodes"]}]), span=4, height="l", order=3)
    F.widget_put(pd, "probe", "Attached still", text=PROBE_HTML, attach=[f"probe.png={shots[0]}"], summary="A widget reading its own file", span=12, height="auto", order=4)
    F.widget_put(pd, "grade", "Grade comparison", text=json.dumps([{"type": "gallery", "files": ["grade-a.png", "grade-b.png"]}, {"type": "text", "text": "**A** is warmer, **B** keeps the product blue. See the [notes](https://example.com/grade)."}]),
                 attach=[f"grade-a.png={shots[1]}", f"grade-b.png={shots[2]}"], place="storyboard", span=12)


def round_files(tmp, pd, n, verdict, feedback_urls=3):
    sha = BR.intent_sha(BR.load(pd))
    co = os.path.join(tmp, f"co{n}.md")
    re_ = os.path.join(tmp, f"re{n}.md")
    write(co, f"intent-check: intent_sha={sha} verdict={verdict} intent=4 reference=3 lens=intent-reference\nThe cut keeps the calm night-to-dawn arc the request asked for.")
    urls = ["https://www.apple.com/newsroom/", "https://vimeo.com/staffpicks", "https://www.linear.app/changelog", "https://www.theverge.com/tech", "https://stripe.com/blog/engineering"]
    write(re_, "\n".join(urls[:max(feedback_urls, 3)]))
    return co, re_


def council_marks(pd, fails=()):
    """What the council does on a new draft before the round can close: every judge check marked (the hidden control as false, `fails` as
    failing) and the draft compared blind with the one the person reviewed, both orders preferring the new one."""
    for c in FC.judge_checks(F.load(pd)):
        bad = c.get("control") or c["what"] in fails
        FC.mark(pd, c["id"], None, "fail" if bad else "pass", "not on screen in any still" if bad else "visible in the scene's stills", "claude", "story lens")
    jid, _ = AB.judge_pair(pd)
    p = AB.pair(F.load(pd), jid)
    for k, o in p["orders"].items():
        AB.judge(pd, jid, k, "A" if o["A"] == p["draft"] else "B", family="claude")


def check_report(tmp, pd, n, skipped=True):
    """A `promo check` report for draft n's own file, as `promo check` writes it after a build."""
    rows = [dict(gate=g, status="PASS", msg=m) for g, m in (("assets", "manifest complete"), ("footage", "7 referenced clips present, sha256 match"), ("timeline", "9 shots contiguous"),
                                                            ("beat-grid", "all cuts on beats"), ("duration", "60.000s"), ("video-format", "1920x1080 30fps"), ("loudness", "-14.0 LUFS"),
                                                            ("true-peak", "-1.4 dBTP"), ("caption-hold", "every caption held >= 2.0 s"), ("safe-zone", "captions inside the 9:16 column"))]
    rows.append(dict(gate="footage-demo", status="WARN", msg="demo-mode footage in use: ui-tickets"))
    if skipped:
        rows.append(dict(gate="vo-script", status="WARN", msg="skipped: faster-whisper not installed"))
    rp = os.path.join(tmp, f"check-{n}.json")
    write(rp, json.dumps(dict(ok=True, failed=False, results=rows, outputs=[dict(file="x", sha256=F.load(pd)["drafts"][n - 1]["sha"])])))
    FC.verify(pd, n, rp)


def aged(pd, days):
    """Move every timestamp of a flow `days` back, so the picker's "last active" and its most-recent-first order read like real history."""
    fp = os.path.join(pd, "flow", "flow.json")
    st = json.load(open(fp))
    back = lambda at: (datetime.datetime.fromisoformat(at) - datetime.timedelta(days=days)).isoformat(timespec="seconds")  # noqa: E731
    for x in (st.get("log") or []) + (st.get("activity") or []) + list(st["gates"].values()):
        x["at"] = back(x["at"])
    json.dump(st, open(fp, "w"), indent=2)


def picker_states(tmp, finished):
    """States of the promo-projects mod (the /promo-resume picker) over small real flow projects at different steps, plus `finished` (the full fixture project) copied in."""
    base = os.path.join(tmp, "picker")
    if os.path.isdir(base):
        shutil.rmtree(base)
    if os.path.exists(home.recent_path()):
        os.remove(home.recent_path())              # `finished` itself was remembered when it started; the picker shows its copy only
    shutil.copytree(finished, os.path.join(base, "acme-tasks-hero"), symlinks=True)
    aged(os.path.join(base, "acme-tasks-hero"), 9)
    tour = os.path.join(base, "acme-onboarding-tour")
    F.init(tour, "A 45 second tour of Acme onboarding for new admins: invite the team, connect the repo, first task done. Captions only, no voice.")
    F.discover(tour, "Calm product hero", [], True)
    F.advance(tour)
    for sid, title, logline in SCRIPTS[:3]:
        F.add_script(tour, sid, title, logline, text=f"# {title}\n\n{logline}\n\n" + "\n".join(f"{i + 1}. {b}" for i, b in enumerate(BEATS[sid])))
    write(os.path.join(tmp, "tour-council.md"), COUNCIL_NOTE)
    F.add_council(tour, "scripts", os.path.join(tmp, "tour-council.md"))
    F.advance(tour)
    F.approve(tour, "scripts-picked", "Sam", ["A"])
    F.advance(tour)
    gen_boards(tour, ("A",))
    aged(tour, 1)
    teaser = os.path.join(base, "acme-mobile-teaser")
    F.init(teaser, "Vertical 20 second teaser of Acme Tasks on mobile for the launch post. Punchy, music-led.")
    F.discover(teaser, "Kinetic anime opening", STYLE_REFS, False)
    F.advance(teaser)
    for sid, title, logline in SCRIPTS[:2]:
        F.add_script(teaser, sid, title, logline, text=f"# {title}\n\n{logline}")
    F.note(teaser, "Drafting the third script", "plan")
    oct_ = os.path.join(base, "release-notes-october")
    F.init(oct_, "Release notes video for October: the three biggest changes, with captions.")
    aged(oct_, 3)
    broken = os.path.join(base, "half-copied-project", "flow")
    os.makedirs(broken)
    write(os.path.join(broken, "flow.json"), "{ not json")
    tour_id = F.project_id(tour)
    out = {"picker": F.picker(), "picker-search": F.picker("mobile teaser"), "picker-resumed": F.picker(resumed=tour_id)}
    os.environ["PROMO_PROJECTS"] = os.path.join(tmp, "picker-empty")
    os.environ["PROMO_CONFIG"] = os.path.join(tmp, "picker-empty", "config.yaml")
    out["picker-empty"] = F.picker()
    out["picker-starting"] = {}
    return out


def build(keep=None):
    tmp = keep or tempfile.mkdtemp(prefix="promo-flow-fixtures-")
    os.makedirs(tmp, exist_ok=True)
    saved = {k: os.environ.get(k) for k in ("PROMO_CONFIG", "PROMO_PROJECTS")}
    os.environ["PROMO_CONFIG"] = os.path.join(tmp, "config", "config.yaml")       # `promo flow init` remembers flows: keep fixtures out of the person's own list
    os.environ["PROMO_PROJECTS"] = os.path.join(tmp, "picker")
    try:
        return _build(tmp)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _build(tmp):
    pd = os.path.join(tmp, "proj")
    if os.path.isdir(pd):
        shutil.rmtree(pd)
    out = {}
    snap = lambda name: out.__setitem__(name, F.snapshot(pd))  # noqa: E731
    F.init(pd, INTENT)
    snap("discover")
    F.discover(pd, "Calm product hero", STYLE_REFS, False)
    F.advance(pd)
    for sid, title, logline in SCRIPTS:
        sf = os.path.join(tmp, f"script-{sid}.md")
        write(sf, f"# {title}\n\n{logline}\n\n" + "\n".join(f"{i + 1}. {b}" for i, b in enumerate(BEATS[sid])) + "\n" + ("\n" + long_script_md("Full script: " + title, 4, 5200) if sid == "A" else ""))
        F.add_script(pd, sid, title, logline, sf)
    snap("scripts")
    cf = os.path.join(tmp, "council.md")
    write(cf, COUNCIL_NOTE)
    F.add_council(pd, "scripts", cf)
    F.recommend(pd, "A", "It follows the app's own run from one typed ask to merged PRs, so every scene is real footage we can capture today.")
    F.advance(pd)
    snap("pick")
    F.approve(pd, "scripts-picked", "Sam", ["A", "B"])
    F.advance(pd)
    gen_boards(pd)
    for sid, text in (("02", "Acme Tasks: New request"), ("06", "Pull requests: 8 merged")):
        shot = os.path.join(tmp, f"screen-{sid}.png")
        still(shot, text, (232, 236, 244))
        SC.add(pd, "A", sid, shot, url=f"https://app.acme.dev/{'tasks' if sid == '02' else 'pulls'}?demo=1")
    SC.miss(pd, "A", "07", "the diff view needs a reviewer account we do not have yet")
    snap("storyboard")
    n1 = F.scene_note(pd, "A", "03", "Hold the plan on screen a beat longer before the push-in.", "Sam")
    F.scene_note(pd, "A", "02", "Show the request being typed, not already sent.", "Sam")
    F.scene_resolve(pd, n1, "Held the plan for 1.5 s more and moved the push-in later.")
    snap("storyboard-notes")
    F.scene_resolve(pd, 2, "Redrew the start frame with the cursor in the box.")
    running_job(pd, 9)
    snap("generating")
    running_job(pd, 5, stopped=True)
    snap("generating-stopped")
    os.remove(os.path.join(pd, "flow", FJ.FILE))
    # the agent adds the whole production pack and a very long script on request
    F.plan_pack(pd)
    F.doc_put(pd, "full-script-a", title="Full script: Wake up to merged PRs", kind="script", text=long_script_md("Full script: Wake up to merged PRs", 8, 14000), story="A",
              summary="Every scene with picture, voice and sound. 8 acts.")
    F.doc_put(pd, "research-notes", kind="research", text="# Research\n\n## What the references do well\n\n- Slow push-ins on real UI, never a mock-up\n- One idea per cut\n\nSee https://www.apple.com/newsroom/ and [Linear's changelog](https://www.linear.app/changelog).\n\nSafe by construction: <img src=x onerror=alert(1)> and [bad](javascript:alert(1)) stay plain text.\n")
    snap("plan")
    add_widgets(tmp, pd)
    snap("widgets")
    st = F.load(pd)                                   # later states are without widgets; the files stay, the Stage serves them from disk
    st["widgets"] = []
    F.save(pd, st)
    fd = os.path.join(pd, "flow")
    bpa = os.path.join(fd, "boards", "A", "board.json")
    before = open(bpa).read()
    BE.density(fd, [b for b in F.boards(pd, F.load(pd)) if b[0] == "A"], every=5)
    dense = json.load(open(bpa))
    for n, sc_ in enumerate(dense["scenes"]):
        for k, fr_ in enumerate(sc_.get("frames") or []):
            if fr_.get("auto") and (n + k) % 3 != 2:
                frame(os.path.join(fd, "boards", "A", fr_["image"]), int(sc_["id"]), "MID", sc_["beat"], HUES[n % len(HUES)])
    snap("dense")
    open(bpa, "w").write(before)                      # the drawn frames stay on disk: the snapshot above serves them
    frames = [os.path.join(pd, "flow", "boards", "A", "frames", f"{x}-end.png") for x in ("02", "05", "07")] + [os.path.join(pd, "flow", "boards", "B", "frames", "13-start.png")]
    for fp in frames:
        os.rename(fp, fp + ".bak")
    snap("storyboard-partial")
    for fp in frames:
        os.rename(fp + ".bak", fp)
    F.advance(pd)
    gen_assets(pd, "plan")
    snap("assets")
    F.approve(pd, "assets-approved", "Sam")
    bp = os.path.join(pd, "flow", "boards", "A", "board.json")
    original = open(bp).read()
    edited = json.loads(original)
    edited["scenes"][2]["caption"] = "8 tasks, 3 agents at once"
    open(bp, "w").write(json.dumps(edited, indent=2))
    snap("stale-approval")
    open(bp, "w").write(original)
    broken = copy.deepcopy(out["assets"])
    broken["assets"][0]["path"] = {"$file": os.path.join(pd, "footage", "missing-capture.png")}
    out["assets-error"] = broken
    F.advance(pd)
    snap("keyframes")
    building_job(pd)
    snap("building")
    os.remove(os.path.join(pd, "flow", FJ.FILE))
    gen_mids(pd)
    gen_assets(pd, "ready")
    if not F.gate_ok(pd, F.load(pd), "assets-approved"):
        F.approve(pd, "assets-approved", "Sam")
    F.advance(pd)
    snap("confirm")
    F.advance(pd)
    for text, kind, done in [("Taking snapshots of the real app", "capture", True), ("Rendering screenshots for scene 2", "render", True), ("Rendering screenshots for scene 3", "render", True),
                             ("Designing the voice for the opening line", "voice", True), ("Cutting the music to 60 s on bar lines", "music", True),
                             ("Checking every cut lands on the beat", "check", True), ("Rendering scene 4 of 9", "render", False)]:
        F.note(pd, text, kind, done)
    snap("drafts")
    d1 = os.path.join(pd, "out", "draft-1.mp4")
    mp4(d1, "testsrc2", 4)
    F.add_draft(pd, d1, "First cut, 60 s, VO and music at rough levels.")
    check_report(tmp, pd, 1)
    F.advance(pd)
    from pathlib import Path
    from promo import watch as W
    os.makedirs(os.path.join(pd, "reference", "ref-1", "cuts"), exist_ok=True)
    for i, src in enumerate(("smptebars", "testsrc")):
        rv = os.path.join(tmp, f"ref-{src}.mp4")
        mp4(rv, src, 3)
        W.grab(Path(rv), 1.5, Path(os.path.join(pd, "reference", "ref-1", "cuts", f"cut-{i + 1:03d}.jpg")), 640)
    FC.look(pd, 1, "A")
    FC.pin(pd, 1, 3.0, "The typed sentence takes too long to appear", "Sam")
    F.round_start(pd, "The close up on the board is rough and the hook is slow. Can the first five seconds get to the typed sentence faster?", by="Sam")
    FC.add(pd, "The board close-up is sharp and readable", scene="03", source="feedback", by="Sam")
    FC.add(pd, "The typed sentence appears within the first five seconds", scene="02", source="feedback", by="Sam")
    F.recipe_use(pd, "hook.result-first")
    d2 = os.path.join(pd, "out", "draft-2.mp4")
    mp4(d2, "smptebars", 4)
    F.add_draft(pd, d2, "Hook shortened, board close-up re-framed.")
    check_report(tmp, pd, 2)
    FC.look(pd, 2, "A")
    council_marks(pd, fails=("The first 3 seconds show the product's real result on screen, readable.",))
    co, re_ = round_files(tmp, pd, 1, "PARTIAL")
    F.round_close(pd, co, re_)
    F.round_start(pd, "Better. Music still feels too present under the voice.", by="Sam")
    FC.add(pd, "The voice-over sits clearly above the music", source="feedback", by="Sam")
    d3 = os.path.join(pd, "out", "draft-3.mp4")
    mp4(d3, "testsrc", 4)
    F.add_draft(pd, d3, "Music ducked 4 dB under VO.")
    check_report(tmp, pd, 3)
    FC.look(pd, 3, "A")
    council_marks(pd, fails=("The first 3 seconds show the product's real result on screen, readable.",))
    co, re_ = round_files(tmp, pd, 2, "YES", 5)
    F.round_close(pd, co, re_)
    end_a, end_b = os.path.join(tmp, "end-a.png"), os.path.join(tmp, "end-b.png")
    still(end_a, "Acme Tasks · Wake up to merged PRs", (240, 214, 170))
    still(end_b, "Acme Tasks", (32, 36, 70))
    AB.add(pd, "Which end card?", end_a, end_b, "Warm dawn card", "Night card")
    AU.assume(pd, "Kept the calm piano track from the asset plan; say so to swap it", "08")
    twg_available(pd, artifacts=True, loom=True)
    uploaded(pd, "draft", 1, "artifacts")
    uploaded(pd, "draft", 2, "artifacts", edited=True)
    uploaded(pd, "draft", 2, "loom")
    snap("review")
    AU.start(pd, 60, "Sam")
    AU.begin(pd)
    snap("autopilot")
    AU.control(pd, "stop", "Sam")
    st_ = F.load(pd)
    st_.pop("autopilot")
    F.save(pd, st_)
    long = copy.deepcopy(out["review"])
    long["rounds"][0]["feedback"] += " " + "The pacing between the second and third scene still drags, and the caption sits too close to the bottom edge on a phone. " * 4
    long["rounds"][1]["research"] = ["https://example.com/a-really-long-path/that/keeps-going/and-going/and-going/for-a-while?x=1"] + long["rounds"][1]["research"] * 2
    long["scripts"] = [dict(s, title=s["title"] + " (extended director's cut with a very long working title)", logline=s["logline"] + " " + s["logline"]) for s in out["pick"]["scripts"]]
    long["boards"] = copy.deepcopy(out["storyboard"]["boards"])
    long["boards"][0]["scenes"][3]["action"] += " " + "The log keeps scrolling and the light keeps changing while nothing else moves in the frame. " * 3
    long["boards"][0]["scenes"][3]["proof"] = "Footage take 04, minutes 12 to 19 of the overnight run, " * 3
    long["assets"] = copy.deepcopy(out["assets"]["assets"])
    long["assets"][0]["id"] = "ui-ticket-list-with-a-very-long-descriptive-identifier-that-wraps"
    long["assets"][0]["how"] = "Full-resolution capture of the ticket list, " * 8
    long["summary"]["title"] = "Make a 60 second promo for Acme Tasks: tell it what you want at night, wake up to merged PRs"[:80]
    out["long-content"] = long
    many = copy.deepcopy(out["review"])
    clip1, clip2 = os.path.join(pd, "out", "draft-1.mp4"), os.path.join(pd, "out", "draft-2.mp4")
    many["pairs"] += [dict(id=f"p{n}", question=q, scene=None, media="video", left={"$file": clip1}, right={"$file": clip2}, answered=None) for n, q in
                      ((2, "Music test 1: which track under the same film feels better? (same voice, same cuts)"), (3, "Music test 2: which track under the same film feels better?"), (4, "Music test 3: which track under the same film feels better?"))]
    many["assumptions"] += [dict(id=f"a{n}", text=t, scene=None, overturned=None) for n, t in enumerate((
        "Shadows, rim light and glow are drawn around the app card (backdrop, halo, outline, reflection) and never over the app's own pixels, so the UI stays untouched (team rule 2); say so to swap it for something else",
        "A voice-over is added. For this sample it is a macOS system voice; the real voice is chosen at the assets step (licensed model). Lines only say what the footage shows; say so to cut the voice-over",
        "The build accelerates on purpose: shots go 5 s, 3 s, 2.5 s, 2 s, 1.5 s, 1 s, so the film speeds up toward the end card"), 2)]
    out["foryou-many"] = many
    for n in (3, 4, 5):
        F.round_start(pd, f"Round {n} feedback: tighten the end card.", by="Sam")
        FC.add(pd, f"The end card holds 3 seconds (round {n})", scene="08", source="feedback", by="Sam")
        dn = os.path.join(pd, "out", f"draft-{n + 1}.mp4")
        mp4(dn, "testsrc", 3)
        F.add_draft(pd, dn, f"Round {n} draft.")
        check_report(tmp, pd, n + 1)
        FC.look(pd, n + 1, "A")
        council_marks(pd, fails=("The first 3 seconds show the product's real result on screen, readable.",))
        co, re_ = round_files(tmp, pd, n, "YES")
        F.round_close(pd, co, re_)
    snap("review-maxed")
    F.approve(pd, "draft-approved", "Sam")
    F.advance(pd)
    fin = os.path.join(pd, "out", "acme-hero-1080.mp4")
    mp4(fin, "smptebars", 2, "1920x1080")
    F.add_final(pd, fin)
    uploaded(pd, "final", 1, "artifacts")
    snap("final")
    order = ["discover", "scripts", "pick", "storyboard", "storyboard-notes", "assets", "keyframes", "confirm", "drafts", "review", "autopilot", "final",
             "generating", "generating-stopped", "building", "storyboard-partial", "plan", "widgets", "dense", "assets-error", "stale-approval", "long-content", "foryou-many", "review-maxed"]
    res = {k: out[k] for k in order}
    res["starting"] = {}
    res.update(picker_states(tmp, pd))
    return res, tmp


if __name__ == "__main__":
    keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
    states, tmp = build(keep)
    if "--dump" in sys.argv:
        dd = sys.argv[sys.argv.index("--dump") + 1]
        os.makedirs(dd, exist_ok=True)
        for k, v in states.items():
            json.dump(v, open(os.path.join(dd, k + ".json"), "w"), indent=2)
    for k, v in states.items():
        sm = v.get("summary") or {}
        print(f"{k:<20} {sm.get('badge', '-'):<10} {sm.get('status', '')}")
    print(tmp)
