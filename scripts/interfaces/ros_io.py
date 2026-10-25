"""rclpy 공용 도우미 — 토픽 계약(topics.TYPES · qos_kind)으로 발행자 · 구독자를 만든다.

ROS 2 가 있는 곳(ROS 컨테이너 · Isaac 내장 Jazzy)에서만 import 한다. 제어기 코어는 이 파일을 쓰지 않는다.
"""

from __future__ import annotations

from typing import Any, Callable

from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs import msg as std

from interfaces import topics as T

MSG = {T.F32: std.Float32, T.BOOL: std.Bool, T.STR: std.String, T.I8: std.Int8}
CAST = {T.F32: float, T.BOOL: bool, T.STR: str, T.I8: int}


def qos(topic: str) -> QoSProfile:
    if T.qos_kind(topic) == "sensor":
        depth = 5 if topic == T.S_WINDOW_MOTOR_CURRENT else 10
        return QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=depth)
    return QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=10)


def msg_type(topic: str):
    return MSG[T.TYPES.get(topic, T.F32)]


def publisher(node, topic: str):
    return node.create_publisher(msg_type(topic), topic, qos(topic))


def publish(pub, topic: str, value: Any) -> None:
    kind = T.TYPES.get(topic, T.F32)
    m = MSG[kind]()
    m.data = CAST[kind](value) if kind != T.I8 else max(-128, min(127, int(round(value))))
    pub.publish(m)


def subscribe(node, topic: str, cb: Callable[[str, Any], None]):
    """cb(topic, 파이썬 값)."""
    return node.create_subscription(msg_type(topic), topic, lambda m: cb(topic, m.data), qos(topic))


class SimClock:
    """시뮬레이션 시각 — 월드 노드의 /clock(하루 중 초)을 따르고, 없으면 벽시계(현지 시각).

    now()  하루 중 초 (제어기 now_s) · elapsed()  시작 뒤 경과 초 (L0 보호 · 전력 감시 시간 판정)
    """

    def __init__(self, node):
        import time

        from rosgraph_msgs.msg import Clock

        self._time = time
        self.sim: float | None = None
        self._first: float | None = None
        self._t0 = time.monotonic()
        node.create_subscription(Clock, "/clock", self._on_clock, 10)

    def _on_clock(self, m) -> None:
        self.sim = m.clock.sec + m.clock.nanosec * 1e-9
        if self._first is None:
            self._first = self.sim

    def now(self) -> float:
        if self.sim is not None:
            return self.sim % 86400.0
        return (self._time.time() - self._time.timezone) % 86400.0

    def seconds(self) -> float:
        """제어기 시각 — 연속 초 (자정에 0 으로 돌아가지 않는다 · 하루 중 시각은 제어기가 % 86400 으로 구한다).
        고속 하네스(clock0 + 경과) · BOPTEST 연결과 같은 기준 (2026-10-24 모드 대조)."""
        if self.sim is not None:
            return self.sim
        return self._time.time() - self._time.timezone

    def elapsed(self) -> float:
        if self.sim is not None:
            return self.sim - self._first
        return self._time.monotonic() - self._t0
