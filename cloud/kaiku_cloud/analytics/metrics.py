"""Daily metric extraction, driven entirely by `Criteria` (config/criteria.toml). No metric is defined in code.

For each enabled [[metric]]: take its obs type's events, drop readings below its quality_min, apply its `where`
filters (equality / any-of), read `field` (a payload key, or derived "@count" / "@local_minutes"), aggregate per
local day with `agg`, and — for missing = "zero" — fill days without data with 0 over the span in which the
metric's source sent anything. The consensus source comes from the obs type (kaiku_contracts.sources).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import fmean, median
from typing import Any

from kaiku_contracts.criteria import Criteria, MetricSpec

from ..settings import TZ

Series = dict[date, float]

AGG = {
    "mean": fmean, "median": median, "min": min, "max": max, "sum": sum, "count": len,
    "first": lambda v: v[0], "last": lambda v: v[-1],
}


def parse_ts(ts: str | datetime) -> datetime:
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def local_date(ts: str | datetime) -> date:
    return parse_ts(ts).astimezone(TZ).date()


def _passes(where: dict[str, Any], p: dict[str, Any]) -> bool:
    for key, want in where.items():
        have = p.get(key)
        if isinstance(want, list):
            if have not in want:
                return False
        elif have != want:
            return False
    return True


def extract(m: MetricSpec, p: dict[str, Any], t_local: datetime) -> float | None:
    """One reading's value for metric m (None = this reading doesn't count)."""
    if not _passes(m.where, p):
        return None
    if m.field == "@count":
        return 1.0
    if m.field == "@local_minutes":
        return float(t_local.hour * 60 + t_local.minute)
    v = p.get(m.field)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else (1.0 if v is True else None)


def daily_metrics(events: list[dict[str, Any]], crit: Criteria, source_spans: dict[str, tuple[date, date]] | None = None,
                  include_disabled: bool = False) -> dict[str, Series]:
    """events: envelope dicts (json mode), any order. Returns {metric name: {local day: value}}."""
    by_type: dict[str, list[MetricSpec]] = defaultdict(list)
    for m in crit.metrics:
        if m.enabled or include_disabled:
            by_type[m.obs].append(m)
    buckets: dict[str, dict[date, list[tuple[datetime, float]]]] = defaultdict(lambda: defaultdict(list))
    for e in events:
        specs = by_type.get(e["type"])
        if not specs:
            continue
        t = parse_ts(e["ts"]).astimezone(TZ)
        q = e.get("quality")
        for m in specs:
            if q is not None and q < crit.param(m, "quality_min"):
                continue
            v = extract(m, e["payload"], t)
            if v is not None:
                buckets[m.name][t.date()].append((t, v))
    out: dict[str, Series] = {}
    for specs in by_type.values():
        for m in specs:
            per_day = buckets.get(m.name, {})
            series = {d: float(AGG[m.agg]([v for _, v in sorted(vals)])) for d, vals in per_day.items()}
            span = (source_spans or {}).get(m.source)
            if m.missing == "zero" and span:
                d = span[0]
                while d <= span[1]:
                    series.setdefault(d, 0.0)
                    d += timedelta(days=1)
            if series:
                out[m.name] = series
    return out
