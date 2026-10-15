"""W13 결과 분석 — 평가 지표 16종 산출 (docs/03 §7 · W13 T13.1 · T13.v1 · T13.w1).

    uv run python scripts/analyze_results.py           # → results/tables/w13_metrics.csv · w13_tier2_compare.csv · w13_metrics.md

입력: 고속 요약(results/summary.csv) · 물리 요약(results/physics/summary.csv) — 실행마다 `m.*` 지표 열
      · 끼임 스윕(#4 · #5) · 창문 안전 시험(#4 오검출) 결과
판정: 목표는 thresholds.yaml targets · 지표 → 목표 매핑 · 판정 방식은 config/harness.yaml analysis
  max / min   제안 제어기의 모든 실행이 목표 안 (agg: mean 이면 평균으로)
  reduce      비교 대상(ref)과 같은 시나리오 · 반복끼리 짝지어 합계 기준 감소율(%) ≥ 목표
  better      비교 대상보다 평균이 높음
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from controller.params import load_params  # noqa: E402

PROPOSED = "proposed"


def load_runs(cfg: dict) -> pd.DataFrame:
    frames = []
    for mode, key in (("fast", "fast_summary"), ("physics", "physics_summary")):
        p = REPO / cfg[key]
        if p.exists():
            df = pd.read_csv(p)
            df = df[df.status != "SKIPPED"].copy()
            df["mode"] = mode
            frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _fmt(x: float, nd: int = 2) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}".rstrip("0").rstrip(".")


def eval_metric(spec: dict, runs: pd.DataFrame, targets: dict) -> dict:
    col = f"m.{spec['col']}"
    sel = runs if spec.get("mode", "all") == "all" else runs[runs["mode"] == spec["mode"]]
    if col not in sel.columns:
        return {"n": 0, "verdict": "자료 없음"}
    if spec.get("scenarios"):
        sel = sel[sel.scenario.isin(spec["scenarios"])]
    sel = sel[~sel.scenario.isin(list((spec.get("exempt") or {}).keys()))]
    sel = sel.assign(v=_num(sel[col]) * float(spec.get("scale", 1.0)))
    if spec.get("only_with"):
        sel = sel[_num(sel[f"m.{spec['only_with']}"]).notna() | (sel.baseline != PROPOSED)]
    p = sel[(sel.baseline == PROPOSED) & sel.v.notna()]
    target = (float(targets[spec["target"]]) * float(spec.get("target_scale", 1.0))
              if spec.get("target") else math.nan)
    row = {"n": len(p), "target": target, "mean": p.v.mean(), "worst": math.nan, "ref_mean": math.nan,
           "reduction_pct": math.nan, "pass_runs_pct": math.nan}
    kind = spec["kind"]
    if kind in ("max", "min"):
        if p.empty:
            return {**row, "verdict": "자료 없음"}
        tgt = p.scenario.map({k: float(v) * float(spec.get("target_scale", 1.0))
                              for k, v in (spec.get("target_by_scenario") or {}).items()}).fillna(target)
        ok = p.v <= tgt + 1e-9 if kind == "max" else p.v >= tgt - 1e-9
        row["worst"] = p.v.max() if kind == "max" else p.v.min()
        row["pass_runs_pct"] = 100.0 * ok.mean()
        if spec.get("agg") == "mean":
            met = row["mean"] <= target if kind == "max" else row["mean"] >= target
        else:
            met = bool(ok.all())
        row["fail_runs"] = ", ".join(p[~ok].run_id.tolist()[:8])
        return {**row, "verdict": "달성" if met else "미달"}
    # 비교형 — 같은 (모드 · 시나리오 · 반복) 짝
    ref = sel[(sel.baseline == spec["ref"]) & sel.v.notna()]
    if spec.get("ref_pass_only"):
        ref = ref[ref.status == "PASS"]
    ref = ref[["mode", "scenario", "rep", "v"]]
    pair = p[["mode", "scenario", "rep", "v", "run_id"]].merge(ref, on=["mode", "scenario", "rep"], suffixes=("", "_ref"))
    row["n"] = len(pair)
    if pair.empty:
        return {**row, "verdict": "자료 없음"}
    row["mean"], row["ref_mean"] = pair.v.mean(), pair.v_ref.mean()
    if kind == "reduce":
        tot_ref = pair.v_ref.sum()
        row["reduction_pct"] = 100.0 * (tot_ref - pair.v.sum()) / tot_ref if tot_ref > 0 else math.nan
        per = 100.0 * (pair.v_ref - pair.v) / pair.v_ref.where(pair.v_ref > 0)
        row["pass_runs_pct"] = 100.0 * (per >= target).mean()
        row["worst"] = per.min()
        return {**row, "verdict": "달성" if row["reduction_pct"] >= target else "미달"}
    better = (pair.v > pair.v_ref + 1e-9).groupby(pair.scenario).mean()
    worse = (pair.v < pair.v_ref - 1e-9).groupby(pair.scenario).mean()
    row["pass_runs_pct"] = 100.0 * (pair.v >= pair.v_ref - 1e-9).mean()
    row["fail_runs"] = ", ".join(sorted(worse[worse > 0].index))
    row["better_scenarios"] = int((better > 0).sum())
    return {**row, "verdict": "달성" if row["mean"] > row["ref_mean"] else "미달"}


def pinch_metrics(cfg: dict, targets: dict) -> list[dict]:
    """#4 감지 성공률 · 오검출률 · #5 (끼임 스윕) — 물리 끼임 시험 결과 파일에서."""
    out = []
    sw = REPO / cfg["pinch_sweep"]
    if sw.exists():
        d_all = pd.read_csv(sw)
        d = d_all[d_all.contact_peak_n > 0]               # 접촉이 없던 시행(물체가 창턱에 가라앉음 · W12 한계)은 끼임 시험이 아니다
        skipped = d_all[d_all.contact_peak_n <= 0].groupby(["object", "zone"]).size()
        rate = 100.0 * d.detected.mean()
        out.append({"no": 4, "name": "끼임 감지 성공률", "col": "pinch_sweep.detected", "n": len(d), "mode": "physics",
                    "target": float(targets["pinch_detection_rate_pct"]), "mean": rate, "worst": rate,
                    "verdict": "달성" if rate >= float(targets["pinch_detection_rate_pct"]) else "미달",
                    "fail_runs": "접촉 없음 제외: " + " · ".join(f"{o} {z.split(' (')[0]} {n}회" for (o, z), n in skipped.items())})
        fmax = d.contact_peak_n.max()
        out.append({"no": 5, "name": "최대 접촉 반력 (끼임 스윕)", "col": "pinch_sweep.contact_peak_n", "n": len(d),
                    "mode": "physics", "target": float(targets["max_contact_force_n"]), "mean": d.contact_peak_n.mean(),
                    "worst": fmax, "verdict": "달성" if fmax <= float(targets["max_contact_force_n"]) else "미달"})
    ws = REPO / cfg["window_safety"]
    if ws.exists():
        items = json.loads(ws.read_text(encoding="utf-8"))
        it = next((i for i in items if "오검출" in i["item"]), None)
        if it:
            out.append({"no": 4, "name": "끼임 오검출률 (정상 폐쇄)", "col": "window_safety_test", "n": None, "mode": "physics",
                        "target": float(targets["false_trigger_rate_pct"]), "mean": 0.0 if it["ok"] else math.nan,
                        "worst": math.nan, "verdict": "달성" if it["ok"] else "미달", "fail_runs": it["detail"]})
    return out


