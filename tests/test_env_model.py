"""환경 참값 모델 검증 — 문서의 수치 예시 · W08 완료 기준(DoD)을 그대로 옮긴 테스트."""

import math

import pytest

from env_model import (
    AcCommand,
    ActuatorCommands,
    ExternalConditions,
    Occupancy,
    RoomModel,
    SourceRates,
    load_config,
)
from env_model import condensation, psychro


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def run(model, seconds, act, ext, src=None, occ=None, dt=1.0):
    obs = None
    for _ in range(int(seconds / dt)):
        obs = model.step(dt, act, ext, src, occ)
    return obs


# ---- docs/06 §5.5 결로 계산 예시 ------------------------------------------------


@pytest.mark.parametrize(
    "blind_deg, fan, expected",
    [(0.0, 0, 1.6), (90.0, 0, -1.3), (0.0, -1, 3.0)],
    ids=["기본", "블라인드 닫힘", "실링팬 역회전"],
)
def test_dew_margin_example(cfg, blind_deg, fan, expected):
    """실내 21 °C · 외기 0 °C · RH 60 % → Δ = +1.6 / −1.3 / +3.0 °C."""
    r_si = condensation.inner_surface_resistance(cfg, blind_deg, fan)
    delta = condensation.dew_margin_c(21.0, 60.0, 0.0, r_si, cfg)
    assert delta == pytest.approx(expected, abs=0.1)


def test_dew_point_example(cfg):
    b, c = cfg.get("condensation.magnus_b"), cfg.get("condensation.magnus_c")
    assert psychro.dew_point_c(21.0, 60.0, b, c) == pytest.approx(12.9, abs=0.1)


@pytest.mark.parametrize(
    "t_out, cap_default, cap_reverse",
    [(5.0, 64, 69), (0.0, 58, 64), (-5.0, 53, 59), (-10.0, 48, 54)],
)
def test_humidify_cap_table(cfg, t_out, cap_default, cap_reverse):
    """docs/06 §5.5 가습 상한표 (실내 21 °C, 여유 2 °C) — 문서 값은 정수 반올림."""
    margin = 2.0
    r_def = condensation.inner_surface_resistance(cfg, 0.0, 0)
    r_rev = condensation.inner_surface_resistance(cfg, 0.0, -1)
    assert condensation.humidify_cap_rh_pct(21.0, t_out, r_def, margin, cfg) == pytest.approx(cap_default, abs=1.0)
    assert condensation.humidify_cap_rh_pct(21.0, t_out, r_rev, margin, cfg) == pytest.approx(cap_reverse, abs=1.0)


def test_psychro_roundtrip(cfg):
    b, c = cfg.get("condensation.magnus_b"), cfg.get("condensation.magnus_c")
    w = psychro.rh_to_abs(26.0, 55.0, b, c)
    assert psychro.abs_to_rh(26.0, w, b, c) == pytest.approx(55.0)
    # 이슬점의 포화 증기압 = 현재 증기압 (Magnus 식의 역함수 관계)
    t_d = psychro.dew_point_c(26.0, 55.0, b, c)
    assert psychro.saturation_pressure_pa(t_d, b, c) == pytest.approx(0.55 * psychro.saturation_pressure_pa(26.0, b, c))


# ---- 공기 수지 (docs/06 §5.1 · W08 v3.0 DoD) --------------------------------------


def test_hood_infiltration_37x(cfg):
    """후드 450 m³/h 단독 가동 → 틈새 유입 약 37배."""
    model = RoomModel.from_conditions(cfg, 26.0, 55.0, 12.0, 600.0)
    ext = ExternalConditions(outdoor_temp_c=24.0, outdoor_rh_pct=60.0)
    base = model.step(1.0, ActuatorCommands(), ext)["q_inf_m3h"]
    hood = model.step(1.0, ActuatorCommands(range_hood_level=2), ext)["q_inf_m3h"]
    assert base == pytest.approx(12.6)
    assert hood / base == pytest.approx(37.0, abs=0.5)


def test_window_10pct_flow_matches_base_vent(cfg):
    """창문 10 % 는 일반 모드 기본 환기(25 m³/h)를 채울 크기여야 한다 (docs/07 §3.3 수단 ①)."""
    model = RoomModel.from_conditions(cfg, 26.0, 55.0, 12.0, 600.0)
    ext = ExternalConditions(outdoor_temp_c=21.0, outdoor_rh_pct=60.0)
    q = model.step(1.0, ActuatorCommands(window_open_ratio=0.1), ext)["q_window_m3h"]
    assert 25.0 <= q <= 80.0


# ---- W08 완료 기준 — 시나리오 성립 전제 ---------------------------------------------


