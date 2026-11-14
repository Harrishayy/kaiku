"""Use-cases shared by API routes and jobs: criteria, recompute consensus, explanations, timelines, PHQ-9, me.

Flow: effective Criteria (config/criteria.toml, or a live override stored in the DB) → store events →
analytics.data.build → consensus.compute (deterministic) → explanation (template on recompute; LLM lazily on
GET /consensus, cached by input hash) → homes summary row. Criteria are loaded once per recompute.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from kaiku_contracts.api import (
    STATE_RANK,
    Consensus,
    CriteriaPreview,
    CriteriaResponse,
    Explanation,
    HelpStat,
    MeResponse,
    MetricSeries,
    NudgeResponse,
    PatientSummary,
    Phq9Entry,
    Phq9History,
    PreviewChange,
    SourceBadge,
    TimelinePoint,
)
from kaiku_contracts.config import get
from kaiku_contracts.criteria import Criteria, criteria_path, load_criteria
from kaiku_contracts.sources import SOURCE_LABELS

from . import companion
from .analytics import bandit
from .analytics.consensus import compute
from .analytics.data import PatientData, build
from .analytics.drift import baseline_of
from .analytics.metrics import local_date
from .llm.explain import make_explanation
from .llm.template import template_explanation
from .settings import TZ, Settings
from .store.db import Store


def today_local() -> date:
    return datetime.now(TZ).date()


def display_name(home_id: str) -> str:
    return home_id.rsplit("-", 1)[-1].replace("_", " ").title()


# ------------------------------------------------------------------ criteria (ground truth: config/criteria.toml)
OVERRIDE_KEY = "criteria_override"
_file_cache: dict[str, tuple[float, Criteria]] = {}


def file_criteria() -> Criteria:
    """config/criteria.toml (or $KAIKU_CRITERIA), re-read whenever the file's mtime changes (no restart needed)."""
    path = criteria_path()
    if path is None or not path.is_file():
        return load_criteria()  # raises a clear FileNotFoundError
    key, mtime = str(path), path.stat().st_mtime
    hit = _file_cache.get(key)
    if hit is None or hit[0] != mtime:
        _file_cache[key] = (mtime, load_criteria(path))
    return _file_cache[key][1]


def active_criteria(store: Store) -> Criteria:
    o = store.kv_get(OVERRIDE_KEY)
    return Criteria.model_validate(o["criteria"]) if o else file_criteria()


def criteria_response(store: Store) -> CriteriaResponse:
    o = store.kv_get(OVERRIDE_KEY)
    crit = active_criteria(store)
    return CriteriaResponse(criteria=crit, rule_version=crit.rule_version, origin="override" if o else "file",
                            updated_at=o.get("updated_at") if o else None, updated_by=o.get("by") if o else None)


def set_criteria(store: Store, settings: Settings, crit: Criteria | None, by: str | None) -> CriteriaResponse:
    """Apply a live override (validated by the caller's model), or reset to the file with None; recompute all."""
    if crit is None:
        store.kv_delete(OVERRIDE_KEY)
    else:
        store.kv_set(OVERRIDE_KEY, {"criteria": crit.model_dump(mode="json", by_alias=True), "by": by,
                                    "updated_at": datetime.now(UTC).isoformat()})
    store.kv_delete("eval")  # simulation results belong to a rule version
    recompute_all(store, settings)
    return criteria_response(store)


CUMULATIVE = ("sum", "count")  # a day's total only means something once the day is over
ROBOT_SOURCES = {"hub", "head", "sensors"}  # envelope sources that only a robot at home produces
ROBOT_ARMS = {"drum"}  # suggestions that need the robot's hardware


