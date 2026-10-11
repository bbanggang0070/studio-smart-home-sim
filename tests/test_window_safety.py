"""센서리스 창문 상위 안전 계층 (W10 T10.3–T10.8)."""

import numpy as np
import pytest

from controller.params import load_params
from controller.window_safety import SAFETY_HOLD, WindowSafety, load_reference, torque_pct
from harness.runner import REPO

WS = load_params().get("window_sensorless")


def _ws(hold_s=30.0):
    return WindowSafety(WS, 0.7, load_reference(REPO / "models" / "window_reference_profile.csv"), hold_s)


def _close(s, t0=0.0, q0=0.7, q_end=0.0, extra=None, stop_at=None, rng=None, speed=0.05):
    """50 Hz 로 닫는다. extra(q) = 기준 위에 더할 전류 · stop_at = 막혀 서는 위치. → (첫 지령, 시각, 위치)."""
    rng = rng or np.random.default_rng(0)
    t, q = t0, q0
    while q > q_end:
        q_next = max(q - speed * 0.02, q_end)
        if stop_at is not None and q_next <= stop_at:
            q_next = stop_at
        cur = s.expected(q, -1) + (extra(q) if extra else 0.0) + rng.normal(0, 0.02)
        act = s.update(t, q, cur, -1, speed)
        if act:
            return act, t, q
        t += 0.02
        if q_next == q and stop_at is not None and t - t0 > 30:
            break
        q = q_next
    s.update(t, q, s.expected(q, -1), 0, speed)
    return None, t, q


def test_torque_profile_shape():
    tp = WS["torque_profile"]
    assert torque_pct("A_START", 1, tp) == 100 and torque_pct("C_ENDZONE", 90, tp) == 70
    assert torque_pct("B_RUN", 5, tp) == pytest.approx(100) and torque_pct("B_RUN", 85, tp) == pytest.approx(55)


def test_normal_closes_are_not_pinch():
    s = _ws()
    for k in range(20):                                    # 정상 폐쇄 20회 — 엔드존 램프 포함 (W10 DoD)
        act, _, _ = _close(s, t0=k * 100.0, rng=np.random.default_rng(k))
        assert act is None
    assert s.state == "NORMAL"


def test_step_pinch_in_run_is_detected_fast_then_reverse_and_hold():
    s = _ws(hold_s=5.0)
    extra = lambda q: 0.0 if q > 0.40 else 0.6          # noqa: E731 — 0.40 m 에서 계단 상승 + 막힘
    act, t, q = _close(s, extra=extra, stop_at=0.40)
    assert act == "reverse" and abs(q - 0.40) < 0.003 and s.last.zone == "B_RUN"
    # 반전 50 mm → SAFETY_HOLD → 해제
    assert s.update(t + 1.0, 0.45, 0.2, +1, 0.05) == "hold" and s.state == SAFETY_HOLD
    assert not s.allowed(-1)
    assert s.update(t + 7.0, 0.45, 0.2, 0, 0.05) == "release" and s.allowed(-1)


def test_pinch_just_before_endzone_is_detected():
    s = _ws()
    extra = lambda q: 0.0 if q > 0.11 else 0.8           # noqa: E731 — 엔드존(0.105 m) 직전
    act, _, q = _close(s, extra=extra, stop_at=0.11)
    assert act == "reverse"


def test_repeat_pinch_locks_direction_until_unlock():
    s = _ws(hold_s=0.5)
    extra = lambda q: 0.0 if q > 0.40 else 0.6           # noqa: E731
    for k in range(2):
        act, t, q = _close(s, t0=k * 50.0, extra=extra, stop_at=0.40)
        assert act == "reverse"
        s.update(t + 1, 0.45, 0.2, +1, 0.05)
        s.update(t + 3, 0.45, 0.2, 0, 0.05)
    assert -1 in s.locked and not s.allowed(-1) and s.allowed(+1)
    s.unlock()
    assert s.allowed(-1)


def test_adaptive_threshold_tracks_drift():
    s = _ws()
    before = s.expected(0.40, -1)
    for k in range(5):                                     # 레일 오염 — 전류가 0.1 A 늘었다
        _close(s, t0=k * 100.0, extra=lambda q: 0.1, rng=np.random.default_rng(k))
    assert s.expected(0.40, -1) > before + 0.05


def test_local_trip_is_taken_as_pinch_by_upper_layer():
    s = _ws(hold_s=0.5)
    t, q = 0.0, 0.7
    while q > 0.40:                                        # 정상 주행 중 …
        assert s.update(t, q, s.expected(q, -1), -1, 0.05) is None
        t, q = t + 0.02, q - 0.001
    assert s.local_trip(t, q, 1.9) == "reverse"            # 로컬이 먼저 끊음 → 상위가 반전 정책 (T10.7b)
    assert s.state == "PINCH_REVERSE" and abs(s._reverse_to - (q + 0.05)) < 1e-9
    assert s.local_trip(t + 0.1, q, 1.9) is None           # 이미 판정 중이면 다시 세지 않는다


def test_clean_run_past_pinch_spot_clears_repeat_history():
    s = _ws(hold_s=0.5)
    extra = lambda q: 0.0 if q > 0.40 else 0.6           # noqa: E731
    act, t, _ = _close(s, extra=extra, stop_at=0.40)
    assert act == "reverse"
    s.update(t + 1, 0.45, 0.2, +1, 0.05)
    s.update(t + 3, 0.45, 0.2, 0, 0.05)
    _close(s, t0=t + 10, q0=0.45)                          # 물체를 치우고 끝까지 닫힘 — 정상 완주
    act, t, _ = _close(s, t0=t + 100, extra=extra, stop_at=0.40)
    assert act == "reverse" and not s.locked               # 새 물체 — 반복이 아니다


def test_blocked_reverse_times_out_into_hold():
    s = _ws(hold_s=1.0)
    extra = lambda q: 0.0 if q > 0.40 else 0.6           # noqa: E731
    act, t, q = _close(s, extra=extra, stop_at=0.40)
    assert act == "reverse"
    assert s.update(t + 1.0, q, 0.2, +1, 0.05) is None     # 반전 지령 뒤 움직이지 않음
    to = WS["pinch_detection"]["reverse_timeout_s"]
    assert s.update(t + to + 0.1, q, 0.2, +1, 0.05) == "hold" and s.state == SAFETY_HOLD
