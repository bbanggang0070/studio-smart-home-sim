#!/usr/bin/env bash
# ============================================================================
#  물리 모드 1회 실행 (W08 T8.6 · W10 T10.v1) — Isaac 브릿지 + ROS 노드 전체 → 실험 로그 → 채점
#
#    tools/run_physics.sh B3 [baseline=proposed] [rep=1]
#    GUI=1 tools/run_physics.sh B3                      # Isaac Sim 창으로 시나리오를 보면서 실행 (X11 · 채점은 같다)
#    BRIDGE_ARGS="--record results/media/c2 --record-camera window --record-fps 2" tools/run_physics.sh C2   # 녹화
#
#  1) Isaac 액추에이터 브릿지 기동 (tools/isaac/run.sh)  2) ROS 런치 (월드 · 센서 · 제어기 · 로거)
#  3) 시나리오가 끝나고 로거가 파일을 닫으면 컨테이너를 정리  4) scripts/physics_eval.py 로 채점
#  결과: results/physics/raw/<id>_<baseline>_<rep>.csv · results/physics/summary.csv · results/physics/logs/
#  PHYS_RANDOM=1 PHYS_DIR=physics_random tools/run_physics.sh B3 proposed 2   # 조건 무작위화 — 반복마다 참값 계수 · 외기 · 잡음 시드 (2026-10-26)
# ============================================================================
set -uo pipefail
SC="${1:?시나리오 id}"; BASE="${2:-proposed}"; REP="${3:-1}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
PD="results/${PHYS_DIR:-physics}"; RAND=$([ "${PHYS_RANDOM:-0}" = "1" ] && echo true || echo false)
LOGS="$REPO/$PD/logs"; mkdir -p "$LOGS"
DUR=$(uv run python -c "
import sys; sys.path.insert(0,'scripts')
from harness.scenario import load_scenarios
print(int(next(s for s in load_scenarios('config/scenario_profiles.yaml') if s['id']=='$SC')['duration_s']))")
echo "물리 모드 실행: $SC · $BASE · 반복 $REP · ${DUR} s (실시간)"

docker rm -f studio-isaac >/dev/null 2>&1; tools/ros/run.sh stop
# 이전 실행의 로그 · CSV 를 지운다 — 남아 있으면 '기록 종료' 대기가 옛 로그를 보고 바로 끝나고 채점도 옛 CSV 로 된다
rm -f "$LOGS/${SC}_bridge.log" "$LOGS/${SC}_launch.log" "$REPO/$PD/raw/${SC}_${BASE}_${REP}.csv"
# Baseline A 는 창문 안전 계층(로컬 컷오프 · 상위 판정)이 없다 — 장치별 독립 규칙 (docs/03 C2 '계속 밀어 반력 초과')
EXTRA=""; [ "$BASE" = "A" ] && EXTRA="--no-local-cutoff"
if [ "${GUI:-0}" = "1" ]; then EXTRA="$EXTRA --gui"; export STUDIO_ISAAC_X11=1; fi
EXTRA="$EXTRA ${BRIDGE_ARGS:-}"
[ "$RAND" = "true" ] && EXTRA="$EXTRA --seed-offset $REP"                            # 예: BRIDGE_ARGS="--record results/media/x --record-camera window" (녹화)
timeout $((DUR + 400)) tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py --duration $((DUR + 120)) $EXTRA \
  > "$LOGS/${SC}_bridge.log" 2>&1 &
for i in $(seq 1 60); do grep -q "브릿지 시작\|Traceback" "$LOGS/${SC}_bridge.log" && break; sleep 5; done
grep -q "브릿지 시작" "$LOGS/${SC}_bridge.log" || { echo "브릿지 기동 실패 — $LOGS/${SC}_bridge.log"; exit 1; }

timeout $((DUR + 300)) tools/ros/run.sh ros2 launch launch/studio_smart_home.launch.py \
  scenario:="$SC" baseline:="$BASE" rep:="$REP" randomize:="$RAND" out_dir:="$PD" > "$LOGS/${SC}_launch.log" 2>&1 &
until grep -q "기록 종료\|Traceback" "$LOGS/${SC}_launch.log"; do sleep 5; done
grep -E "Traceback" -A5 "$LOGS/${SC}_launch.log" | head -20
tools/ros/run.sh stop; docker rm -f studio-isaac >/dev/null 2>&1
uv run python scripts/physics_eval.py --scenarios "$SC" --baselines "$BASE" --reps "$REP" --dir "$PD"
