"""분위수 GBM 귀가 예측 — 평가기 (docs/08 §5.3 · EXP-2). numpy 만 쓴다 (ROS 컨테이너에 scikit-learn 없음).

학습은 tools/energy/train_arrival_gbm.py (scikit-learn GradientBoostingRegressor, loss='quantile') — 나무들을 JSON 으로 내보낸다.
  특성   weekday(0=월) · is_weekend · depart_h(출발 시각) · prev_arrive_h(직전 주 귀가 시각)
  출력   분위수별 귀가 시각 [h, 출발한 날 0시 기준 — 24 이상이면 다음날]
분포   분위수 사이는 선형 보간한 역누적분포 · 양 끝은 가장 가까운 분위수 간격만큼 늘린다
조건부 '지금까지 안 돌아왔다' → 누적확률 F(지금) 위쪽에서만 뽑는다
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

FEATURES = ("weekday", "is_weekend", "depart_h", "prev_arrive_h")


def _tree_predict(t: dict, x: np.ndarray) -> float:
    n = 0
    left, right, feat, thr, val = t["left"], t["right"], t["feature"], t["threshold"], t["value"]
    while left[n] != -1:
        n = left[n] if x[feat[n]] <= thr[n] else right[n]
    return val[n]


class ArrivalGBM:
    def __init__(self, path: str | Path):
        m = json.loads(Path(path).read_text(encoding="utf-8"))
        assert tuple(m["features"]) == FEATURES, m["features"]
        self.q = np.asarray(m["quantiles"], float)
        self.models = m["models"]

    @staticmethod
    def features(weekday: int, depart_h: float, prev_arrive_h: float) -> np.ndarray:
        return np.array([weekday, 1.0 if weekday >= 5 else 0.0, depart_h, prev_arrive_h], float)

    def quantiles_h(self, x: np.ndarray) -> np.ndarray:
        out = [m["init"] + m["lr"] * sum(_tree_predict(t, x) for t in m["trees"]) for m in self.models]
        return np.maximum.accumulate(np.asarray(out, float))       # 분위수 교차 방지 (단조)

    def _cdf_knots(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        qh = self.quantiles_h(x)
        lo = qh[0] - (qh[1] - qh[0]) * self.q[0] / max(self.q[1] - self.q[0], 1e-9)
        hi = qh[-1] + (qh[-1] - qh[-2]) * (1 - self.q[-1]) / max(self.q[-1] - self.q[-2], 1e-9)
        return np.concatenate([[0.0], self.q, [1.0]]), np.concatenate([[lo], qh, [hi]])

    def conditional_quantiles_h(self, x: np.ndarray, now_h: float, probs) -> np.ndarray:
        """'now_h 까지 안 돌아왔다'는 조건에서의 분위수 [h]."""
        p, h = self._cdf_knots(x)
        f_now = float(np.interp(now_h, h, p))
        u = f_now + (1.0 - f_now) * np.asarray(probs, float)
        return np.maximum(np.interp(u, p, h), now_h)

    def sample_h(self, x: np.ndarray, now_h: float, n: int, rng) -> np.ndarray:
        return self.conditional_quantiles_h(x, now_h, rng.random(n))
