"""scenario_profiles.yaml 로드 · 검증 · 실행 조합 전개 (docs/03 §8 하네스 동작 규약 1단계).

시나리오 × baseline × 반복 → Run 목록. 같은 반복 번호의 baseline 들은 같은 시드를 쓴다
(외란 · 노이즈가 같아야 baseline 끼리 공정하게 비교된다).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REQUIRED_KEYS = ("id", "duration_s", "repeat", "baselines", "seed", "run_mode", "initial", "external")
RUN_MODES = ("fast", "physics")


@dataclass(frozen=True)
class Run:
    scenario: dict[str, Any]
    baseline: str
    rep: int
    seed: int

    @property
    def scenario_id(self) -> str:
        return self.scenario["id"]

    @property
    def run_id(self) -> str:
        return f"{self.scenario_id}_{self.baseline}_{self.rep}"


class ScenarioError(ValueError):
    pass


def load_scenarios(path: str | Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    scenarios = data.get("scenarios") or []
    seen: set[str] = set()
    for sc in scenarios:
        missing = [k for k in REQUIRED_KEYS if k not in sc]
        if missing:
            raise ScenarioError(f"시나리오 {sc.get('id', '?')}: 필수 키 누락 {missing}")
        if sc["id"] in seen:
            raise ScenarioError(f"시나리오 id 중복: {sc['id']}")
        if sc["run_mode"] not in RUN_MODES:
            raise ScenarioError(f"시나리오 {sc['id']}: run_mode 는 {RUN_MODES} 중 하나")
        seen.add(sc["id"])
    return scenarios


def scenario_baselines(sc: dict[str, Any], extra: dict[str, str] | None = None) -> list[str]:
    """시나리오의 기준선 + extra 중 짝 기준선이 있는 것 (시나리오 파일은 동결 — 고치지 않고 추가 기준선을 붙인다)."""
    bls = list(sc["baselines"])
    return bls + [x for x, ref in (extra or {}).items() if ref in bls and x not in bls]


def expand_runs(
    scenarios: list[dict[str, Any]],
    ids: list[str] | None = None,
    baselines: list[str] | None = None,
    reps: int | None = None,
    extra: dict[str, str] | None = None,
) -> list[Run]:
    """extra = {추가 기준선: 짝 기준선} — 짝 기준선을 돌리는 시나리오에서 추가 기준선도 돌린다 (예: {"A2": "A"} · 2026-10-26)."""
    if ids:
        unknown = set(ids) - {s["id"] for s in scenarios}
        if unknown:
            raise ScenarioError(f"없는 시나리오 id: {sorted(unknown)}")
    runs: list[Run] = []
    for sc in scenarios:
        if ids and sc["id"] not in ids:
            continue
        n_rep = sc["repeat"] if reps is None else min(reps, sc["repeat"])
        for rep in range(1, n_rep + 1):
            for bl in scenario_baselines(sc, extra):
                if baselines and bl not in baselines:
                    continue
                runs.append(Run(scenario=sc, baseline=bl, rep=rep, seed=int(sc["seed"]) + rep))
    return runs
