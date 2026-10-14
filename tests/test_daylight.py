"""주광 모델 (common/daylight.py · v3.4.21) — 렌더 대조 값 재현 · 제어용 = 참값 사본 · 역탐색."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from common import daylight as dlm  # noqa: E402
from controller.params import load_params  # noqa: E402
from env_model.config import load_config  # noqa: E402


def _cfgs():
    return load_params().get("lighting_model.daylight"), load_config(REPO / "config" / "environment_model.yaml").get("lighting.daylight")


def test_control_copy_matches_truth():
    ctl, truth = _cfgs()
    assert ctl == truth


def test_components_reproduce_render():
    ctl, _ = _cfgs()
    sun = {**ctl, "direct_fraction": {"clear": 1.0}}
    sky = {**ctl, "direct_fraction": {"clear": 0.0}}
    assert dlm.workplane_per_outdoor(sun, "clear", 0.0) == pytest.approx(0.084)
    assert dlm.relative_transmittance(sun, "clear", 45.0) == pytest.approx(0.126)
    assert dlm.relative_transmittance(sky, "clear", 75.0) == pytest.approx(0.284)
    assert 1.0 / dlm.sensor_to_workplane(sun, "clear", 75.0) == pytest.approx(1.342)


def test_sky_changes_shading_and_inverse_angle():
    ctl, _ = _cfgs()
    # 같은 45° 라도 맑은 날이 흐린 날보다 훨씬 많이 가린다
    assert dlm.relative_transmittance(ctl, "clear", 45.0) < dlm.relative_transmittance(ctl, "overcast", 45.0)
    for sky in ("clear", "overcast"):
        d = dlm.angle_for_relative(ctl, sky, 0.5, 75.0)
        assert dlm.relative_transmittance(ctl, sky, d) <= 0.5 < dlm.relative_transmittance(ctl, sky, d - 1.0)
    assert dlm.direct_fraction(ctl, "unknown") == dlm.direct_fraction(ctl, "clear")
