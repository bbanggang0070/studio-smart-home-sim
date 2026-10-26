"""EXP-5 공통 — 에피소드 · 기상 · 참값 실행 · 비용 · 기준 정책 (사전 등록 docs/13 §3–§5).

에피소드 = 재실 생성기의 외출 하나. 출발 warmup_h 전부터 설정 온도로 냉방(재실)한 뒤 출발 → 정책이 에어컨을 정한다 →
귀가하면 설정 온도 냉방(모든 방식 같음) → 귀가 후 after_arrival_min 에 끝.
비용 = 에어컨 전력량 Wh (출발 ~ 귀가 + 창) + discomfort_wh_per_kh × λ × 귀가 후 불쾌 K·h — 계획기(controller/energy.py)와 같은 정의.

정책은 참값 계수 · 참 귀가 시각을 보지 않는다 (오라클만 예외). 관측 = 실내 온도 · 외기 · 실내 주광 · 에어컨 전력 · 시각 · 요일 · 출발 시각 · 직전 귀가.
"""

from __future__ import annotations

import copy
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from controller.params import ControllerParams, load_params  # noqa: E402
from env_model.config import load_config  # noqa: E402
from env_model.room import AcCommand, ActuatorCommands, ExternalConditions, Occupancy, RoomModel  # noqa: E402
from harness import occupancy_gen as OG  # noqa: E402
from harness import randomize as RZ  # noqa: E402
from harness import weather as W  # noqa: E402

ACTIONS = ("off", "setback", "cool")


