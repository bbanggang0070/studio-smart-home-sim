"""ROS 2 토픽 계약 — docs/02 §6 (55개: 센서 13 · 명령 16 · 상태 26).

제어기 · 하네스(고속 모드) · ROS 노드(물리 모드)가 같은 이름을 쓴다.
고속 모드에서는 메시지 대신 파이썬 값으로 주고받는다 — String(JSON) 토픽은 JSON 문자열 그대로.
"""

from __future__ import annotations

P = "/studio"

# ---- 센서 (13) -----------------------------------------------------------------
S_ILLUMINANCE = f"{P}/sensor/illuminance"                # Float32 · 10 Hz
S_TEMPERATURE = f"{P}/sensor/temperature"                # Float32 · 10 Hz
S_HUMIDITY = f"{P}/sensor/humidity"                      # Float32 · 10 Hz
S_OCCUPANCY = f"{P}/sensor/occupancy"                    # Bool · 10 Hz
S_OCCUPANT_ZONE = f"{P}/sensor/occupant_zone"            # String · 변경 시
S_WINDOW_MOTOR_CURRENT = f"{P}/sensor/window_motor_current"  # Float32 · 50 Hz (물리 모드 전용)
S_OUTDOOR_PM_GRADE = f"{P}/sensor/outdoor_pm_grade"      # String · 변경 시
S_PM25 = f"{P}/sensor/pm25"                              # Float32 · 1 Hz
S_WIFI_PRESENCE = f"{P}/sensor/wifi_presence"            # Bool · 변경 시
S_DOOR_CONTACT = f"{P}/sensor/door_contact"              # Bool · 변경 시
S_HOOD_TEMPERATURE = f"{P}/sensor/hood_temperature"      # Float32 · 1 Hz
S_APPLIANCE_POWER = f"{P}/sensor/appliance_power"        # String(JSON {device: W}) · 1 Hz
S_WEATHER = f"{P}/sensor/weather"                        # String(JSON {"raining","outdoor_temp_c","outdoor_rh_pct"}) · 변경 시 (v3.4.2)

SENSOR_TOPICS = (
    S_ILLUMINANCE, S_TEMPERATURE, S_HUMIDITY, S_OCCUPANCY, S_OCCUPANT_ZONE, S_WINDOW_MOTOR_CURRENT,
    S_OUTDOOR_PM_GRADE, S_PM25, S_WIFI_PRESENCE, S_DOOR_CONTACT, S_HOOD_TEMPERATURE, S_APPLIANCE_POWER, S_WEATHER,
)

# ---- 명령 (16) -----------------------------------------------------------------
C_CEILING_LIGHT = f"{P}/cmd/ceiling_light_intensity"     # Float32 (0–100 %)
C_DESK_LIGHT = f"{P}/cmd/desk_light_intensity"           # Float32 (0–100 %)
C_DESK_LIGHT_CCT = f"{P}/cmd/desk_light_cct"             # Float32 (K)
C_FAN_RPM = f"{P}/cmd/fan_rpm"                           # Float32 — 배기팬
C_BLIND_ANGLE = f"{P}/cmd/blind_angle"                   # Float32 (deg)
C_WINDOW_OPEN_RATIO = f"{P}/cmd/window_open_ratio"       # Float32 (0–1)
C_MODE = f"{P}/cmd/mode"                                 # String — 사용자 모드 설정
C_AC = f"{P}/cmd/ac"                                     # String(JSON {"power","mode","setpoint","fan"})
C_DEHUMIDIFIER = f"{P}/cmd/dehumidifier"                 # Bool
C_HUMIDIFIER = f"{P}/cmd/humidifier"                     # Bool
C_CEILING_FAN = f"{P}/cmd/ceiling_fan"                   # Int8 (−2…+2)
C_INTAKE_FAN_RPM = f"{P}/cmd/intake_fan_rpm"             # Float32
C_PURIFIER_LEVEL = f"{P}/cmd/purifier_level"             # Int8 (0–3)
C_RANGE_HOOD_LEVEL = f"{P}/cmd/range_hood_level"         # Int8 (0–2)
C_ACTIVITY = f"{P}/cmd/activity"                         # String — 사용자 행동 선언
C_COOKTOP_POWER = f"{P}/cmd/cooktop_power"               # Bool — 플러그형 인덕션 릴레이 (false = 차단, v3.4.5)

