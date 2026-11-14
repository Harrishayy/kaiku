"""GET /v1/debug/day — everything about one local day of one home, for developers.

Not for a practitioner and never for the person: it lists every stored envelope of the day, every criteria metric
beside its baseline, each signal group's verdict with its weights, the consensus with its reasons, the day's
conversations as enums (never words) and the model-call ledger. `api/auth.py` closes it like `/v1/admin`.

A past day is recomputed with today's criteria over the record as it stands: the metric values are the ones the
practitioner's chart has for that day, and the verdicts and the state are the rule's own replay ending on that day
(`analytics.consensus.replay`), with acknowledgements and safety flags counted only up to the day's end.

The day read (`DebugRead`) is a developer-facing reading of that same structured data. Code decides the `reading`
and writes the citable `facts` (each with the numbers and the yes/no flags a sentence citing it may state); Gemma
writes sentences that cite them, and code keeps a sentence only when its ids exist, every number in it is written
in a fact it cites and sits in its own role, every yes or no it states (held, acknowledged, an open safety flag, a
group's enough data, a measure scored, beyond or within its threshold on the day) is what a cited fact carries,
its wording passes the practitioner review's checks and it sits in the right section. A read is Gemma's when its
summary stands; a measure code chose as moved, the state's and the groups' lines about tomorrow and the rule check
are always there, in code's own words and marked `by_code` when the model's sentence was missing or failed.
Without a valid read (not requested, no provider, over budget, cooldown, nothing valid after one corrective
retry) the same shape is written by code and says so; an ask the model answered with nothing valid is kept with
its reason and rejection counts and not asked again until the day's data, the rule or the instruction changes.
The read never reaches the consensus: nothing here writes a summary, a verdict or a state.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from time import monotonic
from time import time as wall_time
from typing import Any

from kaiku_contracts import budget, wording
from kaiku_contracts.api import (
    DebugBaseline,
    DebugClaim,
    DebugConsensus,
    DebugConversation,
    DebugDay,
    DebugEvent,
    DebugFact,
    DebugFeel,
    DebugMetric,
    DebugModelCall,
    DebugRead,
    DebugVerdict,
)
from kaiku_contracts.config import get
from kaiku_contracts.criteria import Criteria, MetricSpec
from kaiku_contracts.jlog import get_logger
from kaiku_contracts.sources import SOURCE_LABELS, SOURCE_OF

from . import insight, service
from .analytics import consensus
from .analytics.data import PatientData
from .analytics.drift import baseline_of, drift_for, worse_z
from .analytics.metrics import daily_metrics, extract, observation_day, parse_ts
from .analytics.verdict import all_verdicts, rule_fires
from .llm import gemma, ledger
from .llm.errors import LlmUnavailable
from .llm.explain import contains_banned
from .mind import feel
from .settings import TZ, Settings
from .store.db import Store

READ_VERSION = "debug-read-v7"  # bump when the instruction or a check changes: retires cached reads
CLOCK_UNITS = ("min after midnight", "min from midnight")
NO_MODEL = ("deterministic", "scripted", "template", "rule")
SECTION_KIND = {"moved": "metric", "missing": "missing", "tomorrow": "tomorrow", "rule_check": "consensus"}
KEPT_FAILURES = ("invalid_json", "no_valid_claims")  # the model answered and nothing was valid: not asked again
MAX_CITES = 8  # the instruction asks for six at most; a sentence resting on one or two more is still checked whole
READING_WORDS = {"as_usual": "as usual", "slight_shift": "a slight shift", "clear_shift": "a clear shift",
                 "not_enough_data": "not enough data to say"}
log = get_logger("cloud.debug_day")
_NUMBER = re.compile(r"(?<![A-Za-z])-?\d+(?:\.\d+)?")
_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)


def cfg(key: str, default: Any) -> Any:
    return get("debug_day", key, default)


def bounds(day: date) -> tuple[datetime, datetime]:
    """The local day as two UTC instants: [start, end)."""
    start = datetime.combine(day, time(0), TZ)
    return start.astimezone(UTC), datetime.combine(day + timedelta(days=1), time(0), TZ).astimezone(UTC)


def _n(x: float) -> str:
    """A number as it is printed in a fact (two decimals at most, no exponent)."""
    return f"{round(float(x), 2):.2f}".rstrip("0").rstrip(".") or "0"


def _clock(minutes: float) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _cut(text: str, n: int) -> str:
    """At most n characters, ending at the end of an item (never in the middle of one)."""
    if len(text) <= n:
        return text
    head = text[:n - 2]
    return head[:max(head.rfind("; "), head.rfind(". "))].rstrip(";. ") + " …"


def _compact(v: Any, n: int) -> Any:
    if isinstance(v, dict):
        return {k: _compact(x, n) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [*(_compact(x, n) for x in v[:n]), f"(+{len(v) - n} more)"] if len(v) > n else [_compact(x, n) for x in v]
    if isinstance(v, float):
        return round(v, 3)
    return v[:120] + "…" if isinstance(v, str) and len(v) > 120 else v


# ------------------------------------------------------------------ the day's data
def _counted(e: dict[str, Any], specs: list[MetricSpec], crit: Criteria) -> list[str]:
    """The metrics one envelope counted toward, by the analytics' own reading rules."""
    t = parse_ts(e["ts"]).astimezone(TZ)
    q = e.get("quality")
    return [m.name for m in specs
            if not (q is not None and q < crit.param(m, "quality_min")) and extract(m, e["payload"], t) is not None]


def _events(events: list[dict[str, Any]], day: date, crit: Criteria
            ) -> tuple[list[DebugEvent], dict[str, list[str]]]:
    start, end = bounds(day)
    by_type: dict[str, list[MetricSpec]] = defaultdict(list)
    for m in crit.metrics:
        by_type[m.obs].append(m)
    n = int(cfg("payload_list_items", 8))
    out: list[DebugEvent] = []
    ids: dict[str, list[str]] = defaultdict(list)
    for e in sorted(events, key=lambda e: parse_ts(e["ts"])):
        ts = parse_ts(e["ts"])
        counts_on = observation_day(e, crit)
        measured = counts_on == day
        if not (start <= ts < end or measured):
            continue
        names = _counted(e, by_type.get(e["type"], []), crit)
        for name in names if measured else ():  # a summary stamped today that measures another day counts there
            ids[name].append(str(e["id"]))
        out.append(DebugEvent(id=str(e["id"]), ts=ts, local_time=ts.astimezone(TZ).strftime("%H:%M:%S"),
                              source=e["source"], type=e["type"], sim=bool(e.get("sim")), quality=e.get("quality"),
                              payload=_compact(e["payload"], n), metrics=names, day=counts_on))
    return out, ids


def _series(m: MetricSpec, full: dict[str, dict[date, float]], today: date) -> dict[date, float]:
    """The metric's days as the rule reads them: today's running total of a sum or a count is not there yet."""
    s = full.get(m.name, {})
    return {d: v for d, v in s.items() if d < today} if m.agg in service.CUMULATIVE else s


