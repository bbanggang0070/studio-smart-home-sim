# Tier 2 목표 달성 스코어카드 (본문) — 시나리오 판정 기준 × 기준선 (반복 통과 수 / 반복)

| 기준선 | 시나리오 판정 통과 | 판정 기준 단위 통과율 |
|---|---:|---:|
| A (장치별 독립) | 25 % | 62 % |
| B (히스테리시스 없음) | 96 % | 100 % |
| 제안 | 100 % | 100 % |

## C1 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `window_open_ratio == 0 for all t` | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 |
| `cmd_ac_power within 10 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `humidity <= 72 within 3600 after 0` | ❌ 0/3 (구간 0–3600s 에 없음) | ✅ 3/3 | ✅ 3/3 |
| `exhaust_fan_rpm == 0 for all t` | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 |
| `energy_wh <= baseline_A.energy_wh` | – | ✅ 3/3 | ✅ 3/3 |

## C2 · physics

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `pinch_events >= 1` | ❌ 0/3 (값=False) | ✅ 3/3 | ✅ 3/3 |
| `max_contact_force_n <= 100` | ❌ 0/3 (값=False) | ✅ 3/3 | ✅ 3/3 |
| `pinch_stop_ms <= 200` | ❌ 0/3 (값=False) | ✅ 3/3 | ✅ 3/3 |
| `exhaust_fan_rpm >= 500 within 300 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |

## C3 · physics

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `window_open_ratio >= 0.35 within 120 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `blind_angle <= 50 when t > 120` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature < value_at('temperature', 0) by 600 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `ac_power == 0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |

## C4 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `desk_illuminance >= 600 when t >= 60` | ❌ 0/3 (해당 시각 3541개) | ✅ 3/3 | ✅ 3/3 |
| `ceiling_light <= 60 when t >= 60` | ❌ 0/3 (해당 시각 3541개) | ✅ 3/3 | ✅ 3/3 |
| `temperature <= 28 by 1800 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature <= 28 when t >= 1800` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `lux_temp_ok_ratio > baseline_A.lux_temp_ok_ratio` | – | ✅ 3/3 | ✅ 3/3 |

## C5 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `exhaust_fan_rpm <= 600 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `intake_fan_rpm <= 700 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `window_open_ratio >= 0.39 within 60 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature <= 28 within 3600 after 0` | ❌ 0/3 (구간 0–3600s 에 없음) | ✅ 3/3 | ✅ 3/3 |

## C6 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `dew_margin >= 0.5 within 1800 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature >= 19.0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `humidifier == 0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `condensation_exposure_s < baseline_A.condensation_exposure_s` | – | ✅ 3/3 | ✅ 3/3 |

## C7 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `occupied == 0 within 200 after leave_end` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `cmd_window == 0 within 5 after 495` | ❌ 0/3 (구간 495–500s 에 없음) | ✅ 3/3 | ✅ 3/3 |
| `window_open_ratio <= 0.01 by 600 after 495` | ❌ 0/3 (t=1095s 에서 거짓) | ✅ 3/3 | ✅ 3/3 |
| `exhaust_fan_rpm <= 1 when t >= 600` | ❌ 0/3 (해당 시각 601개) | ✅ 3/3 | ✅ 3/3 |
| `intake_fan_rpm <= 1 when t >= 600` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `ac_power == 0 when t >= 600` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `purifier_level == 0 when t >= 600` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |

## C8 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `window_open_ratio <= 0.4 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `window_open_ratio <= 0.01 when outdoor_pm25 > 35 and t >= 1215` | ❌ 0/3 (해당 시각 2386개) | ✅ 3/3 | ✅ 3/3 |
| `q_net >= 0 when outdoor_pm25 > 35 and t >= 1215` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `pm25 <= 35 for all t` | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 |
| `co2 <= 1000 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `purifier_level >= 2 when outdoor_pm25 > 75 and t >= 2405` | △ 2/3 (해당 시각 1196개) | △ 2/3 (해당 시각 1196개) | ✅ 3/3 |
| `exhaust_fan_rpm <= 1400 when outdoor_pm25 > 15 and t >= 15` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `exhaust_fan_rpm <= 600 when outdoor_pm25 > 35 and t >= 1215` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `exhaust_fan_rpm <= 1 when outdoor_pm25 > 75 and t >= 2415` | ❌ 0/3 (해당 시각 1186개) | ✅ 3/3 | ✅ 3/3 |

