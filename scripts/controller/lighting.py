"""조명 · 조도 (docs/07 §2.1 모드 조명 · L6) + 가상 조도 페일세이프 (docs/08 §2.2 · X3).

목표: 모드의 lighting {target, lux, cct, ceiling_lux, off_after_min} — lux 는 작업면(바닥 · 책상) 기준
  천장 센서(아래를 봄)는 반사광만 받아 작업면보다 낮게 읽는다 (W05 T5.7 · config/lighting_calibration.yaml) →
  작업면 주광 = (센서 측정 − 자기 조명의 센서 기여) / daylight_sensor_ratio
  천장등 % = (방 목표 − 작업면 주광) / ceiling_lux_at_floor_full
  스탠드 % = (책상 목표 − 작업면 주광 − 천장등의 책상 기여) / desk_lux_at_desk_full   (책상 조도 센서 없이 추정 — docs/02 §2.5)
  수면: off_after_min 뒤 소등 · 외출 · 빈방 절전: 소등 · 눈부심(700 lux 초과) → 블라인드 차광 (620 lux 해제)
조도 센서가 무효(NaN · 범위 밖)면 마지막 유효값을 hold_last_valid_s 동안 쓰고, 그 뒤 가상 조도(시각 · 비 · 블라인드)로 계속 제어한다.
"""

from __future__ import annotations

import math

from controller.params import ControllerParams
from controller.signals import Observation

L5, L6 = 5, 6


