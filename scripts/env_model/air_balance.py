"""공기 수지 (docs/06 §5.1) — 모든 확장의 기반.

Q_sup = Q_intake + Q_window_in,  Q_exh = Q_exhaust + Q_hood,  Q_net = Q_sup − Q_exh
Q_inf = Q_inf0 + max(0, −Q_net)          (음압일수록 틈새 유입이 커진다 — 가정 A8)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from env_model.psychro import KELVIN

GRAVITY = 9.81  # 물리 상수


@dataclass(frozen=True)
class AirFlows:
    """유량 [m³/h]."""

    intake: float
    window: float
    exhaust: float
    hood: float
    infiltration: float

    @property
    def supply(self) -> float:
        return self.intake + self.window

    @property
    def mech_exhaust(self) -> float:
        return self.exhaust + self.hood

    @property
    def net_supply(self) -> float:
        return self.supply - self.mech_exhaust

    @property
    def outdoor_air(self) -> float:
        """실내로 들어오는 외기 총량 = 실내에서 나가는 공기 총량 (질량 보존)."""
        return self.supply + self.infiltration


INFILTRATION_MODELS = ("additive", "positive_zero")


def infiltration_m3h(base_m3h: float, net_supply_m3h: float, model: str = "additive") -> float:
    """틈새 유입. docs/06 §5.1 의 식(additive)과 주석(positive_zero)이 달라 둘 다 둔다."""
    if model not in INFILTRATION_MODELS:
        raise ValueError(f"infiltration_model 은 {INFILTRATION_MODELS} 중 하나여야 한다: {model!r}")
    if model == "positive_zero" and net_supply_m3h > 0.0:
        return 0.0
    return base_m3h + max(0.0, -net_supply_m3h)


def alternative_model(model: str) -> str:
    return INFILTRATION_MODELS[1 - INFILTRATION_MODELS.index(model)]


def window_flow_m3h(
    open_ratio: float,
    t_in: float,
    t_out: float,
    wind_ms: float,
    width_max_m: float,
    height_m: float,
    cd: float,
    wind_coef: float,
) -> float:
    """단측 자연 환기 근사: Q = Cd·A/3·sqrt(g·h·|ΔT|/T_mean) + c_w·A·U."""
    area = max(0.0, min(open_ratio, 1.0)) * width_max_m * height_m
    if area <= 0.0:
        return 0.0
    t_mean_k = (t_in + t_out) / 2.0 + KELVIN
    stack = cd * area / 3.0 * math.sqrt(GRAVITY * height_m * abs(t_in - t_out) / t_mean_k)
    wind = wind_coef * area * max(wind_ms, 0.0)
    return (stack + wind) * 3600.0