def test_rain_window_raises_humidity(cfg):
    """⭐ 강우 중 창문을 열면 습도가 상승한다 — C1 성립의 전제."""
    ext = ExternalConditions(outdoor_temp_c=24.0, outdoor_rh_pct=95.0)
    model = RoomModel.from_conditions(cfg, 26.0, 60.0, 12.0, 600.0)
    w0 = model.state.abs_humidity_g_m3
    obs = run(model, 600, ActuatorCommands(window_open_ratio=0.4), ext)
    assert obs["abs_humidity_g_m3"] > w0
    assert obs["humidity_pct"] > 60.0


def test_exhaust_with_closed_window_worsens_pm(cfg):
    """⭐ 창문을 닫고 배기를 최대로 → 외기 나쁨이면 실내 PM 악화 (음압 유입) — C8 전제."""
    ext = ExternalConditions(outdoor_temp_c=30.0, outdoor_rh_pct=60.0, outdoor_pm25_ugm3=52.0)
    still = RoomModel.from_conditions(cfg, 28.0, 55.0, 12.0, 600.0)
    fan = RoomModel.from_conditions(cfg, 28.0, 55.0, 12.0, 600.0)
    pm_still = run(still, 3600, ActuatorCommands(), ext)["pm25_ugm3"]
    pm_fan = run(fan, 3600, ActuatorCommands(exhaust_fan_rpm=2000.0), ext)["pm25_ugm3"]
    assert pm_fan > pm_still > 12.0


def test_filtered_intake_keeps_pm_low(cfg):
    """필터 흡기(양압)는 같은 외기에서 배기보다 실내 PM 이 낮다 — 규칙 I7 의 물리 근거."""
    ext = ExternalConditions(outdoor_temp_c=30.0, outdoor_rh_pct=60.0, outdoor_pm25_ugm3=52.0)
    exh = RoomModel.from_conditions(cfg, 28.0, 55.0, 12.0, 600.0)
    intake = RoomModel.from_conditions(cfg, 28.0, 55.0, 12.0, 600.0)
    pm_exh = run(exh, 3600, ActuatorCommands(exhaust_fan_rpm=2000.0), ext)["pm25_ugm3"]
    pm_in = run(intake, 3600, ActuatorCommands(intake_fan_rpm=2000.0), ext)["pm25_ugm3"]
    assert pm_in < pm_exh


def test_fan_moves_temperature_toward_outdoor(cfg):
    """팬 1400 rpm 인가 시 실내 온도가 외기 방향으로 단조 감소."""
    ext = ExternalConditions(outdoor_temp_c=22.0, outdoor_rh_pct=50.0)
    model = RoomModel.from_conditions(cfg, 29.0, 55.0, 12.0, 600.0)
    act = ActuatorCommands(exhaust_fan_rpm=1400.0, intake_fan_rpm=1400.0)
    temps = [run(model, 300, act, ext)["temperature_c"] for _ in range(6)]
    assert all(a > b for a, b in zip([29.0] + temps, temps))
    assert temps[-1] > 22.0


def test_fan_lowers_humidity_when_outdoor_drier(cfg):
    """팬 가동 시 습도가 하강한다 (외기가 더 건조할 때)."""
    ext = ExternalConditions(outdoor_temp_c=22.0, outdoor_rh_pct=40.0)
    model = RoomModel.from_conditions(cfg, 26.0, 70.0, 12.0, 600.0)
    obs = run(model, 1800, ActuatorCommands(exhaust_fan_rpm=1400.0, intake_fan_rpm=1400.0), ext)
    assert obs["humidity_pct"] < 70.0


def test_light_heat_raises_temperature(cfg):
    """조명 100 % → 실내 온도가 유의미하게 상승 — C4 전제."""
    ext = ExternalConditions(outdoor_temp_c=26.0, outdoor_rh_pct=50.0)
    off = RoomModel.from_conditions(cfg, 26.0, 50.0, 12.0, 600.0)
    on = RoomModel.from_conditions(cfg, 26.0, 50.0, 12.0, 600.0)
    t_off = run(off, 3600, ActuatorCommands(), ext)["temperature_c"]
    t_on = run(on, 3600, ActuatorCommands(ceiling_light_pct=100.0, desk_light_pct=100.0), ext)["temperature_c"]
    assert t_on - t_off > 0.1


def test_condensation_flag_when_cold_and_humid(cfg):
    """저온 + 고습 → 결로 여유가 경고/위험 영역으로 떨어지고 창에 물이 맺힌다 — C6 전제."""
    ext = ExternalConditions(outdoor_temp_c=-5.0, outdoor_rh_pct=70.0)
    model = RoomModel.from_conditions(cfg, 21.0, 65.0, 12.0, 600.0)
    obs = run(model, 600, ActuatorCommands(blind_angle_deg=90.0), ext, dt=5.0)
    assert obs["dew_margin_c"] < 0.5
    assert obs["condensate_g"] > 0.0


