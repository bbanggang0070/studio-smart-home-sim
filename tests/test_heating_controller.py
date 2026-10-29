"""난방 확장 트랙 — 제어기 난방 사다리 · 규칙 · 이벤트 단위 테스트 (docs/14 §4 · controller/heating.py)."""

import json

import pytest

from controller.smart_home import SmartHomeController
from interfaces import topics as T


def inbox(temp=18.0, out=0.0, mode="NORMAL", occupied=True, **kw):
    base = {
        T.S_TEMPERATURE: temp, T.S_HUMIDITY: 40.0, T.S_PM25: 10.0, T.S_HOOD_TEMPERATURE: temp,
        T.S_OCCUPANCY: occupied, T.S_OCCUPANT_ZONE: "room" if occupied else "none", T.S_OUTDOOR_PM_GRADE: "good",
        T.S_APPLIANCE_POWER: "{}", T.C_MODE: mode, T.S_ILLUMINANCE: 300.0,
        T.S_WEATHER: json.dumps({"raining": False, "outdoor_temp_c": out, "outdoor_rh_pct": 50.0, "sky": "overcast"}),
    }
    base.update(kw)
    return base


def ctrl(profile="full_heating", **sc):
    c = SmartHomeController()
    c.reset({"baseline": "proposed", "scenario": {"appliance_profile": profile, **sc}})
    return c


def boiler(out):
    return json.loads(out[T.C_BOILER]) if T.C_BOILER in out else None


def test_v129_profile_has_no_boiler():
    c = ctrl(profile="full")
    out = c.step(8 * 3600.0, inbox())
    assert T.C_BOILER not in out


@pytest.mark.parametrize("mode,sp", [("NORMAL", 21.0), ("STUDY", 21.0), ("SLEEP", 19.0)])
def test_mode_targets(mode, sp):
    b = boiler(ctrl().step(8 * 3600.0, inbox(mode=mode)))
    assert b["power"] and b["setpoint"] == pytest.approx(sp)


def test_away_setback():
    c = ctrl()
    for t in range(0, 600, 60):                       # 외출 모드는 사용자 지정
        out = c.step(8 * 3600.0 + t, inbox(mode="AWAY", occupied=False))
    assert boiler(out)["setpoint"] == pytest.approx(16.0)


def test_summer_off():
    b = boiler(ctrl().step(14 * 3600.0, inbox(temp=26.0, out=28.0)))
    assert b is not None and not b["power"]


def test_i11_window_open_pauses_heating():
    b = boiler(ctrl().step(8 * 3600.0, inbox(**{T.T_WINDOW_OPEN_RATIO: 0.3})))
    assert b["setpoint"] == pytest.approx(10.0)


def test_frost_force_and_alert_when_away_off():
    c = ctrl()
    c.p.modes["energy"]["away_heating_strategy"] = "off"
    out = c.step(3 * 3600.0, inbox(temp=11.0, out=-12.0, mode="AWAY", occupied=False))
    assert boiler(out)["setpoint"] == pytest.approx(12.0)
    assert "FROST_RISK" in json.loads(out[T.T_ACTIVE_EVENTS])
    assert any(a["code"] == "H_FROST" for a in json.loads(out[T.T_ALERTS]))


def test_deadband_limits_heating_below_cooling():
    c = ctrl()
    c.p.mode("NORMAL")["cooling_setpoint_c"] = 22.0
    sp, why = c.rules.heating.target("NORMAL", "NORMAL")
    assert sp == pytest.approx(20.0) and "데드밴드" in why
    c.p.mode("NORMAL")["cooling_setpoint_c"] = 26.0


def test_manual_thermostat_is_respected():
    c = ctrl()
    out = c.step(8 * 3600.0, inbox(**{T.T_BOILER: json.dumps({"power": True, "setpoint": 24.0, "manual": True})}))
    assert T.C_BOILER not in out
    out = c.step(8 * 3600.0 + 600, inbox(**{T.T_BOILER: json.dumps({"power": True, "setpoint": 24.0, "manual": False})}))
    assert T.C_BOILER not in out                       # 30분 보류 중
    out = c.step(8 * 3600.0 + 1900, inbox(**{T.T_BOILER: json.dumps({"power": True, "setpoint": 24.0, "manual": False})}))
    assert boiler(out)["setpoint"] == pytest.approx(21.0)


