"""Isaac 액추에이터 브릿지 (W06 T6.1–T6.3b · T6.5 · T6.7) — 명령 토픽 → 조인트 · 조명, 조인트 → 상태 토픽.

Isaac 내장 Python 3.11 + 내장 Jazzy rclpy 에서 돈다:
    tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py [--gui] [--duration 초]
제어기 · 센서 노드(ROS 컨테이너)와는 토픽으로만 연결 (같은 DDS 도메인 · UDP).

  구독  ceiling/desk_light_intensity · desk_light_cct · fan_rpm(배기) · intake_fan_rpm · ceiling_fan(단) · blind_angle ·
        window_open_ratio · /studio/internal/window_torque_pct (W10 토크 프로파일 경로, 계약 밖 내부 토픽)
  발행  state/{ceiling_light_intensity, desk_light_intensity, fan_rpm, intake_fan_rpm, ceiling_fan, blind_angle,
        window_open_ratio, window_zone, safety_state, pinch_detected} · sensor/window_motor_current (50 Hz)
  범위 밖 명령은 actuator_limits.yaml 범위로 자른다 (T6.5). 로컬 컷오프는 물리 콜백 안에서 (T6.7 · scripts/sim/window_local.py).
"""

import argparse
import sys
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--gui", action="store_true")
ap.add_argument("--duration", type=float, default=0.0, help="초 (0 = 끝없이)")
args, _ = ap.parse_known_args()

