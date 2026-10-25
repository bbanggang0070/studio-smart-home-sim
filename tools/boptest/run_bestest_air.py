"""BOPTEST BESTEST Air 에서 우리 제어기 비교 (docs/11 필수 조치 5) — 외부 Modelica 에뮬레이터로 순위를 다시 본다.

    tools/boptest/run_server.sh                      # BOPTEST 테스트 케이스 서버 (도커)
    uv run python tools/boptest/run_bestest_air.py [--periods typical_cool_day] [--methods proposed]
        → results/boptest/<기간>_<방식>.csv (시계열) · results/tables/boptest_kpis.csv · .md

방식: boptest_baseline (테스트 케이스 내장 제어 — 덮어쓰기 없음) · A · B · proposed (우리 제어기 코드 그대로 · 장치 = 에어컨만).
지표: BOPTEST 표준 KPI (tdis_tot 열 불쾌 K·h · ener_tot kWh/m² · cost_tot · pele_tot …) + 재실 중 실내 온도 분포.
열 불쾌는 테스트 케이스 쾌적 범위(재실 21–24 °C)로 계산된다 — 우리 목표(냉방 26–27 °C)와 다르다는 점을 함께 적는다.
설정: config/harness.yaml boptest
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from actuators.l0_protect import CompressorGuard  # noqa: E402
from controller.params import load_params  # noqa: E402
from harness.controllers import make_controller  # noqa: E402
from harness.runner import load_harness_config  # noqa: E402
from interfaces import topics as T  # noqa: E402
from sensors.power_monitor import PowerMonitor  # noqa: E402

K0 = 273.15


class Client:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def _call(self, method: str, p: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url + p, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.load(r)
        if d.get("status", 200) != 200:
            raise RuntimeError(d.get("message"))
        return d["payload"]

    def get(self, p):
        return self._call("GET", p)

    def put(self, p, b):
        return self._call("PUT", p, b)

    def post(self, p, b):
        return self._call("POST", p, b)


def make_ours(method: str, hcfg: dict, bc: dict):
    spec = hcfg["controllers"][method]
    ctrl = make_controller(spec)
    sc = {"initial": {"appliances": {"ac": {"power": method == "A"}}}, "baseline_a": bc["baseline_a"]}
    ctrl.reset({"scenario": sc, "baseline": method, "seed": 0, "rng": np.random.default_rng(0)})
    if hasattr(ctrl, "rules"):                                       # 장치 목록 = 이 건물에 있는 것 (X8 과 같은 방식)
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
    pmon = PowerMonitor(th["power_monitor"], th["events"]["appliance_no_response"]["power_confirm_s"])
    ac = {"power": False, "mode": "cool", "setpoint": 26.0}      # 실제 에어컨 상태 (L0 보호 뒤)
    want = dict(ac)                                               # 제어기 명령
    a_ac = th["appliances"]["ac"]
    l0 = CompressorGuard(a_ac["compressor_min_off_s"], a_ac["compressor_min_on_s"])   # 가전 브릿지와 같은 L0 (2026-10-24)
    ctrl_state: dict = {}
    u: dict = {}
    rows = []
    a = bc["assumed"]
    h0, h1 = bc["occupied_hours"]
    t_start = float(y["time"])
    end = t_start + 14 * 86400.0
    while float(y["time"]) < end - 1e-6:
        t = float(y["time"])
        tod = t % 86400.0
        occ = h0 <= tod / 3600.0 < h1
        to, tz = y["zon_weaSta_reaWeaTDryBul_y"] - K0, y["zon_reaTRooAir_y"] - K0
        p_ac = float(y["fcu_reaPCoo_y"]) + (float(y["fcu_reaPFan_y"]) if ac["power"] else 0.0)
        if ours:
            for i in range(int(bc["step_s"] / bc["controller_dt_s"])):
                now = t + i * bc["controller_dt_s"]
                # 계량 플러그 = 명령에 바로 반응하는 실제 에어컨 — 켜짐: max(BOPTEST 냉방 · 팬 전력, 실내기 팬) · 꺼짐: 0.
                # BOPTEST 전력은 step_s(60 s) 마다만 바뀌어, 그대로 넘기면 켜고 끈 직후 최대 60 s 동안 명령과 다르게 보이고
                # E9(확인 10 s + 이동평균 10 s · 재송신 2회)가 한 스텝 안에 무응답으로 확정한다 (2026-10-24 — 켤 때 · 끌 때 모두).
                # 냉방 효과 · 에너지 KPI 는 BOPTEST 값 그대로다 (플러그 값은 제어기의 가전 확인에만 쓴다)
                p_now = max(p_ac, bc["ac_indoor_fan_w"]) if ac["power"] else 0.0
                inbox = {T.S_TEMPERATURE: tz, T.S_HUMIDITY: a["humidity_pct"], T.S_PM25: a["pm25_ugm3"],
                         T.S_HOOD_TEMPERATURE: tz, T.S_ILLUMINANCE: a["illuminance_lux"],
                         T.S_OCCUPANCY: occ, T.S_OCCUPANT_ZONE: "desk" if occ else "none", T.S_DOOR_CONTACT: False,
                         T.S_WIFI_PRESENCE: occ, T.S_OUTDOOR_PM_GRADE: "good",
                         T.S_APPLIANCE_POWER: json.dumps({"ac": round(p_now, 1)}),
                         T.S_WEATHER: json.dumps({"raining": False, "sky": "clear", "outdoor_temp_c": to,
                                                  "outdoor_rh_pct": 100.0 * float(y["zon_weaSta_reaWeaRelHum_y"])}),
                         T.T_OCCUPANCY_BASIS: "LATCHED_OCCUPIED" if occ else "LATCHED_VACANT",
                         T.T_APPLIANCE_STATES: json.dumps(pmon.update(now, {"ac": p_now})),
                         T.T_AC: json.dumps({**ac, "confidence": "CONFIRMED", "l0_hold": l0.held})}
                inbox.update(ctrl_state)
                # 제어기 시각은 계속 증가해야 한다 (하루 중 시각은 제어기가 % 86400 으로 구한다 — 고속 하네스와 같다).
                # 하루 중 시각을 넘기면 자정마다 0 으로 돌아가 이력 정리 · 타이머가 깨진다 (2026-10-24 수정)
                out = ctrl.step(now, inbox) or {}
                ctrl_state.update({tp: v for tp, v in out.items() if tp.startswith(f"{T.P}/state/")})
                if T.C_AC in out:
                    d = json.loads(out[T.C_AC]) if isinstance(out[T.C_AC], str) else dict(out[T.C_AC])
                    new = {"power": bool(d.get("power", False)), "mode": str(d.get("mode", "cool")),
                           "setpoint": float(d.get("setpoint", want["setpoint"]))}
                    if new != want:
                        pmon.note_command("ac", now)
                    want = new
                # L0 압축기 최소 ON/OFF — 고속 하네스 · 물리 모드 브릿지와 같다 (보류되면 직전 전원 상태 유지)
                ac = {**want, "power": l0.apply(want["power"], now)}
            cool_on = ac["power"] and ac["mode"] in ("cool", "dry", "auto")
            u = {"con_oveTSetCoo_u": (ac["setpoint"] + K0) if cool_on else bc["ac_off_setpoint_k"],
                 "con_oveTSetCoo_activate": 1}
        rows.append({"time_s": t, "zone_temp_c": tz, "outdoor_temp_c": to, "occupied": occ,
                     "p_cool_w": float(y["fcu_reaPCoo_y"]), "p_fan_w": float(y["fcu_reaPFan_y"]),
                     "p_heat_w": float(y["fcu_reaPHea_y"]), "ac_power": ac["power"] if ours else None,
                     "ac_setpoint_c": ac["setpoint"] if ours else None,
                     "events": ctrl_state.get(T.T_ACTIVE_EVENTS, "") if ours else ""})
        y = cli.post("/advance", u)
    k = cli.get("/kpis")
    return k, pd.DataFrame(rows)


def main() -> None:
    hcfg = load_harness_config()
    bc = hcfg["boptest"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--periods", default=",".join(bc["periods"]))
    ap.add_argument("--methods", default=",".join(bc["methods"]))
    ap.add_argument("--url", default=bc["url"])          # 서버를 여러 개 띄워 기간을 나눠 돌릴 때 (run_server.sh <케이스> <포트>)
    a = ap.parse_args()
    cli = Client(a.url)
    assert cli.get("/name")["name"] == bc["testcase"], "서버의 테스트 케이스가 설정과 다르다"
    out = REPO / bc["out_dir"]
    out.mkdir(parents=True, exist_ok=True)
    tab = REPO / "results" / "tables"
    rows = []
    kp = tab / "boptest_kpis.csv"
    for period in a.periods.split(","):
        for method in a.methods.split(","):
            t0 = time.perf_counter()
            k, df = run(method, period, cli, hcfg, bc)
            df.to_csv(out / f"{period}_{method}.csv", index=False)
            occ = df[df.occupied]
            row = {"period": period, "method": method, **{kk: k.get(kk) for kk in sorted(k)},
                   "occ_temp_mean_c": float(occ.zone_temp_c.mean()), "occ_temp_p95_c": float(occ.zone_temp_c.quantile(0.95)),
                   "occ_over_26_ratio": float((occ.zone_temp_c > 26.0).mean()), "occ_over_28_ratio": float((occ.zone_temp_c > 28.0).mean()),
                   "cool_kwh": float((df.p_cool_w + df.p_fan_w).sum() * bc["step_s"] / 3.6e6), "wall_s": time.perf_counter() - t0}
            rows.append(row)
            print(f"{period} · {method}: tdis {row.get('tdis_tot'):.1f} K·h · ener {row.get('ener_tot'):.3f} kWh/m² · "
                  f"냉방 {row['cool_kwh']:.1f} kWh · 재실 평균 {row['occ_temp_mean_c']:.2f} °C · {row['wall_s']:.0f}s", flush=True)
    new = pd.DataFrame(rows)
    old = pd.read_csv(kp) if kp.exists() else pd.DataFrame()   # 저장 직전에 다시 읽는다 — 다른 서버로 돌린 기간 결과와 합친다
    if not old.empty:
        old = old[~old.set_index(["period", "method"]).index.isin(new.set_index(["period", "method"]).index)]
    allk = pd.concat([old, new], ignore_index=True)
    allk.to_csv(kp, index=False)
    lines = ["# BOPTEST BESTEST Air — 방식별 KPI (각 14일)", "",
             "| 기간 | 방식 | 열 불쾌 tdis [K·h] | 에너지 ener [kWh/m²] | 냉방 전력량 [kWh] | 재실 평균 [°C] | 재실 > 26 °C | 재실 > 28 °C |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for _, r in allk.iterrows():
        lines.append(f"| {r.period} | {r.method} | {r.tdis_tot:.1f} | {r.ener_tot:.3f} | {r.cool_kwh:.1f} | "
                     f"{r.occ_temp_mean_c:.2f} | {r.occ_over_26_ratio * 100:.0f} % | {r.occ_over_28_ratio * 100:.0f} % |")
    (tab / "boptest_kpis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
