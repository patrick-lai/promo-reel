"""`promo watch`: turn a video (file or URL) into something an agent can actually "watch".

Outputs in <out>/ (default build/watch/<id>/):
  video.mp4 / info.json     downloaded source (URLs go through yt-dlp)
  sheets/sheet-NN.png       time-stamped contact sheets, uniform sampling (read these first)
  cuts/cut-NNN.jpg          one still per detected cut (just after the cut), full 960 px wide
  audio.wav, transcript.json  16 kHz mono audio and word-timed transcript (faster-whisper or whisper CLI, if installed)
  watch.json                machine-readable report: cuts, shot lengths, cut-rate curve, loudness, tempo, onsets, palette
  WATCH.md                  human/agent summary: shot table with transcript lines and the cut-rate curve

Nothing here judges taste. It gives a reviewer (human or model) frames, timing and words to look at.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def find_ytdlp() -> list[str] | None:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    cand = Path.home() / ".promo-tools" / "venv" / "bin" / "yt-dlp"
    if cand.exists():
        return [str(cand)]
    r = _run([sys.executable, "-m", "yt_dlp", "--version"])
    return [sys.executable, "-m", "yt_dlp"] if r.returncode == 0 else None


def fetch(url: str, out: Path, height: int = 1080) -> Path:
    yt = find_ytdlp()
    if not yt:
        raise SystemExit("yt-dlp not found: `uv venv ~/.promo-tools/venv && uv pip install --python ~/.promo-tools/venv/bin/python yt-dlp`")
    out.mkdir(parents=True, exist_ok=True)
    dst = out / "video.mp4"
    if not dst.exists():
        cmd = yt + ["-f", f"bv*[height<={height}]+ba/b[height<={height}]", "--merge-output-format", "mp4",
                    "--write-info-json", "--no-playlist", "-o", str(out / "video.%(ext)s"), url]
        r = subprocess.run(cmd)
        if r.returncode:
            raise SystemExit(f"yt-dlp failed for {url}")
        info = out / "video.info.json"
        if info.exists():
            info.rename(out / "info.json")
    return dst


def probe(path: Path) -> dict:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,duration:format=duration",
              "-of", "json", str(path)])
    j = json.loads(r.stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    n, d = v["r_frame_rate"].split("/")
    return {"width": v["width"], "height": v["height"], "fps": float(n) / float(d),
            "duration": float(j["format"]["duration"]), "audio": any(s["codec_type"] == "audio" for s in j["streams"])}


def detect_cuts(path: Path, thresh: float = 0.28, min_gap: float = 0.25) -> list[float]:
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf", f"select='gt(scene,{thresh})',showinfo",
              "-an", "-f", "null", "-"])
    ts = [float(m.group(1)) for m in re.finditer(r"pts_time:([0-9.]+)", r.stderr)]
    out: list[float] = []
    for t in ts:
        if not out or t - out[-1] >= min_gap:
            out.append(round(t, 3))
    return out


def grab(path: Path, t: float, dst: Path, width: int = 960) -> bool:
    r = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(t, 0):.3f}", "-i", str(path),
              "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(dst)])
    return r.returncode == 0 and dst.exists()


def _font(size: int):
    for p in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def dump_frames(path: Path, out: Path, fps: float, width: int = 960) -> list[tuple[float, Path]]:
    """ONE ffmpeg pass: every 1/fps seconds at `width` px. Per-frame ffmpeg spawns are far too slow on a busy box."""
    d = out / "_frames"
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.jpg"):
        f.unlink()
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-an", "-vf", f"fps={fps},scale={width}:-2",
          "-q:v", "3", "-start_number", "0", str(d / "%05d.jpg")])
    return [(round(i / fps, 3), f) for i, f in enumerate(sorted(d.glob("*.jpg")))]


def nearest(frames: list[tuple[float, Path]], t: float) -> Path:
    return min(frames, key=lambda tf: abs(tf[0] - t))[1]


def contact_sheets(frames: list[tuple[float, Path]], out: Path, dur: float, per_sheet: int = 20, cols: int = 4,
                   thumb_w: int = 480) -> list[str]:
    """Uniform sampling, labelled with timestamps (~80 frames max over the whole video)."""
    out.mkdir(parents=True, exist_ok=True)
    step = max(0.5, dur / 80)
    picks, last = [], -1e9
    for t, f in frames:
        if t - last >= step - 1e-6:
            picks.append((t, f))
            last = t
    paths = []
    font = _font(15)
    for k in range(0, len(picks), per_sheet):
        ims = []
        for t, f in picks[k:k + per_sheet]:
            im = Image.open(f)
            im = im.resize((thumb_w, round(im.height * thumb_w / im.width)))
            ims.append((t, im))
        w, h = ims[0][1].size
        rows = (len(ims) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * w, rows * h), (12, 12, 14))
        dr = ImageDraw.Draw(sheet)
        for j, (t, im) in enumerate(ims):
            x, y = (j % cols) * w, (j // cols) * h
            sheet.paste(im, (x, y))
            dr.rectangle([x, y, x + 78, y + 20], fill=(0, 0, 0))
            dr.text((x + 4, y + 2), f"{t:6.2f}s", fill=(255, 255, 255), font=font)
        p = out / f"sheet-{k // per_sheet + 1:02d}.png"
        sheet.save(p)
        paths.append(str(p))
    return paths


def extract_audio(path: Path, wav: Path) -> bool:
    r = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    return r.returncode == 0 and wav.exists() and wav.stat().st_size > 1000


def transcribe(wav: Path) -> dict | None:
    try:
        from faster_whisper import WhisperModel
        m = WhisperModel("small.en", device="cpu", compute_type="int8")
        segs, _ = m.transcribe(str(wav), word_timestamps=True, vad_filter=True)
        out = []
        for s in segs:
            out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                        "words": [{"w": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)} for w in (s.words or [])]})
        return {"engine": "faster-whisper small.en", "segments": out}
    except Exception:
        pass
    exe = shutil.which("whisper")
    if exe:
        d = wav.parent / "_whisper"
        d.mkdir(exist_ok=True)
        r = _run([exe, str(wav), "--model", "small.en", "--language", "en", "--output_format", "json", "--output_dir", str(d),
                  "--word_timestamps", "True"])
        j = d / (wav.stem + ".json")
        if r.returncode == 0 and j.exists():
            data = json.loads(j.read_text())
            segs = [{"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip(),
                     "words": [{"w": w["word"].strip(), "start": round(w["start"], 2), "end": round(w["end"], 2)} for w in s.get("words", [])]}
                    for s in data["segments"]]
            return {"engine": "whisper-cli small.en", "segments": segs}
    return None


def audio_metrics(wav: Path) -> dict:
    import soundfile as sf
    y, sr = sf.read(str(wav), dtype="float32")
    m: dict = {"duration": round(len(y) / sr, 2)}
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(sr)
        m["lufs_integrated"] = round(float(meter.integrated_loudness(y)), 1)
    except Exception:
        pass
    m["peak_dbfs"] = round(float(20 * np.log10(max(np.abs(y).max(), 1e-9))), 1)
    # short-term loudness curve per 2 s (RMS dBFS): shows build / drop shape
    hop = int(2 * sr)
    m["rms_curve_2s"] = [round(float(20 * np.log10(max(np.sqrt(np.mean(y[i:i + hop] ** 2)), 1e-9))), 1) for i in range(0, len(y), hop)]
    try:
        import librosa
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        m["tempo_bpm"] = round(float(np.atleast_1d(tempo)[0]), 1)
        on = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=False)
        m["onsets"] = [round(float(t), 2) for t in on][:400]
        m["beats"] = [round(float(t), 2) for t in librosa.frames_to_time(beats, sr=sr)][:400]
    except Exception:
        pass
    return m


def palette(im_path: Path, k: int = 4) -> list[str]:
    im = Image.open(im_path).convert("RGB").resize((64, 36))
    q = im.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:k * 3]
    counts = sorted(q.getcolors(), reverse=True)
    return ["#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]) for _, i in counts[:k]]


def motion_energy(path: Path, dur: float, fps: float = 4.0) -> list[float]:
    """Mean abs frame difference at low res, per second: camera / graphic activity curve (0..1)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-an", "-vf", f"fps={fps},scale=96:54,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, np.uint8)
    n = len(a) // (96 * 54)
    if n < 2:
        return []
    f = a[: n * 96 * 54].reshape(n, 54 * 96).astype(np.float32)
    d = np.abs(np.diff(f, axis=0)).mean(axis=1) / 255.0
    per = int(fps)
    return [round(float(d[i:i + per].mean()), 4) for i in range(0, len(d), per)]


