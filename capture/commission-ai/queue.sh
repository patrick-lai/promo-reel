#!/bin/bash
# sequential capture queue; each line of $QUEUE (default queue.txt, a git-ignored local run list) is a command.
# Succeeded lines are appended to logs/queue-done.txt; a line that fails all 3 attempts goes to logs/queue-failed.txt (not retried
# on the next pass) and the queue exits 1 at the end. Memory gate: waitmem.sh $QUEUE_MEM_MB (5500) $QUEUE_MEM_WAIT (3600 s).
cd "$(dirname "$0")"; mkdir -p logs
Q=${QUEUE:-queue.txt}; [ -f "$Q" ] || { echo "no queue file $Q (copy queue.example.txt)" >&2; exit 2; }
failed=0
while :; do
  line=$(grep -vxF -f <(cat logs/queue-done.txt logs/queue-failed.txt 2>/dev/null) "$Q" | grep -v '^[[:space:]]*$' | head -1)
  [ -z "$line" ] && break
  ok=0
  for attempt in 1 2 3; do
    ./waitmem.sh "${QUEUE_MEM_MB:-5500}" "${QUEUE_MEM_WAIT:-3600}" || { echo "=== $(date +%T) MEM-WAIT TIMEOUT [$attempt] $line"; sleep 20; continue; }
    echo "=== $(date +%T) START [$attempt] $line"
    if timeout 5400 bash -c "$line"; then echo "=== $(date +%T) OK $line"; ok=1; break; fi
    echo "=== $(date +%T) FAIL [$attempt] $line"; sleep 20
  done
  if [ $ok = 1 ]; then echo "$line" >> logs/queue-done.txt
  else echo "$line" >> logs/queue-failed.txt; echo "$(date -Is) $line" >> logs/queue-failed.log; echo "=== $(date +%T) GAVE UP after 3 attempts: $line"; failed=$((failed + 1)); fi
done
echo "=== QUEUE EMPTY $(date +%T) failed=$failed"
[ $failed = 0 ]
