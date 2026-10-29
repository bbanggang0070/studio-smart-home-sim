"""v1.29 회귀 확인 (난방 확장 docs/14 §15 T2 · M4) — 지금 코드로 v1.29 시나리오를 다시 돌려 보관 요약(archive/v1.29)과 대조.

    uv run python tools/check_v129_regression.py                 # 개발 시나리오 (fast_dev_summary.csv · 249회)
    uv run python tools/check_v129_regression.py --heldout       # + 보류 7차 (heldout_r7_summary.csv)
    uv run python tools/check_v129_regression.py --heldout-all   # + 보류 1–6차 (참고 — 이전 버전 제어기 · 환경 모델로 돌린 보관본이라 다른 것이 정상)

v1.29 동결 제어기로 돌린 보류 묶음은 7차뿐이다 (1–6차는 v1.29 이전 버전 · 2026-10-29 확인: 1–4차 모두 A 까지 다름).

같다 = 공통 지표 열 · 판정 통과 수 · 상태가 모두 같고, 새로 생긴 열이 없다. 다르면 종료 코드 1 + 다른 열 · 실행 목록.
시계열은 저장하지 않는다 (임시 폴더 · 요약만).
"""

from __future__ import annotations

import argparse
import copy
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from harness.runner import load_harness_config, run_batch  # noqa: E402

ARCH = REPO / "archive" / "v1.29"
SETS = [("개발", None, "fast_dev_summary.csv")]
OLD_HELDOUT = [("보류 1차", "config/heldout_scenarios.yaml", "heldout_summary.csv")] + [
    (f"보류 {k}차", f"config/heldout_scenarios_r{k}.yaml", f"heldout_r{k}_summary.csv") for k in range(2, 7)]
HELDOUT = [("보류 7차", "config/heldout_scenarios_r7.yaml", "heldout_r7_summary.csv")]


def compare(new: pd.DataFrame, old: pd.DataFrame) -> tuple[int, list, list]:
    j = new.merge(old, on="run_id", suffixes=("_new", "_old"))
    cols = [c for c in new.columns if c.startswith("m.") and c in old.columns] + ["criteria_pass", "status"]
    bad = []
    for c in cols:
        a, b = j[c + "_new"], j[c + "_old"]
        na, nb = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
        d = ~((a == b) | (a.isna() & b.isna()) | ((na - nb).abs() < 1e-9))
        if d.any():
            bad.append((c, int(d.sum()), j.run_id[d].tolist()[:5]))
    extra = [c for c in new.columns if c.startswith("m.") and c not in old.columns]
    return len(j), bad, extra


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heldout", action="store_true")
    ap.add_argument("--heldout-all", action="store_true")
    a = ap.parse_args()
    ok = True
    for name, scen, ref in SETS + (HELDOUT if a.heldout or a.heldout_all else []) + (OLD_HELDOUT if a.heldout_all else []):
        hcfg = copy.deepcopy(load_harness_config())
        if scen:
            hcfg["paths"]["scenarios"] = scen
        hcfg["keep_raw"] = False
        with tempfile.TemporaryDirectory() as tmp:
            run_batch(hcfg=hcfg, out_dir=tmp, progress=lambda m: None)
            new = pd.read_csv(Path(tmp) / "summary.csv")
        old = pd.read_csv(ARCH / ref)
        n, bad, extra = compare(new, old)
        same = not bad and not extra and n == len(old)
        ok &= same or (name, scen, ref) in OLD_HELDOUT     # 1–6차는 참고만
        print(f"{name}: 비교 {n}/{len(old)} · {'같다' if same else '⚠ 다르다'}" + (f" · 다른 열 {bad}" if bad else "")
              + (f" · 새 열 {extra}" if extra else ""), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
