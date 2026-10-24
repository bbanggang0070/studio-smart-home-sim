"""센서리스 토크 스윕 · 물체 강성 (W12 T12.3 · T12.4) — results/sweep/pinch_sweep.csv → 그래프 · 표.

    uv run python tools/analysis/plot_torque_sweep.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")
REPO = Path(__file__).resolve().parents[2]
for f in ("Noto Sans CJK JP", "Noto Sans CJK KR", "Noto Serif CJK SC"):
    if any(f in x.name for x in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
NAMES = {"rigid_pot": "강체 화분", "soft_cushion": "연질 쿠션", "elastic_sponge": "탄성 스펀지"}
COLORS = {"rigid_pot": "#b91c1c", "soft_cushion": "#ca8a04", "elastic_sponge": "#4d7c0f"}


def main() -> None:
    d = pd.read_csv(REPO / "results" / "sweep" / "pinch_sweep.csv")
    g = d.groupby(["torque_pct", "object"]).agg(n=("trial", "count"), detect=("detected", "mean"),
                                                 peak_mean=("contact_peak_n", "mean"), peak_max=("contact_peak_n", "max"),
                                                 stop_ms=("stop_ms", "mean")).reset_index()
    out_t = REPO / "results" / "tables"
    out_t.mkdir(parents=True, exist_ok=True)
    g.round(2).to_csv(out_t / "torque_sweep.csv", index=False)
    fig, ax = plt.subplots(1, 2, figsize=(16, 9))          # 1920 × 1080 (슬라이드)
    for obj, gg in g.groupby("object"):
        ax[0].plot(gg.torque_pct, gg.detect * 100, "o-", color=COLORS[obj], label=NAMES[obj])
        ax[1].errorbar(gg.torque_pct, gg.peak_mean, yerr=[gg.peak_mean - gg.peak_mean, gg.peak_max - gg.peak_mean],
                       fmt="o-", color=COLORS[obj], capsize=3, label=NAMES[obj])
    ax[0].set_ylabel("감지율 [%]")
    ax[0].set_ylim(0, 105)
    ax[1].axhline(100, color="k", lw=1, ls="--")
    ax[1].text(g.torque_pct.min(), 102, "상한 100 N", fontsize=9)
    ax[1].set_ylabel("최대 접촉력 [N] (점 = 평균, 막대 = 최대)")
    for a in ax:
        a.set_xlabel("주행 구간 끝 토크 [%]")
        a.grid(alpha=0.3)
        a.legend()
    fig.suptitle("센서리스 토크 스윕 — 감지율 · 최대 접촉력 (물리 모드 · 끼임마다 1회)")
    out = REPO / "results" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out / "torque_sweep.png", dpi=120)
    print(g.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
