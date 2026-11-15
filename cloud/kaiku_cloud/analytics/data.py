"""PatientData: everything the rule needs, extracted ONCE from a patient's events under a given Criteria.

Pure data, no I/O. verdict.py / consensus.py evaluate it for any day, so the same code serves live recompute,
the day-by-day hysteresis replay, criteria previews and the simulation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from kaiku_contracts.criteria import Criteria
from kaiku_contracts.sources import CONSENSUS_SOURCES, SOURCE_OF

from .metrics import Series, daily_metrics, observation_day, parse_ts


@dataclass(frozen=True)
class Reading:
    ts: datetime
    day: date
    value: float


@dataclass(frozen=True)
class Phq9Point:
    ts: datetime
    day: date
    total: int
    item9_positive: bool
    mode: str


@dataclass
class PatientData:
    home_id: str
    series: dict[str, Series]  # enabled metrics only (names from criteria), scored and shown alike
    source_days: dict[str, dict[date, list[float]]]  # source -> day -> qualities (for confidence); never from a
    # type that only shown metrics read
    last_data_at: dict[str, datetime]
    rule_readings: dict[str, list[Reading]]  # rule name -> chronological readings of its obs.field
    safety_flags: list[datetime]
    acks: list[tuple[datetime, str | None]]  # (ts, by)
    last_activity_at: datetime | None
    sim: bool
    first_day: date | None
    phq9: list[Phq9Point] = field(default_factory=list)  # history view (not a criterion)
    interventions: list[dict[str, Any]] = field(default_factory=list)
    nudge_outcomes: list[dict[str, Any]] = field(default_factory=list)
    rituals: list[datetime] = field(default_factory=list)
    outing_days: set[date] = field(default_factory=set)
    safety_local: set[datetime] = field(default_factory=set)  # flags whose payload says `handled_locally`


def build(home_id: str, events: list[dict[str, Any]], crit: Criteria, actions: list[dict[str, Any]] | None = None,
          exclude_sources: frozenset[str] = frozenset()) -> PatientData:
    """events: envelope dicts (json mode). exclude_sources: drop a consensus source (ablation / disabled source)."""
    exclude = set(exclude_sources) | {s for s in CONSENSUS_SOURCES if not crit.sources[s].enabled}
    if exclude:
        events = [e for e in events if SOURCE_OF.get(e["type"]) not in exclude]
    qmin = crit.defaults.quality_min
    source_days: dict[str, dict[date, list[float]]] = {s: defaultdict(list) for s in CONSENSUS_SOURCES}
    last_data_at: dict[str, datetime] = {}
    rules_by_obs: dict[str, list] = defaultdict(list)
    for r in crit.rules:
        if r.enabled:
            rules_by_obs[r.obs].append(r)
    rule_readings: dict[str, list[Reading]] = defaultdict(list)
    d = PatientData(home_id=home_id, series={}, source_days={}, last_data_at=last_data_at, rule_readings={},
                    safety_flags=[], acks=[], last_activity_at=None, sim=False, first_day=None)
    # Observation types that only `role = "shown"` metrics read (camera face signs, D52) are kept, charted and
    # cited, but the rule must not be able to see them: no coverage, no freshness, no first day of the record.
    shown_only = crit.shown_types
    for e in events:
        ts = parse_ts(e["ts"])
        day = observation_day(e, crit)
        if d.last_activity_at is None or ts > d.last_activity_at:
            d.last_activity_at = ts
        d.sim = d.sim or bool(e.get("sim"))
        if e["type"] in shown_only:
            continue
        if d.first_day is None or day < d.first_day:
            d.first_day = day
        role = SOURCE_OF.get(e["type"])
        q = e.get("quality")
        if role in source_days and (q is None or q >= qmin):
            source_days[role][day].append(1.0 if q is None else float(q))
            if role not in last_data_at or ts > last_data_at[role]:
                last_data_at[role] = ts
        p = e["payload"]
        for r in rules_by_obs.get(e["type"], ()):
            v = p.get(r.field)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                rule_readings[r.name].append(Reading(ts, day, float(v)))
        t = e["type"]
        if t == "obs.phq9":
            d.phq9.append(Phq9Point(ts, day, int(p["total"]), bool(p["item9_positive"]), p.get("mode", "laptop")))
        elif t == "obs.safety_flag":
            d.safety_flags.append(ts)
            if p.get("handled_locally") is True:
                d.safety_local.add(ts)
        elif t == "obs.intervention_response":
            d.interventions.append({**p, "_ts": ts})
        elif t == "obs.nudge_outcome":
            d.nudge_outcomes.append({**p, "_ts": ts})
        elif t == "obs.outing":
            d.outing_days.add(day)
        elif t == "obs.ritual" and p.get("step") == "close" and p.get("status") == "completed":
            d.rituals.append(ts)
    d.source_days = {s: dict(v) for s, v in source_days.items()}
    spans = {s: (min(v), max(v)) for s, v in d.source_days.items() if v}
    d.series = daily_metrics(events, crit, spans)
    d.rule_readings = {k: sorted(v, key=lambda r: r.ts) for k, v in rule_readings.items()}
    d.acks = sorted((parse_ts(a["ts"]), a.get("by")) for a in (actions or []) if a["action"] == "acknowledge")
    d.phq9.sort(key=lambda x: x.ts)
    d.safety_flags.sort()
    return d
