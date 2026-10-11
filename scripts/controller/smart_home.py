"""통합 제어기 v1 (docs/07 §5.3 실행 파이프라인) — ROS 비의존. 하네스 · ROS 노드가 같은 클래스를 쓴다.

정책 주기마다:
  ① 입력 해석 → ② 모드(mode_manager) → ③ 이벤트(event_detector) → ④ 후보 명령(rule_engine)
  → ⑤ 6계층 병합(arbiter) → ⑥ I7 사후 점검 → ⑦ 명령 · 상태 토픽 발행 + 사유 기록
가전 보호(L0: 압축기 최소 ON/OFF 등)는 appliance_bridge 의 몫이라 여기서 하지 않는다.
"""

from __future__ import annotations

import json
from typing import Any

from controller.appliance_guard import ApplianceGuard
from controller.energy import EnergyPlanner
from controller.arbiter import Decision, merge
from controller.event_detector import ActiveEvent
from controller.feasibility import Feasibility
from controller.event_detector import GRADE_ORDER, EventDetector
from controller.ladders import ac_json
from controller.mode_manager import ModeManager
from controller.params import ControllerParams, load_params
from controller.rule_engine import RuleEngine
from controller.signals import Psychro, parse_inbox
from interfaces import topics as T

# 내부 장치 이름 → (명령 토픽, 형 변환, 가전 프로파일 이름)
DEVICE_TOPIC = {
    "window": (T.C_WINDOW_OPEN_RATIO, float, "window"),
    "blind": (T.C_BLIND_ANGLE, float, "blind"),
    "exhaust": (T.C_FAN_RPM, float, "exhaust_fan"),
    "intake": (T.C_INTAKE_FAN_RPM, float, "intake_fan"),
    "hood": (T.C_RANGE_HOOD_LEVEL, int, "range_hood"),
    "purifier": (T.C_PURIFIER_LEVEL, int, "purifier"),
    "dehumidifier": (T.C_DEHUMIDIFIER, bool, "dehumidifier"),
    "humidifier": (T.C_HUMIDIFIER, bool, "humidifier"),
    "ceiling_fan": (T.C_CEILING_FAN, int, "ceiling_fan"),
    "ac": (T.C_AC, None, "ac"),                         # JSON — 사다리가 정한 모드 · 설정온도로 만든다
    "cooktop": (T.C_COOKTOP_POWER, bool, "cooktop_plug"),  # 요구가 있을 때만 (E15 차단 · 귀가 복구)
    "ceiling_light": (T.C_CEILING_LIGHT, float, "ceiling_light"),
    "desk_light": (T.C_DESK_LIGHT, float, "desk_lamp"),
    "desk_cct": (T.C_DESK_LIGHT_CCT, float, "desk_lamp"),
}
# 아무 요구가 없을 때의 값 — 요구가 사라지면 끈다 (블라인드 · 실링팬은 요구가 있을 때만 움직인다)
DEFAULTS = {"window": 0.0, "exhaust": 0.0, "intake": 0.0, "hood": 0.0, "purifier": 0.0,
            "dehumidifier": 0.0, "humidifier": 0.0, "ac": 0.0}


