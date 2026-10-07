# 선행연구 및 참고문헌 (Related Work & References)

> **신규 산출물** · 작성일 2026-09-12 · v1.0
> 본 프로젝트의 학술적 위치를 명확히 하고, 선행연구와의 차별점을 정량적으로 제시한다.

---

## 1. 선행연구 대비표 — 한눈에 보기

| 구분 | [3] 박재민 외 (2018) | [1] 연승재 외 (2025) | [5] 장총민 외 (2013) | **본 프로젝트 (2026)** |
|---|---|---|---|---|
| **대상 공간** | 일반 창호 | 주택 일반 | 사무/주거 창측 | **원룸 17.5 m² 특화** |
| **창문 안전** | 인체 감지 → **강제 폐쇄** | – | – | **끼임 감지 → 정지·반전 (센서 없음)** |
| **블라인드 제어** | PDLC 필름 투과도 | – | **PID 제어** | 구간 제어 + 히스테리시스 |
| **센서 수** | 5종 이상 | 다수 노드 | 1종(CdS) | **4종 — 알고리즘으로 3종 대체** |
| **제어 구조** | 조건별 **단일 액추에이터** 규칙 | 허브 통합 판단 | 단일 루프 | **제약 충돌 시 역할 재분배** |
| **통신** | 라즈베리파이 로컬 | **MQTT** | – | **ROS 2** |
| **검증 방식** | 실물 시작품 | 실물 + 모바일 앱 | 실물 시작품 | **시뮬레이션 — 시나리오 180회 + 끼임 스윕 70회** |
| **외부 데이터** | 기상청 API + 미세먼지 | – | – | **기상청/에어코리아 API (강우·미세먼지)** |

---

## 2. 핵심 선행연구 3편 — 상세 대비

### 2.1 [3] 박재민 외 (2018) — 가장 가까운 선행연구 ⚠️

> 조도·온습도·연기·빗물·인체감지 센서 + 라즈베리파이. 조도값으로 PDLC 필름 채광 제어,
> 온습도 + 기상청 API + 미세먼지로 창문 자동 개폐, **인체감지 시 강제 폐쇄**

**본 프로젝트와 구조가 가장 유사하다.** 따라서 차별점을 명확히 제시하지 못하면
*"이미 존재하는 연구"* 로 평가될 위험이 있다. 반대로 잘 대비시키면 가장 강력한 근거가 된다.

#### 결정적 차이 — 창문 안전의 **정의**가 다르다

| | [3] 박재민 외 | **본 프로젝트** |
|---|---|---|
| 감지 대상 | **사람(인체)** | **물체 종류 무관 — 주행 경로의 저항** |
| 동작 | 사람이 감지되면 **강제 폐쇄** | 끼임이 감지되면 **정지 + 반전** |
| 전제 | 창가에 사람이 있는 것이 위험 | **패널 주행 경로의 물체**가 위험 |
| 부품 | 인체감지 센서 | **없음** (모터 전류만) |

> **[3]의 "인체감지 시 강제 폐쇄"는 본 프로젝트가 초기 검토 후 폐기한 접근이다.**
> 미닫이 창은 옆으로 미끄러지므로 **창 앞에 서 있는 사람은 패널에 부딪히지 않는다.**
> 실제 위험은 **패널이 지나갈 경로에 놓인 물체**다. 또한 사람이 감지될 때 창문을 **닫는** 동작은,
> 그 사람의 손이 창틀에 있다면 오히려 위험을 증가시킨다.
>
> → 본 프로젝트는 감지 대상을 **"사람"이 아니라 "주행 저항"** 으로 재정의하고,
> 동작을 **"폐쇄"가 아니라 "정지·반전"** 으로 바꿨다.

#### 그 외 차별점

| 축 | [3] | 본 프로젝트 |
|---|---|---|
| 제약 충돌 | 조건별 독립 규칙 | **제약이 충돌할 때의 역할 재분배**를 정면으로 다룸 (Tier 2 8개) |
| 센서 정책 | 기능마다 센서 추가 | **알고리즘으로 3종 대체** (−39 %) |
| 안전 검증 | 시작품 시연 | **반복 끼임 실험(토크 스윕 · 강성 3종) + 최대 접촉 반력 정량 측정** |

> **인용 시 주의:** 2018년 발표로 연식이 있다. *"최신 동향"* 이 아니라
> **"본 연구가 출발점으로 삼는 선행연구"** 로 위치시키고, 위 차별점을 함께 제시한다.

---

