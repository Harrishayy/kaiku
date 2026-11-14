"""Per-person, per-metric robust baseline: median + MAD over `baseline_days` (criteria [defaults] / per metric).

scale = max(1.4826 × MAD, min_mad)  — min_mad is the noise floor so flat baselines don't explode z.
The window ends `lag` days before the scored day (criteria [defaults].baseline_lag_days, passed in by drift.py)
so a slow drift is not absorbed into its own baseline. Fewer than
`baseline_min_days` data points → no baseline → the metric is "insufficient".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

MAD_TO_SD = 1.4826


@dataclass(frozen=True)
class Baseline:
    median: float
    scale: float
    n: int
    early: bool = False  # provisional baseline of a young record (criteria [defaults].early_baseline_*)


def baseline_for(series: dict[date, float], day: date, *, window: int, min_days: int, min_mad: float,
                 lag: int) -> Baseline | None:
    end = day - timedelta(days=lag)
    start = end - timedelta(days=window)
    vals = [v for d, v in series.items() if start <= d < end]
    if len(vals) < min_days:
        return None
    med = median(vals)
    mad = median(abs(v - med) for v in vals)
    return Baseline(median=med, scale=max(MAD_TO_SD * mad, min_mad, 1e-9), n=len(vals))
