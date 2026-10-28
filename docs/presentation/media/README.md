# 중간발표(10/23) 영상 — Isaac Sim 실시간 시뮬레이션 화면

발표 슬라이드: https://www.figma.com/slides/gYoSgMdBzvRJ4GT4WiuUe9 (각 슬라이드의 "영상 자리: 파일명" 사각형에 넣는다)

| 파일 | 슬라이드 | 내용 | 만든 방법 |
|---|---|---|---|
| window.mp4 | 4 | 모터로 창문 50 % 열기 (블라인드는 화면에서만 숨김) | 브릿지 `--record` + `tools/ros/pinch_once.py` |
| sunblind.mp4 | 4 | 블라인드 0° → 75° → 0° — 닫으면 바닥의 햇빛이 사라진다 | 브릿지 `--record --record-sun 4000` + `tools/ros/demo_cmds.py` |
| pinch.mp4 | 5 | 30 kg 화분(밀리지 않음)에 닿는 순간 정지 → 5 cm 후퇴 → 대기 (접촉 최대 63.6 N · 정지 8.3 ms · 브릿지 + 상위 안전 노드 실제 동작) | 브릿지 `--record` + `window_safety_node` + `pinch_once.py "rigid_pot@0.22:30" 0.0` |
| c3.mp4 | 7 | 햇빛 강한 29 °C 방 — 제어기가 블라인드를 먼저 닫고 창문을 연다 (시나리오 C3) | 브릿지 `--record --record-sun 4000` + 런치 `scenario:=C3` |

800 px · 10 fps · H.264 (CRF 30). 햇빛(`--record-sun`)과 주변광(`--record-ambient`)은 화면용이며, 제어용 조도는 환경 모델이 계산한다.

## 최종 발표 (v1.29 · 2026-10-28 재녹화)

| 파일 | 덱 | 내용 | 만든 방법 |
|---|---|---|---|
| v129_c3.mp4 (58 s) | 8 | C3 햇빛 강한 29 °C 방 — 블라인드 45° + 창문 40 % · 10분 에어컨 0회 · 판정 통과 | `PHYS_DIR=physics_demo BRIDGE_ARGS="--record … --record-sun 4000" tools/run_physics.sh C3` · 감마 1.9 보정 · 실시간 29 s + 20배속 |
| v129_c2.mp4 (54 s) | 8 | C2 창문 경로 화분 — 끼임 2회 (49.9 · 48.5 N · 정지 8.3 ms) · 판정 통과 | `--record-camera window --record-hide /World/blind` (화면에서만 블라인드 숨김) · 끼임 구간 실시간 + 배속 |
| v129_*_poster.jpg | 8 | 덱 영상 자리용 대표 장면 | 위 영상에서 추출 |

물리 결과는 `results/physics_demo/` 에 따로 남겼다 (본 실험 `results/physics/` 를 덮어쓰지 않음).
