"""실험 하네스 실행기 (docs/03 §8 하네스 동작 규약).

1 로드 · 전개 → 2 run_mode 선택 → 3 초기 상태 · 시드 → 4 events · injections 주입
→ 5 로그 CSV (results/raw/<id>_<baseline>_<rep>.csv) → 6 pass_criteria → 7 results/summary.csv
"""

from __future__ import annotations

import json
import math
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from env_model import load_config
from harness import criteria as C
from harness.controllers import ControllerNotImplemented, make_controller
from harness.fast_world import (FastActuators, WorldInputs, initial_actuators, make_model, sensor_topics)
from harness.scenario import Run, expand_runs, load_scenarios
from harness.sensing import PersonTruth, SensingWorld
from controller.params import load_params
from sensors.occupancy import OccupancyJudge
from sensors.power_monitor import PowerMonitor
from harness.timeline import build_timeline
from interfaces import topics as T

REPO = Path(__file__).resolve().parents[2]


@dataclass
class RunResult:
    run: Run
    status: str                          # PASS | FAIL | PENDING | ERROR | SKIPPED
    controller: str
    df: pd.DataFrame | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    criteria: list[C.CriterionResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    wall_s: float = 0.0


def load_harness_config(path: str | Path = REPO / "config" / "harness.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _flatten(prefix: str, d: dict[str, Any], row: dict[str, Any]) -> None:
    for k, v in d.items():
        if isinstance(v, dict):
            _flatten(f"{prefix}{k}.", v, row)
        else:
            row[f"{prefix}{k}"] = v


def _dew(t: float, rh: float, env_cfg) -> float:
    from env_model.psychro import dew_point_c
    return dew_point_c(t, rh, env_cfg.get("condensation.magnus_b"), env_cfg.get("condensation.magnus_c"))


def run_fast(run: Run, hcfg: dict[str, Any], env_cfg, controller, controller_name: str) -> RunResult:
    """고속 모드 1회 실행. 제어기는 정책 주기(dt)마다 최신 토픽 값을 받는다."""
    sc = run.scenario
    fm = hcfg["fast_mode"]
    dt, log_every = float(fm["dt_s"]), float(fm["log_interval_s"])
    duration = float(sc["duration_s"])
    np.random.seed(run.seed)                      # 이후 노이즈 · 확률 주입이 이 시드를 쓴다
    rng = np.random.default_rng(run.seed)

    tl = build_timeline(sc)
    world = WorldInputs.from_scenario(sc)
    if sc.get("environment_overrides"):             # 시나리오별 참값 계수 (예: X6 침기 0.1 ACH)
        env_cfg = env_cfg.with_overrides(sc["environment_overrides"])
    model = make_model(env_cfg, sc)
    devices = hcfg["appliance_profiles"][sc.get("appliance_profile", "full")]
    acts = FastActuators(initial_actuators(sc), fm["actuator_time_constant_s"], devices)
    grade = hcfg["outdoor_api"]

    # 재실 판정 노드 (sensors/occupancy) — 설정은 시스템 상수 thresholds.yaml occupancy 블록
    occ_params = load_params().th["occupancy"]
    sensing = SensingWorld(cfg=hcfg["mmwave"], rng=np.random.default_rng(run.seed + 7919),
                           judge=OccupancyJudge(occ_params, world.occupancy),
                           person=PersonTruth(world.occupancy, world.occupant_zone, world.motion,
                                              phone_with_person=world.phone == "person",
                                              left_phone_home=world.phone == "home"))
    was_present = world.occupancy
    # 가전 브릿지 · 전력 감시 노드
    th = load_params().th
    # IR 누락은 기준선마다 독립 추첨 — 송신 시각 · 내용이 제어기마다 달라 'n번째 송신'끼리 같은 난수를 쓰면
    # 한 번의 우연(2 %)이 모든 기준선의 첫 명령을 함께 지워 비교가 왜곡된다 (C1). 시드로 재현은 그대로.
    acts.rng = np.random.default_rng([run.seed, 104729, zlib.crc32(run.baseline.encode())])
    base_miss = th["appliances"]["ir"]["sim_miss_probability"]
    pmon = PowerMonitor(th["power_monitor"], th["events"]["appliance_no_response"]["power_confirm_s"])
    logged_cmds = 0

    controller.reset({"scenario": sc, "baseline": run.baseline, "seed": run.seed, "rng": rng})
    user_cmds: dict[str, Any] = {T.C_MODE: world.user_mode}
    if world.activity:
        user_cmds[T.C_ACTIVITY] = world.activity
    ctrl_state: dict[str, Any] = {}
    reasons_fn = getattr(controller, "reasons", None)
    # 제어기 시각 = 하루 기준 초 (시나리오 time_of_day + 경과) — ROS 노드도 같은 기준(현지 자정부터 초)을 쓴다
    hh, mm = str(sc["initial"].get("time_of_day", "00:00")).split(":")
    clock0 = (int(hh) * 60 + int(mm)) * 60.0

    rows: list[dict[str, Any]] = []
    src, extra_power = tl.sources_at(0.0)
    obs = model.step(0.0, acts.actual, world.ext, src, world.occupancy_model())   # 초기 관측 (적분 없음)
    steps = int(round(duration / dt))
    next_log = 0.0
    last_ac_cmd: dict[str, Any] = {}
    for k in range(steps + 1):
        now = k * dt
        for change in tl.events_between(now - dt if k else -1.0, now + 1e-9 if k == 0 else now):
            world.apply(change)
            if "user_mode" in change:
                user_cmds[T.C_MODE] = world.user_mode
            if "activity" in change:
                user_cmds[T.C_ACTIVITY] = world.activity
        src, extra_power = tl.sources_at(now, acts.cooktop_relay)
        hung = tl.laundry_hung_between(now - dt if k else -1.0, now)
        if hung > 0:
            model.hang_laundry(model.state.laundry_moisture_g + hung)

        # 사람 참값 → 재실 판정 노드
        p = sensing.person
        if world.occupancy and not was_present:
            p.arrived_at = now                                     # 귀가 — 잠시 방 안을 걷는다
        was_present = world.occupancy
        silent = bool(tl.active_kind(now, "radar"))                # 욕실 등 레이더 시야 밖
        p.present, p.motion = world.occupancy, world.motion
        p.zone = "none" if silent else world.occupant_zone
        p.phone_with_person, p.left_phone_home = world.phone == "person", world.phone == "home"
        for iv in tl.instants_between(now - dt if k else -1.0, now, "door_sensor_stuck"):
            sensing.door_sensor_stuck_at = tl.door_open_at(now)    # 고장 — 접점 값이 그 자리에 멈춘다
        extra_m = {int(iv.spec["curtain"].get("gate", 4)): float(iv.spec["curtain"].get("moving_energy", 35.0))
                   for iv in tl.active_kind(now, "curtain")}
        extra_s = {int(iv.spec["neighbor"].get("gate", 6)): float(iv.spec["neighbor"].get("static_energy", 45.0))
                   for iv in tl.active_kind(now, "neighbor")}
        if tl.active_kind(now, "mmwave_lost"):                    # mmWave 신호 두절 — 노드가 구간 신호를 못 받는다
            sensing.judge.mmwave_lost = True
        occ, wifi, contact = sensing.step(now, tl.door_open_at(now), bool(tl.active_kind(now, "wifi")),
                                          extra_power, extra_m, extra_s)
        for iv in tl.instants_between(now - dt if k else -1.0, now, "manual"):
            acts.manual(iv.spec["manual"]["device"], iv.spec["manual"]["action"])
        miss = tl.active_kind(now, "ir_miss")
        acts.ir_miss_p = float(miss[0].spec.get("probability", 1.0)) if miss else base_miss
        for dev, tcmd in acts.cmd_log[logged_cmds:]:
            pmon.note_command(dev, tcmd)
        logged_cmds = len(acts.cmd_log)
        plug_power = {**{d: obs["appliance_power_w"].get(d, 0.0) for d in ("ac", "dehumidifier", "humidifier")},
                      **extra_power}
        app_states = pmon.update(now, plug_power)

        inbox = sensor_topics(obs, world, contact, extra_power,
                              grade["pm_grade_bounds_ugm3"], grade["pm_grade_names"], occ=occ, wifi=wifi)
        inbox[T.T_OCCUPANCY_BASIS] = occ.basis                    # 재실 노드가 내는 상태 토픽
        inbox[T.T_APPLIANCE_STATES] = json.dumps(app_states)      # 전력 감시 노드
        if tl.active_kind(now, "lux_invalid"):
            inbox[T.S_ILLUMINANCE] = float("nan")                  # 조도 센서 무효값
        inbox.update(acts.state_topics())
        inbox.update(ctrl_state)
        inbox.update(user_cmds)
        outbox = controller.step(clock0 + now, inbox) or {}
        ctrl_state.update({tp: v for tp, v in outbox.items() if tp.startswith(f"{T.P}/state/")})
        acts.command(outbox, now)
        if T.C_AC in outbox:                           # 제어기가 마지막으로 낸 에어컨 명령 (IR 누락과 무관한 '결정')
            last_ac_cmd = json.loads(outbox[T.C_AC])

        if now + 1e-9 >= next_log:
            row: dict[str, Any] = {"time_s": now}
            _flatten("truth.", {k2: v for k2, v in obs.items()
                                if k2 not in ("appliance_power_w", "energy_wh", "time_s")}, row)
            _flatten("energy_wh.", obs["energy_wh"], row)
            _flatten("act.", {f: getattr(acts.actual, f) for f in
                              ("window_open_ratio", "blind_angle_deg", "exhaust_fan_rpm", "intake_fan_rpm",
                               "range_hood_level", "purifier_level", "dehumidifier", "humidifier",
                               "ceiling_fan", "ceiling_light_pct", "desk_light_pct")}, row)
            ac = acts.actual.ac
            row["act.ac"] = acts.state_topics()[T.T_AC]
            row["act.ac_power"] = ac.power
            row["cmd.ac_power"] = bool(last_ac_cmd.get("power", False))
            row["cmd.ac_sent"] = T.C_AC in outbox      # 이 주기에 에어컨 명령을 냈나 (E9 · E12 판정)
            row["act.ac_cool"] = ac.power and ac.mode == "cool"
            row["act.ac_dry"] = ac.power and ac.mode == "dry"
            row["act.ac_setpoint"] = ac.setpoint_c
            row["act.ac_fan"] = acts.ac_fan
            row["act.cooktop_power"] = acts.cooktop_relay
            row["act.desk_cct"] = acts.desk_cct
            row["bridge.ir_tx_ac"] = acts.ir_tx["ac"]
            row["pm.ac.state"] = app_states.get("ac", {}).get("state", "")
            row["pm.ac.source"] = app_states.get("ac", {}).get("source", "")
            row["pm.ac.run"] = row["pm.ac.state"] == "run"
            row["pm.ac.fan_only"] = row["pm.ac.state"] == "fan_only"
            row["pm.ac.manual"] = row["pm.ac.source"] == "manual"
            row["power.ac_w"] = obs["appliance_power_w"].get("ac", 0.0)
            row["truth.illuminance_lux"] = obs["illuminance_lux"]
            row[T.S_ILLUMINANCE] = inbox[T.S_ILLUMINANCE]
            for tp in (T.S_TEMPERATURE, T.S_HUMIDITY, T.S_PM25, T.S_HOOD_TEMPERATURE, T.S_OCCUPANCY,
                       T.S_DOOR_CONTACT, T.S_OUTDOOR_PM_GRADE):
                row[tp] = inbox[tp]
            for tp, v in outbox.items():
                row[tp] = v if not isinstance(v, (dict, list)) else json.dumps(v)
            for tp, v in ctrl_state.items():
                row.setdefault(tp, v)
            row["truth.occupied"] = world.occupancy
            row["truth.door_open"] = tl.door_open_at(now)
            row[T.T_OCCUPANCY_BASIS] = occ.basis
            row["occ.alerts"] = len(sensing.alerts)
            row[T.S_WIFI_PRESENCE] = wifi
            row["power.total_w"] = sum(float(v) for v in json.loads(inbox[T.S_APPLIANCE_POWER]).values())
            row["ext.outdoor_pm25_ugm3"] = world.ext.outdoor_pm25_ugm3
            row["ext.outdoor_dew_c"] = _dew(world.ext.outdoor_temp_c, world.ext.outdoor_rh_pct, env_cfg)
            row["ext.outdoor_temp_c"] = world.ext.outdoor_temp_c
            row["ext.outdoor_illuminance_lux"] = world.ext.outdoor_illuminance_lux   # 상충 점검 R9 (일사 중 블라인드 열림)
            row["ext.raining"] = world.raining
            row["injections"] = ",".join(tl.active_labels(now))
            if callable(reasons_fn):
                row["ctrl.reasons"] = json.dumps(reasons_fn(), ensure_ascii=False)
            rows.append(row)
            next_log += log_every

        if k == steps:
            break
        acts.update(dt)
        obs = model.step(dt, acts.actual, world.ext, src, world.occupancy_model())

    df = pd.DataFrame(rows)
    notes = [f"미지원 주입: {u}" for u in tl.unsupported]
    if acts.rejected:
        notes.append(f"프로파일에 없는 장치 명령 무시: {acts.rejected}")
    return finish_run(run, df, tl, hcfg, env_cfg, log_every, controller_name, notes)


def _budgets(hcfg: dict[str, Any], um: dict[str, Any]) -> dict[str, Any]:
    """지표 #16 — 이벤트별 예산(thresholds events.<키>.budget) + 예산 소음 등급의 장치 상한(user_modes noise_grades)."""
    bc = hcfg["metrics"].get("budget_check") or {}
    p = load_params()
    out: dict[str, Any] = {}
    for ev_name, key in (bc.get("events") or {}).items():
        b = dict(p.get(f"events.{key}.budget"))
        grade = um["noise_grades"].get(b.get("noise_grade", ""), {})
        b["noise_caps"] = {col: (0.0 if grade_key == "dehumidifier_allowed" and not grade.get(grade_key) else
                                 math.inf if grade_key == "dehumidifier_allowed" else float(grade[grade_key]))
                           for col, grade_key in (bc.get("noise_columns") or {}).items() if grade_key in grade}
        out[ev_name] = b
    return out


def finish_run(run: Run, df: pd.DataFrame, tl, hcfg: dict[str, Any], env_cfg, log_every: float,
               controller_name: str, notes: list[str]) -> RunResult:
    """로그(DataFrame) → 지표 · 앵커 · 구간이 붙은 RunResult. 고속 모드와 물리 모드(scripts/physics_eval.py)가 함께 쓴다."""
    sc = run.scenario
    sources = {iv.label: iv.kind for iv in tl.intervals}
    with open(REPO / hcfg["metrics"]["user_modes"], encoding="utf-8") as f:
        um = yaml.safe_load(f)
    mode0 = sc["initial"].get("user_mode", "NORMAL")
    ctx = {"user_mode": mode0,
           "humidity_range_pct": (um["modes"].get(mode0) or {}).get("humidity_range_pct"),
           "base_vent_m3h": (um["modes"].get(mode0) or {}).get("base_vent_m3h") or 0.0,
           "cooling_setpoint_c": (um["modes"].get(mode0) or {}).get("cooling_setpoint_c"),
           "window_travel_m": load_params().get("window_sensorless.travel_length_m"),
           "q_inf0_m3h": env_cfg.get("air_balance.base_infiltration_ach") * env_cfg.get("room.volume_m3")}
    ctx["budgets"] = _budgets(hcfg, um)
    metrics = C.compute_metrics(df, tl.anchors(), sources, hcfg["metrics"], log_every, ctx)
    res = RunResult(run=run, status="", controller=controller_name, df=df, metrics=metrics, notes=notes)
    res.intervals = {iv.label: (iv.start_s, iv.end_s) for iv in tl.intervals}   # type: ignore[attr-defined]
    res.anchors = tl.anchors()                                                  # type: ignore[attr-defined]
    return res


def _overall(results: list[C.CriterionResult]) -> str:
    st = {r.status for r in results} - {C.NA}
    for s in (C.ERROR, C.FAIL, C.PENDING):
        if s in st:
            return s
    return C.PASS


def run_batch(ids: list[str] | None = None, baselines: list[str] | None = None, reps: int | None = None,
              controller_override: str | None = None, out_dir: str | Path | None = None,
              mode: str = "fast", hcfg: dict[str, Any] | None = None,
              progress=print) -> list[RunResult]:
    hcfg = hcfg or load_harness_config()
    env_cfg = load_config(REPO / hcfg["paths"]["environment_model"])
    scenarios = load_scenarios(REPO / hcfg["paths"]["scenarios"])
    runs = expand_runs(scenarios, ids, baselines, reps)
    out = Path(out_dir) if out_dir else REPO / hcfg["paths"]["results_dir"]
    (out / "raw").mkdir(parents=True, exist_ok=True)

    results: list[RunResult] = []
    by_scenario: dict[str, list[RunResult]] = {}
    for i, run in enumerate(runs, 1):
        spec = controller_override or hcfg["controllers"].get(run.baseline, "unimplemented")
        if run.scenario["run_mode"] != mode:
            r = RunResult(run, "SKIPPED", spec, notes=[f"run_mode={run.scenario['run_mode']} (현재 {mode} 모드)"])
        else:
            t0 = time.perf_counter()
            try:
                r = run_fast(run, hcfg, env_cfg, make_controller(spec), spec)
            except ControllerNotImplemented as exc:
                r = RunResult(run, C.ERROR, spec, notes=[str(exc)])
            except Exception as exc:
                r = RunResult(run, C.ERROR, spec, notes=[f"{type(exc).__name__}: {exc}"])
            r.wall_s = time.perf_counter() - t0
            if r.df is not None:
                r.df.to_csv(out / "raw" / f"{run.run_id}.csv", index=False)
        progress(f"[{i}/{len(runs)}] {run.run_id} · 제어기 {spec} · {r.wall_s:.1f}s")
        results.append(r)
        by_scenario.setdefault(run.scenario_id, []).append(r)

    # 판정 — baseline 간 비교(baseline_A.*)가 있으므로 같은 시나리오의 모든 실행이 끝난 뒤에 한다
    for rs in by_scenario.values():
        judge_group(rs)
    write_summary(results, out / "summary.csv")
    return results


def judge_group(rs: list[RunResult]) -> None:
    """같은 시나리오의 실행들(기준선 · 반복)을 판정한다 — 기준선 비교 판정 때문에 묶어서."""
    for r in rs:
        if r.df is None:
            r.status = r.status or C.ERROR
            continue
        peers = {o.run.baseline: o.metrics for o in rs if o.run.rep == r.run.rep and o.df is not None}
        sc = r.run.scenario
        r.criteria = C.evaluate(r.df, sc.get("pass_criteria") or [], sc.get("expect") or {},
                                r.anchors, r.intervals, r.metrics, peers,   # type: ignore[attr-defined]
                                own_baseline=r.run.baseline)
        r.status = _overall(r.criteria) if r.criteria else C.PASS


def write_summary(results: list[RunResult], path: Path) -> None:
    rows = []
    for r in results:
        row: dict[str, Any] = {
            "run_id": r.run.run_id, "scenario": r.run.scenario_id, "baseline": r.run.baseline,
            "rep": r.run.rep, "seed": r.run.seed, "controller": r.controller, "status": r.status,
            "wall_s": round(r.wall_s, 2),
            "criteria_pass": sum(c.status == C.PASS for c in r.criteria),
            "criteria_total": len(r.criteria),
        }
        for k, v in r.metrics.items():
            row[f"m.{k}"] = None if (isinstance(v, float) and math.isnan(v)) else v
        row["criteria"] = json.dumps([[c.status, c.text, c.detail] for c in r.criteria], ensure_ascii=False)
        row["notes"] = " | ".join(r.notes)
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False)
