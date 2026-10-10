"""실험 하네스 검증 — 전개 · 재현성 · 판정 문법 · 미지원 주입 기록 · 제어기 계약(폐루프)."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from harness import controllers
from harness import criteria as C
from harness.runner import REPO, load_harness_config, run_batch
from harness.scenario import expand_runs, load_scenarios
from interfaces import topics as T


@pytest.fixture(scope="module")
def hcfg():
    return load_harness_config()


@pytest.fixture(scope="module")
def scenarios(hcfg):
    return load_scenarios(REPO / hcfg["paths"]["scenarios"])


def _quiet(*_args):
    pass


# ---- 전개 · 재현성 --------------------------------------------------------------


def test_expand_runs_counts_and_shared_seeds(scenarios):
    runs = expand_runs(scenarios, ids=["C9"])
    assert len(runs) == 9                                   # 3 baseline × 3 반복
    by_rep = {}
    for r in runs:
        by_rep.setdefault(r.rep, set()).add(r.seed)
    assert all(len(s) == 1 for s in by_rep.values())         # 같은 반복의 baseline 은 같은 시드
    assert len({r.run_id for r in runs}) == 9


def test_unknown_scenario_id_is_an_error(scenarios):
    with pytest.raises(ValueError):
        expand_runs(scenarios, ids=["Z99"])


def test_same_seed_same_log(hcfg, tmp_path):
    a = run_batch(["B7"], reps=1, controller_override="hold", out_dir=tmp_path / "a", hcfg=hcfg, progress=_quiet)
    b = run_batch(["B7"], reps=1, controller_override="hold", out_dir=tmp_path / "b", hcfg=hcfg, progress=_quiet)
    pd.testing.assert_frame_equal(a[0].df, b[0].df)
    assert (tmp_path / "a" / "raw" / "B7_proposed_1.csv").exists()
    assert (tmp_path / "a" / "summary.csv").exists()


def test_unimplemented_controller_is_reported_not_crashed(hcfg, tmp_path):
    cfg = copy.deepcopy(hcfg)
    cfg["controllers"]["B"] = "unimplemented"
    res = run_batch(["C9"], baselines=["B"], reps=1, out_dir=tmp_path, hcfg=cfg, progress=_quiet)
    assert res[0].status == C.ERROR
    assert "구현되지 않았다" in res[0].notes[0]


def test_unsupported_injection_is_recorded(hcfg, tmp_path):
    """아직 처리하지 못하는 주입(센서 드리프트 등)은 조용히 무시하지 않고 notes 에 남긴다."""
    import yaml
    scen = load_scenarios(REPO / hcfg["paths"]["scenarios"])
    sc = copy.deepcopy(next(s for s in scen if s["id"] == "B6"))
    sc["injections"] = sc["injections"] + [{"at_s": 0, "fault": "sensor_drift"}]
    path = tmp_path / "sc.yaml"
    path.write_text(yaml.safe_dump({"scenarios": [sc]}, allow_unicode=True), encoding="utf-8")
    cfg = copy.deepcopy(hcfg)
    cfg["paths"]["scenarios"] = str(path)
    res = run_batch(["B6"], reps=1, controller_override="hold", out_dir=tmp_path / "o", hcfg=cfg, progress=_quiet)
    assert any("fault" in n for n in res[0].notes)


def test_profile_rejects_absent_device(hcfg, tmp_path):
    """core 프로파일에는 후드가 없다 — 후드 명령은 무시되고 기록된다 (X8 전제)."""
    class HoodController:
        def reset(self, params):
            pass

        def step(self, now_s, inbox):
            return {T.C_RANGE_HOOD_LEVEL: 2}

    cfg = copy.deepcopy(hcfg)
    sc_path = tmp_path / "sc.yaml"
    scen = load_scenarios(REPO / hcfg["paths"]["scenarios"])
    sc = copy.deepcopy(next(s for s in scen if s["id"] == "B7"))
    sc["appliance_profile"] = "core"
    import yaml
    sc_path.write_text(yaml.safe_dump({"scenarios": [sc]}, allow_unicode=True), encoding="utf-8")
    cfg["paths"]["scenarios"] = str(sc_path)
    controllers.BUILTIN["hood_test"] = HoodController
    try:
        res = run_batch(["B7"], reps=1, controller_override="hood_test", out_dir=tmp_path / "o", hcfg=cfg,
                        progress=_quiet)
    finally:
        controllers.BUILTIN.pop("hood_test")
    assert (res[0].df["act.range_hood_level"] == 0).all()
    assert any("무시" in n for n in res[0].notes)


# ---- 판정 문법 -------------------------------------------------------------------


def _df():
    t = np.arange(0, 101, 1.0)
    pm = np.where(t < 20, 10.0, np.where(t < 60, 80.0, 20.0))
    ev = ["[]" if x < 30 else json.dumps(["COOKING"]) for x in t]
    return pd.DataFrame({"time_s": t, "truth.pm25_ugm3": pm, "act.range_hood_level": np.where(t >= 30, 1, 0),
                         "truth.q_net_m3h": np.where(t >= 30, -40.0, 0.0), T.T_ACTIVE_EVENTS: ev})


@pytest.mark.parametrize("text, status", [
    ("event_entered('COOKING') within 15 after 20", C.PASS),
    ("event_entered('COOKING') within 5 after 20", C.FAIL),
    ("not event_entered('SHOWER')", C.PASS),
    ("pm25 <= 35 within 50 after cook_end", C.PASS),
    ("pm25 <= 35 by 5 after cook_start", C.FAIL),         # 앵커 직후엔 이미 참이었지만 5초 뒤엔 거짓
    ("pm25 <= value_at('pm25', 0) + 15 by 70 after 0", C.PASS),
    ("range_hood_level == 0 for all t", C.FAIL),
    ("range_hood_level == 1 during cook", C.FAIL),         # 20–30 s 구간은 아직 0
    ("q_net >= -50 when range_hood_level > 0", C.PASS),
    ("pm25_peak <= 0.7 * baseline_A.pm25_peak", C.PASS),
    ("pm25_peak <= 0.7 * baseline_B.pm25_peak", C.PENDING),
    ("unknown_name > 0", C.ERROR),
    ("__import__('os')", C.ERROR),                         # 허용되지 않은 호출
])
def test_criteria_grammar(text, status):
    res = C.evaluate(_df(), [text], {}, anchors={"cook_start": 20.0, "cook_end": 60.0},
                     intervals={"cook": (20.0, 60.0)}, metrics={"pm25_peak": 80.0},
                     baselines={"A": {"pm25_peak": 200.0}})
    assert res[0].status == status, res[0].detail


def test_expect_block_and_self_baseline_na():
    res = C.evaluate(_df(), ["pm25_peak <= baseline_A.pm25_peak"], {"range_hood_level": {"max": 1}},
                     anchors={}, intervals={}, metrics={"pm25_peak": 80.0},
                     baselines={"A": {"pm25_peak": 80.0}}, own_baseline="A")
    assert [r.status for r in res] == [C.NA, C.PASS]


# ---- 제어기 계약 — 폐루프 ------------------------------------------------------------


class ScriptedCookingController:
    """테스트용 모범 답안: 후드 아래 온도로 요리를 감지해 C9 기대 동작을 낸다 (실제 제어기 아님)."""

    def reset(self, params):
        self.cooking = False

    def step(self, now_s, inbox):
        rise = inbox[T.S_HOOD_TEMPERATURE] - inbox[T.S_TEMPERATURE]
        self.cooking = rise >= 8.0 or (self.cooking and rise >= 2.0)
        if self.cooking:
            return {T.C_RANGE_HOOD_LEVEL: 1, T.C_INTAKE_FAN_RPM: 2000.0, T.C_PURIFIER_LEVEL: 3,
                    T.T_ACTIVE_EVENTS: json.dumps(["COOKING"])}
        return {T.C_RANGE_HOOD_LEVEL: 0, T.C_INTAKE_FAN_RPM: 0.0, T.C_PURIFIER_LEVEL: 1,
                T.T_ACTIVE_EVENTS: "[]"}


def test_closed_loop_controller_contract_c9(hcfg, tmp_path):
    cfg = copy.deepcopy(hcfg)
    cfg["controllers"] = {"A": "hold", "B": "hold", "proposed": "scripted_c9"}
    controllers.BUILTIN["scripted_c9"] = ScriptedCookingController
    try:
        res = run_batch(["C9"], baselines=["A", "proposed"], reps=1, out_dir=tmp_path, hcfg=cfg, progress=_quiet)
    finally:
        controllers.BUILTIN.pop("scripted_c9")
    a = next(r for r in res if r.run.baseline == "A")
    p = next(r for r in res if r.run.baseline == "proposed")
    status = {c.text: c.status for c in p.criteria}
    assert status["event_entered('COOKING') within 90 after cooking_start"] == C.PASS
    assert status["window_open_ratio == 0 for all t"] == C.PASS
    assert status["pm25_peak <= 0.85 * baseline_A.pm25_peak"] == C.PASS
    assert p.metrics["pm25_peak"] < a.metrics["pm25_peak"]
    # 후드 약(300) + 흡기 100 %(60, 필터 막힘 0) → 정상 상태 Q_net = −240 m³/h (docs/07 §5.4 결정 추적표와 같다)
    # 흡기팬은 1차 지연(2 s)이라 후드가 켜진 직후 몇 초는 더 음압이다 — 그 과도 구간은 뺀다
    hood_on = p.df["act.range_hood_level"] > 0
    steady = p.df.loc[hood_on, "truth.q_net_m3h"].iloc[15:]
    assert steady.min() == pytest.approx(-240.0, abs=0.5)
