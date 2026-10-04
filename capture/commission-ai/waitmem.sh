#!/bin/bash
# wait until at least $1 MB available (default 3500), max $2 seconds (default 1800)
need=${1:-3500}; max=${2:-1800}; t=0; [ "$need" -lt 5500 ] && need=5500; max=3600
while :; do a=$(free -m | awk '/Mem/{print $7}'); [ "$a" -ge "$need" ] && { echo "mem ok ${a}MB"; exit 0; }; [ $t -ge $max ] && { echo "mem timeout ${a}MB"; exit 1; }; sleep 15; t=$((t+15)); done
