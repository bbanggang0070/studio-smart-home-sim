"""조도 해석 모델 대조 — 주광 (W12 T12.5) · 렌더(경로 추적) vs 제어 · 참값 모델의 주광 가정.

모델 (v3.4.21 개정 — thresholds lighting_model.daylight · common/daylight.py):
  작업면 주광 = 외부 조도 × [직사광 · 확산광별 주광률 × 블라인드 각도 표 투과 비]
  천장 센서 주광 = 작업면 주광 × 각도 표 센서 비
  (개정 전: 주광률 0.02 × 투과율 0.85 → 0.12 선형 · 센서 비 0.38 고정 — 이 도구의 첫 대조 결과로 개정했다)
  렌더 '해만' = 직사광 성분 · '돔' = 확산광 성분으로 비교한다
렌더: 조명 끔 · 흰 확산 패치(ρ = 0.8)의 휘도 L → E = π·L/ρ (calibrate_lighting.py 와 같은 방법)
  바깥 기준 = 건물 밖 수평 패치 · 작업면 = 바닥 6점 평균(높이 0) · 센서 = 천장 센서 위치(아래를 봄)
  하늘 조건 (가) 해만(맑음 · 고도 = scene_layout sun) (나) 돔(흐림 · 균일 하늘)
  블라인드 0 · 45 · 75° — 슬랫 표시 회전(정적 렌더 · 닫힘 방향 = 방 쪽 끝 위)

    tools/isaac/run.sh python tools/isaac/check_daylight.py   → results/validation/daylight_check.csv
"""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True, "width": 256, "height": 256})

import math  # noqa: E402
import sys  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ALBEDO = 0.8
BLIND = [0.0, 45.0, 75.0]


