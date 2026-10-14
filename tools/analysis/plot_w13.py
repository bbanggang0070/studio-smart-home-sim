"""W13 그래프 (T13.4 · T13.3) — Tier 2 3군 비교 막대 · 지표 요약 · 대표 시계열 5단.

    uv run python scripts/analyze_results.py        # 먼저 (results/tables/w13_*.csv)
    uv run python tools/analysis/plot_w13.py        → results/figures/w13_tier2_pass.png · w13_tier2_metrics.png · w13_timeseries_<id>.png

발표 슬라이드 해상도(16:9 · 1920 px 폭)로 저장한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.use("Agg")
REPO = Path(__file__).resolve().parents[2]
for f in ("Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Serif CJK KR", "Noto Serif CJK SC"):
    if any(f in x.name for x in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False

STYLE = {"A": ("A (장치별 독립 규칙)", "#b91c1c"), "B": ("B (히스테리시스 없음)", "#a1a5ac"), "proposed": ("제안", "#4d7c0f")}
SLIDE = dict(figsize=(16, 9), dpi=120)          # 1920 × 1080
OUT = REPO / "results" / "figures"


def _bars(ax, df: pd.DataFrame, col: str, order: list[str], ylabel: str, scale: float = 1.0) -> None:
    x = np.arange(len(order))
    w = 0.27
    for k, (b, (label, color)) in enumerate(STYLE.items()):
        v = df[df.baseline == b].set_index("scenario").reindex(order)[col] * scale
        ax.bar(x + (k - 1) * w, v.to_numpy(), w, label=label, color=color)
    ax.set_xticks(x, order)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)


def tier2(cmp_: pd.DataFrame) -> None:
    order = sorted(cmp_.scenario.unique(), key=lambda s: (s.rstrip("b"), s))
    fig, ax = plt.subplots(1, 1, **SLIDE)
    _bars(ax, cmp_, "pass_rate", order, "판정 통과율 [%]", 100.0)
    ax.set_ylim(0, 105)
    ax.set_title("Tier 2 — 시나리오 판정 통과율 (3회 반복 · 고속 + 물리)")
    ax.legend(loc="upper right", ncols=3)
    fig.tight_layout()
    fig.savefig(OUT / "w13_tier2_pass.png")
    plt.close(fig)

    fig, axs = plt.subplots(2, 1, sharex=True, **SLIDE)
    _bars(axs[0], cmp_, "m.comfort_ratio", order, "재실 중 쾌적 유지율 [%]", 100.0)
    _bars(axs[1], cmp_, "m.energy_wh", order, "추정 소비전력량 [Wh]")
    axs[0].set_title("Tier 2 — 쾌적 유지율(체감온도 · 습도)과 추정 소비전력량: A 는 덜 쓰는 대신 목표를 못 지킨다")
    axs[0].legend(loc="upper left", ncols=3)
    fig.tight_layout()
    fig.savefig(OUT / "w13_tier2_metrics.png")
    plt.close(fig)


def timeseries(sid: str) -> None:
    """T13.3 — 온도 · 습도 · 조도 · 액추에이터(창문 · 블라인드 / 팬 · 에어컨) 5단 (반복 1)."""
    fig, ax = plt.subplots(5, 1, sharex=True, **SLIDE)
    for b, (label, color) in STYLE.items():
        p = REPO / "results" / "raw" / f"{sid}_{b}_1.csv"
        if not p.exists():
            p = REPO / "results" / "physics" / "raw" / f"{sid}_{b}_1.csv"
        if not p.exists():
            continue
        d = pd.read_csv(p, low_memory=False)
        t = d["time_s"] / 60.0
        lw = 2.0 if b == "proposed" else 1.3
        ax[0].plot(t, d["truth.temperature_c"], color=color, lw=lw, label=label)
        ax[1].plot(t, d["truth.humidity_pct"], color=color, lw=lw)
        ax[2].plot(t, d["truth.floor_illuminance_lux"], color=color, lw=lw)
        ax[3].plot(t, d["act.window_open_ratio"] * 100, color=color, lw=lw)
        ax[3].plot(t, d["act.blind_angle_deg"], color=color, lw=lw, ls=":")
        ax[4].plot(t, d["act.exhaust_fan_rpm"], color=color, lw=lw)
        if "act.ac_cool" in d:
            ac = pd.to_numeric(d["act.ac_cool"], errors="coerce").fillna(0) + pd.to_numeric(d.get("act.ac_dry", 0), errors="coerce").fillna(0)
            ax[4].fill_between(t, 0, ac.clip(0, 1) * 300, color=color, alpha=0.12, step="post")
    for a, yl in zip(ax, ["온도 [°C]", "습도 [%]", "바닥 조도 [lux]", "창문 [%] · 블라인드 [°] (점선)", "배기 [rpm] · 에어컨 가동(음영)"]):
        a.set_ylabel(yl)
        a.grid(alpha=0.3)
    ax[-1].set_xlabel("시간 [분]")
    ax[0].legend(loc="upper right", ncols=3)
    ax[0].set_title(f"{sid} — 기준선별 환경 · 액추에이터 시계열 (반복 1)")
    fig.tight_layout()
    fig.savefig(OUT / f"w13_timeseries_{sid}.png")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cmp_ = pd.read_csv(REPO / "results" / "tables" / "w13_tier2_compare.csv")
    tier2(cmp_)
    for sid in (sys.argv[1:] or ["C1", "C8", "C15"]):
        timeseries(sid)
    print("저장:", ", ".join(sorted(p.name for p in OUT.glob("w13_*.png"))))


if __name__ == "__main__":
    main()
