"""Isaac 액추에이터 브릿지 (W06 T6.1–T6.3b · T6.5 · T6.7) — 명령 토픽 → 조인트 · 조명, 조인트 → 상태 토픽.

Isaac 내장 Python 3.11 + 내장 Jazzy rclpy 에서 돈다:
    tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py [--gui] [--duration 초]
제어기 · 센서 노드(ROS 컨테이너)와는 토픽으로만 연결 (같은 DDS 도메인 · UDP).

  구독  ceiling/desk_light_intensity · desk_light_cct · fan_rpm(배기) · intake_fan_rpm · ceiling_fan(단) · blind_angle ·
        window_open_ratio · /studio/internal/window_torque_pct (W10 토크 프로파일 경로, 계약 밖 내부 토픽)
  발행  state/{ceiling_light_intensity, desk_light_intensity, fan_rpm, intake_fan_rpm, ceiling_fan, blind_angle,
        window_open_ratio, window_zone, safety_state, pinch_detected} · sensor/window_motor_current (50 Hz)
  범위 밖 명령은 actuator_limits.yaml 범위로 자른다 (T6.5). 로컬 컷오프는 물리 콜백 안에서 (T6.7 · scripts/sim/window_local.py).
  W07 — 센서: sensor/door_contact (문 조인트 각도 > contact_open_angle_deg · 10 Hz) · state/window_position_est (리플 카운팅 20 Hz)
        · 모터 전류 측정 잡음 · 월드 노드의 /studio/internal/door_open → 문 구동 · /studio/internal/person → 사람 프록시 자리
"""

import argparse
import sys
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--gui", action="store_true")
ap.add_argument("--duration", type=float, default=0.0, help="초 (0 = 끝없이)")
ap.add_argument("--no-local-cutoff", action="store_true", help="Baseline A — 로컬 컷오프 없음 (C2 대비군 · 단독 규칙 제어기)")
ap.add_argument("--record", default="", help="발표 영상용 — 이 폴더에 카메라 프레임(JPG)을 저장")
ap.add_argument("--record-camera", default="overview",
                help="scene_layout 카메라 이름 또는 'x,y,z:tx,ty,tz' (위치:바라보는 점)")
ap.add_argument("--record-fps", type=float, default=10.0)
ap.add_argument("--seed-offset", type=int, default=0, help="물리 조건 무작위화 — 반복마다 다른 리플 · 전류 잡음 (0 = 고정 시드)")
ap.add_argument("--record-from", type=float, default=0.0, help="녹화 시작 시각 [s] (브릿지 시작 기준)")
ap.add_argument("--record-ambient", type=float, default=150.0, help="녹화용 주변광(돔) 세기 — 화면용, 조도 센서는 환경 모델이 계산")
ap.add_argument("--record-sun", type=float, default=0.0, help="녹화용 햇빛(장면의 sun) 세기 — 화면용 (0 = 장면 기본값 · 꺼짐)")
ap.add_argument("--record-hide", default="", help="녹화에서 숨길 프림 경로 (쉼표) — 예: /World/blind (물리는 그대로)")
args, _ = ap.parse_known_args()

from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp({"headless": not args.gui, "width": 1280, "height": 720})

import math  # noqa: E402
import traceback  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))


