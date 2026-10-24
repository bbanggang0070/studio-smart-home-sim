"""창문 기준 반력 프로파일 그래프 (W05 T5.8) — models/window_reference_profile.csv 로 그린다 (Isaac Sim 없이 다시 그리기).

    uv run python tools/analysis/plot_window_profile.py   → results/actuators/window_profile.png (1920 × 1080)

tools/isaac/window_profile.py 도 측정 뒤 이 함수로 그린다.
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SLIDE = dict(figsize=(16, 9), dpi=120)          # 1920 × 1080 (plot_w13 과 같은 규격)


def plot_profile(rows: list[dict], travel_m: float, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=SLIDE["figsize"])
    for d, col in (("close", "tab:red"), ("open", "tab:blue")):
        rr = [r for r in rows if r["direction"] == d]
        ax.plot([(float(r["bin_lo_m"]) + float(r["bin_hi_m"])) / 2 * 1000 for r in rr],
                [float(r["force_mean_n"]) for r in rr], "o-", color=col, label=d)
    for x in (0.03, 0.15, 0.95):                 # 폐쇄 기준 Zone 경계 (D | C | B | A)
        ax.axvline(x * travel_m * 1000, ls=":", c="gray")
    ax.set_xlabel("panel position q [mm] (0 = closed)")
    ax.set_ylabel("|joint force| [N]")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=SLIDE["dpi"])
    plt.close(fig)


def main() -> None:
    with open(REPO / "models" / "window_reference_profile.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(l for l in fh if not l.startswith("#")))
    layout = yaml.safe_load((REPO / "config" / "scene_layout.yaml").read_text(encoding="utf-8"))
    plot_profile(rows, float(layout["window"]["travel_m"]), REPO / "results" / "actuators" / "window_profile.png")


if __name__ == "__main__":
    main()
