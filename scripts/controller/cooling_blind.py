"""냉방 중 블라인드 각도 선택 (v3.4.18 · docs/07 §4.3) — 순수 Python.

블라인드를 닫으면 일사열은 줄지만, 창 안쪽 블라인드는 창문 바람도 막고 방을 어둡게 해 조명을 켜게 만든다.
'차광 먼저 → 창문' 같은 고정 순서는 이 상충을 무시한다. 후보 각도마다 순 열량을 비교해 가장 작은 쪽을 고른다.

    순 열량(θ) [W] = 일사열(θ) + 조명 열(θ) − 환기 냉방(θ)
      일사열     = 유리 면적 × (외부 조도 / 발광효율) × SHGC × 열 계수(θ)        외부 조도는 '블라인드 개방 환산 주광'에서 역산
      조명 열    = 천장등 전력 × (모드 목표 − 주광(θ))/천장등 바닥 조도              재실 중 · 목표가 있을 때만
      환기 냉방 = ρc × Q_창(θ) × (실내 − 외기)                                     창문을 냉방에 쓸 때만 (Q 는 단측 환기 근사 × 유량 계수(θ))
값은 제어용 추정(thresholds means_ladder.cooling_blind) — 참값 모델과 같은 초기값의 사본이다.
"""

from __future__ import annotations

import math

from common import daylight as dlm

KELVIN, GRAVITY = 273.15, 9.81


def _lerp(deg: float, shade_deg: float, a: float, b: float) -> float:
    f = min(max(deg / shade_deg, 0.0), 1.0)
    return a + f * (b - a)


class CoolingBlind:
    def __init__(self, p, lighting):
        self.p, self.lighting = p, lighting
        self.deg: float | None = None
        self.last: dict[float, dict] = {}

    def _c(self, key: str):
        return self.p.get(f"means_ladder.cooling_blind.{key}")

    def _shade(self) -> float:
        return self.p.get("setpoints.blind_shade_angle_deg")

    def solar_w(self, o, deg: float) -> float:
        dl = self.p.get("lighting_model.daylight")
        outdoor_lux = self.lighting.daylight_open_equiv(o) / max(dlm.workplane_per_outdoor(dl, o.sky, 0.0), 1e-9)
        irr = max(outdoor_lux, 0.0) / self._c("solar_luminous_efficacy_lm_per_w")
        heat = _lerp(deg, self._shade(), self._c("heat_factor_open"), self._c("heat_factor_shaded"))
        return self._c("glazing_area_m2") * irr * self._c("solar_heat_gain_fraction") * heat

    def vent_w(self, o, deg: float, ratio: float) -> float:
        dt = o.temp_c - o.outdoor_temp_c
        if ratio <= 0.0 or not dt > 0.0:
            return 0.0
        area = ratio * self._c("window_width_max_m") * self._c("window_height_m")
        h = self._c("window_height_m")
        t_mean = (o.temp_c + o.outdoor_temp_c) / 2.0 + KELVIN
        q = (self._c("discharge_coefficient") * area / 3.0 * math.sqrt(GRAVITY * h * dt / t_mean)
             + self._c("wind_coefficient") * area * self._c("wind_speed_ms")) * 3600.0
        q *= _lerp(deg, self._shade(), self._c("flow_factor_open"), self._c("flow_factor_shaded"))
        return self._c("air_heat_capacity_wh_per_m3k") * q * dt

    def light_w(self, o, deg: float, target_lux: float) -> float:
        if not o.occupied or target_lux <= 0.0:
            return 0.0
        g = self.p.get
        lm = "lighting_model."
        daylight = self.lighting.daylight_open_equiv(o) * dlm.relative_transmittance(g(lm + "daylight"), o.sky, deg)
        short = target_lux - daylight
        if short < g("illuminance.ceiling_deadband_lux"):
            return 0.0
        pct = min(1.0, short / g(lm + "ceiling_lux_at_floor_full"))
        return self._c("ceiling_light_w") * pct

    def choose(self, o, target_lux: float, window_ratio: float, min_deg: float = 0.0) -> tuple[float, str]:
        """→ (각도, 사유). window_ratio = 창문을 냉방에 쓸 개방률 (못 쓰면 0)."""
        cands = [d for d in self._c("candidates_deg") if d >= min_deg - 1e-6] or [max(self._c("candidates_deg"))]
        net = {}
        for d in cands:
            s, l, v = self.solar_w(o, d), self.light_w(o, d, target_lux), self.vent_w(o, d, window_ratio)
            net[d] = s + l - v
            self.last[d] = {"solar_w": round(s), "light_w": round(l), "vent_w": round(v), "net_w": round(s + l - v)}
        best = min(net, key=net.get)
        if self.deg in net and net[self.deg] - net[best] < self._c("switch_margin_w"):
            best = self.deg                                     # 차이가 작으면 지금 각도 유지
        self.deg = best
        e = self.last[best]
        why = (f"냉방 — 블라인드 {best:g}° (일사 {e['solar_w']} W + 조명 {e['light_w']} W − 환기 {e['vent_w']} W"
               f" = {e['net_w']} W · 후보 {', '.join(f'{d:g}°:{self.last[d]['net_w']}' for d in net)})")
        return best, why

    def reset(self) -> None:
        self.deg = None
