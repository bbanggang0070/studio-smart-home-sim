"""후드 단수 예측 선택 (docs/06 §3.3 · docs/07 §5.4) — 제어용 PM 모델.

후드 {끔, 약, 강} 3안 각각에 대해 '그 안을 고르면 함께 쓸 급기 · 청정기'를 포함해 10분 앞까지 실내 PM 을 예측하고,
피크가 최선안의 (1 + 허용 비율) 이내인 안 가운데 **가장 낮은 단**을 고른다 (싼 수단부터 — 소음 · 음압 · 에너지).

발생량은 PM 기울기 잔차로 추정한다:  S ≈ V·dP/dt + (Q_oa + CADR + k·V)·P − 유입항
진입 직후(이력이 짧을 때)는 사전값(nominal)을 쓴다. 상수는 모두 thresholds.yaml — 참값 모델과 공유하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from controller.params import ControllerParams

MG_PER_MIN_TO_UG_PER_H = 60_000.0


@dataclass
class Plan:
    hood_level: int
    intake_m3h: float
    window_m3h: float
    purifier_level: int


class HoodPredictor:
    def __init__(self, p: ControllerParams):
        g = p.get
        self.v = g("air_balance.room_volume_m3")
        self.q_inf0 = g("air_balance.base_infiltration_ach") * self.v
        self.pen = g("air_balance.penetration_factor")
        self.hood_flow = g("appliances.range_hood.flow_m3h")
        self.eps = g("appliances.range_hood.capture_efficiency")
        self.eta = g("appliances.intake_fan.filter_efficiency_pm25")
        self.cadr = g("appliances.purifier.cadr_m3h")
        hp = "events.cooking.hood_prediction."
        self.k_dep = g(hp + "deposition_rate_per_h")
        self.step_s = g(hp + "step_s")
        self.horizon_s = g("events.cooking.hood_prediction_horizon_s")
        self.nominal_ug_h = g(hp + "nominal_source_mg_per_min") * MG_PER_MIN_TO_UG_PER_H
        self.tolerance = g(hp + "peak_tolerance_pct") / 100.0

    def _flows(self, plan: Plan) -> tuple[float, float, float]:
        q_hood = self.hood_flow[f"l{plan.hood_level}"] if plan.hood_level > 0 else 0.0
        net = plan.intake_m3h + plan.window_m3h - q_hood
        q_inf = self.q_inf0 + max(0.0, -net)
        cadr = self.cadr[f"l{plan.purifier_level}"] if plan.purifier_level > 0 else 0.0
        return q_hood, q_inf, cadr

    def estimate_source(self, pm: float, dpdt_per_h: float, current: Plan, pm_out: float) -> float:
        """현재 계획(실제 동작 중인 장치) 아래 PM 수지의 잔차 → 발생량 [µg/h]. 후드 포집 전 값으로 되돌린다."""
        q_hood, q_inf, cadr = self._flows(current)
        q_oa = current.intake_m3h + current.window_m3h + q_inf
        inflow = (current.intake_m3h * (1 - self.eta) + current.window_m3h + q_inf * self.pen) * pm_out
        captured = self.eps if current.hood_level > 0 else 0.0
        s_room = self.v * dpdt_per_h + (q_oa + cadr + self.k_dep * self.v) * pm - inflow
        return max(0.0, s_room) / max(1e-6, 1.0 - captured)

    def predict_peak(self, plan: Plan, pm0: float, pm_out: float, source_ug_h: float) -> float:
        q_hood, q_inf, cadr = self._flows(plan)
        q_oa = plan.intake_m3h + plan.window_m3h + q_inf
        s = source_ug_h * (1.0 - (self.eps if plan.hood_level > 0 else 0.0))
        inflow = (plan.intake_m3h * (1 - self.eta) + plan.window_m3h + q_inf * self.pen) * pm_out
        loss = q_oa + cadr + self.k_dep * self.v
        pm, peak, dt_h = pm0, pm0, self.step_s / 3600.0
        for _ in range(int(self.horizon_s / self.step_s)):
            pm += (s + inflow - loss * pm) / self.v * dt_h
            peak = max(peak, pm)
        return peak

    def choose(self, plans: list[Plan], pm0: float, pm_out: float, source_ug_h: float,
               peak_cap: float | None = None) -> tuple[Plan, dict[int, float]]:
        """peak_cap — 주면 최선안 대비 허용 범위 밖이라도 예측 피크가 이 이하인 안을 허용한다 (급기 불가 시 낮은 단 우선)."""
        peaks = {pl.hood_level: self.predict_peak(pl, pm0, pm_out, source_ug_h) for pl in plans}
        best = min(peaks.values())
        lim = best * (1.0 + self.tolerance)
        if peak_cap is not None:
            lim = max(lim, peak_cap)
        ok = [pl for pl in plans if peaks[pl.hood_level] <= lim]
        return min(ok, key=lambda pl: pl.hood_level), peaks