def build_report(path: Path, out: Path, thresh: float = 0.28) -> dict:
    info = probe(path)
    dur = info["duration"]
    cuts = detect_cuts(path, thresh)
    bounds = [0.0] + cuts + [dur]
    shots = [{"i": i + 1, "t0": round(a, 2), "t1": round(b, 2), "len": round(b - a, 2)} for i, (a, b) in enumerate(zip(bounds, bounds[1:]))]
    frames = dump_frames(path, out, fps=6 if dur <= 40 else 3 if dur <= 200 else 1)
    cdir = out / "cuts"
    cdir.mkdir(parents=True, exist_ok=True)
    for s in shots:
        p = cdir / f"cut-{s['i']:03d}.jpg"
        shutil.copyfile(nearest(frames, min(s["t0"] + min(0.2, s["len"] / 2), dur - 0.05)), p)
        s["still"] = str(p.relative_to(out))
        s["palette"] = palette(p)
    sheets = contact_sheets(frames, out / "sheets", dur)
    shutil.rmtree(out / "_frames", ignore_errors=True)
    rep: dict = {"source": str(path), **info, "n_cuts": len(cuts), "cuts": cuts, "shots": shots,
                 "sheets": [str(Path(p).relative_to(out)) for p in sheets]}
    lens = [s["len"] for s in shots]
    rep["shot_len"] = {"mean": round(float(np.mean(lens)), 2), "median": round(float(np.median(lens)), 2),
                       "min": min(lens), "max": max(lens), "cuts_per_s": round(len(cuts) / dur, 3)}
    q = 5
    edges = np.linspace(0, dur, q + 1)
    rep["cut_rate_curve"] = [round(sum(1 for c in cuts if a <= c < b) / (b - a), 2) for a, b in zip(edges, edges[1:])]
    rep["motion_per_s"] = motion_energy(path, dur)
    if info["audio"]:
        wav = out / "audio.wav"
        if extract_audio(path, wav):
            try:
                rep["audio_metrics"] = audio_metrics(wav)
            except Exception as e:      # soundfile / librosa missing (system python): frames and cuts are still useful
                rep["audio_metrics_error"] = str(e)
            tr = transcribe(wav) if os.environ.get("PROMO_WATCH_ASR", "1") != "0" else None
            if tr:
                rep["transcript"] = tr
                (out / "transcript.json").write_text(json.dumps(tr, indent=1))
    (out / "watch.json").write_text(json.dumps(rep, indent=1))
    (out / "WATCH.md").write_text(render_md(rep))
    return rep


