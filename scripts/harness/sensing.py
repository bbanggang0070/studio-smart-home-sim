"""고속 모드 재실 감지 — 참값 사람 상태 → mmWave 구간 에너지 · Wi-Fi · 문 접점 → 재실 판정 노드 (sensors/occupancy).

물리 모드에서는 Isaac Sim 사람 프록시 · 문 조인트가 같은 원시 신호를 만들고 occupancy_sensor_node 가 판정한다.
여기서는 그 원시 신호를 참값에서 합성한다 (docs/08 §1.0 · §1.5 · 가정 A20).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from sensors.occupancy import OccupancyJudge, OccupancyOutput


@dataclass
class PersonTruth:
    present: bool
    zone: str                     # desk | bed | kitchen | room | none(욕실 · 레이더 밖)
    motion: str                   # still | moving | sleeping
    phone_with_person: bool = True
    arrived_at: float | None = None
    left_phone_home: bool = False


@dataclass
class SensingWorld:
    cfg: dict[str, Any]           # harness.yaml mmwave
    rng: np.random.Generator
    judge: OccupancyJudge
    person: PersonTruth
    door_sensor_stuck_at: bool | None = None
    _wifi_on_at: float | None = None
    _was_present: bool = True
    last: OccupancyOutput | None = None
    alerts: list[str] = field(default_factory=list)

    def gate_energies(self, now: float, extra_moving: dict[int, float], extra_static: dict[int, float]):
        c = self.cfg
        n = int(c["gates"])
        moving = list(self.rng.uniform(0.0, c["noise_max"], n))
        static = list(self.rng.uniform(0.0, c["noise_max"], n))
        p = self.person
        if p.present and p.zone in c["zone_gate"]:
            gate = int(c["zone_gate"][p.zone])
            walking = p.arrived_at is not None and now - p.arrived_at < c["arrival_walk_s"]
            if walking or p.motion == "moving":
                moving[gate] = max(moving[gate], c["moving_moving"])
            elif p.motion == "sleeping":
                static[gate] = max(static[gate], c["sleeping_static"])
            else:
                static[gate] = max(static[gate], c["still_static"])
        for g, e in extra_moving.items():
            moving[g] = max(moving[g], e)
        for g, e in extra_static.items():
            static[g] = max(static[g], e)
        return moving, static

    def wifi(self, now: float, doze: bool) -> bool:
        p = self.person
        if p.present and not self._was_present:          # 귀가 — 접속 지연
            lo, hi = self.cfg["wifi_arrival_delay_s"]
            self._wifi_on_at = now + max(0.0, float(self.rng.uniform(lo, hi)))
        self._was_present = p.present
        if p.left_phone_home:
            on = True                                     # 휴대폰을 두고 나갔다 — 계속 접속
        elif p.present and p.phone_with_person:
            on = self._wifi_on_at is None or now >= self._wifi_on_at
        else:
            on = False
        return on and not doze

    def step(self, now: float, door_open_truth: bool, doze: bool, power_w: dict[str, float],
             extra_moving: dict[int, float], extra_static: dict[int, float]) -> tuple[OccupancyOutput, bool, bool]:
        contact = door_open_truth if self.door_sensor_stuck_at is None else self.door_sensor_stuck_at
        moving, static = self.gate_energies(now, extra_moving, extra_static)
        wifi = self.wifi(now, doze)
        out = self.judge.update(now, contact, moving, static, wifi, power_w)
        self.alerts.extend(out.alerts)
        self.last = out
        return out, wifi, contact
