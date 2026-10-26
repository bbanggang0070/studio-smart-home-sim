# 10. 에너지 제어 방식 비교 연구 — 질문별 모델 vs LSTM vs 강화학습

> 작성 2026-10-07 · 기획 v3.4 기준 · **논문용 비교 실험 계획 + 벤치마킹 문헌**
> 제어기 설계(docs/08 §5)는 그대로 두고, **논문을 위한 비교 실험으로만** 추가한다.
> **사전 등록(실행 기준): [`13`](13_exp5_preregistration.md)** · 실험 등록: [`03` §5.2](03_scenarios.md) · [`08` §5.8](08_multisignal_energy.md) (EXP-5) · 문헌 목록: [`05` §4.9](05_related_work.md) (G1–G18)
> 서지 정보는 Crossref · arXiv에서 확인했다. ⚠️ 표시는 초록 · 요약만 확인한 문헌이라 인용 전 원문을 확인한다.

---

## 0. 한 줄 요약

**같은 원룸 시뮬레이터에서 세 방식(질문별 모델 · LSTM · 심층 강화학습)을 같은 기준으로 비교한다.**
에너지 절감률만이 아니라 **학습 데이터 양 · 해 보지 않은 상황 · 쾌적 위반 · 개발 · 계산 비용**까지 비교하는 것이 선행연구 대비 차별점이다.

---

## 1. 비교 대상 3가지

| | ① 질문별 모델 (현재 설계) | ② LSTM 계열 | ③ 심층 강화학습 |
|---|---|---|---|
| 방의 열 거동 | 회색상자 2R2C (1–2주 데이터로 보정) | LSTM 실내온도 시계열 예측 | 정책이 직접 학습 (모델 없음) |
| 귀가 시각 | 분위수 GBM — 분포 예측 | LSTM 시계열 예측 (분위수 출력 헤드) | 상태에 시각 · 요일 · 최근 외출 기록 포함 |
| 소비 패턴 | 변화점(냉방도일) 회귀 | LSTM 소비 예측 | 보상에 전력 포함 |
| 언제 켤지 · 켜둘지 | 기대비용 최소화 (전기 + λ × 불쾌) | ①과 같은 최적화에 LSTM 예측을 넣음 (또는 LSTM-MPC) | 정책 출력 (SAC 또는 DQN) |
| 근거 | docs/08 §5 | Esrafilian-Najafabadi 2021 · Stoffel 2024 | Wang 2023 · Mulayim 2025 · Hou 2025 |

**공통 조건:** 같은 고속 모드 시뮬레이터(참값 열모델 3R3C) · 같은 거주자 데이터(마르코프 생성 12주) · 같은 전력 한도 · 같은 우선순위 규칙(안전 · 결로는 세 방식 모두 규칙 계층이 강제).

---

## 2. 벤치마킹 문헌

### A. 가장 가까운 벤치마크 — 같은 환경에서 방식끼리 직접 비교

| # | 문헌 | 무엇을 비교했나 | 우리 연구에 주는 것 |
|---|---|---|---|
| A1 | Wang 외, *Applied Thermal Engineering* 228, 2023 | RL 3종(DDPG · DDQN · SAC)과 RC 축소모델 기반 MPC를 **같은 가상 건물(BOPTEST)**에서 비교. 기존 제어보다 나은 RL은 DDPG뿐 | "같은 환경 · 같은 기준선" 비교 실험의 기본 틀 |
| A2 | Mulayim 외, arXiv:2510.01475, 2025 (⚠️ 심사 중 프리프린트) | **실제 거주 주택** 히트펌프에서 RL과 MPC를 각각 한 달 운영. 절감 MPC 18.1 % · RL 20.9 %, RL은 불쾌 신고 3건, RL 개발 노력 약 1/3 적음(추정) | **주거용** 비교 — 절감률 · 쾌적 위반 · 개발 노력을 함께 비교하는 방식 |
| A3 | Arroyo, Spiessens, Helsen, *Frontiers in Built Environment* 8, 2022 | MPC · RL · 혼합 방식을 같은 틀에서 비교 | 방식별 차이(필요 모델 · 데이터 · 제약 처리) 정리 |
| A4 | ⚠️ Kumkam 외, *Journal of Building Engineering* 112, 2025 | RL과 MPC 비교 (상세 미확인) | 최신 비교 사례 — 원문 확인 후 사용 |

### B. 모델 쪽 비교 — 물리 기반(회색상자) vs LSTM

