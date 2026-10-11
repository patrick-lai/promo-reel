"""Concat per-shot segments (stream copy) + mux each mastered mix -> out/<name>-<tag><suffix>.mp4; EDL json + EDL.md.

Frame counts of every segment are asserted against the timeline before concat. Per-shot EDL entries are written by
`promo shot` next to each segment (segs/<id>.edl.json) and merged here into build/<WxH>/edl.json and out/EDL.md.
"""
from __future__ import annotations

import json
import os
import subprocess

from .mix import master_path


def count_frames(path):
    return int(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                                        "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path]).decode().strip())


def edl_json_path(spec):
    return os.path.join(spec.res_dir, "edl.json")


def build_edl(spec):
    edl = {}
    for s in spec.shots:
        p = os.path.join(spec.segs_dir, f"{s.id}.edl.json")
        e = json.load(open(p)) if os.path.exists(p) else {}
        edl[s.id] = dict(shot=s.id, beats=[s.b0, s.b1], t0=round(s.t0, 3), t1=round(s.t1, 3), frames=s.n, type=s.type, **e)
    with open(edl_json_path(spec), "w") as f:
        json.dump(edl, f, indent=1)
    os.makedirs(spec.out, exist_ok=True)
    rows = ["| # | Time (s) | Frames | Type | Source | In-out | Move | Caption |", "|---|---|---|---|---|---|---|---|"]
    for s in spec.shots:
        e = edl[s.id]
        rows.append(f"| {s.id} | {s.t0:.2f}-{s.t1:.2f} | {s.n} | {s.type} | {e.get('src', '')} | {e.get('inout', '')} | {e.get('move', '')} | {e.get('caption', '')} |")
    with open(os.path.join(spec.out, "EDL.md"), "w") as f:
        f.write(f"# {spec.title}: EDL ({spec.timeline.beats} beats at {spec.timeline.bpm} BPM, {spec.total_frames()} frames @ {spec.fps} fps)\n\n" + "\n".join(rows) + "\n")
    return edl


def fade_out_filter(duration, fade):
    """ffmpeg -vf value fading the picture to black over the last `fade` s of a `duration` s film (None for no fade)."""
    fade = float(fade or 0)
    if fade <= 0:
        return None
    fade = min(fade, duration)
    return f"fade=t=out:st={duration - fade:.3f}:d={fade:.3f}:color=black"


def fade_out_video(spec, vid):
    """`output.fade_out: <s>`: fade the picture to black over the last N seconds (the audio master has its own `mix.fade_out`).
    Re-encodes the concatenated video once (crf 14); without the option the segments stay a stream copy."""
    vf = fade_out_filter(spec.duration, (spec.raw.get("output") or {}).get("fade_out"))
    if not vf:
        return vid
    out = os.path.join(spec.segs_dir, "video-faded.mp4")
    subprocess.run(["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-threads", "2", "-i", vid, "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "14",
                    "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", "60", "-bf", "2", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", out], check=True)
    return out


WATERMARK = "TEST · 試作 · unlicensed audio · not for publication"


def watermark_png(spec, path, text=WATERMARK):
    """A small dark pill with the TEST line (Japanese-capable font), sized for the output scale."""
    from PIL import Image, ImageDraw, ImageFont
    K = spec.OW / 1920
    fp = next((p for p in ("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc",
                           "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc") if os.path.exists(p)), None)
    f = ImageFont.truetype(fp, int(22 * K)) if fp else ImageFont.load_default()
    x0, y0, x1, y1 = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=f)
    pad = int(10 * K)
    im = Image.new("RGBA", (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=int(8 * K), fill=(150, 20, 30, 210))
    d.text((pad - x0, pad - y0), text, font=f, fill=(255, 255, 255, 255))
    im.save(path)
    return path


def watermark_video(spec, vid):
    """Burn the TEST watermark into every frame (top-left, inside the frame) while a `test_only` asset is in the spec."""
    from . import assets as A
    tests = A.test_only_assets(spec)
    if not tests:
        return vid
    png = watermark_png(spec, os.path.join(spec.segs_dir, "watermark.png"))
    out = os.path.join(spec.segs_dir, "video-watermarked.mp4")
    m = int(24 * spec.OW / 1920)
    subprocess.run(["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-threads", "2", "-i", vid, "-i", png, "-filter_complex", f"[0:v][1:v]overlay={m}:{m}",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", "60", "-bf", "2",
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", out], check=True)
    print(f"watermarked (test-only assets: {', '.join(tests)})", flush=True)
    return out


def run(spec, force=False):
    os.makedirs(spec.out, exist_ok=True)
    lst = os.path.join(spec.segs_dir, "list.txt")
    with open(lst, "w") as f:
        for s in spec.shots:
            p = spec.seg_path(s.id)
            assert os.path.exists(p), f"segment missing: {p} (run `promo shot {s.id}`)"
            n = count_frames(p)
            assert n == s.n, (s.id, n, s.n)
            f.write(f"file '{p}'\n")
    vid = os.path.join(spec.segs_dir, "video-only.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "2", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", vid], check=True)
    vid = fade_out_video(spec, vid)
    vid = watermark_video(spec, vid)
    outs = []
    for m in spec.masters:
        wav = master_path(spec, m["name"])
        out = spec.output_path(m.get("suffix", ""))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "2", "-i", vid, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", str(m.get("aac_bitrate", "320k")), "-ar", "48000", "-ac", "2"]
                       # optional encoder low-pass: ffmpeg's native AAC at full bandwidth can overshoot true peak on hot masters
                       + (["-cutoff", str(int(m["aac_cutoff"]))] if m.get("aac_cutoff") else [])
                       + ["-t", f"{spec.duration}", "-movflags", "+faststart", out], check=True)
        print("wrote", out, flush=True)
        outs.append(out)
    build_edl(spec)
    return outs
