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


def test_manual_away_kept_until_door_then_presence(params):
    """수동 외출 — 사람이 잠시 남아 있어도 유지 · 문 출입 뒤 60 s 에 실내에 사람이 있으면 해제 (2026-10-24 사용자 결정)."""
    mm = ModeManager(params)
    o = lambda t, **kw: parse_inbox(t, inbox(**{T.C_MODE: "AWAY", **kw}))
    assert mm.update(parse_inbox(0, inbox(**{T.C_MODE: "STUDY"})))[0] == "STUDY"
    assert mm.update(o(10))[0] == "AWAY"                         # 직접 고른 외출 — 사람이 아직 있어도 유지
    assert mm.update(o(100))[0] == "AWAY"
    mm.update(o(200, **{T.S_DOOR_CONTACT: True}))                # 출입
    mm.update(o(208, **{T.S_DOOR_CONTACT: False, T.T_OCCUPANCY_BASIS: "JUDGING"}))
    assert mm.update(o(250, **{T.T_OCCUPANCY_BASIS: "LATCHED_OCCUPIED"}))[0] == "AWAY"   # 60 s 전 — 아직 판단하지 않는다
    assert mm.update(o(261, **{T.T_OCCUPANCY_BASIS: "LATCHED_OCCUPIED"})) == ("STUDY", "away_release")   # 재실 확정 → 고르기 전 모드로
    assert mm.update(o(400))[0] == "STUDY"                       # 같은 선택이 계속 들어와도 다시 외출로 가지 않는다
    mm.update(parse_inbox(500, inbox(**{T.C_MODE: "NORMAL"})))
    assert mm.update(o(510))[0] == "AWAY"                        # 새로 고르면 다시 외출


def test_manual_away_stays_when_person_left(params):
    mm = ModeManager(params)
    mm.away_auto = False                                         # 자동 외출 경로와 분리해 수동 경로만 본다
    o = lambda t, **kw: parse_inbox(t, inbox(**{T.C_MODE: "AWAY", **kw}))
    mm.update(o(0))
    mm.update(o(100, **{T.S_DOOR_CONTACT: True}))
    mm.update(o(108, **{T.S_DOOR_CONTACT: False, T.T_OCCUPANCY_BASIS: "JUDGING"}))
    assert mm.update(o(170, **{T.S_OCCUPANT_ZONE: "room", T.T_OCCUPANCY_BASIS: "JUDGING"}))[0] == "AWAY"   # 판정 창 — 위치는 'room' 이어도 증거 없음 → 유지 (H302)
    assert mm.update(o(400, **{T.S_OCCUPANT_ZONE: "room"}))[0] == "AWAY"   # 출입 없이 감지만 — 해제하지 않는다


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
    assert st["pm25 <= 35 within 1200 after cooking_end"] == C.PASS     # 외기 오염 중 열 꺼진 뒤 후드 재예측
    assert p.status == C.PASS, [(c.status, c.text, c.detail) for c in p.criteria]
    a = next(r for r in res if r.run.baseline == "A")
    assert p.metrics["pm25_peak"] < a.metrics["pm25_peak"]


def test_b6_proposed_passes(tmp_path):
    res = run_batch(["B6"], baselines=["proposed"], reps=1, out_dir=tmp_path, progress=lambda *_: None)
    assert res[0].status == C.PASS, [(c.status, c.text, c.detail) for c in res[0].criteria]


# ---- 쾌적 사다리 (docs/06 §4) -------------------------------------------------------------


def _weather(t_out, rh_out, rain=False):
    return json.dumps({"raining": rain, "outdoor_temp_c": t_out, "outdoor_rh_pct": rh_out})


def test_cooling_ladder_skips_window_when_outside_hotter_and_relaxes_ac(params):
    c = _ctrl(params)
    out = c.step(14 * 3600, inbox(**{T.S_TEMPERATURE: 31.0, T.S_HUMIDITY: 55.0, T.S_ILLUMINANCE: 600.0,
                                     T.S_WEATHER: _weather(33.0, 50.0)}))
    ac = json.loads(out[T.C_AC])
    assert out[T.C_WINDOW_OPEN_RATIO] == 0.0
    assert out[T.C_BLIND_ANGLE] == params.get("setpoints.blind_shade_angle_deg")
    assert out[T.C_CEILING_FAN] > 0
    assert ac["power"] and ac["mode"] == "cool"
    assert ac["setpoint"] == 26.0 + params.get("interaction_rules.I5_ceiling_fan_setpoint_relax_c")


def test_cooling_ladder_prefers_free_cooling_then_escalates(params):
    c = _ctrl(params)
    hot = {T.S_TEMPERATURE: 29.5, T.S_WEATHER: _weather(24.0, 60.0)}
    out = c.step(0, inbox(**hot))
    assert out[T.C_WINDOW_OPEN_RATIO] > 0.0 and not json.loads(out[T.C_AC])["power"]
    out = c.step(params.get("comfort_ladders.escalate_to_ac_after_s") + 1, inbox(**hot))
    assert json.loads(out[T.C_AC])["power"]                          # 무료 냉방 부족 → 승격


