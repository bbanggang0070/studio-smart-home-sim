"""전력 감시 노드 (W07 T7.w3) — 계량 플러그 전력 → 다단계 상태 · 엣지 · 원인(command/manual).

    tools/ros/run.sh node scripts/nodes/power_monitor_node.py

  코어는 고속 모드와 같다 (sensors/power_monitor.py). 명령 토픽이 바뀐 시각을 그 기기의 '명령 시각'으로 기록한다 (원인 판정).
  입력 sensor/appliance_power · cmd/{ac, dehumidifier, humidifier}  →  발행 state/appliance_states (1 Hz)
"""

from __future__ import annotations

import json

import rclpy

from controller.params import load_params
from interfaces import ros_io
from interfaces import topics as T
from sensors.power_monitor import PowerMonitor

CMD_DEVICE = {T.C_AC: "ac", T.C_DEHUMIDIFIER: "dehumidifier", T.C_HUMIDIFIER: "humidifier"}


def main() -> None:
    th = load_params().th
    pm = PowerMonitor(th["power_monitor"], th["events"]["appliance_no_response"]["power_confirm_s"])
    rclpy.init()
    node = rclpy.create_node("power_monitor")
    clock = ros_io.SimClock(node)
    st: dict = {"power": None, "last_cmd": {}, "last_state": {}}

    def on_cmd(topic, v):
        if st["last_cmd"].get(topic) != v:                 # 바뀐 명령만 '명령 시각' (같은 값 반복 발행은 무시)
            st["last_cmd"][topic] = v
            want_on = None                                 # 명령의 전원 방향 (원인 판정 — 고속 하네스와 같다)
            try:
                want_on = bool(json.loads(v).get("power")) if topic == T.C_AC else bool(v)
            except (ValueError, TypeError, AttributeError):
                pass
            pm.note_command(CMD_DEVICE[topic], clock.elapsed(), want_on)

    for tp in CMD_DEVICE:
        ros_io.subscribe(node, tp, on_cmd)

    # 가전 브릿지 상태(L0 보호 뒤 실제 전원)가 바뀐 시각도 '명령 시각' — 보호로 미뤘던 명령이 늦게 실행되면
    # 명령 토픽 시각만으로는 전력 변화를 수동 조작으로 판정한다 (고속 하네스와 같다 · 2026-10-25)
    def on_state(topic, v):
        if topic == T.T_AC:
            try:
                on = bool(json.loads(v).get("power"))
            except (ValueError, TypeError):
                return
            dev = "ac"
        else:
            on, dev = bool(v), ("dehumidifier" if topic == T.T_DEHUMIDIFIER else "humidifier")
        if st["last_state"].get(dev) is not None and st["last_state"][dev] != on:
            pm.note_command(dev, clock.elapsed(), on)
        st["last_state"][dev] = on

    for tp in (T.T_AC, T.T_DEHUMIDIFIER, T.T_HUMIDIFIER):
        ros_io.subscribe(node, tp, on_state)
    ros_io.subscribe(node, T.S_APPLIANCE_POWER, lambda _, v: st.update(power=json.loads(v)))
    pub = ros_io.publisher(node, T.T_APPLIANCE_STATES)

    def tick():
        if st["power"] is None:
            return
        states = pm.update(clock.elapsed(), {k: float(v) for k, v in st["power"].items()})
        ros_io.publish(pub, T.T_APPLIANCE_STATES, json.dumps(states))

    node.create_timer(1.0, tick)
    node.get_logger().info("전력 감시 노드 시작 — " + ", ".join(pm.devices))
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
