"""실측(재분석) 시간별 기상 받기 (docs/11 필수 조치 3) — Open-Meteo 과거 기상 API → data/weather/<site>_<year>.csv.

    uv run python tools/weather/fetch_weather.py            # 설정의 학습 · 평가 연도 모두
    uv run python tools/weather/fetch_weather.py --years 2024

설정: config/harness.yaml weather. 인증키가 필요 없다. 열: time(현지 시각) + 설정의 hourly 변수.
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
import urllib.request
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from harness.runner import load_harness_config  # noqa: E402


def fetch_year(cfg: dict, year: int) -> pd.DataFrame:
    s = cfg["site"]
    q = {"latitude": s["latitude"], "longitude": s["longitude"], "timezone": s["timezone"],
         "start_date": f"{year}-01-01", "end_date": f"{year}-12-31",
         "hourly": ",".join(cfg["hourly"]), "wind_speed_unit": "ms"}
    with urllib.request.urlopen(cfg["api"] + "?" + urllib.parse.urlencode(q), timeout=120) as r:
        data = json.load(r)
    df = pd.DataFrame(data["hourly"])
    missing = int(df[cfg["hourly"]].isna().sum().sum())
    print(f"{year}: {len(df)}시간 · 결측 {missing} · 격자 ({data['latitude']:.3f}, {data['longitude']:.3f}) 고도 {data['elevation']} m")
    return df


def main() -> None:
    cfg = load_harness_config()["weather"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="")
    a = ap.parse_args()
    years = [int(y) for y in a.years.split(",")] if a.years else sorted({*cfg["years"]["train"], *cfg["years"]["eval"]})
    out = REPO / cfg["data_dir"]
    out.mkdir(parents=True, exist_ok=True)
    for y in years:
        fetch_year(cfg, y).to_csv(out / f"{cfg['site']['name']}_{y}.csv", index=False)


if __name__ == "__main__":
    main()
