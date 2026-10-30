"""공개 생활시간 통계로 귀가 분포 점검 (docs/11 권장 9 · 2026-10-30) — 통계청 2024 생활시간조사 vs 우리 출근자 페르소나.

    uv run python tools/energy/timeuse_calibration.py      # → 화면 + results/tables/timeuse_calibration.md
    uv run python tools/energy/timeuse_calibration.py --write-model   # + models/energy_commuter_kostat.yaml (귀가 이력만 통계 표본 · docs/15 §16)

통계 → 귀가 분포: 취업자 중 일한 사람 비율(평일 30분)의 오후 감소 = 퇴근 · 퇴근 + 편도 통근(평균 45분 ± 15분) = 귀가
  (21:30 이후에도 일하는 비율(야근 · 야간 근무)은 '22시 이후' 로 따로 센다 — 출근자 페르소나 비교는 22시까지의 조건부 분포로)
비교 대상: ① 학습 페르소나 personas.commuter (정규 + 늦는 날) ② 마르코프 재실 생성기 commuter 평일 주 귀가 ③ 제어기 귀가 이력 (models/energy_commuter.yaml)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import ks_2samp

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from harness.occupancy_gen import absences, generate  # noqa: E402
from harness.runner import load_harness_config  # noqa: E402


def hm(s: str) -> float:
    h, m = s.split(":")
    return int(h) + int(m) / 60.0


def kostat_arrivals(c: dict, rng: np.random.Generator) -> tuple[np.ndarray, float]:
    d = pd.read_csv(REPO / c["work_share_file"], comment="#")
    t = d["time"].map(hm).to_numpy()
    share = d[c["column"]].to_numpy(float)
    p0, p1 = (hm(x) for x in c["plateau"])
    plateau = share[(t >= p0) & (t <= p1)].mean()
    m = t >= hm(c["end_from"])
    tt, surv = t[m], np.minimum(share[m] / plateau, 1.0)
    surv = np.concatenate([[1.0], surv[1:]])                          # 기준 시각 = 아직 모두 일함
    drop = np.clip(-np.diff(surv), 0.0, None)                         # 30분 구간마다 퇴근한 비율
    after = float(surv[-1])                                           # 21:30 이후에도 일함 (야근 · 야간)
    mids = tt[:-1] + 0.25
    n = int(c["samples"])
    end = rng.choice(mids, size=n, p=drop / drop.sum()) + rng.uniform(-0.25, 0.25, n)
    arr = end + rng.normal(c["commute_one_way_min"], c["commute_sd_min"], n) / 60.0
    return arr, after


def write_model(hcfg: dict, c: dict) -> None:
    """제어기 모델 파일 사본 — 귀가 이력(arrival_history_tod_s)만 통계 분포 표본으로 (개수 · 22시 이전 · 열 모델 그대로)."""
    base = REPO / hcfg_model(hcfg)
    m = yaml.safe_load(open(base, encoding="utf-8"))
    n = len(m["arrival_history_tod_s"])
    k, _ = kostat_arrivals(c, np.random.default_rng(int(c["seed"]) + 1))
    k = k[k < 22.0][:n]
    m["arrival_history_tod_s"] = [round(float(v) * 3600.0, 1) for v in k]
    m["arrival_history_source"] = f"통계청 2024 생활시간조사 표본 {n}개 (tools/energy/timeuse_calibration.py --write-model · {c['work_share_file']}) · 열 모델은 {base.name} 그대로"
    out = REPO / "models" / "energy_commuter_kostat.yaml"
    out.write_text("# docs/15 §16 민감도 — 귀가 이력만 통계 표본 (기본 모델은 바꾸지 않는다)\n" + yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"{out.relative_to(REPO)} · 귀가 표본 {n}개")


def main() -> None:
    hcfg = load_harness_config()
    if "--write-model" in sys.argv:
        write_model(hcfg, hcfg["timeuse_calibration"])
    c = hcfg["timeuse_calibration"]
    rng = np.random.default_rng(int(c["seed"]))
    k, after = kostat_arrivals(c, rng)
    p = hcfg["personas"]["commuter"]
    n = int(c["samples"])
    late = rng.random(n) < p["late_probability"]
    a1 = hm(p["arrival_mean"]) + rng.normal(0.0, p["arrival_sd_min"], n) / 60.0 + late * p["late_shift_min"] / 60.0
    og = hcfg["occupancy_generator"]
    occ, types = generate(og, "commuter")
    a2 = np.array([a.arrive_tod_s / 3600.0 for a in absences(occ, types, og) if a.weekday < 5 and a.arrive_tod_s < 86400])
    m = yaml.safe_load(open(REPO / hcfg_model(hcfg), encoding="utf-8"))
    a3 = np.asarray(m["arrival_history_tod_s"], float) / 3600.0
    rows = []
    for name, x in (("통계청 2024 (퇴근 + 통근)", k), ("① 학습 페르소나 (정규 + 늦는 날)", a1),
                    ("② 마르코프 생성기 (평일 주 귀가)", a2), ("③ 제어기 귀가 이력 (경험 분포)", a3)):
        x = x[x < 24.0]
        q = np.quantile(x, [0.1, 0.25, 0.5, 0.75, 0.9])
        ks = ks_2samp(x, k).statistic if x is not k else 0.0
        rows.append((name, len(x), *[f"{int(v)}:{int(round(v % 1 * 60)):02d}" for v in q], f"{np.mean(x >= 21.0) * 100:.0f} %", f"{ks:.2f}"))
    lines = ["# 귀가 시각 분포 — 통계청 2024 생활시간조사 vs 출근자 페르소나 (평일)", "",
             f"통계: 취업자 일한 사람 비율 오후 감소 + 편도 통근 {c['commute_one_way_min']:.0f} ± {c['commute_sd_min']:.0f} 분 · "
             f"21:30 이후에도 일하는 비율 {after * 100:.0f} % 는 제외(야근 · 야간 근무)", "",
             "| 분포 | n | 10 % | 25 % | 중앙 | 75 % | 90 % | 21시 이후 | KS 거리 (통계 대비) |",
             "|---|---:|---|---|---|---|---|---:|---:|"]
    lines += [f"| {r[0]} | {r[1]} | " + " | ".join(r[2:]) + " |" for r in rows]
    out = REPO / "results" / "tables" / "timeuse_calibration.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def hcfg_model(hcfg: dict) -> str:
    from controller.params import load_params
    return load_params().get("energy.learned_model_file")


if __name__ == "__main__":
    main()
