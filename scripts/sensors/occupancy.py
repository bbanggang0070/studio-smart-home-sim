"""재실 판정 노드 코어 — 문 이벤트 + 판정 창 (호텔 객실 로직, docs/08 §1.0) · 24시간 융합 폴백 (§1.2).

ROS 비의존 순수 Python. 물리 모드에서는 occupancy_sensor_node 가, 고속 모드에서는 하네스가 감싼다.

입력 (매 주기):
    door_open        현관문 열림 (리드 스위치 — 고장이면 값이 멈춘다)
    moving[0..8]     LD2410 구간별 움직임 에너지 (0–100)
    static[0..8]     LD2410 구간별 정지(호흡) 에너지
    wifi             휴대폰 접속 (재실 증거가 아니다 — 판정 창 중 '끊김'만 외출 증거)
    power_w          기기별 전력 {device: W} — 사람이 켜는 기기의 상승 엣지 = 강한 증거
출력:
    occupied · zone(desk/bed/kitchen/room/none) · basis(LATCHED_OCCUPIED/LATCHED_VACANT/JUDGING/DOOR_OPEN/FALLBACK) · alerts

상태
    DOOR_OPEN ──닫힘──► JUDGING ──강한 증거──► LATCHED_OCCUPIED (다음 문 열림까지 · 시간 기준 없음)
                          └─ 증거 없음(3분) · 약한 증거만이면 최대 10분 연장 · Wi-Fi 끊김 ─► LATCHED_VACANT
    DOOR_OPEN 10분 초과 · 빈방 고정 중 모순(강한 움직임 + 기기 조작) ─► FALLBACK (융합: Wi-Fi ∨ 전력 ∨ (mmWave ∧ 최근 증거))
    FALLBACK 은 정상 문 이벤트(열림 → 닫힘)가 다시 들어오면 JUDGING 으로 돌아간다
mmWave 자동 보정(걷기 · 빈방 기준선 학습, X9 ⑨)은 아직 없다 — 기본 임계값을 쓴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

LATCHED_OCCUPIED, LATCHED_VACANT = "LATCHED_OCCUPIED", "LATCHED_VACANT"
JUDGING, DOOR_OPEN, FALLBACK = "JUDGING", "DOOR_OPEN", "FALLBACK"


@dataclass
class OccupancyOutput:
    occupied: bool
    zone: str
    basis: str
    alerts: list[str] = field(default_factory=list)
    fault: bool = False


class OccupancyJudge:
    def __init__(self, occ_params: dict[str, Any], initial_occupied: bool, now_s: float = 0.0):
        """occ_params = thresholds.yaml 의 occupancy 블록."""
        self.c = occ_params
        dg = occ_params["door_gating"]
        self.judge_s = dg["judge_window_s"]
        self.extend_s = dg["evidence_strength"]["weak_only_extend_max_s"]
        self.inner_static_hold_s = dg["evidence_strength"]["inner_static_hold_s"]
        self.wifi_out_is_evidence = dg["evidence_strength"]["wifi_disconnect_is_vacancy_evidence"]
        self.open_fallback_s = dg["door_left_open_fallback_min"] * 60.0
        self.person_devices = set(occ_params["power_evidence_devices"])
        self.e_move = occ_params["evidence_energy"]["moving"]
        self.e_static = occ_params["evidence_energy"]["static"]
        self.edge_w = occ_params["person_power_edge_w"]
        self.contradiction_s = occ_params["contradiction_window_s"]
        self.fusion_confirm_s = occ_params["departure_confirm_min"] * 60.0
        self.wifi_valid_s = occ_params["wifi_presence"]["evidence_valid_min"] * 60.0
        gate = occ_params["gate_size_m"]
        # 방 끝(벽에 붙은) 구간 번호 — 깊이 5.25 m 를 0.75 m 구간으로 나누면 0–6번 7개 → 6번 (docs/08 §1.0)
        self.last_gate = math.ceil(occ_params["mmwave_calibration"]["room_depth_m"] / gate - 1e-9) - 1
        self.zones = {k: list(v) for k, v in occ_params["zone_gates"].items()}

        self.state = LATCHED_OCCUPIED if initial_occupied else LATCHED_VACANT
        self.occupied = initial_occupied
        self.fault = False
        self._t_state = now_s
        self._door_prev: bool | None = None
        self._inner_static_since: float | None = None
        self._prev_power: dict[str, float] = {}
        self._last_power_edge: float | None = None
        self._last_strong_move: float | None = None
        self._last_wifi_or_power: float | None = now_s if initial_occupied else None
        self._fusion_quiet_since: float | None = None
        self._wifi_prev: bool | None = None
        self._wifi_dropped_in_window = False

    # ---- 증거 ----

    def _evidence(self, now: float, moving: list[float], static: list[float], power_w: dict[str, float]):
        inner = range(0, self.last_gate)                 # 벽에 붙은 마지막 구간 제외
        strong_move = any(moving[i] >= self.e_move for i in inner)
        inner_static = any(static[i] >= self.e_static for i in inner)
        self._inner_static_since = (self._inner_static_since or now) if inner_static else None
        strong_static = self._inner_static_since is not None and now - self._inner_static_since >= self.inner_static_hold_s
        wall = self.last_gate
        weak = moving[wall] >= self.e_move or static[wall] >= self.e_static
        edge = False
        for dev in self.person_devices:
            p = float(power_w.get(dev, 0.0))
            if p - self._prev_power.get(dev, 0.0) >= self.edge_w:
                edge = True
            self._prev_power[dev] = p
        if edge:
            self._last_power_edge = now
        if strong_move:
            self._last_strong_move = now
        return strong_move or strong_static or edge, weak, strong_move, edge

    def _zone(self, moving: list[float], static: list[float]) -> str:
        if not self.occupied:
            return "none"
        best, best_e = "none", 0.0
        for name, gates in self.zones.items():
            e = max(max(moving[g], static[g]) for g in gates)
            if e > best_e and e >= min(self.e_move, self.e_static):
                best, best_e = name, e
        return best if best != "none" else "room"

    def _set(self, state: str, now: float) -> None:
        self.state, self._t_state = state, now

    # ---- 갱신 ----

    def update(self, now: float, door_open: bool, moving: list[float], static: list[float], wifi: bool,
               power_w: dict[str, float]) -> OccupancyOutput:
        alerts: list[str] = []
        strong, weak, strong_move, edge = self._evidence(now, moving, static, power_w)
        if wifi or edge:
            self._last_wifi_or_power = now
        wifi_dropped = self._wifi_prev is True and not wifi
        self._wifi_prev = wifi
        opened = self._door_prev is False and door_open
        closed = self._door_prev is True and not door_open
        self._door_prev = door_open

        if self.state == FALLBACK:
            if closed:                                    # 정상 문 이벤트가 돌아왔다 → 문 기반 판정 복귀
                self.fault = False
                self._set(JUDGING, now)
                self._wifi_dropped_in_window = False
            else:
                self._fusion(now, strong_move, edge, wifi)
        elif opened:
            self._set(DOOR_OPEN, now)
            self.occupied = True                          # 문 열림 즉시 귀가 처리 (E7)
        elif self.state == DOOR_OPEN:
            if closed:
                self._set(JUDGING, now)
                self._wifi_dropped_in_window = False
            elif now - self._t_state >= self.open_fallback_s:
                self._set(FALLBACK, now)
                self._fusion_quiet_since = None
                alerts.append("문이 10분 넘게 열려 있음 — 24시간 융합 판정으로 전환")
        elif self.state == JUDGING:
            self._wifi_dropped_in_window |= wifi_dropped and self.wifi_out_is_evidence
            elapsed = now - self._t_state
            if strong:
                self._set(LATCHED_OCCUPIED, now)
                self.occupied = True
            elif self._wifi_dropped_in_window and elapsed >= self.judge_s:   # 연장 단계에서 Wi-Fi 끊김 = 외출 증거
                self._set(LATCHED_VACANT, now)
                self.occupied = False
            elif elapsed >= self.judge_s and not weak:
                self._set(LATCHED_VACANT, now)
                self.occupied = False
            elif elapsed >= self.extend_s:                # 약한 증거만 — 최대 10분까지 기다렸다
                self._set(LATCHED_VACANT, now)
                self.occupied = False
            else:
                self.occupied = True                      # 판정 중에는 재실로 둔다
        elif self.state == LATCHED_VACANT:
            # E14 — 빈방 고정인데 강한 움직임 + 기기 조작이 함께 (문을 거치지 않고는 들어올 수 없다)
            if (self._last_strong_move is not None and self._last_power_edge is not None
                    and abs(self._last_strong_move - self._last_power_edge) <= self.contradiction_s
                    and now - max(self._last_strong_move, self._last_power_edge) <= 1.0
                    and min(self._last_strong_move, self._last_power_edge) > self._t_state):
                self._set(FALLBACK, now)
                self.fault = True
                self._fusion_quiet_since = None
                self._fusion(now, strong_move, edge, wifi)
                alerts.append("문 센서 이상 의심 — 빈방 고정 중 실내 사람 신호 + 기기 조작 · 24시간 융합으로 전환")
        # LATCHED_OCCUPIED 는 다음 문 열림까지 유지 — 시간 기준 없음

        return OccupancyOutput(self.occupied, self._zone(moving, static), self.state, alerts, self.fault)

    def _fusion(self, now: float, strong_move: bool, edge: bool, wifi: bool) -> None:
        """폴백 — 하나라도 확실하면 재실, 셋 다 없을 때만 부재 (15분)."""
        recent = self._last_wifi_or_power is not None and now - self._last_wifi_or_power <= self.wifi_valid_s
        evidence = wifi or edge or (strong_move and recent)
        if evidence:
            self.occupied, self._fusion_quiet_since = True, None
        else:
            self._fusion_quiet_since = self._fusion_quiet_since or now
            if now - self._fusion_quiet_since >= self.fusion_confirm_s:
                self.occupied = False
