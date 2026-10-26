"""실측 기상 평가 (docs/11 필수 조치 3) — 평가 연도의 실측(재분석) 시간별 기상으로 고속 시나리오 전체를 돌린다.

    uv run python tools/run_measured_weather.py [--samples 5] [--workers 16] [--ids C1,C8] [--no-raw]
        → results/measured_weather/summary.csv (실행마다 지표 · 판정 · 고른 날 · 시작 외기) · raw/<run_id>.csv

설정: config/harness.yaml weather. 평가 연도(years.eval)만 읽는다 — 학습 연도는 학습 도구 몫.
시나리오마다 시작 시각 · 시작 외기(기온 · 습도 · 비 여부)가 전제와 가까운 날을 samples 개 고르고,
그날의 기온 · 습도 · 일사 · 하늘 · 풍속 변화를 그대로 넣는다. 시나리오 events 가 바꾸는 외기 키(시험 자극)는 시나리오 값.
같은 (시나리오, 날)은 모든 기준선이 같은 조건 · 참값 계수는 명목값 · 판정 · 지표는 동결된 정의(시작 때 점검).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from env_model import load_config  # noqa: E402
from harness import weather as W  # noqa: E402
from harness.manifest import write_manifest  # noqa: E402
from harness.controllers import make_controller  # noqa: E402
from harness.runner import judge_group, load_harness_config, run_fast  # noqa: E402
from harness.scenario import Run, load_scenarios  # noqa: E402

_SERIES: pd.DataFrame | None = None


def series(cfg: dict) -> pd.DataFrame:
    global _SERIES
    if _SERIES is None:
        _SERIES = W.load_series(cfg, REPO, "eval")
    return _SERIES


def one(args):
    sid, rep, start_iso, scale, keep_raw = args
    hcfg = load_harness_config()
    cfg = hcfg["weather"]
    env_cfg = load_config(REPO / hcfg["paths"]["environment_model"])
    eff = float(env_cfg.get("thermal.solar_luminous_efficacy_lm_per_w"))
    sc0 = next(s for s in load_scenarios(REPO / hcfg["paths"]["scenarios"]) if s["id"] == sid)
    start = pd.Timestamp(start_iso)
    sc = W.apply_to_scenario(sc0, series(cfg), start, cfg, eff)
    out = REPO / cfg["out_dir"] / "raw"
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for bl in sc["baselines"]:
        run = Run(scenario=sc, baseline=bl, rep=rep, seed=int(sc["seed"]) + rep)
        spec = hcfg["controllers"][bl]
        r = run_fast(run, hcfg, env_cfg, make_controller(spec), spec)
        if keep_raw and r.df is not None:
            r.df.to_csv(out / f"{run.run_id}.csv", index=False)
        results.append(r)
    judge_group(results)
    seg = series(cfg).loc[start:start + pd.Timedelta(seconds=float(sc["duration_s"]))]
    sky = [W.sky_of(float(p), float(c), cfg) for p, c in zip(seg["precip_mm"], seg["cloud_pct"])]
    cond = {"w.start": start.isoformat(), "w.match_scale": scale, "w.keys": ",".join(sc["weather_source"]["keys"]),
            **{f"w.{k}": sc["external"][k] for k in W.SERIES_KEYS},
            "w.temp_min": float(seg["outdoor_temp_c"].min()), "w.temp_max": float(seg["outdoor_temp_c"].max()),
            "w.ghi_max": float(seg["ghi_w_m2"].max()), "w.rain_hours": int(sum(s == "rain" for s in sky)),
            "w.nominal_temp": float(sc0["external"]["outdoor_temp_c"]), "w.nominal_rh": float(sc0["external"]["outdoor_rh_pct"])}
    rows = []
    for r in results:
        row = {"run_id": r.run.run_id, "scenario": sid, "baseline": r.run.baseline, "rep": rep, "status": r.status,
               "criteria_pass": sum(c.status == "PASS" for c in r.criteria), "criteria_total": len(r.criteria),
               "criteria": json.dumps([[c.status, c.text, c.detail] for c in r.criteria], ensure_ascii=False), **cond}
        row.update({f"m.{k}": v for k, v in r.metrics.items()})
        rows.append(row)
    return rows


def main() -> None:
    hcfg = load_harness_config()
    cfg = hcfg["weather"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=cfg["samples"])
    ap.add_argument("--workers", type=int, default=cfg["workers"])
    ap.add_argument("--ids", default="")
    ap.add_argument("--no-raw", action="store_true")   # 시계열을 저장하지 않는다 (디스크 절약 — 요약 · 판정만)
    a = ap.parse_args()
    chk = subprocess.run([sys.executable, str(REPO / "tools" / "check_freeze.py")], capture_output=True, text=True)
    print(chk.stdout.strip())
    if chk.returncode != 0:
        sys.exit("동결된 판정 · 지표가 바뀌었다 — docs/12 동결 개정을 먼저 기록할 것")
    scen = [s for s in load_scenarios(REPO / hcfg["paths"]["scenarios"]) if s["run_mode"] == "fast"]
    if a.ids:
        scen = [s for s in scen if s["id"] in a.ids.split(",")]
    ser = series(cfg)
    jobs = []
    for s in scen:
        rng = np.random.default_rng(int(cfg["seed"]) + int(s["seed"]))
        starts, scale = W.match_starts(ser, s, cfg, a.samples, rng)
        widen = "" if scale == 1.0 else f" (허용 차이 ×{scale:g})"
        print(f"{s['id']}: {', '.join(t.strftime('%m-%d') for t in starts)}{widen}")
        jobs += [(s["id"], k + 1, t.isoformat(), scale, not a.no_raw) for k, t in enumerate(starts)]
    print(f"시나리오 {len(scen)}개 × 날 {a.samples} = {len(jobs)}묶음 · 평가 연도 {cfg['years']['eval']} · 병렬 {a.workers}", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for part in ex.map(one, jobs):
            rows += part
    df = pd.DataFrame(rows)
    out = REPO / cfg["out_dir"]
    df.to_csv(out / "summary.csv", index=False)
    write_manifest(out, {"kind": "measured_weather", "samples": a.samples, "eval_years": cfg["years"]["eval"], "runs": len(df)})
    p = df[df.baseline == "proposed"]
    print(f"실행 {len(df)}회 · 제안 판정 통과 {int((p.status == 'PASS').sum())}/{len(p)}")


if __name__ == "__main__":
    main()
