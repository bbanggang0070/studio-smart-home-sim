"""Baseline A′ — 상용 스마트홈 허브 수준의 규칙 자동화 (docs/11 권장 7 · 2026-10-26 · 결과를 보기 전에 규칙을 정했다).

SmartThings · IFTTT 같은 허브에 사용자가 흔히 거는 '조건 → 동작' 자동화를 기기마다 하나씩 둔다.
모든 센서를 쓸 수 있지만 **기기끼리 협조하지 않는다** — 우선순위 · 수단 사다리 · 결로 · 전력 한도 · 이벤트 판단이 없다.
기기마다 히스테리시스(켜는 값 ≠ 끄는 값)는 있다 (상용 자동화도 보통 쓴다). 수치는 config/baselines.yaml baseline_a2.

  에어컨      스마트 온도조절 — 재실 · 실내 > 설정 + on_above 면 냉방 · < 설정 − off_below 면 끔 · 외출이면 끔
              실내 습도 > dry_rh 이고 실내 ≤ 설정 + on_above 면 제습 모드 (에어컨 자동 제습)
  창문        무료 냉방 — 재실 · 실내 > open_above · 외기 ≤ 실내 − outdoor_cooler_by · 비 없음 · 외기 PM 양호/보통 · 에어컨 꺼짐이면 열고,
              비 · PM 나쁨 · 에어컨 켬 · 실내 < close_below 면 닫는다
  배기팬      욕실 습도 스위치 — RH > on_rh 켬 · < off_rh 끔
  후드        쿡탑 계량 플러그 · 후드 아래 온도 트리거 — 요리 감지 즉시 켬 · 끝나고 off_after_s 뒤 끔
  흡기팬      보충 급기 연동 — 배기팬 · 후드가 돌면 켬
  청정기      자동 모드 상시 (자체 PM · 히스테리시스 — Baseline A 와 같은 내장 자동)
  제습 · 가습 내장 습도 설정 (서로 · 결로를 모른다)
  조명        재실 · 어두우면 천장등 · 공부 모드면 스탠드
  블라인드    밝으면(눈부심) 차광 · 아니면 열기
  실링팬      더우면 약
  외출        모두 끄고 제습기만 곰팡이 방지 설정
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from interfaces import topics as T

BASELINES = Path(__file__).resolve().parents[2] / "config" / "baselines.yaml"
GOOD_PM = ("good", "moderate")


class BaselineAPrime:
    name = "baseline_A2"

    def __init__(self, path: str | Path = BASELINES):
        with open(path, encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)["baseline_a2"]
        self.pur = yaml.safe_load(open(path, encoding="utf-8"))["baseline_a"]

    def reset(self, params: dict[str, Any]) -> None:
        from controller.baseline_a import has_boiler
        self.heating = has_boiler(params.get("scenario") or {})
        self._absent_since: float | None = None
        self._ac = self._dry = self._win = self._exh = self._dehum = self._hum = self._shade = self._fan = self._hood = False
        self._cook_end: float | None = None
        self._pur_level: int | None = None

    @staticmethod
    def _flip(state: bool, on: bool, off: bool) -> bool:
        return (not off) if state else on

    def step(self, now_s: float, inbox: dict[str, Any]) -> dict[str, Any]:
        c = self.cfg
        temp, rh, pm = float(inbox[T.S_TEMPERATURE]), float(inbox[T.S_HUMIDITY]), float(inbox[T.S_PM25])
        lux = float(inbox.get(T.S_ILLUMINANCE, 0.0))
        lux = lux if lux == lux else 0.0
        occ = bool(inbox.get(T.S_OCCUPANCY, True))
        w = json.loads(inbox.get(T.S_WEATHER) or "{}")
        rain, t_out = bool(w.get("raining", False)), float(w.get("outdoor_temp_c", temp))
        pm_ok = str(inbox.get(T.S_OUTDOOR_PM_GRADE, "good")) in GOOD_PM
        mode = str(inbox.get(T.C_MODE, "NORMAL"))
        out: dict[str, Any] = {}

        # 에어컨 — 스마트 온도조절 · 자동 제습
        a = c["ac"]
        sp = float(a["setpoint_c"])
        self._ac = occ and self._flip(self._ac, temp > sp + a["on_above_c"], temp < sp - a["off_below_c"])
        self._dry = self._ac and self._flip(self._dry, rh > a["dry_rh_pct"] and temp <= sp + a["on_above_c"],
                                            rh < a["dry_rh_pct"] - a["dry_band_pct"] or temp > sp + a["cool_resume_above_c"])
        out[T.C_AC] = json.dumps({"power": self._ac, "mode": "dry" if self._dry else "cool", "setpoint": sp, "fan": "auto"})

        # 창문 — 무료 냉방 자동화 (비 · 외기 PM · 에어컨이면 닫는다)
        wn = c["window"]
        can = occ and not rain and pm_ok and not self._ac and t_out <= temp - wn["outdoor_cooler_by_c"]
        self._win = can and self._flip(self._win, temp > wn["open_above_c"], temp < wn["close_below_c"])
        out[T.C_WINDOW_OPEN_RATIO] = float(wn["ratio"]) if self._win else 0.0

        # 배기팬 — 습도 스위치 · 후드 — 요리 트리거 · 흡기팬 — 보충 급기 연동
        e = c["exhaust"]
        self._exh = self._flip(self._exh, rh > e["on_rh_pct"], rh < e["off_rh_pct"])
        out[T.C_FAN_RPM] = float(e["rpm"]) if self._exh else 0.0
        h = c["hood"]
        cooking = (float(inbox[T.S_HOOD_TEMPERATURE]) - temp >= h["cooking_hood_delta_c"]
                   or float(json.loads(inbox.get(T.S_APPLIANCE_POWER) or "{}").get("cooktop", 0.0)) >= h["cooktop_power_w"])
        if cooking:
            self._cook_end, hood_on = None, True
        else:
            if self._hood and self._cook_end is None:
                self._cook_end = now_s                      # 요리가 막 끝났다 — off_after_s 뒤 끈다
            hood_on = self._cook_end is not None and now_s - self._cook_end < h["off_after_s"]
        self._hood = hood_on
        out[T.C_RANGE_HOOD_LEVEL] = int(h["level"]) if hood_on else 0
        out[T.C_INTAKE_FAN_RPM] = float(c["intake_rpm"]) if (self._exh or hood_on) else 0.0

        # 청정기 — 자동 모드 상시 (Baseline A 내장 자동과 같다)
        lo, hi = self.pur["purifier_auto_bounds_ugm3"]
        want = 1 if pm <= lo else 2 if pm <= hi else 3
        if self._pur_level is not None and want != self._pur_level:
            b = self.pur["purifier_auto_band_ugm3"]
            up = want > self._pur_level
            edge = lo if min(want, self._pur_level) == 1 else hi
            if (up and pm <= edge + b) or (not up and pm >= edge - b):
                want = self._pur_level
        self._pur_level = want
        out[T.C_PURIFIER_LEVEL] = want if occ else 0

        # 제습 · 가습 — 내장 습도 설정 (외출이면 제습기만 곰팡이 방지)
        hs = c["humidistat"]
        band = hs["band_pct"]
        sp_d = hs["dehumidifier_pct"] if occ else hs["away_dehumidifier_pct"]
        self._dehum = self._flip(self._dehum, rh > sp_d + band, rh < sp_d - band)
        self._hum = occ and self._flip(self._hum, rh < hs["humidifier_pct"] - band, rh > hs["humidifier_pct"] + band)
        out[T.C_DEHUMIDIFIER], out[T.C_HUMIDIFIER] = self._dehum, self._hum

        # 조명 · 블라인드 · 실링팬
        lt = c["lighting"]
        dark = lux < lt["dark_below_lux"]
        out[T.C_CEILING_LIGHT] = float(lt["ceiling_pct"]) if (occ and dark and mode != "SLEEP") else 0.0
        out[T.C_DESK_LIGHT] = float(lt["desk_pct"]) if (occ and mode == "STUDY") else 0.0
        bl = c["blind"]
        self._shade = self._flip(self._shade, lux > bl["shade_above_lux"], lux < bl["open_below_lux"])
        out[T.C_BLIND_ANGLE] = float(bl["shade_deg"]) if self._shade else 0.0
        f = c["ceiling_fan"]
        self._fan = occ and self._flip(self._fan, temp > f["on_above_c"], temp < f["off_below_c"])
        out[T.C_CEILING_FAN] = int(f["level"]) if self._fan else 0
        if self.heating:                               # [난방 확장] 스마트 조절기 — 재실 연동 + 밤 시간대 (협조 없음)
            b = c["boiler"]
            if occ:
                self._absent_since = None
            elif self._absent_since is None:
                self._absent_since = now_s
            h = (now_s % 86400.0) / 3600.0
            night = h >= b["night_start_h"] or h < b["night_end_h"]
            away = self._absent_since is not None and now_s - self._absent_since >= b["away_after_s"]
            sp = b["away_c"] if away else b["night_c"] if night else b["home_c"]
            out[T.C_BOILER] = json.dumps({"power": True, "setpoint": float(sp)})
        return out