def _window(m: MetricSpec, series: dict[date, float], day: date, crit: Criteria) -> list[float]:
    """The worse-signed z of each of the metric's last scored days up to `day` (the days drift_for counts)."""
    window, bdays = int(crit.param(m, "drift_window")), int(crit.param(m, "baseline_days"))
    out = []
    for d in sorted(x for x in series if day - timedelta(days=bdays) < x <= day)[-window:]:
        b = baseline_of(m, series, d, crit)
        if b is not None:
            out.append(worse_z(series[d], b, m.worse_when))
    return out


def _metrics(crit: Criteria, full: dict[str, dict[date, float]], day: date, today: date,
             ids: dict[str, list[str]]) -> list[DebugMetric]:
    out: list[DebugMetric] = []
    active = set(crit.active_sources())
    keep = int(cfg("event_ids_per_metric", 20))
    for m in crit.metrics:
        if m.source not in active:
            continue
        series = _series(m, full, today)
        value = full.get(m.name, {}).get(day)
        partial = value is not None and day not in series
        base = baseline_of(m, series, day, crit)
        d = drift_for(m, series, day, crit)
        z = wz = None
        if value is not None and base is not None and not partial:
            z, wz = (value - base.median) / base.scale, worse_z(value, base, m.worse_when)
        thr = float(crit.param(m, "z_threshold"))
        scored = m.votes  # enabled, role scored, weight above zero; a shown metric is listed and never a vote
        zs = _window(m, series, day, crit)  # counted here so a metric with too few scored days still shows them
        out.append(DebugMetric(
            id=f"metric:{m.name}", metric=m.name, label=m.label, unit=m.unit, source=m.source, obs=m.obs, value=value,
            partial=partial, readings=len(ids.get(m.name, [])),
            baseline=DebugBaseline(median=base.median, spread=base.scale, days=base.n, early=base.early) if base else None,
            z=None if z is None else round(z, 2), worse_z=None if wz is None else round(wz, 2), direction=m.worse_when,
            z_threshold=thr, beyond_today=wz is not None and wz >= thr, status=d.status,
            worse_days=sum(z >= thr for z in zs), better_days=sum(z <= -thr for z in zs), scored_days=len(zs),
            drift_days_needed=int(crit.param(m, "drift_days")),
            weight=m.weight, enabled=m.enabled, scored=scored, flagged=scored and d.status == "drifting",
            event_ids=ids.get(m.name, [])[:keep]))
    return out


def _verdicts(crit: Criteria, data: PatientData, metrics: list[DebugMetric], last: consensus.DayResult,
              prev: consensus.DayResult | None, day: date, events: list[dict[str, Any]]) -> list[DebugVerdict]:
    _start, end = bounds(day)
    seen: dict[str, datetime] = {}
    for e in events:
        role, ts = SOURCE_OF.get(e["type"]), parse_ts(e["ts"])
        if e["type"] in crit.shown_types:
            continue  # shown, not scored: it does not make its group look fresh (analytics/data.py)
        if role and ts < end and (role not in seen or ts > seen[role]):
            seen[role] = ts
    before = {v.source: v.verdict for v in prev.verdicts} if prev else {}
    better_ok = {m.name for m in crit.metrics if m.counts_for_better}
    window = crit.defaults.baseline_days
    out = []
    for v in last.verdicts:
        spec = crit.sources[v.source]
        mine = [m for m in metrics if m.source == v.source and m.scored]
        had = [d for d in data.source_days.get(v.source, {}) if d <= day]
        why = None
        if v.verdict == "insufficient":  # the rule's own order (analytics/verdict.py)
            why = ("stale" if not had or (day - max(had)).days > spec.max_age_days
                   else "low_confidence" if v.confidence < spec.min_confidence else "no_usable_metric")
        out.append(DebugVerdict(
            id=f"source:{v.source}", source=v.source, label=SOURCE_LABELS[v.source], verdict=v.verdict,
            confidence=v.confidence, min_confidence=spec.min_confidence,
            worse_weight=round(sum(m.weight for m in mine if m.status == "drifting"), 3),
            worse_min_weight=spec.worse_min_weight,
            better_weight=round(sum(m.weight for m in mine if m.status == "improved" and m.metric in better_ok), 3),
            better_min_weight=spec.better_min_weight,
            rules_fired=[r.name for r in crit.rules_for(v.source) if rule_fires(r, data, day, crit) is not None],
            evidence=v.evidence,
            days_with_data=sum(1 for d in data.source_days.get(v.source, {}) if day - timedelta(days=window) < d <= day),
            last_data_at=seen.get(v.source), previous=before.get(v.source), insufficient_reason=why))  # type: ignore[arg-type]
    return out


def _consensus(crit: Criteria, data: PatientData, last: consensus.DayResult, prev: consensus.DayResult | None,
               results: list[Any], metrics: list[DebugMetric], before: dict[str, str], day: date) -> DebugConsensus:
    st = crit.state
    sufficient = [r for r in results if r.model.verdict != "insufficient"]
    worse = [r.model.source for r in sufficient if r.model.verdict == "worse"]
    counted = consensus.worse_count(sufficient, st)
    reasons: list[str] = []
    if last.safety_since is not None:
        reasons.append("an open safety flag overrides everything else")
    reasons.append(f"{len(worse)} of {len(sufficient)} signal groups with enough data are worse"
                   f"{' (' + ', '.join(worse) + ')' if worse else ''}; needs_call takes {st.needs_call_min_worse}, "
                   f"watch takes {st.watch_min_worse}")
    if counted != len(worse):
        reasons.append(f"groups that are worse only through the same correlated family count as one: {counted} counted")
    if st.watch_if_single_sufficient and len(sufficient) == 1:
        reasons.append("only one signal group has enough data: watch at least")
    if len(sufficient) < st.min_sufficient_for_stable:
        reasons.append(f"fewer than {st.min_sufficient_for_stable} signal groups have enough data: never stable")
    if last.held:
        reasons.append(f"needs_call is held: the day alone gives {last.raw}; it stays until a clinician acknowledges "
                       f"or {st.hysteresis_stable_days} stable days in a row")
    if last.raw == "stable" and last.state == "watch" and data.first_day is not None:
        reasons.append(f"day {(day - data.first_day).days + 1} of the record: never stable before day "
                       f"{st.min_history_days_for_stable}")
    if last.acknowledged_by:
        reasons.append(f"acknowledged by {last.acknowledged_by}")
    if last.correlated_families:
        reasons.append("every worse group is worse only through correlated families: "
                       + ", ".join(last.correlated_families))
    changed: list[str] = []
    if prev is not None:
        if prev.state != last.state:
            changed.append(f"state {prev.state} -> {last.state}")
        if prev.held != last.held:
            changed.append("needs_call now held by hysteresis" if last.held else "no longer held by hysteresis")
        if prev.acknowledged_by != last.acknowledged_by and last.acknowledged_by:
            changed.append(f"acknowledged by {last.acknowledged_by}")
        was = {v.source: v.verdict for v in prev.verdicts}
        changed += [f"{v.source}: {was[v.source]} -> {v.verdict}" for v in last.verdicts
                    if v.source in was and was[v.source] != v.verdict]
        changed += [f"{m.metric}: {before[m.metric]} -> {m.status}" for m in metrics
                    if m.scored and m.metric in before and before[m.metric] != m.status]
    return DebugConsensus(state=last.state, raw_state=last.raw, held=last.held, agreement=last.agreement,  # type: ignore[arg-type]
                          rule_version=crit.rule_version, reasons=reasons, previous_state=prev.state if prev else None,  # type: ignore[arg-type]
                          changed=changed, acknowledged_by=last.acknowledged_by, safety_since=last.safety_since,
                          state_since=last.state_since)


