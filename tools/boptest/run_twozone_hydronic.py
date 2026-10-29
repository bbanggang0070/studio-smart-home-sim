"""BOPTEST twozone_apartment_hydronic — 난방 확장 트랙 외부 검증 (docs/14 F8 · docs/15 §4 부 지표).

    tools/boptest/run_server.sh twozone_apartment_hydronic 5002
    uv run python tools/boptest/run_twozone_hydronic.py [--periods typical_heat_day,peak_heat_day] [--methods proposed]

건물: 2구역(거실 · 침실) 아파트 · 온수 바닥난방 · 공기열 히트펌프 5 kW · 밀라노 TMY · 재실 평일 20–08시 (테스트 케이스 문서).
우리 쪽 연결: 원룸이라 '방 하나' 로 본다 — 제어는 거실(dayZon) 실내 온도로, 보일러 설정은 두 구역 조절기에 같은 값.
  재실 = 테스트 케이스 일정 '월–금 20시 ~ 다음 날 08시' (문서) — 우리 하네스의 재실 센서 자리.
    처음엔 거실 실내 발열(reaPowQint 0 / 201 W)로 판정했으나, 조절기 설정을 덮어쓰면 발열이 201 W 로 고정돼(BOPTEST 모델 특성)
    쓸 수 없었다 (2026-10-28 · 기준 실행에서 1월 1일 = 월요일 확인)
  보일러 계량 플러그 = 히트펌프 + 순환펌프 전력 (E17 확인용 — 이 건물에선 '보일러' = 히트펌프)
방식: boptest_baseline (내장 조절기 21/16 °C) · A (22 °C 켜 둠) · A2 (스마트 조절기 재실 · 밤) · B · proposed (v1.30-H 코드 그대로 · 장치 = 보일러만)
KPI: BOPTEST 표준 tdis_tot · ener_tot · cost_tot · 재실 중 실내 온도 분포
설정: config/harness.yaml boptest_heating · 결과 results/boptest_heating/ · results/tables/boptest_heating_kpis.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from actuators.l0_protect import BoilerGuard  # noqa: E402
from controller.params import load_params  # noqa: E402
from harness.controllers import make_controller  # noqa: E402
from harness.manifest import write_manifest  # noqa: E402
from harness.runner import load_harness_config  # noqa: E402
from interfaces import topics as T  # noqa: E402
from run_bestest_air import Client  # noqa: E402

K0 = 273.15


def make_ours(method: str, hcfg: dict, bc: dict):
    spec = hcfg["controllers"][method]
    ctrl = make_controller(spec)
    sc = {"appliance_profile": "full_heating", "initial": {"appliances": {"boiler": {"power": True, "setpoint": 21.0}}}}
    ctrl.reset({"scenario": sc, "baseline": method, "seed": 0, "rng": np.random.default_rng(0)})
    if hasattr(ctrl, "rules"):
        ctrl.rules.devices = set(bc["devices"])
        ctrl.devices = ctrl.rules.devices
    return ctrl


def run(method: str, period: str, cli: Client, hcfg: dict, bc: dict) -> tuple[dict, pd.DataFrame]:
    th = load_params().th
    cli.put("/step", {"step": bc["step_s"]})
    y = cli.put("/scenario", {"time_period": period, "electricity_price": bc["electricity_price"],
                               "temperature_uncertainty": None, "solar_uncertainty": None, "seed": None})["time_period"]
    ours = method != "boptest_baseline"
    ctrl = make_ours(method, hcfg, bc) if ours else None
    b = th["appliances"]["boiler"]
    l0 = BoilerGuard(b["min_power_toggle_s"], b["min_setpoint_change_s"], b["setpoint_range_c"], b["setpoint_step_c"],
                     True, 21.0)
    want = {"power": True, "setpoint": 21.0}
    ctrl_state: dict = {}
    u: dict = {}
    rows = []
    a = bc["assumed"]
    t_start = float(y["time"])
    end = t_start + 14 * 86400.0
    q_min = float(y["dayZon_reaPowQint_y"])
    while float(y["time"]) < end - 1e-6:
        t = float(y["time"])
        q = float(y["dayZon_reaPowQint_y"])
        day, h = int(t // 86400) % 7, (t % 86400.0) / 3600.0      # 0 = 월 (1월 1일 = 월요일 — 기준 실행 발열로 확인)
        occ = (day <= 4 and h >= bc["occupied_from_h"]) or (1 <= day <= 5 and h < bc["occupied_until_h"])
        to, tz = y["weatherStation_reaWeaTDryBul_y"] - K0, y["dayZon_reaTRooAir_y"] - K0
        p_hp = float(y["hydronicSystem_reaPeleHeaPum_y"]) + float(y["hydronicSystem_reaPPum_y"])
        if ours:
            for i in range(int(bc["step_s"] / bc["controller_dt_s"])):
                now = t + i * bc["controller_dt_s"]
                inbox = {T.S_TEMPERATURE: tz, T.S_HUMIDITY: a["humidity_pct"], T.S_PM25: a["pm25_ugm3"],
                         T.S_HOOD_TEMPERATURE: tz, T.S_ILLUMINANCE: a["illuminance_lux"],
                         T.S_OCCUPANCY: occ, T.S_OCCUPANT_ZONE: "room" if occ else "none", T.S_DOOR_CONTACT: False,
                         T.S_WIFI_PRESENCE: occ, T.S_OUTDOOR_PM_GRADE: "good",
                         T.S_APPLIANCE_POWER: json.dumps({"boiler": round(p_hp, 1)}),
                         T.S_WEATHER: json.dumps({"raining": False, "sky": "clear", "outdoor_temp_c": to,
                                                  "outdoor_rh_pct": 100.0 * float(y["weatherStation_reaWeaRelHum_y"])}),
                         T.T_OCCUPANCY_BASIS: "LATCHED_OCCUPIED" if occ else "LATCHED_VACANT",
                         T.T_BOILER: json.dumps({"power": l0.power, "setpoint": l0.setpoint, "manual": False,
                                                 "l0_hold": l0.held})}
                inbox.update(ctrl_state)
                out = ctrl.step(now, inbox) or {}
                ctrl_state.update({tp: v for tp, v in out.items() if tp.startswith(f"{T.P}/state/")})
                if T.C_BOILER in out:
                    d = json.loads(out[T.C_BOILER])
                    want = {"power": bool(d.get("power", False)), "setpoint": float(d.get("setpoint", want["setpoint"]))}
                l0.apply(want["power"], want["setpoint"], now)
            sp = l0.setpoint if l0.power else bc["off_setpoint_c"]
            u = {"thermostatDayZon_oveTsetZon_u": sp + K0, "thermostatDayZon_oveTsetZon_activate": 1,
                 "thermostatNigZon_oveTsetZon_u": sp + K0, "thermostatNigZon_oveTsetZon_activate": 1}
        rows.append({"time_s": t, "qint_w": q, "zone_temp_c": tz, "night_temp_c": y["nigZon_reaTRooAir_y"] - K0, "outdoor_temp_c": to,
                     "occupied": occ, "p_hp_w": p_hp, "setpoint_c": (l0.setpoint if l0.power else bc["off_setpoint_c"]) if ours else None,
                     "events": ctrl_state.get(T.T_ACTIVE_EVENTS, "") if ours else ""})
        y = cli.post("/advance", u)
    return cli.get("/kpis"), pd.DataFrame(rows)


def main() -> None:
    hcfg = load_harness_config()
    bc = hcfg["boptest_heating"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--periods", default=",".join(bc["periods"]))
    ap.add_argument("--methods", default=",".join(bc["methods"]))
    ap.add_argument("--url", default=bc["url"])
    a = ap.parse_args()
    cli = Client(a.url)
    assert cli.get("/name")["name"] == bc["testcase"], "서버의 테스트 케이스가 설정과 다르다"
    out = REPO / bc["out_dir"]
    out.mkdir(parents=True, exist_ok=True)
    tab = REPO / "results" / "tables"
    tab.mkdir(parents=True, exist_ok=True)
    rows = []
    for period in a.periods.split(","):
        for method in a.methods.split(","):
            t0 = time.perf_counter()
            k, df = run(method, period, cli, hcfg, bc)
            df.to_csv(out / f"{period}_{method}.csv", index=False)
            occ = df[df.occupied]
            row = {"period": period, "method": method, **{kk: k.get(kk) for kk in sorted(k)},
                   "occ_temp_mean_c": float(occ.zone_temp_c.mean()), "occ_under_20_ratio": float((occ.zone_temp_c < 20.0).mean()),
                   "occ_ratio": float(df.occupied.mean()), "hp_kwh": float(df.p_hp_w.sum() * bc["step_s"] / 3.6e6),
                   "wall_s": time.perf_counter() - t0}
            rows.append(row)
            print(f"{period} · {method}: tdis {row.get('tdis_tot'):.1f} K·h · ener {row.get('ener_tot'):.3f} kWh/m² · "
                  f"히트펌프 {row['hp_kwh']:.1f} kWh · 재실 평균 {row['occ_temp_mean_c']:.2f} °C · 재실 비율 {row['occ_ratio']:.2f} · "
                  f"{row['wall_s']:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    kp = tab / "boptest_heating_kpis.csv"                # 다른 서버로 돌린 기간 결과와 합친다 (저장 직전에 다시 읽는다)
    if kp.exists():
        old = pd.read_csv(kp)
        old = old[~old.set_index(["period", "method"]).index.isin(df.set_index(["period", "method"]).index)]
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(kp, index=False)
    lines = ["# BOPTEST twozone_apartment_hydronic — 방식별 KPI (각 14일 · 난방 확장 트랙)", "",
             "| 기간 | 방식 | 열 불쾌 tdis [K·h] | 에너지 ener [kWh/m²] | 비용 cost | 히트펌프 [kWh] | 재실 평균 [°C] | 재실 < 20 °C |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for _, r in df.iterrows():
        lines.append(f"| {r.period} | {r.method} | {r.tdis_tot:.1f} | {r.ener_tot:.3f} | {r.cost_tot:.4f} | {r.hp_kwh:.1f} | "
                     f"{r.occ_temp_mean_c:.2f} | {r.occ_under_20_ratio * 100:.0f} % |")
    (tab / "boptest_heating_kpis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_manifest(out, {"kind": "boptest_heating", "periods": a.periods, "methods": a.methods, "url": a.url})
    print("\n".join(lines))


if __name__ == "__main__":
    main()
