"""Metric deviation (criteria step 3). Every threshold comes from Criteria (per-metric override, else [defaults]).

robust z = (value − median) / max(1.4826 × MAD, min_mad), signed so that positive = "worse" (worse_when).
DRIFTING if worse-z ≥ z_threshold on ≥ drift_days of the metric's last drift_window available days (within the
last baseline_days); IMPROVED symmetrically; NORMAL otherwise; INSUFFICIENT if too few days have a baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from kaiku_contracts.criteria import Criteria, MetricSpec

from .baseline import Baseline, baseline_for

DriftStatus = Literal["drifting", "improved", "normal", "insufficient"]


@dataclass(frozen=True)
class MetricDrift:
    metric: str
    status: DriftStatus
    z_last: float | None  # worse-signed z on the latest scored day (positive = worse)
    worse_days: int
    better_days: int
    scored_days: int
    value_last: float | None
    baseline: Baseline | None

    @property
    def direction(self) -> str:
        """Raw direction of the latest value vs the baseline median ("up"/"down")."""
        return "up" if (self.value_last or 0) >= (self.baseline.median if self.baseline else 0) else "down"


def baseline_of(m: MetricSpec, series: dict[date, float], day: date, crit: Criteria) -> Baseline | None:
    return baseline_for(series, day, window=int(crit.param(m, "baseline_days")),
                        min_days=int(crit.param(m, "baseline_min_days")), min_mad=float(crit.param(m, "min_mad")),
                        lag=crit.defaults.baseline_lag_days)


def worse_z(value: float, base: Baseline, worse_when: str) -> float:
    z = (value - base.median) / base.scale
    return z if worse_when == "up" else -z


def drift_for(m: MetricSpec, series: dict[date, float], day: date, crit: Criteria) -> MetricDrift:
    thr = float(crit.param(m, "z_threshold"))
    need = int(crit.param(m, "drift_days"))
    window = int(crit.param(m, "drift_window"))
    bdays = int(crit.param(m, "baseline_days"))
    recent = sorted(d for d in series if day - timedelta(days=bdays) < d <= day)[-window:]
    zs: list[float] = []
    base_last = None
    for d in recent:
        b = baseline_of(m, series, d, crit)
        if b is not None:
            zs.append(worse_z(series[d], b, m.worse_when))
            base_last = b
    value_last = series[recent[-1]] if recent else None
    if len(zs) < need:
        return MetricDrift(m.name, "insufficient", round(zs[-1], 2) if zs else None, 0, 0, len(zs), value_last,
                           base_last)
    worse = sum(z >= thr for z in zs)
    better = sum(z <= -thr for z in zs)
    status: DriftStatus = "drifting" if worse >= need else "improved" if better >= need else "normal"
    return MetricDrift(m.name, status, round(zs[-1], 2), worse, better, len(zs), value_last, base_last)