def _conversations(store: Store, home_id: str, day: date) -> list[DebugConversation]:
    start, end = bounds(day)
    moments = store.kv_get(feel._key(home_id)) or {}
    billed: dict[str, float] = defaultdict(float)
    for t in budget.live_reservations():
        if t["session"]:
            billed[t["session"]] += t["billed_min"] if t["settled"] else t["minutes"]
    out = []
    for ep in store.episodes(home_id):
        began = parse_ts(ep["start"])
        if not start <= began < end:
            continue
        ended = parse_ts(ep["end"]) if ep.get("end") else None
        tools = list(ep.get("tools") or [])
        # Each tool call is appended as it happens; the device's upload then replaces the list with one of each,
        # sorted (mind/session.py record_episode, which leaves a marker). Without the marker a closed
        # conversation whose list could be either cannot be told apart.
        if store.kv_get(f"episode-uploaded:{home_id}:{ep['id']}") is not None:
            in_order: bool | None = len(tools) <= 1
        else:
            in_order = True if ended is None or len(tools) <= 1 or tools != sorted(set(tools)) else None
        out.append(DebugConversation(
            session_id=ep["id"], surface=ep["surface"], intent=ep["intent"], start=began, end=ended,
            minutes=round((ended - began).total_seconds() / 60, 1) if ended else None, outcome=ep.get("outcome"),
            tools=tools, tools_in_order=in_order,
            feel=[DebugFeel(ts=parse_ts(m["ts"]), kind=m["kind"], valence=m["valence"], energy=m.get("energy"),
                            tone=list(m.get("tone") or []), via=m.get("via"), stance=m.get("stance"),
                            depth=m.get("depth"), offered=m.get("offered"))
                  for m in (moments.get(ep["id"]) or {}).get("moments", [])],
            billed_minutes=billed.get(ep["id"]), transcript_kept=store.transcript_exists(home_id, ep["id"])))
    return out


def provider_of(model: str) -> str:
    if model in NO_MODEL:
        return "none"
    if "/" in model:
        return "modal"
    return "gemma-hosted" if model.startswith("gemma") else "gemini" if model.startswith(("gemini", "lyria")) else "other"


def _model_calls(store: Store, home_id: str, day: date) -> list[DebugModelCall]:
    """This home's rows of the content-free ledger for the day, each beside the spend ledger's estimate when one
    row there has the same model and task and was reserved while the call ran."""
    start, end = bounds(day)
    calls = [r for r in store.model_calls(start.isoformat()) if r["home_id"] == home_id and parse_ts(r["ts"]) < end]
    spend = budget.rows(start.timestamp() - 120, end.timestamp() + 5)
    live = {t["ts"]: t["cost"] for t in budget.live_reservations()}
    used: set[int] = set()
    out = []
    for r in calls:
        ts = parse_ts(r["ts"])
        took = (r["latency_ms"] or 0) / 1000
        est = None
        near = [(abs(s["ts"] - (ts.timestamp() - took)), i) for i, s in enumerate(spend)
                if i not in used and s["model"] == r["model"] and s["task"] == r["task"]
                and ts.timestamp() - took - 3 <= s["ts"] <= ts.timestamp() + 1]
        if near:
            _gap, i = min(near)
            used.add(i)
            est = round(float(live.get(spend[i]["ts"], spend[i]["usd"])), 6)
        out.append(DebugModelCall(ts=ts, provider=provider_of(r["model"]), model=r["model"], task=r["task"],
                                  route=r["route"], ok=bool(r["ok"]), fallback=bool(r["fallback"]),
                                  latency_ms=r["latency_ms"], est_usd=est))
    return out


# ------------------------------------------------------------------ facts the read may cite
def _fact(id_: str, kind: str, label: str, detail: str, flags: dict[str, bool] | None = None) -> DebugFact:
    """One citable line. Its length is bounded by what it lists (every list in a fact has its own cap), never by
    cutting the text: a cut would end a sentence in the middle of an item."""
    numbers = sorted({abs(float(x)) for x in _NUMBER.findall(f"{label} {detail}")})
    return DebugFact(id=id_, kind=kind, label=label, detail=detail, numbers=numbers, flags=flags or {})  # type: ignore[arg-type]


def metric_fact(m: DebugMetric) -> DebugFact | None:
    if m.value is None:
        return None
    clock = m.unit in CLOCK_UNITS
    show = (lambda v: f"{_n(v)} ({_clock(v)})") if clock else _n
    parts = [f"{show(m.value)} on this day from {m.readings} reading{'s' if m.readings != 1 else ''}"
             if m.readings else f"{show(m.value)} on this day, counted by the rule for a day without a reading"]
    b = m.baseline
    if m.partial:
        parts.append("today's running total: not compared or scored until the day is over")
    if b is None:
        parts.append("no baseline yet")
    else:
        parts.append(f"usual {show(b.median)} with spread {_n(b.spread)} from a baseline of {b.days} days"
                     f"{' (early baseline)' if b.early else ''}")
    if b is not None and m.z is not None and m.worse_z is not None:
        delta = m.value - b.median
        if round(delta, 2) == 0:
            parts.append("at its usual")
        else:
            pct = f", {_n(round(abs(delta) / abs(b.median) * 100))}%" if b.median else ""
            parts.append(f"{_n(abs(delta))} {'above' if delta > 0 else 'below'} usual{pct}")
        side = ("beyond its threshold in the worse direction" if m.beyond_today
                else "beyond its threshold in the better direction" if m.worse_z <= -m.z_threshold
                else "within its threshold")
        parts.append(f"{_n(abs(m.z))} spreads {'above' if m.z > 0 else 'below'} usual (z {_n(m.z)}), threshold "
                     f"{_n(m.z_threshold)}, worse is {m.direction}: {side} on this day")
    parts.append(f"beyond its threshold in the worse direction on {m.worse_days} of the last {m.scored_days} scored "
                 f"days, in the better direction on {m.better_days}; {m.drift_days_needed} such days make a drift; "
                 f"status {m.status}")
    parts.append(f"weight {_n(m.weight)}, scored" if m.scored else "observe-only, never a vote")
    flags = {"scored": m.scored}
    if m.worse_z is not None:
        flags["beyond"] = abs(m.worse_z) >= m.z_threshold
        flags["within"] = not flags["beyond"]
    return _fact(m.id, "metric", f"{m.label}{f' ({m.unit})' if m.unit else ''}", "; ".join(parts) + ".", flags)


