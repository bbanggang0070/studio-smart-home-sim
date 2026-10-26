"""EXP-5 도구 단위 테스트 — 판정 규칙 · Holm · 비용 정의 · 귀가 분위 캐시 · 에피소드 환경 (docs/13)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from exp5 import analyze as A  # noqa: E402
from exp5.common import Ctx, Fixed, run_episode, shifted_occ_cfg, train_val_episodes, weather  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    return Ctx.load()


def test_holm_monotone_and_capped():
    assert A.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert A.holm([0.5, 0.9]) == pytest.approx([1.0, 1.0])


def test_verdict_rules():
    assert A.verdict(0.80, 0.95, 0.01) == "① 보다 낫다"
    assert A.verdict(1.05, 1.20, 0.01) == "① 보다 못하다"
    assert A.verdict(0.80, 1.05, 0.01) == "차이를 확인하지 못함"
    assert A.verdict(0.80, 0.95, 0.20) == "차이를 확인하지 못함"


def test_sign_p_counts_cheaper_episodes():
    m = pd.DataFrame({"cost": [1.0] * 10, "cost_ref": [2.0] * 10})
    assert A.sign_p(m) < 0.01


def test_cost_matches_planner_definition(ctx):
    # 비용 = Wh + λ · 2000 · K·h (계획기 discomfort_wh_per_kh · NORMAL λ)
    assert ctx.cost(100.0, 0.1) == pytest.approx(100.0 + ctx.lam * ctx.w_kh * 0.1)
    assert ctx.w_kh == 2000.0


def test_pattern_shift_only_changes_named_weights(ctx):
    base = shifted_occ_cfg(ctx, "commuter", None)["personas"]["commuter"]["day_types"]
    sh = shifted_occ_cfg(ctx, "commuter", ctx.cfg["eval"]["pattern_shift"]["commuter"])["personas"]["commuter"]["day_types"]
    assert sh["late"]["weight_weekday"] == pytest.approx(base["late"]["weight_weekday"] * 3.333)
    assert sh["weekday"]["weight_weekday"] == base["weekday"]["weight_weekday"]
    home = shifted_occ_cfg(ctx, "home", ctx.cfg["eval"]["pattern_shift"]["home"])["personas"]["home"]["day_types"]
    hb = shifted_occ_cfg(ctx, "home", None)["personas"]["home"]["day_types"]
    assert home["weekday"]["p_home"][12] == pytest.approx(1 - 2 * (1 - hb["weekday"]["p_home"][12]))
    assert home["weekday"]["p_home"][8] == hb["weekday"]["p_home"][8]


def test_setback_costs_more_energy_than_off_on_long_absence(ctx):
    # 평가 집합은 방식 동결 전에 만들지 않는다 (docs/13) — 검증 에피소드로 시험
    eps = [e for e in train_val_episodes(ctx, "commuter", 4)[1] if e.away_h > 6][:1]
    wx = weather(ctx, "train")
    sb = run_episode(ctx, eps[0], Fixed("setback"), wx)
    off = run_episode(ctx, eps[0], Fixed("off"), wx)
    assert sb["energy_wh"] > off["energy_wh"]
    assert sb["overrides"] == 0 and off["overrides"] == 0


def test_arrival_quantile_cache_equals_gbm(ctx):
    from exp5.data import data_dir
    from exp5.rl import ArrivalInfo
    d = data_dir(ctx, "commuter", 4)
    if not (d / "gbm.json").exists():
        pytest.skip("학습 데이터 없음 — tools/exp5/data.py")
    a = ArrivalInfo(d)
    if a.gbm is None:
        pytest.skip("경험 분포 선택")
    x = a.gbm.features(2, 8.0, 19.0)
    want = a.gbm.conditional_quantiles_h(x, 10.0, (0.2, 0.5, 0.8)) * 3600
    assert np.allclose(a.quantiles(10 * 3600, 2, 8 * 3600, 19 * 3600), want)
