"""pass_criteria · expect 판정기와 지표 계산 (docs/03 §7 · §8 규약 6–7단계).

판정은 참값 로그(DataFrame)로 한다. 문법 (한 줄 = 판정 1개):

    <식>                              식이 모든 시각에서 참 (스칼라면 그 값)
    <식> for all t                    위와 같음
    <식> during <label>               injections 의 label 구간 안에서 항상 참
    <식> during <label> settle <N>    구간 시작 N 초 뒤부터 (감지 지연 허용 · expect 의 settle_s)
    <식> when <조건식>                 조건식이 참인 시각에서 항상 참 (해당 시각이 없으면 참)
    <식> within <N> after <앵커>       앵커 ~ 앵커+N 초 사이에 한 번이라도 참 (감지 · 진입 · 회복 시점)
    <식> by <N> after <앵커>           앵커+N 초 시각에 참 ("N초 안에 ~로 돌아온다" — 앵커 직후에 이미 참인 경우를 걸러냄)
                                     앵커 = 숫자 | <label>_start | <label>_end

식에 쓸 수 있는 것
    열 별칭 (ALIASES) · 숫자 · 비교 · + − × ÷ · and/or/not
    지표 이름 (pm25_peak 등) · baseline_<X>.<지표>  (같은 반복의 다른 baseline 결과)
    event_entered('NAME')            제어기가 /studio/state/active_events 에 NAME 을 낸 시각들
    value_at('<별칭>', <앵커|숫자>)    그 시각의 값
    ratio(<조건식>)                   조건이 참인 시각의 비율 (체류율)
    entries('NAME')                  이벤트 진입 횟수 (알림 횟수 판정)
    ended_for('NAME', N)             이벤트가 끝난 뒤 N 초 이상 지난 시각 (끝난 적이 없으면 거짓)
    basis_is('FALLBACK')             재실 판정 근거(occupancy_basis)가 그 값인 시각
    alert_raised('E15')              /studio/state/alerts 에 그 코드의 알림이 나온 뒤의 시각
    ac_fan_is('low')                 에어컨이 꺼져 있거나 그 풍량인 시각
    abs(<식>)                         절댓값
    [난방 확장] 별칭 floor_temp · boiler_burning · boiler_on · boiler_setpoint · boiler_gas_w (hydronic 실행)
                지표 gas_kwh · electric_kwh · energy_cost_won · cold_discomfort_kh · min_temp_c · boiler_ignitions · expected_cost_heating
                · base_vent_compliance_mode (시각별 생활 모드 목표 · v1.31-H)
    mode_is('SLEEP')                 제어기가 낸 유효 생활 모드(living_mode)가 그 값인 시각
    feasibility_is('DEGRADED')       control_feasibility 가 그 값인 시각
    cmd_* 별칭은 제어기가 낸 명령값 — 내지 않은 주기는 직전 값을 이어 쓴다

평가할 수 없는 판정(다른 baseline 이 아직 없음 등)은 PENDING 으로 남긴다 — FAIL 과 구분한다.
baseline_<X>.* 를 쓰는 판정은 baseline X 자신의 실행에서는 N/A (자기 자신과 비교하지 않는다).
"""

from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from interfaces import topics as T

ALIASES = {
    "window_open_ratio": "act.window_open_ratio",
    "blind_angle": "act.blind_angle_deg",
    "exhaust_fan_rpm": "act.exhaust_fan_rpm",
    "intake_fan_rpm": "act.intake_fan_rpm",
    "range_hood_level": "act.range_hood_level",
    "purifier_level": "act.purifier_level",
    "dehumidifier": "act.dehumidifier",
    "humidifier": "act.humidifier",
    "ceiling_fan": "act.ceiling_fan",
    "temperature": "truth.temperature_c",
    "humidity": "truth.humidity_pct",
    "pm25": "truth.pm25_ugm3",
    "co2": "truth.co2_ppm",
    "dew_margin": "truth.dew_margin_c",
    "q_net": "truth.q_net_m3h",
    "q_inf": "truth.q_inf_m3h",
    "hood_temperature": "truth.hood_temperature_c",
    "operative_temperature": "truth.operative_temp_c",
    "ac_power": "act.ac_power",
    "cmd_ac_power": "cmd.ac_power",                    # 명령(결정) 기준 — IR 누락 · 재송신과 분리해 볼 때
    "ac_cool": "act.ac_cool",
    "ac_dry": "act.ac_dry",
    "ac_setpoint": "act.ac_setpoint",
    "blind_angle_deg": "act.blind_angle_deg",
    "condensate": "truth.condensate_g",
    "outdoor_pm25": "ext.outdoor_pm25_ugm3",
    "outdoor_temp": "ext.outdoor_temp_c",
    "outdoor_dew": "ext.outdoor_dew_c",
    "dew_point": "truth.dew_point_c",
    "total_power": "power.total_w",
    "laundry_moisture": "truth.laundry_moisture_g",
    "occupied": "/studio/sensor/occupancy",             # 재실 판정 노드 출력
    "occupied_truth": "truth.occupied",
    "occupancy_alerts": "occ.alerts",
    "cooktop_power": "act.cooktop_power",
    "ceiling_light": "act.ceiling_light_pct",
    "desk_light": "act.desk_light_pct",
    "desk_cct": "act.desk_cct",
    "desk_illuminance": "truth.desk_illuminance_lux",   # 책상면 조도 참값 (센서 없음 — C4 판정용)
    "floor_illuminance": "truth.floor_illuminance_lux", # 방 작업면(바닥 중앙) 조도 참값 — 모드 조도 목표의 기준면 (B1 · B2)
    "cmd_window": T.C_WINDOW_OPEN_RATIO,
    "cmd_blind": T.C_BLIND_ANGLE,
    "cmd_ceiling_light": T.C_CEILING_LIGHT,
    "cmd_desk_light": T.C_DESK_LIGHT,
    "cmd_desk_cct": T.C_DESK_LIGHT_CCT,
    "cmd_exhaust_rpm": T.C_FAN_RPM,
    "cmd_intake_rpm": T.C_INTAKE_FAN_RPM,
    "ac_sent": "cmd.ac_sent",
    "ir_tx_ac": "bridge.ir_tx_ac",
    "pm_ac_run": "pm.ac.run",                          # 전력 감시가 판정한 에어컨 상태 (B11)
    "pm_ac_fan_only": "pm.ac.fan_only",
    "ac_manual_detected": "pm.ac.manual",
    # [난방 확장 docs/14 · heating.mode = hydronic 실행에만 있는 열]
    "floor_temp": "truth.floor_temp_c",
    "boiler_burning": "truth.boiler_burning",
    "boiler_on": "act.boiler_power",                   # 조절기 전원 (L0 뒤 실제)
    "boiler_setpoint": "act.boiler_setpoint",
    "boiler_gas_w": "truth.boiler_gas_w",
}