### 2.2 [2] Buildings (MDPI, 2025) — 센서 최소화의 학술적 근거 ⭐

> 책상 스탠드에 온습도·조도·공기질·소음 **통합 센서 내장**. 3D 프린팅 + 오픈소스로
> **약 33유로(5만원 내외)** 에 구현. **"한 공간 = 통합센서 하나"** 컨셉

**본 프로젝트 차별점 ②(센서 최소화)의 직접적 근거 문헌이다.**

| 공통점 | 본 프로젝트의 확장 |
|---|---|
| 한 공간에 최소한의 센서만 배치 | **알고리즘으로 센서를 대체**하는 단계까지 진행 |
| 저비용(약 5만원) 목표 | **부품 57,500원** — 액추에이터까지 포함하고도 유사 수준 |
| 오픈소스·범용 부품 | ESP32급 + 아두이노 입문 키트 수준 부품 |

> **차별점 서술:** [2]가 *"센서를 한 곳에 모아 수를 줄인다"* 라면,
> 본 프로젝트는 *"센서를 **알고리즘으로 대체**하여 수를 줄인다"* 이다.
> 책상 조도는 추정식으로, 재실 영역은 거리 게이트로, 창문 안전은 모터 전류로 대체했다.

**오픈액세스**이므로 전문 확보와 인용이 용이하다.

---

### 2.3 [5] 장총민·김성걸 (2013) — 블라인드 제어 방식의 대비

> CdS 조도센서 + **PID 제어**로 블라인드 조도 균일화. 편광필름으로 태양광 반사, BEMS 연동 가능성

**본 프로젝트는 PID를 쓰지 않는다. 그 이유를 설명하는 근거로 인용한다.**

| | [5] PID 제어 | **본 프로젝트 구간 제어 + 히스테리시스** |
|---|---|---|
| 목표 | 조도를 연속적으로 균일 유지 | **불필요 구동 최소화** + 목표 범위 유지 |
| 액추에이터 부담 | 목표값 추종을 위해 **지속적 미세 조정** | 데드밴드 내에서는 **움직이지 않음** |
| 저가 서보 적합성 | 미세 조정 반복 시 마모·소음 | SG90급 저가 서보에 적합 |
| 평가 지표 | 조도 오차 | **불필요 구동 횟수 50 % 감소** |

> **차별점 서술:** 원룸의 저가 서보는 PID의 지속적 미세 조정을 견디기 어렵고,
> 사용자 체감상으로도 블라인드가 계속 미세하게 움직이는 것은 불편하다.
> 본 프로젝트는 **"정확한 추종"보다 "불필요한 구동을 하지 않는 것"** 을 목표로 삼았고,
> 이를 평가 지표(불필요 구동 횟수)로 정량화했다.

---

### 2.4 [1] 연승재 외 (2025) — 아키텍처 선행연구

> 저비용 개방형 스마트홈. **MQTT** 프로토콜, 라즈베리파이(메인 서버) + 아두이노 메가(센서·액추에이터 노드),
> 모바일 앱 모니터링/원격제어

**허브-노드 분리 아키텍처**가 본 프로젝트와 동일하다. 다만 통신 계층이 다르다.

| | [1] MQTT | **본 프로젝트 ROS 2** |
|---|---|---|
| 통신 | MQTT 브로커 | ROS 2 DDS (토픽 44개) |
| 선택 이유 | IoT 표준, 경량 | **Isaac Sim 연동** · QoS 제어 · 로봇 생태계 재사용 |
| QoS | QoS 0/1/2 | **센서 BEST_EFFORT / 명령·상태 RELIABLE** 분리 |

> **차별점 서술:** MQTT는 IoT 표준이지만 시뮬레이터 연동과 실시간 제어 QoS 제어에는 제약이 있다.
> 본 프로젝트는 Isaac Sim ROS 2 Bridge를 통한 물리 시뮬레이션 연동이 핵심이므로 ROS 2를 채택했다.
> 실물 이식 시에는 ROS 2 ↔ MQTT 브리지로 [1]의 구조에 접속할 수 있다.

---

### 2.5 [4] 김경영 외 (2021) — 저비용 지향의 동시대 연구

> 조도·우적·연기 센서 + 아두이노 DC모터 창문 개폐, PDLC 필름 투과도 조절.
> **"고가 장비 없이 자동 환기 + 일조량 조절"** 을 명시적 목표로 제시

저비용 지향점이 본 프로젝트와 동일하다. **PDLC 필름은 블라인드의 대안**이나
단가·시공 난이도가 높아 본 프로젝트에서는 **확장 아이디어로 분류**한다.

