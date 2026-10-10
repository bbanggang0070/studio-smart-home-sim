"""고속 모드의 '세계' — 환경 참값 모델을 토픽 계약(docs/02 §6)으로 감싼다.

물리 모드에서 Isaac Sim + ROS 노드가 하는 일을 대신한다:
  센서 노드  : 참값 → /studio/sensor/* (v0.1 은 노이즈 없음 — 센서 모델은 W07)
  브릿지     : /studio/cmd/* → 액추에이터 목표 (가전 보호 L0 · IR 역확인은 W06 · W10 에서 이 자리에 들어온다)
  액추에이터 : 창문 · 블라인드 · 팬은 1차 지연, 가전은 즉시 (docs/03 §5.3)
  상태 발행  : 실제 동작값 → /studio/state/*
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from typing import Any

from env_model import AcCommand, ActuatorCommands, ExternalConditions, Occupancy, RoomModel
from interfaces import topics as T

# 명령 토픽 → ActuatorCommands 필드 (스칼라만; AC 는 JSON 으로 따로 처리)
CMD_TO_FIELD = {
    T.C_WINDOW_OPEN_RATIO: ("window_open_ratio", float),
    T.C_BLIND_ANGLE: ("blind_angle_deg", float),
    T.C_FAN_RPM: ("exhaust_fan_rpm", float),
    T.C_INTAKE_FAN_RPM: ("intake_fan_rpm", float),
    T.C_RANGE_HOOD_LEVEL: ("range_hood_level", int),
    T.C_PURIFIER_LEVEL: ("purifier_level", int),
    T.C_DEHUMIDIFIER: ("dehumidifier", bool),
    T.C_HUMIDIFIER: ("humidifier", bool),
    T.C_CEILING_FAN: ("ceiling_fan", int),
    T.C_CEILING_LIGHT: ("ceiling_light_pct", float),
    T.C_DESK_LIGHT: ("desk_light_pct", float),
}
FIELD_TO_STATE = {
    "window_open_ratio": T.T_WINDOW_OPEN_RATIO,
    "blind_angle_deg": T.T_BLIND_ANGLE,
    "exhaust_fan_rpm": T.T_FAN_RPM,
    "intake_fan_rpm": T.T_INTAKE_FAN_RPM,
    "range_hood_level": T.T_RANGE_HOOD_LEVEL,
    "purifier_level": T.T_PURIFIER_LEVEL,
    "dehumidifier": T.T_DEHUMIDIFIER,
    "humidifier": T.T_HUMIDIFIER,
    "ceiling_fan": T.T_CEILING_FAN,
    "ceiling_light_pct": T.T_CEILING_LIGHT,
    "desk_light_pct": T.T_DESK_LIGHT,
}
# 장치 이름(가전 프로파일) → 그 장치를 움직이는 필드
DEVICE_FIELDS = {
    "window": ("window_open_ratio",),
    "blind": ("blind_angle_deg",),
    "exhaust_fan": ("exhaust_fan_rpm",),
    "intake_fan": ("intake_fan_rpm",),
    "range_hood": ("range_hood_level",),
    "purifier": ("purifier_level",),
    "dehumidifier": ("dehumidifier",),
    "humidifier": ("humidifier",),
    "ceiling_fan": ("ceiling_fan",),
    "ceiling_light": ("ceiling_light_pct",),
    "desk_lamp": ("desk_light_pct",),
    "ac": ("ac",),
}


@dataclass
class WorldInputs:
    """시나리오가 주는 세계 상태 (센서가 아니라 참값 · 외부 입력)."""

    ext: ExternalConditions
    raining: bool
    occupancy: bool
    occupants: int
    occupant_zone: str
    user_mode: str
    activity: str
    illuminance_lux: float
    motion: str = "still"          # still | moving | sleeping — mmWave 신호 합성
    phone: str = "person"          # person(들고 다님) | home(두고 나감)

    @classmethod
    def from_scenario(cls, sc: dict[str, Any]) -> "WorldInputs":
        ini, ext = sc["initial"], sc["external"]
        return cls(
            ext=ExternalConditions(
                outdoor_temp_c=float(ext["outdoor_temp_c"]),
                outdoor_rh_pct=float(ext["outdoor_rh_pct"]),
                outdoor_pm25_ugm3=float(ext.get("outdoor_pm25_ugm3", 12.0)),
                outdoor_illuminance_lux=float(ext.get("outdoor_illuminance_lux", 0.0)),
                wind_speed_ms=float(ext.get("wind_speed_ms", -1.0)),
                heating_setpoint_c=float(ext.get("heating_setpoint_c", -1.0)),
            ),
            raining=ext.get("weather") == "rain",
            occupancy=bool(ini.get("occupancy", True)),
            occupants=int(ini.get("occupants", 1)),
            occupant_zone=str(ini.get("occupant_zone", "room")),
            user_mode=str(ini.get("user_mode", "NORMAL")),
            activity=str(ini.get("activity", "")),
            illuminance_lux=float(ini.get("illuminance_lux", 0.0)),
            motion=str(ini.get("motion", "sleeping" if ini.get("user_mode") == "SLEEP" else "still")),
            phone=str(ini.get("phone", "person")),
        )

    def apply(self, changes: dict[str, Any]) -> None:
        for key, val in changes.items():
            if key == "weather":
                self.raining = val == "rain"
            elif hasattr(self.ext, key):
                setattr(self.ext, key, float(val))
            elif key == "illuminance_lux":
                self.illuminance_lux = float(val)
            elif hasattr(self, key):
                setattr(self, key, type(getattr(self, key))(val))

    def occupancy_model(self) -> Occupancy:
        if not self.occupancy:
            return Occupancy(count=0)
        return Occupancy(count=self.occupants, activity="sleeping" if self.user_mode == "SLEEP" else "seated")


def initial_actuators(sc: dict[str, Any]) -> ActuatorCommands:
    ini = sc["initial"]
    app = ini.get("appliances") or {}
    ac = app.get("ac") or {}
    return ActuatorCommands(
        window_open_ratio=float(ini.get("window_open_ratio", 0.0)),
        blind_angle_deg=float(ini.get("blind_angle_deg", 0.0)),
        exhaust_fan_rpm=float(app.get("exhaust_fan_rpm", 0.0)),
        intake_fan_rpm=float(app.get("intake_fan_rpm", 0.0)),
        range_hood_level=int(app.get("range_hood_level", 0)),
        purifier_level=int(app.get("purifier_level", 0)),
        ac=AcCommand(power=bool(ac.get("power", False)), mode=str(ac.get("mode", "cool")),
                     setpoint_c=float(ac.get("setpoint", 26.0))),
        dehumidifier=bool(app.get("dehumidifier", False)),
        humidifier=bool(app.get("humidifier", False)),
        ceiling_fan=int(app.get("ceiling_fan", 0)),
        ceiling_light_pct=float(app.get("ceiling_light_pct", 0.0)),
        desk_light_pct=float(app.get("desk_light_pct", 0.0)),
    )


class FastActuators:
    """명령 → 목표 → 실제 동작값. 프로파일에 없는 장치 명령은 무시하고 기록한다."""

    def __init__(self, initial: ActuatorCommands, time_constants: dict[str, float], devices: list[str]):
        self.actual = replace(initial, ac=replace(initial.ac))
        self.target = replace(initial, ac=replace(initial.ac))
        self.tau = time_constants
        self.allowed = {f for d in devices for f in DEVICE_FIELDS.get(d, ())}
        self.allowed_devices = set(devices)
        self.rejected: dict[str, int] = {}
        self.ac_fan = "auto"                          # 참값 모델은 풍량을 쓰지 않지만 소음 제약 판정용으로 기록한다
        self.cooktop_relay = True                     # 플러그형 인덕션 계량 플러그 (false = 차단)
        # 가전 브릿지 (L0 자리) — IR 기기는 명령이 바뀔 때만 송신 · 수신 실패 확률 · 송신 횟수
        self.ir_devices = {"ac": T.C_AC, "purifier": T.C_PURIFIER_LEVEL}
        self.ir_last: dict[str, Any] = {}
        self.ir_tx: dict[str, int] = {"ac": 0, "purifier": 0}
        self.ir_miss_p = 0.0
        self.rng = None
        self.cmd_log: list[tuple[str, float]] = []    # (기기, 시각) — 전력 감시 노드의 원인 판정용
        self.desk_cct = 0.0

    def command(self, cmds: dict[str, Any], now: float = 0.0) -> None:
        for topic, value in cmds.items():
            if topic == T.C_DESK_LIGHT_CCT:
                self.desk_cct = float(value)
                continue
            dev = next((d for d, tp in self.ir_devices.items() if tp == topic), None)
            if dev is not None:                       # IR — 바뀐 명령만 송신, 수신 실패면 기기는 모른다
                if self.ir_last.get(dev) == value:
                    continue
                self.ir_last[dev] = value
                self.ir_tx[dev] += 1
                self.cmd_log.append((dev, now))
                if self.rng is not None and self.rng.random() < self.ir_miss_p:
                    continue
            elif topic in (T.C_DEHUMIDIFIER, T.C_HUMIDIFIER):
                name = "dehumidifier" if topic == T.C_DEHUMIDIFIER else "humidifier"
                if bool(getattr(self.target, name)) != bool(value):
                    self.cmd_log.append((name, now))
            if topic == T.C_COOKTOP_POWER:
                if "cooktop_plug" in self.allowed_devices:
                    self.cooktop_relay = bool(value)
                else:
                    self.rejected[topic] = self.rejected.get(topic, 0) + 1
                continue
            if topic == T.C_AC:
                field_name = "ac"
            elif topic in CMD_TO_FIELD:
                field_name = CMD_TO_FIELD[topic][0]
            else:
                continue   # 상태 · 사용자 토픽 등 — 액추에이터가 아님
            if field_name not in self.allowed:
                self.rejected[topic] = self.rejected.get(topic, 0) + 1
                continue
            if field_name == "ac":
                d = json.loads(value) if isinstance(value, str) else dict(value)
                self.ac_fan = str(d.get("fan", self.ac_fan))
                self.target.ac = AcCommand(power=bool(d.get("power", False)), mode=str(d.get("mode", "cool")),
                                           setpoint_c=float(d.get("setpoint", self.target.ac.setpoint_c)))
            else:
                setattr(self.target, field_name, CMD_TO_FIELD[topic][1](value))

    def manual(self, device: str, action: str) -> None:
        """사용자가 리모컨 · 스위치로 직접 조작 (제어기를 거치지 않는다)."""
        on = action == "on"
        if device == "ac":
            self.target.ac = replace(self.target.ac, power=on)
            self.actual.ac = replace(self.target.ac)
        elif device in ("dehumidifier", "humidifier"):
            setattr(self.target, device, on)
            setattr(self.actual, device, on)

    def update(self, dt: float) -> None:
        for name in FIELD_TO_STATE:
            tgt = getattr(self.target, name)
            tau = self.tau.get(name)
            if tau and tau > 0:
                cur = getattr(self.actual, name)
                setattr(self.actual, name, tgt + (cur - tgt) * math.exp(-dt / tau))
            else:
                setattr(self.actual, name, tgt)
        self.actual.ac = replace(self.target.ac)

    def state_topics(self) -> dict[str, Any]:
        out: dict[str, Any] = {topic: getattr(self.actual, name) for name, topic in FIELD_TO_STATE.items()}
        ac = self.actual.ac
        out[T.T_AC] = json.dumps({"power": ac.power, "mode": ac.mode, "setpoint": ac.setpoint_c,
                                  "confidence": "CONFIRMED"})   # 고속 모드 v0.1: IR 역확인 없음
        return out


def pm_grade(pm: float, bounds: list[float], names: list[str]) -> str:
    for bound, name in zip(bounds, names):
        if pm <= bound:
            return name
    return names[-1]


def sensor_topics(obs: dict[str, Any], world: WorldInputs, door_open: bool, extra_power: dict[str, float],
                  grade_bounds: list[float], grade_names: list[str], occ=None, wifi: bool | None = None) -> dict[str, Any]:
    """참값 → 센서 토픽. 재실 · 위치 · Wi-Fi 는 재실 판정 노드(occ) 결과를 쓴다 (없으면 참값 — 단위 시험용).
    온습도 · PM 등은 아직 노이즈 · 지연 없음 (W07 센서 노드에서 추가)."""
    power = {k: round(v, 1) for k, v in obs["appliance_power_w"].items()}
    power.update(extra_power)
    return {
        T.S_TEMPERATURE: obs["temperature_c"],
        T.S_HUMIDITY: obs["humidity_pct"],
        T.S_PM25: obs["pm25_ugm3"],
        T.S_HOOD_TEMPERATURE: obs["hood_temperature_c"],
        T.S_ILLUMINANCE: obs["illuminance_lux"],         # 천장 BH1750 위치 참값 (W08 T8.3)
        T.S_OCCUPANCY: occ.occupied if occ else world.occupancy,
        T.S_OCCUPANT_ZONE: occ.zone if occ else (world.occupant_zone if world.occupancy else "none"),
        T.S_DOOR_CONTACT: door_open,
        T.S_WIFI_PRESENCE: wifi if wifi is not None else world.occupancy,
        T.S_OUTDOOR_PM_GRADE: pm_grade(world.ext.outdoor_pm25_ugm3, grade_bounds, grade_names),
        T.S_APPLIANCE_POWER: json.dumps(power, sort_keys=True),
        T.S_WEATHER: json.dumps({"raining": world.raining,
                                           "outdoor_temp_c": world.ext.outdoor_temp_c,
                                           "outdoor_rh_pct": world.ext.outdoor_rh_pct}),
    }


def make_model(env_cfg, sc: dict[str, Any]) -> RoomModel:
    ini = sc["initial"]
    return RoomModel.from_conditions(
        env_cfg,
        temp_c=float(ini["temperature_c"]),
        rh_pct=float(ini["humidity_pct"]),
        pm25_ugm3=float(ini.get("pm25_ugm3", 12.0)),
        co2_ppm=float(ini.get("co2_ppm", 600.0)),
        filter_hours=float(ini.get("filter_hours", 0.0)),
        mass_temp_c=ini.get("mass_temp_c"),           # 선택 — 공기만 데워진 상태 등 (B11)
        envelope_temp_c=ini.get("envelope_temp_c"),
    )
