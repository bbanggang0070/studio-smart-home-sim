"""원룸 Scene v0.3 생성 (v0.2 + 화장실 · 배기팬 이전 · 도어락 · 책장 · 냉장고 / v0.2: 실제 기기 모양 · 가습기 · 가전 표시등 — tools/isaac/scene_props.py)

원룸 Scene v0.1 생성 — worlds/lowcost_studio_room.usd (W03 T3.1–T3.9 · W04 T4.1–T4.5).

입력: config/scene_layout.yaml (치수 · 좌표) · config/actuator_limits.yaml (조인트 제한 · 드라이브)
실행: tools/isaac/run.sh python tools/isaac/build_scene.py
검증: tools/isaac/run.sh python tools/isaac/check_scene.py

구조 원칙
- 강체 = 변환만 가진 Xform(RigidBodyAPI) + 크기를 준 자식 Cube(충돌 · 표시). 조인트 프레임이 스케일에 흔들리지 않는다.
- 움직이는 모듈은 각자 관절 묶음(articulation): 숨은 mount 강체를 고정 조인트로 세계에 붙이고 그 아래에 구동 조인트.
  PhysX 는 조인트로 이어진 두 강체끼리 충돌을 끄므로, 창문 씰 · 창틀은 mount 가 아닌 정적 충돌체로 둔다 (패널과 접촉해야 한다).
- 재실 영역은 표시 안 되는 guide 상자 — 진입 · 이탈 판정은 check_scene 이 좌표로 한다.
"""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

