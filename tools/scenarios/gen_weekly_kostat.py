"""귀가 분포 보정 민감도 시나리오 K1–K6 (docs/15 §16) — 평일 귀가 시각을 통계청 2024 분포에서 뽑은 1주 시나리오 (실행 전 생성 · 등록).

    uv run python tools/scenarios/gen_weekly_kostat.py    # → config/scenarios_weekly_kostat.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tools" / "energy"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_weekly_v133 as G  # noqa: E402
from harness.runner import load_harness_config  # noqa: E402
from timeuse_calibration import kostat_arrivals  # noqa: E402

BUILD = [("기본 원룸", {}), ("노후 원룸", G.OLD), ("가벼운 노후 원룸", G.LIGHT)]
WEATHER = [(2.0, -6.0), (0.0, -9.0), (4.0, -3.0)]


def hhmm(h: float) -> str:
    m = int(round(h * 60))
    return f"{m // 60:02d}:{m % 60:02d}"


def main() -> None:
    c = load_harness_config()["timeuse_calibration"]
    sc = []
    for i in range(6):
        rng = np.random.default_rng(20263400 + i)
        k, _ = kostat_arrivals(c, rng)
        arr = [a for a in k if 16.5 <= a < 22.5][:5]                    # 출근자 — 16:30 전 귀가 · 22:30 이후는 제외
        leave = rng.uniform(7.5, 8.5, 5)
        plan = {d: (hhmm(leave[d]), hhmm(arr[d])) for d in range(5)}
        bname, env = BUILD[i % 3]
        td, tn = WEATHER[i % 3]
        s = G.build(f"K{i + 1}", f"평일 귀가 = 통계청 2024 분포 표본 ({', '.join(hhmm(a) for a in arr)}) · 주말 재택 — {bname}",
                    0, plan, env, td, tn, 20263400 + i)
        sc.append(s)
    out = REPO / "config" / "scenarios_weekly_kostat.yaml"
    head = ("# ============================================================================\n"
            "#  귀가 분포 보정 민감도 K1–K6 (docs/15 §16) — tools/scenarios/gen_weekly_kostat.py 가 만든다 (손으로 고치지 않는다)\n"
            "#  평일 귀가 = 통계청 2024 생활시간조사 분포 (data/timeuse) · 실행 전 생성 · 등록\n"
            "# ============================================================================\n")
    out.write_text(head + yaml.safe_dump({"scenarios": sc}, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    for s in sc:
        print(s["id"], s["name"])


if __name__ == "__main__":
    main()