# ---- CO₂ 참값 · 기본 환기 (docs/07 §3.3) ------------------------------------------


def test_co2_steady_state_base_vent(cfg):
    """1인 착석 · 흡기 25 m³/h · 틈새 0.15 ACH → 정상상태 약 1,000 ppm (07 §3.3 설계 근거)."""
    c = cfg.with_overrides({"air_balance.base_infiltration_ach": 0.15})
    model = RoomModel.from_conditions(c, 24.0, 50.0, 12.0, 420.0)
    rpm = 25.0 / 60.0 * 2000.0
    ext = ExternalConditions(outdoor_temp_c=24.0, outdoor_rh_pct=50.0)
    obs = run(model, 8 * 3600, ActuatorCommands(intake_fan_rpm=rpm), ext, occ=Occupancy(1, "seated"), dt=10.0)
    expected = 420.0 + 18000.0 / (25.0 + 6.3)
    assert obs["co2_ppm"] == pytest.approx(expected, rel=0.02)
    assert obs["co2_ppm"] == pytest.approx(1000.0, abs=20.0)


def test_co2_rises_without_ventilation(cfg):
    """환기 없이 착석 1인 → 시간당 약 430 ppm 상승 (docs/06 §5.2)."""
    model = RoomModel.from_conditions(cfg.with_overrides({"air_balance.base_infiltration_ach": 0.0}),
                                      24.0, 50.0, 12.0, 420.0)
    ext = ExternalConditions(outdoor_temp_c=24.0, outdoor_rh_pct=50.0)
    obs = run(model, 3600, ActuatorCommands(), ext, occ=Occupancy(1, "seated"), dt=10.0)
    assert obs["co2_ppm"] - 420.0 == pytest.approx(430.0, abs=10.0)


# ---- 가전 · 발생원 ---------------------------------------------------------------


def test_cooking_hood_reduces_pm_peak(cfg):
    """요리 PM 은 후드(포집 ε)로 피크가 줄고, 후드 아래 온도가 E1 진입(+8 °C)을 넘는다."""
    ext = ExternalConditions(outdoor_temp_c=24.0, outdoor_rh_pct=60.0)
    src = SourceRates(cooking_pm_mg_per_min=1.5, moisture_g_per_h=400.0, cooking_heat_w=800.0)
    peaks = {}
    for lv in (0, 1):
        model = RoomModel.from_conditions(cfg, 26.0, 55.0, 12.0, 600.0)
        act = ActuatorCommands(range_hood_level=lv, intake_fan_rpm=2000.0 if lv else 0.0)
        obs = run(model, 900, act, ext, src)
        peaks[lv] = obs["pm25_ugm3"]
        assert obs["hood_temperature_c"] - obs["temperature_c"] >= 8.0
    assert peaks[1] < 0.7 * peaks[0]


def test_dehumidifier_heats_and_dries(cfg):
    """제습기: 습도 하강 + 발열 약 480 W (docs/08 §4.4)."""
    ext = ExternalConditions(outdoor_temp_c=27.0, outdoor_rh_pct=60.0)
    model = RoomModel.from_conditions(cfg, 27.0, 60.0, 12.0, 600.0)
    removal, heat, power = model._dehumidifier_effect(True, 27.0, 60.0)
    assert removal == pytest.approx(417.0)
    assert heat == pytest.approx(483.6, abs=1.0)
    obs = run(model, 1800, ActuatorCommands(dehumidifier=True), ext)
    assert obs["humidity_pct"] < 60.0
    assert obs["temperature_c"] > 27.0


def test_ac_cools_and_dries(cfg):
    ext = ExternalConditions(outdoor_temp_c=33.0, outdoor_rh_pct=60.0)
    model = RoomModel.from_conditions(cfg, 31.0, 60.0, 12.0, 600.0)
    w0 = model.state.abs_humidity_g_m3
    obs = run(model, 3600, ActuatorCommands(ac=AcCommand(power=True, mode="cool", setpoint_c=26.0)), ext,
              occ=Occupancy(1))
    assert obs["temperature_c"] < 27.5
    assert obs["abs_humidity_g_m3"] < w0
    assert obs["energy_wh"]["ac"] > 0.0


