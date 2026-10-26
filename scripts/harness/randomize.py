"""무작위 조건 추출 (docs/11 필수 조치 2) — 고속 무작위 반복(tools/run_randomized.py) · 물리 모드 조건 무작위화가 같이 쓴다.

config/harness.yaml randomization — 참값 계수(truth_params) · 외기(external) 변동. numpy 만 쓴다 (ROS 컨테이너에서도 돈다).
"""

from __future__ import annotations

import copy

import numpy as np


def draw(cfg: dict, env_cfg, seed: int, nominal: bool) -> tuple[dict, dict]:
    """→ (참값 덮어쓰기, 외기 변동 {키: (종류, 값)})."""
    rng = np.random.default_rng(seed)
    over, ext = {}, {}
    for key, spec in cfg["truth_params"].items():
        kind, (lo, hi) = next(iter((k, v) for k, v in spec.items()))
        x = 1.0 if (nominal and kind == "scale") else float(rng.uniform(lo, hi))
        base = env_cfg.get(key)
        if kind == "uniform":
            over[key] = base if nominal else x
        else:
            over[key] = [v * x for v in base] if isinstance(base, list) else base * x
    for key, spec in cfg["external"].items():
        kind = "offset" if "offset" in spec else "scale"
        lo, hi = spec[kind]
        x = (0.0 if kind == "offset" else 1.0) if nominal else float(rng.uniform(lo, hi))
        ext[key] = (kind, x, spec.get("clip"))
    return over, ext


def perturb_scenario(sc: dict, ext: dict) -> dict:
    sc = copy.deepcopy(sc)

    def apply(d: dict) -> None:
        for key, (kind, x, clip) in ext.items():
            if key in d and isinstance(d[key], (int, float)):
                v = d[key] + x if kind == "offset" else d[key] * x
                d[key] = float(np.clip(v, *clip)) if clip else float(v)
    apply(sc["external"])
    for ev in sc.get("events") or []:
        apply(ev.get("set") or {})
    return sc


def scale_controller_params(p, spec: dict, seed: int):
    """A2 임계값 민감도 (2026-10-26) — 제어기 판단 임계값(숫자 · float)을 각각 균등 [lo, hi] 배로 흔든 ControllerParams 사본.
    spec = {sections: [...], range: [lo, hi], exclude: 정규식} · 판정 · 지표가 쓰는 값(budget)과 모델 상수는 exclude 로 뺀다.
    → (새 params, {키: 배율})"""
    import re
    from controller.params import ControllerParams
    rng = np.random.default_rng(seed)
    ex = re.compile(spec.get("exclude", "$^"))
    th = copy.deepcopy(p.th)
    lo, hi = spec["range"]
    drawn: dict[str, float] = {}

    def walk(d: dict, pre: str) -> None:
        for k in sorted(d):
            v, key = d[k], f"{pre}.{k}"
            if isinstance(v, dict):
                walk(v, key)
            elif isinstance(v, float) and not ex.search(key):
                x = float(rng.uniform(lo, hi))
                d[k], drawn[key] = v * x, x
    for sec in spec["sections"]:
        walk(th[sec], sec)
    return ControllerParams(th, p.modes), drawn

