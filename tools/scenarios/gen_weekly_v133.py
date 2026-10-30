"""v1.33-H 검증용 1주 시나리오 생성 (docs/14 §17 · docs/15 §14) — 구현 전에 쓰고 등록한다.

    uv run python tools/scenarios/gen_weekly_v133.py      # → config/scenarios_weekly_v133.yaml

요일을 아는 제어기를 시험한다 — 시나리오가 initial.weekday (0 = 월) 를 준다. 하루 일과 (출근자):
  00:00 수면 · 07:00 기상(일반) · 08:30 출근 · 귀가(날마다 다름) · 23:30 수면 · 주말은 집 (외출 · 외박은 시나리오마다)
외기: 낮(07–17시) 따뜻 · 맑음 / 밤 춥다 — 시나리오마다 수준만 다르다. 판정: 귀가마다 1 h 안 19.5 °C · 동파 · 결로 · A′V 대비 비용.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
DAY = 86400
OLD = {"air_balance.base_infiltration_ach": 0.7, "window.glazing_u_w_m2k": 4.2, "thermal.envelope_outdoor_conductance_w_per_k": 6.6}
LIGHT = {**OLD, "thermal.mass_capacity_wh_per_k": 600.0, "thermal.envelope_capacity_wh_per_k": 320.0,
         "heating.hydronic.floor_capacity_wh_per_k": 200.0}


def hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 3600 + int(m) * 60


def build(sid: str, name: str, start_wd: int, plan: dict[int, tuple[str | None, str | None]], env: dict, t_day: float, t_night: float,
          seed: int) -> dict:
    """plan: 경과 일 → (출발 'HH:MM' | None, 귀가 'HH:MM' | None) — None 이면 그날 출발/귀가 없음 (집에 있거나 밖에 있음)."""
    inj, ev, crit = [], [], ["temperature >= 12.0 for all t", "dew_margin >= 0 for all t",
                             "energy_cost_won <= baseline_A2V.energy_cost_won"]
    home = True
    for d in range(7):
        base = d * DAY
        ev.append({"at_s": base + hm("07:00"), "set": {"outdoor_temp_c": t_day, "outdoor_illuminance_lux": 20000.0,
                                                       **({"user_mode": "NORMAL", "occupant_zone": "room", "motion": "still"} if home else {})}})
        ev.append({"at_s": base + hm("17:00"), "set": {"outdoor_temp_c": t_night, "outdoor_illuminance_lux": 0.0}})
        leave, arrive = plan.get(d, (None, None))
        if leave:
            inj.append({"at_s": base + hm(leave), "door": "open_close", "label": f"leave{d}", "open_s": 8})
            ev.append({"at_s": base + hm(leave) + 4, "set": {"occupancy": False, "occupant_zone": "none"}})
            home = False
        if arrive:
            lab = f"arrive{d}"
            inj.append({"at_s": base + hm(arrive), "door": "open_close", "label": lab, "open_s": 8})
            ev.append({"at_s": base + hm(arrive), "set": {"occupancy": True, "occupant_zone": "room", "user_mode": "NORMAL", "motion": "still"}})
            crit.append(f"temperature >= 19.5 by 3600 after {lab}_start")
            home = True
        if home:
            ev.append({"at_s": base + hm("23:30"), "set": {"user_mode": "SLEEP", "occupant_zone": "bed", "motion": "sleeping"}})
    ev.sort(key=lambda e: e["at_s"])
    return {
        "id": sid, "tier": 3, "name": name, "duration_s": 7 * DAY, "log_interval_s": 60, "repeat": 3,
        "baselines": ["A", "B", "proposed"], "seed": seed, "run_mode": "fast", "appliance_profile": "full_heating",
        "season": "winter", "persona": "commuter", "power_limit_w": 3000,
        "environment_overrides": {"heating.mode": "hydronic", **env},
        "initial": {"thermal_steady": True, "weekday": start_wd, "user_mode": "SLEEP", "temperature_c": 20.0, "humidity_pct": 38.0,
                    "co2_ppm": 900.0, "pm25_ugm3": 8.0, "illuminance_lux": 0.0, "occupancy": True, "occupant_zone": "bed",
                    "motion": "sleeping", "time_of_day": "00:00", "window_open_ratio": 0.0, "blind_angle_deg": 0.0,
                    "appliances": {"purifier_level": 0, "boiler": {"power": True, "setpoint": 19.0}}},
        "external": {"weather": "clear", "outdoor_pm25_ugm3": 15.0, "outdoor_temp_c": t_night, "outdoor_rh_pct": 55.0,
                     "outdoor_illuminance_lux": 0.0},
        "injections": inj, "events": ev, "pass_criteria": crit,
        "metrics": ["cold_discomfort_kh", "gas_kwh", "energy_cost_won", "min_temp_c", "boiler_ignitions"],
    }


def main() -> None:
    work = {d: ("08:30", "19:00") for d in range(5)}
    sc = [
        build("W1", "평일 출근 · 주말 재택 (수요일 야근 21:30 · 토요일 오후 외출 3 h) — 기본 원룸", 0,
              {**work, 2: ("08:30", "21:30"), 5: ("14:00", "17:00")}, {}, 2.0, -6.0, 20263301),
        build("W2", "주말 외박 (토 08:00 → 월 19:30 · BOPTEST 와 같은 형태) — 가벼운 노후 원룸 · 목요일 시작", 3,
              {0: ("08:30", "19:00"), 1: ("08:30", "19:00"), 2: ("08:00", None), 4: (None, "19:30"),
               5: ("08:30", "19:00"), 6: ("08:30", "19:00")}, LIGHT, 3.0, -4.0, 20263302),
        build("W3", "수요일 출발 3박 출장 (수 08:30 → 토 15:00) — 노후 원룸", 0,
              {0: ("08:30", "19:00"), 1: ("08:30", "19:00"), 2: ("08:30", None), 5: (None, "15:00")}, OLD, 0.0, -8.0, 20263303),
        build("W4", "금요일 출근 뒤 주말 여행 (금 08:30 → 일 18:00) — 기본 원룸", 0,
              {**{d: ("08:30", "19:00") for d in range(4)}, 4: ("08:30", None), 6: (None, "18:00")}, {}, 1.0, -7.0, 20263304),
    ]
    out = REPO / "config" / "scenarios_weekly_v133.yaml"
    head = ("# ============================================================================\n"
            "#  v1.33-H 검증 — 1주 시나리오 W1–W4 (docs/14 §17 · docs/15 §14) — tools/scenarios/gen_weekly_v133.py 가 만든다 (손으로 고치지 않는다)\n"
            "#  요일을 아는 제어기 시험 (initial.weekday · 0 = 월) · 구현 전에 쓰고 등록 · 결과는 고치지 않고 보고\n"
            "# ============================================================================\n")
    out.write_text(head + yaml.safe_dump({"scenarios": sc}, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    print(f"{out.relative_to(REPO)} · {len(sc)}개")


if __name__ == "__main__":
    main()
