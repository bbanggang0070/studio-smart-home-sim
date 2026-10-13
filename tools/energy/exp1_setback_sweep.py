"""EXP-1 — 셋백 vs 끄기 손익분기 외출 시간 T* (docs/08 §5.4 · W12 T12.w2). 고속 모드 · 제안 제어기.

    uv run python tools/energy/exp1_setback_sweep.py

외출 시간 × 외기온 × 전략(셋백 +2 °C · 끄기 · 끄기 + 예측 프리쿨링) — C16 을 틀로 쓴다 (13:00 외출 · 일사 이벤트).
비용 = 전력량 Wh(외출 ~ 귀가 후 60분) + 2,000 × 귀가 후 불쾌(냉방 목표 + 1 °C 초과 K·h) — 계획기(energy.planner)와 같은 정의
T*(외기온) = 끄는 쪽(끄기 · 프리쿨링 중 싼 것)이 셋백보다 비싸지 않은 가장 짧은 외출
결과: results/exp1/runs.csv · t_star.csv
"""

from __future__ import annotations

import copy
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from controller.params import load_params  # noqa: E402
from harness import runner as R  # noqa: E402
from harness.controllers import make_controller  # noqa: E402
from harness.scenario import Run, load_scenarios  # noqa: E402


def scenario(base: dict, away_h: float, tout: float, strategy: str, after_s: float) -> dict:
    sc = copy.deepcopy(base)
    leave = next(i for i in sc["injections"] if i.get("label") == "leave")["at_s"]
    arrive = leave + away_h * 3600.0
    sc["id"] = f"EXP1_{away_h:g}h_{int(tout)}C_{strategy}"
    sc["external"]["outdoor_temp_c"] = tout
    sc["injections"] = [i for i in sc["injections"] if i.get("label") != "arrive"] + [
        {"at_s": arrive, "door": "open_close", "label": "arrive", "open_s": 8}]
    ev = []
    for e in sc.get("events", []):
        s = {k: v for k, v in e["set"].items() if k != "outdoor_temp_c"}
        if "occupancy" in s and s["occupancy"]:
            e = {"at_s": arrive, "set": s}                       # 귀가 이벤트 시각을 옮긴다
        elif s:
            e = {"at_s": e["at_s"], "set": s}
        else:
            continue
        ev.append(e)
    sc["events"] = ev
    sc["duration_s"] = arrive + after_s
    sc["user_settings_by_baseline"] = {"proposed": {"away_strategy": {"precool": "auto_precool"}.get(strategy, strategy)}}
    sc["run_mode"], sc["baselines"], sc["repeat"], sc["pass_criteria"] = "fast", ["proposed"], 1, []
    return sc, leave, arrive


def main() -> None:
    h = yaml.safe_load((REPO / "config" / "harness.yaml").read_text(encoding="utf-8"))
    c = h["exp1_setback"]
    p = load_params()
    w = p.get("energy.planner.discomfort_wh_per_kh")
    margin = p.get("energy.planner.discomfort_margin_c")
    hcfg = R.load_harness_config()
    env = R.load_config(REPO / hcfg["paths"]["environment_model"])
    base = next(s for s in load_scenarios(REPO / hcfg["paths"]["scenarios"]) if s["id"] == c["template"])
    sp = 26.0 + p.get("interaction_rules.I5_ceiling_fan_setpoint_relax_c")    # NORMAL 냉방 목표 + I5 완화 (실링팬)
    rows = []
    for tout in c["outdoor_c"]:
        for away in c["away_h"]:
            for strat in c["strategies"]:
                sc, leave, arrive = scenario(base, away, tout, strat, c["after_arrival_min"] * 60.0)
                r = R.run_fast(Run(sc, "proposed", 1, sc["seed"]), hcfg, env, make_controller(hcfg["controllers"]["proposed"]), "proposed")
                d = r.df
                win = d[d.time_s >= leave]
                e_wh = float((win["power.total_w"] if "power.total_w" in win else 0).sum() / 3600.0) if "power.total_w" in win else math.nan
                ac_wh = float(win["power.ac_w"].sum() / 3600.0) if "power.ac_w" in win else math.nan
                after = d[d.time_s >= arrive]
                disc = float(np.clip(after["truth.temperature_c"] - (sp + margin), 0, None).sum() / 3600.0)
                t_arr = float(np.interp(arrive, d.time_s, d["truth.temperature_c"]))
                rows.append({"outdoor_c": tout, "away_h": away, "strategy": strat, "ac_wh": round(ac_wh, 1),
                             "discomfort_kh": round(disc, 3), "cost": round(ac_wh + w * disc, 1), "temp_at_arrival_c": round(t_arr, 2)})
                print(rows[-1], flush=True)
    df = pd.DataFrame(rows)
    out = REPO / "results" / "exp1"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "runs.csv", index=False)
    ts = []
    for tout, g in df.groupby("outdoor_c"):
        t = math.inf
        for away, gg in g.groupby("away_h"):
            cost = gg.set_index("strategy")["cost"]
            if min(cost.get("off", math.inf), cost.get("precool", math.inf)) <= cost["setback"]:
                t = away
                break
        ts.append({"outdoor_c": tout, "t_star_h": t})
    pd.DataFrame(ts).to_csv(out / "t_star.csv", index=False)
    print(df.pivot_table(index=["outdoor_c", "away_h"], columns="strategy", values="cost").round(0).to_string())
    print(pd.DataFrame(ts).to_string(index=False))


if __name__ == "__main__":
    main()