| # | 문헌 | 핵심 | 우리 연구에 주는 것 |
|---|---|---|---|
| B1 | Vivian 외, *Journal of Building Engineering* 84, 2024 | 평균 예측 성능은 LSTM이 우수. 그러나 **설정온도가 학습 때와 달라지면 LSTM 성능이 크게 떨어지고** 회색상자는 안정적 | docs/08 §5.2가 LSTM을 뺀 이유("해 보지 않은 방법을 모른다")를 **실험으로 검증**할 근거 — 켜두기 vs 끄기가 바로 이 상황 |
| B2 | ⚠️ Stoffel, Berktold, Müller, *Energy and Buildings* 305, 2024 | 실제 건물에서 여러 기계학습 모델(ANN · GPR · 선형)을 MPC 예측 모델로 바꿔 끼우며 비교 — **LSTM 은 다루지 않는다** | 학습 모델을 MPC 예측기로 넣는 구성 방법 · 모델 종류 비교 축 (LSTM 근거는 아님) |
| B3 | Esrafilian-Najafabadi, Haghighat, *Energy and Buildings* 252, 2021 | **주거용 · 미리 공조 시작 시각**을 딥러닝(LSTM 계열)으로 추정 | ② LSTM 방식의 귀가 예측 · 미리 냉방 구현 기준 |

### C. 재실 · 주거용 강화학습 (+ LSTM과의 결합)

| # | 문헌 | 핵심 |
|---|---|---|
| C1 | ⚠️ Hou, Cheng, Ma, *Building and Environment* 284, 2025 | LSTM 재실 예측 + Dueling DQN 제어 — LSTM과 RL 결합의 대표 사례 |
| C2 | Esrafilian-Najafabadi, Haghighat, *Building and Environment* 226, 2022 | B3과 **같은 저자**의 후속 RL 연구 — 같은 문제를 LSTM과 RL로 푼 짝 |
| C3 | McKee 외, *IEEE PES General Meeting*, 2020 | 주거용 · 재실 고려 심층 강화학습 (ORNL) |
| C4 | Wang, Lin, *Building and Environment* 244, 2023 | 주거용에서 데이터로 학습 환경을 만들어 RL 훈련 — 시뮬레이터가 없을 때의 대안 |
| C5 | Chen, Cai, Bergés, *ACM BuildSys*, 2019 | MPC 구조를 RL 정책에 넣어 **적은 데이터로 학습** — 물리 기반과 RL의 연결 |
| C6 | Arroyo 외, *Applied Energy* 309, 2022 | 순수 RL은 제약을 어기고, RL-MPC는 제약을 지키며 성능은 MPC와 비슷 — 안전 제약 논의 |

### D. 실험 틀 · 리뷰 (방법론 장에 인용)

| # | 문헌 | 용도 |
|---|---|---|
| D1 | Blum 외, *Journal of Building Performance Simulation* 14, 2021 (BOPTEST) | 제어 방식 비교용 표준 가상 건물 · 지표 정의 |
| D2 | Drgoňa 외, *Annual Reviews in Control* 50, 2020 | MPC 리뷰 |
| D3 | Wang, Hong, *Applied Energy* 269, 2020 | RL 리뷰 — 데이터 효율 · 안전 · 학습 환경 문제 |
| D4 | Zhang 외, *IEEE Access* 10, 2022 | MPC + RL 서베이 |
| D5 | Jiménez-Raboso 외, *ACM BuildSys*, 2021 (Sinergym) | RL 학습 환경 구성 참고 |

---

## 3. 비교 축 — 선행연구가 공통으로 지적한 것

| 비교 축 | 근거 | 우리 실험으로 바꾸면 | 관련 지표 |
|---|---|---|---|
| **에너지** | A1 · A2 | 기준선(고정 설정) 대비 추정 소비전력량 절감률 | #7 |
| **쾌적 · 제약 위반** | A2 · C6 | 귀가 시 쾌적 도달률 · 감수 한도 위반 · 전력 한도 초과 | #15 · #16 |
| **학습 데이터 양** | B1 · D3 | 1 · 2 · 4 · 8 · 12주 데이터에서의 성능 곡선 (EXP-4 확장) | 신규 |
| **해 보지 않은 상황** | B1 | 학습에 없던 외출 길이 · 설정온도 · 폭염일에서의 켜두기 vs 끄기 판단 정확도 | 신규 |
| **재실 패턴 변화** | C1 · C2 | 학기 → 방학처럼 귀가 패턴이 바뀐 뒤 적응 속도 | 신규 |
| **개발 · 계산 비용** | A2 | 학습 시간 · 튜닝 항목 수 · 1 Hz 제어 주기 안의 계산 시간 · 설명 가능성 | 신규 |

---

## 4. 공정성 설계 — 논문의 신뢰도를 좌우한다

