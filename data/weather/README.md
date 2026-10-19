# data/weather — 시간별 기상 (docs/11 필수 조치 3)

| 파일 | 내용 |
|---|---|
| `seoul_<연도>.csv` | 서울(기상청 108 지점 좌표 37.5714, 126.9658) 시간별 기온 · 상대습도 · 일사(앞 1시간 평균) · 강수 · 운량 · 10 m 풍속 — 현지 시각 |

- 출처: [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) — ERA5 · ERA5-Land 재분석(Copernicus/ECMWF). **CC BY 4.0** — 논문 · 그림에 출처를 적는다.
- 재분석 격자 값이다(지점 관측 아님). 기상청 ASOS 로 바꾸려면 같은 열 이름으로 이 폴더에 둔다.
- 받기: `uv run python tools/weather/fetch_weather.py` · 설정 `config/harness.yaml` weather
- 연도 분리: 학습 2021–2023 · 평가 2024 — 학습 도구는 `load_series(..., "train")` 만, 평가는 `"eval"` 만 읽는다.
