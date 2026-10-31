# 16. 논문 계획 — Smart Structures and Systems (Techno-Press) 투고

> 2026-11-01 · 사용자 결정 기록 · 양식 교차 검증 · 구성안 (본문 작성 전 확인용)
> 원칙: **불분명한 부분은 반드시 사용자 확인 뒤 진행** (사용자 지시 2026-11-01) · 새 실험 없음 · 수치 출처는 `archive/` · docs/12 · 13 · 15 · 보고서

## 1. 사용자 결정 (2026-11-01)

| 항목 | 결정 |
|---|---|
| 투고처 | Smart Structures and Systems (Techno-Press · ISSN 1738-1584 / 1738-1991 · SCIE) |
| 주제 | 기존 연구와 달리 협조 제어 시뮬레이션을 구현하고 여러 제어 방식을 비교해 기존 방식과의 차이를 보인다 |
| 비교 구성 | **두 축 · 새 실험 없음** — 축 1 시스템 전체: 협조 제어 vs A · A′ · A′V · B / 축 2 에너지 핵심 결정: 질문별 모델 vs LSTM vs 강화학습 vs 단순 규칙 (EXP-5) |
| 결과 범위 | 냉방 주 결과(v1.29 · 보류 7차) + 난방 확장(v1.31-H 확정) · 사후 개선(v1.32 · v1.33-H)은 짧게 |
| 범위 적합성 | SSS 범위(Sensors/Actuators · Control)에 맞춰 **'저가 센서 · 액추에이터 네트워크의 협조 제어 + 센서리스 액추에이터'** 로 구성 |
| 언어 · 진행 | 영어 원고 + 절마다 한국어 검토본 — 절 단위로 확인받으며 진행 |
| 분량 | 템플릿 기준 18–22쪽 · 그림 10–12 · 표 5–6 · 참고문헌 40–50 |
| 표 캡션 | 템플릿 따름 — **표 위 · 왼쪽 정렬** (가이드의 'bottom left-aligned' 와 불일치 → 투고 전 편집부 확인 목록) |

## 2. 양식 교차 검증 (2026 템플릿 `TP_Template(2026).docx` ↔ 공식 Authors' Guide · 2026-11-01 확인)

| 항목 | 규정 (원고에 적용) | 근거 |
|---|---|---|
| 용지 · 단 · 여백 | A4 · 1단 · 위 5.0 / 아래 4.0 / 좌우 2.8 cm · 머리글 1.5 · 바닥글 1.75 cm | 템플릿 sectPr (옛 안내문의 2단 · 15 pt 는 구판) |
| 제목 | Arial 16 pt · 2줄 이내 · 첫 글자만 대문자 | 두 곳 일치 |
| 저자 · 소속 | 저자 Arial 12 pt · 소속 Arial 9.5 pt 이탤릭 · 교신저자 각주 TNR 10 pt | 가이드 |
| 머리글 | 저자 이니셜 + 성 (3인 이상 'et al.') · 제목 | 가이드 · 템플릿 header1 · 2 |
| 초록 | TNR 10.5 pt · 약 250단어 · 한 문단 · 인용 · 식 · 그림 · 표 없음 | 두 곳 일치 |
| 키워드 | 알파벳 순 · 소문자 · 세미콜론 · TNR 10.5 pt | 두 곳 일치 |
| 본문 | TNR 11 pt · 첫 줄 0.5 cm 들여쓰기 | 가이드 |
| 절 제목 | 1단계 Arial 11 pt 굵게 · 2–3단계 Arial 11 pt 0.5 cm 들여쓰기 · 4단계 밑줄 · 첫 글자만 대문자 | 가이드 |
| 인용 | 숫자 [1], [2, 3], [5-8] · **파란색** · 등장 순 · 'et al.' 정자체 | 가이드 |
| 그림 | JPG · PNG · **하위 그림도 파일 따로** · 캡션 'Figure 1.' 아래 가운데 TNR 10 pt · 본문 'Fig. 1' 파란색 | 가이드 |
| 수식 | Word 수식 · 가운데 · 번호 오른쪽 · 본문 'Eq. (1)' 파란색 | 가이드 |
| 표 | 'Table 1.' TNR 10 pt · 내용 가운데 · 캡션 위치는 §1 결정 | 가이드 · 템플릿 |
| 결론 | 목록이 아닌 문단 | 가이드 |
| 참고문헌 | APA · 등장 순 번호(Word 번호 매기기) · 0.63 cm · 굵게 · 기울임 없음 · DOI 링크 · 마침표로 끝 · TNR 10 pt | 가이드 · 템플릿 |
| 투고 | 영어 · PDF · ManuscriptLink | 학술지 페이지 |
| 미확인 | 쪽수 제한 · 게재료 · 표 캡션 위치 · 범위 적합성 | 투고 전 편집부 확인 목록 |

