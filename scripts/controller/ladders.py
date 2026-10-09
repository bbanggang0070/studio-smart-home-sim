"""쾌적 수단 사다리 (docs/06 §4 · docs/07 §4.2–4.3) — L5 냉방 · 제습 · 가습.

냉방  ① 블라인드 차광 ② 창문(외기 < 실내 − 1 °C) + 배기 저속 ③ 실링팬 정회전 ④ 배기 + 흡기(창문 불가 시)
      ⑤ 에어컨 — 무료 냉방(②④)을 쓸 수 없을 때만. 실링팬 정회전 중이면 설정 +1 °C (I5)
제습  ① 창문 · ② 배기 + 흡기 — 바깥이 더 건조할 때만 (I10) ③ 계절 수단 (I6): 여름 에어컨 제습 / 그 외 제습기
가습  유효 상한 = min(모드 상한, 결로 상한 I4). 결로 상한이 더 낮으면 실링팬 역회전으로 상한을 넓힌다 (C10)
히스테리시스 폭은 Baseline B 에서 0 이다.
"""

from __future__ import annotations

import json
import math

from controller.params import ControllerParams
from controller.signals import Observation, Psychro

L5 = 5
SPEED = {"low": 1, "mid": 1, "high": 2}


class ComfortLadders:
    def __init__(self, p: ControllerParams, psy: Psychro, rules, hysteresis: bool = True):
        self.p, self.psy, self.rules, self.hyst = p, psy, rules, hysteresis
        self.cooling = self.dehumidifying = self.humidifying = False
        self._hum_paused = False
        self._i10_open = False
        self._free_cool_since: float | None = None
        self._ac_dry = False

    def _band(self, key: str) -> float:
        return self.p.get(f"comfort_ladders.{key}") if self.hyst else 0.0

    def season(self, o: Observation) -> str:
        s = self.p.get("comfort_ladders.season_outdoor_temp_c")
        if math.isnan(o.outdoor_temp_c):
            return "mid"
        return "summer" if o.outdoor_temp_c >= s["summer_min"] else "winter" if o.outdoor_temp_c <= s["winter_max"] else "mid"

    def _i10(self, o: Observation) -> bool:
        """바깥 이슬점이 실내보다 enter_margin 이상 낮으면 열고, exit_margin 아래로 좁혀지면 닫는다."""
        if math.isnan(o.outdoor_temp_c):
            return False
        i10 = "interaction_rules.I10_vent_dehumidify_requires_drier_outside."
        diff = self.psy.dew_point(o.temp_c, o.rh_pct) - self.psy.dew_point(o.outdoor_temp_c, o.outdoor_rh_pct)
        if diff >= self.p.get(i10 + "enter_margin_c"):
            self._i10_open = True
        elif diff < self.p.get(i10 + "exit_margin_c"):
            self._i10_open = False
        return self._i10_open

    def apply(self, o: Observation, mode: str, blocked: list[str], noise: dict, add) -> dict:
        g = self.p.get
        m = self.p.mode(mode)
        season = self.season(o)
        info: dict = {"season": season}
        free_cool = (not math.isnan(o.outdoor_temp_c)
                     and o.outdoor_temp_c <= o.temp_c - g("means_ladder.window_cooling_requires_outdoor_below_c"))
        ac_allowed = "ac" in self.rules.devices and m.get("cooling_setpoint_c") is not None
        ac_cmd = None                                   # (mode, setpoint) — 냉방 · 제습이 함께 정한다
        fan_max = SPEED[noise["ceiling_fan_max_speed"]]

        # ---- 제습 상태 (냉방 수단 선택에 쓰므로 먼저 정한다) ----
        hi = (m.get("humidity_range_pct") or [None, None])[1]
        if hi is None:
            self.dehumidifying = False
        elif o.rh_pct > hi:
            self.dehumidifying = True
        elif o.rh_pct < hi - self._band("dehumidify_off_band_pct"):
            self.dehumidifying = False
        i10 = self._i10(o)
        # ---- 냉방 ----
        sp = m.get("cooling_setpoint_c")
        if sp is None or season == "winter":
            self.cooling = False
        elif o.temp_c > sp + g("comfort_ladders.cooling_on_above_setpoint_c"):
            self.cooling = True
        elif o.temp_c < sp - self._band("cooling_off_band_c"):
            self.cooling = False
        # 제습이 필요한데 바깥이 더 습하면(I10 불만족) 환기로 냉방하지 않는다 — 습기를 들인다 (C1)
        if self.dehumidifying and not i10:
            free_cool = False
        if self.cooling:
            if o.illuminance_lux >= g("comfort_ladders.shade_requires_lux"):
                add("blind", "need", g("setpoints.blind_shade_angle_deg"), L5, "냉방 ① 블라인드 차광")
            if free_cool and not blocked:
                add("window", "need", g("setpoints.window_vent_ratio_pct") / 100.0, L5, "냉방 ② 창문 (외기가 더 시원)")
                add("exhaust", "need", g("setpoints.fan_low_rpm"), L5, "냉방 ② 배기 저속 (창문 병행)")
            speed = 2 if o.temp_c > sp + g("comfort_ladders.ceiling_fan_high_above_setpoint_c") else 1
            fan = min(speed, fan_max)
            if "ceiling_fan" in self.rules.devices:
                add("ceiling_fan", "need", fan, L5, "냉방 ③ 실링팬 정회전")
            if free_cool and blocked:
                rpm = g("setpoints.fan_high_rpm")
                add("exhaust", "need", rpm, L5, f"냉방 ④ 배기 + 흡기 (창문 불가 {','.join(blocked)})")
                add("intake", "need", self.rules.intake_rpm_for(self.rules.exhaust_m3h(rpm)), L5, "냉방 ④ 균형 급기")
            # 무료 냉방을 쓰는 중이어도 escalate_to_ac_after_s 동안 목표 + margin 아래로 못 내리면 에어컨으로 승격
            cl = "comfort_ladders."
            if free_cool:
                self._free_cool_since = self._free_cool_since if self._free_cool_since is not None else o.now_s
            else:
                self._free_cool_since = None
            escalate = (free_cool and o.now_s - self._free_cool_since >= g(cl + "escalate_to_ac_after_s")
                        and o.temp_c > sp + g(cl + "escalate_above_setpoint_c"))
            if (not free_cool or escalate) and ac_allowed:
                relax = g("interaction_rules.I5_ceiling_fan_setpoint_relax_c") if "ceiling_fan" in self.rules.devices else 0.0
                sp_ac = sp + relax
                # 냉방 + 제습이 함께 필요하면 설정 근처에서는 제습 모드 — 저부하 냉방은 습기를 거의 못 뺀다 (C1)
                if self.dehumidifying and season == "summer":
                    if o.temp_c <= sp_ac + g(cl + "ac_dry_within_setpoint_c"):
                        self._ac_dry = True
                    elif o.temp_c > sp_ac + g(cl + "ac_cool_resume_above_c"):
                        self._ac_dry = False
                else:
                    self._ac_dry = False
                why = "냉방 ⑤ 에어컨" + (" (승격 — 무료 냉방 부족)" if escalate else "") + (f" (I5 +{relax:g} °C)" if relax else "")
                ac_cmd = ("dry", sp_ac, why + " → 제습 모드 (냉방 + 제습)") if self._ac_dry else ("cool", sp_ac, why)
        else:
            self._free_cool_since = None
        info["cooling"] = self.cooling

        # ---- 제습 수단 ----

        if self.dehumidifying:
            if i10 and not blocked:
                add("window", "need", g("setpoints.window_vent_ratio_pct") / 100.0, L5, "제습 ① 창문 (I10 바깥이 더 건조)")
            elif i10 and "outdoor_pm_bad" not in blocked:
                rpm = g("setpoints.fan_high_rpm")
                add("exhaust", "need", rpm, L5, "제습 ② 배기 + 흡기 (I10)")
                add("intake", "need", self.rules.intake_rpm_for(self.rules.exhaust_m3h(rpm)), L5, "제습 ② 균형 급기")
            elif season == "summer" and ac_allowed:
                if ac_cmd is None:
                    ac_cmd = ("dry", sp, "제습 ③ 에어컨 제습 (I6 여름)")
            else:
                add("dehumidifier", "need", 1, L5, f"제습 ③ 제습기 (I6 {season})")
        info["dehumidifying"] = self.dehumidifying

        # ---- 가습 (I4 상한) ----
        lo = (m.get("humidity_range_pct") or [None, None])[0]
        r_si = self.psy.surface_resistance(o.blind_deg, o.ceiling_fan)
        cap = self._humidify_cap(o, r_si)
        target = min(hi if hi is not None else 100.0, cap)
        info["humidify_cap_pct"] = round(cap, 1)
        if lo is None:
            self.humidifying = False
        elif o.rh_pct < lo:
            self.humidifying, self._hum_paused = True, False
        if self.humidifying:
            if o.rh_pct >= target:
                self._hum_paused = True
            elif o.rh_pct < target - self._band("humidify_restart_band_pct"):
                self._hum_paused = False
            if not self._hum_paused:
                add("humidifier", "need", 1, L5, f"가습 (유효 상한 {target:.0f} %)")
            if (g("comfort_ladders.cap_extension_by_ceiling_fan") and hi is not None and season == "winter"
                    and self._humidify_cap(o, self.psy.r_si["default"]) < hi and "ceiling_fan" in self.rules.devices):
                add("ceiling_fan", "need", -1, L5, "I4 상한 확장 — 실링팬 역회전")
        info["humidifying"] = self.humidifying

        if ac_cmd and noise.get("ac_fan_max"):
            add("ac", "need", 1, L5, ac_cmd[2])
            info["ac"] = {"mode": ac_cmd[0], "setpoint": ac_cmd[1], "fan": noise["ac_fan_max"]}
        return info

    def _humidify_cap(self, o: Observation, r_si: float) -> float:
        """이슬점이 창 표면온도 − margin 을 넘지 않는 최대 RH (I4). 외기온을 모르면 상한 없음."""
        if math.isnan(o.outdoor_temp_c):
            return 100.0
        g = self.p.get
        b, c = self.psy.b, self.psy.c
        t_s = o.temp_c - r_si / (r_si + self.psy.r_rest) * (o.temp_c - o.outdoor_temp_c)
        t_dew_max = t_s - g("condensation.humidify_margin_c")
        gamma = b * t_dew_max / (c + t_dew_max)
        return min(100.0, 100.0 * math.exp(gamma - b * o.temp_c / (c + o.temp_c)))


def ac_json(info: dict, on: bool) -> str:
    if not on or "ac" not in info:
        return json.dumps({"power": False, "mode": "cool", "setpoint": 26.0, "fan": "auto"})
    a = info["ac"]
    return json.dumps({"power": True, "mode": a["mode"], "setpoint": a["setpoint"], "fan": a["fan"]})
