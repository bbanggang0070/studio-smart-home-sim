"""C1 비교 그래프 (W11 T11.6) — 고온다습 + 우천: 제안 vs Baseline A · B (고속 모드 반복 1).

    uv run python tools/analysis/plot_c1.py        → results/figures/c1_compare.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")
REPO = Path(__file__).resolve().parents[2]
for f in ("Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Serif CJK KR", "Noto Serif CJK SC"):
    if any(f in x.name for x in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False

STYLE = {"proposed": ("제안", "#4d7c0f"), "B": ("B (히스테리시스 없음)", "#a1a5ac"), "A": ("A (장치별 독립 규칙)", "#b91c1c")}


def main() -> None:
    fig, ax = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    for b, (label, color) in STYLE.items():
        d = pd.read_csv(REPO / "results" / "raw" / f"C1_{b}_1.csv")
        t = d["time_s"] / 60.0
        ax[0].plot(t, d["truth.humidity_pct"], color=color, label=label, lw=2 if b == "proposed" else 1.5)
        ax[1].plot(t, d["truth.temperature_c"], color=color, label=label, lw=2 if b == "proposed" else 1.5)
        ax[2].plot(t, d["act.window_open_ratio"] * 100, color=color, label=label, lw=2 if b == "proposed" else 1.5)
    ax[0].set_ylabel("실내 습도 [%]")
    ax[1].set_ylabel("실내 온도 [°C]")
    ax[2].set_ylabel("창문 개방 [%]")
    ax[2].set_xlabel("시간 [분]")
    ax[0].set_title("C1 — 고온다습 + 우천: 제안은 창문을 닫고 에어컨 제습, A 는 온도 규칙으로 창문을 열어 습기가 들어온다")
    for a in ax:
        a.grid(alpha=0.3)
    ax[0].legend(loc="lower left")
    out = REPO / "results" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out / "c1_compare.png", dpi=130)
    print(f"저장: {(out / 'c1_compare.png').relative_to(REPO)}")


if __name__ == "__main__":
    main()