## 3. 구성안 (확인 대기)

**제목 후보** (16 pt · 2줄 이내)
1. Cooperative control of a low-cost sensor–actuator network for conflicting indoor goals in single-room dwellings
2. Coordinating appliances as actuators: pre-registered simulation comparison of cooperative, rule-based and learning-based smart-home control
3. Cost-ordered cooperative control of retrofit sensors and household actuators in a studio apartment: a simulation study with commercial-grade and learning-based baselines

| 절 | 내용 | 그림 · 표 (안) |
|---|---|---|
| 1 Introduction | 한 방의 목표 충돌 · 기존 접근(기기별 자동 · 상용 규칙 허브 · MPC/RL 은 대개 단일 장치 · 데이터 많은 조건) · 공백 · 기여 4 (① 비용 순 수단 사다리 + 계층 중재로 11 액추에이터 + 보일러 협조 ② 센서리스 창문 액추에이터 ③ 상용 수준 기준선 사전 고정 · 사전 등록 보류 평가 · 결과 기준 판정 · 외부 에뮬레이터 ④ 두 축 비교) | — |
| 2 Related work | 스마트홈 자동화 · 건물 제어 MPC/RL · 실내 환경 다목적 제어 · 센서리스 액추에이터 · 시뮬레이션 평가 신뢰성(BOPTEST) | Table 1 기존 연구 대비 |
| 3 System | 원룸 3.5 × 5 m · 센서 7 + 비센서 3 · 액추에이터 11 + 보일러 · 부품비 · ROS 2 · 두 실행 모드 · 참값(3R3C · 온수 바닥난방) ↔ 제어 모델 분리 | Fig. 1 시스템 · Table 2 센서 · 액추에이터 · 비용 |
| 4 Control method | 모드 · 이벤트 · 규칙 · 6계층 중재 · 수단 사다리(냉방 · 제습 · PM · 난방) · 가전 보호 L0 · 센서리스 창문(리플 · 반력) | Fig. 2 제어 흐름 · Fig. 3 센서리스 궤적 |
| 5 Evaluation method | 시나리오(41 + 난방 18) · 기준선 A · A′ · A′V · B · 학습 방식(EXP-5) · 판정 3분류 · 지표(통과율 · 기대비용) · 무작위 · 실측 기상(ERA5 · ASOS) · 사전 등록 보류 · 통계(묶음 부트스트랩 · McNemar · 부호 · Holm) · BOPTEST | Table 3 기준선 명세 · Fig. 4 평가 절차 |
| 6.1 Axis 1 — cooling season | 통과율 · 효과 크기 · 쾌적 ↔ 비용 | Fig. 5 · 6 · 7 · Table 4 |
| 6.2 Generalization · robustness | 보류 7차 · 센서 결함 · 임계값 · 물리 무작위 · 기상 출처 | Fig. 8 |
| 6.3 Heating-season extension | v1.31-H 확정 주 비교 · 보류 3 · 4차 · BOPTEST 2구역 · 사후 개선 요약 | Fig. 9 · Table 5 |
| 6.4 Axis 2 — learning-based | EXP-5 질문별 모델 · LSTM · RL · 단순 규칙 | Fig. 10 · Table 6 |
| 6.5 Sensorless window safety | 끼임 165/165 · 86.5 N | Fig. 11 |
| 7 Discussion | 데이터가 적을 때 구조화된 협조가 결과를 좌우 · 평가 장치가 찾아낸 결함 · 한계 | — |
| 8 Conclusions | 문단 | — |

## 4. 받아야 할 정보 (사용자)
- 저자 순서 · 영문 이름 · 소속(학과 · 기관 · 주소 · 국가) · 교신저자 · 직위 · 이메일
- 감사의 글(연구비 · 지원) 유무

## 변경 이력
| 날짜 | 버전 | 내용 |
|---|---|---|
| 2026-11-01 | v0.1 | 사용자 결정 · 양식 교차 검증 · 구성안 (본문 작성 전) |
