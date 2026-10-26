# 판정 기준 사후 개정 감사 — 같은 로그를 개정 전 · 현재 기준으로 (통과 비율)

| 시나리오 | 기준선 | 개정 전 기준 통과 | 현재 기준 통과 |
|---|---|---:|---:|
| B1 | proposed | 0 % | 100 % |
| B2 | proposed | 0 % | 100 % |
| B3 | proposed | 100 % | 100 % |
| B6 | proposed | 0 % | 100 % |
| C1 | A | 0 % | 0 % |
| C1 | B | 0 % | 100 % |
| C1 | proposed | 0 % | 100 % |
| C11 | A | 0 % | 0 % |
| C11 | B | 100 % | 100 % |
| C11 | proposed | 0 % | 100 % |
| C13 | A | 0 % | 0 % |
| C13 | B | 0 % | 100 % |
| C13 | proposed | 0 % | 100 % |
| C15 | A | 0 % | 0 % |
| C15 | B | 0 % | 100 % |
| C15 | proposed | 0 % | 100 % |
| C15 | proposed_np | 0 % | 0 % |
| C3 | A | 0 % | 100 % |
| C3 | B | 0 % | 100 % |
| C3 | proposed | 0 % | 100 % |
| C9 | A | 0 % | 0 % |
| C9 | B | 0 % | 100 % |
| C9 | proposed | 0 % | 100 % |
| X5 | proposed | 0 % | 100 % |

개정 전 기준에서 제안이 실패한 기준 (반복 1):

- **C1** — humidity <= 60 within 1800 after 0 (구간 0–1800s 에 없음)
- **C13** — humidity <= 60 within 1800 after 0 (구간 0–1800s 에 없음)
- **C9** — pm25_peak <= 0.7 * baseline_A.pm25_peak (값=False)
- **C11** — energy_wh <= baseline_B.energy_wh (값=False)
- **C15** — laundry_dry_time_s <= 14400 (값=False)
- **X5** — intake_fan_rpm <= 900 within 300 after cook_end (구간 960–1260s 에 없음) | humidity <= 60 within 1800 after cook_end (구간 960–2760s 에 없음)
- **B6** — event_entered('SHOWER') within 120 after shower_start (구간 900–1020s 에 없음)
- **B1** — window_open_ratio <= 0.01 for all t ()
- **B2** — blind_angle >= 72 within 30 after 0 (구간 0–30s 에 없음)
- **C3** — blind_lead_s > 0 (값=False) | blind_angle >= 70 within 120 after 0 (구간 0–120s 에 없음) | energy_wh <= baseline_A.energy_wh (값=False)
