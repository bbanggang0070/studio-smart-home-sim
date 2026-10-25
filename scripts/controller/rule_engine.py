"""규칙 엔진 (docs/07 §4 · §3.3–3.5) — 모드 ⊕ 이벤트 ⊕ 규칙 → 계층별 후보 명령.

장치 이름 (제어기 내부)
    window(0–1) · blind(deg) · exhaust(rpm) · intake(rpm) · hood(0–2) · purifier(0–3)
    dehumidifier(0/1) · humidifier(0/1) · ceiling_fan(−2…2)

v1 범위: L1 강우 · 외기 등급 · I2 / L2 요리(I3 보상 급기 · 후드 예측) · 샤워(I10 · 균형 급기) · 결로 위험 /
         L3 외출 보안 / L4 소음 등급 · 금지 장치 / L5 재실 기본 환기 · 실내 PM · 결로 경고 · 냉방 · 제습 · 가습 사다리(ladders.py).
조명 사다리와 E4 · E7–E15 는 W09–W10 에 같은 틀로 더한다.
"""

from __future__ import annotations

import math
from collections import deque

from controller.arbiter import Candidate
from controller.energy import EnergyPlanner, daylight_fn
from controller.event_detector import GRADE_ORDER, ActiveEvent, _History, own_load_w
from controller.ladders import ComfortLadders
from controller.lighting import Lighting
from controller.params import ControllerParams
from controller.predictor import HoodPredictor, Plan
from controller.signals import Observation, Psychro

L0, L1, L2, L3, L4, L5, L6 = 0, 1, 2, 3, 4, 5, 6


