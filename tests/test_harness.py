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


def test_response_time_and_budget_violation_metrics():
    """W13 T13.1 — 지표 #2 응답 시간(지령 → 허용 오차 도달) · #16 예산 위반(이벤트 구간 × 항목, 30 s 이상)."""
    import numpy as np
    import pandas as pd

    from harness.criteria import _budget_violations, _response_time
    t = np.arange(0.0, 10.0)
    cmd = pd.Series([np.nan, 0.4, 0.4, 0.4, 0.4, 0.4, 0.0, 0.0, 0.0, 0.0])
    act = pd.Series([0.0, 0.1, 0.2, 0.3, 0.39, 0.4, 0.3, 0.1, 0.0, 0.0])
    assert _response_time(t, cmd, act, 0.02) == 3.0                     # 0.4 지령 t=1 → 도달 t=4 · 0 지령 t=6 → t=8 (2 s)
    n = 100
    df = pd.DataFrame({
        T.T_ACTIVE_EVENTS: ['["LAUNDRY_DRYING"]'] * 60 + ["[]"] * 40,
        "truth.temperature_c": np.r_[np.linspace(26.0, 27.5, 60), np.full(40, 27.5)],
        "truth.occupied": [True] * n,
        "act.exhaust_fan_rpm": np.r_[np.full(50, 1000.0), np.full(10, 1600.0), np.zeros(40)],
    })
    b = {"LAUNDRY_DRYING": {"indoor_temp_rise_c": 1.0, "indoor_temp_rise_away_c": 3.0,
                            "noise_caps": {"act.exhaust_fan_rpm": 1400.0}}}
    assert _budget_violations(df, b, [], 5) == 2.0                     # 온도 +1.5 °C · 배기 1,600 rpm 10 샘플
    assert _budget_violations(df, b, [], 15) == 1.0                    # 소음은 15 샘플 미만 — 온도만
    b["LAUNDRY_DRYING"]["indoor_temp_rise_c"] = 2.0
    assert _budget_violations(df, b, [], 15) == 0.0


def test_bridge_blind_repeat_and_refresh_for_purifier():
    """피드백 없는 IR 기기(청정기) — 바뀐 명령은 60 s 간격 3번 더 · 그 뒤엔 state_refresh_s 마다 다시 쏜다 (H210)."""
    from harness.fast_world import FastActuators, initial_actuators
    acts = FastActuators(initial_actuators({"initial": {}}), {}, ["purifier"])
    acts.ir_refresh_s, acts.ir_refresh_devices, acts.ir_repeat = 600.0, {"purifier"}, (3, 60.0)
    for t in range(0, 1300):
        acts.command({T.C_PURIFIER_LEVEL: 2}, float(t))
    assert acts.ir_tx["purifier"] == 1 + 3 + 1                  # 첫 송신 + 반복 3 (60 · 120 · 180 s) + 주기 1 (180 + 600 = 780 s)



def test_fast_l0_compressor_guard_and_mutex():
    """고속 하네스 L0 — 물리 모드 가전 브릿지와 같은 압축기 최소 ON 300 s / OFF 180 s · 제습 ⟂ 가습 (2026-10-24)."""
    from controller.params import load_params
    from harness.fast_world import FastActuators, initial_actuators
    acts = FastActuators(initial_actuators({"initial": {}}), {}, ["ac", "dehumidifier", "humidifier"])
    acts.l0_setup(load_params().th["appliances"])
    on = json.dumps({"power": True, "mode": "cool", "setpoint": 26.0})
    off = json.dumps({"power": False, "mode": "cool", "setpoint": 26.0})
    acts.command({T.C_AC: on}, 0.0); acts.update(1.0)
    assert acts.actual.ac.power                                   # 처음 켜기는 바로 (최소 OFF 는 시작 전부터 지났다)
    acts.command({T.C_AC: off}, 60.0); acts.update(59.0)
    assert acts.actual.ac.power                                   # 켠 지 60 s — 최소 ON 300 s 전이라 유지
    for _ in range(250):
        acts.update(1.0)
    assert not acts.actual.ac.power                               # 300 s 지나 꺼짐
    acts.command({T.C_AC: on}, 320.0); acts.update(10.0)
    assert not acts.actual.ac.power                               # 끈 지 10 s — 최소 OFF 180 s 전
    acts.command({T.C_DEHUMIDIFIER: True, T.C_HUMIDIFIER: True}, 330.0); acts.update(1.0)
    assert acts.actual.dehumidifier and not acts.actual.humidifier   # 제습 ⟂ 가습


def test_sensor_faults_bias_dropout_and_pairing():
    """센서 결함 (A1 · 2026-10-26) — 편향은 실행 동안 고정 · 끊김이면 마지막 값 유지 · 결함 난수는 따로라 기본 잡음 순서가 같다."""
    import numpy as np
    from sensors.sensor_models import SensorModel
    spec = {"tau_s": 0.0, "sigma": 0.0, "rel_sigma": 0.0, "resolution": 0.0, "range": [-100.0, 100.0]}
    f = {"bias": 0.3, "drift_per_h": 0.0, "outlier_p": 0.0, "outlier_sigma": 10.0, "dropout_p_per_s": 0.0, "dropout_s": [10.0, 60.0]}
    m = SensorModel(spec, np.random.default_rng(0), f, np.random.default_rng(1))
    vals = [m.measure(20.0, 1.0) for _ in range(5)]
    assert len(set(vals)) == 1 and abs(vals[0] - 20.0) <= 0.3 and vals[0] != 20.0     # 고정 편향
    f2 = {**f, "bias": 0.0, "dropout_p_per_s": 1.0, "dropout_s": [30.0, 30.0]}
    m2 = SensorModel(spec, np.random.default_rng(0), f2, np.random.default_rng(1))
    first = m2.measure(20.0, 1.0)
    assert all(m2.measure(25.0, 1.0) == first for _ in range(20))                    # 끊김 — 참값이 바뀌어도 마지막 값
    a = SensorModel({**spec, "sigma": 1.0}, np.random.default_rng(5))
    b = SensorModel({**spec, "sigma": 1.0}, np.random.default_rng(5), {**f, "bias": 0.0}, np.random.default_rng(9))
    assert [a.measure(0.0, 1.0) for _ in range(5)] == [b.measure(0.0, 1.0) for _ in range(5)]   # 결함 0 이면 기본 잡음이 같다
