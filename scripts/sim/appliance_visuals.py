"""가전 · 창문 표시 (Scene v0.3 · 2026-10-16) — 상태 토픽을 Scene 의 렌더 전용 프림에 반영한다 (물리 · 판정과 무관).

isaac_actuator_bridge 가 /studio/state/{ac, dehumidifier, humidifier, purifier_level, range_hood_level, safety_state} ·
/studio/sensor/appliance_power 를 받아 on_state() 를 부른다. 프림 · 재질은 tools/isaac/scene_props.py 가 만든다.

표시등은 **상태별 재질을 미리 만들어 두고 바꿔 끼운다** (`<계열>__<상태>`). 물리 World 가 도는 동안 셰이더 값(발광색)을 바꾸면
렌더에 반영되지 않거나 들쭉날쭉했다 — 2026-10-16 녹화 실험: 값 변경 0 px · 재질 교체 확실. 색 · 밝기는 config/scene_layout.yaml indicators.
"""

from __future__ import annotations

import json
from typing import Any

from pxr import Gf, Usd, UsdGeom, UsdLux, UsdShade

from interfaces import topics as T

AP = "/World/appliances"
LOOKS = "/World/Looks"


def led_states(cfg: dict) -> dict[str, dict[str, tuple[tuple, tuple]]]:
    """표시등 계열 → {상태: (바탕색, 발광색)} — scene_props(재질 생성)와 ApplianceVisuals(교체)가 같은 표를 쓴다."""
    k = float(cfg["led_emissive_scale"])
    off = tuple(cfg["off_rgb"])
    dark = (0.06, 0.06, 0.07)

    def lit(rgb, s=k, level=1.0):
        return (tuple(rgb), tuple(v * s * level for v in rgb))

    hood_max = int(cfg["range_hood"]["max_level"])
    ws = cfg["window_safety"]
    kw = float(ws.get("emissive_scale", k))
    kc = float(cfg["cooktop"].get("emissive_scale", k))
    return {
        "led_ac": {"off": (dark, off), **{m: lit(rgb) for m, rgb in cfg["ac"]["mode_rgb"].items()}},
        "led_dehumidifier": {"off": (dark, off), "on": lit(cfg["dehumidifier"]["on_rgb"])},
        "led_humidifier": {"off": (dark, off), "on": lit(cfg["humidifier"]["on_rgb"])},
        "led_purifier": {"off": (dark, off), **{f"l{n}": lit(cfg["purifier"]["on_rgb"], level=n / 3.0) for n in (1, 2, 3)}},
        "led_range_hood": {"off": (dark, off), **{f"l{n}": lit(cfg["range_hood"]["on_rgb"], level=n / hood_max)
                                                  for n in range(1, hood_max + 1)}},
        "hood_lamp_panel": {"off": (dark, off), "on": lit(cfg["range_hood"]["lamp_rgb"])},
        "cooktop_burner": {"off": ((0.22, 0.10, 0.08), off), "on": ((0.22, 0.10, 0.08), lit(cfg["cooktop"]["glow_rgb"], kc)[1])},
        "led_window": {"off": (dark, off), "normal": lit(ws["normal_rgb"], kw), "alarm": lit(ws["alarm_rgb"], kw),
                       "locked": lit(ws["locked_rgb"], kw)},
        "led_hub": {"off": (dark, off)},
    }


class ApplianceVisuals:
    def __init__(self, stage, layout: dict, log=None):
        self.stage = stage
        self.cfg = layout["indicators"]
        self.log = log or (lambda msg: None)
        self._last: dict[str, Any] = {}
        self.families = led_states(self.cfg)
        # 계열마다 그 재질을 쓰는 프림 (장면을 열 때 한 번) — 처음엔 '<계열>__off' 가 붙어 있다
        self.prims: dict[str, list] = {f: [] for f in self.families}
        for p in Usd.PrimRange(stage.GetPrimAtPath("/World")):
            if not p.IsA(UsdGeom.Gprim):
                continue
            mat, _ = UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial()
            name = str(mat.GetPath()).rsplit("/", 1)[-1] if mat else ""
            fam = name.split("__", 1)[0]
            if "__" in name and fam in self.prims:
                self.prims[fam].append(p)
        self.ok = any(self.prims.values())                    # v0.2 이전 Scene 이면 아무것도 안 한다

    def _set(self, family: str, state: str) -> None:
        m = UsdShade.Material(self.stage.GetPrimAtPath(f"{LOOKS}/{family}__{state}"))
        if not m:
            return
        for p in self.prims.get(family, []):
            UsdShade.MaterialBindingAPI(p).Bind(m)

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
        if not self.ok or self._last.get(topic) == value:   # 같은 값 반복(1 Hz 전력 · 20 Hz 상태)은 건너뛴다
            return
        self._last[topic] = value
        self.log(f"표시 갱신 {topic.rsplit('/', 1)[-1]} = {value}")
        c = self.cfg
        if topic == T.T_AC:
            d = json.loads(value) if isinstance(value, str) else dict(value)
            power = bool(d.get("power"))
            mode = str(d.get("mode"))
            self._set("led_ac", (mode if mode in c["ac"]["mode_rgb"] else "fan") if power else "off")
            self._rot(f"{AP}/air_conditioner/visual/louver", c["ac"]["louver_open_deg"] if power else 0.0)
        elif topic == T.T_DEHUMIDIFIER:
            self._set("led_dehumidifier", "on" if value else "off")
        elif topic == T.T_HUMIDIFIER:
            self._set("led_humidifier", "on" if value else "off")
            self._visible(f"{AP}/humidifier/visual/mist", bool(value))
        elif topic == T.T_PURIFIER_LEVEL:
            n = min(3, max(0, int(value)))
            self._set("led_purifier", f"l{n}" if n else "off")
        elif topic == T.T_RANGE_HOOD_LEVEL:
            n = min(int(c["range_hood"]["max_level"]), max(0, int(value)))
            self._set("led_range_hood", f"l{n}" if n else "off")
            self._set("hood_lamp_panel", "on" if n else "off")
            lamp = UsdLux.RectLight(self.stage.GetPrimAtPath(f"{AP}/range_hood/visual/lamp"))
            if lamp:
                lamp.GetIntensityAttr().Set(float(c["range_hood"]["lamp_intensity"]) if n else 0.0)
        elif topic == T.S_APPLIANCE_POWER:                    # 쿡탑 — 계량 플러그 전력 (요리 중 · 차단되면 0)
            d = json.loads(value) if isinstance(value, str) else dict(value)
            self._set("cooktop_burner", "on" if float(d.get("cooktop", 0.0)) > float(c["cooktop"]["on_w"]) else "off")
        elif topic == T.T_SAFETY_STATE:                       # 창문 안전 계층 — 정상 초록 · 끼임 반전 / 정지 유지 빨강 · 잠금 주황
            s = str(value)
            self._set("led_window", "alarm" if ("PINCH_REVERSE" in s or "SAFETY_HOLD" in s) else "locked" if "LOCKED" in s else "normal")

    TOPICS = (T.T_AC, T.T_DEHUMIDIFIER, T.T_HUMIDIFIER, T.T_PURIFIER_LEVEL, T.T_RANGE_HOOD_LEVEL,
              T.S_APPLIANCE_POWER, T.T_SAFETY_STATE)
