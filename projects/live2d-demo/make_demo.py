"""Build the 10 s Live2D talk-show demo end to end (prototype; no music/VO pipeline needed).

    python projects/live2d-demo/make_demo.py [--out-dir /workspace/promo-reel-evals]

1. `promo shot 01 02` (renders both Live2D host layers once, niced + locked, then composites the livestream shots)
2. concat the segments + mix the two host WAVs -> <out-dir>/live2d-demo.mp4
3. 6-frame contact sheet -> <out-dir>/live2d-demo-contact.png
4. lip-lag + render-speed report -> <out-dir>/live2d-demo-report.json
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from promo import live2d as L2  # noqa: E402
from promo.cache import Stamps  # noqa: E402
from promo.cli import main as promo_main  # noqa: E402
from promo.spec import load_spec  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out-dir", default="/workspace/promo-reel-evals")
ap.add_argument("--force", action="store_true")
a = ap.parse_args()
spec_path = os.path.join(HERE, "promo.yaml")
spec = load_spec(spec_path)
os.makedirs(a.out_dir, exist_ok=True)

t0 = time.time()
rc = promo_main(["-p", spec_path, "shot", *[s.id for s in spec.shots]] + (["--force"] if a.force else []))
if rc:
    sys.exit(rc)
t_shots = time.time() - t0

# mux: segments + both host voices (each host WAV is already placed on the show timeline)
lst = os.path.join(spec.segs_dir, "list.txt")
with open(lst, "w") as f:
    for s in spec.shots:
        f.write(f"file '{spec.seg_path(s.id)}'\n")
hosts = spec.raw["livestream"]["hosts"]
wavs = [spec.resolve(h["wav"]) for h in hosts]
mp4 = os.path.join(a.out_dir, "live2d-demo.mp4")
cmd = ["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst]
for w in wavs:
    cmd += ["-i", w]
cmd += ["-filter_complex", "".join(f"[{i + 1}:a]" for i in range(len(wavs))) + f"amix=inputs={len(wavs)}:normalize=0,loudnorm=I=-16:TP=-1.5,aresample=48000[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{spec.duration}", "-threads", "2", "-movflags", "+faststart", mp4]
subprocess.run(cmd, check=True)

# 6-frame contact sheet
times = [1.2, 3.9, 5.5, 6.4, 7.2, 8.6]
tiles = []
for t in times:
    tmp = os.path.join(spec.build, "peek", f"demo-{t:.2f}.png")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", mp4, "-frames:v", "1", tmp], check=True)
    im = Image.open(tmp).convert("RGB").resize((640, 360), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    d.rectangle([520, 336, 640, 360], fill=(0, 0, 0))
    d.text((528, 340), f"t = {t:.2f} s", fill=(255, 230, 90), font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15))
    tiles.append(im)
sheet = Image.new("RGB", (3 * 640 + 4 * 8, 2 * 360 + 3 * 8 + 36), (20, 20, 24))
ImageDraw.Draw(sheet).text((10, 8), "Live2D talk-show prototype: Hiyori (left) + Mao, livestream layout, one slide at 6.0 s (hosts pass behind the screen)",
                           fill=(230, 230, 230), font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17))
for i, im in enumerate(tiles):
    sheet.paste(im, (8 + (i % 3) * 648, 44 + (i // 3) * 368))
png = os.path.join(a.out_dir, "live2d-demo-contact.png")
sheet.save(png)

# report: per-host render speed + lip lag (planned track, and values read back from the Cubism model per rendered frame)
st = Stamps(spec.build)
rep = dict(mp4=mp4, contact=png, shots_wall_s=round(t_shots, 1), hosts={})
for i, h in enumerate(hosts):
    r = (st.get(f"live2d_{h['id']}_{spec.OW}") or {}).get("report")
    rep["hosts"][h["id"]] = r
from promo import check as CK  # noqa: E402
from promo import livestream as LS  # noqa: E402
rep["livestream_gates"] = LS.check(spec)
with open(os.path.join(a.out_dir, "live2d-demo-report.json"), "w") as f:
    json.dump(rep, f, indent=1)
print(json.dumps(rep, indent=1))
