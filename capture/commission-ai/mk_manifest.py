#!/usr/bin/env python3
# Rebuilds the "v1-1080" section of footage/manifest.md from notes.json + ffprobe durations of footage/v1-1080/*.mov
import json, subprocess, os, re
FOOT = "/workspace/videos/commission-ai-promo/footage"
D = f"{FOOT}/v1-1080"
notes = json.load(open(os.path.join(os.path.dirname(__file__), "notes.json")))
import hashlib
def sha(f):
    h=hashlib.sha256()
    with open(f,'rb') as fh:
        for b in iter(lambda: fh.read(1<<20), b''): h.update(b)
    return h.hexdigest()
def probe(f):
    o=subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=width,height,r_frame_rate,nb_frames","-of","csv=p=0",f]).decode().strip().split(",")
    return f"{o[0]}x{o[1]} @ {o[2].replace('/1','')} fps, {o[3]} frames"
def dur(f):
    try: return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).decode().strip())
    except Exception: return None
rows = []; full = []
for n in notes["clips"]:
    f = f"{D}/{n['file']}.mov"
    if not os.path.exists(f): continue
    d = dur(f)
    full.append(f"### Shot {n['shot']}\n- **File:** `footage/v1-1080/{n['file']}.mov` (lossless H.264 yuv444p) + `{n['file']}-preview.mp4` + poster `{n['file']}-poster.png`\n- **sha256 (.mov):** `{sha(f)}`\n- **DPR:** {n.get('dpr',1)}\n- **Duration:** {d:.2f} s; **video:** {probe(f)}\n- **URL / route:** {n['url']}\n- **Demo beat:** {n['beat']}\n- **Commit:** `{n.get('commit','4a427fc05f829d7b2e4ed7ea642d77340554f7f8')}` (main)\n- **Framing:** {n['framing']}\n- **Notes / Zen checks:** {n['notes']}\n")
    rows.append(f"| {n['shot']} | `v1-1080/{n['file']}.mov` (+`-preview.mp4`, `-poster.png`) | {d:.2f} s | {n.get('dpr',1)} | {n['url']} | {n['beat']} | `{n.get('commit','4a427fc05f829d7b2e4ed7ea642d77340554f7f8')[:8]}` | {n['framing']} | {n['notes']} |")
sec = ["<!-- v1-1080 BEGIN -->", "## v1-1080 recapture (main 4a427fc0; shot-12 retake from main 4ccfa5be; 1920x1080 60 fps)", ""] + notes["header"] + ["",
       "| Shot | File | Duration | DPR | URL / route | Demo beat | Commit | Framing | Notes / Zen checks |", "|---|---|---|---|---|---|---|---|---|"] + rows + [""] + notes.get("stills", []) + [""] + notes.get("footer", []) + ["<!-- v1-1080 END -->", ""]
m = open(f"{FOOT}/manifest.md").read()
block = "\n".join(sec)
if "<!-- v1-1080 BEGIN -->" in m: m = re.sub(r"<!-- v1-1080 BEGIN -->.*<!-- v1-1080 END -->\n?", block, m, flags=re.S)
else: m = block + "\n" + m
open(f"{FOOT}/manifest.md", "w").write(m)
print("rows", len(rows))

loc = ["# commission-ai promo footage: v1-1080 recapture", ""] + notes["header"] + [""] + full + notes.get("stills", []) + [""] + notes.get("footer", [])
open(f"{D}/manifest.md","w").write("\n".join(loc)+"\n")
