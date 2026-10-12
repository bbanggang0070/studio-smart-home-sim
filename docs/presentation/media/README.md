# 중간발표(10/23) 영상 — Isaac Sim 실시간 시뮬레이션 화면

발표 슬라이드: https://www.figma.com/slides/gYoSgMdBzvRJ4GT4WiuUe9 (각 슬라이드의 "영상 자리: 파일명" 사각형에 넣는다)

| 파일 | 슬라이드 | 내용 | 만든 방법 |
|---|---|---|---|
| window.mp4 | 4 | 모터로 창문 50 % 열기 (블라인드는 화면에서만 숨김) | 브릿지 `--record` + `tools/ros/pinch_once.py` |
| sunblind.mp4 | 4 | 블라인드 0° → 75° → 0° — 닫으면 바닥의 햇빛이 사라진다 | 브릿지 `--record --record-sun 4000` + `tools/ros/demo_cmds.py` |
| pinch.mp4 | 5 | 화분 끼임 → 정지 → 5 cm 후퇴 (브릿지 + 상위 안전 노드 실제 동작) | 브릿지 `--record` + `window_safety_node` + `pinch_once.py` |
| c3.mp4 | 7 | 햇빛 강한 29 °C 방 — 제어기가 블라인드를 먼저 닫고 창문을 연다 (시나리오 C3) | 브릿지 `--record --record-sun 4000` + 런치 `scenario:=C3` |

800 px · 10 fps · H.264 (CRF 30). 햇빛(`--record-sun`)과 주변광(`--record-ambient`)은 화면용이며, 제어용 조도는 환경 모델이 계산한다.
