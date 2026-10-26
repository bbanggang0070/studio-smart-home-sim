"""환경 센서 노드 (W07 T7.1 · T7.2 · T7.v1 · T7.h1 · T7.4c) — 참값 → 측정값 (잡음 · 지연 · 양자화 · 주기).

    tools/ros/run.sh node scripts/nodes/environment_sensor_node.py

  입력  /studio/internal/env_truth (월드 노드)
  발행  sensor/{temperature, humidity, illuminance} 10 Hz · {pm25, hood_temperature, appliance_power} 1 Hz
        sensor/{weather, outdoor_pm_grade} 변경 시 + API 주기 (기상청 10분 · 에어코리아 1시간 자리)
  조도는 참값 모델이 이미 W05 캘리브레이션 계수로 천장 센서 위치 값을 낸다. 고장 주입 lux_invalid → NaN
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import rclpy
import yaml
from std_msgs.msg import String

from harness.fast_world import pm_grade
from interfaces import ros_io
from interfaces import topics as T
from sensors.sensor_models import PLUG_DEVICES, TRUTH_SENSORS, SensorModel

REPO = Path(__file__).resolve().parents[2]
ENV_TRUTH = f"{T.P}/internal/env_truth"
_TOPIC = {"temperature": T.S_TEMPERATURE, "humidity": T.S_HUMIDITY, "illuminance": T.S_ILLUMINANCE,
          "pm25": T.S_PM25, "hood_temperature": T.S_HOOD_TEMPERATURE}
TRUTH_KEY = {_TOPIC[name]: (name, key) for name, key in TRUTH_SENSORS.items()}   # 고속 하네스와 같은 표 (sensors/sensor_models.py)


def main() -> None:
    cfg = yaml.safe_load((REPO / "config" / "sensor_models.yaml").read_text(encoding="utf-8"))
    hcfg = yaml.safe_load((REPO / "config" / "harness.yaml").read_text(encoding="utf-8"))
    grade = hcfg["outdoor_api"]
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-offset", type=int, default=0)   # 물리 조건 무작위화 — 반복마다 다른 잡음 (0 = 이전과 같은 고정 시드)
    args, _ = ap.parse_known_args()
    rng = np.random.default_rng(cfg["seed"] + 1000 * args.seed_offset)
    S = cfg["sensors"]
    models = {tp: SensorModel(S[name], rng) for tp, (name, _) in TRUTH_KEY.items()}
    plug = {d: SensorModel(S["appliance_power"], rng) for d in PLUG_DEVICES}
    rclpy.init()
    node = rclpy.create_node("environment_sensor")
    log = node.get_logger()
    truth: dict = {}
    pubs = {tp: ros_io.publisher(node, tp) for tp in list(TRUTH_KEY) + [T.S_APPLIANCE_POWER, T.S_WEATHER,
                                                                         T.S_OUTDOOR_PM_GRADE]}
    node.create_subscription(String, ENV_TRUTH, lambda m: truth.update(json.loads(m.data)), ros_io.qos(T.C_MODE))
    api = {"weather": None, "grade": None, "t_weather": -1e9, "t_grade": -1e9}

    def sample(topics, dt):
        if not truth:
            return
        for tp in topics:
            if tp == T.S_ILLUMINANCE and "lux_invalid" in truth.get("faults", []):
                ros_io.publish(pubs[tp], tp, math.nan)
                continue
            ros_io.publish(pubs[tp], tp, models[tp].measure(float(truth["obs"][TRUTH_KEY[tp][1]]), dt))

    def slow():
        if not truth:
            return
        sample((T.S_PM25, T.S_HOOD_TEMPERATURE), 1.0)
        power = {d: plug[d].measure(float(truth["obs"]["appliance_power_w"].get(d, 0.0)), 1.0) for d in PLUG_DEVICES}
        power.update({k: round(float(v), 1) for k, v in truth.get("extra_power_w", {}).items()})
        ros_io.publish(pubs[T.S_APPLIANCE_POWER], T.S_APPLIANCE_POWER, json.dumps(power, sort_keys=True))
        t, e = truth["t"], truth["ext"]
        w = json.dumps({"raining": e["raining"], "sky": e.get("sky", "clear"), "outdoor_temp_c": round(e["outdoor_temp_c"], 1),
                        "outdoor_rh_pct": round(e["outdoor_rh_pct"], 1)})
        if w != api["weather"] or t - api["t_weather"] >= cfg["api"]["weather_period_s"]:
            api["weather"], api["t_weather"] = w, t
            ros_io.publish(pubs[T.S_WEATHER], T.S_WEATHER, w)
        g = pm_grade(e["outdoor_pm25_ugm3"], grade["pm_grade_bounds_ugm3"], grade["pm_grade_names"])
        if g != api["grade"] or t - api["t_grade"] >= cfg["api"]["outdoor_pm_period_s"]:
            api["grade"], api["t_grade"] = g, t
            ros_io.publish(pubs[T.S_OUTDOOR_PM_GRADE], T.S_OUTDOOR_PM_GRADE, g)

    fast = (T.S_TEMPERATURE, T.S_HUMIDITY, T.S_ILLUMINANCE)
    node.create_timer(1.0 / S["temperature"]["rate_hz"], lambda: sample(fast, 1.0 / S["temperature"]["rate_hz"]))
    node.create_timer(1.0 / S["pm25"]["rate_hz"], slow)
    log.info("환경 센서 노드 시작 — 온습도 · 조도 10 Hz · PM · 후드 온도 · 가전 전력 1 Hz · 날씨 · 외기 등급 (config/sensor_models.yaml)")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
