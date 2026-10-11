"""제어 가능성 판정 (W09 T9.7)."""

from types import SimpleNamespace

from controller.arbiter import Decision
from controller.feasibility import Feasibility
from controller.params import load_params

P = load_params()
MODE = P.mode("NORMAL")


def _o(t, temp, rh=50.0, pm=10.0):
    return SimpleNamespace(now_s=t, temp_c=temp, rh_pct=rh, pm25=pm)


def _run(temps, decided, caps, useful, events=None, dt=60):
    f = Feasibility(P)
    states = [f.update(_o(i * dt, T), MODE, decided, set(decided), caps, events or {}, useful) for i, T in enumerate(temps)]
    return states, f


def test_infeasible_when_all_cooling_means_blocked_and_not_improving():
    decided = {"window": Decision(0.0, []), "exhaust": Decision(0.0, []), "blind": Decision(75.0, [])}
    caps = {"window": 0.0, "exhaust": 0.0, "blind": 75.0}            # 비로 창문 · I7 로 배기 막힘 · 블라인드 최대
    useful = {"cooling": {"window": True, "exhaust": True, "blind": True}}
    states, f = _run([32.0] * 15, decided, caps, useful)          # 1분 간격 — DEGRADED(2분) → INFEASIBLE(5분)
    assert states[1] == "FEASIBLE" and states[3] == "DEGRADED" and states[-1] == "INFEASIBLE" and f.reason == "cooling"


def test_feasible_while_a_means_has_headroom_or_improving():
    decided = {"window": Decision(0.0, []), "exhaust": Decision(600.0, [])}
    caps = {"window": 0.0, "exhaust": 2000.0}                        # 배기는 더 올릴 수 있다
    useful = {"cooling": {"window": True, "exhaust": True}}
    assert _run([32.0] * 15, decided, caps, useful)[0][-1] == "DEGRADED"      # 미달은 길지만 수단이 남았다
    caps = {"window": 0.0, "exhaust": 600.0}
    falling = [32.0 - 0.1 * i for i in range(15)]                    # 막혔지만 나아지는 중
    assert _run(falling, decided, caps, useful)[0][-1] != "INFEASIBLE"


def test_useless_means_count_as_exhausted_and_fault_degrades():
    decided = {"exhaust": Decision(0.0, [])}
    caps = {"exhaust": 2000.0}
    useful = {"cooling": {"exhaust": False}}                         # 외기가 더 더움 — 배기는 냉방 수단이 아니다
    assert _run([32.0] * 15, decided, caps, useful)[0][-1] == "INFEASIBLE"
    assert _run([24.0] * 3, decided, caps, useful, {"APPLIANCE_FAULT": 1})[0][-1] == "DEGRADED"
