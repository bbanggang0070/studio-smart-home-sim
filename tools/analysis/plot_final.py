"""최종 보고서 그림 (보고서 v0.5 §6 · 2026-10-27) — archive/v1.29 요약에서 그린다 (다시 돌리지 않는다).

    uv run python tools/analysis/plot_final.py   → results/figures/final_*.png

  final_baselines   기준선 비교 — 환경 결과 기준 통과율 (A 가 도는 시나리오만 짝) · 실험별
  final_effects     짝 효과 크기 — 통과율 차 · 기대비용 비 · 에너지 비 (묶음 부트스트랩 95 %)
  final_robustness  견고성 — 조건별 제안 통과율 (전체 · 환경 결과)
  final_intake      흡기 용량 민감도 — C9 PM 피크 · 틈새 유입 · 에너지
  final_tradeoff    쾌적 ↔ 기대비용 — 같은 조건 쌍의 평균 (A · A′ · 제안)
색: 비교군마다 고정 (제안 slot 1 · A slot 2 · A′ slot 3 · B slot 4 — dataviz 기본 범주형 · 검증 통과) · 값은 막대 옆에 직접 쓴다
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from criteria_classes import table  # noqa: E402

AR = REPO / "archive" / "v1.29"
OUT = REPO / "results" / "figures"
COLOR = {"proposed": "#2a78d6", "A": "#eb6834", "A2": "#1baf7a", "B": "#eda100"}
LABEL = {"proposed": "제안", "A": "A (기기별 독립)", "A2": "A′ (상용 허브 규칙)", "B": "B (히스테리시스 없음)"}
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"


def style() -> None:
    for f in ("NanumGothic", "Noto Sans CJK KR", "Noto Sans KR", "UnDotum"):
        if any(f in x.name for x in matplotlib.font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams.update({"axes.unicode_minus": False, "figure.facecolor": SURF, "axes.facecolor": SURF,
                         "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
                         "grid.linewidth": 0.8, "axes.axisbelow": True, "font.size": 10, "savefig.dpi": 160})


def merged(main: str, a2: str | None) -> pd.DataFrame:
    d = pd.read_csv(AR / main)
    if a2 and (AR / a2).exists():
        x = pd.read_csv(AR / a2)
        d = pd.concat([d, x[x.baseline == "A2"]])
    return d[d.status != "SKIPPED"]


def outcome_rates(d: pd.DataFrame) -> dict[str, float]:
    t = table(d)
    t = t[t.scenario.isin(set(t[t.baseline == "A"].scenario))]
    return {bl: float(t[t.baseline == bl].outcome.dropna().mean()) for bl in COLOR if (t.baseline == bl).any()}


def fig_baselines() -> None:
    sets = [("개발 시나리오", "fast_dev_summary.csv", "a2_dev_summary.csv"), ("무작위 반복", "randomized_summary.csv", "randomized_a2_summary.csv"),
            ("실측 기상 2024", "measured_weather_summary.csv", "measured_weather_a2_summary.csv"),
            ("보류 7차 (마지막)", "heldout_r7_summary.csv", "heldout_r7_a2_summary.csv")]
    order = ["A", "A2", "B", "proposed"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    w, gap = 0.19, 0.012
    for i, (name, m, a2) in enumerate(sets):
        r = outcome_rates(merged(m, a2))
        for j, bl in enumerate(order):
            if bl not in r:
                continue
            x = i + (j - 1.5) * (w + gap)
            ax.bar(x, r[bl] * 100, w, color=COLOR[bl], label=LABEL[bl] if i == 0 else None)
            ax.text(x, r[bl] * 100 + 1.5, f"{r[bl] * 100:.0f}", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(range(len(sets)), [s[0] for s in sets], color=INK)
    ax.set_ylim(0, 110)
    ax.set_ylabel("환경 결과 기준을 모두 지킨 실행 [%]")
    ax.set_title("기준선 비교 — 환경 결과 기준 통과율 (A 가 도는 시나리오만 · 같은 조건 짝)", color=INK, loc="left", fontsize=11)
    ax.legend(frameon=False, ncol=4, loc="upper left", bbox_to_anchor=(0, -0.09), fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "final_baselines.png")
    plt.close(fig)


def fig_effects() -> None:
    p = pd.read_csv(AR / "tables" / "paired_tests.csv")
    p["src"] = p.src.replace({"randomized": "무작위", "measured_weather": "실측 기상"})
    panels = [("환경 결과 통과율 차 (제안 − 기준)", "환경 결과 통과율 차", 0.0, "%p", 100),
              ("기대비용 비 (제안 / 기준)", "기대비용 비", 1.0, "", 1),
              ("에너지 비 (제안 / 기준)", "에너지 비", 1.0, "", 1)]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), sharey=True)
    rows = [(ref, src) for ref in ("A", "A2", "B") for src in ("무작위", "실측 기상")]
    for ax, (title, key, ref_line, unit, k) in zip(axes, panels):
        for yi, (ref, src) in enumerate(rows):
            r = p[(p.ref == ref) & (p.src == src) & p.measure.str.startswith(key)]
            if r.empty:
                continue
            r = r.iloc[0]
            ax.plot([r.lo * k, r.hi * k], [yi, yi], color=COLOR[ref], lw=2, solid_capstyle="round")
            ax.plot(r.effect * k, yi, "o", ms=8, color=COLOR[ref], mec=SURF, mew=2)
            ax.annotate(f"{r.effect * k:.0f}" if unit else f"{r.effect * k:.2f}", (r.hi * k, yi), textcoords="offset points",
                        xytext=(6, 0), va="center", ha="left", fontsize=8, color=INK,
                        bbox=dict(boxstyle="square,pad=0.1", fc=SURF, ec="none"), zorder=5)
        ax.axvline(ref_line * k, color=INK2, lw=1, ls=(0, (3, 3)))
        ax.set_title(title, color=INK, fontsize=10, loc="left")
        ax.grid(axis="y", visible=False)
        lo_, hi_ = ax.get_xlim()
        ax.set_xlim(lo_, hi_ + (hi_ - lo_) * 0.12)                 # 오른쪽 값 라벨 자리
    axes[0].set_yticks(range(len(rows)), [f"vs {LABEL[r].split(' ')[0]} · {s}" for r, s in rows], color=INK)
    axes[0].invert_yaxis()
    fig.suptitle("짝 효과 크기 — 점 = 효과 · 선 = 시나리오 묶음 부트스트랩 95 % · 점선 = 차이 없음", x=0.01, ha="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "final_effects.png")
    plt.close(fig)


def fig_robustness() -> None:
    items = [("기본 무작위", "randomized_summary.csv"), ("센서 결함", "randomized_faults_summary.csv"),
             ("임계값 ±20 %", "randomized_thresholds_summary_filled.csv"), ("흡기 150", "randomized_intake150_summary_filled.csv"),
             ("흡기 300", "randomized_intake300_summary_filled.csv"), ("물리 고정 조건", "physics_summary.csv"),
             ("물리 조건 무작위", "physics_random_summary.csv")]
    fig, ax = plt.subplots(figsize=(8.5, 4))
    for yi, (name, f) in enumerate(items):
        d = pd.read_csv(AR / f)
        g = d[d.baseline == "proposed"]
        t = table(g)
        allr, outr = (g.status == "PASS").mean() * 100, t.outcome.dropna().mean() * 100
        ax.plot([outr, allr], [yi, yi], color=GRID, lw=2, zorder=1)
        ax.plot(allr, yi, "o", ms=8, color=COLOR["proposed"], mec=SURF, mew=2, zorder=3, label="전체 기준" if yi == 0 else None)
        ax.plot(outr, yi, "o", ms=8, mfc=SURF, mec=COLOR["proposed"], mew=2, zorder=3, label="환경 결과 기준" if yi == 0 else None)
        ax.text(max(allr, outr) + 1.2, yi, f"{allr:.0f} · {outr:.0f}", va="center", fontsize=8, color=INK)
    ax.set_yticks(range(len(items)), [i[0] for i in items], color=INK)
    ax.invert_yaxis()
    ax.set_xlim(70, 105)
    ax.set_xlabel("제안 통과율 [%]")
    ax.set_title("견고성 — 조건을 바꿨을 때 제안 통과율 (전체 기준 · 환경 결과 기준)", color=INK, loc="left", fontsize=11)
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "final_robustness.png")
    plt.close(fig)


def fig_intake() -> None:
    src = [(60, "randomized_summary.csv"), (150, "randomized_intake150_summary_filled.csv"), (300, "randomized_intake300_summary_filled.csv")]
    vals = {m: [] for m in ("m.pm25_peak", "m.infiltration_volume", "m.energy_wh")}
    for _, f in src:
        d = pd.read_csv(AR / f)
        g = d[(d.baseline == "proposed") & (d.scenario == "C9")]
        for m in vals:
            vals[m].append(float(pd.to_numeric(g[m], errors="coerce").mean()))
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.3))
    for ax, (m, title) in zip(axes, [("m.pm25_peak", "PM2.5 피크 [µg/m³]"), ("m.infiltration_volume", "틈새 유입량 [m³]"),
                                     ("m.energy_wh", "에너지 [Wh]")]):
        xs = [s[0] for s in src]
        ax.plot(xs, vals[m], "-o", color=COLOR["proposed"], lw=2, ms=8, mec=SURF, mew=2)
        for x, v in zip(xs, vals[m]):
            ax.text(x, v, f" {v:.0f}", fontsize=8, color=INK, va="bottom")
        ax.set_xticks(xs, [f"{x}" for x in xs])
        ax.set_xlabel("흡기 최대 [m³/h]")
        ax.set_title(title, color=INK, loc="left", fontsize=10)
        ax.set_ylim(0, max(vals[m]) * 1.25)
    fig.suptitle("흡기 용량 민감도 — C9 요리 + 외기 미세먼지 (제안 · 5회 평균 · 사양은 바꾸지 않음)", x=0.01, ha="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "final_intake.png")
    plt.close(fig)


def fig_tradeoff() -> None:
    d = merged("randomized_summary.csv", "randomized_a2_summary.csv")
    paired = set(d[d.baseline == "A"].scenario)
    d = d[d.scenario.isin(paired)]
    d["cost"] = pd.to_numeric(d["m.energy_compare_wh"], errors="coerce") + 2000 * pd.to_numeric(d["m.temp_excess_ch"], errors="coerce")
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    for bl in ("A", "A2", "B", "proposed"):
        g = d[d.baseline == bl]
        c, e = pd.to_numeric(g["m.comfort_ratio"], errors="coerce").mean(), g["cost"].median()
        ax.plot(c, e, "o", ms=11, color=COLOR[bl], mec=SURF, mew=2)
        ax.annotate(LABEL[bl], (c, e), textcoords="offset points", xytext=(8, 4), fontsize=9, color=INK)
    ax.set_xlabel("쾌적 유지율 (평균) →  좋음")
    ax.set_ylabel("기대비용 (중앙값) [Wh 환산] ↓  좋음")
    ax.set_title("쾌적 ↔ 기대비용 — 무작위 반복 · A 가 도는 시나리오", color=INK, loc="left", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "final_tradeoff.png")
    plt.close(fig)


def main() -> None:
    style()
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (fig_baselines, fig_effects, fig_robustness, fig_intake, fig_tradeoff):
        f()
        print("저장:", f.__name__.replace("fig_", "final_") + ".png")


if __name__ == "__main__":
    main()
