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


def _variant(name: str) -> Any:
    """[v1.32-H] 'variant:<이름>' — 같은 협조 제어기에 harness.yaml controller_variants.<이름> 의 임계값만 바꾼 인스턴스.
    proposed_v131 = v1.32-H 수정 플래그(C5–C8)를 v1.31-H 값으로 되돌린 것 — 같은 새 데이터에서 짝 비교 (docs/15 §12 H-RQ6)."""
    import copy

    from controller.params import ControllerParams, load_params
    from controller.smart_home import SmartHomeController
    from harness.runner import load_harness_config

    over = load_harness_config()["controller_variants"][name]
    p0 = load_params()
    th = copy.deepcopy(p0.th)
    for key, v in over.items():
        node = th
        *head, last = key.split(".")
        for k in head:
            node = node[k]
        if last not in node:
            raise KeyError(f"controller_variants.{name}: thresholds 에 '{key}' 가 없다")
        node[last] = v
    return SmartHomeController(ControllerParams(th, p0.modes))


def make_controller(spec: str) -> Any:
    if spec in BUILTIN:
        return BUILTIN[spec]()
    if spec.startswith("variant:"):
        return _variant(spec.split(":", 1)[1])
    if spec == "unimplemented" or ":" not in spec:
        raise ControllerNotImplemented(
            f"제어기 '{spec}' 는 아직 구현되지 않았다 — config/harness.yaml controllers 를 채우거나 "
            f"--controller hold 로 하네스만 검증하라")
    module, cls = spec.split(":", 1)
    return getattr(importlib.import_module(module), cls)()
