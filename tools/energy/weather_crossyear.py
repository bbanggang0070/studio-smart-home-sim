"""2R2C 식별 연도 분리 점검 (docs/11 필수 조치 3) — 학습 연도 실측 기상으로 식별 → 평가 연도 실측 기상에서 예측 오차.

    uv run python tools/energy/weather_crossyear.py   → results/tables/weather_crossyear.csv · .md

비교: ① 지금 제어기 모델 방식(합성 날씨 기록 energy_training 으로 식별) ② 학습 연도(weather.years.train) 실측 기상 기록으로 식별 (연도마다 train_windows_per_year 기간 · 각각 식별).
둘 다 평가 연도(weather.years.eval) 실측 기상 기록 test_windows 개에서 시뮬레이션 RMSE 를 잰다.
기록 = 참값 3R3C 를 같은 무작위 운전(에어컨 켬/끔 · 설정 · 재실)으로 돌린 것 — 날씨만 다르다. models/ 는 바꾸지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from controller.params import load_params  # noqa: E402
from env_model.config import load_config  # noqa: E402
from harness import weather as W  # noqa: E402
from harness.runner import load_harness_config  # noqa: E402
from train_energy_model import generate_trace, identify, simulate  # noqa: E402


def windows(series: pd.DataFrame, months: list[int], days: int, n: int, rng: np.random.Generator) -> list[pd.Timestamp]:
    """months 안에서 days 일이 다 들어가는 0시 시작일 n 개 (서로 겹치지 않게)."""
    span = pd.Timedelta(days=days)
    cand = [d for d in pd.date_range(series.index[0], series.index[-1], freq="D")
            if d.month in months and (d + span - pd.Timedelta(hours=1)).month in months and d + span <= series.index[-1]]
    out: list[pd.Timestamp] = []
    for k in rng.permutation(len(cand)):
        d = cand[int(k)]
        if all(abs((d - o).days) >= days for o in out):
            out.append(d)
        if len(out) == n:
            break
    return sorted(out)


def main() -> None:
    h = load_harness_config()
    wc, cy, tc = h["weather"], h["weather"]["crossyear"], h["energy_training"]
    p = load_params()
    env_cfg = load_config(REPO / h["paths"]["environment_model"])
    eff = float(env_cfg.get("thermal.solar_luminous_efficacy_lm_per_w"))
    ac = p.get("appliances.ac")
    cop = ac["cooling_kw"] * 1000.0 / ac["power_w"]
    dt_h = float(tc["dt_s"]) / 3600.0
    rng = np.random.default_rng(int(wc["seed"]))
    train_s, eval_s = W.load_series(wc, REPO, "train"), W.load_series(wc, REPO, "eval")

    def trace(series, start, days, seed):
        fn = lambda ts: W.external_at(series, start + pd.Timedelta(seconds=ts), wc, eff)  # noqa: E731
        return generate_trace({**tc, "days": days, "seed": seed}, env_cfg, p, weather=fn)

    tests = [(d, trace(eval_s, d, cy["test_days"], tc["seed"] + 200 + i))
             for i, d in enumerate(windows(eval_s, cy["months"], cy["test_days"], cy["test_windows"], rng))]
    models = []
    print("① 합성 날씨로 식별 ...", flush=True)
    m, fit = identify(generate_trace(tc, env_cfg, p), float(tc["dt_s"]), cop)
    models.append(("합성 날씨 (지금 방식)", "-", m, fit))
    starts = [d for y in wc["years"]["train"]                      # 학습 연도마다 같은 수 — 한 해에 몰리지 않게
              for d in windows(train_s[train_s.index.year == y], cy["months"], cy["train_days"], cy["train_windows_per_year"], rng)]
    for i, d in enumerate(starts):
        print(f"② 학습 연도 실측 {d:%Y-%m-%d} 부터 {cy['train_days']}일로 식별 ...", flush=True)
        m, fit = identify(trace(train_s, d, cy["train_days"], tc["seed"] + 100 + i), float(tc["dt_s"]), cop)
        models.append(("학습 연도 실측", f"{d:%Y-%m-%d}", m, fit))
    rows = []
    for name, start, m, fit in models:
        for d, rec in tests:
            pred = simulate(m, rec, dt_h, cop, rec["t"][0], rec["t"][0])
            rows.append({"model": name, "train_start": start, "fit_rmse_c": fit, "test_start": f"{d:%Y-%m-%d}",
                         "test_rmse_c": float(np.sqrt(np.mean((pred - rec["t"]) ** 2))),
                         "test_to_mean": float(np.mean(rec["to"])), "test_to_max": float(np.max(rec["to"]))})
    df = pd.DataFrame(rows)
    out = REPO / "results" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "weather_crossyear.csv", index=False)
    g = df.groupby(["model", "train_start"], sort=False).agg(fit=("fit_rmse_c", "first"), test=("test_rmse_c", "mean"),
                                                             worst=("test_rmse_c", "max")).reset_index()
    lines = [f"# 2R2C 식별 연도 분리 — 평가 연도 {wc['years']['eval']} 실측 기상 {len(tests)}기간 × {cy['test_days']}일", "",
             "시험 기간: " + " · ".join(f"{d:%m-%d}" for d, _ in tests), "",
             "| 식별 기록 | 시작 | 학습 RMSE [°C] | 평가 연도 RMSE 평균 [°C] | 최악 [°C] |", "|---|---|---:|---:|---:|"]
    for _, r in g.iterrows():
        lines.append(f"| {r.model} | {r.train_start} | {r.fit:.3f} | {r.test:.3f} | {r.worst:.3f} |")
    (out / "weather_crossyear.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
