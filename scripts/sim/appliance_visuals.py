"""가전 표시등 · 루버 · 분무 (v0.2 · 2026-10-15) — 가전 상태 토픽을 Scene 의 렌더 전용 프림에 반영한다 (물리 · 판정과 무관).

isaac_actuator_bridge 가 /studio/state/{ac, dehumidifier, humidifier, purifier_level, range_hood_level} 을 받아 on_state() 를 부른다.
프림은 tools/isaac/scene_props.py 가 만든다 · 색 · 각도 · 밝기는 config/scene_layout.yaml indicators.
"""

from __future__ import annotations

import json
from typing import Any

from pxr import Gf, UsdGeom, UsdLux, UsdShade

from interfaces import topics as T

AP = "/World/appliances"


class ApplianceVisuals:
    def __init__(self, stage, layout: dict):
        self.stage = stage
        self.cfg = layout["indicators"]
        self.scale = float(self.cfg["led_emissive_scale"])
        self.off = tuple(self.cfg["off_rgb"])
        self.ok = stage.GetPrimAtPath(f"{AP}/air_conditioner/visual/louver").IsValid()   # v0.1 Scene 이면 아무것도 안 한다
        self._last: dict[str, Any] = {}

    def _led(self, name: str, rgb, level: float = 1.0) -> None:
        sh = UsdShade.Shader(self.stage.GetPrimAtPath(f"/World/Looks/{name}/shader"))
        if not sh:
            return
        on = rgb is not None and level > 0
        c = tuple(v * self.scale * level for v in rgb) if on else self.off
        sh.GetInput("emissiveColor").Set(Gf.Vec3f(*c))

    def _rot(self, path: str, deg: float) -> None:
        p = self.stage.GetPrimAtPath(path)
        if p.IsValid():
            for op in UsdGeom.Xformable(p).GetOrderedXformOps():
                if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                    op.Set(Gf.Vec3f(0.0, float(deg), 0.0))

    def _visible(self, path: str, on: bool) -> None:
        p = self.stage.GetPrimAtPath(path)
        if p.IsValid():
            UsdGeom.Imageable(p).GetVisibilityAttr().Set("inherited" if on else "invisible")

    def on_state(self, topic: str, value: Any) -> None:
        if not self.ok or self._last.get(topic) == value:
            return
        self._last[topic] = value
        c = self.cfg
        if topic == T.T_AC:
            d = json.loads(value) if isinstance(value, str) else dict(value)
            power = bool(d.get("power"))
            self._led("led_ac", c["ac"]["mode_rgb"].get(str(d.get("mode")), c["ac"]["mode_rgb"]["fan"]) if power else None)
            self._rot(f"{AP}/air_conditioner/visual/louver", c["ac"]["louver_open_deg"] if power else 0.0)
        elif topic == T.T_DEHUMIDIFIER:
            self._led("led_dehumidifier", c["dehumidifier"]["on_rgb"] if value else None)
        elif topic == T.T_HUMIDIFIER:
            self._led("led_humidifier", c["humidifier"]["on_rgb"] if value else None)
            self._visible(f"{AP}/humidifier/visual/mist", bool(value))
        elif topic == T.T_PURIFIER_LEVEL:
            self._led("led_purifier", c["purifier"]["on_rgb"], max(0, int(value)) / 3.0)
        elif topic == T.T_RANGE_HOOD_LEVEL:
            on = int(value) > 0
            self._led("led_range_hood", c["range_hood"]["on_rgb"] if on else None)
            self._led("hood_lamp_panel", c["range_hood"]["lamp_rgb"] if on else None)
            lamp = UsdLux.RectLight(self.stage.GetPrimAtPath(f"{AP}/range_hood/visual/lamp"))
            if lamp:
                lamp.GetIntensityAttr().Set(float(c["range_hood"]["lamp_intensity"]) if on else 0.0)

    TOPICS = (T.T_AC, T.T_DEHUMIDIFIER, T.T_HUMIDIFIER, T.T_PURIFIER_LEVEL, T.T_RANGE_HOOD_LEVEL)
