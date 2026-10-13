#!/usr/bin/env bash
# ============================================================================
#  센서리스 토크 스윕 · 물체 강성 민감도 (W12 T12.3 · T12.4) — Isaac 브릿지 1개 + 조건마다 안전 노드 재시작
#    tools/run_pinch_sweep.sh                    # 45 · 65 · 75 % × 3종 × 5회 + 55 % × 3종 × 10회
#  결과: results/sweep/pinch_sweep.csv (덧붙임) · 로그 results/sweep/logs/
# ============================================================================
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$REPO"
LOGS=results/sweep/logs; mkdir -p "$LOGS"
PLAN=${PLAN:-"55:10 45:5 65:5 75:5"}
docker rm -f studio-isaac >/dev/null 2>&1; tools/ros/run.sh stop
(timeout 14400 tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py --duration 13000 > "$LOGS/bridge.log" 2>&1 &)
for i in $(seq 1 60); do grep -q "브릿지 시작\|Traceback" "$LOGS/bridge.log" 2>/dev/null && break; sleep 5; done
for item in $PLAN; do
  PCT=${item%%:*}; N=${item##*:}
  echo "=== $(date +%H:%M:%S) 토크 ${PCT} % × ${N}회"
  tools/ros/run.sh stop
  (tools/ros/run.sh node scripts/nodes/window_safety_node.py --run-torque-end-pct "$PCT" > "$LOGS/safety_${PCT}.log" 2>&1 &)
  sleep 6
  tools/ros/run.sh node tools/ros/pinch_sweep.py --torque "$PCT" --trials "$N" ${SWEEP_ARGS:-} 2>&1 | grep -E "토크|Traceback|Error"
done
tools/ros/run.sh stop; docker rm -f studio-isaac >/dev/null 2>&1
echo "=== 끝"
