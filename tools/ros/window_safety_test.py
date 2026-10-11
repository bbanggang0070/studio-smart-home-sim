"""W10 센서리스 안전 DoD 자동 검증 — Isaac 브릿지 + window_safety_node 만 띄운 상태 (제어기 없음 · 사용자 직접 조작 = MANUAL).

    (터미널 1) tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py --duration 1500
    (터미널 2) tools/ros/run.sh node scripts/nodes/window_safety_node.py
    (터미널 3) tools/ros/run.sh node tools/ros/window_safety_test.py
결과: 화면 + results/window_safety_test.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import rclpy
from std_msgs.msg import Float32, String

from controller.params import load_params
from interfaces import ros_io
from interfaces import topics as T
from sim.window_local import window_zone

REPO = Path(__file__).resolve().parents[2]
results: list[dict] = []
TRAVEL = 0.70


def record(item, ok, detail):
    results.append({"item": item, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {item} — {detail}", flush=True)


def main() -> None:
    ws = load_params().get("window_sensorless")
    rclpy.init()
    node = rclpy.create_node("window_safety_test")
    st: dict = {"local": {}, "torque": [], "zones": []}
    for tp in (T.T_WINDOW_OPEN_RATIO, T.T_WINDOW_POSITION_EST, T.T_SAFETY_STATE, T.T_PINCH_DETECTED,
               T.S_WINDOW_MOTOR_CURRENT):
        ros_io.subscribe(node, tp, lambda t, v: st.__setitem__(t, v))
    rel = ros_io.qos(T.C_WINDOW_OPEN_RATIO)
    node.create_subscription(String, T.I_WINDOW_LOCAL, lambda m: st.update(local=json.loads(m.data)), rel)
    node.create_subscription(Float32, T.I_WINDOW_TORQUE_PCT,
                             lambda m: st["torque"].append((st.get(T.T_WINDOW_OPEN_RATIO, 0.0), m.data)), rel)
    pub = ros_io.publisher(node, T.C_WINDOW_OPEN_RATIO)
    act = ros_io.publisher(node, T.C_ACTIVITY)
    obstacle = node.create_publisher(String, T.I_SIM_OBSTACLE, rel)

    def spin(sec, probe=None):
        end = time.perf_counter() + sec
        while time.perf_counter() < end:
            rclpy.spin_once(node, timeout_sec=0.01)
            if probe:
                probe()

    def cmd(r):
        ros_io.publish(pub, T.C_WINDOW_OPEN_RATIO, r)

    def ratio():
        return st.get(T.T_WINDOW_OPEN_RATIO, 0.0)

    print("브릿지 · 안전 노드 대기 ...", flush=True)
    end = time.perf_counter() + 180
    while (T.T_SAFETY_STATE not in st or T.T_WINDOW_OPEN_RATIO not in st) and time.perf_counter() < end:
        spin(0.5)
    if T.T_SAFETY_STATE not in st:
        record("연결", False, "safety_state 를 받지 못함 (브릿지 · window_safety_node 확인)")
        return
    obstacle.publish(String(data="park"))

    # 1. 정상 폐쇄 20회 + Zone 라벨 (추정 위치 기준 vs 실제 위치 기준)
    false_pinch, agree, total = 0, 0, 0
    for k in range(20):
        cmd(0.5)
        spin(12.0)
        start_q = ratio() * TRAVEL

        def probe():
            nonlocal agree, total
            q, e = ratio() * TRAVEL, st.get(T.T_WINDOW_POSITION_EST)
            if e is None or abs(q - start_q) < 0.002:
                return
            total += 1
            agree += window_zone(q, TRAVEL, -1, start_q, ws) == window_zone(e, TRAVEL, -1, start_q, ws)
        cmd(0.0)
        spin(12.0, probe)
        if st.get(T.T_SAFETY_STATE) not in ("NORMAL",) or st.get(T.T_PINCH_DETECTED):
            false_pinch += 1
            act.publish(String(data="WINDOW_UNLOCK"))
            spin(1.0)
    record("⭐ 정상 폐쇄 20회 무오검출 (엔드존 · 씰 압착 포함)", false_pinch == 0, f"오검출 {false_pinch}회")
    record("Zone A–D 라벨 (리플 추정 위치 기준 = 실제 위치 기준)", total and agree / total >= 0.99,
           f"일치 {agree}/{total} ({agree / max(total, 1) * 100:.2f} %) — 경계 근처 추정 오차만큼 어긋날 수 있다")
    tq = st["torque"]
    a = [v for r, v in tq if r > 0.48]
    b = [v for r, v in tq if 0.15 < r < 0.45]
    # 주행 구간은 100 → 55 % 점감이라 최댓값은 기동과 같다 — 평균으로 비교한다
    record("토크 프로파일 반영 (기동 > 주행)", a and b and max(a) > sum(b) / len(b),
           f"기동 구간 최대 {max(a) if a else 0:.0f} % · 주행 구간 {min(b) if b else 0:.0f}–{max(b) if b else 0:.0f} % "
           f"(평균 {sum(b) / max(len(b), 1):.0f} %)")

    # 2. 끼임 3종 — 감지 · 접촉력 ≤ 100 N · 반전 50 mm · SAFETY_HOLD
    hold_s = load_params().get("window_sensorless.layered_safety.safety_hold_s")
    for name in ("rigid_pot", "soft_cushion", "elastic_sponge"):
        cmd(0.5)
        spin(12.0)
        obstacle.publish(String(data=name))
        spin(1.5)
        cmd(0.0)
        q_hit, state_seen = None, set()

        def probe2():
            nonlocal q_hit
            state_seen.add(st.get(T.T_SAFETY_STATE))
            if q_hit is None and st.get(T.T_PINCH_DETECTED):
                q_hit = ratio() * TRAVEL
        spin(12.0, probe2)
        q_after = ratio() * TRAVEL
        peak = st["local"].get("contact_peak_n", -1)
        detected = q_hit is not None
        back = (q_after - q_hit) * 1000 if detected else 0.0
        upper = "SAFETY_HOLD" in state_seen or "PINCH_REVERSE" in state_seen
        record(f"⭐ 끼임 감지 — {name}", detected and peak <= ws["pinch_detection"]["max_contact_force_n"] and upper,
               f"감지 위치 {q_hit * 1000 if detected else -1:.0f} mm · 반전 {back:.0f} mm · 최대 접촉력 {peak} N · "
               f"상태 {sorted(s for s in state_seen if s)}")
        obstacle.publish(String(data="park"))
        spin(hold_s + 2.0)                                   # SAFETY_HOLD 해제 대기
        cmd(0.0)                                             # 물체를 치운 뒤 닫아 본다 — 정상 완주가 그 자리 반복 기록을 지운다
        spin(15.0)

    # 3. 엔드존 직전 끼임 (문설주에서 0.21 m → 물체 앞면에서 패널이 멈추는 위치 ≈ 0.11 m, 엔드존 0.105 m 직전)
    cmd(0.5)
    spin(12.0)
    obstacle.publish(String(data="rigid_pot@0.21"))
    spin(1.5)
    cmd(0.0)
    seen = set()
    spin(10.0, lambda: seen.add(st.get(T.T_SAFETY_STATE)))
    record("엔드존 직전 끼임 검출", "SAFETY_HOLD" in seen or "PINCH_REVERSE" in seen,
           f"상태 {sorted(s for s in seen if s)} · 접촉력 최대 {st['local'].get('contact_peak_n')} N")
    spin(hold_s + 2.0)

    # 4. 같은 자리 2회 → 방향 잠금 → 사용자 해제 (화분은 그대로)
    cmd(0.0)
    spin(10.0)
    locked = str(st.get(T.T_SAFETY_STATE, ""))
    spin(hold_s + 2.0)
    cmd(0.0)
    spin(3.0)
    still = ratio()
    act.publish(String(data="WINDOW_UNLOCK"))
    spin(1.0)
    record("같은 자리 2회 끼임 → 닫힘 방향 잠금 · 사용자 해제", locked.startswith("LOCKED_CLOSING") and still > 0.1
           and st.get(T.T_SAFETY_STATE) == "NORMAL",
           f"2회째 뒤 {locked} · 잠긴 동안 닫기 지령 → 위치 {still:.3f} 유지 · 해제 뒤 {st.get(T.T_SAFETY_STATE)}")
    obstacle.publish(String(data="park"))
    cmd(0.0)
    spin(12.0)

    out = REPO / "results" / "window_safety_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== 센서리스 안전 시험 {sum(r['ok'] for r in results)}/{len(results)} PASS ===", flush=True)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
