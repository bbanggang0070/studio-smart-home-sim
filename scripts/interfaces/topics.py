"""ROS 2 토픽 계약 — docs/02 §6 (52개: 센서 12 · 명령 15 · 상태 25).

제어기 · 하네스(고속 모드) · ROS 노드(물리 모드)가 같은 이름을 쓴다.
고속 모드에서는 메시지 대신 파이썬 값으로 주고받는다 — String(JSON) 토픽은 JSON 문자열 그대로.
"""

from __future__ import annotations

P = "/studio"

# ---- 센서 (12) -----------------------------------------------------------------
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

SENSOR_TOPICS = (
    S_ILLUMINANCE, S_TEMPERATURE, S_HUMIDITY, S_OCCUPANCY, S_OCCUPANT_ZONE, S_WINDOW_MOTOR_CURRENT,
    S_OUTDOOR_PM_GRADE, S_PM25, S_WIFI_PRESENCE, S_DOOR_CONTACT, S_HOOD_TEMPERATURE, S_APPLIANCE_POWER,
)

# ---- 명령 (15) -----------------------------------------------------------------
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

COMMAND_TOPICS = (
    C_CEILING_LIGHT, C_DESK_LIGHT, C_DESK_LIGHT_CCT, C_FAN_RPM, C_BLIND_ANGLE, C_WINDOW_OPEN_RATIO, C_MODE,
    C_AC, C_DEHUMIDIFIER, C_HUMIDIFIER, C_CEILING_FAN, C_INTAKE_FAN_RPM, C_PURIFIER_LEVEL, C_RANGE_HOOD_LEVEL,
    C_ACTIVITY,
)
USER_COMMAND_TOPICS = (C_MODE, C_ACTIVITY)   # 사용자(시나리오)가 내는 명령 — 제어기 입력

# ---- 상태 (25) -----------------------------------------------------------------
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

STATE_TOPICS = (
    T_CEILING_LIGHT, T_DESK_LIGHT, T_FAN_RPM, T_BLIND_ANGLE, T_WINDOW_OPEN_RATIO, T_WINDOW_POSITION_EST,
    T_WINDOW_ZONE, T_PINCH_DETECTED, T_LIVING_MODE, T_SAFETY_STATE, T_CONTROL_FEASIBILITY, T_AC,
    T_DEHUMIDIFIER, T_HUMIDIFIER, T_CEILING_FAN, T_INTAKE_FAN_RPM, T_PURIFIER_LEVEL, T_RANGE_HOOD_LEVEL,
    T_ACTIVE_EVENTS, T_AIR_BALANCE, T_DEW_MARGIN, T_APPLIANCE_STATES, T_VENTILATION, T_OCCUPANCY_BASIS,
    T_ENERGY_FORECAST,
)

ALL_TOPICS = SENSOR_TOPICS + COMMAND_TOPICS + STATE_TOPICS

# ---- ⚠️ 계약 미정 (2026-10-09 보고) ------------------------------------------------
#  docs/02 §6 의 52개에는 기상청 입력(강우 · 외기 온습도)을 받는 토픽이 없다.
#  제어기는 E5(강우) · I10(외기 이슬점) · 결로 여유(외기온)에 이 값이 필요하므로,
#  계약이 정해질 때까지 아래 임시 토픽으로 넘긴다 (집계 52개에 넣지 않는다).
PROVISIONAL_WEATHER = f"{P}/sensor/weather"              # String(JSON {"raining","outdoor_temp_c","outdoor_rh_pct"})