COMMAND_TOPICS = (
    C_CEILING_LIGHT, C_DESK_LIGHT, C_DESK_LIGHT_CCT, C_FAN_RPM, C_BLIND_ANGLE, C_WINDOW_OPEN_RATIO, C_MODE,
    C_AC, C_DEHUMIDIFIER, C_HUMIDIFIER, C_CEILING_FAN, C_INTAKE_FAN_RPM, C_PURIFIER_LEVEL, C_RANGE_HOOD_LEVEL,
    C_ACTIVITY, C_COOKTOP_POWER,
)
USER_COMMAND_TOPICS = (C_MODE, C_ACTIVITY)   # 사용자(시나리오)가 내는 명령 — 제어기 입력

# ---- 상태 (26) -----------------------------------------------------------------
T_CEILING_LIGHT = f"{P}/state/ceiling_light_intensity"
T_DESK_LIGHT = f"{P}/state/desk_light_intensity"
T_FAN_RPM = f"{P}/state/fan_rpm"
T_BLIND_ANGLE = f"{P}/state/blind_angle"
T_WINDOW_OPEN_RATIO = f"{P}/state/window_open_ratio"
T_WINDOW_POSITION_EST = f"{P}/state/window_position_est"
T_WINDOW_ZONE = f"{P}/state/window_zone"
T_PINCH_DETECTED = f"{P}/state/pinch_detected"
T_LIVING_MODE = f"{P}/state/living_mode"
T_SAFETY_STATE = f"{P}/state/safety_state"
T_CONTROL_FEASIBILITY = f"{P}/state/control_feasibility"
T_AC = f"{P}/state/ac"
T_DEHUMIDIFIER = f"{P}/state/dehumidifier"
T_HUMIDIFIER = f"{P}/state/humidifier"
T_CEILING_FAN = f"{P}/state/ceiling_fan"
T_INTAKE_FAN_RPM = f"{P}/state/intake_fan_rpm"
T_PURIFIER_LEVEL = f"{P}/state/purifier_level"
T_RANGE_HOOD_LEVEL = f"{P}/state/range_hood_level"
T_ACTIVE_EVENTS = f"{P}/state/active_events"             # String(JSON 배열)
T_AIR_BALANCE = f"{P}/state/air_balance"
T_DEW_MARGIN = f"{P}/state/dew_margin"
T_APPLIANCE_STATES = f"{P}/state/appliance_states"
T_VENTILATION = f"{P}/state/ventilation"
T_OCCUPANCY_BASIS = f"{P}/state/occupancy_basis"
T_ENERGY_FORECAST = f"{P}/state/energy_forecast"
T_ALERTS = f"{P}/state/alerts"                           # String(JSON 배열 [{"code","level","msg","t"}]) — 사용자 알림 (v3.4.5)

STATE_TOPICS = (
    T_CEILING_LIGHT, T_DESK_LIGHT, T_FAN_RPM, T_BLIND_ANGLE, T_WINDOW_OPEN_RATIO, T_WINDOW_POSITION_EST,
    T_WINDOW_ZONE, T_PINCH_DETECTED, T_LIVING_MODE, T_SAFETY_STATE, T_CONTROL_FEASIBILITY, T_AC,
    T_DEHUMIDIFIER, T_HUMIDIFIER, T_CEILING_FAN, T_INTAKE_FAN_RPM, T_PURIFIER_LEVEL, T_RANGE_HOOD_LEVEL,
    T_ACTIVE_EVENTS, T_AIR_BALANCE, T_DEW_MARGIN, T_APPLIANCE_STATES, T_VENTILATION, T_OCCUPANCY_BASIS,
    T_ENERGY_FORECAST, T_ALERTS,
)

ALL_TOPICS = SENSOR_TOPICS + COMMAND_TOPICS + STATE_TOPICS