class SmartHomeController:
    name = "smart_home_v1"

    def __init__(self, params: ControllerParams | None = None):
        self.p = params or load_params()

    def reset(self, params: dict[str, Any]) -> None:
        self.baseline = params.get("baseline", "proposed")
        # Baseline B = 협조는 하되 히스테리시스 · 최소 유지 시간 없음 (docs/03 §6)
        self.hysteresis = self.baseline != "B"
        self.psy = Psychro(self.p)
        self.modes = ModeManager(self.p)
        if not self.hysteresis:
            self.modes.hysteresis_s = 0.0
        self.events = EventDetector(self.p, self.psy)
        # Proposed−P = 우선 목표(L4.5) 비활성 대조군 (docs/03 C15)
        self.rules = RuleEngine(self.p, self.psy, hysteresis=self.hysteresis,
                                primary_goals=self.baseline not in ("P-", "proposed_np"))
        sc = params.get("scenario") or {}
        # 가전 프로파일 · 필터 누적 시간은 설치 설정 · 저장 상태다 — 시나리오가 주면 그것을 쓴다 (X8 · X6)
        if sc.get("appliance_profile"):
            self.rules.devices = set(self.p.get("appliances.profiles")[sc["appliance_profile"]])
        self.rules.filter_hours = float((sc.get("initial") or {}).get("filter_hours", 0.0))
        # 사용자 설정 (user_modes.yaml 의 switching 값을 시나리오가 바꿀 수 있다 — 예: B4 외출 자동 전환 끔)
        us = sc.get("user_settings") or {}
        # 기준선별 사용자 설정 (C16 — B 는 셋백 유지)
        us = {**us, **((sc.get("user_settings_by_baseline") or {}).get(self.baseline) or {})}
        if "away_auto_enabled" in us:
            self.modes.away_auto = bool(us["away_auto_enabled"])
        en = self.p.modes.get("energy") or {}
        strategy = str(us.get("away_strategy", en.get("away_strategy", "auto")))
        strategy = "precool" if strategy == "auto_precool" else strategy
        self.rules.energy = EnergyPlanner(self.p, self.p.get("energy.learned_model_file"),
                                          float(us.get("comfort_weight", en.get("comfort_weight", 1.0))),
                                          strategy if strategy in ("auto", "setback", "off", "precool") else "auto")
        self.devices = self.rules.devices
        self.guard = ApplianceGuard(self.p)
        self.feas = Feasibility(self.p)
        self._last_t: float | None = None
        self._reasons: list[str] = []
        self._safety_prev = "NORMAL"
        self.safety_alerts: list[dict] = []

    def reasons(self) -> list[str]:
        return self._reasons

    def step(self, now_s: float, inbox: dict[str, Any]) -> dict[str, Any]:
        o = parse_inbox(now_s, inbox)
        if self._last_t is not None and o.intake_rpm > 0:
            self.rules.filter_hours += (now_s - self._last_t) / 3600.0
        self._last_t = now_s
        self._safety_alert(o)
        if o.user_mode == "MANUAL":                    # 제어 상태 MANUAL — 사용자가 직접 조작, 제어기는 액추에이터 명령을 내지 않는다
            return self._manual_step(o)                # (창문 안전은 상위 · 로컬 계층이 그대로 지킨다 — W10 T10.21 · X4)
        mode, path = self.modes.update(o)
        self.rules.home_mode = self.modes._before_away if mode == "AWAY" else mode
        ev = self.events.update(o)
        cands = self.rules.candidates(o, mode, ev)
        decided = merge(cands, {k: v for k, v in DEFAULTS.items() if DEVICE_TOPIC[k][2] in self.devices})
        self._i7_check(o, decided)
        self._i1_check(decided)
        ac_action = self._ac_guard(o, decided, ev)

        out: dict[str, Any] = {}
        self._reasons = []
        for dev, d in decided.items():
            topic, cast, profile_name = DEVICE_TOPIC[dev]
            if profile_name not in self.devices:
                continue
            if dev == "ac":
                if ac_action != "send":
                    continue                           # E12 보류 · E9 무응답 — 명령을 내지 않는다
                out[topic] = self._ac_command(d.value > 0)
            else:
                out[topic] = cast(round(d.value) if cast is int else d.value)
            self._reasons.append(f"{dev}={out[topic]} ← {' / '.join(d.reasons)}")

        info = self.rules.info
        out[T.T_ACTIVE_EVENTS] = json.dumps(sorted(ev))
        out[T.T_LIVING_MODE] = json.dumps({"mode": mode, "path": path, "noise_grade": info["noise_grade"],
                                           "state": "AUTO_SAVING" if info.get("saving") else "AUTO_COMFORT"})
        out[T.T_DEW_MARGIN] = self.psy.dew_margin(o)
        out[T.T_VENTILATION] = json.dumps({"base_vent_m3h": info.get("base_vent_m3h", 0.0),
                                           "window_blocked": info["window_blocked"],
                                           "i10_dew_diff_c": info.get("i10_dew_diff_c")})
        if "energy_forecast" in info:
            out[T.T_ENERGY_FORECAST] = json.dumps(info["energy_forecast"])
        out[T.T_CONTROL_FEASIBILITY] = self.feas.update(o, self.p.mode(mode), decided, set(decided),
                                                        self._caps(cands, decided), ev, info.get("useful_means"),
                                                        info.get("cooling_target_c"),
                                                        (info.get("ac_override") or info.get("ac") or {}).get("mode"))
        if self.feas.reason:
            self._reasons.append(f"control_feasibility={self.feas.state} ← {self.feas.reason}")
        alerts = sorted(self.rules.alerts + self.events.alerts + self.guard.alerts + self.safety_alerts, key=lambda a: a["t"])
        if alerts:                                     # 사용자 알림 (v3.4.5 전용 토픽)
            out[T.T_ALERTS] = json.dumps(alerts, ensure_ascii=False)
        return out

    def _ac_command(self, on: bool) -> str:
        """에어컨 JSON — 이벤트 지정(ac_override) > 사다리(ac). E11 설정 +1 °C · 풍량 약을 마지막에 덧씌운다."""
        info = dict(self.rules.info)
        if "ac_override" in info:
            info["ac"] = info["ac_override"]
        if on and "ac" in info:
            a = dict(info["ac"])
            a["setpoint"] = a["setpoint"] + info.get("ac_setpoint_offset", 0.0)
            if "ac_fan_force" in info:
                a["fan"] = info["ac_fan_force"]
            info["ac"] = a
        return ac_json(info, on, self.guard.seq)       # seq — 재송신하면 값이 바뀌어 브릿지가 다시 쏜다 (E9)

    def _manual_step(self, o) -> dict[str, Any]:
        ev = self.events.update(o)
        self._reasons = ["MANUAL — 사용자 직접 조작 (액추에이터 명령 없음)"]
        return {T.T_LIVING_MODE: json.dumps({"mode": "MANUAL", "path": "manual", "noise_grade": "-", "state": "MANUAL"}),
                T.T_ACTIVE_EVENTS: json.dumps(sorted(ev)), T.T_CONTROL_FEASIBILITY: "FEASIBLE",
                T.T_DEW_MARGIN: self.psy.dew_margin(o),
                **({T.T_ALERTS: json.dumps(self.safety_alerts, ensure_ascii=False)} if self.safety_alerts else {})}

    def _safety_alert(self, o) -> None:
        """창문 안전 상태가 바뀌면 거부 사유를 사용자 알림으로 (X4 — 수동 명령도 끼임이면 거부 · W10 T10.21)."""
        cur, prev = o.safety_state, self._safety_prev
        self._safety_prev = cur
        if cur == prev:
            return
        if cur.startswith("LOCKED") and not prev.startswith("LOCKED"):
            d = "닫힘" if "CLOSING" in cur else "열림"
            self.safety_alerts.append({"code": "W_LOCK", "level": "critical", "t": o.now_s,
                                       "msg": f"같은 자리 반복 끼임 — 창문 {d} 방향 잠금 · 명령 거부 (WINDOW_UNLOCK 으로 해제)"})
        elif ("PINCH_REVERSE" in cur or cur == "LOCAL_CUTOFF") and "PINCH_REVERSE" not in prev and prev != "LOCAL_CUTOFF":
            self.safety_alerts.append({"code": "W_PINCH", "level": "warning", "t": o.now_s,
                                       "msg": "창문 끼임 감지 — 정지 · 반전 · 안전 대기 중 창문 명령 거부"})

    def _caps(self, cands, decided: dict[str, Decision]) -> dict[str, float]:
        """장치별 지금 낼 수 있는 최댓값 — cap · force 후보의 최솟값, 없으면 장치 최댓값 (I7 후처리로 줄었으면 그 값)."""
        g = self.p.get
        top = {"window": 1.0, "exhaust": g("appliances.exhaust_fan.max_rpm"), "intake": g("appliances.intake_fan.max_rpm"),
               "ceiling_fan": 2.0, "blind": g("setpoints.blind_shade_angle_deg"), "ac": 1.0, "dehumidifier": 1.0,
               "humidifier": 1.0, "purifier": 3.0, "range_hood": 2.0}
        caps = {}
        for dev in decided:
            lim = [c.value for c in cands if c.device == dev and c.kind in ("cap", "force")]
            caps[dev] = min(lim + [top.get(dev, float("inf"))])
        ex = decided.get("exhaust")
        if ex is not None and any(r.startswith("I7") for r in ex.reasons):
            caps["exhaust"] = min(caps.get("exhaust", ex.value), ex.value)
        return caps

    def _ac_guard(self, o, decided: dict[str, Decision], ev: dict) -> str:
        """E9 · E12 — 전력 감시로 에어컨 명령 결과를 확인한다 (appliance_guard)."""
        if "ac" not in self.devices or "ac" not in decided:
            return "send" if "ac" in decided else "failed"
        on = decided["ac"].value > 0
        key = self._ac_command(on).rsplit('"seq"', 1)[0]   # seq 를 뺀 명령 내용
        action = self.guard.ac_step(o.now_s, on, o.appliance_states, key)
        if action == "failed" and "APPLIANCE_FAULT" not in ev:
            ev["APPLIANCE_FAULT"] = ActiveEvent("APPLIANCE_FAULT", o.now_s, {"device": "ac"})
            self.rules.devices = self.devices = self.devices - {"ac"}     # 사다리에서 제외 → 다음 주기부터 다른 수단
        if action == "hold":
            ev.setdefault("MANUAL_OVERRIDE", ActiveEvent("MANUAL_OVERRIDE", o.now_s, {"device": "ac"}))
        else:
            ev.pop("MANUAL_OVERRIDE", None)
        return action

    def _i1_check(self, decided: dict[str, Decision]) -> None:
        """I1 — 제습기 ⟂ 가습기. 둘 다 켜지면 가습을 끈다 (결로 · 습기 쪽이 재산 보호에 가깝다)."""
        dh, hu = decided.get("dehumidifier"), decided.get("humidifier")
        if dh and hu and dh.value > 0 and hu.value > 0:
            hu.value = 0.0
            hu.reasons.append("I1 제습기 ⟂ 가습기")

    def _i7_check(self, o, decided: dict[str, Decision]) -> None:
        """I7 — 외기 나쁨 이상에서 급기 없는 배기 금지: 흡기가 배기량을 못 맞추면 배기를 줄인다."""
        if GRADE_ORDER.index(o.outdoor_pm_grade) < GRADE_ORDER.index("bad"):
            return
        ex = decided.get("exhaust")
        if not ex or ex.value <= 0:
            return
        intake_m3h = self.rules.intake_max_m3h * decided.get("intake", Decision(0.0, [])).value / self.rules.intake_max_rpm
        allowed_rpm = min(ex.value, intake_m3h / self.rules.exhaust_max_m3h * self.rules.exhaust_max_rpm)
        if allowed_rpm < ex.value:
            ex.value = allowed_rpm
            ex.reasons.append("I7 외기 나쁨 — 흡기량만큼만 배기")
