"""끼임 1회 재현 (디버그) — 브릿지 + window_safety_node 가 떠 있을 때. 창 50 % → 물체 → 닫기 → 상태 · 위치 추적 출력.

    tools/ros/run.sh node tools/ros/pinch_once.py [물체=rigid_pot] [닫기 목표 비율=0.0]
"""

from __future__ import annotations

import json
import sys
import time

import rclpy
from std_msgs.msg import String

from interfaces import ros_io
from interfaces import topics as T


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "rigid_pot"
    goal = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0                # 0.0 닫기 · 1.0 열기 (여는 방향 끼임은 'rigid_pot@1.03:30')
    rclpy.init()
    node = rclpy.create_node("pinch_once")
    st: dict = {}
    for tp in (T.T_WINDOW_OPEN_RATIO, T.T_SAFETY_STATE, T.T_PINCH_DETECTED):
        ros_io.subscribe(node, tp, lambda tp_, v: st.__setitem__(tp_, v))
    pub = ros_io.publisher(node, T.C_WINDOW_OPEN_RATIO)
    node.create_subscription(String, T.I_WINDOW_LOCAL, lambda m: st.__setitem__("local", json.loads(m.data)),
                             ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    obstacle = node.create_publisher(String, T.I_SIM_OBSTACLE, ros_io.qos(T.C_WINDOW_OPEN_RATIO))

    def spin(sec, every=None):
        end, nxt = time.perf_counter() + sec, 0.0
        while time.perf_counter() < end:
            rclpy.spin_once(node, timeout_sec=0.01)
            if every and time.perf_counter() >= nxt:
                nxt = time.perf_counter() + every
                print(f"  위치 {st.get(T.T_WINDOW_OPEN_RATIO, -1) * 700:6.1f} mm · 안전 {st.get(T.T_SAFETY_STATE)} · "
                      f"끼임 {st.get(T.T_PINCH_DETECTED)} · 접촉 최대 {st.get('local', {}).get('contact_peak_n')} N · "
                      f"정지 {st.get('local', {}).get('stop_ms')} ms", flush=True)

    spin(10.0)
    obstacle.publish(String(data="park"))
    ros_io.publish(pub, T.C_WINDOW_OPEN_RATIO, 0.5 if goal < 0.5 else 0.0)
    spin(12.0)
    obstacle.publish(String(data=name))
    spin(1.5)
    print(f"창문 목표 → {goal}", flush=True)
    ros_io.publish(pub, T.C_WINDOW_OPEN_RATIO, goal)
    spin(12.0, every=0.5)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