def verdict_fact(v: DebugVerdict, metrics: list[DebugMetric]) -> DebugFact:
    drifting = [m.label for m in metrics if m.source == v.source and m.flagged]
    why = {"stale": "its last data is older than the rule allows", "low_confidence": "its confidence is too low",
           "no_usable_metric": "no scored measure has a usable baseline and no rule fired"}
    parts = [f"verdict {v.verdict}" + (f" (the day before: {v.previous})" if v.previous else "")
             + (f": it does not have enough data, {why[v.insufficient_reason]}" if v.insufficient_reason
                else ": it has enough data"),
             f"confidence {_n(v.confidence)}, needs {_n(v.min_confidence)}",
             f"worse weight {_n(v.worse_weight)}, needs {_n(v.worse_min_weight)}",
             f"better weight {_n(v.better_weight)}, needs {_n(v.better_min_weight)}",
             f"rules fired: {', '.join(v.rules_fired) or 'none'}",
             f"data on {v.days_with_data} days of the baseline window",
             f"drifting scored measures: {', '.join(drifting) or 'none'}"]
    return _fact(v.id, "source", v.label, "; ".join(parts) + ".", {"enough_data": v.verdict != "insufficient"})


def reading_of(metrics: list[DebugMetric]) -> str:
    """Code's own call on the day, from the scored measures that have a value and a baseline on it."""
    scored = [m for m in metrics if m.scored and m.worse_z is not None]
    if len(scored) < int(cfg("min_scored", 3)):
        return "not_enough_data"
    beyond = [m for m in scored if abs(m.worse_z or 0) >= m.z_threshold]
    if len(beyond) >= int(cfg("clear_beyond", 2)):
        return "clear_shift"
    return "slight_shift" if beyond or any(abs(m.worse_z or 0) >= float(cfg("slight_z", 1.0)) for m in scored) \
        else "as_usual"


def consensus_fact(c: DebugConsensus, metrics: list[DebugMetric], day: date, data: PatientData) -> DebugFact:
    scored = [m for m in metrics if m.scored and m.worse_z is not None]
    worse = sum(1 for m in scored if m.beyond_today)
    better = sum(1 for m in scored if (m.worse_z or 0) <= -m.z_threshold)
    slight = float(cfg("slight_z", 1.0))
    far = sum(1 for m in scored if abs(m.worse_z or 0) >= slight)
    n = (day - data.first_day).days + 1 if data.first_day is not None and data.first_day <= day else 0
    keep = int(cfg("changed_max", 12))  # the state's own changes come first in the list; the measures are capped
    # by label, as a sentence would name them (`consensus.changed` keeps the keys for the developer)
    label = {**SOURCE_LABELS, **{m.metric: m.label for m in metrics}}
    named = [f"{label[k]}: {rest}" if sep and k in label else item
             for item in c.changed for k, sep, rest in [item.partition(": ")]]
    changed = named[:keep] + ([f"and {len(named) - keep} more measures"] if len(named) > keep else [])
    parts = [f"state {c.state}; the day alone gives {c.raw_state}; agreement {c.agreement}; the day before: "
             f"{c.previous_state or 'no day before'}",
             ("the state is held by hysteresis" if c.held else "the state is not held by hysteresis") + "; "
             + (f"it is acknowledged by {c.acknowledged_by}" if c.acknowledged_by else "it is not acknowledged") + "; "
             + ("a safety flag is open" if c.safety_since is not None else "no safety flag is open"),
             f"day {n} of the record",
             f"on this day {len(scored)} scored measures have a value and a baseline: {worse} beyond their threshold "
             f"in the worse direction, {better} in the better, {far} at least {_n(slight)} spreads from their usual; "
             f"the day itself reads as {READING_WORDS[reading_of(metrics)]}",
             "why: " + "; ".join(c.reasons),
             "changed since the day before: " + ("; ".join(changed) if changed else "nothing")]
    return _fact(c.id, "consensus", "Consensus", ". ".join(parts) + ".",
                 {"held": c.held, "acknowledged": c.acknowledged_by is not None, "safety": c.safety_since is not None,
                  "beyond": worse + better > 0, "within": len(scored) > worse + better})


def tomorrow_facts(crit: Criteria, full: dict[str, dict[date, float]], metrics: list[DebugMetric],
                   verdicts: list[DebugVerdict], c: DebugConsensus, day: date, today: date) -> list[DebugFact]:
    """What one more day could change, worked out from the rule's own windows. One more scored day is added to each
    metric's window as beyond or as within its threshold; nothing else is assumed."""
    facts: list[DebugFact] = []
    spec = {m.name: m for m in crit.metrics}
    could_start: dict[str, list[DebugMetric]] = defaultdict(list)
    could_stop: dict[str, list[DebugMetric]] = defaultdict(list)
    for m in metrics:
        if not m.scored or m.status == "insufficient":
            continue
        s = spec[m.metric]
        flags = [z >= m.z_threshold for z in _window(s, _series(s, full, today), day, crit)]
        window, need = int(crit.param(s, "drift_window")), m.drift_days_needed
        if m.status != "drifting" and sum([*flags, True][-window:]) >= need:
            could_start[m.source].append(m)
            facts.append(_fact(f"tomorrow:{m.metric}", "tomorrow", f"{m.label} tomorrow",
                               f"One more day beyond its threshold in the worse direction makes {m.label} a drift: "
                               f"{m.worse_days} of its last {m.scored_days} scored days are beyond now, {need} make "
                               f"a drift; weight {_n(m.weight)}."))
        elif m.status == "drifting" and sum([*flags, False][-window:]) < need:
            could_stop[m.source].append(m)
            facts.append(_fact(f"tomorrow:{m.metric}", "tomorrow", f"{m.label} tomorrow",
                               f"One day within its threshold ends the drift of {m.label}: {m.worse_days} of its "
                               f"last {m.scored_days} scored days are beyond now, {need} make a drift; weight "
                               f"{_n(m.weight)}."))
    up, down = [], []
    for v in verdicts:
        gain = sum(m.weight for m in could_start[v.source])
        loss = sum(m.weight for m in could_stop[v.source])
        if v.verdict in ("as_usual", "better") and gain and v.worse_weight + gain >= v.worse_min_weight:
            up.append(v)
            facts.append(_fact(f"tomorrow:group_{v.source}", "tomorrow", f"{v.label} tomorrow",
                               f"{v.label} could turn worse tomorrow: worse weight {_n(v.worse_weight)} now, "
                               f"{_n(v.worse_weight + gain)} if {', '.join(m.label for m in could_start[v.source])} "
                               f"cross{'es' if len(could_start[v.source]) == 1 else ''} again; it needs "
                               f"{_n(v.worse_min_weight)}."))
        if v.verdict == "worse" and loss and not v.rules_fired and v.worse_weight - loss < v.worse_min_weight:
            down.append(v)
            facts.append(_fact(f"tomorrow:group_{v.source}", "tomorrow", f"{v.label} tomorrow",
                               f"{v.label} could leave worse tomorrow: worse weight {_n(v.worse_weight)} now, "
                               f"{_n(v.worse_weight - loss)} if {', '.join(m.label for m in could_stop[v.source])} "
                               f"stay{'s' if len(could_stop[v.source]) == 1 else ''} within threshold; it needs "
                               f"{_n(v.worse_min_weight)}."))
    st = crit.state
    worse_now = sum(1 for v in verdicts if v.verdict == "worse")
    lines = []
    if c.state == "safety":
        lines.append("The safety state stays until a clinician acknowledges the flag.")
    elif c.state == "needs_call" and c.acknowledged_by:
        # analytics/consensus.py replay: after an acknowledgement nothing is held, the state is the day's own result
        lines.append(f"needs_call is acknowledged by {c.acknowledged_by}, so it is not held: from here the state is "
                     f"what the day itself gives. It stays needs_call while {st.needs_call_min_worse} groups are "
                     f"worse; {worse_now} are worse now.")
        if down:
            lines.append(f"{len(down)} of them could leave worse tomorrow ({', '.join(v.label for v in down)})"
                         + ("; the state then leaves needs_call." if worse_now - len(down) < st.needs_call_min_worse
                            else "; the state would still be needs_call."))
    elif c.state == "needs_call":
        lines.append(f"needs_call stays until a clinician acknowledges it or the rule gives stable on "
                     f"{st.hysteresis_stable_days} days in a row; it is not acknowledged.")
        if down:
            lines.append(f"{len(down)} of the {worse_now} worse groups could leave worse tomorrow "
                         f"({', '.join(v.label for v in down)}); without an acknowledgement the state would be held.")
    else:
        if up and worse_now + len(up) >= st.needs_call_min_worse:
            lines.append(f"The state could become needs_call tomorrow: {worse_now} groups are worse now, "
                         f"{len(up)} more could turn worse ({', '.join(v.label for v in up)}), needs_call takes "
                         f"{st.needs_call_min_worse}.")
        elif up and worse_now + len(up) >= st.watch_min_worse and c.state == "stable":
            lines.append(f"The state could become watch tomorrow: {len(up)} group could turn worse "
                         f"({', '.join(v.label for v in up)}), watch takes {st.watch_min_worse}.")
        if c.raw_state == "stable" and c.state == "watch":
            lines.append(f"The record is too young to be stable before day {st.min_history_days_for_stable}.")
    if lines:
        said = {"safety": True} if c.state == "safety" else \
            {"acknowledged": c.acknowledged_by is not None, "held": c.held} if c.state == "needs_call" else {}
        facts.append(_fact("tomorrow:state", "tomorrow", "The state tomorrow", " ".join(lines), said))
    return facts


