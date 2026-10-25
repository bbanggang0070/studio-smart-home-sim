"""전력 감시(B11) · 가전 확인 E9 · E12 · 조도 페일세이프(X3) 단위 테스트."""

import pytest

from controller.appliance_guard import ApplianceGuard
from controller.lighting import Lighting
from controller.params import load_params
from controller.signals import Observation
from sensors.power_monitor import PowerMonitor


@pytest.fixture(scope="module")
def params():
    return load_params()


@pytest.fixture()
def monitor(params):
    return PowerMonitor(params.get("power_monitor"), params.get("events.appliance_no_response.power_confirm_s"))


def _feed(m, t0, t1, w, dev="ac"):
    out = None
    for t in range(t0, t1):
        out = m.update(float(t), {dev: w})
    return out


def test_power_monitor_thermo_off_is_not_off_and_manual_detected(monitor):
    _feed(monitor, 0, 5, 0.0)
    monitor.note_command("ac", 5.0)
    st = _feed(monitor, 5, 30, 700.0)["ac"]
    assert st == {"state": "run", "edge": "off→run", "source": "command"}
    st = _feed(monitor, 30, 80, 30.0)["ac"]                 # 써모오프 — 송풍
    assert st["state"] == "fan_only" and st["source"] == "self"
    st = _feed(monitor, 80, 140, 0.0)["ac"]                 # 명령 없이 꺼짐 = 수동 조작
    assert st["state"] == "off" and st["source"] == "manual"


def test_manual_off_right_after_on_command_is_manual(monitor):
    """'켜라' 명령 2 s 뒤 사용자가 끄면 명령 창 안이어도 manual — 방향이 반대 (실측 기상 B11 · 2026-10-25)."""
    _feed(monitor, 0, 5, 0.0)
    monitor.note_command("ac", 5.0, True)
    assert _feed(monitor, 5, 40, 700.0)["ac"]["source"] == "command"
    monitor.note_command("ac", 100.0, True)                     # 설정만 바뀐 '켜라' 프레임
    _feed(monitor, 40, 102, 700.0)
    st = _feed(monitor, 102, 140, 0.0)["ac"]                    # 2 s 뒤 리모컨으로 끔
    assert st["state"] == "off" and st["source"] == "manual"
    monitor.note_command("ac", 200.0, False)
    _feed(monitor, 140, 200, 0.0)
    monitor.note_command("ac", 210.0, True)
    assert _feed(monitor, 200, 240, 700.0)["ac"]["source"] == "command"   # 방향이 맞으면 그대로 command


def test_inverter_low_load_is_run(monitor):
    _feed(monitor, 0, 5, 0.0)
    monitor.note_command("ac", 5.0)
    assert _feed(monitor, 5, 40, 155.0)["ac"]["state"] == "run"   # 저부하 제습 ~150 W 가 빈 구간에 빠지지 않는다


def test_guard_resends_exactly_max_then_fails(params):
    g = ApplianceGuard(params)
    off = {"ac": {"state": "off", "edge": "", "source": ""}}
    actions = [g.ac_step(float(t), True, off) for t in range(0, 300)]
    assert g.resends == params.get("events.appliance_no_response.max_resend")
    assert actions[-1] == "failed" and g.alerts and g.alerts[0]["code"] == "E9"


def test_guard_holds_after_manual_then_resumes(params):
    g = ApplianceGuard(params)
    hold_s = params.get("events.manual_override.hold_min") * 60.0
    manual = {"ac": {"state": "off", "edge": "run→off", "source": "manual"}}
    assert g.ac_step(100.0, True, manual) == "hold"
    assert g.ac_step(100.0 + hold_s - 1, True, manual) == "hold"
    seq = g.seq
    assert g.ac_step(100.0 + hold_s + 1, True, manual) == "send"   # 같은 엣지는 다시 보류하지 않는다
    assert g.seq == seq + 1                                         # 보류 끝 — 다시 송신


def test_guard_confirm_resend_on_mode_change(params):
    g = ApplianceGuard(params)
    run = {"ac": {"state": "run", "edge": "off→run", "source": "command"}}
    g.ac_step(0.0, True, run, key="cool")
    g.ac_step(1.0, True, run, key="dry")
    seq = g.seq
    for t in range(2, 60):
        g.ac_step(float(t), True, run, key="dry")
    assert g.seq == seq + 1                                         # 모드 변경 확인 재송신 1회


def test_lighting_holds_then_virtual_lux(params):
    li = Lighting(params)
    o = Observation.__new__(Observation)
    base = dict(now_s=50000.0, illuminance_lux=300.0, raining=False, blind_deg=0.0,
                ceiling_pct=0.0, desk_pct=0.0)
    for k, v in base.items():
        setattr(o, k, v)
    assert li.measured(o) == (300.0, False)
    o.now_s, o.illuminance_lux = 50005.0, float("nan")
    assert li.measured(o) == (300.0, False)                         # 마지막 유효값 유지
    o.now_s = 50000.0 + params.get("sensor_failsafe.hold_last_valid_s") + 1
    lux, entered = li.measured(o)
    assert entered and li.virtual and lux > 0                       # 낮 — 가상 조도로 전환