PASS, FAIL, PENDING, ERROR, NA = "PASS", "FAIL", "PENDING", "ERROR", "N/A"


class Pending(Exception):
    pass


@dataclass
class CriterionResult:
    text: str
    status: str
    detail: str = ""


# ---- 지표 -------------------------------------------------------------------------


def _first_time(t: np.ndarray, mask: np.ndarray) -> float:
    idx = np.flatnonzero(mask)
    return float(t[idx[0]]) if idx.size else math.nan


def _response_time(t: np.ndarray, cmd: pd.Series, act: pd.Series, tol: float) -> float:
    """지표 #2 — 지령 값이 바뀐 샘플 → 실제 상태가 지령 ± tol 안에 든 샘플까지 [s] 의 최댓값.
    이미 목표 근처였던 지령 · 다음 지령 전에 도달하지 못한 지령(덮어씀)은 세지 않는다. 해상도 = 로그 주기."""
    c = pd.to_numeric(cmd, errors="coerce").ffill().to_numpy()
    a = pd.to_numeric(act, errors="coerce").ffill().to_numpy()
    starts = [i for i in range(1, len(c)) if not np.isnan(c[i]) and (np.isnan(c[i - 1]) or c[i] != c[i - 1])
              and not abs(a[i - 1] - c[i]) <= tol]
    worst = math.nan
    for n, i in enumerate(starts):
        j = starts[n + 1] if n + 1 < len(starts) else len(c)
        hit = np.flatnonzero(np.abs(a[i:j] - c[i]) <= tol)
        if hit.size:
            dt = float(t[i + hit[0]] - t[i])
            worst = dt if math.isnan(worst) else max(worst, dt)
    return worst


def _longest_run(m: np.ndarray) -> int:
    best = cur = 0
    for x in m:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return best


def _budget_violations(df: pd.DataFrame, budgets: dict[str, Any], exempt: list[str], n_min: int) -> float:
    """지표 #16 — 우선 목표 이벤트(예산이 있는 E3 샤워 · E10 빨래 건조)가 켜진 구간마다 온도 · 소음 예산을 넘었는지.
    구간 1개 × 예산 항목 1개 = 최대 1회 · n_min 샘플 이상 이어져야 센다. 다른 이벤트의 소음 완화(요리 N3) 중인 시각은 소음에서 뺀다."""
    col = T.T_ACTIVE_EVENTS
    if col not in df.columns or not budgets:
        return math.nan
    ev = df[col].ffill().fillna("[]").astype(str).reset_index(drop=True)
    temp = df["truth.temperature_c"].reset_index(drop=True)
    occ = (df["truth.occupied"].astype(bool) if "truth.occupied" in df.columns
           else pd.Series(True, index=df.index)).reset_index(drop=True)
    relaxed = pd.Series(False, index=ev.index)
    for name in exempt:
        relaxed |= ev.str.contains(f'"{name}"', regex=False)
    count = 0
    for name, b in budgets.items():
        active = ev.str.contains(f'"{name}"', regex=False)
        if not active.any():
            continue
        run = (active != active.shift()).cumsum()
        for _, idx in active[active].groupby(run[active]).groups.items():
            idx = list(idx)
            d_t = (temp[idx] - temp[idx[0]]).to_numpy()
            checks = []
            if b.get("indoor_temp_change_c", -1.0) >= 0:
                checks.append(np.abs(d_t) > b["indoor_temp_change_c"])
            if b.get("indoor_temp_rise_c", -1.0) >= 0:
                lim = np.where(occ[idx].to_numpy(), b["indoor_temp_rise_c"],
                               b.get("indoor_temp_rise_away_c", b["indoor_temp_rise_c"]))
                checks.append(d_t > lim)
            noise = np.zeros(len(idx), dtype=bool)
            for act_col, cap in (b.get("noise_caps") or {}).items():
                if act_col in df.columns:
                    v = pd.to_numeric(df[act_col].reset_index(drop=True)[idx], errors="coerce").fillna(0.0).to_numpy()
                    noise |= v > cap + 1e-6
            checks.append(noise & ~relaxed[idx].to_numpy())
            count += sum(_longest_run(m) >= n_min for m in checks)
    return float(count)