def load_cfg() -> dict:
    with open(REPO / "config" / "exp5.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_harness() -> dict:
    with open(REPO / "config" / "harness.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class Ctx:
    """한 번 읽어 두는 설정 묶음."""
    cfg: dict
    h: dict
    p: ControllerParams
    env_cfg: Any
    sp: float                       # 냉방 목표 °C
    setback_c: float
    lam: float
    w_kh: float                     # 불쾌 1 K·h 의 Wh 환산
    margin: float
    eff: float                      # 일사 → 조도
    min_on_s: float
    min_off_s: float

    @classmethod
    def load(cls) -> "Ctx":
        cfg, h, p = load_cfg(), load_harness(), load_params()
        env_cfg = load_config(REPO / h["paths"]["environment_model"])
        mode = p.mode(cfg["mode"])
        en = p.modes.get("energy") or {}
        ac = p.get("appliances.ac")
        return cls(cfg, h, p, env_cfg, float(mode["cooling_setpoint_c"]), float(p.get("energy.away_strategy.setback_c")),
                   float(en.get("comfort_weight", 1.0)), float(p.get("energy.planner.discomfort_wh_per_kh")),
                   float(p.get("energy.planner.discomfort_margin_c")),
                   float(env_cfg.get("thermal.solar_luminous_efficacy_lm_per_w")),
                   float(ac["compressor_min_on_s"]), float(ac["compressor_min_off_s"]))

    def cost(self, energy_wh: float, discomfort_kh: float) -> float:
        return energy_wh + self.lam * self.w_kh * discomfort_kh


# ---------------------------------------------------------------- 기상

class Weather:
    """시간별 실측 기상 → 선형 보간 (numpy · pandas 호출 없이)."""

    def __init__(self, ctx: Ctx, years: list[int]):
        wc = copy.deepcopy(ctx.h["weather"])
        wc["years"] = {"x": years}
        s = W.load_series(wc, REPO, "x")
        self.index = s.index
        self.t0 = s.index[0]
        self.hours = ((s.index - self.t0) / pd.Timedelta(hours=1)).to_numpy(float)
        self.temp = s["outdoor_temp_c"].to_numpy(float)
        self.rh = s["outdoor_rh_pct"].to_numpy(float)
        self.lux = s["ghi_w_m2"].to_numpy(float) * ctx.eff
        months = set(ctx.cfg["episode"]["months"])
        days = pd.date_range(s.index[0].normalize(), s.index[-1].normalize(), freq="D")
        self.days = [d for d in days if d.month in months and d.year in years]

    def at(self, ts: pd.Timestamp) -> tuple[float, float, float]:
        x = (ts - self.t0) / pd.Timedelta(hours=1)
        return (float(np.interp(x, self.hours, self.temp)), float(np.interp(x, self.hours, self.rh)),
                float(np.interp(x, self.hours, self.lux)))

    def arrays(self, start: pd.Timestamp, n: int, dt_s: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x = (start - self.t0) / pd.Timedelta(hours=1) + np.arange(n) * dt_s / 3600.0
        return np.interp(x, self.hours, self.temp), np.interp(x, self.hours, self.rh), np.interp(x, self.hours, self.lux)


# ---------------------------------------------------------------- 에피소드

@dataclass
class Episode:
    persona: str
    split: str                      # train · val · eval
    cond: str                       # base · params · pattern (학습 · 검증은 base)
    idx: int
    week: int
    weekday: int
    day_type: str
    depart_tod: float               # 출발한 날 0시 기준 초
    arrive_tod: float               # 출발한 날 0시 기준 초 (다음날이면 86400 이상)
    prev_arrive_tod: float
    date: pd.Timestamp              # 출발한 날 0시 (기상)
    truth_over: dict = field(default_factory=dict)

    @property
    def away_h(self) -> float:
        return (self.arrive_tod - self.depart_tod) / 3600.0

    def key(self) -> str:
        return f"{self.persona}|{self.split}|{self.cond}|{self.idx}"


def shifted_occ_cfg(ctx: Ctx, persona: str, shift: dict | None) -> dict:
    oc = copy.deepcopy(ctx.h["occupancy_generator"])
    oc["min_absence_h"] = float(ctx.cfg["episode"]["min_absence_h"])
    if not shift:
        return oc
    dts = oc["personas"][persona]["day_types"]
    for name, k in (shift.get("weight") or {}).items():
        for wk in ("weight_weekday", "weight_weekend"):
            dts[name][wk] = float(dts[name][wk]) * float(k)
    if "out_scale" in shift:
        lo, hi = shift["out_scale"]["hours"]
        f = float(shift["out_scale"]["factor"])
        for d in dts.values():
            d["p_home"] = [max(0.0, 1.0 - f * (1.0 - p)) if lo <= hr < hi else p for hr, p in enumerate(d["p_home"])]
    return oc


def absences(ctx: Ctx, persona: str, weeks: int, seed: int | None, shift: dict | None = None):
    oc = shifted_occ_cfg(ctx, persona, shift)
    occ, types = OG.generate(oc, persona, weeks=weeks, seed=seed)
    return OG.absences(occ, types, oc)


def _fits(wx: Weather, d: pd.Timestamp, ctx: Ctx, depart: float, arrive: float) -> bool:
    e = ctx.cfg["episode"]
    a = d + pd.Timedelta(seconds=depart - e["warmup_h"] * 3600.0)
    b = d + pd.Timedelta(seconds=arrive + e["after_arrival_min"] * 60.0)
    return a >= wx.index[0] and b <= wx.index[-1]


def make_episodes(ctx: Ctx, persona: str, split: str, cond: str, absn, wx: Weather, rng: np.random.Generator,
                  week_offset: int = 0, truth_draw_seed: int | None = None) -> list[Episode]:
    """외출 목록 → 에피소드. 날짜는 기상 연도의 냉방철에서 무작위 · 참값 계수는 cond == params 일 때 뽑는다."""
    eps: list[Episode] = []
    prev = None
    rz = ctx.h["randomization"]
    for i, a in enumerate(absn):
        p_arr = prev if prev is not None else float(np.median([x.arrive_tod_s for x in absn]))
        prev = a.arrive_tod_s % 86400.0
        for _ in range(50):
            d = wx.days[int(rng.integers(len(wx.days)))]
            if _fits(wx, d, ctx, a.depart_tod_s, a.arrive_tod_s):
                break
        over = {}
        if cond == "params":
            over, _ = RZ.draw(rz, ctx.env_cfg, int(rng.integers(2**31)) if truth_draw_seed is None else truth_draw_seed + i,
                              nominal=False)
        eps.append(Episode(persona, split, cond, i, a.day // 7 - week_offset, a.weekday, a.day_type, a.depart_tod_s,
                           a.arrive_tod_s, p_arr, d, over))
    return eps


def train_val_episodes(ctx: Ctx, persona: str, k: int) -> tuple[list[Episode], list[Episode]]:
    """학습 k주 · 검증 val_weeks — 페르소나 기본 시드 연속 · 학습 연도 기상."""
    vw = int(ctx.cfg["data"]["val_weeks"])
    ab = absences(ctx, persona, k + vw, None)
    wx = weather(ctx, "train")
    rng = np.random.default_rng(1000 + k)
    eps = make_episodes(ctx, persona, "train", "base", ab, wx, rng)
    tr = [e for e in eps if e.week < k]
    va = [e for e in eps if e.week >= k]
    for e in va:
        e.split = "val"
    return tr, va


def eval_episodes(ctx: Ctx, persona: str, cond: str) -> list[Episode]:
    """평가 — 평가 전용 시드 · 2024 기상. 세 조건은 같은 재실 시드(패턴만 바꾼 것 제외)."""
    ev = ctx.cfg["eval"]
    pi = ctx.cfg["personas"].index(persona)
    shift = ev["pattern_shift"].get(persona) if cond == "pattern" else None
    ab = absences(ctx, persona, int(ev["weeks"]), int(ev["occupancy_seed_base"]) + pi, shift)
    wx = weather(ctx, "eval")
    rng = np.random.default_rng(int(ev["draw_seed_base"]) + pi + 100 * ctx.cfg["eval"]["conditions"].index(cond))
    eps = make_episodes(ctx, persona, "eval", cond, ab, wx, rng)
    return eps


_WX: dict[str, Weather] = {}


def weather(ctx: Ctx, split: str) -> Weather:
    if split not in _WX:
        _WX[split] = Weather(ctx, ctx.cfg["weather"]["eval_years" if split == "eval" else "train_years"])
    return _WX[split]


# ---------------------------------------------------------------- 참값 실행

@dataclass
class Obs:
    now_s: float                    # 에피소드 시작(출발한 날 0시) 기준 초 = 그날 시각
    temp_c: float
    outdoor_c: float
    lux: float                      # 실내 주광 (조명 꺼 둠)
    ac_w: float
    occupied: bool
    weekday: int
    depart_tod: float
    prev_arrive_tod: float


class Policy:
    """정책 — 외출 중 결정 간격마다 act(). observe() 는 참값 보폭마다 (관측기용)."""
    name = "policy"

    def reset(self, ep: Episode, ctx: Ctx) -> None: ...

    def observe(self, o: Obs, dt_s: float) -> None: ...

    def act(self, o: Obs) -> str:
        raise NotImplementedError


class Fixed(Policy):
    def __init__(self, action: str):
        self.action = action
        self.name = f"always_{action}"

    def act(self, o: Obs) -> str:
        return self.action


def run_episode(ctx: Ctx, ep: Episode, policy: Policy, wx: Weather, record: bool = False) -> dict[str, Any]:
    """→ {energy_wh, discomfort_kh, cost, overrides, arrive_ok, ...}. 압축기 최소 ON/OFF 는 여기서 강제한다."""
    e = ctx.cfg["episode"]
    dt = float(e["truth_dt_s"])
    dec = int(round(float(e["decision_s"]) / dt))
    env_cfg = ctx.env_cfg.with_overrides(ep.truth_over) if ep.truth_over else ctx.env_cfg
    room = RoomModel.from_conditions(env_cfg, float(e["start_temp_c"]), float(e["start_rh_pct"]), 10.0, 450.0)
    t_start = ep.depart_tod - float(e["warmup_h"]) * 3600.0
    t_end = ep.arrive_tod + float(e["after_arrival_min"]) * 60.0
    n = int(math.ceil((t_end - t_start) / dt))
    to, rh, lux = wx.arrays(ep.date + pd.Timedelta(seconds=t_start), n, dt)
    policy.reset(ep, ctx)
    sp, sb = ctx.sp, ctx.sp + ctx.setback_c
    ac_on, last_change = True, -1e9
    action = "cool"
    energy = disc = 0.0
    overrides = decisions = 0
    temp = float(e["start_temp_c"])
    ac_w = last_lux = 0.0
    t_arr_c = math.nan
    rec = []
    for i in range(n):
        now = t_start + i * dt
        away = ep.depart_tod <= now < ep.arrive_tod
        home_after = now >= ep.arrive_tod
        o = Obs(now, temp, float(to[i]), last_lux, ac_w, not away, ep.weekday, ep.depart_tod, ep.prev_arrive_tod)
        policy.observe(o, dt if i else 0.0)             # 관측기는 출발 전부터 (제어기와 같다)
        if away:
            if (i - int(round((ep.depart_tod - t_start) / dt))) % dec == 0:
                action = policy.act(o)
                decisions += 1
        else:
            action = "cool"
        want_on = action != "off"
        if want_on != ac_on:
            if now - last_change >= (ctx.min_off_s if not ac_on else ctx.min_on_s):
                ac_on, last_change = want_on, now
            elif away:
                overrides += 1
        cmd = AcCommand(power=ac_on, mode="cool", setpoint_c=sb if action == "setback" else sp)
        ext = ExternalConditions(outdoor_temp_c=float(to[i]), outdoor_rh_pct=float(rh[i]), outdoor_illuminance_lux=float(lux[i]))
        ob = room.step(dt, ActuatorCommands(ac=cmd), ext, occ=Occupancy(count=0 if away else 1))
        temp = float(ob["temperature_c"])
        ac_w = float(ob["appliance_power_w"].get("ac", 0.0))
        last_lux = max(0.0, float(ob["illuminance_lux"]))
        if now >= ep.depart_tod:
            energy += ac_w * dt / 3600.0
        if home_after:
            disc += max(0.0, temp - (sp + ctx.margin)) * dt / 3600.0
            if math.isnan(t_arr_c):
                t_arr_c = temp
        if record:
            rec.append((now, temp, float(to[i]), ac_w, action, int(ac_on)))
    out = {"persona": ep.persona, "split": ep.split, "cond": ep.cond, "idx": ep.idx, "week": ep.week,
           "weekday": ep.weekday, "day_type": ep.day_type, "away_h": round(ep.away_h, 3), "date": f"{ep.date:%Y-%m-%d}",
           "energy_wh": energy, "discomfort_kh": disc, "cost": ctx.cost(energy, disc), "overrides": overrides,
           "decisions": decisions, "temp_at_arrival_c": t_arr_c,
           "arrive_ok": float(t_arr_c <= sp + ctx.margin) if t_arr_c == t_arr_c else math.nan}
    if record:
        out["trace"] = rec
    return out


# ---------------------------------------------------------------- 오라클 (비용 하한 · 참 귀가 · 참값 모델)

class Scripted(Policy):
    """정해 둔 계획 — 셋백 / 끄기 / start 이후 냉방 (오라클 탐색용)."""

    def __init__(self, kind: str, start: float | None = None):
        self.kind, self.start = kind, start
        self.name = "scripted"

    def act(self, o: Obs) -> str:
        if self.kind == "precool":
            return "cool" if o.now_s >= self.start else "off"
        return self.kind


def oracle(ctx: Ctx, ep: Episode, wx: Weather) -> dict[str, Any]:
    """참 귀가 · 참값 모델로 셋백 · 끄기 · 프리쿨링(결정 간격 격자) 중 최저 비용."""
    dec = float(ctx.cfg["episode"]["decision_s"])
    best = None
    cands = [Scripted("setback"), Scripted("off")]
    t = ep.depart_tod
    while t < ep.arrive_tod:
        cands.append(Scripted("precool", t))
        t += dec
    for c in cands:
        r = run_episode(ctx, ep, c, wx)
        if best is None or r["cost"] < best["cost"]:
            best = {**r, "oracle_plan": c.kind, "oracle_start_h": (c.start - ep.depart_tod) / 3600 if c.start else -1.0}
    return best
