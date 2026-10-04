#!/bin/bash
# sequential capture queue; each line of queue.txt is a command; done lines are logged to logs/queue-done.txt
cd "$(dirname "$0")"
while kill -0 929903 2>/dev/null; do sleep 10; done
while :; do
  line=$(grep -vxF -f <(cat logs/queue-done.txt 2>/dev/null) queue.txt | head -1)
  [ -z "$line" ] && break
  for attempt in 1 2 3; do
    ./waitmem.sh 3000 1800
    echo "=== $(date +%T) START [$attempt] $line"
    if timeout 5400 bash -c "$line"; then echo "=== $(date +%T) OK $line"; break; fi
    echo "=== $(date +%T) FAIL $line"; sleep 20
  done
  echo "$line" >> logs/queue-done.txt
done
echo "=== QUEUE EMPTY $(date +%T)"