def test_boiler_fault_alert():
    c = ctrl()
    st = json.dumps({"power": True, "setpoint": 21.0, "manual": False})
    alerts = []
    for t in range(0, 2000, 10):
        out = c.step(8 * 3600.0 + t, inbox(temp=17.0, **{T.T_BOILER: st, T.S_APPLIANCE_POWER: json.dumps({"boiler": 5.0})}))
        alerts += json.loads(out.get(T.T_ALERTS, "[]"))
    assert any(a["code"] == "H_BOILER_FAULT" for a in alerts)


def test_no_fault_when_boiler_burns():
    c = ctrl()
    st = json.dumps({"power": True, "setpoint": 21.0, "manual": False})
    alerts = []
    for t in range(0, 2000, 10):
        out = c.step(8 * 3600.0 + t, inbox(temp=17.0, **{T.T_BOILER: st, T.S_APPLIANCE_POWER: json.dumps({"boiler": 90.0})}))
        alerts += json.loads(out.get(T.T_ALERTS, "[]"))
    assert not any(a["code"] == "H_BOILER_FAULT" for a in alerts)


def test_i12_no_humidify_while_warming_up():
    c = ctrl()
    for t in range(0, 180, 10):                       # 가습 진입은 60 s 확인 뒤 — 그 뒤에도 I12 가 막는다
        out = c.step(19 * 3600.0 + t, inbox(temp=17.0, **{T.S_HUMIDITY: 30.0}))
    assert out.get(T.C_HUMIDIFIER) is False
    assert any("I12" in r for r in c.reasons())


def test_cooking_keeps_heating_target():
    """I13('요리 중 올리지 않음')은 삭제 — 후드 · 급기 손실이 커서 오히려 더 식었다 (H5 개발). 요리 중에도 목표 유지."""
    c = ctrl()
    out = c.step(19 * 3600.0, inbox(temp=20.0, **{T.C_ACTIVITY: "cooking", T.S_APPLIANCE_POWER: json.dumps({"cooktop": 1500.0})}))
    assert boiler(out)["setpoint"] == pytest.approx(21.0)


def test_away_off_uses_frost_margin():
    c = ctrl()
    c.p.modes["energy"]["away_heating_strategy"] = "off"
    sp, _ = c.rules.heating.target("AWAY", "NORMAL")
    assert sp == pytest.approx(12.0)


# ---- v1.31-H C1 · C2 · C3 ------------------------------------------------------------------------

from controller.heating import HeatingLadder  # noqa: E402
from controller.params import load_params  # noqa: E402
from controller.signals import parse_inbox  # noqa: E402


class _Arrive:
    """귀가 예측 고정 — 18:00 (분위와 무관하게 같은 값)."""
    def _arrival_samples(self, tod):
        import numpy as np
        return np.full(50, 18 * 3600.0)


def _obs(t, temp, out=-5.0, **kw):
    return parse_inbox(t, inbox(temp=temp, out=out, occupied=False, **kw))


def test_preheat_skipped_when_room_still_warm():
    h = HeatingLadder(load_params())
    sp, why = h._preheat(_obs(17 * 3600.0, temp=20.8), "AWAY", "NORMAL", {}, _Arrive(), 16.0, "셋백")
    assert sp == 16.0                                     # 21 − 20.8 = 0.2 ≤ 0.5 — 데울 필요 없음


def test_preheat_lead_scales_with_deficit():
    p = load_params()
    h = HeatingLadder(p)
    # 부족 2 K × 75 분/K = 150분 → 15:30 부터
    sp, _ = h._preheat(_obs(15 * 3600.0, temp=19.0), "AWAY", "NORMAL", {}, _Arrive(), 16.0, "셋백")
    assert sp == 16.0
    h2 = HeatingLadder(p)
    sp, _ = h2._preheat(_obs(15.6 * 3600.0, temp=19.0), "AWAY", "NORMAL", {}, _Arrive(), 16.0, "셋백")
    assert sp == 21.0