def test_humid_outside_blocks_vent_cooling_and_uses_ac(params):
    c = _ctrl(params)
    out = c.step(0, inbox(**{T.S_TEMPERATURE: 31.0, T.S_HUMIDITY: 78.0, T.S_WEATHER: _weather(29.0, 95.0, True)}))
    assert out[T.C_FAN_RPM] == 0.0                                   # I10 — 배기로 습기를 들이지 않는다
    assert json.loads(out[T.C_AC])["power"]


def test_humidify_cap_extension_by_ceiling_fan_reverse(params):
    c = _ctrl(params)
    out = c.step(0, inbox(**{T.S_TEMPERATURE: 21.0, T.S_HUMIDITY: 30.0, T.S_WEATHER: _weather(-5.0, 70.0)}))
    assert out[T.C_HUMIDIFIER] is True
    assert out[T.C_CEILING_FAN] == -1                                # I4 상한 확장
    assert out[T.C_DEHUMIDIFIER] is False                            # I1


def test_away_dehumidifies_with_dehumidifier_not_ac(params):
    c = _ctrl(params)
    out = c.step(0, inbox(**{T.C_MODE: "AWAY", T.S_OCCUPANCY: False, T.S_TEMPERATURE: 25.0,
                             T.S_HUMIDITY: 72.0, T.S_WEATHER: _weather(24.0, 90.0)}))
    assert out[T.C_DEHUMIDIFIER] is True
    assert not json.loads(out[T.C_AC])["power"]
    assert out[T.C_WINDOW_OPEN_RATIO] == 0.0


def test_hysteresis_cuts_actuations_vs_baseline_b(tmp_path):
    """지표 #8 — 같은 제어기에서 히스테리시스만 뺀 B 대비 장치 전환이 50 % 이상 줄어야 한다 (C11 공부 · 기본 환기 40 m³/h).
    v3.4.18 — C12(수면)는 블라인드가 닫혀 창문 환기가 줄면서 경계를 오가지 않게 되어 비교 대상에서 뺐다."""
    res = run_batch(["C11"], baselines=["B", "proposed"], reps=1, out_dir=tmp_path, progress=lambda *_: None)
    b = next(r for r in res if r.run.baseline == "B").metrics["actuation_count"]
    p = next(r for r in res if r.run.baseline == "proposed").metrics["actuation_count"]
    assert p <= 0.5 * b


def test_c15_priority_goal_dries_faster_within_budget(tmp_path):
    """C15 — 우선 목표(E10)가 Proposed−P 보다 빨리 말리고 온도 예산을 지킨다. (4시간 절대 목표는 결정 대기)"""
    res = run_batch(["C15"], baselines=["proposed", "proposed_np"], reps=1, out_dir=tmp_path, progress=lambda *_: None)
    p = next(r for r in res if r.run.baseline == "proposed")
    st = {c.text: c.status for c in p.criteria}
    assert st["event_entered('LAUNDRY_DRYING') within 3600 after washer_end"] == C.PASS
    assert st["laundry_dry_time_s < baseline_proposed_np.laundry_dry_time_s"] == C.PASS
    assert st["temperature <= value_at('temperature', washer_end) + 1.0 when t >= washer_end"] == C.PASS
    assert st["humidity <= 70 when t >= 1800"] == C.PASS
    assert p.status == C.PASS, [(c.status, c.text, c.detail) for c in p.criteria]


def test_baseline_b_has_no_hysteresis(params):
    b = SmartHomeController(params)
    b.reset({"baseline": "B"})
    assert b.modes.hysteresis_s == 0.0
    assert b.rules.ladders._band("cooling_off_band_c") == 0.0


@pytest.mark.parametrize("sid", ["B8", "B9", "C1", "C5", "C6", "C8", "C10", "C11", "C12", "C13", "C14", "C17", "C18", "C19",
                                 "X1", "X5", "X6", "X8", "B10", "B11", "X3", "X7", "C16", "C4", "C7"])
def test_comfort_scenarios_pass(sid, tmp_path):
    # baseline_A.* 비교 판정이 있는 시나리오는 A 도 함께 돌린다 (없으면 PENDING)
    res = run_batch([sid], baselines=["A", "B", "proposed"], reps=1, out_dir=tmp_path, progress=lambda *_: None)
    p = next(r for r in res if r.run.baseline == "proposed")
    assert p.status == C.PASS, [(c.status, c.text, c.detail) for c in p.criteria]


def test_schedule_path_and_manual_hold_until_boundary():
    import copy

    from controller.params import ControllerParams
    p0 = load_params()
    modes = copy.deepcopy(p0.modes)
    modes["schedule"]["enabled"] = True                         # 23:30 SLEEP · 07:00 NORMAL
    mm = ModeManager(ControllerParams(p0.th, modes))
    o = parse_inbox(22 * 3600, inbox(**{T.C_MODE: "AUTO"}))
    assert mm.update(o) == ("NORMAL", "schedule")
    o = parse_inbox(23 * 3600, inbox(**{T.C_MODE: "STUDY"}))       # 수동 — 다음 경계(23:30)까지 유지
    assert mm.update(o) == ("STUDY", "manual")
    o = parse_inbox(23 * 3600 + 1800 + 10, inbox(**{T.C_MODE: "STUDY"}))
    assert mm.update(o) == ("SLEEP", "schedule")


