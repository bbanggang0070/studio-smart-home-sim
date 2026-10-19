"""실측 기상 대입 검증 (harness/weather.py · docs/11 필수 조치 3) — 연도 분리 · 보간 · 하늘 판정 · 자극 키 보존 · 날 고르기."""

import numpy as np
import pandas as pd
import pytest

from harness import weather as W
from harness.runner import REPO, load_harness_config


@pytest.fixture(scope="module")
def cfg():
    return load_harness_config()["weather"]


def _series(cfg):
    idx = pd.date_range("2024-07-01", periods=72, freq="h")
    h = idx.hour.to_numpy()
    return pd.DataFrame({"outdoor_temp_c": 25.0 + h * 0.1, "outdoor_rh_pct": 60.0 + 0 * h,
                         "ghi_w_m2": np.where((h > 6) & (h < 19), 500.0, 0.0), "precip_mm": np.where(h == 12, 1.0, 0.0),
                         "cloud_pct": 10.0 + 0 * h, "wind_speed_ms": 2.0 + 0 * h}, index=idx)


def test_split_years_disjoint(cfg):
    assert not set(cfg["years"]["train"]) & set(cfg["years"]["eval"])
    ev = W.load_series(cfg, REPO, "eval")
    assert set(ev.index.year) == set(cfg["years"]["eval"])
    assert (ev["ghi_w_m2"] >= 0).all() and not ev.isna().any().any()


def test_interpolation_and_sky(cfg):
    s = _series(cfg)
    e = W.external_at(s, pd.Timestamp("2024-07-01T03:30"), cfg, 105.0)
    assert e["outdoor_temp_c"] == pytest.approx(25.35)
    assert e["weather"] == "clear"
    assert W.external_at(s, pd.Timestamp("2024-07-01T12:10"), cfg, 105.0)["weather"] == "rain"
    assert W.external_at(s, pd.Timestamp("2024-07-01T10:00"), cfg, 105.0)["outdoor_illuminance_lux"] == pytest.approx(52500.0)


def test_staged_keys_kept(cfg):
    s = _series(cfg)
    sc = {"id": "T", "duration_s": 3600, "initial": {"time_of_day": "10:00"},
          "external": {"weather": "clear", "outdoor_temp_c": 30.0, "outdoor_rh_pct": 50.0, "outdoor_pm25_ugm3": 80.0},
          "events": [{"at_s": 600, "set": {"outdoor_rh_pct": 90.0}}]}
    out = W.apply_to_scenario(sc, s, pd.Timestamp("2024-07-01T10:00"), cfg, 105.0)
    assert out["external"]["outdoor_rh_pct"] == 50.0            # 자극 키는 시나리오 값
    assert out["external"]["outdoor_pm25_ugm3"] == 80.0         # PM2.5 는 대입하지 않는다
    assert out["external"]["outdoor_temp_c"] == pytest.approx(26.0)
    added = [e for e in out["events"] if e.get("label") == "measured_weather"]
    assert added and all("outdoor_rh_pct" not in e["set"] for e in added)
    assert sc["external"]["outdoor_temp_c"] == 30.0              # 원본은 그대로


def test_match_starts_same_time_of_day(cfg):
    s = _series(cfg)
    sc = {"duration_s": 3600, "initial": {"time_of_day": "02:00"},
          "external": {"weather": "clear", "outdoor_temp_c": 25.2, "outdoor_rh_pct": 60.0}}
    starts, scale = W.match_starts(s, sc, cfg, 2, np.random.default_rng(0))
    assert scale == 1.0 and len(starts) == 2 and all(t.hour == 2 for t in starts)
    assert len({t.date() for t in starts}) == 2
