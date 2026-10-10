"""액추에이터 지령 · 피드백 변환 (W05 T5.3 · T5.3b · T5.5) + 목표 램프.

단위 변환은 순수 함수 — 호스트 pytest 로 검증한다. Isaac 조작은 IsaacActuators 가 맡는다 (Isaac 안에서만 import).
  창문     개방률 0–1 ↔ prismatic q [m] (0 = 닫힘 · travel = 완전 개방)
  블라인드  각도 [deg] ↔ revolute q (USD 는 deg, PhysX 읽기는 rad)
  팬       rpm ↔ 속도 드라이브 목표 [deg/s] · 읽기 [rad/s]
  조명     0–100 % → intensity (선형 디밍 · lighting_calibration.yaml 의 intensity_at_full)
  색온도   2700–6500 K 로 클램프 · enableColorTemperature 를 반드시 켠다
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def window_ratio_to_q(ratio: float, travel_m: float) -> float:
    return min(max(ratio, 0.0), 1.0) * travel_m


def window_q_to_ratio(q_m: float, travel_m: float) -> float:
    return min(max(q_m / travel_m, 0.0), 1.0)


def rpm_to_deg_s(rpm: float) -> float:
    return rpm * 6.0


def rad_s_to_rpm(w: float) -> float:
    return w * 60.0 / (2.0 * math.pi)


def dimming_to_intensity(pct: float, intensity_at_full: float) -> float:
    return min(max(pct, 0.0), 100.0) / 100.0 * intensity_at_full


def clamp_cct(k: float, lo: float = 2700.0, hi: float = 6500.0) -> float:
    return min(max(k, lo), hi)


@dataclass
class Ramp:
    """목표값을 최대 속도로 따라가는 램프 — 위치 드라이브에 큰 계단을 주지 않는다 (W05 리스크: 떨림 · 오버슈트)."""
    rate: float                 # 단위/s
    value: float = 0.0
    goal: float = 0.0
    velocity: float = 0.0       # 직전 스텝의 지령 속도 — 0 이면 지령상 정지 (로컬 컷오프의 이동 방향 · 기동 판정)

    def set_goal(self, goal: float) -> None:
        self.goal = goal

    def step(self, dt: float) -> tuple[float, float]:
        """→ (목표 위치, 목표 속도)."""
        err = self.goal - self.value
        dv = math.copysign(min(abs(err), self.rate * dt), err)
        self.value += dv
        self.velocity = dv / dt if dt > 0 else 0.0
        return self.value, self.velocity


class IsaacActuators:
    """Isaac 스테이지의 드라이브 · 조명을 다룬다. stage = pxr Usd.Stage."""

    def __init__(self, stage, layout: dict, limits: dict, calib: dict | None = None):
        from pxr import UsdLux, UsdPhysics  # Isaac 안에서만

        self._UsdPhysics, self._UsdLux = UsdPhysics, UsdLux
        self.stage, self.L, self.A = stage, layout, limits
        self.calib = calib or {}
        self.travel = layout["window"]["travel_m"]
        self.window_ramp = Ramp(limits["window_prismatic_joint"]["max_speed_mps"])
        self.blind_ramp = Ramp(limits["blind_joint"]["max_speed_dps"])

    def _drive(self, path: str, kind: str):
        return self._UsdPhysics.DriveAPI(self.stage.GetPrimAtPath(path), kind)

    # ---- 지령 ----

    def set_window_ratio(self, ratio: float) -> None:
        self.window_ramp.set_goal(window_ratio_to_q(ratio, self.travel))

    def set_blind_deg(self, deg: float) -> None:
        lo, hi = self.A["blind_joint"]["range_deg"]
        self.blind_ramp.set_goal(min(max(deg, lo), hi))

    def set_fan_rpm(self, name: str, rpm: float) -> None:
        mx = self.A[f"{name}_joint"]["max_rpm"]
        self._drive(f"/World/{name}/{name}_joint", "angular").GetTargetVelocityAttr().Set(
            float(rpm_to_deg_s(max(-mx, min(mx, rpm)))))

    def set_light(self, which: str, pct: float, cct_k: float | None = None) -> None:
        path = {"ceiling": "/World/lighting_module/ceiling_led_light/light",
                "desk": "/World/lighting_module/desk_lamp/light"}[which]
        prim = self.stage.GetPrimAtPath(path)
        light = self._UsdLux.LightAPI(prim)
        full = self.calib.get(f"{which}_intensity_at_full") or (
            self.L["ceiling_light"]["intensity"] if which == "ceiling" else self.L["desk_lamp"]["intensity"])
        light.GetIntensityAttr().Set(float(dimming_to_intensity(pct, full)))
        if cct_k is not None:
            light.CreateEnableColorTemperatureAttr(True)
            light.GetColorTemperatureAttr().Set(float(clamp_cct(cct_k)))

    def step(self, dt: float) -> None:
        """램프 진행 — 물리 한 주기마다 부른다."""
        q, v = self.window_ramp.step(dt)
        d = self._drive("/World/window/window_prismatic_joint", "linear")
        d.GetTargetPositionAttr().Set(float(q))
        d.GetTargetVelocityAttr().Set(float(v))
        b, bv = self.blind_ramp.step(dt)
        for k in range(self.L["blind"]["slat_count"]):
            d = self._drive(f"/World/blind/blind_joint_{k:02d}", "angular")
            d.GetTargetPositionAttr().Set(float(b))
            d.GetTargetVelocityAttr().Set(float(bv))
