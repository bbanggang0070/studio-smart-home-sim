"""보류(held-out) 시나리오 평가 (docs/11 필수 조치 4 · docs/12 §5) — 동결된 제어기로 사전 등록한 H1–H12 를 한 번 돌린다.

    uv run python tools/run_heldout.py     → results/heldout/summary.csv · raw/ · results/tables/heldout_summary.md
    uv run python tools/run_heldout.py --scenarios config/heldout_scenarios_r2.yaml --tag r2   (2차 보류 · docs/12 §7)

시작 때 판정 · 지표(files)와 제어기(controller) 동결을 모두 점검한다 — 하나라도 바뀌었으면 돌리지 않는다.
실행 · 판정은 고속 모드 기본 실행기(run_batch)와 같다 — 시나리오 파일만 config/harness.yaml heldout.scenarios.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from harness.manifest import write_manifest  # noqa: E402
from harness.runner import load_harness_config, run_batch  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--extra-baselines", default="")   # 예: A2 (기준선 A′ · 2026-10-26)
    ap.add_argument("--freeze-config", default="")     # [난방 확장] config/freeze_heating.yaml
    a = ap.parse_args()
    fz = ["--config", a.freeze_config] if a.freeze_config else []
    chk = subprocess.run([sys.executable, str(REPO / "tools" / "check_freeze.py"), "--group", "all", *fz],
                         capture_output=True, text=True)
    print(chk.stdout.strip())
    if chk.returncode != 0:
        sys.exit("동결이 깨졌다 — 보류 평가는 동결된 판정 · 제어기로만 한다 (docs/12 §5)")
    hcfg = copy.deepcopy(load_harness_config())
    hcfg["paths"]["scenarios"] = a.scenarios or hcfg["heldout"]["scenarios"]
    sfx = f"_{a.tag}" if a.tag else ""
    out = REPO / (hcfg["heldout"]["out_dir"] + sfx)
    if a.extra_baselines:
        hcfg["extra_baselines"] = {x: "A" for x in a.extra_baselines.split(",") if x}
    res = run_batch(hcfg=hcfg, out_dir=out, progress=lambda m: None)
    write_manifest(out, {"kind": "heldout", "scenarios": hcfg["paths"]["scenarios"], "runs": len(res)})
    df = pd.read_csv(out / "summary.csv")
    lines = [f"# 보류(held-out) 평가 {a.tag or 'r1'} — {hcfg['paths']['scenarios']} · 동결 제어기 · 고속 모드 · 시나리오당 반복 3", "",
             "| 시나리오 | " + " | ".join(b for b in ("A", "B", "proposed")) + " | 제안이 실패한 판정 |", "|---|---:|---:|---:|---|"]
    for sid, g in df.groupby("scenario", sort=False):
        cells = []
        for bl in ("A", "B", "proposed"):
            x = g[g.baseline == bl]
            cells.append(f"{int((x.status == 'PASS').sum())}/{len(x)}" if len(x) else "–")
        bad = sorted({c[1] for _, r in g[g.baseline == "proposed"].iterrows()
                      for c in json.loads(r.criteria) if c[0] == "FAIL"})
        lines.append(f"| {sid} | " + " | ".join(cells) + " | " + " · ".join(f"`{b}`" for b in bad) + " |")
    for bl in ("A", "B", "proposed"):
        x = df[df.baseline == bl]
        lines.append(f"\n{bl}: {int((x.status == 'PASS').sum())}/{len(x)}")
    (REPO / "results" / "tables" / f"heldout_summary{sfx}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"실행 {len(res)}회")


if __name__ == "__main__":
    main()
