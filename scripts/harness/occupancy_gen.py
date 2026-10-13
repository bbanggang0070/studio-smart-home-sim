"""비균질 마르코프 재실 생성기 (docs/08 §5.8 · T10.w2) — 페르소나별 12주 재실 이력.

5분 단위 2상태(집 1 · 외출 0). 시간대 h 의 '집에 있을 확률' p(h) 와 평균 머무름 tau 로
    P(외출→집) = dt/tau · p(h)      P(집→외출) = dt/tau · (1 − p(h))
날마다 근무 형태(day_types: 가중치는 평일 · 주말 따로)를 뽑아 p(h) 를 바꾼다.
'주 외출' = min_absence_h 이상 이어진 외출 — 출발 · 귀가 시각을 이벤트로 뽑는다 (EXP-2 의 학습 · 평가 단위).
설정: config/harness.yaml occupancy_generator
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Absence:
    day: int            # 출발한 날 (0부터)
    weekday: int        # 0 = 월
    day_type: str
    depart_tod_s: float  # 출발 시각 (그날 0시 기준 초)
    arrive_tod_s: float  # 귀가 시각 (출발한 날 0시 기준 — 다음날이면 86400 이상)


def generate(cfg: dict, persona: str, weeks: int | None = None, seed: int | None = None) -> tuple[np.ndarray, list[str]]:
    """→ (재실 배열 [날 × 슬롯], 날별 근무 형태). 첫날은 월요일 0시 · 집."""
    pc = cfg["personas"][persona]
    rng = np.random.default_rng(pc["seed"] if seed is None else seed)
    dt = float(cfg["dt_min"])
    k = dt / float(cfg["tau_min"])
    slots = int(round(24 * 60 / dt))
    days = 7 * int(cfg["weeks"] if weeks is None else weeks)
    names = list(pc["day_types"])
    occ = np.zeros((days, slots), dtype=np.int8)
    types: list[str] = []
    state = 1
    for d in range(days):
        weekend = d % 7 >= 5
        w = np.array([pc["day_types"][n]["weight_weekend" if weekend else "weight_weekday"] for n in names], float)
        name = names[int(rng.choice(len(names), p=w / w.sum()))]
        types.append(name)
        p_home = np.asarray(pc["day_types"][name]["p_home"], float)
        for s in range(slots):
            p = p_home[int(s * dt // 60)]
            if state == 0 and rng.random() < k * p:
                state = 1
            elif state == 1 and rng.random() < k * (1.0 - p):
                state = 0
            occ[d, s] = state
    return occ, types


def absences(occ: np.ndarray, types: list[str], cfg: dict) -> list[Absence]:
    """주 외출 목록 — min_absence_h 이상 이어진 외출 구간의 출발 · 귀가."""
    dt_s = float(cfg["dt_min"]) * 60.0
    flat = occ.reshape(-1)
    slots = occ.shape[1]
    min_len = int(round(float(cfg["min_absence_h"]) * 3600.0 / dt_s))
    out: list[Absence] = []
    i = 0
    while i < flat.size:
        if flat[i] == 0:
            j = i
            while j < flat.size and flat[j] == 0:
                j += 1
            if j - i >= min_len and j < flat.size and i > 0:
                d = i // slots
                out.append(Absence(d, d % 7, types[d], (i % slots) * dt_s, (j - d * slots) * dt_s))
            i = j
        else:
            i += 1
    return out
