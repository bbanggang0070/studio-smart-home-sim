"""제어기 계약과 레지스트리.

제어기는 고속 · 물리 모드에서 같은 코드다. 하네스(또는 ROS 노드 래퍼)와는 이 계약으로만 만난다:

    reset(scenario_params)                         # 실행 시작 시 1회
    step(now_s, inbox) -> outbox                   # 정책 주기마다
        inbox  : {토픽: 최신 값}  — 센서 · 상태 · 사용자 명령(/studio/cmd/mode · activity)
        outbox : {토픽: 값}       — /studio/cmd/* 는 액추에이터로, /studio/state/* 는 로그 · 판정으로 간다
    reasons() -> list[str]  (선택)                  # 이번 주기 결정의 사유 코드 (docs/07 §5.3 ⑥)

harness.yaml 의 controllers 에 baseline → "모듈:클래스" 를 적으면 여기서 불러온다.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol


class Controller(Protocol):
    def reset(self, params: dict[str, Any]) -> None: ...

    def step(self, now_s: float, inbox: dict[str, Any]) -> dict[str, Any]: ...


class HoldController:
    """아무 명령도 내지 않는다 — 액추에이터는 시나리오 초기 상태를 유지한다.
    하네스 자체(주입 · 로깅 · 판정 · 집계)를 검증하는 용도. 판정은 대부분 FAIL 이 정상이다."""

    name = "hold"

    def reset(self, params: dict[str, Any]) -> None:
        pass

    def step(self, now_s: float, inbox: dict[str, Any]) -> dict[str, Any]:
        return {}


BUILTIN = {"hold": HoldController}


class ControllerNotImplemented(RuntimeError):
    pass


def make_controller(spec: str) -> Any:
    if spec in BUILTIN:
        return BUILTIN[spec]()
    if spec == "unimplemented" or ":" not in spec:
        raise ControllerNotImplemented(
            f"제어기 '{spec}' 는 아직 구현되지 않았다 — config/harness.yaml controllers 를 채우거나 "
            f"--controller hold 로 하네스만 검증하라")
    module, cls = spec.split(":", 1)
    return getattr(importlib.import_module(module), cls)()
