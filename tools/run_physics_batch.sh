#!/usr/bin/env bash
# ============================================================================
#  물리 모드 배치 (W11 T11.3 · T11.5) — 시나리오 · baseline · 반복을 차례로 tools/run_physics.sh 로 실행
#
#    tools/run_physics_batch.sh B1 B2 B3 B5 C2 C3        # 시나리오 정의의 baselines × repeat 전부
#    FORCE=1 tools/run_physics_batch.sh C3               # 이미 있는 결과도 다시
#
#  이어 돌리기: results/physics/raw/<id>_<baseline>_<rep>.csv 가 있으면 건너뛴다 (중간에 멈춰도 다시 실행하면 이어서)
#  끝나면 scripts/physics_eval.py 로 전체를 다시 채점한다 (baseline_A.* 비교 판정은 같은 시나리오가 다 모여야 된다)
# ============================================================================
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
RAW="$REPO/results/physics/raw"; mkdir -p "$RAW"
for SC in "$@"; do
  mapfile -t COMBOS < <(uv run python -c "
import sys; sys.path.insert(0,'scripts')
from harness.scenario import load_scenarios
s=next(s for s in load_scenarios('config/scenario_profiles.yaml') if s['id']=='$SC')
for b in s['baselines']:
    for r in range(1, int(s['repeat'])+1): print(b, r)")
  for c in "${COMBOS[@]}"; do
    read -r B R <<< "$c"
    if [ -z "${FORCE:-}" ] && [ -s "$RAW/${SC}_${B}_${R}.csv" ]; then echo "건너뜀 (결과 있음): $SC $B $R"; continue; fi
    echo "=== $(date +%H:%M:%S) 실행: $SC · $B · 반복 $R"
    tools/run_physics.sh "$SC" "$B" "$R" 2>&1 | grep -E "^${SC}_|FAIL|ERROR|Traceback|실패" | head -8
  done
done
echo "=== 전체 채점"
uv run python scripts/physics_eval.py --scenarios "$(IFS=,; echo "$*")" 2>&1 | grep -E "^[A-Z][0-9a-z]*_|요약" | head -60
