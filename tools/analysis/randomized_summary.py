"""무작위 반복 결과 요약 (docs/11 필수 조치 2) — 판정 통과율 · 지표 평균의 95 % 신뢰구간 · 기준선과의 짝 비교.

    uv run python tools/analysis/randomized_summary.py   → results/tables/randomized_*.csv · randomized_summary.md
    uv run python tools/analysis/randomized_summary.py --kind weather   → measured_weather_*  (필수 조치 3 · 실측 기상)

통과율: Wilson 95 % 구간 (실행 독립 가정) + **시나리오 묶음 부트스트랩** 95 % 구간 (같은 시나리오의 반복은 서로 닮았다 —
        시나리오를 복원 추출해 통과율을 다시 계산 · 논문 보고값 · 2026-10-26) · 지표: 평균 ± t 분포 95 % 구간 (반복 = 표본)
    uv run python tools/analysis/randomized_summary.py --kind shared | heldout_r7 | physics_random   (공유 계수 · 보류 7차 · 물리 조건 무작위)
짝 비교: 같은 (시나리오, 반복) 조건에서 제안 − 기준선 차이의 평균 ± 95 % 구간 (공통 난수 — 조건 차이가 상쇄된다)
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "tables"
# 종류별 입력 · 출력 이름 · 제목 · 실패 표에 함께 적을 조건 열
KINDS = {
    "randomized": {"src": "results/randomized/summary.csv", "prefix": "randomized",
                   "title": "무작위 반복 결과 (고속 모드 · 반복 1 = 명목값 · 반복 2– = 참값 계수 · 외기 무작위)",
                   "cond": [("p.air_balance.base_infiltration_ach", "침기 ACH", ".2f"), ("x.outdoor_temp_c", "외기 Δ°C", "+.2f")]},
    "weather": {"src": "results/measured_weather/summary.csv", "prefix": "measured_weather",
                "title": "실측 기상 평가 (고속 모드 · 평가 연도 재분석 시간별 기상 · 날 = 반복)",
                "cond": [("w.start", "시작", "s"), ("w.outdoor_temp_c", "시작 기온", ".1f"), ("w.outdoor_rh_pct", "시작 RH", ".0f"),
                         ("w.rain_hours", "비 시간", "d")]},
    "shared": {"src": "results/randomized_shared/summary.csv", "prefix": "randomized_shared",
               "title": "공유 계수 무작위 (제어기가 참값과 같은 사본을 쓰는 계수만 참값 쪽에서 ±30 % · docs/11 권장 10)",
               "cond": [("p.thermal.solar_heat_gain_fraction", "일사열 비", ".2f")]},
    "heldout_r7": {"src": "results/heldout_r7/summary.csv", "prefix": "heldout_r7",
                   "title": "보류 평가 7차 (마지막 · 사전 등록 · 결과를 고치지 않음)", "cond": []},
    "physics_random": {"src": "results/physics_random/summary.csv", "prefix": "physics_random",
                       "title": "물리 모드 조건 무작위 (반복마다 참값 계수 · 외기 · 잡음 시드 · 2026-10-26)", "cond": []},
}
BOOT_N = 5000
METRICS = [("energy_compare_wh", "추정 전력 (조명 제외) [Wh]"), ("comfort_ratio", "쾌적 유지율"),
           ("temp_excess_ch", "온도 초과 [°C·h]"), ("rh_excess_pcth", "습도 이탈 [%RH·h]"),
           ("pm_excess_ugh", "PM 초과 [µg/m³·h]"), ("rule_violation_count", "규칙 위반 [회]")]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def cluster_ci(g: pd.DataFrame, n_boot: int = BOOT_N, seed: int = 0) -> tuple[float, float]:
    """시나리오 묶음 부트스트랩 — 시나리오를 복원 추출해 (통과 합 / 실행 합) 을 다시 구한다."""
    by = g.groupby("scenario")["pass"].agg(["sum", "count"])
    if len(by) < 2:
        return (math.nan, math.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(by), size=(n_boot, len(by)))
    s, c = by["sum"].to_numpy()[idx].sum(1), by["count"].to_numpy()[idx].sum(1)
    lo, hi = np.percentile(s / c, [2.5, 97.5])
    return (float(lo), float(hi))


def mean_ci(x: pd.Series) -> tuple[float, float, float, int]:
    x = pd.to_numeric(x, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    n = len(x)
    if n < 2:
        return (float(x.mean()) if n else math.nan, math.nan, math.nan, n)
    m, s = float(x.mean()), float(x.std(ddof=1))
    h = float(stats.t.ppf(0.975, n - 1)) * s / math.sqrt(n)
    return (m, m - h, m + h, n)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=sorted(KINDS), default="randomized")
    kd = KINDS[ap.parse_args().kind]
    df = pd.read_csv(REPO / kd["src"])
    if "rep" not in df.columns and "run_id" in df.columns:
        df["rep"] = df.run_id.str.rsplit("_", n=1).str[-1].astype(int)
    df["pass"] = (df.status == "PASS").astype(int)
    lines = [f"# {kd["title"]}", ""]
    # 1. 판정 통과율
    lines += ["## 판정 통과율", "", "| 기준선 | 통과 / 실행 | 통과율 | 시나리오 묶음 부트스트랩 95 % (보고값) | Wilson 95 % (실행 독립 가정) |",
              "|---|---:|---:|---|---|"]
    prow0 = []
    for bl in ("A", "B", "proposed", "proposed_np"):
        g = df[df.baseline == bl]
        if g.empty:
            continue
        k, n = int(g["pass"].sum()), len(g)
        lo, hi = wilson(k, n)
        clo, chi = cluster_ci(g)
        prow0.append({"baseline": bl, "pass": k, "runs": n, "rate": k / n, "cluster_lo": clo, "cluster_hi": chi,
                      "wilson_lo": lo, "wilson_hi": hi, "scenarios": g.scenario.nunique()})
        lines.append(f"| {bl} | {k} / {n} | {k / n * 100:.1f} % | {clo * 100:.1f} – {chi * 100:.1f} % | {lo * 100:.1f} – {hi * 100:.1f} % |")
    pd.DataFrame(prow0).to_csv(OUT / f"{kd['prefix']}_pass.csv", index=False)
    # 2. 제안 실패 실행
    fail = df[(df.baseline == "proposed") & (df.status != "PASS")]
    lines += ["", f"## 제안 제어기 실패 {len(fail)}회", "", "| 실행 | " + " | ".join(c[1] for c in kd["cond"]) + " | 실패한 판정 |",
              "|---|" + "---:|" * len(kd["cond"]) + "---|"]
    for _, r in fail.iterrows():
        bad = " · ".join(f"`{c[1]}` ({c[2]})" for c in json.loads(r.criteria) if c[0] == "FAIL")
        cells = " | ".join(format(r[col], fmt) if fmt != "s" else str(r[col])[:16] for col, _, fmt in kd["cond"])
        lines.append(f"| {r.run_id} | {cells} | {bad} |")
    # 3. 지표 평균 ± 구간
    rows = []
    lines += ["", "## 지표 — 시나리오 · 반복 전체 평균 (95 % 구간)", "", "| 지표 | A | B | 제안 |", "|---|---|---|---|"]
    for col, label in METRICS:
        cells = []
        for bl in ("A", "B", "proposed"):
            m, lo, hi, n = mean_ci(df[df.baseline == bl][f"m.{col}"])
            rows.append({"metric": col, "baseline": bl, "mean": m, "ci_lo": lo, "ci_hi": hi, "n": n})
            cells.append(f"{m:.3g} [{lo:.3g}, {hi:.3g}]" if n > 1 else "–")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    pd.DataFrame(rows).to_csv(OUT / f"{kd["prefix"]}_metrics.csv", index=False)
    # 4. 짝 비교
    lines += ["", "## 짝 비교 — 같은 조건에서 제안 − 기준선 (평균 · 95 % 구간 · 짝 수)", "", "| 지표 | 제안 − A | 제안 − B |", "|---|---|---|"]
    prow = []
    for col, label in METRICS:
        cells = []
        for ref in ("A", "B"):
            a = df[df.baseline == "proposed"][["scenario", "rep", f"m.{col}"]]
            b = df[df.baseline == ref][["scenario", "rep", f"m.{col}"]]
            m = a.merge(b, on=["scenario", "rep"], suffixes=("", "_ref"))
            d = pd.to_numeric(m[f"m.{col}"], errors="coerce") - pd.to_numeric(m[f"m.{col}_ref"], errors="coerce")
            mu, lo, hi, n = mean_ci(d)
            prow.append({"metric": col, "ref": ref, "mean_diff": mu, "ci_lo": lo, "ci_hi": hi, "pairs": n})
            sig = "" if (math.isnan(lo) or (lo <= 0 <= hi)) else " *"
            cells.append(f"{mu:+.3g} [{lo:+.3g}, {hi:+.3g}] · {n}{sig}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    pd.DataFrame(prow).to_csv(OUT / f"{kd["prefix"]}_paired.csv", index=False)
    lines.append("")
    lines.append("\\* 95 % 구간이 0 을 포함하지 않음")
    # 5. 반복 간 분산이 생겼는지
    g = df.groupby(["scenario", "baseline"])["m.energy_wh"].std().fillna(0)
    lines += ["", f"반복 간 에너지 표준편차 0 인 (시나리오, 기준선) 묶음: {float((g < 1e-6).mean()) * 100:.0f} % "
              f"({len(g)}개 중) — 명목 반복만 쓰던 때는 81 %"]
    # 6. 시나리오별 제안 통과율 (실패가 몰린 곳)
    by = df[df.baseline == "proposed"].groupby("scenario")["pass"].agg(["sum", "count"])
    weak = by[by["sum"] < by["count"]]
    if len(weak):
        lines += ["", "시나리오별 제안 통과 (실패가 있는 곳): " + " · ".join(f"{i} {int(r['sum'])}/{int(r['count'])}" for i, r in weak.iterrows())]
    (OUT / f"{kd["prefix"]}_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