---

## 3. 본 프로젝트의 학술적 기여

선행연구 대비 본 프로젝트가 새로 제시하는 것은 다음 3가지다.

| # | 기여 | 선행연구와의 차이 |
|---|---|---|
| **①** | **제약 충돌 상황의 협조 제어를 실험 설계로 정식화** | 선행연구는 조건별 단일 액추에이터 규칙에 머문다. 본 연구는 **제약 충돌 개수로 시나리오를 계층화**하고 3군 비교로 정량 검증한다 |
| **②** | **알고리즘에 의한 센서 대체** | [2]가 센서를 물리적으로 통합했다면, 본 연구는 **추정식·거리 게이트·모터 전류**로 센서 자체를 제거한다 |
| **③** | **센서리스 끼임 방지를 시뮬레이션에서 정량 검증** | 자동차 anti-pinch 기술을 **주거 창호에 이식**하고, 실물로는 반복 불가능한 끼임 실험을 반복 수행해 **최대 접촉 반력을 정량 측정**한다 |

---

## 4. 기술 참고자료

### 4.1 센서리스 Anti-pinch

| # | 자료 | 활용 |
|---|---|---|
| T1 | *Research on Anti-pinch Control Strategy for Low-cost Automotive Electric Window* (2024) | **저비용 anti-pinch 제어 전략의 직접 근거.** 적응형 임계값 개념 |
| T2 | *Automatic Threshold on Current based Anti-pinch Mechanism for Power Windows* | 고정 임계값 대신 **자동 임계값** 기법 |
| T3 | *Safety mechanism design for automotive power windows using Hall sensor* | Hall 방식과의 대비 (본 연구는 Ripple 방식 채택) |
| T4 | 특허 **CN202450928U** — 무센서 파워윈도우 anti-pinch | **센서 없는 구성의 선행 특허** |
| T5 | 특허 **US6788016** — Motor speed-based anti-pinch control with **endzone ramp detection and compensation** | **Zone C 엔드존 보상의 직접 근거** |
| T6 | Texas Instruments, *Sensorless stall detection* (SLYP727) | back-EMF 임계값 기반 스톨 검출의 한계 |
| T7 | STMicroelectronics, AN1946 — *Sensorless BLDC motor control and BEMF sampling* | 저속에서 back-EMF 검출이 어려워지는 근거 |

### 4.2 기구 설계

| # | 자료 | 활용 |
|---|---|---|
| M1 | 특허 **KR20090056308A** — 창문 자동 개폐장치 | **랙-피니언 구동 방식의 선행 기술.** 창틀에 랙, 패널에 피니언 |
| M2 | 특허 KR101789878B1 — 자동 미닫이 창문 | 미닫이 자동화 일반 |
| M3 | *Linear actuators: belt driven vs. rack and pinion driven* | 벨트 대비 랙-피니언의 **정지·기동 정밀도** 우위 근거 |

### 4.3 기준·표준

| # | 자료 | 활용 |
|---|---|---|
| S1 | **KS A 3011** 조도기준 | 조명 모드 목표 조도 근거 (독서 300–750 lux, 거실 100–200 lux, 침실 60–150 lux) |
| S2 | **FMVSS 118** (미 연방 자동차 안전기준, 파워윈도우) | **최대 접촉 반력 100 N 상한**의 참조 기준 |
| S3 | Lee et al., *Melatonin suppression and sleepiness in children exposed to blue-enriched white LED lighting at night*, Physiological Reports, 2018 | **수면 모드 저색온도(2700 K)** 근거. 6200 K가 3000 K보다 멜라토닌 억제가 크다 |
| S4 | *Home lighting, blue-light filtering, and their effects on melatonin suppression*, Scientific Reports, 2025 | 냉백색 LED 멜라토닌 억제율 12.3 % vs 온백색 3.6 % |

### 4.4 시뮬레이션 환경

| # | 자료 | 활용 |
|---|---|---|
| E1 | NVIDIA Isaac Sim — **Effort Sensor** 공식 문서 | Prismatic 조인트의 **힘 측정** → 전류 환산의 근거 |
| E2 | NVIDIA Isaac Sim — Contact Sensor / Sensors 문서 | 접촉 반력 실측 · 가용 센서 목록 (**조도 센서 부재 확인**) |
| E3 | NVIDIA Developer Forums — *Measure Light info* | **"조도 측정 내장 도구 없음"** 공식 답변 → 해석 모델 채택 근거 |

### 4.5 재실 감지

