#!/bin/bash
# grid.sh FILE OUT crop t1 t2 ... -> 3-column grid
f=$1; out=$2; crop=$3; shift 3; i=0; args=(); fl=""
for t in "$@"; do ffmpeg -v error -y -ss $t -i "$f" -frames:v 1 -vf "crop=$crop,drawtext=text='$t s':x=10:y=10:fontsize=28:fontcolor=yellow" /tmp/chk/g-$i.png; args+=(-i /tmp/chk/g-$i.png); i=$((i+1)); done
n=$i; ffmpeg -v error -y "${args[@]}" -filter_complex "$(for k in $(seq 0 $((n-1))); do printf "[%d]" $k; done)xstack=inputs=$n:layout=$(python3 -c "
n=$n;c=3;print('|'.join(f'{\"+\".join([\"w0\"]*(k%c)) or 0}_{\"+\".join([\"h0\"]*(k//c)) or 0}' for k in range(n)))"):fill=black" "$out"
