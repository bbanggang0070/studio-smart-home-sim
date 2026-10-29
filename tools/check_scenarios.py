"""시나리오 작성 점검 — 시작 상태를 실제로 계산해 점검표를 확인한다 (보류 묶음 등록 전 · 2026-10-28).

보류 난방 1차(HH101–HH112)에서 점검표 ③ '시작 결로 여유 > 0' 을 손으로만 적고 계산하지 않아 3개 시나리오가 t = 0 에서
결로(−0.2 ~ −1.7 °C)로 시작했다 (모든 방식 실패 · docs/15). 그 뒤로 등록 전에 이 도구를 돌린다.

    uv run python tools/check_scenarios.py config/heldout_heating_r2.yaml

확인: ① 시작 결로 여유 > 0 (thermal_steady 면 평형 상태로 계산) ② 시작 습도 ≤ 70 % ③ 창문 '== 0' 판정 없음
      ④ 기준선 A 와 에너지 비교 없음 ⑤ 모드 전환 시나리오는 시각별 모드 환기 판정
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from env_model import load_config  # noqa: E402
from harness.fast_world import WorldInputs, initial_actuators, make_model  # noqa: E402
from harness.runner import load_harness_config  # noqa: E402
from harness.scenario import load_scenarios  # noqa: E402


def main() -> None:
    path = REPO / sys.argv[1]
    hcfg = load_harness_config()
    env0 = load_config(REPO / hcfg["paths"]["environment_model"])
    bad = 0
    for sc in load_scenarios(path):
        env = env0.with_overrides(sc["environment_overrides"]) if sc.get("environment_overrides") else env0
        m = make_model(env, sc)
        w = WorldInputs.from_scenario(sc)
        ob = m.step(0.0, initial_actuators(sc), w.ext, None, w.occupancy_model())
        issues = []
        if ob["dew_margin_c"] <= 0.0 and not sc.get("expect_initial_condensation"):
            issues.append(f"시작 결로 여유 {ob['dew_margin_c']:.2f} °C ≤ 0")
        if sc["initial"]["humidity_pct"] > 70:
            issues.append(f"시작 습도 {sc['initial']['humidity_pct']} %")
        crit = sc.get("pass_criteria", [])
        if any(re.search(r"window_open_ratio\s*==\s*0", c) for c in crit):
            issues.append("창문 '== 0' 판정 (1차 지연)")
        # [v1.31-H M2] 기준선 A · A2 는 기본 환기를 하지 않는다 — 에너지 · 가스 · 비용을 A 와 비교하면 다른 일을 비교한다 (H3 · H8 교훈)
        if any(re.search(r"(gas_kwh|energy_cost_won|energy_wh|electric_kwh)\s*<=.*baseline_A2?\.", c) for c in crit):
            issues.append("기준선 A · A2 와 에너지 비교 (기본 환기 없음 — A2V 와 비교할 것)")
        # 모드가 바뀌는 시나리오의 기본 환기 판정은 시각별 모드 목표로 (HH205 교훈)
        mode_change = any("user_mode" in (e.get("set") or {}) for e in sc.get("events", []))
        if mode_change and any(re.search(r"\bbase_vent_compliance\b", c) for c in crit):
            issues.append("모드 전환 + 시작 모드 기준 환기 판정 (base_vent_compliance_mode 를 쓸 것)")
        bad += bool(issues)
        print(f"{sc['id']:<7} 결로 여유 {ob['dew_margin_c']:6.2f} °C  {'⚠ ' + ' · '.join(issues) if issues else 'OK'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