| # | 자료 | 활용 |
|---|---|---|
| O1 | HLK-LD2410 데이터시트 (Hi-Link) | 24 GHz FMCW, 정지 5 m / 이동 6 m, ±60°, **0.75 m 거리 게이트 8개** |
| O2 | ESP32 mmWave + PIR Presence Fusion (ESPHome) | **"PIR-validates, mmWave-holds"** 융합 전략의 근거 |
| O3 | HC-SR501 데이터시트 | 최대 7 m, 110°, **움직임 기반 감지의 한계** |

### 4.6 공공 데이터 API

| # | 자료 | 활용 |
|---|---|---|
| A1 | **기상청 단기예보 API** | 강우 여부 — 우적 센서 대체 (부품비 0원) |
| A2 | **에어코리아 대기오염정보 API** | 실외 미세먼지 — 외기 등급 · **v3.0: 실내 PM 실측과 교차 확인 · 요리 판별의 외기 유입 예측 입력** |

### 4.7 공기질 · 결로 · 열쾌적 (v3.0 추가)

| # | 자료 | 활용 |
|---|---|---|
| Q1 | Satish et al., *Is CO₂ an Indoor Pollutant?*, Environmental Health Perspectives, 2012 | **공부 모드 CO₂ 800 ppm** 근거 — 1,000 ppm 이상에서 의사결정 수행 저하 |
| Q2 | Allen et al., *Associations of Cognitive Function Scores with CO₂, Ventilation, and VOC Exposures*, EHP, 2016 | 환기량과 인지 기능의 관계 — 수요 환기의 필요성 |
| Q3 | **실내공기질 관리법 시행규칙** 실내공기질 유지기준 | **CO₂ 1,000 ppm** — 일반 · 수면 모드 상한 |
| Q4 | **환경부 미세먼지 예보 등급** (PM2.5) | 좋음 0–15 · 보통 16–35 · 나쁨 36–75 · 매우나쁨 76 이상 µg/m³ — 등급형 제약(C8) |
| Q5 | **WHO Global Air Quality Guidelines**, 2021 | PM2.5 실내 목표 15 µg/m³ 근거 (24시간 지침값) |
| Q6 | Abdullahi, Delgado-Saborit, Harrison, *Emissions and indoor concentrations of particulate matter … from cooking: A review*, Atmospheric Environment, 2013 | **요리 PM 발생원** 크기 범위 — 시나리오 주입값(1.5 mg/min) 근거 |
| Q7 | Alduchov & Eskridge, *Improved Magnus Form Approximation of Saturation Vapor Pressure*, J. Applied Meteorology, 1996 | **이슬점 Magnus 식** (본 설계 계수 b = 17.62, c = 243.12 °C — 실내 온도 범위에서 차이 무시 가능) |
| Q8 | 국토교통부 「**공동주택 결로 방지를 위한 설계기준**」 | 창호 결로 평가 개념 (실내외 온도차 · 표면온도) — 결로 여유 Δ 설계 근거 |
| Q9 | **ASHRAE Standard 55** — elevated air speed | 실링팬 기류의 체감온도 보정 → 냉방 목표 완화(규칙 I5) 근거 |
| Q10 | Winsen **MH-Z19C** · Plantower **PMS7003** 데이터시트 | NDIR 측정 범위 · 응답시간(T90) · 레이저 PM 측정 범위 |

### 4.8 다중 신호 · 에너지 (v3.1 추가 — 웹 확인 완료)

