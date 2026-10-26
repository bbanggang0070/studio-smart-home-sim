"""EXP-5 방식 ② — LSTM 열 모델 + v1.29 와 같은 기대비용 최적화 (docs/13 §3 · §6).

열 모델만 바꾼다: 2R2C 대신 LSTM 이 다음 5분 실내 온도 변화를 예측하고, 계획기는 같은 후보(셋백 · 끄기 · 프리쿨링 격자) ·
같은 귀가 분포 · 같은 비용식 · 같은 에어컨 명판 근사로 고른다 (후보 × 귀가 분위를 한 번에 굴린다 — 결과는 같은 정의).

학습 — 운전 기록(2R2C 식별과 같은 데이터)에서 창 W 를 관측값으로 데운 뒤 H 스텝을 자기 예측으로 굴려 오차를 줄인다
(2R2C 식별의 '시뮬레이션 오차 최소제곱'과 같은 목표). 기록의 마지막 15 % 로 조기 종료.
선택 — 무작위 탐색 tuning_trials 회 · 검증 2주 에피소드의 참값 비용 평균이 가장 낮은 설정 (평가 집합은 쓰지 않는다).

    uv run python tools/exp5/lstm.py tune  [--persona P] [--weeks K]     # 튜닝 → 선택 설정
    uv run python tools/exp5/lstm.py train [--persona P] [--weeks K]     # 선택 설정으로 시드 5개 학습
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exp5.common import REPO, Ctx, Obs, run_episode, train_val_episodes, weather  # noqa: E402
from exp5.data import data_dir  # noqa: E402
from exp5.policies import PlannerPolicy  # noqa: E402

from controller.energy import EnergyPlanner  # noqa: E402

N_IN = 5                                  # 실내 · 외기 · 주광 · 재실 · 에어컨 전력
HOLDOUT = 0.15
EPOCH_BATCHES = 20
ROLL_H = 12.0                             # 학습 때 자기회귀로 굴리는 길이 [h]


class ThermalLSTM(nn.Module):
    def __init__(self, hidden: int, dropout: float, mean: np.ndarray, std: np.ndarray, dt_s: float):
        super().__init__()
        self.cell = nn.LSTMCell(N_IN, hidden)
        self.drop = nn.Dropout(dropout)
        self.head = nn.Linear(hidden, 1)
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32))
        self.register_buffer("std", torch.tensor(std, dtype=torch.float32))
        self.hidden, self.dt_s = hidden, dt_s

    def step(self, x: torch.Tensor, hc):
        """x [B, 5] (원 단위) → (다음 실내 온도 [B], 상태)."""
        h, c = self.cell((x - self.mean) / self.std, hc)
        return x[:, 0] + self.head(self.drop(h)).squeeze(-1), (h, c)

    def zero(self, b: int):
        z = torch.zeros(b, self.hidden)
        return (z, z.clone())


def _features(rec) -> np.ndarray:
    return np.stack([rec["t"], rec["to"], rec["lux"], rec["occ"], rec["ac_w"]], axis=1).astype(np.float32)


def train_lstm(log: dict, hp: dict, seed: int, max_epochs: int, patience: int) -> tuple[ThermalLSTM, float]:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    x = _features(log)
    dt_s = 300.0                                          # 운전 기록 간격 (data.log_dt_s)
    w = int(round(hp["window_h"] * 3600 / dt_s))
    hz = int(round(ROLL_H * 3600 / dt_s))
    n = len(x)
    cut = int(n * (1 - HOLDOUT))
    hz = min(hz, max(12, cut // 3 - w))
    m = ThermalLSTM(int(hp["hidden"]), float(hp["dropout"]), x[:cut].mean(0), x[:cut].std(0) + 1e-6, dt_s)
    opt = torch.optim.Adam(m.parameters(), lr=10 ** hp["lr_log10"])
    xt = torch.tensor(x)

    def batch_loss(starts: np.ndarray, train: bool) -> torch.Tensor:
        idx = torch.tensor(starts)[:, None] + torch.arange(w + hz)[None, :]
        seq = xt[idx]                                      # [B, w+hz, 5]
        hc = m.zero(len(starts))
        for i in range(w):                                 # 관측값으로 데우기
            _, hc = m.step(seq[:, i], hc)
        t = seq[:, w, 0]
        loss = 0.0
        for i in range(w, w + hz - 1):                     # 자기 예측으로 굴리기
            inp = seq[:, i].clone()
            inp[:, 0] = t
            t, hc = m.step(inp, hc)
            loss = loss + ((t - seq[:, i + 1, 0]) ** 2).mean()
        return loss / (hz - 1)

    hi_tr = cut - (w + hz)
    hi_va = n - (w + hz)
    va_starts = np.linspace(cut, max(cut, hi_va), num=min(32, max(1, hi_va - cut + 1))).astype(int) if hi_va > cut else \
        np.array([max(0, n - (w + hz))])
    best, best_state, bad = math.inf, None, 0
    bs = int(hp["batch"])
    for ep in range(max_epochs):
        m.train()
        for _ in range(EPOCH_BATCHES):
            loss = batch_loss(rng.integers(0, max(1, hi_tr), size=bs), True)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(m.parameters(), 1.0)
            opt.step()
        m.eval()
        with torch.no_grad():
            v = float(batch_loss(va_starts, False))
        if v < best - 1e-5:
            best, bad = v, 0
            best_state = {k: t.clone() for k, t in m.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    m.load_state_dict(best_state)
    m.eval()
    return m, math.sqrt(best)


class LSTMPlanner(EnergyPlanner):
    """EnergyPlanner 와 같은 후보 · 비용 · 선택 — 열 예측만 LSTM (후보 × 귀가 분위를 한 번에 굴린다)."""

    def __init__(self, p, model_file, comfort_weight, strategy="auto", lstm: ThermalLSTM | None = None, window: int = 12):
        super().__init__(p, model_file, comfort_weight, strategy)
        self.lstm, self.window = lstm, window
        self.hist: list[list[float]] = []
        self._acc = 0.0

    def reset(self) -> None:
        super().reset()
        self.hist, self._acc = [], math.inf

    def observe(self, t_meas, t_out, lux, occ, ac_w, dt_s) -> None:
        super().observe(t_meas, t_out, lux, occ, ac_w, dt_s)
        self._acc += dt_s
        if self._acc >= self.dt_s - 1e-6:                  # 계획 보폭(300 s)마다 한 칸
            self._acc = 0.0
            self.hist.append([t_meas, t_out, lux, occ, ac_w])
            self.hist = self.hist[-self.window:]

    @torch.no_grad()
    def _batch(self, now_tod, t0, t_out, lux_fn, sp, starts, setbacks, arrives):
        m, ac = self.lstm, self.ac
        b = len(starts)
        hc = m.zero(1)
        for row in self.hist[:-1]:
            _, hc = m.step(torch.tensor([row], dtype=torch.float32), hc)
        hc = (hc[0].expand(b, -1).contiguous(), hc[1].expand(b, -1).contiguous())
        t = torch.full((b,), float(t0))
        st = torch.tensor(starts, dtype=torch.float32)
        sb = torch.tensor(setbacks)
        arr = torch.tensor(arrives, dtype=torch.float32)
        end = arr + self.horizon_after_s
        e = torch.zeros(b)
        d = torch.zeros(b)
        dt_h = self.dt_s / 3600.0
        tod = now_tod
        tmax = float(end.max())
        while tod < tmax:
            live = tod < end
            home = tod >= arr
            cool = home | (tod >= st)
            spe = torch.where(cool, torch.tensor(sp), torch.where(sb, torch.tensor(sp + self.setback_c), torch.tensor(math.inf)))
            q = torch.where(t < spe - ac.band_c, torch.zeros(b), torch.clamp(ac.modulation_w_per_k * (t - spe + ac.band_c), max=ac.capacity_w))
            q = torch.where(torch.isfinite(spe), q, torch.zeros(b))
            e += torch.where(live, q / ac.cop * dt_h, torch.zeros(b))
            d += torch.where(live & home, torch.clamp(t - (sp + self.margin), min=0.0) * dt_h, torch.zeros(b))
            x = torch.stack([t, torch.full((b,), float(t_out)), torch.full((b,), float(lux_fn(tod))), home.float(), q / ac.cop], 1)
            t, hc = m.step(x, hc)
            tod += self.dt_s
        return e.numpy(), d.numpy()

    def plan(self, now_tod, t_out, lux_fn, sp):
        arr = self._arrival_samples(now_tod)
        qs = np.quantile(arr, np.linspace(0.05, 0.95, 10))
        specs = [("setback", None), ("off", None)]
        tod = now_tod
        while tod <= float(np.quantile(arr, 0.9)):
            specs.append(("precool", tod))
            tod += self.grid_s
        starts, sbs, arrs = [], [], []
        for kind, s in specs:
            for a in qs:
                starts.append(math.inf if s is None else s)
                sbs.append(kind == "setback")
                arrs.append(a)
        e, d = self._batch(now_tod, self.t_hat, t_out, lux_fn, sp, starts, sbs, arrs)
        e, d = e.reshape(len(specs), len(qs)).mean(1), d.reshape(len(specs), len(qs)).mean(1)
        cands = [(k, s, float(ei + self.lam * self.w * di), float(ei), float(di)) for (k, s), ei, di in zip(specs, e, d)]
        allowed = {"auto": ("setback", "off", "precool"), "setback": ("setback",), "off": ("off",),
                   "precool": ("precool",)}[self.strategy_setting]
        best = min((x for x in cands if x[0] in allowed), key=lambda x: x[2])
        prev = self.decision.get("strategy")
        if prev and prev != best[0] and prev in allowed:
            keep = min((x for x in cands if x[0] == prev), key=lambda x: x[2])
            if keep[2] - best[2] < self.switch_margin:
                best = keep
        self.decision = {"strategy": best[0], "start_tod": best[1], "cost": round(best[2], 1),
                         "arrival_q20": float(np.quantile(arr, 0.2)), "arrival_q50": float(np.quantile(arr, 0.5)),
                         "arrival_q80": float(np.quantile(arr, 0.8)), "arrival_model": self.arrival_model}
        return self.decision


class LSTMPolicy(PlannerPolicy):
    name = "m2_lstm"

    def __init__(self, ctx: Ctx, data: Path, lstm: ThermalLSTM, window: int):
        super().__init__(ctx, data, planner_cls=LSTMPlanner, lstm=lstm, window=window)


# ---------------------------------------------------------------- 튜닝 · 학습

def sample_hp(space: dict, rng: np.random.Generator) -> dict:
    return {"hidden": int(rng.choice(space["hidden"])), "window_h": float(rng.choice(space["window_h"])),
            "lr_log10": float(rng.uniform(*space["lr_log10"])), "dropout": float(rng.uniform(*space["dropout"])),
            "batch": int(rng.integers(space["batch"][0], space["batch"][1] + 1))}


def out_dir(ctx: Ctx, persona: str, k: int) -> Path:
    return REPO / ctx.cfg["out_dir"] / "m2_lstm" / f"{persona}_k{k}"


def val_cost(ctx: Ctx, persona: str, k: int, m: ThermalLSTM, window: int) -> float:
    _, va = train_val_episodes(ctx, persona, k)
    wx = weather(ctx, "train")
    pol = LSTMPolicy(ctx, data_dir(ctx, persona, k), m, window)
    return float(np.mean([run_episode(ctx, ep, pol, wx)["cost"] for ep in va]))


def trial(persona: str, k: int, i: int, hp: dict, seed: int) -> dict:
    torch.set_num_threads(1)
    ctx = Ctx.load()
    log = dict(np.load(data_dir(ctx, persona, k) / "log.npz"))
    t0 = time.time()
    m, rmse = train_lstm(log, hp, seed, int(ctx.cfg["train"]["lstm_max_epochs"]), int(ctx.cfg["train"]["lstm_patience"]))
    t_train = time.time() - t0
    w = int(round(hp["window_h"] * 3600 / 300.0))
    t0 = time.time()
    c = val_cost(ctx, persona, k, m, w)
    return {"persona": persona, "weeks": k, "trial": i, "seed": seed, **hp, "holdout_rmse_c": round(rmse, 4),
            "val_cost": round(c, 2), "train_s": round(t_train, 1), "val_s": round(time.time() - t0, 1), "_model": m.state_dict()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["tune", "train"])
    ap.add_argument("--persona")
    ap.add_argument("--weeks", type=int)
    a = ap.parse_args()
    ctx = Ctx.load()
    tcfg = ctx.cfg["train"]
    combos = [(p, k) for p in ([a.persona] if a.persona else ctx.cfg["personas"])
              for k in ([a.weeks] if a.weeks else ctx.cfg["data"]["weeks"])]
    jobs = []
    for p, k in combos:
        od = out_dir(ctx, p, k)
        od.mkdir(parents=True, exist_ok=True)
        if a.stage == "tune":
            rng = np.random.default_rng(int(tcfg["tuning_seed"]) + 1000 * ctx.cfg["personas"].index(p) + k)
            jobs += [(p, k, i, sample_hp(ctx.cfg["lstm_space"], rng), int(tcfg["tuning_seed"]) + i)
                     for i in range(int(tcfg["tuning_trials"]))]
        else:
            hp = json.loads((od / "selected.json").read_text(encoding="utf-8"))["hp"]
            jobs += [(p, k, 100 + s, hp, s) for s in tcfg["seeds"]]
    rows = []
    with ProcessPoolExecutor(int(ctx.cfg["workers"])) as ex:
        for r in ex.map(trial, *zip(*jobs)):
            state = r.pop("_model")
            od = out_dir(ctx, r["persona"], r["weeks"])
            if a.stage == "train":
                torch.save({"state": state, "hp": {k: r[k] for k in ("hidden", "window_h", "lr_log10", "dropout", "batch")}},
                           od / f"seed{r['seed']}.pt")
            rows.append(r)
            print({k: v for k, v in r.items()}, flush=True)
    import pandas as pd
    df = pd.DataFrame(rows)
    for (p, k), g in df.groupby(["persona", "weeks"]):
        od = out_dir(ctx, p, k)
        g.to_csv(od / f"{a.stage}.csv", index=False)
        if a.stage == "tune":
            b = g.sort_values("val_cost").iloc[0]
            hp = {kk: (int(b[kk]) if kk in ("hidden", "batch") else float(b[kk]))
                  for kk in ("hidden", "window_h", "lr_log10", "dropout", "batch")}
            (od / "selected.json").write_text(json.dumps({"hp": hp, "val_cost": float(b.val_cost), "trial": int(b.trial)},
                                                         ensure_ascii=False), encoding="utf-8")


def load_policy(ctx: Ctx, persona: str, k: int, seed: int) -> LSTMPolicy:
    ck = torch.load(out_dir(ctx, persona, k) / f"seed{seed}.pt", weights_only=False)
    hp = ck["hp"]
    log = dict(np.load(data_dir(ctx, persona, k) / "log.npz"))
    x = _features(log)
    cut = int(len(x) * (1 - HOLDOUT))
    m = ThermalLSTM(hp["hidden"], hp["dropout"], x[:cut].mean(0), x[:cut].std(0) + 1e-6, 300.0)
    m.load_state_dict(ck["state"])
    m.eval()
    return LSTMPolicy(ctx, data_dir(ctx, persona, k), m, int(round(hp["window_h"] * 12)))


if __name__ == "__main__":
    main()
