"""Horizon v4: discoveries on the horizon + a BUILD of real product teases + a bang proof run (user's brief, rounds/4).

    .venv/bin/python projects/commission-ai-horizon/make_shots.py > /tmp/hz_shots.yaml

Structure (120 BPM, 1 beat = 0.5 s, 40 beats = 20 s):
  0-7    open: slow dawn limb (hold)
  7-15   SLOW   specimens 1-1.5 beats, ONE tease
  15-23  BUILD  specimens 1 -> 0.5 beats, THREE teases
  23-27  FAST   0.5-beat specimens, TWO teases
  27-32  BANG   PR raised (1) -> Approved (1) -> Merged held (3), the last words sit on it
  32-40  dawn card (name only)
Each plate's real edge is MEASURED so the serif line kisses it; every tease uses a real UI line as its horizon.
"""
import io, os, subprocess, sys
import numpy as np
import yaml
from PIL import Image

GEN = os.path.expanduser("~/promo-footage/gen")
OUT_Y = 0.47

# ("p", plate, beats, t_in) | ("u", tease-id, beats, t_in)
SEQ = [
    # SLOW 7-15
    ("p", "hz5-cells", 1.5, 0.4), ("p", "hz5-strata", 1, 0.4), ("u", "wave", .5, 0.6), ("p", "hz5-textile", 1, 0.4),
    ("p", "hz5-nautilus", 1.5, 0.4), ("p", "hz5-fern", 1, 0.4), ("p", "hz5-rings", 1, 0.4), ("p", "hz5-crystal", .5, 0.4),
    # BUILD 15-23 (words start at 17 over dark plates)
    ("p", "hz5-pottery", 1, 0.4), ("u", "needs", 1, 1.6), ("p", "hz5-meteorite", 1, 0.4), ("p", "hz5-ammonite", 1, 0.4),
    ("u", "checks", 1, 2.6), ("p", "hz5-coin", .5, 0.4), ("p", "hz5-globe", .5, 0.4), ("u", "pushed", .5, 5.0),
    ("p", "hz5-wing", .5, 0.4), ("p", "hz5-geode", 1, 0.4),
    # FAST 23-27
    ("p", "hz5-wafer", .5, 0.4), ("p", "hz5-vinyl", .5, 0.4), ("u", "wave2", .5, 0.8), ("p", "hz5-manuscript", .5, 0.4),
    ("p", "hz5-opal", .5, 0.4), ("u", "needs", .5, 2.4), ("p", "hz5-shell", .5, 0.4), ("p", "hz5-feather-neg", .5, 0.4),
    ("p", "hz5-frost", .5, 0.4),
    # BANG 27-32
    ("u", "raised", 1, 0.6), ("u", "approved", 1, 1.0), ("u", "merged", 3, 4.1),
]
UI = {  # id -> (source clip, anchor src [x, y], w, out_y)   a real UI line is the horizon
    "wave": ("shot-04p-4k", (0.165, 0.115), 0.30, 0.30),      # top border of the PAY-103 'Running' card
    "wave2": ("shot-04p-4k", (0.50, 0.115), 0.30, 0.30),      # top border of the Wave 2 card
    "needs": ("shot-10b-4k", (0.60, 0.775), 0.32, 0.47),      # top border of the Needs-you card
    "checks": ("shot-08-dpr2", (0.52, 0.385), 0.44, 0.47),    # stepper row, Checks lit
    "pushed": ("shot-08-dpr2", (0.64, 0.385), 0.44, 0.47),    # stepper row, Pushed lit
    "raised": ("shot-merged-drawer-dpr2", (0.76, 0.29), 0.46, 0.47),   # stepper row, PR raised
    "approved": ("shot-12b-4k", (0.45, 0.43), 0.60, 0.47),    # 'Approved. Cart summary uses the pricing engine matches the plan'
    "merged": ("shot-merged-drawer-dpr2", (0.76, 0.225), 0.46, 0.47),  # stepper row, Merged lit
}


def frame(plate, t):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t}", "-i", f"{GEN}/{plate}.mp4", "-frames:v", "1",
                        "-vf", "scale=480:270", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    return np.asarray(Image.open(io.BytesIO(r.stdout)).convert("L"), dtype=np.float32)


def edge_y(plate, t):
    g = frame(plate, t)
    band = g[:, 150:330].mean(axis=1)
    k = 6
    d = np.abs(band[k:] - band[:-k])
    lo, hi = int(0.1 * len(d)), int(0.9 * len(d))
    y = (np.argmax(d[lo:hi]) + lo + k / 2) / 270.0
    return float(np.clip(y, 0.08, 0.92))


def fit_w(ay, oy=OUT_Y, want=0.8):
    return round(min(want, ay / oy * 0.98, (1 - ay) / (1 - oy) * 0.98), 3)


def build():
    shots, b, n = [], 7.0, 2
    for kind, pid, ln, t_in in SEQ:
        sid = f"{n:02d}"
        n += 1
        if kind == "p":
            ay = edge_y(pid, t_in)
            w = fit_w(ay)
            s = dict(id=sid, beats=[b, b + ln], type="horizon", source=pid, t_in=t_in,
                     anchor=dict(src=[0.5, round(ay, 3)], out_y=OUT_Y), w=[w, round(w * 0.94, 3)])
        else:
            src, (ax, ay), w, oy = UI[pid]
            s = dict(id=sid, beats=[b, b + ln], type="horizon", source=src, t_in=t_in,
                     anchor=dict(src=[ax, ay], out_y=oy), w=[w, round(w * 0.95, 3)], text_over_ui=True)
        shots.append(s)
        b += ln
    assert abs(b - 32) < 1e-6, b
    return shots


if __name__ == "__main__":
    yaml.safe_dump(dict(shots=build()), sys.stdout, sort_keys=False, default_flow_style=None, width=200)