def compute_metrics(df: pd.DataFrame, anchors: dict[str, float], sources: dict[str, str],
                    cfg_metrics: dict[str, Any], dt_s: float, ctx: dict[str, Any] | None = None) -> dict[str, float]:
    """docs/03 §7 지표 중 참값 로그로 계산할 수 있는 것. 계산할 수 없으면 NaN (사유는 metric_notes)."""
    t = df["time_s"].to_numpy()
    out: dict[str, float] = {}
    pm = df["truth.pm25_ugm3"].to_numpy()
    out["pm25_peak"] = float(pm.max())

    cook = next((lb for lb, kind in sources.items() if kind == "cooking"), None)
    if cook:
        end = anchors[f"{cook}_end"]
        rec = _first_time(t, (t >= end) & (pm <= cfg_metrics["pm25_recovery_ugm3"]))
        out["pm25_recovery_time"] = rec - end if not math.isnan(rec) else math.nan
    else:
        out["pm25_recovery_time"] = math.nan

    # 지표 #14 — 습기 발생원(샤워 우선, 없으면 요리) 시작 시각의 RH 기준, 기준+5 %p 또는 60 % 이하로 복귀
    moist = next((lb for lb, kind in sources.items() if kind == "shower"), cook)
    if moist:
        start, end = anchors[f"{moist}_start"], anchors[f"{moist}_end"]
        rh = df["truth.humidity_pct"].to_numpy()
        base = float(np.interp(start, t, rh))
        thr = max(base + cfg_metrics["rh_recovery_delta_pct"], cfg_metrics["rh_recovery_abs_pct"])
        rec = _first_time(t, (t >= end) & (rh <= thr))
        out["humidity_recovery_time"] = rec - start if not math.isnan(rec) else math.nan
    else:
        out["humidity_recovery_time"] = math.nan

    out["infiltration_volume"] = float(df["truth.q_inf_m3h"].sum() * dt_s / 3600.0)
    out["infiltration_volume_alt"] = float(df["truth.q_inf_alt_m3h"].sum() * dt_s / 3600.0)
    energy_cols = [c for c in df.columns if c.startswith("energy_wh.")]
    out["energy_wh"] = float(df[energy_cols].iloc[-1].sum()) if energy_cols else math.nan
    # 지표 #7 '같은 목표 달성' 비교용 — 조명 제외 (Baseline A 는 C4 외에는 조명을 켜지 않아 조명 목표가 다르다 · 조명은 #1 · C4 가 본다)
    ex = cfg_metrics.get("energy_exclude_for_compare") or []
    keep = [c for c in energy_cols if c.split(".", 1)[1] not in ex]
    out["energy_compare_wh"] = float(df[keep].iloc[-1].sum()) if keep else math.nan
    out["condensation_exposure_s"] = float((df["truth.dew_margin_c"] < 0).sum() * dt_s)
    if "pm.ac.state" in df.columns and "truth.ac_state" in df.columns:   # B11 — 전력 기반 상태 판정 정확도
        out["appliance_state_accuracy"] = float((df["pm.ac.state"] == df["truth.ac_state"]).mean())
    lt = cfg_metrics.get("lux_temp_ok")
    if lt and "truth.desk_illuminance_lux" in df.columns:       # C4 — 조도 · 온도 동시 유지율 (재실 중)
        occ = df["truth.occupied"].astype(bool) if "truth.occupied" in df.columns else pd.Series(True, index=df.index)
        ok = (df["truth.desk_illuminance_lux"] >= lt["desk_lux_min"]) & (df["truth.temperature_c"] <= lt["temp_max_c"])
        out["lux_temp_ok_ratio"] = float(ok[occ].mean()) if occ.any() else math.nan
    # #1 환경 목표 유지율 — 재실 중 체감온도 ≤ 냉방 목표 + 0.5 · 습도가 모드 범위 안 (ctx 모드)
    #   체감온도(실링팬 기류 보정) — 공기 온도로 세면 I5(실링팬으로 설정 완화)가 만든 쾌적 상태를 '더움'으로 센다 (overheat_time_s 와 같은 기준 · W13)
    occ_mask = df["truth.occupied"].astype(bool) if "truth.occupied" in df.columns else pd.Series(True, index=df.index)
    sp_c = (ctx or {}).get("cooling_setpoint_c")
    hr = (ctx or {}).get("humidity_range_pct") or [None, None]
    ok = pd.Series(True, index=df.index)
    if sp_c is not None:
        ok &= df["truth.operative_temp_c"] <= sp_c + cfg_metrics["overheat_margin_c"]
    if hr[0] is not None:
        ok &= df["truth.humidity_pct"] >= hr[0]
    if hr[1] is not None:
        ok &= df["truth.humidity_pct"] <= hr[1]
    out["comfort_ratio"] = float(ok[occ_mask].mean()) if occ_mask.any() else math.nan
    # 개정 전 정의(v2.30 까지 · 공기 온도 기준) — 사후 재정의 전후를 함께 보고하기 위해 남긴다 (docs/11 §6.2)
    ok_air = pd.Series(True, index=df.index)
    if sp_c is not None:
        ok_air &= df["truth.temperature_c"] <= sp_c + cfg_metrics["overheat_margin_c"]
    if hr[0] is not None:
        ok_air &= df["truth.humidity_pct"] >= hr[0]
    if hr[1] is not None:
        ok_air &= df["truth.humidity_pct"] <= hr[1]
    out["comfort_ratio_air"] = float(ok_air[occ_mask].mean()) if occ_mask.any() else math.nan
    # 목표 이탈 적분 (W13 · Tier 2 우위 제시) — 유지율은 0 · 1 에 붙어 차이가 안 보이므로 '얼마나 크게 · 오래 벗어났나'를 재실 중에 적분
    #   온도 °C·h = ∫ max(0, 체감온도 − (냉방 목표 + margin)) · 습도 %RH·h = 모드 범위 밖 거리 · PM µg/m³·h = ∫ max(0, PM − 35)
    occ_v = occ_mask.to_numpy(dtype=bool)
    h = dt_s / 3600.0
    if sp_c is not None:
        dev_t = np.clip(df["truth.operative_temp_c"].to_numpy() - (sp_c + cfg_metrics["overheat_margin_c"]), 0.0, None)
        out["temp_excess_ch"] = float(dev_t[occ_v].sum() * h)
    else:
        out["temp_excess_ch"] = math.nan
    rh = df["truth.humidity_pct"].to_numpy()
    dev_h = np.zeros_like(rh)
    if hr[1] is not None:
        dev_h += np.clip(rh - hr[1], 0.0, None)
    if hr[0] is not None:
        dev_h += np.clip(hr[0] - rh, 0.0, None)
    out["rh_excess_pcth"] = float(dev_h[occ_v].sum() * h)
    dev_pm = np.clip(df["truth.pm25_ugm3"].to_numpy() - cfg_metrics["pm25_recovery_ugm3"], 0.0, None)
    out["pm_excess_ugh"] = float(dev_pm[occ_v].sum() * h)
    # 물리 모드 전용 (#3 추종 오차 · #4 끼임 · #5 접촉 반력 · #6 리플 위치 오차) — 열이 없으면 NaN
    # #2 · #3 은 안전 계층이 처음 개입(끼임 반전 · 정지 유지 · 잠금)하기 전까지만 — 그 뒤 지령 ≠ 실제는 의도된 동작이다
    if T.T_SAFETY_STATE in df.columns:
        normal = df[T.T_SAFETY_STATE].ffill().fillna("NORMAL").astype(str).eq("NORMAL")
        pre_safety = normal.astype(int).cummin().astype(bool).to_numpy()
    else:
        pre_safety = np.ones(len(df), dtype=bool)
    for name, cmd_col, act_col, scale in (("window_track_err_pct", T.C_WINDOW_OPEN_RATIO, "act.window_open_ratio", 100.0),
                                          ("blind_track_err_deg", T.C_BLIND_ANGLE, "act.blind_angle_deg", 1.0)):
        if cmd_col in df.columns and act_col in df.columns:
            c = df[cmd_col].ffill()
            n = max(1, int(round(cfg_metrics["tracking_steady_s"] / dt_s)))
            steady = c.eq(c.shift(n)) & c.notna() & pre_safety          # 지령이 tracking_steady_s 이상 그대로인 시각만 (이동 중 제외)
            out[name] = float((c[steady] - df[act_col][steady]).abs().quantile(0.95) * scale) if steady.any() else math.nan
    if T.T_PINCH_DETECTED in df.columns:
        p = df[T.T_PINCH_DETECTED].fillna(False).astype(bool)
        out["pinch_events"] = float((p & ~p.shift(1, fill_value=False)).sum())
    if "sim.contact_peak_n" in df.columns:
        out["max_contact_force_n"] = float(pd.to_numeric(df["sim.contact_peak_n"], errors="coerce").max())
    for col, name in (("sim.pinch_detect_ms", "pinch_detect_ms"), ("sim.pinch_stop_ms", "pinch_stop_ms")):
        if col in df.columns:
            out[name] = float(pd.to_numeric(df[col], errors="coerce").max())
    if T.T_WINDOW_POSITION_EST in df.columns and "act.window_open_ratio" in df.columns:
        travel = (ctx or {})["window_travel_m"]
        out["ripple_pos_err_mm"] = float((df[T.T_WINDOW_POSITION_EST] - df["act.window_open_ratio"] * travel).abs().max() * 1000)
    out["temp_end_c"] = float(df["truth.temperature_c"].iloc[-1])      # 마지막 실내 온도 — baseline 간 냉방 결과 비교 (C3b)
    # C3 동작 순서 — 블라인드 차광 도달 시각이 창문 개방 시각보다 몇 초 앞섰나 (창문을 안 열었으면 +inf → 준수)
    oc = cfg_metrics["order_check"]
    if "act.blind_angle_deg" in df.columns and "act.window_open_ratio" in df.columns:
        tb = _first_time(t, df["act.blind_angle_deg"].to_numpy(dtype=float) >= oc["blind_shaded_deg"])
        tw = _first_time(t, df["act.window_open_ratio"].to_numpy(dtype=float) > oc["window_opened_ratio"])
        out["blind_lead_s"] = (math.inf if math.isnan(tw) else tw - tb) if not math.isnan(tb) else -math.inf
    # #15 귀가 시 쾌적 — 귀가 앵커 시각에 실내 ≤ 냉방 목표 + 1
    if "arrive_start" in anchors and sp_c is not None:
        tt = float(np.interp(anchors["arrive_start"], df["time_s"], df["truth.temperature_c"]))
        out["arrival_comfort"] = float(tt <= sp_c + 1.0)
    out["ir_tx_ac"] = float(df["bridge.ir_tx_ac"].iloc[-1]) if "bridge.ir_tx_ac" in df.columns else math.nan
    # 지표 #12 규칙 위반 — 로그로 확인할 수 있는 하드 규칙: I1 제습 + 가습 · I2 에어컨 냉방 중 창문 · L1 우천 창문
    #   rule_violation.min_duration_s 이상 이어진 구간 1개 = 1회 (동작이 바뀌는 순간의 과도 상태는 세지 않는다)
    rv = cfg_metrics["rule_violation"]

    def _flag(col):
        return df[col].astype(str).isin(["True", "1", "1.0"]) if col in df.columns else pd.Series(False, index=df.index)

    win = pd.to_numeric(df.get("act.window_open_ratio", pd.Series(0.0, index=df.index)), errors="coerce").fillna(0) > rv["window_open_min"]
    win &= pre_safety                 # 안전 계층이 창문을 잠근 뒤(L0 > L1)의 열림은 제어기 위반이 아니다 (X2 물리)
    viol = [(_flag("act.dehumidifier") | _flag("act.ac_dry")) & _flag("act.humidifier"),
            _flag("act.ac_cool") & win, _flag("ext.raining") & win]
    n_min = max(1, int(round(rv["min_duration_s"] / dt_s)))
    count = 0
    for m in viol:
        m = m.reset_index(drop=True)
        run = (m != m.shift()).cumsum()
        lengths = m.groupby(run).transform("size")
        count += int(((m & (lengths >= n_min)) & ~(m & (lengths >= n_min)).shift(fill_value=False)).sum())
    out["rule_violation_count"] = float(count)

    # 지표 #8 — 장치 전환(구동) 횟수 (불필요 구동 · 채터링은 Baseline B 대비로 본다)
    n = 0
    for col in cfg_metrics.get("actuation_columns", []):
        if col in df.columns:
            n += int((df[col].astype(float).diff().abs() > 1e-6).sum())
    for col, step in (cfg_metrics.get("actuation_continuous") or {}).items():
        if col in df.columns:
            v = df[col].astype(float).to_numpy()
            ref, cnt = v[0], 0
            for x in v[1:]:                          # 직전 '구동 시점' 값 대비 step 이상 바뀌면 1회
                if abs(x - ref) >= step:
                    cnt, ref = cnt + 1, x
            n += cnt
    out["actuation_count"] = float(n)

    # 빨래 건조 시간 — 처음 널린 시각부터 잔여 수분 ≤ 5 % 까지 (C15 · C19)
    lm = df["truth.laundry_moisture_g"].to_numpy()
    if lm.max() > 0:
        t_hang = float(t[np.flatnonzero(lm > 0)[0]])
        dry = _first_time(t, (t > t_hang) & (lm <= 0.05 * lm.max()))
        out["laundry_dry_time_s"] = dry - t_hang if not math.isnan(dry) else math.inf   # 널었는데 끝까지 안 마름
    else:
        out["laundry_dry_time_s"] = math.nan

    # 쾌적 — 체감온도(실링팬 기류 보정)가 모드 냉방 목표 + margin 을 넘은 누적 시간
    # (공기 온도로 세면 I5 로 설정을 완화하고 실링팬으로 체감을 낮춘 상태까지 '과열'로 센다)
    sp = (ctx or {}).get("cooling_setpoint_c")
    out["overheat_time_s"] = (float((df["truth.operative_temp_c"] > sp + cfg_metrics["overheat_margin_c"]).sum() * dt_s)
                              if sp is not None else math.nan)

    # 지표 #9 — 재실 중 기본 환기 충족률 · 참값 CO2 기준 이하 비율 (제어에 쓰지 않는 검증값)
    ctx = ctx or {}
    occ_col = T.S_OCCUPANCY
    occ = df[occ_col].astype(bool).to_numpy() if occ_col in df.columns else np.ones(len(df), dtype=bool)
    target = float(ctx.get("base_vent_m3h") or 0.0)
    if occ.any() and target > 0:
        supplied = (df["truth.q_intake_m3h"] + df["truth.q_window_m3h"] + df["truth.q_inf_m3h"]
                    - float(ctx.get("q_inf0_m3h", 0.0))).to_numpy()      # 기저 침기를 뺀 '공급한' 외기
        ok = supplied >= target - cfg_metrics["base_vent_tolerance_m3h"]
        out["base_vent_compliance"] = float(ok[occ].mean())
    else:
        out["base_vent_compliance"] = math.nan
    ref = cfg_metrics["co2_reference_ppm"]["study" if ctx.get("user_mode") == "STUDY" else "other"]
    co2 = df["truth.co2_ppm"].to_numpy()
    out["co2_compliance"] = float((co2[occ] <= ref).mean()) if occ.any() else math.nan

    # 지표 #2 응답 시간 (물리 모드에서 의미 — 고속 모드 액추에이터는 1차 지연 근사)
    for name, spec in ((cfg_metrics.get("response_time") or {}).get("pairs") or {}).items():
        k = int(pre_safety.sum()) if not pre_safety.all() else len(df)          # 안전 개입 전까지
        out[f"response_{name}_s"] = (_response_time(t[:k], df[spec["cmd"]].iloc[:k], df[spec["act"]].iloc[:k], float(spec["tol"]))
                                     if spec["cmd"] in df.columns and spec["act"] in df.columns else math.nan)
    # 지표 #16 허용 손실 예산 위반
    bc = cfg_metrics.get("budget_check") or {}
    out["budget_violation_count"] = _budget_violations(
        df, ctx.get("budgets") or {}, list(bc.get("noise_exempt_events") or []),
        max(1, int(round(float(bc.get("min_duration_s", 30.0)) / dt_s))))
    if "truth.floor_temp_c" in df.columns:               # [난방 확장] hydronic 실행에만 — v1.29 실행의 지표 열은 그대로
        out.update(_heating_metrics(df, t, dt_s, cfg_metrics.get("heating") or {}, occ))
        out["base_vent_compliance_mode"] = _vent_compliance_by_mode(df, occ, cfg_metrics, ctx)
    return out


