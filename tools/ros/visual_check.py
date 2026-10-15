"""가전 · 창문 표시 검증 (Scene v0.3) — 브릿지만 떠 있을 때 상태 토픽을 차례로 보내 표시등 · 루버 · 분무 · 화구 · 안전 LED 변화를 녹화한다.

    tools/record_visual_check.sh   (브릿지 기동 · 녹화 · 이 스크립트 실행을 카메라 4곳에 대해 차례로)
    또는 (터미널 1) tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py --duration 90 \
                 --record results/media/visual_check/<cam> --record-camera <cam> --record-fps 2 --record-ambient 150
    (터미널 2) tools/ros/run.sh node tools/ros/visual_check.py
단계마다 3 s · 같은 값은 1 s 마다 다시 보낸다 (브릿지 표시는 값이 바뀔 때만 갱신 — 렌더 프레임과 대조하기 쉽게)
"""

from __future__ import annotations

import json
import time

import rclpy

from interfaces import ros_io
from interfaces import topics as T

AC = lambda power, mode="cool": json.dumps({"power": power, "mode": mode, "setpoint": 26.0, "fan": "auto"})   # noqa: E731
STEPS = [                                   # (라벨, {토픽: 값})
    ("모두 끔", {T.T_AC: AC(False), T.T_DEHUMIDIFIER: False, T.T_HUMIDIFIER: False, T.T_PURIFIER_LEVEL: 0,
                 T.T_RANGE_HOOD_LEVEL: 0, T.S_APPLIANCE_POWER: json.dumps({"cooktop": 0.0}), T.T_SAFETY_STATE: "NORMAL"}),
    ("에어컨 냉방", {T.T_AC: AC(True, "cool")}),
    ("에어컨 제습", {T.T_AC: AC(True, "dry")}),
    ("제습기", {T.T_DEHUMIDIFIER: True}),
    ("가습기 (제습기 끔)", {T.T_DEHUMIDIFIER: False, T.T_HUMIDIFIER: True}),
    ("청정기 1단", {T.T_PURIFIER_LEVEL: 1}),
    ("청정기 3단", {T.T_PURIFIER_LEVEL: 3}),
    ("요리 — 쿡탑 1500 W · 후드 약", {T.S_APPLIANCE_POWER: json.dumps({"cooktop": 1500.0}), T.T_RANGE_HOOD_LEVEL: 1}),
    ("후드 강", {T.T_RANGE_HOOD_LEVEL: 2}),
    ("쿡탑 플러그 차단 (E15)", {T.S_APPLIANCE_POWER: json.dumps({"cooktop": 0.0})}),
    ("창문 끼임 반전", {T.T_SAFETY_STATE: "PINCH_REVERSE"}),
    ("정지 유지", {T.T_SAFETY_STATE: "SAFETY_HOLD"}),
    ("닫힘 방향 잠금", {T.T_SAFETY_STATE: "LOCKED_CLOSING"}),
    ("정상 · 모두 끔", {T.T_SAFETY_STATE: "NORMAL", T.T_AC: AC(False), T.T_HUMIDIFIER: False, T.T_PURIFIER_LEVEL: 0,
                       T.T_RANGE_HOOD_LEVEL: 0}),
]
STEP_S = 3.0


def main() -> None:
    rclpy.init()
    node = rclpy.create_node("visual_check")
    topics = sorted({tp for _, d in STEPS for tp in d})
    pubs = {tp: ros_io.publisher(node, tp) for tp in topics}
    cur: dict = {}
    t0 = time.perf_counter()
    for k, (label, change) in enumerate(STEPS):
        cur.update(change)
        print(f"{time.perf_counter() - t0:6.1f} s  [{k:02d}] {label}", flush=True)
        end = time.perf_counter() + STEP_S
        while time.perf_counter() < end:
            for tp, v in cur.items():
                ros_io.publish(pubs[tp], tp, v)
            rclpy.spin_once(node, timeout_sec=1.0)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
