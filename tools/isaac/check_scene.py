"""원룸 Scene v0.1 검증 — W03 · W04 완료 기준(DoD)을 헤드리스로 확인한다.

실행: tools/isaac/run.sh python tools/isaac/check_scene.py
결과: 화면 출력 + results/scene_check.json (커밋하지 않는다)
화면 확인이 필요한 항목(조명 밝기 · 색이 '보이는지')은 속성 반영까지만 자동 확인하고, GUI 확인 항목으로 따로 표시한다.
"""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
results: list[dict] = []


def record(item: str, ok: bool, detail: str) -> None:
    results.append({"item": item, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {item} — {detail}", flush=True)


def main() -> None:
    import numpy as np
    import omni.usd
    from isaacsim.core.api import World
    from isaacsim.core.prims import SingleArticulation, SingleRigidPrim
    from isaacsim.sensors.physics import ContactSensor, EffortSensor
    from pxr import UsdLux, UsdPhysics

    L = yaml.safe_load((REPO / "config" / "scene_layout.yaml").read_text(encoding="utf-8"))
    A = yaml.safe_load((REPO / "config" / "actuator_limits.yaml").read_text(encoding="utf-8"))
    th = yaml.safe_load((REPO / "config" / "thresholds.yaml").read_text(encoding="utf-8"))
    th = th["smart_home_controller"]["ros__parameters"]
    usd = REPO / L["usd_path"]
    omni.usd.get_context().open_stage(str(usd))
    stage = omni.usd.get_context().get_stage()
    hz = L["physics"]["steps_per_second"]
    world = World(stage_units_in_meters=1.0, physics_dt=1.0 / hz, rendering_dt=1.0 / 60.0)

    # ---- 1. 프림 계층 (W03 창문 모듈 구조) ----
    required = ["/World/window/window_frame", "/World/window/window_frame/rack_visual", "/World/window/window_frame/seal",
                "/World/window/window_panel", "/World/window/window_panel/panel_glass",
                "/World/window/window_panel/motor_unit", "/World/window/window_prismatic_joint",
                "/World/lighting_module/ceiling_led_light", "/World/lighting_module/desk_lamp",
                "/World/entrance_door/entrance_door_joint", "/World/blind/blind_joint_00",
                "/World/exhaust_fan/exhaust_fan_joint", "/World/intake_fan/intake_fan_joint",
                "/World/ceiling_fan/ceiling_fan_joint", "/World/occupancy_object",
                "/World/obstacles/rigid_pot", "/World/obstacles/soft_cushion", "/World/obstacles/elastic_sponge",
                "/World/zones/desk_zone", "/World/zones/bed_zone", "/World/zones/kitchen_zone",
                "/World/cameras/overview", "/World/cameras/window", "/World/cameras/desk",
                # v0.2 — 가습기 · 시각 모델 · 가전 표시 프림 (scene_props · appliance_visuals)
                "/World/appliances/humidifier/collider", "/World/appliances/humidifier/visual/mist",
                "/World/appliances/air_conditioner/visual/louver", "/World/appliances/range_hood/visual/lamp",
                "/World/Looks/led_ac", "/World/furniture/bed/collider", "/World/cameras/kitchen", "/World/cameras/bedside"]
    missing = [p for p in required if not stage.GetPrimAtPath(p).IsValid()]
    record("프림 계층 (창문 모듈 구조 · 액추에이터 · 영역 · 카메라)", not missing,
           f"필수 {len(required)}개 중 누락 {missing or '없음'}")

    contact = world.scene.add(ContactSensor(prim_path="/World/window/window_panel/contact_sensor", name="panel_contact",
                                            min_threshold=0.0, max_threshold=1.0e7, radius=-1))
    world.reset()
    win = SingleArticulation("/World/window", name="window")
    door = SingleArticulation("/World/entrance_door", name="door")
    blind = SingleArticulation("/World/blind", name="blind")
    fans = {n: SingleArticulation(f"/World/{n}", name=n) for n in ("exhaust_fan", "intake_fan", "ceiling_fan")}
    for a in (win, door, blind, *fans.values()):
        a.initialize()
    obstacles = {n: SingleRigidPrim(f"/World/obstacles/{n}", name=n) for n in ("rigid_pot", "soft_cushion", "elastic_sponge")}
    for o in obstacles.values():
        o.initialize()
    person = SingleRigidPrim("/World/occupancy_object", name="person")
    person.initialize()
    effort = EffortSensor(prim_path="/World/window/window_prismatic_joint")

    def steps(seconds: float, probe=None):
        for _ in range(int(seconds * hz)):
            world.step(render=False)
            if probe:
                probe()

    def drive(path: str, kind: str, target: float, velocity: bool = False):
        d = UsdPhysics.DriveAPI(stage.GetPrimAtPath(path), kind)
        (d.GetTargetVelocityAttr() if velocity else d.GetTargetPositionAttr()).Set(float(target))

    wdof = win.get_dof_index("window_prismatic_joint")

    def q_window() -> float:
        return float(win.get_joint_positions()[wdof])

    # ---- 2. 물리 안정성 — 2 s 동안 낙하 · 진동 없음 ----
    start = {n: o.get_world_pose()[0].copy() for n, o in obstacles.items()}
    steps(2.0)
    drift = {n: float(np.linalg.norm(o.get_world_pose()[0] - start[n])) for n, o in obstacles.items()}
    vmax = max(float(np.linalg.norm(o.get_linear_velocity())) for o in obstacles.values())
    record("물리 안정성 (2 s 정지 — 낙하 · 진동 없음)", max(drift.values()) < 0.01 and vmax < 0.05 and abs(q_window()) < 0.01,
           f"물체 이동 최대 {max(drift.values()) * 1000:.1f} mm · 속도 최대 {vmax:.3f} m/s · 창문 q {q_window() * 1000:.1f} mm")

    # ---- 3. 창문 — 열기 · 닫기(씰 압착) · 반력 ----
    wd = L["window"]
    jpath = "/World/window/window_prismatic_joint"
    peak = {"contact": 0.0, "effort": 0.0}

    def probe():
        f = contact.get_current_frame()
        peak["contact"] = max(peak["contact"], float(f.get("force", 0.0)))
        r = effort.get_sensor_reading()
        if r.is_valid:
            peak["effort"] = max(peak["effort"], abs(float(r.value)))

    drive(jpath, "linear", 0.30)
    steps(10.0)
    q_open = q_window()
    peak.update(contact=0.0, effort=0.0)
    steps(2.0, probe)
    free_effort, free_contact = peak["effort"], peak["contact"]
    drive(jpath, "linear", -wd["seal_compress_m"])
    peak.update(contact=0.0, effort=0.0)
    steps(10.0, probe)
    record("창문 개폐 (prismatic · 속도 제한)", abs(q_open - 0.30) < 0.01 and q_window() < 0.003,
           f"열기 목표 0.30 → {q_open:.3f} m · 닫기 → {q_window() * 1000:.1f} mm")
    record("⭐ 씰 압착 — Contact Sensor · Effort Sensor 반력", peak["contact"] > 1.0 and peak["effort"] > free_effort + 5.0,
           f"접촉력 최대 {peak['contact']:.1f} N (자유 주행 {free_contact:.1f}) · Effort 최대 {peak['effort']:.1f} N "
           f"(자유 주행 {free_effort:.1f})")

    # ---- 4. 끼임 물체 3종 — 레일 경로에 놓고 닫으면 실제로 충돌 ----
    wx0 = wd["opening_x_range_m"][0]
    track_y = L["room"]["depth_m"] + wd["panel_track_y_offset_m"]
    pinch = {}
    for name, o in obstacles.items():
        sz = L["obstacles"][name]["size_m"]
        drive(jpath, "linear", 0.50)
        steps(12.0)
        o.set_world_pose(position=np.array([wx0 + wd["seal_thickness_m"] + 0.20, track_y, wd["sill_height_m"] + sz[2] / 2 + 0.002]))
        o.set_linear_velocity(np.zeros(3))
        o.set_angular_velocity(np.zeros(3))
        steps(1.0)
        drive(jpath, "linear", -wd["seal_compress_m"])
        peak.update(contact=0.0, effort=0.0)
        steps(14.0, probe)
        q_stop = q_window()
        pinch[name] = {"q_stop_m": round(q_stop, 4), "contact_max_n": round(peak["contact"], 1),
                       "effort_max_n": round(peak["effort"], 1)}
        ok = q_stop > 0.05 and peak["contact"] > 1.0
        record(f"끼임 물체 — {name}", ok,
               f"패널 정지 위치 {q_stop * 1000:.0f} mm (막힘) · 접촉력 최대 {peak['contact']:.1f} N · Effort 최대 {peak['effort']:.1f} N")
        drive(jpath, "linear", 0.50)
        steps(12.0)
        o.set_world_pose(position=start[name])
        o.set_linear_velocity(np.zeros(3))
        steps(0.5)
    drive(jpath, "linear", 0.0)
    steps(14.0)

    # ---- 5. 현관문 — 개방 각도 → 문 열림 판정 ----
    dpath = "/World/entrance_door/entrance_door_joint"
    drive(dpath, "angular", 30.0)
    steps(3.0)
    ang = math.degrees(float(door.get_joint_positions()[0]))
    is_open = ang > L["entrance_door"]["contact_open_angle_deg"]
    drive(dpath, "angular", 0.0)
    steps(3.0)
    ang_closed = math.degrees(float(door.get_joint_positions()[0]))
    record("현관문 개방 각도 → 문 열림 판정", is_open and ang_closed < L["entrance_door"]["contact_open_angle_deg"],
           f"30° 지령 → {ang:.1f}° (열림 {is_open}) · 닫기 → {ang_closed:.1f}°")

    # ---- 6. 블라인드 · 팬 ----
    n = L["blind"]["slat_count"]
    for k in range(n):
        drive(f"/World/blind/blind_joint_{k:02d}", "angular", 75.0)
    steps(4.0)
    slats = np.degrees(blind.get_joint_positions())
    record("블라인드 슬랫 회전 (0–90°)", float(np.max(np.abs(slats - 75.0))) < 3.0,
           f"75° 지령 → {float(np.min(slats)):.1f}–{float(np.max(slats)):.1f}°")
    targets = {"exhaust_fan": 1000.0, "intake_fan": 800.0, "ceiling_fan": 100.0}       # rpm
    for name, rpm in targets.items():
        drive(f"/World/{name}/{name}_joint", "angular", rpm * 6.0, velocity=True)          # deg/s
    steps(4.0)
    speeds = {name: abs(float(fans[name].get_joint_velocities()[0])) * 60.0 / (2 * math.pi) for name in targets}
    record("팬 3종 회전 (속도 드라이브)", all(abs(speeds[k] - targets[k]) / targets[k] < 0.1 for k in targets),
           " · ".join(f"{k} {targets[k]:.0f}→{speeds[k]:.0f} rpm" for k in targets))

    # ---- 7. 조명 2종 — 속성 반영 (화면 반영은 GUI 확인) ----
    rl = UsdLux.RectLight(stage.GetPrimAtPath("/World/lighting_module/ceiling_led_light/light"))
    sl = UsdLux.SphereLight(stage.GetPrimAtPath("/World/lighting_module/desk_lamp/light"))
    rl.GetIntensityAttr().Set(L["ceiling_light"]["intensity"] * 0.5)
    sl.GetColorTemperatureAttr().Set(2700.0)
    a = (rl.GetIntensityAttr().Get(), sl.GetColorTemperatureAttr().Get(), sl.GetEnableColorTemperatureAttr().Get())
    sl.GetColorTemperatureAttr().Set(6500.0)
    record("조명 2종 — 밝기 · 색온도 독립 변경 (속성)", a[0] == L["ceiling_light"]["intensity"] * 0.5 and a[1] == 2700.0
           and a[2] and sl.GetColorTemperatureAttr().Get() == 6500.0,
           f"천장 50 % → {a[0]:.0f} · 스탠드 2700 K → 6500 K · enableColorTemperature={a[2]} (화면 색 변화는 GUI 확인)")

    # ---- 8. 재실 영역 — 사람 프록시 진입 · 이탈 + mmWave 거리 구간 ----
    zones = L["zones"]
    sensor = np.array(L["mmwave_sensor"]["pos"][:2])
    gate = th["occupancy"]["gate_size_m"]
    zone_gates = th["occupancy"]["zone_gates"]

    def zone_of(p) -> str:
        for name, z in zones.items():
            if all(z["min"][i] <= p[i] <= z["min"][i] + z["size"][i] for i in range(2)):
                return name
        return "none"

    pp = L["person_proxy"]
    expected = {"entrance": "none", "kitchen": "kitchen", "desk": "desk", "bed": "bed", "room": "none"}
    ok_all, lines = True, []
    for spot, xy in pp["positions"].items():
        person.set_world_pose(position=np.array([xy[0], xy[1], pp["height_m"] / 2]))
        steps(0.1)
        pos = person.get_world_pose()[0]
        z = zone_of(pos)
        g = int(np.linalg.norm(pos[:2] - sensor) // gate)
        gate_ok = spot not in zone_gates or g in zone_gates[spot]
        ok = z == expected[spot] and gate_ok
        ok_all &= ok
        lines.append(f"{spot}→영역 {z} · 구간 {g}{'' if gate_ok else '(불일치)'}")
    record("재실 영역 진입 · 이탈 + mmWave 구간 일치 (thresholds zone_gates)", ok_all, " / ".join(lines))

    out = REPO / "results" / "scene_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"usd": L["usd_path"], "results": results, "pinch": pinch}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    n_ok = sum(r["ok"] for r in results)
    print(f"=== Scene 검증: {n_ok}/{len(results)} PASS → {out.relative_to(REPO)} ===", flush=True)
    del A


try:
    main()
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
finally:
    app.close()