def _vent_compliance_by_mode(df: pd.DataFrame, occ: np.ndarray, cfg_metrics: dict[str, Any], ctx: dict[str, Any]) -> float:
    """[v1.31-H M1] 기본 환기 충족률 — 시각마다 그때의 생활 모드 목표 (base_vent_compliance 는 시작 모드 하나 · HH205 에서 모드 전환 뒤
    정상 감축까지 미달로 셈). 생활 모드 = 제어기 living_mode 토픽 (없으면 시작 모드)."""
    import yaml
    from pathlib import Path as _P
    modes = yaml.safe_load((_P(__file__).resolve().parents[2] / cfg_metrics["user_modes"]).read_text(encoding="utf-8"))["modes"]
    start = ctx.get("user_mode") or "NORMAL"
    if T.T_LIVING_MODE in df.columns:
        mode = df[T.T_LIVING_MODE].astype(str).str.extract(r'"mode": "([A-Z]+)"')[0].ffill().fillna(start).to_numpy()
    else:
        mode = np.full(len(df), start)
    target = np.array([float((modes.get(m) or {}).get("base_vent_m3h") or 0.0) for m in mode])
    supplied = (df["truth.q_intake_m3h"] + df["truth.q_window_m3h"] + df["truth.q_inf_m3h"]
                - float(ctx.get("q_inf0_m3h", 0.0))).to_numpy()
    need = occ & (target > 0)
    if not need.any():
        return math.nan
    return float((supplied[need] >= target[need] - cfg_metrics["base_vent_tolerance_m3h"]).mean())


