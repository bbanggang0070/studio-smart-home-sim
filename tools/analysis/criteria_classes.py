"""판정 기준 3분류 집계 (2026-10-26 · 기준선 A′ 비교) — 환경 결과 · 수단 · 과정.

    uv run python tools/analysis/criteria_classes.py [summary.csv ...]   → 화면 + results/tables/criteria_classes.md

  환경 결과  실내 환경 · 물리량 · 자원 — 온도 · 습도 · PM · 결로 · CO₂ · 체감 · 공기 수지 · 전력 · 에너지 · 건조 시간 · 접촉력 · 기본 환기
  과정       제어기 내부 동작 — 이벤트 · 경보 · 모드 · 실행 가능성 · 명령 · 재실 판정 · 끼임 판정 · IR · 예산
  수단       그 밖 — 특정 장치를 어떤 상태로 쓰는지 (창문 · 팬 · 후드 · 블라인드 · 에어컨 모드 …)
과정 · 수단 기준은 제안 제어기의 설계를 묻는다 — 내부 상태가 없는 기준선(A · A2)은 원리상 지키기 어렵다.
기준선 비교의 주 지표는 '환경 결과 기준을 모두 지킨 실행' 비율이다. 판정 결과(criteria 열)를 다시 집계할 뿐 다시 돌리지 않는다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
PROCESS = re.compile(r"event_entered\(|alert_raised\(|mode_is\(|feasibility_is\(|ac_manual_detected|ac_sent|cmd_|occupied|"
                     r"pinch_events|pinch_stop|pinch_detect|ir_tx|budget|appliance_state")
OUTCOME = re.compile(r"\b(temperature|humidity|pm25|pm25_peak|dew_margin|co2|operative_temperature|q_net|total_power|energy_wh|"
                     r"energy_compare_wh|laundry_dry_time_s|max_contact_force_n|base_vent_compliance|comfort_ratio|"
                     r"humidity_recovery_time|overheat_time_s)\b")


def kind(text: str) -> str:
    if PROCESS.search(text):
        return "process"
    return "outcome" if OUTCOME.search(text) else "means"


def table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        cs = json.loads(r.criteria) if isinstance(r.criteria, str) else []
        cls = {"outcome": [], "means": [], "process": []}
        for st, text, *_ in cs:
            cls[kind(text)].append(st)
        row = {"scenario": r.scenario, "baseline": r.baseline, "all": r.status == "PASS"}
        for k, v in cls.items():
            row[k] = (all(s == "PASS" for s in v)) if v else None
            row[f"n_{k}"] = len(v)
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    srcs = sys.argv[1:] or ["results/summary.csv", "results/randomized/summary.csv", "results/measured_weather/summary.csv",
                            "results/heldout_r7/summary.csv"]
    lines = ["# 판정 기준 3분류 — 환경 결과 · 수단 · 과정 기준 통과율", "",
             "실행 통과 = 그 분류의 기준을 모두 지킴 · 분류 기준이 없는 실행은 제외 · `tools/analysis/criteria_classes.py`", ""]
    for src in srcs:
        p = REPO / src
        if not p.exists():
            continue
        df = pd.read_csv(p)
        df = df[df.status != "SKIPPED"]
        t = table(df)
        paired = set(t[t.baseline == "A"].scenario)        # A 를 돌리는 시나리오만 — 모든 기준선이 같은 시나리오 집합
        for title, tt in (("전체 시나리오", t), ("A 가 도는 시나리오만 (짝 비교 · 주 지표)", t[t.scenario.isin(paired)])):
          lines += [f"## {src} — {title}", "", "| 기준선 | 전체 | 환경 결과 | 수단 | 과정 |", "|---|---:|---:|---:|---:|"]
          for bl in ("A", "A2", "B", "proposed"):
            g = tt[tt.baseline == bl]
            if g.empty:
                continue

            def rate(col, g=g):
                x = g[col].dropna()
                return f"{int(x.sum())}/{len(x)} · {100 * x.mean():.1f} %" if len(x) else "–"
            lines.append(f"| {bl} | {rate('all')} | {rate('outcome')} | {rate('means')} | {rate('process')} |")
          lines.append("")
    out = REPO / "results" / "tables" / "criteria_classes.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
