"""통합 제어기 v1 검증 — 중재 규칙 · 모드 · 이벤트 · 사다리 규칙 · 하네스 폐루프 회귀."""

import json

import pytest

from controller.arbiter import Candidate, merge
from controller.event_detector import EventDetector
from controller.mode_manager import ModeManager
from controller.params import load_params
from controller.signals import Psychro, parse_inbox
from controller.smart_home import SmartHomeController
from harness import criteria as C
from harness.runner import load_harness_config, run_batch
from interfaces import topics as T


@pytest.fixture(scope="module")
def params():
    return load_params()


def inbox(**kw):
    base = {
        T.S_TEMPERATURE: 24.0, T.S_HUMIDITY: 50.0, T.S_PM25: 12.0, T.S_HOOD_TEMPERATURE: 24.0,
        T.S_OCCUPANCY: True, T.S_OCCUPANT_ZONE: "room", T.S_OUTDOOR_PM_GRADE: "good",
        T.S_APPLIANCE_POWER: "{}", T.C_MODE: "NORMAL",
        T.S_WEATHER: json.dumps({"raining": False, "outdoor_temp_c": 20.0, "outdoor_rh_pct": 55.0}),
    }
    base.update(kw)
    return base


# ---- 중재 (docs/07 §5.2) ----------------------------------------------------------


def test_merge_need_max_cap_min():
    d = merge([Candidate("window", "need", 0.1, 5, "기본 환기"), Candidate("window", "need", 0.4, 2, "요리"),
               Candidate("window", "cap", 0.3, 1, "외기 보통")], {})
    assert d["window"].value == pytest.approx(0.3)


def test_merge_force_wins_but_respects_higher_cap():
    d = merge([Candidate("exhaust", "force", 2000, 2, "샤워"), Candidate("exhaust", "cap", 600, 1, "외기 나쁨"),
               Candidate("exhaust", "cap", 1000, 4, "소음 N1")], {})
    assert d["exhaust"].value == 600          # L1 cap 은 지키고, L4 cap 은 L2 force 가 이긴다


def test_merge_default_when_no_need():
    d = merge([Candidate("hood", "cap", 1, 4, "소음")], {"hood": 0.0})
    assert d["hood"].value == 0.0


# ---- 모드 관리자 (docs/07 §2) -----------------------------------------------------


def test_auto_mode_with_hysteresis(params):
    mm = ModeManager(params)
    desk = lambda t: parse_inbox(t, inbox(**{T.C_MODE: "AUTO", T.S_OCCUPANT_ZONE: "desk"}))
    room = lambda t: parse_inbox(t, inbox(**{T.C_MODE: "AUTO", T.S_OCCUPANT_ZONE: "room"}))
    ten = 10 * 3600.0
    assert mm.update(desk(ten))[0] == "STUDY"
    assert mm.update(room(ten + 60))[0] == "STUDY"             # 10분 히스테리시스 전
    assert mm.update(room(ten + 60 + 600))[0] == "NORMAL"


def test_manual_mode_and_away_arrival(params):
    mm = ModeManager(params)
    assert mm.update(parse_inbox(0, inbox(**{T.C_MODE: "SLEEP"}))) == ("SLEEP", "manual")
    assert mm.update(parse_inbox(1, inbox(**{T.S_OCCUPANCY: False})))[0] == "AWAY"
    assert mm.update(parse_inbox(2, inbox(**{T.C_MODE: "NORMAL"})))[0] == "NORMAL"


# ---- 이벤트 감지기 (docs/07 §3) ---------------------------------------------------


def _detector(params):
    return EventDetector(params, Psychro(params))


def test_cooking_by_hood_heat_and_steam_vs_smoke(params):
    det = _detector(params)
    for t in range(0, 61):
        det.update(parse_inbox(t, inbox()))
    det.update(parse_inbox(61, inbox(**{T.S_HOOD_TEMPERATURE: 40.0})))
    assert det.active["COOKING"].info["source"] == "steam"          # 열만
    det.update(parse_inbox(90, inbox(**{T.S_HOOD_TEMPERATURE: 44.0, T.S_PM25: 30.0})))
    assert det.active["COOKING"].info["source"] == "cooking"        # 열 + 연기


def test_cooktop_power_triggers_cooking(params):
    det = _detector(params)
    det.update(parse_inbox(0, inbox(**{T.S_APPLIANCE_POWER: json.dumps({"cooktop": 1500.0})})))
    assert "COOKING" in det.active


