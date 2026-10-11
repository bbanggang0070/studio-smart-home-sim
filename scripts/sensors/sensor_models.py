"""가상 센서 특성 (W07 T7.5) — 참값 → 측정값: 1차 지연 → 가우시안 잡음 → 양자화 → 범위 클램프.

순수 Python (numpy 난수). 물리 모드 센서 노드가 쓴다. 계수는 config/sensor_models.yaml.
"""

from __future__ import annotations

import math

import numpy as np


class SensorModel:
    def __init__(self, spec: dict, rng: np.random.Generator):
        self.s, self.rng = spec, rng
        self.y: float | None = None

    def measure(self, truth: float, dt: float) -> float:
        s = self.s
        if self.y is None or s["tau_s"] <= 0:
            self.y = truth
        else:
            self.y += (truth - self.y) * (1.0 - math.exp(-dt / s["tau_s"]))
        v = self.y + self.rng.normal(0.0, s["sigma"] + s["rel_sigma"] * abs(self.y))
        q = s["resolution"]
        v = round(v / q) * q if q > 0 else v
        lo, hi = s["range"]
        return float(min(max(v, lo), hi))


class RippleCounter:
    """창문 위치 추정 (T7.4b · docs/04 §4.3) — 리플 주파수(수백 Hz)는 물리 스텝을 넘으므로 조인트 위치에서 해석적으로 센다.

    리플 1개 = 2πr/(G·N_c) 이동. 이동할 때마다 지나간 리플 수를 세되 미스카운트(확률)로 빠뜨리고, 추정값에 잡음을 더한다.
    하드 스톱(완전 닫힘 · 완전 열림)에서 멈추면 카운트를 끝 위치로 맞춘다 (재동기화).
    """

    def __init__(self, ws: dict, travel: float, resync_m: float, rng: np.random.Generator):
        r = ws["ripple_estimation"]
        self.pitch = 2 * math.pi * ws["pinion_radius_m"] / (ws["gear_ratio"] * ws["commutator_ripple_per_rev"])
        self.miss = r["miscount_rate_pct"] / 100.0
        self.noise = r["position_noise_sigma_m"]
        self.travel, self.resync, self.rng = travel, resync_m, rng
        self.count = 0
        self._last_q: float | None = None
        self._acc = 0.0

    def update(self, q: float, moving: bool) -> float:
        if self._last_q is None:
            self._last_q = q
            self.count = round(max(q, 0.0) / self.pitch)
        self._acc += q - self._last_q
        self._last_q = q
        n = int(self._acc / self.pitch)                       # 지나간 리플 (부호 = 방향)
        if n:
            self._acc -= n * self.pitch
            missed = self.rng.binomial(abs(n), self.miss)
            self.count += int(math.copysign(abs(n) - missed, n))
        if not moving:                                        # 하드 스톱 재동기화
            if q <= self.resync:
                self.count = 0
            elif q >= self.travel - self.resync:
                self.count = round(self.travel / self.pitch)
        return self.count * self.pitch + float(self.rng.normal(0.0, self.noise))
