"""실험 로그 열 이름 (고속 모드 harness/runner.py 와 같은 이름) — 물리 모드 로거 · 채점기가 같이 쓴다. ROS 의존 없음."""

from __future__ import annotations

from interfaces import topics as T

# 상태 토픽 → act.<이름> 열
ACT = {T.T_WINDOW_OPEN_RATIO: "window_open_ratio", T.T_BLIND_ANGLE: "blind_angle_deg", T.T_FAN_RPM: "exhaust_fan_rpm",
       T.T_INTAKE_FAN_RPM: "intake_fan_rpm", T.T_RANGE_HOOD_LEVEL: "range_hood_level",
       T.T_PURIFIER_LEVEL: "purifier_level", T.T_DEHUMIDIFIER: "dehumidifier", T.T_HUMIDIFIER: "humidifier",
       T.T_CEILING_FAN: "ceiling_fan", T.T_CEILING_LIGHT: "ceiling_light_pct", T.T_DESK_LIGHT: "desk_light_pct"}
AC_COLUMNS = ("act.ac", "act.ac_power", "act.ac_cool", "act.ac_dry", "act.ac_setpoint", "act.ac_fan")


def fill_act_from_topics(df):
    """act.* 열이 없는 옛 물리 모드 로그 — 같은 값인 상태 토픽 열로 채운다 (2026-10-12 로거 열 누락 수정 이전 로그)."""
    for tp, name in ACT.items():
        col = f"act.{name}"
        if col not in df.columns and tp in df.columns:
            df[col] = df[tp]
    # 시작 직후 상태 토픽이 아직 안 온 첫 행들 — 처음 들어온 값으로 채운다 (중간의 빈 값은 그대로 둔다)
    #   (물리 B3 · C3: 첫 1 행 act.ac_power 가 비어 'ac_power == 0 for all t' 가 FAIL — 2026-10-13 W11 배치)
    for col in [c for c in df.columns if c.startswith("act.")] + [c for c in AC_COLUMNS if c in df.columns]:
        first = df[col].first_valid_index()
        if first is not None and first > df.index[0]:
            df.loc[:first, col] = df.loc[:first, col].bfill()
    return df
