"""창문 무부하 기준 반력 프로파일 수집 (W05 T5.8 → W10 센서리스 입력 Î_expected(x)).

장애물 없이 개방 → 폐쇄 → 개방을 5회 왕복(최대 속도 램프)하며 조인트 반력(드라이브 힘)과 씰 접촉력을 기록하고,
20 mm 구간 · 방향별 평균을 낸다. 전류 환산: I = I0 + |F|·r / (G·Kt·η)  (thresholds window_sensorless — docs/04 §6).
Zone(폐쇄 진행률 기준, docs/04): A 기동 0–5 % · B 주행 5–85 % · C 엔드존 85–97 % · D 밀착 97–100 %.

실행: tools/isaac/run.sh python tools/isaac/window_profile.py
결과: models/window_reference_profile.csv (W10 입력 — 커밋) · results/actuators/window_profile_raw.csv · window_profile.png
"""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

import csv  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

ROUND_TRIPS = 5
BIN_M = 0.020


def main() -> None:
    import numpy as np
    import omni.usd
    from isaacsim.core.api import World
    from isaacsim.core.prims import SingleArticulation
    from isaacsim.sensors.physics import ContactSensor

    from sim.actuators import IsaacActuators

    L = yaml.safe_load((REPO / "config" / "scene_layout.yaml").read_text(encoding="utf-8"))
    A = yaml.safe_load((REPO / "config" / "actuator_limits.yaml").read_text(encoding="utf-8"))
    th = yaml.safe_load((REPO / "config" / "thresholds.yaml").read_text(encoding="utf-8"))
    ws = th["smart_home_controller"]["ros__parameters"]["window_sensorless"]
    omni.usd.get_context().open_stage(str(REPO / L["usd_path"]))
    stage = omni.usd.get_context().get_stage()
    hz = L["physics"]["steps_per_second"]
    dt = 1.0 / hz
    world = World(stage_units_in_meters=1.0, physics_dt=dt, rendering_dt=1.0 / 60.0)
    contact = world.scene.add(ContactSensor(prim_path="/World/window/window_panel/contact_sensor", name="pc",
                                            min_threshold=0.0, max_threshold=1.0e7, radius=-1))
    world.reset()
    win = SingleArticulation("/World/window", name="window")
    win.initialize()
    act = IsaacActuators(stage, L, A)
    wdof = win.get_dof_index("window_prismatic_joint")       # 패드 스프링 조인트가 더해져 DOF 가 2개
    travel = L["window"]["travel_m"]
    amp_per_n = ws["pinion_radius_m"] / (ws["gear_ratio"] * ws["torque_constant_nm_per_a"] * ws["mechanical_efficiency"])

    raw = []

    compress = L["window"]["seal_compress_m"]

    def run(goal_ratio, direction, trip, seconds):
        act.set_window_ratio(goal_ratio)
        if goal_ratio == 0.0:                       # 닫힘은 씰을 눌러 닫는다 (Zone D 압착)
            act.window_ramp.set_goal(-compress)
        for _ in range(int(seconds * hz)):
            act.step(dt)
            world.step(render=False)
            q = float(win.get_joint_positions()[wdof])
            v = float(win.get_joint_velocities()[wdof])
            f = float(np.asarray(win.get_measured_joint_efforts())[wdof])
            c = float(contact.get_current_frame().get("force", 0.0))
            raw.append((trip, direction, q, v, f, c))

    settle = travel / A["window_prismatic_joint"]["max_speed_mps"] + 3.0
    run(0.0, "close", 0, 2.0)                                # 닫힘에서 시작
    for trip in range(1, ROUND_TRIPS + 1):
        run(1.0, "open", trip, settle)
        run(0.0, "close", trip, settle)

    out = REPO / "results" / "actuators"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "window_profile_raw.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["trip", "direction", "q_m", "v_mps", "effort_n", "contact_n"])
        w.writerows(raw)

    arr = np.array([(r[2], r[3], r[4], r[5]) for r in raw if r[0] > 0])
    dirs = np.array([r[1] for r in raw if r[0] > 0])
    nb = int(round(travel / BIN_M))
    rows = []
    for d in ("open", "close"):
        m = dirs == d
        q, v, f, c = arr[m].T
        moving_or_pressing = (np.abs(v) > 1e-4) | (c > 0.5)   # 정지 · 대기 구간은 뺀다 (씰 압착은 넣는다)
        for b in range(nb):
            lo, hi = b * BIN_M, (b + 1) * BIN_M
            sel = moving_or_pressing & (q >= lo - (0.01 if b == 0 else 0.0)) & (q < hi)
            if not sel.any():
                continue
            fa = np.abs(f[sel])
            prog = (travel - (lo + hi) / 2) / travel * 100 if d == "close" else (lo + hi) / 2 / travel * 100
            zone = ("A" if prog < 5 else "B" if prog < 85 else "C" if prog < 97 else ("D" if d == "close" else "C"))
            rows.append({"direction": d, "bin_lo_m": round(lo, 3), "bin_hi_m": round(hi, 3), "progress_pct": round(prog, 1),
                         "zone": zone, "force_mean_n": round(float(fa.mean()), 2), "force_std_n": round(float(fa.std()), 2),
                         "force_max_n": round(float(fa.max()), 2), "contact_mean_n": round(float(c[sel].mean()), 2),
                         "current_expected_a": round(ws["no_load_current_a"] + float(fa.mean()) * amp_per_n, 4),
                         "samples": int(sel.sum())})
    prof = REPO / "models" / "window_reference_profile.csv"
    with open(prof, "w", newline="", encoding="utf-8") as fh:
        fh.write("# 자동 생성 — tools/isaac/window_profile.py (W05 T5.8) · 무부하 기준 반력 · 20 mm 구간 · 5회 왕복 평균\n")
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    # Zone 판정 (폐쇄 방향)
    cl = [r for r in rows if r["direction"] == "close"]
    z = {k: [r["force_mean_n"] for r in cl if r["zone"] == k] for k in "ABCD"}
    b_mean = float(np.mean(z["B"])) if z["B"] else 0.0
    c_vals = [r["force_mean_n"] for r in sorted(cl, key=lambda r: r["progress_pct"]) if r["zone"] == "C"]
    checks = {
        "A_peak_over_B": (max(z["A"]) if z["A"] else 0.0) > 1.2 * b_mean,
        "B_flat_cv": (float(np.std(z["B"]) / b_mean) if b_mean else 9.9) < 0.25,
        "C_ramp_rises": len(c_vals) >= 2 and c_vals[-1] > c_vals[0] * 1.3 and c_vals[-1] > b_mean * 1.3,
        "D_spike_over_C": (max(z["D"]) if z["D"] else 0.0) > 1.5 * (max(c_vals) if c_vals else 0.0),
    }
    summary = {"zone_force_n": {k: [round(min(v), 1), round(max(v), 1)] if v else [] for k, v in z.items()},
               "B_mean_n": round(b_mean, 2), "checks": checks,
               "trip_repeatability_n": None}
    # 왕복 반복성 — 같은 구간 · 방향의 왕복별 차이
    per_trip = {}
    for r in raw:
        if r[0] > 0 and r[1] == "close" and abs(r[3]) > 1e-4:
            per_trip.setdefault(r[0], []).append(abs(r[4]))
    means = [np.mean(v) for v in per_trip.values()]
    summary["trip_repeatability_n"] = round(float(np.std(means)), 3)
    (out / "window_profile_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in summary["zone_force_n"].items():
        print(f"Zone {k}: 반력 {v} N", flush=True)
    print(f"판정: {checks} · 왕복 반복성 σ {summary['trip_repeatability_n']} N", flush=True)
    print(f"=== 기준 프로파일 → {prof.relative_to(REPO)} ({len(rows)}개 구간) ===", flush=True)

    try:                                           # 그래프 = tools/analysis/plot_window_profile.py (CSV 로 다시 그릴 수 있게)
        sys.path.insert(0, str(REPO / "tools" / "analysis"))
        from plot_window_profile import plot_profile
        plot_profile(rows, travel, out / "window_profile.png")
    except Exception as exc:                       # 그래프는 선택
        print(f"(그래프 생략: {exc})", flush=True)


try:
    main()
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
finally:
    app.close()
