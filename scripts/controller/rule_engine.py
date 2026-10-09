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
from controller.event_detector import GRADE_ORDER, ActiveEvent
from controller.ladders import ComfortLadders
from controller.params import ControllerParams
from controller.predictor import HoodPredictor, Plan
from controller.signals import Observation, Psychro

L0, L1, L2, L3, L4, L5, L6 = 0, 1, 2, 3, 4, 5, 6


class RuleEngine:
    def __init__(self, p: ControllerParams, psy: Psychro, hysteresis: bool = True):
        self.p, self.psy = p, psy
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
        self.info: dict = {}
        self.ladders = ComfortLadders(p, psy, self, hysteresis)

    # ---- 도우미 ----

    def intake_rpm_for(self, m3h: float) -> float:
        return min(self.intake_max_rpm, m3h / self.intake_max_m3h * self.intake_max_rpm)

    def exhaust_m3h(self, rpm: float) -> float:
        return self.exhaust_max_m3h * min(rpm / self.exhaust_max_rpm, 1.0)

    def window_blocked(self, o: Observation, ev: dict[str, ActiveEvent], mode: str) -> list[str]:
        """I3 · 기본 환기 — 창문을 급기 수단으로 쓸 수 없는 이유들."""
        why = []
        if "RAIN" in ev:
            why.append("rain")
        if GRADE_ORDER.index(o.outdoor_pm_grade) >= GRADE_ORDER.index("bad"):
            why.append("outdoor_pm_bad")
        if o.ac_cooling:
            why.append("ac_cooling")
        if mode == "AWAY":
            why.append("away")
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
        self.pm_hist.append((o.now_s, o.pm25))
        out: list[Candidate] = []
        add = lambda dev, kind, val, layer, why: out.append(Candidate(dev, kind, float(val), layer, why))
        blocked = self.window_blocked(o, ev, mode)
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

        # -- L2 건강 · 재산 --
        self._cooking(o, ev, blocked, noise, add)
        self._shower(o, ev, blocked, noise, add)
        cond = ev.get("CONDENSATION")
        if cond and cond.info.get("level") == "critical":
            add("blind", "force", g("condensation.blind_slat_on_critical_deg"), L2, "E2 결로 위험 블라인드 개방")
            add("humidifier", "force", 0, L2, "E2 결로 위험 가습 금지")
            add("ceiling_fan", "need", -1, L2, "E2 결로 위험 실링팬 역회전")
            add("dehumidifier", "need", 1, L2, "E2 결로 위험 제습")

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
        self.info.update(self.ladders.apply(o, mode, blocked, noise, add))
        if mode in ("AWAY",) and "ac" in self.devices:
            add("ac", "cap", 0, L3, "외출 — 냉방 정지")
        pm = "indoor_pm."
        if o.pm25 > g(pm + "bad_ugm3"):
            add("purifier", "need", g(pm + "purifier_level_above_bad"), L5, "실내 PM 나쁨")
        elif o.pm25 > g(pm + "target_ugm3"):
            add("purifier", "need", g(pm + "purifier_level_above_target"), L5, "실내 PM 목표 초과")
        if cond and cond.info.get("level") == "warn":
            add("ceiling_fan", "need", -1, L5, "E2 결로 경고 실링팬 역회전")
            add("humidifier", "cap", 0, L5, "E2 결로 경고 가습 중단")
        return out

    def _supply_for(self, exhaust_m3h: float, o: Observation, blocked: list[str], window_ratio: float,
                    add, why: str) -> None:
        """I3 · I7 — 기계 배기에 맞춰 급기. 창문을 쓸 수 있으면 창문, 아니면 흡기팬(필터)."""
        g = self.p.get
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
            lv = self._choose_hood(o, cook, blocked, noise, outdoor_polluted="OUTDOOR_PM" in ev)
            add("hood", "need", lv, L2, f"E1 요리 후드 예측 선택 {cook.info.get('peaks', {})}")
            add("purifier", "need", g(c + ("purifier_level_outdoor_bad" if bad_out else "purifier_level")), L2,
                "E1 요리 청정기")
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
        if "hood_level" in cook.info:
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
        for lv in range(0, int(noise["range_hood_max_level"]) + 1):
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
        plan, peaks = self.pred.choose(plans, o.pm25, pm_out, source)
        cook.info.update(hood_level=plan.hood_level, peaks={k: round(v) for k, v in peaks.items()},
                         source_ug_h=round(source))
        self._hood_next_eval = o.now_s + g(hp + "reevaluate_s")
        return plan.hood_level

    def _shower(self, o, ev, blocked, noise, add) -> None:
        g = self.p.get
        if "SHOWER" not in ev:
            self._i10_open = False
            return
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