def patient_data(store: Store, home_id: str, crit: Criteria, today: date | None = None) -> PatientData:
    """Today's running total of a cumulative metric (steps, minutes, counts) reads low until the day ends, so it
    is neither scored nor charted yet; it appears tomorrow as a complete day."""
    data = build(home_id, store.events_for_home(home_id), crit, store.actions(home_id))
    today = today or today_local()
    for m in crit.metrics:
        if m.agg in CUMULATIVE and m.name in data.series:
            data.series[m.name] = {d: v for d, v in data.series[m.name].items() if d < today}
    return data


def nudge_arms(store: Store, home_id: str) -> tuple[str, ...]:
    """Suggestions this home can actually do: no drumming without a robot that has ever reported."""
    arms = bandit.enabled_arms()
    if any(e["source"] in ROBOT_SOURCES for e in store.events_for_home(home_id)):
        return arms
    return tuple(a for a in arms if a not in ROBOT_ARMS) or ("breathe",)


def explain_ctx(home_id: str, c: Consensus, notes: list[str], sim: bool, families: list[str] | None = None
                ) -> dict[str, Any]:
    return {
        "display_name": display_name(home_id), "simulated": sim,
        "state": c.state, "agreement": c.agreement, "rule_version": c.rule_version,
        "acknowledged": c.acknowledged_by is not None, "notes": notes, "correlated_families": families or [],
        "sources": [{**v.model_dump(mode="json", exclude={"computed_at", "home_id"}),
                     "label": SOURCE_LABELS[v.source]} for v in c.sources],
    }


def evaluate_home(store: Store, home_id: str, crit: Criteria, today: date | None = None) -> dict[str, Any]:
    """Compute (don't save) the summary row for one home under `crit`."""
    end = today or today_local()
    data = patient_data(store, home_id, crit, end)
    c, last = compute(data, crit, end)
    c.simulated = data.sim
    ctx = explain_ctx(home_id, c, last.notes, data.sim, last.correlated_families)
    c.explanation = template_explanation(ctx)
    summary = PatientSummary(
        id=home_id, display_name=display_name(home_id), state=c.state, agreement=c.agreement,
        headline=c.explanation.headline,
        sources=[SourceBadge(source=v.source, verdict=v.verdict, confidence=v.confidence, last_data_at=v.last_data_at)
                 for v in c.sources],
        last_activity_at=data.last_activity_at, safety_since=c.safety_since,
        acknowledged=c.acknowledged_by is not None, sim=data.sim,
    )
    return {"summary": summary.model_dump(mode="json"), "consensus": c.model_dump(mode="json"), "notes": last.notes,
            "correlated_families": last.correlated_families,
            "state_since": last.state_since.isoformat() if last.state_since else None}


def recompute_home(store: Store, settings: Settings, home_id: str, today: date | None = None,
                   crit: Criteria | None = None) -> dict[str, Any]:
    row = evaluate_home(store, home_id, crit or active_criteria(store), today)
    store.save_home_summary(home_id, row["summary"]["state"], row)
    return row


def recompute_all(store: Store, settings: Settings) -> int:
    crit = active_criteria(store)  # once per recompute
    ids = store.home_ids()
    for h in ids:
        recompute_home(store, settings, h, crit=crit)
    return len(ids)


def preview(store: Store, candidate: Criteria | None, *, with_eval: bool = False) -> CriteriaPreview:
    """Who would change state under `candidate` (None = the file). Nothing is saved."""
    current = active_criteria(store)
    cand = candidate or file_criteria()
    changes: list[PreviewChange] = []
    unchanged = 0
    for h in store.home_ids():
        a, b = evaluate_home(store, h, current), evaluate_home(store, h, cand)
        sa, sb = a["summary"], b["summary"]
        va = {x["source"]: x["verdict"] for x in sa["sources"]}
        vb = {x["source"]: x["verdict"] for x in sb["sources"]}
        common = va.keys() & vb.keys()  # a source the candidate disables is not, by itself, a change
        if sa["state"] == sb["state"] and all(va[k] == vb[k] for k in common):
            unchanged += 1
            continue
        changes.append(PreviewChange(patient_id=h, display_name=sa["display_name"], from_state=sa["state"],
                                     to_state=sb["state"], from_sources=va, to_sources=vb))
    ev = None
    if with_eval:
        from .jobs.simulate import run_eval

        ev = run_eval(n_patients=18, shards=1, criteria=cand)
    return CriteriaPreview(current_rule_version=current.rule_version, candidate_rule_version=cand.rule_version,
                           changes=changes, unchanged=unchanged, eval=ev)


