"""토픽 발행 주기 측정 (W07 T7.5 DoD) — 계약 QoS 그대로 구독해 일정 시간 동안 메시지를 센다.

    tools/ros/run.sh node tools/ros/topic_rates.py [--seconds 10] [토픽 ...]   (기본: 주기 규정이 있는 센서 · 상태)
"""

from __future__ import annotations

import argparse
import time

import rclpy

from interfaces import ros_io
from interfaces import topics as T

DEFAULT = {T.S_TEMPERATURE: 10, T.S_HUMIDITY: 10, T.S_ILLUMINANCE: 10, T.S_OCCUPANCY: 10, T.S_PM25: 1,
           T.S_HOOD_TEMPERATURE: 1, T.S_APPLIANCE_POWER: 1, T.S_WINDOW_MOTOR_CURRENT: 50, T.T_WINDOW_POSITION_EST: 20}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("topics", nargs="*")
    a = ap.parse_args()
    topics = a.topics or list(DEFAULT)
    rclpy.init()
    node = rclpy.create_node("topic_rates")
    count = {tp: 0 for tp in topics}
    for tp in topics:
        ros_io.subscribe(node, tp, lambda t, _v: count.__setitem__(t, count[t] + 1))
    end = time.time() + 3.0                     # 발견 시간
    while time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.1)
    for tp in count:
        count[tp] = 0
    t0 = time.time()
    while time.time() - t0 < a.seconds:
        rclpy.spin_once(node, timeout_sec=0.01)
    el = time.time() - t0
    for tp in topics:
        hz = count[tp] / el
        want = DEFAULT.get(tp)
        mark = "" if want is None else ("✓" if abs(hz - want) <= 0.05 * want else "✗")
        print(f"{mark:1s} {tp:42s} {hz:7.2f} Hz" + (f" (규정 {want} Hz)" if want else ""), flush=True)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
