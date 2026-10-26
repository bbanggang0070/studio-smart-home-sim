"""재실 판정 노드 (W07 T7.3 · T7.3b · T7.d1 · T7.d2 · T7.w1 · T7.w2) — 문 이벤트 + 판정 창 3분 (호텔 로직) · 폴백 융합.

    tools/ros/run.sh node scripts/nodes/occupancy_sensor_node.py [--door-from-truth]

  판정 코어는 고속 모드와 같다 (sensors/occupancy.py OccupancyJudge). mmWave 구간 에너지 · 휴대폰 Wi-Fi 는
  사람 참값(월드 노드)에서 합성한다 (harness/sensing.py — 레이더 · 공유기 시뮬레이션).
  문 접점은 Isaac 문 조인트 각도에서 나온 /studio/sensor/door_contact 를 쓴다 (--door-from-truth: Isaac 없이 시험할 때 참값)
  발행  sensor/{occupancy 10 Hz, occupant_zone 변경 시, wifi_presence 변경 시 + 1 Hz} · state/occupancy_basis
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rclpy
import yaml
from std_msgs.msg import String

from controller.params import load_params
from harness.sensing import PersonTruth, SensingWorld
from interfaces import ros_io
from interfaces import topics as T
from sensors.occupancy import OccupancyJudge

REPO = Path(__file__).resolve().parents[2]
ENV_TRUTH = f"{T.P}/internal/env_truth"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--door-from-truth", action="store_true")
    ap.add_argument("--seed-offset", type=int, default=0)   # 물리 조건 무작위화 — 반복마다 다른 레이더 · Wi-Fi 잡음
    args, _ = ap.parse_known_args()
    hcfg = yaml.safe_load((REPO / "config" / "harness.yaml").read_text(encoding="utf-8"))
    seed = yaml.safe_load((REPO / "config" / "sensor_models.yaml").read_text(encoding="utf-8"))["seed"]
    occ_params = load_params().th["occupancy"]
    rclpy.init()
    node = rclpy.create_node("occupancy_sensor")
    log = node.get_logger()
    st: dict = {"truth": None, "door": False, "power": {}, "sensing": None, "out": None, "wifi": None}

    def on_truth(m):
        tr = json.loads(m.data)
        p = tr["person"]
        if st["sensing"] is None:                    # 첫 참값으로 시작 상태를 맞춘다
            st["sensing"] = SensingWorld(cfg=hcfg["mmwave"], rng=np.random.default_rng(seed + 7919 + 1000 * args.seed_offset),
                                         judge=OccupancyJudge(occ_params, p["present"], tr["t"]),
                                         person=PersonTruth(p["present"], p["zone"], p["motion"]))
        sw = st["sensing"]
        pt = sw.person
        pt.present, pt.motion = p["present"], p["motion"]
        pt.zone = "none" if "radar" in tr["faults"] else p["zone"]
        pt.arrived_at = p["arrived_at"]
        pt.phone_with_person, pt.left_phone_home = p["phone"] == "person", p["phone"] == "home"
        sw.judge.mmwave_lost = "mmwave_lost" in tr["faults"]
        extra_m = {int(c.get("gate", 4)): float(c.get("moving_energy", 35.0)) for c in p["curtain"]}
        extra_s = {int(c.get("gate", 6)): float(c.get("static_energy", 45.0)) for c in p["neighbor"]}
        door = tr["door_open"] if args.door_from_truth else st["door"]
        out, wifi, _ = sw.step(tr["t"], door, p["wifi_doze"], st["power"], extra_m, extra_s)
        for a in out.alerts:
            log.warn(f"재실 판정: {a}")
        if st["out"] is None or out.zone != st["out"].zone:
            ros_io.publish(pubs[T.S_OCCUPANT_ZONE], T.S_OCCUPANT_ZONE, out.zone)
        if wifi != st["wifi"]:
            ros_io.publish(pubs[T.S_WIFI_PRESENCE], T.S_WIFI_PRESENCE, wifi)
        st["out"], st["wifi"] = out, wifi

    def on_power(_, v):
        st["power"] = {k: float(x) for k, x in json.loads(v).items()}

    node.create_subscription(String, ENV_TRUTH, on_truth, ros_io.qos(T.C_MODE))
    ros_io.subscribe(node, T.S_DOOR_CONTACT, lambda _, v: st.update(door=bool(v)))
    ros_io.subscribe(node, T.S_APPLIANCE_POWER, on_power)
    pubs = {tp: ros_io.publisher(node, tp) for tp in (T.S_OCCUPANCY, T.S_OCCUPANT_ZONE, T.S_WIFI_PRESENCE,
                                                      T.T_OCCUPANCY_BASIS)}

    def fast():
        o = st["out"]
        if o is None:
            return
        ros_io.publish(pubs[T.S_OCCUPANCY], T.S_OCCUPANCY, o.occupied)
        ros_io.publish(pubs[T.T_OCCUPANCY_BASIS], T.T_OCCUPANCY_BASIS, o.basis)

    def slow():
        if st["out"] is not None:
            ros_io.publish(pubs[T.S_OCCUPANT_ZONE], T.S_OCCUPANT_ZONE, st["out"].zone)
            ros_io.publish(pubs[T.S_WIFI_PRESENCE], T.S_WIFI_PRESENCE, st["wifi"])

    node.create_timer(0.1, fast)
    node.create_timer(1.0, slow)
    log.info("재실 판정 노드 시작 — 문 이벤트 + 판정 창 · 폴백 융합 (문 접점: "
             + ("참값" if args.door_from_truth else "Isaac /studio/sensor/door_contact") + ")")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
