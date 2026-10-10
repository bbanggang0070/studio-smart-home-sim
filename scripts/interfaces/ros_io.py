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
