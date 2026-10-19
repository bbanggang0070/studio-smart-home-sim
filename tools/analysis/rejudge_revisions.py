"""판정 기준 사후 개정 감사 (docs/11 §6.1 · 필수 조치 1) — 지금 로그를 '개정 직전' 판정 기준과 현재 기준으로 함께 판정한다.

    uv run python tools/analysis/rejudge_revisions.py     → results/tables/criteria_revisions.csv · .md

개정 목록 = config/harness.yaml criteria_audit.revisions (시나리오 · 개정 직전 커밋).
옛 기준은 `git show <rev>:config/scenario_profiles.yaml` 에서 그 시나리오의 pass_criteria 를 가져온다.
로그 · 타임라인(앵커)은 현재 시나리오 정의를 쓴다 — '지금 동작이 옛 기준도 통과하나'를 본다.
옛 기준이 지금 로그에 없는 열 · 앵커를 쓰면 그 기준은 '평가 불가'로 따로 센다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from env_model.config import load_config  # noqa: E402
from harness import criteria as C  # noqa: E402
from harness.runner import finish_run, load_harness_config  # noqa: E402
from harness.scenario import expand_runs, load_scenarios  # noqa: E402
from harness.timeline import build_timeline  # noqa: E402
from interfaces.log_columns import fill_act_from_topics  # noqa: E402


def old_criteria(rev: str, sid: str) -> list[str] | None:
    text = subprocess.run(["git", "show", f"{rev}:config/scenario_profiles.yaml"], cwd=REPO,
                          capture_output=True, text=True, check=True).stdout
    for sc in yaml.safe_load(text)["scenarios"]:
        if sc["id"] == sid:
            return list(sc.get("pass_criteria") or [])
    return None


def load_log(run) -> tuple[pd.DataFrame | None, str]:
    fast = REPO / "results" / "raw" / f"{run.run_id}.csv"
    phys = REPO / "results" / "physics" / "raw" / f"{run.run_id}.csv"
    if run.scenario["run_mode"] == "physics" and phys.exists():
        return fill_act_from_topics(pd.read_csv(phys, low_memory=False)), "physics"
    if fast.exists():
        return pd.read_csv(fast, low_memory=False), "fast"
    return None, ""


def main() -> None:
    hcfg = load_harness_config()
    env_cfg = load_config(REPO / hcfg["paths"]["environment_model"])
    scen = {s["id"]: s for s in load_scenarios(REPO / hcfg["paths"]["scenarios"])}
    rows = []
    for rv in hcfg["criteria_audit"]["revisions"]:
        for sid in rv["scenarios"]:
            old = old_criteria(rv["base_rev"], sid)
            cur = list(scen[sid].get("pass_criteria") or [])
            runs = expand_runs([scen[sid]])
            res = []
            for run in runs:
                df, mode = load_log(run)
                if df is None:
                    continue
                res.append(finish_run(run, df, build_timeline(run.scenario), hcfg, env_cfg, 1.0, mode, []))
            for r in res:
                run = r.run
                peers = {o.run.baseline: o.metrics for o in res if o.run.rep == run.rep}
                for tag, crit in (("현재", cur), ("개정 전", old)):
                    if crit is None:
                        rows.append({"scenario": sid, "baseline": run.baseline, "rep": run.rep, "criteria": tag,
                                     "status": "시나리오 없음", "n_pass": 0, "n_fail": 0, "n_na": 0, "failed": ""})
                        continue
                    cr = C.evaluate(r.df, crit, run.scenario.get("expect") or {}, r.anchors, r.intervals,   # type: ignore[attr-defined]
                                    r.metrics, peers, own_baseline=run.baseline)
                    st = [c.status for c in cr]
                    n_fail = st.count(C.FAIL)
                    n_err = sum(s not in (C.PASS, C.FAIL, C.NA) for s in st)
                    rows.append({"scenario": sid, "baseline": run.baseline, "rep": run.rep, "criteria": tag,
                                 "status": C.FAIL if n_fail else ("평가 불가 포함" if n_err else C.PASS),
                                 "n_pass": st.count(C.PASS), "n_fail": n_fail, "n_na": st.count(C.NA) + n_err,
                                 "failed": " | ".join(f"{c.text} ({c.detail})" for c in cr if c.status == C.FAIL)[:300],
                                 "rev": rv["base_rev"], "note": rv["note"]})
    df = pd.DataFrame(rows)
    out = REPO / "results" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "criteria_revisions.csv", index=False)
    piv = (df.assign(ok=(df.status == C.PASS).astype(int))
             .pivot_table(index=["scenario", "baseline"], columns="criteria", values="ok", aggfunc="mean")
             .reindex(columns=["개정 전", "현재"]))
    lines = ["# 판정 기준 사후 개정 감사 — 같은 로그를 개정 전 · 현재 기준으로 (통과 비율)", "",
             "| 시나리오 | 기준선 | 개정 전 기준 통과 | 현재 기준 통과 |", "|---|---|---:|---:|"]
    for (sid, bl), r in piv.iterrows():
        lines.append(f"| {sid} | {bl} | {r['개정 전'] * 100:.0f} % | {r['현재'] * 100:.0f} % |")
    lines += ["", "개정 전 기준에서 제안이 실패한 기준 (반복 1):", ""]
    for _, r in df[(df.criteria == "개정 전") & (df.baseline == "proposed") & (df.rep == 1) & (df.status == C.FAIL)].iterrows():
        lines.append(f"- **{r.scenario}** — {r.failed}")
    (out / "criteria_revisions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