import math  # noqa: E402
import sys  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def main() -> None:
    from pxr import Gf, PhysxSchema, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scene_props import Props                      # v0.2 — 실제 기기를 닮은 시각 모델 (충돌 없음)

    L = yaml.safe_load((REPO / "config" / "scene_layout.yaml").read_text(encoding="utf-8"))
    A = yaml.safe_load((REPO / "config" / "actuator_limits.yaml").read_text(encoding="utf-8"))
    out = REPO / L["usd_path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(out))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    R = L["room"]
    W, D, H, T = R["width_m"], R["depth_m"], R["height_m"], R["wall_thickness_m"]
    ph = L["physics"]
    props = Props(stage, L)

    # ---- 도우미 ----

    def no_shadow(prim):
        """유리 — 표시용 투명도(displayOpacity)는 렌더러 그림자에 반영되지 않아 햇빛을 통째로 막는다 → 그림자를 만들지 않게."""
        UsdGeom.PrimvarsAPI(prim).CreatePrimvar("doNotCastShadows", Sdf.ValueTypeNames.Bool).Set(True)

    def color(prim, rgb, opacity=None):
        g = UsdGeom.Gprim(prim)
        g.CreateDisplayColorAttr([Gf.Vec3f(*rgb)])
        if opacity is not None:
            g.CreateDisplayOpacityAttr([opacity])

    def cube(path, center, size, rgb=(0.7, 0.7, 0.7), collide=True, opacity=None, visible=True):
        """크기를 준 Cube — 부모 Xform 기준 center."""
        c = UsdGeom.Cube.Define(stage, path)
        c.CreateSizeAttr(1.0)
        xf = UsdGeom.Xformable(c)
        xf.AddTranslateOp().Set(Gf.Vec3d(*center))
        xf.AddScaleOp().Set(Gf.Vec3f(*size))
        color(c.GetPrim(), rgb, opacity)
        if collide:
            UsdPhysics.CollisionAPI.Apply(c.GetPrim())
        if not visible:
            c.CreateVisibilityAttr("invisible")
        return c.GetPrim()

    def xform(path, pos=(0.0, 0.0, 0.0)):
        x = UsdGeom.Xform.Define(stage, path)
        x.AddTranslateOp().Set(Gf.Vec3d(*pos))
        return x.GetPrim()

    def rigid(path, pos, mass=None, kinematic=False, inertia=None):
        """inertia — 충돌체가 없는 강체(mount · 슬랫 · 팬 날개)는 관성을 직접 준다 (형상으로 계산할 수 없다)."""
        p = xform(path, pos)
        rb = UsdPhysics.RigidBodyAPI.Apply(p)
        if kinematic:
            rb.CreateKinematicEnabledAttr(True)
        if mass is not None:
            ma = UsdPhysics.MassAPI.Apply(p)
            ma.CreateMassAttr(float(mass))
            if inertia is not None:
                ma.CreateDiagonalInertiaAttr(Gf.Vec3f(*inertia))
        pr = PhysxSchema.PhysxRigidBodyAPI.Apply(p)
        pr.CreateSolverPositionIterationCountAttr(ph["solver_position_iterations"])
        pr.CreateSolverVelocityIterationCountAttr(ph["solver_velocity_iterations"])
        return p

    def box_min(path, mn, size, **kw):
        return cube(path, [mn[i] + size[i] / 2 for i in range(3)], size, **kw)

    def material(path, static_f, dynamic_f, restitution=0.0, compliance=None):
        m = UsdShade.Material.Define(stage, path)
        api = UsdPhysics.MaterialAPI.Apply(m.GetPrim())
        api.CreateStaticFrictionAttr(static_f)
        api.CreateDynamicFrictionAttr(dynamic_f)
        api.CreateRestitutionAttr(restitution)
        if compliance:
            px = PhysxSchema.PhysxMaterialAPI.Apply(m.GetPrim())
            px.CreateCompliantContactStiffnessAttr(compliance["stiffness"])
            px.CreateCompliantContactDampingAttr(compliance["damping"])
        return m

    def bind(prim, mat):
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(mat, UsdShade.Tokens.weakerThanDescendants, "physics")

    def articulation(path, mount_pos):
        """관절 묶음 루트 + 세계에 고정된 숨은 mount 강체."""
        root = xform(path)
        UsdPhysics.ArticulationRootAPI.Apply(root)
        pa = PhysxSchema.PhysxArticulationAPI.Apply(root)
        pa.CreateSolverPositionIterationCountAttr(ph["solver_position_iterations"])
        pa.CreateSolverVelocityIterationCountAttr(ph["solver_velocity_iterations"])
        pa.CreateEnabledSelfCollisionsAttr(False)
        mount = rigid(f"{path}/mount", mount_pos, mass=1.0, inertia=(0.01, 0.01, 0.01))
        fj = UsdPhysics.FixedJoint.Define(stage, f"{path}/mount_fixed_joint")
        fj.CreateBody1Rel().SetTargets([mount.GetPath()])
        fj.CreateLocalPos0Attr(Gf.Vec3f(*mount_pos))
        return mount

    def joint(kind, path, body0, body1, axis, pos0, pos1, lim=None, drive=None, drive_kind="linear", flip=False):
        j = (UsdPhysics.PrismaticJoint if kind == "prismatic" else UsdPhysics.RevoluteJoint).Define(stage, path)
        j.CreateBody0Rel().SetTargets([body0.GetPath()])
        j.CreateBody1Rel().SetTargets([body1.GetPath()])
        j.CreateAxisAttr(axis)
        j.CreateLocalPos0Attr(Gf.Vec3f(*pos0))
        j.CreateLocalPos1Attr(Gf.Vec3f(*pos1))
        if flip:                                       # 조인트 프레임을 Z 축으로 180° — 회전축이 −X 가 되어 양의 각도 방향이 바뀐다
            j.CreateLocalRot0Attr(Gf.Quatf(0.0, 0.0, 0.0, 1.0))
            j.CreateLocalRot1Attr(Gf.Quatf(0.0, 0.0, 0.0, 1.0))
        if lim is not None:
            j.CreateLowerLimitAttr(lim[0])
            j.CreateUpperLimitAttr(lim[1])
        if drive:
            d = UsdPhysics.DriveAPI.Apply(j.GetPrim(), drive_kind)
            d.CreateTypeAttr(drive.get("type", "force"))
            d.CreateStiffnessAttr(drive["stiffness"])
            d.CreateDampingAttr(drive["damping"])
            d.CreateMaxForceAttr(drive["max"])
            d.CreateTargetPositionAttr(0.0)
            if drive_kind == "angular" and drive["stiffness"] == 0.0:
                d.CreateTargetVelocityAttr(0.0)
        PhysxSchema.PhysxJointAPI.Apply(j.GetPrim())
        return j

    def look_at(path, eye, target):
        cam = UsdGeom.Camera.Define(stage, path)
        m = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1)).GetInverse()
        UsdGeom.Xformable(cam).AddTransformOp().Set(m)
        cam.CreateFocalLengthAttr(14.0)
        cam.CreateClippingRangeAttr(Gf.Vec2f(0.05, 100.0))

    # ---- 물리 장면 (T3.6) ----
    scene = UsdPhysics.Scene.Define(stage, "/World/physicsScene")
    scene.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
    scene.CreateGravityMagnitudeAttr(ph["gravity_mps2"])
    PhysxSchema.PhysxSceneAPI.Apply(scene.GetPrim()).CreateTimeStepsPerSecondAttr(ph["steps_per_second"])

    # ---- 방 껍데기 (T3.1) — 창 · 문 개구부를 남기고 벽을 조각으로 ----
    shell = "/World/room_shell"
    xform(shell)
    wall_rgb = (0.86, 0.84, 0.80)
    cube(f"{shell}/floor", (W / 2, D / 2, -0.05), (W + 2 * T, D + 2 * T, 0.1), rgb=(0.55, 0.45, 0.35))
    cube(f"{shell}/ceiling", (W / 2, D / 2, H + 0.05), (W + 2 * T, D + 2 * T, 0.1), rgb=(0.95, 0.95, 0.95))
    # 왼쪽 벽 — v0.3 화장실 문 개구부를 남기고 세 조각
    bt = L["bathroom"]
    bd0, bd1 = bt["door"]["y_range_m"]
    bdh = bt["door"]["height_m"]
    cube(f"{shell}/wall_left_a", (-T / 2, (bd0 - T) / 2, H / 2), (T, bd0 + T, H), rgb=wall_rgb)
    cube(f"{shell}/wall_left_b", (-T / 2, (bd1 + D + T) / 2, H / 2), (T, D + T - bd1, H), rgb=wall_rgb)
    cube(f"{shell}/wall_left_top", (-T / 2, (bd0 + bd1) / 2, (bdh + H) / 2), (T, bd1 - bd0, H - bdh), rgb=wall_rgb)
    cube(f"{shell}/wall_right", (W + T / 2, D / 2, H / 2), (T, D + 2 * T, H), rgb=wall_rgb)
    dr = L["entrance_door"]
    dx0, dx1 = dr["x_range_m"]
    dh = dr["height_m"]
    y = -T / 2
    cube(f"{shell}/wall_front_a", (dx0 / 2, y, H / 2), (dx0, T, H), rgb=wall_rgb)
    cube(f"{shell}/wall_front_b", ((dx1 + W) / 2, y, H / 2), (W - dx1, T, H), rgb=wall_rgb)
    cube(f"{shell}/wall_front_top", ((dx0 + dx1) / 2, y, (dh + H) / 2), (dx1 - dx0, T, H - dh), rgb=wall_rgb)
    wd = L["window"]
    wx0, wx1 = wd["opening_x_range_m"]
    z0, z1 = wd["sill_height_m"], wd["sill_height_m"] + wd["opening_height_m"]
    y = D + T / 2
    cube(f"{shell}/wall_back_a", (wx0 / 2, y, H / 2), (wx0, T, H), rgb=wall_rgb)
    cube(f"{shell}/wall_back_b", ((wx1 + W) / 2, y, H / 2), (W - wx1, T, H), rgb=wall_rgb)
    cube(f"{shell}/wall_back_bottom", ((wx0 + wx1) / 2, y, z0 / 2), (wx1 - wx0, T, z0), rgb=wall_rgb)
    cube(f"{shell}/wall_back_top", ((wx0 + wx1) / 2, y, (z1 + H) / 2), (wx1 - wx0, T, H - z1), rgb=wall_rgb)

    # ---- 화장실 (v0.3) — 방 왼쪽 벽 바깥 · 벽 · 바닥 · 천장 · 문 · 설비 · 천장등 ----
    bx0, bx1 = bt["interior_x_m"]
    by0, by1 = bt["interior_y_m"]
    bshell = "/World/bathroom"
    xform(bshell)
    tile_rgb = (0.86, 0.87, 0.88)
    cube(f"{bshell}/floor", ((bx0 - T + bx1) / 2, (by0 + by1) / 2, -0.05), (bx1 - bx0 + T, by1 - by0 + 2 * T, 0.1), rgb=(0.55, 0.57, 0.60))
    cube(f"{bshell}/ceiling", ((bx0 - T + bx1) / 2, (by0 + by1) / 2, H + 0.05), (bx1 - bx0 + T, by1 - by0 + 2 * T, 0.1), rgb=(0.95, 0.95, 0.95))
    cube(f"{bshell}/wall_west", (bx0 - T / 2, (by0 + by1) / 2, H / 2), (T, by1 - by0 + 2 * T, H), rgb=tile_rgb)
    cube(f"{bshell}/wall_front", ((bx0 + bx1) / 2, by0 - T / 2, H / 2), (bx1 - bx0, T, H), rgb=tile_rgb)
    cube(f"{bshell}/wall_back", ((bx0 + bx1) / 2, by1 + T / 2, H / 2), (bx1 - bx0, T, H), rgb=tile_rgb)
    bdoor = bt["door"]
    xform(f"{bshell}/door")
    props.xform(f"{bshell}/door/hinge", (bx1 + 0.02, bd1, 0.0), rot_deg=(0.0, 0.0, -float(bdoor["open_deg"])))   # 화장실 쪽으로 열림 (화면용 · 물리 없음)
    props.bathroom_door(f"{bshell}/door/hinge", bd1 - bd0 - 0.02, bdh - 0.01, 0.035)
    xform(f"{bshell}/fixtures")
    props.bathroom(f"{bshell}/fixtures")
    bl_ = bt["light"]
    blight = UsdLux.RectLight.Define(stage, f"{bshell}/ceiling_light")
    blight.CreateWidthAttr(bl_["size_m"])
    blight.CreateHeightAttr(bl_["size_m"])
    blight.CreateIntensityAttr(bl_["intensity"])
    UsdGeom.Xformable(blight).AddTranslateOp().Set(Gf.Vec3d(*bl_["pos"]))
    cube(f"{bshell}/ceiling_light_fixture", (bl_["pos"][0], bl_["pos"][1], bl_["pos"][2] + 0.012), (bl_["size_m"], bl_["size_m"], 0.02),
         rgb=(1.0, 1.0, 0.97), collide=False)

    # ---- 현관문 (T3.2 · T3.5) — 경첩 Revolute (문 열림 센서 = 개방 각도) ----
    dl = A["entrance_door_joint"]
    gap = 0.01
    door_w = dx1 - dx0 - 2 * gap
    dth = dr["thickness_m"]
    hinge = (dx0, 0.0, dh / 2)
    door_c = (dx0 + gap + door_w / 2, -dth / 2, dh / 2 - 0.005)
    mount = articulation("/World/entrance_door", hinge)
    panel = rigid("/World/entrance_door/door_leaf", door_c, mass=dr["mass_kg"])
    cube("/World/entrance_door/door_leaf/geom", (0, 0, 0), (door_w, dth, dh - 0.02), rgb=(0.45, 0.30, 0.20))
    joint("revolute", "/World/entrance_door/entrance_door_joint", mount, panel, "Z", (0, 0, 0),
          tuple(hinge[i] - door_c[i] for i in range(3)), lim=dl["range_deg"],
          drive={"stiffness": dl["drive"]["stiffness"], "damping": dl["drive"]["damping"], "max": dl["max_torque_nm"]},
          drive_kind="angular")
    dcs = (dx1 - 0.05, -0.02, dh - 0.1)
    xform("/World/entrance_door/door_contact_sensor", dcs)
    props.door_contact("/World/entrance_door/door_contact_sensor", "/World/entrance_door/door_leaf", door_c, dcs)
    props.door_hardware("/World/entrance_door/door_leaf", door_w, dth, door_c[2], dr["hardware"])   # v0.3 도어락 · 손잡이

    # ---- 창문 모듈 (T3.3 · T3.4 · T3.4b · T4.3 · T4.3b) ----
    wl = A["window_prismatic_joint"]
    track_y = D + wd["panel_track_y_offset_m"]
    pt, pw = wd["panel_thickness_m"], wd["panel_width_m"]
    clr = wd["panel_clearance_m"]
    seal_t = wd["seal_thickness_m"]
    ph_ = wd["opening_height_m"] - 2 * clr
    frame = "/World/window/window_frame"
    xform("/World/window")
    UsdPhysics.ArticulationRootAPI.Apply(stage.GetPrimAtPath("/World/window"))
    pa = PhysxSchema.PhysxArticulationAPI.Apply(stage.GetPrimAtPath("/World/window"))
    pa.CreateSolverPositionIterationCountAttr(ph["solver_position_iterations"])
    pa.CreateSolverVelocityIterationCountAttr(ph["solver_velocity_iterations"])
    pa.CreateEnabledSelfCollisionsAttr(False)
    xform(frame)                                                     # 정적 — 강체 아님
    rail_h = 0.02
    cube(f"{frame}/rail_bottom", ((wx0 + wx1) / 2, track_y, z0 - rail_h / 2 + 0.0), (wx1 - wx0, pt + 0.03, rail_h),
         rgb=(0.6, 0.6, 0.62), collide=False)
    cube(f"{frame}/rail_top", ((wx0 + wx1) / 2, track_y, z1 + rail_h / 2), (wx1 - wx0, pt + 0.03, rail_h),
         rgb=(0.6, 0.6, 0.62), collide=False)
    rack = f"{frame}/rack_visual"
    xform(rack)
    pitch = wd["rack_tooth_pitch_m"]
    n_teeth = int((wx1 - wx0) / pitch)
    cube(f"{rack}/bar", ((wx0 + wx1) / 2, track_y + pt / 2 + 0.008, z0 + 0.004), (wx1 - wx0, 0.006, 0.008),
         rgb=(0.3, 0.3, 0.32), collide=False)
    for k in range(n_teeth):
        cube(f"{rack}/tooth_{k:03d}", (wx0 + pitch * (k + 0.5), track_y + pt / 2 + 0.008, z0 + 0.010),
             (pitch * 0.45, 0.006, 0.006), rgb=(0.3, 0.3, 0.32), collide=False)
    seal = cube(f"{frame}/seal", (wx0 + seal_t / 2, track_y, (z0 + z1) / 2), (seal_t, pt + 0.02, wd["opening_height_m"]),
                rgb=(0.1, 0.1, 0.1))
    bind(seal, material("/World/materials/seal", wd["seal_friction"]["static"], wd["seal_friction"]["dynamic"],
                        compliance=wd["seal_compliance"]))
    cube(f"{frame}/outer_pane", ((wx0 + wx1) / 2 + (wx1 - wx0) / 4, D + T / 2 + 0.03, (z0 + z1) / 2),
         ((wx1 - wx0) / 2, 0.02, wd["opening_height_m"]), rgb=(0.7, 0.85, 0.95), opacity=0.25, collide=False)
    no_shadow(stage.GetPrimAtPath(f"{frame}/outer_pane"))
    cube(f"{frame}/windowsill", ((wx0 + wx1) / 2, D - wd["windowsill_depth_m"] / 2, z0 - 0.02),
         (wx1 - wx0, wd["windowsill_depth_m"], 0.04), rgb=(0.9, 0.9, 0.88))
    closed_cx = wx0 + seal_t + pw / 2                                 # 닫힘(q = 0) 때 패널 중심
    pc = (closed_cx, track_y, (z0 + z1) / 2)
    wmount = rigid("/World/window/mount", pc, mass=1.0, inertia=(0.01, 0.01, 0.01))
    fj = UsdPhysics.FixedJoint.Define(stage, "/World/window/mount_fixed_joint")
    fj.CreateBody1Rel().SetTargets([wmount.GetPath()])
    fj.CreateLocalPos0Attr(Gf.Vec3f(*pc))
    wp = rigid("/World/window/window_panel", pc, mass=wd["panel_mass_kg"])
    PhysxSchema.PhysxContactReportAPI.Apply(wp).CreateThresholdAttr(0.0)
    cube("/World/window/window_panel/panel_glass", (0, 0, 0), (pw, pt, ph_), rgb=(0.7, 0.85, 0.95), opacity=0.35)
    no_shadow(stage.GetPrimAtPath("/World/window/window_panel/panel_glass"))
    xform("/World/window/window_panel/motor_unit", (pw / 2 - 0.08, pt / 2 + 0.02, -ph_ / 2 + 0.04))
    props.window_motor("/World/window/window_panel/motor_unit")
    # 스프링식 레일 씰 (T5.8 — Zone A · B · C 의 물리적 근거): 패드 + Z 스프링 조인트 + 레일 띠 + 엔드존 경사로
    ws_, er = wd["weatherstrip"], wd["endzone_ramp"]   # noqa: F841
    psx, psy, psz = ws_["pad_size_m"]
    face_y = track_y - pt / 2
    pad_x0 = wx0 + seal_t + ws_["pad_offset_from_edge_m"]            # 닫힘 때 패드 중심 x
    rail_top = z0 + 0.001                                              # 벽 윗면보다 1 mm 위 — 패드가 레일 재질에만 닿게
    # 패드 기준 위치(스프링 0) = 닫힘 때 경사로 꼭대기 위 — 처음부터 파묻히지 않게. 평평한 레일에서는 rise 만큼 내려가 있다
    pad_c = (pad_x0, face_y - psy / 2 - 0.004, rail_top + er["rise_m"] + psz / 2)   # 패널 면에서 3 mm 이상 띄운다 (레일이 패널에 닿지 않게)
    pad = rigid("/World/window/weatherstrip_pad", pad_c, mass=ws_["pad_mass_kg"], inertia=(1e-5, 1e-5, 1e-5))
    pg = cube("/World/window/weatherstrip_pad/geom", (0, 0, 0), (psx, psy, psz), rgb=(0.15, 0.15, 0.15))
    stripmat = material("/World/materials/weatherstrip", ws_["friction"]["static"], ws_["friction"]["dynamic"])
    bind(pg, stripmat)
    strip_y = (pad_c[1], psy + 0.002)
    strip = cube(f"{frame}/rail_strip", ((wx0 + wx1) / 2, strip_y[0], rail_top - 0.005), (wx1 - wx0, strip_y[1], 0.01),
                 rgb=(0.4, 0.4, 0.42))
    bind(strip, stripmat)
    L_r = wd["travel_m"] * er["length_ratio"]
    theta = math.atan2(er["rise_m"], L_r)
    t_r = 0.01
    xs, xe = pad_x0 + L_r, pad_x0 - psx                               # 경사 시작(낮음) → 끝(높음, 문설주 쪽)
    xs_ext = xs + 0.02                                                 # 시작점 너머로 연장 — 레일 띠 아래로 묻혀 모서리에 걸리지 않게
    z_top = lambda x: rail_top + er["rise_m"] * (xs - x) / L_r        # noqa: E731 — 경사 윗면 높이
    mid = ((xs_ext + xe) / 2, (z_top(xs_ext) + z_top(xe)) / 2)
    ramp = UsdGeom.Cube.Define(stage, f"{frame}/endzone_ramp")
    ramp.CreateSizeAttr(1.0)
    rx = UsdGeom.Xformable(ramp)
    rx.AddTranslateOp().Set(Gf.Vec3d(mid[0] - math.sin(theta) * t_r / 2, strip_y[0], mid[1] - math.cos(theta) * t_r / 2))
    rx.AddRotateYOp().Set(math.degrees(theta))
    rx.AddScaleOp().Set(Gf.Vec3f((xs_ext - xe) / math.cos(theta), strip_y[1], t_r))
    color(ramp.GetPrim(), (0.5, 0.3, 0.3))
    UsdPhysics.CollisionAPI.Apply(ramp.GetPrim())
    bind(ramp.GetPrim(), stripmat)
    joint("prismatic", "/World/window/weatherstrip_spring", wp, pad, "Z",
          tuple(pad_c[i] - pc[i] for i in range(3)), (0, 0, 0), lim=(-0.03, 0.03),
          drive={"stiffness": ws_["spring_n_per_m"], "damping": ws_["spring_damping"], "max": 1000.0})
    UsdPhysics.DriveAPI(stage.GetPrimAtPath("/World/window/weatherstrip_spring"), "linear") \
        .GetTargetPositionAttr().Set(-(er["rise_m"] + ws_["preload_m"]))   # 평평한 곳 예압 = preload · 꼭대기 = rise + preload
    joint("prismatic", "/World/window/window_prismatic_joint", wmount, wp, "X", (0, 0, 0), (0, 0, 0),
          lim=(wl["range_m"][0] - wd["seal_compress_m"], wl["range_m"][1]),
          drive={"stiffness": wl["drive"]["stiffness"], "damping": wl["drive"]["damping"], "max": wl["max_force_n"]})
    PhysxSchema.PhysxJointAPI(stage.GetPrimAtPath("/World/window/window_prismatic_joint")) \
        .CreateMaxJointVelocityAttr(wl["max_speed_mps"])

    # ---- 끼임 시험 물체 3종 (T3.4c) — 침대 위에 대기 ----
    ob = L["obstacles"]
    xform("/World/obstacles")
    pk = ob["park"]                                             # v0.2 — 방 밖 숨은 받침대 (보이지 않는 충돌체)
    box_min("/World/obstacles/park_shelf", pk["shelf"]["min"], pk["shelf"]["size"], visible=False)
    shelf_top = pk["shelf"]["min"][2] + pk["shelf"]["size"][2]
    for k, name in enumerate(("rigid_pot", "soft_cushion", "elastic_sponge")):
        o = ob[name]
        sx, sy, sz = o["size_m"]
        pos = (pk["pos_m"][0] + pk["spacing_m"] * k, pk["pos_m"][1], shelf_top + sz / 2 + 0.002)
        body = rigid(f"/World/obstacles/{name}", pos, mass=o["mass_kg"])
        g = cube(f"/World/obstacles/{name}/geom", (0, 0, 0), (sx, sy, sz),
                 rgb={"rigid_pot": (0.6, 0.3, 0.2), "soft_cushion": (0.8, 0.5, 0.6), "elastic_sponge": (0.9, 0.85, 0.3)}[name])
        bind(g, material(f"/World/materials/{name}", o["friction"], o["friction"], o.get("restitution", 0.0),
                         o.get("compliance")))
        del body

    # ---- 블라인드 (T4.2) — 슬랫 Revolute (X 축) ----
    bl, blj = L["blind"], A["blind_joint"]
    by = D + bl["y_offset_m"]
    bmount = articulation("/World/blind", ((wx0 + wx1) / 2, by, z1 + 0.05))
    cube("/World/blind/mount/headrail", (0, 0, 0), (wx1 - wx0, 0.05, 0.04), rgb=(0.9, 0.9, 0.9), collide=False)
    n = bl["slat_count"]
    for k in range(n):
        zc = z1 - (k + 0.5) * (z1 - z0) / n
        sc = ((wx0 + wx1) / 2, by, zc)
        s = rigid(f"/World/blind/slat_{k:02d}", sc, mass=0.05, inertia=(1e-4, 1e-3, 1e-3))
        cube(f"/World/blind/slat_{k:02d}/geom", (0, 0, 0), (wx1 - wx0 - 0.02, bl["slat_depth_m"], bl["slat_thickness_m"]),
             rgb=(0.92, 0.92, 0.9), collide=False)
        joint("revolute", f"/World/blind/blind_joint_{k:02d}", bmount, s, "X",
              tuple(sc[i] - ((wx0 + wx1) / 2, by, z1 + 0.05)[i] for i in range(3)), (0, 0, 0), lim=blj["range_deg"],
              drive={"stiffness": blj["drive"]["stiffness"], "damping": blj["drive"]["damping"], "max": blj["max_torque_nm"]},
              drive_kind="angular", flip=True)   # 닫힘 = 방 쪽 끝이 위로 (위에서 내리쬐는 햇빛을 막는 방향)

    # ---- 팬 3종 (T4.4) — 날개 Revolute 속도 드라이브 · 충돌 없음 ----
    def fan(name, pos, diameter, axis, lim_key, blades=4, room_side=-1):
        fl = A[lim_key]
        m = articulation(f"/World/{name}", pos)
        xform(f"/World/{name}/mount/housing")
        if axis == "Z":
            props.ceiling_fan_housing(f"/World/{name}/mount/housing", pos)
        else:
            props.wall_fan_housing(f"/World/{name}/mount/housing", diameter, axis, intake=name == "intake_fan", room_side=room_side)
        rotor = rigid(f"/World/{name}/rotor", pos, mass=0.3 if axis != "Z" else 3.0,
                      inertia=(0.002, 0.002, 0.002) if axis != "Z" else (0.3, 0.3, 0.5))   # 벽 팬 날개 ≈ 0.3 kg · 반경 0.1 m
        # PhysX 기본 각속도 상한이 최대 rpm 보다 낮다 — 날개 강체 · 조인트 상한을 최대 rpm 의 1.2 배로
        vmax = fl["max_rpm"] * 6.0 * 1.2                                   # deg/s
        PhysxSchema.PhysxRigidBodyAPI(rotor).CreateMaxAngularVelocityAttr(vmax)
        for b in range(blades):
            ang = b * math.pi / blades
            if axis == "Z":
                size = (diameter, 0.10, 0.01)
                geo = cube(f"/World/{name}/rotor/blade_{b}", (0, 0, -0.1), size, rgb=(0.6, 0.45, 0.3), collide=False)
                UsdGeom.Xformable(geo).AddRotateZOp().Set(math.degrees(ang))
            else:
                size = (0.01, diameter * 0.95, 0.05) if axis == "X" else (diameter * 0.95, 0.01, 0.05)
                geo = cube(f"/World/{name}/rotor/blade_{b}", (0, 0, 0), size, rgb=(0.5, 0.5, 0.55), collide=False)
                (UsdGeom.Xformable(geo).AddRotateXOp() if axis == "X" else UsdGeom.Xformable(geo).AddRotateYOp()) \
                    .Set(math.degrees(ang))
        fj_ = joint("revolute", f"/World/{name}/{lim_key}", m, rotor, axis, (0, 0, 0), (0, 0, 0), lim=None,
                    drive={"stiffness": 0.0, "damping": fl["drive"]["damping"], "max": fl["max_torque_nm"]},
                    drive_kind="angular")
        PhysxSchema.PhysxJointAPI(fj_.GetPrim()).CreateMaxJointVelocityAttr(vmax)

    fan("exhaust_fan", L["exhaust_fan"]["pos"], L["exhaust_fan"]["diameter_m"], L["exhaust_fan"]["axis"], "exhaust_fan_joint",
        room_side=L["exhaust_fan"].get("room_side", -1))     # v0.3 화장실 바깥벽 — 실내 쪽 = +X
    fan("intake_fan", L["intake_fan"]["pos"], L["intake_fan"]["diameter_m"], L["intake_fan"]["axis"], "intake_fan_joint")
    fan("ceiling_fan", L["ceiling_fan"]["pos"], L["ceiling_fan"]["blade_span_m"], "Z", "ceiling_fan_joint", blades=3)

    # ---- 가구 · 가전 (T3.2 · v0.2) — 충돌체(레이아웃 상자 그대로 · 보이지 않음) + 시각 모델(scene_props) ----
    xform("/World/furniture")
    for name, f in L["furniture"].items():
        xform(f"/World/furniture/{name}")
        box_min(f"/World/furniture/{name}/collider", f["min"], f["size"], visible=False)
        xform(f"/World/furniture/{name}/visual")
        getattr(props, name)(f"/World/furniture/{name}/visual")
    xform("/World/appliances")
    for name in ("range_hood", "air_conditioner", "dehumidifier", "purifier", "humidifier"):
        f = L[name]
        xform(f"/World/appliances/{name}")
        if name in ("dehumidifier", "purifier", "humidifier"):            # 바닥에 놓인 것만 충돌 (벽걸이 · 후드는 손이 닿지 않는다)
            box_min(f"/World/appliances/{name}/collider", f["min"], f["size"], visible=False)
        xform(f"/World/appliances/{name}/visual")
        getattr(props, name)(f"/World/appliances/{name}/visual")

    # ---- 조명 2종 (T3.7 · T4.1 · T4.1b) ----
    cl, dl_ = L["ceiling_light"], L["desk_lamp"]
    xform("/World/lighting_module")
    lx = xform("/World/lighting_module/ceiling_led_light", cl["pos"])
    del lx
    rl = UsdLux.RectLight.Define(stage, "/World/lighting_module/ceiling_led_light/light")
    rl.CreateWidthAttr(cl["size_m"])
    rl.CreateHeightAttr(cl["size_m"])
    rl.CreateIntensityAttr(cl["intensity"])
    rl.CreateEnableColorTemperatureAttr(True)
    rl.CreateColorTemperatureAttr(4000.0)
    UsdGeom.Xformable(rl).AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.012))   # 광원은 등기구 상자 아래 — 안에 있으면 가려진다
    cube("/World/lighting_module/ceiling_led_light/fixture", (0, 0, 0.0), (cl["size_m"], cl["size_m"], 0.02),
         rgb=(1.0, 1.0, 0.97), collide=False)
    xform("/World/lighting_module/desk_lamp", dl_["pos"])
    sl = UsdLux.SphereLight.Define(stage, "/World/lighting_module/desk_lamp/light")
    sl.CreateRadiusAttr(dl_["radius_m"])
    sl.CreateIntensityAttr(dl_["intensity"])
    sl.CreateEnableColorTemperatureAttr(True)      # 기본값 False — 빼면 색온도가 무시된다 (W04 함정)
    sl.CreateColorTemperatureAttr(dl_["cct_k"])
    UsdLux.ShapingAPI.Apply(sl.GetPrim()).CreateShapingConeAngleAttr(dl_["cone_deg"])   # 갓 — 아래(−Z)로만
    xform("/World/lighting_module/desk_lamp/fixture")
    props.desk_lamp("/World/lighting_module/desk_lamp/fixture")
    sun = UsdLux.DistantLight.Define(stage, "/World/lighting_module/sun")
    sun.CreateIntensityAttr(0.0)                   # 일사 — 브릿지가 시각 · 날씨로 켠다
    UsdGeom.Xformable(sun).AddRotateXYZOp().Set(Gf.Vec3f(*L["sun"]["rotate_xyz_deg"]))   # 창밖 → 방 안

    # ---- 센서 (실제 모듈 · 하우징 모양 — v0.2) ----
    xform("/World/sensors")
    for name in ("mmwave_sensor", "pm25_sensor", "hood_temperature_sensor", "ceiling_sensor_hub"):
        xform(f"/World/sensors/{name}", L[name]["pos"])
        props.sensor(f"/World/sensors/{name}", name)
    for name in ("temp_humidity_sensor", "illuminance_sensor"):      # 측정점 표시 (박스 안 · 시각 모델 없음)
        xform(f"/World/sensors/{name}", L[name]["pos"])

    # ---- 재실 영역 (T3.5) — guide 상자 ----
    xform("/World/zones")
    for name, z in L["zones"].items():
        p = box_min(f"/World/zones/{name}_zone", z["min"], z["size"], rgb=(0.2, 0.8, 0.3), collide=False, opacity=0.1)
        UsdGeom.Imageable(p).CreatePurposeAttr(UsdGeom.Tokens.guide)

    # ---- 사람 프록시 (T4.5) — kinematic 캡슐 ----
    pp = L["person_proxy"]
    start = pp["positions"][pp["start"]]
    person = rigid("/World/occupancy_object", (start[0], start[1], pp["height_m"] / 2), kinematic=True)
    cap = UsdGeom.Capsule.Define(stage, "/World/occupancy_object/body")
    cap.CreateRadiusAttr(pp["radius_m"])
    cap.CreateHeightAttr(pp["height_m"] - 2 * pp["radius_m"])
    cap.CreateAxisAttr("Z")
    color(cap.GetPrim(), (0.95, 0.7, 0.5))
    cap.CreateVisibilityAttr("invisible")                  # v0.2 — 위치 판정용 캡슐은 숨기고 사람 모습을 보인다
    if not props.character("/World/occupancy_object/character", pp):
        xform("/World/occupancy_object/mannequin")
        props.mannequin("/World/occupancy_object/mannequin", pp["height_m"])
    del person

    # ---- 카메라 3종 (T3.8) ----
    xform("/World/cameras")
    for name, c in L["cameras"].items():
        look_at(f"/World/cameras/{name}", c["pos"], c["target"])

    stage.GetRootLayer().customLayerData = {"generated_by": "tools/isaac/build_scene.py", "version": "0.3"}
    stage.GetRootLayer().Save()
    n_prims = len(list(stage.Traverse()))
    print(f"Scene 저장: {out.relative_to(REPO)} · 프림 {n_prims}개", flush=True)


try:
    main()
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
    sys.exit(1)
finally:
    app.close()
