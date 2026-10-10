"""조도 캘리브레이션 (W05 T5.7) — 조명 intensity ↔ lux 매핑 · 책상 조도 추정 오차.

1) 단위 검증: 빈 장면에서 사각 광원(휘도 L_s, 면적 A) 아래 거리 d 의 흰 패치 → 해석해 E = L_s·A/d² 와 비교
2) 광원 세기 = 정격 광속에서: 천장(사각) L = Φ/(π·A) · 스탠드(구 + 갓 원뿔 Ω) L = Φ/(π·r²·Ω)   (Φ = 소비전력 × 광효율)
3) 암실(외부광 0 · 주변광 0)에서 천장 · 스탠드를 각각 0 → 100 % 스윕 · 동시 점등 → 기준점 조도
   기준점: 천장 센서(아래를 봄) · 책상면(위를 봄) · 바닥 중앙(위를 봄) — 흰 확산 패치의 휘도 L → E = π·L/ρ
4) 책상 조도 추정식 (제어기 controller/lighting.py): 책상 = k_geo × 천장 기여(센서) + 스탠드 책상 기여 → 실측 대비 오차

실행: tools/isaac/run.sh python tools/isaac/calibrate_lighting.py
결과: config/lighting_calibration.yaml (커밋) · results/lighting/*.json
"""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True, "width": 256, "height": 256})

import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ALBEDO = 0.8                      # 측정 패치 반사율 (흰 확산면)
LUMINOUS_EFFICACY_LM_PER_W = 100.0   # environment_model lighting 주석의 가정 (LED 약 100 lm/W)
SWEEP = [0, 25, 50, 75, 100]