| # | 자료 | 활용 |
|---|---|---|
| F1 | Comai 외, *Sensors* 25(19):6221, 2025 | 마이크 1개 + ESP32로 물 사용 4종 90.6 % — 소리 기반 행동 인식의 근거 (확장 슬롯) |
| F2 | Hyun, *Sensors* 24(1):22, 2024 | YAMNet 2단계 물소리 분류 |
| F3 | Boovaraghavan 외 (Kirigami), *Proc. ACM IMWUT* 8(1), 2024 | 말소리 필터로 사생활 보호 · Cortex-M4F 동작 |
| F4 | Pantelic 외, *Scientific Reports*, 2024 | 원룸형 아파트 자동 공기질 제어 PM2.5 40 % 감소 · 피크 50 %↑ 감소 → **후드 선제 기동** 근거 |
| F5 | Kang 외, *Air Quality, Atmosphere & Health*, 2025 | 후드 + 보충 급기 PM2.5 96.9 % 제거 → 규칙 I3 근거 |
| F6 | Kang 외, *Building and Environment*, 2024 | 침실 CO₂ 1,000 ppm에서 수면 효율 저하 → 수면 모드 상한 근거 |
| F7 | Miller 외, *Energy and Buildings*, 2021 | 자동 실링팬 + 에어컨 압축기 에너지 36 % 절감 → 사다리 · I5 근거 |
| F8 | Niknami 외, *Energy and Buildings* 322, 2024 | 설정 1 °C 상향 57 W 감소 · 증발기 오염 영향 → 셋백 · 효율 저하 감지 |
| F9 | MPC for Residential Split AC, 2022 | 적응형 MPC 7.06 % 이상 절감 (IR 제어 인버터 에어컨) |
| F10 | 다이킨 여름(2016) · 겨울(2018) 검증 | 짧은 외출은 켜 두기 유리 — 제조사 실험(참고치) |
| F11 | 재실 예측 기반 사전 공조 (Energy and Buildings, 2021) | 귀가 예측 + 프리쿨링 개념 근거 |
| F14 | *Development, calibration, and validation of a novel gray-box energy model for residential split air conditioners* (OSTI 2418657) | **원룸형 벽걸이 에어컨 회색상자 모델 보정** — 전략 비교 모델 근거 |
| F15 | ASHRAE Guideline 14 — 변화점(change-point) 회귀 | 에너지 기준선 · 냉방도일 회귀 표준 (W14 원문 재확인) |
| F16 | Page, Robinson, Morel, Scartezzini, *A generalised stochastic model for the simulation of occupant presence*, Energy and Buildings, 2008 | 비균질 마르코프 재실 생성기 (W14 원문 재확인) |
| F12 | IEEE Std 802.11bf-2025 | Wi-Fi 센싱 표준 — 확장 아이디어 |
| F13 | 주택용 하계 누진 구간 (300 / 450 kWh) | 누진 방어 규칙 (선택) |
| F17 | 호텔 객실 재실 판정 — 문 + 동작 센서 로직 (US 8184004 *System to detect presence in a space* · Honeywell INNCOM 객실 센서) | **문이 닫힌 직후 사람이 있으면 다음 문 열림까지 재실** — v3.2 문 기반 재실 판정의 직접 근거 |
| F19 | 열 감지 레인지후드 (EP3137817A1 *Sensor-enabled range hood* · GE 자동 열 감지) | 후드 아래 서미스터 · 적외선 센서로 조리 열 감지 — **후드 아래 온도 센서**의 근거 |
| F20 | Safera Sense (레인지 위 조리 센서 · EN 50615 스토브 가드) · iGuardStove | 온도 + 공기질 + 사람 감지로 조리 인식 · 방치 경고 — **불 켜고 외출 경고** 근거 |
| F21 | 초음파 가습기 수돗물 → 실내 PM (University of Alberta 2020 · *Sci. Total Environ.* 2022) · National Academies 실내 PM2.5 보고서 | 실내 PM 발생원은 요리 외에도 가습기 · 향초 · 흡연 · 청소 — **미세먼지 원인 구분 · 센서 유지** 근거 |
| F18 | Google Home presence sensing · ecobee · Aqara FP300 (PIR + mmWave) | 상용 스마트홈의 재실 융합 방식 — 휴대폰 위치 + 기기 조작 + 센서, 센서가 휴대폰보다 우선 |

### 4.9 에너지 제어 방식 비교 연구 — 질문별 모델 vs LSTM vs 강화학습 (v3.4 추가 · 논문용)

> 실험 계획 · 비교 축 · 공정성 설계: [`10_energy_control_comparison_study.md`](10_energy_control_comparison_study.md) · 실험 EXP-5([`03` §5.2](03_scenarios.md) · [`08` §5.8](08_multisignal_energy.md))
> ⚠️ 표시는 초록 · 요약만 확인 — 인용 전 원문 확인

