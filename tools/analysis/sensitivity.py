"""환경 모델 민감도 분석 (W13 T13.v3) — 참값 계수를 하나씩 바꿔 제안 제어기의 판정 · 지표가 어떻게 변하는지.

    uv run python tools/analysis/sensitivity.py      → results/tables/sensitivity_runs.csv · sensitivity_summary.csv

설정: config/harness.yaml sensitivity (변수 · 값 · 지표 · 병렬 수). 고속 시나리오 전부 × 제안 제어기 × 반복 1.
판정에서 기준선 비교(baseline_*) 항목은 뺀다 — 다른 기준선을 함께 돌리지 않으므로 (나머지 판정만으로 통과 여부를 본다).
"""

from __future__ import annotations

import copy
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from env_model import load_config  # noqa: E402
from harness import criteria as C  # noqa: E402
from harness.controllers import make_controller  # noqa: E402
from harness.runner import judge_group, load_harness_config, run_fast  # noqa: E402
from harness.scenario import expand_runs, load_scenarios  # noqa: E402

PROPOSED = "proposed"


def _one(args):
    label, overrides, sid = args
    hcfg = load_harness_config()
    env_cfg = load_config(REPO / hcfg["paths"]["environment_model"])
    if overrides:
        env_cfg = env_cfg.with_overrides(overrides)
    sc = next(s for s in load_scenarios(REPO / hcfg["paths"]["scenarios"]) if s["id"] == sid)
    sc = copy.deepcopy(sc)
    sc["pass_criteria"] = [c for c in (sc.get("pass_criteria") or []) if "baseline_" not in c]
    run = expand_runs([sc], baselines=[PROPOSED], reps=1)[0]
    spec = hcfg["controllers"][PROPOSED]
    try:
        r = run_fast(run, hcfg, env_cfg, make_controller(spec), spec)
        judge_group([r])
        status = r.status
    except Exception as exc:                       # 실행 실패도 결과로 남긴다
        return {"variant": label, "scenario": sid, "status": C.ERROR, "note": f"{type(exc).__name__}: {exc}"}
    row = {"variant": label, "scenario": sid, "status": status,
           "failed": " | ".join(c.text for c in r.criteria if c.status != C.PASS)}
    row.update({f"m.{k}": r.metrics.get(k) for k in hcfg["sensitivity"]["metrics"]})
    return row


def main() -> None:
    hcfg = load_harness_config()
    cfg = hcfg["sensitivity"]
    ids = [s["id"] for s in load_scenarios(REPO / hcfg["paths"]["scenarios"])
           if s["run_mode"] == "fast" and PROPOSED in s["baselines"]]
    variants = [(cfg["baseline_label"], {})] + [(f"{v['key'].split('.')[-1]}={x}", {v["key"]: x})
                                                for v in cfg["variants"] for x in v["values"]]
    jobs = [(label, ov, sid) for label, ov in variants for sid in ids]
    print(f"변수 {len(variants)}개 × 시나리오 {len(ids)}개 = {len(jobs)}회 · 병렬 {cfg['workers']}", flush=True)
    with ProcessPoolExecutor(max_workers=int(cfg["workers"])) as ex:
        rows = list(ex.map(_one, jobs))
    df = pd.DataFrame(rows)
    out = REPO / "results" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "sensitivity_runs.csv", index=False)
    base = df[df.variant == cfg["baseline_label"]].set_index("scenario")
    summ = []
    for label, g in df.groupby("variant", sort=False):
        g = g.set_index("scenario")
        row = {"variant": label, "pass": int((g.status == "PASS").sum()), "runs": len(g),
               "newly_failed": ", ".join(sorted(set(g.index[g.status != "PASS"]) - set(base.index[base.status != "PASS"])))}
        for m in cfg["metrics"]:
            a, b = pd.to_numeric(g[f"m.{m}"], errors="coerce"), pd.to_numeric(base[f"m.{m}"], errors="coerce")
            row[f"Δ{m}"] = float((a - b.reindex(a.index)).mean())
        summ.append(row)
    s = pd.DataFrame(summ)
    s.to_csv(out / "sensitivity_summary.csv", index=False)
    print(s.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