def test_preheat_not_repeated_after_missed_arrival():
    h = HeatingLadder(load_params())
    ev = {}
    t0 = 16 * 3600.0
    h._preheat(_obs(t0, temp=18.0), "AWAY", "NORMAL", ev, _Arrive(), 16.0, "셋백")
    assert h._pre_started is not None
    # 귀가하지 않은 채 상한 + 시간 초과가 지나면 그만 · 다음 날 같은 시각에도 다시 하지 않는다
    sp, _ = h._preheat(_obs(t0 + 5 * 3600.0, temp=21.0), "AWAY", "NORMAL", ev, _Arrive(), 16.0, "셋백")
    assert sp == 16.0 and h._pre_missed
    sp, _ = h._preheat(_obs(t0 + 86400.0 - 3600, temp=18.0), "AWAY", "NORMAL", ev, _Arrive(), 16.0, "셋백")
    assert sp == 16.0


def test_preheat_skipped_on_long_trip():
    h = HeatingLadder(load_params())
    h._preheat(_obs(10 * 3600.0, temp=20.0), "AWAY", "NORMAL", {}, _Arrive(), 16.0, "셋백")     # 외출 시작 기록
    sp, _ = h._preheat(_obs(10 * 3600.0 + 25 * 3600.0 + 6.5 * 3600, temp=17.0), "AWAY", "NORMAL", {}, _Arrive(), 16.0, "셋백")
    assert sp == 16.0                                     # 24 h 넘음 — 여행


def test_night_blind_only_when_condensation_safe():
    c = ctrl()
    dry = c.step(22 * 3600.0, inbox(temp=19.0, out=0.0, **{T.S_HUMIDITY: 30.0}))
    assert any("사다리 2" in r for r in c.reasons())
    c = ctrl()
    wet = c.step(22 * 3600.0, inbox(temp=19.0, out=-12.0, **{T.S_HUMIDITY: 55.0}))
    assert not any("사다리 2" in r for r in c.reasons())


# ---- [v1.32-H] C5 – C8 (docs/14 §16) ----

def _run(c, t0, n, step=10, **kw):
    out, alerts = {}, []
    for t in range(0, n, step):
        out = c.step(t0 + t, inbox(**kw))
        alerts += json.loads(out.get(T.T_ALERTS, "[]"))
    return out, alerts


def test_c5_no_winter_ceiling_fan_rung():
    """바닥난방 중 실링팬 역회전 사다리는 끈다 — v1.31-H 변형(proposed_v131)은 켠다."""
    from harness.controllers import make_controller

    out, _ = _run(ctrl(), 8 * 3600.0, 120, temp=19.0)
    assert out.get(T.C_CEILING_FAN, 0) == 0 and not any("사다리 3" in r for r in ctrl().reasons())
    old = make_controller("variant:proposed_v131")
    old.reset({"baseline": "proposed", "scenario": {"appliance_profile": "full_heating"}})
    out, _ = _run(old, 8 * 3600.0, 120, temp=19.0)
    assert out.get(T.C_CEILING_FAN) == -1


def test_c8_fault_detected_on_small_deficit():
    """설정 − 0.6 °C 에서 대기 전력만 15분 → 알림 (전: 1 °C · 30분이라 못 잡았다) · 설정 − 0.4 °C 면 알리지 않는다."""
    st = json.dumps({"power": True, "setpoint": 21.0, "manual": False})
    kw = {T.T_BOILER: st, T.S_APPLIANCE_POWER: json.dumps({"boiler": 5.0})}
    _, a = _run(ctrl(), 8 * 3600.0, 1000, temp=20.4, **kw)
    assert any(x["code"] == "H_BOILER_FAULT" for x in a)
    _, a = _run(ctrl(), 8 * 3600.0, 1000, temp=20.6, **kw)
    assert not any(x["code"] == "H_BOILER_FAULT" for x in a)


def test_c6_heating_humidify_stops_at_45():
    """난방 중 가습은 하한 40 + 5 = 45 % 에서 멈춘다 — 보일러 없는 v1.29 프로파일은 상한 − 3 %p 까지 계속.
    습도는 2분에 1 %p 씩 천천히 올린다 (한 번에 올리면 샤워 감지 E3 가 된다)."""
    for prof, expect_on in (("full_heating", False), ("full", True)):
        c = ctrl(profile=prof)
        kw = {T.T_BLIND_ANGLE: 0.0}
        t = 14 * 3600.0
        _run(c, t, 200, temp=21.0, out=5.0, **{T.S_HUMIDITY: 36.0}, **kw)
        t += 200
        for rh in range(37, 47):
            out, _ = _run(c, t, 120, temp=21.0, out=5.0, **{T.S_HUMIDITY: float(rh)}, **kw)
            t += 120
        assert bool(out.get(T.C_HUMIDIFIER)) is expect_on, (prof, [r for r in c.reasons() if "humid" in r])