def _heating_metrics(df: pd.DataFrame, t: np.ndarray, dt_s: float, hc: dict[str, Any], occ: np.ndarray) -> dict[str, float]:
    """난방 지표 (docs/14 §8) — 가스 · 전기 · 비용(원) · 재실 중 추위 K·h · 최저 실내 · 보일러 점화 횟수."""
    out: dict[str, float] = {}
    gas_kwh = float(df["energy_wh.boiler_gas"].iloc[-1]) / 1000.0 if "energy_wh.boiler_gas" in df.columns else 0.0
    elec_cols = [c for c in df.columns if c.startswith("energy_wh.") and c != "energy_wh.boiler_gas"]
    elec_kwh = float(sum(df[c].iloc[-1] for c in elec_cols)) / 1000.0
    out["gas_kwh"] = gas_kwh
    out["electric_kwh"] = elec_kwh
    out["energy_cost_won"] = gas_kwh * float(hc.get("gas_won_per_kwh", math.nan)) + elec_kwh * float(hc.get("electric_won_per_kwh", math.nan))
    temp = df["truth.temperature_c"].to_numpy()
    cold = np.full(len(df), float((hc.get("cold_below_c") or {}).get("default", 20.0)))
    if T.T_LIVING_MODE in df.columns:
        for mode, thr in (hc.get("cold_below_c") or {}).items():
            if mode != "default":
                m = df[T.T_LIVING_MODE].astype(str).str.contains(f'"mode": "{mode}"', regex=False).to_numpy()
                cold[m] = float(thr)
    deficit = np.clip(cold - temp, 0.0, None) * occ
    out["cold_discomfort_kh"] = float(deficit.sum() * dt_s / 3600.0)
    out["min_temp_c"] = float(temp.min())
    b = df["truth.boiler_burning"].astype(float).to_numpy()
    out["boiler_ignitions"] = float(((b[1:] > 0.5) & (b[:-1] < 0.5)).sum())
    out["expected_cost_heating"] = out["energy_cost_won"] + float(hc.get("cold_won_per_kh", math.nan)) * out["cold_discomfort_kh"]
    # [v1.32-H M6] 보일러 고장 알림 지연 = 첫 조절기 점화 요구(참값) → H_BOILER_FAULT 알림 (s) · 요구 없음 = NaN · 알림 없음 = inf
    if "truth.boiler_call" in df.columns:
        call = df["truth.boiler_call"].astype(float).to_numpy() > 0.5
        al = (df[T.T_ALERTS].fillna("[]").map(lambda x: any(a.get("code") == "H_BOILER_FAULT" for a in json.loads(x))).to_numpy(bool)
              if T.T_ALERTS in df.columns else np.zeros(len(df), dtype=bool))
        out["boiler_fault_alert_delay_s"] = (math.nan if not call.any() else
                                             float(t[al.argmax()] - t[call.argmax()]) if al.any() else math.inf)
    return out


