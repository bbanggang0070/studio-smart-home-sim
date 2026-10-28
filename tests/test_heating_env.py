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
