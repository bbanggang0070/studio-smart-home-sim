"""EXP-5 방식 ① — v1.29 계획기(controller/energy.py EnergyPlanner)를 코드 그대로 쓴다 (docs/13 §3).

바꾸는 것은 입력뿐 — 학습 k주로 만든 2R2C · 귀가 이력 · GBM 파일, 에피소드의 요일 · 직전 귀가(관측 가능한 값).
v1.29 하네스는 요일이 없어 default_weekday 를 쓴다 — EXP-5 에피소드는 요일이 있으므로 그 값을 넣는다 (②도 같은 귀가 예측을 쓴다).
"""

from __future__ import annotations

import copy
from pathlib import Path

from exp5.common import Ctx, Episode, Obs, Policy

from controller.energy import EnergyPlanner, daylight_fn
from controller.params import ControllerParams


def planner_params(ctx: Ctx, gbm_file: Path) -> ControllerParams:
    th = copy.deepcopy(ctx.p.th)
    th["energy"]["arrival_gbm"]["model_file"] = str(gbm_file)
    return ControllerParams(th, ctx.p.modes)


def action_of(d: dict) -> str:
    """계획기 결정 → 에어컨 행동 (controller/rule_engine.py _away_ac 와 같은 대응)."""
    if d.get("precool_active"):
        return "cool"
    return "setback" if d.get("strategy") == "setback" else "off"


class PlannerPolicy(Policy):
    """① 질문별 모델 — 2R2C + 귀가 분포 + 기대비용 격자 탐색."""
    name = "m1_model"

    def __init__(self, ctx: Ctx, data: Path, planner_cls=EnergyPlanner, **kw):
        self.p = planner_params(ctx, data / "gbm.json")
        self.planner = planner_cls(self.p, data / "energy.yaml", ctx.lam, "auto", **kw)
        self.sp = ctx.sp

    def reset(self, ep: Episode, ctx: Ctx) -> None:
        self.planner.reset()
        self.planner.weekday = ep.weekday
        self.planner.prev_arrive_tod = ep.prev_arrive_tod

    def observe(self, o: Obs, dt_s: float) -> None:
        self.planner.observe(o.temp_c, o.outdoor_c, o.lux, 1.0 if o.occupied else 0.0, o.ac_w, dt_s)

    def act(self, o: Obs) -> str:
        d = self.planner.step(o.now_s, o.outdoor_c, daylight_fn(self.p, o.now_s, o.lux), self.sp)
        return action_of(d)
