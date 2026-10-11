"""제어기 설정 — thresholds.yaml(시스템 상수, ROS 2 파라미터 형식) + user_modes.yaml(사용자 설정).

제어기는 환경 참값 설정(environment_model.yaml)을 읽지 않는다 (참값 ≠ 제어용).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
THRESHOLDS = REPO / "config" / "thresholds.yaml"
USER_MODES = REPO / "config" / "user_modes.yaml"


@dataclass(frozen=True)
class ControllerParams:
    th: dict[str, Any]
    modes: dict[str, Any]

    def get(self, dotted: str) -> Any:
        node: Any = self.th
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                raise KeyError(f"thresholds.yaml 에 '{dotted}' 가 없다")
            node = node[key]
        return node

    def mode(self, name: str) -> dict[str, Any]:
        return self.modes["modes"][name]

    def noise(self, grade: str) -> dict[str, Any]:
        return self.modes["noise_grades"][grade]


def load_params(thresholds: str | Path = THRESHOLDS, user_modes: str | Path = USER_MODES) -> ControllerParams:
    with open(thresholds, encoding="utf-8") as f:
        th = yaml.safe_load(f)["smart_home_controller"]["ros__parameters"]
    with open(user_modes, encoding="utf-8") as f:
        modes = yaml.safe_load(f)
    clamp_user_modes(modes)
    return ControllerParams(th, modes)


def clamp_user_modes(modes: dict[str, Any]) -> list[str]:
    """user_modes.yaml 의 사용자 설정을 editable_ranges 로 자른다 (W09 T9.v1). → 자른 항목 목록."""
    r = modes.get("editable_ranges") or {}
    changed = []

    def clip(name, val, rng):
        if val is None or rng is None:
            return val
        new = min(max(float(val), rng[0]), rng[1])
        if new != val:
            changed.append(f"{name} {val} → {new}")
        return new

    for name, m in (modes.get("modes") or {}).items():
        if not isinstance(m, dict) or name == "AWAY":     # AWAY 는 쾌적 범위가 아니라 곰팡이 방지 등 시스템 값 — 자르지 않는다
            continue
        key = "sleep_cooling_setpoint_c" if name == "SLEEP" else "cooling_setpoint_c"
        if "cooling_setpoint_c" in m:
            m["cooling_setpoint_c"] = clip(f"{name}.cooling_setpoint_c", m["cooling_setpoint_c"], r.get(key))
        if m.get("base_vent_m3h"):                         # 0 = 무재실(외출) — 범위 밖이 정상
            m["base_vent_m3h"] = clip(f"{name}.base_vent_m3h", m["base_vent_m3h"], r.get("base_vent_m3h"))
        hr = m.get("humidity_range_pct")
        if hr:
            m["humidity_range_pct"] = [clip(f"{name}.humidity_low", hr[0], r.get("humidity_low_pct")),
                                       clip(f"{name}.humidity_high", hr[1], r.get("humidity_high_pct"))]
        lt = m.get("lighting") or {}
        if lt.get("cct_k"):
            lt["cct_k"] = clip(f"{name}.cct_k", lt["cct_k"], r.get("cct_k"))
    return changed
