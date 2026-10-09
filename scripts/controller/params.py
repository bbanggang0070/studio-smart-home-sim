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
    return ControllerParams(th, modes)
