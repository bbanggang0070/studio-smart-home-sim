"""귀가 예측 (W11 T11.w2) — 재실 생성기 · numpy GBM 평가기 · 계획기 연결."""

import json

import numpy as np
import yaml

from controller.arrival_gbm import ArrivalGBM
from controller.energy import EnergyPlanner
from controller.params import load_params
from harness.occupancy_gen import absences, generate
from harness.runner import REPO

GEN = yaml.safe_load((REPO / "config" / "harness.yaml").read_text(encoding="utf-8"))["occupancy_generator"]


def test_generator_reproducible_and_personas_differ():
    a, ta = generate(GEN, "commuter")
    b, tb = generate(GEN, "commuter")
    assert (a == b).all() and ta == tb                              # 같은 시드 → 같은 이력
    home, _ = generate(GEN, "home")
    assert home.mean() > a.mean() + 0.15                            # 재택이 더 오래 집에 있다
    arr = [x.arrive_tod_s / 3600 for x in absences(a, ta, GEN) if x.weekday < 5 and x.day_type == "weekday"]
    assert 17.5 < np.median(arr) < 20.0                            # 정시 출퇴근 평일 귀가 ≈ 19 시


def test_gbm_conditional_quantiles_are_monotone_and_after_now():
    g = ArrivalGBM(REPO / "models" / "arrival_gbm_irregular.json")
    x = g.features(2, 8.0, 18.0)
    q = g.quantiles_h(x)
    assert (np.diff(q) >= 0).all()
    c = g.conditional_quantiles_h(x, 12.0, [0.1, 0.5, 0.9])
    assert (np.diff(c) >= 0).all() and c[0] >= 12.0                # 지금 이후만


def test_planner_uses_selected_arrival_model(monkeypatch):
    p = load_params()
    for persona, want in (("irregular", "quantile_gbm"), ("home", "empirical")):
        sel = json.loads((REPO / "models" / f"arrival_gbm_{persona}.json").read_text(encoding="utf-8"))["selected"]
        assert sel == want                                          # 검증 2주로 고른 모델 (EXP-2)
        orig = p.get
        monkeypatch.setattr(type(p), "get", lambda self, k, *a, _o=orig, _p=persona: (
            f"models/arrival_gbm_{_p}.json" if k == "energy.arrival_gbm.model_file" else _o(k, *a)))
        pl = EnergyPlanner(p, p.get("energy.learned_model_file"), 1.0)
        assert pl.arrival_model == want
        monkeypatch.undo()
    pl = EnergyPlanner(p, p.get("energy.learned_model_file"), 1.0)
    pl.gbm = ArrivalGBM(REPO / "models" / "arrival_gbm_irregular.json")
    pl.depart_tod = 8 * 3600.0
    s = pl._arrival_samples(10 * 3600.0)
    assert s.min() >= 10 * 3600.0 and s.size == pl.n_samples
