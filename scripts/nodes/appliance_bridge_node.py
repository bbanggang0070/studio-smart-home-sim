"""가전 브릿지 (W06 T6.v1 · T6.v2) — 가전 명령 → L0 보호 → 가전 상태 토픽. Isaac 의 물리 구동 대상이 아니다.

    tools/ros/run.sh node scripts/nodes/appliance_bridge_node.py

  구독  cmd/{ac(JSON), dehumidifier, humidifier, purifier_level, range_hood_level, cooktop_power}
  발행  state/{ac(JSON + confidence), dehumidifier, humidifier, purifier_level, range_hood_level} · 1 Hz
  L0    압축기 최소 ON/OFF (에어컨 · 제습기) · 제습 ⟂ 가습 (actuators/l0_protect.py)
  에어컨 신뢰도: IR 은 단방향 — 브릿지는 '보낸 것'만 안다 → UNKNOWN. 전력 감시(W07)가 확인하면 제어기가 CONFIRMED 로 본다.
  가전 효과(냉방 · 제습 등)는 환경 상태 노드(W08)가 이 상태 토픽을 받아 계산한다.
"""

from __future__ import annotations

import json
import time

import rclpy

from actuators.l0_protect import CompressorGuard, dehum_hum_mutex
from controller.params import load_params
from interfaces import ros_io
from interfaces import topics as T


def main() -> None:
    p = load_params()
    ap_ = p.get("appliances")
    rclpy.init()
    node = rclpy.create_node("appliance_bridge")
    log = node.get_logger()
    ac_g = CompressorGuard(ap_["ac"]["compressor_min_off_s"], ap_["ac"]["compressor_min_on_s"])
    dh_g = CompressorGuard(ap_["dehumidifier"]["compressor_min_off_s"], ap_["dehumidifier"]["compressor_min_on_s"])
    want = {"ac": {"power": False, "mode": "cool", "setpoint": 26.0, "fan": "auto"}, "dehumidifier": False,
            "humidifier": False, "purifier_level": 0, "range_hood_level": 0, "cooktop_power": True}
    lo, hi = ap_["ac"]["setpoint_range_c"]

    def on_cmd(topic, v):
        if topic == T.C_AC:
            try:
                a = json.loads(v)
                a["setpoint"] = min(max(float(a.get("setpoint", 26.0)), lo), hi)
                want["ac"] = {**want["ac"], **a}
            except (ValueError, TypeError):
                log.warn(f"cmd/ac JSON 해석 실패: {v!r}")
        elif topic == T.C_PURIFIER_LEVEL:
            want["purifier_level"] = min(max(int(v), 0), 3)
        elif topic == T.C_RANGE_HOOD_LEVEL:
            want["range_hood_level"] = min(max(int(v), 0), 2)
        else:
            want[topic.rsplit("/", 1)[-1]] = bool(v)

    for tp in (T.C_AC, T.C_DEHUMIDIFIER, T.C_HUMIDIFIER, T.C_PURIFIER_LEVEL, T.C_RANGE_HOOD_LEVEL, T.C_COOKTOP_POWER):
        ros_io.subscribe(node, tp, on_cmd)
    out = (T.T_AC, T.T_DEHUMIDIFIER, T.T_HUMIDIFIER, T.T_PURIFIER_LEVEL, T.T_RANGE_HOOD_LEVEL)
    pubs = {tp: ros_io.publisher(node, tp) for tp in out}
    t0 = time.monotonic()

    def tick():
        now = time.monotonic() - t0
        ac = dict(want["ac"])
        ac["power"] = ac_g.apply(bool(ac.get("power")), now)
        dehum, hum = dehum_hum_mutex(want["dehumidifier"], want["humidifier"])
        dehum = dh_g.apply(dehum, now)
        ac["confidence"] = "UNKNOWN"
        ac["l0_hold"] = ac_g.held
        ros_io.publish(pubs[T.T_AC], T.T_AC, json.dumps(ac))
        ros_io.publish(pubs[T.T_DEHUMIDIFIER], T.T_DEHUMIDIFIER, dehum)
        ros_io.publish(pubs[T.T_HUMIDIFIER], T.T_HUMIDIFIER, hum and not dehum)
        ros_io.publish(pubs[T.T_PURIFIER_LEVEL], T.T_PURIFIER_LEVEL, want["purifier_level"])
        ros_io.publish(pubs[T.T_RANGE_HOOD_LEVEL], T.T_RANGE_HOOD_LEVEL, want["range_hood_level"])

    node.create_timer(1.0, tick)
    log.info("가전 브릿지 시작 — L0 보호 (압축기 최소 ON/OFF · 제습 ⟂ 가습)")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
