"""물리 모드 채점 — 실험 로거 CSV(results/physics/raw)를 고속 모드와 같은 판정기로 평가한다 (W08 T8.6 · W10 T10.v1).

    uv run python scripts/physics_eval.py --scenarios B1,B2,B3 [--baselines proposed] [--reps 1]

로그 열 이름은 고속 모드와 같다 (nodes/experiment_logger_node.py) → harness.runner.finish_run · judge_group 을 그대로 쓴다.
결과: 화면 + results/physics/summary.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from env_model.config import load_config  # noqa: E402
from harness import criteria as C  # noqa: E402
from interfaces.log_columns import fill_act_from_topics
from harness.manifest import write_manifest  # noqa: E402
from harness.runner import RunResult, finish_run, judge_group, load_harness_config, write_summary  # noqa: E402
from harness.scenario import expand_runs, load_scenarios  # noqa: E402
from harness.timeline import build_timeline  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--baselines", default="proposed")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--dir", default="results/physics")       # 물리 조건 무작위화는 results/physics_random
    a = ap.parse_args()
    hcfg = load_harness_config()
    env_cfg = load_config(REPO / hcfg["paths"]["environment_model"])
    scen = load_scenarios(REPO / hcfg["paths"]["scenarios"])
    runs = expand_runs(scen, a.scenarios.split(","), a.baselines.split(","), a.reps)
    raw = REPO / a.dir / "raw"
    results: list[RunResult] = []
    groups: dict[str, list[RunResult]] = {}
    for run in runs:
        path = raw / f"{run.scenario_id}_{run.baseline}_{run.rep}.csv"
        if not path.exists():
            r = RunResult(run, C.PENDING, "physics", notes=[f"로그 없음: {path.relative_to(REPO)}"])
        else:
            df = fill_act_from_topics(pd.read_csv(path))
            r = finish_run(run, df, build_timeline(run.scenario), hcfg, env_cfg, 1.0, "physics",
                           [f"물리 모드 로그 {len(df)}행"])
        results.append(r)
        groups.setdefault(run.scenario_id, []).append(r)
    for rs in groups.values():
        judge_group(rs)
    for r in results:
        print(f"{r.run.run_id:<20} {r.status:<8} " + " · ".join(r.notes), flush=True)
        for c in r.criteria:
            print(f"    {c.status:<7} {c.text}  {c.detail}", flush=True)
    out = REPO / a.dir / "summary.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(out) if out.exists() else None
    write_summary(results, out)
    write_manifest(out.parent, {"kind": "physics_eval", "dir": a.dir})
    if old is not None:                                   # 이번에 채점한 실행만 바꾸고 나머지는 남긴다 (일부 시나리오만 재실행해도 요약이 줄지 않게)
        new = pd.read_csv(out)
        merged = pd.concat([old[~old.run_id.isin(new.run_id)], new], ignore_index=True).sort_values("run_id")
        merged.to_csv(out, index=False)


if __name__ == "__main__":
    main()
