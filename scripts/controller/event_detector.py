"""이벤트 감지기 (docs/07 §3) — 진입 · 해제(히스테리시스) · 상태.

v1 구현: E1 요리(후드 아래 온도 · 쿡탑 전력, 열 + 연기 / 열만 구분) · E2 결로 · E3 샤워 · E5 강우 · E6 외기 오염 ·
        E10 빨래 건조(사용자 선언 ∨ 탈수 종료 + 습기 수지 잔차) · E11 전력 한도.
나머지(E4 · E7–E9 · E12–E15)는 W09–W10 에 같은 틀로 더한다.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from controller.params import ControllerParams
from controller.moisture import MoistureResidual
from controller.signals import Observation, Psychro

GRADE_ORDER = ["good", "moderate", "bad", "very_bad"]


@dataclass
class ActiveEvent:
    name: str
    since_s: float
    info: dict[str, Any] = field(default_factory=dict)


class _History:
    """최근 값 버퍼 — (시각, 값)."""

    def __init__(self, keep_s: float):
        self.keep_s = keep_s
        self.buf: deque[tuple[float, float]] = deque()

    def push(self, t: float, v: float) -> None:
        self.buf.append((t, v))
        while self.buf and t - self.buf[0][0] > self.keep_s:
            self.buf.popleft()

    def ago(self, t: float, dt: float) -> float | None:
        """t − dt 시각 이전의 가장 최근 값 (충분한 이력이 없으면 None)."""
        best = None
        for ts, v in self.buf:
            if ts <= t - dt:
                best = v
            else:
                break
        return best


class EventDetector:
    def __init__(self, p: ControllerParams, psy: Psychro):
        self.p, self.psy = p, psy
        self.active: dict[str, ActiveEvent] = {}
        self.hood_hist = _History(120.0)
        self.rh_hist = _History(600.0)
        self.dew_hist = _History(600.0)
        self._rain_clear_since: float | None = None
        self._pm_clear_since: float | None = None
        self._cook_release_since: float | None = None
        self._cond_release_since: float | None = None
        self.moisture = MoistureResidual(p, psy)
        self.alerts: list[str] = []
        self.residual: float | None = None
        self._washer_spinning = False
        self._spin_end_at: float | None = None
        self._laundry_quiet_since: float | None = None
        self._power_ok_since: float | None = None

    # -- 공통 --

    def _enter(self, name: str, t: float, **info: Any) -> None:
        if name not in self.active:
            self.active[name] = ActiveEvent(name, t, dict(info))

    def _exit(self, name: str) -> ActiveEvent | None:
        return self.active.pop(name, None)

    def update(self, o: Observation) -> dict[str, ActiveEvent]:
        t = o.now_s
        self.hood_hist.push(t, o.hood_temp_c)
        self.rh_hist.push(t, o.rh_pct)
        self.dew_hist.push(t, self.psy.dew_point(o.temp_c, o.rh_pct))
        self._rain(o)
        self._outdoor_pm(o)
        self._cooking(o)
        self._shower(o)
        self._condensation(o)
        self.residual = self.moisture.update(o)
        self._laundry(o)
        self._power_limit(o)
        self._door_fault(o)
        self._unattended_cooking(o)
        return self.active

    # -- E14 문 센서 이상 (L1) — 재실 노드가 24시간 융합으로 폴백했다 --

    def _door_fault(self, o: Observation) -> None:
        if o.occupancy_basis == "FALLBACK":
            if "DOOR_SENSOR_FAULT" not in self.active:
                self._enter("DOOR_SENSOR_FAULT", o.now_s)
                self.alerts.append({"code": "E14", "level": "warning", "t": o.now_s,
                                    "msg": "재실 판정이 24시간 융합으로 전환됨 — 문 센서 점검"})
        else:
            self._exit("DOOR_SENSOR_FAULT")

    # -- E15 불 켜고 외출 (L1) --

    def _unattended_cooking(self, o: Observation) -> None:
        g = self.p.get
        c = "events.cooking."
        heat = (o.hood_temp_c - o.temp_c >= g(c + "hood_temp_delta_vs_room_c")
                or o.power_w.get("cooktop", 0.0) >= g(c + "cooktop_power_trigger_w"))
        if not o.occupied and heat:
            if "UNATTENDED_COOKING" not in self.active:
                self._enter("UNATTENDED_COOKING", o.now_s)
                plug = o.power_w.get("cooktop", 0.0) >= g(c + "cooktop_power_trigger_w")
                self.active["UNATTENDED_COOKING"].info["plug"] = plug
                self.alerts.append({"code": "E15", "level": "critical", "t": o.now_s,
                                    "msg": "불을 켠 채 외출 — 즉시 확인" + (" · 플러그형 인덕션 전원 차단" if plug and
                                           g("events.unattended_cooking.plug_cooktop_cutoff") else " · 가스레인지 — 경고만")})
        elif not heat:
            self._exit("UNATTENDED_COOKING")

    # -- E5 강우 (L1) --

    def _rain(self, o: Observation) -> None:
        if o.raining:
            self._enter("RAIN", o.now_s)
            self._rain_clear_since = None
        elif "RAIN" in self.active:
            self._rain_clear_since = self._rain_clear_since or o.now_s
            if o.now_s - self._rain_clear_since >= self.p.get("weather.rain_clear_hold_s"):
                self._exit("RAIN")

    # -- E6 외기 오염 (L1) --

    def _outdoor_pm(self, o: Observation) -> None:
        min_grade = self.p.get("events.outdoor_pm.min_grade")
        bad = GRADE_ORDER.index(o.outdoor_pm_grade) >= GRADE_ORDER.index(min_grade)
        if bad:
            self._enter("OUTDOOR_PM", o.now_s)
            self.active["OUTDOOR_PM"].info["grade"] = o.outdoor_pm_grade
            self._pm_clear_since = None
        elif "OUTDOOR_PM" in self.active:
            self._pm_clear_since = self._pm_clear_since or o.now_s
            if o.now_s - self._pm_clear_since >= self.p.get("air_quality.improve_hold_s"):
                self._exit("OUTDOOR_PM")

    # -- E1 요리 (L2) — 후드 아래 온도 1순위 · 쿡탑 전력 · PM 은 연기 세기 · 원인 구분 --

    def _cooking(self, o: Observation) -> None:
        c = "events.cooking."
        g = self.p.get
        delta = o.hood_temp_c - o.temp_c
        prev = self.hood_hist.ago(o.now_s, 60.0)
        rise_per_min = (o.hood_temp_c - prev) if prev is not None else 0.0
        cooktop = o.power_w.get("cooktop", 0.0) >= g(c + "cooktop_power_trigger_w")
        heat_on = (delta >= g(c + "hood_temp_delta_vs_room_c") and rise_per_min >= g(c + "hood_temp_rise_c_per_min"))
        post = self.active.get("HOOD_POST_RUN")
        if post and o.now_s >= post.info["until"]:
            self._exit("HOOD_POST_RUN")
        if "COOKING" not in self.active and (heat_on or cooktop):
            self._enter("COOKING", o.now_s, pm_at_entry=o.pm25, source="steam", post_run_until=None)
            self._cook_release_since = None
            return
        ev = self.active.get("COOKING")
        if ev is None:
            return
        if ev.info["source"] == "steam" and o.pm25 - ev.info["pm_at_entry"] >= g(c + "pm_rise_for_smoke_ugm3"):
            ev.info["source"] = "cooking"           # 열 + 연기 → 요리
        # 요리 끝 = 후드 아래 온도 하강 ∧ 쿡탑 꺼짐 (docs/08 §2.3 v1.4).
        # PM ≤ 진입 시 + 기준 은 '보조 조건' — 열이 꺼진 뒤 최대 release_hold_s 까지만 기다린다.
        # (PM 에 무기한 묶으면 뒤이어 생긴 열 없는 미세먼지에도 요리 이벤트가 이어져 후드가 켜진다 — B7 ②)
        heat_ended = delta <= g(c + "hood_temp_end_delta_c") and not cooktop
        ev.info["heat_ended"] = heat_ended
        pm_ok = o.pm25 <= ev.info["pm_at_entry"] + g(c + "release_above_baseline_ugm3")
        if heat_ended:
            self._cook_release_since = self._cook_release_since or o.now_s
            waited = o.now_s - self._cook_release_since
            if pm_ok or waited >= g(c + "release_hold_s"):
                self._exit("COOKING")
                self._enter("HOOD_POST_RUN", o.now_s, until=o.now_s + g(c + "hood_post_run_s"),
                            level=ev.info.get("hood_level", 1))
        else:
            self._cook_release_since = None

    # -- E3 샤워 (L2) --

    def _shower(self, o: Observation) -> None:
        s = "events.shower."
        g = self.p.get
        ev = self.active.get("SHOWER")
        if ev is None:
            rh_5min = self.rh_hist.ago(o.now_s, 300.0)
            if rh_5min is None:
                return
            hood_normal = (o.hood_temp_c - o.temp_c) < g("events.cooking.hood_temp_delta_vs_room_c")
            need = g(s + "rh_rise_pct_in_5min")
            if o.dehumidifier_on and g(s + "compensate_dehumidifier_removal"):
                # 제습기가 5분 동안 빼는 습기만큼 상승이 가려진다 — %p 로 환산해 기준에서 뺀다 (보류 H10)
                removed_g_m3 = g("appliances.dehumidifier.rated_g_per_h") * 300.0 / 3600.0 / g("air_balance.room_volume_m3")
                need -= 100.0 * removed_g_m3 / self.psy.abs_humidity(o.temp_c, 100.0)
            ok = (o.rh_pct - rh_5min >= need
                  and (hood_normal or not g(s + "require_no_hood_heat"))
                  and (not o.humidifier_on or not g(s + "require_humidifier_off"))
                  and (o.occupied or not g(s + "require_occupied"))
                  and "COOKING" not in self.active and "HOOD_POST_RUN" not in self.active)   # 잔류 운전 중 습기도 요리 몫 (v3.4.24)
            if ok:
                pre_dew = self.dew_hist.ago(o.now_s, 300.0)
                self._enter("SHOWER", o.now_s, pre_dew=pre_dew)
            return
        dew = self.psy.dew_point(o.temp_c, o.rh_pct)
        recovered = dew <= ev.info["pre_dew"] + g(s + "release_dewpoint_above_pre_c")
        timeout = o.now_s - ev.since_s >= g(s + "max_duration_min") * 60.0
        if (recovered and o.now_s - ev.since_s >= g(s + "min_hold_s")) or timeout:
            self._exit("SHOWER")

    # -- E10 빨래 건조 (L4.5) --

    def _laundry(self, o: Observation) -> None:
        g = self.p.get
        e = "events.laundry_drying."
        pw = o.power_w.get("washer", 0.0)
        st = self.p.get("power_monitor.states_w.washer")
        if pw >= st["spin_gt"]:
            self._washer_spinning = True
        elif self._washer_spinning and pw < st["off_lt"]:
            self._washer_spinning, self._spin_end_at = False, o.now_s     # 탈수 종료 엣지
        ev = self.active.get("LAUNDRY_DRYING")
        if ev is None:
            declared = o.activity == "LAUNDRY"
            recent_spin = (self._spin_end_at is not None
                           and o.now_s - self._spin_end_at <= g(e + "spin_end_window_min") * 60.0)
            residual_ok = self.residual is not None and self.residual >= g(e + "moisture_residual_enter_g_per_h")
            if declared or (recent_spin and residual_ok):
                self._enter("LAUNDRY_DRYING", o.now_s, entry_temp_c=o.temp_c,
                            source="user_declare" if declared else "washer_spin_end+moisture_residual")
                self._laundry_quiet_since, self._spin_end_at = None, None
            return
        quiet = self.residual is not None and self.residual < g(e + "moisture_residual_release_g_per_h")
        self._laundry_quiet_since = (self._laundry_quiet_since or o.now_s) if quiet else None
        done = self._laundry_quiet_since is not None and o.now_s - self._laundry_quiet_since >= g(e + "release_hold_min") * 60.0
        if done or o.now_s - ev.since_s >= g(e + "max_duration_h") * 3600.0:
            self._exit("LAUNDRY_DRYING")

    # -- E11 전력 한도 (L1) --

    def _power_limit(self, o: Observation) -> None:
        pl = "events.power_limit."
        g = self.p.get
        limit = float(self.p.modes["energy"]["power_limit_w"])
        total = sum(float(v) for v in o.power_w.values())
        ev = self.active.get("POWER_LIMIT")
        if ev is None:
            if total >= g(pl + "enter_ratio") * limit:
                self._enter("POWER_LIMIT", o.now_s, stage=1, last_step=o.now_s, shed={})
                self._power_ok_since = None
            return
        ev.info["total_w"] = total
        if total >= g(pl + "enter_ratio") * limit and o.now_s - ev.info["last_step"] >= g(pl + "shed_step_s"):
            ev.info["stage"] += 1
            ev.info["last_step"] = o.now_s
        if total < g(pl + "release_ratio") * limit:
            self._power_ok_since = self._power_ok_since or o.now_s
            if o.now_s - self._power_ok_since >= g(pl + "release_hold_s"):
                self._exit("POWER_LIMIT")
        else:
            self._power_ok_since = None

    # -- E2 결로 (경고 L5 / 위험 L2) --

    def _condensation(self, o: Observation) -> None:
        c = "condensation."
        g = self.p.get
        margin = self.psy.dew_margin(o)
        if math.isnan(margin):
            return
        level = "critical" if margin < g(c + "critical_margin_c") else "warn" if margin < g(c + "warn_margin_c") else None
        if level:
            self._enter("CONDENSATION", o.now_s)
            ev = self.active["CONDENSATION"]
            if level == "critical" or ev.info.get("level") != "critical":
                ev.info["level"] = level
            ev.info["margin"] = margin
            self._cond_release_since = None
        elif "CONDENSATION" in self.active and margin > g(c + "release_margin_c"):
            self._cond_release_since = self._cond_release_since or o.now_s
            if o.now_s - self._cond_release_since >= g(c + "release_hold_s"):
                self._exit("CONDENSATION")
