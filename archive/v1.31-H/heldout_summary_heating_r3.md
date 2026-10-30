# 보류(held-out) 평가 heating_r3fix — config/heldout_heating_r3.yaml · 동결 제어기 · 고속 모드 · 시나리오당 반복 3

| 시나리오 | A | B | proposed | 제안이 실패한 판정 |
|---|---:|---:|---:|---|
| HH301 | 0/3 | 0/3 | 0/3 | `energy_cost_won <= baseline_A2V.energy_cost_won` |
| HH302 | 0/3 | 3/3 | 3/3 |  |
| HH303 | 0/3 | 3/3 | 3/3 |  |
| HH304 | 0/3 | 3/3 | 3/3 |  |
| HH305 | 3/3 | 3/3 | 3/3 |  |
| HH306 | 0/3 | 3/3 | 3/3 |  |
| HH307 | 3/3 | 3/3 | 3/3 |  |
| HH308 | 0/3 | 0/3 | 0/3 | `alert_raised('H_BOILER_FAULT') within 3600 after 0` |
| HH309 | 3/3 | 3/3 | 3/3 |  |
| HH310 | 0/3 | 3/3 | 3/3 |  |
| HH311 | 0/3 | 0/3 | 0/3 |  |
| HH312 | 0/3 | 3/3 | 3/3 |  |

A: 9/36

B: 27/36

proposed: 27/36
