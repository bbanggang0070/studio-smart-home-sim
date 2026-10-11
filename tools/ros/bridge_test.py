"""W06 DoD (+ W07 리플 위치 추정) 자동 검증 — ROS 컨테이너에서 Isaac 액추에이터 브릿지를 토픽만으로 시험한다.

    (터미널 1) tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py
    (터미널 2) tools/ros/run.sh node tools/ros/bridge_test.py

제어기 노드는 띄우지 않는다 — '제어기가 없어도 로컬 컷오프가 창문을 멈춘다'(T6.7)를 그대로 확인한다.
결과: 화면 + results/bridge_test.json
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import rclpy
from std_msgs.msg import Float32, String

from interfaces import ros_io
from interfaces import topics as T

REPO = Path(__file__).resolve().parents[2]
results: list[dict] = []


def record(item, ok, detail):
    results.append({"item": item, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {item} — {detail}", flush=True)


def main() -> None:
    rclpy.init()
    node = rclpy.create_node("bridge_test")
    state: dict[str, tuple[float, object]] = {}
    peak = {"current": 0.0}

    def on_state(tp, v):
        state[tp] = (time.perf_counter(), v)
        if tp == T.S_WINDOW_MOTOR_CURRENT:
            peak["current"] = max(peak["current"], float(v))

    for tp in (T.T_CEILING_LIGHT, T.T_DESK_LIGHT, T.T_FAN_RPM, T.T_INTAKE_FAN_RPM, T.T_CEILING_FAN, T.T_BLIND_ANGLE,
               T.T_WINDOW_OPEN_RATIO, T.T_WINDOW_ZONE, T.T_SAFETY_STATE, T.T_PINCH_DETECTED, T.S_WINDOW_MOTOR_CURRENT,
               T.T_WINDOW_POSITION_EST, T.S_DOOR_CONTACT):
        ros_io.subscribe(node, tp, on_state)
    pubs = {tp: ros_io.publisher(node, tp) for tp in T.COMMAND_TOPICS}
    torque = node.create_publisher(Float32, T.I_WINDOW_TORQUE_PCT, ros_io.qos(T.C_WINDOW_OPEN_RATIO))
    obstacle = node.create_publisher(String, T.I_SIM_OBSTACLE, ros_io.qos(T.C_WINDOW_OPEN_RATIO))

    def spin(seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            rclpy.spin_once(node, timeout_sec=0.01)

    def cmd(tp, v):
        ros_io.publish(pubs[tp], tp, v)

    def val(tp, default=None):
        return state.get(tp, (0, default))[1]

    print("브릿지 대기 중 ...", flush=True)
    end = time.perf_counter() + 120
    while T.T_WINDOW_OPEN_RATIO not in state and time.perf_counter() < end:
        spin(0.5)
    if T.T_WINDOW_OPEN_RATIO not in state:
        record("브릿지 연결", False, "상태 토픽을 받지 못함 (브릿지가 떠 있나?)")
        return
    record("브릿지 연결", True, f"상태 토픽 {len(state)}종 수신")
    obstacle.publish(String(data="park"))

    # 1. 5종 구동 (+ 흡기 · 실링팬)
    cmd(T.C_WINDOW_OPEN_RATIO, 0.5)
    cmd(T.C_BLIND_ANGLE, 60.0)
    cmd(T.C_FAN_RPM, 1000.0)
    cmd(T.C_INTAKE_FAN_RPM, 800.0)
    cmd(T.C_CEILING_FAN, 2)
    cmd(T.C_CEILING_LIGHT, 50.0)
    cmd(T.C_DESK_LIGHT, 80.0)
    cmd(T.C_DESK_LIGHT_CCT, 2700.0)
    spin(12.0)
    checks = {"창문 0.5": abs(val(T.T_WINDOW_OPEN_RATIO, -1) - 0.5) <= 0.02,
              "블라인드 60°": abs(val(T.T_BLIND_ANGLE, -1) - 60.0) <= 2.0,
              "배기 1000 rpm": abs(val(T.T_FAN_RPM, 0) - 1000.0) <= 50.0,
              "흡기 800 rpm": abs(val(T.T_INTAKE_FAN_RPM, 0) - 800.0) <= 40.0,
              "실링팬 2단": val(T.T_CEILING_FAN) == 2,
              "천장등 50 %": val(T.T_CEILING_LIGHT) == 50.0, "스탠드 80 %": val(T.T_DESK_LIGHT) == 80.0}
    record("ros2 토픽으로 액추에이터 구동 (창문 · 블라인드 · 팬 3 · 조명 2)", all(checks.values()),
           " · ".join(f"{k} {'✓' if v else '✗'}" for k, v in checks.items())
           + f" (창문 {val(T.T_WINDOW_OPEN_RATIO):.3f} · 블라인드 {val(T.T_BLIND_ANGLE):.1f}° · 배기 {val(T.T_FAN_RPM):.0f})")

    # 2. 클램핑 (T6.5)
    cmd(T.C_WINDOW_OPEN_RATIO, 1.5)
    cmd(T.C_BLIND_ANGLE, 200.0)
    spin(14.0)
    record("범위 밖 명령 클램핑 (창문 150 % · 블라인드 200°)",
           val(T.T_WINDOW_OPEN_RATIO, 9) <= 1.0001 and val(T.T_BLIND_ANGLE, 999) <= 90.5,
           f"창문 → {val(T.T_WINDOW_OPEN_RATIO):.3f} · 블라인드 → {val(T.T_BLIND_ANGLE):.1f}°")
    record("정상 주행에서 로컬 컷오프 미작동", val(T.T_SAFETY_STATE) == "NORMAL", f"safety_state = {val(T.T_SAFETY_STATE)}")

    # 3. 지연 (T6.6) — 명령 발행 → 상태 변화 첫 관측 (상태 20 Hz)
    lat = []
    for k in range(10):
        target = 20.0 if k % 2 == 0 else 70.0
        t_pub = time.perf_counter()
        cmd(T.C_CEILING_LIGHT, target)
        while time.perf_counter() - t_pub < 2.0:
            rclpy.spin_once(node, timeout_sec=0.002)
            ts, v = state.get(T.T_CEILING_LIGHT, (0, None))
            if v == target and ts > t_pub:
                lat.append((ts - t_pub) * 1000)
                break
    wl = []
    for k in range(4):
        q0 = val(T.T_WINDOW_OPEN_RATIO)
        t_pub = time.perf_counter()
        cmd(T.C_WINDOW_OPEN_RATIO, 0.9 if q0 > 0.95 else 1.0)
        while time.perf_counter() - t_pub < 2.0:
            rclpy.spin_once(node, timeout_sec=0.002)
            ts, v = state.get(T.T_WINDOW_OPEN_RATIO, (0, q0))
            if ts > t_pub and abs(v - q0) > 0.002:
                wl.append((ts - t_pub) * 1000)
                break
        spin(3.0)
    record("명령 → 반응 지연 ≤ 100 ms", lat and max(lat) <= 100 and (not wl or max(wl) <= 150),
           f"조명 상태 반영 중앙 {statistics.median(lat):.0f} · 최대 {max(lat):.0f} ms · "
           f"창문 조인트 이동 관측 {[round(x) for x in wl]} ms (상태 20 Hz · 램프 가속 포함)" if lat else "측정 실패")

    # 3b. 리플 위치 추정 (W07 T7.4b) — 왕복 중 오차 · 하드 스톱 재동기화
    travel = 0.70
    errs = []
    cmd(T.C_WINDOW_OPEN_RATIO, 0.0)                       # 하드 스톱에서 시작 (재동기화) → 1회 왕복 (docs/04 §7: 1회 왕복 누적 ≤ 5 mm)
    spin(16.0)
    for goal in (0.9, 0.1):
        cmd(T.C_WINDOW_OPEN_RATIO, goal)
        spin(14.0)
        errs.append(abs(val(T.T_WINDOW_POSITION_EST, 0) - val(T.T_WINDOW_OPEN_RATIO, 0) * travel) * 1000)
    cmd(T.C_WINDOW_OPEN_RATIO, 0.0)
    spin(10.0)
    resync = abs(val(T.T_WINDOW_POSITION_EST, 1)) * 1000
    record("리플 위치 추정 ±5 mm · 하드 스톱 재동기화", max(errs) <= 5.0 and resync <= 1.0,
           f"멈춘 위치별 오차 {[round(e, 2) for e in errs]} mm · 닫힘 뒤 {resync:.2f} mm")

    # 4. 토크 상한 (T6.3b) — 씰 압착 전류: 100 % vs 30 %
    def seal_current(pct):
        torque.publish(Float32(data=float(pct)))
        cmd(T.C_WINDOW_OPEN_RATIO, 0.1)
        spin(14.0)
        peak["current"] = 0.0
        cmd(T.C_WINDOW_OPEN_RATIO, 0.0)
        spin(5.0)
        return peak["current"]
    i100, i30 = seal_current(100.0), seal_current(30.0)
    torque.publish(Float32(data=100.0))
    record("창문 토크 상한 → 구동력 변화 (씰 압착 전류)", i30 < 0.75 * i100,
           f"상한 100 % → {i100:.2f} A · 30 % → {i30:.2f} A")

    # 5. 로컬 컷오프 (T6.7) — 제어기 없이 · 강체 화분
    cmd(T.C_WINDOW_OPEN_RATIO, 0.5)
    spin(12.0)
    obstacle.publish(String(data="rigid_pot"))
    spin(1.5)
    peak["current"] = 0.0
    cmd(T.C_WINDOW_OPEN_RATIO, 0.0)
    spin(10.0)
    tripped = val(T.T_SAFETY_STATE) == "LOCAL_CUTOFF" and val(T.T_PINCH_DETECTED) is True
    q_stop = val(T.T_WINDOW_OPEN_RATIO)
    record("⭐ 로컬 컷오프 — 제어기 없이 장애물에서 정지", tripped and q_stop > 0.1,
           f"safety_state {val(T.T_SAFETY_STATE)} · 정지 위치 {q_stop * 700:.0f} mm · 최대 전류 {peak['current']:.2f} A")
    cmd(T.C_WINDOW_OPEN_RATIO, 0.0)                       # 같은 방향 재지령 → 거부되어야 한다
    spin(3.0)
    held = abs(val(T.T_WINDOW_OPEN_RATIO) - q_stop) < 0.005
    cmd(T.C_WINDOW_OPEN_RATIO, 0.5)                       # 반대 방향 → 해제
    spin(8.0)
    record("컷오프 뒤 같은 방향 거부 · 반대 방향 해제", held and val(T.T_SAFETY_STATE) == "NORMAL",
           f"재지령 뒤 위치 유지 {held} · 열기 뒤 {val(T.T_SAFETY_STATE)}")
    obstacle.publish(String(data="park"))
    spin(1.0)

    out = REPO / "results" / "bridge_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== 브릿지 시험 {sum(r['ok'] for r in results)}/{len(results)} PASS ===", flush=True)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
