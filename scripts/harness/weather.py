"""실측(재분석) 시간별 기상 → 시나리오 외기 조건 (docs/11 필수 조치 3) — 순수 함수 · ROS 의존 없음.

  load_series(cfg, repo, split)      학습(train) / 평가(eval) 연도만 읽는다 — 섞어 읽는 길을 두지 않는다
  external_at(series, ts, ...)       시각 ts 의 외기 (수치는 시간별 값 선형 보간 · 하늘은 가까운 시각)
  match_starts(series, sc, ...)      시나리오 시작 시각과 같은 시각 중 시작 외기가 전제와 가까운 날
  apply_to_scenario(sc, ...)         시나리오 사본 — external 시작값 + event_step_s 간격 외기 이벤트

일사 [W/m²] → 바깥 수평 조도 [lux] 는 참값 환경 모델과 같은 발광 효율(thermal.solar_luminous_efficacy_lm_per_w)로 바꾼다
— 조도로 받은 값을 환경 모델이 다시 일사로 되돌리므로 열 입력이 실측 일사와 같다.
설정: config/harness.yaml weather
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

COLS = {"temperature_2m": "outdoor_temp_c", "relative_humidity_2m": "outdoor_rh_pct",
        "shortwave_radiation": "ghi_w_m2", "precipitation": "precip_mm", "cloud_cover": "cloud_pct",
        "wind_speed_10m": "wind_speed_ms"}
# 시나리오에 넣는 외기 키 (PM2.5 · 난방 경계는 시나리오 값을 쓴다)
SERIES_KEYS = ("outdoor_temp_c", "outdoor_rh_pct", "outdoor_illuminance_lux", "wind_speed_ms", "weather")


def load_series(cfg: dict, repo: Path, split: str) -> pd.DataFrame:
    """split = 'train' | 'eval' → 시간별 표 (index = 현지 시각)."""
    frames = [pd.read_csv(repo / cfg["data_dir"] / f"{cfg['site']['name']}_{y}.csv") for y in cfg["years"][split]]
    df = pd.concat(frames, ignore_index=True).rename(columns=COLS)
    df.index = pd.to_datetime(df.pop("time"))
    # 일사는 앞 1시간 평균 — radiation_lag_h 만큼 앞 시각 값으로 옮긴다 (보간 뒤 다시 정시에 맞춘다)
    ghi = df["ghi_w_m2"].copy()
    ghi.index = ghi.index - pd.Timedelta(hours=float(cfg["radiation_lag_h"]))
    grid = ghi.index.union(df.index)
    df["ghi_w_m2"] = ghi.reindex(grid).interpolate(method="time").reindex(df.index).fillna(0.0).clip(lower=0.0)
    return df


def sky_of(precip_mm: float, cloud_pct: float, cfg: dict) -> str:
    if precip_mm >= float(cfg["rain_mm_per_h"]):
        return "rain"
    if cloud_pct <= float(cfg["sky_cloud_pct"]["clear"]):
        return "clear"
    if cloud_pct <= float(cfg["sky_cloud_pct"]["cloudy"]):
        return "cloudy"
    return "overcast"


def external_at(series: pd.DataFrame, ts: pd.Timestamp, cfg: dict, efficacy_lm_per_w: float) -> dict[str, Any]:
    i = int(series.index.searchsorted(ts, side="right")) - 1
    i = min(max(i, 0), len(series) - 1)
    j = min(i + 1, len(series) - 1)
    t0, t1 = series.index[i], series.index[j]
    w = 0.0 if t1 == t0 else float(np.clip((ts - t0) / (t1 - t0), 0.0, 1.0))
    a, b = series.iloc[i], series.iloc[j]
    near = a if w < 0.5 else b

    def lerp(k: str) -> float:
        return float(a[k] + w * (b[k] - a[k]))

    return {"outdoor_temp_c": round(lerp("outdoor_temp_c"), 2),
            "outdoor_rh_pct": round(min(max(lerp("outdoor_rh_pct"), 0.0), 100.0), 1),
            "outdoor_illuminance_lux": round(lerp("ghi_w_m2") * efficacy_lm_per_w, 0),
            "wind_speed_ms": round(lerp("wind_speed_ms"), 2),
            "weather": sky_of(float(near["precip_mm"]), float(near["cloud_pct"]), cfg)}


def staged_keys(sc: dict) -> set[str]:
    """시나리오 events 가 바꾸는 외기 키 — 시험 자극이므로 시나리오 값을 지킨다."""
    return {k for ev in sc.get("events") or [] for k in (ev.get("set") or {}) if k in SERIES_KEYS}


def match_starts(series: pd.DataFrame, sc: dict, cfg: dict, n: int, rng: np.random.Generator) -> tuple[list[pd.Timestamp], float]:
    """→ (시작 시각 n 개, 허용 차이 배율). 시작 시각의 기온 · 습도 · 비 여부가 시나리오 전제와 가까운 날 (서로 다른 날)."""
    hh, mm = str(sc["initial"].get("time_of_day", "00:00")).split(":")
    ext = sc["external"]
    m = cfg["match"]
    span = pd.Timedelta(seconds=float(sc["duration_s"]))
    days = pd.date_range(series.index[0].normalize(), series.index[-1].normalize(), freq="D")
    starts = [d + pd.Timedelta(hours=int(hh), minutes=int(mm)) for d in days]
    starts = [s for s in starts if s + span <= series.index[-1]]
    want_rain = ext.get("weather") == "rain"
    eff = 1.0   # 매칭에는 조도가 필요 없다
    rows = [(s, external_at(series, s, cfg, eff)) for s in starts]
    scale = 1.0
    for _ in range(int(m["max_widen"]) + 1):
        ok = [s for s, e in rows
              if abs(e["outdoor_temp_c"] - float(ext["outdoor_temp_c"])) <= m["temp_c"] * scale
              and abs(e["outdoor_rh_pct"] - float(ext["outdoor_rh_pct"])) <= m["rh_pct"] * scale
              and (e["weather"] == "rain") == want_rain]
        if len(ok) >= n:
            pick = rng.choice(len(ok), size=n, replace=False)
            return sorted(ok[int(k)] for k in pick), scale
        scale *= float(m["widen"])
    # 넓혀도 모자라면 가장 가까운 날들 (기온 · 습도 차이를 허용치로 나눈 거리)
    def dist(e: dict) -> float:
        return (abs(e["outdoor_temp_c"] - float(ext["outdoor_temp_c"])) / m["temp_c"]
                + abs(e["outdoor_rh_pct"] - float(ext["outdoor_rh_pct"])) / m["rh_pct"]
                + (0.0 if (e["weather"] == "rain") == want_rain else 100.0))
    rows.sort(key=lambda r: dist(r[1]))
    return sorted(s for s, _ in rows[:n]), float("inf")


def apply_to_scenario(sc: dict, series: pd.DataFrame, start: pd.Timestamp, cfg: dict,
                      efficacy_lm_per_w: float) -> dict:
    """시나리오 사본 — 자극 키(staged)는 그대로 · 나머지 외기는 실측 시계열."""
    sc = copy.deepcopy(sc)
    keep = staged_keys(sc)
    keys = [k for k in SERIES_KEYS if k not in keep]
    e0 = external_at(series, start, cfg, efficacy_lm_per_w)
    for k in keys:
        sc["external"][k] = e0[k]
    step = float(cfg["event_step_s"])
    evs = list(sc.get("events") or [])
    t = step
    while t < float(sc["duration_s"]):
        e = external_at(series, start + pd.Timedelta(seconds=t), cfg, efficacy_lm_per_w)
        evs.append({"at_s": t, "set": {k: e[k] for k in keys}, "label": "measured_weather"})
        t += step
    sc["events"] = evs
    sc["weather_source"] = {"start": start.isoformat(), "keys": keys}
    return sc
