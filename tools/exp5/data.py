"""EXP-5 학습 데이터 — 페르소나 · 학습 k주마다 같은 데이터를 세 방식에 준다 (docs/13 §5).

  운전 기록  참값 3R3C 를 k주 동안 무작위 운전(에어컨 켬/끔 · 설정 · 재실 — energy_training 과 같은 방식)으로 돌린 기록
            · 학습 연도 실측 기상 · 제어기가 볼 수 있는 값만 (실내 온도 · 외기 · 실내 주광 · 재실 · 에어컨 전력)
  귀가 이력  학습 k주 에피소드의 귀가 시각 · 분위수 GBM (검증 2주 분위 손실로 경험 분포와 비교해 선택 — v1.29 의 auto)

산출물: results/exp5/data/<persona>_k<k>/ {log.npz · energy.yaml · gbm.json}

    uv run python tools/exp5/data.py [--persona commuter] [--weeks 4]
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.ensemble import GradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "energy"))

from exp5.common import REPO, Ctx, Episode, train_val_episodes, weather  # noqa: E402
from train_arrival_gbm import EVAL_Q, export, pinball  # noqa: E402
from train_energy_model import generate_trace, identify  # noqa: E402

from controller.arrival_gbm import ArrivalGBM  # noqa: E402


def data_dir(ctx: Ctx, persona: str, k: int) -> Path:
    return REPO / ctx.cfg["out_dir"] / "data" / f"{persona}_k{k}"


def operation_log(ctx: Ctx, persona: str, k: int) -> dict[str, np.ndarray]:
    tc = dict(ctx.h["energy_training"])
    pi = ctx.cfg["personas"].index(persona)
    days = 7 * k
    wx = weather(ctx, "train")
    rng = np.random.default_rng(tc["seed"] + 100 * pi + k)
    months = set(ctx.cfg["episode"]["months"])
    cand = [d for d in wx.days if (d + pd.Timedelta(days=days - 1)).month in months]
    start = cand[int(rng.integers(len(cand)))]
    fn = lambda ts: dict(zip(("outdoor_temp_c", "outdoor_rh_pct", "outdoor_illuminance_lux"),  # noqa: E731
                             wx.at(start + pd.Timedelta(seconds=ts))))
    tc.update(days=days, dt_s=float(ctx.cfg["data"]["log_dt_s"]), seed=int(tc["seed"] + 100 * pi + k))
    rec = generate_trace(tc, ctx.env_cfg, ctx.p, weather=fn)
    rec["start"] = np.array(str(start.date()))
    return rec


def fit_gbm(ctx: Ctx, tr: list[Episode], va: list[Episode], path: Path) -> dict:
    """v1.29 train_arrival_gbm.run 과 같은 설정 · 같은 선택 규칙 — 데이터만 학습 k주 · 검증 2주."""
    g = ctx.p.get("energy.arrival_gbm")

    def feats(eps):
        return np.array([[e.weekday, float(e.weekday >= 5), e.depart_tod / 3600, e.prev_arrive_tod / 3600 % 24] for e in eps])

    x, y = feats(tr), np.array([e.arrive_tod / 3600 for e in tr])
    models = []
    for q in g["quantiles"]:
        m = GradientBoostingRegressor(loss="quantile", alpha=q, n_estimators=g["n_estimators"], max_depth=g["max_depth"],
                                      learning_rate=g["learning_rate"], min_samples_leaf=g["min_samples_leaf"], random_state=0)
        m.fit(x, y)
        models.append(m)
    export(models, g["quantiles"], path)
    gbm = ArrivalGBM(path)
    loss = {"empirical": [], "quantile_gbm": []}
    for e in va:
        now = e.depart_tod / 3600 + 1.0
        if e.arrive_tod / 3600 <= now:
            continue
        later = y[y > now]
        emp = np.quantile(later, EVAL_Q) if later.size else np.full(EVAL_Q.size, now)
        gq = gbm.conditional_quantiles_h(gbm.features(e.weekday, e.depart_tod / 3600, e.prev_arrive_tod / 3600 % 24), now, EVAL_Q)
        loss["empirical"].append(pinball(e.arrive_tod / 3600, emp, EVAL_Q))
        loss["quantile_gbm"].append(pinball(e.arrive_tod / 3600, gq, EVAL_Q))
    vmean = {kk: (float(np.mean(v)) * 60 if v else float("inf")) for kk, v in loss.items()}
    selected = min(vmean, key=vmean.get) if np.isfinite(vmean["quantile_gbm"]) else "empirical"
    m = json.loads(path.read_text(encoding="utf-8"))
    m.update({"selected": selected, "validation_pinball_min": {kk: round(v, 2) for kk, v in vmean.items()},
              "n_train": len(tr), "n_val": len(va)})
    path.write_text(json.dumps(m, separators=(",", ":")), encoding="utf-8")
    return {"selected": selected, **{f"val_pinball_{kk}": round(v, 2) for kk, v in vmean.items()}}


def build(persona: str, k: int) -> dict:
    ctx = Ctx.load()
    out = data_dir(ctx, persona, k)
    out.mkdir(parents=True, exist_ok=True)
    tr, va = train_val_episodes(ctx, persona, k)
    rec = operation_log(ctx, persona, k)
    np.savez_compressed(out / "log.npz", **rec)
    ac = ctx.p.get("appliances.ac")
    cop = ac["cooling_kw"] * 1000.0 / ac["power_w"]
    m, rmse = identify(rec, float(ctx.cfg["data"]["log_dt_s"]), cop)
    doc = {"persona": persona, "weeks": k, "generated_by": "tools/exp5/data.py",
           "thermal_2r2c": {kk: float(f"{v:.6g}") for kk, v in m.to_dict().items()},
           "thermal_fit": {"days": 7 * k, "dt_s": float(ctx.cfg["data"]["log_dt_s"]), "rmse_c": round(rmse, 3),
                           "log_start": str(rec["start"])},
           "arrival_history_tod_s": sorted(float(e.arrive_tod) for e in tr)}
    (out / "energy.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sel = fit_gbm(ctx, tr, va, out / "gbm.json")
    info = {"persona": persona, "weeks": k, "n_train": len(tr), "n_val": len(va), "rmse_2r2c_c": round(rmse, 3), **sel}
    (out / "info.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona")
    ap.add_argument("--weeks", type=int)
    a = ap.parse_args()
    ctx = Ctx.load()
    jobs = [(p, k) for p in ([a.persona] if a.persona else ctx.cfg["personas"])
            for k in ([a.weeks] if a.weeks else ctx.cfg["data"]["weeks"])]
    with ProcessPoolExecutor(min(len(jobs), int(ctx.cfg["workers"]))) as ex:
        for info in ex.map(build, *zip(*jobs)):
            print(info, flush=True)


if __name__ == "__main__":
    main()
