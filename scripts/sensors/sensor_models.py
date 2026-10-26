"""가상 센서 특성 (W07 T7.5) — 참값 → 측정값: 1차 지연 → 가우시안 잡음 → 양자화 → 범위 클램프.

순수 Python (numpy 난수). 물리 모드 센서 노드가 쓴다. 계수는 config/sensor_models.yaml.
"""

from __future__ import annotations

import math

import numpy as np


# 참값 관측 키 ← 센서 이름 (config/sensor_models.yaml sensors) — 물리 모드 센서 노드 · 고속 하네스가 같이 쓴다
TRUTH_SENSORS = {"temperature": "temperature_c", "humidity": "humidity_pct", "illuminance": "illuminance_lux",
                 "pm25": "pm25_ugm3", "hood_temperature": "hood_temperature_c"}
PLUG_DEVICES = ("ac", "dehumidifier", "humidifier")          # 계량 플러그가 달린 가전 (+ 시나리오 발생원 전력) — docs/08 §3


class SensorModel:
    def __init__(self, spec: dict, rng: np.random.Generator, faults: dict | None = None, frng: np.random.Generator | None = None):
        """faults (선택 · 2026-10-26) — 실제 센서 결함: 편향(실행마다 고정) · 드리프트(시간 비례) · 이상값 · 끊김(마지막 값 유지).
        결함 난수(frng)는 기본 잡음 난수와 따로 — 같은 시드면 결함만 더한 짝 비교가 된다."""
        self.s, self.rng = spec, rng
        self.y: float | None = None
        self.f, self.frng = faults, frng
        self.t = 0.0
        self.last: float | None = None
        self.hold_until = -1.0
        if faults:
            self.bias = float(frng.uniform(-faults["bias"], faults["bias"]))
            self.drift = float(frng.uniform(-faults["drift_per_h"], faults["drift_per_h"]))

    def measure(self, truth: float, dt: float) -> float:
        s = self.s
        if self.y is None or s["tau_s"] <= 0:
            self.y = truth
        else:
            self.y += (truth - self.y) * (1.0 - math.exp(-dt / s["tau_s"]))
        v = self.y + self.rng.normal(0.0, s["sigma"] + s["rel_sigma"] * abs(self.y))
        f = self.f
        if f:
            self.t += dt
            scale = abs(self.y) if f.get("relative") else 1.0          # 상대 편향(PM · 조도 · 전력)은 값에 비례
            v += (self.bias + self.drift * self.t / 3600.0) * scale
            if self.frng.random() < f["outlier_p"]:
                v += self.frng.choice([-1.0, 1.0]) * f["outlier_sigma"] * (s["sigma"] + s["rel_sigma"] * abs(self.y))
            if self.t < self.hold_until and self.last is not None:
                return self.last                                       # 끊김 — 갱신이 멈춰 마지막 값이 남는다
            if self.frng.random() < f["dropout_p_per_s"] * dt:
                self.hold_until = self.t + float(self.frng.uniform(*f["dropout_s"]))
        q = s["resolution"]
        v = round(v / q) * q if q > 0 else v
        lo, hi = s["range"]
        self.last = float(min(max(v, lo), hi))
        return self.last


class SensorSuite:
    """참값 관측 → 센서 측정값 묶음 (고속 하네스 · 2026-10-24 모드 대조). 물리 모드 센서 노드와 같은 모델 · 같은 계량 플러그 범위.
    측정 주기는 제어 주기(1 Hz)로 한 번 — 물리 모드는 온습도 · 조도를 10 Hz 로 뽑지만 제어기는 1 Hz 로 마지막 값을 읽는다."""

    def __init__(self, cfg: dict, rng: np.random.Generator, frng: np.random.Generator | None = None):
        """frng 를 주면 cfg['faults'] 의 센서 결함을 켠다 (기본 꺼짐)."""
        s = cfg["sensors"]
        fl = (cfg.get("faults") or {}) if frng is not None else {}
        self.models = {name: SensorModel(s[name], rng, fl.get(name), frng) for name in TRUTH_SENSORS}
        self.plug = {d: SensorModel(s["appliance_power"], rng, fl.get("appliance_power"), frng) for d in PLUG_DEVICES}

    def measure(self, obs: dict, dt: float) -> dict[str, float]:
        return {name: self.models[name].measure(float(obs[key]), dt) for name, key in TRUTH_SENSORS.items()}

    def plug_power(self, obs: dict, extra_power: dict[str, float], dt: float) -> dict[str, float]:
        p = {d: self.plug[d].measure(float(obs["appliance_power_w"].get(d, 0.0)), dt) for d in PLUG_DEVICES}
        p.update({k: round(float(v), 1) for k, v in extra_power.items()})
        return p


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
