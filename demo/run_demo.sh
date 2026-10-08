#!/usr/bin/env bash
# ARC cross-platform demo - safe everywhere (dry-run actions, synthetic load).
# Usage: bash demo/run_demo.sh          (add --real to really touch matched processes)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1. platform capabilities =="
python3 -m arc status

echo
echo "== 2. contract validation =="
python3 -m arc validate contracts/examples/full_suite.yaml

echo
echo "== 3. scenario replay (compile appears, CPU rises; battery drops later) =="
if [[ "${1:-}" == "--real" ]]; then
  python3 -m arc simulate --contracts contracts/examples/full_suite.yaml \
      --scenario demo/scenario_compile_battery.json --speed 3 --duration 12 --real-actions
else
  python3 -m arc simulate --contracts contracts/examples/full_suite.yaml \
      --scenario demo/scenario_compile_battery.json --speed 3 --duration 12
fi

echo
echo "== 4. built-in selftest =="
python3 -m arc selftest

echo
echo "== tip: for a LIVE visual demo run: python3 -m arc web --contracts contracts/examples/full_suite.yaml =="
echo "        then 'bash demo/generate_load.sh' in another terminal and watch the dashboard."
