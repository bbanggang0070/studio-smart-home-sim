"""EXP-4 — 열모델 식별: 학습 기록 1 · 2 · 4주 → 온도 예측 RMSE · 손익분기 외출 시간 T* 오차 (docs/08 §5.3-1 · §5.8).

    uv run python tools/energy/exp4_identification.py

1) 학습: 참값 3R3C 무작위 운전 기록(train_energy_model.generate_trace) N일 → 2R2C 식별 (제어기가 볼 수 있는 값만)
2) 예측 RMSE: 따로 만든 7일 시험 기록에서 2R2C 시뮬레이션 오차
3) T*: 외출 D 시간 동안 세 전략의 비용 = 전력량 Wh + 불쾌(귀가 후 60분, 설정 + 1 °C 초과 K·h) × 2,000
     셋백(+2 °C) · 끄기 · 끄기 + 귀가 L 분 전 냉방(가장 좋은 L)
   T* = 끄는 쪽(끄기 · 미리 냉방 중 좋은 것)이 셋백보다 싸지는 가장 짧은 D — 참값(3R3C)과 식별 모델(2R2C) 각각
   귀가 시각은 확정값 (귀가 예측 오차는 EXP-2 에서 따로 본다) · 낮 외출(9시 출발 · 맑은 날 일사) · 외기온 고정
   식별 모델의 조도 입력 = 참값 실행에서 기록한 센서 조도 (제어기가 보는 값) · 비교는 '끄는 쪽이 셋백보다 비싸지 않은' 가장 짧은 D
결과: results/exp4/summary.csv · 표 출력
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tools" / "energy"))

from common import daylight as daylight_model  # noqa: E402
from controller.energy import AcSpec, Thermal2R2C  # noqa: E402
from controller.params import load_params  # noqa: E402
from env_model.config import load_config  # noqa: E402
from env_model.room import AcCommand, ActuatorCommands, ExternalConditions, Occupancy, RoomModel  # noqa: E402
from train_energy_model import generate_trace, identify, simulate  # noqa: E402


def schedules(D_h: float, lead_min: list[float], sp: float, setback: float):
    """전략 → 함수(t_s) = (에어컨 켜짐, 설정). 외출 0 ~ D, 귀가 후 60분."""
    D = D_h * 3600.0
    out = {"setback": lambda t: (True, sp + setback if t < D else sp)}
    for L in lead_min:
        start = max(0.0, D - L * 60.0)
        out[f"off_L{int(L)}"] = (lambda s: (lambda t: (t >= s, sp)))(start if L > 0 else D)
    return out, D


def sun_lux(c: dict, p, t_s: float) -> float:
    """출발(depart_tod_h) 뒤 t_s 초의 외부 조도 — 맑은 날 해 고도 모양."""
    v = "virtual_sensors.lux."
    rise, sset = p.get(v + "sunrise_h"), p.get(v + "sunset_h")
    h = (c["depart_tod_h"] + t_s / 3600.0) % 24.0
    return c["sun_peak_lux"] * np.sin(np.pi * (h - rise) / (sset - rise)) if rise < h < sset else 0.0


def cost_truth(env_cfg, tout: float, sched, D: float, c: dict, w: float, margin: float, p=None, lux_log=None) -> float:
    dt = c["dt_s"]
    room = RoomModel.from_conditions(env_cfg, c["setpoint_c"], 55.0, 10.0, 450.0)
    for k in range(int(c["warmup_h"] * 3600 / dt)):                 # 출발 전 평형 (재실 · 설정온도 냉방 · 출발 전 일사)
        ext = ExternalConditions(outdoor_temp_c=tout, outdoor_rh_pct=60.0,
                                 outdoor_illuminance_lux=sun_lux(c, p, (k * dt) - c["warmup_h"] * 3600))
        room.step(dt, ActuatorCommands(ac=AcCommand(power=True, mode="cool", setpoint_c=c["setpoint_c"])), ext, occ=Occupancy(1))
    e = disc = 0.0
    t = 0.0
    while t < D + 3600.0:
        on, sp = sched(t)
        home = t >= D
        ext = ExternalConditions(outdoor_temp_c=tout, outdoor_rh_pct=60.0, outdoor_illuminance_lux=sun_lux(c, p, t))
        obs = room.step(dt, ActuatorCommands(ac=AcCommand(power=on, mode="cool", setpoint_c=sp)), ext,
                        occ=Occupancy(1 if home else 0))
        if lux_log is not None:
            lux_log.append(obs["illuminance_lux"])                  # 조명 꺼짐 — 센서 조도 = 주광 (식별 모델 입력)
        e += obs["appliance_power_w"].get("ac", 0.0) * dt / 3600.0
        if home:
            disc += max(0.0, obs["temperature_c"] - (c["setpoint_c"] + margin)) * dt / 3600.0
        t += dt
    return e + w * disc


def cost_model(m: Thermal2R2C, ac: AcSpec, tout: float, sched, D: float, c: dict, w: float, margin: float,
               lux_warm: list, lux_away: list) -> float:
    dt_h = c["dt_s"] / 3600.0
    sp0 = c["setpoint_c"]
    t = tm = sp0
    for lux in lux_warm:
        q = ac.removal(t, sp0)
        t, tm = m.step(t, tm, tout, lux, 1.0, q, dt_h)
    e = disc = 0.0
    s = 0.0
    i = 0
    while s < D + 3600.0:
        on, sp = sched(s)
        home = s >= D
        q = ac.removal(t, sp) if on else 0.0
        e += q / ac.cop * dt_h
        t, tm = m.step(t, tm, tout, lux_away[min(i, len(lux_away) - 1)], 1.0 if home else 0.0, q, dt_h)
        i += 1
        if home:
            disc += max(0.0, t - (sp0 + margin)) * dt_h
        s += c["dt_s"]
    return e + w * disc


def env_lux(env_cfg, outdoor_lux: float) -> float:
    """천장 센서 위치 주광 (참값 환경 모델과 같은 식 · 블라인드 열림 · 조명 꺼짐) — 식별 모델 입력."""
    return outdoor_lux * daylight_model.sensor_per_outdoor(env_cfg.get("lighting.daylight"), "clear", 0.0)


def t_star(cost_fn, c: dict, setback: float) -> float:
    for D_h in c["away_grid_h"]:
        sch, D = schedules(D_h, c["precool_lead_min"], c["setpoint_c"], setback)
        costs = {k: cost_fn(f, D) for k, f in sch.items()}
        off_best = min(v for k, v in costs.items() if k != "setback")
        if off_best <= costs["setback"] + 1e-6:                     # 끄는 쪽이 비싸지 않으면 끈다
            return D_h
    return float("inf")


def main() -> None:
    h = yaml.safe_load((REPO / "config" / "harness.yaml").read_text(encoding="utf-8"))
    p = load_params()
    env_cfg = load_config(REPO / h["paths"]["environment_model"])
    c, tc = h["exp4_identification"], h["energy_training"]
    acp = p.get("appliances.ac")
    cop = acp["cooling_kw"] * 1000.0 / acp["power_w"]
    ac = AcSpec(acp["cooling_kw"] * 1000.0, cop, p.get("energy.planner.ac_modulation_w_per_k"), p.get("energy.planner.ac_band_c"))
    w = p.get("energy.planner.discomfort_wh_per_kh")
    margin = p.get("energy.planner.discomfort_margin_c")
    setback = p.get("energy.away_strategy.setback_c")
    test = generate_trace({**tc, "days": c["test_days"], "seed": tc["seed"] + 99}, env_cfg, p)
    dt_h = tc["dt_s"] / 3600.0
    # 식별 모델이 볼 조도 — 참값 실행에서 센서 조도를 기록 (전략과 무관 · 조명 꺼짐 · 블라인드 열림)
    lux_warm, lux_away = [], []
    dt = c["dt_s"]
    for k in range(int(c["warmup_h"] * 3600 / dt)):
        lux_warm.append(env_lux(env_cfg, sun_lux(c, p, k * dt - c["warmup_h"] * 3600)))
    for k in range(int((max(c["away_grid_h"]) + 1.0) * 3600 / dt) + 2):
        lux_away.append(env_lux(env_cfg, sun_lux(c, p, k * dt)))
    truth_t = {to: t_star(lambda f, D, to=to: cost_truth(env_cfg, to, f, D, c, w, margin, p), c, setback) for to in c["outdoor_c"]}
    print("참값 T*:", {f"{k:g}°C": v for k, v in truth_t.items()}, flush=True)
    rows = []
    for days in c["train_days"]:
        for k in c["seeds"]:
            rec = generate_trace({**tc, "days": days, "seed": tc["seed"] + k}, env_cfg, p)
            m, rmse_fit = identify(rec, float(tc["dt_s"]), cop)
            pred = simulate(m, test, dt_h, cop, test["t"][0], test["t"][0])
            rmse_test = float(np.sqrt(np.mean((pred - test["t"]) ** 2)))
            row = {"train_days": days, "seed": k, "rmse_fit_c": round(rmse_fit, 3), "rmse_test_c": round(rmse_test, 3)}
            for to in c["outdoor_c"]:
                ts = t_star(lambda f, D, to=to: cost_model(m, ac, to, f, D, c, w, margin, lux_warm, lux_away), c, setback)
                row[f"t_star_{int(to)}_h"] = ts
                row[f"t_star_err_{int(to)}_h"] = abs(ts - truth_t[to]) if np.isfinite(ts) and np.isfinite(truth_t[to]) else np.nan
            rows.append(row)
            print(row, flush=True)
    df = pd.DataFrame(rows)
    out = REPO / "results" / "exp4"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "runs.csv", index=False)
    summ = df.groupby("train_days").agg(["mean", "std"]).drop(columns="seed").round(3)
    summ.to_csv(out / "summary.csv")
    pd.DataFrame([{f"t_star_{int(k)}_h": v for k, v in truth_t.items()}]).to_csv(out / "truth_t_star.csv", index=False)
    print(summ.to_string())


if __name__ == "__main__":
    main()