def main() -> None:
    import numpy as np
    import omni.usd
    from isaacsim.core.api import World
    from isaacsim.core.prims import SingleArticulation, SingleRigidPrim
    from isaacsim.core.utils.extensions import enable_extension
    from pxr import UsdPhysics

    enable_extension("isaacsim.ros2.bridge")
    app.update()
    import rclpy

    from interfaces import ros_io
    from interfaces import topics as T
    from sim.actuators import IsaacActuators, rad_s_to_rpm, window_q_to_ratio, window_ratio_to_q
    from actuators.l0_protect import FanDirectionGuard
    from sensors.sensor_models import RippleCounter
    from sim.window_local import LocalCutoff, motor_current, window_zone
    from sim.appliance_visuals import ApplianceVisuals

    L = yaml.safe_load((REPO / "config" / "scene_layout.yaml").read_text(encoding="utf-8"))
    A = yaml.safe_load((REPO / "config" / "actuator_limits.yaml").read_text(encoding="utf-8"))
    th = yaml.safe_load((REPO / "config" / "thresholds.yaml").read_text(encoding="utf-8"))
    ws = th["smart_home_controller"]["ros__parameters"]["window_sensorless"]
    calib_p = REPO / "config" / "lighting_calibration.yaml"
    calib = yaml.safe_load(calib_p.read_text(encoding="utf-8")) if calib_p.exists() else {}
    B = A["bridge"]

    omni.usd.get_context().open_stage(str(REPO / L["usd_path"]))
    stage = omni.usd.get_context().get_stage()
    hz = B["physics_hz"]
    dt = 1.0 / hz
    world = World(stage_units_in_meters=1.0, physics_dt=dt, rendering_dt=dt * B["render_every_n_steps"])
    from isaacsim.sensors.physics import ContactSensor
    contact = world.scene.add(ContactSensor(prim_path="/World/window/window_panel/contact_sensor", name="panel_contact",
                                            min_threshold=0.0, max_threshold=1.0e7, radius=-1))
    world.reset()
    win = SingleArticulation("/World/window", name="window")
    fans = {n: SingleArticulation(f"/World/{n}", name=n) for n in ("exhaust_fan", "intake_fan", "ceiling_fan")}
    blind = SingleArticulation("/World/blind", name="blind")
    for a in (win, blind, *fans.values()):
        a.initialize()
    wdof = win.get_dof_index("window_prismatic_joint")
    door = SingleArticulation("/World/entrance_door", name="door")
    door.initialize()
    person = SingleRigidPrim("/World/occupancy_object", name="person")
    person.initialize()
    sm = yaml.safe_load((REPO / "config" / "sensor_models.yaml").read_text(encoding="utf-8"))
    rng = np.random.default_rng(sm["seed"] + 11 + 1000 * args.seed_offset)   # 리플 미스카운트 · 전류 잡음 (물리 조건 무작위화)
    ripple = RippleCounter(ws, L["window"]["travel_m"], sm["window_current"]["hard_stop_resync_m"], rng)
    i_noise = ws["ripple_estimation"]["current_noise_sigma_a"]
    ddrive = UsdPhysics.DriveAPI(stage.GetPrimAtPath("/World/entrance_door/entrance_door_joint"), "angular")
    sim_in = {"door_open": False, "person": None}
    obstacles = {n: SingleRigidPrim(f"/World/obstacles/{n}", name=n) for n, v in L["obstacles"].items() if "size_m" in v}
    for o in obstacles.values():
        o.initialize()
    park = {n: o.get_world_pose()[0].copy() for n, o in obstacles.items()}
    pending_obstacle: list[str] = []
    # 배치 확인 (2026-10-26) — 물리 39회 중 1–2회 화분이 경로에 없이 창문이 완주했다(접촉 0 N). 놓은 자리를 기억해 두고,
    # 창문이 움직이기 전까지 매 스텝 확인해 벗어나 있으면 다시 놓는다. 벗어난 거리 · 재배치 횟수는 실험 로그에 남는다
    placed = {"name": None, "spec": None, "target": None, "replaced": 0, "max_dev_m": 0.0}
    act = IsaacActuators(stage, L, A, calib)
    travel = L["window"]["travel_m"]
    wdrive = UsdPhysics.DriveAPI(stage.GetPrimAtPath("/World/window/window_prismatic_joint"), "linear")
    max_force = A["window_prismatic_joint"]["max_force_n"]
    if args.no_local_cutoff:                                  # Baseline A — 안전 계층 없이 계속 민다 (docs/03 C2 대비)
        ws = {**ws, "layered_safety": {**ws["layered_safety"], "local_cutoff_enabled": False}}
    cut = LocalCutoff(ws, travel)
    lv = {"ceiling": 0.0, "desk": 0.0, "cct": L["desk_lamp"]["cct_k"]}
    levels = A["ceiling_fan_joint"]["levels_rpm"]
    fan_guard = FanDirectionGuard(th["smart_home_controller"]["ros__parameters"]["appliances"]["ceiling_fan"]["direction_change_wait_s"])
    fan_want = {"level": 0}
    st = {"t": 0.0, "q": 0.0, "v": 0.0, "force": 0.0, "dir": 0, "new_trip": False, "clamped": 0}

    rclpy.init()
    node = rclpy.create_node("isaac_actuator_bridge")
    log = node.get_logger()

    def clamp(name, v, lo, hi):
        if v < lo or v > hi:
            st["clamped"] += 1
            log.warn(f"{name} {v} → 범위 [{lo}, {hi}] 로 자름")
        return min(max(v, lo), hi)

    ovr = {"mode": "normal", "locked": []}

    def on_override(m):
        """상위 안전 계층의 우선 지령 — 반전 · 유지 · 방향 잠금 (W10 T10.7). 제어기 지령보다 먼저 적용한다."""
        d = _json.loads(m.data)
        ovr.update(mode=d.get("mode", "normal"), locked=list(d.get("locked", [])))
        if ovr["mode"] == "reverse":
            if "detect" not in lat:                          # 상위만 감지한 경우 — 감지 시각 = 반전 지령 수신
                lat["detect"], lat["dir"] = st["t"], st["dir"]
            goal = float(d["to_ratio"]) * travel
            cut.on_command(1 if goal > st["q"] else -1)       # 반대 방향 — 로컬 컷오프도 풀린다
            act.window_ramp.set_goal(goal)
        elif ovr["mode"] == "hold":
            act.window_ramp.set_goal(act.window_ramp.value)
        log.info(f"상위 안전 지령: {d}")

    def on_cmd(topic, value):
        if topic == T.C_WINDOW_OPEN_RATIO:
            goal = clamp("window_open_ratio", float(value), 0.0, 1.0) * travel
            direction = 0 if abs(goal - st["q"]) < 1e-4 else (1 if goal > st["q"] else -1)
            if ovr["mode"] != "normal" or direction in ovr["locked"]:
                return                                        # 상위 SAFETY_HOLD · 반전 중 · 잠긴 방향 — 제어기 지령 무시
            if not cut.on_command(direction):
                log.warn(f"로컬 컷오프 — 같은 방향 지령 거부 ({cut.reason})")
                return
            act.window_ramp.set_goal(goal if goal > 0 else -L["window"]["seal_compress_m"])   # 닫힘은 씰을 눌러 닫는다
            if direction != 0:
                lat.clear()                                   # 새 주행 — 접촉 · 감지 · 정지 시각을 다시 잰다
                peak["contact"] = 0.0                         # 접촉력 최댓값도 (안전 반전 · 유지로는 지우지 않는다 — 끼임 피크 보존)
        elif topic == T.C_BLIND_ANGLE:
            act.set_blind_deg(clamp("blind_angle", float(value), *A["blind_joint"]["range_deg"]))
        elif topic == T.C_FAN_RPM:
            act.set_fan_rpm("exhaust_fan", clamp("fan_rpm", float(value), 0.0, A["exhaust_fan_joint"]["max_rpm"]))
        elif topic == T.C_INTAKE_FAN_RPM:
            act.set_fan_rpm("intake_fan", clamp("intake_fan_rpm", float(value), 0.0, A["intake_fan_joint"]["max_rpm"]))
        elif topic == T.C_CEILING_FAN:
            fan_want["level"] = int(clamp("ceiling_fan", int(value), -2, 2))   # 실제 단은 L0 방향 보호를 거쳐 매 주기 적용
        elif topic == T.C_CEILING_LIGHT:
            lv["ceiling"] = clamp("ceiling_light", float(value), 0.0, 100.0)
            act.set_light("ceiling", lv["ceiling"])
        elif topic == T.C_DESK_LIGHT:
            lv["desk"] = clamp("desk_light", float(value), 0.0, 100.0)
            act.set_light("desk", lv["desk"], lv["cct"])
        elif topic == T.C_DESK_LIGHT_CCT:
            lv["cct"] = clamp("desk_light_cct", float(value), 2700.0, 6500.0)
            act.set_light("desk", lv["desk"], lv["cct"])
        elif topic == T.I_WINDOW_TORQUE_PCT:                  # T6.3b — 토크 상한 (드라이브 maxForce 를 런타임에 바꾼다)
            pct = clamp("window_torque_pct", float(value), 0.0, 100.0)
            wdrive.GetMaxForceAttr().Set(max_force * pct / 100.0)

    for tp in (T.C_WINDOW_OPEN_RATIO, T.C_BLIND_ANGLE, T.C_FAN_RPM, T.C_INTAKE_FAN_RPM, T.C_CEILING_FAN,
               T.C_CEILING_LIGHT, T.C_DESK_LIGHT, T.C_DESK_LIGHT_CCT):
        ros_io.subscribe(node, tp, on_cmd)
    vis = ApplianceVisuals(stage, L, log=log.info)                          # v0.2 — 가전 표시등 · 에어컨 루버 · 가습 분무 (렌더 전용)
    for tp in ApplianceVisuals.TOPICS:
        ros_io.subscribe(node, tp, vis.on_state)
    node.create_subscription(ros_io.MSG[T.F32], T.I_WINDOW_TORQUE_PCT,
                             lambda m: on_cmd(T.I_WINDOW_TORQUE_PCT, m.data), ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    node.create_subscription(ros_io.MSG[T.STR], T.I_SIM_OBSTACLE, lambda m: pending_obstacle.append(m.data),
                             ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    node.create_subscription(ros_io.MSG[T.STR], T.I_WINDOW_OVERRIDE, on_override, ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    pub_local = node.create_publisher(ros_io.MSG[T.STR], T.I_WINDOW_LOCAL, ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    peak = {"contact": 0.0}
    lat: dict = {}                                            # 접촉 시작 · 감지 · 정지 (물리 콜백 시각)
    pdet = ws["pinch_detection"]

    def _ms(a, b):
        return None if a is None or b is None else round((a - b) * 1000.0, 1)
    pending_init: list[dict] = []
    node.create_subscription(ros_io.MSG[T.STR], T.I_SIM_INIT, lambda m: pending_init.append(_json.loads(m.data)),
                             ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    init_done = {"v": False}

    def apply_init(d):
        """시나리오 초기 상태 — 창문 · 블라인드를 그 자리에 바로 둔다 (한 번만 · 제어 지령 전에)."""
        if init_done["v"]:
            return
        init_done["v"] = True
        q = window_ratio_to_q(float(d.get("window_open_ratio", 0.0)), travel)
        pos = np.array(win.get_joint_positions())
        pos[wdof] = q
        win.set_joint_positions(pos)
        act.window_ramp.value = act.window_ramp.goal = q
        b = float(d.get("blind_angle_deg", 0.0))
        blind.set_joint_positions(np.full(L["blind"]["slat_count"], math.radians(b)))
        act.blind_ramp.value = act.blind_ramp.goal = b
        log.info(f"초기 상태: 창문 {d.get('window_open_ratio', 0.0)} · 블라인드 {b}°")

    def place_obstacle(name):
        """시험 전용 — 끼임 물체를 창 개구부에 놓거나('park') 모두 치운다. 'rigid_pot@0.15' = 문설주에서 0.15 m (기본 0.2).
        'rigid_pot@1.03:30' = 질량 30 kg 로 바꿔 놓는다 (여는 방향 끼임 — 가벼운 물체는 뒤에 막는 것이 없어 밀려 간다)."""
        wd = L["window"]
        if placed["spec"] == name and placed["target"] is not None:
            return                                    # 이미 놓았다 — 확인 전 재전송 (월드 노드) 은 무시 (실행 중 순간 이동 방지)
        spec_in = name
        name, _, mass = name.partition(":")
        name, _, at = name.partition("@")
        gap_x = float(at) if at else 0.20
        for n, o in obstacles.items():
            if n == name:
                sz = L["obstacles"][n]["size_m"]
                pos = np.array([wd["opening_x_range_m"][0] + wd["seal_thickness_m"] + gap_x,
                                L["room"]["depth_m"] + wd["panel_track_y_offset_m"], wd["sill_height_m"] + sz[2] / 2 + 0.002])
            else:
                pos = park[n]
            o.set_world_pose(position=pos)
            if n == name:
                placed["target"] = pos.copy()
            o.set_mass(float(mass) if (n == name and mass) else L["obstacles"][n]["mass_kg"])
            o.set_linear_velocity(np.zeros(3))
            o.set_angular_velocity(np.zeros(3))
        if name in obstacles:
            placed["name"], placed["spec"] = name, spec_in
        log.info(f"시험 물체: {name}")

    def check_obstacle() -> float:
        """놓은 물체가 목표 자리에서 벗어난 거리 [m] — 창문이 거의 닫혀 있고 접촉 전이면 다시 놓는다."""
        if placed["name"] is None or placed["target"] is None:
            return 0.0
        cur = np.array(obstacles[placed["name"]].get_world_pose()[0])
        dev = float(np.linalg.norm(cur - placed["target"]))
        placed["max_dev_m"] = max(placed["max_dev_m"], dev)
        before_motion = window_q_to_ratio(st["q"], travel) < B["obstacle_check_until_ratio"] and peak["contact"] <= 0.0
        if before_motion and dev > B["obstacle_tolerance_m"]:
            placed["replaced"] += 1
            log.warn(f"시험 물체가 자리에서 {dev * 1000:.0f} mm 벗어남 — 다시 놓는다 ({placed['replaced']}회)")
            spec, placed["spec"] = placed["spec"], None       # 같은 배치 무시를 피해 강제로 다시 놓는다
            place_obstacle(spec)
        return dev

    import json as _json
    from std_msgs.msg import Bool as _Bool
    node.create_subscription(_Bool, f"{T.P}/internal/door_open", lambda m: sim_in.update(door_open=bool(m.data)),
                             ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    node.create_subscription(ros_io.MSG[T.STR], f"{T.P}/internal/person",
                             lambda m: sim_in.update(person=_json.loads(m.data)), ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    pp = L["person_proxy"]
    away_xy = (pp["positions"]["entrance"][0], -1.5)                       # 집 밖 (현관 바깥)

    def apply_world():
        """월드 노드 입력 → 문 조인트 목표 · 사람 프록시 자리 (사람이 문을 연다 · 방 안을 옮겨 다닌다)."""
        ddrive.GetTargetPositionAttr().Set(L["entrance_door"]["open_max_deg"] * 0.6 if sim_in["door_open"] else 0.0)
        p = sim_in["person"]
        if p is None:
            return
        xy = pp["positions"].get(p["zone"], pp["positions"]["room"]) if p["present"] else away_xy
        if sim_in["door_open"]:
            xy = pp["positions"]["entrance"]
        cur = person.get_world_pose()[0]
        if abs(cur[0] - xy[0]) + abs(cur[1] - xy[1]) > 0.05:
            person.set_world_pose(position=np.array([xy[0], xy[1], pp["height_m"] / 2]))

    def door_contact() -> bool:
        return math.degrees(float(door.get_joint_positions()[0])) > L["entrance_door"]["contact_open_angle_deg"]

    out = [T.T_CEILING_LIGHT, T.T_DESK_LIGHT, T.T_FAN_RPM, T.T_INTAKE_FAN_RPM, T.T_CEILING_FAN, T.T_BLIND_ANGLE,
           T.T_WINDOW_OPEN_RATIO, T.T_WINDOW_ZONE, T.S_WINDOW_MOTOR_CURRENT,
           T.S_DOOR_CONTACT, T.T_WINDOW_POSITION_EST]
    pubs = {tp: ros_io.publisher(node, tp) for tp in out}

    # ---- 로컬 컷오프 — 물리 콜백 안 (ROS 왕복 없음) ----
    def physics_step(step_dt):
        st["t"] += step_dt
        st["q"] = float(win.get_joint_positions()[wdof])
        st["v"] = float(win.get_joint_velocities()[wdof])
        st["force"] = float(np.asarray(win.get_measured_joint_efforts())[wdof])
        f_contact = float(contact.get_current_frame().get("force", 0.0))
        # 씰 구간(Zone D)의 접촉은 씰 압착이지 끼임이 아니다 — 접촉 센서는 패널에 닿는 힘을 모두 합하므로 끼임 반력(지표 #5)에서 뺀다
        if window_zone(st["q"], travel, -1, None, ws) != "D_SEAL":
            peak["contact"] = max(peak["contact"], f_contact)
        # 지연 계측 (C2 · 지표 #4) — 접촉 시작 → 감지(로컬 차단 · 상위 반전) → 정지
        if lat.get("onset") is None and st["dir"] != 0 and f_contact > pdet["contact_onset_n"]:
            lat["onset"] = st["t"]
        # 정지 = 감지 당시 진행 방향의 속도가 stopped_speed 아래 (곧바로 반전하면 0 근처를 샘플 사이에서 건너뛴다)
        if (lat.get("detect") is not None and lat.get("stop_ms") is None
                and st["v"] * lat.get("dir", 0) < pdet["stopped_speed_mps"]):
            lat["stop_ms"] = (st["t"] - lat["detect"]) * 1000.0
        # 이동 방향 = 지령 램프의 속도 (실제 위치 오차로 정하면 마찰로 남은 정지 오차 때문에 '새 출발'을 놓친다 → 기동 피크 오작동)
        rv = act.window_ramp.velocity
        st["dir"] = 0 if abs(rv) < 1e-6 else (1 if rv > 0 else -1)
        if cut.step(st["t"], st["q"], st["v"], st["force"], st["dir"]):
            act.window_ramp.value = act.window_ramp.goal = st["q"]          # 즉시 정지 — 지금 위치에 고정
            wdrive.GetTargetPositionAttr().Set(st["q"])
            wdrive.GetTargetVelocityAttr().Set(0.0)
            st["new_trip"] = st.get("new_trip", 0) + 1                     # 로그 전에 여러 번 끊겨도 센다
            if "detect" not in lat:
                lat["detect"], lat["dir"] = st["t"], st["dir"]

    world.add_physics_callback("window_local_cutoff", physics_step)

    def fan_rpm(name):
        return rad_s_to_rpm(float(fans[name].get_joint_velocities()[0]))

    def publish_state():
        p = lambda tp, v: ros_io.publish(pubs[tp], tp, v)   # noqa: E731
        p(T.T_CEILING_LIGHT, lv["ceiling"])
        p(T.T_DESK_LIGHT, lv["desk"])
        p(T.T_FAN_RPM, fan_rpm("exhaust_fan"))
        p(T.T_INTAKE_FAN_RPM, fan_rpm("intake_fan"))
        c = fan_rpm("ceiling_fan")
        lvl = min(range(len(levels)), key=lambda i: abs(levels[i] - abs(c)))
        p(T.T_CEILING_FAN, int(math.copysign(lvl, c)) if lvl else 0)
        p(T.T_BLIND_ANGLE, float(np.degrees(blind.get_joint_positions()[0])))
        p(T.T_WINDOW_OPEN_RATIO, window_q_to_ratio(st["q"], travel))
        p(T.T_WINDOW_ZONE, window_zone(st["q"], travel, st["dir"], cut._start_q, ws))
        # 로컬 상태는 내부 토픽으로 — 계약 토픽 safety_state · pinch_detected 는 상위(window_safety_node)가 낸다
        pub_local.publish(ros_io.MSG[T.STR](data=_json.dumps({"tripped": cut.tripped, "reason": cut.reason,
                                                                 "contact_peak_n": round(peak["contact"], 1),
                                                                 "detect_ms": _ms(lat.get("detect"), lat.get("onset")),
                                                                 "stop_ms": None if lat.get("stop_ms") is None
                                                                 else round(lat["stop_ms"], 1),
                                                                 "obstacle": placed["name"],
                                                                 "obstacle_dev_mm": round(1000 * obstacle_dev["v"], 1),
                                                                 "obstacle_replaced": placed["replaced"]})))
        p(T.S_DOOR_CONTACT, door_contact())

    # ---- 발표 영상 녹화 (선택) — 실시간 제어 루프는 그대로, 일정 간격으로 렌더해 프레임 저장 ----
    rec = None
    if args.record:
        import omni.replicator.core as rep
        from PIL import Image
        from pxr import UsdGeom
        rec_dir = Path(args.record)
        rec_dir.mkdir(parents=True, exist_ok=True)
        if args.record_ambient > 0:
            from pxr import UsdLux
            UsdLux.DomeLight.Define(stage, "/World/lighting_module/record_ambient").CreateIntensityAttr(args.record_ambient)
        if args.record_sun > 0:
            from pxr import UsdLux
            UsdLux.DistantLight(stage.GetPrimAtPath("/World/lighting_module/sun")).GetIntensityAttr().Set(args.record_sun)
        for path in L.get("render_visible", []):              # GUI 기본 숨김(천장) — 녹화는 천장 반사광까지 보이게
            if stage.GetPrimAtPath(path).IsValid():
                UsdGeom.Imageable(stage.GetPrimAtPath(path)).GetVisibilityAttr().Set("inherited")
        for path in filter(None, args.record_hide.split(",")):
            UsdGeom.Imageable(stage.GetPrimAtPath(path)).MakeInvisible()
        if ":" in args.record_camera:
            pos, tgt = (tuple(float(v) for v in part.split(",")) for part in args.record_camera.split(":"))
            cam = rep.create.camera(position=pos, look_at=tgt, focal_length=18.0)
        else:
            cam = f"/World/cameras/{args.record_camera}"
        rp = rep.create.render_product(cam, (1280, 720))
        ann = rep.AnnotatorRegistry.get_annotator("rgb")
        ann.attach([rp])
        rec = {"ann": ann, "dir": rec_dir, "n": 0, "every": max(1, int(round(hz / args.record_fps))), "img": Image}
        log.info(f"녹화 — {rec_dir} · {args.record_camera} · {args.record_fps:g} fps · {args.record_from:g} s 부터")

    log.info(f"브릿지 시작 — 물리 {hz:.0f} Hz · 상태 {B['state_hz']:.0f} Hz · 전류 {B['current_hz']:.0f} Hz")
    # 발행 주기 — 물리 주기의 정수배가 아니어도 맞게 (120 Hz 에서 50 Hz 를 '2 스텝마다'로 반올림하면 60 Hz 가 된다)
    rates = {"state": B["state_hz"], "cur": B["current_hz"], "pos": sm["window_current"]["position_est_hz"]}
    last_tick = {name: -1 for name in rates}

    def due(name: str) -> bool:
        n = int(k * dt * rates[name])
        if n != last_tick[name]:
            last_tick[name] = n
            return True
        return False
    obstacle_dev = {"v": 0.0}
    t0 = time.perf_counter()
    k = 0
    while app.is_running() and (args.duration <= 0 or k * dt < args.duration):
        rclpy.spin_once(node, timeout_sec=0.0)
        while pending_init:
            apply_init(pending_init.pop(0))
        while pending_obstacle:
            place_obstacle(pending_obstacle.pop(0))
        obstacle_dev["v"] = check_obstacle()
        apply_world()
        lvl = fan_guard.apply(fan_want["level"], k * dt)                     # L0 — 실링팬 방향 전환 대기
        act.set_fan_rpm("ceiling_fan", math.copysign(levels[abs(lvl)], lvl) if lvl else 0.0)
        act.step(dt)
        shoot = rec is not None and k * dt >= args.record_from and k % rec["every"] == 0
        # 녹화 중에는 렌더 주기마다 렌더한다 — 저장할 때만 렌더하면 렌더러의 시간 누적이 상태 변화(표시등 · 분무)를 몇 초씩 늦게 따라간다
        world.step(render=shoot or ((args.gui or rec is not None) and k % B["render_every_n_steps"] == 0))
        if shoot:
            frame = np.asarray(rec["ann"].get_data())
            if frame.size:
                rec["img"].fromarray(frame[..., :3]).save(rec["dir"] / f"f{rec['n']:05d}.jpg", quality=90)
                rec["n"] += 1
        k += 1
        if st["new_trip"]:
            n, st["new_trip"] = st["new_trip"], 0
            log.warn(f"로컬 컷오프 — {cut.reason}" + (f" (직전 로그 뒤 {n}회)" if n > 1 else ""))
            publish_state()
        est = ripple.update(st["q"], moving=st["dir"] != 0 or abs(st["v"]) > 1e-4)   # 리플 카운팅 (매 물리 스텝)
        if due("cur"):
            ros_io.publish(pubs[T.S_WINDOW_MOTOR_CURRENT], T.S_WINDOW_MOTOR_CURRENT,
                           motor_current(st["force"], ws) + float(rng.normal(0.0, i_noise)))
        if due("pos"):
            ros_io.publish(pubs[T.T_WINDOW_POSITION_EST], T.T_WINDOW_POSITION_EST, est)
        if due("state"):
            publish_state()
        lag = t0 + k * dt - time.perf_counter()                              # 실시간 맞춤
        if lag > 0:
            time.sleep(lag)
    log.info(f"브릿지 종료 — {k * dt:.1f} s · 실시간 비 {k * dt / (time.perf_counter() - t0):.2f} · 클램핑 {st['clamped']}회")
    node.destroy_node()
    rclpy.shutdown()


try:
    main()
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
finally:
    app.close()
