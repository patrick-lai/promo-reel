#!/usr/bin/env python3
"""Rebuilds the "v1-1080" section of footage/manifest.md from notes.json + ffprobe of <footage-dir>/*.mov, and writes <footage-dir>/manifest.md.

usage: mk_manifest.py [--footage-dir DIR] [--manifest-md FILE] [--notes FILE]
  --footage-dir  default $FOOTAGE_DIR, else <repo>/../videos/commission-ai-promo/footage/v1-1080
  --manifest-md  default <footage-dir>/../manifest.md
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capmeta  # noqa: E402

BEGIN, END = "<!-- v1-1080 BEGIN -->", "<!-- v1-1080 END -->"


def sha(f):
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def probe(f):
    o = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate,nb_frames", "-of", "csv=p=0", f]).decode().strip().split(",")
    return f"{o[0]}x{o[1]} @ {o[2].replace('/1', '')} fps, {o[3]} frames"


def dur(f):
    try:
        return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).decode().strip())
    except Exception:
        return None


def build(notes, fdir, probe=None, dur=None, sha=None):
    """Returns (section_lines, local_manifest_lines, n_rows). Clips whose .mov is missing are skipped. probe/dur/sha default to the ffprobe/hash helpers."""
    g = globals(); probe, dur, sha = probe or g["probe"], dur or g["dur"], sha or g["sha"]
    rows, full = [], []
    for n in notes["clips"]:
        f = f"{fdir}/{n['file']}.mov"
        if not os.path.exists(f):
            continue
        d = dur(f)
        ds = f"{d:.2f} s" if d is not None else "? s"
        commit = n.get("commit", capmeta.DEFAULT_COMMIT)
        cap = capmeta.capture_text(capmeta.clip_flags(n, fdir))
        full.append(f"### Shot {n['shot']}\n- **File:** `footage/v1-1080/{n['file']}.mov` (lossless H.264 yuv444p) + `{n['file']}-preview.mp4` + poster `{n['file']}-poster.png`\n- **sha256 (.mov):** `{sha(f)}`\n- **DPR:** {n.get('dpr', 1)}\n- **Duration:** {ds}; **video:** {probe(f)}\n- **URL / route:** {n['url']}\n- **Demo beat:** {n['beat']}\n- **Commit:** `{commit}` (main)\n- **Framing:** {n['framing']}\n- **Capture:** {cap}\n- **Notes / Zen checks:** {n['notes']}\n")
        rows.append(f"| {n['shot']} | `v1-1080/{n['file']}.mov` (+`-preview.mp4`, `-poster.png`) | {ds} | {n.get('dpr', 1)} | {n['url']} | {n['beat']} | `{commit[:8]}` | {n['framing']} | {cap} | {n['notes']} |")
    sec = [BEGIN, "## v1-1080 recapture (main 4a427fc0; shot-12 retake from main 4ccfa5be; 1920x1080 60 fps)", ""] + notes["header"] + ["",
           "| Shot | File | Duration | DPR | URL / route | Demo beat | Commit | Framing | Capture (injected CSS, cursor) | Notes / Zen checks |", "|---|---|---|---|---|---|---|---|---|---|"] + rows + [""] + notes.get("stills", []) + [""] + notes.get("footer", []) + [END, ""]
    loc = ["# commission-ai promo footage: v1-1080 recapture", ""] + notes["header"] + [""] + full + notes.get("stills", []) + [""] + notes.get("footer", [])
    return sec, loc, len(rows)


def splice(md, block):
    """Replace the v1-1080 block in manifest.md text (or prepend it)."""
    if BEGIN in md:
        return re.sub(re.escape(BEGIN) + r".*" + re.escape(END) + r"\n?", lambda _: block, md, flags=re.S)
    return block + "\n" + md


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--footage-dir")
    ap.add_argument("--manifest-md")
    ap.add_argument("--notes")
    a = ap.parse_args(argv)
    fdir = capmeta.footage_dir(a.footage_dir)
    md_path = a.manifest_md or os.path.join(os.path.dirname(fdir), "manifest.md")
    sec, loc, n = build(capmeta.load_notes(a.notes), fdir)
    md = open(md_path).read() if os.path.exists(md_path) else ""
    open(md_path, "w").write(splice(md, "\n".join(sec)))
    open(os.path.join(fdir, "manifest.md"), "w").write("\n".join(loc) + "\n")
    print("rows", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
