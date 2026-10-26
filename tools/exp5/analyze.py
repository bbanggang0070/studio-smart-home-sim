"""EXP-5 분석 — 사전 등록 docs/13 §7 의 규칙 그대로.

주 지표  에피소드 비용의 짝 비 (방식 / ①) 중앙값 · 같은 에피소드 · 같은 조건 · 같은 k
         학습 방식의 에피소드 비용 = 시드 5개 평균 (docs/13 §10 — 평가 전 기록)
주 비교  k = main_weeks · 조건 3 · 페르소나 3 합침 — ② / ① · ③a / ① · ③b / ①
구간     (페르소나 × 평가 주) 묶음 부트스트랩 95 % · 검정 = 에피소드 짝 부호 검정 + Holm (3개)
판정     상한 < 1 · p_holm < 0.05 → '① 보다 낫다' · 하한 > 1 · p_holm < 0.05 → '① 보다 못하다' · 그 외 → '차이를 확인하지 못함'

    uv run python tools/exp5/analyze.py [results/exp5/eval/episodes.csv]
결과: results/exp5/tables/*.md · *.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exp5.common import REPO, load_cfg  # noqa: E402

KEY = ["persona", "cond", "idx"]
LEARNED = ("m2_lstm", "m3a_dqn", "m3b_dqn")
NAMES = {"m1_model": "① 질문별 모델", "m2_lstm": "② LSTM", "m3a_dqn": "③a 데이터 RL", "m3b_dqn": "③b 시뮬레이터 RL",
         "always_setback": "언제나 셋백", "always_off": "언제나 끄기", "oracle": "오라클"}


def per_episode(df: pd.DataFrame) -> pd.DataFrame:
    """방식 · k · 에피소드 → 비용 (학습 방식은 시드 평균)."""
    cols = ["cost", "energy_wh", "discomfort_kh", "arrive_ok", "overrides"]
    g = df.groupby(["method", "weeks", *KEY, "week", "away_h"], as_index=False)[cols].mean()
    return g


def paired(ep: pd.DataFrame, method: str, k: int, ref_k: int) -> pd.DataFrame:
    """method(k) 와 ①(ref_k) 의 같은 에피소드 짝. ③b · 기준 정책은 k 가 없다(-1)."""
    a = ep[(ep.method == method) & (ep.weeks == (k if method in ("m2_lstm", "m3a_dqn", "m1_model") else -1))]
    b = ep[(ep.method == "m1_model") & (ep.weeks == ref_k)]
    m = a.merge(b, on=[*KEY, "week", "away_h"], suffixes=("", "_ref"))
    m["ratio"] = m.cost / m.cost_ref
    m["cluster"] = m.persona + "|" + m.week.astype(str)
    return m


def boot_median(m: pd.DataFrame, n: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    groups = [g.ratio.to_numpy() for _, g in m.groupby("cluster")]
    stats = np.empty(n)
    for i in range(n):
        pick = rng.integers(len(groups), size=len(groups))
        stats[i] = np.median(np.concatenate([groups[j] for j in pick]))
    return float(np.quantile(stats, 0.025)), float(np.quantile(stats, 0.975))


def sign_p(m: pd.DataFrame) -> float:
    d = m.cost - m.cost_ref
    pos, neg = int((d > 1e-9).sum()), int((d < -1e-9).sum())
    return float(binomtest(neg, pos + neg, 0.5).pvalue) if pos + neg else 1.0


def holm(ps: list[float]) -> list[float]:
    order = np.argsort(ps)
    out = [0.0] * len(ps)
    run = 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - r) * ps[i]))
        out[i] = run
    return out


def verdict(lo: float, hi: float, p: float) -> str:
    if hi < 1.0 and p < 0.05:
        return "① 보다 낫다"
    if lo > 1.0 and p < 0.05:
        return "① 보다 못하다"
    return "차이를 확인하지 못함"


def main() -> None:
    cfg = load_cfg()
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / cfg["out_dir"] / "eval" / "episodes.csv"
    df = pd.read_csv(src)
    ep = per_episode(df)
    km = int(cfg["data"]["main_weeks"])
    nb, bs = int(cfg["eval"]["bootstrap"]), int(cfg["eval"]["bootstrap_seed"])
    out = REPO / cfg["out_dir"] / "tables"
    out.mkdir(parents=True, exist_ok=True)

    # 주 비교
    rows = []
    for meth in LEARNED:
        m = paired(ep, meth, km, km)
        lo, hi = boot_median(m, nb, bs)
        rows.append({"비교": f"{NAMES[meth]} / ①", "에피소드": len(m), "비 중앙값": float(np.median(m.ratio)), "하한": lo, "상한": hi,
                     "더 쌈": int((m.cost < m.cost_ref - 1e-9).sum()), "더 비쌈": int((m.cost > m.cost_ref + 1e-9).sum()),
                     "p": sign_p(m)})
    for r, ph in zip(rows, holm([r["p"] for r in rows])):
        r["p_holm"] = ph
        r["판정"] = verdict(r["하한"], r["상한"], ph)
    main_t = pd.DataFrame(rows)
    main_t.to_csv(out / "exp5_primary.csv", index=False)

    # 부 지표 — 방식 · k · 조건별 평균 · ① 대비 비 · 오라클 대비 후회
    orc = ep[ep.method == "oracle"][[*KEY, "cost"]].rename(columns={"cost": "oracle"})
    e2 = ep.merge(orc, on=KEY)
    e2["regret"] = e2.cost - e2.oracle
    sec = (e2.groupby(["method", "weeks", "cond"])
           .agg(n=("cost", "size"), cost=("cost", "mean"), energy_wh=("energy_wh", "mean"), discomfort_kh=("discomfort_kh", "mean"),
                arrive_ok=("arrive_ok", "mean"), regret=("regret", "mean"), overrides=("overrides", "sum")).reset_index())
    sec.to_csv(out / "exp5_secondary.csv", index=False)
    curve = []
    for meth in ("m2_lstm", "m3a_dqn"):
        for k in cfg["data"]["weeks"]:
            m = paired(ep, meth, k, k)
            if len(m):
                lo, hi = boot_median(m, 2000, bs)
                curve.append({"방식": NAMES[meth], "k": k, "비 중앙값": float(np.median(m.ratio)), "하한": lo, "상한": hi})
    pd.DataFrame(curve).to_csv(out / "exp5_data_curve.csv", index=False)

    lines = ["# EXP-5 결과 — 사전 등록 docs/13", "", f"원자료: `{src.relative_to(REPO) if src.is_relative_to(REPO) else src}`", "",
             f"## 주 비교 (k = {km}주 · 조건 3 · 페르소나 3 합침 · 비 = 방식 / ① 의 에피소드 비용 · 묶음 부트스트랩 95 % · Holm)", "",
             "| 비교 | 에피소드 | 비 중앙값 [95 %] | 더 쌈 · 더 비쌈 | p_holm | 판정 |", "|---|---:|---|---|---:|---|"]
    for _, r in main_t.iterrows():
        lines.append(f"| {r['비교']} | {r['에피소드']} | {r['비 중앙값']:.3f} [{r['하한']:.3f}, {r['상한']:.3f}] | "
                     f"{r['더 쌈']} · {r['더 비쌈']} | {r['p_holm']:.3g} | {r['판정']} |")
    lines += ["", "## 부 지표 — 평균 비용 · 후회(오라클 대비) · 귀가 도달률 (판정 없음)", "",
              "| 방식 | k | 조건 | n | 비용 | 전력량 Wh | 불쾌 K·h | 귀가 도달 | 후회 |", "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for _, r in sec.sort_values(["method", "weeks", "cond"]).iterrows():
        lines.append(f"| {NAMES.get(r.method, r.method)} | {r.weeks if r.weeks >= 0 else '-'} | {r.cond} | {r.n} | {r.cost:.1f} | "
                     f"{r.energy_wh:.1f} | {r.discomfort_kh:.3f} | {r.arrive_ok:.2f} | {r.regret:.1f} |")
    lines += ["", "## 데이터 양 곡선 — 같은 k 의 ① 대비 비 (판정 없음)", "", "| 방식 | k | 비 중앙값 [95 %] |", "|---|---:|---|"]
    for r in curve:
        lines.append(f"| {r['방식']} | {r['k']} | {r['비 중앙값']:.3f} [{r['하한']:.3f}, {r['상한']:.3f}] |")
    (out / "exp5_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    main()
