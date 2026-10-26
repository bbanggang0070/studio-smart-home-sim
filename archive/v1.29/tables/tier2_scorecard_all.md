# Tier 2 목표 달성 스코어카드 (Tier 2 전체) — 시나리오 판정 기준 × 기준선 (반복 통과 수 / 반복)

| 기준선 | 시나리오 판정 통과 | 판정 기준 단위 통과율 |
|---|---:|---:|
| A (장치별 독립) | 15 % | 55 % |
| B (히스테리시스 없음) | 88 % | 95 % |
| 제안 | 100 % | 100 % |

## C9 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `event_entered('COOKING') within 90 after cooking_start` | ❌ 0/3 (구간 60–150s 에 없음) | ✅ 3/3 | ✅ 3/3 |
| `window_open_ratio == 0 for all t` | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 |
| `pm25 <= 35 within 1200 after cooking_end` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `window_open_ratio <= 0.0 for all t` | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 |
| `intake_fan_rpm >= 1800.0 during cooking settle 90` | ❌ 0/3 (구간 150–960s) | ✅ 3/3 | ✅ 3/3 |
| `range_hood_level == 1 during cooking settle 90` | ❌ 0/3 (구간 150–960s) | ✅ 3/3 | ✅ 3/3 |
| `pm25_peak <= 0.85 * baseline_A.pm25_peak` | – | ✅ 3/3 | ✅ 3/3 |

## C1 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `window_open_ratio == 0 for all t` | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 |
| `cmd_ac_power within 10 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `humidity <= 72 within 3600 after 0` | ❌ 0/3 (구간 0–3600s 에 없음) | ✅ 3/3 | ✅ 3/3 |
| `exhaust_fan_rpm == 0 for all t` | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 |
| `energy_wh <= baseline_A.energy_wh` | – | ✅ 3/3 | ✅ 3/3 |

## C5 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `exhaust_fan_rpm <= 600 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `intake_fan_rpm <= 700 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `window_open_ratio >= 0.39 within 60 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature <= 28 within 3600 after 0` | ❌ 0/3 (구간 0–3600s 에 없음) | ✅ 3/3 | ✅ 3/3 |

## C10 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `dew_margin >= 0 for all t` | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 |
| `humidity >= 50 within 7200 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `humidifier + dehumidifier <= 1 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |

## C13 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `humidity <= 60 within 3600 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `dehumidifier == 0 for all t` | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature <= 26.05 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `energy_wh <= baseline_A.energy_wh` | – | ✅ 3/3 | ✅ 3/3 |

## C14 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `ratio(humidity <= 70) >= 0.95` | ❌ 0/3 (값=False) | ❌ 0/3 (값=False) | ✅ 3/3 |
| `window_open_ratio == 0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `ac_power == 0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `humidifier == 0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |

## C6 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `dew_margin >= 0.5 within 1800 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature >= 19.0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `humidifier == 0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `condensation_exposure_s < baseline_A.condensation_exposure_s` | – | ✅ 3/3 | ✅ 3/3 |

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

## C11 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `window_open_ratio <= 0.1 for all t` | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 |
| `base_vent_compliance >= 0.95` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `co2_compliance >= 0.95` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `actuation_count <= 0.5 * baseline_B.actuation_count` | ✅ 3/3 | – | ✅ 3/3 |

## C12 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `base_vent_compliance >= 0.95` | ❌ 0/3 (값=False) | ✅ 3/3 | ✅ 3/3 |
| `exhaust_fan_rpm <= 600 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `intake_fan_rpm <= 700 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `co2_compliance >= 0.95` | ❌ 0/3 (값=False) | ✅ 3/3 | ✅ 3/3 |

## C15 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `event_entered('LAUNDRY_DRYING') within 3600 after washer_end` | ❌ 0/3 (구간 600–4200s 에 없음) | ✅ 3/3 | ✅ 3/3 |
| `laundry_dry_time_s <= 21600` | ❌ 0/3 (값=False) | ✅ 3/3 | ✅ 3/3 |
| `temperature <= value_at('temperature', washer_end) + 1.0 when t >= washer_end` | ❌ 0/3 (해당 시각 28201개) | ✅ 3/3 | ✅ 3/3 |
| `humidity <= 70 when t >= 1800` | ❌ 0/3 (해당 시각 27001개) | ✅ 3/3 | ✅ 3/3 |
| `laundry_dry_time_s < baseline_proposed_np.laundry_dry_time_s` | ❌ 0/3 (값=False) | ✅ 3/3 | ✅ 3/3 |

## C17 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `event_entered('POWER_LIMIT') within 30 after cook_start` | ❌ 0/3 (구간 300–330s 에 없음) | ✅ 3/3 | ✅ 3/3 |
| `total_power <= 3000 when t >= 360` | ❌ 0/3 (해당 시각 3241개) | ✅ 3/3 | ✅ 3/3 |
| `range_hood_level >= 1 during cook settle 30` | ❌ 0/3 (구간 330–1200s) | ✅ 3/3 | ✅ 3/3 |
| `dehumidifier within 330 after cook_end` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |

## C18 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `window_open_ratio == 0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `humidity <= 60 within 1800 after shower_end` | ❌ 0/3 (구간 1200–3000s 에 없음) | ✅ 3/3 | ✅ 3/3 |
| `exhaust_fan_rpm < 1 when outdoor_dew > dew_point` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature <= value_at('temperature', shower_start) + 1.0 when t >= shower_start` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature >= value_at('temperature', shower_start) - 1.0 when t >= shower_start` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |

## C19 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `window_open_ratio == 0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `q_net >= -1 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `pm25 <= 35 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `humidity <= value_at('humidity', shower_start) + 5 by 1800 after shower_start` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `dew_margin >= 0 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature >= 19.5 for all t` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |

## C16 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `event_entered('PRECOOL') within 22800 after 0` | ❌ 0/3 (구간 0–22800s 에 없음) | ❌ 0/3 (구간 0–22800s 에 없음) | ✅ 3/3 |
| `value_at('temperature', arrive_start) <= 27` | ❌ 0/3 (값=False) | ❌ 0/3 (값=False) | ✅ 3/3 |
| `value_at('humidity', arrive_start) <= 60` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `energy_wh <= baseline_B.energy_wh` | ✅ 3/3 | – | ✅ 3/3 |

## C4 · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `desk_illuminance >= 600 when t >= 60` | ❌ 0/3 (해당 시각 3541개) | ✅ 3/3 | ✅ 3/3 |
| `ceiling_light <= 60 when t >= 60` | ❌ 0/3 (해당 시각 3541개) | ✅ 3/3 | ✅ 3/3 |
| `temperature <= 28 by 1800 after 0` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `temperature <= 28 when t >= 1800` | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| `lux_temp_ok_ratio > baseline_A.lux_temp_ok_ratio` | – | ✅ 3/3 | ✅ 3/3 |

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

## C3b · fast

| 판정 기준 | A (장치별 독립) | B (히스테리시스 없음) | 제안 |
|---|---|---|---|
| `blind_angle >= 70 within 120 after 0` | ❌ 0/3 (구간 0–120s 에 없음) | ✅ 3/3 | ✅ 3/3 |
| `window_open_ratio <= 0.15 when t > 60` | ❌ 0/3 (해당 시각 540개) | ✅ 3/3 | ✅ 3/3 |
| `temp_end_c < baseline_A.temp_end_c` | – | ✅ 3/3 | ✅ 3/3 |

