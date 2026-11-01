# 제목 · 초록 후보 — A 방향 (평가 방법 중심) · 2026-11-01

> 사용자 결정: A 방향(평가 절차와 '엄격한 평가 뒤에 남는 것' 중심 · 새 실험 없음). 세 안 모두 같은 결과를 쓰고 강조점만 다르다.
> 수치 출처: 보고서 v1.2 · docs/12 · 13 · 15 · `archive/`. 제목은 템플릿 규정(Arial 16 pt · 2줄 이내 ≈ 130자) 안.

---

## A1 — 제어기 + 평가 절차를 함께 내세움 (균형형)

**Title.** Cooperative multi-actuator control of a studio apartment under a pre-registered evaluation protocol

**Abstract.** Smart-home controllers are usually evaluated against weak baselines, on scenarios chosen by their designers and with criteria that reward their own internal behavior. This study develops a cooperative controller that coordinates eleven low-cost actuators — household appliances and retrofit devices — in a simulated 3.5 m × 5 m studio apartment, and evaluates it under a protocol fixed before any result was seen. The controller resolves conflicting indoor goals through layered arbitration and cost-ordered means ladders, and a window actuator detects pinching from the motor current without additional sensors. The protocol specifies commercial-grade rule automation as a baseline in advance, restricts pass/fail criteria to environmental outcomes, reports scenario-cluster bootstrap intervals with Holm correction, and runs pre-registered held-out scenarios once without revision. In the cooling season, the controller kept environmental outcomes within criteria in 91.2% of randomized runs against 31.2% for commercial-grade automation, a difference of 60 percentage points (95% interval 35–84), and passed 32 of 36 runs in the final held-out round. Its expected cost was 0.69 times that of the commercial-grade baseline, but energy savings alone could not be established. In a heating-season extension with a combi boiler and hydronic floor heating, environmental outcomes again improved over a commercial thermostat with continuous ventilation, while heating cost showed no difference. For the energy-critical away-time cooling decision, LSTM and reinforcement learning trained on four weeks of data did not outperform a model-based planner, and a simple always-off rule was cheaper than all of them. The protocol also revealed defects and overstated claims that conventional evaluation would have missed.

**Keywords.** cooperative control; held-out evaluation; indoor environment; multi-actuator; pre-registration; smart home

---

## A2 — '엄격한 평가 뒤에 무엇이 남는가' 를 정면으로 (발견형)

**Title.** What survives rigorous evaluation? A pre-registered simulation comparison of residential multi-actuator controllers

**Abstract.** Simulation studies of residential control often report large benefits that depend on how the evaluation was designed. This paper asks which claims about a multi-actuator smart-home controller survive when the evaluation is made deliberately strict. A cooperative controller that coordinates eleven appliances and retrofit actuators in a simulated studio apartment was compared with device-independent automation, commercial-grade rule automation with and without continuous ventilation, and an ablation without hysteresis. The evaluation fixed baselines and criteria before results were seen, judged runs only by environmental outcomes, used scenario-cluster bootstrap intervals with Holm correction, ran seven pre-registered held-out rounds once each, and cross-checked against measured weather, official time-use statistics and an external building emulator. One claim survived every step: the controller kept indoor environmental outcomes within criteria far more often than commercial-grade automation, by 60 percentage points (95% interval 35–84) in randomized runs and with 32 of 36 runs passing in the final held-out round, and the same direction held in a heating-season extension with a combi boiler. Other claims did not survive: an apparent 18% energy saving became uncertain once runs were resampled by scenario, the cost advantage under measured weather lost significance when the weather source changed, physics-mode success fell from 24/24 to 20/24 under randomized conditions, and learning-based alternatives trained on four weeks of data did not beat a simple always-off rule for away-time cooling. The results suggest that evaluation design, more than controller sophistication, determines which conclusions a simulation study can support.

**Keywords.** evaluation protocol; held-out scenarios; multi-actuator control; pre-registration; reproducibility; smart home

---

## A3 — 비교 대상(기준선 · 학습 방식)을 앞세움 (벤치마크형)

**Title.** Commercial-grade baselines, held-out scenarios and learning-based alternatives: evaluating smart-home control in simulation

**Abstract.** Learning-based and model predictive controllers for buildings are commonly benchmarked against simple thermostats on a single conditioning plant, whereas real homes contain many appliances that act on the same air. This study builds a simulated studio apartment in which eleven low-cost actuators share one room, and uses it to compare four classes of control under one pre-registered protocol: device-independent automation, commercial-grade rule automation (with and without continuous ventilation), a cooperative controller with layered arbitration and cost-ordered means ladders, and, for the energy-critical away-time cooling decision, LSTM-based and reinforcement-learning alternatives trained on the same data. Baselines and criteria were fixed before results were seen, runs were judged only by environmental outcomes, held-out scenarios were run once, and results were checked with measured weather and an external building emulator. The cooperative controller kept environmental outcomes within criteria in 91.2% of randomized cooling-season runs, against 31.2% for commercial-grade automation and 23.8% for device-independent automation, and improved outcomes in a heating-season extension with a combi boiler and hydronic floor heating. Its expected cost was 0.69 times that of commercial-grade automation, but energy and heating-cost savings alone were not established. With four weeks of training data, neither the LSTM model nor reinforcement learning improved on the model-based planner, and a simple always-off rule was the cheapest policy. Coordination structure rather than learning capacity explained most of the difference between controllers in this setting.

**Keywords.** benchmarking; building control; cooperative control; learning-based control; multi-actuator; smart home

---

## 비교 (한국어)

| | A1 균형형 | A2 발견형 | A3 벤치마크형 |
|---|---|---|---|
| 한 줄 | 협조 제어기를 사전 등록 평가로 검증 | 엄격하게 평가하면 무엇이 남고 무엇이 사라지나 | 네 부류 제어를 한 절차로 비교 |
| 주인공 | 제어기 + 평가 절차 | **평가 결과(살아남은 주장 · 사라진 주장)** | 비교 대상 · 벤치마크 |
| 새로움 | 중간 | **가장 높음** — 다른 논문에 드문 '사라진 주장' 을 정면으로 | 중간 — 비교 범위가 넓어 보이지만 시스템 수준 RL 이 없다는 지적 가능 |
| 위험 | 제어기 자체의 새로움을 물으면 약함 | 결론이 '평가가 중요하다' 로 읽혀 제어 기여가 작아 보일 수 있음 | 'RL · MPC 를 시스템 전체에 적용 안 함' 공격 |
| 맞는 학술지 | 건물 제어 · 스마트홈 (Buildings · Sensors · ABER) | 건물 시뮬레이션 · 방법론 (Journal of Building Performance Simulation · ABER · Building and Environment) | 건물 제어 (Energy and Buildings 계열 · JBE) |
| SSS 적합성 | 낮음 | 가장 낮음 | 낮음 |
| 단어 수 | 약 250 | 약 250 | 약 240 |

**추천**: **A2** — 이 연구에만 있는 것(엄격한 평가가 주장을 어떻게 바꿨나)을 제목부터 내세워, 심사위원이 '그냥 규칙 기반 제어기' 로 읽을 여지를 줄인다. 제어 기여(사다리 · 센서리스 창문)는 방법 절에서 충실히 쓴다.
