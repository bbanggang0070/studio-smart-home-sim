# 결과 요약 보관 — 제어기 v1.29 (2026-10-27)

`results/` 는 커밋하지 않는다 (CLAUDE.md). 보고서 · 논문 수치의 출처를 커밋에 고정하려고 **요약만** 여기에 둔다 (사용자 결정 2026-10-26 — B7).
시계열(raw) · 그림 · BOPTEST 분 단위 기록은 넣지 않는다 — 같은 명령으로 다시 만들 수 있다 (README §9.5).

| 파일 | 내용 | 만든 명령 (요약) |
|---|---|---|
| `fast_dev_summary.csv` | 개발 시나리오 고속 33개 (A · B · 제안) | `scripts/scenario_runner.py --mode fast` |
| `a2_dev_summary.csv` | 개발 시나리오 A · A′ | `--baselines A,A2 --extra-baselines A2` |
| `physics_summary.csv` | 물리 모드 8개 · 고정 조건 39회 | `tools/run_physics_batch.sh` |
| `physics_random_summary.csv` · `physics_random_conditions/` | 물리 모드 조건 무작위 39회 · 반복마다 뽑은 조건 | `PHYS_RANDOM=1 PHYS_DIR=physics_random` |
| `randomized_summary.csv` | 무작위 반복 350회 (참값 계수 · 외기) | `tools/run_randomized.py` |
| `randomized_a2_summary.csv` | 같은 조건 A · A′ | `--extra-baselines A2 --only A,A2` |
| `randomized_shared_summary.csv` | 공유 계수 무작위 | `--profile shared_copies` |
| `randomized_faults_summary.csv` | 센서 결함 (A1) | `--profile sensor_faults` |
| `randomized_thresholds_summary_filled.csv` | 임계값 ±20 % (A2) — 보류 3개 시나리오 채움 | `--profile threshold_sensitivity` (+ `_fill`) |
| `randomized_intake{150,300}_summary_filled.csv` | 흡기 용량 민감도 (B4) | `--profile intake150 / intake300` |
| `measured_weather_summary.csv` · `measured_weather_a2_summary.csv` | 실측 기상 2024 (A · B · 제안 / A · A′) | `tools/run_measured_weather.py` |
| `heldout*_summary.csv` | 보류 평가 1–7차 (+ 7차 A′) | `tools/run_heldout.py` |
| `*_manifest.json` | 실행 기록 — 커밋 · 미커밋 파일 · 동결 점검 · 명령줄 (2026-10-26 이후 실행만) | `harness/manifest.py` |
| `tables/` | 분석 표 — 지표 16종 · 무작위 요약 · 3분류 · 짝 검정 · BOPTEST KPI 등 | `scripts/analyze_results.py` · `tools/analysis/*` |

`*_fill` · `*_filled` — A2 · B4 를 A · 제안만 돌려 B 를 참조하는 판정(C11 · C15 · C16)이 보류됐던 것을, 그 3개 시나리오만 전체 기준선으로 다시 돌려 채운 것.