class Lighting:
    def __init__(self, p: ControllerParams):
        self.p = p
        self._last_valid: tuple[float, float] | None = None   # (시각, 값)
        self._sleep_since: float | None = None
        self._glare = False
        self._glare_deg: float | None = None
        self._settled_since: float | None = None
        self._hold_c_pct: float | None = None
        self.virtual = False
        self.alerted = False

    def _virtual_lux(self, o: Observation) -> float:
        g = self.p.get
        v = "virtual_sensors.lux."
        h = (o.tod_s / 3600.0) % 24.0
        rise, sset = g(v + "sunrise_h"), g(v + "sunset_h")
        sun = math.sin(math.pi * (h - rise) / (sset - rise)) if rise < h < sset else 0.0
        out = g(v + "clear_sky_peak_lux") * sun * (g(v + "rain_factor") if o.raining else 1.0)
        lm = "lighting_model."
        frac = min(max(o.blind_deg / g("setpoints.blind_shade_angle_deg"), 0.0), 1.0)
        tau = g(lm + "outdoor_transmittance_open") + frac * (g(lm + "outdoor_transmittance_shaded") - g(lm + "outdoor_transmittance_open"))
        # 센서 눈금으로 돌려준다 (측정값 대신 쓰므로)
        return out * g(lm + "daylight_factor") * tau * g(lm + "daylight_sensor_ratio") + self._own_light(o)

    def _own_light(self, o: Observation) -> float:
        g = self.p.get
        lm = "lighting_model."
        return (g(lm + "ceiling_lux_at_sensor_full") * o.ceiling_pct / 100.0       # 자기 조명의 센서 기여
                + g(lm + "desk_lux_at_sensor_full") * o.desk_pct / 100.0)

    def measured(self, o: Observation) -> tuple[float, bool]:
        """→ (쓸 조도, 새로 페일세이프에 들어갔나)."""
        g = self.p.get
        lo, hi = g("sensor_failsafe.illuminance_valid_range")
        val = o.illuminance_lux
        if val == val and lo <= val <= hi:                    # NaN 이 아니고 범위 안
            self._last_valid, self.virtual = (o.now_s, val), False
            return val, False
        if self._last_valid and o.now_s - self._last_valid[0] <= g("sensor_failsafe.hold_last_valid_s"):
            return self._last_valid[1], False
        entered = not self.virtual
        self.virtual = True
        return self._virtual_lux(o), entered

    def daylight_workplane(self, o: Observation) -> float:
        """작업면 주광 추정 — 센서 값(자기 조명 기여 제외)을 작업면 기준으로 환산 (냉방 사다리 차광 판단도 이 값을 쓴다)."""
        g = self.p.get
        lo, hi = g("sensor_failsafe.illuminance_valid_range")
        val = o.illuminance_lux
        if val == val and lo <= val <= hi:
            lux = val
        elif self._last_valid and o.now_s - self._last_valid[0] <= g("sensor_failsafe.hold_last_valid_s"):
            lux = self._last_valid[1]
        else:
            lux = self._virtual_lux(o)                 # measured() 와 같은 규칙 — 페일세이프 상태는 바꾸지 않는다 (알림은 apply 가 낸다)
        return max(0.0, lux - self._own_light(o)) / g("lighting_model.daylight_sensor_ratio")

    def apply(self, o: Observation, mode: str, saving: bool, cooling: bool, add) -> dict:
        g = self.p.get
        lm = "lighting_model."
        lux, entered = self.measured(o)
        m = self.p.mode(mode)["lighting"]
        info = {"lux_used": round(lux, 1), "lux_virtual": self.virtual}
        if entered and not self.alerted:
            info["alert"] = {"code": "S_LUX", "level": "warning", "t": o.now_s,
                             "msg": "조도 센서 무효 — 가상 조도(시각 · 날씨 · 블라인드)로 계속 제어"}
            self.alerted = True
        self._sleep_since = (self._sleep_since or o.now_s) if mode == "SLEEP" else None
        off = (not o.occupied or saving or m.get("target") == "none" or mode == "AWAY"
               or (self._sleep_since is not None and o.now_s - self._sleep_since >= (m.get("off_after_min") or 0) * 60.0
                   and m.get("off_after_min")))
        if off:
            add("ceiling_light", "force", 0, L6, "조명 소등 (빈방 · 외출 · 수면 경과)")
            add("desk_light", "force", 0, L6, "스탠드 소등")
            return info
        daylight = max(0.0, lux - self._own_light(o)) / g(lm + "daylight_sensor_ratio")   # 작업면 주광 추정
        info["daylight_workplane_lux"] = round(daylight, 1)
        ceil_target = m.get("ceiling_lux", m["lux"]) if m["target"] == "desk" else m["lux"]
        # 블라인드가 움직이는 중이거나 막 멈췄으면(센서 · 조명 지연) 조도로 다시 판단하지 않는다 — 과보정 진동 방지 (B2 물리 모드)
        settled = self._blind_settled(o)
        short = ceil_target - daylight
        if short < g("illuminance.ceiling_deadband_lux"):
            short = 0.0                                    # 목표 근처 — 센서 잡음에 천장등이 깜빡이지 않게
        c_pct = min(100.0, max(0.0, short / g(lm + "ceiling_lux_at_floor_full") * 100.0))
        if settled or self._hold_c_pct is None:
            self._hold_c_pct = c_pct
        else:
            c_pct = self._hold_c_pct
        add("ceiling_light", "need", c_pct, L6, f"조명 — 천장 {ceil_target:g} lux 목표 ({mode})")
        if cooling:
            add("ceiling_light", "cap", g("setpoints.ceiling_light_thermal_cap_pct"), L5, "고온 — 조명 발열 상한 (C4)")
        if m["target"] == "desk":
            c_eff = min(c_pct, g("setpoints.ceiling_light_thermal_cap_pct")) if cooling else c_pct   # 고온 상한이 걸린 실제 밝기
            desk_from_ceiling = g(lm + "ceiling_lux_at_desk_full") * c_eff / 100.0
            d_pct = min(100.0, max(0.0, (m["lux"] - daylight - desk_from_ceiling) / g(lm + "desk_lux_at_desk_full") * 100.0))
            add("desk_light", "need", d_pct, L6, f"스탠드 — 책상 {m['lux']:g} lux 목표 (추정)")
        else:
            add("desk_light", "need", 0, L6, "스탠드 — 모드 목표 없음")
        add("desk_cct", "need", m["cct_k"], L6, f"색온도 {m['cct_k']:g} K ({mode})")
        # 눈부심 — 차광 (B2 · 히스테리시스 700 / 620). 블라인드를 닫으면 측정 주광이 줄어 바로 풀리므로
        # '블라인드를 열었을 때의 주광'으로 환산해 판단한다 (차광 ↔ 개방 채터링 방지)
        il = "illuminance."
        frac = min(max(o.blind_deg / g("setpoints.blind_shade_angle_deg"), 0.0), 1.0)
        t_open, t_sh = g(lm + "outdoor_transmittance_open"), g(lm + "outdoor_transmittance_shaded")
        open_equiv = daylight * t_open / (t_open + frac * (t_sh - t_open))
        if settled:
            if open_equiv > g(il + "over_bright_lux"):
                self._glare = True
            elif open_equiv < g(il + "shade_release_lux"):
                self._glare = False
        if self._glare:
            if not g(il + "glare_partial_shade"):
                deg = g("setpoints.blind_shade_angle_deg")
            elif settled or self._glare_deg is None:
                deg = self._partial_shade_deg(open_equiv, ceil_target, t_open, t_sh)
            else:
                deg = self._glare_deg                      # 움직이는 중 — 직전 지령 유지
            add("blind", "need", deg, L6, f"눈부심 — 블라인드 차광 {deg:g}°")
            info["glare_shade_deg"] = deg
        else:
            self._glare_deg = None
        return info

    def _partial_shade_deg(self, open_equiv: float, target: float, t_open: float, t_sh: float) -> float:
        """방 조도 목표에 맞는 차광 각도 — 블라인드를 연 상태의 작업면 주광(open_equiv)에서 필요한 투과율을 거꾸로 푼다.
        목표가 눈부심 해제 조도보다 높으면 해제 조도에 맞춘다. 각도 단위 · 데드밴드로 떨림을 막는다."""
        g = self.p.get
        il = "illuminance."
        goal = min(target, g(il + "shade_release_lux"))
        tau = t_open * goal / max(open_equiv, 1e-6)
        frac = min(max((tau - t_open) / (t_sh - t_open), 0.0), 1.0)
        step = g(il + "glare_angle_step_deg")
        # 내림 — 덜 가리는 쪽으로 (주광이 목표보다 약간 밝게 남아 조명이 켜지지 않게)
        deg = min(g("setpoints.blind_shade_angle_deg"), math.floor(frac * g("setpoints.blind_shade_angle_deg") / step) * step)
        if self._glare_deg is None or abs(deg - self._glare_deg) > step:
            self._glare_deg = deg
        return self._glare_deg

    def _blind_settled(self, o: Observation) -> bool:
        """블라인드가 직전 차광 지령 각도에 도착해 glare_settle_s 이상 지났나 (지령이 없으면 늘 정착)."""
        if self._glare_deg is None:
            self._settled_since = None
            return True
        if abs(o.blind_deg - self._glare_deg) > 2.0:
            self._settled_since = None
            return False
        self._settled_since = self._settled_since if self._settled_since is not None else o.now_s
        return o.now_s - self._settled_since >= self.p.get("illuminance.glare_settle_s")