| # | 자료 | 활용 |
|---|---|---|
| G1 | Wang 외, *Applied Thermal Engineering* 228, 2023 | RL 3종(DDPG · DDQN · SAC) vs RC 기반 MPC를 **같은 가상 건물(BOPTEST)**에서 비교 — 비교 실험 설계의 기본 틀 |
| G2 | ⚠️ Mulayim 외, arXiv:2510.01475, 2025 (심사 중) | **실제 주택** RL vs MPC 각 1개월 — 절감 MPC 18.1 % · RL 20.9 %, RL 불쾌 신고 3건 · 개발 노력 비교 |
| G3 | Arroyo, Spiessens, Helsen, *Frontiers in Built Environment* 8, 2022 | MPC · RL · 혼합 방식 비교 |
| G4 | ⚠️ Kumkam 외, *Journal of Building Engineering* 112, 2025 | RL vs MPC 비교 (상세 미확인) |
| G5 | Vivian 외, *Journal of Building Engineering* 84, 2024 | 회색상자 vs 신경망(LSTM) 실내온도 예측 — **설정온도가 학습과 달라지면 LSTM 성능 급락**, 회색상자 안정 → `08` §5.2 LSTM 제외 근거의 검증 |
| G6 | ⚠️ Stoffel, Berktold, Müller, *Energy and Buildings* 305, 2024 | 실건물에서 여러 기계학습 모델을 MPC 예측 모델로 비교 — LSTM + MPC 구성 |
| G7 | Esrafilian-Najafabadi, Haghighat, *Energy and Buildings* 252, 2021 | 주거용 미리 공조 시작 시각을 딥러닝으로 추정 — **LSTM 방식의 기준** (F11과 같은 문헌) |
| G8 | ⚠️ Hou, Cheng, Ma 외, *Building and Environment* 284, 2025 | LSTM 재실 예측 + Dueling DQN — LSTM과 RL의 결합 |
| G9 | Esrafilian-Najafabadi, Haghighat, *Building and Environment* 226, 2022 | G7 저자의 후속 RL 연구 — 같은 문제를 LSTM과 RL로 푼 짝 |
| G10 | McKee 외, *IEEE PES General Meeting*, 2020 | 주거용 · 재실 고려 심층 RL (ORNL) |
| G11 | Wang, Lin, *Building and Environment* 244, 2023 | 주거용에서 데이터로 학습 환경 구성 후 RL (MF²) |
| G12 | Chen, Cai, Bergés, *ACM BuildSys*, 2019 | Gnu-RL — MPC 구조를 RL 정책에 넣어 적은 데이터로 학습 |
| G13 | Arroyo 외, *Applied Energy* 309, 2022 | RL-MPC — 순수 RL의 제약 위반 · 혼합 방식의 안전성 |
| G14 | Blum 외, *Journal of Building Performance Simulation* 14, 2021 | BOPTEST — 제어 방식 비교용 표준 가상 건물 · 지표 |
| G15 | Drgoňa 외, *Annual Reviews in Control* 50, 2020 | MPC 리뷰 |
| G16 | Wang, Hong, *Applied Energy* 269, 2020 | RL 리뷰 — 데이터 효율 · 안전 · 학습 환경 |
| G17 | Zhang 외, *IEEE Access* 10, 2022 | MPC + RL 서베이 |
| G18 | Jiménez-Raboso 외, *ACM BuildSys*, 2021 | Sinergym — RL 학습 환경 구성 참고 |

---

## 5. 인용 시 유의사항

| # | 유의점 |
|---|---|
| 1 | **[3]은 2018년 발표**로 3년을 초과한다. *"최신 동향"* 이 아니라 **"출발점이 된 선행연구"** 로 위치시킨다 |
| 2 | **[5]는 2013년**으로 더 오래되었다. PID 제어의 **고전적 기준**으로만 인용하고, 본 연구가 다른 목표(구동 최소화)를 가짐을 명시한다 |
| 3 | **[2]는 오픈액세스**이므로 전문 확보가 쉽다. 센서 최소화 논거의 주 인용으로 삼는다 |
| 4 | 원문·서지사항은 **RISS / DBpia에서 재확인**한다 (W14 최종 보고서 작성 시) |
| 5 | 특허(T4·T5·M1)는 **선행 기술**로 인용하되, 본 연구가 특허 회피를 목표로 하지 않음을 명확히 한다 (학술 목적) |

---

## 참고문헌 목록

### 국내 학술

1. 연승재, 김진혁, 정진우, 윤영무, 강은주, "IoT 기반 스마트홈 시스템 설계 및 구현," 대한산업공학회 추계학술대회 논문집, 2025.11, pp.3295–3299.
2. 박재민, 권오은, 김병규, 노우현, 박진우, 전준영, 고병철, "IoT 센서 기술을 이용한 원격 스마트 창문 제어," 한국정보과학회 2018 한국소프트웨어종합학술대회 논문집, 2018.12, pp.414–416.
3. 김경영, 이용환, 문상국, "PDLC 필름을 사용하는 스마트 창문," 한국정보기술학회 Proceedings of KIIT Conference, 2021.6, pp.578–580.
4. 장총민, 김성걸, "자동 조도 조절 블라인드 시스템 설계 및 제작에 대한 연구," 한국생산제조학회지, Vol.22, No.3-1, 2013, pp.615–621.

