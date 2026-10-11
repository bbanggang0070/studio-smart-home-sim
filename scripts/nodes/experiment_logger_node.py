"""실험 로거 (W08 T8.7) — 계약 55개 토픽 + 참값(CO₂ 등)을 시뮬레이션 1 s 마다 CSV 로 남긴다.

    tools/ros/run.sh node scripts/nodes/experiment_logger_node.py --scenario B3 [--baseline proposed] [--rep 1]

  열 이름은 고속 모드 로그(harness/runner.py)와 같다 — truth.* · energy_wh.* · act.* · ext.* · 토픽 이름 그대로
  → scripts/physics_eval.py 가 같은 판정기(pass_criteria · 지표)로 채점한다.
  행은 월드 노드의 참값 메시지(시뮬레이션 1 s)마다 하나. 참값이 15 s 넘게 끊기면 파일을 닫고 끝낸다.
  결과: results/physics/raw/<시나리오>_<기준선>_<반복>.csv (커밋하지 않는다)
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import rclpy
from std_msgs.msg import String

from interfaces import ros_io
from interfaces import topics as T

REPO = Path(__file__).resolve().parents[2]
ENV_TRUTH = f"{T.P}/internal/env_truth"
ACT = {T.T_WINDOW_OPEN_RATIO: "window_open_ratio", T.T_BLIND_ANGLE: "blind_angle_deg", T.T_FAN_RPM: "exhaust_fan_rpm",
       T.T_INTAKE_FAN_RPM: "intake_fan_rpm", T.T_RANGE_HOOD_LEVEL: "range_hood_level",
       T.T_PURIFIER_LEVEL: "purifier_level", T.T_DEHUMIDIFIER: "dehumidifier", T.T_HUMIDIFIER: "humidifier",
       T.T_CEILING_FAN: "ceiling_fan", T.T_CEILING_LIGHT: "ceiling_light_pct", T.T_DESK_LIGHT: "desk_light_pct"}


def flatten(prefix: str, d: dict, row: dict) -> None:
    for k, v in d.items():
        if isinstance(v, dict):
            flatten(f"{prefix}{k}.", v, row)
        else:
            row[f"{prefix}{k}"] = v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--baseline", default="proposed")
    ap.add_argument("--rep", type=int, default=1)
    args, _ = ap.parse_known_args()
    out = REPO / "results" / "physics" / "raw" / f"{args.scenario}_{args.baseline}_{args.rep}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    rclpy.init()
    node = rclpy.create_node("experiment_logger")
    log = node.get_logger()
    last: dict = {}
    st = {"writer": None, "fh": None, "fields": None, "rows": 0, "t_last": time.monotonic()}

    for tp in T.ALL_TOPICS:
        ros_io.subscribe(node, tp, lambda t, v: last.__setitem__(t, v))

    def on_truth(m):
        tr = json.loads(m.data)
        st["t_last"] = time.monotonic()
        if st.get("last_t") is not None and tr["t"] <= st["last_t"]:
            return                                                # 월드 노드 준비 대기 중 반복되는 t = 0 — 한 번만 쓴다
        st["last_t"] = tr["t"]
        row: dict = {"time_s": tr["t"]}
        obs = dict(tr["obs"])
        energy = obs.pop("energy_wh", {})
        power = obs.pop("appliance_power_w", {})
        obs.pop("time_s", None)
        flatten("truth.", obs, row)
        flatten("energy_wh.", energy, row)
        for tp, name in ACT.items():
            if tp in last:
                row[f"act.{name}"] = last[tp]
        if T.T_AC in last:
            a = json.loads(last[T.T_AC])
            row["act.ac"] = last[T.T_AC]
            row["act.ac_power"] = bool(a.get("power"))
            row["act.ac_cool"] = bool(a.get("power")) and a.get("mode") == "cool"
            row["act.ac_dry"] = bool(a.get("power")) and a.get("mode") == "dry"
            row["act.ac_setpoint"] = a.get("setpoint")
            row["act.ac_fan"] = a.get("fan")
        if T.C_AC in last:
            row["cmd.ac_power"] = bool(json.loads(last[T.C_AC]).get("power"))
        row["act.cooktop_power"] = last.get(T.C_COOKTOP_POWER, True)
        row["act.desk_cct"] = last.get(T.C_DESK_LIGHT_CCT)
        if T.T_APPLIANCE_STATES in last:
            ac = json.loads(last[T.T_APPLIANCE_STATES]).get("ac", {})
            row["pm.ac.state"], row["pm.ac.source"] = ac.get("state", ""), ac.get("source", "")
            row["pm.ac.run"], row["pm.ac.fan_only"] = ac.get("state") == "run", ac.get("state") == "fan_only"
            row["pm.ac.manual"] = ac.get("source") == "manual"
        row["power.ac_w"] = power.get("ac", 0.0)
        if T.S_APPLIANCE_POWER in last:
            row["power.total_w"] = sum(float(v) for v in json.loads(last[T.S_APPLIANCE_POWER]).values())
        row["truth.occupied"] = tr["occupied_truth"]
        row["truth.door_open"] = tr["door_open"]
        for k, v in tr["ext"].items():
            row[f"ext.{k}"] = v
        row["injections"] = tr["injections"]
        for tp in T.ALL_TOPICS:
            if tp in last:
                row[tp] = last[tp]
        if st["writer"] is None:                                  # 열 = 첫 행 + 계약 55개 토픽 (늦게 오는 토픽도 자리를 둔다)
            fields = list(row) + [tp for tp in T.ALL_TOPICS if tp not in row]
            st["fh"] = open(out, "w", newline="", encoding="utf-8")
            st["writer"] = csv.DictWriter(st["fh"], fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            st["writer"].writeheader()
            log.info(f"기록 시작 → {out.relative_to(REPO)} ({len(fields)}열)")
        st["writer"].writerow(row)
        st["rows"] += 1
        if st["rows"] % 60 == 0:
            st["fh"].flush()

    node.create_subscription(String, ENV_TRUTH, on_truth, ros_io.qos(T.C_MODE))

    def watchdog():
        if st["writer"] is not None and time.monotonic() - st["t_last"] > 15.0:
            log.info(f"참값이 끊김 — 기록 종료 ({st['rows']}행)")
            raise SystemExit

    node.create_timer(1.0, watchdog)
    log.info(f"실험 로거 시작 — {args.scenario} · {args.baseline} · 반복 {args.rep}")
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    if st["fh"]:
        st["fh"].close()
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
