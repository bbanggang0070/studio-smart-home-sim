"""Baseline A — 장치 · 가전 독립 제어 (docs/03 §6). 비교용이며 제안 제어기와 코드를 공유하지 않는다.

각 가전은 자기 센서 · 자기 설정만 본다:
  에어컨      내장 온도조절 (켜져 있을 때) — 창문 상태를 모른다
  제습 · 가습 내장 습도조절 (켜져 있을 때) — 서로 · 결로를 모른다 (동시 가동 가능)
  청정기      내장 자동 (켜져 있을 때) — 자체 PM 단계
  후드        사용자 모델 — 요리 시작 2분 후 강 · 끝나면 끔 · 습관적으로 창문 개방
  실링팬 · 흡기팬  수동 고정 (약 · OFF)
  창문 · 배기팬 v1.1 단독 온도 규칙 — 28 °C 이상이면 열고 25 °C 이하에서 닫는다 (강우 · 외기 · 냉방을 모른다)
블라인드 · 조명 단독 규칙은 W10 T10.v4 에서 더한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from interfaces import topics as T

BASELINES = Path(__file__).resolve().parents[2] / "config" / "baselines.yaml"


def has_boiler(sc: dict) -> bool:
    """[난방 확장] 시나리오 가전 프로파일에 boiler 가 있나 — 없으면 기준선은 보일러 명령을 내지 않는다 (v1.29 와 같다)."""
    from controller.params import load_params
    return "boiler" in load_params().get("appliances.profiles").get(sc.get("appliance_profile", "full"), [])


class BaselineA:
    name = "baseline_A"

    def __init__(self, path: str | Path = BASELINES):
        with open(path, encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)["baseline_a"]

    def reset(self, params: dict[str, Any]) -> None:
        sc = params.get("scenario") or {}
        app = sc.get("initial", {}).get("appliances") or {}
        # 사용자가 켜 둔 가전만 내장 자동으로 돈다 — 시나리오가 지정하면 그것을 따른다
        auto = (sc.get("baseline_a") or {}).get("auto_appliances")
        if auto is None:
            auto = [k for k, on in (("ac", (app.get("ac") or {}).get("power", False)),
                                    ("dehumidifier", app.get("dehumidifier", False)),
                                    ("humidifier", app.get("humidifier", False)),
                                    ("purifier", int(app.get("purifier_level", 0)) > 0)) if on]
        self.ac_on, self.dehum_on = "ac" in auto, "dehumidifier" in auto
        self.hum_on, self.purifier_on = "humidifier" in auto, "purifier" in auto
        self._pur_level: int | None = None           # 청정기 내장 자동의 현재 단 (히스테리시스)
        self._venting = False
        self._cook_seen_at: float | None = None
        self._dehum_run = self._hum_run = False
        self.user_ac_away = bool((sc.get("baseline_a") or {}).get("user_ac_away", False))
        self.user_lights = bool((sc.get("baseline_a") or {}).get("user_lights", False))
        self._home_since: float | None = None
        self._was_away = False
        self.heating = has_boiler(sc)

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

        # 창문 · 배기팬 단독 온도 규칙 + 후드 사용 습관 (각자 자기 조건만 본다)
        tr, temp = c["temperature_rule"], float(inbox[T.S_TEMPERATURE])
        self._venting = temp >= tr["vent_on_c"] or (self._venting and temp > tr["vent_off_c"])
        window = max(float(tr["window_ratio"]) if self._venting else 0.0,
                     float(c["user_hood"]["window_habit_ratio"]) if on else 0.0)
        out[T.C_WINDOW_OPEN_RATIO] = window
        out[T.C_FAN_RPM] = float(tr["exhaust_rpm"]) if self._venting else 0.0

        if self.purifier_on:
            lo, hi = c["purifier_auto_bounds_ugm3"]
            want = 1 if pm <= lo else 2 if pm <= hi else 3
            if self._pur_level is not None and want != self._pur_level:     # 경계 ± 폭 히스테리시스 (실제 청정기의 평활 자리)
                b = c["purifier_auto_band_ugm3"]
                up = want > self._pur_level
                edge = (lo if min(want, self._pur_level) == 1 else hi)
                if (up and pm <= edge + b) or (not up and pm >= edge - b):
                    want = self._pur_level
            self._pur_level = want
            out[T.C_PURIFIER_LEVEL] = want
        band = c["humidistat_band_pct"]
        if self.dehum_on:
            sp = c["dehumidifier_setpoint_pct"]
            self._dehum_run = rh > sp + band or (self._dehum_run and rh > sp - band)
            out[T.C_DEHUMIDIFIER] = self._dehum_run
        if self.hum_on:
            sp = c["humidifier_setpoint_pct"]
            self._hum_run = rh < sp - band or (self._hum_run and rh < sp + band)
            out[T.C_HUMIDIFIER] = self._hum_run
        if self.user_lights:                           # C4 — 어두우면 천장등 최대 (스탠드 · 발열은 생각하지 않는다)
            out[T.C_CEILING_LIGHT] = float(c["user_ceiling_light_pct"]) if bool(inbox.get(T.S_OCCUPANCY, True)) else 0.0
        ac_run = self.ac_on
        if self.user_ac_away:                          # 나갈 때 끄고 귀가 후 수동으로 켠다 (C16 Baseline A)
            if bool(inbox.get(T.S_OCCUPANCY, True)):
                self._home_since = self._home_since if self._home_since is not None else now_s
                ac_run = self.ac_on and now_s - self._home_since >= c["user_ac_on_after_arrival_s"]
                if not self._was_away:
                    ac_run = self.ac_on                # 처음부터 집에 있었다 — 켜 둔 상태
            else:
                self._home_since, ac_run, self._was_away = None, False, True
            out[T.C_AC] = json.dumps({"power": ac_run, "mode": "cool", "setpoint": c["ac_setpoint_c"], "fan": "auto"})
        elif self.ac_on:
            out[T.C_AC] = json.dumps({"power": True, "mode": "cool", "setpoint": c["ac_setpoint_c"], "fan": "auto"})
        if self.heating:                               # [난방 확장] 조절기 22 °C 켜 둠 (사람이 바꾸지 않는다)
            out[T.C_BOILER] = json.dumps({"power": True, "setpoint": float(c["boiler_fixed_c"])})
        return out
