"""난방 확장 발표 · 보고서 그림 (보고서 §6.14 · 2026-10-30) — archive/v1.31-H · v1.32-H · v1.33-H 요약에서 그린다 (다시 돌리지 않는다).

    uv run python tools/analysis/plot_heating.py   # → results/figures/heating_extension.png

왼쪽  v1.31-H 확정 결과 — 무작위 반복(넓은 건물 범위) 환경 결과 기준 통과율 · 방식별 (criteria_classes 3분류)
오른쪽 같은 새 데이터에서 v1.31-H → 사후 개선판(v1.32 · v1.33-H) 전체 통과율 · 데이터별
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from criteria_classes import table  # noqa: E402
from plot_final import GRID, INK, INK2, style as setup  # noqa: E402

AR = REPO / "archive"
# 범주 색 = 검증된 기본 팔레트 순서 (plot_final 과 같고 A′V 는 5번 magenta) · 버전은 같은 색상의 명도 단계
COLOR = {"proposed": "#2a78d6", "B": "#eda100", "A2V": "#e87ba4", "A2": "#1baf7a", "A": "#eb6834"}
LABEL = {"proposed": "제안", "B": "B (히스테리시스 없음)", "A2V": "A′V (스마트 조절기 + 24 h 환기)", "A2": "A′ (스마트 조절기)", "A": "A (22 °C 상시)"}
OLD, NEW = "#86b6ef", "#2a78d6"


def outcome_rates(path: Path) -> dict[str, float]:
    d = pd.read_csv(path)
    t = table(d[d.status != "SKIPPED"])
    return {bl: float(t[t.baseline == bl].outcome.dropna().astype(bool).mean()) for bl in COLOR}


def pass_rate(path: Path, bl: str, scen: str | None = None) -> tuple[int, int]:
    d = pd.read_csv(path)
    d = d[(d.baseline == bl) & (d.status != "SKIPPED")]
    if scen:
        d = d[d.scenario == scen]
    return int((d.status == "PASS").sum()), len(d)


def main() -> None:
    setup()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.8), gridspec_kw={"width_ratios": [1, 1.25]})

    r = outcome_rates(AR / "v1.31-H" / "randomized_heating_summary.csv")
    order = list(COLOR)[::-1]
    ax1.barh([LABEL[b] for b in order], [r[b] * 100 for b in order], color=[COLOR[b] for b in order], height=0.6)
    for i, b in enumerate(order):
        ax1.text(r[b] * 100 + 1.5, i, f"{r[b] * 100:.1f} %", va="center", color=INK, fontsize=10)
    ax1.set_xlim(0, 105)
    ax1.set_xlabel("환경 결과 기준 통과율 (%)")
    ax1.set_title("v1.31-H 확정 결과 — 무작위 반복 (신축 ~ 노후 원룸 · 90회)", loc="left", color=INK, fontsize=11)
    ax1.grid(axis="y", visible=False)

    w = AR / "v1.33-H" / "weekly_nominal_summary.csv"
    wr = AR / "v1.33-H" / "randomized_weekly_summary.csv"
    rows = [  # (이름, v1.31 계열 짝 (파일 · 기준선), 개선판 (파일 · 기준선))
        ("새 시드\n무작위 (90)", (AR / "v1.32-H" / "randomized_heating_summary.csv", "proposed_v131", None),
         (AR / "v1.32-H" / "randomized_heating_summary.csv", "proposed", None)),
        ("ASOS 2025\n실측 (90)", (AR / "v1.32-H" / "measured_weather_heating_2025_summary.csv", "proposed_v131", None),
         (AR / "v1.32-H" / "measured_weather_heating_2025_summary.csv", "proposed", None)),
        ("보류 3차\n재실행 (36)", (AR / "v1.32-H" / "heldout_heating_r3_rerun_summary.csv", "proposed_v131", None),
         (AR / "v1.32-H" / "heldout_heating_r3_rerun_summary.csv", "proposed", None)),
        ("보류 4차\n재실행 (36)", (AR / "v1.32-H" / "heldout_heating_r4_rerun_summary.csv", "proposed_v131", None),
         (AR / "v1.32-H" / "heldout_heating_r4_rerun_summary.csv", "proposed", None)),
    ]
    names, old, new, ann = [], [], [], []
    for name, (fo, bo, so), (fn, bn, sn) in rows:
        po, no = pass_rate(fo, bo, so)
        pn, nn = pass_rate(fn, bn, sn)
        names.append(name), old.append(100 * po / no), new.append(100 * pn / nn), ann.append((po, no, pn, nn))
    # 주말 외박 W2 — v1.32 짝 → v1.33 (기본 3 + 무작위 5)
    po = pass_rate(w, "proposed_v132", "W2")[0] + pass_rate(wr, "proposed_v132", "W2")[0]
    pn = pass_rate(w, "proposed", "W2")[0] + pass_rate(wr, "proposed", "W2")[0]
    n = pass_rate(w, "proposed", "W2")[1] + pass_rate(wr, "proposed", "W2")[1]
    names.append("주말 외박 뒤\n월 귀가 (8)"), old.append(100 * po / n), new.append(100 * pn / n), ann.append((po, n, pn, n))
    x = range(len(names))
    ax2.bar([i - 0.19 for i in x], old, width=0.36, color=OLD, label="v1.31-H (W2 는 v1.32-H)")
    ax2.bar([i + 0.19 for i in x], new, width=0.36, color=NEW, label="사후 개선판 (v1.32-H · W2 는 v1.33-H)")
    for i, (po, no, pn, nn) in enumerate(ann):
        ax2.text(i - 0.19, old[i] + 1.5, f"{po}", ha="center", color=INK2, fontsize=9)
        ax2.text(i + 0.19, new[i] + 1.5, f"{pn}", ha="center", color=INK, fontsize=9)
    ax2.set_xticks(list(x), names, fontsize=9)
    ax2.set_ylim(0, 112)
    ax2.set_ylabel("전체 통과율 (%) · 막대 위 = 통과 수")
    ax2.set_title("같은 새 데이터 · 짝 — 확정 결과 대 사후 개선판", loc="left", color=INK, fontsize=11)
    ax2.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, fontsize=9)
    ax2.grid(axis="x", visible=False)
    for a in (ax1, ax2):
        a.spines["left"].set_color(GRID)
    fig.tight_layout()
    out = REPO / "results" / "figures" / "heating_extension.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print(out.relative_to(REPO))


if __name__ == "__main__":
    main()
