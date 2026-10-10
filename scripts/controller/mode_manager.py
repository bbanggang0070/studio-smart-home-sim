"""모드 관리자 (docs/07 §2) — 수동 · AUTO 경로 → 유효 모드 · 결정 경로.

- 수동: /studio/cmd/mode 가 AUTO 가 아니면 그 모드 (즉시 반영)
- AUTO: user_modes.yaml 의 rules 를 위에서부터 평가. 자동 전환에만 히스테리시스(auto_hysteresis_min)
- 외출(E8): 재실이 false 이고 away_auto_enabled 이면 AWAY — 재실 판정(문 이벤트 · 판정 창)은 재실 노드의 몫이다
- 귀가(E7): AWAY 중 재실 true → 직전 모드로 복귀
스케줄 경로는 W09 후반 (schedule.enabled 가 기본 false).
"""

from __future__ import annotations

from controller.params import ControllerParams
from controller.signals import Observation

SECONDS_PER_DAY = 86400.0


def _hhmm(s: str) -> float:
    h, m = s.split(":")
    return (int(h) * 60 + int(m)) * 60.0


def _in_window(tod: float, start: str, end: str) -> bool:
    a, b = _hhmm(start), _hhmm(end) % SECONDS_PER_DAY
    return a <= tod < b if a < b else (tod >= a or tod < b)


class ModeManager:
    def __init__(self, p: ControllerParams):
        self.p = p
        sw = p.modes["switching"]
        self.hysteresis_s = float(sw["auto_hysteresis_min"]) * 60.0
        self.away_auto = bool(sw["away_auto_enabled"])
        self.mode = "NORMAL"
        self.path = "auto"
        self._candidate: str | None = None
        self._candidate_since = 0.0
        self._before_away = "NORMAL"
        self._initialized = False

    def _auto_select(self, o: Observation) -> str:
        for rule in self.p.mode("AUTO")["rules"]:
            w = rule["when"]
            if w.get("default"):
                return rule["select"]
            if "event" in w:
                continue                      # DEPARTURE 는 아래 외출 경로에서 처리
            if w.get("occupied") and not o.occupied:
                continue
            if o.zone == "unknown" and ("zone" in w or "zone_not" in w):
                continue                      # 레이더 두절 — 위치로 고르는 규칙은 건너뛴다 (X3 → NORMAL)
            if "zone" in w and o.zone != w["zone"]:
                continue
            if "zone_not" in w and o.zone == w["zone_not"]:
                continue
            if "time" in w and not _in_window(o.tod_s, *w["time"]):
                continue
            return rule["select"]
        return "NORMAL"

    def update(self, o: Observation) -> tuple[str, str]:
        """→ (유효 모드, 결정 경로 manual | auto | away)."""
        if self.away_auto and not o.occupied:
            if self.mode != "AWAY":
                self._before_away = self.mode
            self.mode, self.path = "AWAY", "away"
            return self.mode, self.path
        if self.mode == "AWAY" and self.path == "away":       # 귀가 (E7)
            self.mode, self.path = self._before_away, "arrival"

        if o.user_mode != "AUTO":
            self.mode, self.path = o.user_mode, "manual"
            return self.mode, self.path

        want = self._auto_select(o)
        if not self._initialized:
            self.mode, self.path, self._initialized = want, "auto", True
        elif want != self.mode:
            if want != self._candidate:
                self._candidate, self._candidate_since = want, o.now_s
            elif o.now_s - self._candidate_since >= self.hysteresis_s:
                self.mode, self.path, self._candidate = want, "auto", None
        else:
            self._candidate = None
        return self.mode, self.path
