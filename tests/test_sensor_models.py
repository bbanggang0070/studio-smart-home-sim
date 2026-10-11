"""가상 센서 특성 · 리플 카운팅 (W07 T7.4b · T7.5)."""

import numpy as np
import yaml

from controller.params import load_params
from harness.runner import REPO
from sensors.sensor_models import RippleCounter, SensorModel


def _spec(name):
    return yaml.safe_load((REPO / "config" / "sensor_models.yaml").read_text(encoding="utf-8"))["sensors"][name]


def test_lag_noise_quantization():
    m = SensorModel(_spec("temperature"), np.random.default_rng(0))
    vals = [m.measure(25.0, 0.1) for _ in range(5)] + [m.measure(30.0, 0.1) for _ in range(600)]
    assert abs(vals[0] - 25.0) < 0.5
    assert abs(np.mean(vals[-100:]) - 30.0) < 0.1 and np.std(vals[-100:]) < 0.2   # 60 s 뒤 수렴 (τ 5 s)
    assert all(abs(v * 100 - round(v * 100)) < 1e-6 for v in vals)               # 0.01 분해능


def test_ripple_counter_drift_and_resync():
    ws = load_params().get("window_sensorless")
    rc = RippleCounter(ws, 0.7, 0.002, np.random.default_rng(1))
    q = 0.0
    errs = []
    for _ in range(5):                                       # 5회 왕복 · 끝에서 멈추지 않으면 미스카운트가 쌓인다
        for k in range(1400):
            q = min(0.7, q + 0.0005)
            est = rc.update(q, moving=True)
        for k in range(1400):
            q = max(0.0, q - 0.0005)
            est = rc.update(q, moving=True)
        errs.append(abs(est - q))
    assert rc.pitch * 1000 < 0.25                            # 리플 1개 ≈ 0.209 mm
    assert max(errs) < 0.02                                  # 미스카운트 0.3 % — 1회 왕복 수 mm 이내
    est = rc.update(0.0, moving=False)                       # 하드 스톱 재동기화
    assert abs(est) < 0.001