def render_md(rep: dict) -> str:
    L = [f"# WATCH: {Path(rep['source']).parent.name}", "",
         f"{rep['width']}x{rep['height']} @ {rep['fps']:.2f} fps, {rep['duration']:.1f} s, {rep['n_cuts']} cuts "
         f"({rep['shot_len']['cuts_per_s']} cuts/s; shot length mean {rep['shot_len']['mean']} s, median {rep['shot_len']['median']} s, "
         f"min {rep['shot_len']['min']}, max {rep['shot_len']['max']})", "",
         f"Cut rate by fifth of runtime (cuts/s): {rep['cut_rate_curve']}", ""]
    am = rep.get("audio_metrics")
    if am:
        L += [f"Audio: {am.get('lufs_integrated', '?')} LUFS, peak {am['peak_dbfs']} dBFS, tempo ~{am.get('tempo_bpm', '?')} BPM "
              f"(librosa guess; confirm by ear), RMS per 2 s: {am['rms_curve_2s']}", ""]
    L += ["Contact sheets (read first): " + ", ".join(rep["sheets"]), ""]
    segs = rep.get("transcript", {}).get("segments", [])
    L += ["## Shots", "", "| # | t0 | len | palette | still | words in shot |", "|---|---|---|---|---|---|"]
    for s in rep["shots"]:
        words = " ".join(w["w"] for sg in segs for w in sg["words"] if s["t0"] <= w["start"] < s["t1"]) or " ".join(
            sg["text"] for sg in segs if s["t0"] <= sg["start"] < s["t1"])
        L.append(f"| {s['i']} | {s['t0']} | {s['len']} | {' '.join(s.get('palette', []))} | {s['still']} | {words[:140]} |")
    if segs:
        L += ["", "## Transcript", ""] + [f"- [{sg['start']:.1f}-{sg['end']:.1f}] {sg['text']}" for sg in segs]
    return "\n".join(L) + "\n"


def run(src: str, out: str | None = None, thresh: float = 0.28) -> dict:
    if re.match(r"https?://", src):
        vid = re.search(r"(?:v=|youtu\.be/)([\w-]{6,})", src)
        name = vid.group(1) if vid else re.sub(r"\W+", "_", src)[-24:]
        od = Path(out or f"build/watch/{name}")
        path = fetch(src, od)
    else:
        path = Path(src).resolve()
        od = Path(out or f"build/watch/{path.stem}")
    od.mkdir(parents=True, exist_ok=True)
    rep = build_report(path, od, thresh)
    rep["out"] = str(od)
    return rep
