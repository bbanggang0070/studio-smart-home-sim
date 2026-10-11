"""모드 관리자 (docs/07 §2) — 수동 · AUTO 경로 → 유효 모드 · 결정 경로.

- 수동: /studio/cmd/mode 가 AUTO 가 아니면 그 모드 (즉시 반영)
- AUTO: user_modes.yaml 의 rules 를 위에서부터 평가. 자동 전환에만 히스테리시스(auto_hysteresis_min)
- 외출(E8): 재실이 false 이고 away_auto_enabled 이면 AWAY — 재실 판정(문 이벤트 · 판정 창)은 재실 노드의 몫이다
- 귀가(E7): AWAY 중 재실 true → 직전 모드로 복귀
- 스케줄(schedule.enabled): 우선순위 수동 > 스케줄 > AUTO. 수동 선택은 다음 스케줄 경계까지 유지된다
  (switching.manual_hold_until). 요일(days)은 시뮬레이션 시각에 없어 v1 은 무시한다
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
        sch = p.modes.get("schedule") or {}
        self.schedule = sorted(((_hhmm(e["at"]), e["mode"]) for e in sch.get("entries") or []), key=lambda x: x[0]) \
            if sch.get("enabled") else []
        self._manual = None                     # (모드, 설정 시각)

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

    def _scheduled(self, tod: float) -> str:
        """지금 시각 직전의 스케줄 항목 모드 (자정을 넘으면 전날 마지막 항목)."""
        past = [m for t, m in self.schedule if t <= tod]
        return past[-1] if past else self.schedule[-1][1]

    def _boundary_since(self, t0: float, t1: float) -> bool:
        """t0 (초과) ~ t1 (이하) 사이에 스케줄 경계가 있었나 (하루 안 · 자정 넘김 처리)."""
        if t1 - t0 >= SECONDS_PER_DAY:
            return True
        a, b = t0 % SECONDS_PER_DAY, t1 % SECONDS_PER_DAY
        for t, _ in self.schedule:
            if (a < t <= b) if a <= b else (t > a or t <= b):
                return True
        return False

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
            if self._manual is None or self._manual[0] != o.user_mode:
                self._manual = (o.user_mode, o.now_s)
            if not (self.schedule and self._boundary_since(self._manual[1], o.now_s)):
                self.mode, self.path = o.user_mode, "manual"
                return self.mode, self.path
        else:
            self._manual = None
        if self.schedule:                                     # 수동이 없거나 다음 경계가 지났다 → 스케줄
            self.mode, self.path = self._scheduled(o.tod_s), "schedule"
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
