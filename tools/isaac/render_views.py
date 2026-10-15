"""Scene 스크린샷 — 카메라 3종 + 스탠드 색온도 2700 K / 6500 K 비교 (W03 T3.8 · W04 T4.1b 화면 확인).

실행: tools/isaac/run.sh python tools/isaac/render_views.py
결과: results/screenshots/w03_<camera>.png · w04_desk_cct_<K>.png (커밋하지 않는다)
"""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True, "width": 1280, "height": 720})

import sys  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def main() -> None:
    import numpy as np
    import omni.replicator.core as rep
    import omni.usd
    from PIL import Image
    from pxr import UsdLux

    L = yaml.safe_load((REPO / "config" / "scene_layout.yaml").read_text(encoding="utf-8"))
    omni.usd.get_context().open_stage(str(REPO / L["usd_path"]))
    stage = omni.usd.get_context().get_stage()
    out = REPO / "results" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    # 낮은 주변광 — 조명 효과가 보이게 (실내 조명만으로는 벽이 거의 검다)
    dome = UsdLux.DomeLight.Define(stage, "/World/lighting_module/ambient_preview")
    dome.CreateIntensityAttr(150.0)
    import omni.timeline
    omni.timeline.get_timeline_interface().set_current_time(1.0)   # 사람 캐릭터 대기 애니메이션 — 시간 샘플이 있는 시각에서 찍는다
    for _ in range(10):
        app.update()

    def shot(camera: str, name: str, warmup: int = 40) -> None:
        rp = rep.create.render_product(f"/World/cameras/{camera}", (1280, 720))
        ann = rep.AnnotatorRegistry.get_annotator("rgb")
        ann.attach([rp])
        for _ in range(warmup):
            app.update()
        rep.orchestrator.step(rt_subframes=8)
        img = np.asarray(ann.get_data())[..., :3]
        Image.fromarray(img).save(out / f"{name}.png")
        ann.detach()
        rp.destroy()
        print(f"저장: results/screenshots/{name}.png · 평균 밝기 {img.mean():.1f}", flush=True)

    sun = UsdLux.DistantLight(stage.GetPrimAtPath("/World/lighting_module/sun"))
    blight = UsdLux.RectLight(stage.GetPrimAtPath("/World/bathroom/ceiling_light"))
    for cam in L["cameras"]:
        sun.GetIntensityAttr().Set(3000.0 if cam == "window" else 0.0)    # 창 쪽은 낮 미리보기
        if blight:
            blight.GetIntensityAttr().Set(20000.0 if cam == "bathroom" else 0.0)   # 화장실 화면만 천장등 (화면용)
        shot(cam, f"w03_{cam}")
    sun.GetIntensityAttr().Set(0.0)
    lamp = UsdLux.SphereLight(stage.GetPrimAtPath("/World/lighting_module/desk_lamp/light"))
    ceiling = UsdLux.RectLight(stage.GetPrimAtPath("/World/lighting_module/ceiling_led_light/light"))
    ceiling.GetIntensityAttr().Set(0.0)                 # 스탠드만 — 색 차이가 잘 보이게
    for k in (2700.0, 6500.0):
        lamp.GetColorTemperatureAttr().Set(k)
        shot("desk", f"w04_desk_cct_{int(k)}")
    # v0.2 — 가전을 켠 모습 (표시등 · 루버 · 분무 · 후드 등) — 브릿지와 같은 코드로 상태를 넣는다
    sys.path.insert(0, str(REPO / "scripts"))
    from interfaces import topics as T
    from sim.appliance_visuals import ApplianceVisuals
    vis = ApplianceVisuals(stage, L)
    for tp, v in ((T.T_AC, '{"power": true, "mode": "cool"}'), (T.T_DEHUMIDIFIER, True), (T.T_HUMIDIFIER, True),
                  (T.T_PURIFIER_LEVEL, 3), (T.T_RANGE_HOOD_LEVEL, 2)):
        vis.on_state(tp, v)
    ceiling.GetIntensityAttr().Set(L["ceiling_light"]["intensity"] * 0.3)
    for cam in ("kitchen", "bedside"):
        shot(cam, f"w03_{cam}_on")


try:
    main()
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
finally:
    app.close()