# ---- 메시지 타입 · QoS (docs/02 §6 표 · W06 리스크) -----------------------------
#  std_msgs 타입 이름. 고속 모드는 쓰지 않는다 — ROS 노드(scripts/nodes · scripts/sim)가 쓴다.
F32, BOOL, STR, I8 = "Float32", "Bool", "String", "Int8"
TYPES: dict[str, str] = {
    S_ILLUMINANCE: F32, S_TEMPERATURE: F32, S_HUMIDITY: F32, S_OCCUPANCY: BOOL, S_OCCUPANT_ZONE: STR,
    S_WINDOW_MOTOR_CURRENT: F32, S_OUTDOOR_PM_GRADE: STR, S_PM25: F32, S_WIFI_PRESENCE: BOOL, S_DOOR_CONTACT: BOOL,
    S_HOOD_TEMPERATURE: F32, S_APPLIANCE_POWER: STR, S_WEATHER: STR,
    C_CEILING_LIGHT: F32, C_DESK_LIGHT: F32, C_DESK_LIGHT_CCT: F32, C_FAN_RPM: F32, C_BLIND_ANGLE: F32,
    C_WINDOW_OPEN_RATIO: F32, C_MODE: STR, C_AC: STR, C_DEHUMIDIFIER: BOOL, C_HUMIDIFIER: BOOL, C_CEILING_FAN: I8,
    C_INTAKE_FAN_RPM: F32, C_PURIFIER_LEVEL: I8, C_RANGE_HOOD_LEVEL: I8, C_ACTIVITY: STR, C_COOKTOP_POWER: BOOL,
    T_CEILING_LIGHT: F32, T_DESK_LIGHT: F32, T_FAN_RPM: F32, T_BLIND_ANGLE: F32, T_WINDOW_OPEN_RATIO: F32,
    T_WINDOW_POSITION_EST: F32, T_WINDOW_ZONE: STR, T_PINCH_DETECTED: BOOL, T_LIVING_MODE: STR, T_SAFETY_STATE: STR,
    T_CONTROL_FEASIBILITY: STR, T_AC: STR, T_DEHUMIDIFIER: BOOL, T_HUMIDIFIER: BOOL, T_CEILING_FAN: I8,
    T_INTAKE_FAN_RPM: F32, T_PURIFIER_LEVEL: I8, T_RANGE_HOOD_LEVEL: I8, T_ACTIVE_EVENTS: STR, T_AIR_BALANCE: F32,
    T_DEW_MARGIN: F32, T_APPLIANCE_STATES: STR, T_VENTILATION: STR, T_OCCUPANCY_BASIS: STR, T_ENERGY_FORECAST: STR,
    T_ALERTS: STR,
}


def qos_kind(topic: str) -> str:
    """'sensor' = BEST_EFFORT(depth 10, 전류는 5) · 'reliable' = 명령 · 상태 (W06 리스크 표)."""
    return "sensor" if topic in SENSOR_TOPICS else "reliable"


# ---- 내부 토픽 (계약 55개 밖 — 같은 계층 노드끼리만) -------------------------------
#  창문 토크 상한 (W06 T6.3b) — 센서리스 창문 노드(W10)가 Zone 별 토크 프로파일을 브릿지에 전달한다. Float32 (최대 힘의 %)
I_WINDOW_TORQUE_PCT = f"{P}/internal/window_torque_pct"
#  시험 전용 (물리 모드 검증 스크립트) — 끼임 물체를 창 레일 경로에 놓기 / 치우기. String: 'rigid_pot' | 'soft_cushion' | 'elastic_sponge' | 'park'
I_SIM_OBSTACLE = f"{P}/internal/sim_obstacle"
#  시험 전용 — 시나리오 초기 액추에이터 상태를 Isaac 에 적용 (월드 노드 → 브릿지). String JSON {window_open_ratio, blind_angle_deg}
I_SIM_INIT = f"{P}/internal/sim_init"
#  창문 2계층 안전 (W10) — 상위(window_safety_node) ↔ 하위(Isaac 브릿지 로컬 컷오프)
#  브릿지 → 상위: 로컬 상태 String JSON {tripped, reason, contact_peak_n}
#  상위 → 브릿지: 우선 지령 String JSON {mode: normal|reverse|hold, to_ratio, locked: [−1/+1]} — 제어기 지령보다 먼저
I_WINDOW_LOCAL = f"{P}/internal/window_local"
I_WINDOW_OVERRIDE = f"{P}/internal/window_override"
