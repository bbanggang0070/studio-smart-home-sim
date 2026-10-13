"""상충 제어 점검 (v3.4.18) — 서로 효과를 깎는 동시 동작을 고속 모드 로그에서 찾는다.

    uv run python tools/audit_conflicts.py                 # 고속 시나리오 전체 · 제안 제어기 1회씩 실행 후 점검
    uv run python tools/audit_conflicts.py --raw results/raw --baseline proposed   # 이미 있는 로그만 점검

규칙 (기준값 config/harness.yaml conflict_audit — 기본 환기 틈 · 요리 중 보충 공기는 예외):
  R1 에어컨 냉방 + 창문 열림            냉기가 빠져나간다
  R2 블라인드 닫힘 + 환기 냉방          창 안쪽 블라인드가 바람을 막는다
  R3 제습 + 가습 동시
  R4 제습 + 더 습한 외기 유입
  R5 가습 + 더 건조한 외기 유입
  R6 공기청정기 + 더 탁한 외기 유입
  R7 더운 날 더 더운 외기 유입
  R8 에어컨 냉방 + 배기 강               냉기를 내보낸다
  R9 에어컨 냉방 + 일사 중 블라인드 열림  막을 수 있는 열을 들인다
  R10 냉방 수단 공백                    덥고 외기가 더 시원한데 에어컨 · 창문 · 배기 · 흡기 어느 것도 안 쓴다 (없는 수단을 기다림)
결과: 규칙 × 시나리오별 해당 초 · 처음 시각 · 그때 제어기 사유(관련 장치만)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from harness.runner import load_harness_config, run_batch  # noqa: E402

RULES = {
    "R1": ("에어컨 냉방 + 창문 열림", ("ac", "window")),
    "R2": ("블라인드 닫힘 + 환기 냉방", ("blind", "window")),
    "R3": ("제습 + 가습 동시", ("dehumidifier", "humidifier")),
    "R4": ("제습 + 더 습한 외기", ("dehumidifier", "ac", "window")),
    "R5": ("가습 + 더 건조한 외기", ("humidifier", "window")),
    "R6": ("청정기 + 더 탁한 외기", ("purifier", "window")),
    "R7": ("더운 외기 유입", ("window",)),
    "R8": ("에어컨 냉방 + 배기 강", ("ac", "exhaust")),
    "R9": ("에어컨 냉방 + 일사 중 블라인드 열림", ("ac", "blind")),
    "R10": ("냉방 수단 공백", ("ac", "window", "exhaust", "intake")),
}


def masks(d: pd.DataFrame, c: dict) -> dict[str, pd.Series]:
    num = lambda col: pd.to_numeric(d[col], errors="coerce").fillna(0.0) if col in d else pd.Series(0.0, index=d.index)  # noqa: E731
    flag = lambda col: d[col].astype(str).isin(["True", "1", "1.0"]) if col in d else pd.Series(False, index=d.index)  # noqa: E731
    win = num("act.window_open_ratio") > c["window_open_min"]
    hood = num("act.range_hood_level") > 0
    t_in, t_out = num("truth.temperature_c"), num("ext.outdoor_temp_c")
    dew_in, dew_out = num("truth.dew_point_c"), num("ext.outdoor_dew_c")
    ac_cool, ac_dry = flag("act.ac_cool"), flag("act.ac_dry")
    dehum, hum = flag("act.dehumidifier") | ac_dry, flag("act.humidifier")
    blind = num("act.blind_angle_deg")
    rain = flag("ext.raining")
    return {
        "R1": ac_cool & win & ~hood,
        "R2": win & (blind >= c["blind_closed_min_deg"]) & (t_out <= t_in - c["outdoor_cooler_c"]) & ~rain & ~hood,
        "R3": dehum & hum,
        "R4": dehum & win & (dew_out > dew_in + c["dew_margin_c"]) & ~hood,
        "R5": hum & win & (dew_out < dew_in - c["dry_margin_c"]) & ~hood,
        "R6": (num("act.purifier_level") > 0) & win & (num("ext.outdoor_pm25_ugm3") > num("truth.pm25_ugm3")) & ~hood,
        "R7": win & (t_out >= t_in + c["outdoor_warmer_c"]) & (t_in >= c["hot_indoor_c"]) & ~hood,
        "R8": ac_cool & (num("act.exhaust_fan_rpm") >= c["exhaust_high_rpm"]) & ~hood,
        "R9": ac_cool & (blind <= c["open_blind_max_deg"]) & (num("ext.outdoor_illuminance_lux") >= c["sunny_outdoor_lux"]),
        "R10": (t_in >= c["cooling_gap_above_c"]) & (t_out <= t_in - c["outdoor_cooler_c"]) & ~ac_cool & ~ac_dry
               & (num("act.window_open_ratio") <= c["window_open_min"]) & (num("act.exhaust_fan_rpm") < 1.0)
               & (num("act.intake_fan_rpm") < c["exhaust_high_rpm"] / 2) & (num("truth.occupied") > 0),
    }


def reason_for(d: pd.DataFrame, i: int, devices: tuple[str, ...]) -> str:
    if "ctrl.reasons" not in d:
        return ""
    parts = [p for p in str(d["ctrl.reasons"].iloc[i]).split(" | ") if p.split("=")[0].strip() in devices]
    return " | ".join(parts)[:220]


def sustained(m: pd.Series, n: int) -> pd.Series:
    """n 샘플 이상 이어진 구간만 남긴다 (과도 상태 제외)."""
    run_id = (m != m.shift()).cumsum()
    length = m.groupby(run_id).transform("size")
    return m & (length >= n)


def audit(frames: dict[str, pd.DataFrame], c: dict, dt: float = 1.0) -> pd.DataFrame:
    rows = []
    n_min = max(1, int(round(c["min_duration_s"] / dt)))
    for run_id, d in frames.items():
        for rule, m in masks(d, c).items():
            m = sustained(m.reset_index(drop=True), n_min)
            d = d.reset_index(drop=True)
            if m.any():
                i = int(m.to_numpy().nonzero()[0][0])
                rows.append({"규칙": rule, "내용": RULES[rule][0], "실행": run_id, "초": int(m.sum() * dt),
                             "처음 s": int(d["time_s"].iloc[i]), "그때 사유": reason_for(d, i, RULES[rule][1])})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="", help="이미 있는 고속 모드 로그 폴더 (없으면 새로 실행)")
    ap.add_argument("--baseline", default="proposed")
    ap.add_argument("--out", default=str(REPO / "results" / "audit"))
    args = ap.parse_args()
    hcfg = load_harness_config()
    c = hcfg["conflict_audit"]
    if args.raw:
        frames = {p.stem: pd.read_csv(p) for p in sorted(Path(args.raw).glob(f"*_{args.baseline}_*.csv"))}
    else:
        res = run_batch(None, baselines=[args.baseline], reps=1, out_dir=args.out, progress=lambda *_: None)
        frames = {r.run.run_id: r.df for r in res if r.df is not None}
    rep = audit(frames, c)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    rep.to_csv(Path(args.out) / "conflicts.csv", index=False)
    print(f"점검한 실행 {len(frames)}개 · 상충 {len(rep)}건")
    if len(rep):
        pd.set_option("display.width", 250, "display.max_colwidth", 120)
        print(rep.sort_values(["규칙", "초"], ascending=[True, False]).to_string(index=False))


if __name__ == "__main__":
    main()
