"""X8(우천 · 에어컨 없는 방 — 배기팬 최대) vs C8(외기 미세먼지 등급 — 나쁠수록 창문 · 배기 단계적 감소, 매우나쁨 정지) 대비 (W12 DoD).

    uv run python tools/analysis/plot_x8_c8.py      → results/figures/x8_vs_c8.png
C1(에어컨 있는 방)은 v3.0 부터 에어컨이 냉방 · 제습을 맡아 배기팬을 쓰지 않는다 — 비에 배기팬이 대신하는 것은 X8(P-core).
같은 '창문을 못 쓴다'는 제약이라도 원인이 다르면 배기팬이 반대로 움직인다 — 비는 팬이 대신하고, 오염 외기는 팬도 막는다.
W13 (2026-10-15): C8 은 에어컨 있는 방(full) · 외기 27 °C — 외기가 냉방 목표보다 더워 처음부터 에어컨이 냉방을 맡는다(docs/07 v1.21).
그래서 C8 쪽은 '등급별 팬 단계 감소'가 아니라 '오염 외기 → 배기팬 0 · 필터 흡기 · 에어컨'을 보여 준다 (사용자 결정 · 시나리오 입력 유지).
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


def load(sid: str) -> pd.DataFrame:
    for d in ("results/raw", "results/w12/raw"):
        p = REPO / d / f"{sid}_proposed_1.csv"
        if p.exists():
            return pd.read_csv(p)
    raise FileNotFoundError(sid)


def main() -> None:
    c1, c8 = load("X8"), load("C8")
    fig, ax = plt.subplots(2, 2, figsize=(16, 9), sharey="row")   # 발표 1920 × 1080 (W13 T13.5b)
    for col, (d, title) in enumerate(((c1, "X8 · 고온다습 + 우천 · 에어컨 없음"), (c8, "C8 · 고온 + 외기 미세먼지 (보통 → 나쁨 → 매우나쁨) · 에어컨 있음"))):
        t = d["time_s"] / 60
        ax[0, col].plot(t, d["act.exhaust_fan_rpm"], color="#4d7c0f", lw=2, label="배기팬")
        ax[0, col].plot(t, d["act.intake_fan_rpm"], color="#ca8a04", lw=1.5, label="흡기팬 (필터)")
        ax[0, col].plot(t, d["act.window_open_ratio"] * 2000, color="#71717a", lw=1.5, ls="--", label="창문 × 2000")
        ac = pd.to_numeric(d.get("act.ac_cool", pd.Series(0, index=d.index)), errors="coerce").fillna(0).astype(bool)
        if ac.any():
            ax[0, col].fill_between(t, 0, 1500, where=ac, color="#2563eb", alpha=0.10, step="post", lw=0, label="에어컨 냉방")
        ax[0, col].set_title(title)
        ax[1, col].plot(t, d["truth.pm25_ugm3"], color="#b91c1c", lw=1.8, label="실내 PM2.5")
        if "ext.outdoor_pm25_ugm3" in d:
            ax[1, col].plot(t, d["ext.outdoor_pm25_ugm3"], color="#b91c1c", lw=1, ls=":", label="외기 PM2.5")
        ax[1, col].set_xlabel("시간 [분]")
        for a in ax[:, col]:
            a.grid(alpha=0.3)
    ax[0, 0].set_ylabel("rpm")
    ax[1, 0].set_ylabel("µg/m³")
    ax[0, 0].legend(loc="upper right")
    ax[1, 1].legend(loc="upper left")
    ax[0, 1].legend(loc="upper right")
    fig.suptitle("창문을 못 쓰는 이유가 다르면 배기팬은 반대로 — 비(X8 · 에어컨 없음)는 배기팬이 냉방을 대신하고, "
                 "오염 외기(C8)는 배기팬을 끄고(음압 유입 차단) 필터 흡기 + 에어컨으로 바꾼다")
    out = REPO / "results" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out / "x8_vs_c8.png", dpi=120)
    print("저장: results/figures/x8_vs_c8.png")


if __name__ == "__main__":
    main()