def ranked_summaries(rows: list[dict[str, Any]]) -> list[PatientSummary]:
    out = [PatientSummary.model_validate(r["summary"]) for r in rows]
    return sorted(out, key=lambda s: (STATE_RANK[s.state], s.display_name))


_EXPLANATION_LOCKS: dict[str, Any] = defaultdict(threading.Lock)


def get_consensus(store: Store, settings: Settings, row: dict[str, Any], log: Any = None) -> Consensus:
    """Consensus with the configured explainer (LLM if KAIKU_LLM says so), cached by input hash."""
    c = Consensus.model_validate(row["consensus"])
    if settings.llm == "template":
        return c
    ctx = explain_ctx(c.home_id, c, row.get("notes", []), bool(row["summary"].get("sim")),
                      row.get("correlated_families"))
    # Arrival timestamps are presentation metadata, not new explanation evidence.
    semantic = {**ctx, "sources": [{k: v for k, v in source.items() if k != "last_data_at"}
                                    for source in ctx["sources"]]}
    h = hashlib.sha256(json.dumps(["verified-selection-v2", semantic, settings.llm], sort_keys=True, default=str).encode()).hexdigest()[:16]
    with _EXPLANATION_LOCKS[f"{settings.db_path}:{c.home_id}"]:
        cached = store.get_explanation(c.home_id)
        cooldown = float(get("gemma_hosted", "explanation_cooldown_s", 300))
        age = float("inf")
        if cached:
            last = Explanation.model_validate(cached[1])
            age = (datetime.now(UTC) - last.generated_at).total_seconds() if last.generated_at else float("inf")
            if cached[0] == h and (last.by != "template" or age < cooldown):
                c.explanation = last
                return c
            if age < cooldown:
                # New evidence is always represented by today's deterministic explanation; never show stale prose.
                return c
        c.explanation = make_explanation(ctx, settings, log)
        store.save_explanation(c.home_id, h, c.explanation.model_dump(mode="json"))
        return c


def timeline(store: Store, home_id: str, metrics: list[str] | None, days: int = 30) -> list[MetricSeries]:
    """Series for the criteria's enabled metrics (all, or the requested names) with the baseline band."""
    crit = active_criteria(store)
    data = patient_data(store, home_id, crit)
    end = today_local()
    start = end - timedelta(days=days - 1)
    specs = [m for m in crit.metrics if m.enabled and (metrics is None or m.name in metrics)]
    out: list[MetricSeries] = []
    for m in specs:
        s = data.series.get(m.name, {})
        if not s and metrics is None:
            continue
        z = float(crit.param(m, "z_threshold"))
        pts = []
        for i in range(days):
            d = start + timedelta(days=i)
            b = baseline_of(m, s, d, crit)
            pts.append(TimelinePoint(date=d, value=round(s[d], 3) if d in s else None,
                                     baseline_median=round(b.median, 3) if b else None,
                                     band_low=round(b.median - z * b.scale, 3) if b else None,
                                     band_high=round(b.median + z * b.scale, 3) if b else None,
                                     early=bool(b and b.early)))
        out.append(MetricSeries(metric=m.name, label=m.label, unit=m.unit, source=m.source, worse_when=m.worse_when,
                                points=pts))
    return out


def phq9_due(data: PatientData, every_days: int, today: date | None = None) -> bool:
    today = today or today_local()
    return not data.phq9 or (today - data.phq9[-1].day).days >= every_days


