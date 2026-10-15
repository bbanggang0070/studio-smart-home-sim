"""센서리스 성능 그래프 (W13 T13.6) — 정상 닫힘 vs 끼임 닫힘: 전류 파형 · Zone 전환 · 리플 추정 위치 · 검출 순간.

    tools/ros/run.sh node tools/ros/sensorless_trace.py     # 먼저 기록 (Isaac 브릿지 + 안전 노드)
    uv run python tools/analysis/plot_sensorless.py         → results/figures/sensorless_trace.png · results/tables/sensorless_summary.csv

임계값(전류 차단 · 끼임 판정)은 thresholds window_sensorless 에서 읽어 선으로 그린다.
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
sys.path.insert(0, str(REPO / "scripts"))
from controller.params import load_params  # noqa: E402

for f in ("Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Serif CJK KR", "Noto Serif CJK SC"):
    if any(f in x.name for x in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False

CUR, EST, POS = "/studio/sensor/window_motor_current", "/studio/state/window_position_est", "/studio/state/window_open_ratio"
ZONE, SAFE = "/studio/state/window_zone", "/studio/state/safety_state"
ZONES = ["A_START", "B_RUN", "C_ENDZONE", "D_SEAL"]
ZCOL = {"A_START": "#dbeafe", "B_RUN": "#f1f5f9", "C_ENDZONE": "#fef3c7", "D_SEAL": "#fee2e2"}


def series(d: pd.DataFrame, topic: str) -> pd.Series:
    x = d[d.topic == topic]
    return pd.Series(x.value.to_numpy(), index=x.t_s.to_numpy())


def main() -> None:
    ws = load_params().get("window_sensorless")
    travel_mm = float(ws["travel_length_m"]) * 1000.0
    d = pd.read_csv(REPO / "results" / "sensorless" / "trace.csv")
    phases = [("normal_close", "① 정상 닫힘 (엔드존 · 씰 압착 포함)"), ("pinch_close", "② 끼임 닫힘 (강체 화분)")]
    fig, ax = plt.subplots(3, 2, figsize=(16, 9), sharex="col", gridspec_kw={"height_ratios": [2.2, 1.6, 1]})
    summary = []
    for col, (ph, title) in enumerate(phases):
        x = d[d.phase == ph]
        t0 = x.t_s.min()
        cur = series(x, CUR).astype(float)
        est = series(x, EST).astype(float) * 1000.0
        pos = series(x, POS).astype(float) * travel_mm
        zone = series(x, ZONE).astype(str)
        safe = series(x, SAFE).astype(str)
        end = t0 + (12.0 if ph == "normal_close" else 14.0)              # 움직임이 있는 앞부분만
        sl = lambda s: s[(s.index >= t0) & (s.index <= end)]  # noqa: E731
        cur, est, pos, zone, safe = map(sl, (cur, est, pos, zone, safe))
        # Zone 배경
        zt = zone.index.to_numpy() - t0
        for i in range(len(zt) - 1):
            for a in ax[:, col]:
                a.axvspan(zt[i], zt[i + 1], color=ZCOL.get(zone.iloc[i], "white"), lw=0)
        ax[0, col].plot(cur.index - t0, cur.to_numpy(), color="#1d4ed8", lw=1.0, label="모터 전류 (리플 · 잡음 포함)")
        i_cut = float(ws["layered_safety"]["local_cutoff_current_a"])
        ax[0, col].axhline(i_cut, color="#b91c1c", ls="--", lw=1.2, label=f"로컬 전류 차단 {i_cut:.2f} A (Zone D 씰 압착에선 끔)")
        ax[1, col].plot(pos.index - t0, pos.to_numpy(), color="#111827", lw=2.0, label="실제 위치 (조인트)")
        ax[1, col].plot(est.index - t0, est.to_numpy(), color="#ea580c", lw=1.2, ls="--", label="리플 카운팅 추정")
        sv = safe.map({"NORMAL": 0, "PINCH_REVERSE": 1, "SAFETY_HOLD": 2}).fillna(3)
        ax[2, col].step(sv.index - t0, sv.to_numpy(), where="post", color="#7c3aed", lw=2)
        ax[2, col].set_yticks([0, 1, 2], ["NORMAL", "끼임 반전", "정지 유지"])
        ax[0, col].set_title(title)
        ax[2, col].set_xlabel("닫기 지령 후 시간 [s]")
        det = safe[safe != "NORMAL"]
        t_det = float(det.index[0] - t0) if len(det) else np.nan
        if not np.isnan(t_det):
            for a in ax[:, col]:
                a.axvline(t_det, color="#7c3aed", ls=":", lw=1.5)
            ax[1, col].annotate(f"검출 {t_det:.2f} s · 위치 {np.interp(det.index[0], pos.index, pos.to_numpy()):.0f} mm",
                                (t_det, np.interp(det.index[0], pos.index, pos.to_numpy())), xytext=(-200, 40),
                                textcoords="offset points", arrowprops={"arrowstyle": "->"})
        err = (est - np.interp(est.index, pos.index, pos.to_numpy())).abs()
        summary.append({"phase": ph, "detect_s": t_det, "zones": " → ".join(dict.fromkeys(zone)),
                        "current_peak_a": float(cur.max()), "pos_est_err_max_mm": float(err.max()),
                        "contact_peak_n": float(pd.to_numeric(series(x, "local.contact_peak_n"), errors="coerce").max())})
    ax[0, 0].set_ylabel("전류 [A]")
    ax[1, 0].set_ylabel("위치 [mm] (0 = 닫힘)")
    ax[2, 0].set_ylabel("안전 상태")
    ax[0, 1].legend(loc="upper right")
    ax[1, 0].legend(loc="upper right")
    handles = [plt.Rectangle((0, 0), 1, 1, color=ZCOL[z]) for z in ZONES]
    fig.legend(handles, ["Zone A 기동", "Zone B 주행", "Zone C 엔드존", "Zone D 씰 압착"], loc="lower center", ncols=4)
    fig.suptitle("센서리스 창문 — 정상 닫힘은 엔드존 · 씰에서 전류가 올라도 끼임으로 보지 않고, 주행 중 반력 상승은 끼임으로 검출해 반전한다")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    out = REPO / "results" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "sensorless_trace.png", dpi=120)
    tab = REPO / "results" / "tables"
    tab.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summary).to_csv(tab / "sensorless_summary.csv", index=False)
    print(pd.DataFrame(summary).round(3).to_string(index=False))
    print("저장: results/figures/sensorless_trace.png · results/tables/sensorless_summary.csv")


if __name__ == "__main__":
    main()
