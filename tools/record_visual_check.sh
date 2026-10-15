#!/usr/bin/env bash
# ============================================================================
#  작동 표시 녹화 검증 (Scene v0.3) — 브릿지만 띄우고 tools/ros/visual_check.py 로 상태 토픽을 차례로 보내며 카메라별로 녹화
#
#    tools/record_visual_check.sh                          # 주방 · 침대 쪽 · 에어컨 · 창문 제어 박스 4곳
#    ITEMS="kitchen|kitchen" tools/record_visual_check.sh  # 한 곳만 (이름|카메라 — 카메라는 장면 이름 또는 "x,y,z:tx,ty,tz")
#  결과: results/media/visual_check/<이름>/f*.jpg · <이름>_bridge.log → uv run python tools/analysis/visual_check_sheet.py
# ============================================================================
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$REPO"
export STUDIO_ISAAC_NAME=studio-isaac-vc
OUT=results/media/visual_check; mkdir -p $OUT
for item in ${ITEMS:-"kitchen|kitchen" "bedside|bedside" "ac|2.2,2.0,1.6:3.4,3.0,2.05" "window|window_ctrl"}; do
  name=${item%%|*}; cam=${item#*|}
  rm -rf $OUT/$name; docker rm -f $STUDIO_ISAAC_NAME >/dev/null 2>&1
  (timeout 400 tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py --duration 75 --record $OUT/$name \
      --record-camera "$cam" --record-fps 1 --record-ambient 150 > $OUT/${name}_bridge.log 2>&1 &)
  for i in $(seq 1 80); do grep -q "브릿지 시작\|Traceback" $OUT/${name}_bridge.log 2>/dev/null && break; sleep 3; done
  grep -q "브릿지 시작" $OUT/${name}_bridge.log || { echo "$name 브릿지 실패"; continue; }
  tools/ros/run.sh node tools/ros/visual_check.py > $OUT/${name}_steps.log 2>&1
  for i in $(seq 1 60); do grep -q "브릿지 종료\|Traceback" $OUT/${name}_bridge.log && break; sleep 3; done
  echo "$name 프레임 $(ls $OUT/$name | wc -l) · 오류 $(grep -c Traceback $OUT/${name}_bridge.log)"
done
docker rm -f $STUDIO_ISAAC_NAME >/dev/null 2>&1; tools/ros/run.sh stop >/dev/null 2>&1
echo 끝
