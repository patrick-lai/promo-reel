"""Concat per-shot segments (stream copy) + mux each mastered mix -> out/<name>-<tag><suffix>.mp4; EDL json + EDL.md.

Frame counts of every segment are asserted against the timeline before concat. Per-shot EDL entries are written by
`promo shot` next to each segment (segs/<id>.edl.json) and merged here into build/<WxH>/edl.json and out/EDL.md.

Dissolves (`cut_in: dissolve` or `{kind: dissolve, dur: S}` on the shot after the cut) are blended here, in the one delivery
encode, so every segment keeps its frames, the cut stays on the beat and no shot re-renders. The window is centred on the cut:
the outgoing side blends towards the next shot's first frame, the incoming side from the last frame before the cut (the
segments have no handles to run on). Allowed per style in `transitions.allowed`; promo check gates it (`cut-in`).
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess

import numpy as np

from .mix import master_path
from .spec import cuts


def dissolve(frames, cut_list, size):
    """The film's yuv420p frames (bytes of `size`, in order) with every dissolve window blended. Linear in Y'CbCr, the same mix as in
    R'G'B'. Weights run (j + 1) / (n + 1) across the n-frame window, so neither end repeats a source frame."""
    before, into = {}, {}
    for c in cut_list:
        n = c["a"] + c["b"]
        for j in range(c["a"]):
            before[c["frame"] - c["a"] + j] = (j + 1) / (n + 1)
        for j in range(c["b"]):
            into[c["frame"] + j] = (c["a"] + j + 1) / (n + 1)
    mix = lambda x, y, p: np.rint(np.frombuffer(x, np.uint8) * (1 - p) + np.frombuffer(y, np.uint8) * p).astype(np.uint8).tobytes()
    waiting, held, prev = [], None, None
    for i, f in enumerate(frames):
        assert len(f) == size, (i, len(f), size)
        if i in before:
            waiting.append((f, before[i]))         # blended once the next shot's first frame arrives
        else:
            if waiting:
                yield from (mix(x, f, p) for x, p in waiting)
                waiting, held = [], prev
            yield mix(held, f, into[i]) if i in into else f
        prev = f
    if waiting:
        raise RuntimeError(f"the film ended {len(waiting)} frame(s) before a dissolve's cut: the segments decoded short")


def count_frames(path):
    return int(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                                        "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path]).decode().strip())


def edl_json_path(spec):
    return os.path.join(spec.res_dir, "edl.json")


def build_edl(spec):
    edl = {}
    into = {c["shot"]: c["a"] + c["b"] for c in cuts(spec)}
    for s in spec.shots:
        p = os.path.join(spec.segs_dir, f"{s.id}.edl.json")
        e = json.load(open(p)) if os.path.exists(p) else {}
        edl[s.id] = dict(shot=s.id, beats=[s.b0, s.b1], t0=round(s.t0, 3), t1=round(s.t1, 3), frames=s.n, type=s.type, **e)
        if s.id in into:
            edl[s.id]["dissolve_in_frames"] = into[s.id]
    with open(edl_json_path(spec), "w") as f:
        json.dump(edl, f, indent=1)
    os.makedirs(spec.out, exist_ok=True)
    rows = ["| # | Time (s) | Frames | Type | Source | In-out | Move | Caption |", "|---|---|---|---|---|---|---|---|"]
    for s in spec.shots:
        e = edl[s.id]
        typ = s.type + (f" (dissolve in, {into[s.id]} frames)" if s.id in into else "")
        rows.append(f"| {s.id} | {s.t0:.2f}-{s.t1:.2f} | {s.n} | {typ} | {e.get('src', '')} | {e.get('inout', '')} | {e.get('move', '')} | {e.get('caption', '')} |")
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


DELIVERY_CRF = 23          # the masters people watch and drafts are cloned from: ~15x smaller than the crf 16 segments, no visible loss


def final_video(spec, vid, watermark=False, cut_list=()):
    """The delivered picture: the stream-copied segments encoded ONCE (H.264, `output.crf`, default 23), with the dissolves (`cut_list`),
    the TEST watermark (`watermark`: a `test_only` asset is in the mix) and `output.fade_out` in the same pass. The crf 16 segments stay
    the editing source. With dissolves the frames pass through Python by index: concatenated segments drift off N/fps timestamps."""
    out_cfg = spec.raw.get("output") or {}
    inputs, chain, label = ["-i", vid], [], "[0:v]"
    if cut_list:
        size = spec.OW * spec.OH * 3 // 2
        inputs =["-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{spec.OW}x{spec.OH}", "-r", str(spec.fps), "-i", "-"]
        chain.append("[0:v]setparams=range=tv:colorspace=bt709[raw]")      # the segments' tags, so nothing converts the pixels
        label = "[raw]"
    if watermark:
        png = watermark_png(spec, os.path.join(spec.segs_dir, "watermark.png"))
        m = int(24 * spec.OW / 1920)
        inputs += ["-i", png]
        chain.append(f"{label}[1:v]overlay={m}:{m}[wm]")
        label = "[wm]"
    fade = fade_out_filter(spec.duration, out_cfg.get("fade_out"))
    chain.append(f"{label}{fade or 'null'}[v]")
    out = os.path.join(spec.segs_dir, "video-final.mp4")
    cmd = ["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-threads", "2", *inputs, "-filter_complex", ";".join(chain), "-map", "[v]",
           "-c:v", "libx264", "-preset", "slow", "-crf", str(out_cfg.get("crf", DELIVERY_CRF)), "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-g", "60", "-bf", "2", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", out]
    if not cut_list:
        subprocess.run(cmd, check=True)
        return out
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-threads", "2", "-i", vid, "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    frames = iter(lambda: dec.stdout.read(size), b"")
    try:
        for f in dissolve(frames, cut_list, size):
            enc.stdin.write(f)
    finally:
        for pipe in (enc.stdin, dec.stdout):
            with contextlib.suppress(BrokenPipeError):         # an encoder that died is reported by its exit code below
                pipe.close()
        codes = dec.wait(), enc.wait()
    if any(codes):
        raise subprocess.CalledProcessError(codes[1] or codes[0], "ffmpeg " + ("encode" if codes[1] else "decode") + " (dissolve pass)")
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
    from . import assets as A
    tests = A.test_only_assets(spec)
    concat, vid = vid, final_video(spec, vid, watermark=bool(tests), cut_list=cuts(spec))
    if tests:
        print(f"watermarked (test-only assets: {', '.join(tests)})", flush=True)
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
    for f in (concat, vid):              # full-size intermediates: the segments and the masters are what is kept
        os.remove(f)
    build_edl(spec)
    return outs
