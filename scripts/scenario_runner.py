"""실험 자동화 하네스 CLI (docs/03 §8 · W08 T8.v6 · W10 T10.9–T10.15).

예)
  uv run python scripts/scenario_runner.py --mode fast --list
  uv run python scripts/scenario_runner.py --mode fast --scenarios B6,C9 --controller hold --reps 1
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import criteria as C  # noqa: E402
from harness.manifest import write_manifest  # noqa: E402
from harness.runner import REPO, load_harness_config, run_batch  # noqa: E402
from harness.scenario import expand_runs, load_scenarios  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="원룸 스마트홈 시나리오 하네스")
    ap.add_argument("--mode", choices=["fast", "physics"], default="fast")
    ap.add_argument("--scenarios", help="쉼표로 구분한 시나리오 id (기본: 전체)")
    ap.add_argument("--baselines", help="쉼표로 구분한 baseline (A,B,proposed)")
    ap.add_argument("--reps", type=int, help="반복 횟수 상한 (기본: 시나리오의 repeat)")
    ap.add_argument("--controller", help="모든 baseline 에 이 제어기를 쓴다 (예: hold)")
    ap.add_argument("--out", help="결과 폴더 (기본: results/)")
    ap.add_argument("--list", action="store_true", help="실행 조합만 출력")
    ap.add_argument("--extra-baselines", default="", help="A 를 돌리는 시나리오에서 함께 돌릴 기준선 (예: A2)")
    ap.add_argument("--scenario-file", help="시나리오 파일 (기본: harness.yaml paths.scenarios) — 예: config/scenarios_heating.yaml (난방 확장)")
    args = ap.parse_args(argv)

    ids = args.scenarios.split(",") if args.scenarios else None
    bls = args.baselines.split(",") if args.baselines else None
    hcfg = load_harness_config()
    if args.scenario_file:                             # 난방 확장 등 — 동결 시나리오 파일 대신 이 파일 (run_batch 도 이 경로를 읽는다)
        hcfg["paths"]["scenarios"] = args.scenario_file

    if args.list:
        runs = expand_runs(load_scenarios(REPO / hcfg["paths"]["scenarios"]), ids, bls, args.reps)
        by_mode = Counter(r.scenario["run_mode"] for r in runs)
        for r in runs:
            print(f"{r.run_id:<20} {r.scenario['run_mode']:<8} seed={r.seed}")
        print(f"합계 {len(runs)}회 (" + ", ".join(f"{m} {n}" for m, n in by_mode.items()) + ")")
        return 0
    if args.mode == "physics":
        print("물리 모드는 W10 (T10.v1) 에 Isaac Sim 컨테이너(tools/isaac/run.sh)와 ROS 2 로 연결한다 — 아직 없음",
              file=sys.stderr)
        return 2

    if args.extra_baselines:
        hcfg["extra_baselines"] = {x: "A" for x in args.extra_baselines.split(",") if x}
    results = run_batch(ids, bls, args.reps, args.controller, args.out, args.mode, hcfg)
    write_manifest(Path(args.out or REPO / "results"), {"kind": f"scenario_runner_{args.mode}", "runs": len(results)})
    print()
    for r in results:
        print(f"{r.run.run_id:<20} {r.status:<8} 판정 {sum(c.status == C.PASS for c in r.criteria)}/{len(r.criteria)}"
              f"  {r.wall_s:5.1f}s")
        for c in r.criteria:
            if c.status != C.PASS:
                print(f"    {c.status:<7} {c.text}  {c.detail}")
        for n in r.notes:
            print(f"    ※ {n}")
    print(f"\n요약: {Counter(r.status for r in results)} → {Path(args.out or REPO / 'results') / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
