"""에너지 예측 · 외출 전략 (docs/08 §5.3–5.4 · E13) 단위 테스트."""

import pytest

from controller.energy import EnergyPlanner, Thermal2R2C
from controller.params import load_params


@pytest.fixture(scope="module")
def params():
    return load_params()


def _planner(params, strategy="auto", weight=1.0):
    pl = EnergyPlanner(params, params.get("energy.learned_model_file"), weight, strategy)
    pl.observe(26.0, 32.0, 0.0, 0.0, 0.0, 0.0)
    pl.tm_hat = 28.5                                  # 데워진 구조체
    return pl


def test_model_heats_toward_outdoor_without_ac(params):
    pl = _planner(params)
    m: Thermal2R2C = pl.model
    t, tm = 26.0, 28.5
    for _ in range(72):                               # 6 h (5분 보폭)
        t, tm = m.step(t, tm, 32.0, 0.0, 0.0, 0.0, 300 / 3600)
    assert 26.0 < t < 32.0


def test_precool_chosen_and_starts_before_median_arrival(params):
    pl = _planner(params)
    d = pl.plan(13 * 3600.0, 32.0, lambda tod: 0.0, 26.0)
    assert d["cost_setback"] > d["cost"]              # 오후 내내 셋백 유지는 비싸다
    assert d["strategy"] == "precool" or d["cost_precool_best"] <= d["cost_off"]
    if d["strategy"] == "precool":
        assert d["start_tod"] < d["arrival_q50"]


def test_strategy_setting_is_respected(params):
    pl = _planner(params, strategy="setback")
    assert pl.plan(13 * 3600.0, 32.0, lambda tod: 0.0, 26.0)["strategy"] == "setback"


def test_higher_comfort_weight_starts_earlier(params):
    early = _planner(params, "precool", 5.0).plan(13 * 3600.0, 32.0, lambda tod: 0.0, 26.0)["start_tod"]
    late = _planner(params, "precool", 0.2).plan(13 * 3600.0, 32.0, lambda tod: 0.0, 26.0)["start_tod"]
    assert early <= late
