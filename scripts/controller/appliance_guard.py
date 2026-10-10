"""가전 확인 — E9 무응답 · E12 수동 조작 (docs/07 §3 · docs/08 §3.5–3.6 · docs/06 §3.4).

E9  명령한 상태(켜짐/꺼짐)가 전력 감시(appliance_states)에 power_confirm_s + 이동평균 창 안에 나타나지 않으면 재송신
    (JSON 의 seq 를 올려 브릿지가 다시 쏘게 한다). max_resend 회 뒤에도 안 되면 무응답 확정 →
    그 가전을 사다리에서 뺀다 · 알림 · control_feasibility = DEGRADED. 무한 재시도는 없다 (헛구동 지표 #8).
E12 전력 감시가 command 가 아닌 manual 원인의 변화를 보고하면 그 가전의 자동 제어를 hold_min 동안 보류한다
    (명령 토픽을 내지 않는다 — 협조 동작인 창문 · 배기는 계속).
    모드 · 설정온도 · 풍량만 바뀐 명령은 전력으로 확인할 수 없다(제습 · 냉방 모두 '가동') → 확인 시간 뒤 1회 확인 재송신.
    IR 에어컨 프레임은 전체 상태를 담으므로 같은 프레임을 다시 쏘아도 무해하다.
    확인 재송신까지 누락되면 잘못된 모드가 계속 남으므로(C15) state_refresh_s 마다 같은 프레임을 다시 보낸다.
v1: 에어컨 (IR). 청정기 효과 확인 · 제습기 물통 가득은 같은 틀로 W10 에 더한다.
"""

from __future__ import annotations

from controller.params import ControllerParams


class ApplianceGuard:
    def __init__(self, p: ControllerParams):
        g = p.get
        self.wait_s = g("events.appliance_no_response.power_confirm_s") + g("power_monitor.moving_avg_s")
        self.max_resend = int(g("events.appliance_no_response.max_resend"))
        self.refresh_s = g("appliances.ir.state_refresh_s")
        self._last_bump: float | None = None
        self.hold_s = g("events.manual_override.hold_min") * 60.0
        self.seq = 0
        self.resends = 0
        self._mismatch_since: float | None = None
        self._last_want: bool | None = None
        self.failed = False
        self.manual_until: float | None = None
        self._seen_manual_edge: str | None = None
        self._last_key: str | None = None
        self._confirm_at: float | None = None
        self.alerts: list[dict] = []

    def ac_step(self, now: float, want_on: bool, states: dict, key: str | None = None) -> str:
        """→ 'send' (평소대로 명령) | 'hold' (수동 조작 보류 — 내지 않음) | 'failed' (무응답 확정 — 내지 않음)."""
        st = states.get("ac") or {}
        if self._last_bump is None:
            self._last_bump = now
        # E12 — 사용자가 직접 조작했다
        edge_key = f"{st.get('edge')}@{st.get('source')}"
        if st.get("source") == "manual" and edge_key != self._seen_manual_edge:
            self._seen_manual_edge = edge_key
            self.manual_until = now + self.hold_s
            self._mismatch_since = None
        if self.manual_until is not None:
            if now < self.manual_until:
                return "hold"
            self.manual_until = None
            self._bump(now)                            # 보류 끝 — 같은 명령이라도 다시 쏘게 한다
        if self.failed:
            return "failed"
        observed_on = st.get("state", "off") != "off"
        if key is not None and key != self._last_key:  # 명령 내용이 바뀌었다 — 확인 재송신 예약
            self._last_key, self._confirm_at = key, now + self.wait_s
        if self._confirm_at is not None and now >= self._confirm_at:
            self._confirm_at = None
            self._bump(now)                            # 켜짐/꺼짐은 아래에서 전력으로 따로 확인한다
        elif now - self._last_bump >= self.refresh_s:
            self._bump(now)                            # 주기 상태 동기화
        if want_on != self._last_want:                 # 원하는 상태가 바뀌었다 — 새 명령, 재송신 횟수 초기화
            self._last_want, self.resends, self._mismatch_since = want_on, 0, None
        if not st or want_on == observed_on:
            self._mismatch_since = None
            return "send"
        self._mismatch_since = self._mismatch_since if self._mismatch_since is not None else now
        if now - self._mismatch_since >= self.wait_s:
            if self.resends < self.max_resend:
                self.resends += 1
                self._bump(now)                        # 브릿지가 바뀐 명령으로 보고 다시 송신한다
                self._mismatch_since = now
            else:
                self.failed = True
                self.alerts.append({"code": "E9", "level": "warning", "t": now,
                                    "msg": f"에어컨 무응답 — 재송신 {self.max_resend}회 실패 · 다른 수단으로 대체 (UNKNOWN)"})
                return "failed"
        return "send"

    def _bump(self, now: float) -> None:
        self.seq += 1
        self._last_bump = now
