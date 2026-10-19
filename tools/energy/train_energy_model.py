"""에너지 예측 학습 산출물 생성 — models/energy_<persona>.yaml (docs/08 §5.3 · §5.3-1 · §5.8).

1) 귀가 이력: 페르소나 설정(harness.yaml personas)으로 학습 기간 평일의 귀가 시각을 만든다.
2) 2R2C 식별: 참값 3R3C 환경 모델을 무작위 운전(외기 · 일사 · 에어컨 켬/끔 · 재실)으로 돌려 기록을 만들고,
   제어기가 볼 수 있는 값(실내 온도 · 외기 · 실내 주광 · 재실 · 에어컨 전력)만으로 2R2C 를 시뮬레이션 오차 최소제곱으로 맞춘다.
   참값 계수는 쓰지 않는다 — '자기 답을 자기가 맞히는' 순환을 피한다.

    uv run python tools/energy/train_energy_model.py [--persona commuter] [--out models/energy_commuter.yaml]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import least_squares

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from controller.energy import Thermal2R2C  # noqa: E402
from controller.params import load_params  # noqa: E402
from env_model.config import load_config  # noqa: E402
from env_model.room import (AcCommand, ActuatorCommands, ExternalConditions, Occupancy,  # noqa: E402
                            RoomModel)

PARAM_NAMES = list(Thermal2R2C.__dataclass_fields__)


def _hhmm(s: str) -> float:
    h, m = s.split(":")
    return int(h) * 3600.0 + int(m) * 60.0


def arrival_history(cfg: dict) -> list[float]:
    rng = np.random.default_rng(cfg["seed"])
    n = int(cfg["train_weeks"] * cfg["weekdays_per_week"])
    base = _hhmm(cfg["arrival_mean"]) + rng.normal(0.0, cfg["arrival_sd_min"] * 60.0, n)
    late = rng.random(n) < cfg["late_probability"]
    return sorted(float(round(x)) for x in base + late * cfg["late_shift_min"] * 60.0)


def generate_trace(tc: dict, env_cfg, p, weather=None) -> dict[str, np.ndarray]:
    """weather: 시각[s] → {outdoor_temp_c, outdoor_rh_pct, outdoor_illuminance_lux} (실측 기상 · 없으면 합성 일교차 · 일사)."""
    rng = np.random.default_rng(tc["seed"])
    dt = float(tc["dt_s"])
    steps = int(tc["days"] * 86400 / dt)
    room = RoomModel.from_conditions(env_cfg, 27.0, 55.0, 10.0, 450.0)
    lm = "lighting_model."
    own = 0.0
    rec = {k: np.zeros(steps) for k in ("t", "to", "lux", "occ", "ac_w")}
    ac_on, sp, block_end, occ, occ_end = False, 26.0, 0.0, 0, 0.0
    day_mean, sun_peak = 30.0, 40000.0
    v = "virtual_sensors.lux."
    rise, sset = p.get(v + "sunrise_h"), p.get(v + "sunset_h")
    for i in range(steps):
        ts = i * dt
        tod_h = (ts % 86400.0) / 3600.0
        if i % int(86400 / dt) == 0:
            day_mean = rng.uniform(*tc["outdoor_mean_c"])
            sun_peak = rng.uniform(*tc["sun_peak_lux"])
        to = day_mean + tc["outdoor_swing_c"] * math.cos(2 * math.pi * (tod_h - 15.0) / 24.0)
        sun = math.sin(math.pi * (tod_h - rise) / (sset - rise)) if rise < tod_h < sset else 0.0
        if ts >= block_end:
            ac_on = bool(rng.random() < 0.5)
            sp = float(rng.choice(tc["ac_setpoints_c"]))
            block_end = ts + rng.uniform(*tc["ac_block_h"]) * 3600.0
        if ts >= occ_end:
            occ = int(rng.random() < tc["occupied_probability"])
            occ_end = ts + rng.uniform(1.0, 4.0) * 3600.0
        act = ActuatorCommands(ac=AcCommand(power=ac_on, mode="cool", setpoint_c=sp))
        if weather is None:
            ext = ExternalConditions(outdoor_temp_c=to, outdoor_rh_pct=tc["outdoor_rh_pct"],
                                     outdoor_illuminance_lux=sun_peak * sun)
        else:
            w = weather(ts)
            to = w["outdoor_temp_c"]
            ext = ExternalConditions(outdoor_temp_c=to, outdoor_rh_pct=w["outdoor_rh_pct"],
                                     outdoor_illuminance_lux=w["outdoor_illuminance_lux"])
        obs = room.step(dt, act, ext, occ=Occupancy(count=occ))
        rec["t"][i] = obs["temperature_c"]
        rec["to"][i] = to
        rec["lux"][i] = max(0.0, obs["illuminance_lux"] - own)      # 조명 꺼 둠 — 측정 조도 = 주광
        rec["occ"][i] = occ
        rec["ac_w"][i] = obs["appliance_power_w"].get("ac", 0.0)
    return rec


def simulate(m: Thermal2R2C, rec, dt_h: float, cop: float, t0: float, tm0: float) -> np.ndarray:
    n = rec["t"].size
    out = np.empty(n)
    t, tm = t0, tm0
    for i in range(n):
        out[i] = t
        t, tm = m.step(t, tm, rec["to"][i], rec["lux"][i], rec["occ"][i], rec["ac_w"][i] * cop, dt_h)
    return out


def identify(rec, dt_s: float, cop: float):
    dt_h = dt_s / 3600.0
    # η 는 1 로 고정한다 — 모든 C · 이득을 k 배, R 을 1/k 배 해도 같은 거동이라 기준 하나를 정해야 식별된다
    # (명판 COP 로 환산한 에어컨 제거 열량이 기준 · 부분부하 COP 차이는 다른 계수에 흡수된다)
    x0 = np.log([60.0, 1500.0, 0.02, 0.05, 0.03, 0.02, 80.0, 50.0])   # Ca Cm Rim Rao Rmo gs go q0
    lo = np.log([5.0, 100.0, 1e-4, 1e-3, 1e-3, 1e-4, 1.0, 1.0])
    hi = np.log([1000.0, 5e4, 0.5, 1.0, 10.0, 2.0, 500.0, 1500.0])

    def unpack(x):
        return Thermal2R2C(**dict(zip(PARAM_NAMES, [*np.exp(x), 1.0])))

    def resid(x):
        return simulate(unpack(x), rec, dt_h, cop, rec["t"][0], rec["t"][0]) - rec["t"]

    r = least_squares(resid, x0, bounds=(lo, hi), x_scale=1.0, max_nfev=400)
    m = unpack(r.x)
    rmse = float(np.sqrt(np.mean(resid(r.x) ** 2)))
    return m, rmse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="commuter")
    ap.add_argument("--out")
    a = ap.parse_args()
    with open(REPO / "config" / "harness.yaml", encoding="utf-8") as f:
        h = yaml.safe_load(f)
    p = load_params()
    env_cfg = load_config(REPO / h["paths"]["environment_model"])
    tc = h["energy_training"]
    ac = p.get("appliances.ac")
    cop = ac["cooling_kw"] * 1000.0 / ac["power_w"]           # 명판 COP — 제어기가 아는 값
    print("학습 기록 생성 중 (참값 3R3C) ...", flush=True)
    rec = generate_trace(tc, env_cfg, p)
    print("2R2C 식별 중 ...", flush=True)
    m, rmse = identify(rec, float(tc["dt_s"]), cop)
    arrivals = arrival_history(h["personas"][a.persona])
    out = Path(a.out) if a.out else REPO / "models" / f"energy_{a.persona}.yaml"
    doc = {
        "persona": a.persona,
        "generated_by": "tools/energy/train_energy_model.py",
        "thermal_2r2c": {k: float(f"{v:.6g}") for k, v in m.to_dict().items()},
        "thermal_fit": {"days": tc["days"], "dt_s": tc["dt_s"], "rmse_c": round(rmse, 3)},
        "arrival_history_tod_s": arrivals,
    }
    out.write_text("# 자동 생성 — 손으로 고치지 말 것 (tools/energy/train_energy_model.py)\n"
                   + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"2R2C RMSE {rmse:.3f} °C · 귀가 이력 {len(arrivals)}일 → {out.relative_to(REPO)}")
    print(" ".join(f"{k}={v:.4g}" for k, v in m.to_dict().items()))


if __name__ == "__main__":
    main()