def main() -> None:
    import carb
    import numpy as np
    import omni.replicator.core as rep
    import omni.usd
    from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdShade

    def path_tracing():
        s = carb.settings.get_settings()
        s.set("/rtx/rendermode", "PathTracing")
        s.set("/rtx/pathtracing/spp", 128)
        s.set("/rtx/pathtracing/maxBounces", 6)
        s.set("/rtx/post/tonemap/op", 0)
        s.set("/rtx/post/histogram/enabled", False)
        for _ in range(20):
            app.update()

    def measure(cams):
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
            res[name] = math.pi * float((0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]).mean()) / ALBEDO
        return res

    L = yaml.safe_load((REPO / "config" / "scene_layout.yaml").read_text(encoding="utf-8"))
    th = yaml.safe_load((REPO / "config" / "thresholds.yaml").read_text(encoding="utf-8"))["smart_home_controller"]["ros__parameters"]
    lm = th["lighting_model"]
    room = L["room"]
    W, D = room["width_m"], room["depth_m"]
    floor = [(x, y, 0.001) for x in (0.8, 1.75, 2.7) for y in (2.0, 3.6)]

    def run_condition(sun_i: float, dome_i: float, deg: float) -> dict:
        """장면을 새로 열어 조명 끔 · 하늘 · 블라인드 각도를 맞춘 뒤 한 번 잰다 (렌더 제품을 만들면 장면이 다시 구성돼 이후 수정이 안 먹는다)."""
        omni.usd.get_context().open_stage(str(REPO / L["usd_path"]))
        st = omni.usd.get_context().get_stage()
        from pxr import UsdGeom
        for _p in L.get("render_visible", []):              # GUI 기본 숨김(천장) — 렌더 값(천장 반사광)이 캘리브레이션과 같도록 다시 보이게
            _pr = st.GetPrimAtPath(_p)
            if _pr.IsValid():
                UsdGeom.Imageable(_pr).GetVisibilityAttr().Set("inherited")
        m = UsdShade.Material.Define(st, "/World/Looks/day_white")
        sh = UsdShade.Shader.Define(st, "/World/Looks/day_white/shader")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(ALBEDO, ALBEDO, ALBEDO))
        sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1.0)
        sh.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(1)
        sh.CreateInput("specularColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0, 0, 0))
        m.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")

        def probe(name, pos, up):
            root = f"/World/daycheck/{name}"
            UsdGeom.Xform.Define(st, root)
            c = UsdGeom.Cube.Define(st, f"{root}/patch")
            c.CreateSizeAttr(1.0)
            x = UsdGeom.Xformable(c)
            x.AddTranslateOp().Set(Gf.Vec3d(pos[0], pos[1], pos[2] + (-0.001 if up else 0.001)))
            x.AddScaleOp().Set(Gf.Vec3f(0.12, 0.12, 0.002))
            UsdShade.MaterialBindingAPI.Apply(c.GetPrim()).Bind(m)
            cam = UsdGeom.Camera.Define(st, f"{root}/cam")
            eye = Gf.Vec3d(pos[0], pos[1], pos[2] + (0.15 if up else -0.15))
            UsdGeom.Xformable(cam).AddTransformOp().Set(Gf.Matrix4d().SetLookAt(eye, Gf.Vec3d(*pos), Gf.Vec3d(0, 1, 0)).GetInverse())
            cam.CreateFocalLengthAttr(50.0)
            cam.CreateClippingRangeAttr(Gf.Vec2f(0.01, 10.0))
            return f"{root}/cam"

        for path in ("/World/lighting_module/ceiling_led_light/light", "/World/lighting_module/desk_lamp/light"):
            UsdLux.LightAPI(st.GetPrimAtPath(path)).GetIntensityAttr().Set(0.0)
        UsdLux.DistantLight(st.GetPrimAtPath("/World/lighting_module/sun")).GetIntensityAttr().Set(sun_i)
        UsdLux.DomeLight.Define(st, "/World/daycheck_sky").CreateIntensityAttr(dome_i)
        n_rot = 0
        for p in st.Traverse():
            ps = str(p.GetPath())
            if ps.startswith("/World/blind/slat_") and ps.endswith("/geom"):
                # 슬랫 강체(slat_kk)는 물리 자세로 그려져 USD 변환이 안 먹는다 — 강체가 아닌 자식 형상을 돌린다
                x = UsdGeom.Xformable(p)
                ops = x.GetOrderedXformOps()
                r = x.AddRotateXOp(opSuffix="daycheck")
                r.Set(-deg)                                  # 조인트 축 −X (닫힘 = 방 쪽 끝 위)
                x.SetXformOpOrder([ops[0], r] + ops[1:])     # 이동 → 회전 → (비균일) 스케일 순서로 — 회전이 스케일보다 먼저 적용
                n_rot += 1
        assert n_rot > 0, "슬랫 형상을 못 찾음"
        cams = {"outdoor": probe("outdoor", (W / 2, D + 2.5, 0.9), True),
                "sensor": probe("sensor", tuple(np.asarray(L["illuminance_sensor"]["pos"]) - [0, 0, 0.015]), False)}
        for i, pt in enumerate(floor):
            cams[f"floor{i}"] = probe(f"floor{i}", pt, True)
        path_tracing()
        r = measure(cams)
        return {"outdoor_lux": r["outdoor"], "workplane_lux": float(np.mean([r[f"floor{i}"] for i in range(len(floor))])),
                "sensor_lux": r["sensor"]}

    rows = []
    for sky, sun_i, dome_i in (("sun", 3000.0, 0.0), ("overcast", 0.0, 1000.0)):
        for deg in BLIND:
            rows.append({"sky": sky, "blind_deg": deg, **run_condition(sun_i, dome_i, deg)})
            print(rows[-1], flush=True)
    import pandas as pd
    df = pd.DataFrame(rows)
    sys.path.insert(0, str(REPO / "scripts"))
    from common import daylight as dlm
    dl = {**lm["daylight"], "direct_fraction": {"sun": 1.0, "overcast": 0.0, "clear": 1.0}}   # 렌더 조건 = 성분 하나씩
    df["df_render"] = df.workplane_lux / df.outdoor_lux
    df["df_model"] = [dlm.workplane_per_outdoor(dl, s, d) for s, d in zip(df.sky, df.blind_deg)]
    df["sensor_ratio_render"] = df.sensor_lux / df.workplane_lux
    df["sensor_ratio_model"] = [1.0 / dlm.sensor_to_workplane(dl, s, d) for s, d in zip(df.sky, df.blind_deg)]
    df["blind_rel_render"] = df.workplane_lux / df.groupby("sky").workplane_lux.transform("first")
    df["blind_rel_model"] = [dlm.relative_transmittance(dl, s, d) for s, d in zip(df.sky, df.blind_deg)]
    out = REPO / "results" / "validation"
    out.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(out / "daylight_check.csv", index=False)
    print(df.round(3).to_string(index=False), flush=True)


try:
    main()
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
finally:
    app.close()
