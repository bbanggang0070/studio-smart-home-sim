"""Tier 2 협조 제어 우위 정량 제시 (W13 DoD) — ① 시나리오별 목표 달성 스코어카드 ② 쾌적-에너지 2축 그림.

    uv run python tools/analysis/tier2_advantage.py
        → results/tables/tier2_scorecard.md · tier2_scorecard.csv · tier2_tradeoff.csv
          results/figures/w13_scorecard.png · w13_tradeoff.png

① 각 시나리오가 정해 둔 판정 기준(config/scenario_profiles.yaml pass_criteria)을 기준선별로 — 기준 단위 통과율 · 실패한 기준
   (baseline_A.* 비교 기준은 A 자신에게는 적용되지 않으므로 기준 수가 다를 수 있다)
② 목표 이탈 적분(온도 °C·h · 습도 %RH·h · PM µg/m³·h) vs 추정 소비전력량(조명 제외) — A → 제안 화살표
본문 = harness.yaml analysis.headline_scenarios (C1–C8) · 부록 = Tier 2 전체
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
REPO = Path(__file__).resolve().parents[2]
for f in ("Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Serif CJK KR", "Noto Serif CJK SC"):
    if any(f in x.name for x in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False

BASE = {"A": ("A (장치별 독립)", "#b91c1c"), "B": ("B (히스테리시스 없음)", "#a1a5ac"), "proposed": ("제안", "#4d7c0f")}
OUT_T, OUT_F = REPO / "results" / "tables", REPO / "results" / "figures"
NA_MARK = "자신의 실행"                 # harness criteria 가 A 자신과의 비교 기준에 남기는 표시


def load(cfg: dict) -> pd.DataFrame:
    frames = []
    for mode, key in (("fast", "fast_summary"), ("physics", "physics_summary")):
        p = REPO / cfg[key]
        if p.exists():
            d = pd.read_csv(p)
            d["mode"] = mode
            frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    return d[(d.status != "SKIPPED") & d.baseline.isin(list(BASE))]


def scorecard(runs: pd.DataFrame, ids: list[str], tag: str) -> pd.DataFrame:
    rows, lines = [], [f"# Tier 2 목표 달성 스코어카드 ({tag}) — 시나리오 판정 기준 × 기준선 (반복 통과 수 / 반복)", ""]
    for sid in ids:
        g = runs[runs.scenario == sid]
        if g.empty:
            continue
        crit: dict[str, dict[str, list]] = {}
        for _, r in g.iterrows():
            for st, text, detail in json.loads(r.criteria):
                if NA_MARK in detail:                        # A 자신과의 비교 — A 에게는 해당 없음
                    continue
                crit.setdefault(text, {}).setdefault(r.baseline, []).append((st == "PASS", detail))
        lines += [f"## {sid} · {g['mode'].iloc[0]}", "", "| 판정 기준 | " + " | ".join(BASE[b][0] for b in BASE) + " |",
                  "|---|" + "---|" * len(BASE)]
        for text, by in crit.items():
            cells = []
            for b in BASE:
                v = by.get(b)
                if not v:
                    cells.append("–")
                    continue
                k = sum(ok for ok, _ in v)
                mark = "✅" if k == len(v) else ("❌" if k == 0 else "△")
                det = next((d for ok, d in v if not ok), "") if k < len(v) else ""
                cells.append(f"{mark} {k}/{len(v)}" + (f" ({det})" if det else ""))
            lines.append(f"| `{text}` | " + " | ".join(cells) + " |")
        lines.append("")
        for b in BASE:
            gb = g[g.baseline == b]
            if len(gb):
                res = [st == "PASS" for c in gb.criteria for st, _, det in json.loads(c) if NA_MARK not in det]
                rows.append({"scenario": sid, "baseline": b, "runs": len(gb), "scenario_pass": float((gb.status == "PASS").mean()),
                             "criteria_pass_ratio": float(np.mean(res)) if res else np.nan})
    sc = pd.DataFrame(rows)
    piv = sc.pivot(index="scenario", columns="baseline", values="criteria_pass_ratio").reindex(ids).dropna(how="all")
    tot = sc.groupby("baseline")[["scenario_pass", "criteria_pass_ratio"]].mean()
    head = ["| 기준선 | 시나리오 판정 통과 | 판정 기준 단위 통과율 |", "|---|---:|---:|"]
    head += [f"| {BASE[b][0]} | {tot.loc[b, 'scenario_pass'] * 100:.0f} % | {tot.loc[b, 'criteria_pass_ratio'] * 100:.0f} % |"
             for b in BASE if b in tot.index]
    (OUT_T / f"tier2_scorecard{'' if tag == '본문' else '_all'}.md").write_text(
        "\n".join(lines[:2] + head + [""] + lines[2:]) + "\n", encoding="utf-8")
    sc.to_csv(OUT_T / f"tier2_scorecard{'' if tag == '본문' else '_all'}.csv", index=False)
    print(f"[{tag}] " + " · ".join(f"{BASE[b][0]} 판정 {tot.loc[b, 'scenario_pass'] * 100:.0f} % / 기준 {tot.loc[b, 'criteria_pass_ratio'] * 100:.0f} %"
                                   for b in BASE if b in tot.index))
    return piv


def heatmap(piv: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(16, 9), dpi=120)
    cols = [b for b in BASE if b in piv.columns]
    m = piv[cols].to_numpy() * 100
    im = ax.imshow(m, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(cols)), [BASE[b][0] for b in cols], fontsize=14)
    ax.set_yticks(range(len(piv.index)), piv.index, fontsize=14)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            if not np.isnan(m[i, j]):
                ax.text(j, i, f"{m[i, j]:.0f} %", ha="center", va="center", fontsize=15, color="black")
    fig.colorbar(im, ax=ax, label="시나리오 판정 기준 통과율 [%]")
    ax.set_title("Tier 2 (C1–C8) — 시나리오마다 정한 목표(판정 기준)를 몇 % 지켰나 · 3회 반복", fontsize=15)
    fig.tight_layout()
    fig.savefig(OUT_F / "w13_scorecard.png")
    plt.close(fig)


def tradeoff(runs: pd.DataFrame, ids: list[str], cfg: dict) -> None:
    ecol = f"m.{cfg['energy_col']}"
    devs = cfg["deviation_metrics"]
    g = runs[runs.scenario.isin(ids)].copy()
    for c in [ecol] + [f"m.{d['col']}" for d in devs]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    agg = g.groupby(["scenario", "baseline"])[[ecol] + [f"m.{d['col']}" for d in devs]].mean().reset_index()
    agg.to_csv(OUT_T / "tier2_tradeoff.csv", index=False)
    fig, axs = plt.subplots(1, len(devs), figsize=(16, 9), dpi=120)
    for ax, d in zip(axs, devs):
        y = f"m.{d['col']}"
        for sid in ids:
            s = agg[agg.scenario == sid].set_index("baseline")
            if "A" not in s.index or "proposed" not in s.index:
                continue
            a, p = s.loc["A"], s.loc["proposed"]
            if (a[y] + p[y]) <= 1e-9:
                continue                                   # 둘 다 이탈 0 — 이 축에서 비교할 것이 없다
            ax.annotate("", (p[ecol], p[y]), (a[ecol], a[y]), arrowprops={"arrowstyle": "->", "color": "#71717a", "lw": 1.2})
            ax.scatter(a[ecol], a[y], color=BASE["A"][1], s=60, zorder=3)
            ax.scatter(p[ecol], p[y], color=BASE["proposed"][1], s=60, zorder=3)
            ax.annotate(sid, (a[ecol], a[y]), xytext=(4, 4), textcoords="offset points", fontsize=11)
        ax.set_xlabel("추정 소비전력량 (조명 제외) [Wh]")
        ax.set_ylabel(d["label"])
        ax.grid(alpha=0.3)
    axs[0].scatter([], [], color=BASE["A"][1], label=BASE["A"][0])
    axs[0].scatter([], [], color=BASE["proposed"][1], label=BASE["proposed"][0])
    axs[0].legend(loc="upper right")
    fig.suptitle("Tier 2 (C1–C8) — A → 제안: 목표 이탈(아래가 좋음)과 에너지(왼쪽이 좋음) · 둘 다 이탈 0 인 시나리오는 그 축에서 뺐다", fontsize=14)
    fig.tight_layout()
    fig.savefig(OUT_F / "w13_tradeoff.png")
    plt.close(fig)
    show = agg[agg.baseline.isin(["A", "proposed"])].pivot(index="scenario", columns="baseline").round(1)
    print(show.to_string())


def main() -> None:
    hcfg = yaml.safe_load(open(REPO / "config" / "harness.yaml", encoding="utf-8"))
    cfg = hcfg["analysis"]
    OUT_T.mkdir(parents=True, exist_ok=True)
    OUT_F.mkdir(parents=True, exist_ok=True)
    runs = load(cfg)
    scen = yaml.safe_load(open(REPO / hcfg["paths"]["scenarios"], encoding="utf-8"))["scenarios"]
    tier2 = [s["id"] for s in scen if s.get("tier") == 2]
    heatmap(scorecard(runs, cfg["headline_scenarios"], "본문"))
    scorecard(runs, tier2, "Tier 2 전체")
    tradeoff(runs, cfg["headline_scenarios"], cfg)
    print("저장: results/tables/tier2_scorecard*.md · tier2_tradeoff.csv · results/figures/w13_scorecard.png · w13_tradeoff.png")


if __name__ == "__main__":
    main()
