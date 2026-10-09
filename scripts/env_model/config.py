"""config/environment_model.yaml 로더.

파일은 ROS 2 파라미터 형식(`environment_model: ros__parameters: ...`)이므로
그 아래 딕셔너리만 꺼내 쓴다. 키 접근은 점 경로(`get("thermal.air_capacity_wh_per_k")`)로 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "environment_model.yaml"
NODE_NAME = "environment_model"


@dataclass(frozen=True)
class EnvModelConfig:
    params: dict[str, Any]

    def get(self, dotted: str) -> Any:
        node: Any = self.params
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                raise KeyError(f"environment_model.yaml 에 '{dotted}' 가 없다")
            node = node[key]
        return node

    def with_overrides(self, overrides: dict[str, Any]) -> "EnvModelConfig":
        """점 경로 → 값 딕셔너리로 일부 계수만 바꾼 사본 (민감도 · 파라미터 변동 실험용)."""
        import copy

        params = copy.deepcopy(self.params)
        for dotted, value in overrides.items():
            *parents, leaf = dotted.split(".")
            node = params
            for key in parents:
                node = node[key]
            if leaf not in node:
                raise KeyError(f"environment_model.yaml 에 '{dotted}' 가 없다")
            node[leaf] = value
        return EnvModelConfig(params)


def load_config(path: str | Path = DEFAULT_PATH) -> EnvModelConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return EnvModelConfig(raw[NODE_NAME]["ros__parameters"])
