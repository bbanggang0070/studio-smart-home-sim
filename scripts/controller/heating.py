"""난방 사다리 · 규칙 (난방 확장 트랙 docs/14 §4) — ROS 비의존. 가전 프로파일에 boiler 가 있을 때만 동작한다.

장치 'boiler' 의 값 = 룸 온도조절기 설정 °C (0 = 전원 끔). 병합은 다른 장치와 같다 — need 최댓값 · cap 최솟값 · force 최상위.

  사다리 (싼 수단부터)  1 낮 · 맑음 → 블라인드 개방(일사 받기) · 2 밤 → 블라인드 닫기(창 단열) · 3 실링팬 역회전 약 · 4 보일러
  목표                 모드 heating_setpoint_c · 외출(AWAY) = away_heating 전략(셋백 · 끄기) · 난방 목표 ≤ 냉방 목표 − 데드밴드
  I11 환기 ↔ 난방      창문이 열려 있으면 보일러를 동파 하한으로 낮춘다 (열린 창으로 데운 공기를 버리지 않는다)
  I13 후드 ↔ 난방      요리 · 후드 후속 중에는 목표 − cooking_hold_c 까지만 (찬 외기 유입에 바로 올리지 않는다)
  I12 가습 ↔ 난방      데우는 중(실내 < 목표 − warmup_no_humidify_c)에는 가습하지 않는다 (차가운 방 = 차가운 창 표면 → 결로)
  I14 빨래 ↔ 난방      E10 빨래 건조 중 목표 + laundry_boost_c (L4.5)
  난방 ⟂ 냉방           냉방 사다리가 켜져 있으면 보일러는 동파 하한만 (L5 cap)
  E16 동파 위험         실내 < frost_alert_c 이고 목표가 그보다 낮으면 L1 force + 알림 · 설정은 frost_min_c 아래로 내리지 않는다
  E17 보일러 이상       연소 요구가 fault_confirm_s 이어졌는데 보일러 전력 · 실내 온도 상승이 없으면 알림 (보조 열원 없음)
  수동 조작(L4)         조절기를 사람이 직접 바꾸면(state/boiler manual) hold_min 동안 명령하지 않는다 (E12 와 같은 틀)
"""

from __future__ import annotations

import math

from controller.event_detector import ActiveEvent
from controller.params import ControllerParams
from controller.signals import Observation

L1, L2, L3, L4, L45, L5 = 1, 2, 3, 4, 4.5, 5


