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

from controller.cooling_blind import CoolingBlind
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
        self._outdoor_cooler = False
        self._shade_useful = False
        self._blind_choice = None                    # CoolingBlind — 조명 모듈이 필요해 처음 쓸 때 만든다
        self._ac_mode_since = -math.inf              # 냉방 ↔ 제습 모드를 바꾼 시각 (최소 유지 · B8)
        self._escalated_since = -math.inf            # 에어컨 승격 시각 (최소 유지 · C4)
        self.moisture_event = False                  # 요리 · 샤워 진행 중 (규칙 엔진이 알려 준다 — I6 회복 보조)
        self._moisture_recovery = False

    def _dry_sp(self, sp: float) -> float:
        """에어컨 제습 운전 설정 — 냉방 목표보다 낮춰 둔다. 제습 운전도 실내가 설정 아래로 내려가면 압축기가 멈춰
        (써모오프) 습기를 못 뺀다 (C13 — 26 °C · 80 %). 사용자 설정 범위 하한으로 클램프."""
        g = self.p.get
        cl = "comfort_ladders."
        return max(g(cl + "ac_dry_min_setpoint_c"), sp - g(cl + "ac_dry_setpoint_below_c"))

    def _band_ml(self, key: str) -> float:
        return self.p.get(f"means_ladder.{key}") if self.hyst else 0.0

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
        # 외기가 더 시원한가 — 히스테리시스 (경계에서 실내 온도 잡음만으로 매 주기 뒤집히지 않게, X2 물리 모드)
        need_dt = g("means_ladder.window_cooling_requires_outdoor_below_c")
        if self._outdoor_cooler:
            need_dt -= self._band_ml("window_cooling_release_band_c")
        self._outdoor_cooler = (not math.isnan(o.outdoor_temp_c) and o.outdoor_temp_c <= o.temp_c - need_dt)
        outdoor_cooler = self._outdoor_cooler
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
        if not self.cooling or not free_cool or not ac_allowed:
            # 에어컨이 없으면 승격할 곳이 없다 — 무료 냉방을 멈추면 아무 냉방도 안 하게 된다 (X8 P-core · 상충 점검 R10)
            self._escalated, self._free_cool_since = False, None
        else:
            if self._free_cool_since is None:
                self._free_cool_since = o.now_s
            over_at = sp + g(cl + "escalate_above_setpoint_c")
            # 외기가 냉방 목표보다 더우면 환기로는 목표에 닿을 수 없다 — 15분을 기다리지 않고 바로 승격 (EXP-1 28 °C 귀가 · v3.4.20)
            sp_reach = sp + (g("interaction_rules.I5_ceiling_fan_setpoint_relax_c") if "ceiling_fan" in self.rules.devices else 0.0)
            unreachable = o.outdoor_temp_c > sp_reach - g(cl + "free_cool_reach_margin_c")
            if (not self._escalated and o.temp_c > over_at
                    and (unreachable or o.now_s - self._free_cool_since >= g(cl + "escalate_to_ac_after_s"))):
                self._escalated, self._escalated_since = True, o.now_s
            elif (self._escalated and o.temp_c <= over_at - self._band("escalate_release_band_c")
                  and (not self.hyst or o.now_s - self._escalated_since >= g(cl + "escalate_min_hold_s"))):
                # 승격 최소 유지 — 풀리자마자 창문으로 돌아가 다시 더워지는 왕복을 막는다 (실측 기상 C4)
                self._escalated = False
        window_cool = free_cool and not blocked and not self._escalated   # 창문을 냉방에 쓰나
        if self._blind_choice is None:
            self._blind_choice = CoolingBlind(self.p, self.rules.lighting)
        saving_w = self._blind_choice.solar_w(o, 0.0) - self._blind_choice.solar_w(o, g("setpoints.blind_shade_angle_deg"))
        cb = "means_ladder.cooling_blind."
        if saving_w >= g(cb + "engage_min_saving_w"):          # 흐린 날도 막을 열이 있으면 판단 (상충 점검 R9)
            self._shade_useful = True
        elif saving_w < (g(cb + "engage_release_saving_w") if self.hyst else g(cb + "engage_min_saving_w")):
            self._shade_useful = False
        shade_useful = self._shade_useful
        if self.cooling:
            if shade_useful:
                # 블라인드 각도 — 막는 일사열 vs 잃는 환기 냉방 vs 늘어나는 조명 열 (v3.4.18 · 고정 순서 없음)
                li = self.rules.lighting
                lm = m.get("lighting") or {}
                target = 0.0 if lm.get("target") in (None, "none") else float(
                    lm.get("ceiling_lux", lm.get("lux", 0.0)) if lm.get("target") == "desk" else lm.get("lux", 0.0))
                glare_min = (li._glare_deg or 0.0) if li._glare else 0.0      # 눈부심 차광보다 덜 가리지는 않는다
                ratio = g("setpoints.window_vent_ratio_pct") / 100.0 if window_cool else 0.0
                deg, why = self._blind_choice.choose(o, target, ratio, glare_min)
                add("blind", "need", deg, L5, why)
                info["cooling_blind"] = self._blind_choice.last
            else:
                if self._blind_choice is not None:
                    self._blind_choice.reset()
                if m.get("blind_policy") == "night_cooling" and outdoor_cooler:   # 복사냉각은 공기를 들이지 않는다 — I10 무관
                    add("blind", "need", g("setpoints.blind_night_cooling_deg"), L5, "냉방 — 야간 복사냉각 블라인드 개방 (수면)")
            if window_cool:
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
                prev = self._ac_dry
                # 더 많이 벗어난 쪽 우선 — 습도가 조금만 넘으면 온도가 먼저 (B8), 크게 넘으면 제습을 오래 끈다 (C1 · C13)
                humid_first = hi is not None and o.rh_pct - hi >= g(cl + "humid_priority_excess_pct")
                resume = g(cl + "ac_cool_resume_above_c") if humid_first else g(cl + "ac_cool_resume_above_mild_c")
                dwell_ok = (humid_first or not self.hyst
                            or o.now_s - self._ac_mode_since >= g(cl + "ac_mode_min_dwell_s"))
                if self.dehumidifying and season == "summer":
                    if not self._ac_dry and dwell_ok and o.temp_c <= sp_ac + g(cl + "ac_dry_within_setpoint_c"):
                        self._ac_dry = True
                    elif self._ac_dry and o.temp_c > sp_ac + resume:
                        self._ac_dry = False
                else:
                    self._ac_dry = False
                if self._ac_dry != prev:
                    self._ac_mode_since = o.now_s
                why = "냉방 ⑤ 에어컨" + (" (승격 — 무료 냉방 부족)" if escalate else "") + (f" (I5 +{relax:g} °C)" if relax else "")
                ac_cmd = ("dry", self._dry_sp(sp_ac), why + " → 제습 모드 (냉방 + 제습)") if self._ac_dry else ("cool", sp_ac, why)
        info["cooling"] = self.cooling
        if sp is not None:                              # 실제 냉방 목표 (I5 완화 포함) — 제어 가능성 판정이 쓴다
            info["cooling_target_c"] = sp + (g("interaction_rules.I5_ceiling_fan_setpoint_relax_c")
                                             if "ceiling_fan" in self.rules.devices else 0.0)

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
                    ac_cmd = ("dry", self._dry_sp(sp), "제습 ③ 에어컨 제습 (I6 여름)")
            else:
                add("dehumidifier", "need", 1, L5, f"제습 ③ 제습기 (I6 {season})")
        # I6 해제 확장 — 요리 · 샤워가 들인 습기: 이벤트 중 RH 가 상한을 넘으면 상한 − 해제 폭까지 제습기 보조 (보류 H10)
        if hi is not None and g("comfort_ladders.moisture_recovery_dehumidifier") and "dehumidifier" in self.rules.devices:
            if self.moisture_event and o.rh_pct > hi:
                self._moisture_recovery = True
            elif o.rh_pct < hi - self._band("dehumidify_off_band_pct") or not self.dehumidifying:
                self._moisture_recovery = False
            if self._moisture_recovery and not (i10 and not blocked):
                add("dehumidifier", "need", 1, L5, "제습 — 요리 · 샤워 습기 회복 보조 (I6 해제 확장)")
        info["dehumidifying"] = self.dehumidifying
        # 목표별 '쓸모 있는 수단' — 제어 가능성 판정(feasibility)이 소진 여부를 볼 때 쓴다 (외기가 더 더우면 환기는 냉방 수단이 아니다)
        info["useful_means"] = {
            "cooling": {"ac": ac_allowed, "window": free_cool, "exhaust": free_cool, "intake": free_cool,
                        "ceiling_fan": True, "blind": shade_useful},
            "dehum": {"ac": ac_allowed and season == "summer", "dehumidifier": True, "window": i10, "exhaust": i10},
        }

        # ---- 가습 (I4 상한) ----
        lo = (m.get("humidity_range_pct") or [None, None])[0]
        r_si = self.psy.surface_resistance(o.blind_deg, o.ceiling_fan)
        cap = self._humidify_cap(o, r_si)
        # 결로 상한에 딱 붙으면 끄는 지연 동안 여유가 상한 아래로 내려간다 — 상한 − guard 에서 멈춘다 (보류 H9)
        target = min(hi - g("comfort_ladders.humidify_target_below_hi_pct") if hi is not None else 100.0,
                     cap - g("comfort_ladders.humidify_cap_guard_pct"))
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
            if not self._hum_paused and not self.dehumidifying:     # 제습 중에는 가습하지 않는다 (상충 점검 R5)
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


def ac_json(info: dict, on: bool, seq: int = 0) -> str:
    if not on or "ac" not in info:
        return json.dumps({"power": False, "mode": "cool", "setpoint": 26.0, "fan": "auto", "seq": seq})
    a = info["ac"]
    return json.dumps({"power": True, "mode": a["mode"], "setpoint": a["setpoint"], "fan": a["fan"], "seq": seq})
