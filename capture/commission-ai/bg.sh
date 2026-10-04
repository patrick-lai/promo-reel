#!/bin/bash
# usage: bg.sh NAME cmd... -> runs detached, log in logs/NAME.log, pid in logs/NAME.pid
n=$1; shift; cd "$(dirname "$0")"; mkdir -p logs probe
nohup setsid "$@" > logs/$n.log 2>&1 < /dev/null & echo $! > logs/$n.pid; echo "pid $(cat logs/$n.pid)"
