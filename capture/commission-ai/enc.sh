#!/bin/bash
# enc.sh NAME POSTERFRAME [FRAMESDIR] [START] [FRAMES] -> encode recorded frames by hand (same settings as rec.mjs encode())
#   START  first frame number fed to ffmpeg (-start_number; rec.mjs's startFn offset), default 0
#   FRAMES number of frames to encode (-frames:v), default: all frames on disk from START (highest NNNNN.png + 1 - START)
#   FOOTAGE_DIR env: footage output dir (default <repo>/../videos/commission-ai-promo/footage/v1-1080, same as rec.mjs)
set -euo pipefail
[ $# -ge 2 ] || { echo "usage: enc.sh NAME POSTERFRAME [FRAMESDIR] [START] [FRAMES]" >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd)
FOOTAGE_DIR=${FOOTAGE_DIR:-$(cd "$here/../.." && pwd)/../videos/commission-ai-promo/footage/v1-1080}
cd "$FOOTAGE_DIR"
n=$1; pf=$2; d=${3:-.frames/$n}; start=${4:-0}
last=$(ls "$d" | grep -E '^[0-9]{5}\.png$' | sort | tail -1 || true)
[ -n "$last" ] || { echo "no frames in $d" >&2; exit 1; }
total=$((10#${last%.png} + 1))
frames=${5:-$((total - start))}
[ "$frames" -gt 0 ] || { echo "nothing to encode (start=$start, total=$total)" >&2; exit 1; }
# fit inside 1920x1080 without stretching, pad the rest (identical to VF in rec.mjs)
W=${OUT_W:-1920}; H=$((W*9/16)); VF="scale=$W:$H:force_original_aspect_ratio=decrease:flags=lanczos,pad=$W:$H:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
ffmpeg -v error -y -i "$d/$(printf %05d "$pf").png" -vf "$VF" "$n-poster.png"
nice -n 5 ffmpeg -y -loglevel error -framerate 60 -start_number "$start" -i "$d/%05d.png" -frames:v "$frames" -vf "$VF" -c:v libx264 -preset medium -qp 0 -pix_fmt yuv444p -threads 4 -r 60 -movflags +faststart "$n.mov"
nice -n 10 ffmpeg -y -loglevel error -i "$n.mov" -c:v libx264 -preset medium -crf 16 -pix_fmt yuv420p -threads 4 -movflags +faststart "$n-preview.mp4"
# keep the take's params (injected css flags, cursor overlay, ...) next to the clip for register.py
if [ -f "$d/meta.json" ]; then python3 - "$d/meta.json" "$n.meta.json" "$frames" "$start" "$pf" <<'PY'
import json, sys, datetime
m = json.load(open(sys.argv[1])); m.update(encodedFrames=int(sys.argv[3]), startNumber=int(sys.argv[4]), posterFrame=int(sys.argv[5]), encodedBy="enc.sh",
                                           encodedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
json.dump(m, open(sys.argv[2], "w"), indent=1); open(sys.argv[2], "a").write("\n")
PY
else echo "warning: $d/meta.json missing; add the clip's injected css / cursor overlay to notes.json 'inject'" >&2; fi
echo "$n $(ffprobe -v error -show_entries stream=width,height,r_frame_rate:format=duration -of csv=p=0 "$n.mov" | tr '\n' ' ')"
