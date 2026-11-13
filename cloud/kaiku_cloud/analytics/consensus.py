"""Consensus (criteria step 5). Deterministic, unit-tested, fully driven by Criteria [state]. No LLM touches it.

  safety      any open safety flag (not yet acknowledged)                                  — overrides everything
  needs_call  ≥ needs_call_min_worse sufficient sources are "worse"
  watch       ≥ watch_min_worse are "worse", OR only one source is sufficient (watch_if_single_sufficient),
              OR fewer than min_sufficient_for_stable sources are sufficient            — thin data is never "stable"
  stable      otherwise
correlated families: if every worse source is worse only via families in `correlated_families`, the explanation
carries an independence caveat; with count_correlated_as_one, sources worse only via the same correlated family
count as ONE worse source.
hysteresis: needs_call holds until a clinician acknowledges or `hysteresis_stable_days` consecutive stable days —
implemented by replaying the rule day by day (no hidden mutable state).
agreement:  low_coverage (< 2 sufficient) | disagree (worse alongside as_usual/better) | agree
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from kaiku_contracts.api import Consensus, SourceVerdict
from kaiku_contracts.criteria import Criteria, StateSpec

from ..settings import TZ
from .data import PatientData
from .verdict import VerdictResult, all_verdicts

REPLAY_DAYS = 45
CORRELATED_NOTE = "correlated_only"


@dataclass
class DayResult:
    day: date
    raw: str
    state: str
    verdicts: list[SourceVerdict]
    agreement: str
    safety_since: datetime | None
    held: bool = False
    acknowledged_by: str | None = None
    state_since: date | None = None
    notes: list[str] = field(default_factory=list)
    correlated_families: list[str] = field(default_factory=list)


def _correlated_family(r: VerdictResult, corr: set[str]) -> str | None:
    """The single correlated family a worse source is worse through, or None."""
    fams = r.worse_families
    return next(iter(fams)) if len(fams) == 1 and fams <= corr else None


def worse_count(results: list[VerdictResult], st: StateSpec) -> int:
    worse = [r for r in results if r.model.verdict == "worse"]
    if not st.count_correlated_as_one:
        return len(worse)
    corr = set(st.correlated_families)
    groups = {_correlated_family(r, corr) for r in worse} - {None}
    independent = [r for r in worse if _correlated_family(r, corr) is None]
    return len(independent) + len(groups)


def correlated_only(results: list[VerdictResult], st: StateSpec) -> list[str]:
    """Families, if ≥ 2 sources are worse and ALL of them only via correlated families (else [])."""
    worse = [r for r in results if r.model.verdict == "worse"]
    corr = set(st.correlated_families)
    if len(worse) < 2 or not all(r.worse_families and r.worse_families <= corr for r in worse):
        return []
    return sorted(set().union(*(r.worse_families for r in worse)))


def raw_state(results: list[VerdictResult], safety_open: bool, st: StateSpec) -> tuple[str, str]:
    sufficient = [r for r in results if r.model.verdict != "insufficient"]
    n_worse = worse_count(sufficient, st)
    if len(sufficient) < 2:
        agreement = "low_coverage"
    elif n_worse and any(r.model.verdict in ("as_usual", "better") for r in sufficient):
        agreement = "disagree"
    else:
        agreement = "agree"
    if safety_open:
        return "safety", agreement
    if n_worse >= st.needs_call_min_worse:
        return "needs_call", agreement
    if (n_worse >= st.watch_min_worse or (st.watch_if_single_sufficient and len(sufficient) == 1)
            or len(sufficient) < st.min_sufficient_for_stable):
        return "watch", agreement
    return "stable", agreement


def open_safety(data: PatientData, until: datetime) -> datetime | None:
    """Earliest safety flag after the latest acknowledgement (both up to `until`)."""
    last_ack = max((t for t, _ in data.acks if t <= until), default=None)
    open_flags = [f for f in data.safety_flags if f <= until and (last_ack is None or f > last_ack)]
    return open_flags[0] if open_flags else None


def replay(data: PatientData, crit: Criteria, end: date, now: datetime | None = None) -> list[DayResult]:
    """Evaluate the rule for each day up to `end` (last REPLAY_DAYS), applying hysteresis forward."""
    now = now or datetime.now(UTC)
    st = crit.state
    start = max(data.first_day or end, end - timedelta(days=REPLAY_DAYS - 1))
    out: list[DayResult] = []
    prev: DayResult | None = None
    stable_streak = 0
    call_since: datetime | None = None
    d = start
    while d <= end:
        eod = datetime.combine(d + timedelta(days=1), time(0), TZ) if d < end else now
        results = all_verdicts(data, d, crit, now)
        since = open_safety(data, eod)
        raw, agreement = raw_state(results, since is not None, st)
        stable_streak = stable_streak + 1 if raw == "stable" else 0
        state, held = raw, False
        if prev is not None and prev.state == "needs_call" and raw in ("watch", "stable"):
            acked = any(call_since is not None and call_since <= t <= eod for t, _ in data.acks)
            if not acked and stable_streak < st.hysteresis_stable_days:
                state, held = "needs_call", True
        if state == "needs_call" and (prev is None or prev.state != "needs_call"):
            call_since = datetime.combine(d, time(0), TZ)
        ack_by = None
        if state in ("needs_call", "safety"):
            ref = call_since if state == "needs_call" else since
            ack_by = next((by or "clinician" for t, by in reversed(data.acks) if ref and ref <= t <= eod), None)
        state_since = prev.state_since if prev is not None and prev.state == state else d
        fams = correlated_only(results, st)
        res = DayResult(d, raw, state, [r.model for r in results], agreement, since, held, ack_by, state_since,
                        [CORRELATED_NOTE] if fams else [], fams)
        out.append(res)
        prev = res
        d += timedelta(days=1)
    return out


def compute(data: PatientData, crit: Criteria, end: date, now: datetime | None = None) -> tuple[Consensus, DayResult]:
    now = now or datetime.now(UTC)
    if data.first_day:
        last = replay(data, crit, end, now)[-1]
    else:
        results = all_verdicts(data, end, crit, now)
        raw, agreement = raw_state(results, False, crit.state)
        last = DayResult(end, raw, raw, [r.model for r in results], agreement, None)
    c = Consensus(home_id=data.home_id, state=last.state, rule_version=crit.rule_version, sources=last.verdicts,
                  agreement=last.agreement, explanation=None, acknowledged_by=last.acknowledged_by,
                  safety_since=last.safety_since, computed_at=now)
    return c, last
