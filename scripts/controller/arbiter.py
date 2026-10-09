"""중재기 (docs/07 §5.2) — 같은 장치에 걸린 후보 명령을 하나로 합친다.

후보 = (장치, 종류, 값, 계층, 사유). 종류는 need(필요) · cap(상한) · force(강제).
  1. force : 가장 높은 계층(숫자가 작은)의 force 가 최종값 — 단 그보다 높은 계층의 cap 은 지킨다
  2. cap   : 활성 cap 중 최솟값
  3. need  : need 중 최댓값 (없으면 기본값)
  4. 최종  : min(max(need), min(cap))
L2 이벤트가 L4 소음 상한을 완화하는 것은 규칙 엔진이 '유효 소음 등급'을 바꿔서 처리한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    device: str
    kind: str          # need | cap | force
    value: float
    layer: float       # 0–6 (4.5 = 우선 목표)
    reason: str


@dataclass
class Decision:
    value: float
    reasons: list[str]


def merge(cands: list[Candidate], defaults: dict[str, float]) -> dict[str, Decision]:
    devices = {c.device for c in cands} | set(defaults)
    out: dict[str, Decision] = {}
    for dev in sorted(devices):
        cs = [c for c in cands if c.device == dev]
        forces = sorted((c for c in cs if c.kind == "force"), key=lambda c: c.layer)
        caps = [c for c in cs if c.kind == "cap"]
        needs = [c for c in cs if c.kind == "need"]
        if forces:
            f = forces[0]
            val, why = f.value, [f"force L{f.layer:g} {f.reason}"]
            for cap in caps:
                if cap.layer < f.layer and cap.value < val:
                    val, why = cap.value, why + [f"cap L{cap.layer:g} {cap.reason}"]
            out[dev] = Decision(val, why)
            continue
        if needs:
            top = max(needs, key=lambda c: (c.value, -c.layer))
            val, why = top.value, [f"need L{top.layer:g} {top.reason}"]
        elif dev in defaults:
            val, why = defaults[dev], ["기본값"]
        else:
            continue
        if caps:
            low = min(caps, key=lambda c: (c.value, c.layer))
            if low.value < val:
                val, why = low.value, why + [f"cap L{low.layer:g} {low.reason}"]
        out[dev] = Decision(val, why)
    return out
