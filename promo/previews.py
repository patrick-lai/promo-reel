"""Real previews for the flow: the agent MAKES every storyboard frame and a sample of every planned asset, so the person can look at it and listen
to it before approving. A placeholder (a text slate, a striped MOCK tile) is not a preview.

    frames   `make_frames`   each START / END / mid frame of a board, generated as an image from its prompt (grok or codex CLI, `promo gen detect`)
    samples  `make_samples`  per planned asset, a lower-resolution or shorter stand-in of what it will be:
               screenshot / image   a generated concept still of the planned picture
               recording / video    a ~7 s silent clip that crossfades start -> end through the storyboard stills of the scenes using it
               music                a 20 s excerpt of the licensed track (`path`, or downloaded from `fetch_url`, sha256-checked)
               voice                the first lines of the covered scenes read by the macOS system voice
               sfx                  the planned hits, synthesised by `promo sfx`

A sample never replaces the asset: `flow/samples.json` records it ({asset id: {path, note, at}}), the asset keeps its state (mock / to make) and the
mod labels it as a sample. Frames and samples are planning material, not footage: they never enter the footage manifest.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import genvideo as G
from . import storyboard as SB

VOICES = ("Flo (English (UK))", "Samantha")
CLIP_SIZE = (960, 540)
CLIP_FPS = 24
CLIP_SCENES = 3
SCENE_SECONDS = 2.4
MUSIC_SECONDS = 20
SFX_DEFAULT = ("tick", "tick2", "click")
SFX_WORDS = ("tick", "click", "whoosh", "chime", "swell", "impact", "riser", "key")
LOGO_KEEP = 0.92        # a generator's corner logo sits in the bottom-right ~8%: keep the rest
FRAME_SIZE = (1280, 720)


class PreviewError(Exception):
    """Something a preview needs is missing; the message says what to do."""


def samples_path(flow_dir):
    return os.path.join(flow_dir, "samples.json")


def load_samples(flow_dir):
    try:
        return json.load(open(samples_path(flow_dir)))
    except (OSError, ValueError):
        return {}


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode:
        raise PreviewError(f"ffmpeg failed: {r.stderr.strip()[-300:]}")


# ---------------------------------------------------------------- storyboard frames
def frame_prompt(board, scene, label, frame, look):
    parts = [frame.get("prompt") or f"{label} of the scene", f"Scene {scene['id']} ({scene.get('beat', '')}): {scene.get('action', '')}",
             f"Frame: {board.get('aspect', '16:9')}." + (f" Look: {look}." if look else "")]
    return " ".join(p for p in parts if p)


def _crop_logo(path, size):
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        im = im.crop((0, 0, round(im.width * LOGO_KEEP), round(im.height * LOGO_KEEP)))
        im.resize(size, Image.LANCZOS).save(path, "PNG")


def _make_one(prompt, final, provider, size=FRAME_SIZE):
    """Generate beside `final` first: an old slate at `final` must never be mistaken for the generator's output."""
    tmp = os.path.join(os.path.dirname(final), "." + os.path.basename(final) + ".new.png")
    meta = G.generate("image", prompt, tmp, provider=provider, guard=G.STORYBOARD)
    if meta["provider"] == "grok":
        _crop_logo(tmp, size)
    os.replace(tmp, final)
    os.remove(tmp + ".gen.json")
    meta = {k: meta[k] for k in ("provider", "prompt", "at") if k in meta}
    with open(final + ".gen.json", "w") as f:
        json.dump(dict(meta, storyboard=True, note="storyboard still, not footage"), f, indent=1)


def frame_targets(bds, scene=None, which=("start", "end"), force=False):
    """[(label, board, scene, frame, path)] for frames that are not real images yet (all of them with force)."""
    out = []
    for sid, b, d in bds:
        for s in b.get("scenes") or []:
            if scene and s.get("id") != scene:
                continue
            for w, f in SB._frames(s, which):
                if f.get("image"):
                    p = os.path.join(d, f["image"])
                    if force or not os.path.isfile(p) or SB.is_slate(p):
                        out.append((f"{sid}/{s['id']}/{w}", b, s, f, p))
    return out


