"""L0 가전 보호 (W06 T6.v2)."""

from actuators.l0_protect import CompressorGuard, FanDirectionGuard, dehum_hum_mutex


def test_compressor_min_on_off():
    g = CompressorGuard(180, 300)
    assert g.apply(True, 0) is True                     # 처음 켬 (오래 꺼져 있었다)
    assert g.apply(False, 100) is True and g.held       # 300 s 전에는 못 끈다
    assert g.apply(False, 301) is False
    assert g.apply(True, 400) is False and g.held       # 꺼진 지 180 s 전에는 못 켠다
    assert g.apply(True, 482) is True


def test_fan_direction_wait():
    f = FanDirectionGuard(10)
    assert f.apply(2, 0) == 2
    assert f.apply(-1, 5) == 0                           # 반대 방향 — 멈춤
    assert f.apply(-1, 10) == 0                          # 아직 10 s 안
    assert f.apply(-1, 15.5) == -1
    assert f.apply(-1, 16) == -1 and f.apply(-2, 17) == -2   # 같은 방향 단 변경은 바로


def test_mutex():
    assert dehum_hum_mutex(True, True) == (True, False) and dehum_hum_mutex(False, True) == (False, True)
