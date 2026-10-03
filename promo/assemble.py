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
