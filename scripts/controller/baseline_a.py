"""Baseline A — 장치 · 가전 독립 제어 (docs/03 §6). 비교용이며 제안 제어기와 코드를 공유하지 않는다.

각 가전은 자기 센서 · 자기 설정만 본다:
  에어컨      내장 온도조절 (켜져 있을 때) — 창문 상태를 모른다
  제습 · 가습 내장 습도조절 (켜져 있을 때) — 서로 · 결로를 모른다 (동시 가동 가능)
  청정기      내장 자동 (켜져 있을 때) — 자체 PM 단계
  후드        사용자 모델 — 요리 시작 2분 후 강 · 끝나면 끔 · 습관적으로 창문 개방
  실링팬 · 흡기팬  수동 고정 (약 · OFF)
창문 · 블라인드 · 배기팬 · 조명의 v1.1 단독 규칙은 이 시나리오들에서 쓰이지 않아 W10 T10.v4 에서 더한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from interfaces import topics as T

BASELINES = Path(__file__).resolve().parents[2] / "config" / "baselines.yaml"


class BaselineA:
    name = "baseline_A"

    def __init__(self, path: str | Path = BASELINES):
        with open(path, encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)["baseline_a"]

    def reset(self, params: dict[str, Any]) -> None:
        app = (params.get("scenario") or {}).get("initial", {}).get("appliances") or {}
        # 사용자가 켜 둔 가전만 내장 자동으로 돈다
        self.ac_on = bool((app.get("ac") or {}).get("power", False))
        self.dehum_on = bool(app.get("dehumidifier", False))
        self.hum_on = bool(app.get("humidifier", False))
        self.purifier_on = int(app.get("purifier_level", 0)) > 0
        self._cook_seen_at: float | None = None
        self._dehum_run = self._hum_run = False

    def step(self, now_s: float, inbox: dict[str, Any]) -> dict[str, Any]:
        c = self.cfg
        out: dict[str, Any] = {T.C_CEILING_FAN: int(c["ceiling_fan_fixed"]),
                               T.C_INTAKE_FAN_RPM: float(c["intake_fan_fixed_rpm"])}
        rh, pm = float(inbox[T.S_HUMIDITY]), float(inbox[T.S_PM25])

        # 사용자 후드 모델
        cooking = float(inbox[T.S_HOOD_TEMPERATURE]) - float(inbox[T.S_TEMPERATURE]) >= c["user_hood"]["cooking_hood_delta_c"]
        if cooking:
            self._cook_seen_at = self._cook_seen_at if self._cook_seen_at is not None else now_s
            on = now_s - self._cook_seen_at >= c["user_hood"]["delay_s"]
        else:
            self._cook_seen_at, on = None, False
        out[T.C_RANGE_HOOD_LEVEL] = int(c["user_hood"]["level"]) if on else 0
        out[T.C_WINDOW_OPEN_RATIO] = float(c["user_hood"]["window_habit_ratio"]) if on else 0.0

        if self.purifier_on:
            lo, hi = c["purifier_auto_bounds_ugm3"]
            out[T.C_PURIFIER_LEVEL] = 1 if pm <= lo else 2 if pm <= hi else 3
        band = c["humidistat_band_pct"]
        if self.dehum_on:
            sp = c["dehumidifier_setpoint_pct"]
            self._dehum_run = rh > sp + band or (self._dehum_run and rh > sp - band)
            out[T.C_DEHUMIDIFIER] = self._dehum_run
        if self.hum_on:
            sp = c["humidifier_setpoint_pct"]
            self._hum_run = rh < sp - band or (self._hum_run and rh < sp + band)
            out[T.C_HUMIDIFIER] = self._hum_run
        if self.ac_on:
            out[T.C_AC] = json.dumps({"power": True, "mode": "cool", "setpoint": c["ac_setpoint_c"], "fan": "auto"})
        return out
