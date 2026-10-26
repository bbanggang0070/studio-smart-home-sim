# 보류(held-out) 평가 — H1–H12 · 동결 제어기 · 고속 모드 · 시나리오당 반복 3

| 시나리오 | A | B | proposed | 제안이 실패한 판정 |
|---|---:|---:|---:|---|
| H1 | 0/3 | 3/3 | 3/3 |  |
| H2 | 0/3 | 0/3 | 0/3 | `total_power <= 2500 when t >= cook_start + 60` |
| H3 | 0/3 | 0/3 | 0/3 | `dew_margin >= 0 for all t` · `temperature >= 19.5 for all t` |
| H4 | 0/3 | 2/3 | 3/3 |  |
| H5 | 0/3 | 0/3 | 0/3 | `q_net >= -1 during cook settle 120` |
| H6 | 0/3 | 3/3 | 3/3 |  |
| H7 | – | – | 3/3 |  |
| H8 | 0/3 | 3/3 | 3/3 |  |
| H9 | 0/3 | 0/3 | 0/3 | `humidifier == 0 when dew_margin < 2` |
| H10 | 0/3 | 0/3 | 0/3 | `humidity <= 60 within 1800 after shower_end` |
| H11 | – | – | 0/3 | `q_net >= 0 when t >= 15` |
| H12 | – | – | 3/3 |  |

A: 0/27

B: 11/27

proposed: 18/36
