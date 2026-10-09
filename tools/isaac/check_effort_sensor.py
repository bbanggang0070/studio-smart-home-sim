"""SETUP §7-4 · W02 리스크 — Effort Sensor 로 Prismatic 조인트의 반력을 읽을 수 있는지 실증한다.

구성: 고정 베이스 + Prismatic 조인트로 연결된 패널(창문 축소판) + 정적 벽.
패널을 위치 드라이브로 벽 너머 목표까지 밀면, 벽에 닿은 뒤 조인트 힘이 올라가야 한다.

실행: tools/isaac/run.sh python tools/isaac/check_effort_sensor.py
"""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

import sys  # noqa: E402
import traceback  # noqa: E402


def main():
    import numpy as np
    import omni.usd
    from isaacsim.core.api import World
    from isaacsim.core.prims import SingleArticulation
    from pxr import Gf, PhysxSchema, UsdGeom, UsdPhysics

    # 검증용 장치 치수 — 실제 창문 계수가 아니라 실증용 값이다
    WALL_X_M = 0.30
    TARGET_X_M = 0.60
    DRIVE_STIFFNESS = 2000.0     # N/m
    DRIVE_DAMPING = 200.0
    DRIVE_MAX_FORCE = 300.0      # N
    SETTLE_STEPS = 240           # 60 Hz × 4 s

    world = World(stage_units_in_meters=1.0, physics_dt=1.0 / 60.0)
    stage = omni.usd.get_context().get_stage()
    UsdGeom.Xform.Define(stage, "/World")

    def box(path, size, pos, dynamic):
        cube = UsdGeom.Cube.Define(stage, path)
        cube.CreateSizeAttr(1.0)
        xf = UsdGeom.Xformable(cube)
        xf.AddTranslateOp().Set(Gf.Vec3d(*pos))
        xf.AddScaleOp().Set(Gf.Vec3f(*size))
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        if dynamic:
            UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim())
            UsdPhysics.MassAPI.Apply(cube.GetPrim()).CreateMassAttr(2.0)
        return cube.GetPrim()

    UsdGeom.Xform.Define(stage, "/World/rig")
    UsdPhysics.ArticulationRootAPI.Apply(stage.GetPrimAtPath("/World/rig"))
    base = box("/World/rig/base", (0.05, 0.05, 0.05), (0.0, 0.0, 0.5), dynamic=True)
    panel = box("/World/rig/panel", (0.05, 0.4, 0.4), (0.1, 0.0, 0.5), dynamic=True)
    box("/World/wall", (0.02, 1.0, 1.0), (WALL_X_M + 0.035, 0.0, 0.5), dynamic=False)

    fixed = UsdPhysics.FixedJoint.Define(stage, "/World/rig/root_joint")
    fixed.CreateBody1Rel().SetTargets([base.GetPath()])

    joint = UsdPhysics.PrismaticJoint.Define(stage, "/World/rig/slider")
    joint.CreateBody0Rel().SetTargets([base.GetPath()])
    joint.CreateBody1Rel().SetTargets([panel.GetPath()])
    joint.CreateAxisAttr("X")
    joint.CreateLocalPos0Attr(Gf.Vec3f(0.0, 0.0, 0.0))
    joint.CreateLocalPos1Attr(Gf.Vec3f(0.0, 0.0, 0.0))
    joint.CreateLowerLimitAttr(-0.1)
    joint.CreateUpperLimitAttr(1.0)
    drive = UsdPhysics.DriveAPI.Apply(joint.GetPrim(), "linear")
    drive.CreateTypeAttr("force")
    drive.CreateStiffnessAttr(DRIVE_STIFFNESS)
    drive.CreateDampingAttr(DRIVE_DAMPING)
    drive.CreateMaxForceAttr(DRIVE_MAX_FORCE)
    drive.CreateTargetPositionAttr(0.0)
    PhysxSchema.PhysxJointAPI.Apply(joint.GetPrim())

    world.reset()
    art = SingleArticulation("/World/rig", name="rig")
    art.initialize()
    dof = art.get_dof_index("slider")

    effort_sensor = None
    sensor_error = ""
    try:
        from isaacsim.sensors.physics import EffortSensor

        effort_sensor = EffortSensor(prim_path="/World/rig/slider")
    except Exception as exc:  # 확장 경로가 바뀌었으면 기록만 하고 대체 API로 판정
        sensor_error = repr(exc)

    def settle(target):
        drive.GetTargetPositionAttr().Set(target)
        for _ in range(SETTLE_STEPS):
            world.step(render=False)
        pos = float(art.get_joint_positions()[dof])
        eff = float(np.asarray(art.get_measured_joint_efforts())[dof])
        sens = None
        if effort_sensor is not None:
            r = effort_sensor.get_sensor_reading()
            sens = float(r.value) if r.is_valid else None
        return pos, eff, sens

    free_pos, free_eff, free_sens = settle(0.15)          # 벽 앞 — 자유 이동
    push_pos, push_eff, push_sens = settle(TARGET_X_M)    # 벽 너머 목표 — 벽에 막힘

    print("=== Effort Sensor 검증 (Isaac Sim) ===", flush=True)
    print(f"EffortSensor 확장: {'isaacsim.sensors.physics.EffortSensor 사용' if effort_sensor else '실패 ' + sensor_error}", flush=True)
    print(f"자유 이동: 위치 {free_pos:.3f} m · get_measured_joint_efforts {free_eff:.1f} N · EffortSensor {free_sens}", flush=True)
    print(f"벽에 밀기: 위치 {push_pos:.3f} m · get_measured_joint_efforts {push_eff:.1f} N · EffortSensor {push_sens}", flush=True)
    blocked = push_pos < WALL_X_M + 0.02
    rose = abs(push_eff) > abs(free_eff) + 50.0
    print(f"판정: 벽에서 멈춤={blocked} · 반력 상승={rose} → {'PASS' if blocked and rose else 'FAIL'}", flush=True)


try:
    main()
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
finally:
    app.close()
