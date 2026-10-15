"""원룸 Scene 시각 모델 (v0.2 · 2026-10-15) — 가구 · 가전 · 센서 · 팬을 실제 기기와 닮게 (충돌 없음 · 렌더 전용).

build_scene.py 가 부른다. 물리는 그대로 — 충돌체는 build_scene 이 레이아웃 상자 크기 그대로(보이지 않게) 따로 둔다.
모든 치수는 레이아웃 상자(min · size) 또는 위치(pos) 기준 비율 · 실제 제품 치수(일반적인 원룸용 제품 기준 근사)로 만든다.
표시등(LED) 재질은 상태마다 /World/Looks/<계열>__<상태> 로 미리 만든다 (scripts/sim/appliance_visuals.led_states 와 같은 표) —
프림은 처음에 '<계열>__off' 를 쓰고, 브릿지가 상태에 맞는 재질로 바꿔 끼운다.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdShade

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from sim.appliance_visuals import led_states  # noqa: E402

# 재질 — (색, 거칠기, 금속성, 불투명도)
MATS = {
    "white_plastic": ((0.93, 0.93, 0.92), 0.45, 0.0, 1.0),
    "grey_plastic": ((0.62, 0.63, 0.65), 0.5, 0.0, 1.0),
    "dark_plastic": ((0.10, 0.10, 0.11), 0.5, 0.0, 1.0),
    "stainless": ((0.78, 0.78, 0.80), 0.25, 0.9, 1.0),
    "black_metal": ((0.12, 0.12, 0.13), 0.4, 0.6, 1.0),
    "wood": ((0.66, 0.49, 0.32), 0.6, 0.0, 1.0),
    "dark_wood": ((0.38, 0.26, 0.17), 0.6, 0.0, 1.0),
    "mattress": ((0.92, 0.92, 0.94), 0.8, 0.0, 1.0),
    "blanket": ((0.36, 0.47, 0.66), 0.85, 0.0, 1.0),
    "fabric_grey": ((0.32, 0.33, 0.36), 0.85, 0.0, 1.0),
    "countertop": ((0.28, 0.28, 0.30), 0.3, 0.0, 1.0),
    "cabinet": ((0.90, 0.89, 0.86), 0.5, 0.0, 1.0),
    "ceramic_glass": ((0.03, 0.03, 0.035), 0.08, 0.0, 1.0),
    "burner": ((0.22, 0.10, 0.08), 0.3, 0.0, 1.0),
    "tank": ((0.70, 0.86, 0.96), 0.1, 0.0, 0.4),
    "mist": ((0.96, 0.97, 1.0), 0.9, 0.0, 0.22),
    "lens": ((0.04, 0.04, 0.05), 0.15, 0.0, 1.0),
    "pcb": ((0.08, 0.40, 0.20), 0.5, 0.0, 1.0),
    "filter": ((0.80, 0.80, 0.74), 0.9, 0.0, 1.0),
    "lamp_shade": ((0.95, 0.94, 0.88), 0.6, 0.0, 1.0),
    "skin": ((0.85, 0.66, 0.52), 0.6, 0.0, 1.0),
    "shirt": ((0.30, 0.42, 0.62), 0.8, 0.0, 1.0),
    "pants": ((0.18, 0.19, 0.22), 0.8, 0.0, 1.0),
    "tile": ((0.86, 0.87, 0.88), 0.35, 0.0, 1.0),
    "porcelain": ((0.97, 0.97, 0.96), 0.15, 0.0, 1.0),
    "mirror": ((0.85, 0.88, 0.90), 0.02, 1.0, 1.0),
    "shower_glass": ((0.80, 0.90, 0.95), 0.05, 0.0, 0.25),
    "fridge": ((0.80, 0.81, 0.82), 0.3, 0.5, 1.0),
}
BOOK_RGB = ((0.55, 0.15, 0.12), (0.12, 0.25, 0.50), (0.85, 0.75, 0.40), (0.20, 0.42, 0.25), (0.40, 0.40, 0.42), (0.70, 0.45, 0.20))


class Props:
    def __init__(self, stage, L: dict):
        self.stage, self.L = stage, L
        self._mats: dict[str, UsdShade.Material] = {}
        UsdGeom.Scope.Define(stage, "/World/Looks")
        for name, (rgb, rough, metal, opacity) in MATS.items():
            self.material(name, rgb, rough, metal, opacity)
        for k, rgb in enumerate(BOOK_RGB):
            self.material(f"book_{k}", rgb, 0.7, 0.0, 1.0)
        # 표시등 — 상태별 재질 (셰이더 값 변경은 물리 실행 중 렌더에 반영되지 않아 재질을 바꿔 끼운다 · 2026-10-16)
        self.leds = led_states(L["indicators"])
        for fam, states in self.leds.items():
            for st_, (base, emis) in states.items():
                self.material(f"{fam}__{st_}", base, 0.3, 0.0, 1.0, emissive=emis)

    # ---- 재질 · 기본 도형 ----
    def material(self, name, rgb, rough=0.5, metal=0.0, opacity=1.0, emissive=None):
        path = f"/World/Looks/{name}"
        m = UsdShade.Material.Define(self.stage, path)
        sh = UsdShade.Shader.Define(self.stage, f"{path}/shader")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
        sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(float(rough))
        sh.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(float(metal))
        sh.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(float(opacity))
        if opacity < 1.0:                                  # 반투명 — 굴절 없이 (유리 굴절이면 RTX 에서 검게 보인다)
            sh.CreateInput("ior", Sdf.ValueTypeNames.Float).Set(1.0)
            sh.CreateInput("opacityThreshold", Sdf.ValueTypeNames.Float).Set(0.0)
        if emissive is not None:
            sh.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*emissive))
        m.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
        self._mats[name] = (m, rgb, opacity)
        return m

    def _finish(self, prim, mat):
        if mat in self.leds:                               # 표시등 계열 → 꺼짐 재질로 시작
            mat = f"{mat}__off"
        m, rgb, opacity = self._mats[mat]
        g = UsdGeom.Gprim(prim)
        g.CreateDisplayColorAttr([Gf.Vec3f(*rgb)])
        if opacity < 1.0:
            g.CreateDisplayOpacityAttr([opacity])
            UsdGeom.PrimvarsAPI(prim).CreatePrimvar("doNotCastShadows", Sdf.ValueTypeNames.Bool).Set(True)
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(m)
        return prim

    def xform(self, path, pos=(0.0, 0.0, 0.0), rot_deg=None):
        x = UsdGeom.Xform.Define(self.stage, path)
        x.AddTranslateOp().Set(Gf.Vec3d(*pos))
        if rot_deg is not None:
            x.AddRotateXYZOp().Set(Gf.Vec3f(*rot_deg))
        return x.GetPrim()

    def box(self, path, center, size, mat, rot_deg=None):
        c = UsdGeom.Cube.Define(self.stage, path)
        c.CreateSizeAttr(1.0)
        xf = UsdGeom.Xformable(c)
        xf.AddTranslateOp().Set(Gf.Vec3d(*center))
        if rot_deg is not None:
            xf.AddRotateXYZOp().Set(Gf.Vec3f(*rot_deg))
        xf.AddScaleOp().Set(Gf.Vec3f(*size))
        return self._finish(c.GetPrim(), mat)

    def cyl(self, path, center, radius, height, mat, axis="Z"):
        c = UsdGeom.Cylinder.Define(self.stage, path)
        c.CreateRadiusAttr(radius)
        c.CreateHeightAttr(height)
        c.CreateAxisAttr(axis)
        UsdGeom.Xformable(c).AddTranslateOp().Set(Gf.Vec3d(*center))
        return self._finish(c.GetPrim(), mat)

    def sphere(self, path, center, radius, mat, scale=None):
        s = UsdGeom.Sphere.Define(self.stage, path)
        s.CreateRadiusAttr(radius)
        xf = UsdGeom.Xformable(s)
        xf.AddTranslateOp().Set(Gf.Vec3d(*center))
        if scale is not None:
            xf.AddScaleOp().Set(Gf.Vec3f(*scale))
        return self._finish(s.GetPrim(), mat)

    def cone(self, path, center, radius, height, mat, axis="Z"):
        c = UsdGeom.Cone.Define(self.stage, path)
        c.CreateRadiusAttr(radius)
        c.CreateHeightAttr(height)
        c.CreateAxisAttr(axis)
        UsdGeom.Xformable(c).AddTranslateOp().Set(Gf.Vec3d(*center))
        return self._finish(c.GetPrim(), mat)

    def _env(self, key, src=None):
        f = (src or self.L)[key]
        mn, sz = f["min"], f["size"]
        return mn, sz, [mn[i] + sz[i] / 2 for i in range(3)]

    # ---- 가전 ----
    def air_conditioner(self, root):
        """벽걸이 에어컨 실내기 (오른쪽 벽 · 방 안쪽 = −X) — 본체 · 앞 패널 · 아래 토출구 · 루버 · 표시창."""
        mn, sz, c = self._env("air_conditioner")
        x0, x1, y0, y1, z0, z1 = mn[0], mn[0] + sz[0], mn[1], mn[1] + sz[1], mn[2], mn[2] + sz[2]
        self.box(f"{root}/body", (c[0] + 0.01, c[1], c[2] + 0.01), (sz[0] - 0.02, sz[1], sz[2] - 0.02), "white_plastic")
        self.box(f"{root}/front_panel", (x0 + 0.012, c[1], c[2] + 0.03), (0.012, sz[1] - 0.02, sz[2] - 0.08), "white_plastic")
        self.box(f"{root}/top_grille", (c[0] + 0.03, c[1], z1 - 0.004), (sz[0] - 0.08, sz[1] - 0.06, 0.008), "grey_plastic")
        self.box(f"{root}/outlet", (x0 + 0.05, c[1], z0 + 0.025), (0.07, sz[1] - 0.08, 0.03), "dark_plastic")
        # 루버 — 토출구 벽 쪽 모서리에서 방 쪽으로 뻗은 판 · 회전(Y 축)은 브릿지가 바꾼다 (0 = 닫힘)
        piv = (x0 + 0.085, c[1], z0 + 0.008)
        lv = self.xform(f"{root}/louver", piv, rot_deg=(0.0, 0.0, 0.0))
        del lv
        self.box(f"{root}/louver/flap", (-0.04, 0.0, 0.0), (0.08, sz[1] - 0.09, 0.005), "white_plastic")
        self.box(f"{root}/display", (x0 + 0.005, y0 + 0.18, z0 + 0.09), (0.004, 0.08, 0.025), "lens")
        self.box(f"{root}/led", (x0 + 0.002, y0 + 0.18, z0 + 0.09), (0.003, 0.05, 0.012), "led_ac")   # 표시창 (방에서 보이게 5 × 1.2 cm)
        self.box(f"{root}/pipe_cover", (x1 - 0.02, y1 - 0.06, z0 - 0.25), (0.04, 0.05, 0.5), "white_plastic")

    def dehumidifier(self, root):
        """가정용 제습기 (앞 = −Y · 방 쪽) — 본체 · 물통 · 위 토출 그릴 · 조작부 · 바퀴."""
        mn, sz, c = self._env("dehumidifier")
        x0, y0, z0 = mn
        sx, sy, sz_ = sz
        self.box(f"{root}/body", (c[0], c[1], z0 + 0.03 + (sz_ - 0.03) / 2), (sx, sy, sz_ - 0.03), "white_plastic")
        self.box(f"{root}/tank", (c[0], y0 - 0.004, z0 + 0.04 + 0.11), (sx - 0.04, 0.01, 0.22), "grey_plastic")
        self.box(f"{root}/tank_window", (c[0] + 0.08, y0 - 0.010, z0 + 0.15), (0.03, 0.004, 0.14), "tank")
        self.box(f"{root}/tank_handle", (c[0], y0 - 0.012, z0 + 0.245), (0.12, 0.012, 0.015), "dark_plastic")
        for k in range(7):
            self.box(f"{root}/top_grille_{k}", (c[0], y0 + 0.04 + k * (sy - 0.08) / 6, z0 + sz_ + 0.002),
                     (sx - 0.05, 0.008, 0.004), "dark_plastic")
        self.box(f"{root}/panel", (c[0], y0 + 0.02, z0 + sz_ - 0.01), (sx - 0.06, 0.04, 0.012), "dark_plastic")
        self.box(f"{root}/led", (c[0] + 0.05, y0 - 0.002, z0 + sz_ - 0.035), (0.04, 0.003, 0.015), "led_dehumidifier")   # 앞면 표시창 4 × 1.5 cm
        for k in range(5):
            self.box(f"{root}/side_vent_{k}", (x0 - 0.002, c[1], z0 + 0.32 + k * 0.03), (0.004, sy - 0.08, 0.008), "grey_plastic")
        for i, (dx, dy) in enumerate(((0.04, 0.04), (sx - 0.04, 0.04), (0.04, sy - 0.04), (sx - 0.04, sy - 0.04))):
            self.sphere(f"{root}/caster_{i}", (x0 + dx, y0 + dy, z0 + 0.015), 0.015, "dark_plastic")

    def humidifier(self, root):
        """바닥형 초음파 가습기 — 받침 · 반투명 물통 · 위 덮개 · 분무구 · 분무(켜지면 보임)."""
        mn, sz, c = self._env("humidifier")
        r = min(sz[0], sz[1]) / 2
        z0, h = mn[2], sz[2]
        self.cyl(f"{root}/base", (c[0], c[1], z0 + 0.05), r, 0.10, "white_plastic")
        self.cyl(f"{root}/tank", (c[0], c[1], z0 + 0.10 + (h - 0.16) / 2), r * 0.92, h - 0.16, "tank")
        self.cyl(f"{root}/cap", (c[0], c[1], z0 + h - 0.03), r * 0.95, 0.06, "white_plastic")
        self.cyl(f"{root}/nozzle", (c[0], c[1], z0 + h + 0.012), 0.022, 0.024, "grey_plastic")
        self.box(f"{root}/led", (c[0], mn[1] + 0.002, z0 + 0.06), (0.03, 0.004, 0.012), "led_humidifier")
        mist = self.cone(f"{root}/mist", (c[0], c[1], z0 + h + 0.024 + 0.11), 0.06, 0.22, "mist")
        UsdGeom.Xformable(mist).AddRotateXOp().Set(180.0)                  # 꼭짓점이 아래(분무구) — 위로 퍼진다
        UsdGeom.Imageable(mist).CreateVisibilityAttr("invisible")          # 켜지면 브릿지가 보이게 한다

    def purifier(self, root):
        """원통형 공기청정기 — 흡입 몸통 · 위 토출 그릴 · LED 링 · 받침."""
        mn, sz, c = self._env("purifier")
        r = min(sz[0], sz[1]) / 2 - 0.005
        z0, h = mn[2], sz[2]
        self.cyl(f"{root}/plinth", (c[0], c[1], z0 + 0.012), r * 0.9, 0.024, "grey_plastic")
        self.cyl(f"{root}/body", (c[0], c[1], z0 + 0.024 + (h - 0.11) / 2), r, h - 0.11, "white_plastic")
        for k in range(10):                                               # 흡입 홈 (아래쪽 둘레)
            a = 2 * math.pi * k / 10
            self.box(f"{root}/intake_{k}", (c[0] + r * math.cos(a), c[1] + r * math.sin(a), z0 + 0.20),
                     (0.006, 0.006, 0.26), "grey_plastic")
        self.cyl(f"{root}/led_ring", (c[0], c[1], z0 + h - 0.08), r + 0.002, 0.012, "led_purifier")
        self.cyl(f"{root}/top", (c[0], c[1], z0 + h - 0.037), r, 0.074, "white_plastic")
        self.cyl(f"{root}/top_grille", (c[0], c[1], z0 + h + 0.001), r * 0.8, 0.004, "dark_plastic")
        self.box(f"{root}/display", (c[0], mn[1] + 0.004, z0 + h - 0.03), (0.06, 0.004, 0.025), "lens")

    def range_hood(self, root):
        """벽부착 침니 후드 (스테인리스) — 캐노피 · 경사부 · 굴뚝 · 기름 필터 · 후드 등 · 조작 버튼."""
        mn, sz, c = self._env("range_hood")
        x0, x1, y0, y1, z0, z1 = mn[0], mn[0] + sz[0], mn[1], mn[1] + sz[1], mn[2], mn[2] + sz[2]
        H = self.L["room"]["height_m"]
        self.box(f"{root}/canopy", (c[0], c[1], z0 + 0.04), (sz[0], sz[1], 0.08), "stainless")
        self.box(f"{root}/taper", (x1 - sz[0] * 0.35, c[1], z0 + 0.08 + (z1 - z0 - 0.08) / 2),
                 (sz[0] * 0.7, sz[1] * 0.75, z1 - z0 - 0.08), "stainless")
        self.box(f"{root}/chimney", (x1 - 0.13, c[1], z1 + (H - z1) / 2), (0.26, 0.24, H - z1), "stainless")
        for i, dy in enumerate((-0.12, 0.12)):
            self.box(f"{root}/filter_{i}", (c[0], c[1] + dy, z0 - 0.002), (sz[0] - 0.08, 0.2, 0.004), "black_metal")
        self.box(f"{root}/lamp_panel", (x0 + 0.08, c[1], z0 - 0.003), (0.06, 0.06, 0.004), "hood_lamp_panel")
        lamp = UsdLux.RectLight.Define(self.stage, f"{root}/lamp")
        lamp.CreateWidthAttr(0.06)
        lamp.CreateHeightAttr(0.06)
        lamp.CreateIntensityAttr(0.0)                                     # 화면용 — 브릿지가 켠다
        UsdGeom.Xformable(lamp).AddTranslateOp().Set(Gf.Vec3d(x0 + 0.08, c[1], z0 - 0.008))
        for k in range(3):
            self.box(f"{root}/button_{k}", (x0 - 0.002, y0 + 0.12 + k * 0.035, z0 + 0.04), (0.004, 0.02, 0.012), "dark_plastic")
        self.box(f"{root}/led", (x0 - 0.002, y0 + 0.26, z0 + 0.04), (0.003, 0.04, 0.012), "led_range_hood")   # 단 표시 (약 · 강 밝기)

    # ---- 가구 ----
    def bed(self, root):
        mn, sz, c = self._env("bed", self.L["furniture"])
        x0, y0, z0 = mn
        x1 = x0 + sz[0]
        H = sz[2]
        self.box(f"{root}/frame", (c[0], c[1], z0 + 0.13), (sz[0], sz[1], 0.22), "wood")
        self.box(f"{root}/mattress", (c[0], c[1], z0 + 0.24 + (H - 0.24) / 2), (sz[0] - 0.04, sz[1] - 0.04, H - 0.24), "mattress")
        self.box(f"{root}/headboard", (x1 - 0.03, c[1], 0.45), (0.06, sz[1], 0.90), "dark_wood")
        self.box(f"{root}/blanket", (x0 + 0.45, c[1], H + 0.015), (0.9, sz[1] - 0.02, 0.03), "blanket")
        self.sphere(f"{root}/pillow", (x1 - 0.20, c[1], H + 0.05), 0.08, "mattress", scale=(1.2, 3.0, 0.6))
        for i, (dx, dy) in enumerate(((0.04, 0.04), (sz[0] - 0.04, 0.04), (0.04, sz[1] - 0.04), (sz[0] - 0.04, sz[1] - 0.04))):
            self.box(f"{root}/leg_{i}", (x0 + dx, y0 + dy, 0.01), (0.05, 0.05, 0.02), "dark_wood")

    def desk(self, root):
        mn, sz, c = self._env("desk", self.L["furniture"])
        x0, y0, _ = mn
        H = sz[2]
        self.box(f"{root}/top", (c[0], c[1], H - 0.015), (sz[0], sz[1], 0.03), "wood")
        for i, (dx, dy) in enumerate(((0.04, 0.04), (sz[0] - 0.04, 0.04), (0.04, sz[1] - 0.04), (sz[0] - 0.04, sz[1] - 0.04))):
            self.box(f"{root}/leg_{i}", (x0 + dx, y0 + dy, (H - 0.03) / 2), (0.04, 0.04, H - 0.03), "black_metal")
        self.box(f"{root}/modesty_panel", (x0 + 0.03, c[1], H * 0.6), (0.015, sz[1] - 0.1, H * 0.5), "black_metal")
        self.box(f"{root}/laptop_base", (x0 + 0.30, c[1] + 0.05, H + 0.008), (0.24, 0.33, 0.016), "grey_plastic")
        self.box(f"{root}/laptop_screen", (x0 + 0.17, c[1] + 0.05, H + 0.12), (0.012, 0.33, 0.22), "dark_plastic",
                 rot_deg=(0.0, -15.0, 0.0))

    def chair(self, root):
        mn, sz, c = self._env("chair", self.L["furniture"])
        x1 = mn[0] + sz[0]
        H = sz[2]
        self.cyl(f"{root}/base", (c[0], c[1], 0.03), 0.26, 0.02, "black_metal")
        self.cyl(f"{root}/post", (c[0], c[1], (H - 0.04) / 2 + 0.03), 0.025, H - 0.08, "black_metal")
        self.box(f"{root}/seat", (c[0], c[1], H - 0.03), (sz[0], sz[1], 0.06), "fabric_grey")
        self.box(f"{root}/back", (x1 - 0.03, c[1], H + 0.25), (0.05, sz[1] - 0.04, 0.42), "fabric_grey", rot_deg=(0.0, -8.0, 0.0))

    def kitchen_counter(self, root):
        mn, sz, c = self._env("kitchen_counter", self.L["furniture"])
        x0, y0, _ = mn
        H = sz[2]
        self.box(f"{root}/toe_kick", (c[0] + 0.04, c[1], 0.05), (sz[0] - 0.08, sz[1], 0.10), "dark_plastic")
        self.box(f"{root}/cabinet", (c[0], c[1], 0.10 + (H - 0.13) / 2), (sz[0], sz[1], H - 0.13), "cabinet")
        self.box(f"{root}/countertop", (c[0] - 0.01, c[1], H - 0.015), (sz[0] + 0.02, sz[1] + 0.02, 0.03), "countertop")
        n = 3
        for k in range(1, n):
            self.box(f"{root}/door_seam_{k}", (x0 - 0.001, y0 + sz[1] * k / n, 0.10 + (H - 0.13) / 2), (0.002, 0.004, H - 0.15), "grey_plastic")
        for k in range(n):
            self.box(f"{root}/handle_{k}", (x0 - 0.012, y0 + sz[1] * (k + 0.5) / n, H - 0.12), (0.012, 0.10, 0.012), "stainless")
        sink_y = y0 + sz[1] - 0.22
        self.box(f"{root}/sink", (c[0], sink_y, H - 0.005), (0.40, 0.32, 0.012), "stainless")
        self.box(f"{root}/sink_basin", (c[0], sink_y, H - 0.006), (0.34, 0.26, 0.012), "black_metal")
        self.cyl(f"{root}/faucet", (x0 + sz[0] - 0.08, sink_y, H + 0.12), 0.012, 0.24, "stainless")
        self.box(f"{root}/spout", (x0 + sz[0] - 0.15, sink_y, H + 0.235), (0.15, 0.02, 0.02), "stainless")

    def cooktop(self, root):
        mn, sz, c = self._env("cooktop", self.L["furniture"])
        self.box(f"{root}/glass", (c[0], c[1], mn[2] + sz[2] / 2), (sz[0], sz[1], sz[2]), "ceramic_glass")
        for i, dy in enumerate((-sz[1] / 4, sz[1] / 4)):
            self.cyl(f"{root}/burner_{i}", (c[0], c[1] + dy, mn[2] + sz[2] + 0.0005), 0.09, 0.001, "cooktop_burner")
        self.box(f"{root}/touch_panel", (mn[0] + 0.03, c[1], mn[2] + sz[2] + 0.0005), (0.04, sz[1] - 0.1, 0.001), "grey_plastic")

    def bookshelf(self, root):
        """책장 (왼쪽 벽 · 앞 = +X) — 옆판 · 위아래 · 뒤판 · 선반 4칸 · 책."""
        mn, sz, c = self._env("bookshelf", self.L["furniture"])
        x0, y0, _ = mn
        sx, sy, H = sz
        t = 0.018
        for i, y in enumerate((y0 + t / 2, y0 + sy - t / 2)):
            self.box(f"{root}/side_{i}", (c[0], y, H / 2), (sx, t, H), "wood")
        self.box(f"{root}/back", (x0 + 0.005, c[1], H / 2), (0.01, sy, H), "dark_wood")
        n = 4
        for k in range(n + 1):
            z = 0.05 + k * (H - 0.06) / n
            self.box(f"{root}/shelf_{k}", (c[0], c[1], z), (sx - 0.01, sy - 2 * t, t), "wood")
            if k == n:
                break
            yb, j = y0 + t + 0.01, 0
            while True:                                  # 칸마다 책 — 폭 · 높이를 조금씩 다르게 (결정적)
                w = 0.025 + 0.012 * ((k * 7 + j * 3) % 4)
                h = (H - 0.06) / n * (0.62 + 0.08 * ((k + j * 5) % 4))
                if yb + w > y0 + sy - t - 0.06:
                    break
                self.box(f"{root}/book_{k}_{j}", (x0 + 0.03 + (sx - 0.08) / 2, yb + w / 2, z + t / 2 + h / 2),
                         (sx - 0.08, w, h), f"book_{(k * 2 + j) % len(BOOK_RGB)}")
                yb += w + 0.003
                j += 1

    def fridge(self, root):
        """원룸용 2도어 냉장고 (오른쪽 벽 · 앞 = −X) — 본체 · 냉동실 / 냉장실 문 · 세로 손잡이 · 받침."""
        mn, sz, c = self._env("fridge", self.L["furniture"])
        x0, y0, _ = mn
        sx, sy, H = sz
        self.box(f"{root}/body", (c[0] + 0.02, c[1], H / 2 + 0.01), (sx - 0.04, sy, H - 0.02), "fridge")
        split = H * 0.66
        self.box(f"{root}/door_fridge", (x0 + 0.015, c[1], 0.04 + (split - 0.05) / 2), (0.03, sy - 0.01, split - 0.05), "fridge")
        self.box(f"{root}/door_freezer", (x0 + 0.015, c[1], split + (H - split - 0.01) / 2), (0.03, sy - 0.01, H - split - 0.02), "fridge")
        for i, (z0_, z1_) in enumerate(((0.25, split - 0.08), (split + 0.04, split + 0.28))):
            self.box(f"{root}/handle_{i}", (x0 - 0.02, y0 + sy - 0.06, (z0_ + z1_) / 2), (0.02, 0.025, z1_ - z0_), "stainless")
        self.box(f"{root}/kick", (x0 + 0.04, c[1], 0.02), (0.02, sy - 0.04, 0.04), "dark_plastic")

    def door_hardware(self, leaf_root, door_w, dth, leaf_center_z, cfg):
        """현관문 철물 — 디지털 도어락(실내 본체 · 실외 키패드) + 레버 손잡이 (문짝 기준 · 잠금 쪽 끝)."""
        x = door_w / 2 - cfg["from_latch_edge_m"]
        zl, zh = cfg["lock_height_m"] - leaf_center_z, cfg["handle_height_m"] - leaf_center_z
        self.box(f"{leaf_root}/lock_inside", (x, dth / 2 + 0.018, zl), (0.075, 0.036, 0.26), "black_metal")
        self.box(f"{leaf_root}/lock_inside_cover", (x, dth / 2 + 0.037, zl + 0.05), (0.05, 0.004, 0.10), "dark_plastic")
        self.box(f"{leaf_root}/lock_keypad", (x, -dth / 2 - 0.011, zl), (0.07, 0.022, 0.20), "black_metal")
        self.box(f"{leaf_root}/lock_keypad_glass", (x, -dth / 2 - 0.023, zl + 0.02), (0.05, 0.003, 0.11), "lens")
        for i, sgn in enumerate((1, -1)):                # 실내 · 실외 레버
            y = sgn * (dth / 2 + 0.03)
            self.cyl(f"{leaf_root}/handle_rose_{i}", (x, sgn * (dth / 2 + 0.005), zh), 0.028, 0.01, "stainless", axis="Y")
            self.cyl(f"{leaf_root}/handle_neck_{i}", (x, y - sgn * 0.012, zh), 0.009, 0.045, "stainless", axis="Y")
            self.box(f"{leaf_root}/handle_lever_{i}", (x - 0.06, y, zh), (0.13, 0.018, 0.02), "stainless")

    def bathroom(self, root):
        """화장실 설비 — 변기(서쪽 벽 · 앞쪽) · 세면대 + 거울(앞 벽) · 샤워부스(서쪽 · 안쪽) · 바닥 배수구."""
        b = self.L["bathroom"]
        xa, xb = b["interior_x_m"]
        ya, yb = b["interior_y_m"]
        H = self.L["room"]["height_m"]
        # 변기 — 물탱크는 서쪽 벽, 앞으로 볼
        ty = ya + 0.45
        self.box(f"{root}/toilet/tank", (xa + 0.09, ty, 0.62), (0.18, 0.40, 0.36), "porcelain")
        self.cyl(f"{root}/toilet/bowl", (xa + 0.42, ty, 0.20), 0.18, 0.40, "porcelain")
        self.box(f"{root}/toilet/bowl_neck", (xa + 0.25, ty, 0.20), (0.18, 0.28, 0.40), "porcelain")
        self.cyl(f"{root}/toilet/seat", (xa + 0.42, ty, 0.415), 0.19, 0.03, "porcelain")
        self.cyl(f"{root}/toilet/lid_hinge", (xa + 0.24, ty, 0.44), 0.012, 0.16, "porcelain", axis="Y")
        self.cyl(f"{root}/toilet/flush", (xa + 0.10, ty + 0.12, 0.805), 0.015, 0.012, "stainless")
        # 세면대 — 앞 벽(y = ya), 하부장 + 세면볼 + 수전 + 거울
        vx = xb - 0.32
        self.box(f"{root}/vanity/cabinet", (vx, ya + 0.22, 0.38), (0.50, 0.44, 0.76), "cabinet")
        self.box(f"{root}/vanity/top", (vx, ya + 0.23, 0.78), (0.52, 0.46, 0.04), "porcelain")
        self.cyl(f"{root}/vanity/basin", (vx, ya + 0.25, 0.795), 0.15, 0.012, "tile")
        self.cyl(f"{root}/vanity/faucet", (vx, ya + 0.06, 0.88), 0.012, 0.16, "stainless")
        self.box(f"{root}/vanity/spout", (vx, ya + 0.11, 0.955), (0.02, 0.10, 0.02), "stainless")
        self.box(f"{root}/mirror", (vx, ya + 0.008, 1.35), (0.50, 0.012, 0.60), "mirror")
        # 샤워부스 — 서쪽 · 안쪽 (문 열리는 자리를 피한다) · 강화유리 칸막이 · 샤워기
        sx0, sx1, sy0 = xa, xa + 0.65, yb - 0.85
        self.box(f"{root}/shower/tray", ((sx0 + sx1) / 2, (sy0 + yb) / 2, 0.025), (sx1 - sx0, yb - sy0, 0.05), "porcelain")
        self.box(f"{root}/shower/glass_side", (sx1, (sy0 + yb) / 2, 1.0), (0.01, yb - sy0, 1.90), "shower_glass")
        self.box(f"{root}/shower/glass_front", (sx0 + 0.15, sy0, 1.0), (0.30, 0.01, 1.90), "shower_glass")
        self.cyl(f"{root}/shower/riser", (sx0 + 0.32, yb - 0.03, 1.40), 0.012, 1.10, "stainless")
        self.cyl(f"{root}/shower/head", (sx0 + 0.32, yb - 0.12, 2.00), 0.10, 0.02, "stainless")
        self.box(f"{root}/shower/arm", (sx0 + 0.32, yb - 0.07, 2.02), (0.02, 0.10, 0.02), "stainless")
        self.cyl(f"{root}/shower/mixer", (sx0 + 0.32, yb - 0.02, 1.05), 0.035, 0.05, "stainless", axis="Y")
        self.cyl(f"{root}/drain", ((sx0 + sx1) / 2, (sy0 + yb) / 2, 0.052), 0.05, 0.004, "black_metal")
        self.box(f"{root}/towel_bar", (xb - 0.02, ya + 0.75, 1.20), (0.02, 0.50, 0.02), "stainless")
        self.box(f"{root}/towel", (xb - 0.04, ya + 0.75, 1.02), (0.02, 0.40, 0.36), "mattress")
        del H

    def bathroom_door_hardware(self, root, width, thickness, handle_z):
        """화장실 문 손잡이 (문짝 강체 기준 · 문짝 중심 원점 · 문짝은 Y 방향으로 width) — 경첩 반대쪽 끝(−Y)."""
        for i, sgn in enumerate((1, -1)):
            self.cyl(f"{root}/handle_rose_{i}", (sgn * (thickness / 2 + 0.004), -width / 2 + 0.07, handle_z), 0.025, 0.008, "stainless", axis="X")
            self.box(f"{root}/handle_lever_{i}", (sgn * (thickness / 2 + 0.03), -width / 2 + 0.12, handle_z), (0.018, 0.12, 0.02), "stainless")

    # ---- 센서 (실제 모듈 크기 근사 · 하우징 포함) ----
    def sensor(self, root, name):
        if name == "mmwave_sensor":            # HLK-LD2410 (22 × 16 mm) 하우징 · 앞(+Y)에 레이돔
            self.box(f"{root}/housing", (0, 0, 0), (0.06, 0.02, 0.045), "white_plastic")
            self.box(f"{root}/radome", (0, 0.011, 0), (0.04, 0.003, 0.03), "lens")
        elif name == "ceiling_sensor_hub":     # v0.2 천장 센서 박스 — 온습도(옆면 통풍구) + 조도(아랫면 확산 돔) 한 함체
            sx, sy, sz = self.L["ceiling_sensor_hub"]["size_m"]
            self.box(f"{root}/housing", (0, 0, 0), (sx, sy, sz), "white_plastic")
            for k in range(5):                                 # 옆면 통풍 슬롯 (온습도 — 공기가 지나가게)
                for side in (-1, 1):
                    self.box(f"{root}/vent_{'lr'[side > 0]}{k}", (side * sx / 2, -sy / 3 + k * sy / 6, 0), (0.002, 0.008, sz * 0.5), "dark_plastic")
            self.sphere(f"{root}/light_dome", (sx / 4, 0, -sz / 2), 0.008, "white_plastic", scale=(1.0, 1.0, 0.6))   # 조도 창 (아래를 봄)
            self.box(f"{root}/status_led", (-sx / 3, sy / 3, -sz / 2 - 0.0005), (0.004, 0.004, 0.001), "led_hub")
        elif name == "temp_humidity_sensor":   # 천장 부착 통풍형 온습도 센서 (SHT3x 계열)
            self.box(f"{root}/housing", (0, 0, 0), (0.06, 0.06, 0.022), "white_plastic")
            for k in range(4):
                self.box(f"{root}/vent_{k}", (-0.02 + k * 0.013, 0.0, -0.0115), (0.005, 0.045, 0.002), "dark_plastic")
        elif name == "illuminance_sensor":     # BH1750 모듈 + 확산 돔 (아래를 봄)
            self.box(f"{root}/pcb", (0, 0, 0), (0.032, 0.020, 0.0016), "pcb")
            self.sphere(f"{root}/dome", (0, 0, -0.004), 0.006, "white_plastic")
        elif name == "pm25_sensor":            # 레이저 PM 센서(PMS 계열) 벽부착 하우징 · 앞(+X)에 흡입구
            self.box(f"{root}/housing", (0, 0, 0), (0.03, 0.07, 0.05), "white_plastic")
            self.cyl(f"{root}/inlet", (0.016, -0.015, 0.0), 0.007, 0.004, "dark_plastic", axis="X")
            self.cyl(f"{root}/outlet", (0.016, 0.018, 0.0), 0.009, 0.004, "dark_plastic", axis="X")
        elif name == "hood_temperature_sensor":   # NTC 프로브 + 작은 하우징 (후드 아래)
            self.box(f"{root}/housing", (0, 0, 0.004), (0.03, 0.02, 0.01), "black_metal")
            self.cyl(f"{root}/probe", (0, 0, -0.018), 0.003, 0.035, "stainless")

    # ---- 팬 하우징 (mount 아래 · 회전체는 build_scene) ----
    def wall_fan_housing(self, root, diameter, axis, intake=False, room_side=-1):
        s = diameter + 0.06
        t = 0.05
        n_ax = 0 if axis == "X" else 1
        def v(a, b, c_):                           # 축 방향 a · 가로 b · 세로 c
            return (a, b, c_) if n_ax == 0 else (b, a, c_)
        for i, sgn in enumerate((-1, 1)):
            self.box(f"{root}/frame_side_{i}", v(0, sgn * (s / 2 - 0.015), 0), v(t, 0.03, s), "white_plastic")
            self.box(f"{root}/frame_tb_{i}", v(0, 0, sgn * (s / 2 - 0.015)), v(t, s, 0.03), "white_plastic")
        side = room_side                                     # 실내 쪽 (배기: 화장실 쪽 +X · 흡기: 방 쪽 −Y)
        for k in range(5):
            self.box(f"{root}/grille_{k}", v(side * 0.028, 0, -diameter / 2 + (k + 0.5) * diameter / 5), v(0.004, diameter, 0.006), "grey_plastic")
        self.cyl(f"{root}/hub_cover", v(side * 0.03, 0, 0), 0.03, 0.01, "white_plastic", axis=axis)
        if intake:                                           # 필터 카세트 (방 쪽) — 주름 필터
            self.box(f"{root}/filter_cassette", v(side * 0.06, 0, 0), v(0.04, s, s), "white_plastic")
            for k in range(9):
                self.box(f"{root}/filter_pleat_{k}", v(side * 0.081, -s / 2 + 0.03 + k * (s - 0.06) / 8, 0), v(0.003, 0.006, s - 0.05), "filter")

    def ceiling_fan_housing(self, root, pos):
        H = self.L["room"]["height_m"]
        z = pos[2]
        self.cyl(f"{root}/canopy", (0, 0, H - z - 0.02), 0.07, 0.04, "white_plastic")
        self.cyl(f"{root}/downrod", (0, 0, (H - 0.04 - z) / 2 - 0.03), 0.012, H - 0.04 - z + 0.06, "white_plastic")
        self.cyl(f"{root}/motor", (0, 0, -0.06), 0.11, 0.07, "white_plastic")

    def window_motor(self, root):
        """창문 기어드 DC 모터 (패널 하단) — 모터 캔 · 기어박스 · 피니언 (전류 센서는 모터 드라이버 안)."""
        self.box(f"{root}/gearbox", (0.02, 0.0, 0.0), (0.05, 0.035, 0.05), "black_metal")
        self.cyl(f"{root}/motor_can", (-0.025, 0.0, 0.0), 0.017, 0.05, "stainless", axis="X")
        self.cyl(f"{root}/pinion", (0.02, 0.0, -0.03), 0.010, 0.012, "black_metal", axis="Y")

    def window_controller(self, root):
        """창문 제어 박스 (방 쪽 창턱 끝 · 블라인드 앞) — 모터 드라이버 · 전류 감지 · 안전 상태 LED. 모터 LED 는 블라인드에 가려 방에서 보이지 않는다."""
        self.box(f"{root}/housing", (0, 0, 0.015), (0.08, 0.05, 0.03), "white_plastic")
        self.box(f"{root}/status_led", (0.02, -0.005, 0.0305), (0.025, 0.02, 0.002), "led_window")
        self.box(f"{root}/unlock_button", (-0.022, -0.005, 0.0305), (0.016, 0.016, 0.002), "grey_plastic")   # WINDOW_UNLOCK (사용자 해제)

    def desk_lamp(self, root):
        self.cyl(f"{root}/base", (-0.06, 0, -0.41 + 0.008), 0.07, 0.016, "black_metal")   # 책상면(조명 위치 − 0.41 m) 위
        self.cyl(f"{root}/stem", (-0.06, 0, -0.205), 0.008, 0.39, "black_metal")
        self.box(f"{root}/arm", (-0.03, 0, 0.012), (0.07, 0.012, 0.012), "black_metal")
        self.cone(f"{root}/shade", (0, 0, 0.065), 0.08, 0.09, "lamp_shade")

    def character(self, root, pp) -> bool:
        """Isaac Sim 사람 캐릭터 (에셋 서버) — T 자세에서 위팔을 내린 서 있는 자세를 메시에 구워(UsdSkel 베이크) 참조한다.
        에셋 서버 애니메이션은 공용 골격용(리타깃 필요)이라 바로 입혀지지 않아(2026-10-15 확인) 자세를 직접 만든다.
        결과는 worlds/cache/ (git 제외 · NVIDIA 에셋 파생 데이터) — build_scene 을 다시 돌리면 새로 만든다.
        원점 = 캡슐 중심(키의 절반) → 발이 바닥에 닿게 내린다. 에셋 서버에 연결할 수 없으면 False (마네킹으로 대체)."""
        ch = pp.get("character")
        if not ch:
            return False
        try:
            from isaacsim.storage.native import get_assets_root_path
            from pxr import Gf as _Gf, Usd, UsdSkel, Vt
            base = get_assets_root_path()
            if not base:
                return False
            scene_dir = self.stage.GetRootLayer().realPath.rsplit("/", 1)[0]
            rel = f"cache/{ch['usd'].rsplit('/', 1)[1].replace('.usd', '')}_idle.usd"
            bake = Usd.Stage.CreateNew(f"{scene_dir}/{rel}")
            UsdGeom.SetStageUpAxis(bake, UsdGeom.Tokens.z)
            UsdGeom.SetStageMetersPerUnit(bake, 1.0)
            top = bake.DefinePrim("/Character", "Xform")
            top.GetReferences().AddReference(base + ch["usd"])
            roots = [p for p in Usd.PrimRange(top) if p.IsA(UsdSkel.Root)]
            skels = [UsdSkel.Skeleton(p) for p in Usd.PrimRange(top) if p.IsA(UsdSkel.Skeleton)]
            # 에셋 서버 애니메이션은 공용(Biped) 골격용이라 이 캐릭터 관절과 맞지 않는다(리타깃 필요) —
            # 캐릭터 자체 골격의 쉬는 자세(T 자세)에서 위팔만 어깨를 중심으로 몸 쪽으로 내려 '서 있는 자세'를 만든다
            ok = False
            for sk in skels:
                joints = list(sk.GetJointsAttr().Get())
                rest = list(sk.GetRestTransformsAttr().Get())
                topo = UsdSkel.Topology(joints)
                world = UsdSkel.ConcatJointTransforms(topo, rest)
                idx = {j.rsplit("/", 1)[-1]: i for i, j in enumerate(joints)}
                down = (world[idx[ch["pose"]["hip_joint"]]].ExtractTranslation()
                        - world[idx[ch["pose"]["chest_joint"]]].ExtractTranslation()).GetNormalized()
                new_world = list(world)
                for arm, fore in ch["pose"]["arms"]:
                    i, k = idx[arm], idx[fore]
                    p0 = world[i].ExtractTranslation()
                    d = (world[k].ExtractTranslation() - p0).GetNormalized()
                    side = (d - down * (d * down)).GetNormalized()
                    a_ = math.radians(ch["pose"]["arm_out_deg"])
                    tgt = (down * math.cos(a_) + side * math.sin(a_)).GetNormalized()
                    R = _Gf.Matrix4d().SetRotate(_Gf.Rotation(d, tgt))
                    M = _Gf.Matrix4d().SetTranslate(-p0) * R * _Gf.Matrix4d().SetTranslate(p0)
                    sub = [j for j in range(len(joints)) if joints[j] == joints[i] or joints[j].startswith(joints[i] + "/")]
                    for j in sub:                              # 위팔 아래 관절 전체를 같은 회전으로 (자식은 따라온다)
                        new_world[j] = world[j] * M
                parents = topo.GetParentIndices()
                local = [new_world[j] * (new_world[parents[j]].GetInverse() if parents[j] >= 0 else _Gf.Matrix4d(1.0))
                         for j in range(len(joints))]
                anim = UsdSkel.Animation.Define(bake, f"/StandPose_{len(new_world)}_{skels.index(sk)}")
                anim.CreateJointsAttr(joints)
                anim.SetTransforms(Vt.Matrix4dArray(local), Usd.TimeCode.Default())
                UsdSkel.BindingAPI.Apply(sk.GetPrim()).CreateAnimationSourceRel().SetTargets([anim.GetPath()])
                ok = True
            f = 0.0
            ok = ok and UsdSkel.BakeSkinning(Usd.PrimRange(top), _Gf.Interval(f, f))
            for p in roots:                                   # 베이크한 메시를 다시 스키닝하지 않게 — SkelRoot 를 일반 Xform 으로
                p.SetTypeName("Xform")
            bake.SetDefaultPrim(top)
            bake.GetRootLayer().Save()
            if not ok:
                return False
        except Exception as exc:
            print(f"사람 캐릭터 실패 — 마네킹으로 대체: {exc}", flush=True)
            return False
        x = self.xform(root, (0.0, 0.0, -pp["height_m"] / 2), rot_deg=(0.0, 0.0, float(ch.get("yaw_deg", 0.0))))
        x.GetReferences().AddReference(f"./{rel}")
        print(f"사람 캐릭터: {ch['usd']} · 위팔을 내린 서 있는 자세로 베이크 → worlds/{rel}", flush=True)
        return True

    def mannequin(self, root, height):
        """사람 대용 — 마네킹 모양 (충돌 · 위치 판정은 build_scene 의 캡슐 그대로 · 원점 = 키의 절반 높이)."""
        h = height
        z = lambda f: -h / 2 + f * h                    # noqa: E731 — 발(0) ~ 머리끝(1) 비율 → 원점 기준 높이
        for i, dy in enumerate((-0.09, 0.09)):
            self.cyl(f"{root}/leg_{i}", (0, dy, z(0.24)), 0.065, h * 0.48, "pants")
            self.box(f"{root}/shoe_{i}", (0.04, dy, z(0.015)), (0.24, 0.10, 0.06), "dark_plastic")
            self.cyl(f"{root}/arm_{i}", (0, dy * 2.55, z(0.62)), 0.04, h * 0.33, "shirt")
            self.sphere(f"{root}/hand_{i}", (0, dy * 2.55, z(0.44)), 0.045, "skin")
        self.box(f"{root}/torso", (0, 0, z(0.63)), (0.22, 0.38, h * 0.32), "shirt")
        self.cyl(f"{root}/neck", (0, 0, z(0.81)), 0.045, h * 0.05, "skin")
        self.sphere(f"{root}/head", (0, 0, z(0.89)), 0.105, "skin", scale=(1.0, 0.9, 1.15))

    def door_contact(self, sensor_root, leaf_root, leaf_center, sensor_pos):
        """리드 스위치 문 열림 센서 — 본체(문틀 · 문 열리는 쪽 끝 너머 벽면) + 자석(문짝 실내 면 끝)."""
        self.box(f"{sensor_root}/body", (0.07, 0.026, 0), (0.014, 0.012, 0.07), "white_plastic")
        rel = tuple(sensor_pos[i] - leaf_center[i] for i in range(3))
        self.box(f"{leaf_root}/contact_magnet", (rel[0] + 0.02, rel[1] + 0.026, rel[2]), (0.012, 0.012, 0.05), "white_plastic")