def main() -> None:
    import carb
    import numpy as np
    import omni.replicator.core as rep
    import omni.usd
    from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdShade

    def path_tracing():
        """경로 추적 — 실시간(RaytracedLighting)은 간접광이 거의 0 이라 천장 센서(반사광만 받음)를 잴 수 없다.
        스테이지를 열면 렌더 모드가 기본값으로 돌아가므로 열 때마다 다시 켠다."""
        st_ = carb.settings.get_settings()
        st_.set("/rtx/rendermode", "PathTracing")
        st_.set("/rtx/pathtracing/spp", 64)
        st_.set("/rtx/pathtracing/maxBounces", 6)
        st_.set("/rtx/post/tonemap/op", 0)            # 톤매핑 · 자동 노출 끔 (W05 리스크)
        st_.set("/rtx/post/histogram/enabled", False)
        for _ in range(20):
            app.update()

    L = yaml.safe_load((REPO / "config" / "scene_layout.yaml").read_text(encoding="utf-8"))
    env = yaml.safe_load((REPO / "config" / "environment_model.yaml").read_text(encoding="utf-8"))
    env_l = env["environment_model"]["ros__parameters"]["lighting"]
    out = REPO / "results" / "lighting"
    out.mkdir(parents=True, exist_ok=True)

    def white_material(stage):
        m = UsdShade.Material.Define(stage, "/World/Looks/calib_white")
        sh = UsdShade.Shader.Define(stage, "/World/Looks/calib_white/shader")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(ALBEDO, ALBEDO, ALBEDO))
        sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1.0)
        sh.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        sh.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(1)
        sh.CreateInput("specularColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0, 0, 0))
        m.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
        return m

    def probe(stage, name, pos, facing_up, mat):
        """흰 패치 + 패치를 수직으로 보는 카메라."""
        root = f"/World/calib/{name}"
        UsdGeom.Xform.Define(stage, root)
        c = UsdGeom.Cube.Define(stage, f"{root}/patch")
        c.CreateSizeAttr(1.0)
        x = UsdGeom.Xformable(c)
        x.AddTranslateOp().Set(Gf.Vec3d(pos[0], pos[1], pos[2] + (-0.001 if facing_up else 0.001)))
        x.AddScaleOp().Set(Gf.Vec3f(0.12, 0.12, 0.002))
        UsdShade.MaterialBindingAPI.Apply(c.GetPrim()).Bind(mat)
        cam = UsdGeom.Camera.Define(stage, f"{root}/cam")
        eye = Gf.Vec3d(pos[0], pos[1], pos[2] + (0.15 if facing_up else -0.15))
        up = Gf.Vec3d(0, 1, 0)
        m = Gf.Matrix4d().SetLookAt(eye, Gf.Vec3d(*pos), up).GetInverse()
        UsdGeom.Xformable(cam).AddTransformOp().Set(m)
        cam.CreateFocalLengthAttr(50.0)
        cam.CreateClippingRangeAttr(Gf.Vec2f(0.01, 10.0))
        return f"{root}/cam"

    def measure(cams: dict) -> dict:
        res = {}
        for name, cam in cams.items():
            rp = rep.create.render_product(cam, (64, 64))
            ann = rep.AnnotatorRegistry.get_annotator("HdrColor")
            ann.attach([rp])
            for _ in range(5):
                app.update()
            rep.orchestrator.step(rt_subframes=64)
            img = np.asarray(ann.get_data(), dtype=float)[..., :3]
            ann.detach()
            rp.destroy()
            c = img[24:40, 24:40]
            lum = float((0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]).mean())
            res[name] = math.pi * lum / ALBEDO
        return res

    # ---- 1. 단위 검증 — 빈 장면 ----
    omni.usd.get_context().new_stage()
    st = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(st, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(st, 1.0)
    UsdGeom.Xform.Define(st, "/World")
    mat = white_material(st)
    d, side, lum_src = 2.0, 0.6, 1000.0
    rl = UsdLux.RectLight.Define(st, "/World/test_light")
    rl.CreateWidthAttr(side)
    rl.CreateHeightAttr(side)
    rl.CreateIntensityAttr(lum_src)
    UsdGeom.Xformable(rl).AddTranslateOp().Set(Gf.Vec3d(0, 0, d))
    cam = probe(st, "unit", (0.0, 0.0, 0.0), True, mat)
    path_tracing()
    # 정사각 람베르트 광원 정면의 정확한 조도 (작은 광원 근사 L·A/d² 보다 정확한 해석식)
    a = side / 2 / d
    e_exact = 4 * lum_src * (a / math.sqrt(1 + a * a) * math.atan(a / math.sqrt(1 + a * a)))
    e_meas = measure({"unit": cam})["unit"]
    unit_ratio = e_meas / e_exact
    print(f"단위 검증: 해석 {e_exact:.2f} lux · 렌더 {e_meas:.2f} → 비 {unit_ratio:.3f}", flush=True)

    # ---- 2–3. 원룸 암실 스윕 ----
    omni.usd.get_context().open_stage(str(REPO / L["usd_path"]))
    st = omni.usd.get_context().get_stage()
    mat = white_material(st)
    cl, dl = L["ceiling_light"], L["desk_lamp"]
    phi_c = env_l["ceiling_light_w"] * LUMINOUS_EFFICACY_LM_PER_W
    phi_d = env_l["desk_lamp_w"] * LUMINOUS_EFFICACY_LM_PER_W
    # 정격 광속의 물리 휘도 [nit] vs Scene 표시용 intensity — 측정은 표시용 세기로(렌더 선형 범위) 하고 정격 광속으로 환산한다
    phys_c = phi_c / (math.pi * cl["size_m"] ** 2)
    # 스탠드는 갓이 빛을 원뿔(cone_deg) 안으로 모은다 — 구 광원 I = L·π·r² 가 원뿔 입체각 Ω 로만 나간다: Φ = L·π·r²·Ω
    omega = 2 * math.pi * (1 - math.cos(math.radians(dl["cone_deg"])))
    phys_d = phi_d / (math.pi * dl["radius_m"] ** 2 * omega)
    full_c, full_d = cl["intensity"], dl["intensity"]
    scale = {"ceiling": phys_c / full_c / unit_ratio, "desk": phys_d / full_d / unit_ratio}   # 렌더 값 → 정격 lux
    ceil = UsdLux.RectLight(st.GetPrimAtPath("/World/lighting_module/ceiling_led_light/light"))
    lamp = UsdLux.SphereLight(st.GetPrimAtPath("/World/lighting_module/desk_lamp/light"))
    sens = L["illuminance_sensor"]["pos"]
    desk = L["furniture"]["desk"]
    desk_pt = (desk["min"][0] + 0.30, desk["min"][1] + 0.65, desk["size"][2] + 0.001)
    floor_pt = (L["room"]["width_m"] / 2, L["room"]["depth_m"] / 2, 0.001)
    cams = {"sensor": probe(st, "sensor", (sens[0], sens[1], sens[2] - 0.015), False, mat),
            "desk": probe(st, "desk", desk_pt, True, mat),
            "floor": probe(st, "floor", floor_pt, True, mat)}
    path_tracing()

    def set_lights(c_pct, d_pct):
        ceil.GetIntensityAttr().Set(full_c * c_pct / 100.0)
        lamp.GetIntensityAttr().Set(full_d * d_pct / 100.0)

    sweep = {"ceiling": [], "desk": [], "both": []}
    for p in SWEEP:
        set_lights(p, 0)
        sweep["ceiling"].append({"pct": p, **{k: v * scale["ceiling"] for k, v in measure(cams).items()}})
        set_lights(0, p)
        sweep["desk"].append({"pct": p, **{k: v * scale["desk"] for k, v in measure(cams).items()}})
        print(f"{p:3d} % — 천장 단독 {sweep['ceiling'][-1]} · 스탠드 단독 {sweep['desk'][-1]}", flush=True)
    # 동시 점등 — 두 광원의 표시용/정격 배율이 다르므로 정격 비율대로 맞춘 세기로 켠다 (한 배율로 환산)
    ratio_d = scale["desk"] / scale["ceiling"]
    for cp, dp in ((50, 50), (100, 100), (30, 80), (80, 30)):
        ceil.GetIntensityAttr().Set(full_c * cp / 100.0)
        lamp.GetIntensityAttr().Set(full_d * ratio_d * dp / 100.0)
        sweep["both"].append({"ceiling_pct": cp, "desk_pct": dp,
                              **{k: v * scale["ceiling"] for k, v in measure(cams).items()}})

    def at(kind, pct, key):
        return next(r[key] for r in sweep[kind] if r["pct"] == pct)

    c_sens, c_desk, c_floor = at("ceiling", 100, "sensor"), at("ceiling", 100, "desk"), at("ceiling", 100, "floor")
    d_sens, d_desk = at("desk", 100, "sensor"), at("desk", 100, "desk")
    k_geo = c_desk / c_sens
    # 선형성 — 0–100 % 스윕의 최대 편차 (100 % 값을 직선으로 본 것 대비)
    lin = max(abs(r[k] - at(kind, 100, k) * r["pct"] / 100.0) / max(at(kind, 100, k), 1e-9)
              for kind in ("ceiling", "desk") for r in sweep[kind] for k in ("sensor", "desk"))
    # 합산성 + 책상 조도 추정 오차 (제어기 식: 책상 = k_geo × 천장 센서 기여 + 스탠드 책상 기여)
    add_err, est_err = [], []
    for r in sweep["both"]:
        pred_desk = c_desk * r["ceiling_pct"] / 100 + d_desk * r["desk_pct"] / 100
        add_err.append(abs(r["desk"] - pred_desk) / r["desk"])
        sensor_ceiling_part = r["sensor"] - d_sens * r["desk_pct"] / 100     # 제어기는 스탠드 몫을 빼고 천장 몫을 본다
        est = k_geo * sensor_ceiling_part + d_desk * r["desk_pct"] / 100
        est_err.append(abs(est - r["desk"]) / r["desk"])
    calib = {
        "version": 1,
        "generated_by": "tools/isaac/calibrate_lighting.py (W05 T5.7)",
        "renderer_unit_ratio": round(unit_ratio, 4),
        "ceiling_intensity_at_full": round(full_c, 2),          # Scene 표시용 (화면 밝기) — lux 는 아래 정격 값
        "desk_intensity_at_full": round(full_d, 2),
        "physical_luminance_nit": {"ceiling": round(phys_c, 1), "desk": round(phys_d, 1)},
        "luminous_flux_lm": {"ceiling": phi_c, "desk": phi_d},
        "lux_at_full": {"ceiling_at_sensor": round(c_sens, 1), "ceiling_at_desk": round(c_desk, 1),
                        "ceiling_at_floor": round(c_floor, 1), "desk_at_sensor": round(d_sens, 1),
                        "desk_at_desk": round(d_desk, 1)},
        "ceiling_to_desk_k_geo": round(k_geo, 3),
        "linearity_max_dev": round(lin, 4),
        "additivity_max_err": round(max(add_err), 4),
        "desk_estimate_max_err": round(max(est_err), 4),
    }
    (out / "sweep.json").write_text(json.dumps(sweep, ensure_ascii=False, indent=2), encoding="utf-8")
    path = REPO / "config" / "lighting_calibration.yaml"
    path.write_text("# 조도 캘리브레이션 결과 — 자동 생성 (tools/isaac/calibrate_lighting.py · W05 T5.7)\n"
                    "# 암실 · 경로 추적 렌더 · 톤매핑 끔 · 흰 확산 패치(ρ = 0.8)의 휘도로 조도 계산\n"
                    + yaml.safe_dump(calib, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(json.dumps(calib, ensure_ascii=False, indent=1), flush=True)
    print(f"=== → {path.relative_to(REPO)} ===", flush=True)


try:
    main()
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
finally:
    app.close()
