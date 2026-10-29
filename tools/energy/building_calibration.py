"""건물 프리셋 보정 점검 (v1.32-H · 2026-10-29) — 참값 모델 건물 계수가 실제 원룸 범위에 드는지 본다.

    uv run python tools/energy/building_calibration.py            # config/harness.yaml building_presets 전부
    uv run python tools/energy/building_calibration.py --mass 0.6  # 축열 ×0.6 을 함께 (무작위 범위 끝 확인)

지표 (모두 재실 1인 · 일사 0 · 보일러 21 °C 상시 · 외기 고정)
  UA        유효 열손실 계수 W/K = 24 h 평균 바닥 → 실내 열 / (21 − 외기)  — 침기 · 기본 환기 · 외피 · 창 합
  τ12       난방 끈 뒤 12 h 자연 냉각의 유효 시간상수 h = 12 / ln((T0 − To)/(T12 − To))  (외기 −5 °C)
  gas_day   1월 평균(외기 −2 °C) 하루 난방 가스 kWh (온수 제외)
비교 기준 (docs/14 §16 · draft)
  τ: 영국 742가구 실측 중앙값 44.4 h · 주택 재고 22.8–30.6 h (Halloran 외 2024, arXiv 2405.10450)
  하루 가스: 1인 원룸 겨울 월 20–80 m³ (고지서 사례 · 1 m³ ≈ 11.6 kWh) − 온수 약 3 kWh/일 → 하루 난방 약 5–28 kWh
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from env_model.config import load_config  # noqa: E402
from env_model.room import ActuatorCommands, BoilerCommand, ExternalConditions, Occupancy, RoomModel  # noqa: E402
from harness.runner import load_harness_config  # noqa: E402


def measure(cfg) -> dict[str, float]:
    on = ActuatorCommands(boiler=BoilerCommand(power=True, setpoint_c=21.0))
    off = ActuatorCommands(boiler=BoilerCommand(power=False, setpoint_c=21.0))
    occ = Occupancy(count=1, activity="seated")
    out: dict[str, float] = {}
    for to, key in ((-2.0, "jan"), (-5.0, "cold")):
        ext = ExternalConditions(outdoor_temp_c=to, outdoor_rh_pct=60.0)
        m = RoomModel.from_conditions(cfg, 21.0, 40.0, 8.0, 800.0)
        for _ in range(72 * 60):
            m.step(60.0, on, ext, None, occ)
        g0 = m.state.energy_wh.get("boiler_gas", 0.0)
        for _ in range(24 * 60):
            m.step(60.0, on, ext, None, occ)
        gas = (m.state.energy_wh.get("boiler_gas", 0.0) - g0) / 1000.0
        if key == "jan":
            out["gas_day"] = gas
            out["UA"] = gas * 1000.0 * cfg.get("heating.hydronic.boiler_efficiency") / 24.0 / (21.0 - to)
        else:
            t0 = m.state.temp_c
            for _ in range(12 * 60):
                m.step(60.0, off, ext, None, occ)
            out["tau12"] = 12.0 / math.log((t0 - to) / (m.state.temp_c - to))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mass", type=float, default=1.0, help="축열 · 외피 · 바닥 열용량 배수")
    a = ap.parse_args()
    hcfg = load_harness_config()
    base = load_config(REPO / hcfg["paths"]["environment_model"]).with_overrides({"heating.mode": "hydronic"})
    print(f"{'프리셋':<8} {'UA W/K':>7} {'τ12 h':>7} {'가스 kWh/일':>11}   (축열 ×{a.mass})")
    for name, ov in hcfg["building_presets"].items():
        cfg = base.with_overrides(ov or {})
        if a.mass != 1.0:
            cfg = cfg.with_overrides({k: cfg.get(k) * a.mass for k in (
                "thermal.mass_capacity_wh_per_k", "thermal.envelope_capacity_wh_per_k", "heating.hydronic.floor_capacity_wh_per_k")})
        r = measure(cfg)
        print(f"{name:<8} {r['UA']:7.1f} {r['tau12']:7.0f} {r['gas_day']:11.1f}")


if __name__ == "__main__":
    main()