def missing_facts(crit: Criteria, data: PatientData, metrics: list[DebugMetric], day: date) -> list[DebugFact]:
    facts: list[DebugFact] = []
    silent = set()
    for s in crit.active_sources():
        days = [d for d in data.source_days.get(s, {}) if d <= day]
        if day in days:
            continue
        silent.add(s)
        last = max(days, default=None)
        facts.append(_fact(f"missing:{s}", "missing", f"No {SOURCE_LABELS[s]} data",
                           f"{SOURCE_LABELS[s]} sent nothing that counts on this day; "
                           + (f"its last day with data was {(day - last).days} days before." if last
                              else "it has never sent anything.")))
    usual = [m for m in metrics if m.scored and m.value is None and m.baseline is not None and m.source not in silent]
    for m in usual[:int(cfg("missing_max", 8))]:
        facts.append(_fact(f"missing:{m.metric}", "missing", f"No {m.label}",
                           f"{m.label} has no value on this day although it has a baseline of {m.baseline.days} "  # type: ignore[union-attr]
                           f"days; its group ({SOURCE_LABELS[m.source]}) did send other data."))
    return facts


def event_facts(events: list[DebugEvent], metrics: list[DebugMetric]) -> list[DebugFact]:
    """The envelopes behind the measures that moved most, as citable lines (numbers and short enums only). The
    day's camera face-sign records are always among them (`[debug_day].face_event_facts`), counted or not: a
    developer must be able to see what the camera counted and whether it was enough to be a reading."""
    order = [m for m in sorted(metrics, key=lambda m: -abs(m.z or 0)) if m.z is not None and m.event_ids]
    by_id = {e.id: e for e in events}
    faces = [e.id for e in events if e.type == "obs.face_signs"][:int(cfg("face_event_facts", 4))]
    picked: list[str] = []
    for m in order:
        picked += [i for i in m.event_ids[:2] if i not in picked and i in by_id]
    picked = [*faces, *(i for i in picked if i not in faces)]
    out = []
    for i in picked[:int(cfg("max_event_facts", 12))]:
        e = by_id[i]
        fields = [f"{k} {_n(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v}"
                  for k, v in e.payload.items() if isinstance(v, (int, float, bool)) or (isinstance(v, str) and len(v) <= 24)]
        counted = f"counted toward {', '.join(e.metrics)}" if e.metrics else "counted toward no measure"
        out.append(_fact(f"event:{e.id}", "event", f"{e.type} at {e.local_time[:5]} from {e.source}",
                         ", ".join(fields[:16 if e.type == "obs.face_signs" else 10]) + f"; {counted}."))
    return out


# ------------------------------------------------------------------ the read
def code_line(f: DebugFact, *, in_model_read: bool = False) -> DebugClaim:
    """A fact as a line of the read, in code's own words."""
    return DebugClaim(text=_cut(f"{f.label}: {f.detail}", 500), cites=[f.id], by_code=in_model_read)


def rule_line(c: DebugConsensus, verdicts: list[DebugVerdict], *, in_model_read: bool = False) -> DebugClaim:
    """Why the rule gives this state, in the rule's own reasons."""
    worse_groups = [v.id for v in verdicts if v.verdict == "worse"]
    return DebugClaim(text=_cut("; ".join(c.reasons) + ".", 500), cites=[c.id, *worse_groups][:6], by_code=in_model_read)


def deterministic_read(reading: str, facts: list[DebugFact], metrics: list[DebugMetric], c: DebugConsensus,
                       verdicts: list[DebugVerdict], digest: str, now: datetime, reason: str) -> DebugRead:
    by_id = {f.id: f for f in facts}
    # what moved, the measures the rule reads first: a measure that is shown and not scored (face signs, more of the
    # day from Apple Health) never pushes a scored one off the list
    moved = sorted((m for m in metrics if m.z is not None and abs(m.z) >= float(cfg("slight_z", 1.0)) and m.id in by_id),
                   key=lambda m: (not m.scored, -abs(m.z or 0)))[:int(cfg("moved_max", 8))]
    scored = [m for m in metrics if m.scored and m.worse_z is not None]
    worse = sum(1 for m in scored if m.beyond_today)
    summary = (f"The day reads as {READING_WORDS[reading]}: {len(scored)} scored measures have a value and a baseline, "
               f"{worse} beyond their threshold in the worse direction. The rule gives {c.state}"
               f"{' (held)' if c.held else ''}; the day alone gives {c.raw_state}.")

    def claim(f: DebugFact) -> DebugClaim:
        return code_line(f)

    return DebugRead(
        by="deterministic", fallback_reason=reason, reading=reading,  # type: ignore[arg-type]
        summary=DebugClaim(text=_cut(summary, 500), cites=[c.id, *(m.id for m in moved[:3])]),
        moved=[claim(by_id[m.id]) for m in moved],
        missing=[claim(f) for f in facts if f.kind == "missing"],
        tomorrow=[claim(f) for f in facts if f.kind == "tomorrow"],
        rule_check=rule_line(c, verdicts),
        digest=digest, generated_at=now)