# ---- 안전한 식 평가 ------------------------------------------------------------------

_ANCHOR_RE = r"(?P<anchor>[A-Za-z_][A-Za-z0-9_]*|[0-9.]+)"
_FORMS = [
    ("within", re.compile(rf"^(?P<expr>.+?)\s+within\s+(?P<n>[0-9.]+)\s+after\s+{_ANCHOR_RE}\s*$")),
    ("by", re.compile(rf"^(?P<expr>.+?)\s+by\s+(?P<n>[0-9.]+)\s+after\s+{_ANCHOR_RE}\s*$")),
    ("during", re.compile(r"^(?P<expr>.+?)\s+during\s+(?P<label>[A-Za-z_][A-Za-z0-9_]*)(?:\s+settle\s+(?P<settle>[0-9.]+))?\s*$")),
    ("when", re.compile(r"^(?P<expr>.+?)\s+when\s+(?P<cond>.+)$")),
    ("forall", re.compile(r"^(?P<expr>.+?)\s+for\s+all\s+t\s*$")),
]

_CMP = {ast.Lt: np.less, ast.LtE: np.less_equal, ast.Gt: np.greater, ast.GtE: np.greater_equal,
        ast.Eq: np.equal, ast.NotEq: np.not_equal}
_BIN = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide}


