"""토픽 계약 점검 (W06 DoD — 55개: 센서 13 · 명령 16 · 상태 26) — ROS 그래프에서 발행자 · 구독자 · 타입을 대조한다.

    tools/ros/run.sh node tools/ros/check_topics.py [--wait 5]
결과: 화면 표 + results/topic_check.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import rclpy

from interfaces import topics as T

REPO = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=5.0)
    args = ap.parse_args()
    rclpy.init()
    node = rclpy.create_node("topic_check")
    end = time.time() + args.wait
    while time.time() < end:                             # 발견(discovery) 시간
        rclpy.spin_once(node, timeout_sec=0.2)
    graph = dict(node.get_topic_names_and_types())
    rows, ok_n = [], 0
    for group, topics in (("센서", T.SENSOR_TOPICS), ("명령", T.COMMAND_TOPICS), ("상태", T.STATE_TOPICS)):
        for tp in topics:
            pubs = node.count_publishers(tp)
            subs = node.count_subscribers(tp)
            types = graph.get(tp, [])
            type_ok = (not types) or types == [f"std_msgs/msg/{T.TYPES[tp]}"]
            connected = pubs > 0 and subs > 0 and type_ok
            ok_n += connected
            rows.append({"group": group, "topic": tp, "type": T.TYPES[tp], "publishers": pubs, "subscribers": subs,
                         "type_ok": type_ok, "connected": connected})
    for g in ("센서", "명령", "상태"):
        rs = [r for r in rows if r["group"] == g]
        print(f"[{g}] 연결 {sum(r['connected'] for r in rs)}/{len(rs)}", flush=True)
        for r in rs:
            mark = "✓" if r["connected"] else ("발행 없음" if r["publishers"] == 0 else "구독 없음" if r["subscribers"] == 0 else "타입 불일치")
            print(f"   {mark:6s} {r['topic']:42s} pub {r['publishers']} · sub {r['subscribers']}", flush=True)
    print(f"=== 계약 {len(rows)}개 중 연결 {ok_n}개 ===", flush=True)
    out = REPO / "results" / "topic_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    rclpy.shutdown()


if __name__ == "__main__":
    main()
