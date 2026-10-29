"""난방 확장 트랙 — 참값 온수 바닥난방 모델 단위 테스트 (docs/14 §3 · heating.mode = hydronic)."""

import math

import pytest

from env_model.config import load_config
from env_model.room import ActuatorCommands, BoilerCommand, ExternalConditions, RoomModel


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def hyd(cfg):
    return cfg.with_overrides({"heating.mode": "hydronic"})


def run(model, act, ext, minutes):
    obs = None
    for _ in range(minutes):
        obs = model.step(60.0, act, ext)
    return obs


def test_boundary_mode_is_default_and_unchanged(cfg):
    """기본은 경계 조건 — 보일러 · 바닥 출력이 없고 A13 난방이 그대로 동작한다 (v1.29 재현)."""
    assert cfg.get("heating.mode") == "boundary"
    r = RoomModel.from_conditions(cfg, 18.0, 40.0, 10.0, 600.0)
    o = run(r, ActuatorCommands(), ExternalConditions(outdoor_temp_c=-5.0, outdoor_rh_pct=60.0, heating_setpoint_c=21.0), 60)
    assert "boiler" not in o["appliance_power_w"] and "floor_temp_c" not in o and "boiler_gas" not in o["energy_wh"]
    assert o["heating_w"] > 0


def test_hydronic_holds_setpoint_in_cold(hyd):
    r = RoomModel.from_conditions(hyd, 18.0, 40.0, 10.0, 600.0)
    act = ActuatorCommands(boiler=BoilerCommand(power=True, setpoint_c=21.0))
    ext = ExternalConditions(outdoor_temp_c=-10.0, outdoor_rh_pct=60.0)
    run(r, act, ext, 12 * 60)
    temps = [run(r, act, ext, 1)["temperature_c"] for _ in range(12 * 60)]
    assert 20.5 < sum(temps) / len(temps) < 21.5
    assert min(temps) > 20.0 and max(temps) < 22.0


def test_power_off_never_burns_and_room_cools(hyd):
    r = RoomModel.from_conditions(hyd, 21.0, 40.0, 10.0, 600.0)
    act = ActuatorCommands(boiler=BoilerCommand(power=False, setpoint_c=25.0))
    o = run(r, act, ExternalConditions(outdoor_temp_c=-5.0, outdoor_rh_pct=60.0), 6 * 60)
    assert not o["boiler_burning"] and o["energy_wh"].get("boiler_gas", 0.0) == 0.0
    assert o["temperature_c"] < 21.0
    assert o["appliance_power_w"]["boiler"] == hyd.get("heating.hydronic.boiler_electric_standby_w")


def test_boiler_min_burn_time(hyd):
    """설정을 바로 낮춰도 최소 연소 시간 전에는 끄지 않는다 (보일러 자체 보호)."""
    r = RoomModel.from_conditions(hyd, 15.0, 40.0, 10.0, 600.0)
    ext = ExternalConditions(outdoor_temp_c=0.0, outdoor_rh_pct=60.0)
    o = r.step(10.0, ActuatorCommands(boiler=BoilerCommand(power=True, setpoint_c=25.0)), ext)
    assert o["boiler_burning"]
    o = r.step(60.0, ActuatorCommands(boiler=BoilerCommand(power=True, setpoint_c=5.0)), ext)
    assert o["boiler_burning"]                                    # 70 s < 최소 연소 180 s
    o = r.step(150.0, ActuatorCommands(boiler=BoilerCommand(power=True, setpoint_c=5.0)), ext)
    assert not o["boiler_burning"]


def test_floor_heat_and_gas_balance(hyd):
    """연소 중 바닥이 실내보다 따뜻해지고, 가스 에너지 = 배관 열 / 효율 (적분 일치)."""
    r = RoomModel.from_conditions(hyd, 18.0, 40.0, 10.0, 600.0)
    act = ActuatorCommands(boiler=BoilerCommand(power=True, setpoint_c=24.0))
    o = run(r, act, ExternalConditions(outdoor_temp_c=0.0, outdoor_rh_pct=60.0), 120)
    assert o["boiler_burning"] and o["floor_temp_c"] > o["temperature_c"] + 1.0 and o["heating_w"] > 0
    h = "heating.hydronic."
    q_pipe = hyd.get(h + "pipe_conductance_w_per_k") * (o["supply_temp_c"] - o["floor_temp_c"])
    assert o["boiler_gas_w"] == pytest.approx(q_pipe / hyd.get(h + "boiler_efficiency"), rel=0.05)


