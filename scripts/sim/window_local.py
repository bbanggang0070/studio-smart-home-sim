"""창문 로컬 안전 계층 (W06 T6.7 · docs/04 §3.7) + 모터 전류 환산 · Zone 판정.

브릿지의 물리 콜백 안에서 매 물리 스텝 부른다 — ROS 2 왕복 없음. 로컬은 '정지만' 한다 (판정 · 반전은 상위 W10).
  전류   I = I0 + |F|·r / (G·Kt·η)        (thresholds window_sensorless · docs/04 §6)  — 리플 · 잡음은 W07 전류 노드
  컷오프  운동 방향으로 미는 힘 F⁺ = F·방향 (제동 · 감속 힘은 반대 부호 — 회생 전류라 끼임이 아니다)
          I(F⁺) > local_cutoff_current_a  또는  F⁺ > local_cutoff_force_n  → 정지
          예외: 기동 후 start_blanking_ms 동안 전류 기준 무시 (Zone A 기동 피크)
                폐쇄 Zone D(씰 압착 — 정상적으로 최대 힘까지 민다): 전류 기준 끔 · 반력 백업은 덜 닫혔을 때(q > seal_closed_tolerance_m)만
  정지 뒤  막힌 방향의 지령은 받지 않는다 — 반대 방향(빠져나오는) 지령이 오면 해제 (상위 응답이 없으면 정지 유지)
"""

from __future__ import annotations

from dataclasses import dataclass


def motor_current(force_n: float, p: dict) -> float:
    """p = thresholds window_sensorless."""
    amp_per_n = p["pinion_radius_m"] / (p["gear_ratio"] * p["torque_constant_nm_per_a"] * p["mechanical_efficiency"])
    return p["no_load_current_a"] + abs(force_n) * amp_per_n


def window_zone(q: float, travel: float, direction: int, start_q: float | None, p: dict) -> str:
    """direction: −1 닫힘 · +1 열림 · 0 정지. 진행률은 폐쇄 기준(닫힘 쪽 끝 = 100 %)."""
    tp = p["torque_profile"]
    closed_pct = (1.0 - q / travel) * 100.0
    if direction <= 0 and closed_pct >= tp["seal_zone_pct"][0]:      # 씰 구간은 위치로 정해진다 — 기동 구간보다 우선
        return "D_SEAL"
    if direction != 0 and start_q is not None and abs(q - start_q) / travel * 100.0 < tp["start_zone_pct"][1]:
        return "A_START"
    if closed_pct >= tp["endzone_pct"][0]:
        return "C_ENDZONE"
    return "B_RUN"


@dataclass
class LocalCutoff:
    p: dict                       # thresholds window_sensorless
    travel: float
    tripped: bool = False
    blocked_dir: int = 0          # 막힌 방향 (−1 닫힘 · +1 열림)
    reason: str = ""
    _move_start_t: float | None = None
    _start_q: float | None = None
    _dir: int = 0

    def on_command(self, direction: int) -> bool:
        """새 지령 방향 — 막힌 방향이면 거부(False). 반대 방향이면 해제."""
        if self.tripped:
            if direction == self.blocked_dir:
                return False
            if direction != 0:
                self.tripped, self.reason = False, ""
        return True

    def step(self, t: float, q: float, v: float, force: float, direction: int) -> bool:
        """→ 이번 스텝에 새로 끊었으면 True."""
        ls = self.p["layered_safety"]
        if direction != self._dir:
            self._dir = direction
            self._move_start_t, self._start_q = (t, q) if direction != 0 else (None, None)
        if not ls["local_cutoff_enabled"] or self.tripped or direction == 0:
            return False
        zone = window_zone(q, self.travel, direction, self._start_q, self.p)
        push = max(0.0, force * direction)                 # 운동 방향으로 미는 힘만
        cur = motor_current(push, self.p)
        since = 0.0 if self._move_start_t is None else t - self._move_start_t
        blank = since * 1000.0 < self.p["torque_profile"]["start_blanking_ms"]
        over_i = cur > ls["local_cutoff_current_a"] and zone != "D_SEAL" and not blank
        over_f = push > ls["local_cutoff_force_n"] and (zone != "D_SEAL" or q > ls["seal_closed_tolerance_m"])
        if over_i or over_f:
            self.tripped, self.blocked_dir = True, direction
            self.reason = f"{'전류' if over_i else '반력'} {cur:.2f} A / {push:.1f} N @ {zone}"
            return True
        return False