| 위험 | 대응 |
|---|---|
| **RL이 정답 환경을 외운다** — 3R3C 참값 시뮬레이터에서 학습하고 같은 시뮬레이터로 평가하면 RL이 유리 | 평가용 참값 모델에 **파라미터 변동**(열용량 · 틈새 바람 · 에어컨 COP ±20 %)과 **학습에 없던 재실 패턴**을 넣는다. docs/08 §5.3-1 "제어용 모델 ≠ 참값 모델" 원칙을 RL까지 확장 |
| LSTM에 데이터를 더 준다 | 세 방식 모두 **같은 기간 · 같은 데이터**만 사용. RL의 시뮬레이터 상호작용 횟수는 별도로 보고 |
| 하이퍼파라미터 튜닝 노력 차이 | 방식별 튜닝 예산(시도 횟수)을 같게 하고 보고 |
| 안전 규칙이 결과를 가린다 | 세 방식 모두 같은 규칙 계층(안전 · 결로 · 전력 한도) 아래에서 실행. **규칙이 덮어쓴 횟수**도 지표로 기록 |
| 운이 좋은 한 번 | 시드 5개 이상 · 거주자 유형 3종 · 신뢰구간 보고 (A2처럼) |

---

## 5. 실험 계획 초안 — EXP-5

```text
EXP-5  에너지 제어 방식 비교 (고속 모드 · 논문용)
  방식      : ① 질문별 모델  ② LSTM(+ 기대비용 최적화)  ③ 심층 RL(SAC)
  학습 데이터: 1 · 2 · 4 · 8 · 12주 (마르코프 재실 생성기 · 거주자 3유형)
  평가      : 학습 외 4주 × 참값 파라미터 변동 3수준 × 시드 5
  상황      : 짧은 외출 · 긴 외출 · 불규칙 귀가 · 폭염일 · 패턴 변화(학기 → 방학)
  지표      : 에너지(#7) · 귀가 쾌적(#15) · 예산 위반(#16) · 전력 한도 초과 · 규칙 덮어쓰기 횟수
              · 학습 시간 · 제어 주기당 계산 시간
```

| 단계 | 내용 | 시기(안) |
|---|---|---|
| 1 | 고속 모드 하네스 · 참값 3R3C · 재실 생성기 완성 (기존 계획) | W08 · W10 |
| 2 | ② LSTM · ③ RL 학습 환경을 하네스에 붙이기 (Gym 인터페이스) | W11 |
| 3 | 학습 · 평가 실행 | W12 |
| 4 | 결과 분석 · 논문 초안 | W13 – W14 |

> GPU 학습이 필요한 ② · ③은 RTX 5070 Ti에서 Isaac Sim 없이 돌린다(고속 모드). 일정 여유가 없으면 데이터 양 축을 1 · 4 · 12주로 줄인다.

---

## 6. 연구 질문 (안)

1. 데이터가 몇 주뿐인 1인 원룸에서, 세 방식 중 어느 것이 **에너지와 귀가 쾌적을 함께** 가장 잘 지키는가?
2. 학습에 없던 상황(외출 길이 · 설정온도 · 재실 패턴 변화)에서 **성능이 얼마나 떨어지는가**?
3. 같은 성능을 얻기까지 필요한 **데이터 · 개발 · 계산 비용**은 얼마나 다른가?

---

## 7. 참고문헌 (전체 서지)

**A. 직접 비교**
- [A1] Wang, D., Zheng, W., Wang, Z. et al., "Comparison of reinforcement learning and model predictive control for building energy system optimization," *Applied Thermal Engineering*, 228, 120430, 2023. doi:10.1016/j.applthermaleng.2023.120430
- [A2] Mulayim, O. B., Pergantis, E. N., Reyes Premer, L. D., Chen, B., Qu, G., Kircher, K. J., Bergés, M., "Comparative Field Deployment of Reinforcement Learning and Model Predictive Control for Residential HVAC," arXiv:2510.01475, 2025 (preprint).
- [A3] Arroyo, J., Spiessens, F., Helsen, L., "Comparison of Optimal Control Techniques for Building Energy Management," *Frontiers in Built Environment*, 8, 849754, 2022. doi:10.3389/fbuil.2022.849754
- [A4] Kumkam, S., Trinuruk, P., Chaiwiwatworakul, P., Saito, K., "A comparative analysis of reinforcement learning and model predictive control for HVAC system optimization," *Journal of Building Engineering*, 112, 113776, 2025. doi:10.1016/j.jobe.2025.113776

**B. 회색상자 vs LSTM**
- [B1] Vivian, J., Prataviera, E., Gastaldello, N., Zarrella, A., "A comparison between grey-box models and neural networks for indoor air temperature prediction in buildings," *Journal of Building Engineering*, 84, 108583, 2024. doi:10.1016/j.jobe.2024.108583
- [B2] Stoffel, P., Berktold, M., Müller, D., "Real-life data-driven model predictive control for building energy systems comparing different machine learning models," *Energy and Buildings*, 305, 113895, 2024. doi:10.1016/j.enbuild.2024.113895
- [B3] Esrafilian-Najafabadi, M., Haghighat, F., "Occupancy-based HVAC control using deep learning algorithms for estimating online preconditioning time in residential buildings," *Energy and Buildings*, 252, 111377, 2021. doi:10.1016/j.enbuild.2021.111377

