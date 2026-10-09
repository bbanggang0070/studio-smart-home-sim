"""창 내표면 온도 · 결로 여유 · 가습 상한 (docs/06 §5.5 · 규칙 I4).

T_s = T_in − R_si/(R_si + R_rest)·(T_in − T_out),  Δ = T_s − T_dew
"""

from __future__ import annotations

import math

from env_model.config import EnvModelConfig
from env_model.psychro import dew_point_c


def inner_surface_resistance(cfg: EnvModelConfig, blind_angle_deg: float, ceiling_fan_level: int) -> float:
    """블라인드 · 실링팬 상태 → 실내측 표면저항 R_si.

    블라인드가 닫혀 유리 앞 공기가 정체되면 그것이 우선한다(역회전 기류가 닿지 않음).
    """
    c = "condensation."
    if blind_angle_deg >= cfg.get(c + "blind_closed_min_deg"):
        return cfg.get(c + "r_si_blind_closed_m2k_w")
    if blind_angle_deg >= cfg.get(c + "blind_slat_min_deg"):
        return cfg.get(c + "r_si_blind_slat_45_m2k_w")
    if ceiling_fan_level < 0:
        return cfg.get(c + "r_si_ceiling_fan_reverse_m2k_w")
    return cfg.get(c + "r_si_default_m2k_w")


def window_surface_temp_c(t_in: float, t_out: float, r_si: float, r_rest: float) -> float:
    return t_in - r_si / (r_si + r_rest) * (t_in - t_out)


def dew_margin_c(t_in: float, rh_pct: float, t_out: float, r_si: float, cfg: EnvModelConfig) -> float:
    b, c = cfg.get("condensation.magnus_b"), cfg.get("condensation.magnus_c")
    t_s = window_surface_temp_c(t_in, t_out, r_si, cfg.get("condensation.r_rest_m2k_w"))
    return t_s - dew_point_c(t_in, rh_pct, b, c)


def humidify_cap_rh_pct(t_in: float, t_out: float, r_si: float, margin_c: float, cfg: EnvModelConfig) -> float:
    """이슬점이 T_s − margin 을 넘지 않는 최대 RH (I4 가습 상한). Magnus 식을 이슬점에서 거꾸로 푼다."""
    b, c = cfg.get("condensation.magnus_b"), cfg.get("condensation.magnus_c")
    t_s = window_surface_temp_c(t_in, t_out, r_si, cfg.get("condensation.r_rest_m2k_w"))
    t_dew_max = t_s - margin_c
    gamma = b * t_dew_max / (c + t_dew_max)
    rh = 100.0 * math.exp(gamma - b * t_in / (c + t_in))
    return min(rh, 100.0)
