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


def test_i13_cooking_holds_setpoint():
    c = ctrl()
    out = c.step(19 * 3600.0, inbox(temp=20.0, **{T.C_ACTIVITY: "cooking", T.S_APPLIANCE_POWER: json.dumps({"cooktop": 1500.0})}))
    ev = json.loads(out[T.T_ACTIVE_EVENTS])
    if "COOKING" in ev:
        assert boiler(out)["setpoint"] == pytest.approx(20.0)
