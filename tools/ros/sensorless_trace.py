"""센서리스 파형 기록 (W13 T13.6) — 정상 닫힘 1회 + 끼임 닫힘 1회 동안 전류 · 리플 추정 위치 · 실제 위치 · Zone · 안전 상태를 받은 그대로 기록.

    (터미널 1) tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py --duration 200
    (터미널 2) tools/ros/run.sh node scripts/nodes/window_safety_node.py
    (터미널 3) tools/ros/run.sh node tools/ros/sensorless_trace.py [물체=rigid_pot]
결과: results/sensorless/trace.csv (t_s · phase · topic · value) — tools/analysis/plot_sensorless.py 가 그린다
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import rclpy
from std_msgs.msg import String

from interfaces import ros_io
from interfaces import topics as T

REPO = Path(__file__).resolve().parents[2]
TOPICS = (T.S_WINDOW_MOTOR_CURRENT, T.T_WINDOW_POSITION_EST, T.T_WINDOW_OPEN_RATIO, T.T_WINDOW_ZONE,
          T.T_SAFETY_STATE, T.T_PINCH_DETECTED)


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "rigid_pot"
    rclpy.init()
    node = rclpy.create_node("sensorless_trace")
    rows: list[tuple] = []
    t0 = time.perf_counter()
    phase = {"now": "wait"}

    def on(tp, v):
        rows.append((round(time.perf_counter() - t0, 4), phase["now"], tp, v))

    for tp in TOPICS:
        ros_io.subscribe(node, tp, on)
    node.create_subscription(String, T.I_WINDOW_LOCAL, lambda m: on("local.contact_peak_n", json.loads(m.data).get("contact_peak_n")),
                             ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    pub = ros_io.publisher(node, T.C_WINDOW_OPEN_RATIO)
    obstacle = node.create_publisher(String, T.I_SIM_OBSTACLE, ros_io.qos(T.C_WINDOW_OPEN_RATIO))

    def spin(sec):
        end = time.perf_counter() + sec
        while time.perf_counter() < end:
            rclpy.spin_once(node, timeout_sec=0.005)

    def step(label, msg=None, goal=None, sec=0.0):
        phase["now"] = label
        on("cmd", f"{label} · 물체 {msg}" if msg else label)
        if msg is not None:
            obstacle.publish(String(data=msg))
        if goal is not None:
            ros_io.publish(pub, T.C_WINDOW_OPEN_RATIO, goal)
        print(f"{time.perf_counter() - t0:7.1f} s  {label}", flush=True)
        spin(sec)

    spin(8.0)
    step("open", msg="park", goal=0.5, sec=14.0)          # 처음 50 % 로
    step("normal_close", goal=0.0, sec=16.0)              # ① 정상 닫힘 — 엔드존 · 씰 압착 포함
    step("reopen", goal=0.5, sec=14.0)
    step("place", msg=name, sec=1.5)
    step("pinch_close", goal=0.0, sec=40.0)               # ② 끼임 닫힘 — 검출 → 반전 → 정지 유지 (SAFETY_HOLD 30 s)
    out = REPO / "results" / "sensorless"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "trace.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "phase", "topic", "value"])
        w.writerows(rows)
    print(f"저장: results/sensorless/trace.csv ({len(rows)}행)", flush=True)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
