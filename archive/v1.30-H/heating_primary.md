# 난방 확장 주 비교 — 등록 docs/15 §4 · `results/randomized_heating/summary.csv`

| 비교 | 지표 | n | 값 [95 % 묶음 구간] | p_holm | 판정 | 세부 |
|---|---|---:|---|---:|---|---|
| 제안-H vs A-H | 환경 결과 통과율 차 | 90 | +0.444 [0.244, 0.667] | 7.28e-12 | **낫다** | 제안 91.1% · 기준 46.7% · 불일치 40:0 |
| 제안-H vs A-H | 난방 기대비용 비 (제안 / 기준) | 90 | 0.962 [0.872, 1.077] | 0.343 | **차이를 확인하지 못함** | 제안이 쌈 50 · 비쌈 40 |
| 제안-H vs A2-H | 환경 결과 통과율 차 | 90 | +0.211 [-0.022, 0.467] | 0.00176 | **차이를 확인하지 못함** | 제안 91.1% · 기준 70.0% · 불일치 25:6 |
| 제안-H vs A2-H | 난방 기대비용 비 (제안 / 기준) | 90 | 2.294 [1.004, 2.716] | 0.000563 | **못하다** | 제안이 쌈 27 · 비쌈 63 |

## 부 지표 — 전체 · 환경 결과 기준 통과율 (판정 없음)

| 실험 | 방식 | 전체 | 환경 결과 |
|---|---|---:|---:|
| randomized_heating | proposed | 91.1% | 91.1% (n 90) |
| randomized_heating | B | 94.4% | 94.4% (n 90) |
| randomized_heating | A2 | 58.9% | 70.0% (n 90) |
| randomized_heating | A | 52.2% | 46.7% (n 90) |
| measured_weather_heating | proposed | 96.7% | 96.7% (n 90) |
| measured_weather_heating | B | 97.8% | 97.8% (n 90) |
| measured_weather_heating | A2 | 60.0% | 71.1% (n 90) |
| measured_weather_heating | A | 56.7% | 55.6% (n 90) |
| heldout_heating_r1 | proposed | 66.7% | 66.7% (n 36) |
| heldout_heating_r1 | B | 66.7% | 66.7% (n 36) |
| heldout_heating_r1 | A2 | 50.0% | 58.3% (n 36) |
| heldout_heating_r1 | A | 41.7% | 33.3% (n 36) |