def test_user_mode_ranges_are_clamped():
    from controller.params import clamp_user_modes
    modes = {"editable_ranges": {"cooling_setpoint_c": [24.0, 28.0], "cct_k": [2700.0, 6500.0]},
             "modes": {"NORMAL": {"cooling_setpoint_c": 20.0, "lighting": {"cct_k": 9000.0}},
                       "AWAY": {"cooling_setpoint_c": None, "humidity_range_pct": [None, 70.0]}}}
    changed = clamp_user_modes(modes)
    assert modes["modes"]["NORMAL"]["cooling_setpoint_c"] == 24.0 and modes["modes"]["NORMAL"]["lighting"]["cct_k"] == 6500.0
    assert modes["modes"]["AWAY"]["humidity_range_pct"] == [None, 70.0] and len(changed) == 2


def test_manual_control_state_issues_no_actuator_commands():
    c = SmartHomeController()
    c.reset({"baseline": "proposed", "scenario": {}})
    out = c.step(50000.0, inbox(**{T.C_MODE: "MANUAL", T.S_TEMPERATURE: 30.0}))
    assert not any(tp in T.COMMAND_TOPICS for tp in out)
    assert json.loads(out[T.T_LIVING_MODE])["state"] == "MANUAL"
    # 수동 조작 중 끼임 → 거부 사유 알림 (X4) · 반복 끼임 잠금
    out = c.step(50001.0, inbox(**{T.C_MODE: "MANUAL", T.T_SAFETY_STATE: "PINCH_REVERSE"}))
    assert [a["code"] for a in json.loads(out[T.T_ALERTS])] == ["W_PINCH"]
    out = c.step(50002.0, inbox(**{T.C_MODE: "MANUAL", T.T_SAFETY_STATE: "LOCKED_CLOSING|SAFETY_HOLD"}))
    assert [a["code"] for a in json.loads(out[T.T_ALERTS])] == ["W_PINCH", "W_LOCK"]


def test_blind_and_window_chosen_together_by_net_heat_and_safety_hold_redistributes():
    """v3.4.18 — '차광 먼저 → 창문' 고정 순서 없음. 창문을 냉방에 쓰면 블라인드가 바람을 막는 손실까지 계산해 각도를 고른다."""
    c = SmartHomeController()
    c.reset({"baseline": "proposed", "scenario": {}})
    # 맑은 날 강한 해 — 센서 2100 lux ≈ 바깥 7만 lux (v3.4.21 주광 모델: 센서/바깥 0.029 · 블라인드 열림)
    hot = dict(**{T.S_TEMPERATURE: 29.0, T.S_ILLUMINANCE: 2100.0,
                  T.S_WEATHER: json.dumps({"raining": False, "sky": "clear", "outdoor_temp_c": 24.0, "outdoor_rh_pct": 50.0})})
    out = c.step(50000.0, inbox(**hot, **{T.T_BLIND_ANGLE: 0.0}))
    assert out[T.C_WINDOW_OPEN_RATIO] > 0.3                                           # 블라인드를 기다리지 않는다
    nets = c.rules.ladders._blind_choice.last
    glare = c.rules.lighting._glare_deg or 0.0                                        # 눈부심 차광보다 덜 가리지는 않는다
    assert out[T.C_BLIND_ANGLE] == max(min(nets, key=lambda d: nets[d]["net_w"]), glare)  # 순 열량이 가장 작은 각도
    assert nets[75.0]["vent_w"] < nets[0.0]["vent_w"]                                 # 닫을수록 환기 냉방을 잃는다
    out = c.step(50002.0, inbox(**hot, **{T.T_BLIND_ANGLE: out[T.C_BLIND_ANGLE], T.T_SAFETY_STATE: "SAFETY_HOLD"}))
    assert any("창문 불가 safety" in r for r in c.reasons())                         # 창문 불가 → 배기 + 흡기로


def test_blind_fully_shades_when_window_cannot_cool():
    """바깥이 더 더우면 창문 환기 냉방이 없다 → 일사열을 가장 많이 막는 완전 차광."""
    c = SmartHomeController()
    c.reset({"baseline": "proposed", "scenario": {}})
    hot = dict(**{T.S_TEMPERATURE: 29.0, T.S_ILLUMINANCE: 2100.0,
                  T.S_WEATHER: json.dumps({"raining": False, "sky": "clear", "outdoor_temp_c": 32.0, "outdoor_rh_pct": 50.0})})
    out = c.step(50000.0, inbox(**hot, **{T.T_BLIND_ANGLE: 0.0}))
    assert out[T.C_BLIND_ANGLE] >= 70 and out.get(T.C_WINDOW_OPEN_RATIO, 0.0) <= 0.15
