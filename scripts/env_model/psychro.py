"""습공기 계산 — 절대습도(수증기 밀도) · 상대습도 · 이슬점 (docs/06 §5.4 · §5.5).

절대습도 w 는 g/m³ (수증기 밀도). 환경 모델은 w 를 적분하고 RH 는 출력할 때만 계산한다.
포화수증기압은 이슬점과 같은 Magnus 식(b = 17.62, c = 243.12 °C)을 써서 서로 역함수가 되게 한다.
"""

from __future__ import annotations

import math

MAGNUS_A_HPA = 6.112          # Magnus 식 계수 [hPa] — 물리 상수
WATER_VAPOR_R = 461.5         # 수증기 기체상수 [J/(kg·K)] — 물리 상수
KELVIN = 273.15


def saturation_pressure_pa(temp_c: float, b: float, c: float) -> float:
    return MAGNUS_A_HPA * 100.0 * math.exp(b * temp_c / (c + temp_c))


def saturation_density_g_m3(temp_c: float, b: float, c: float) -> float:
    """포화 수증기 밀도 w_sat(T) [g/m³]."""
    return saturation_pressure_pa(temp_c, b, c) / (WATER_VAPOR_R * (temp_c + KELVIN)) * 1000.0


def rh_to_abs(temp_c: float, rh_pct: float, b: float, c: float) -> float:
    return rh_pct / 100.0 * saturation_density_g_m3(temp_c, b, c)


def abs_to_rh(temp_c: float, w_g_m3: float, b: float, c: float) -> float:
    return 100.0 * w_g_m3 / saturation_density_g_m3(temp_c, b, c)


def dew_point_c(temp_c: float, rh_pct: float, b: float, c: float) -> float:
    """Magnus 이슬점: γ = ln(RH/100) + bT/(c+T), T_d = cγ/(b−γ)."""
    rh = max(rh_pct, 1e-6)
    gamma = math.log(rh / 100.0) + b * temp_c / (c + temp_c)
    return c * gamma / (b - gamma)