def tier2_compare(runs: pd.DataFrame, cfg: dict, tier2: list[str]) -> pd.DataFrame:
    """Tier 2 시나리오 × 기준선 — 판정 통과율 · 주요 지표 평균 (T13.4 막대그래프 입력)."""
    t = runs[runs.scenario.isin(tier2) & runs.baseline.isin(["A", "B", PROPOSED])].copy()
    t["pass"] = (t.status == "PASS").astype(float)
    agg = {"pass": "mean", "run_id": "count"}
    for c in cfg["tier2_compare"]:
        if f"m.{c}" in t.columns:
            t[f"m.{c}"] = _num(t[f"m.{c}"])
            agg[f"m.{c}"] = "mean"
    g = t.groupby(["scenario", "baseline"]).agg(agg).rename(columns={"run_id": "runs", "pass": "pass_rate"})
    return g.reset_index()


def main() -> None:
    hcfg = yaml.safe_load(open(REPO / "config" / "harness.yaml", encoding="utf-8"))
    cfg = hcfg["analysis"]
    targets = load_params().get("targets")
    runs = load_runs(cfg)
    rows = [{"no": s["num"], "name": s["name"], "col": s["col"], "mode": s.get("mode", "all"), "kind": s["kind"],
             "ref": s.get("ref", ""), **eval_metric(s, runs, targets)} for s in cfg["metrics"]]
    rows += pinch_metrics(cfg, targets)
    res = pd.DataFrame(rows).sort_values("no", kind="stable")
    out = REPO / cfg["out_dir"]
    out.mkdir(parents=True, exist_ok=True)
    res.to_csv(out / "w13_metrics.csv", index=False)

    scen = yaml.safe_load(open(REPO / hcfg["paths"]["scenarios"], encoding="utf-8"))["scenarios"]
    tier2 = [s["id"] for s in scen if s.get("tier") == 2]
    cmp_ = tier2_compare(runs, cfg, tier2)
    cmp_.to_csv(out / "w13_tier2_compare.csv", index=False)

    # 사람이 읽는 표 (발표 · 보고서 초안)
    lines = ["| # | 지표 | 모드 | n | 제안 평균 | 최악 | 비교 대상 평균 | 감소율 % | 목표 | 판정 |", "|---|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for r in res.to_dict("records"):
        tgt = (f"≥ {_fmt(r['target'])} % 감소" if r.get("kind") == "reduce" else
               f"> {r['ref']}" if r.get("kind") == "better" else _fmt(r.get("target", math.nan)))
        lines.append(f"| {r['no']} | {r['name']} | {r['mode']} | {r['n'] if r['n'] is not None else '–'} | {_fmt(r['mean'])} | "
                     f"{_fmt(r.get('worst', math.nan))} | {_fmt(r.get('ref_mean', math.nan))} | "
                     f"{_fmt(r.get('reduction_pct', math.nan), 1)} | {tgt} | {r['verdict']} |")
    pr = runs[runs.baseline == PROPOSED]
    head = [f"실행 {len(runs)}회 (고속 {int((runs['mode'] == 'fast').sum())} · 물리 {int((runs['mode'] == 'physics').sum())}) · "
            f"제안 제어기 판정 통과 {int((pr.status == 'PASS').sum())}/{len(pr)}", ""]
    (out / "w13_metrics.md").write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    print("\n".join(head + lines))
    ex = [f"- #{s['num']} {s['name']} — {k} 제외: {v}" for s in cfg["metrics"] for k, v in (s.get("exempt") or {}).items()]
    if ex:
        (out / "w13_metrics.md").write_text("\n".join(head + lines + ["", "제외 (지표 목표가 시나리오 전제와 다름):"] + ex) + "\n",
                                           encoding="utf-8")
        print("\n제외:\n" + "\n".join(ex))
    miss = res[res.verdict == "미달"]
    if not miss.empty:
        print("\n미달 항목 — 실패 실행:")
        for r in miss.to_dict("records"):
            print(f"  #{r['no']} {r['name']}: {r.get('fail_runs') or ''}")


if __name__ == "__main__":
    main()
