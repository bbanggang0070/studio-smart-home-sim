"""EXP-H — 바닥난방 외출 전략 비교 (docs/14 §4.5 · docs/15 H-RQ3) — 동결 제어기(지금 코드) 그대로, 설정값만 바꾼 인스턴스.

틀: H4 (출근 → 귀가) · 외출 길이 × 외기온 격자 · 전략 6종:
  need_based  셋백 16 °C + 필요 기반 프리히팅 (v1.31-H 기본 — 부족 K × 75 분/K · 상한 3 h · 외출당 한 번)
  fixed_120   셋백 16 °C + 고정 2 h (v1.30-H 재현) · no_preheat 프리히팅 없음 · off_need 끄기 12 °C + 필요 기반 · keep 집 목표 유지
비용(원) = 가스 · 전기 요금 · 귀가 뒤 추위 = 귀가 ~ 귀가 + 2 h 의 (20 °C − 실내)+ K·h · 기대비용 = 비용 + 160 원/K·h × 추위 (harness metrics heating)
결과: results/exp_heating_away<접미사>/runs.csv · summary.md (요약은 archive/<제어기 버전> 으로)
    uv run python tools/energy/exp_heating_away.py _v131   # v1.31-H 동결 실행 (2026-10-29)
    uv run python tools/energy/exp_heating_away.py _v132   # v1.32-H — 건물 3종 (basic · old · old_light)

    uv run python tools/energy/exp_heating_away.py
"""

from __future__ import annotations

import copy
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from controller.params import ControllerParams, load_params  # noqa: E402
from controller.smart_home import SmartHomeController  # noqa: E402
from env_model import load_config  # noqa: E402
from harness import runner as R  # noqa: E402
from harness.scenario import Run, load_scenarios  # noqa: E402

STRATS = {   # (외출 전략, 셋백 °C, 프리히팅 설정 {heating.*}) — v1.31-H (2026-10-29)
    "need_based": ("setback", 16.0, {}),                                                          # v1.31-H 기본 (필요 기반)
    "fixed_120": ("setback", 16.0, {"preheat_need_margin_c": -100.0, "preheat_recover_min_per_k": 1e6,
                                    "preheat_lead_max_min": 120.0}),                               # v1.30-H 의 고정 2 h 재현
    "no_preheat": ("setback", 16.0, {"preheat_need_margin_c": 100.0}),
    "off_need": ("off", 16.0, {}),                                                                 # 끄기(12 °C) + 필요 기반
    "keep": ("setback", 21.0, {"preheat_need_margin_c": 100.0}),
}
BUILDINGS = R.load_harness_config()["building_presets"]   # [v1.32-H M5] basic · old · old_light (config/harness.yaml · building_calibration.py)
AWAY_H = [4.0, 8.0, 10.0, 12.0]
OUT_C = [-10.0, -3.0, 3.0]
LEAVE_S = 1800.0


def scenario(base: dict, away_h: float, tout: float) -> tuple[dict, float]:
    sc = copy.deepcopy(base)
    arrive = LEAVE_S + away_h * 3600.0
    sc["id"] = f"EXPH_{away_h:g}h_{int(tout)}C"
    sc["external"]["outdoor_temp_c"] = tout
    sc["duration_s"] = arrive + 7200.0
    sc["log_interval_s"] = 10
    sc["injections"] = [{"at_s": LEAVE_S, "door": "open_close", "label": "leave", "open_s": 8},
                        {"at_s": arrive, "door": "open_close", "label": "arrive", "open_s": 8}]
    sc["events"] = [{"at_s": LEAVE_S + 4, "set": {"occupancy": False, "occupant_zone": "none"}},
                    {"at_s": arrive, "set": {"occupancy": True, "occupant_zone": "room"}}]
    sc["pass_criteria"], sc["baselines"], sc["repeat"] = [], ["proposed"], 1
    return sc, arrive


def one(args) -> dict:
    away_h, tout, strat, bld = args
    hcfg = R.load_harness_config()
    env0 = load_config(REPO / hcfg["paths"]["environment_model"])
    base = next(s for s in load_scenarios(REPO / "config" / "scenarios_heating.yaml") if s["id"] == "H4")
    sc, arrive = scenario(base, away_h, tout)
    env = env0.with_overrides({**sc["environment_overrides"], **BUILDINGS[bld]})
    p0 = load_params()
    th, modes = copy.deepcopy(p0.th), copy.deepcopy(p0.modes)
    kind, sb, pre = STRATS[strat]
    modes["energy"]["away_heating_strategy"], modes["energy"]["away_heating_setback_c"] = kind, sb
    th["heating"].update(pre)
    ctrl = SmartHomeController(ControllerParams(th, modes))
    r = R.run_fast(Run(sc, "proposed", 1, sc["seed"]), hcfg, env, ctrl, "proposed")
    d = r.df
    hc = hcfg["metrics"]["heating"]
    win = d[(d.time_s >= arrive) & (d.time_s <= arrive + 7200)]
    dt_h = float(d.time_s.iloc[1] - d.time_s.iloc[0]) / 3600.0
    cold = float(np.clip(20.0 - win["truth.temperature_c"], 0, None).sum() * dt_h)
    gas = float(d["energy_wh.boiler_gas"].iloc[-1]) / 1000.0
    elec = float(sum(d[c].iloc[-1] for c in d.columns if c.startswith("energy_wh.") and c != "energy_wh.boiler_gas")) / 1000.0
    cost = gas * hc["gas_won_per_kwh"] + elec * hc["electric_won_per_kwh"]
    t1 = float(np.interp(arrive + 3600, d.time_s, d["truth.temperature_c"]))
    return {"building": bld, "away_h": away_h, "outdoor_c": tout, "strategy": strat, "gas_kwh": round(gas, 3), "cost_won": round(cost, 1),
            "cold_after_arrival_kh": round(cold, 3), "expected_cost_won": round(cost + hc["cold_won_per_kh"] * cold, 1),
            "temp_at_arrival": round(float(np.interp(arrive, d.time_s, d["truth.temperature_c"])), 2),
            "temp_1h_after": round(t1, 2), "min_temp": round(float(d["truth.temperature_c"].min()), 2)}


def main() -> None:
    jobs = [(a, t, s, b) for a in AWAY_H for t in OUT_C for s in STRATS for b in BUILDINGS]
    with ProcessPoolExecutor(24) as ex:
        rows = list(ex.map(one, jobs))
    df = pd.DataFrame(rows)
    out = REPO / "results" / ("exp_heating_away" + (sys.argv[1] if len(sys.argv) > 1 else ""))
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "runs.csv", index=False)
    piv = df.pivot_table(index=["building", "outdoor_c", "away_h"], columns="strategy", values="expected_cost_won").round(0)
    best = piv.idxmin(axis=1)
    mean = df.groupby(["building", "strategy"])[["cost_won", "cold_after_arrival_kh", "expected_cost_won", "temp_1h_after", "min_temp"]].mean().round(2)
    tag = sys.argv[1].lstrip("_") if len(sys.argv) > 1 else "현재"
    lines = [f"# EXP-H 바닥난방 외출 전략 — 동결 제어기 {tag} · 설정값만 다른 인스턴스 · H4 틀 · 건물 {' · '.join(BUILDINGS)}", "",
             "## 전략별 평균 (외출 4 · 8 · 10 · 12 h × 외기 −10 · −3 · 3 °C)", "", mean.to_string(), "",
             "## 조건별 기대비용(원) — 가장 싼 전략", "", piv.assign(best=best).to_string()]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
