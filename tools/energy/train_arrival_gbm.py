"""분위수 GBM 귀가 예측 학습 + EXP-2 오프라인 비교 (docs/08 §5.8 · W11 T11.w2 · T11.w3).

    uv run python tools/energy/train_arrival_gbm.py --persona commuter            # 학습 → models/arrival_gbm_commuter.json
    uv run python tools/energy/train_arrival_gbm.py --all                         # 페르소나 3종 학습 + EXP-2 표

데이터: 비균질 마르코프 재실 생성기 12주 (harness/occupancy_gen.py) — 학습 8주 · 검증 2주 · 시험 2주 (주 단위로 나눈다)
EXP-2 (시험 2주의 주 외출마다, 출발 1시간 뒤 '아직 안 돌아왔다'는 조건에서):
  경험 분포  학습 기간 주 귀가 시각 중 지금 이후인 것 (현재 제어기 · 특성 없음)
  분위수 GBM 요일 · 출발 시각 · 직전 귀가 시각 → 분위수 → 같은 조건부
  지표       pinball(분위 손실, 0.1–0.9 평균, 분) · 20분위 커버리지(실제 < 예측 20분위 비율 — 0.2 가 이상적) · 중앙값 절대 오차(분)
결과: results/exp2/arrival_<persona>.csv · 요약 표 출력
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.ensemble import GradientBoostingRegressor

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from controller.arrival_gbm import FEATURES, ArrivalGBM  # noqa: E402
from controller.params import load_params  # noqa: E402
from harness.occupancy_gen import absences, generate  # noqa: E402

EVAL_Q = np.round(np.arange(0.1, 0.91, 0.1), 2)
DECIDE_AFTER_H = 1.0          # 출발 1시간 뒤에 예측한다 (주 외출은 3시간 이상)


def dataset(cfg: dict, persona: str, seed: int | None = None) -> pd.DataFrame:
    occ, types = generate(cfg, persona, seed=seed)
    ab = absences(occ, types, cfg)
    rows, prev = [], None
    for a in ab:
        rows.append({"day": a.day, "week": a.day // 7, "weekday": a.weekday, "is_weekend": float(a.weekday >= 5),
                     "depart_h": a.depart_tod_s / 3600, "arrive_h": a.arrive_tod_s / 3600,
                     "prev_arrive_h": prev if prev is not None else np.nan, "day_type": a.day_type})
        prev = (a.arrive_tod_s % 86400) / 3600
    df = pd.DataFrame(rows)
    df["prev_arrive_h"] = df["prev_arrive_h"].fillna(df["arrive_h"].median())
    return df


def export(models: list[GradientBoostingRegressor], quantiles, path: Path) -> None:
    out = {"features": list(FEATURES), "quantiles": [float(q) for q in quantiles], "models": []}
    for m in models:
        trees = []
        for est in m.estimators_[:, 0]:
            t = est.tree_
            trees.append({"left": t.children_left.tolist(), "right": t.children_right.tolist(),
                          "feature": t.feature.tolist(), "threshold": [round(float(v), 6) for v in t.threshold],
                          "value": [round(float(v), 6) for v in t.value[:, 0, 0]]})
        init = float(m.init_.constant_[0][0]) if hasattr(m.init_, "constant_") else float(m._raw_predict_init(np.zeros((1, 4)))[0][0])
        out["models"].append({"init": init, "lr": float(m.learning_rate), "trees": trees})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")


def pinball(y: float, qhat: np.ndarray, q: np.ndarray) -> float:
    d = y - qhat
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def run(persona: str, cfg: dict, gcfg: dict, out_model: Path, seed: int | None = None) -> pd.DataFrame:
    df = dataset(cfg, persona, seed)
    w = cfg["weeks"]
    syn = load_params().get("energy.synthetic_weeks")
    train = df[df.week < syn["train"]]
    val = df[(df.week >= syn["train"]) & (df.week < syn["train"] + syn["val"])]
    test = df[df.week >= w - syn["test"]]
    x = train[list(FEATURES)].to_numpy()
    models = []
    for q in gcfg["quantiles"]:
        m = GradientBoostingRegressor(loss="quantile", alpha=q, n_estimators=gcfg["n_estimators"], max_depth=gcfg["max_depth"],
                                      learning_rate=gcfg["learning_rate"], min_samples_leaf=gcfg["min_samples_leaf"], random_state=0)
        m.fit(x, train["arrive_h"].to_numpy())
        models.append(m)
    export(models, gcfg["quantiles"], out_model)
    gbm = ArrivalGBM(out_model)
    # 내보낸 JSON 평가기 = scikit-learn 예측 (numpy 평가기 검증)
    x0 = x[:5]
    sk = np.array([[m.predict(x0[i:i + 1])[0] for m in models] for i in range(len(x0))])
    js = np.array([gbm.quantiles_h(x0[i]) for i in range(len(x0))])
    assert np.allclose(np.maximum.accumulate(sk, axis=1), js, atol=1e-3), "JSON 평가기 ≠ scikit-learn"

    hist = train["arrive_h"].to_numpy()

    def predict(r):
        now = r.depart_h + DECIDE_AFTER_H
        later = hist[hist > now]
        emp = np.quantile(later, EVAL_Q) if later.size else np.full(EVAL_Q.size, now)
        g = gbm.conditional_quantiles_h(gbm.features(int(r.weekday), r.depart_h, r.prev_arrive_h), now, EVAL_Q)
        return now, emp, g

    # 모델 선택 — 검증 주의 분위 손실이 작은 쪽 (재택처럼 데이터가 적으면 경험 분포가 낫다 · EXP-2)
    vloss = {"empirical": [], "quantile_gbm": []}
    for _, r in val.iterrows():
        now, emp, g = predict(r)
        if r.arrive_h > now:
            vloss["empirical"].append(pinball(r.arrive_h, emp, EVAL_Q))
            vloss["quantile_gbm"].append(pinball(r.arrive_h, g, EVAL_Q))
    vmean = {k: (float(np.mean(v)) * 60 if v else float("inf")) for k, v in vloss.items()}
    selected = min(vmean, key=vmean.get) if np.isfinite(vmean["quantile_gbm"]) else "empirical"
    m = json.loads(out_model.read_text(encoding="utf-8"))
    m.update({"selected": selected, "validation_pinball_min": {k: round(v, 2) for k, v in vmean.items()},
              "n_train": int(len(train)), "n_val": int(len(val))})
    out_model.write_text(json.dumps(m, separators=(",", ":")), encoding="utf-8")
    rec = []
    for _, r in test.iterrows():
        now, emp, g = predict(r)
        if r.arrive_h <= now:
            continue
        auto = g if selected == "quantile_gbm" else emp
        for name, qh in (("empirical", emp), ("quantile_gbm", g), ("auto", auto)):
            rec.append({"persona": persona, "seed": seed, "model": name, "day": r.day, "day_type": r.day_type, "actual_h": r.arrive_h,
                        "pinball_min": pinball(r.arrive_h, qh, EVAL_Q) * 60, "q20_h": qh[1], "q50_h": qh[4],
                        "below_q20": float(r.arrive_h < qh[1]), "abs_err_q50_min": abs(r.arrive_h - qh[4]) * 60})
    res = pd.DataFrame(rec)
    res["n_train"] = len(train)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="commuter")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seeds", type=int, default=10, help="생성기 시드 반복 수 (시험 표본이 페르소나당 10여 회라 반복해 평균)")
    args = ap.parse_args()
    h = yaml.safe_load((REPO / "config" / "harness.yaml").read_text(encoding="utf-8"))
    cfg = h["occupancy_generator"]
    gcfg = load_params().get("energy.arrival_gbm")
    out = REPO / "results" / "exp2"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in (list(cfg["personas"]) if args.all else [args.persona]):
        base = cfg["personas"][p]["seed"]
        # 반복 k = 1.. 은 평가용 (시드만 바꾼 12주) · k = 0 은 배포 모델 (models/arrival_gbm_<persona>.json)
        res = pd.concat([run(p, cfg, gcfg, (REPO / "models" / f"arrival_gbm_{p}.json") if k == 0
                             else out / "tmp_model.json", base + k) for k in range(args.seeds)], ignore_index=True)
        res.to_csv(out / f"arrival_{p}.csv", index=False)
        per_seed = res.groupby(["model", "seed"])[["pinball_min", "below_q20", "abs_err_q50_min"]].mean()
        agg = per_seed.groupby("model").agg(["mean", "std"]).round(2)
        n = res[res.model == "empirical"].groupby("seed").size()
        print(f"== {p} — 시드 {args.seeds}개 · 시드당 학습 주 외출 {int(res.n_train.mean())}회 · 시험 {n.mean():.0f}회 "
              f"(출발 {DECIDE_AFTER_H:g} h 뒤 예측)")
        print(agg.to_string())
        for m in ("empirical", "quantile_gbm", "auto"):
            r = per_seed.loc[m].mean()
            rows.append({"persona": p, "model": m, "pinball_min": round(r.pinball_min, 1),
                         "coverage_q20": round(r.below_q20, 3), "abs_err_q50_min": round(r.abs_err_q50_min, 1)})
    (out / "tmp_model.json").unlink(missing_ok=True)
    pd.DataFrame(rows).to_csv(out / "summary.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