def make_frames(bds, look="", scene=None, which=("start", "end"), force=False, provider="auto", jobs=3, limit=None, say=print):
    """Generate the missing frames in parallel. Returns (made, failed): the labels, and [(label, reason)] for the ones a provider could not make."""
    todo = frame_targets(bds, scene, which, force)[:limit]
    made, failed = [], []

    def run(t):
        label, b, s, f, p = t
        try:
            _make_one(frame_prompt(b, s, label.rsplit("/", 1)[1], f, look), p, provider)
        except (RuntimeError, OSError) as e:
            return label, str(e)
        return label, None

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for label, err in ex.map(run, todo):
            (failed.append((label, err)) if err else made.append(label))
            say(f"  {'FAILED' if err else 'made  '} frame {label}" + (f": {err[:160]}" if err else ""))
    return made, failed


# ---------------------------------------------------------------- asset samples
def has_sample(a, pd, samples):
    """An asset the person can already open or play: its real file, or its sample."""
    s = samples.get(a["id"])
    return any(p and os.path.isfile(os.path.join(pd, p)) for p in (a.get("path"), s and s.get("path")))


def _scene_frames(bds, a):
    """[(scene, start path, end path)] for the scenes this asset covers, whose frames are real images."""
    want = set(a.get("scenes") or [])
    out = []
    for _, b, d in bds:
        for s in b.get("scenes") or []:
            if s["id"] in want:
                ps = [os.path.join(d, (s.get(w) or {}).get("image", "")) for w in ("start", "end")]
                if all(os.path.isfile(p) and not SB.is_slate(p) for p in ps):
                    out.append((s, *ps))
    return out


def _spread(xs, n):
    return xs if len(xs) <= n else [xs[round(i * (len(xs) - 1) / (n - 1))] for i in range(n)]


def _label_font(size):
    from PIL import ImageFont
    for p in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf", "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.isfile(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def _clip(a, bds, out):
    from PIL import Image, ImageDraw
    pairs = _spread(_scene_frames(bds, a), CLIP_SCENES)
    if not pairs:
        raise PreviewError(f"{a['id']}: no real storyboard frame for scenes {', '.join(a.get('scenes') or [])} yet; run `promo flow frames` first")
    W, H = CLIP_SIZE
    font = _label_font(15)
    n = round(SCENE_SECONDS * CLIP_FPS)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(CLIP_FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for s, p0, p1 in pairs:
            ims = [Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS) for p in (p0, p1)]
            note = f"SAMPLE  storyboard stills, not footage  ·  scene {s['id']} {s.get('beat', '')}"
            for i in range(n):
                t = i / (n - 1)
                mix = min(1.0, max(0.0, (t - 0.4) / 0.2))      # hold START, a quick dissolve, hold END: a long half-blend of two different stills is mud
                mix = mix * mix * (3 - 2 * mix)
                zoom = 1 + 0.05 * t
                cw, ch = round(W / zoom), round(H / zoom)
                x0, y0 = (W - cw) // 2, (H - ch) // 2
                fr = Image.blend(ims[0], ims[1], mix).crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR)
                d = ImageDraw.Draw(fr, "RGBA")
                w = d.textlength(note, font=font)
                d.rounded_rectangle((12, H - 40, 12 + w + 20, H - 12), 6, fill=(0, 0, 0, 170))
                d.text((22, H - 36), note, font=font, fill=(255, 255, 255, 235))
                enc.stdin.write(fr.tobytes())
        enc.stdin.close()
        if enc.wait():
            raise PreviewError("ffmpeg could not encode the clip: " + enc.stderr.read().decode()[-300:])
    finally:
        if enc.poll() is None:
            enc.kill()
    return "Storyboard stills played as a clip. Not footage."


def _image(a, bds, out, provider):
    scenes = ", ".join(f"{s['beat']}: {s.get('action', '')}" for _, b, _ in bds for s in b.get("scenes") or [] if s["id"] in (a.get("scenes") or []))[:400]
    _make_one(f"{a.get('how', '')} Used in: {scenes}", out, provider)
    return "Generated concept still. Not the final."


def _download(url, dest, sha):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "promo-reel"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    got = hashlib.sha256(open(dest, "rb").read()).hexdigest()
    if sha and got != sha:
        os.remove(dest)
        raise PreviewError(f"downloaded file does not match sha256 {sha[:12]}… (got {got[:12]}…)")