def numbers_ok(text: str, cited: list[DebugFact]) -> bool:
    """Every number in the sentence is written in a fact it cites (to the decimals the sentence uses)."""
    allowed = {n for f in cited for n in f.numbers}
    for raw in _NUMBER.findall(text):
        digits = len(raw.split(".")[1]) if "." in raw else 0
        if not any(abs(abs(float(raw)) - n) <= 0.5 * 10 ** -digits + 1e-9 for n in allowed):
            return False
    return True


_SIDE = re.compile(r"(\d+(?:\.\d+)?)\s*(%|percent|spreads?)?\s*(?:(?:minutes?|min|steps|ms|bpm|points?|pebbles|taps|"
                   r"hours?|seconds?|s)\s+)?(above|below|over|under)\b", re.I)


_STATUS = re.compile(r"\b(drifting|improved|insufficient)\b|\bstatus (normal)\b|\((normal)\)", re.I)
_DAYS_OF = re.compile(r"(\d+) of (?:the |its )?last (\d+) scored days", re.I)
_WEIGHT = re.compile(r"\bweight (\d+(?:\.\d+)?)", re.I)


def _near(raw: str, want: float) -> bool:
    digits = len(raw.split(".")[1]) if "." in raw else 0
    return abs(float(raw) - want) <= 0.5 * 10 ** -digits + 1e-9


# "beyond its threshold on 3 of the last 5 scored days" counts days; without the count it is about this day
_BEYOND = re.compile(r"\bbeyond (?:its|the|their) (?:own )?thresholds?(?: in the (?:worse|better) direction)?( on \d+ of)?",
                     re.I)
_WITHIN = re.compile(r"\bwithin (?:its|the|their) (?:own )?thresholds?\b", re.I)
_ZERO = re.compile(r"\b(?:0|zero)\b", re.I)


def role_issue(text: str, m: DebugMetric) -> str | None:
    """A sentence about ONE measure must use that measure's numbers and words in their own roles: "N above /
    below" is the distance (or the spreads, or the percentage) on the side the day is really on; "A of the last B
    scored days" are its counts; a weight is its weight; drifting / normal / insufficient is its status."""
    if m.value is not None and m.baseline is not None and m.z is not None:
        delta = m.value - m.baseline.median
        pct = abs(delta) / abs(m.baseline.median) * 100 if m.baseline.median else None
        for raw, unit, side in _SIDE.findall(text):
            want = abs(m.z) if unit.lower().startswith("spread") else pct if unit else abs(delta)
            if want is None or not _near(raw, want) or (side.lower() in ("above", "over")) != (delta > 0):
                return "number_in_wrong_role"
    for a, b in _DAYS_OF.findall(text):
        if int(b) != m.scored_days or int(a) not in (m.worse_days, m.better_days):
            return "number_in_wrong_role"
    if any(abs(float(raw) - m.weight) > 1e-9 for raw in _WEIGHT.findall(text)):
        return "number_in_wrong_role"
    said = {next(w for w in found if w).lower() for found in _STATUS.findall(text)}
    if said and said != {m.status}:
        return "status_mismatch"
    return None


# What a sentence says about a yes/no fact. Each pattern is one way of stating it; the second item is what the
# words say before any "not" in front of them.
_YES_NO: tuple[tuple[str, bool, re.Pattern[str]], ...] = (
    ("held", True, re.compile(r"\bheld\b", re.I)),
    ("acknowledged", True, re.compile(r"\backnowledged\b|\backnowledge?ments?\b", re.I)),
    ("acknowledged", False, re.compile(r"\bunacknowledged\b", re.I)),
    ("safety", True, re.compile(r"\bsafety (?:flag|state)s?\b", re.I)),
    ("enough_data", True, re.compile(r"\benough data\b", re.I)),
    ("enough_data", False, re.compile(r"\btoo little data\b|\binsufficient\b", re.I)),
    ("scored", True, re.compile(r"(?:(?<=[;,] )|(?<=\bis )|(?<=\bare )|(?<=\band ))scored\b", re.I)),
    ("scored", False, re.compile(r"\bnot scored\b|\bobserve-only\b|\bnever a vote\b", re.I)),
)
_CLAUSE = re.compile(r"[.;:,()]|\b(?:and|but|while|although|so|because)\b", re.I)
_NOT = re.compile(r"\b(?:not|never|no|none|nothing|nobody|neither|nor|without|cannot)\b|n't\b", re.I)
# Words that make the statement a condition, a wish or a count of some, not a yes or a no about this day.
_OPEN = re.compile(r"\b(?:until|unless|if|whether|once|when|would|could|should|may|might|await\w*|pending|needs?|"
                   r"requires?|waiting|fewer|only|few|less|some|one (?:more )?day)\b", re.I)
_STATE_WORD = re.compile(r"\bstate\b|\bneeds_call\b", re.I)
_MUST_CITE = ("held", "acknowledged", "safety")  # the consensus's own: a sentence stating one must cite its carrier


def stated(text: str, *, about_a_measure: bool = False) -> list[tuple[str, bool]]:
    """Every yes/no fact the sentence states, with the side it takes. The words in front of it within its own
    clause decide: a "not" turns it, a condition ("until it is acknowledged", "whether it is held") states nothing.
    "insufficient" beside a cited measure is that measure's status word, not a statement about a group's data.
    `beyond` and `within` are about this day: some cited measure is beyond (within) its threshold on it."""
    out: list[tuple[str, bool]] = []

    def add(flag: str, plain: bool, m: re.Match[str], *, counted: bool = False) -> None:
        before = " ".join(_CLAUSE.split(text[:m.start()])[-1].split()[-8:])
        if not _OPEN.search(before):
            turned = bool(_NOT.search(before)) or (counted and bool(_ZERO.search(before)))  # "0 beyond their threshold"
            out.append((flag, plain != turned))

    for flag, plain, pattern in _YES_NO:
        for m in pattern.finditer(text):
            if not (about_a_measure and m.group(0).lower() == "insufficient"):
                add(flag, plain, m)
    for m in _BEYOND.finditer(text):
        if not m.group(1):
            add("beyond", True, m, counted=True)
    for m in _WITHIN.finditer(text):
        add("within", True, m, counted=True)
    return out


def yes_no_ok(text: str, cited: list[DebugFact]) -> bool:
    """Checked the way the numbers are: what the sentence states about held, acknowledged, an open safety flag,
    a group's enough data, a measure being scored, or a measure being beyond or within its threshold on this day
    must be what a fact it cites carries (`DebugFact.flags`; with several cited facts, what one of them carries).
    The consensus's own three must be cited to be stated at all."""
    for flag, says in stated(text, about_a_measure=any(f.kind == "metric" for f in cited)):
        have = [f.flags[flag] for f in cited if flag in f.flags]
        if (says not in have) if have else (flag in _MUST_CITE):
            return False
    return True