### 국외 학술

5. "Design and Validation of a Compact, Low-Cost Sensor System for Real-Time Indoor Environmental Monitoring," *Buildings* (MDPI), Vol.15, No.19, 3440, 2025.
6. Lee, S. et al., "Melatonin suppression and sleepiness in children exposed to blue-enriched white LED lighting at night," *Physiological Reports*, 2018.
7. "Home lighting, blue-light filtering, and their effects on melatonin suppression," *Scientific Reports*, 2025.
8. "Research on Anti-pinch Control Strategy for Low-cost Automotive Electric Window," 2024.
9. "Automatic Threshold on Current based Anti-pinch Mechanism for Power Windows."

### 특허

10. KR20090056308A, "창문 자동 개폐장치 및 이를 구비하는 창호 시스템."
11. US6788016B2, "Motor speed-based anti-pinch control apparatus and method with endzone ramp detection and compensation."
12. CN202450928U, "Anti-pinch control device of sensorless power window."

### 표준·기술문서

13. KS A 3011, "조도 기준," 한국산업표준.
14. FMVSS 118, "Power-Operated Window, Partition, and Roof Panel Systems," U.S. Federal Motor Vehicle Safety Standards.
15. Texas Instruments, "Sensorless stall detection," SLYP727.
16. STMicroelectronics, "Sensorless BLDC motor control and BEMF sampling methods," AN1946.
17. NVIDIA, "Isaac Sim Documentation — Effort Sensor / Sensors," 2026.

### v3.0 추가 (공기질 · 결로 · 열쾌적)

18. Satish, U. et al., "Is CO2 an Indoor Pollutant? Direct Effects of Low-to-Moderate CO2 Concentrations on Human Decision-Making Performance," *Environmental Health Perspectives*, 120(12), 2012.
19. Allen, J. G. et al., "Associations of Cognitive Function Scores with Carbon Dioxide, Ventilation, and Volatile Organic Compound Exposures in Office Workers," *Environmental Health Perspectives*, 124(6), 2016.
20. Abdullahi, K. L., Delgado-Saborit, J. M., Harrison, R. M., "Emissions and indoor concentrations of particulate matter and its specific chemical components from cooking: A review," *Atmospheric Environment*, 71, 2013.
21. Alduchov, O. A., Eskridge, R. E., "Improved Magnus Form Approximation of Saturation Vapor Pressure," *Journal of Applied Meteorology*, 35(4), 1996.
22. World Health Organization, "WHO Global Air Quality Guidelines," 2021.
23. 환경부, "미세먼지(PM2.5) 예보 등급 기준."
24. 「실내공기질 관리법 시행규칙」, 실내공기질 유지기준.
25. 국토교통부, 「공동주택 결로 방지를 위한 설계기준」.
26. ASHRAE Standard 55, "Thermal Environmental Conditions for Human Occupancy."
27. Winsen, "MH-Z19C NDIR CO2 Sensor Datasheet" · Plantower, "PMS7003 Datasheet."

### v3.4 추가 (에너지 제어 방식 비교 연구 — §4.9)

