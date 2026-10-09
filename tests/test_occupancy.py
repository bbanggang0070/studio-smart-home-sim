"""재실 판정 노드 (sensors/occupancy) — 문 이벤트 + 판정 창 · 증거 강도 · 폴백."""

import pytest

from controller.params import load_params
from sensors.occupancy import FALLBACK, LATCHED_OCCUPIED, LATCHED_VACANT, OccupancyJudge


@pytest.fixture(scope="module")
def occ():
    return load_params().th["occupancy"]


Q = [0.0] * 9   # 조용한 레이더


def gates(**kw):
    m, s = list(Q), list(Q)
    for k, v in kw.items():
        kind, g = k.split("_")
        (m if kind == "m" else s)[int(g)] = v
    return m, s


def run(j, t0, t1, door=False, wifi=True, power=None, **g):
    m, s = gates(**g)
    out = None
    for t in range(t0, t1):
        out = j.update(float(t), door, m, s, wifi, power or {})
    return out


def test_wall_gate_is_six(occ):
    assert OccupancyJudge(occ, True).last_gate == 6


def test_leave_latches_vacant_after_judge_window(occ):
    j = OccupancyJudge(occ, True)
    run(j, 0, 10, s_2=55.0)
    run(j, 10, 15, door=True)                       # 문 열림 → 닫힘
    out = run(j, 15, 15 + 179)
    assert out.occupied and out.basis == "JUDGING"
    out = run(j, 194, 200)
    assert not out.occupied and out.basis == LATCHED_VACANT


def test_still_person_latches_occupied_and_holds_without_wifi(occ):
    j = OccupancyJudge(occ, True)
    run(j, 0, 1)
    run(j, 1, 5, door=True)
    out = run(j, 5, 100, s_2=55.0)                  # 안쪽 정지 60 s → 강한 증거
    assert out.basis == LATCHED_OCCUPIED
    out = run(j, 100, 4000, wifi=False)             # 레이더 · Wi-Fi 모두 조용해도 다음 문 열림까지 유지
    assert out.occupied


def test_wall_only_signal_extends_then_vacant(occ):
    j = OccupancyJudge(occ, True)
    run(j, 0, 1)
    run(j, 1, 5, door=True)
    out = run(j, 5, 400, s_6=45.0)                  # 벽 구간(약한 증거)만 → 3분 넘어도 판정 중
    assert out.basis == "JUDGING"
    out = run(j, 400, 700, s_6=45.0)
    assert out.basis == LATCHED_VACANT


def test_vacant_ignores_curtain_but_contradiction_falls_back(occ):
    j = OccupancyJudge(occ, False)
    out = run(j, 0, 300, wifi=False, m_4=35.0)      # 빈방 고정 — mmWave 단독 신호 무시
    assert not out.occupied and out.basis == LATCHED_VACANT
    run(j, 300, 310, wifi=False, m_3=60.0)
    out = j.update(310.0, False, *gates(m_3=60.0), False, {"pc": 120.0})   # 움직임 + 기기 조작 → 모순
    assert out.basis == FALLBACK and out.fault and out.alerts


def test_door_left_open_falls_back_then_returns(occ):
    j = OccupancyJudge(occ, True)
    run(j, 0, 1)
    out = run(j, 1, 602, door=True, s_2=55.0)
    assert out.basis == FALLBACK
    out = run(j, 602, 700, door=False, s_2=55.0)
    assert out.basis == LATCHED_OCCUPIED


def test_scenarios_pass(tmp_path):
    from harness import criteria as C
    from harness.runner import run_batch
    res = run_batch(["B4", "B12", "X9"], reps=1, out_dir=tmp_path, progress=lambda *_: None)
    for r in res:
        assert r.status == C.PASS, (r.run.run_id, [(c.status, c.text, c.detail) for c in r.criteria])
