"""창문 로컬 안전 계층 (W06 T6.7) — 전류 환산 · Zone · 컷오프 조건."""

import pytest

from controller.params import load_params
from sim.window_local import LocalCutoff, motor_current, window_zone


@pytest.fixture(scope="module")
def ws():
    return load_params().get("window_sensorless")


def test_current_conversion(ws):
    assert motor_current(0.0, ws) == pytest.approx(ws["no_load_current_a"])
    assert motor_current(-50.0, ws) == pytest.approx(0.12 + 50 * 0.01 / (30 * 0.012 * 0.65), rel=1e-6)


def test_zones_closing(ws):
    assert window_zone(0.69, 0.7, -1, 0.70, ws) == "A_START"
    assert window_zone(0.40, 0.7, -1, 0.70, ws) == "B_RUN"
    assert window_zone(0.05, 0.7, -1, 0.70, ws) == "C_ENDZONE"
    assert window_zone(0.01, 0.7, -1, 0.70, ws) == "D_SEAL"
    assert window_zone(0.01, 0.7, +1, 0.00, ws) == "A_START"        # 열기 시작


def _run(cut, forces, q0=0.5, direction=-1, dt=1 / 120, speed=0.05):
    """forces = 운동 방향으로 미는 힘의 크기 (조인트 힘 = 크기 × 방향)."""
    q, t = q0, 0.0
    for f in forces:
        if cut.step(t, q, direction * speed, f * direction, direction):
            return t
        q += direction * speed * dt
        t += dt
    return None


def test_normal_run_and_start_peak_do_not_trip(ws):
    cut = LocalCutoff(ws, 0.7)
    peak = [80.0] * 12 + [5.0] * 600              # 기동 100 ms 동안 큰 힘(블랭킹 안 · 반력 120 N 미만) → 주행
    assert _run(cut, peak) is None and not cut.tripped


def test_pinch_trips_and_blocks_same_direction(ws):
    cut = LocalCutoff(ws, 0.7)
    forces = [5.0] * 120 + [5.0 + 2.0 * k for k in range(60)]   # 1 s 주행 뒤 반력 상승
    t = _run(cut, forces)
    assert t is not None and cut.tripped and "전류" in cut.reason
    assert cut.on_command(-1) is False                          # 같은 방향 거부
    assert cut.on_command(+1) is True and not cut.tripped       # 반대 방향(빠져나옴) 허용


def test_seal_zone_uses_force_only(ws):
    cut = LocalCutoff(ws, 0.7)
    assert _run(cut, [5.0] * 60 + [71.0] * 60, q0=0.012) is None    # 씰 압착 71 N — 전류는 넘어도 정지 안 함
    closed = LocalCutoff(ws, 0.7)                                    # 다 닫혀 최대 힘으로 누름 — 정상
    assert _run(closed, [5.0] * 60 + [130.0] * 10, q0=0.0, speed=0.0) is None
    stuck = LocalCutoff(ws, 0.7)                                     # 씰 구간인데 10 mm 앞에서 막힘 — 반력 백업
    assert _run(stuck, [5.0] * 60 + [130.0] * 10, q0=0.010, speed=0.0) is not None


def test_braking_force_is_not_pinch(ws):
    cut = LocalCutoff(ws, 0.7)
    q, t = 0.3, 0.0
    for k in range(240):                                             # 열면서(+1) 목표 도착 제동 −45 N
        f = 5.0 if k < 200 else -45.0
        assert not cut.step(t, q, 0.05, f, +1)
        q += 0.05 / 120
        t += 1 / 120
