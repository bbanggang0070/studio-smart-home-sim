"""난방 확장 — 제어용 3노드 열모델 식별 (docs/14 §4.1) — 참값 4R4C(온수 바닥) ≠ 제어용 (공기 · 축열 · 바닥).

제어기가 볼 수 있는 값만 쓴다: 실내 온도 · 외기 · 실내 주광 · 재실 · 보일러 연소 여부(전원 계량 플러그 W > 기준).
보일러 열량 · 바닥 온도는 모른다 → 연소 1 일 때의 바닥 공급 열량 Qb 를 함께 식별한다.

  Cf·dTf/dt = Qb·u − (Tf − T)/Rfa
  Ca·dT/dt  = (Tf − T)/Rfa + (Tm − T)/Rim + (To − T)/Rao + gs·L + go·occ + q0
  Cm·dTm/dt = (T − Tm)/Rim + (To − Tm)/Rmo

학습 기록: 참값(hydronic)을 겨울 실측 기상(ASOS 학습 연도)으로 돌리며 조절기 켬/끔 · 설정 · 재실을 무작위로 바꾼다.
평가: 평가 연도(ASOS 2024) 겨울 기간에서 시뮬레이션 RMSE (연도 분리).

    uv run python tools/energy/train_heating_model.py [--days 14] [--out models/heating_3node.yaml]
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.optimize import least_squares

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from env_model.config import load_config  # noqa: E402
from env_model.room import ActuatorCommands, BoilerCommand, ExternalConditions, Occupancy, RoomModel  # noqa: E402

NAMES = ("ca", "cm", "cf", "rim", "rao", "rmo", "rfa", "qb", "gs", "go", "q0")


@dataclass
class Heating3Node:
    ca: float
    cm: float
    cf: float
    rim: float
    rao: float
    rmo: float
    rfa: float
    qb: float
    gs: float
    go: float
    q0: float

    def step(self, t, tm, tf, to, lux, occ, u, dt_h):
        qf = (tf - t) / self.rfa
        dt = qf + (tm - t) / self.rim + (to - t) / self.rao + self.gs * lux + self.go * occ + self.q0
        dtm = (t - tm) / self.rim + (to - tm) / self.rmo
        dtf = self.qb * u - qf
        return t + dt_h * dt / self.ca, tm + dt_h * dtm / self.cm, tf + dt_h * dtf / self.cf


def asos_series(years: list[int]) -> pd.DataFrame:
    fr = [pd.read_csv(REPO / "data" / "weather" / f"asos_seoul_{y}.csv", parse_dates=["time"]) for y in years]
    return pd.concat(fr).set_index("time").sort_index()


def winter_start(series: pd.DataFrame, days: int, rng) -> pd.Timestamp:
    cand = [d for d in pd.date_range(series.index[0].normalize(), series.index[-1].normalize() - pd.Timedelta(days=days), freq="D")
            if d.month in (12, 1, 2) and (d + pd.Timedelta(days=days - 1)).month in (12, 1, 2, 3)]
    return cand[int(rng.integers(len(cand)))]


def trace(env_cfg, series: pd.DataFrame, start: pd.Timestamp, days: int, seed: int, dt_s: float = 300.0) -> dict:
    """참값 hydronic · 실측 기상 · 무작위 운전 → 제어기 관측 기록."""
    rng = np.random.default_rng(seed)
    cfg = env_cfg.with_overrides({"heating.mode": "hydronic"})
    eff = float(env_cfg.get("thermal.solar_luminous_efficacy_lm_per_w"))
    room = RoomModel.from_conditions(cfg, 19.0, 40.0, 10.0, 600.0)
    n = int(days * 86400 / dt_s)
    hours = ((series.index - series.index[0]) / pd.Timedelta(hours=1)).to_numpy(float)
    x0 = (start - series.index[0]) / pd.Timedelta(hours=1)
    rec = {k: np.zeros(n) for k in ("t", "to", "lux", "occ", "u")}
    on, sp, block, occ, occ_end = True, 21.0, 0.0, 1, 0.0
    for i in range(n):
        ts = i * dt_s
        if ts >= block:
            on = bool(rng.random() < 0.7)
            sp = float(rng.choice([16.0, 19.0, 21.0, 23.0]))
            block = ts + rng.uniform(2.0, 8.0) * 3600.0
        if ts >= occ_end:
            occ = int(rng.random() < 0.6)
            occ_end = ts + rng.uniform(1.0, 6.0) * 3600.0
        x = x0 + ts / 3600.0
        to = float(np.interp(x, hours, series["temperature_2m"].to_numpy()))
        rh = float(np.interp(x, hours, series["relative_humidity_2m"].to_numpy()))
        sw = float(np.interp(x, hours, series["shortwave_radiation"].to_numpy()))
        ob = room.step(dt_s, ActuatorCommands(boiler=BoilerCommand(power=on, setpoint_c=sp)),
                       ExternalConditions(outdoor_temp_c=to, outdoor_rh_pct=rh, outdoor_illuminance_lux=sw * eff),
                       occ=Occupancy(count=occ))
        rec["t"][i], rec["to"][i], rec["occ"][i] = ob["temperature_c"], to, occ
        rec["lux"][i] = max(0.0, ob["illuminance_lux"])
        rec["u"][i] = 1.0 if ob["appliance_power_w"].get("boiler", 0.0) > 40.0 else 0.0   # 계량 플러그로 본 연소 여부
    return rec


def simulate(m: Heating3Node, rec: dict, dt_h: float) -> np.ndarray:
    t = tm = tf = rec["t"][0]
    out = np.empty(rec["t"].size)
    for i in range(out.size):
        out[i] = t
        t, tm, tf = m.step(t, tm, tf, rec["to"][i], rec["lux"][i], rec["occ"][i], rec["u"][i], dt_h)
    return out


def identify(rec: dict, dt_s: float) -> tuple[Heating3Node, float]:
    dt_h = dt_s / 3600.0
    x0 = np.log([60.0, 1500.0, 500.0, 0.005, 0.02, 0.3, 0.005, 1500.0, 0.005, 70.0, 20.0])
    lo = np.log([5.0, 100.0, 50.0, 1e-4, 1e-3, 1e-3, 1e-4, 100.0, 1e-5, 1.0, 0.1])
    hi = np.log([1000.0, 5e4, 5000.0, 0.5, 1.0, 10.0, 0.5, 2e4, 1.0, 500.0, 1500.0])

    def unpack(x):
        return Heating3Node(*np.exp(x))

    def resid(x):
        return simulate(unpack(x), rec, dt_h) - rec["t"]

    r = least_squares(resid, x0, bounds=(lo, hi), max_nfev=600)
    return unpack(r.x), float(np.sqrt(np.mean(resid(r.x) ** 2)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--out", default=str(REPO / "models" / "heating_3node.yaml"))
    a = ap.parse_args()
    with open(REPO / "config" / "harness.yaml", encoding="utf-8") as f:
        h = yaml.safe_load(f)
    env_cfg = load_config(REPO / h["paths"]["environment_model"])
    rng = np.random.default_rng(20261128)
    train, test = asos_series(h["weather"]["years"]["train"]), asos_series(h["weather"]["years"]["eval"])
    s0 = winter_start(train, a.days, rng)
    print(f"학습 기록: ASOS {s0:%Y-%m-%d} 부터 {a.days}일 (참값 hydronic · 무작위 운전)", flush=True)
    rec = trace(env_cfg, train, s0, a.days, 1)
    m, fit = identify(rec, 300.0)
    tests = []
    for i in range(3):
        st = winter_start(test, 7, rng)
        tr = trace(env_cfg, test, st, 7, 100 + i)
        pred = simulate(m, tr, 300.0 / 3600.0)
        tests.append((f"{st:%Y-%m-%d}", float(np.sqrt(np.mean((pred - tr["t"]) ** 2)))))
    doc = {"generated_by": "tools/energy/train_heating_model.py", "structure": "3-node (air · mass · floor) — 참값 4R4C 와 다름",
           "train": {"weather": "ASOS", "start": f"{s0:%Y-%m-%d}", "days": a.days, "rmse_c": round(fit, 3)},
           "test_2024": [{"start": s, "rmse_c": round(e, 3)} for s, e in tests],
           "heating_3node": {k: float(f"{getattr(m, k):.6g}") for k in NAMES}}
    Path(a.out).write_text("# 자동 생성 — 손으로 고치지 말 것\n" + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"학습 RMSE {fit:.3f} °C · 평가(2024 겨울) " + " · ".join(f"{s} {e:.3f}" for s, e in tests))
    print(" ".join(f"{k}={getattr(m, k):.4g}" for k in NAMES))


if __name__ == "__main__":
    main()
