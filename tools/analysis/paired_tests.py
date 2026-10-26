"""짝 검정 · 효과 크기 (A8 · 2026-10-26) — 같은 (시나리오, 반복) 조건의 제안 vs 기준선.

    uv run python tools/analysis/paired_tests.py <summary.csv> [...]   → 화면 + results/tables/paired_tests.md

  지표 1  환경 결과 기준 통과 (tools/analysis/criteria_classes.py 의 분류) — McNemar 정확 검정 (불일치 쌍 이항)
  지표 2  에너지 비 · 기대비용 비 (전력 + 2000 × 온도 불쾌 K·h) — 부호 검정 (제안 < 기준 쌍 비율)
  효과 크기  통과율 차 · 비의 중앙값 + **시나리오 묶음 부트스트랩** 95 % 구간 (반복끼리 닮은 점 반영)
  다중 비교  비교 전체에 Holm 보정 (p_holm) — 독립 가정 검정(McNemar · 부호)은 같은 시나리오 반복의 상관을 무시하므로
             판단은 묶음 부트스트랩 구간을 우선한다
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from criteria_classes import table  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
LAMBDA = 2000.0
BOOT = 5000


def cluster_boot(df: pd.DataFrame, stat, seed: int = 0) -> tuple[float, float]:
    groups = [g for _, g in df.groupby("scenario")]
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(BOOT):
        pick = pd.concat([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        vals.append(stat(pick))
    lo, hi = np.nanpercentile(vals, [2.5, 97.5])
    return float(lo), float(hi)


def holm(ps: list[float]) -> list[float]:
    order = np.argsort(ps)
    out, run = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i]))
        out[i] = run
    return out


def main() -> None:
    rows = []
    for src in sys.argv[1:]:
        df = pd.read_csv(src)
        df = df[df.status != "SKIPPED"].copy()
        if "rep" not in df.columns:
            df["rep"] = df.run_id.str.rsplit("_", n=1).str[-1].astype(int)
        t = table(df)
        t["rep"] = df["rep"].values
        df["cost"] = pd.to_numeric(df["m.energy_compare_wh"], errors="coerce") + LAMBDA * pd.to_numeric(df["m.temp_excess_ch"], errors="coerce")
        for ref in ("A", "A2", "B"):
            if ref not in set(df.baseline):
                continue
            a = t[t.baseline == "proposed"][["scenario", "rep", "outcome"]]
            b = t[t.baseline == ref][["scenario", "rep", "outcome"]]
            m = a.merge(b, on=["scenario", "rep"], suffixes=("_p", "_r")).dropna()
            m["outcome_p"], m["outcome_r"] = m.outcome_p.astype(bool), m.outcome_r.astype(bool)
            n10, n01 = int((m.outcome_p & ~m.outcome_r).sum()), int((~m.outcome_p & m.outcome_r).sum())
            p = binomtest(n10, n10 + n01, 0.5).pvalue if n10 + n01 else 1.0
            diff = m.outcome_p.mean() - m.outcome_r.mean()
            lo, hi = cluster_boot(m, lambda g: g.outcome_p.mean() - g.outcome_r.mean())
            rows.append({"src": Path(src).parent.name or src, "ref": ref, "measure": "환경 결과 통과율 차 (제안 − 기준)", "pairs": len(m),
                         "effect": diff, "lo": lo, "hi": hi, "p": p, "detail": f"제안만 통과 {n10} · 기준만 통과 {n01}"})
            for col, label in (("m.energy_compare_wh", "에너지 비 (제안 / 기준 · 중앙값)"), ("cost", "기대비용 비 (λ 2000 · 중앙값)")):
                pa = df[df.baseline == "proposed"][["scenario", "rep", col]]
                pb = df[df.baseline == ref][["scenario", "rep", col]]
                mm = pa.merge(pb, on=["scenario", "rep"], suffixes=("_p", "_r"))
                mm["ratio"] = pd.to_numeric(mm[f"{col}_p"], errors="coerce") / pd.to_numeric(mm[f"{col}_r"], errors="coerce")
                mm = mm.replace([np.inf, -np.inf], np.nan).dropna(subset=["ratio"])
                k = int((mm.ratio < 1).sum())
                p = binomtest(k, len(mm), 0.5).pvalue if len(mm) else 1.0
                lo, hi = cluster_boot(mm, lambda g: g.ratio.median())
                rows.append({"src": Path(src).parent.name or src, "ref": ref, "measure": label, "pairs": len(mm),
                             "effect": float(mm.ratio.median()), "lo": lo, "hi": hi, "p": p, "detail": f"제안이 작은 쌍 {k}/{len(mm)}"})
    r = pd.DataFrame(rows)
    r["p_holm"] = holm(r.p.tolist())
    lines = ["# 짝 검정 · 효과 크기 (제안 vs 기준선 · 같은 조건 쌍)", "",
             "효과 [묶음 부트스트랩 95 %] · p = McNemar(통과) / 부호 검정(비) · p_holm = 비교 전체 Holm 보정", "",
             "| 자료 | 기준 | 측정 | 쌍 | 효과 [95 %] | p | p_holm | 비고 |", "|---|---|---|---:|---|---:|---:|---|"]
    for _, x in r.iterrows():
        lines.append(f"| {x.src} | {x.ref} | {x.measure} | {x.pairs} | {x.effect:.3f} [{x.lo:.3f}, {x.hi:.3f}] | {x.p:.2g} | {x.p_holm:.2g} | {x.detail} |")
    out = REPO / "results" / "tables" / "paired_tests.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r.to_csv(out.with_suffix(".csv"), index=False)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
