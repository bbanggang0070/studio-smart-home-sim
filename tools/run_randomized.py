"""무작위 반복 실행 (docs/11 필수 조치 2) — 반복마다 참값 계수 · 외기를 뽑아 고속 시나리오 전체를 돌린다.

    uv run python tools/run_randomized.py [--reps 5] [--workers 16] [--ids C1,C8] [--profile shared_copies] [--no-raw]
        → results/randomized/summary.csv (실행마다 지표 · 판정 · 뽑은 조건) · raw/<run_id>.csv

설정: config/harness.yaml randomization. 판정 · 지표는 동결된 정의(config/freeze.yaml)를 그대로 쓴다 — 시작 때 점검한다.
같은 (시나리오, 반복) 은 모든 기준선이 같은 조건 · 반복 1 은 명목값.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from env_model import load_config  # noqa: E402
from harness.controllers import make_controller  # noqa: E402
from harness.runner import judge_group, load_harness_config, run_fast  # noqa: E402
from harness.randomize import draw, perturb_scenario  # noqa: E402
from harness.manifest import write_manifest  # noqa: E402
from harness.scenario import Run, load_scenarios, scenario_baselines  # noqa: E402


def profile_cfg(hcfg: dict, profile: str) -> dict:
    cfg = dict(hcfg["randomization"])
    if profile:
        cfg.update(cfg["profiles"][profile])          # truth_params · external · out_dir 를 프로파일 값으로
    return cfg


def one(args):
    sid, rep, profile, keep_raw, extra, only = args
    hcfg = load_harness_config()
    cfg = profile_cfg(hcfg, profile)
    for sect, vals in (cfg.get("harness_overrides") or {}).items():   # 프로파일의 하네스 설정 덮어쓰기 (예: 센서 결함 켬)
        hcfg[sect] = {**hcfg.get(sect, {}), **vals}
    env0 = load_config(REPO / hcfg["paths"]["environment_model"])
    sc0 = next(s for s in load_scenarios(REPO / hcfg["paths"]["scenarios"]) if s["id"] == sid)
    over, ext = draw(cfg, env0, int(sc0["seed"]) * 1000 + rep, nominal=(rep == 1 and cfg["nominal_first"]))
    env_cfg = env0.with_overrides(over)
    sc = perturb_scenario(sc0, ext)
    out = REPO / cfg["out_dir"] / "raw"
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for bl in [b for b in scenario_baselines(sc, extra) if not only or b in only]:
        run = Run(scenario=sc, baseline=bl, rep=rep, seed=int(sc["seed"]) + rep)
        spec = hcfg["controllers"][bl]
        r = run_fast(run, hcfg, env_cfg, make_controller(spec), spec)
        if keep_raw and r.df is not None:
            r.df.to_csv(out / f"{run.run_id}.csv", index=False)
        results.append(r)
    judge_group(results)
    cond = {**{f"p.{k}": (v if not isinstance(v, list) else v[3]) for k, v in over.items()},
            **{f"x.{k}": v[1] for k, v in ext.items()}}
    rows = []
    for r in results:
        row = {"run_id": r.run.run_id, "scenario": sid, "baseline": r.run.baseline, "rep": rep, "status": r.status,
               "criteria_pass": sum(c.status == "PASS" for c in r.criteria), "criteria_total": len(r.criteria),
               "criteria": json.dumps([[c.status, c.text, c.detail] for c in r.criteria], ensure_ascii=False), **cond}
        row.update({f"m.{k}": v for k, v in r.metrics.items()})
        rows.append(row)
    return rows


def main() -> None:
    hcfg = load_harness_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=hcfg["randomization"]["reps"])
    ap.add_argument("--workers", type=int, default=hcfg["randomization"]["workers"])
    ap.add_argument("--ids", default="")
    ap.add_argument("--profile", default="")
    ap.add_argument("--no-raw", action="store_true")   # 시계열을 저장하지 않는다 (디스크 절약 — 요약 · 판정만)
    ap.add_argument("--extra-baselines", default="")   # 예: A2 — A 를 돌리는 시나리오에서 A2 도 (harness extra_baselines · 2026-10-26)
    ap.add_argument("--only", default="")              # 이 기준선만 돌린다 (예: A,A2 — 제안 · B 는 이미 있는 결과와 짝 비교)
    ap.add_argument("--out-suffix", default="")        # 결과 폴더 뒤에 붙인다 (예: _a2)
    a = ap.parse_args()
    cfg = profile_cfg(hcfg, a.profile)
    chk = subprocess.run([sys.executable, str(REPO / "tools" / "check_freeze.py")], capture_output=True, text=True)
    print(chk.stdout.strip())
    if chk.returncode != 0:
        sys.exit("동결된 판정 · 지표가 바뀌었다 — docs/12 동결 개정을 먼저 기록할 것")
    scen = [s for s in load_scenarios(REPO / hcfg["paths"]["scenarios"]) if s["run_mode"] == "fast"]
    if a.ids:
        scen = [s for s in scen if s["id"] in a.ids.split(",")]
    extra = {x: "A" for x in a.extra_baselines.split(",") if x}
    only = [x for x in a.only.split(",") if x]
    jobs = [(s["id"], k, a.profile, not a.no_raw, extra, only) for s in scen for k in range(1, a.reps + 1)]
    print(f"시나리오 {len(scen)}개 × 반복 {a.reps} = {len(jobs)}묶음 · 병렬 {a.workers}", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for part in ex.map(one, jobs):
            rows += part
    df = pd.DataFrame(rows)
    out = REPO / (cfg["out_dir"] + a.out_suffix)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "summary.csv", index=False)
    write_manifest(out, {"kind": "randomized", "profile": a.profile or "default", "reps": a.reps, "runs": len(df)})
    p = df[df.baseline == "proposed"]
    print(f"실행 {len(df)}회 · 제안 판정 통과 {int((p.status == 'PASS').sum())}/{len(p)}")


if __name__ == "__main__":
    main()