class HeatingLadder:
    def __init__(self, p: ControllerParams, hysteresis: bool = True):
        self.p = p
        self.hysteresis = hysteresis
        self.fault = False
        self._demand_since: float | None = None
        self._demand_t0 = math.nan
        self._demand_max_w = 0.0
        self._frost_alerted = False
        self._manual_until = -math.inf
        self.alerts: list[dict] = []

    def target(self, mode: str, home_mode: str) -> tuple[float, str]:
        """→ (설정 °C, 사유). 동파 하한 · 냉방 데드밴드 적용."""
        g = self.p.get
        frost = g("heating.frost_min_c")
        if mode == "AWAY":
            en = self.p.modes.get("energy") or {}
            strat = str(en.get("away_heating_strategy", "setback"))
            sp = float(en.get("away_heating_setback_c", frost)) if strat == "setback" else frost
            why = f"외출 난방 {strat} {sp:g} °C"
        else:
            m = self.p.mode(mode if mode in self.p.modes["modes"] else home_mode)
            hs = m.get("heating_setpoint_c")
            sp, why = (float(hs), f"{mode} 난방 목표 {float(hs):g} °C") if hs is not None else (frost, f"{mode} 난방 목표 없음")
            cs = m.get("cooling_setpoint_c")
            if cs is not None and sp > cs - g("heating.cooling_deadband_c"):
                sp = cs - g("heating.cooling_deadband_c")
                why += f" (냉방 목표 − 데드밴드로 제한 {sp:g} °C)"
        return max(sp, frost), why

    def apply(self, o: Observation, mode: str, home_mode: str, ev: dict, devices: set, cooling: bool,
              add) -> dict:
        if "boiler" not in devices:
            return {}
        g = self.p.get
        frost = g("heating.frost_min_c")
        info: dict = {}
        # -- 수동 조작 존중 (L4 · E12 틀) --
        b = o.boiler or {}
        if b.get("manual"):
            self._manual_until = o.now_s + g("events.manual_override.hold_min") * 60.0
            self.alerts.append({"code": "H_MANUAL", "level": "info", "t": o.now_s,
                                "msg": f"온도조절기 직접 조작 — {g('events.manual_override.hold_min'):g}분 자동 난방 보류"})
        if o.now_s < self._manual_until:
            info["boiler_hold"] = True
            return info
        sp, why = self.target(mode, home_mode)
        season = (o.outdoor_temp_c <= g("heating.season_max_outdoor_c")) if not math.isnan(o.outdoor_temp_c) \
            else o.temp_c < sp
        info["heating_target_c"] = sp
        # -- E16 동파 (L1) — 계절과 무관 --
        if o.temp_c < g("heating.frost_alert_c"):
            if not self._frost_alerted:
                self.alerts.append({"code": "H_FROST", "level": "critical", "t": o.now_s,
                                    "msg": f"실내 {o.temp_c:.1f} °C — 동파 위험 · 난방 하한 강제"})
                self._frost_alerted = True
            ev.setdefault("FROST_RISK", ActiveEvent("FROST_RISK", o.now_s, {}))
            if sp < g("heating.frost_alert_c"):
                add("boiler", "force", g("heating.frost_alert_c"), L1, "E16 동파 위험 — 난방 하한")
        elif o.temp_c > g("heating.frost_alert_c") + 1.0:
            self._frost_alerted = False
            ev.pop("FROST_RISK", None)
        if not season:
            info["heating_season"] = False
            return info                                   # 기본값 0 (끔) — 계절 밖
        info["heating_season"] = True
        # -- 보일러 목표 (L3 외출 · L5 쾌적) --
        add("boiler", "need", sp, L3 if mode == "AWAY" else L5, why)
        if "LAUNDRY_DRYING" in ev and mode != "AWAY":
            add("boiler", "need", sp + g("heating.laundry_boost_c"), L45, "I14 빨래 건조 — 난방 목표 상향")
        # -- 규칙 --
        if o.window_ratio >= g("heating.vent_pause_window_ratio"):
            add("boiler", "cap", frost, L2, f"I11 창문 {o.window_ratio:.0%} 열림 — 난방 일시 정지")
        if "COOKING" in ev or "HOOD_POST_RUN" in ev:
            add("boiler", "cap", max(sp - g("heating.cooking_hold_c"), frost), L2, "I13 요리 · 후드 — 난방 올리지 않음")
        if cooling:
            add("boiler", "cap", frost, L5, "난방 ⟂ 냉방 — 냉방 사다리 동작 중")
        if o.temp_c < sp - g("heating.warmup_no_humidify_c") and mode != "AWAY":
            add("humidifier", "cap", 0, L5, f"I12 데우는 중 ({o.temp_c:.1f} < {sp:g} °C) — 가습 보류")
        # -- 사다리 아래 칸 (재실 · 난방 필요할 때) --
        need = o.temp_c < sp and not cooling and mode not in ("AWAY",)
        if need and o.occupied:
            v = "virtual_sensors.lux."
            day = g(v + "sunrise_h") * 3600 <= o.tod_s <= g(v + "sunset_h") * 3600
            if day and o.sky in ("clear", "cloudy"):
                add("blind", "need", 0.0, L5, "난방 사다리 1 — 낮 일사 받기 (블라인드 개방)")
            elif not day and g("heating.blind_close_night"):
                add("blind", "need", g("setpoints.blind_shade_angle_deg"), L5, "난방 사다리 2 — 밤 창 단열 (블라인드 닫기)")
            if o.temp_c < sp - g("heating.fan_reverse_above_c") and "ceiling_fan" in devices:
                add("ceiling_fan", "need", -1, L5, "난방 사다리 3 — 실링팬 역회전 (천장 열 섞기)")
        # -- E17 보일러 이상 --
        self._fault_check(o, sp)
        return info

    def _fault_check(self, o: Observation, sp: float) -> None:
        g = self.p.get
        b = o.boiler or {}
        demand = bool(b.get("power")) and o.temp_c < float(b.get("setpoint", sp)) - 1.0
        if not demand:
            self._demand_since, self._demand_max_w = None, 0.0
            return
        w = float(o.power_w.get("boiler", math.nan))
        if self._demand_since is None:
            self._demand_since, self._demand_t0, self._demand_max_w = o.now_s, o.temp_c, 0.0
        if not math.isnan(w):
            self._demand_max_w = max(self._demand_max_w, w)
        if (not self.fault and o.now_s - self._demand_since >= g("appliances.boiler.fault_confirm_s")
                and self._demand_max_w < g("appliances.boiler.fault_burn_w_min")
                and o.temp_c - self._demand_t0 < g("appliances.boiler.fault_temp_rise_c")):
            self.fault = True
            self.alerts.append({"code": "H_BOILER_FAULT", "level": "critical", "t": o.now_s,
                                "msg": "보일러 무응답 — 난방 요구 중 연소 전력 · 온도 상승 없음 (점검 필요)"})