def test_laundry_calibration_10h(cfg):
    """교정 조건(24 °C · 60 % · 무풍)을 유지하면 약 10시간에 감률 구간에 들어간다."""
    model = RoomModel.from_conditions(cfg, 24.0, 60.0, 12.0, 600.0)
    model.hang_laundry()
    w = model.state.abs_humidity_g_m3
    rate = model._laundry_rate_g_h(24.0, w, 0)
    assert 2000.0 / rate == pytest.approx(10.0, rel=1e-6)
    assert model._laundry_rate_g_h(24.0, w, 2) > rate   # 실링팬 기류로 빨라진다


def test_humidifier_adds_moisture_and_pm(cfg):
    ext = ExternalConditions(outdoor_temp_c=0.0, outdoor_rh_pct=60.0)
    model = RoomModel.from_conditions(cfg, 21.0, 30.0, 5.0, 600.0)
    obs = run(model, 1800, ActuatorCommands(humidifier=True), ext)
    assert obs["humidity_pct"] > 30.0
    assert obs["pm25_ugm3"] > 5.0


# ---- 수치 안정성 · 재현성 ----------------------------------------------------------


def _schedule(t):
    return ActuatorCommands(
        window_open_ratio=0.3 if (t // 1800) % 2 else 0.0,
        exhaust_fan_rpm=1400.0 if (t // 900) % 3 == 0 else 0.0,
        intake_fan_rpm=1000.0,
        range_hood_level=2 if 3600 <= t < 4500 else 0,
        purifier_level=3 if t > 4000 else 1,
        ac=AcCommand(power=t > 7200, setpoint_c=25.0),
        dehumidifier=10_000 < t < 14_000,
        ceiling_fan=-1 if t > 18_000 else 1,
        ceiling_light_pct=60.0,
    )


def _long_run(cfg):
    model = RoomModel.from_conditions(cfg, 28.0, 65.0, 15.0, 700.0)
    model.hang_laundry()
    ext = ExternalConditions(outdoor_temp_c=30.0, outdoor_rh_pct=80.0, outdoor_pm25_ugm3=40.0,
                             outdoor_illuminance_lux=20_000.0)
    src = SourceRates(cooking_pm_mg_per_min=1.5, moisture_g_per_h=400.0, cooking_heat_w=800.0)
    trace = []
    for t in range(0, 6 * 3600, 5):
        obs = model.step(5.0, _schedule(t), ext, src if 3600 <= t < 4500 else None, Occupancy(1))
        trace.append((obs["temperature_c"], obs["humidity_pct"], obs["pm25_ugm3"], obs["co2_ppm"]))
    return trace


def test_six_hour_run_is_stable_and_deterministic(cfg):
    a = _long_run(cfg)
    b = _long_run(cfg)
    assert a == b
    for temp, rh, pm, co2 in a:
        assert all(math.isfinite(x) for x in (temp, rh, pm, co2))
        assert 10.0 < temp < 45.0
        assert 0.0 < rh <= 120.0
        assert 0.0 <= pm < 2000.0
        assert 400.0 < co2 < 5000.0


def test_winter_heating_holds_21c(cfg):
    """가정 A13 — 난방 경계 조건이 겨울 실내 21 °C 를 유지한다 (가습기 증발 냉각이 있어도)."""
    ext = ExternalConditions(outdoor_temp_c=-5.0, outdoor_rh_pct=60.0, heating_setpoint_c=21.0)
    model = RoomModel.from_conditions(cfg, 21.0, 35.0, 12.0, 600.0)
    obs = run(model, 3 * 3600, ActuatorCommands(humidifier=True), ext, occ=Occupancy(1, "sleeping"), dt=10.0)
    assert obs["temperature_c"] == pytest.approx(21.0, abs=0.5)
    assert obs["heating_w"] > 0.0


@pytest.mark.parametrize("model, alt", [("additive", "positive_zero"), ("positive_zero", "additive")])
def test_infiltration_model_switch(cfg, model, alt):
    """docs/06 §5.1 식 · 주석 불일치 — 두 식을 스위치로 고르고, 다른 쪽 값을 진단용으로 남긴다."""
    c = cfg.with_overrides({"air_balance.infiltration_model": model})
    m = RoomModel.from_conditions(c, 26.0, 55.0, 12.0, 600.0)
    ext = ExternalConditions(outdoor_temp_c=24.0, outdoor_rh_pct=60.0)
    pos = m.step(1.0, ActuatorCommands(intake_fan_rpm=2000.0), ext)       # 양압 — 두 식이 다르다
    expected = {"additive": 12.6, "positive_zero": 0.0}
    assert pos["q_inf_m3h"] == pytest.approx(expected[model])
    assert pos["q_inf_alt_m3h"] == pytest.approx(expected[alt])
    neg = m.step(1.0, ActuatorCommands(range_hood_level=2), ext)          # 음압 — 두 식이 같다
    assert neg["q_inf_m3h"] == pytest.approx(neg["q_inf_alt_m3h"])