from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp({"headless": not args.gui})

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
    from sim.actuators import IsaacActuators, rad_s_to_rpm, window_q_to_ratio
    from actuators.l0_protect import FanDirectionGuard
    from sim.window_local import LocalCutoff, motor_current, window_zone

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
    world.reset()
    win = SingleArticulation("/World/window", name="window")
    fans = {n: SingleArticulation(f"/World/{n}", name=n) for n in ("exhaust_fan", "intake_fan", "ceiling_fan")}
    blind = SingleArticulation("/World/blind", name="blind")
    for a in (win, blind, *fans.values()):
        a.initialize()
    wdof = win.get_dof_index("window_prismatic_joint")
    obstacles = {n: SingleRigidPrim(f"/World/obstacles/{n}", name=n) for n in L["obstacles"] if n != "park_x_m"}
    for o in obstacles.values():
        o.initialize()
    park = {n: o.get_world_pose()[0].copy() for n, o in obstacles.items()}
    pending_obstacle: list[str] = []
    act = IsaacActuators(stage, L, A, calib)
    travel = L["window"]["travel_m"]
    wdrive = UsdPhysics.DriveAPI(stage.GetPrimAtPath("/World/window/window_prismatic_joint"), "linear")
    max_force = A["window_prismatic_joint"]["max_force_n"]
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

    def on_cmd(topic, value):
        if topic == T.C_WINDOW_OPEN_RATIO:
            goal = clamp("window_open_ratio", float(value), 0.0, 1.0) * travel
            direction = 0 if abs(goal - st["q"]) < 1e-4 else (1 if goal > st["q"] else -1)
            if not cut.on_command(direction):
                log.warn(f"로컬 컷오프 — 같은 방향 지령 거부 ({cut.reason})")
                return
            act.window_ramp.set_goal(goal if goal > 0 else -L["window"]["seal_compress_m"])   # 닫힘은 씰을 눌러 닫는다
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
    node.create_subscription(ros_io.MSG[T.F32], T.I_WINDOW_TORQUE_PCT,
                             lambda m: on_cmd(T.I_WINDOW_TORQUE_PCT, m.data), ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    node.create_subscription(ros_io.MSG[T.STR], T.I_SIM_OBSTACLE, lambda m: pending_obstacle.append(m.data),
                             ros_io.qos(T.C_WINDOW_OPEN_RATIO))

    def place_obstacle(name):
        """시험 전용 — 끼임 물체를 창 개구부(문설주에서 0.2 m)에 놓거나 모두 치운다."""
        wd = L["window"]
        for n, o in obstacles.items():
            if n == name:
                sz = L["obstacles"][n]["size_m"]
                pos = np.array([wd["opening_x_range_m"][0] + wd["seal_thickness_m"] + 0.20,
                                L["room"]["depth_m"] + wd["panel_track_y_offset_m"], wd["sill_height_m"] + sz[2] / 2 + 0.002])
            else:
                pos = park[n]
            o.set_world_pose(position=pos)
            o.set_linear_velocity(np.zeros(3))
            o.set_angular_velocity(np.zeros(3))
        log.info(f"시험 물체: {name}")

    out = [T.T_CEILING_LIGHT, T.T_DESK_LIGHT, T.T_FAN_RPM, T.T_INTAKE_FAN_RPM, T.T_CEILING_FAN, T.T_BLIND_ANGLE,
           T.T_WINDOW_OPEN_RATIO, T.T_WINDOW_ZONE, T.T_SAFETY_STATE, T.T_PINCH_DETECTED, T.S_WINDOW_MOTOR_CURRENT]
    pubs = {tp: ros_io.publisher(node, tp) for tp in out}

    # ---- 로컬 컷오프 — 물리 콜백 안 (ROS 왕복 없음) ----
    def physics_step(step_dt):
        st["t"] += step_dt
        st["q"] = float(win.get_joint_positions()[wdof])
        st["v"] = float(win.get_joint_velocities()[wdof])
        st["force"] = float(np.asarray(win.get_measured_joint_efforts())[wdof])
        # 이동 방향 = 지령 램프의 속도 (실제 위치 오차로 정하면 마찰로 남은 정지 오차 때문에 '새 출발'을 놓친다 → 기동 피크 오작동)
        rv = act.window_ramp.velocity
        st["dir"] = 0 if abs(rv) < 1e-6 else (1 if rv > 0 else -1)
        if cut.step(st["t"], st["q"], st["v"], st["force"], st["dir"]):
            act.window_ramp.value = act.window_ramp.goal = st["q"]          # 즉시 정지 — 지금 위치에 고정
            wdrive.GetTargetPositionAttr().Set(st["q"])
            wdrive.GetTargetVelocityAttr().Set(0.0)
            st["new_trip"] = True

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
        p(T.T_SAFETY_STATE, "LOCAL_CUTOFF" if cut.tripped else "NORMAL")
        p(T.T_PINCH_DETECTED, cut.tripped)

    log.info(f"브릿지 시작 — 물리 {hz:.0f} Hz · 상태 {B['state_hz']:.0f} Hz · 전류 {B['current_hz']:.0f} Hz")
    k_state = max(1, int(round(hz / B["state_hz"])))
    k_cur = max(1, int(round(hz / B["current_hz"])))
    t0 = time.perf_counter()
    k = 0
    while app.is_running() and (args.duration <= 0 or k * dt < args.duration):
        rclpy.spin_once(node, timeout_sec=0.0)
        while pending_obstacle:
            place_obstacle(pending_obstacle.pop(0))
        lvl = fan_guard.apply(fan_want["level"], k * dt)                     # L0 — 실링팬 방향 전환 대기
        act.set_fan_rpm("ceiling_fan", math.copysign(levels[abs(lvl)], lvl) if lvl else 0.0)
        act.step(dt)
        world.step(render=args.gui and k % B["render_every_n_steps"] == 0)
        k += 1
        if st["new_trip"]:
            st["new_trip"] = False
            log.warn(f"로컬 컷오프 — {cut.reason}")
            publish_state()
        if k % k_cur == 0:
            ros_io.publish(pubs[T.S_WINDOW_MOTOR_CURRENT], T.S_WINDOW_MOTOR_CURRENT, motor_current(st["force"], ws))
        if k % k_state == 0:
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
