"""Per-source verdict (criteria step 4). Source-agnostic and fully driven by Criteria:

  worse        sum(weight of drifting metrics) ≥ sources.<s>.worse_min_weight, or any enabled [[rule]] fires
  better       sum(weight of improving metrics with counts_for_better) ≥ better_min_weight and nothing worse
  insufficient confidence < min_confidence, or no metric has a usable baseline and no rule fired
  as_usual     otherwise
confidence = min(1, days with data in the last baseline_days / expected) × mean reading quality.
Rules look at the latest reading no older than criteria [defaults].rule_max_age_days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import fmean

from kaiku_contracts.api import SourceVerdict, VerdictEvidence
from kaiku_contracts.criteria import Criteria, RuleSpec

from .data import PatientData
from .drift import MetricDrift, drift_for


@dataclass
class VerdictResult:
    model: SourceVerdict
    worse_families: set[str]  # families of everything that made it worse (for the independence caveat)


def confidence(data: PatientData, source: str, day: date, crit: Criteria) -> float:
    window = crit.defaults.baseline_days
    days = data.source_days.get(source, {})
    recent = [qs for d, qs in days.items() if day - timedelta(days=window) < d <= day]
    if not recent:
        return 0.0
    expected = max(1.0, crit.sources[source].expected_per_week * window / 7)
    coverage = min(1.0, len(recent) / expected)
    return round(coverage * fmean(q for qs in recent for q in qs), 3)


def rule_fires(rule: RuleSpec, data: PatientData, day: date, crit: Criteria) -> VerdictEvidence | None:
    max_age = crit.defaults.rule_max_age_days
    pts = [r for r in data.rule_readings.get(rule.name, []) if r.day <= day]
    if not pts or (day - pts[-1].day).days > max_age:
        return None
    last, prev = pts[-1], (pts[-2] if len(pts) > 1 else None)
    fired = False
    detail = f"{last.value:g}"
    if rule.kind == "at_least":
        fired = last.value >= rule.threshold
    elif rule.kind == "at_most":
        fired = last.value <= rule.threshold
    elif prev is not None:
        change = last.value - prev.value
        detail = f"{last.value:g} (was {prev.value:g}, {change:+g})"
        fired = change >= rule.threshold if rule.kind == "rise_vs_previous" else -change >= rule.threshold
    if not fired:
        return None
    up = rule.kind in ("at_least", "rise_vs_previous")
    return VerdictEvidence(metric=rule.name, z=None, direction="up" if up else "down", days=1,
                           summary=f"{rule.label}: {detail}")


def _evidence(d: MetricDrift, crit: Criteria) -> VerdictEvidence:
    m = crit.metric(d.metric)
    raw_z = None if d.z_last is None else (d.z_last if m.worse_when == "up" else -d.z_last)
    days = d.worse_days if d.status == "drifting" else d.better_days
    word = "higher" if d.direction == "up" else "lower"
    return VerdictEvidence(metric=d.metric, z=raw_z, direction="up" if d.direction == "up" else "down", days=days,
                           summary=f"{m.label} {word} than usual on {days} of the last {d.scored_days} days")


def verdict_for(data: PatientData, source: str, day: date, crit: Criteria, now: datetime | None = None
                ) -> VerdictResult:
    spec = crit.sources[source]
    metrics = crit.metrics_for(source)
    drifts = [drift_for(m, data.series.get(m.name, {}), day, crit) for m in metrics]
    weight = {m.name: m.weight for m in metrics}
    better_ok = {m.name for m in metrics if m.counts_for_better}
    fired = [(r, ev) for r in crit.rules_for(source) if (ev := rule_fires(r, data, day, crit)) is not None]
    conf = confidence(data, source, day, crit)
    drifting = [d for d in drifts if d.status == "drifting"]
    improved = [d for d in drifts if d.status == "improved" and d.metric in better_ok]
    usable = [d for d in drifts if d.status != "insufficient"]

    evidence: list[VerdictEvidence] = []
    families: set[str] = set()
    if conf < spec.min_confidence or (not usable and not fired):
        verdict = "insufficient"
    elif sum(weight[d.metric] for d in drifting) >= spec.worse_min_weight or fired:
        verdict = "worse"
        evidence = [ev for _, ev in fired] + [_evidence(d, crit) for d in drifting]
        families = {r.family for r, _ in fired} | {crit.metric(d.metric).family for d in drifting}
    elif sum(weight[d.metric] for d in improved) >= spec.better_min_weight and not drifting:
        verdict = "better"
        evidence = [_evidence(d, crit) for d in improved]
    else:
        verdict = "as_usual"
        evidence = [_evidence(d, crit) for d in drifting]  # sub-threshold signals still shown
    evidence.sort(key=lambda e: -abs(e.z) if e.z is not None else -99)
    model = SourceVerdict(home_id=data.home_id, source=source, verdict=verdict, confidence=conf, evidence=evidence[:5],
                          last_data_at=data.last_data_at.get(source), computed_at=now or datetime.now(UTC))
    return VerdictResult(model, families)


def all_verdicts(data: PatientData, day: date, crit: Criteria, now: datetime | None = None) -> list[VerdictResult]:
    return [verdict_for(data, s, day, crit, now) for s in crit.active_sources()]