def test_c7_condensation_costly_means_only_while_critical():
    """E2 위험 뒤 블라인드를 열어 지금 여유가 위험 기준 위면 난방 중엔 제습을 멈춘다 · v1.29 프로파일은 래치 유지."""
    for prof, expect_dehum in (("full_heating", False), ("full", True)):
        c = ctrl(profile=prof)
        _run(c, 7 * 3600.0, 60, temp=20.0, out=-10.0, **{T.S_HUMIDITY: 50.0, T.T_BLIND_ANGLE: 75.0})
        out, _ = _run(c, 7 * 3600.0 + 60, 60, temp=20.0, out=-10.0, **{T.S_HUMIDITY: 50.0, T.T_BLIND_ANGLE: 0.0})
        assert bool(out.get(T.C_DEHUMIDIFIER)) is expect_dehum, prof


def test_c8_fault_detected_even_if_room_warms_from_mass():
    """[C8′] 고장 중에도 축열 · 일사로 실내가 오를 수 있다 — 플러그 전력이 대기 수준이면 알린다."""
    c = ctrl()
    st = json.dumps({"power": True, "setpoint": 21.0, "manual": False})
    kw = {T.T_BOILER: st, T.S_APPLIANCE_POWER: json.dumps({"boiler": 5.0})}
    alerts = []
    for k, t in enumerate(range(0, 1200, 10)):
        out = c.step(8 * 3600.0 + t, inbox(temp=19.0 + min(1.0, k * 0.02), **kw))
        alerts += json.loads(out.get(T.T_ALERTS, "[]"))
    assert any(a["code"] == "H_BOILER_FAULT" for a in alerts)


# ---- [v1.33-H] C9 달력 · 여행 판정 (docs/14 §17) ----

def _wobs(t, temp, wd0):
    o = _obs(t, temp)
    o.weekday = (wd0 + int(t // 86400.0)) % 7
    return o


def _away_weekend_then_monday(h, wd0):
    """토 08:00 출발 (시작 = 토 0시 · wd0 = 5) → 토 · 일 저녁을 지나 월 저녁 예측 귀가. 월요일 17:00 의 설정을 돌려준다."""
    ev = {}
    for t in range(int(8 * 3600), int(2 * 86400 + 17 * 3600) + 1, 600):
        sp, why = h._preheat(_wobs(float(t), 17.0, wd0), "AWAY", "NORMAL", ev, _Arrive(), 16.0, "셋백")
    return sp, why


def test_c9_monday_preheat_after_weekend_away():
    """주말 외박(60 h) 뒤 월요일 예측 귀가 전에 데운다 — 요일을 모르면(v1.32-H) 24 h 초과 = 여행으로 데우지 않는다."""
    sp, why = _away_weekend_then_monday(HeatingLadder(load_params()), 5)
    assert sp == 21.0, why
    h = HeatingLadder(load_params())
    ev = {}
    for t in range(int(8 * 3600), int(2 * 86400 + 17 * 3600) + 1, 600):
        sp, _ = h._preheat(_obs(float(t), 17.0), "AWAY", "NORMAL", ev, _Arrive(), 16.0, "셋백")   # weekday = None
    assert sp == 16.0


def test_c9_workday_missed_arrival_is_trip():
    """출근일(수)에 예측 귀가를 놓치면 여행 — 다음 날(목) 저녁에도 데우지 않는다 (HH207 그대로)."""
    h = HeatingLadder(load_params())
    ev = {}
    for t in range(int(8 * 3600), int(86400 + 17 * 3600) + 1, 600):
        sp, _ = h._preheat(_wobs(float(t), 17.0, 2), "AWAY", "NORMAL", ev, _Arrive(), 16.0, "셋백")
    assert h._pre_missed and sp == 16.0


def test_c9_controller_counts_weekday():
    c = ctrl(initial={"weekday": 4})                     # 금 0시 시작
    c.step(10.0, inbox())
    assert c._weekday0 == 4
    from controller.signals import parse_inbox as _p
    o = _p(3 * 86400.0 + 10.0, inbox())
    assert (c._weekday0 + int(o.now_s // 86400)) % 7 == 0   # 3일 뒤 = 월