28. Wang, D., Zheng, W., Wang, Z. et al., "Comparison of reinforcement learning and model predictive control for building energy system optimization," *Applied Thermal Engineering*, 228, 120430, 2023. doi:10.1016/j.applthermaleng.2023.120430
29. Mulayim, O. B., Pergantis, E. N., Reyes Premer, L. D., Chen, B., Qu, G., Kircher, K. J., Bergés, M., "Comparative Field Deployment of Reinforcement Learning and Model Predictive Control for Residential HVAC," arXiv:2510.01475, 2025 (preprint).
30. Arroyo, J., Spiessens, F., Helsen, L., "Comparison of Optimal Control Techniques for Building Energy Management," *Frontiers in Built Environment*, 8, 849754, 2022. doi:10.3389/fbuil.2022.849754
31. Kumkam, S., Trinuruk, P., Chaiwiwatworakul, P., Saito, K., "A comparative analysis of reinforcement learning and model predictive control for HVAC system optimization," *Journal of Building Engineering*, 112, 113776, 2025. doi:10.1016/j.jobe.2025.113776
32. Vivian, J., Prataviera, E., Gastaldello, N., Zarrella, A., "A comparison between grey-box models and neural networks for indoor air temperature prediction in buildings," *Journal of Building Engineering*, 84, 108583, 2024. doi:10.1016/j.jobe.2024.108583
33. Stoffel, P., Berktold, M., Müller, D., "Real-life data-driven model predictive control for building energy systems comparing different machine learning models," *Energy and Buildings*, 305, 113895, 2024. doi:10.1016/j.enbuild.2024.113895
34. Esrafilian-Najafabadi, M., Haghighat, F., "Occupancy-based HVAC control using deep learning algorithms for estimating online preconditioning time in residential buildings," *Energy and Buildings*, 252, 111377, 2021. doi:10.1016/j.enbuild.2021.111377
35. Hou, F., Cheng, J. C. P., Ma, J. et al., "Occupancy-driven HVAC control optimization via LSTM and deep reinforcement learning for enhanced indoor air quality, thermal comfort and energy efficiency," *Building and Environment*, 284, 113501, 2025. doi:10.1016/j.buildenv.2025.113501
36. Esrafilian-Najafabadi, M., Haghighat, F., "Towards self-learning control of HVAC systems with the consideration of dynamic occupancy patterns: Application of model-free deep reinforcement learning," *Building and Environment*, 226, 109747, 2022. doi:10.1016/j.buildenv.2022.109747
37. McKee, E., Du, Y., Li, F. et al., "Deep Reinforcement Learning for Residential HVAC Control with Consideration of Human Occupancy," *2020 IEEE PES General Meeting*, 1–5, 2020. doi:10.1109/PESGM41954.2020.9281893
38. Wang, M., Lin, B., "MF²: Model-free reinforcement learning for modeling-free building HVAC control with data-driven environment construction in a residential building," *Building and Environment*, 244, 110816, 2023. doi:10.1016/j.buildenv.2023.110816
39. Chen, B., Cai, Z., Bergés, M., "Gnu-RL: A precocial reinforcement learning solution for building HVAC control using a differentiable MPC policy," *Proc. ACM BuildSys 2019*, 316–325, 2019. doi:10.1145/3360322.3360849
40. Arroyo, J., Manna, C., Spiessens, F., Helsen, L., "Reinforced model predictive control (RL-MPC) for building energy management," *Applied Energy*, 309, 118346, 2022. doi:10.1016/j.apenergy.2021.118346
41. Blum, D., Arroyo, J., Huang, S. et al., "Building optimization testing framework (BOPTEST) for simulation-based benchmarking of control strategies in buildings," *Journal of Building Performance Simulation*, 14(5), 586–610, 2021. doi:10.1080/19401493.2021.1986574
42. Drgoňa, J., Arroyo, J., Cupeiro Figueroa, I. et al., "All you need to know about model predictive control for buildings," *Annual Reviews in Control*, 50, 190–232, 2020. doi:10.1016/j.arcontrol.2020.09.001
43. Wang, Z., Hong, T., "Reinforcement learning for building controls: The opportunities and challenges," *Applied Energy*, 269, 115036, 2020. doi:10.1016/j.apenergy.2020.115036
44. Zhang, H., Seal, S., Wu, D. et al., "Building Energy Management With Reinforcement Learning and Model Predictive Control: A Survey," *IEEE Access*, 10, 27853–27862, 2022. doi:10.1109/ACCESS.2022.3156581
45. Jiménez-Raboso, J., Campoy-Nieves, A., Manjavacas-Lucas, A. et al., "Sinergym: a building simulation and control framework for training reinforcement learning agents," *Proc. ACM BuildSys 2021*, 319–323, 2021. doi:10.1145/3486611.3488729

---

## 변경 이력

| 일자 | 버전 | 내용 |
|---|---|---|
| 2026-09-12 | v1.0 | 신규 작성. 국내외 학술 문헌 9편 · 특허 3건 · 표준 5건 정리. 선행연구 대비표 및 학술적 기여 3가지 명시 |
| 2026-10-05 | **v1.2** | **피드백 2 반영** — §4.8 다중 신호 · 에너지 참고자료 13건 (웹 확인 완료) |
| 2026-10-05 | **v1.1** | **기획 v3.0 반영** — §4.7 공기질 · 결로 · 열쾌적 참고자료 10건, 참고문헌 18–27 추가 · 에어코리아 API 용도 갱신. ⚠️ 서지사항(권·호·면)은 W14 최종 보고서 작성 시 원문으로 재확인 |
| 2026-10-07 | **v1.3** | **§4.9 에너지 제어 방식 비교 연구 (논문용)** — 질문별 모델 vs LSTM vs 강화학습 벤치마킹 문헌 G1–G18 · 참고문헌 28–45 (Crossref · arXiv로 서지 확인, ⚠️ 4건은 원문 미확인) |
