"""주광 모델 (v3.4.21 · W12 T12.5 렌더 대조로 개정) — 순수 함수. 참값 환경 모델과 제어기가 각자의 설정값으로 부른다.

바깥 수평 조도 E 를 직사광(해) · 확산광(하늘)으로 나눈다 — 직사광 비율 f 는 하늘 상태(맑음 · 구름 · 흐림 · 비)로 정한다.
  작업면 주광(θ)  = E · [ f·DF_d·τ_d(θ) + (1−f)·DF_s·τ_s(θ) ]
  천장 센서 주광(θ) = E · [ f·DF_d·τ_d(θ)·r_d(θ) + (1−f)·DF_s·τ_s(θ)·r_s(θ) ]
    DF = 블라인드 열림 주광률 · τ(θ) = 열림 대비 투과 비 · r(θ) = 센서/작업면 비 — 블라인드 각도 표를 선형 보간
렌더(경로 추적, results/validation/daylight_check.csv)에서: 직사광은 블라인드가 거의 다 막고(45° 0.13) 센서 비가 1 을 넘는다(닫히면
천장 센서가 슬랫 반사광을 받는다) · 확산광은 덜 막고(45° 0.71) 센서 비 ≈ 0.9. 이전 모델(주광률 0.02 · 투과율 0.85 → 0.12 선형 ·
센서 비 0.38 고정)은 맑고 블라인드가 열렸을 때만 맞았다.
cfg = {direct_fraction: {sky: f}, blind_deg: [...], direct: {df_open, transmittance: [...], sensor_ratio: [...]}, diffuse: {...}}
"""

from __future__ import annotations

import numpy as np


def _tab(cfg: dict, part: str, key: str, deg: float) -> float:
    return float(np.interp(deg, cfg["blind_deg"], cfg[part][key]))


def direct_fraction(cfg: dict, sky: str) -> float:
    return float(cfg["direct_fraction"].get(sky, cfg["direct_fraction"]["clear"]))


def workplane_per_outdoor(cfg: dict, sky: str, deg: float) -> float:
    """작업면 주광 / 바깥 수평 조도 (유효 주광률)."""
    f = direct_fraction(cfg, sky)
    return (f * cfg["direct"]["df_open"] * _tab(cfg, "direct", "transmittance", deg)
            + (1 - f) * cfg["diffuse"]["df_open"] * _tab(cfg, "diffuse", "transmittance", deg))


def sensor_per_outdoor(cfg: dict, sky: str, deg: float) -> float:
    """천장 센서 위치 주광 / 바깥 수평 조도."""
    f = direct_fraction(cfg, sky)
    return (f * cfg["direct"]["df_open"] * _tab(cfg, "direct", "transmittance", deg) * _tab(cfg, "direct", "sensor_ratio", deg)
            + (1 - f) * cfg["diffuse"]["df_open"] * _tab(cfg, "diffuse", "transmittance", deg) * _tab(cfg, "diffuse", "sensor_ratio", deg))


def sensor_to_workplane(cfg: dict, sky: str, deg: float) -> float:
    """센서 주광 → 작업면 주광 배율 (= 1 / 유효 센서 비)."""
    s = sensor_per_outdoor(cfg, sky, deg)
    return workplane_per_outdoor(cfg, sky, deg) / s if s > 0 else 0.0


def relative_transmittance(cfg: dict, sky: str, deg: float) -> float:
    """작업면 주광의 블라인드 열림 대비 비 (0° = 1)."""
    o = workplane_per_outdoor(cfg, sky, 0.0)
    return workplane_per_outdoor(cfg, sky, deg) / o if o > 0 else 1.0


def angle_for_relative(cfg: dict, sky: str, rel: float, max_deg: float, step: float = 1.0) -> float:
    """작업면 주광을 열림의 rel 배로 줄이는 가장 작은 각도 (투과 비는 각도에 단조 감소)."""
    d = 0.0
    while d < max_deg and relative_transmittance(cfg, sky, d) > rel:
        d += step
    return min(d, max_deg)
