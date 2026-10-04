#!/bin/bash
# enc.sh NAME POSTERFRAME [FRAMESDIR] -> encode recorded frames by hand (same settings as rec.mjs)
cd /workspace/videos/commission-ai-promo/footage/v1-1080; n=$1; pf=$2; d=${3:-.frames/$n}
ffmpeg -v error -y -i $d/$(printf %05d $pf).png -vf scale=1920:1080:flags=lanczos $n-poster.png
nice -n 5 ffmpeg -y -loglevel error -framerate 60 -i $d/%05d.png -vf scale=1920:1080:flags=lanczos -c:v libx264 -preset medium -qp 0 -pix_fmt yuv444p -threads 4 -r 60 -movflags +faststart $n.mov && nice -n 10 ffmpeg -y -loglevel error -i $n.mov -c:v libx264 -preset medium -crf 16 -pix_fmt yuv420p -threads 4 -movflags +faststart $n-preview.mp4 && echo $n $(ffprobe -v error -show_entries stream=width,height,r_frame_rate:format=duration -of csv=p=0 $n.mov | tr '\n' ' ')