**C. 재실 · 주거용 강화학습**
- [C1] Hou, F., Cheng, J. C. P., Ma, J. et al., "Occupancy-driven HVAC control optimization via LSTM and deep reinforcement learning for enhanced indoor air quality, thermal comfort and energy efficiency," *Building and Environment*, 284, 113501, 2025. doi:10.1016/j.buildenv.2025.113501
- [C2] Esrafilian-Najafabadi, M., Haghighat, F., "Towards self-learning control of HVAC systems with the consideration of dynamic occupancy patterns: Application of model-free deep reinforcement learning," *Building and Environment*, 226, 109747, 2022. doi:10.1016/j.buildenv.2022.109747
- [C3] McKee, E., Du, Y., Li, F. et al., "Deep Reinforcement Learning for Residential HVAC Control with Consideration of Human Occupancy," *2020 IEEE Power & Energy Society General Meeting (PESGM)*, 1–5, 2020. doi:10.1109/PESGM41954.2020.9281893
- [C4] Wang, M., Lin, B., "MF²: Model-free reinforcement learning for modeling-free building HVAC control with data-driven environment construction in a residential building," *Building and Environment*, 244, 110816, 2023. doi:10.1016/j.buildenv.2023.110816
- [C5] Chen, B., Cai, Z., Bergés, M., "Gnu-RL: A precocial reinforcement learning solution for building HVAC control using a differentiable MPC policy," *Proc. ACM BuildSys '19*, 316–325, 2019. doi:10.1145/3360322.3360849
- [C6] Arroyo, J., Manna, C., Spiessens, F., Helsen, L., "Reinforced model predictive control (RL-MPC) for building energy management," *Applied Energy*, 309, 118346, 2022. doi:10.1016/j.apenergy.2021.118346

**D. 실험 틀 · 리뷰**
- [D1] Blum, D., Arroyo, J., Huang, S. et al., "Building optimization testing framework (BOPTEST) for simulation-based benchmarking of control strategies in buildings," *Journal of Building Performance Simulation*, 14(5), 586–610, 2021. doi:10.1080/19401493.2021.1986574
- [D2] Drgoňa, J., Arroyo, J., Cupeiro Figueroa, I. et al., "All you need to know about model predictive control for buildings," *Annual Reviews in Control*, 50, 190–232, 2020. doi:10.1016/j.arcontrol.2020.09.001
- [D3] Wang, Z., Hong, T., "Reinforcement learning for building controls: The opportunities and challenges," *Applied Energy*, 269, 115036, 2020. doi:10.1016/j.apenergy.2020.115036
- [D4] Zhang, H., Seal, S., Wu, D. et al., "Building Energy Management With Reinforcement Learning and Model Predictive Control: A Survey," *IEEE Access*, 10, 27853–27862, 2022. doi:10.1109/ACCESS.2022.3156581
- [D5] Jiménez-Raboso, J., Campoy-Nieves, A., Manjavacas-Lucas, A. et al., "Sinergym: a building simulation and control framework for training reinforcement learning agents," *Proc. ACM BuildSys '21*, 319–323, 2021. doi:10.1145/3486611.3488729

> **확인 상태:** 모든 항목은 Crossref(또는 arXiv)로 저자 · 제목 · 학술지 · 권 · 번호 · DOI를 확인했다.
> ⚠️ A2 · A4 · B2 · C1은 본문을 확인하지 않았다 (A2는 심사 중 프리프린트).

---

## 변경 이력

| 날짜 | 버전 | 내용 |
|---|---|---|
| 2026-10-07 | v1.0 | 초판 — 비교 대상 3방식 · 벤치마킹 문헌 18편 · 비교 축 · 공정성 설계 · EXP-5 초안 · 연구 질문 |
| 2026-10-27 | v1.1 | **EXP-5 사전 등록** → [`13`](13_exp5_preregistration.md) — 범위를 외출 중 냉방 결정으로 좁힘 · ③ 을 데이터 기반 RL(③a) / 시뮬레이터 접근 RL(③b) 로 나눔 · 데이터 1 · 2 · 4 · 8주 · 평가 2024 기상 · 판정 규칙. §5 초안과 다르면 13 이 우선 |
| 2026-10-19 | v1.1 | B2(Stoffel 2024) 서술 정정 — ANN · GPR · 선형 비교(LSTM 아님) (docs/11 §6.7) |
