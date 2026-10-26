"""EXP-5 평가 — 방식 동결(docs/13 §9 4단계) 뒤 한 번만 돌린다.

평가 에피소드(평가 전용 시드 · 2024 기상 · 조건 3)에서 모든 방식 · 학습 k · 시드를 참값 환경으로 돌린다.
    기준 정책  always_setback · always_off · oracle
    ①         m1_model  (k 마다 · 결정론)
    ②         m2_lstm   (k × 시드 5)
    ③a        m3a_dqn   (k × 시드 5)
    ③b        m3b_dqn   (시드 5 · k 없음)
결과: results/exp5/eval/episodes.csv (에피소드 한 줄 · 원시 기록은 커밋하지 않는다)

    uv run python tools/exp5/evaluate.py --confirm-frozen
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exp5.common import REPO, Ctx, Fixed, eval_episodes, oracle, run_episode, weather  # noqa: E402
from exp5.data import data_dir  # noqa: E402


def policy(ctx: Ctx, method: str, persona: str, k: int, seed: int):
    if method in ("always_setback", "always_off"):
        return Fixed(method.split("_")[1])
    if method == "m1_model":
        from exp5.policies import PlannerPolicy
        return PlannerPolicy(ctx, data_dir(ctx, persona, k))
    if method == "m2_lstm":
        from exp5 import lstm
        return lstm.load_policy(ctx, persona, k, seed)
    from exp5 import rl
    return rl.load_policy(ctx, "a" if method == "m3a_dqn" else "b", persona, k if method == "m3a_dqn" else None, seed)


def job(method: str, persona: str, k: int, seed: int, cond: str) -> list[dict]:
    import torch
    torch.set_num_threads(1)
    ctx = Ctx.load()
    eps = eval_episodes(ctx, persona, cond)
    wx = weather(ctx, "eval")
    rows = []
    pol = None if method == "oracle" else policy(ctx, method, persona, k, seed)
    for ep in eps:
        t0 = time.time()
        r = oracle(ctx, ep, wx) if method == "oracle" else run_episode(ctx, ep, pol, wx)
        rows.append({"method": method, "weeks": k, "seed": seed, **r, "sec": round(time.time() - t0, 2)})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm-frozen", action="store_true", help="docs/13 §11 에 방식 동결을 기록했다")
    ap.add_argument("--only", help="쉼표로 구분한 방식만 (재실행용)")
    a = ap.parse_args()
    if not a.confirm_frozen:
        sys.exit("방식 동결(docs/13 §9 4단계) 뒤에만 실행한다 — --confirm-frozen")
    ctx = Ctx.load()
    seeds = list(ctx.cfg["train"]["seeds"])
    ks = list(ctx.cfg["data"]["weeks"])
    jobs = []
    for p in ctx.cfg["personas"]:
        for c in ctx.cfg["eval"]["conditions"]:
            jobs += [(m, p, -1, -1, c) for m in ("always_setback", "always_off", "oracle")]
            jobs += [("m1_model", p, k, -1, c) for k in ks]
            jobs += [(m, p, k, s, c) for m in ("m2_lstm", "m3a_dqn") for k in ks for s in seeds]
            jobs += [("m3b_dqn", p, -1, s, c) for s in seeds]
    if a.only:
        keep = set(a.only.split(","))
        jobs = [j for j in jobs if j[0] in keep]
    out = REPO / ctx.cfg["out_dir"] / "eval"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with ProcessPoolExecutor(int(ctx.cfg["workers"])) as ex:
        for i, rs in enumerate(ex.map(job, *zip(*jobs))):
            rows += rs
            if (i + 1) % 20 == 0:
                print(f"{i + 1}/{len(jobs)}", flush=True)
    name = "episodes.csv" if not a.only else f"episodes_{a.only.replace(',', '_')}.csv"
    pd.DataFrame(rows).to_csv(out / name, index=False)
    print(f"저장: {(out / name).relative_to(REPO)} · {len(rows)}행")


if __name__ == "__main__":
    main()
