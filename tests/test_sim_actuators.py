"""시뮬레이터 액추에이터 변환 (W05 T5.3 · T5.3b · T5.5) — Isaac 없이 도는 부분."""

import math

from sim.actuators import (Ramp, clamp_cct, dimming_to_intensity, rad_s_to_rpm, rpm_to_deg_s, window_q_to_ratio,
                           window_ratio_to_q)


def test_window_ratio_roundtrip_and_clamp():
    assert window_ratio_to_q(0.5, 0.7) == 0.35
    assert window_q_to_ratio(0.35, 0.7) == 0.5
    assert window_ratio_to_q(1.4, 0.7) == 0.7 and window_q_to_ratio(-0.004, 0.7) == 0.0


def test_fan_and_light_units():
    assert rpm_to_deg_s(1000) == 6000
    assert math.isclose(rad_s_to_rpm(2 * math.pi), 60.0)
    assert dimming_to_intensity(50, 30000) == 15000 and dimming_to_intensity(150, 100) == 100
    assert clamp_cct(2000) == 2700 and clamp_cct(7000) == 6500


def test_ramp_limits_rate_and_reaches_goal():
    r = Ramp(rate=0.05)
    r.set_goal(0.1)
    q, v = r.step(1.0)
    assert math.isclose(q, 0.05) and math.isclose(v, 0.05)
    for _ in range(5):
        q, v = r.step(1.0)
    assert q == 0.1 and v == 0.0