def test_en1264_sign(hyd):
    """바닥이 실내보다 차가우면 열이 바닥으로 간다 (부호 유지)."""
    r = RoomModel.from_conditions(hyd, 22.0, 40.0, 10.0, 600.0)
    r.state.floor_temp_c = 19.0
    r.state.supply_temp_c = 19.0
    o = r.step(5.0, ActuatorCommands(), ExternalConditions(outdoor_temp_c=10.0, outdoor_rh_pct=60.0))
    c, n = hyd.get("heating.hydronic.en1264_coefficient"), hyd.get("heating.hydronic.en1264_exponent")
    assert o["heating_w"] < 0
    assert math.isclose(abs(o["heating_w"]), hyd.get("heating.hydronic.floor_area_m2") * c * 3.0 ** n, rel_tol=0.05)


def _steady_scenario(lux: float, fault: bool) -> tuple:
    """thermal_steady 시나리오 최소형 — 겨울 · 보일러 21 °C · 실내 21 °C 에서 시작."""
    from harness.fast_world import make_model

    sc = {"id": "T", "duration_s": 3600, "environment_overrides": {},
          "initial": {"thermal_steady": True, "user_mode": "NORMAL", "temperature_c": 21.0, "humidity_pct": 38.0,
                      "co2_ppm": 800.0, "pm25_ugm3": 8.0, "illuminance_lux": 300.0, "occupancy": True, "occupant_zone": "room",
                      "time_of_day": "11:00", "window_open_ratio": 0.0, "blind_angle_deg": 0.0,
                      "appliances": {"purifier_level": 0, "boiler": {"power": True, "setpoint": 21.0}}},
          "external": {"weather": "clear", "outdoor_pm25_ugm3": 12.0, "outdoor_temp_c": 2.0, "outdoor_rh_pct": 40.0,
                       "outdoor_illuminance_lux": lux}}
    return sc, {"heating.mode": "hydronic", "heating.hydronic.fault_no_ignition": fault}


def test_steady_start_not_overheated_by_noon_sun(cfg):
    """[v1.31-H 하네스 보정] 한낮 일사를 72 h 고정하지 않는다 — 평형 구조체가 실내보다 크게 뜨겁지 않다 (HH307 교훈)."""
    from harness.fast_world import make_model

    sc, ov = _steady_scenario(55000.0, False)
    m = make_model(cfg.with_overrides(ov), sc)
    assert m.state.mass_temp_c - 21.0 < 1.5


def test_steady_start_without_fault_preapplied(cfg):
    """[v1.31-H 하네스 보정] 고장은 t = 0 에 시작 — 평형 동안에는 정상 보일러로 맞춘다 (HH308 교훈)."""
    from harness.fast_world import make_model

    sc, ov = _steady_scenario(0.0, True)
    m = make_model(cfg.with_overrides(ov), sc)
    assert abs(m.state.mass_temp_c - 21.0) < 1.5
    assert m.cfg.get("heating.hydronic.fault_no_ignition") is True      # 본 실행에는 고장이 그대로


def test_boiler_fault_alert_delay_metric():
    """[v1.32-H M6] 지연 = 첫 점화 요구 → H_BOILER_FAULT 알림 · 요구 없음 NaN · 알림 없음 inf."""
    import json

    import numpy as np
    import pandas as pd

    from harness.criteria import _heating_metrics
    from interfaces import topics as T

    t = np.arange(0.0, 5000.0, 100.0)
    al = [json.dumps([{"code": "H_BOILER_FAULT"}]) if x >= 3000 else "[]" for x in t]
    base = {"time_s": t, "truth.temperature_c": 20.0, "truth.boiler_burning": False, "energy_wh.boiler_gas": 0.0}
    df = pd.DataFrame({**base, "truth.boiler_call": t >= 1000, T.T_ALERTS: al})
    m = _heating_metrics(df, t, 100.0, {}, np.ones(len(t)))
    assert m["boiler_fault_alert_delay_s"] == pytest.approx(2000.0)
    df = pd.DataFrame({**base, "truth.boiler_call": t >= 1000, T.T_ALERTS: "[]"})
    assert math.isinf(_heating_metrics(df, t, 100.0, {}, np.ones(len(t)))["boiler_fault_alert_delay_s"])
    df = pd.DataFrame({**base, "truth.boiler_call": False, T.T_ALERTS: "[]"})
    assert math.isnan(_heating_metrics(df, t, 100.0, {}, np.ones(len(t)))["boiler_fault_alert_delay_s"])
