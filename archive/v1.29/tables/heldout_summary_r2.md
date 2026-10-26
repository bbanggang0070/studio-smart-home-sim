# 보류(held-out) 평가 r2 — config/heldout_scenarios_r2.yaml · 동결 제어기 · 고속 모드 · 시나리오당 반복 3

| 시나리오 | A | B | proposed | 제안이 실패한 판정 |
|---|---:|---:|---:|---|
| H201 | 0/3 | 3/3 | 3/3 |  |
| H202 | 0/3 | 0/3 | 0/3 | `humidifier == 0 for all t` |
| H203 | 0/3 | 0/3 | 0/3 | `laundry_dry_time_s <= 21600` |
| H204 | 0/3 | 3/3 | 3/3 |  |
| H205 | – | – | 3/3 |  |
| H206 | 0/3 | 3/3 | 3/3 |  |
| H207 | 0/3 | 3/3 | 3/3 |  |
| H208 | 0/3 | 0/3 | 0/3 | `temperature >= 19.5 for all t` |
| H209 | 0/3 | 0/3 | 0/3 | `humidity <= 60 within 1800 after shower_end` |
| H210 | – | – | 1/3 | `purifier_level >= 2 when t >= 405` |
| H211 | – | – | 3/3 |  |
| H212 | 3/3 | 3/3 | 3/3 |  |

A: 3/27

B: 15/27

proposed: 22/36
