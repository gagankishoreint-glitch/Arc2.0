#!/usr/bin/env bash
# Generate CPU pressure so the cpu-hot-guard contract fires on the live dashboard.
# Usage: bash demo/generate_load.sh [seconds]     (default 20)
set -u
SECS="${1:-20}"
N="$(python3 -c 'import os; print(os.cpu_count() or 4)')"
PIDS=""
echo "spawning $N CPU hogs for ${SECS}s - watch the dashboard light up..."
for _ in $(seq 1 "$N"); do
  yes > /dev/null 2>&1 &
  PIDS="$PIDS $!"
done
sleep "$SECS"
echo "stopping load - contracts should RESTORE shortly..."
# shellcheck disable=SC2086
kill $PIDS 2>/dev/null
wait 2>/dev/null
echo "done."
