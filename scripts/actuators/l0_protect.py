"""L0 가전 보호 (W06 T6.v2 · docs/07 6계층의 맨 아래) — 제어기 판단과 무관하게 기기를 지킨다.

  압축기(에어컨 · 제습기)  최소 OFF compressor_min_off_s · 최소 ON compressor_min_on_s — 그 전에는 직전 상태 유지
  실링팬                  방향 전환은 정지 후 direction_change_wait_s 뒤에 (모터 보호)
  제습 ⟂ 가습             둘 다 켜라는 지령이면 가습을 끈다 (규칙 I1 의 마지막 방어선)
"""

from __future__ import annotations


class CompressorGuard:
    def __init__(self, min_off_s: float, min_on_s: float, on: bool = False, since: float = -1e9):
        self.min_off, self.min_on = min_off_s, min_on_s
        self.on, self.since = on, since
        self.held = False                       # 직전 결정이 보호로 보류됐나

    def apply(self, want: bool, now: float) -> bool:
        if want != self.on:
            need = self.min_on if self.on else self.min_off
            if now - self.since < need:
                self.held = True
                return self.on
            self.on, self.since = want, now
        self.held = False
        return self.on


class FanDirectionGuard:
    """단(−2…+2) 지령 → 실제로 낼 단. 마지막 회전 방향과 반대로 돌리려면 멈춘 뒤 wait_s 를 기다린다."""

    def __init__(self, wait_s: float):
        self.wait = wait_s
        self.level = 0
        self._last_dir = 0                      # 마지막으로 돌던 방향 (+1 · −1)
        self._stopped_at = -1e9

    def apply(self, want: int, now: float) -> int:
        want_dir = (want > 0) - (want < 0)
        if self.level != 0 and want_dir != self._last_dir:      # 정지 지령이거나 반대 방향 — 먼저 멈춘다
            self.level, self._stopped_at = 0, now
        if want_dir != 0 and want_dir != self._last_dir and self._last_dir != 0 and now - self._stopped_at < self.wait:
            return 0                                             # 반대 방향은 멈춘 지 wait_s 뒤에
        self.level = want
        if want_dir != 0:
            self._last_dir = want_dir
        return self.level


def dehum_hum_mutex(dehum: bool, hum: bool) -> tuple[bool, bool]:
    return (dehum, False) if dehum and hum else (dehum, hum)
