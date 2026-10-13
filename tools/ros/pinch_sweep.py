"""센서리스 토크 스윕 · 물체 강성 민감도 (W12 T12.3 · T12.4) — 브릿지 + window_safety_node 가 떠 있을 때.

    tools/ros/run.sh node tools/ros/pinch_sweep.py --torque 55 --objects rigid_pot,soft_cushion,elastic_sponge --trials 10

시행마다: 창 50 % → 물체 배치(닫힘 경로) → 닫기 → 감지 · 최대 접촉력 · 감지/정지 지연 기록 → 물체 치움 → SAFETY_HOLD 해제 대기
→ 끝까지 닫아 '그 자리 반복 기록'을 지운다 (다음 시행이 잠김으로 오염되지 않게) → 다시 연다
결과: results/sweep/pinch_sweep.csv 에 한 줄씩 덧붙인다
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import rclpy
from std_msgs.msg import String

from controller.params import load_params
from interfaces import ros_io
from interfaces import topics as T

REPO = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--torque", type=float, required=True, help="기록용 — 안전 노드에 준 주행 끝 토크 %")
    ap.add_argument("--objects", default="rigid_pot,soft_cushion,elastic_sponge")
    ap.add_argument("--trials", type=int, default=10)
    args = ap.parse_args()
    p = load_params()
    hold_s = p.get("window_sensorless.layered_safety.safety_hold_s")
    fmax = p.get("window_sensorless.pinch_detection.max_contact_force_n")
    rclpy.init()
    node = rclpy.create_node("pinch_sweep")
    st: dict = {"local": {}}
    for tp in (T.T_WINDOW_OPEN_RATIO, T.T_SAFETY_STATE, T.T_PINCH_DETECTED):
        ros_io.subscribe(node, tp, lambda tp_, v: st.__setitem__(tp_, v))
    qos = ros_io.qos(T.C_WINDOW_OPEN_RATIO)
    node.create_subscription(String, T.I_WINDOW_LOCAL, lambda m: st.__setitem__("local", json.loads(m.data)), qos)
    win = ros_io.publisher(node, T.C_WINDOW_OPEN_RATIO)
    obstacle = node.create_publisher(String, T.I_SIM_OBSTACLE, qos)

    def spin(sec, probe=None):
        end = time.perf_counter() + sec
        while time.perf_counter() < end:
            rclpy.spin_once(node, timeout_sec=0.01)
            if probe:
                probe()

    out = REPO / "results" / "sweep"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "pinch_sweep.csv"
    new = not path.exists()
    f = open(path, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=["torque_pct", "object", "trial", "detected", "upper_seen", "contact_peak_n",
                                      "detect_ms", "stop_ms", "stop_mm", "pass"])
    if new:
        w.writeheader()
    spin(8.0)
    for obj in args.objects.split(","):
        for k in range(1, args.trials + 1):
            obstacle.publish(String(data="park"))
            ros_io.publish(win, T.C_WINDOW_OPEN_RATIO, 0.5)
            spin(13.0)
            obstacle.publish(String(data=obj))
            spin(1.5)
            ros_io.publish(win, T.C_WINDOW_OPEN_RATIO, 0.0)
            seen = {"pinch": False, "upper": False, "q": None}

            def probe():
                if st.get(T.T_PINCH_DETECTED) and not seen["pinch"]:
                    seen["pinch"], seen["q"] = True, st.get(T.T_WINDOW_OPEN_RATIO)
                if str(st.get(T.T_SAFETY_STATE, "")).find("PINCH_REVERSE") >= 0 or "SAFETY_HOLD" in str(st.get(T.T_SAFETY_STATE, "")):
                    seen["upper"] = True
            spin(14.0, probe)
            loc = st["local"]
            peak = float(loc.get("contact_peak_n") or 0.0)
            row = {"torque_pct": args.torque, "object": obj, "trial": k, "detected": int(seen["pinch"]), "upper_seen": int(seen["upper"]),
                   "contact_peak_n": round(peak, 1), "detect_ms": loc.get("detect_ms"), "stop_ms": loc.get("stop_ms"),
                   "stop_mm": round(seen["q"] * 700.0, 1) if seen["q"] is not None else None,
                   "pass": int(seen["pinch"] and peak <= fmax)}
            w.writerow(row)
            f.flush()
            print(f"토크 {args.torque:g} % · {obj} · {k}/{args.trials} → 감지 {row['detected']} · 접촉 {row['contact_peak_n']} N · "
                  f"정지 {row['stop_ms']} ms", flush=True)
            obstacle.publish(String(data="park"))
            spin(hold_s + 2.0)                                   # SAFETY_HOLD 해제
            ros_io.publish(win, T.C_WINDOW_OPEN_RATIO, 0.0)        # 물체 없이 끝까지 닫기 → 그 자리 반복 기록 삭제
            spin(14.0)
    f.close()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
