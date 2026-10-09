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
        self._fan_high = False
        self._escalated = False
        self._ac_on = False

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

    def apply(self, o: Observation, mode: str, blocked: list[str], noise: dict, add, saving: bool = False) -> dict:
        """saving = 빈방 절전(AUTO_SAVING) — 냉방 · 가습은 멈추고 곰팡이 방지 제습만 남긴다."""
        g = self.p.get
        m = dict(self.p.mode(mode))
        if saving:
            m["cooling_setpoint_c"] = None
            m["humidity_range_pct"] = [None, g("events.saving_state.mold_guard_rh_pct")]
        season = self.season(o)
        info: dict = {"season": season}
        outdoor_cooler = (not math.isnan(o.outdoor_temp_c)
                          and o.outdoor_temp_c <= o.temp_c - g("means_ladder.window_cooling_requires_outdoor_below_c"))
        free_cool = outdoor_cooler                      # 환기로 하는 냉방 — 아래에서 I10 이 막을 수 있다
        # 창문을 못 쓰면 배기 + 흡기만 남는다 — 소음 등급 · 외기 등급 상한 뒤 배기 여력이 작으면 무료 냉방이 없는 것과 같다
        if free_cool and blocked:
            ex_cap = min(noise["exhaust_fan_max_rpm"], g("air_quality.grade_policy")[o.outdoor_pm_grade]["fan_max_rpm"])
            if ex_cap < g("comfort_ladders.min_free_cool_exhaust_rpm"):
                free_cool = False
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
        # 단 실내 제습 수단(에어컨 · 제습기)이 아예 없으면 습기는 어차피 못 뺀다 → 환기 냉방이 유일한 수단 (X8 P-core)
        dehum_means = ac_allowed or "dehumidifier" in self.rules.devices
        if self.dehumidifying and not i10 and dehum_means:
            free_cool = False
        # 에어컨 승격 (히스테리시스) — 무료 냉방을 escalate_to_ac_after_s 써도 목표 + margin 을 넘으면 승격하고,
        # 목표 + margin − release_band 아래로 내려오거나 냉방이 끝날 때까지 유지한다. 승격 중엔 무료 냉방을 요청하지 않는다
        # (I2 로 창문이 닫히면 승격 조건이 풀려 다시 창문을 여는 채터링 방지 — C5)
        cl = "comfort_ladders."
        if not self.cooling or not free_cool:
            self._escalated, self._free_cool_since = False, None
        else:
            if self._free_cool_since is None:
                self._free_cool_since = o.now_s
            over_at = sp + g(cl + "escalate_above_setpoint_c")
            if (not self._escalated and o.temp_c > over_at
                    and o.now_s - self._free_cool_since >= g(cl + "escalate_to_ac_after_s")):
                self._escalated = True
            elif self._escalated and o.temp_c <= over_at - self._band("escalate_release_band_c"):
                self._escalated = False
        if self.cooling:
            if o.illuminance_lux >= g("comfort_ladders.shade_requires_lux"):
                add("blind", "need", g("setpoints.blind_shade_angle_deg"), L5, "냉방 ① 블라인드 차광")
            elif m.get("blind_policy") == "night_cooling" and outdoor_cooler:   # 복사냉각은 공기를 들이지 않는다 — I10 무관
                add("blind", "need", g("setpoints.blind_night_cooling_deg"), L5, "냉방 — 야간 복사냉각 블라인드 개방 (수면)")
            if free_cool and not blocked and not self._escalated:
                add("window", "need", g("setpoints.window_vent_ratio_pct") / 100.0, L5, "냉방 ② 창문 (외기가 더 시원)")
                add("exhaust", "need", g("setpoints.fan_low_rpm"), L5, "냉방 ② 배기 저속 (창문 병행)")
            hi_at = sp + g("comfort_ladders.ceiling_fan_high_above_setpoint_c")
            if o.temp_c > hi_at:
                self._fan_high = True
            elif o.temp_c < hi_at - self._band("ceiling_fan_speed_band_c"):
                self._fan_high = False
            fan = min(2 if self._fan_high else 1, fan_max)
            if "ceiling_fan" in self.rules.devices:
                add("ceiling_fan", "need", fan, L5, "냉방 ③ 실링팬 정회전")
            if free_cool and blocked and not self._escalated:
                # 비로 창문이 완전히 막히면 배기팬이 역할을 인수 — 최대 (setpoints.fan_max_rpm, v1.1 C1 · X8)
                rpm = g("setpoints.fan_max_rpm") if "rain" in blocked else g("setpoints.fan_high_rpm")
                add("exhaust", "need", rpm, L5, f"냉방 ④ 배기 + 흡기 (창문 불가 {','.join(blocked)})")
                add("intake", "need", self.rules.intake_rpm_for(self.rules.exhaust_m3h(rpm)), L5, "냉방 ④ 균형 급기")
            escalate = self._escalated
            relax = g("interaction_rules.I5_ceiling_fan_setpoint_relax_c") if "ceiling_fan" in self.rules.devices else 0.0
            sp_ac = sp + relax
            # 실링팬이 체감을 낮추는 동안(I5)은 에어컨 기동 기준도 같이 완화한다 — 설정만 완화하고 기동은 공기 온도
            # 목표 + 0.5 에서 하면, 실링팬만으로 체감이 충분한데도 에어컨이 돈다 (C9: 실링팬 약만 쓰는 A 의 체감 과열 0 s)
            if self._ac_on:
                self._ac_on = o.temp_c >= sp_ac - self._band("cooling_off_band_c")
            else:
                self._ac_on = o.temp_c > sp_ac + g("comfort_ladders.cooling_on_above_setpoint_c")
            if ((not free_cool and self._ac_on) or escalate) and ac_allowed:
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
