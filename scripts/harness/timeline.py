"""시간축 주입기 — `injections` · `events` 를 시뮬레이션 시각에 맞춰 적용 (docs/03 §8 규약 4단계).

지원하지 않는 주입은 조용히 무시하지 않는다: `unsupported` 에 모아 결과(summary)에 그대로 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from env_model import SourceRates

# 주입 종류 → 지원 여부. 아직 처리하지 못하는 것은 해당 주차를 적어 둔다.
UNSUPPORTED_KINDS = {
    "fault": "W10 고장 주입 (ir_miss 등 — door_sensor_stuck 만 지원)",
}
# 재실 감지 주입 (sensing.py) — radar: silent(레이더 시야 밖) · wifi: doze(절전 끊김) · neighbor(벽 너머 정지 신호)
#   · curtain(빈집 움직임 신호) · fault: door_sensor_stuck(문 센서 값 고정) · appliance: pc(사람이 켜는 기기 전력)
SENSING_KINDS = ("radar", "wifi", "neighbor", "curtain")
SUPPORTED_SOURCES = ("cooking", "shower", "pm_no_heat", "laundry")
# 기기 전력 프로파일 주입 — washer: 탈수 구간 전력 → 종료 시 젖은 빨래를 넌다 (laundry_moisture_g)
EXTERNAL_KEYS = ("outdoor_temp_c", "outdoor_rh_pct", "outdoor_pm25_ugm3", "outdoor_illuminance_lux",
                 "wind_speed_ms", "heating_setpoint_c", "weather")
WORLD_KEYS = ("occupancy", "occupant_zone", "user_mode", "illuminance_lux", "activity", "occupants", "motion", "phone")


@dataclass
class Interval:
    label: str
    kind: str
    start_s: float
    end_s: float
    spec: dict[str, Any]

    def active(self, t: float) -> bool:
        return self.start_s <= t < self.end_s


@dataclass
class Timeline:
    intervals: list[Interval] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    def anchors(self) -> dict[str, float]:
        """pass_criteria 에서 쓰는 이름 → 시각. 같은 label 이 여러 번이면 첫 번째."""
        out: dict[str, float] = {}
        for iv in self.intervals:
            out.setdefault(f"{iv.label}_start", iv.start_s)
            out.setdefault(f"{iv.label}_end", iv.end_s)
        return out

    def labels(self) -> set[str]:
        return {iv.label for iv in self.intervals}

    def active_labels(self, t: float) -> list[str]:
        return [iv.label for iv in self.intervals if iv.active(t)]

    def sources_at(self, t: float) -> tuple[SourceRates, dict[str, float]]:
        """t 에서의 발생원 합계 + 전력 신호가 있는 발생원 (플러그형 인덕션 → 쿡탑 전력)."""
        src = SourceRates()
        power: dict[str, float] = {}
        for iv in self.intervals:
            if iv.kind not in SUPPORTED_SOURCES or not iv.active(t):
                continue
            s = iv.spec
            if iv.kind == "cooking":
                src.cooking_pm_mg_per_min += float(s.get("pm_mg_per_min", 0.0))
                src.moisture_g_per_h += float(s.get("moisture_g_per_h", 0.0))
                src.cooking_heat_w += float(s.get("heat_w", 0.0))
                if s.get("stove") == "induction_plug":
                    power["cooktop"] = power.get("cooktop", 0.0) + float(s.get("heat_w", 0.0))
            elif iv.kind == "shower":
                src.moisture_g_per_h += float(s["moisture_g"]) / float(s["duration_s"]) * 3600.0
            elif iv.kind == "pm_no_heat":
                src.other_pm_mg_per_min += float(s.get("pm_mg_per_min", 0.0))
        for iv in self.intervals:
            if iv.kind in ("washer", "pc") and iv.active(t):
                power[iv.kind] = power.get(iv.kind, 0.0) + float(iv.spec.get("power_w", 450.0))
        return src, power

    def active_kind(self, t: float, kind: str) -> list[Interval]:
        return [iv for iv in self.intervals if iv.kind == kind and iv.active(t)]

    def instants_between(self, t0: float, t1: float, kind: str) -> list[Interval]:
        """(t0, t1] 에 시작하는 주입 — 순간 사건 (문 센서 고장 등)."""
        return [iv for iv in self.intervals if iv.kind == kind and t0 < iv.start_s <= t1]

    def laundry_hung_between(self, t0: float, t1: float) -> float:
        """(t0, t1] 에 널린 빨래 수분 [g] — 세탁기 탈수 종료 시각 · 'source: laundry' 시작 시각."""
        g = 0.0
        for iv in self.intervals:
            if iv.kind == "washer" and t0 < iv.end_s <= t1:
                g += float(iv.spec.get("laundry_moisture_g", 0.0))
            elif iv.kind == "laundry" and t0 < iv.start_s <= t1:
                g += float(iv.spec.get("moisture_g", 0.0))
        return g

    def door_open_at(self, t: float) -> bool:
        return any(iv.kind == "door" and iv.active(t) for iv in self.intervals)

    def events_between(self, t0: float, t1: float) -> list[dict[str, Any]]:
        """[t0, t1) 에 발생하는 events 의 set 딕셔너리들."""
        return [e["set"] for e in self.events if t0 <= float(e["at_s"]) < t1]


def build_timeline(scenario: dict[str, Any]) -> Timeline:
    tl = Timeline()
    duration = float(scenario["duration_s"])
    for inj in scenario.get("injections") or []:
        at = float(inj["at_s"])
        if "source" in inj:
            kind = inj["source"]
            if kind not in SUPPORTED_SOURCES:
                tl.unsupported.append(f"source:{kind}")
                continue
            dur = float(inj.get("duration_s", duration - at))
            tl.intervals.append(Interval(inj.get("label", kind), kind, at, at + dur, inj))
        elif inj.get("appliance") in ("washer", "pc"):
            kind = inj["appliance"]
            dur = float(inj.get("duration_s", 600.0))
            tl.intervals.append(Interval(inj.get("label", kind), kind, at, at + dur, inj))
        elif any(k in inj for k in SENSING_KINDS):
            kind = next(k for k in SENSING_KINDS if k in inj)
            dur = float(inj.get("duration_s", duration - at))
            tl.intervals.append(Interval(inj.get("label", kind), kind, at, at + dur, inj))
        elif inj.get("fault") == "door_sensor_stuck":
            tl.intervals.append(Interval(inj.get("label", "door_stuck"), "door_sensor_stuck", at, at, inj))
        elif inj.get("door") == "open_close":
            open_s = float(inj.get("open_s", 5.0))
            tl.intervals.append(Interval(inj.get("label", "door"), "door", at, at + open_s, inj))
        else:
            kind = next((k for k in UNSUPPORTED_KINDS if k in inj), None) or next(iter(inj.keys() - {"at_s"}), "?")
            tl.unsupported.append(f"{kind}@{at:g}s ({UNSUPPORTED_KINDS.get(kind, '미정의 주입')})")
            # 시간 구간은 남겨 둔다 — 판정 앵커(<label>_start)로는 쓸 수 있게
            if "duration_s" in inj:
                tl.intervals.append(Interval(inj.get("label", kind), kind, at, at + float(inj["duration_s"]), inj))
    for ev in scenario.get("events") or []:
        bad = set(ev["set"]) - set(EXTERNAL_KEYS) - set(WORLD_KEYS)
        if bad:
            tl.unsupported.append(f"events.set:{sorted(bad)}@{ev['at_s']}s")
        tl.events.append(ev)
    tl.events.sort(key=lambda e: float(e["at_s"]))
    return tl
