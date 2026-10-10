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
    out["condensation_exposure_s"] = float((df["truth.dew_margin_c"] < 0).sum() * dt_s)
    if "pm.ac.state" in df.columns and "truth.ac_state" in df.columns:   # B11 — 전력 기반 상태 판정 정확도
        out["appliance_state_accuracy"] = float((df["pm.ac.state"] == df["truth.ac_state"]).mean())
    out["ir_tx_ac"] = float(df["bridge.ir_tx_ac"].iloc[-1]) if "bridge.ir_tx_ac" in df.columns else math.nan
    out["rule_violation_count"] = (float(df["ctrl.rule_violations"].iloc[-1])
                                   if "ctrl.rule_violations" in df.columns else math.nan)

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
             "mode_is": mode_is, "feasibility_is": feasibility_is,
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
