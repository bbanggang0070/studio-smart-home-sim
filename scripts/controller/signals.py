"""입력 토픽 → 제어기가 쓰는 관측값 (Observation) + 제어기 쪽 습공기 · 결로 계산.

습공기 식은 환경 참값 모델과 같은 Magnus 식이지만 코드를 공유하지 않는다 —
제어기는 thresholds.yaml 의 상수로 '자기 추정'을 하고, 참값 모델과는 토픽으로만 만난다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from controller.params import ControllerParams
from interfaces import topics as T


def dew_point_c(temp_c: float, rh_pct: float, b: float, c: float) -> float:
    gamma = math.log(max(rh_pct, 1e-6) / 100.0) + b * temp_c / (c + temp_c)
    return c * gamma / (b - gamma)


@dataclass
class Observation:
    now_s: float                  # 하루 기준 시각 [s] (time-of-day = now_s % 86400)
    temp_c: float
    rh_pct: float
    pm25: float
    hood_temp_c: float
    illuminance_lux: float
    occupied: bool
    zone: str
    door_open: bool
    outdoor_pm_grade: str
    power_w: dict[str, float]
    raining: bool
    outdoor_temp_c: float
    outdoor_rh_pct: float
    user_mode: str
    activity: str
    # 액추에이터 실제 상태 (상태 토픽)
    window_ratio: float
    blind_deg: float
    exhaust_rpm: float
    intake_rpm: float
    hood_level: int
    purifier_level: int
    ceiling_fan: int
    humidifier_on: bool
    ac_cooling: bool
    ac_power: bool
    ac_mode: str
    dehumidifier_on: bool
    occupancy_basis: str
    ceiling_pct: float
    desk_pct: float
    appliance_states: dict
    safety_state: str = "NORMAL"           # 창문 안전 계층 (W10) — SAFETY_HOLD · LOCKED_* 이면 창문을 못 쓴다

    @property
    def tod_s(self) -> float:
        return self.now_s % 86400.0


def parse_inbox(now_s: float, inbox: dict[str, Any]) -> Observation:
    weather = json.loads(inbox.get(T.S_WEATHER) or "{}")
    ac = json.loads(inbox.get(T.T_AC) or "{}")
    return Observation(
        now_s=now_s,
        temp_c=float(inbox[T.S_TEMPERATURE]),
        rh_pct=float(inbox[T.S_HUMIDITY]),
        pm25=float(inbox[T.S_PM25]),
        hood_temp_c=float(inbox.get(T.S_HOOD_TEMPERATURE, inbox[T.S_TEMPERATURE])),
        illuminance_lux=float(inbox.get(T.S_ILLUMINANCE, float("nan"))),
        occupied=bool(inbox.get(T.S_OCCUPANCY, False)),
        zone=str(inbox.get(T.S_OCCUPANT_ZONE, "none")),
        door_open=bool(inbox.get(T.S_DOOR_CONTACT, False)),
        outdoor_pm_grade=str(inbox.get(T.S_OUTDOOR_PM_GRADE, "good")),
        power_w=json.loads(inbox.get(T.S_APPLIANCE_POWER) or "{}"),
        raining=bool(weather.get("raining", False)),
        outdoor_temp_c=float(weather.get("outdoor_temp_c", math.nan)),
        outdoor_rh_pct=float(weather.get("outdoor_rh_pct", math.nan)),
        user_mode=str(inbox.get(T.C_MODE, "NORMAL")),
        activity=str(inbox.get(T.C_ACTIVITY, "")),
        window_ratio=float(inbox.get(T.T_WINDOW_OPEN_RATIO, 0.0)),
        blind_deg=float(inbox.get(T.T_BLIND_ANGLE, 0.0)),
        exhaust_rpm=float(inbox.get(T.T_FAN_RPM, 0.0)),
        intake_rpm=float(inbox.get(T.T_INTAKE_FAN_RPM, 0.0)),
        hood_level=int(round(float(inbox.get(T.T_RANGE_HOOD_LEVEL, 0)))),
        purifier_level=int(round(float(inbox.get(T.T_PURIFIER_LEVEL, 0)))),
        ceiling_fan=int(round(float(inbox.get(T.T_CEILING_FAN, 0)))),
        humidifier_on=bool(inbox.get(T.T_HUMIDIFIER, False)),
        ac_cooling=bool(ac.get("power")) and ac.get("mode") == "cool",
        ac_power=bool(ac.get("power")),
        ac_mode=str(ac.get("mode", "cool")),
        dehumidifier_on=bool(inbox.get(T.T_DEHUMIDIFIER, False)),
        occupancy_basis=str(inbox.get(T.T_OCCUPANCY_BASIS, "")),
        ceiling_pct=float(inbox.get(T.T_CEILING_LIGHT, 0.0)),
        desk_pct=float(inbox.get(T.T_DESK_LIGHT, 0.0)),
        appliance_states=json.loads(inbox.get(T.T_APPLIANCE_STATES) or "{}"),
        safety_state=str(inbox.get(T.T_SAFETY_STATE, "NORMAL") or "NORMAL"),
    )


class Psychro:
    """제어기 쪽 이슬점 · 결로 여유 추정 (thresholds condensation 상수)."""

    def __init__(self, p: ControllerParams):
        self.b = p.get("condensation.magnus_b")
        self.c = p.get("condensation.magnus_c")
        self.r_rest = p.get("condensation.r_rest_m2k_w")
        self.r_si = p.get("condensation.r_si_m2k_w")
        self.slat_min = p.get("condensation.blind_slat_min_deg")
        self.closed_min = p.get("condensation.blind_closed_min_deg")

    def dew_point(self, temp_c: float, rh_pct: float) -> float:
        return dew_point_c(temp_c, rh_pct, self.b, self.c)

    def abs_humidity(self, temp_c: float, rh_pct: float) -> float:
        """절대습도 [g/m³] — Magnus 포화수증기압 · 이상기체."""
        e_s = 611.2 * math.exp(self.b * temp_c / (self.c + temp_c))       # Pa (Magnus 계수 6.112 hPa — 물리 상수)
        return rh_pct / 100.0 * e_s / (461.5 * (temp_c + 273.15)) * 1000.0

    def surface_resistance(self, blind_deg: float, ceiling_fan: int) -> float:
        if blind_deg >= self.closed_min:
            return self.r_si["blind_closed"]
        if blind_deg >= self.slat_min:
            return self.r_si["blind_slat_45"]
        if ceiling_fan < 0:
            return self.r_si["ceiling_fan_reverse"]
        return self.r_si["default"]

    def dew_margin(self, o: Observation) -> float:
        if math.isnan(o.outdoor_temp_c):
            return math.nan
        r_si = self.surface_resistance(o.blind_deg, o.ceiling_fan)
        t_s = o.temp_c - r_si / (r_si + self.r_rest) * (o.temp_c - o.outdoor_temp_c)
        return t_s - self.dew_point(o.temp_c, o.rh_pct)
