"""의사결정 추적표 (W13 T13.v4 · docs/07 §5.4 형식) — 하네스 로그의 `ctrl.reasons` 에서 결정이 바뀐 시각만 뽑는다.

    uv run python tools/analysis/decision_trace.py C9 [baseline=proposed] [rep=1]
        → results/tables/decision_trace_C9.md · .csv

열: 시각 · 관측(실내 · 외기 PM, 온도, 습도) · 활성 이벤트 · 결정(바뀐 장치 = 새 값) · 사유(그 장치의 중재 사유)
'기본값'으로 돌아간 장치는 '해제'로 적는다. 같은 장치가 10 s 안에 다시 바뀌면 마지막 값만 남긴다 (중재 과도 상태).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
MERGE_S = 10.0
SKIP = {"desk_cct"}                      # 색온도는 모드에서 고정 — 표가 길어지기만 한다


def _parse(cell) -> dict[str, tuple[str, str]]:
    out = {}
    for item in json.loads(cell) if isinstance(cell, str) else []:
        dev_val, _, why = item.partition(" ← ")
        dev, _, val = dev_val.partition("=")
        out[dev] = (val, why)
    return out


def _key(dev: str, val: str):
    """비교용 값 — 에어컨은 전원 · 모드 · 설정만(seq 제외), 연속값은 1 % 단위로 반올림."""
    if dev == "ac":
        try:
            a = json.loads(val)
            return (a.get("power"), a.get("mode") if a.get("power") else None, a.get("setpoint") if a.get("power") else None)
        except json.JSONDecodeError:
            return val
    try:
        v = float(val)
        return round(v, 1) if abs(v) < 10 else round(v, -1 if abs(v) >= 100 else 0)
    except ValueError:
        return val


def _short(dev: str, val: str) -> str:
    if dev == "ac":
        try:
            a = json.loads(val)
            return f"에어컨 {a.get('mode')} {a.get('setpoint')} °C" if a.get("power") else "에어컨 끔"
        except json.JSONDecodeError:
            return f"에어컨 {val}"
    try:
        v = float(val)
        val = f"{v:.0f}" if abs(v) >= 10 else f"{v:g}"
    except ValueError:
        pass
    return f"{dev} {val}"


def main() -> None:
    sid = sys.argv[1] if len(sys.argv) > 1 else "C9"
    bl = sys.argv[2] if len(sys.argv) > 2 else "proposed"
    rep = sys.argv[3] if len(sys.argv) > 3 else "1"
    d = pd.read_csv(REPO / "results" / "raw" / f"{sid}_{bl}_{rep}.csv", low_memory=False)
    ev_col = "/studio/state/active_events"
    prev: dict[str, tuple[str, str]] = {}
    prev_ev = None
    rows: list[dict] = []
    for _, r in d.iterrows():
        cur = _parse(r.get("ctrl.reasons"))
        if not cur:
            continue
        ev = ", ".join(json.loads(r[ev_col])) if isinstance(r.get(ev_col), str) else ""
        changed = {k: v for k, v in cur.items()
                   if k not in SKIP and (k not in prev or _key(k, prev[k][0]) != _key(k, v[0]))}
        if changed or ev != prev_ev:
            t = float(r["time_s"])
            if rows and t - rows[-1]["t"] <= MERGE_S and rows[-1]["events"] == ev:
                rows[-1]["changes"].update(changed)          # 과도 상태 — 앞 행에 합친다
            else:
                rows.append({"t": t, "events": ev, "changes": dict(changed),
                             "obs": f"실내 PM {r['truth.pm25_ugm3']:.0f} · 외기 {r.get('ext.outdoor_pm25_ugm3', float('nan')):.0f} µg/m³ · "
                                    f"{r['truth.temperature_c']:.1f} °C · {r['truth.humidity_pct']:.0f} %RH"})
        prev, prev_ev = cur, ev
    lines = [f"# 의사결정 추적 — {sid} · {bl} · 반복 {rep} (docs/07 §5.4 형식 · 자동 생성)", "",
             "| 시각 | 관측 | 활성 이벤트 | 결정 | 사유 |", "|---|---|---|---|---|"]
    flat = []
    for row in rows:
        ch = row["changes"]
        dec = " · ".join("해제 " + k if why == "기본값" else _short(k, v) for k, (v, why) in ch.items()) or "–"
        why = " · ".join(sorted({w for _, w in ch.values() if w != "기본값"})) or "–"
        m, s = divmod(int(row["t"]), 60)
        lines.append(f"| {m}:{s:02d} | {row['obs']} | {row['events'] or '–'} | {dec} | {why} |")
        flat.append({"t_s": row["t"], "observation": row["obs"], "events": row["events"], "decision": dec, "reason": why})
    out = REPO / "results" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"decision_trace_{sid}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    pd.DataFrame(flat).to_csv(out / f"decision_trace_{sid}.csv", index=False)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
