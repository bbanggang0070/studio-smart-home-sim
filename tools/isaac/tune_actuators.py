"""액추에이터 드라이브 튜닝 · 응답 특성 측정 (W05 T5.1 · T5.2 · T5.4 · T5.6).

창문 · 블라인드 = 위치 제어(목표 램프 + 위치 · 속도 목표), 팬 = 속도 제어.
창문은 드라이브 계수를 스윕해 오버슈트 0 · 정상상태 오차 최소인 조합을 고른다 (브러시 씰 마찰이 있는 상태).
실행: tools/isaac/run.sh python tools/isaac/tune_actuators.py
결과: results/actuators/step_<장치>.csv · tuning.json (커밋하지 않는다) — 고른 계수는 화면에 출력, actuator_limits.yaml 에 옮긴다
"""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

import csv  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

# 스윕 후보 (draft) — 창문 위치 드라이브 [N/m, N·s/m]
WINDOW_SWEEP = [(2000.0, 400.0), (4000.0, 800.0), (8000.0, 1500.0), (15000.0, 3000.0), (30000.0, 6000.0)]


def main() -> None:
    import numpy as np
    import omni.usd
    from isaacsim.core.api import World
    from isaacsim.core.prims import SingleArticulation
    from pxr import UsdPhysics

    from sim.actuators import IsaacActuators, rad_s_to_rpm

    L = yaml.safe_load((REPO / "config" / "scene_layout.yaml").read_text(encoding="utf-8"))
    A = yaml.safe_load((REPO / "config" / "actuator_limits.yaml").read_text(encoding="utf-8"))
    omni.usd.get_context().open_stage(str(REPO / L["usd_path"]))
    stage = omni.usd.get_context().get_stage()
    hz = L["physics"]["steps_per_second"]
    dt = 1.0 / hz
    world = World(stage_units_in_meters=1.0, physics_dt=dt, rendering_dt=1.0 / 60.0)
    out = REPO / "results" / "actuators"
    out.mkdir(parents=True, exist_ok=True)
    travel = L["window"]["travel_m"]
    report: dict = {}

    def setup():
        world.reset()
        arts = {n: SingleArticulation(f"/World/{n}", name=f"{n}_{id(object())}") for n in
                ("window", "blind", "exhaust_fan", "intake_fan", "ceiling_fan")}
        for a in arts.values():
            a.initialize()
        return arts, IsaacActuators(stage, L, A)

    def run(seconds, act, sample):
        rows = []
        for i in range(int(seconds * hz)):
            act.step(dt)
            world.step(render=False)
            rows.append(sample(i * dt))
        return rows

    def position_metrics(rows, goal, start, tol):
        t = np.array([r[0] for r in rows])
        y = np.array([r[2] for r in rows])
        step = goal - start
        over = max(0.0, float(np.max((y - goal) * np.sign(step)))) if step else 0.0
        err = abs(float(y[-1] - goal))
        inside = np.abs(y - goal) <= tol
        settle = float(t[np.argmax(np.cumprod(inside[::-1])[::-1] > 0)]) if inside[-1] else math.inf
        return {"overshoot": round(over, 5), "overshoot_pct": round(100 * over / abs(step), 2) if step else 0.0,
                "final_error": round(err, 5), "settle_s": round(settle, 2)}

    def save(name, header, rows):
        with open(out / f"step_{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    # ---- T5.1 창문 — 드라이브 계수 스윕 ----
    jp = "/World/window/window_prismatic_joint"
    sweep = []
    for k, c in WINDOW_SWEEP:
        d = UsdPhysics.DriveAPI(stage.GetPrimAtPath(jp), "linear")
        d.GetStiffnessAttr().Set(k)
        d.GetDampingAttr().Set(c)
        arts, act = setup()
        win = arts["window"]
        wd_ = win.get_dof_index("window_prismatic_joint")       # 패드 스프링 조인트가 있어 DOF 2개
        rows, metrics = [], []
        start = 0.0
        for goal_ratio in (0.35, 1.0, 0.0):
            act.set_window_ratio(goal_ratio)
            seg = run(16.0, act, lambda t: (t, act.window_ramp.value, float(win.get_joint_positions()[wd_]),
                                            float(np.asarray(win.get_measured_joint_efforts())[wd_])))
            metrics.append(position_metrics(seg, goal_ratio * travel, start, tol=0.002))
            start = goal_ratio * travel
            rows += seg
        worst = {"overshoot_mm": max(m["overshoot"] for m in metrics[:2]) * 1000,     # 닫힘(0)은 씰에 닿아 제외
                 "final_error_mm": max(m["final_error"] for m in metrics[:2]) * 1000,
                 "close_error_mm": metrics[2]["final_error"] * 1000,
                 "settle_s": max(m["settle_s"] for m in metrics[:2])}
        sweep.append({"stiffness": k, "damping": c, **{k2: round(v, 2) for k2, v in worst.items()}})
        save(f"window_k{int(k)}", ["t_s", "target_m", "q_m", "effort_n"], rows)
        print(f"창문 k={k:.0f} c={c:.0f} → 오버슈트 {worst['overshoot_mm']:.2f} mm · 정상오차 {worst['final_error_mm']:.2f} mm "
              f"· 닫힘 오차 {worst['close_error_mm']:.2f} mm · 정착 {worst['settle_s']:.1f} s", flush=True)
    # 선택: 오버슈트 < 0.5 mm · 닫힘(씰 · 브러시 반발을 이기고) 오차 ≤ 1 mm 중 가장 무른 드라이브 (반력 측정이 부드럽게)
    ok = [s for s in sweep if s["overshoot_mm"] < 0.5 and s["close_error_mm"] <= 1.0]
    best = min(ok or sweep, key=lambda s: (s["stiffness"], s["final_error_mm"]))
    report["window"] = {"sweep": sweep, "chosen": best,
                        "dod_error_pct": round(best["final_error_mm"] / 1000 / travel * 100, 3)}
    d = UsdPhysics.DriveAPI(stage.GetPrimAtPath(jp), "linear")
    d.GetStiffnessAttr().Set(best["stiffness"])
    d.GetDampingAttr().Set(best["damping"])
    print(f"→ 창문 선택: k={best['stiffness']:.0f} c={best['damping']:.0f} · 오차 {report['window']['dod_error_pct']:.3f} % "
          f"(DoD ±2 %)", flush=True)

    # ---- T5.1 블라인드 ----
    arts, act = setup()
    bl = arts["blind"]
    rows, metrics, start = [], [], 0.0
    for goal in (45.0, 90.0, 0.0):
        act.set_blind_deg(goal)
        seg = run(5.0, act, lambda t: (t, act.blind_ramp.value, float(np.degrees(bl.get_joint_positions()[0]))))
        metrics.append(position_metrics(seg, goal, start, tol=0.5))
        start = goal
        rows += seg
    save("blind", ["t_s", "target_deg", "angle_deg"], rows)
    report["blind"] = {"steps": metrics, "max_error_deg": max(m["final_error"] for m in metrics),
                       "max_overshoot_deg": max(m["overshoot"] for m in metrics)}
    print(f"블라인드 → 오차 최대 {report['blind']['max_error_deg']:.2f}° · 오버슈트 {report['blind']['max_overshoot_deg']:.2f}° "
          f"(DoD ±2°)", flush=True)

    # ---- T5.2 팬 — 속도 스텝 (실링팬은 정 · 역) ----
    seq = {"exhaust_fan": (1000.0, 2000.0, 0.0), "intake_fan": (700.0, 1400.0, 0.0), "ceiling_fan": (100.0, 200.0, -100.0)}
    report["fans"] = {}
    seg_s = {"exhaust_fan": 4.0, "intake_fan": 4.0, "ceiling_fan": 12.0}   # 실링팬은 관성이 커서 정 → 역 전환이 느리다
    for name, targets in seq.items():
        arts, act = setup()
        fan = arts[name]
        rows, res = [], []
        for tgt in targets:
            act.set_fan_rpm(name, tgt)
            seg = run(seg_s[name], act, lambda t: (t, tgt, rad_s_to_rpm(float(fan.get_joint_velocities()[0]))))
            y = np.array([r[2] for r in seg])
            prev = rows[-1][2] if rows else 0.0
            span = tgt - prev
            r10 = np.argmax((y - prev) * np.sign(span) >= 0.1 * abs(span)) if span else 0
            r90 = np.argmax((y - prev) * np.sign(span) >= 0.9 * abs(span)) if span else 0
            err_pct = abs(y[-1] - tgt) / max(abs(tgt), 1.0) * 100 if tgt else abs(y[-1])
            over = max(0.0, float(np.max((y - tgt) * np.sign(span)))) if span else 0.0
            res.append({"target_rpm": tgt, "final_rpm": round(float(y[-1]), 1), "error_pct": round(float(err_pct), 2),
                        "rise_s": round(float((r90 - r10) * dt), 3), "overshoot_rpm": round(over, 1)})
            rows += seg
        save(name, ["t_s", "target_rpm", "rpm"], rows)
        report["fans"][name] = res
        print(f"{name} → " + " · ".join(f"{r['target_rpm']:.0f}→{r['final_rpm']:.0f} rpm ({r['error_pct']:.1f} %, "
                                        f"상승 {r['rise_s']:.2f} s)" for r in res), flush=True)

    (out / "tuning.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== 튜닝 결과 → results/actuators/tuning.json ===", flush=True)


try:
    main()
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
finally:
    app.close()
