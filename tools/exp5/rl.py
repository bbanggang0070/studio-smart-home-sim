"""EXP-5 방식 ③ — DQN (docs/13 §3 · §6).

행동 (5분마다) = {끄기 · 셋백 · 설정 온도 냉방} · 보상 = −(전력량 Wh + λ·w·불쾌 K·h) / 100 (계획기와 같은 비용).
관측 = 그날 시각(sin · cos) · 출발 후 시간 · 실내 · 외기 · 주광 · 요일 · 주말 · 직전 귀가 · 귀가 분위(q20 · q50 · q80 — ① 과 같은 귀가 모델) · 에어컨 켬.

학습 환경
  ③a 데이터 기반 — 학습 k주 데이터만: 식별 2R2C (① 과 같은 모델) · 운전 기록의 외기 · 주광을 같은 시각에 맞춰 잘라 씀 ·
     학습 에피소드(출발 · 귀가 · 요일)를 복원 추출. 에어컨 전력은 명판 근사(① 의 계획기와 같다)
  ③b 시뮬레이터 접근 (참고) — 참값 3R3C · 계수 무작위(randomization.truth_params) · 학습 연도 기상 · 페르소나 생성기(학습 · 검증과 다른 시드)
     귀가 분위는 주 비교 데이터(k = main_weeks)의 귀가 모델

    uv run python tools/exp5/rl.py tune  --variant a|b [--persona P] [--weeks K]
    uv run python tools/exp5/rl.py train --variant a|b [--persona P] [--weeks K]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import gymnasium as gym
import numpy as np
import pandas as pd
import torch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exp5.common import (ACTIONS, REPO, Ctx, Episode, Obs, Policy, absences, make_episodes, run_episode,  # noqa: E402
                         train_val_episodes, weather)
from exp5.data import data_dir  # noqa: E402

from controller.arrival_gbm import ArrivalGBM  # noqa: E402
from controller.energy import AcSpec, Thermal2R2C  # noqa: E402
from env_model.room import AcCommand, ActuatorCommands, ExternalConditions, Occupancy, RoomModel  # noqa: E402
from harness import randomize as RZ  # noqa: E402

N_OBS = 13
B_SEED_OFFSET = 777                       # ③b 재실 생성기 시드 = 페르소나 시드 + 이 값 (학습 · 검증 · 평가와 다름)
B_WEEKS = 26


# ---------------------------------------------------------------- 귀가 분위 · 관측

class ArrivalInfo:
    """① 과 같은 귀가 모델 (auto 선택) → 조건부 분위 [s]."""

    def __init__(self, data: Path):
        doc = yaml.safe_load((data / "energy.yaml").read_text(encoding="utf-8"))
        self.hist = np.asarray(doc["arrival_history_tod_s"], float)
        meta = json.loads((data / "gbm.json").read_text(encoding="utf-8"))
        self.gbm = ArrivalGBM(data / "gbm.json") if meta.get("selected") == "quantile_gbm" else None
        self._knots: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}

    def quantiles(self, now: float, weekday: int, depart: float, prev: float) -> np.ndarray:
        """ArrivalGBM.conditional_quantiles_h 와 같은 계산 — 분포 매듭은 에피소드(특성)마다 한 번만 만든다."""
        probs = np.array((0.2, 0.5, 0.8))
        if self.gbm is not None:
            key = (weekday, depart, prev)
            if key not in self._knots:
                if len(self._knots) > 4096:
                    self._knots.clear()
                self._knots[key] = self.gbm._cdf_knots(self.gbm.features(weekday, depart / 3600.0, prev / 3600.0))
            p, h = self._knots[key]
            now_h = now / 3600.0
            f_now = float(np.interp(now_h, h, p))
            return np.maximum(np.interp(f_now + (1.0 - f_now) * probs, p, h), now_h) * 3600.0
        later = self.hist[self.hist > now]
        return np.quantile(later, probs) if later.size else np.full(3, now + 300.0)


def make_obs(now, depart, t, to, lux, weekday, prev, arrq, ac_on) -> np.ndarray:
    tod = (now % 86400.0) / 86400.0 * 2 * math.pi
    return np.array([math.sin(tod), math.cos(tod), (now - depart) / 3600.0 / 12.0, (t - 26.0) / 5.0, (to - 26.0) / 10.0,
                     lux / 2e4, weekday / 6.0, float(weekday >= 5), (prev % 86400.0) / 86400.0,
                     *[min((q - now) / 3600.0, 24.0) / 12.0 for q in arrq], float(ac_on)], np.float32)


# ---------------------------------------------------------------- 학습 환경

class AwayEnv(gym.Env):
    """외출 한 번 = 에피소드. 하위 클래스가 _start · _advance 를 구현한다 (5분 한 칸 → 전력량 · 실내 · 외기 · 주광)."""

    def __init__(self, ctx: Ctx, arrival: ArrivalInfo, seed: int):
        self.ctx, self.arrival = ctx, arrival
        self.rng = np.random.default_rng(seed)
        self.action_space = gym.spaces.Discrete(len(ACTIONS))
        self.observation_space = gym.spaces.Box(-10.0, 10.0, (N_OBS,), np.float32)
        self.dec = float(ctx.cfg["episode"]["decision_s"])
        self.after = float(ctx.cfg["episode"]["after_arrival_min"]) * 60.0

    def _obs(self):
        q = self.arrival.quantiles(self.now, self.ep.weekday, self.ep.depart_tod, self.ep.prev_arrive_tod)
        return make_obs(self.now, self.ep.depart_tod, self.t, self.to, self.lux, self.ep.weekday, self.ep.prev_arrive_tod,
                        q, self.ac_on)

    def reset(self, *, seed=None, options=None):
        self._start()
        return self._obs(), {}

    def step(self, a: int):
        ctx = self.ctx
        act = ACTIONS[int(a)]
        self.ac_on = act != "off"
        e = d = 0.0
        span = min(self.dec, self.ep.arrive_tod - self.now)
        e += self._advance(act, span, home=False)
        done = self.now >= self.ep.arrive_tod - 1e-6
        if done:                                             # 귀가 — 모든 방식 같은 냉방으로 창 끝까지
            t_end = self.ep.arrive_tod + self.after
            while self.now < t_end - 1e-6:
                e1 = self._advance("cool", min(self.dec, t_end - self.now), home=True)
                e += e1
                d += self.last_disc
        r = -(ctx.cost(e, d)) / 100.0
        return self._obs(), r, done, False, {}


class LearnedSim(AwayEnv):
    """③a — 학습 k주 데이터만으로 만든 시뮬레이터."""

    def __init__(self, ctx: Ctx, persona: str, k: int, seed: int):
        data = data_dir(ctx, persona, k)
        super().__init__(ctx, ArrivalInfo(data), seed)
        doc = yaml.safe_load((data / "energy.yaml").read_text(encoding="utf-8"))
        self.model = Thermal2R2C.from_dict(doc["thermal_2r2c"])
        log = np.load(data / "log.npz")
        self.log_to, self.log_lux = log["to"], log["lux"]
        self.log_dt = float(ctx.cfg["data"]["log_dt_s"])
        self.eps, _ = train_val_episodes(ctx, persona, k)
        ac = ctx.p.get("appliances.ac")
        self.ac = AcSpec(ac["cooling_kw"] * 1000.0, ac["cooling_kw"] * 1000.0 / ac["power_w"],
                         ctx.p.get("energy.planner.ac_modulation_w_per_k"), ctx.p.get("energy.planner.ac_band_c"))

    def _exo(self, now: float) -> tuple[float, float]:
        i = int(round((self.day0 + now) / self.log_dt)) % len(self.log_to)
        return float(self.log_to[i]), float(self.log_lux[i])

    def _start(self):
        self.ep = self.eps[int(self.rng.integers(len(self.eps)))]
        ndays = len(self.log_to) * self.log_dt / 86400.0
        self.day0 = float(self.rng.integers(max(1, int(ndays)))) * 86400.0
        self.t = self.tm = float(self.ctx.cfg["episode"]["start_temp_c"])
        self.now = self.ep.depart_tod - float(self.ctx.cfg["episode"]["warmup_h"]) * 3600.0
        self.ac_on = True
        while self.now < self.ep.depart_tod - 1e-6:
            self._advance("cool", min(self.dec, self.ep.depart_tod - self.now), home=True)
        self.to, self.lux = self._exo(self.now)

    def _advance(self, act: str, span: float, home: bool) -> float:
        sp = self.ctx.sp + (self.ctx.setback_c if act == "setback" else 0.0)
        self.to, self.lux = self._exo(self.now)
        q = 0.0 if act == "off" else self.ac.removal(self.t, sp)
        h = span / 3600.0
        self.t, self.tm = self.model.step(self.t, self.tm, self.to, self.lux, 1.0 if home else 0.0, q, h)
        self.now += span
        self.last_disc = max(0.0, self.t - (self.ctx.sp + self.ctx.margin)) * h if home else 0.0
        return q / self.ac.cop * h


class TruthSim(AwayEnv):
    """③b — 참값 3R3C · 계수 무작위 · 학습 연도 기상 (특권 정보 · 참고)."""

    def __init__(self, ctx: Ctx, persona: str, seed: int):
        super().__init__(ctx, ArrivalInfo(data_dir(ctx, persona, int(ctx.cfg["data"]["main_weeks"]))), seed)
        pseed = int(ctx.h["occupancy_generator"]["personas"][persona]["seed"]) + B_SEED_OFFSET
        self.wx = weather(ctx, "train")
        self.eps = make_episodes(ctx, persona, "train", "base", absences(ctx, persona, B_WEEKS, pseed), self.wx,
                                 np.random.default_rng(seed))
        self.dt = float(ctx.cfg["episode"]["truth_dt_s"])

    def _start(self):
        ctx = self.ctx
        self.ep = self.eps[int(self.rng.integers(len(self.eps)))]
        self.date = self.wx.days[int(self.rng.integers(len(self.wx.days)))]
        over, _ = RZ.draw(ctx.h["randomization"], ctx.env_cfg, int(self.rng.integers(2**31)), nominal=False)
        e = ctx.cfg["episode"]
        self.room = RoomModel.from_conditions(ctx.env_cfg.with_overrides(over), float(e["start_temp_c"]),
                                              float(e["start_rh_pct"]), 10.0, 450.0)
        self.now = self.ep.depart_tod - float(e["warmup_h"]) * 3600.0
        self.ac_on = True
        self.t = float(e["start_temp_c"])
        self.to, _, self.lux = self.wx.at(self.date + pd.Timedelta(seconds=self.now))
        while self.now < self.ep.depart_tod - 1e-6:
            self._advance("cool", min(self.dec, self.ep.depart_tod - self.now), home=True)

    def _advance(self, act: str, span: float, home: bool) -> float:
        ctx = self.ctx
        sp = ctx.sp + (ctx.setback_c if act == "setback" else 0.0)
        e = disc = 0.0
        n = max(1, int(round(span / self.dt)))
        for _ in range(n):
            to, rh, lux = self.wx.at(self.date + pd.Timedelta(seconds=self.now))
            ob = self.room.step(self.dt, ActuatorCommands(ac=AcCommand(power=act != "off", mode="cool", setpoint_c=sp)),
                                ExternalConditions(outdoor_temp_c=to, outdoor_rh_pct=rh, outdoor_illuminance_lux=lux),
                                occ=Occupancy(count=1 if home else 0))
            self.t = float(ob["temperature_c"])
            self.to, self.lux = to, max(0.0, float(ob["illuminance_lux"]))
            e += float(ob["appliance_power_w"].get("ac", 0.0)) * self.dt / 3600.0
            if home:
                disc += max(0.0, self.t - (ctx.sp + ctx.margin)) * self.dt / 3600.0
            self.now += self.dt
        self.last_disc = disc
        return e


# ---------------------------------------------------------------- 평가용 정책

class RLPolicy(Policy):
    def __init__(self, model, arrival: ArrivalInfo, name: str):
        self.model, self.arrival, self.name = model, arrival, name

    def reset(self, ep: Episode, ctx: Ctx) -> None:
        self.ep, self.ac_on = ep, True

    def act(self, o: Obs) -> str:
        q = self.arrival.quantiles(o.now_s, o.weekday, o.depart_tod, o.prev_arrive_tod)
        x = make_obs(o.now_s, o.depart_tod, o.temp_c, o.outdoor_c, o.lux, o.weekday, o.prev_arrive_tod, q, self.ac_on)
        a, _ = self.model.predict(x, deterministic=True)
        act = ACTIONS[int(a)]
        self.ac_on = act != "off"
        return act


# ---------------------------------------------------------------- 튜닝 · 학습

def sample_hp(space: dict, rng: np.random.Generator) -> dict:
    return {"lr_log10": float(rng.uniform(*space["lr_log10"])), "gamma": float(rng.uniform(*space["gamma"])),
            "exploration_fraction": float(rng.uniform(*space["exploration_fraction"])),
            "target_update": int(rng.integers(space["target_update"][0], space["target_update"][1] + 1)),
            "net": [int(v) for v in space["net"][int(rng.integers(len(space["net"])))]],
            "batch": int(rng.integers(space["batch"][0], space["batch"][1] + 1))}


def out_dir(ctx: Ctx, variant: str, persona: str, k: int | None) -> Path:
    return REPO / ctx.cfg["out_dir"] / f"m3{variant}_dqn" / (f"{persona}_k{k}" if variant == "a" else persona)


def learn(ctx: Ctx, variant: str, persona: str, k: int | None, hp: dict, seed: int):
    from stable_baselines3 import DQN
    env = LearnedSim(ctx, persona, k, seed) if variant == "a" else TruthSim(ctx, persona, seed)
    model = DQN("MlpPolicy", env, learning_rate=10 ** hp["lr_log10"], gamma=hp["gamma"], buffer_size=100_000,
                learning_starts=1000, batch_size=hp["batch"], train_freq=4, target_update_interval=hp["target_update"],
                exploration_fraction=hp["exploration_fraction"], exploration_final_eps=0.02,
                policy_kwargs={"net_arch": hp["net"]}, seed=seed, device="cpu", verbose=0)
    model.learn(total_timesteps=int(ctx.cfg["train"]["rl_steps"]))
    return model, env.arrival


def val_cost(ctx: Ctx, persona: str, k: int, model, arrival: ArrivalInfo) -> float:
    _, va = train_val_episodes(ctx, persona, k)
    wx = weather(ctx, "train")
    pol = RLPolicy(model, arrival, "rl")
    return float(np.mean([run_episode(ctx, ep, pol, wx)["cost"] for ep in va]))


def trial(variant: str, persona: str, k: int | None, i: int, hp: dict, seed: int, save: str | None) -> dict:
    torch.set_num_threads(1)
    ctx = Ctx.load()
    t0 = time.time()
    model, arrival = learn(ctx, variant, persona, k, hp, seed)
    t_train = time.time() - t0
    vk = k if variant == "a" else int(ctx.cfg["data"]["main_weeks"])
    t0 = time.time()
    c = val_cost(ctx, persona, vk, model, arrival)
    if save:
        model.save(save)
    return {"variant": variant, "persona": persona, "weeks": k if k is not None else -1, "trial": i, "seed": seed,
            **{kk: (json.dumps(v) if isinstance(v, list) else v) for kk, v in hp.items()},
            "val_cost": round(c, 2), "train_s": round(t_train, 1), "val_s": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["tune", "train"])
    ap.add_argument("--variant", choices=["a", "b"], required=True)
    ap.add_argument("--persona")
    ap.add_argument("--weeks", type=int)
    ap.add_argument("--workers", type=int)
    a = ap.parse_args()
    ctx = Ctx.load()
    tcfg = ctx.cfg["train"]
    ks = ([a.weeks] if a.weeks else ctx.cfg["data"]["weeks"]) if a.variant == "a" else [None]
    combos = [(p, k) for p in ([a.persona] if a.persona else ctx.cfg["personas"]) for k in ks]
    jobs = []
    for p, k in combos:
        od = out_dir(ctx, a.variant, p, k)
        od.mkdir(parents=True, exist_ok=True)
        if a.stage == "tune":
            rng = np.random.default_rng(int(tcfg["tuning_seed"]) + 1000 * ctx.cfg["personas"].index(p) + (k or 0)
                                        + (500 if a.variant == "b" else 300))
            jobs += [(a.variant, p, k, i, sample_hp(ctx.cfg["dqn_space"], rng), int(tcfg["tuning_seed"]) + i, None)
                     for i in range(int(tcfg["tuning_trials"]))]
        else:
            hp = json.loads((od / "selected.json").read_text(encoding="utf-8"))["hp"]
            jobs += [(a.variant, p, k, 100 + s, hp, s, str(od / f"seed{s}")) for s in tcfg["seeds"]]
    rows = []
    with ProcessPoolExecutor(a.workers or int(ctx.cfg["workers"])) as ex:
        for r in ex.map(trial, *zip(*jobs)):
            rows.append(r)
            print(r, flush=True)
    df = pd.DataFrame(rows)
    for (p, k), g in df.groupby(["persona", "weeks"]):
        od = out_dir(ctx, a.variant, p, None if k == -1 else int(k))
        g.to_csv(od / f"{a.stage}.csv", index=False)
        if a.stage == "tune":
            b = g.sort_values("val_cost").iloc[0]
            hp = {"lr_log10": float(b.lr_log10), "gamma": float(b.gamma), "exploration_fraction": float(b.exploration_fraction),
                  "target_update": int(b.target_update), "net": json.loads(b.net), "batch": int(b.batch)}
            (od / "selected.json").write_text(json.dumps({"hp": hp, "val_cost": float(b.val_cost), "trial": int(b.trial)},
                                                         ensure_ascii=False), encoding="utf-8")


def load_policy(ctx: Ctx, variant: str, persona: str, k: int | None, seed: int) -> RLPolicy:
    from stable_baselines3 import DQN
    model = DQN.load(str(out_dir(ctx, variant, persona, k) / f"seed{seed}"), device="cpu")
    kk = k if variant == "a" else int(ctx.cfg["data"]["main_weeks"])
    return RLPolicy(model, ArrivalInfo(data_dir(ctx, persona, kk)), f"m3{variant}_dqn")


if __name__ == "__main__":
    main()
