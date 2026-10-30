"""원룸 환경 참값 모델 — 집중 정수(lumped) 모델 (docs/06 §5 · docs/08 §6).

상태: 공기 · 축열 질량 · 외벽 온도(3R3C) · 절대습도 · PM2.5 · CO₂(참값) · 후드 아래 온도 · 빨래 잔여 수분.
입력: 액추에이터 명령(실제 동작값) · 외부 조건 · 실내 발생원 · 재실.
출력: 관측 딕셔너리 (센서 노드 · 로거 · 지표 계산이 쓴다 — 노이즈는 센서 계층에서 더한다).

이 모델은 '참값'이다. 가전 보호(압축기 최소 ON/OFF 등)는 여기서 하지 않는다 — L0 appliance_bridge 의 일이다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from common import daylight as daylight_model
from env_model import air_balance, condensation, psychro
from env_model.config import EnvModelConfig

WH_TO_J = 3600.0
SECONDS_PER_HOUR = 3600.0
MG_PER_MIN_TO_UG_PER_H = 60_000.0


# ---- 입력 ----------------------------------------------------------------------


@dataclass
class AcCommand:
    power: bool = False
    mode: str = "cool"            # cool | dry | fan
    setpoint_c: float = 26.0


@dataclass
class BoilerCommand:
    """룸 온도조절기 명령 (난방 확장 트랙 · heating.mode = hydronic 에서만 쓴다). 켬/끔 판단은 조절기가 한다."""
    power: bool = False
    setpoint_c: float = 21.0


@dataclass
class ActuatorCommands:
    """액추에이터의 실제 동작값. 창문 개방률은 0–1 비율이다."""

    window_open_ratio: float = 0.0
    blind_angle_deg: float = 0.0      # 0 = 완전 개방 · 75 = 차광
    exhaust_fan_rpm: float = 0.0
    intake_fan_rpm: float = 0.0
    range_hood_level: int = 0         # 0–2
    purifier_level: int = 0           # 0–3
    ac: AcCommand = field(default_factory=AcCommand)
    dehumidifier: bool = False
    humidifier: bool = False
    ceiling_fan: int = 0              # −2…+2 (부호 = 방향, 음수 = 역회전)
    ceiling_light_pct: float = 0.0
    desk_light_pct: float = 0.0
    boiler: BoilerCommand = field(default_factory=BoilerCommand)


@dataclass
class ExternalConditions:
    outdoor_temp_c: float
    outdoor_rh_pct: float
    outdoor_pm25_ugm3: float = 12.0
    outdoor_illuminance_lux: float = 0.0
    wind_speed_ms: float = -1.0       # −1 = 설정 기본값 사용 (ROS 파라미터 규칙: null 대신 −1)
    heating_setpoint_c: float = -1.0  # 겨울 난방 경계 조건 (가정 A13) · −1 = 난방 없음
    sky: str = "clear"                # 하늘 상태 clear | cloudy | overcast | rain — 주광의 직사광 비율 (common/daylight.py)


@dataclass
class SourceRates:
    """실내 발생원의 순간 발생률. 시간 프로파일(언제 · 얼마나)은 하네스가 정한다."""

    cooking_pm_mg_per_min: float = 0.0     # 후드가 일부 포집
    other_pm_mg_per_min: float = 0.0       # 향초 · 원인 미상 등 열 없는 발생원
    moisture_g_per_h: float = 0.0          # 요리 · 샤워(욕실 문 유입) 등
    sensible_heat_w: float = 0.0           # 요리 이외의 현열
    cooking_heat_w: float = 0.0            # 조리 열 — 실내 열 + 후드 아래 온도 플룸
    shower_active: bool = False            # [난방 확장 R1] 샤워 중 — 온수 겸용 보일러는 온수 우선 (hydronic 만 영향)


@dataclass
class Occupancy:
    count: int = 1
    activity: str = "seated"               # seated | sleeping


# ---- 상태 ----------------------------------------------------------------------


@dataclass
class RoomState:
    temp_c: float
    abs_humidity_g_m3: float
    pm25_ugm3: float
    co2_ppm: float
    mass_temp_c: float
    envelope_temp_c: float
    hood_temp_c: float
    laundry_moisture_g: float = 0.0
    filter_hours: float = 0.0
    condensate_g: float = 0.0
    time_s: float = 0.0
    energy_wh: dict[str, float] = field(default_factory=dict)
    floor_temp_c: float | None = None      # 온수 바닥난방 슬래브 (hydronic 만)
    supply_temp_c: float | None = None     # 보일러 공급수 (hydronic 만)


# ---- 모델 ----------------------------------------------------------------------


class RoomModel:
    def __init__(self, cfg: EnvModelConfig, state: RoomState):
        self.ac_state = "off"
        self._thermo_off = False                         # 써모오프 중 — 설정 + restart 를 넘어야 압축기 재기동
        self.cfg = cfg
        self.state = state
        self._b = cfg.get("condensation.magnus_b")
        self._c = cfg.get("condensation.magnus_c")
        self._laundry_k_m3h = self._calibrate_laundry()
        # 난방 확장 트랙 — boundary(기본)는 v1.29 와 같다
        self.hydronic = cfg.get("heating.mode") == "hydronic"
        self.boiler_burning = False
        self.boiler_call = False
        self._boiler_change_s = -1e9
        if self.hydronic:
            if state.floor_temp_c is None:
                state.floor_temp_c = state.temp_c
            if state.supply_temp_c is None:
                state.supply_temp_c = state.floor_temp_c

    @classmethod
    def from_conditions(
        cls,
        cfg: EnvModelConfig,
        temp_c: float,
        rh_pct: float,
        pm25_ugm3: float,
        co2_ppm: float,
        filter_hours: float = 0.0,
        mass_temp_c: float | None = None,
        envelope_temp_c: float | None = None,
    ) -> "RoomModel":
        """초기 조건(시나리오 `initial`)에서 시작. 축열 질량 · 외벽은 따로 주지 않으면 실내 온도와 평형이라고 본다."""
        b, c = cfg.get("condensation.magnus_b"), cfg.get("condensation.magnus_c")
        state = RoomState(
            temp_c=temp_c,
            abs_humidity_g_m3=psychro.rh_to_abs(temp_c, rh_pct, b, c),
            pm25_ugm3=pm25_ugm3,
            co2_ppm=co2_ppm,
            mass_temp_c=temp_c if mass_temp_c is None else mass_temp_c,
            envelope_temp_c=temp_c if envelope_temp_c is None else envelope_temp_c,
            hood_temp_c=temp_c,
            filter_hours=filter_hours,
        )
        return cls(cfg, state)

    # -- 온수 바닥난방 (난방 확장 트랙 · docs/14 §3) --

    def _hydronic(self, cmd: BoilerCommand, t_air: float, dt: float, shower: bool = False) -> tuple[float, float, float]:
        """룸 온도조절기 → 보일러 연소 → 공급수 → 바닥 슬래브 → 실내. → (실내로 가는 열 W, 전기 W, 가스 W).

        조절기: 설정 ± 히스테리시스/2 로 켬/끔 · 보일러 자체 최소 연소 · 정지 시간 (참값 쪽 · 제어기 L0 와 별개).
        바닥 → 실내: EN 1264 특성식 q = c·|ΔT|^n (부호 유지) · 바닥 → 아래층: 컨덕턴스 · 배관 → 바닥: K_p·(공급수 − 바닥)."""
        g = self.cfg.get
        h = "heating.hydronic."
        s = self.state
        now = s.time_s
        hyst = g(h + "thermostat_hysteresis_c") / 2.0
        want = self.boiler_burning
        if not cmd.power:
            want = False
        elif t_air < cmd.setpoint_c - hyst:
            want = True
        elif t_air > cmd.setpoint_c + hyst:
            want = False
        # [v1.32-H M6] 조절기 점화 요구 (고장과 무관 · 출력 전용 — 연소 동작은 위 want 그대로) — 고장 알림 지연 지표의 기준 시각
        call = self.boiler_call
        if not cmd.power:
            call = False
        elif t_air < cmd.setpoint_c - hyst:
            call = True
        elif t_air > cmd.setpoint_c + hyst:
            call = False
        self.boiler_call = call
        if g(h + "fault_no_ignition"):
            want = False                                 # 고장 — 점화 실패 (전기 = 대기 전력 · 실내로 열 없음)
        if want != self.boiler_burning:
            hold = g(h + "boiler_min_burn_s") if self.boiler_burning else g(h + "boiler_min_off_s")
            if now - self._boiler_change_s >= hold or not cmd.power:   # 전원을 끄면 바로 멈춘다
                self.boiler_burning, self._boiler_change_s = want, now
        dhw_w = 0.0
        if shower and g(h + "combi"):                    # [R1] 온수 겸용 — 샤워 중엔 온수 우선, 난방 공급 정지 (국내 원룸 보일러 대부분)
            dhw_w = min(g(h + "boiler_max_output_w"),
                        g(h + "dhw_flow_lpm") / 60.0 * 4186.0 * (g(h + "dhw_temp_c") - g(h + "cold_water_temp_c")))
        heating_on = self.boiler_burning and dhw_w == 0.0
        target = g(h + "supply_temp_c") if heating_on else s.floor_temp_c
        k = 1.0 - math.exp(-dt / g(h + "supply_time_constant_s"))
        s.supply_temp_c += (target - s.supply_temp_c) * k
        q_pipe = 0.0
        if heating_on:
            q_pipe = min(g(h + "boiler_max_output_w"), max(0.0, g(h + "pipe_conductance_w_per_k") * (s.supply_temp_c - s.floor_temp_c)))
        d = s.floor_temp_c - t_air
        q_air = g(h + "floor_area_m2") * g(h + "en1264_coefficient") * math.copysign(abs(d) ** g(h + "en1264_exponent"), d)
        q_below = g(h + "floor_below_conductance_w_per_k") * (s.floor_temp_c - g(h + "below_temp_c"))
        s.floor_temp_c += (q_pipe - q_air - q_below) * dt / (g(h + "floor_capacity_wh_per_k") * WH_TO_J)
        p_el = g(h + "boiler_electric_on_w") if (self.boiler_burning or dhw_w > 0) else g(h + "boiler_electric_standby_w")
        self.dhw_w = dhw_w
        return q_air, p_el, (q_pipe + dhw_w) / g(h + "boiler_efficiency")

    # -- 빨래 --

    def hang_laundry(self, moisture_g: float | None = None) -> None:
        self.state.laundry_moisture_g = (
            self.cfg.get("laundry.initial_moisture_g") if moisture_g is None else moisture_g
        )

    def _calibrate_laundry(self) -> float:
        """'24 °C · 60 % · 무풍 → 10시간 건조' 교정 조건에서 k_l·A [m³/h] 를 구한다 (docs/08 §4.3)."""
        g = self.cfg.get
        t, rh = g("laundry.calibration_temp_c"), g("laundry.calibration_rh_pct")
        w_sat = psychro.saturation_density_g_m3(t, self._b, self._c)
        vpd = w_sat * (1.0 - rh / 100.0)
        return g("laundry.initial_moisture_g") / (g("laundry.calibration_hours") * vpd)

    def _laundry_rate_g_h(self, temp_c: float, w: float, fan_level: int) -> float:
        m = self.state.laundry_moisture_g
        if m <= 0.0:
            return 0.0
        g = self.cfg.get
        speeds = g("laundry.ceiling_fan_air_speed_ms")
        v_air = 0.0 if fan_level == 0 else (speeds["low"] if abs(fan_level) == 1 else speeds["high"])
        vpd = max(0.0, psychro.saturation_density_g_m3(temp_c, self._b, self._c) - w)
        rate = self._laundry_k_m3h * vpd * (1.0 + g("laundry.air_speed_gain") * v_air)
        falling = g("laundry.falling_rate_fraction") * g("laundry.initial_moisture_g")
        if m < falling:
            rate *= m / falling
        return rate

    # -- 가전 효과 --

    def _ac_effect(self, ac: AcCommand, temp_c: float, rh_pct: float) -> tuple[float, float, float]:
        """에어컨 → (현열 냉방 W, 제습 g/h, 전력 W). 인버터 비례 제어 + 써모오프."""
        self.ac_state = "off"                          # 참값 상태 — 전력 기반 판정(B11)의 정답
        if not ac.power:
            self._thermo_off = False
            return 0.0, 0.0, 0.0
        p = "appliances.ac."
        g = self.cfg.get
        # 써모오프 히스테리시스 — 설정 − band 아래로 내려가면 멈추고, 설정 + restart 를 넘어야 다시 돈다
        err0 = temp_c - ac.setpoint_c
        if err0 < -g(p + "thermo_off_band_c"):
            self._thermo_off = True
        elif err0 > g(p + "thermo_restart_above_c"):
            self._thermo_off = False
        self.ac_state = "fan_only"
        if ac.mode == "fan":
            return 0.0, 0.0, g(p + "fan_only_power_w")
        latent_wh_g = g("physics.water_latent_heat_wh_per_g")
        floor, full = g(p + "latent_rh_floor_pct"), g(p + "latent_rh_full_pct")
        f_rh = min(1.0, max(0.0, (rh_pct - floor) / (full - floor)))
        cap = g(p + "cooling_capacity_w")
        if ac.mode == "dry":
            if self._thermo_off:
                return 0.0, 0.0, g(p + "fan_only_power_w")   # 제습 운전도 설정 아래로 내려가면 압축기 정지 (송풍)
            removal = g(p + "dry_mode_removal_g_per_h") * f_rh
            sensible = g(p + "dry_mode_sensible_w")
            q_total = sensible + removal * latent_wh_g
        else:
            err = temp_c - ac.setpoint_c
            band = g(p + "thermo_off_band_c")
            if self._thermo_off:
                return 0.0, 0.0, g(p + "fan_only_power_w")
            q_total = min(cap, max(g(p + "min_plr") * cap, g(p + "modulation_w_per_k") * (err + band)))
            shr = g(p + "sensible_heat_ratio")
            sensible = shr * q_total
            removal = (1.0 - shr) * q_total * f_rh / latent_wh_g
        self.ac_state = "run"
        plr = q_total / cap
        cop = float(np.interp(plr, g(p + "cop_plr_points"), g(p + "cop_values")))
        return sensible, removal, q_total / cop

    def _dehumidifier_effect(self, on: bool, temp_c: float, rh_pct: float) -> tuple[float, float, float]:
        """제습기 → (제습 g/h, 발열 W, 전력 W). 발열 = 전력 + 응축 잠열 (docs/08 §4.4)."""
        if not on:
            return 0.0, 0.0, 0.0
        p = "appliances.dehumidifier."
        g = self.cfg.get
        t_lo, t_hi = g(p + "derate_temp_low_c"), g(p + "derate_temp_high_c")
        f_lo, f_hi = g(p + "derate_factor_low"), g(p + "derate_factor_high")
        f_t = f_lo + (f_hi - f_lo) * (temp_c - t_lo) / (t_hi - t_lo)
        f_t = min(f_hi, max(g(p + "derate_factor_min"), f_t))
        f_rh = min(g(p + "rh_factor_max"), max(0.0, rh_pct / g(p + "rh_reference_pct")))
        removal = g(p + "rated_g_per_h") * f_t * f_rh
        power = g(p + "power_w")
        return removal, power + removal * g(p + "latent_heat_wh_per_g"), power

    def _humidifier_effect(self, on: bool) -> tuple[float, float, float, float]:
        """가습기 → (가습 g/h, 열 W, PM mg/min, 전력 W)."""
        if not on:
            return 0.0, 0.0, 0.0, 0.0
        p = "appliances.humidifier."
        g = self.cfg.get
        rate = g(p + "rated_g_per_h")
        power = g(p + "power_w")
        heat = power - (rate * g("physics.water_latent_heat_wh_per_g") if g(p + "evaporative_cooling") else 0.0)
        pm = g(p + "pm_mg_per_min_ultrasonic_tap") * g(p + "pm_emission_relative")[g(p + "type")]
        return rate, heat, pm, power

    def _fan_flow(self, rpm: float, prefix: str) -> float:
        g = self.cfg.get
        return g(prefix + "max_m3h") * min(max(rpm, 0.0) / g(prefix + "max_rpm"), 1.0)

    def _intake_flow(self, rpm: float) -> float:
        p = "appliances.intake_fan."
        g = self.cfg.get
        clogging = min(self.state.filter_hours / g(p + "filter_replace_hours"), 1.0)
        return self._fan_flow(rpm, p) * (1.0 - g(p + "filter_flow_loss_at_replace") * clogging)

    def _solar_w(self, lux: float, blind_deg: float) -> float:
        g = self.cfg.get
        p = "thermal."
        frac = min(max(blind_deg / g(p + "blind_shade_angle_deg"), 0.0), 1.0)
        # 열 계수 — 빛 투과율이 아니다 (창 안쪽 블라인드는 흡수한 햇빛이 실내 열로 남는다 · 2026-10-13)
        heat = g(p + "blind_solar_heat_factor_open") + frac * (
            g(p + "blind_solar_heat_factor_shaded") - g(p + "blind_solar_heat_factor_open")
        )
        irradiance = max(lux, 0.0) / g(p + "solar_luminous_efficacy_lm_per_w")
        return g("window.glazing_area_m2") * irradiance * heat * g(p + "solar_heat_gain_fraction")

    def _blind_flow_factor(self, blind_deg: float) -> float:
        """창 안쪽 블라인드가 창문 환기를 막는 정도 — 유효 유량 계수 (0° 개방 → 차광각, 선형)."""
        g = self.cfg.get
        frac = min(max(blind_deg / g("thermal.blind_shade_angle_deg"), 0.0), 1.0)
        return g("window.blind_flow_factor_open") + frac * (
            g("window.blind_flow_factor_shaded") - g("window.blind_flow_factor_open"))

    # -- 적분 --

    def step(
        self,
        dt_s: float,
        act: ActuatorCommands,
        ext: ExternalConditions,
        src: SourceRates | None = None,
        occ: Occupancy | None = None,
    ) -> dict:
        src = src or SourceRates()
        occ = occ or Occupancy(count=0)
        max_sub = self.cfg.get("integration.max_substep_s")
        n = max(1, math.ceil(dt_s / max_sub))
        obs: dict = {}
        for _ in range(n):
            obs = self._substep(dt_s / n, act, ext, src, occ)
        return obs

    def _substep(
        self, dt: float, act: ActuatorCommands, ext: ExternalConditions, src: SourceRates, occ: Occupancy
    ) -> dict:
        g = self.cfg.get
        s = self.state
        v = g("room.volume_m3")
        b, c = self._b, self._c
        t = s.temp_c
        rh = psychro.abs_to_rh(t, s.abs_humidity_g_m3, b, c)
        w_out = psychro.rh_to_abs(ext.outdoor_temp_c, ext.outdoor_rh_pct, b, c)
        wind = g("window.default_wind_speed_ms") if ext.wind_speed_ms < 0 else ext.wind_speed_ms

        # 공기 수지
        hood_lv = int(act.range_hood_level)
        q_hood = g("appliances.range_hood.flow_m3h")[f"l{hood_lv}"] if hood_lv > 0 else 0.0
        q_win = air_balance.window_flow_m3h(
            act.window_open_ratio, t, ext.outdoor_temp_c, wind,
            g("window.opening_width_max_m"), g("window.opening_height_m"),
            g("window.discharge_coefficient"), g("window.wind_coefficient"),
        )
        flow_k = self._blind_flow_factor(act.blind_angle_deg)     # 창 안쪽 블라인드가 바람을 막는다 (2026-10-13)
        q_win *= flow_k
        q_intake = self._intake_flow(act.intake_fan_rpm)
        q_exhaust = self._fan_flow(act.exhaust_fan_rpm, "appliances.exhaust_fan.")
        # 배기 부족분 중 열린 창문이 받는 몫 — 창문은 큰 개구라 틈새보다 먼저 보충 공기를 받는다
        deficit = max(0.0, q_exhaust + q_hood - q_intake)
        q_win += deficit * air_balance.window_makeup_share(
            act.window_open_ratio * flow_k, g("window.opening_width_max_m"), g("window.opening_height_m"),
            g("window.crack_leakage_area_m2"))
        q_inf0 = g("air_balance.base_infiltration_ach") * v
        net = q_intake + q_win - q_exhaust - q_hood
        inf_model = g("air_balance.infiltration_model")
        flows = air_balance.AirFlows(
            intake=q_intake, window=q_win, exhaust=q_exhaust, hood=q_hood,
            infiltration=air_balance.infiltration_m3h(q_inf0, net, inf_model),
        )
        # 진단용 — 다른 쪽 식의 값 (상태에는 반영하지 않는다)
        q_inf_alt = air_balance.infiltration_m3h(q_inf0, net, air_balance.alternative_model(inf_model))
        q_oa = flows.outdoor_air

        # 가전 · 발생원
        ac_sens, ac_dry, p_ac = self._ac_effect(act.ac, t, rh)
        dh_dry, dh_heat, p_dh = self._dehumidifier_effect(act.dehumidifier, t, rh)
        hu_add, hu_heat, hu_pm, p_hu = self._humidifier_effect(act.humidifier)
        fan_lv = int(act.ceiling_fan)
        fan_key = "low" if abs(fan_lv) == 1 else "high"
        p_cf = g("appliances.ceiling_fan.power_w")[fan_key] if fan_lv != 0 else 0.0
        pur_lv = int(act.purifier_level)
        cadr = g("appliances.purifier.cadr_m3h")[f"l{pur_lv}"] if pur_lv > 0 else 0.0
        p_pur = g("appliances.purifier.power_w")[f"l{pur_lv}"] if pur_lv > 0 else 0.0
        p_hood = g("appliances.range_hood.power_w")[f"l{hood_lv}"] if hood_lv > 0 else 0.0
        p_intake = g("appliances.intake_fan.power_w") if act.intake_fan_rpm > 0 else 0.0
        p_exhaust = g("appliances.exhaust_fan.power_w") if act.exhaust_fan_rpm > 0 else 0.0
        p_light = (g("lighting.ceiling_light_w") * act.ceiling_light_pct
                   + g("lighting.desk_lamp_w") * act.desk_light_pct) / 100.0

        act_key = occ.activity
        n_occ = max(occ.count, 0)
        h_occ = n_occ * g("occupant.sensible_heat_w")[act_key]
        g_occ = n_occ * g("occupant.moisture_g_per_h")[act_key]
        co2_gen = n_occ * g("occupant.co2_ppm_m3_per_h")[act_key]

        # 결로 (창 표면 수분 제거)
        r_si = condensation.inner_surface_resistance(self.cfg, act.blind_angle_deg, fan_lv)
        t_s = condensation.window_surface_temp_c(t, ext.outdoor_temp_c, r_si, g("condensation.r_rest_m2k_w"))
        w_sat_s = psychro.saturation_density_g_m3(t_s, b, c)
        cond_g_h = max(0.0, s.abs_humidity_g_m3 - w_sat_s) * g("condensation.surface_mass_transfer_ms") \
            * g("window.glazing_area_m2") * SECONDS_PER_HOUR

        laundry_g_h = self._laundry_rate_g_h(t, s.abs_humidity_g_m3, fan_lv)

        # 습도 — V·dw/dt (g/h)
        dw = (g_occ + src.moisture_g_per_h + hu_add + laundry_g_h - dh_dry - ac_dry - cond_g_h
              + q_oa * (w_out - s.abs_humidity_g_m3)) / v
        # PM — V·dP/dt (µg/h)
        eps = g("appliances.range_hood.capture_efficiency") if hood_lv > 0 else 0.0
        eta = g("appliances.intake_fan.filter_efficiency_pm25")
        p_out = ext.outdoor_pm25_ugm3
        k_dep = g("pm.deposition_rate_per_h")
        pm_src = (src.cooking_pm_mg_per_min * (1.0 - eps) + src.other_pm_mg_per_min + hu_pm) * MG_PER_MIN_TO_UG_PER_H
        pm_in = (q_intake * (1.0 - eta) + q_win + flows.infiltration * g("air_balance.penetration_factor")) * p_out
        dp = (pm_src + pm_in - (q_oa + cadr + k_dep * v) * s.pm25_ugm3) / v
        # CO₂ 참값 — V·dC/dt (ppm·m³/h)
        dco2 = (co2_gen + q_oa * (g("co2.outdoor_ppm") - s.co2_ppm)) / v

        # 난방 — 경계 조건 (가정 A13) · 확장 트랙은 온수 바닥난방
        h_heat = 0.0
        if self.hydronic:
            h_heat, p_boiler, gas_w = self._hydronic(act.boiler, t, dt, src.shower_active)
        elif ext.heating_setpoint_c >= 0:
            h_heat = min(g("heating.capacity_w"),
                         max(0.0, g("heating.modulation_w_per_k") * (ext.heating_setpoint_c - t)))

        # 온도 — 3R3C (W)
        th = "thermal."
        solar = self._solar_w(ext.outdoor_illuminance_lux, act.blind_angle_deg)
        f_mass = g(th + "solar_to_mass_fraction")
        g_vent = g(th + "air_heat_capacity_wh_per_m3k") * q_oa
        g_glz = g("window.glazing_u_w_m2k") * g("window.glazing_area_m2")
        g_am = g(th + "air_mass_conductance_w_per_k")
        g_ae = g(th + "air_envelope_conductance_w_per_k")
        g_eo = g(th + "envelope_outdoor_conductance_w_per_k")
        h_air = (h_occ + p_light + dh_heat + hu_heat + p_cf + p_pur + src.sensible_heat_w + src.cooking_heat_w
                 + h_heat + solar * (1.0 - f_mass) - ac_sens)
        q_air = ((s.mass_temp_c - t) * g_am + (s.envelope_temp_c - t) * g_ae
                 + (ext.outdoor_temp_c - t) * (g_glz + g_vent) + h_air)
        q_mass = (t - s.mass_temp_c) * g_am + solar * f_mass
        q_env = (t - s.envelope_temp_c) * g_ae + (ext.outdoor_temp_c - s.envelope_temp_c) * g_eo

        hrs = dt / SECONDS_PER_HOUR
        s.temp_c += q_air * dt / (g(th + "air_capacity_wh_per_k") * WH_TO_J)
        s.mass_temp_c += q_mass * dt / (g(th + "mass_capacity_wh_per_k") * WH_TO_J)
        s.envelope_temp_c += q_env * dt / (g(th + "envelope_capacity_wh_per_k") * WH_TO_J)
        s.abs_humidity_g_m3 = max(0.0, s.abs_humidity_g_m3 + dw * hrs)
        # 공기 자체가 과포화되면 넘친 수분은 응결(안개 · 표면 이슬)로 빠진다 — RH > 100 % 방지
        w_sat_air = psychro.saturation_density_g_m3(s.temp_c, b, c)
        if s.abs_humidity_g_m3 > w_sat_air:
            s.condensate_g += (s.abs_humidity_g_m3 - w_sat_air) * v
            s.abs_humidity_g_m3 = w_sat_air
        s.pm25_ugm3 = max(0.0, s.pm25_ugm3 + dp * hrs)
        s.co2_ppm = s.co2_ppm + dco2 * hrs
        s.laundry_moisture_g = max(0.0, s.laundry_moisture_g - laundry_g_h * hrs)
        s.condensate_g += cond_g_h * hrs
        if act.intake_fan_rpm > 0:
            s.filter_hours += hrs
        hood_target = s.temp_c + g("hood_sensor.plume_k_per_w") * src.cooking_heat_w
        s.hood_temp_c += (hood_target - s.hood_temp_c) * (1.0 - math.exp(-dt / g("hood_sensor.time_constant_s")))
        s.time_s += dt

        power = {
            "ac": p_ac, "dehumidifier": p_dh, "humidifier": p_hu, "ceiling_fan": p_cf,
            "intake_fan": p_intake, "exhaust_fan": p_exhaust, "purifier": p_pur,
            "range_hood": p_hood, "lighting": p_light,
        }
        if self.hydronic:
            power["boiler"] = p_boiler                       # 보일러 전원 계량 플러그 (전기)
            s.energy_wh["boiler_gas"] = s.energy_wh.get("boiler_gas", 0.0) + gas_w * hrs   # 가스 (전기 합계와 따로)
            self._last_gas_w = gas_w
        for k, p_w in power.items():
            s.energy_wh[k] = s.energy_wh.get(k, 0.0) + p_w * hrs

        return self._observe(ext, act, flows, power, cond_g_h, r_si, h_heat, q_inf_alt)

    def _observe(self, ext, act, flows, power, cond_g_h, r_si, h_heat, q_inf_alt) -> dict:
        g = self.cfg.get
        s = self.state
        b, c = self._b, self._c
        rh = psychro.abs_to_rh(s.temp_c, s.abs_humidity_g_m3, b, c)
        t_dew = psychro.dew_point_c(s.temp_c, rh, b, c)
        t_s = condensation.window_surface_temp_c(
            s.temp_c, ext.outdoor_temp_c, r_si, g("condensation.r_rest_m2k_w"))
        # 조도 참값 — 주광은 직사광 · 확산광 · 블라인드 각도 표 (common/daylight.py · v2.2 개정 · W12 렌더 대조)
        dl = g("lighting.daylight")
        e_out = max(ext.outdoor_illuminance_lux, 0.0)
        daylight = e_out * daylight_model.workplane_per_outdoor(dl, ext.sky, act.blind_angle_deg)   # 작업면 주광
        daylight_sensor = e_out * daylight_model.sensor_per_outdoor(dl, ext.sky, act.blind_angle_deg)   # 천장 센서 위치
        pc, pd = act.ceiling_light_pct / 100.0, act.desk_light_pct / 100.0
        lux = (daylight_sensor                                                              # 천장 센서 위치
               + g("lighting.ceiling_lux_at_sensor_full") * pc + g("lighting.desk_lux_at_sensor_full") * pd)
        desk_lux = daylight + g("lighting.ceiling_lux_at_desk_full") * pc + g("lighting.desk_lux_at_desk_full") * pd
        floor_lux = daylight + g("lighting.ceiling_lux_at_floor_full") * pc + g("lighting.desk_lux_at_floor_full") * pd
        fan_lv = int(act.ceiling_fan)
        perceived = 0.0
        if fan_lv > 0:
            perceived = g("appliances.ceiling_fan.perceived_cooling_c")["low" if fan_lv == 1 else "high"]
        obs = {
            "time_s": s.time_s,
            "temperature_c": s.temp_c,
            "humidity_pct": rh,
            "abs_humidity_g_m3": s.abs_humidity_g_m3,
            "dew_point_c": t_dew,
            "window_surface_c": t_s,
            "dew_margin_c": t_s - t_dew,
            "pm25_ugm3": s.pm25_ugm3,
            "co2_ppm": s.co2_ppm,
            "hood_temperature_c": s.hood_temp_c,
            "operative_temp_c": s.temp_c - perceived,
            "illuminance_lux": lux,
            "desk_illuminance_lux": desk_lux,
            "floor_illuminance_lux": floor_lux,          # 방 작업면 (바닥 중앙) — 모드 조도 목표의 기준면
            "heating_w": h_heat,
            "ac_state": self.ac_state,
            "mass_temp_c": s.mass_temp_c,
            "envelope_temp_c": s.envelope_temp_c,
            "q_intake_m3h": flows.intake,
            "q_window_m3h": flows.window,
            "q_exhaust_m3h": flows.mech_exhaust,
            "q_net_m3h": flows.net_supply,
            "q_inf_m3h": flows.infiltration,
            "q_inf_alt_m3h": q_inf_alt,
            "condensation_rate_g_h": cond_g_h,
            "condensate_g": s.condensate_g,
            "laundry_moisture_g": s.laundry_moisture_g,
            "filter_hours": s.filter_hours,
            "appliance_power_w": dict(power),
            "energy_wh": dict(s.energy_wh),
        }
        if self.hydronic:                                 # 확장 트랙만 — boundary 출력 열은 v1.29 와 같다
            obs.update({"floor_temp_c": s.floor_temp_c, "supply_temp_c": s.supply_temp_c,
                        "boiler_burning": self.boiler_burning, "boiler_call": self.boiler_call,
                        "boiler_gas_w": getattr(self, "_last_gas_w", 0.0)})
        return obs
