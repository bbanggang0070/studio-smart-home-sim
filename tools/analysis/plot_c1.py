"""C1 비교 그래프 (W11 T11.6 · W13 T13.5 발표용 개정) — 고온다습 + 우천: 제안 vs Baseline A · B (고속 모드 반복 1).

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

STYLE = {"A": ("A (장치별 독립 규칙)", "#b91c1c"), "B": ("B (히스테리시스 없음)", "#a1a5ac"), "proposed": ("제안", "#4d7c0f")}


def _energy(d: pd.DataFrame) -> float:
    return float(d.filter(like="energy").iloc[-1].sum())


def main() -> None:
    """발표용 (W13 T13.5) — 1920 × 1080 · 4단: 습도 · 온도 · 창문 · 에어컨 운전(냉방 / 제습) — 역할 이전을 한 장에."""
    data = {b: pd.read_csv(REPO / "results" / "raw" / f"C1_{b}_1.csv", low_memory=False) for b in STYLE}
    fig, ax = plt.subplots(4, 1, figsize=(16, 9), sharex=True, gridspec_kw={"height_ratios": [3, 2, 1.3, 1.3]})
    for k, (b, (label, color)) in enumerate(STYLE.items()):
        d = data[b]
        t = d["time_s"] / 60.0
        lw = 2.6 if b == "proposed" else 1.6
        ax[0].plot(t, d["truth.humidity_pct"], color=color, lw=lw,
                   label=f"{label} — 끝 {d['truth.humidity_pct'].iloc[-1]:.0f} %RH · {_energy(d):.0f} Wh")
        ax[1].plot(t, d["truth.temperature_c"], color=color, lw=lw)
        ax[2].plot(t, d["act.window_open_ratio"] * 100, color=color, lw=lw)
        cool = pd.to_numeric(d["act.ac_cool"], errors="coerce").fillna(0).astype(bool)
        dry = pd.to_numeric(d["act.ac_dry"], errors="coerce").fillna(0).astype(bool)
        y = 2 - k
        ax[3].fill_between(t, y - 0.35, y + 0.35, where=cool, color=color, alpha=0.35, step="post", lw=0)
        ax[3].fill_between(t, y - 0.35, y + 0.35, where=dry, color=color, alpha=0.95, step="post", lw=0, hatch="//")
    ax[3].set_yticks([2, 1, 0], [STYLE[b][0].split(" (")[0] for b in STYLE])
    ax[3].set_ylim(-0.6, 2.6)
    ax[0].axhline(72, color="#52525b", ls="--", lw=1)
    ax[0].text(0.5, 72.8, "판정: 60분 내 ≤ 72 %RH", color="#52525b")
    ax[0].set_ylabel("실내 습도 [%RH]")
    ax[1].set_ylabel("실내 온도 [°C]")
    ax[2].set_ylabel("창문 [%]")
    ax[3].set_ylabel("에어컨\n(연함 냉방 · 진함 제습)")
    ax[3].set_xlabel("시간 [분]")
    for a in ax:
        a.grid(alpha=0.3)
    ax[0].legend(loc="center right")
    ax[0].set_title("C1 고온다습 + 비 — A 는 온도 규칙대로 창문을 열어 젖은 외기가 들어오고(습도 100 %), "
                    "제안은 창문을 닫고 에어컨 제습으로 역할을 옮긴다", fontsize=13)
    out = REPO / "results" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out / "c1_compare.png", dpi=120)
    print(f"저장: {(out / 'c1_compare.png').relative_to(REPO)}")


if __name__ == "__main__":
    main()