def test_cooking_release_then_post_run(params):
    det = _detector(params)
    for t in range(0, 61):
        det.update(parse_inbox(t, inbox()))
    det.update(parse_inbox(61, inbox(**{T.S_HOOD_TEMPERATURE: 40.0})))
    det.active["COOKING"].info["hood_level"] = 1
    det.update(parse_inbox(200, inbox()))                            # 열 꺼짐 · PM 정상 → 해제
    assert "COOKING" not in det.active and "HOOD_POST_RUN" in det.active
    post_s = params.get("events.cooking.hood_post_run_s")
    det.update(parse_inbox(200 + post_s + 1, inbox()))
    assert "HOOD_POST_RUN" not in det.active


def test_shower_needs_rh_jump_without_hood_heat(params):
    det = _detector(params)
    for t in range(0, 301):
        det.update(parse_inbox(t, inbox()))
    det.update(parse_inbox(301, inbox(**{T.S_HUMIDITY: 60.0})))
    assert "SHOWER" in det.active
    det2 = _detector(params)
    for t in range(0, 301):
        det2.update(parse_inbox(t, inbox()))
    det2.update(parse_inbox(301, inbox(**{T.S_HUMIDITY: 60.0, T.S_HOOD_TEMPERATURE: 40.0})))
    assert "SHOWER" not in det2.active                               # 요리 수증기 — 샤워 아님


def test_rain_and_condensation(params):
    det = _detector(params)
    w = json.dumps({"raining": True, "outdoor_temp_c": -5.0, "outdoor_rh_pct": 80.0})
    det.update(parse_inbox(0, inbox(**{T.S_WEATHER: w, T.S_TEMPERATURE: 21.0, T.S_HUMIDITY: 70.0,
                                       T.S_HOOD_TEMPERATURE: 21.0})))
    assert "RAIN" in det.active
    assert det.active["CONDENSATION"].info["level"] == "critical"


# ---- 규칙 · 출력 ---------------------------------------------------------------------


def _ctrl(params):
    c = SmartHomeController(params)
    c.reset({"baseline": "proposed"})
    return c


def test_rain_forces_window_closed_and_intake_takes_base_vent(params):
    c = _ctrl(params)
    out = c.step(0, inbox(**{T.S_WEATHER: json.dumps({"raining": True, "outdoor_temp_c": 22.0,
                                                      "outdoor_rh_pct": 90.0})}))
    assert out[T.C_WINDOW_OPEN_RATIO] == 0.0
    assert out[T.C_INTAKE_FAN_RPM] > 0.0                             # 기본 환기 수단이 흡기팬으로 넘어간다
    assert any("E5 강우" in r for r in c.reasons())


def test_sleep_noise_grade_caps_intake(params):
    c = _ctrl(params)
    w = json.dumps({"raining": True, "outdoor_temp_c": 22.0, "outdoor_rh_pct": 90.0})
    out = c.step(0, inbox(**{T.C_MODE: "SLEEP", T.S_WEATHER: w}))
    assert out[T.C_INTAKE_FAN_RPM] <= params.noise("N0")["intake_fan_max_rpm"]


def test_i7_no_exhaust_without_supply_when_outdoor_bad(params):
    c = _ctrl(params)
    for t in range(0, 301):
        c.step(t, inbox(**{T.S_OUTDOOR_PM_GRADE: "bad"}))
    out = c.step(301, inbox(**{T.S_OUTDOOR_PM_GRADE: "bad", T.S_HUMIDITY: 62.0,
                               T.S_WEATHER: json.dumps({"raining": False, "outdoor_temp_c": 5.0,
                                                        "outdoor_rh_pct": 40.0})}))
    ex_m3h = out[T.C_FAN_RPM] / 2000.0 * 50.0
    in_m3h = out[T.C_INTAKE_FAN_RPM] / 2000.0 * 60.0
    assert in_m3h >= ex_m3h - 1e-6


# ---- 하네스 폐루프 회귀 ----------------------------------------------------------------


def test_b7_proposed_passes(tmp_path):
    res = run_batch(["B7"], baselines=["proposed"], reps=1, out_dir=tmp_path, progress=lambda *_: None)
    assert res[0].status == C.PASS, [(c.status, c.text, c.detail) for c in res[0].criteria]


def test_c9_proposed_behaviour(tmp_path):
    res = run_batch(["C9"], baselines=["A", "proposed"], reps=1, out_dir=tmp_path, progress=lambda *_: None)
    p = next(r for r in res if r.run.baseline == "proposed")
    st = {c.text: c.status for c in p.criteria}
    assert st["event_entered('COOKING') within 90 after cooking_start"] == C.PASS
    assert st["window_open_ratio == 0 for all t"] == C.PASS
    assert st["range_hood_level == 1 during cooking settle 90"] == C.PASS
    assert st["intake_fan_rpm >= 1800.0 during cooking settle 90"] == C.PASS
