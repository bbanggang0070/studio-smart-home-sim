"""실험 하네스 실행기 (docs/03 §8 하네스 동작 규약).

1 로드 · 전개 → 2 run_mode 선택 → 3 초기 상태 · 시드 → 4 events · injections 주입
→ 5 로그 CSV (results/raw/<id>_<baseline>_<rep>.csv) → 6 pass_criteria → 7 results/summary.csv
"""

from __future__ import annotations

import json
import math
import time
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
    model = make_model(env_cfg, sc)
    devices = hcfg["appliance_profiles"][sc.get("appliance_profile", "full")]
    acts = FastActuators(initial_actuators(sc), fm["actuator_time_constant_s"], devices)
    grade = hcfg["outdoor_api"]

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
    for k in range(steps + 1):
        now = k * dt
        for change in tl.events_between(now - dt if k else -1.0, now + 1e-9 if k == 0 else now):
            world.apply(change)
            if "user_mode" in change:
                user_cmds[T.C_MODE] = world.user_mode
            if "activity" in change:
                user_cmds[T.C_ACTIVITY] = world.activity
        src, extra_power = tl.sources_at(now)

        inbox = sensor_topics(obs, world, tl.door_open_at(now), extra_power,
                              grade["pm_grade_bounds_ugm3"], grade["pm_grade_names"])
        inbox.update(acts.state_topics())
        inbox.update(ctrl_state)
        inbox.update(user_cmds)
        outbox = controller.step(clock0 + now, inbox) or {}
        ctrl_state.update({tp: v for tp, v in outbox.items() if tp.startswith(f"{T.P}/state/")})
        acts.command(outbox)

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
            row["act.ac_cool"] = ac.power and ac.mode == "cool"
            row["act.ac_dry"] = ac.power and ac.mode == "dry"
            row["act.ac_setpoint"] = ac.setpoint_c
            for tp in (T.S_TEMPERATURE, T.S_HUMIDITY, T.S_PM25, T.S_HOOD_TEMPERATURE, T.S_OCCUPANCY,
                       T.S_DOOR_CONTACT, T.S_OUTDOOR_PM_GRADE):
                row[tp] = inbox[tp]
            for tp, v in outbox.items():
                row[tp] = v if not isinstance(v, (dict, list)) else json.dumps(v)
            for tp, v in ctrl_state.items():
                row.setdefault(tp, v)
            row["ext.outdoor_pm25_ugm3"] = world.ext.outdoor_pm25_ugm3
            row["ext.outdoor_temp_c"] = world.ext.outdoor_temp_c
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
    sources = {iv.label: iv.kind for iv in tl.intervals}
    with open(REPO / hcfg["metrics"]["user_modes"], encoding="utf-8") as f:
        um = yaml.safe_load(f)
    mode0 = sc["initial"].get("user_mode", "NORMAL")
    ctx = {"user_mode": mode0,
           "base_vent_m3h": (um["modes"].get(mode0) or {}).get("base_vent_m3h") or 0.0,
           "cooling_setpoint_c": (um["modes"].get(mode0) or {}).get("cooling_setpoint_c"),
           "q_inf0_m3h": env_cfg.get("air_balance.base_infiltration_ach") * env_cfg.get("room.volume_m3")}
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
    write_summary(results, out / "summary.csv")
    return results


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
