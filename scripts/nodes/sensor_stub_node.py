"""센서 스텁 — W07 센서 노드가 생기기 전까지 폐루프 연결을 확인하려고 고정값을 발행한다 (시험 전용).

    tools/ros/run.sh node scripts/nodes/sensor_stub_node.py [--temp 29] [--mode STUDY]
"""

from __future__ import annotations

import argparse
import json

import rclpy

from interfaces import ros_io
from interfaces import topics as T


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--temp", type=float, default=24.0)
    ap.add_argument("--rh", type=float, default=50.0)
    ap.add_argument("--lux", type=float, default=50.0)
    ap.add_argument("--mode", default="NORMAL")
    ap.add_argument("--zone", default="desk")
    args, _ = ap.parse_known_args()
    vals = {
        T.S_ILLUMINANCE: args.lux, T.S_TEMPERATURE: args.temp, T.S_HUMIDITY: args.rh, T.S_OCCUPANCY: True,
        T.S_OCCUPANT_ZONE: args.zone, T.S_OUTDOOR_PM_GRADE: "good", T.S_PM25: 10.0, T.S_WIFI_PRESENCE: True,
        T.S_DOOR_CONTACT: False, T.S_HOOD_TEMPERATURE: args.temp, T.S_APPLIANCE_POWER: json.dumps({}),
        T.S_WEATHER: json.dumps({"raining": False, "outdoor_temp_c": args.temp - 2, "outdoor_rh_pct": 55.0}),
        T.C_MODE: args.mode, T.C_ACTIVITY: "",
    }
    rclpy.init()
    node = rclpy.create_node("sensor_stub")
    pubs = {tp: ros_io.publisher(node, tp) for tp in vals}
    node.create_timer(0.1, lambda: [ros_io.publish(pubs[tp], tp, v) for tp, v in vals.items()])
    node.get_logger().info(f"센서 스텁 — {len(vals)}개 토픽 · 10 Hz (W07 전까지 시험 전용)")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
