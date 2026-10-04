#!/bin/bash
# waitmem.sh [MB] [SECONDS]: wait until at least MB MiB available (default 5500), give up after SECONDS (default 3600) with exit 1
need=${1:-5500}; max=${2:-3600}; t=0
while :; do a=$(free -m | awk '/Mem/{print $7}'); [ "$a" -ge "$need" ] && { echo "mem ok ${a}MB"; exit 0; }; [ $t -ge $max ] && { echo "mem timeout ${a}MB (need ${need}MB)"; exit 1; }; sleep 15; t=$((t+15)); done
