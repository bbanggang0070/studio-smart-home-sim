"""발표 영상용 — 명령 토픽을 정해진 시각에 차례로 보낸다 (브릿지가 --record 로 녹화 중일 때).

    tools/ros/run.sh node tools/ros/demo_cmds.py "0:blind_angle=0" "4:blind_angle=75" "12:window_open_ratio=0.6"
    시각[s]:토픽(/studio/cmd/ 뒤 이름)=값
"""

from __future__ import annotations

import sys
import time

import rclpy

from interfaces import ros_io
from interfaces import topics as T


def main() -> None:
    steps = []
    for a in sys.argv[1:]:
        t, _, rest = a.partition(":")
        name, _, v = rest.partition("=")
        steps.append((float(t), f"{T.P}/cmd/{name}", float(v)))
    rclpy.init()
    node = rclpy.create_node("demo_cmds")
    pubs = {tp: ros_io.publisher(node, tp) for _, tp, _ in steps}
    t0 = time.perf_counter()
    for t, tp, v in sorted(steps):
        while time.perf_counter() - t0 < t:
            rclpy.spin_once(node, timeout_sec=0.02)
        ros_io.publish(pubs[tp], tp, int(v) if T.TYPES.get(tp) == T.I8 else v)
        print(f"{t:5.1f} s  {tp} = {v:g}", flush=True)
    end = time.perf_counter() + 2.0
    while time.perf_counter() < end:
        rclpy.spin_once(node, timeout_sec=0.05)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