class _Evaluator:
    def __init__(self, names: dict[str, Any], funcs: dict[str, Callable[..., Any]], baselines: dict[str, dict]):
        self.names, self.funcs, self.baselines = names, funcs, baselines

    def eval(self, text: str) -> Any:
        return self._node(ast.parse(text.strip(), mode="eval").body)

    def _node(self, n: ast.AST) -> Any:
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in self.names:
                raise NameError(f"알 수 없는 이름 '{n.id}' — 별칭 · 지표 · 앵커가 아니다")
            return self.names[n.id]
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id.startswith("baseline_"):
            bl = n.value.id[len("baseline_"):]
            if bl not in self.baselines:
                raise Pending(f"baseline {bl} 결과 없음")
            val = self.baselines[bl].get(n.attr, math.nan)
            if isinstance(val, float) and math.isnan(val):
                raise Pending(f"baseline {bl} 의 {n.attr} 계산 불가")
            return val
        if isinstance(n, ast.Compare):
            left = self._node(n.left)
            result = None
            for op, right_n in zip(n.ops, n.comparators):
                right = self._node(right_n)
                r = _CMP[type(op)](left, right)
                result = r if result is None else np.logical_and(result, r)
                left = right
            return result
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](self._node(n.left), self._node(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            return np.logical_not(self._node(n.operand))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return np.negative(self._node(n.operand))
        if isinstance(n, ast.BoolOp):
            fn = np.logical_and if isinstance(n.op, ast.And) else np.logical_or
            vals = [self._node(v) for v in n.values]
            out = vals[0]
            for v in vals[1:]:
                out = fn(out, v)
            return out
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in self.funcs:
            return self.funcs[n.func.id](*[self._node(a) for a in n.args])
        raise SyntaxError(f"허용되지 않는 구문: {ast.dump(n)[:80]}")


def _active_event_mask(df: pd.DataFrame, name: str) -> np.ndarray:
    col = T.T_ACTIVE_EVENTS
    if col not in df.columns:
        return np.zeros(len(df), dtype=bool)
    return df[col].fillna("[]").map(lambda s: name in json.loads(s)).to_numpy(dtype=bool)


def evaluate(df: pd.DataFrame, criteria: list[str], expect: dict[str, dict], anchors: dict[str, float],
             intervals: dict[str, tuple[float, float]], metrics: dict[str, float],
             baselines: dict[str, dict], own_baseline: str = "") -> list[CriterionResult]:
    t = df["time_s"].to_numpy()
    names: dict[str, Any] = {a: (df[c].ffill() if a.startswith("cmd_") else df[c]).to_numpy(dtype=float)
                             for a, c in ALIASES.items() if c in df.columns}
    names.update(metrics)
    names.update(anchors)
    names["t"] = t

    def value_at(alias: str, when: float) -> float:
        return float(np.interp(when, t, df[ALIASES[alias]].to_numpy(dtype=float)))

    def entries(name: str) -> int:
        m = _active_event_mask(df, name)
        return int(np.sum(m[1:] & ~m[:-1]) + (1 if m.size and m[0] else 0))

    def ac_fan_is(level: str) -> np.ndarray:
        col = df["act.ac_fan"].astype(str).to_numpy() if "act.ac_fan" in df.columns else np.array([""] * len(df))
        on = df["act.ac_power"].astype(bool).to_numpy() if "act.ac_power" in df.columns else np.zeros(len(df), bool)
        return ~on | (col == level)

    def ended_for(name: str, seconds: float) -> np.ndarray:
        """이벤트가 한 번 이상 활성이었다가 끝난 뒤 seconds 이상 지난 시각."""
        m = _active_event_mask(df, name)
        out = np.zeros(len(df), dtype=bool)
        last_end = None
        for i in range(len(df)):
            if m[i]:
                last_end = None
            elif i > 0 and m[i - 1]:
                last_end = t[i]
            if last_end is not None and t[i] - last_end >= seconds:
                out[i] = True
        return out

    def basis_is(name: str) -> np.ndarray:
        col = T.T_OCCUPANCY_BASIS
        return (df[col].astype(str) == name).to_numpy() if col in df.columns else np.zeros(len(df), dtype=bool)

    def alert_raised(code: str) -> np.ndarray:
        """/studio/state/alerts 에 그 코드의 알림이 이미 나온 시각."""
        col = T.T_ALERTS
        if col not in df.columns:
            return np.zeros(len(df), dtype=bool)
        return df[col].fillna("[]").map(lambda s: any(a.get("code") == code for a in json.loads(s))).to_numpy(bool)

    def _state_is(col: str, name: str) -> np.ndarray:
        return (df[col].astype(str) == name).to_numpy() if col in df.columns else np.zeros(len(df), dtype=bool)

    def mode_is(name: str) -> np.ndarray:
        col = T.T_LIVING_MODE                          # JSON {"mode", "path", ...}
        if col not in df.columns:
            return np.zeros(len(df), dtype=bool)
        return df[col].ffill().fillna("{}").map(lambda s: json.loads(s).get("mode") == name).to_numpy(bool)

    def feasibility_is(name: str) -> np.ndarray:
        return _state_is(T.T_CONTROL_FEASIBILITY, name)

    funcs = {"event_entered": lambda name: _active_event_mask(df, name), "value_at": value_at,
             "mode_is": mode_is, "feasibility_is": feasibility_is, "abs": np.abs,
             "basis_is": basis_is, "alert_raised": alert_raised,
             "ended_for": ended_for,
             "entries": entries, "ac_fan_is": ac_fan_is,
             "ratio": lambda cond: float(np.mean(np.asarray(cond, dtype=bool)))}
    ev = _Evaluator(names, funcs, baselines)

    texts = list(criteria)
    for alias, rule in (expect or {}).items():
        scope = f" during {rule['during']}" if "during" in rule else " for all t"
        if "settle_s" in rule:                   # 감지 지연 허용 — 구간 시작 + settle_s 부터 본다
            scope += f" settle {rule['settle_s']}"
        for key, op in (("max", "<="), ("min", ">="), ("eq", "==")):
            if key in rule:
                texts.append(f"{alias} {op} {rule[key]}{scope}")

    results: list[CriterionResult] = []
    for text in texts:
        if own_baseline and f"baseline_{own_baseline}." in text:
            results.append(CriterionResult(text, NA, f"baseline {own_baseline} 자신의 실행"))
            continue
        try:
            results.append(_evaluate_one(text, ev, t, anchors, intervals))
        except Pending as p:
            results.append(CriterionResult(text, PENDING, str(p)))
        except Exception as exc:   # 문법 오류 · 없는 열 — 판정 실패와 구분해 기록
            results.append(CriterionResult(text, ERROR, f"{type(exc).__name__}: {exc}"))
    return results


def _all(x: Any, mask: np.ndarray | None = None) -> bool:
    arr = np.asarray(x)
    if arr.ndim == 0:
        return bool(arr)
    return bool(np.all(arr[mask])) if mask is not None else bool(np.all(arr))


def _evaluate_one(text: str, ev: _Evaluator, t: np.ndarray, anchors: dict[str, float],
                  intervals: dict[str, tuple[float, float]]) -> CriterionResult:
    for form, rx in _FORMS:
        m = rx.match(text.strip())
        if not m:
            continue
        if form in ("within", "by"):
            a = m["anchor"]
            start = float(a) if re.fullmatch(r"[0-9.]+", a) else anchors.get(a)
            if start is None:
                raise NameError(f"앵커 '{a}' 없음 (있는 앵커: {sorted(anchors)})")
            end = start + float(m["n"])
            arr = np.broadcast_to(np.asarray(ev.eval(m["expr"])).astype(bool), t.shape)
            if form == "by":
                if end > t[-1]:
                    raise NameError(f"판정 시각 {end:.0f}s 가 실행 시간({t[-1]:.0f}s)을 넘는다")
                i = int(np.searchsorted(t, end))
                ok = bool(arr[i])
                return CriterionResult(text, PASS if ok else FAIL, f"t={t[i]:.0f}s 에서 {'참' if ok else '거짓'}")
            hit = _first_time(t, (t >= start) & (t <= end) & arr)
            ok = not math.isnan(hit)
            return CriterionResult(text, PASS if ok else FAIL,
                                   f"t={hit:.0f}s (구간 {start:.0f}–{end:.0f}s)" if ok else f"구간 {start:.0f}–{end:.0f}s 에 없음")
        if form == "during":
            label = m["label"]
            if label not in intervals:
                raise NameError(f"label '{label}' 없음 (있는 label: {sorted(intervals)})")
            s, e = intervals[label]
            s += float(m["settle"] or 0.0)
            ok = _all(ev.eval(m["expr"]), (t >= s) & (t < e))
            return CriterionResult(text, PASS if ok else FAIL, f"구간 {s:.0f}–{e:.0f}s")
        if form == "when":
            mask = np.asarray(ev.eval(m["cond"]), dtype=bool)
            ok = _all(ev.eval(m["expr"]), mask) if mask.any() else True
            return CriterionResult(text, PASS if ok else FAIL, f"해당 시각 {int(mask.sum())}개")
        if form == "forall":
            ok = _all(ev.eval(m["expr"]))
            return CriterionResult(text, PASS if ok else FAIL)
    val = ev.eval(text)
    ok = _all(val)
    detail = "" if np.asarray(val).ndim else f"값={val}"
    return CriterionResult(text, PASS if ok else FAIL, detail)