def phq9_history(store: Store, settings: Settings, home_id: str) -> Phq9History:
    data = patient_data(store, home_id, active_criteria(store))
    entries = [Phq9Entry(ts=p.ts, total=p.total, item9_positive=p.item9_positive, mode=p.mode) for p in data.phq9]
    next_due = (data.phq9[-1].day + timedelta(days=settings.phq9_every_days)) if data.phq9 else today_local()
    return Phq9History(patient_id=home_id, entries=entries, next_due=next_due)


def maybe_queue_phq9_due(store: Store, settings: Settings, home_id: str) -> None:
    """Spoken PHQ-9 mode: queue one cmd.hub {phq9_due} per due period (laptop mode: the web app shows a banner)."""
    from kaiku_contracts import make

    if settings.phq9_mode not in ("spoken", "both") or home_id not in store.home_ids():
        return
    data = patient_data(store, home_id, active_criteria(store))
    if not phq9_due(data, settings.phq9_every_days):
        return
    key = f"phq9_due:{home_id}:{data.phq9[-1].day.isoformat() if data.phq9 else 'never'}"
    if store.kv_get(key):
        return
    cmd = make("cmd.hub", {"phq9_due": True}, source="cloud", home_id=home_id)
    store.queue_command(cmd.model_dump(mode="json", exclude_none=True))
    store.kv_set(key, True)


ME_STATE = {
    "stable": "Your recent days have looked much like your usual.",
    "watch": "A few things look a little different from your usual. That's common and nothing to act on alone.",
    "needs_call": "Things look different from your usual in a few ways, so your care team may get in touch for a chat.",
    "safety": "If you need support right now, call the MIELI Crisis Helpline on 09 2525 0111, or 112 in an emergency.",
}


def me(store: Store, settings: Settings, home_id: str, row: dict[str, Any] | None,
       now: datetime | None = None) -> MeResponse:
    crit = active_criteria(store)
    events = store.events_for_home(home_id)
    data = build(home_id, events, crit, store.actions(home_id))
    state = (row or {}).get("summary", {}).get("state", "watch")
    now_local = (now or datetime.now(UTC)).astimezone(TZ)
    today = now_local.date()
    week = today - timedelta(days=7)
    lines: list[str] = []
    rituals = len({local_date(t) for t in data.rituals if local_date(t) > week})
    if rituals:
        lines.append(f"You did the morning ritual on {rituals} of the last 7 days.")
    walks = [d for d in data.outing_days if d > week]
    if walks:
        lines.append(f"You went for a walk on {len(walks)} days.")
    breaths = [r for r in data.interventions if r["activity"] == "breathe" and local_date(r["_ts"]) > week
               and (r.get("delta") or {}).get("rmssd_ms") is not None]
    if breaths:
        avg = sum(r["delta"]["rmssd_ms"] for r in breaths) / len(breaths)
        if avg > 0:
            lines.append(f"Breathing with Kaiku calmed your heart rhythm on average (+{avg:.0f} ms HRV).")
    helps = [HelpStat(**h) for h in bandit.help_stats(data.nudge_outcomes, data.interventions)]
    nxt = NudgeResponse(**bandit.choose(data.nudge_outcomes, data.interventions, arms=nudge_arms(store, home_id)))
    return MeResponse(home_id=home_id, summary=ME_STATE[state], last_week=lines, what_helps=helps,
                      next_suggestion=nxt, phq9_due=phq9_due(data, settings.phq9_every_days, today),
                      mascot=companion.mascot_for(state, now_local.hour, companion.together_recently(events, today)),
                      highlights=companion.highlights_for(events, data, crit, today),
                      garden=companion.garden_for(events, today), sim=data.sim)


def nudge(store: Store, settings: Settings, home_id: str) -> NudgeResponse:
    data = patient_data(store, home_id, active_criteria(store))
    return NudgeResponse(**bandit.choose(data.nudge_outcomes, data.interventions, arms=nudge_arms(store, home_id)))


def now_utc() -> datetime:
    return datetime.now(UTC)
