"""Canned promo-flow states for the mod harness: a believable flow project built in a temp dir (real PNG frames, WAV, MP4), driven through the real
`promo.flow` state machine, with `promo flow snapshot` captured at every stage. `build()` returns {name: snapshot} in display order.

    .venv/bin/python mod-dev/fixtures.py [--keep DIR] [--dump DIR]   print the stage list; keep the project in DIR; write <stage>.json snapshots (with `$file` paths) to DIR
"""
from __future__ import annotations

import copy
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from promo import assetplan as AP  # noqa: E402
from promo import brief as BR  # noqa: E402
from promo import flow as F  # noqa: E402
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


def round_files(tmp, pd, n, verdict, feedback_urls=3):
    sha = BR.intent_sha(BR.load(pd))
    co = os.path.join(tmp, f"co{n}.md")
    re_ = os.path.join(tmp, f"re{n}.md")
    write(co, f"intent-check: intent_sha={sha} verdict={verdict} intent=4 reference=3 lens=intent-reference\nThe cut keeps the calm night-to-dawn arc the request asked for.")
    urls = ["https://www.apple.com/newsroom/", "https://vimeo.com/staffpicks", "https://www.linear.app/changelog", "https://www.theverge.com/tech", "https://stripe.com/blog/engineering"]
    write(re_, "\n".join(urls[:max(feedback_urls, 3)]))
    return co, re_


def build(keep=None):
    tmp = keep or tempfile.mkdtemp(prefix="promo-flow-fixtures-")
    os.makedirs(tmp, exist_ok=True)
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
        write(sf, f"# {title}\n\n{logline}\n\n" + "\n".join(f"{i + 1}. {b}" for i, b in enumerate(BEATS[sid])) + "\n")
        F.add_script(pd, sid, title, logline, sf)
    snap("scripts")
    cf = os.path.join(tmp, "council.md")
    write(cf, "x" * 300)
    F.add_council(pd, "scripts", cf)
    F.advance(pd)
    snap("pick")
    F.approve(pd, "scripts-picked", "Sam", ["A", "B"])
    F.advance(pd)
    gen_boards(pd)
    snap("storyboard")
    frames = [os.path.join(pd, "flow", "boards", "A", "frames", f"{x}-end.png") for x in ("02", "05", "07")] + [os.path.join(pd, "flow", "boards", "B", "frames", "13-start.png")]
    for fp in frames:
        os.rename(fp, fp + ".bak")
    snap("storyboard-partial")
    for fp in frames:
        os.rename(fp + ".bak", fp)
    F.approve(pd, "storyboard-approved", "Sam")
    F.advance(pd)
    gen_assets(pd, "plan")
    snap("assets")
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
    F.approve(pd, "assets-approved", "Sam")
    F.advance(pd)
    snap("keyframes")
    gen_mids(pd)
    gen_assets(pd, "ready")
    F.approve(pd, "assets-approved", "Sam")
    F.advance(pd)
    snap("confirm")
    F.approve(pd, "final-confirmation", "Sam")
    F.advance(pd)
    for text, kind, done in [("Taking snapshots of the real app", "capture", True), ("Rendering screenshots for scene 2", "render", True), ("Rendering screenshots for scene 3", "render", True),
                             ("Designing the voice for the opening line", "voice", True), ("Cutting the music to 60 s on bar lines", "music", True),
                             ("Checking every cut lands on the beat", "check", True), ("Rendering scene 4 of 9", "render", False)]:
        F.note(pd, text, kind, done)
    snap("drafts")
    d1 = os.path.join(pd, "out", "draft-1.mp4")
    mp4(d1, "testsrc2", 4)
    F.add_draft(pd, d1, "First cut, 60 s, VO and music at rough levels.")
    F.advance(pd)
    F.round_start(pd, "The close up on the board is rough and the hook is slow. Can the first five seconds get to the typed sentence faster?")
    d2 = os.path.join(pd, "out", "draft-2.mp4")
    mp4(d2, "smptebars", 4)
    F.add_draft(pd, d2, "Hook shortened, board close-up re-framed.")
    co, re_ = round_files(tmp, pd, 1, "PARTIAL")
    F.round_close(pd, co, re_)
    F.round_start(pd, "Better. Music still feels too present under the voice.")
    d3 = os.path.join(pd, "out", "draft-3.mp4")
    mp4(d3, "testsrc", 4)
    F.add_draft(pd, d3, "Music ducked 4 dB under VO.")
    co, re_ = round_files(tmp, pd, 2, "YES", 5)
    F.round_close(pd, co, re_)
    twg_available(pd, artifacts=True, loom=True)
    uploaded(pd, "draft", 1, "artifacts")
    uploaded(pd, "draft", 2, "artifacts", edited=True)
    uploaded(pd, "draft", 2, "loom")
    snap("review")
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
    for n in (3, 4, 5):
        F.round_start(pd, f"Round {n} feedback: tighten the end card.")
        dn = os.path.join(pd, "out", f"draft-{n + 1}.mp4")
        mp4(dn, "testsrc", 3)
        F.add_draft(pd, dn, f"Round {n} draft.")
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
    order = ["discover", "scripts", "pick", "storyboard", "assets", "keyframes", "confirm", "drafts", "review", "final",
             "storyboard-partial", "assets-error", "stale-approval", "long-content", "review-maxed"]
    res = {k: out[k] for k in order}
    res["starting"] = {}
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
