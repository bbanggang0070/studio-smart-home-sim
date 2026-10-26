# 보류(held-out) 평가 r3 — config/heldout_scenarios_r3.yaml · 동결 제어기 · 고속 모드 · 시나리오당 반복 3

| 시나리오 | A | B | proposed | 제안이 실패한 판정 |
|---|---:|---:|---:|---|
| H301 | 0/3 | 3/3 | 3/3 |  |
| H302 | – | – | 0/3 | `mode_is('AWAY') for all t` · `window_open_ratio == 0 for all t` |
| H303 | – | – | 3/3 |  |
| H304 | – | – | 3/3 |  |
| H305 | 0/3 | 3/3 | 3/3 |  |
| H306 | 0/3 | 3/3 | 3/3 |  |
| H307 | 3/3 | 0/3 | 0/3 | `humidifier == 0 for all t` |
| H308 | 0/3 | 3/3 | 3/3 |  |
| H309 | 0/3 | 3/3 | 3/3 |  |
| H310 | – | – | 3/3 |  |
| H311 | – | – | 0/3 | `alert_raised('S_MMWAVE') within 10 after radar_lost_start` |
| H312 | 0/3 | 3/3 | 3/3 |  |

A: 3/21

B: 18/21

proposed: 27/36
