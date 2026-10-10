"""에너지 예측 · 외출 전략 (docs/08 §5.3 · §5.4 · 이벤트 E13 프리쿨링).

ROS 비의존 순수 Python. 학습 산출물(models/energy_<persona>.yaml)을 읽는다 — 만드는 쪽은 tools/energy/train_energy_model.py.

  귀가 분포   학습 기간의 귀가 시각 이력 → 부트스트랩 표본 (경험 분포 · arrival_model 'empirical')
              분위수 GBM(quantile_gbm)은 요일 · 외출 시각 특성이 쌓이는 W11 EXP-2 에서 비교한다
  열모델      제어용 2R2C (공기 · 축열 질량) — 기록 데이터로 식별한 R · C · 이득 (참값 3R3C 와 다르다, §5.3-1)
                Ca·dT/dt  = (Tm−T)/Rim + (To−T)/Rao + gs·L + go·occ + q0 − η·Q_ac
                Cm·dTm/dt = (T−Tm)/Rim + (To−Tm)/Rmo
              L = 실내 주광 조도(천장 센서 − 자기 조명) — 일사 대리 변수 · 축열 질량 온도는 관측기로 추정
  전략        셋백(+2 °C 유지) · 끄기(귀가 후 냉방) · 끄기 + 프리쿨링(시작 시각 격자) 의 기대비용
                비용 = E[전력량 Wh] + λ · w · E[귀가 후 불쾌 K·h]     (λ = user_modes energy.comfort_weight)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[2]


@dataclass
class Thermal2R2C:
    ca: float          # Wh/K
    cm: float
    rim: float         # K/W
    rao: float
    rmo: float
    gs: float          # W/lux
    go: float          # W/인
    q0: float          # W
    eta: float         # 에어컨 전력 → 제거 열량 배율 (명판 COP 보정)

    @classmethod
    def from_dict(cls, d: dict[str, float]) -> "Thermal2R2C":
        return cls(**{k: float(d[k]) for k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, float]:
        return {k: float(getattr(self, k)) for k in self.__dataclass_fields__}

    def step(self, t: float, tm: float, to: float, lux: float, occ: float, q_ac: float, dt_h: float):
        """한 보폭 (오일러) — q_ac = 제거 열량 W (전력 × 명판 COP × η)."""
        dt = (tm - t) / self.rim + (to - t) / self.rao + self.gs * lux + self.go * occ + self.q0 - self.eta * q_ac
        dtm = (t - tm) / self.rim + (to - tm) / self.rmo
        return t + dt_h * dt / self.ca, tm + dt_h * dtm / self.cm


@dataclass
class AcSpec:
    """제어기가 아는 에어컨 명판 값 (thresholds appliances.ac) — 참값 모델의 계수가 아니다."""
    capacity_w: float
    cop: float
    modulation_w_per_k: float
    band_c: float

    def removal(self, t: float, sp: float) -> float:
        if t < sp - self.band_c:
            return 0.0
        return min(self.capacity_w, self.modulation_w_per_k * (t - sp + self.band_c))


class EnergyPlanner:
    """외출 중 1분마다 부른다 — 전략 · 프리쿨링 시작 시각을 정한다 (E13)."""

    def __init__(self, p, model_file: str | Path, comfort_weight: float, strategy: str = "auto"):
        g = p.get
        e = "energy."
        path = Path(model_file)
        if not path.is_absolute():
            path = REPO / path
        with open(path, encoding="utf-8") as f:
            m = yaml.safe_load(f)
        self.model = Thermal2R2C.from_dict(m["thermal_2r2c"])
        self.arrivals = np.asarray(m["arrival_history_tod_s"], dtype=float)
        ac = g("appliances.ac")
        self.ac = AcSpec(ac["cooling_kw"] * 1000.0, ac["cooling_kw"] * 1000.0 / ac["power_w"],
                         g(e + "planner.ac_modulation_w_per_k"), g(e + "planner.ac_band_c"))
        self.grid_s = g(e + "precool_optimizer.grid_min") * 60.0
        self.n_samples = int(g(e + "precool_optimizer.samples"))
        self.setback_c = g(e + "away_strategy.setback_c")
        self.lam = comfort_weight
        self.w = g(e + "planner.discomfort_wh_per_kh")
        self.margin = g(e + "planner.discomfort_margin_c")
        self.horizon_after_s = g(e + "planner.after_arrival_horizon_min") * 60.0
        self.dt_s = g(e + "planner.sim_step_s")
        self.replan_s = self.grid_s
        self.timeout_s = g("events.precool.timeout_after_pred_min") * 60.0
        self.strategy_setting = strategy
        self.rng = np.random.default_rng(int(g(e + "planner.sample_seed")))
        self.switch_margin = g(e + "planner.switch_margin_wh")
        self.reset()

    def reset(self) -> None:
        self.t_hat: float | None = None
        self.tm_hat: float | None = None
        self.end_away()

    def end_away(self) -> None:
        """귀가 — 계획 · 프리쿨링 상태를 지운다 (관측기 상태는 유지)."""
        self.decision: dict[str, Any] = {}
        self._last_plan: float | None = None
        self.precool_started: float | None = None

    # ---- 관측기 — 축열 질량 온도는 재지 않으므로 모델로 따라간다 ----

    def observe(self, t_meas: float, t_out: float, lux: float, occ: float, ac_w: float, dt_s: float) -> None:
        if self.t_hat is None:
            self.t_hat = self.tm_hat = t_meas
            return
        q = ac_w * self.ac.cop
        _, self.tm_hat = self.model.step(self.t_hat, self.tm_hat, t_out, lux, occ, q, dt_s / 3600.0)
        self.t_hat = t_meas                         # 공기 온도는 측정값으로 바로잡는다

    # ---- 계획 ----

    def _arrival_samples(self, now_tod: float) -> np.ndarray:
        """학습 이력에서 부트스트랩 — 이미 지난 시각의 표본은 버린다 (조건부 분포)."""
        later = self.arrivals[self.arrivals > now_tod]
        if later.size == 0:
            later = np.array([now_tod + self.grid_s])
        return self.rng.choice(later, size=self.n_samples, replace=True)

    def _simulate(self, now_tod: float, t0: float, tm0: float, t_out: float, lux_fn, sp: float,
                  start_tod: float | None, setback: bool, arrive_tod: float) -> tuple[float, float]:
        """→ (전력량 Wh, 귀가 후 불쾌 K·h). start_tod = 프리쿨링 시작 (None = 귀가 때)."""
        t, tm, e_wh, disc = t0, tm0, 0.0, 0.0
        dt_h = self.dt_s / 3600.0
        tod = now_tod
        end = arrive_tod + self.horizon_after_s
        while tod < end:
            home = tod >= arrive_tod
            if home or (start_tod is not None and tod >= start_tod):
                q = self.ac.removal(t, sp)
            elif setback:
                q = self.ac.removal(t, sp + self.setback_c)
            else:
                q = 0.0
            e_wh += q / self.ac.cop * dt_h
            if home:
                disc += max(0.0, t - (sp + self.margin)) * dt_h
            t, tm = self.model.step(t, tm, t_out, lux_fn(tod), 1.0 if home else 0.0, q, dt_h)
            tod += self.dt_s
        return e_wh, disc

    def plan(self, now_tod: float, t_out: float, lux_fn, sp: float) -> dict[str, Any]:
        """세 전략의 기대비용 → 결정. 반환: {strategy, start_tod, costs, q20, q50, q80}."""
        arr = self._arrival_samples(now_tod)
        # 계산량을 줄이려 표본을 분위수 대표값으로 묶는다 (같은 분포 · 등가중)
        qs = np.quantile(arr, np.linspace(0.05, 0.95, 10))
        t0, tm0 = self.t_hat, self.tm_hat

        def expected(start_tod, setback):
            costs = [self._simulate(now_tod, t0, tm0, t_out, lux_fn, sp, start_tod, setback, a) for a in qs]
            e = float(np.mean([c[0] for c in costs]))
            d = float(np.mean([c[1] for c in costs]))
            return e + self.lam * self.w * d, e, d

        cands: list[tuple[str, float | None, float, float, float]] = []
        c, e, d = expected(None, True)
        cands.append(("setback", None, c, e, d))
        c, e, d = expected(None, False)
        cands.append(("off", None, c, e, d))
        tod = now_tod
        while tod <= float(np.quantile(arr, 0.9)):
            c, e, d = expected(tod, False)
            cands.append(("precool", tod, c, e, d))
            tod += self.grid_s
        allowed = {"auto": ("setback", "off", "precool"), "setback": ("setback",), "off": ("off",),
                   "precool": ("precool",)}[self.strategy_setting]
        best = min((x for x in cands if x[0] in allowed), key=lambda x: x[2])
        prev = self.decision.get("strategy")
        if prev and prev != best[0] and prev in allowed:   # 히스테리시스 — 충분히 나아질 때만 전략을 바꾼다
            keep = min((x for x in cands if x[0] == prev), key=lambda x: x[2])
            if keep[2] - best[2] < self.switch_margin:
                best = keep
        best_pre = min((x for x in cands if x[0] == "precool"), key=lambda x: x[2], default=None)
        self.decision = {
            "strategy": best[0], "start_tod": best[1], "cost": round(best[2], 1),
            "energy_wh": round(best[3], 1), "discomfort_kh": round(best[4], 3),
            "cost_setback": round(cands[0][2], 1), "cost_off": round(cands[1][2], 1),
            "cost_precool_best": round(best_pre[2], 1) if best_pre else -1.0,
            "arrival_q20": float(np.quantile(arr, 0.2)), "arrival_q50": float(np.quantile(arr, 0.5)),
            "arrival_q80": float(np.quantile(arr, 0.8)),
        }
        return self.decision

    def step(self, now_tod: float, t_out: float, lux_fn, sp: float) -> dict[str, Any]:
        """외출 중 매 주기 — 재계획(격자 주기) · 프리쿨링 시작 판단. 반환 decision + active."""
        if self.precool_started is None and (self._last_plan is None or now_tod - self._last_plan >= self.replan_s):
            self.plan(now_tod, t_out, lux_fn, sp)
            self._last_plan = now_tod
        d = self.decision
        if (self.precool_started is None and d.get("strategy") == "precool"
                and d.get("start_tod") is not None and now_tod >= d["start_tod"]):
            self.precool_started = now_tod
        active = self.precool_started is not None
        # 예측 귀가 80분위 + 60분이 지나도 안 오면 끝낸다 (E13 해제)
        if active and now_tod > d.get("arrival_q80", math.inf) + self.timeout_s:
            active = False
        return {**d, "precool_active": active}


def daylight_fn(p, now_tod: float, lux_now: float):
    """앞으로의 실내 주광 — 맑은 날 해 고도 모양을 지금 측정값에 맞춰 늘린다 (일사 예보 없음)."""
    g = p.get
    v = "virtual_sensors.lux."
    rise, sset = g(v + "sunrise_h") * 3600.0, g(v + "sunset_h") * 3600.0

    def shape(tod: float) -> float:
        tod = tod % 86400.0
        return math.sin(math.pi * (tod - rise) / (sset - rise)) if rise < tod < sset else 0.0

    s_now = shape(now_tod)
    k = lux_now / s_now if s_now > 0.05 else 0.0
    return lambda tod: k * shape(tod)