_ID_NOTE = re.compile(r"\s*\[[^\[\]]*\]|\s*\((?:metric|source|consensus|missing|tomorrow|event):[^()]*\)")
_ID = re.compile(r"\b(?:metric|source|consensus|missing|tomorrow|event):\w|\bDAY\.\w")
_READING_SAID = {"slight_shift": re.compile(r"\bslight shift\b", re.I), "clear_shift": re.compile(r"\bclear shift\b", re.I)}


def check_claim(item: Any, allowed: dict[str, DebugFact], section: str,
                metrics: dict[str, DebugMetric] | None = None, reading: str | None = None) -> DebugClaim | str:
    """One sentence of the model's read, or the content-free category it is rejected for."""
    if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not isinstance(item.get("cites"), list) \
            or not all(isinstance(x, str) for x in item["cites"]):
        return "invalid_shape"
    # A citation written into the sentence ("... are worse [consensus:state].") is taken out: `cites` carries it.
    text = re.sub(r"\s+([.,;:])", r"\1", " ".join(_ID_NOTE.sub("", item["text"]).split()))
    cites = list(dict.fromkeys(item["cites"]))
    if not text or not cites:
        return "invalid_shape"
    if len(text) > 500:
        return "too_long"
    keys = {m.metric for m in (metrics or {}).values() if "_" in m.metric}
    if _ID.search(text) or any(re.search(rf"\b{re.escape(k)}\b", text) for k in keys):
        return "id_in_text"  # a developer reads labels; an id or a metric key belongs in `cites`
    if reading and any(p.search(text) for r, p in _READING_SAID.items() if r != reading):
        return "reading_mismatch"  # the reading is code's: a sentence cannot call the day another one
    if len(cites) > MAX_CITES:
        return "too_many_cites"
    if any(i not in allowed for i in cites):
        return "unknown_citation"
    need = SECTION_KIND.get(section)
    if need and not any(allowed[i].kind == need for i in cites):
        return "wrong_section"
    if section == "tomorrow" and _STATE_WORD.search(text) and not any(
            i == "tomorrow:state" or allowed[i].kind == "consensus" for i in cites):
        return "state_not_cited"  # a group's or a measure's fact says nothing about what the state does next
    if contains_banned(text) or wording.codes(wording.lint(text, max_questions=None)) & insight._BAD_LINT:
        return "wording"
    if insight._OVERCLAIM.search(text):
        return "overclaim"
    if insight._FILLER.search(text):
        return "filler"
    if not numbers_ok(text, [allowed[i] for i in cites]):
        return "number_not_in_data"
    if not yes_no_ok(text, [allowed[i] for i in cites]):
        return "yes_no_mismatch"
    about = [i for i in cites if allowed[i].kind == "metric"]
    if metrics and len(about) == 1 and about[0] in metrics:
        issue = role_issue(text, metrics[about[0]])
        if issue:
            return issue
    return DebugClaim(text=text, cites=cites)


def validate(raw: str, allowed: dict[str, DebugFact], metrics: dict[str, DebugMetric] | None = None,
             reading: str | None = None) -> tuple[dict[str, Any], dict[str, int]]:
    """The model's JSON as checked sections ({summary, moved, missing, tomorrow, rule_check}) + rejection counts."""
    data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])  # a code fence or a stray word around the object is not it
    if not isinstance(data, dict):
        raise ValueError("invalid_object")
    rejected: Counter[str] = Counter()
    out: dict[str, Any] = {}
    for section in ("summary", "rule_check"):
        got = check_claim(data.get(section), allowed, section, metrics, reading) \
            if data.get(section) is not None else None
        if isinstance(got, str):
            rejected[got] += 1
            got = None
        elif got is None and section == "summary":
            rejected["no_summary"] += 1  # nothing was wrong with a sentence: the part is simply not there
        out[section] = got
    for section in ("moved", "missing", "tomorrow"):
        kept: list[DebugClaim] = []
        seen: set[tuple[str, ...]] = set()
        items = data.get(section) if isinstance(data.get(section), list) else []
        for item in items[:8]:
            got = check_claim(item, allowed, section, metrics, reading)
            if isinstance(got, str):
                rejected[got] += 1
            elif tuple(sorted(got.cites)) in seen:
                rejected["duplicate"] += 1
            else:
                seen.add(tuple(sorted(got.cites)))
                kept.append(got)
        out[section] = kept[:6]
    return out, dict(rejected)


def _ask_cost(since: float) -> float | None:
    """The spend ledger's estimate for the calls of one ask: its rows for this task since the ask began."""
    mine = [float(r["usd"]) for r in budget.rows(since - 1, wall_time() + 1) if r["task"] == "debug_read"]
    return round(sum(mine), 6) if mine else None


