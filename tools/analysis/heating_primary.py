"""난방 확장 트랙 주 비교 (docs/15 §4 · 등록 규칙 그대로) — 같은 (시나리오, 반복) 조건의 제안-H vs A-H · A′-H.

    uv run python tools/analysis/heating_primary.py [results/randomized_heating/summary.csv] [부 지표용 summary ...]
    → 화면 + results/tables/heating_primary.md

주 지표 1  환경 결과 기준 통과 (criteria_classes 3분류) — 통과율 차 · McNemar 정확 검정
주 지표 2  난방 기대비용 expected_cost_heating (비용 원 + 160 × 재실 중 추위 K·h) — 짝 비(제안 / 기준) 중앙값 · 부호 검정
구간       시나리오 묶음 부트스트랩 95 % (10,000회) · 다중 비교 Holm (주 비교 4개)
판정       구간이 0(차) · 1(비)을 넘지 않고 p_holm < 0.05 → '낫다' / 반대 방향 → '못하다' / 그 외 → '차이를 확인하지 못함'
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
BOOT, SEED = 10000, 20261028


def boot(df: pd.DataFrame, stat) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    groups = [g for _, g in df.groupby("scenario")]
    vals = [stat(pd.concat([groups[j] for j in rng.integers(len(groups), size=len(groups))])) for _ in range(BOOT)]
    return float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))


def holm(ps):
    order = np.argsort(ps)
    out, run = [0.0] * len(ps), 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - r) * ps[i]))
        out[i] = run
    return out


def pairs(df: pd.DataFrame, ref: str) -> pd.DataFrame:
    df = df[df.status != "SKIPPED"].copy()
    cls = table(df)
    df["outcome_ok"] = cls["outcome"].to_numpy()
    p = df[df.baseline == "proposed"].set_index(["scenario", "rep"])
    q = df[df.baseline == ref].set_index(["scenario", "rep"])
    m = p.join(q, lsuffix="_p", rsuffix="_r", how="inner").reset_index()
    return m[m.outcome_ok_p.notna() & m.outcome_ok_r.notna()]


def main() -> None:
    src = REPO / (sys.argv[1] if len(sys.argv) > 1 else "results/randomized_heating/summary.csv")
    df = pd.read_csv(src)
    rows = []
    for ref in ("A", "A2"):
        m = pairs(df, ref)
        a, b = m.outcome_ok_p.astype(bool), m.outcome_ok_r.astype(bool)
        n10, n01 = int((a & ~b).sum()), int((~a & b).sum())
        p = float(binomtest(n10, n10 + n01, 0.5).pvalue) if n10 + n01 else 1.0
        diff = float(a.mean() - b.mean())
        lo, hi = boot(m, lambda x: x.outcome_ok_p.astype(bool).mean() - x.outcome_ok_r.astype(bool).mean())
        rows.append({"비교": f"제안-H vs {ref}-H", "지표": "환경 결과 통과율 차", "n": len(m), "값": diff, "하한": lo, "상한": hi,
                     "p": p, "null": 0.0, "detail": f"제안 {a.mean():.1%} · 기준 {b.mean():.1%} · 불일치 {n10}:{n01}"})
        c = m.dropna(subset=["m.expected_cost_heating_p", "m.expected_cost_heating_r"])
        ratio = c["m.expected_cost_heating_p"] / c["m.expected_cost_heating_r"]
        c = c.assign(ratio=ratio)
        win, lose = int((ratio < 1 - 1e-9).sum()), int((ratio > 1 + 1e-9).sum())
        p2 = float(binomtest(win, win + lose, 0.5).pvalue) if win + lose else 1.0
        lo2, hi2 = boot(c, lambda x: float(np.median(x.ratio)))
        rows.append({"비교": f"제안-H vs {ref}-H", "지표": "난방 기대비용 비 (제안 / 기준)", "n": len(c), "값": float(np.median(ratio)),
                     "하한": lo2, "상한": hi2, "p": p2, "null": 1.0, "detail": f"제안이 쌈 {win} · 비쌈 {lose}"})
    for r, ph in zip(rows, holm([r["p"] for r in rows])):
        r["p_holm"] = ph
        better = (r["하한"] > r["null"]) if r["null"] == 0.0 else (r["상한"] < r["null"])
        worse = (r["상한"] < r["null"]) if r["null"] == 0.0 else (r["하한"] > r["null"])
        r["판정"] = "낫다" if better and ph < 0.05 else "못하다" if worse and ph < 0.05 else "차이를 확인하지 못함"
    lines = [f"# 난방 확장 주 비교 — 등록 docs/15 §4 · `{src.relative_to(REPO)}`", "",
             "| 비교 | 지표 | n | 값 [95 % 묶음 구간] | p_holm | 판정 | 세부 |", "|---|---|---:|---|---:|---|---|"]
    for r in rows:
        v = f"{r['값']:+.3f}" if r["null"] == 0.0 else f"{r['값']:.3f}"
        lines.append(f"| {r['비교']} | {r['지표']} | {r['n']} | {v} [{r['하한']:.3f}, {r['상한']:.3f}] | {r['p_holm']:.3g} | **{r['판정']}** | {r['detail']} |")
    # 부 지표 — 다른 실험의 통과율 (판정 없음)
    lines += ["", "## 부 지표 — 전체 · 환경 결과 기준 통과율 (판정 없음)", "", "| 실험 | 방식 | 전체 | 환경 결과 |", "|---|---|---:|---:|"]
    for s in [str(src.relative_to(REPO))] + sys.argv[2:]:
        d = pd.read_csv(REPO / s)
        d = d[d.status != "SKIPPED"]
        cl = table(d)
        for bl in ("proposed", "B", "A2", "A"):
            x = cl[cl.baseline == bl]
            if len(x):
                o = x.outcome.dropna()
                lines.append(f"| {s.split('/')[1]} | {bl} | {x['all'].mean():.1%} | {o.astype(bool).mean():.1%} (n {len(o)}) |")
    out = REPO / "results" / "tables" / "heating_primary.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
