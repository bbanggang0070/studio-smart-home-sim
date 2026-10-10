"""전력 감시 노드 코어 — 기기 전력 → 다단계 상태 · 엣지 · 원인(command/manual) (docs/08 §3 · W07 T7.w3).

ROS 비의존 순수 Python. 출력은 /studio/state/appliance_states (JSON {device: {state, edge, source}}).

  상태    thresholds power_monitor.states_w 의 구간으로 판정 (예: 에어컨 off < 10 W · 송풍 20–100 W · 가동 > 250 W)
          10 s 이동평균 · 새 상태가 enter_hold_s(꺼짐은 off_hold_s) 이어져야 확정 — 측정 잡음 · 기동 돌입에 흔들리지 않게
  원인    상태가 바뀌기 직전 power_confirm_s 안에 그 기기로 명령이 나갔으면 command, 아니면 manual (규칙 I9 · E12)
          송풍 ↔ 가동(써모오프 · 재기동)은 기기가 스스로 바꾸는 것이라 원인을 따지지 않는다 (B11 — OFF 오판 없음)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

SELF_TRANSITIONS = {frozenset({"fan_only", "run"}), frozenset({"standby", "run"})}


@dataclass
class DeviceState:
    state: str = "off"
    edge: str = ""                # 직전 확정 변화 "off→run" 등
    source: str = ""              # command | manual | self
    since_s: float = 0.0


class PowerMonitor:
    def __init__(self, pm_params: dict[str, Any], confirm_s: float):
        """pm_params = thresholds power_monitor 블록 · confirm_s = events.appliance_no_response.power_confirm_s."""
        self.bands = pm_params["states_w"]
        self.devices = list(pm_params["devices"])
        self.avg_s = pm_params["moving_avg_s"]
        self.enter_hold = pm_params["enter_hold_s"]
        self.off_hold = pm_params["off_hold_s"]
        self.confirm_s = confirm_s
        self.hist: dict[str, deque] = {d: deque() for d in self.devices}
        self.cur = {d: DeviceState() for d in self.devices}
        self._cand: dict[str, tuple[str, float]] = {}
        self.last_cmd_t: dict[str, float] = {}
        self._initialized = False

    def _classify(self, dev: str, w: float) -> str:
        b = self.bands[dev]
        if w < b.get("off_lt", 0.0):
            return "off"
        if "run_gt" in b and w > b["run_gt"]:
            return "run"
        if "heat_gt" in b and w > b["heat_gt"]:
            return "run"
        if "spin_gt" in b and w > b["spin_gt"]:
            return "run"
        if "fan_only" in b and b["fan_only"][0] <= w <= b["fan_only"][1]:
            return "fan_only"
        if "standby" in b and b["standby"][0] <= w <= b["standby"][1]:
            return "standby"
        return "standby"

    def note_command(self, dev: str, t: float) -> None:
        """그 기기로 명령(IR · 릴레이)이 나간 시각 — 하네스 · 브릿지가 알려 준다."""
        self.last_cmd_t[dev] = t

    def update(self, t: float, power_w: dict[str, float]) -> dict[str, dict[str, str]]:
        if not self._initialized:                     # 첫 측정은 초기 상태로 받아들인다 (켜진 채 시작한 기기를 수동 조작으로 보지 않게)
            for dev in self.devices:
                self.cur[dev] = DeviceState(self._classify(dev, float(power_w.get(dev, 0.0))), "", "", t)
            self._initialized = True
        for dev in self.devices:
            h = self.hist[dev]
            h.append((t, float(power_w.get(dev, 0.0))))
            while h and t - h[0][0] > self.avg_s:
                h.popleft()
            avg = sum(v for _, v in h) / len(h)
            new = self._classify(dev, avg)
            cs = self.cur[dev]
            if new == cs.state:
                self._cand.pop(dev, None)
                continue
            cand = self._cand.get(dev)
            if cand is None or cand[0] != new:
                self._cand[dev] = (new, t)
                continue
            hold = self.off_hold if new == "off" else self.enter_hold
            if t - cand[1] < hold:
                continue
            pair = frozenset({cs.state, new})
            if pair in SELF_TRANSITIONS:
                source = "self"
            else:
                lc = self.last_cmd_t.get(dev)
                # 이동평균 창만큼 상태 판정이 늦으므로 원인 창 = 확인 시간 + 평균 창
                source = "command" if lc is not None and cand[1] - lc <= self.confirm_s + self.avg_s else "manual"
            self.cur[dev] = DeviceState(new, f"{cs.state}→{new}", source, t)
            self._cand.pop(dev, None)
        return {d: {"state": s.state, "edge": s.edge, "source": s.source} for d, s in self.cur.items()}
