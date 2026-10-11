"""센서리스 창문 상위 안전 계층 (W10 T10.3–T10.8 · docs/04 §3.3–3.7) — 순수 Python, 50 Hz 로 부른다.

입력: 모터 전류 Ī (50 Hz) · 리플 위치 추정 x̂ (20 Hz) · 지령 방향 · 지령 속도
  Zone        x̂ · 방향 · 기동 후 진행 거리 → A_START / B_RUN / C_ENDZONE / D_SEAL (sim/window_local.window_zone)
  토크 프로파일 A 100 % → B 100→55 % 선형 → C 70 % → D 100 %  (브릿지가 드라이브 maxForce 로 적용 — T10.4)
  기준 전류    Î_expected(x, dir) — models/window_reference_profile.csv (W05 T5.8) · 정상 완주마다 bin 별 EMA 학습 (T10.8)
  끼임 판정    (Ī − Î_expected > ΔI_th(zone)) ∧ (ω̂ < ω_ref·(1 − k_ω)) ∧ (지속 ≥ debounce) ∧ (zone ∈ {B, C})   (T10.6)
              엔드존(C)에서 속도 저하 없이 min_ramp_distance 이상 움직이며 이어지는 초과는 씰 · 가이드 램프 (정상 — T10.5)
  끼임 뒤      정지 → 반대 방향 reverse_distance 반전 → SAFETY_HOLD(hold_s) → 정상
              같은 위치(±reverse_distance) · 같은 방향 repeat_lock_count 회 → 그 방향 잠금 (사용자 해제 WINDOW_UNLOCK)  (T10.7)
              같은 방향 정상 주행이 끼임 위치를 무사히 지나가면(물체가 치워짐) 그 위치의 반복 기록은 지운다
  로컬 차단    브릿지 로컬 컷오프(1.80 A · 120 N)가 먼저 끊으면 그 사건도 끼임으로 받아 같은 정책(반전 · HOLD · 반복 계수)을 적용 (T10.7b)
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from sim.window_local import window_zone

NORMAL, PINCH_REVERSE, SAFETY_HOLD = "NORMAL", "PINCH_REVERSE", "SAFETY_HOLD"


def torque_pct(zone: str, closed_pct: float, tp: dict) -> float:
    """Zone 별 토크 지령 [%] (docs/04 §3.3)."""
    if zone == "A_START":
        return tp["start_torque_pct"]
    if zone == "B_RUN":
        lo, hi = tp["run_zone_pct"]
        f = min(max((closed_pct - lo) / (hi - lo), 0.0), 1.0)
        return tp["run_torque_start_pct"] + f * (tp["run_torque_end_pct"] - tp["run_torque_start_pct"])
    if zone == "C_ENDZONE":
        return tp["endzone_torque_pct"]
    return tp["seal_torque_pct"]


def load_reference(path: Path) -> dict[str, dict[int, float]]:
    """models/window_reference_profile.csv → {dir: {bin: 기준 전류 A}}."""
    ref: dict[str, dict[int, float]] = {"open": {}, "close": {}}
    with open(path, encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        for r in rows:
            width = float(r["bin_hi_m"]) - float(r["bin_lo_m"])
            ref[r["direction"]][int(round(float(r["bin_lo_m"]) / width))] = float(r["current_expected_a"])
    return ref


@dataclass
class Detection:
    t: float
    q: float
    direction: int
    zone: str
    current: float
    expected: float


@dataclass
class WindowSafety:
    ws: dict                                   # thresholds window_sensorless
    travel: float
    ref: dict[str, dict[int, float]]
    hold_s: float
    state: str = NORMAL
    locked: set = field(default_factory=set)   # 잠긴 방향 {−1, +1}
    last: Detection | None = None
    history: list = field(default_factory=list)  # 끼임 기록 (위치 · 방향)
    _over_since: float | None = None
    _start_q: float | None = None
    _dir: int = 0
    _hold_until: float = 0.0
    _reverse_to: float | None = None
    _reverse_t0: float = 0.0
    _run_samples: list = field(default_factory=list)
    _run_clean: bool = True
    _ramp_start_q: float | None = None
    _q_hist: list = field(default_factory=list)

    # ---- 기준 전류 · 학습 ----

    def expected(self, q: float, direction: int) -> float:
        bins = self.ref["close" if direction < 0 else "open"]
        b = min(max(int(q / self.ws["adaptive_threshold"]["position_bin_m"]), 0), max(bins) if bins else 0)
        return bins.get(b, self.ws["no_load_current_a"])

    def _learn(self) -> None:
        """정상 완주 1회 → bin 별 EMA (끼임 주행은 제외 · T10.8)."""
        at = self.ws["adaptive_threshold"]
        if not at["enabled"] or not self._run_clean or not self._run_samples:
            return
        acc: dict[tuple[str, int], list[float]] = {}
        for q, d, i in self._run_samples:
            key = ("close" if d < 0 else "open", int(q / at["position_bin_m"]))
            acc.setdefault(key, []).append(i)
        for (d, b), vals in acc.items():
            if b in self.ref[d]:
                self.ref[d][b] = (1 - at["alpha"]) * self.ref[d][b] + at["alpha"] * sum(vals) / len(vals)

    # ---- 주기 ----

    def zone(self, q: float, direction: int) -> str:
        return window_zone(q, self.travel, direction, self._start_q, self.ws)

    def torque(self, q: float, direction: int) -> float:
        z = self.zone(q, direction)
        return torque_pct(z, (1.0 - q / self.travel) * 100.0, self.ws["torque_profile"])

    def allowed(self, direction: int) -> bool:
        """제어기 지령 방향이 지금 허용되나 (SAFETY_HOLD · 잠김 · 반전 중이면 아니다)."""
        return self.state == NORMAL and direction not in self.locked

    def update(self, t: float, q: float, current: float, direction: int, speed_ref: float) -> str | None:
        """→ 'reverse' (반전 지령을 내라) · 'hold' · 'release' · None."""
        pd = self.ws["pinch_detection"]
        if direction != self._dir:                          # 출발 · 정지 · 방향 전환
            if self._dir != 0 and direction == 0:
                self._learn()
            self._forget_cleared()
            self._dir, self._start_q = direction, (q if direction != 0 else None)
            self._run_samples, self._run_clean, self._over_since, self._ramp_start_q = [], True, None, None
            self._q_hist = []
        self._q_hist.append((t, q))
        self._q_hist = [(a, b) for a, b in self._q_hist if t - a <= 0.2]
        # 상태 머신
        if self.state == PINCH_REVERSE:
            timeout = t - self._reverse_t0 > pd["reverse_timeout_s"]     # 반전이 막혔으면 그 자리에서 멈춰 둔다
            if (self._reverse_to is not None and abs(q - self._reverse_to) < 0.003) or timeout:
                self.state, self._hold_until = SAFETY_HOLD, t + self.hold_s
                return "hold"
            return None
        if self.state == SAFETY_HOLD:
            if t >= self._hold_until:
                self.state = NORMAL
                return "release"
            return None
        if direction == 0:
            return None
        zone = self.zone(q, direction)
        exp = self.expected(q, direction)
        self._run_samples.append((q, direction, current))
        if zone not in ("B_RUN", "C_ENDZONE"):
            self._over_since = None
            return None
        th = pd["delta_i_threshold_run_a"] if zone == "B_RUN" else pd["delta_i_threshold_endzone_a"]
        over = current - exp > th
        # 속도 저하 — 0.2 s 창의 위치 변화로 추정한 속도 vs 지령 속도
        if len(self._q_hist) >= 2 and self._q_hist[-1][0] > self._q_hist[0][0]:
            v = abs(self._q_hist[-1][1] - self._q_hist[0][1]) / (self._q_hist[-1][0] - self._q_hist[0][0])
        else:
            v = abs(speed_ref)
        slow = v < abs(speed_ref) * (1.0 - pd["speed_drop_ratio"])
        # 엔드존 램프 — C 에서 전류 초과가 min_ramp_distance 이상 '움직이며' 이어지면 씰 · 가이드 접근 (정상)
        ed = self.ws["endzone_detection"]
        if zone == "C_ENDZONE" and over and not slow:
            self._ramp_start_q = self._ramp_start_q if self._ramp_start_q is not None else q
            if abs(q - self._ramp_start_q) >= ed["min_ramp_distance_m"]:
                self._over_since = None
                return None
        if over and slow:
            self._over_since = self._over_since if self._over_since is not None else t
            if (t - self._over_since) * 1000.0 >= pd["debounce_ms"]:
                return self._detect(t, q, direction, zone, current, exp)
        else:
            self._over_since = None
        return None

    def _forget_cleared(self) -> None:
        """정상 완주가 지나간 구간의 같은 방향 끼임 기록을 지운다 — 다른 날 · 다른 물체를 '반복'으로 세지 않게."""
        if not self._run_clean or len(self._run_samples) < 2:
            return
        qs = [s[0] for s in self._run_samples]
        lo, hi, d = min(qs), max(qs), self._run_samples[0][1]
        self.history = [h for h in self.history if not (h[1] == d and lo <= h[0] <= hi)]

    def local_trip(self, t: float, q: float, current: float) -> str | None:
        """브릿지 로컬 컷오프가 끊었다 — 상위가 아직 판정 전이면 끼임으로 받아 반전한다 (→ 'reverse' · None)."""
        if self.state != NORMAL or self._dir == 0:
            return None
        return self._detect(t, q, self._dir, self.zone(q, self._dir), current, self.expected(q, self._dir))

    def _detect(self, t, q, direction, zone, current, exp) -> str:
        pd = self.ws["pinch_detection"]
        self.last = Detection(t, q, direction, zone, current, exp)
        self._run_clean = False
        same = [h for h in self.history if h[1] == direction and abs(h[0] - q) <= pd["reverse_distance_m"]]
        self.history.append((q, direction))
        if len(same) + 1 >= pd["repeat_lock_count"]:
            self.locked.add(direction)                     # 같은 자리 반복 — 그 방향 잠금 (사용자 해제)
        self._reverse_to = min(max(q - direction * pd["reverse_distance_m"], 0.0), self.travel)
        self.state, self._reverse_t0 = PINCH_REVERSE, t
        self._over_since = None
        return "reverse"

    def unlock(self) -> None:
        self.locked.clear()
        self.history.clear()

    def state_label(self) -> str:
        if self.locked:
            return "LOCKED_" + ("CLOSING" if -1 in self.locked else "OPENING") + ("" if self.state == NORMAL else "|" + self.state)
        return self.state
