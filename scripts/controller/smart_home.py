"""통합 제어기 v1 (docs/07 §5.3 실행 파이프라인) — ROS 비의존. 하네스 · ROS 노드가 같은 클래스를 쓴다.

정책 주기마다:
  ① 입력 해석 → ② 모드(mode_manager) → ③ 이벤트(event_detector) → ④ 후보 명령(rule_engine)
  → ⑤ 6계층 병합(arbiter) → ⑥ I7 사후 점검 → ⑦ 명령 · 상태 토픽 발행 + 사유 기록
가전 보호(L0: 압축기 최소 ON/OFF 등)는 appliance_bridge 의 몫이라 여기서 하지 않는다.
"""

from __future__ import annotations

import json
from typing import Any

from controller.arbiter import Decision, merge
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
        self.rules = RuleEngine(self.p, self.psy, hysteresis=self.hysteresis)
        self.devices = self.rules.devices
        self._reasons: list[str] = []

    def reasons(self) -> list[str]:
        return self._reasons

    def step(self, now_s: float, inbox: dict[str, Any]) -> dict[str, Any]:
        o = parse_inbox(now_s, inbox)
        mode, path = self.modes.update(o)
        ev = self.events.update(o)
        cands = self.rules.candidates(o, mode, ev)
        decided = merge(cands, {k: v for k, v in DEFAULTS.items() if DEVICE_TOPIC[k][2] in self.devices})
        self._i7_check(o, decided)
        self._i1_check(decided)

        out: dict[str, Any] = {}
        self._reasons = []
        for dev, d in decided.items():
            topic, cast, profile_name = DEVICE_TOPIC[dev]
            if profile_name not in self.devices:
                continue
            if dev == "ac":
                out[topic] = ac_json(self.rules.info, d.value > 0)
            else:
                out[topic] = cast(round(d.value) if cast is int else d.value)
            self._reasons.append(f"{dev}={out[topic]} ← {' / '.join(d.reasons)}")

        info = self.rules.info
        out[T.T_ACTIVE_EVENTS] = json.dumps(sorted(ev))
        out[T.T_LIVING_MODE] = json.dumps({"mode": mode, "path": path, "noise_grade": info["noise_grade"]})
        out[T.T_DEW_MARGIN] = self.psy.dew_margin(o)
        out[T.T_VENTILATION] = json.dumps({"base_vent_m3h": info.get("base_vent_m3h", 0.0),
                                           "window_blocked": info["window_blocked"],
                                           "i10_dew_diff_c": info.get("i10_dew_diff_c")})
        out[T.T_CONTROL_FEASIBILITY] = "FEASIBLE"     # 판정 로직은 W09 T9.7
        return out

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
