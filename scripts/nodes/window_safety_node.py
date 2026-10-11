"""창문 상위 안전 계층 노드 (W10 T10.3–T10.8 · T10.7b) — 50 Hz. 코어는 controller/window_safety.py.

    tools/ros/run.sh node scripts/nodes/window_safety_node.py

  입력  sensor/window_motor_current (50 Hz) · state/window_position_est (리플 추정 20 Hz) · cmd/window_open_ratio (제어기 의도)
        /studio/internal/window_local (브릿지 로컬 컷오프 상태) · cmd/activity (WINDOW_UNLOCK — 방향 잠금 해제)
  출력  /studio/internal/window_torque_pct (Zone 별 토크 상한 — T10.4) · /studio/internal/window_override (반전 · 유지 · 잠금)
        state/safety_state · state/pinch_detected (계약 토픽 — 로컬 · 상위 상태를 합친다)
  2계층: 로컬(브릿지 물리 콜백, 1.80 A)은 정지만 하고, 정밀 판정(0.25 A + 속도 저하) · 반전 · SAFETY_HOLD · 잠금은 여기서 한다.
        이 노드가 죽어도 로컬은 정지 상태를 유지한다 (같은 방향 재지령 거부).
"""

from __future__ import annotations

import json
from pathlib import Path

import rclpy
import yaml
from std_msgs.msg import Float32, String

from controller.params import load_params
from controller.window_safety import WindowSafety, load_reference
from interfaces import ros_io
from interfaces import topics as T

REPO = Path(__file__).resolve().parents[2]


def main() -> None:
    p = load_params()
    ws = p.get("window_sensorless")
    A = yaml.safe_load((REPO / "config" / "actuator_limits.yaml").read_text(encoding="utf-8"))
    travel = ws["travel_length_m"]
    speed = A["window_prismatic_joint"]["max_speed_mps"]
    core = WindowSafety(ws, travel, load_reference(REPO / "models" / "window_reference_profile.csv"),
                        p.get("window_sensorless.layered_safety.safety_hold_s"))
    rclpy.init()
    node = rclpy.create_node("window_safety")
    log = node.get_logger()
    clock = ros_io.SimClock(node)
    st = {"i": None, "q": None, "goal": None, "local": {}, "label": None, "pinch": False}
    rel = ros_io.qos(T.C_WINDOW_OPEN_RATIO)
    pub_torque = node.create_publisher(Float32, T.I_WINDOW_TORQUE_PCT, rel)
    pub_ovr = node.create_publisher(String, T.I_WINDOW_OVERRIDE, rel)
    pubs = {tp: ros_io.publisher(node, tp) for tp in (T.T_SAFETY_STATE, T.T_PINCH_DETECTED)}

    def override(mode, to_ratio=None):
        d = {"mode": mode, "locked": sorted(core.locked)}
        if to_ratio is not None:
            d["to_ratio"] = to_ratio
        pub_ovr.publish(String(data=json.dumps(d)))

    def on_activity(_t, v):
        if v == "WINDOW_UNLOCK" and core.locked:
            core.unlock()
            override("normal")
            log.info("사용자 해제 — 창문 방향 잠금 풀림")

    ros_io.subscribe(node, T.S_WINDOW_MOTOR_CURRENT, lambda _t, v: st.update(i=float(v)))
    ros_io.subscribe(node, T.T_WINDOW_POSITION_EST, lambda _t, v: st.update(q=float(v)))
    ros_io.subscribe(node, T.C_WINDOW_OPEN_RATIO, lambda _t, v: st.update(goal=float(v) * travel))
    ros_io.subscribe(node, T.C_ACTIVITY, on_activity)
    node.create_subscription(String, T.I_WINDOW_LOCAL, lambda m: st.update(local=json.loads(m.data)), rel)

    def tick():
        if st["i"] is None or st["q"] is None:
            return
        q = st["q"]
        if core.state == "PINCH_REVERSE":
            direction = 1 if core._reverse_to > q else -1
        elif st["goal"] is not None and core.allowed(1 if st["goal"] > q else -1) and abs(st["goal"] - q) > 0.003:
            direction = 1 if st["goal"] > q else -1
        else:
            direction = 0
        act = core.update(clock.elapsed(), q, st["i"], direction, speed)
        tripped = bool(st["local"].get("tripped"))
        if tripped and not st.get("local_seen"):            # 로컬이 먼저 끊었다 — 판정 · 반전 정책은 상위가 (T10.7b)
            act = core.local_trip(clock.elapsed(), q, st["i"]) or act
            if act == "reverse":
                log.warn(f"로컬 컷오프 수신 ({st['local'].get('reason')}) → 끼임으로 처리")
        st["local_seen"] = tripped
        if act == "reverse":
            d = core.last
            log.warn(f"끼임 판정 — {d.zone} · 위치 {d.q * 1000:.0f} mm · 전류 {d.current:.2f} A (기준 {d.expected:.2f}) → "
                     f"{ws['pinch_detection']['reverse_distance_m'] * 1000:.0f} mm 반전" + (" · 방향 잠금" if core.locked else ""))
            override("reverse", core._reverse_to / travel)
            st["pinch"] = True
        elif act == "hold":
            override("hold")
        elif act == "release":
            override("normal")
            st["pinch"] = False
        if direction != 0:
            pub_torque.publish(Float32(data=float(core.torque(q, direction))))   # Zone 별 토크 상한 (T10.4)
        label = core.state_label()
        if st["local"].get("tripped") and label == "NORMAL":
            label = "LOCAL_CUTOFF"                                # 로컬만 멈춘 상태 (상위가 아직 판정 전)
        ros_io.publish(pubs[T.T_SAFETY_STATE], T.T_SAFETY_STATE, label)
        ros_io.publish(pubs[T.T_PINCH_DETECTED], T.T_PINCH_DETECTED,
                       bool(st["pinch"] or st["local"].get("tripped")))

    node.create_timer(1.0 / p.get("current_sample_rate_hz"), tick)
    log.info(f"창문 상위 안전 노드 시작 — {p.get('current_sample_rate_hz'):.0f} Hz · 기준 전류 models/window_reference_profile.csv")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
