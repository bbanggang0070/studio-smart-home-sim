"""습기 수지 잔차 — 실내 습기 발생원 추정 (E10 빨래 건조의 두 번째 신호 · docs/08 §4.3 확장).

    발생원 ≈ V·dw/dt − Q_외기·(w_out − w) + 제습 제거량 − 재실자 발생

제어기가 아는 것만 쓴다: 센서(온습도 · 기상청) · 상태 토픽(흡기 · 배기 · 후드 · 제습기 · 에어컨) · thresholds 상수.
창문이 열려 있으면 유량을 알 수 없어 추정하지 않는다(None).
"""

from __future__ import annotations

import math
from collections import deque

from controller.params import ControllerParams
from controller.signals import Observation, Psychro


class MoistureResidual:
    def __init__(self, p: ControllerParams, psy: Psychro):
        self.p, self.psy = p, psy
        g = p.get
        self.v = g("air_balance.room_volume_m3")
        self.q_inf0 = g("air_balance.base_infiltration_ach") * self.v
        self.window_s = g("events.laundry_drying.residual_window_s")
        self.hist: deque[tuple[float, float]] = deque()
        self.res_hist: deque[tuple[float, float]] = deque()

    def _removal_g_h(self, o: Observation) -> float:
        g = self.p.get
        lp = "events.laundry_drying."
        r = 0.0
        if o.dehumidifier_on:
            d = g("appliances.dehumidifier.low_temp_derate")
            f = d["at_18c"] + (d["at_27c"] - d["at_18c"]) * (o.temp_c - 18.0) / 9.0
            r += g("appliances.dehumidifier.rated_g_per_h") * min(d["at_27c"], max(0.0, f))
        if o.ac_power and o.ac_mode == "dry":
            r += g("appliances.ac.dry_g_per_h")
        elif o.ac_power and o.ac_mode == "cool":
            r += g(lp + "ac_cool_latent_g_per_h_est")
        return r

    def update(self, o: Observation) -> float | None:
        """→ 최근 window_s 평균 발생원 [g/h]. 이력이 짧거나 창문이 열려 있으면 None."""
        g = self.p.get
        w = self.psy.abs_humidity(o.temp_c, o.rh_pct)
        self.hist.append((o.now_s, w))
        while self.hist and o.now_s - self.hist[0][0] > self.window_s:
            self.hist.popleft()
        if o.window_ratio > 0.05 or math.isnan(o.outdoor_temp_c) or len(self.hist) < 2:
            return None
        (t0, w0), (t1, w1) = self.hist[0], self.hist[-1]
        if t1 - t0 < 0.5 * self.window_s:
            return None
        dwdt = (w1 - w0) / (t1 - t0) * 3600.0
        intake = g("appliances.intake_fan.max_m3h") * o.intake_rpm / g("appliances.intake_fan.max_rpm")
        exhaust = g("appliances.exhaust_fan.max_m3h") * o.exhaust_rpm / g("appliances.exhaust_fan.max_rpm")
        hood = g("appliances.range_hood.flow_m3h")[f"l{o.hood_level}"] if o.hood_level > 0 else 0.0
        q_oa = intake + self.q_inf0 + max(0.0, exhaust + hood - intake)
        w_out = self.psy.abs_humidity(o.outdoor_temp_c, o.outdoor_rh_pct)
        occ = g("events.laundry_drying.occupant_moisture_g_per_h") if o.occupied else 0.0
        src = self.v * dwdt - q_oa * (w_out - w) + self._removal_g_h(o) - occ
        self.res_hist.append((o.now_s, src))
        while self.res_hist and o.now_s - self.res_hist[0][0] > self.window_s:
            self.res_hist.popleft()
        return sum(v for _, v in self.res_hist) / len(self.res_hist)