class RuleEngine:
    def __init__(self, p: ControllerParams, psy: Psychro, hysteresis: bool = True, primary_goals: bool = True):
        self.p, self.psy = p, psy
        self.primary_goals = primary_goals          # False = Proposed−P (우선 목표 비활성, C15 대조군)
        self.pred = HoodPredictor(p)
        g = p.get
        self.intake_max_m3h = g("appliances.intake_fan.max_m3h")
        self.intake_max_rpm = g("appliances.intake_fan.max_rpm")
        self.exhaust_max_m3h = g("appliances.exhaust_fan.max_m3h")
        self.exhaust_max_rpm = g("appliances.exhaust_fan.max_rpm")
        self.devices = set(g("appliances.profiles")[g("appliances.profile")])
        self.pm_hist: deque[tuple[float, float]] = deque(maxlen=240)
        self._i10_open = False
        self._hood_next_eval = -math.inf
        self._laundry_cooling = False
        self._laundry_temps = _History(120.0)       # 빨래 건조 냉방 ↔ 제습 판단용 평균 온도 (v3.4.27)
        self._precool_dry = False                   # 프리쿨링 제습 모드 (히스테리시스 · v3.4.27)
        self.filter_hours = 0.0                     # 흡기 필터 누적 가동 시간 (제어기가 스스로 기록 · 교체 시 0)
        self._e4_short_since: float | None = None
        self._e4_ok_since: float | None = None
        self._cooktop_cut = False
        self.alerts: list[str] = []
        self.info: dict = {}
        self.ladders = ComfortLadders(p, psy, self, hysteresis)
        self.hysteresis = hysteresis
        self._pm_level = 0                          # 실내 PM 청정기 단 (히스테리시스 상태)
        self._pm_avg: float | None = None           # 청정기 판단용 PM 이동평균
        self._pm_last_t: float | None = None
        self.lighting = Lighting(p)
        self._mm_alerted = False
        self.energy: EnergyPlanner | None = None    # 외출 전략 · 프리쿨링 (smart_home 이 사용자 설정으로 만든다)
        self.home_mode = "NORMAL"                   # 외출 직전 모드 — 프리쿨링 목표 (smart_home 이 알려 준다)
        self._energy_last_t: float | None = None

    # ---- 도우미 ----

    def _energy_observe(self, o: Observation) -> None:
        """2R2C 관측기 — 축열 질량 온도를 매 주기 따라간다 (외출 전에도)."""
        if self.energy is None or math.isnan(o.outdoor_temp_c):
            return
        dt = 0.0 if self._energy_last_t is None else o.now_s - self._energy_last_t
        self._energy_last_t = o.now_s
        lux = max(0.0, o.illuminance_lux - self.lighting._own_light(o)) if o.illuminance_lux == o.illuminance_lux else 0.0
        self.energy.observe(o.temp_c, o.outdoor_temp_c, lux, 1.0 if o.occupied else 0.0,
                            float(o.power_w.get("ac", 0.0)), dt)

    def _away_ac(self, o: Observation, ev: dict[str, ActiveEvent], add) -> None:
        """L3 외출 — 셋백 · 끄기 · 끄기 + 프리쿨링 (docs/08 §5.3–5.4 · E13)."""
        sp = self.p.mode(self.home_mode).get("cooling_setpoint_c")
        # 사용자가 직접 AWAY 를 고른 경우(여행 · 장기 외출 — C14)는 오늘 귀가를 예측하지 않는다
        if (self.energy is None or sp is None or self.ladders.season(o) != "summer"
                or math.isnan(o.outdoor_temp_c) or o.user_mode == "AWAY"):
            add("ac", "cap", 0, L3, "외출 — 냉방 정지")
            return
        lux = max(0.0, o.illuminance_lux) if o.illuminance_lux == o.illuminance_lux else 0.0
        d = self.energy.step(o.tod_s, o.outdoor_temp_c, daylight_fn(self.p, o.tod_s, lux), sp)
        self.info["energy_forecast"] = d
        if d["precool_active"]:
            ev.setdefault("PRECOOL", ActiveEvent("PRECOOL", o.now_s, {"start_tod": d["start_tod"]}))
            # 습도 동시 제어 — 설정 근처에 왔는데 습도가 모드 상한을 넘으면 제습 운전 (사다리 C1 규칙과 같다)
            # 히스테리시스 — 들어갈 때 '설정 + within 이하 · 상한 초과', 나올 때 '설정 + resume_mild 초과 또는 상한 − off_band 미만'
            # (없으면 설정 + 0.5 경계에서 매 초 냉방 ↔ 제습 — C16 330회 · v3.4.27)
            rh_hi = self.p.mode(self.home_mode)["humidity_range_pct"][1]
            cl = "comfort_ladders."
            if rh_hi is None:
                self._precool_dry = False
            elif self._precool_dry:
                self._precool_dry = not (o.temp_c > sp + self.p.get(cl + "ac_cool_resume_above_mild_c")
                                         or o.rh_pct < rh_hi - self.p.get(cl + "dehumidify_off_band_pct"))
            else:
                self._precool_dry = o.rh_pct > rh_hi and o.temp_c <= sp + self.p.get(cl + "ac_dry_within_setpoint_c")
            dry = self._precool_dry
            add("ac", "force", 1, L3, f"E13 프리쿨링 — {sp:g} °C" + (" · 제습" if dry else "")
                + f" (귀가 중앙 {d['arrival_q50'] / 3600:.2f} h)")
            self.info["ac_override"] = ({"mode": "dry", "setpoint": self.ladders._dry_sp(sp), "fan": "auto"} if dry
                                        else {"mode": "cool", "setpoint": sp, "fan": "auto"})
        elif d["strategy"] == "setback":
            sb = sp + self.p.get("energy.away_strategy.setback_c")
            add("ac", "force", 1, L3, f"외출 셋백 — {sb:g} °C 유지")
            self.info["ac_override"] = {"mode": "cool", "setpoint": sb, "fan": "auto"}
        else:
            ev.pop("PRECOOL", None)
            add("ac", "cap", 0, L3, f"외출 — 냉방 정지 (전략 {d['strategy']})")

    def filter_factor(self) -> float:
        """필터 막힘에 따른 흡기 유량 비율 (누적 가동 시간 선형 — base_ventilation.shortfall)."""
        g = self.p.get
        clog = min(self.filter_hours / g("appliances.intake_fan.filter_replace_hours"), 1.0)
        return 1.0 - g("base_ventilation.shortfall.filter_flow_loss_at_replace") * clog

    def intake_rpm_for(self, m3h: float) -> float:
        """원하는 유량을 내는 흡기팬 rpm — 필터 막힘을 보정한다."""
        return min(self.intake_max_rpm, m3h / (self.intake_max_m3h * self.filter_factor()) * self.intake_max_rpm)

    def exhaust_m3h(self, rpm: float) -> float:
        return self.exhaust_max_m3h * min(rpm / self.exhaust_max_rpm, 1.0)

    def window_blocked(self, o: Observation, ev: dict[str, ActiveEvent], mode: str) -> list[str]:
        """I3 · 기본 환기 — 창문을 급기 수단으로 쓸 수 없는 이유들."""
        why = []
        if "RAIN" in ev:
            why.append("rain")
        if GRADE_ORDER.index(o.outdoor_pm_grade) >= GRADE_ORDER.index("bad"):
            why.append("outdoor_pm_bad")
        elif (self._pm_level >= 1 and GRADE_ORDER.index(o.outdoor_pm_grade)
              >= GRADE_ORDER.index(self.p.get("indoor_pm.window_block_grade_while_purifying"))):
            # 청정기가 실내 PM 을 낮추는 중인데 외기가 목표보다 깨끗하지 않다 — 창문은 PM 을 들여 청정기와 상충 (v3.4.18 상충 점검 R6)
            why.append("pm_purifying")
        if o.ac_cooling:
            why.append("ac_cooling")
        if mode == "AWAY":
            why.append("away")
        if o.safety_state not in ("NORMAL", "LOCAL_CUTOFF"):
            why.append("safety")                        # 끼임 SAFETY_HOLD · 방향 잠금 — 창문 불가 → 팬으로 재분배 (docs/04 §3.7 ⑥)
        if "window" not in self.devices:
            why.append("no_window")
        return why

    def noise_grade(self, mode: str, ev: dict[str, ActiveEvent]) -> str:
        """유효 소음 등급 — L2 이벤트가 모드(L4) 상한을 임시로 바꾼다 (docs/07 §2.3)."""
        grade = self.p.mode(mode).get("noise_grade") or "N2"
        if "COOKING" in ev or "HOOD_POST_RUN" in ev:
            return self.p.get("events.cooking.noise_grade_override")
        if "SHOWER" in ev:
            return "N1" if mode == "SLEEP" else self.p.get("events.shower.noise_grade_override")
        if "VENT_SHORTFALL" in ev:                   # E4 — 소음 상한을 한 단계만 완화 (N0 → N1)
            order = ["N0", "N1", "N2", "N3"]
            steps = int(self.p.get("base_ventilation.shortfall.noise_relax_steps"))
            return order[min(order.index(grade) + steps, 2)]
        return grade

    def _pm_slope_per_h(self, now: float) -> float | None:
        if len(self.pm_hist) < 2:
            return None
        t0, p0 = next(((t, v) for t, v in self.pm_hist if now - t <= 60.0), self.pm_hist[0])
        t1, p1 = self.pm_hist[-1]
        return (p1 - p0) / (t1 - t0) * 3600.0 if t1 > t0 else None

    # ---- 규칙 ----

    def candidates(self, o: Observation, mode: str, ev: dict[str, ActiveEvent]) -> list[Candidate]:
        g = self.p.get
        self._mode = mode
        self.pm_hist.append((o.now_s, o.pm25))
        out: list[Candidate] = []
        add = lambda dev, kind, val, layer, why: out.append(Candidate(dev, kind, float(val), layer, why))
        blocked = self.window_blocked(o, ev, mode)
        self._vent_shortfall(o, mode, ev, blocked)
        grade = self.noise_grade(mode, ev)
        noise = self.p.noise(grade)
        self.info = {"noise_grade": grade, "window_blocked": blocked}

        # -- L1 안전 인터록 --
        if "RAIN" in ev:
            add("window", "force", 0.0, L1, "E5 강우")
        pol = g("air_quality.grade_policy")[o.outdoor_pm_grade]
        add("window", "cap", pol["window_max_pct"] / 100.0, L1, f"외기 {o.outdoor_pm_grade} 창문 상한")
        add("exhaust", "cap", pol["fan_max_rpm"], L1, f"외기 {o.outdoor_pm_grade} 배기 상한")
        if o.ac_cooling:
            add("window", "cap", g("interaction_rules.I2_ac_cooling_window_max_pct") / 100.0, L1, "I2 냉방 중 창문")
        if pol.get("purifier_min_level", 0) > 0 and mode != "AWAY":
            add("purifier", "need", pol["purifier_min_level"], L5, f"외기 {o.outdoor_pm_grade} 청정기 예방 가동")

        # E15 — 플러그형 인덕션이면 전원 차단, 사람이 돌아오면 복구 (가스 · 빌트인은 경고만)
        un = ev.get("UNATTENDED_COOKING")
        if un and un.info.get("plug") and g("events.unattended_cooking.plug_cooktop_cutoff") and "cooktop_plug" in self.devices:
            add("cooktop", "force", 0, L1, "E15 불 켜고 외출 — 플러그형 인덕션 전원 차단")
            self._cooktop_cut = True
        elif self._cooktop_cut and o.occupied:
            add("cooktop", "force", 1, L1, "귀가 — 쿡탑 계량 플러그 전원 복구")
            self._cooktop_cut = False
        elif self._cooktop_cut:
            add("cooktop", "force", 0, L1, "E15 차단 유지 (귀가 전)")

        # -- L2 건강 · 재산 --
        self._cooking(o, ev, blocked, noise, add)
        self._shower(o, ev, blocked, noise, add, mode)
        cond = ev.get("CONDENSATION")
        if cond and cond.info.get("level") == "critical":
            add("blind", "force", g("condensation.blind_slat_on_critical_deg"), L2, "E2 결로 위험 블라인드 개방")
            add("humidifier", "force", 0, L2, "E2 결로 위험 가습 금지")
            add("ceiling_fan", "need", -1, L2, "E2 결로 위험 실링팬 역회전")
            add("dehumidifier", "need", 1, L2, "E2 결로 위험 제습")
            self._pulse_vent(o, cond, blocked, add)

        # -- L4.5 우선 목표 (E10 빨래 건조) · L1 전력 한도 (E11) --
        self._laundry(o, ev, mode, noise, add)
        self._power_limit(o, ev, add)

        # -- L3 절전 · 외출 --
        if mode == "AWAY":
            add("window", "force", 0.0, L3, "외출 보안 (창문 닫힘)")

        # -- L4 모드 제약 (소음 등급 · 금지 장치) --
        add("exhaust", "cap", noise["exhaust_fan_max_rpm"], L4, f"소음 {grade}")
        add("intake", "cap", noise["intake_fan_max_rpm"], L4, f"소음 {grade}")
        add("purifier", "cap", noise["purifier_max_level"], L4, f"소음 {grade}")
        add("hood", "cap", noise["range_hood_max_level"], L4, f"소음 {grade}")
        if not noise["dehumidifier_allowed"]:
            add("dehumidifier", "cap", 0, L4, f"소음 {grade} 제습기 금지")
        cooking = "COOKING" in ev or "HOOD_POST_RUN" in ev
        for item in self.p.mode(mode).get("forbidden") or []:
            if item == "range_hood" and not cooking:
                add("hood", "cap", 0, L4, f"{mode} 금지")
            elif item == "range_hood_high" and not cooking:
                add("hood", "cap", 1, L4, f"{mode} 금지")
            elif item == "purifier_level_2_plus":
                add("purifier", "cap", 1, L4, f"{mode} 금지")
            elif item in ("purifier", "humidifier", "dehumidifier", "ceiling_fan"):
                add(item, "cap", 0, L4, f"{mode} 금지")

        # -- L5 쾌적 --
        self._base_ventilation(o, mode, blocked, add)
        saving = not o.occupied and mode != "AWAY"
        self.info["saving"] = saving
        self.ladders.moisture_event = "COOKING" in ev or "HOOD_POST_RUN" in ev or "SHOWER" in ev
        self.info.update(self.ladders.apply(o, mode, blocked, noise, add, saving=saving))
        # -- L6 조도 · 조명 --
        if "ceiling_light" in self.devices or "desk_lamp" in self.devices:
            li = self.lighting.apply(o, mode, saving, self.ladders.cooling, add)
            if "alert" in li:
                self.alerts.append(li.pop("alert"))
            self.info.update(li)
        if o.zone == "unknown" and not self._mm_alerted:     # X3 — 레이더 두절: 위치 구분 불가 → AUTO 는 NORMAL
            self.alerts.append({"code": "S_MMWAVE", "level": "warning", "t": o.now_s,
                                "msg": "mmWave 신호 두절 — Wi-Fi · 전력으로만 재실 판단 · 자동 모드는 NORMAL 고정"})
            self._mm_alerted = True
        self._energy_observe(o)
        if mode == "AWAY" and "ac" in self.devices:
            self._away_ac(o, ev, add)
        elif self.energy is not None:
            self.energy.end_away(o.tod_s)
        pm = "indoor_pm."
        # 히스테리시스 — 켜는 기준(목표 · 나쁨)을 넘어 켰으면 기준 − off_band 아래로 내려가야 한 단 내린다 (센서 잡음 채터링, B5)
        band = g(pm + "purifier_off_band_ugm3") if self.hysteresis else 0.0
        bad_at = g(pm + "bad_ugm3") - (band if self._pm_level >= 2 else 0.0)
        tgt_at = g(pm + "target_ugm3") - (band if self._pm_level >= 1 else 0.0)
        # 청정기 판단은 이동평균으로 (센서 잡음에 단이 오르내리지 않게) — 요리 감지 등 이벤트는 원값을 쓴다
        dt = 1.0 if self._pm_last_t is None else max(o.now_s - self._pm_last_t, 0.0)
        self._pm_last_t = o.now_s
        a = 1.0 - math.exp(-dt / g(pm + "control_filter_s")) if self._pm_avg is not None else 1.0
        self._pm_avg = o.pm25 if self._pm_avg is None else self._pm_avg + a * (o.pm25 - self._pm_avg)
        pm_ctl = self._pm_avg
        if pm_ctl > bad_at:
            self._pm_level = 2
            add("purifier", "need", g(pm + "purifier_level_above_bad"), L5, "실내 PM 나쁨")
        elif pm_ctl > tgt_at:
            self._pm_level = 1
            add("purifier", "need", g(pm + "purifier_level_above_target"), L5, "실내 PM 목표 초과")
        else:
            self._pm_level = 0
        if cond and cond.info.get("level") == "warn":
            add("ceiling_fan", "need", -1, L5, "E2 결로 경고 실링팬 역회전")
            add("humidifier", "cap", 0, L5, "E2 결로 경고 가습 중단")
        return out

    def _pulse_vent(self, o: Observation, cond: ActiveEvent, blocked: list[str], add) -> None:
        """E2 위험 — 외기 절대습도가 낮으면 간헐 환기 (창문 20 % × 60 s / 300 s + 배기 저속). 난방 손실을 줄이려 짧게."""
        g = self.p.get
        if blocked or math.isnan(o.outdoor_temp_c):
            return
        if self.psy.dew_point(o.outdoor_temp_c, o.outdoor_rh_pct) >= self.psy.dew_point(o.temp_c, o.rh_pct):
            return                                         # 바깥 공기가 더 습하면 환기는 제습이 아니다
        phase = (o.now_s - cond.since_s) % g("setpoints.window_pulse_interval_s")
        if phase < g("setpoints.window_pulse_duration_s"):
            add("window", "need", g("setpoints.window_pulse_ratio_pct") / 100.0, L2, "E2 결로 위험 간헐 환기")
            add("exhaust", "need", g("setpoints.fan_low_rpm"), L2, "E2 결로 위험 간헐 환기 (배기 저속)")

    def supply_blocked(self, o: Observation, blocked: list[str]) -> list[str]:
        """I3 보상 급기에 창문을 못 쓰는 이유 — 창문 불가 사유 + 외기온이 기본 환기 창문 범위 밖 (v3.4.24 · 보류 H3)."""
        g = self.p.get
        if not g("interaction_rules.I3_exhaust_requires_supply.window_requires_outdoor_temp_range"):
            return blocked
        lo, hi = g("base_ventilation.window_outdoor_temp_range_c")
        if math.isnan(o.outdoor_temp_c) or not lo <= o.outdoor_temp_c <= hi:
            return [*blocked, "outdoor_temp"]
        return blocked

    def _supply_for(self, exhaust_m3h: float, o: Observation, blocked: list[str], window_ratio: float,
                    add, why: str) -> None:
        """I3 · I7 — 기계 배기에 맞춰 급기. 창문을 쓸 수 있으면 창문, 아니면 흡기팬(필터).
        흡기팬 최대(60 m³/h)는 후드 유량보다 훨씬 작다 — 창문을 못 쓰면 급기는 최선일 뿐 양압은 보장하지 못한다 (장비 한계)."""
        g = self.p.get
        blocked = self.supply_blocked(o, blocked)
        if not blocked:
            add("window", "need", window_ratio, L2, f"{why} I3 보상 급기 (창문)")
        else:
            bad = "outdoor_pm_bad" in blocked
            pct = g("interaction_rules.I3_exhaust_requires_supply.bad_air_intake_pct") if bad else None
            rpm = self.intake_max_rpm * pct / 100.0 if pct is not None else self.intake_rpm_for(exhaust_m3h)
            add("intake", "need", rpm, L2, f"{why} I3 보상 급기 (흡기팬 · {','.join(blocked)})")

    def _cooking(self, o, ev, blocked, noise, add) -> None:
        g = self.p.get
        c = "events.cooking."
        cook, post = ev.get("COOKING"), ev.get("HOOD_POST_RUN")
        if post and not cook:
            lv = int(post.info.get("level", 1))
            if lv <= 0:
                return
            add("hood", "need", lv, L2, "E1 후드 잔류 운전")
            self._supply_for(g("appliances.range_hood.flow_m3h")[f"l{lv}"], o, blocked,
                             g(c + "compensating_window_ratio"), add, "E1 잔류")
            return
        if not cook:
            self._hood_next_eval = -math.inf
            return
        bad_out = GRADE_ORDER.index(o.outdoor_pm_grade) >= GRADE_ORDER.index("bad")
        if cook.info["source"] == "steam":
            lv = int(g(c + "steam_hood_level"))
            cook.info["hood_level"] = lv
            add("hood", "need", lv, L2, "E1 수증기 (열만) 후드 약")
        else:
            lv = self._choose_hood(o, cook, self.supply_blocked(o, blocked), noise, outdoor_polluted="OUTDOOR_PM" in ev)
            add("hood", "need", lv, L2, f"E1 요리 후드 예측 선택 {cook.info.get('peaks', {})}")
            winter = self.ladders.season(o) == "winter"           # 후드를 낮춘 만큼 청정기로 PM 보완 (v3.4.25)
            add("purifier", "need", g(c + ("purifier_level_outdoor_bad" if bad_out or winter else "purifier_level")), L2,
                "E1 요리 청정기" + (" (겨울 — 후드 제한 보완)" if winter and not bad_out else ""))
        # R4 — 비 오는 날 요리: 보상 급기가 습한 외기를 들이므로 요리 시작과 함께 에어컨 제습을 앞당긴다 (X5 · docs/07 §3.5)
        sp = self.p.mode(self._mode).get("cooling_setpoint_c")
        if ("RAIN" in ev and g("recovery.precondition_on_event_start") and "ac" in self.devices and sp is not None
                and self.ladders.season(o) == "summer"):
            add("ac", "need", 1, L2, "E1 · 우천 — 에어컨 유지 + 제습 앞당김 (설정 −1 °C, R4)")
            self.info["ac_override"] = {"mode": "cool", "setpoint": sp + g("recovery.ac_dry_boost_setpoint_c"),
                                        "fan": noise["ac_fan_max"]}
        if lv > 0:
            self._supply_for(g("appliances.range_hood.flow_m3h")[f"l{lv}"], o, blocked,
                             g(c + "compensating_window_ratio"), add, "E1")

    def _choose_hood(self, o, cook: ActiveEvent, blocked, noise, outdoor_polluted: bool) -> int:
        g = self.p.get
        hp = "events.cooking.hood_prediction."
        heat_ended = bool(cook.info.get("heat_ended"))
        # 열이 꺼진 뒤 — 외기가 깨끗하면 마지막 단수를 유지해 해제 · 잔류 운전까지 간다 (docs/07 §5.4 추적표).
        # 외기 오염(E6) 중이면 '발생원 없음'으로 한 번 더 예측해 고른다 — 후드 음압이 오염 외기를 끌어들이는 것을 막는다
        # (docs/09 §5: 외기 오염 시 약 · 강 · 끔 중 실내 PM 이 가장 낮을 단수)
        over_winter = (self.ladders.season(o) == "winter" and "hood_level" in cook.info
                       and cook.info["hood_level"] > int(g("events.cooking.winter_hood_max_level")))
        if "hood_level" in cook.info and not over_winter:        # 겨울 상한을 넘는 단은 유지하지 않고 다시 고른다
            if heat_ended and not outdoor_polluted:
                return cook.info["hood_level"]
            if heat_ended and cook.info.get("post_heat_chosen"):
                return cook.info["hood_level"]
            if not heat_ended and o.now_s < self._hood_next_eval:
                return cook.info["hood_level"]
        pm_out = g("air_quality.grade_representative_ugm3")[o.outdoor_pm_grade]
        purifier = g("events.cooking." + ("purifier_level_outdoor_bad" if "outdoor_pm_bad" in blocked
                                          else "purifier_level"))
        plans = []
        top = int(noise["range_hood_max_level"])
        if self.ladders.season(o) == "winter":
            # 겨울 — 후드 강의 침기 냉기가 난방을 넘는다 (v3.4.25 · 보류 H3 · H208). 요리 중 끄지는 않는다(I8)
            top = min(top, int(g("events.cooking.winter_hood_max_level")))
        for lv in range(0, top + 1):
            q_hood = g("appliances.range_hood.flow_m3h")[f"l{lv}"] if lv > 0 else 0.0
            if blocked:
                plans.append(Plan(lv, self.intake_max_m3h if lv > 0 else 0.0, 0.0, purifier))
            else:
                plans.append(Plan(lv, 0.0, q_hood, purifier))   # 창문이 보충 공기를 받는다 (큰 개구)
        slope = self._pm_slope_per_h(o.now_s)
        if heat_ended:
            source = 0.0                                    # 요리 끝 — 발생원 없음
            cook.info["post_heat_chosen"] = True
        elif o.now_s - cook.since_s < g(hp + "source_estimate_after_s") or slope is None:
            source = self.pred.nominal_ug_h
        else:
            current = Plan(o.hood_level, self.intake_max_m3h * o.intake_rpm / self.intake_max_rpm,
                           0.0 if blocked else (g("appliances.range_hood.flow_m3h")[f"l{o.hood_level}"]
                                                if o.hood_level > 0 else 0.0), o.purifier_level)
            source = self.pred.estimate_source(o.pm25, slope, current, pm_out)
            # 불이 켜져 있는 동안(후드 아래 열 유지)은 발생량을 사전값 아래로 보지 않는다 —
            # 끄기 직전 PM 이 꺾이는 순간의 추정으로 후드를 꺼 버리는 것을 막는다
            if not cook.info.get("heat_ended"):
                source = max(source, self.pred.nominal_ug_h)
        # 창문 급기 불가 — 후드 음압을 흡기팬이 못 메운다(장비 한계). PM 목표를 지키는 가장 낮은 단까지 허용 (v3.4.24 · 보류 H5 · H10)
        cap = g(hp + "blocked_supply_peak_cap_ugm3") if blocked else None
        plan, peaks = self.pred.choose(plans, o.pm25, pm_out, source, peak_cap=cap)
        cook.info.update(hood_level=plan.hood_level, peaks={k: round(v) for k, v in peaks.items()},
                         source_ug_h=round(source))
        self._hood_next_eval = o.now_s + g(hp + "reevaluate_s")
        return plan.hood_level

    def _shower(self, o, ev, blocked, noise, add, mode: str) -> None:
        g = self.p.get
        if "SHOWER" not in ev:
            self._i10_open = False
            return
        # R4 — 안에서 처리하는 수단을 앞당겨 쓴다: 제습기 허용(E3 가 I6 해제) · 여름엔 에어컨 제습 강화
        add("dehumidifier", "need", 1, L2, "E3 샤워 제습기 (I6 해제 · R4)")
        sp = self.p.mode(mode).get("cooling_setpoint_c")
        if (self.ladders.season(o) == "summer" and "ac" in self.devices and sp is not None):
            add("ac", "need", 1, L2, "E3 샤워 에어컨 제습 강화 (R4)")
            self.info["ac_override"] = {"mode": "dry", "setpoint": sp + g("recovery.ac_dry_boost_setpoint_c"),
                                        "fan": noise["ac_fan_max"]}
        i10 = "interaction_rules.I10_vent_dehumidify_requires_drier_outside."
        diff = self.psy.dew_point(o.temp_c, o.rh_pct) - self.psy.dew_point(o.outdoor_temp_c, o.outdoor_rh_pct) \
            if not math.isnan(o.outdoor_temp_c) else -math.inf
        if diff >= g(i10 + "enter_margin_c"):
            self._i10_open = True
        elif diff < g(i10 + "exit_margin_c"):
            self._i10_open = False
        self.info["i10_dew_diff_c"] = round(diff, 2) if math.isfinite(diff) else None
        if self._i10_open:
            rpm = noise["exhaust_fan_max_rpm"]
            add("exhaust", "need", rpm, L2, "E3 샤워 배기 강 (I10 바깥이 더 건조)")
            self._supply_for(self.exhaust_m3h(rpm), o, blocked, g("events.shower.compensating_window_ratio"),
                             add, "E3")
        else:
            add("dehumidifier", "need", 1, L2, "E3 샤워 실내 제습 (I10 바깥이 더 습함 · I6 해제)")

    def _vent_shortfall(self, o: Observation, mode: str, ev: dict, blocked: list[str]) -> None:
        """E4 기본 환기 미달 (docs/07 §3.3) — 모드의 소음 상한 안에서 흡기팬(필터 막힘 반영)으로 기본 환기량을 못 채우고
        창문도 못 쓰면 10분 뒤 진입 → 소음 상한 한 단계 완화 · 필터 교체 알림 1회.
        해제는 '원래 소음 상한으로도 채울 수 있게 되었을 때'(예: 필터 교체) 5분 — 완화 덕에 채워진 것으로 풀면 다시 미달이 반복된다."""
        from controller.event_detector import ActiveEvent
        g = self.p.get
        sf = "base_ventilation.shortfall."
        target = self.p.mode(mode).get("base_vent_m3h") or 0.0
        if not o.occupied or target <= 0.0 or "intake_fan" not in self.devices:
            self._e4_short_since = None
            ev.pop("VENT_SHORTFALL", None)
            return
        target = max(target, g("base_ventilation.hard_min_m3h"))
        mode_grade = self.p.mode(mode).get("noise_grade") or "N2"
        cap_m3h = (self.intake_max_m3h * min(1.0, self.p.noise(mode_grade)["intake_fan_max_rpm"] / self.intake_max_rpm)
                   * self.filter_factor())
        lo, hi = g("base_ventilation.window_outdoor_temp_range_c")
        window_ok = not blocked and not math.isnan(o.outdoor_temp_c) and lo <= o.outdoor_temp_c <= hi
        short = not window_ok and cap_m3h < target
        self.info["base_vent_capacity_m3h"] = round(cap_m3h, 1)
        if "VENT_SHORTFALL" not in ev:
            self._e4_short_since = (self._e4_short_since or o.now_s) if short else None
            if short and o.now_s - self._e4_short_since >= g(sf + "hold_s"):
                ev["VENT_SHORTFALL"] = ActiveEvent("VENT_SHORTFALL", o.now_s, {"capacity_m3h": cap_m3h})
                self.alerts.append({"code": "E4", "level": "warning", "t": o.now_s,
                                    "msg": f"필터 교체 · 흡기팬 점검 — 기본 환기 {target:g} m³/h 미달 (가능 {cap_m3h:.0f})"})
                self._e4_ok_since = None
        else:
            self._e4_ok_since = (self._e4_ok_since or o.now_s) if not short else None
            if self._e4_ok_since is not None and o.now_s - self._e4_ok_since >= g(sf + "release_hold_s"):
                ev.pop("VENT_SHORTFALL", None)

    def _laundry(self, o: Observation, ev, mode: str, noise: dict, add) -> None:
        """E10 — 우선 목표 = 건조 시간 (L4.5). I6 해제: 제습기 + (여름 · 간절기) 에어컨 냉방으로 열 상쇄 · 실링팬 강.
        온도 예산(+1.0 °C)을 지키려 에어컨 설정 = 진입 시 실내 온도. 외출이면 예산 +3.0 °C 로 에어컨을 생략할 수 있다."""
        lev = ev.get("LAUNDRY_DRYING")
        if lev is None or not self.primary_goals:
            return
        g = self.p.get
        e = "events.laundry_drying."
        L45 = g(e + "layer")
        add("dehumidifier", "need", 1, L45, "E10 빨래 건조 제습기 (I6 해제)")
        fan_max = {"low": 1, "mid": 1, "high": 2}[noise["ceiling_fan_max_speed"]]
        if "ceiling_fan" in self.devices:
            add("ceiling_fan", "need", min(g(e + "ceiling_fan_level"), fan_max), L45, "E10 빨래에 기류 (실링팬 정)")
        sp = self.p.mode(mode).get("cooling_setpoint_c")
        season = self.ladders.season(o)
        if season != "winter" and "ac" in self.devices and sp is not None:
            # 온도 예산은 상한이지 목표가 아니다 — 쾌적 냉방 설정(I5 포함)보다 높게 잡지 않는다 (C17: 진입 30 °C)
            relax = g("interaction_rules.I5_ceiling_fan_setpoint_relax_c") if "ceiling_fan" in self.devices else 0.0
            entry = lev.info["entry_temp_c"]
            target = min(entry + g(e + "ac_setpoint_above_entry_c"), sp + relax)
            # 기본은 제습 모드 — 온도가 예산에 가까워지면 냉방, 충분히 내려오면 다시 제습 (예산 히스테리시스)
            # 두 진입 조건 모두 해제 폭이 있다 — 설정 경계에 해제 폭이 없으면 온도 잡음만으로 매 초 냉방 ↔ 제습 (v3.4.27)
            # 판단은 average_window_s 평균 온도로 — 한 샘플로 경계에 닿아 1–2분마다 전환하던 문제 (센서 잡음 · v3.4.27 · C15)
            self._laundry_temps.push(o.now_s, o.temp_c)
            t_avg = self._laundry_temps.mean(o.now_s, 0.0, g(e + "average_window_s")) or o.temp_c
            want_cool = t_avg >= entry + g(e + "cool_switch_above_entry_c") or t_avg > sp + relax
            # 제습 복귀 기준은 실제로 보낸 냉방 설정(0.5 °C 단위 반올림) 기준 — 진입 온도 기준이면 반올림된 설정이 기준보다 높아
            # 에어컨이 설정을 지키는 한 닿지 않는다 (진입 24.76 → 설정 25.0 · 기준 24.96, v3.4.27)
            sent_sp = round(target * 2) / 2
            want_dry = (t_avg <= max(entry, sent_sp) + g(e + "dry_resume_below_entry_c")
                        and t_avg <= sp + relax - g(e + "setpoint_release_band_c"))
            if want_cool:
                self._laundry_cooling = True
            elif want_dry:
                self._laundry_cooling = False
            mode_ac = "cool" if self._laundry_cooling else g(e + "ac_mode")
            add("ac", "need", 1, L45, f"E10 제습기 열 상쇄 — 에어컨 {mode_ac} (예산 +{g(e + 'budget.indoor_temp_rise_c'):g} °C)")
            self.info["ac_override"] = {"mode": mode_ac, "setpoint": round(target * 2) / 2, "fan": noise["ac_fan_max"]}
        self.info["primary_goal"] = "drying_time"

    def _power_limit(self, o: Observation, ev, add) -> None:
        """E11 — I8 차단 순서대로 단계마다 하나씩 더 끈다 (L1). 요리 중 후드는 끄지 않는다(I8_never_shed)."""
        # 기동 전 여유 확인 — 꺼진 에어컨을 켜면 한도를 넘는다면 켜지 않는다. 켠 뒤 줄이려 해도 L0 압축기 최소 ON(300 s)
        # 동안 못 끈다 (v3.4.29 · 6차 보류 H608: 인덕션 1.5 kW 중 에어컨 기동 → 2.4 kW · 5분 초과)
        limit = float(self.p.modes["energy"]["power_limit_w"])
        if "ac" in self.devices and not o.ac_power:
            now_w = sum(float(v) for v in o.power_w.values()) + own_load_w(self.p, o)
            if now_w + float(self.p.get("appliances.ac.power_w")) > limit:
                add("ac", "cap", 0, L1, f"I8 에어컨 기동 전 여유 부족 (지금 {now_w:.0f} W + 정격 > 한도 {limit:.0f} W)")
        pev = ev.get("POWER_LIMIT")
        if pev is None:
            return
        order = self.p.get("interaction_rules.I8_power_shed_order")
        shed = pev.info["shed"]
        for item in order[: int(pev.info["stage"])]:
            if item == "purifier_step_down":
                shed.setdefault("purifier", max(0, o.purifier_level - 1))
                add("purifier", "cap", shed["purifier"], L1, "E11 전력 한도 — 청정기 한 단 하향 (I8)")
            elif item == "ac_setpoint_plus_1":
                self.info["ac_setpoint_offset"] = 1.0
            elif item == "ac_fan_low":
                self.info["ac_fan_force"] = "low"
            elif item in ("humidifier", "dehumidifier"):
                add(item, "cap", 0, L1, f"E11 전력 한도 — {item} 차단 (I8)")
            elif item == "ac_pause":
                # 마지막 단계 — 실제 한도를 넘을 때만 들어가고, 들어가면 E11 이 풀릴 때까지 유지 (보류 H2)
                # 에어컨이 (다시) 정격으로 돌 때의 합계 — 넘을 것 같으면 미리 멈추고, 여유가 생기면 E11 해제 대기 없이 재개 (보류 H2)
                limit = float(self.p.modes["energy"]["power_limit_w"])
                projected = (float(pev.info.get("total_w", 0.0)) - float(o.power_w.get("ac", 0.0))
                             + float(self.p.get("appliances.ac.power_w")))
                if not pev.info.get("ac_paused") and projected > limit:
                    pev.info["ac_paused"] = True
                elif pev.info.get("ac_paused") and projected < self.p.get("events.power_limit.release_ratio") * limit:
                    pev.info["ac_paused"] = False
                if pev.info.get("ac_paused"):
                    add("ac", "cap", 0, L1, "E11 전력 한도 — 에어컨 일시 정지 (I8 마지막 · 끌 수 없는 부하)")
        self.info["power_shed_stage"] = int(pev.info["stage"])

    def _base_ventilation(self, o: Observation, mode: str, blocked: list[str], add) -> None:
        g = self.p.get
        bv = "base_ventilation."
        target = self.p.mode(mode).get("base_vent_m3h") or 0.0
        if not o.occupied or target <= 0.0:
            self.info["base_vent_m3h"] = 0.0
            return
        target = max(target, g(bv + "hard_min_m3h"))
        self.info["base_vent_m3h"] = target
        lo, hi = g(bv + "window_outdoor_temp_range_c")
        if not blocked and not math.isnan(o.outdoor_temp_c) and lo <= o.outdoor_temp_c <= hi:
            add("window", "need", g(bv + "window_crack_pct") / 100.0, L5, f"기본 환기 {target:g} m³/h (창문 소폭)")
        else:
            add("intake", "need", self.intake_rpm_for(target), L5, f"기본 환기 {target:g} m³/h (흡기팬)")
