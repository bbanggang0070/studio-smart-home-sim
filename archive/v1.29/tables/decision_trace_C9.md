# 의사결정 추적 — C9 · proposed · 반복 1 (docs/07 §5.4 형식 · 자동 생성)

| 시각 | 관측 | 활성 이벤트 | 결정 | 사유 |
|---|---|---|---|---|
| 0:00 | 실내 PM 18 · 외기 150 µg/m³ · 26.0 °C · 55 %RH | OUTDOOR_PM | 해제 ac · ceiling_light 100 · 해제 dehumidifier · desk_light 0 · 해제 exhaust · 해제 hood · 해제 humidifier · intake 833 · purifier 2 · 해제 window | need L5 기본 환기 25 m³/h (흡기팬) · need L5 외기 very_bad 청정기 예방 가동 · need L6 스탠드 — 모드 목표 없음 · need L6 조명 — 천장 400 lux 목표 (NORMAL) |
| 1:11 | 실내 PM 24 · 외기 150 µg/m³ · 26.1 °C · 55 %RH | COOKING, OUTDOOR_PM | hood 1 · intake 2000 | need L2 E1 I3 보상 급기 (흡기팬 · outdoor_pm_bad) · need L2 E1 수증기 (열만) 후드 약 |
| 1:39 | 실내 PM 34 · 외기 150 µg/m³ · 26.2 °C · 55 %RH | COOKING, OUTDOOR_PM | purifier 3 | need L2 E1 요리 청정기 |
| 3:39 | 실내 PM 66 · 외기 150 µg/m³ · 26.5 °C · 55 %RH | COOKING, OUTDOOR_PM | ceiling_fan 1 · ceiling_light 60 | need L5 냉방 ③ 실링팬 정회전 · need L6 조명 — 천장 400 lux 목표 (NORMAL) / cap L5 고온 — 조명 발열 상한 (C4) |
| 13:03 | 실내 PM 120 · 외기 150 µg/m³ · 27.5 °C · 54 %RH | COOKING, OUTDOOR_PM | 에어컨 cool 27.0 °C | need L5 냉방 ⑤ 에어컨 (I5 +1 °C) |
| 16:39 | 실내 PM 116 · 외기 150 µg/m³ · 26.9 °C · 55 %RH | COOKING, OUTDOOR_PM | hood 0 · intake 833 | need L2 E1 요리 후드 예측 선택 {0: 116, 1: 116, 2: 116} · need L5 기본 환기 25 m³/h (흡기팬) |
| 21:39 | 실내 PM 74 · 외기 150 µg/m³ · 26.5 °C · 56 %RH | HOOD_POST_RUN, OUTDOOR_PM | – | – |
| 26:39 | 실내 PM 48 · 외기 150 µg/m³ · 26.5 °C · 56 %RH | OUTDOOR_PM | – | – |
| 28:39 | 실내 PM 41 · 외기 150 µg/m³ · 26.5 °C · 56 %RH | OUTDOOR_PM | control_feasibility DEGRADED | pm |
| 32:17 | 실내 PM 31 · 외기 100 µg/m³ · 26.5 °C · 56 %RH | OUTDOOR_PM | purifier 2 | need L5 외기 very_bad 청정기 예방 가동 |
