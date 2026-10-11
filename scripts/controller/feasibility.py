"""제어 가능성 판정 (W09 T9.7 · 시나리오 X2) — FEASIBLE / DEGRADED / INFEASIBLE.

목표별로 '벗어남 ∧ 수단 소진 ∧ 나아지지 않음'이 infeasible_after_s 이상 이어지면 INFEASIBLE (thresholds feasibility).
어느 목표든 벗어남이 degraded_after_s 이상 이어지거나 E9 가전 무응답이면 DEGRADED.
  벗어남      냉방: 실내 > 냉방 목표 + margin · 제습: RH > 상한 + margin · PM: 실내 > 나쁨 기준
  수단 소진   그 목표의 수단이 모두 '프로파일에 없음 · 막힘(cap 0 · 고장) · 이미 상한' (중재 결과 Decision 으로 판단)
  나아짐      improve_window_s 창의 추세(최소제곱 기울기 × 창 길이)가 improve_min 이상 좋아지면 나아지는 중
E9 가전 무응답이 있으면 INFEASIBLE 대신 DEGRADED — 원인이 장치 고장이라 고치면 풀린다 (X7)
해제        벗어남이 풀리거나 수단이 다시 생기면 바로 FEASIBLE (헛구동 지표 #8 — 판정이 구동을 바꾸지는 않는다)
"""

from __future__ import annotations

from collections import deque

from controller.params import ControllerParams

# 목표 → 수단 (장치 이름 = arbiter Decision 키) · 수단마다 '상한' 판단 기준
COOLING_MEANS = ("ac", "window", "exhaust", "ceiling_fan", "blind")
DEHUM_MEANS = ("ac", "dehumidifier", "window", "exhaust")
PM_MEANS = ("purifier", "range_hood", "intake")
DEGRADE_FIRST = ("APPLIANCE_FAULT", "POWER_LIMIT")      # 수단을 잃은 원인이 분명한 이벤트 — INFEASIBLE 보다 DEGRADED


class Feasibility:
    def __init__(self, p: ControllerParams):
        g = p.get
        f = "feasibility."
        self.p = p
        self.enabled = bool(g(f + "enabled"))
        self.after_s = g(f + "infeasible_after_s")
        self.degraded_s = g(f + "degraded_after_s")
        self.violated_since: dict[str, float | None] = {}
        self.disturbance = g(f + "disturbance_events")
        self.window_s = g(f + "improve_window_s")
        self.margin = {"cooling": g(f + "cooling_margin_c"), "dehum": g(f + "humidity_margin_pct")}
        self.improve = {"cooling": g(f + "improve_min_c"), "dehum": g(f + "improve_min_pct"), "pm": g(f + "improve_min_ugm3")}
        self.hist: dict[str, deque] = {k: deque() for k in ("cooling", "dehum", "pm")}
        self.since: dict[str, float | None] = {k: None for k in self.hist}
        self.state = "FEASIBLE"
        self.reason = ""

    def _exhausted(self, means, decided, devices, caps, useful: dict | None = None) -> bool:
        """수단이 모두 없음 · 쓸모없음 · 막힘 · 상한인가. caps = {장치: 지금 낼 수 있는 최댓값 (cap · force 반영)}."""
        for dev in means:
            if dev not in devices or dev not in decided:
                continue
            if useful is not None and not useful.get(dev, True):
                continue                                  # 이 목표에 쓸모없는 수단 (외기가 더 더움 · I10 불만족 등)
            top = caps.get(dev)
            if top is None or top <= 0:
                continue                                  # 막힘 (cap 0 — 비 · 소음 · 등급 · I7 등)
            if decided[dev].value < top * 0.95:
                return False                              # 아직 더 쓸 수 있다
        return True

    def _improving(self, key, now, value) -> bool:
        h = self.hist[key]
        h.append((now, value))
        while h and now - h[0][0] > self.window_s:
            h.popleft()
        if len(h) < 3:
            return False
        # 창 전체의 추세 — 처음 · 끝 두 점만 보면 출렁임(비 오는 날 창 틈 환기 등)의 내려가는 구간을 개선으로 본다 (X2)
        ts = [t for t, _ in h]
        vs = [v for _, v in h]
        tm, vm = sum(ts) / len(ts), sum(vs) / len(vs)
        den = sum((t - tm) ** 2 for t in ts)
        slope = sum((t - tm) * (v - vm) for t, v in h) / den if den > 0 else 0.0
        return -slope * (ts[-1] - ts[0]) >= self.improve[key]

    def update(self, o, mode_cfg: dict, decided: dict, devices: set, caps: dict, events: dict,
               useful: dict | None = None, cooling_target_c: float | None = None, ac_mode: str | None = None) -> str:
        # 냉방 목표 = 사다리가 실제로 쓰는 목표 (실링팬 체감 완화 I5 포함) — 원래 목표로 보면 에어컨이 맞춘 온도를 '벗어남'으로 본다
        sp = cooling_target_c if cooling_target_c is not None else mode_cfg.get("cooling_setpoint_c")
        hi = (mode_cfg.get("humidity_range_pct") or [None, None])[1]
        bad = self.p.get("indoor_pm.bad_ugm3")
        goals = {
            "cooling": (sp is not None and o.temp_c > sp + self.margin["cooling"], o.temp_c, COOLING_MEANS),
            "dehum": (hi is not None and o.rh_pct > hi + self.margin["dehum"], o.rh_pct, DEHUM_MEANS),
            "pm": (o.pm25 > bad, o.pm25, PM_MEANS),
        }
        stuck, long_violated = [], []
        for key, (violated, value, means) in goals.items():
            if any(e in events for e in self.disturbance.get(key, [])):
                violated = False                          # 발생원이 있는 동안 — 외란 (회복 지표가 따로 본다)
            improving = self._improving(key, o.now_s, value)
            vs = self.violated_since.get(key)
            self.violated_since[key] = (vs if vs is not None else o.now_s) if violated else None
            if violated and o.now_s - self.violated_since[key] >= self.degraded_s:
                long_violated.append(key)
            if key == "cooling" and ac_mode not in (None, "cool") and decided.get("ac") and decided["ac"].value > 0:
                violated = False                          # 에어컨이 제습 모드 — 냉방 모드로 바꿀 여지가 있다 (C1)
            if violated and not improving and self._exhausted(means, decided, devices, caps, (useful or {}).get(key)):
                self.since[key] = self.since[key] if self.since[key] is not None else o.now_s
                if o.now_s - self.since[key] >= self.after_s:
                    stuck.append(key)
            else:
                self.since[key] = None
        if not self.enabled:
            self.state, self.reason = "FEASIBLE", ""
        elif any(e in events for e in DEGRADE_FIRST):     # 원인이 장치 고장 · 전력 한도면 DEGRADED 가 먼저 (X7 · C17 — 풀리면 돌아온다)
            self.state = "DEGRADED"
            self.reason = ",".join([e for e in DEGRADE_FIRST if e in events] + stuck)
        elif stuck:
            self.state, self.reason = "INFEASIBLE", ",".join(stuck)
        elif long_violated:
            self.state = "DEGRADED"
            self.reason = ",".join((["APPLIANCE_FAULT"] if "APPLIANCE_FAULT" in events else []) + long_violated)
        else:
            self.state, self.reason = "FEASIBLE", ""
        return self.state
