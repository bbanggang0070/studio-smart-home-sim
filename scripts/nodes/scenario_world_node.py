"""시나리오 월드 노드 (물리 모드) — 시나리오 진행 + 환경 참값 모델 (W07 센서 노드의 입력 · W08 환경 상태 노드 앞당김).

    tools/ros/run.sh node scripts/nodes/scenario_world_node.py --scenario C1 [--fast-actuators] [--speed 1]

  시나리오   config/scenario_profiles.yaml 의 initial · external · events · injections — 고속 모드와 같은 해석(harness)
  참값       RoomModel 을 액추에이터 '실제' 상태로 1 s 마다 적분. 액추에이터 상태는 Isaac 브릿지 · 가전 브릿지 상태 토픽에서 받는다
             --fast-actuators: Isaac 없이 시험 — 고속 모드의 1차 지연 액추에이터가 명령을 받아 상태 토픽을 대신 낸다
  발행       /studio/internal/env_truth (String JSON — 센서 노드 입력: 참값 · 외기 · 사람 · 고장 주입)
             /studio/internal/door_open (Bool — 사람이 문을 연다 → Isaac 문 조인트) · /studio/internal/person (String JSON → Isaac 사람 프록시)
             /studio/state/air_balance (Float32 — Q_net) · /studio/cmd/mode · activity (사용자 = 시나리오) · /clock (시뮬레이션 시각)
  시각       /clock = 하루 중 초 (시나리오 time_of_day + 경과). 제어기 노드가 이 시각을 쓴다
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import rclpy
import yaml
from rosgraph_msgs.msg import Clock
from std_msgs.msg import Bool, String

from harness.fast_world import FIELD_TO_STATE, FastActuators, WorldInputs, initial_actuators, make_model
from harness.scenario import load_scenarios
from harness.timeline import build_timeline
from interfaces import ros_io
from interfaces import topics as T
from env_model.config import load_config
from env_model.psychro import dew_point_c
from env_model.room import AcCommand

REPO = Path(__file__).resolve().parents[2]
ENV_TRUTH = f"{T.P}/internal/env_truth"
DOOR_OPEN = f"{T.P}/internal/door_open"
PERSON = f"{T.P}/internal/person"

# 상태 토픽 → ActuatorCommands 필드 (형 변환)
STATE_FIELDS = {
    T.T_WINDOW_OPEN_RATIO: ("window_open_ratio", float), T.T_BLIND_ANGLE: ("blind_angle_deg", float),
    T.T_FAN_RPM: ("exhaust_fan_rpm", float), T.T_INTAKE_FAN_RPM: ("intake_fan_rpm", float),
    T.T_RANGE_HOOD_LEVEL: ("range_hood_level", int), T.T_PURIFIER_LEVEL: ("purifier_level", int),
    T.T_DEHUMIDIFIER: ("dehumidifier", bool), T.T_HUMIDIFIER: ("humidifier", bool),
    T.T_CEILING_FAN: ("ceiling_fan", int), T.T_CEILING_LIGHT: ("ceiling_light_pct", float),
    T.T_DESK_LIGHT: ("desk_light_pct", float),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--fast-actuators", action="store_true", help="Isaac 없이 — 1차 지연 액추에이터가 상태 토픽을 낸다")
    ap.add_argument("--speed", type=float, default=1.0, help="시뮬레이션 배속 (Isaac 과 함께면 1)")
    args, _ = ap.parse_known_args()

    hcfg = yaml.safe_load((REPO / "config" / "harness.yaml").read_text(encoding="utf-8"))   # harness.runner 는 pandas 가 필요해 직접 읽는다
    sc = next(s for s in load_scenarios(REPO / hcfg["paths"]["scenarios"]) if s["id"] == args.scenario)
    env_cfg = load_config(REPO / hcfg["paths"]["environment_model"])
    if sc.get("environment_overrides"):
        env_cfg = env_cfg.with_overrides(sc["environment_overrides"])
    tl = build_timeline(sc)
    world = WorldInputs.from_scenario(sc)
    model = make_model(env_cfg, sc)
    acts = FastActuators(initial_actuators(sc), hcfg["fast_mode"]["actuator_time_constant_s"],
                         hcfg["appliance_profiles"][sc.get("appliance_profile", "full")])
    actual = acts.actual                                         # Isaac 이 있으면 상태 토픽으로 덮어쓴다
    hh, mm = str(sc["initial"].get("time_of_day", "00:00")).split(":")
    clock0 = (int(hh) * 60 + int(mm)) * 60.0
    duration = float(sc["duration_s"])

    rclpy.init()
    node = rclpy.create_node("scenario_world")
    log = node.get_logger()
    cooktop = {"relay": True}

    def on_state(topic, v):
        if args.fast_actuators:
            return
        if topic == T.T_AC:
            d = json.loads(v)
            actual.ac = AcCommand(power=bool(d.get("power")), mode=str(d.get("mode", "cool")),
                                  setpoint_c=float(d.get("setpoint", 26.0)))
        else:
            name, cast = STATE_FIELDS[topic]
            setattr(actual, name, cast(v))

    def on_cmd(topic, v):
        if topic == T.C_COOKTOP_POWER:
            cooktop["relay"] = bool(v)
        if args.fast_actuators:
            acts.command({topic: v}, state["t"])

    for tp in list(STATE_FIELDS) + [T.T_AC]:
        ros_io.subscribe(node, tp, on_state)
    for tp in T.COMMAND_TOPICS:
        if tp not in T.USER_COMMAND_TOPICS:
            ros_io.subscribe(node, tp, on_cmd)
    rel = ros_io.qos(T.C_MODE)
    pub_truth = node.create_publisher(String, ENV_TRUTH, rel)
    pub_door = node.create_publisher(Bool, DOOR_OPEN, rel)
    pub_person = node.create_publisher(String, PERSON, rel)
    pub_clock = node.create_publisher(Clock, "/clock", 10)
    pubs = {tp: ros_io.publisher(node, tp) for tp in (T.T_AIR_BALANCE, T.C_MODE, T.C_ACTIVITY)}
    fast_pubs = {tp: ros_io.publisher(node, tp) for tp in list(FIELD_TO_STATE.values()) + [T.T_AC]} if args.fast_actuators else {}

    state = {"t": 0.0, "was_present": world.occupancy, "arrived_at": None}
    dt = 1.0
    unsupported_seen: set[str] = set(tl.unsupported)
    for u in unsupported_seen:
        log.warn(f"물리 모드 월드 노드가 아직 처리하지 않는 주입: {u}")

    def tick():
        now = state["t"]
        if now > duration:
            log.info(f"시나리오 {args.scenario} 끝 ({duration:.0f} s)")
            raise SystemExit
        for change in tl.events_between(now - dt if now else -1.0, now + 1e-9 if now == 0 else now):
            world.apply(change)
        if args.fast_actuators:
            acts.update(dt)
        src, extra_power = tl.sources_at(now, cooktop["relay"])
        hung = tl.laundry_hung_between(now - dt if now else -1.0, now)
        if hung > 0:
            model.hang_laundry(model.state.laundry_moisture_g + hung)
        obs = model.step(dt if now else 0.0, actual, world.ext, src, world.occupancy_model())
        if world.occupancy and not state["was_present"]:
            state["arrived_at"] = now
        state["was_present"] = world.occupancy
        faults = sorted({k for k in ("lux_invalid", "mmwave_lost", "radar") if tl.active_kind(now, k)})
        truth = {
            "t": now, "tod_s": (clock0 + now) % 86400.0, "scenario": args.scenario,
            "obs": obs,                                       # energy_wh(누적) 포함 — 로거 · 지표
            "ext": {"outdoor_temp_c": world.ext.outdoor_temp_c, "outdoor_rh_pct": world.ext.outdoor_rh_pct,
                    "outdoor_pm25_ugm3": world.ext.outdoor_pm25_ugm3, "raining": world.raining,
                    "outdoor_dew_c": dew_point_c(world.ext.outdoor_temp_c, world.ext.outdoor_rh_pct,
                                               env_cfg.get("condensation.magnus_b"), env_cfg.get("condensation.magnus_c"))},
            "injections": ",".join(tl.active_labels(now)),
            "occupied_truth": world.occupancy,
            "extra_power_w": extra_power,
            "person": {"present": world.occupancy, "zone": world.occupant_zone, "motion": world.motion,
                       "phone": world.phone, "arrived_at": state["arrived_at"],
                       "wifi_doze": bool(tl.active_kind(now, "wifi")),
                       "curtain": [iv.spec["curtain"] for iv in tl.active_kind(now, "curtain")],
                       "neighbor": [iv.spec["neighbor"] for iv in tl.active_kind(now, "neighbor")]},
            "door_open": tl.door_open_at(now),
            "faults": faults,
        }
        pub_truth.publish(String(data=json.dumps(truth)))
        pub_door.publish(Bool(data=truth["door_open"]))
        pub_person.publish(String(data=json.dumps(truth["person"])))
        ros_io.publish(pubs[T.T_AIR_BALANCE], T.T_AIR_BALANCE, obs["q_net_m3h"])
        ros_io.publish(pubs[T.C_MODE], T.C_MODE, world.user_mode)
        ros_io.publish(pubs[T.C_ACTIVITY], T.C_ACTIVITY, world.activity)
        tod = clock0 + now
        c = Clock()
        c.clock.sec, c.clock.nanosec = int(tod), int((tod % 1) * 1e9)
        pub_clock.publish(c)
        if args.fast_actuators:
            for tp, v in acts.state_topics().items():
                if tp in fast_pubs:
                    ros_io.publish(fast_pubs[tp], tp, v)
        state["t"] = now + dt

    node.create_timer(dt / args.speed, tick)
    log.info(f"월드 노드 시작 — {args.scenario} · {duration:.0f} s · 배속 {args.speed:g}"
             + (" · 고속 액추에이터 (Isaac 없음)" if args.fast_actuators else " · 액추에이터 = Isaac · 가전 브릿지 상태"))
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    node.destroy_node()
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
