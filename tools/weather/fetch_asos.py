"""기상청 ASOS(종관기상관측) 시간자료 받기 — 공공데이터포털 '기상청_지상(종관, ASOS) 시간자료 조회서비스'.

    uv run python tools/weather/fetch_asos.py                 # 설정의 학습 · 평가 연도 모두
    uv run python tools/weather/fetch_asos.py --years 2024

인증키: 환경변수 KMA_API_KEY 또는 ~/.studio_env 의 'KMA_API_KEY=...' (저장소에 넣지 않는다 · 출력하지 않는다).
결과: data/weather/asos_<site>_<year>.csv — ERA5 파일(seoul_<year>.csv)과 같은 열 이름 · 단위로 맞춘다.
  temperature_2m [°C] ← ta · relative_humidity_2m [%] ← hm · shortwave_radiation [W/m²] ← icsr [MJ/m²·h] × 1e6 / 3600
  precipitation [mm] ← rn (빈 값 = 0) · cloud_cover [%] ← dc10Tca [0–10] × 10 · wind_speed_10m [m/s] ← ws (ERA5 파일도 m/s 로 받았다)
관측이 빈 시각(결측)은 앞뒤 값으로 선형 보간하고, 보간한 개수를 출력 · 기록한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from harness.runner import load_harness_config  # noqa: E402

URL = "https://apis.data.go.kr/1360000/AsosHourlyInfoService/getWthrDataList"


def api_key() -> str:
    k = os.environ.get("KMA_API_KEY", "")
    env = Path.home() / ".studio_env"
    if not k and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("KMA_API_KEY="):
                k = line.split("=", 1)[1].strip()
    if not k:
        sys.exit("KMA_API_KEY 가 없다 — ~/.studio_env 에 KMA_API_KEY=<키> 한 줄")
    return k


def fetch_month(key: str, stn: int, y: int, m: int) -> list[dict]:
    start = pd.Timestamp(y, m, 1)
    end = (start + pd.offsets.MonthEnd(0))
    rows, page = [], 1
    while True:
        q = {"serviceKey": key, "pageNo": page, "numOfRows": 999, "dataType": "JSON", "dataCd": "ASOS", "dateCd": "HR",
             "startDt": f"{start:%Y%m%d}", "startHh": "00", "endDt": f"{end:%Y%m%d}", "endHh": "23", "stnIds": stn}
        for attempt in range(5):
            try:
                with urllib.request.urlopen(URL + "?" + urllib.parse.urlencode(q), timeout=60) as r:
                    body = json.loads(r.read().decode("utf-8"))
                break
            except Exception:                                   # 일시 오류 — 잠깐 쉬고 다시
                time.sleep(2 + 3 * attempt)
        else:
            raise RuntimeError(f"{y}-{m:02d} 쪽 {page} 받기 실패")
        h = body["response"]["header"]
        if h["resultCode"] != "00":
            raise RuntimeError(f"{y}-{m:02d}: {h['resultCode']} {h['resultMsg']}")
        b = body["response"]["body"]
        items = b["items"]["item"] if b.get("items") else []
        rows += items
        if page * 999 >= int(b["totalCount"]):
            return rows
        page += 1


def num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def to_frame(items: list[dict], year: int) -> tuple[pd.DataFrame, dict]:
    df = pd.DataFrame({
        "time": pd.to_datetime([i["tm"] for i in items]),
        "temperature_2m": [num(i.get("ta")) for i in items],
        "relative_humidity_2m": [num(i.get("hm")) for i in items],
        "shortwave_radiation": [num(i.get("icsr")) * 1e6 / 3600.0 for i in items],
        "precipitation": [num(i.get("rn")) for i in items],
        "cloud_cover": [num(i.get("dc10Tca")) * 10.0 for i in items],
        "wind_speed_10m": [num(i.get("ws")) for i in items],
    }).drop_duplicates("time").set_index("time").sort_index()
    full = pd.date_range(f"{year}-01-01 00:00", f"{year}-12-31 23:00", freq="h")
    df = df.reindex(full)
    miss = {c: int(df[c].isna().sum()) for c in df.columns}
    # 일사 · 강수는 밤 · 맑은 날 빈 값이 '0' 이다 (기상청 표기) — 0 으로 채운다
    df["shortwave_radiation"] = df["shortwave_radiation"].fillna(0.0)
    df["precipitation"] = df["precipitation"].fillna(0.0)
    for c in ("temperature_2m", "relative_humidity_2m", "cloud_cover", "wind_speed_10m"):
        df[c] = df[c].interpolate(limit_direction="both")
    df.index.name = "time"
    return df.reset_index().assign(time=lambda d: d.time.dt.strftime("%Y-%m-%dT%H:%M")), miss


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*")
    ap.add_argument("--stn", type=int, default=108)
    a = ap.parse_args()
    wc = load_harness_config()["weather"]
    years = a.years or sorted(set(wc["years"]["train"]) | set(wc["years"]["eval"]))
    key = api_key()
    out = REPO / wc["data_dir"]
    log = {}
    for y in years:
        items = []
        for m in range(1, 13):
            items += fetch_month(key, a.stn, y, m)
        df, miss = to_frame(items, y)
        path = out / f"asos_{wc['site']['name']}_{y}.csv"
        df.to_csv(path, index=False)
        log[y] = {"rows": len(df), "raw_items": len(items), "missing_before_fill": miss}
        print(f"{path.relative_to(REPO)} · {len(df)}행 · 결측(채우기 전) {miss}", flush=True)
    (out / "asos_fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