def _music(a, pd, out):
    src = os.path.join(pd, a["path"]) if a.get("path") else ""
    if not os.path.isfile(src):
        if not a.get("fetch_url"):
            raise PreviewError(f"{a['id']}: no track to cut a sample from; add `--path FILE` or `--fetch-url URL [--sha256 H]` (licensed downloads only)")
        src = os.path.join(pd, "media", "music", a["id"] + ".mp3")
        if not os.path.isfile(src):
            _download(a["fetch_url"], src, a.get("sha256"))
    _ffmpeg("-i", src, "-t", str(MUSIC_SECONDS), "-af", f"afade=t=in:d=0.6,afade=t=out:st={MUSIC_SECONDS - 1.5}:d=1.5", "-ac", "2", "-b:a", "128k", out)
    return f"First {MUSIC_SECONDS} s of the licensed track."


def _voice(a, bds, out):
    lines = [s["vo"] for _, b, _ in bds for s in b.get("scenes") or [] if s["id"] in (a.get("scenes") or []) and s.get("vo")][:3]
    if not lines:
        raise PreviewError(f"{a['id']}: none of its scenes has a voice line (`vo`) to read")
    if not shutil.which("say"):
        raise PreviewError(f"{a['id']}: no text-to-speech here to read a sample (macOS `say`); render it with `promo vo` instead")
    have = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    voice = next((v for v in VOICES if re.search(rf"^{re.escape(v)}\s", have, re.M)), None)
    with tempfile.TemporaryDirectory() as tmp:
        aiff = os.path.join(tmp, "v.aiff")
        subprocess.run(["say", *(["-v", voice] if voice else []), "-o", aiff, " ... ".join(lines)], check=True)
        _ffmpeg("-i", aiff, "-ac", "1", "-b:a", "96k", out)
    return f"First {len(lines)} script line{'s' if len(lines) > 1 else ''} read by the macOS voice {voice or 'default'}. The planned voice is made at build."


def _sfx(a, out):
    import numpy as np
    import soundfile as sf
    from . import sfx
    lib = sfx.synthesise()
    names = [w for w in SFX_WORDS if re.search(w, a.get("how", ""), re.I)]
    names = [n for w in names for n in sorted(k for k in lib if k.startswith(w))][:4] or list(SFX_DEFAULT)
    buf = np.zeros((int(sfx.SR * (0.5 + 0.7 * len(names))), 2))
    for i, n in enumerate(names):
        o = int(sfx.SR * (0.2 + 0.7 * i))
        buf[o:o + len(lib[n])] += lib[n][:len(buf) - o]
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "s.wav")
        sf.write(wav, buf / max(1.0, np.abs(buf).max()), sfx.SR)
        _ffmpeg("-i", wav, "-b:a", "128k", out)
    return f"The planned sounds ({', '.join(names)}), played in a row."


EXT = {"screenshot": ".png", "image": ".png", "recording": ".mp4", "video": ".mp4", "music": ".mp3", "voice": ".mp3", "sfx": ".mp3"}


def make_sample(a, pd, bds, provider="auto"):
    """Make one asset's sample; returns {path, note, at}. Raises PreviewError (or RuntimeError from a provider) when it cannot."""
    rel = os.path.join("flow", "previews", a["id"] + EXT[a["kind"]])
    out = os.path.join(pd, rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    k = a["kind"]
    note = (_clip(a, bds, out) if k in ("recording", "video") else _image(a, bds, out, provider) if k in ("screenshot", "image")
            else _music(a, pd, out) if k == "music" else _voice(a, bds, out) if k == "voice" else _sfx(a, out))
    return dict(path=rel, note=note, at=_now())


def make_samples(plan, pd, bds, ids=None, force=False, provider="auto", say=print):
    """Make the missing samples (all with force). Returns (made, failed) like make_frames; writes flow/samples.json."""
    flow_dir = os.path.join(pd, "flow")
    samples = load_samples(flow_dir)
    made, failed = [], []
    for a in plan:
        if (ids and a["id"] not in ids) or (not force and has_sample(a, pd, samples)):
            continue
        try:
            samples[a["id"]] = make_sample(a, pd, bds, provider)
        except (PreviewError, RuntimeError, OSError, subprocess.CalledProcessError) as e:
            failed.append((a["id"], str(e)))
            say(f"  FAILED sample {a['id']}: {str(e)[:200]}")
        else:
            made.append(a["id"])
            say(f"  made   sample {a['id']} -> {samples[a['id']]['path']}")
            with open(samples_path(flow_dir), "w") as f:
                json.dump(samples, f, indent=2)
    return made, failed
