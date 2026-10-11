"""smart_home_controller 노드 — 고속 모드와 같은 SmartHomeController 를 rclpy 로 감싼다 (제어기 코드는 두 모드에서 동일).

    tools/ros/run.sh node scripts/nodes/smart_home_node.py [--baseline proposed] [--clock0 HH:MM]

  입력  센서 13 · 사용자 명령(mode · activity) · 액추에이터 상태(브릿지) → inbox (토픽 이름 그대로)
  출력  step() 의 outbox → 명령 · 상태 토픽 (policy_rate_hz 주기)
  시각  now_s = 하루 중 초 — 월드 노드의 /clock(시뮬레이션 시각)을 따른다. 없으면 --clock0 부터 벽시계 · 그것도 없으면 현지 시각
  필수 센서(온도 · 습도 · PM)가 아직 없으면 판단하지 않고 기다린다 — 센서 노드는 W07
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import rclpy

from controller.params import load_params
from controller.smart_home import SmartHomeController
from interfaces import ros_io
from interfaces import topics as T

REQUIRED = (T.S_TEMPERATURE, T.S_HUMIDITY, T.S_PM25)
CONTROLLER_STATES = (T.T_LIVING_MODE, T.T_ACTIVE_EVENTS, T.T_DEW_MARGIN, T.T_VENTILATION, T.T_CONTROL_FEASIBILITY,
                     T.T_ENERGY_FORECAST, T.T_ALERTS)       # 제어기가 내는 상태 (나머지 상태는 브릿지 · 센서 노드)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="proposed")
    ap.add_argument("--clock0", default="", help="HH:MM — 하루 중 시작 시각 (기본: 현지 시각)")
    ap.add_argument("--scenario", default="", help="시나리오 id — 설치 설정(가전 프로파일 · 사용자 설정 · 필터 누적)을 고속 모드와 같게 읽는다")
    args, _ = ap.parse_known_args()

    p = load_params()
    ctrl = SmartHomeController()
    sc = {}
    if args.scenario:                                   # 고속 모드와 같은 reset — 프로파일이 다르면 쓸 수 있는 가전이 다르다 (X2 P-core)
        from harness.scenario import load_scenarios
        sc = next(s for s in load_scenarios(Path(__file__).resolve().parents[2] / "config" / "scenario_profiles.yaml")
                  if s["id"] == args.scenario)
    ctrl.reset({"baseline": args.baseline, "scenario": sc})
    rclpy.init()
    node = rclpy.create_node("smart_home_controller")
    log = node.get_logger()
    inbox: dict = {}
    own: set[str] = set()
    pubs: dict = {}

    def on_msg(topic, value):
        if topic not in own:                            # 자기가 낸 상태 토픽은 입력으로 받지 않는다
            inbox[topic] = value

    for tp in T.SENSOR_TOPICS + T.USER_COMMAND_TOPICS + T.STATE_TOPICS:
        ros_io.subscribe(node, tp, on_msg)

    clock = ros_io.SimClock(node)
    if args.clock0:
        h, m = args.clock0.split(":")
        base, t_start = int(h) * 3600 + int(m) * 60, time.time()
        now_tod = lambda: clock.now() if clock.sim is not None else (base + time.time() - t_start) % 86400.0   # noqa: E731
    else:
        now_tod = clock.now

    state = {"waiting": True}

    def tick():
        missing = [tp for tp in REQUIRED if tp not in inbox]
        if missing:
            if state["waiting"]:
                log.info(f"센서 대기 — {', '.join(missing)} (센서 노드 W07)", throttle_duration_sec=10.0)
            return
        if state["waiting"]:
            state["waiting"] = False
            log.info("센서 수신 — 제어 시작")
        outbox = ctrl.step(now_tod(), dict(inbox)) or {}
        for tp, v in outbox.items():
            if tp not in T.TYPES:
                continue
            if tp not in pubs:
                pubs[tp] = ros_io.publisher(node, tp)
                if tp in T.STATE_TOPICS:
                    own.add(tp)
            ros_io.publish(pubs[tp], tp, v)

    # 제어기가 낼 수 있는 토픽은 처음부터 발행자를 만든다 (값이 아직 없어도 그래프에 보이게 — 계약 점검)
    for tp in [c for c in T.COMMAND_TOPICS if c not in T.USER_COMMAND_TOPICS] + list(CONTROLLER_STATES):
        pubs[tp] = ros_io.publisher(node, tp)
        if tp in T.STATE_TOPICS:
            own.add(tp)
    node.create_timer(1.0 / p.get("policy_rate_hz"), tick)
    log.info(f"제어기 노드 시작 — baseline {args.baseline} · {p.get('policy_rate_hz')} Hz")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