def read(store: Store, settings: Settings, home_id: str, day: date, reading: str, facts: list[DebugFact],
         metrics: list[DebugMetric], c: DebugConsensus, verdicts: list[DebugVerdict], now: datetime, *,
         generate: bool, gen: Any = None) -> DebugRead:
    model = gemma.model_name()
    instruction = str(cfg("prompt", ""))
    context = [{"id": f.id, "label": f.label, "detail": f.detail} for f in facts]
    digest = hashlib.sha256(json.dumps(
        [READ_VERSION, hashlib.sha256(instruction.encode()).hexdigest()[:16], c.rule_version, model, str(day), reading,
         context], sort_keys=True).encode()).hexdigest()

    def fallback(reason: str) -> DebugRead:
        return deterministic_read(reading, facts, metrics, c, verdicts, digest, now, reason)

    key = f"debug-read:{home_id}:{day.isoformat()}"
    with _LOCKS[f"{settings.db_path}:{key}"]:
        cached = store.kv_get(key)
        if cached and cached.get("digest") == digest:
            if cached.get("read"):
                return DebugRead.model_validate(cached["read"]).model_copy(update={"cached": True})
            kept = cached["failed"]  # asked once about exactly this data, nothing valid came back: not paid for twice
            return fallback(kept["reason"]).model_copy(update={
                "cached": True, "failed": True, "rejected": kept["rejected"], "attempts": kept["attempts"],
                "latency_ms": kept["latency_ms"], "est_usd": kept["est_usd"],
                "generated_at": datetime.fromisoformat(kept["at"])})
        if not generate:
            return fallback("not_requested")
        last = store.kv_get(f"debug-read-last:{home_id}:{day.isoformat()}")
        if last and (now - datetime.fromisoformat(last["ts"])).total_seconds() < float(cfg("cooldown_s", 60)):
            return fallback("cooldown")
        store.kv_set(f"debug-read-last:{home_id}:{day.isoformat()}", {"ts": now.isoformat()})
        gen = gen or gemma.generate
        # A group's own "tomorrow" line already names its measures: the model gets that one, not each of them again.
        grouped = {f.id.removeprefix("tomorrow:group_") for f in facts if f.id.startswith("tomorrow:group_")}
        group_of = {m.metric: m.source for m in metrics}
        allowed = {f.id: f for f in facts
                   if not (f.kind == "tomorrow" and group_of.get(f.id.removeprefix("tomorrow:")) in grouped)}
        # Which measures count as moved is code's call too (the same list the deterministic read uses).
        moved = [m.id for m in sorted((m for m in metrics if m.z is not None and m.id in allowed
                                       and abs(m.z) >= float(cfg("slight_z", 1.0))),
                                      key=lambda m: (not m.scored, -abs(m.z or 0)))][:6]
        ahead = [i for i in allowed if i == "tomorrow:state" or i.startswith("tomorrow:group_")]
        ahead.sort(key=lambda i: i != "tomorrow:state")
        prompt = (instruction + "\nDAY:\n" + json.dumps({"date": str(day), "reading": reading, "moved": moved})
                  + "\nFACTS:\n" + json.dumps([x for x in context if x["id"] in allowed], ensure_ascii=False))
        by_metric = {m.id: m for m in metrics}
        parts: dict[str, Any] = {}
        rejected: Counter[str] = Counter()
        reason: str | None = None
        best, attempts, began, started = -1, 0, wall_time(), monotonic()
        for _attempt in (1, 2):
            attempts += 1
            problems: list[str] = []
            try:
                raw = gen(prompt, timeout_s=float(cfg("timeout_s", 40)), task="debug_read", home_id=home_id,
                          max_output_tokens=int(cfg("max_output_tokens", 2400)))
                got, bad = validate(raw, allowed, by_metric, reading)
                rejected.update(bad)
                covered = {i for claim in got["moved"] for i in claim.cites}
                left_out = [i for i in moved if i not in covered]
                told = {i for claim in got["tomorrow"] for i in claim.cites}
                untold = [i for i in ahead if i not in told]
                kept = (len(moved) - len(left_out) + len(ahead) - len(untold) + len(got["missing"])
                        + 10 * (got["rule_check"] is not None))
                # A read is Gemma's when its summary stands. The fuller of two answers is the one shown.
                if got["summary"] is not None and kept > best:
                    parts, best, reason = got, kept, None
                if got["summary"] is None:
                    reason = reason if parts else "no_valid_claims"
                    problems.append("summary missing or rejected")
                if left_out:
                    rejected["moved_left_out"] += len(left_out)
                    problems.append("no valid moved item for " + ", ".join(left_out))
                if untold:
                    rejected["tomorrow_left_out"] += len(untold)
                    problems.append("no valid tomorrow item citing " + ", ".join(untold))
                if got["rule_check"] is None:
                    problems.append("rule_check missing or rejected")
                problems += sorted(k for k in bad if k != "no_summary")
                if not problems:
                    break
            except LlmUnavailable as e:
                if not parts:
                    reason = "over_budget" if "BudgetExceeded" in str(e) else "provider_unavailable"
                # which kind of failure, never the provider's text (it can quote the request)
                kind = next((w for w in str(e).replace(":", " ").split() if w[:1].isupper() and w.isidentifier()), "error")
                log.warning("debug_read_unavailable", kind, home=home_id, day=str(day))
                break
            except (ValueError, TypeError, AttributeError):
                reason = reason if parts else "invalid_json"
                rejected["invalid_json"] += 1
                problems.append("invalid_json")
            prompt += ("\nYour previous response failed validation (" + "; ".join(problems) + "). Return one complete "
                       "JSON object with every part. " + str(cfg("retry_note", "")))
        asked = {"attempts": attempts, "latency_ms": round((monotonic() - started) * 1000, 1), "est_usd": _ask_cost(began)}
        if not parts:
            reason = reason or "no_valid_claims"
            ledger.record("template", "debug_read", ok=True, fallback=True, route=reason, home_id=home_id)
            keep = reason in KEPT_FAILURES
            if keep:
                store.kv_set(key, {"digest": digest, "failed": {"reason": reason, "rejected": dict(rejected),
                                                                "at": now.isoformat(), **asked}})
            return fallback(reason).model_copy(update={"rejected": dict(rejected), "failed": keep, **asked})
        def whole(section: str, wanted: list[str]) -> list[DebugClaim]:
            """Every fact code wants a line for has one: the model's when it passed the checks, otherwise code's
            own, marked as such. The model's other lines of the section follow."""
            said = {i: claim for claim in reversed(parts[section]) for i in claim.cites if i in wanted}
            lines = [said.get(i) or code_line(allowed[i], in_model_read=True) for i in wanted]
            return list({id(x): x for x in lines}.values()) + [x for x in parts[section] if not set(x.cites) & set(wanted)]

        result = DebugRead(by="gemma", model=model or None, reading=reading, summary=parts["summary"],  # type: ignore[arg-type]
                           moved=whole("moved", moved), missing=parts["missing"], tomorrow=whole("tomorrow", ahead),
                           rule_check=parts["rule_check"] or rule_line(c, verdicts, in_model_read=True),
                           rejected=dict(rejected), digest=digest, generated_at=now,
                           **asked)
        store.kv_set(key, {"digest": digest, "read": result.model_dump(mode="json")})
        return result


# ------------------------------------------------------------------ the whole day
def build(store: Store, settings: Settings, home_id: str, day: date | None = None, *, generate: bool = False,
          now: datetime | None = None, gen: Any = None) -> DebugDay:
    now = now or datetime.now(UTC)
    today = now.astimezone(TZ).date()
    day = day or today
    start, end = bounds(day)
    is_today = day == today
    as_of = now if is_today else end  # acknowledgements and flags after a past day's end are not that day's
    crit = service.active_criteria(store)
    events = store.events_for_home(home_id)
    data = service.patient_data(store, home_id, crit, today)
    spans = {s: (min(v), max(v)) for s, v in data.source_days.items() if v}
    full = daily_metrics(events, crit, spans, include_disabled=True)

    shown, ids = _events(events, day, crit)
    metrics = _metrics(crit, full, day, today, ids)
    results = all_verdicts(data, day, crit, as_of)
    _c, last = consensus.compute(data, crit, day, as_of)
    yesterday = day - timedelta(days=1)
    prev = consensus.compute(data, crit, yesterday, start)[1] \
        if data.first_day is not None and data.first_day <= yesterday else None
    spec = {m.name: m for m in crit.metrics}
    before = {m.metric: drift_for(spec[m.metric], _series(spec[m.metric], full, today), yesterday, crit).status
              for m in metrics} if prev is not None else {}
    verdicts = _verdicts(crit, data, metrics, last, prev, day, events)
    state = _consensus(crit, data, last, prev, results, metrics, before, day)

    facts = [consensus_fact(state, metrics, day, data), *(verdict_fact(v, metrics) for v in verdicts),
             *(f for f in map(metric_fact, metrics) if f is not None),
             *missing_facts(crit, data, metrics, day),
             *tomorrow_facts(crit, full, metrics, verdicts, state, day, today),
             *event_facts(shown, metrics)]
    reading = reading_of(metrics)
    return DebugDay(
        home_id=home_id, date=day, timezone=str(TZ), day_start=start, day_end=end, is_today=is_today,
        first_day=data.first_day,
        sim=any(e.sim for e in shown) if shown else data.sim, events=shown, events_total=len(shown), metrics=metrics,
        verdicts=verdicts, consensus=state, conversations=_conversations(store, home_id, day),
        model_calls=_model_calls(store, home_id, day), facts=facts,
        read=read(store, settings, home_id, day, reading, facts, metrics, state, verdicts, now, generate=generate, gen=gen),
        computed_at=now)
