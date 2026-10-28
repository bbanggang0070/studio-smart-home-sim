"""한계 15 확인 — 동결 제어기 v1.29 전체(고속 모드)에서 외출 전략 auto(기대비용 계획기 · 기본값) vs off vs setback.

EXP-5 는 외출 결정만 떼어 비교했다. 여기서는 제어기 코드를 그대로 두고 사용자 설정(away_strategy)만 바꿔
EXP-1 과 같은 틀(C16 · 13:00 외출)과 같은 비용(에어컨 Wh + 2,000 × 귀가 후 불쾌 K·h)으로 비교한다.
  A  외기 고정 격자 (EXP-1 과 같은 외기 · 외출 시간)
  B  2024 냉방철 실측 기상 — 날 무작위 · 외출 시간 4종
결과: results/away_check/runs.csv · summary.md

    uv run python tools/energy/away_strategy_check.py
"""

from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from controller.params import load_params  # noqa: E402
from exp1_setback_sweep import scenario  # noqa: E402
from harness import runner as R  # noqa: E402
from harness import weather as W  # noqa: E402
from harness.controllers import make_controller  # noqa: E402
from harness.scenario import Run, load_scenarios  # noqa: E402


def one(part: str, tout: float, away: float, strat: str, day: str | None) -> dict:
    h = yaml.safe_load((REPO / "config" / "harness.yaml").read_text(encoding="utf-8"))
    c, e1 = h["away_strategy_check"], h["exp1_setback"]
    p = load_params()
    w, margin = p.get("energy.planner.discomfort_wh_per_kh"), p.get("energy.planner.discomfort_margin_c")
    hcfg = R.load_harness_config()
    env = R.load_config(REPO / hcfg["paths"]["environment_model"])
    base = next(s for s in load_scenarios(REPO / hcfg["paths"]["scenarios"]) if s["id"] == c["template"])
    sc, leave, arrive = scenario(base, away, tout, strat, e1["after_arrival_min"] * 60.0)
    sc["user_settings_by_baseline"] = {"proposed": {"away_strategy": strat}}
    if day is not None:
        wc = dict(hcfg["weather"])
        wc["years"] = {"x": c["measured"]["years"]}
        series = W.load_series(wc, REPO, "x")
        hh, mm = str(sc["initial"].get("time_of_day", "00:00")).split(":")
        start = pd.Timestamp(day) + pd.Timedelta(hours=int(hh), minutes=int(mm))
        sc = W.apply_to_scenario(sc, series, start, wc, float(env.get("thermal.solar_luminous_efficacy_lm_per_w")))
    r = R.run_fast(Run(sc, "proposed", 1, sc["seed"]), hcfg, env, make_controller(hcfg["controllers"]["proposed"]), "proposed")
    d = r.df
    sp = 26.0 + p.get("interaction_rules.I5_ceiling_fan_setpoint_relax_c")   # EXP-1 과 같은 기준
    win = d[d.time_s >= leave]
    ac_wh = float(win["power.ac_w"].sum() / 3600.0)
    after = d[d.time_s >= arrive]
    disc = float(np.clip(after["truth.temperature_c"] - (sp + margin), 0, None).sum() / 3600.0)
    return {"part": part, "day": day or "", "outdoor_c": tout, "away_h": away, "strategy": strat, "ac_wh": round(ac_wh, 1),
            "discomfort_kh": round(disc, 4), "cost": round(ac_wh + w * disc, 1),
            "temp_at_arrival_c": round(float(np.interp(arrive, d.time_s, d["truth.temperature_c"])), 2)}


def boot(x: pd.DataFrame, n: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    g = [v.ratio.to_numpy() for _, v in x.groupby("unit")]
    s = [np.median(np.concatenate([g[j] for j in rng.integers(len(g), size=len(g))])) for _ in range(n)]
    return float(np.quantile(s, 0.025)), float(np.quantile(s, 0.975))


def main() -> None:
    h = yaml.safe_load((REPO / "config" / "harness.yaml").read_text(encoding="utf-8"))
    c = h["away_strategy_check"]
    jobs = [("A", t, a, s, None) for t in c["grid"]["outdoor_c"] for a in c["grid"]["away_h"] for s in c["strategies"]]
    m = c["measured"]
    rng = np.random.default_rng(int(m["seed"]))
    days = [d for d in pd.date_range(f"{m['years'][0]}-06-01", f"{m['years'][-1]}-09-29", freq="D") if d.month in m["months"]]
    pick = sorted(days[int(i)] for i in rng.choice(len(days), size=int(m["days"]), replace=False))
    jobs += [("B", -1.0, a, s, f"{d:%Y-%m-%d}") for d in pick for a in m["away_h"] for s in c["strategies"]]
    with ProcessPoolExecutor(int(c["workers"])) as ex:
        rows = list(ex.map(one, *zip(*jobs)))
    df = pd.DataFrame(rows)
    out = REPO / "results" / "away_check"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "runs.csv", index=False)
    lines = ["# 외출 전략 확인 — 동결 제어기 v1.29 전체 (고속) · auto vs off vs setback", ""]
    for part, g in df.groupby("part"):
        piv = g.pivot_table(index=["day", "outdoor_c", "away_h"], columns="strategy", values="cost").reset_index()
        piv["unit"] = piv["day"] + "|" + piv["outdoor_c"].astype(str)
        piv["ratio"] = piv["auto"] / piv["off"]
        lo, hi = boot(piv, int(c["bootstrap"]), int(m["seed"]))
        mean = g.groupby("strategy")[["cost", "ac_wh", "discomfort_kh"]].mean()
        lines += [f"## {'A 외기 고정 격자' if part == 'A' else 'B 2024 실측 기상'} — 실행 {len(piv)}쌍", "",
                  "| 전략 | 평균 비용 | 에어컨 Wh | 불쾌 K·h |", "|---|---:|---:|---:|"]
        for s, r in mean.iterrows():
            lines.append(f"| {s} | {r.cost:.1f} | {r.ac_wh:.1f} | {r.discomfort_kh:.3f} |")
        lines += ["", f"auto / off 비용 비 중앙값 **{piv.ratio.median():.3f}** [{lo:.3f}, {hi:.3f}] (묶음 = {'외기' if part == 'A' else '날'}) · "
                  f"auto 가 쌈 {int((piv.auto < piv.off - 1e-6).sum())} · 비쌈 {int((piv.auto > piv.off + 1e-6).sum())} · 같음 {int((abs(piv.auto - piv.off) <= 1e-6).sum())}", ""]
        by = piv.groupby("away_h")[["auto", "off"]].mean().round(1)
        lines += ["| 외출 h | auto | off |", "|---:|---:|---:|"] + [f"| {a:g} | {r.auto} | {r.off} |" for a, r in by.iterrows()] + [""]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
