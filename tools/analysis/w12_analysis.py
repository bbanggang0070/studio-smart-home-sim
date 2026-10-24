"""W12 분석 (T12.v2 · T12.v3 · T12.w3) — 고속 모드 로그로 표 · 그래프.

    uv run python tools/analysis/w12_analysis.py --raw <고속 배치 raw 폴더>

  C9  후드 단수 선택 근거 — 선택 시점에 예측한 단수별 PM 피크 vs 그 단수로 강제해 다시 돌린 실제 피크
  C10 가습 상한 확장 — 결로 상한(I4) · 실링팬 역회전으로 넓힌 상한 · 실내 습도
  C15 우선 목표(Proposed) vs 우선 목표 없음(Proposed−P) — 건조 시간 ↔ 온도 · 에너지
  X8  가전 프로파일 비교 — C1(에어컨 있음) vs X8(에어컨 없음) 수단 · 결과
결과: results/tables/*.csv · results/figures/*.png
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.use("Agg")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
for f in ("Noto Sans CJK JP", "Noto Sans CJK KR", "Noto Serif CJK SC"):
    if any(f in x.name for x in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break

from harness import runner as R  # noqa: E402
from harness.controllers import make_controller  # noqa: E402
from harness.scenario import Run, load_scenarios  # noqa: E402
from interfaces import topics as T  # noqa: E402

TAB, FIG = REPO / "results" / "tables", REPO / "results" / "figures"


class ForceHood:
    """요리 중 후드 단수를 강제 (예측 대조용) — 제어기가 후드 명령을 낼 때만 바꾼다."""

    def __init__(self, inner, level):
        self.inner, self.level = inner, level

    def __getattr__(self, k):
        return getattr(self.inner, k)

    def step(self, now, inbox):
        out = self.inner.step(now, inbox)
        if T.C_RANGE_HOOD_LEVEL in out and out[T.C_RANGE_HOOD_LEVEL] > 0:
            out[T.C_RANGE_HOOD_LEVEL] = self.level
        return out


def c9(hcfg, env) -> pd.DataFrame:
    sc = next(s for s in load_scenarios(REPO / hcfg["paths"]["scenarios"]) if s["id"] == "C9")
    run = Run(sc, "proposed", 1, sc["seed"])
    base = R.run_fast(run, hcfg, env, make_controller(hcfg["controllers"]["proposed"]), "proposed")
    reasons = base.df["ctrl.reasons"].astype(str)
    hit = reasons[reasons.str.contains("후드 예측 선택")].iloc[0]
    pred = ast.literal_eval(re.search(r"후드 예측 선택 (\{[^}]*\})", hit).group(1))
    chosen = int(base.df.loc[reasons.str.contains("후드 예측 선택"), "act.range_hood_level"].round().max())
    rows = []
    for lv in sorted(pred):
        r = R.run_fast(run, hcfg, env, ForceHood(make_controller(hcfg["controllers"]["proposed"]), lv), "proposed")
        rows.append({"hood_level": lv, "predicted_peak_ugm3": pred[lv], "actual_peak_ugm3": round(r.metrics["pm25_peak"], 1),
                     "chosen": int(lv == chosen)})
    return pd.DataFrame(rows)


def load(raw: Path, rid: str) -> pd.DataFrame:
    return pd.read_csv(raw / f"{rid}.csv")


def c10(raw: Path) -> None:
    d = load(raw, "C10_proposed_1")
    t = d["time_s"] / 60
    fig, ax = plt.subplots(2, 1, figsize=(16, 9), sharex=True)          # 1920 × 1080 (슬라이드)
    ax[0].plot(t, d["truth.humidity_pct"], color="#4d7c0f", lw=2, label="실내 습도")
    ax[0].plot(t, d["act.humidifier"].astype(float) * 5 + 35, color="#ca8a04", lw=1, label="가습기 (켜짐 = 40)")
    ax[0].set_ylabel("%")
    ax[0].legend(loc="lower right")
    ax[0].set_title("C10 — 겨울 가습: 결로 상한(I4) 안에서 가습 · 실링팬 역회전으로 창 표면을 데워 상한을 넓힌다")
    ax[1].plot(t, d["truth.dew_margin_c"], color="#b91c1c", lw=1.5, label="결로 여유 (창 표면 − 이슬점)")
    ax[1].plot(t, d["act.ceiling_fan"], color="#71717a", lw=1, label="실링팬 (−1 = 역회전)")
    ax[1].axhline(0, color="k", lw=0.6)
    ax[1].set_xlabel("시간 [분]")
    ax[1].legend(loc="upper right")
    for a in ax:
        a.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "c10_humidify_cap.png", dpi=120)


def c15(summary: pd.DataFrame) -> pd.DataFrame:
    d = summary[summary.scenario == "C15"]
    cols = [c for c in ("m.laundry_dry_time_s", "m.energy_wh", "m.overheat_time_s", "m.comfort_ratio") if c in d]
    t = d.groupby("baseline")[cols].mean().round(2)
    t["건조 시간 h"] = (t["m.laundry_dry_time_s"] / 3600).round(2)
    return t


def x8(raw: Path) -> pd.DataFrame:
    rows = []
    for rid, prof in (("C1_proposed_1", "P-full (에어컨 있음)"), ("X8_proposed_1", "P-core (에어컨 없음)")):
        d = load(raw, rid)
        ac = d["act.ac_power"].astype(str).eq("True")
        rows.append({"시나리오": rid.split("_")[0], "가전": prof, "창문 최대 %": round(d["act.window_open_ratio"].max() * 100),
                     "배기 평균 rpm": round(d["act.exhaust_fan_rpm"].mean()), "에어컨 가동 %": round(ac.mean() * 100),
                     "제습기 가동 %": round(d["act.dehumidifier"].astype(str).eq("True").mean() * 100),
                     "온도 시작 → 끝": f"{d['truth.temperature_c'].iloc[0]:.1f} → {d['truth.temperature_c'].iloc[-1]:.1f}",
                     "습도 시작 → 끝": f"{d['truth.humidity_pct'].iloc[0]:.0f} → {d['truth.humidity_pct'].iloc[-1]:.0f}"})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    a = ap.parse_args()
    raw = Path(a.raw)
    TAB.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    hcfg = R.load_harness_config()
    env = R.load_config(REPO / hcfg["paths"]["environment_model"])
    t9 = c9(hcfg, env)
    t9.to_csv(TAB / "c9_hood_prediction.csv", index=False)
    print("== C9 후드 단수: 예측 vs 실제 PM 피크\n" + t9.to_string(index=False))
    c10(raw)
    t15 = c15(pd.read_csv(raw.parent / "summary.csv"))
    t15.to_csv(TAB / "c15_priority_goal.csv")
    print("== C15 우선 목표 효과\n" + t15.to_string())
    t8 = x8(raw)
    t8.to_csv(TAB / "x8_profile_compare.csv", index=False)
    print("== C1 vs X8 가전 프로파일\n" + t8.to_string(index=False))


if __name__ == "__main__":
    main()
