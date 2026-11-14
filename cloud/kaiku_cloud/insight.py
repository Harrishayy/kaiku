"""Practitioner insight: everything the intelligence layer knows that a care team may see, in one payload.

GET /v1/patients/{id}/insight → `PatientInsight`:
- review     Gemma interprets the record: per finding it picks a theme, cites evidence ids and writes what it likely
             means and what to consider. Code checks every finding (known ids, no digits, wording, no causal claim,
             theme consistent with the recorded direction) and renders every number from the cited records itself.
             Rejected findings are dropped and counted; no valid finding, no key, cooldown → deterministic template.
- trace      the steps that really ran (timings, model, cache hit, validator rejections). Counts only, no content.
- comparison this week vs the week before vs the personal usual, per measure and per signal group.
- routine    routines found by code, what the learner has seen help (with an interval), adherence.
- graph      signal groups, measures, observed activities, routines, what helped. Observations only; conversation
             counts join when the person shares. Never people, places, likes, plans, memories or transcripts.
- coverage   what was recorded, by which device, how much of it is simulated.
State comes from the deterministic consensus only; nothing here changes it. No private mind table is read except
episode counts through the same sharing gate as `/week`.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

import numpy as np
from kaiku_contracts import wording
from kaiku_contracts.api import (
    AgentStep,
    CareAction,
    Consensus,
    Course,
    DataCoverage,
    GroupComparison,
    GroupCoverage,
    HelpEffect,
    InsightEdge,
    InsightGraph,
    InsightNode,
    LearnedRoutine,
    MetricComparison,
    ObsTypeCoverage,
    PatientInsight,
    PatientReview,
    PeriodComparison,
    RecordCitation,
    ReviewFinding,
    Routine,
    StateDay,
)
from kaiku_contracts.config import get
from kaiku_contracts.sources import CONSENSUS_SOURCES, SOURCE_LABELS, SOURCE_OF

from . import account, clinician_chat, service, week
from . import course as course_mod
from .analytics import bandit
from .analytics import consensus as consensus_rule
from .analytics.drift import MetricDrift, drift_for
from .analytics.metrics import local_date, parse_ts
from .clinician_chat import compared, human_value
from .llm import gemma, ledger
from .llm.errors import LlmUnavailable
from .llm.explain import contains_banned
from .mind import graph as mind_graph
from .settings import TZ, Settings
from .store.db import Store

REVIEW_VERSION = "insight-review-v12"
_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)
THEMES = ("change", "improvement", "steady", "routine", "what_helps", "coverage")
THEME_TITLE = {"change": "Change from usual", "improvement": "Improved signs", "steady": "Holding steady",
               "routine": "Routine", "what_helps": "What seems to help", "coverage": "Data coverage"}
SUSTAINED = {"drifting": "change_from_usual", "improved": "better_than_usual", "normal": "as_usual",
             "insufficient": "not_enough_data"}
TONE_OF_DRIFT = {"drifting": "worse", "improved": "better", "normal": "similar", "insufficient": "unknown"}
TONE_OF_VERDICT = {"worse": "worse", "better": "better", "as_usual": "similar", "insufficient": "unknown"}
CLOCK_UNITS = ("min after midnight", "min from midnight")
OBS_LABEL = {
    "obs.self_report": "Mood, energy and sleep check-ins", "obs.presence": "Presence at the robot",
    "obs.hrv_session": "Pulse during breathing", "obs.drum_session": "Drum sessions",
    "obs.speech_features": "Speech pace and pauses", "obs.light_level": "Room light",
    "obs.friend_link": "Friend lamp", "obs.outing": "Walks and outings", "obs.laptop_session": "Laptop check-ins",
    "obs.screen_activity": "Mac usage rhythm", "obs.play_session": "Games and tasks",
    "obs.wearable_daily": "Watch daily summary", "obs.phq9": "PHQ-9 questionnaire", "obs.ritual": "Ritual steps",
    "obs.intervention_response": "Before/after activity ratings", "obs.nudge_offered": "Suggestions offered",
    "obs.nudge_outcome": "Suggestion outcomes", "obs.safety_flag": "Safety flags",
    "obs.engagement": "Robot session engagement summary",
}
_SYSTEM = (
    "You are reviewing one person's record for their practitioner after TMS treatment. Say what THIS record shows: "
    "the arc, in order. Each EVIDENCE item has an id, a label, a verified detail, a direction (better | worse | "
    "similar | unknown, against this person's own usual or the week before) and sustained (true = the rule engine "
    "reads a sustained change from usual). The course: items are the timeline: what moved away from usual first, "
    "what followed, what is back within usual, what is still away, and when the care team acted. obs: items are other "
    "recorded signals (for example from the robot) and reflect: is how the person's own reflections sounded, as a "
    "level and themes: cite them as supporting detail in any finding they belong to.\n"
    "Return ONLY JSON: {\"overview\": {\"text\": \"...\", \"cites\": [ids]}, \"findings\": [{\"theme\": "
    "\"change|improvement|steady|routine|what_helps|coverage\", \"cites\": [one to four ids], \"meaning\": \"...\", "
    "\"consider\": \"...\"}]}.\n"
    "overview: three or four sentences for the whole record: what moved first, what followed, what has come back, "
    "what has not, and how sure the record is (say early baseline when RECORD says early). Cite the course: items "
    "you use.\n"
    "findings: three to five, each about a different part of the picture (what moved first; what followed; what is "
    "back; what lags; which routines held or slipped; what the person reported helped). meaning = two sentences that "
    "add what a single fact line cannot: the order, the timing against the care team's call, which measures moved "
    "together, which one lags. Never just restate one item ('Energy is still away from usual' is rejected as "
    "thin). Combine two to four related items per finding. consider = one concrete question or check that follows "
    "from that pattern.\n"
    "GOOD meaning: \"Late-night screen time moved first and sleep shortened the next day; mood and outings "
    "followed. Mood and walks are back within her usual, sleep is the one still lagging.\"\n"
    "GOOD consider: \"Ask what the late nights before the dip were about, and whether sleep is still short.\"\n"
    "BAD (rejected): \"This may impact their overall daily vitality.\" / \"Worth a check-in on how these areas "
    "feel interconnected.\" / \"These habits provide structure to their daily life.\"\n"
    "Rules:\n"
    "- No filler: never write overall, vitality, interconnected, well-being, areas, may impact, daily life. Every "
    "sentence names a measure from the cited items or their order in time.\n"
    "- Never write digits, dates, times, percentages or scores: the server prints them beside your words. Say "
    "'the day after', 'since the care team's call', 'this week'.\n"
    "- Order in time is not cause. Allowed: first, then, followed, came before, since, still, back. Never: because, "
    "caused, due to, led to, results in.\n"
    "- theme change is only for a sustained change from the person's own usual: it needs a cited item with "
    "sustained true. A week-to-week dip inside the usual range is not a change from their usual: leave it out. "
    "improvement needs a cited item with direction better (a course:back_in_range item, or a better week) and no "
    "item that is still worse; steady needs none worse; routine cites a routine: item; what_helps cites a helps: "
    "item whose direction is better (skip it otherwise); coverage is only for a source: item with direction unknown "
    "or a personal baseline that is still forming (skip it otherwise).\n"
    "- status:line, course:back and course:still_away are the reconciled truth. A measure with now = back within "
    "usual is back: never write that it remains, lags or is still away. A measure with now = still away has not "
    "returned. Never say both about one measure. 'Still flagged by the rule' is different from 'still away': "
    "sustained true on a measure that is back means the rule still counts the last several scored days, so say "
    "'the rule still counts those days', not that the measure remains changed.\n"
    "- consider is a question to explore or something to check with the person. Never tell anyone to increase, "
    "reduce or do more of an activity.\n"
    "- Say 'change from their usual', 'worth a check-in'. Never diagnose, never predict, never name a condition, "
    "never say relapse, never state or change the consensus state, never recommend medicine or treatment.\n"
    "- Responses to activities are what the person reported: never write that an activity works, is effective or "
    "is proven; say it is an early or reported response.\n"
    "- Give every signal group whose direction is worse a change finding of its own, citing that source: item "
    "and its most telling measures. Do not repeat the same cites in two findings.\n"
)
_DIGIT = re.compile(r"\d")
_CAUSAL = re.compile(r"\b(because|caus\w*|due to|leads? to|led to|results? in|as a result|driver|driven by|"
                     r"trigger\w*|responsible for|thanks to|explains?)\b", re.I)
_STATE = re.compile(r"\b(needs[_ ]a?[_ ]?call|safety state|watch state|consensus (?:is|state|says)|(?:state|status) is)\b", re.I)
_WORSE_WORD = re.compile(r"\b(wors\w*|declin\w*|deteriorat\w*)\b", re.I)
_BETTER_WORD = re.compile(r"\b(improv\w*|better)\b", re.I)
_OVERCLAIM = re.compile(r"\b(proven|proves?|effective|works|definitely|certainly|clearly helps|established effect)\b", re.I)
_FILLER = re.compile(
    r"\b(overall|vitality|interconnect\w*|(?:may|might|could|can) (?:impact|affect)|impact(?:s|ing)? (?:their|on)|"
    r"structure to their|general sense|well-?being|areas?|holistic|various|a range of|(?:daily|day-to-day) life|"
    r"daily activities|in general|a variety of|different aspects|quality of life)\b", re.I)
_SEQUENCE = re.compile(r"\b(first|then|follow\w*|before|after|since|earlier|later|still|back|lag\w*|came|while|"
                       r"kept|slipped|held|returned|remain\w*|preced\w*)\b", re.I)
_LABEL_NOISE = {"this", "week", "before", "time", "dial", "response", "their", "from", "with", "last", "night",
                "nights", "middle", "daily", "record", "taking", "shape", "course", "change", "care", "team", "apps"}
_BAD_LINT = {"clinical_term", "promise", "medical_advice"}


def cfg(key: str, default: Any) -> Any:
    return get("insight", key, default)


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


def _direction(value: float, other: float, unit: str) -> str:
    if unit in CLOCK_UNITS:
        return "later" if value > other else "earlier"
    return "higher" if value > other else "lower"


def _trend(value: float | None, other: float | None, scale: float | None, worse_when: str, unit: str,
           tolerance: float) -> str:
    if value is None or other is None:
        return "unknown"
    if human_value(value, unit) == human_value(other, unit):
        return "similar"
    band = tolerance * scale if scale else 0.05 * max(abs(other), 1e-9)
    if abs(value - other) <= band:
        return "similar"
    return "worse" if (value > other) == (worse_when == "up") else "better"


def week_sentence(m: Any, a: float | None, b: float | None, usual: float | None, base: Any, d: MetricDrift,
                  n_this: int, vs_prev: str, vs_usual: str) -> str:
    """One plain sentence per measure: this week, the week before, their usual, how many recent days were away."""
    name = course_mod.short(m.label)
    if a is None:
        return f"{name} recorded on {n_this} of 7 days this week, too few to compare."
    out = f"{name} {human_value(a, m.unit)} this week"
    if b is None:
        out += ", too few days the week before to compare"
    elif vs_prev == "similar":
        out += ", about the same as the week before"
    elif m.unit in CLOCK_UNITS:
        out += f", {'later' if a > b else 'earlier'} than {human_value(b, m.unit)} the week before"
    else:
        out += f", {'up' if a > b else 'down'} from {human_value(b, m.unit)} the week before"
    if usual is None:
        out += "; no personal usual yet"
    else:
        early = " (early baseline)" if base.early else ""
        if vs_usual == "similar":
            out += f" and within their usual {human_value(usual, m.unit)}{early}"
        else:
            out += f" and {compared(a, usual, m.unit)} their usual {human_value(usual, m.unit)}{early}"
    if d.status == "drifting":
        out += f"; away from usual on {d.worse_days} of the last {d.scored_days} scored days"
    elif d.status == "improved":
        out += f"; better than usual on {d.better_days} of the last {d.scored_days} scored days"
    return out + "."


# ------------------------------------------------------------------ period comparison
def comparison(crit: Any, data: Any, c: Consensus, end: date) -> tuple[PeriodComparison, dict[str, MetricDrift]]:
    start, prev_start, prev_end = end - timedelta(days=6), end - timedelta(days=13), end - timedelta(days=7)
    need = int(cfg("min_days_per_week", 2))
    drifts: dict[str, MetricDrift] = {}
    by_source: dict[str, list[MetricComparison]] = defaultdict(list)
    for m in crit.metrics:
        series = data.series.get(m.name)
        if not m.enabled or not series:
            continue
        d = drift_for(m, series, end, crit)
        drifts[m.name] = d
        this = [v for day, v in series.items() if start <= day <= end]
        prev = [v for day, v in series.items() if prev_start <= day <= prev_end]
        a = median(this) if len(this) >= need else None
        b = median(prev) if len(prev) >= need else None
        base = d.baseline
        usual = base.median if base else None
        vs_prev = _trend(a, b, base.scale if base else None, m.worse_when, m.unit, float(cfg("similar_scale", 0.5)))
        vs_usual = _trend(a, usual, base.scale if base else None, m.worse_when, m.unit, float(cfg("usual_scale", 1.0)))
        meaning = week_sentence(m, a, b, usual, base, d, len(this), vs_prev, vs_usual)
        by_source[m.source].append(MetricComparison(
            metric=m.name, label=m.label, unit=m.unit, source=m.source, worse_when=m.worse_when,
            this_week=None if a is None else round(a, 3), previous_week=None if b is None else round(b, 3),
            usual=None if usual is None else round(usual, 3),
            early_baseline=bool(base and base.early), baseline_days=base.n if base else None,
            this_week_text=None if a is None else human_value(a, m.unit),
            previous_week_text=None if b is None else human_value(b, m.unit),
            usual_text=None if usual is None else human_value(usual, m.unit),
            days_this_week=min(7, len(this)), days_previous_week=min(7, len(prev)), vs_previous=vs_prev,  # type: ignore[arg-type]
            vs_usual=vs_usual, sustained=SUSTAINED[d.status], meaning=meaning[:300]))  # type: ignore[arg-type]
    groups = []
    for v in c.sources:
        ms = by_source.get(v.source, [])
        days = data.source_days.get(v.source, {})
        n = Counter(m.vs_previous for m in ms)
        trend = "worse" if n["worse"] > n["better"] else "better" if n["better"] > n["worse"] else \
            "similar" if n["similar"] and not n["worse"] else "unknown"
        reading = {"worse": "Change from this person's usual", "better": "Better than this person's usual",
                   "as_usual": "Within this person's usual",
                   "insufficient": "Not enough recent usable data for a reading"}[v.verdict]
        if ms:
            weeks = (f"This week against the week before: {n['better']} improved, {n['worse']} moved away from usual, "
                     f"{n['similar']} about the same, {n['unknown']} not comparable.")
        else:
            weeks = "No measures recorded for this group."
        groups.append(GroupComparison(
            source=v.source, label=SOURCE_LABELS[v.source], verdict=v.verdict, confidence=v.confidence,
            days_this_week=sum(1 for d in days if start <= d <= end),
            days_previous_week=sum(1 for d in days if prev_start <= d <= prev_end),
            trend=trend, meaning=f"{reading}. {weeks}", metrics=ms))  # type: ignore[arg-type]
    flat = [m for g in groups for m in g.metrics]
    improved = [m.metric for m in flat if m.vs_previous == "better"]
    changed = [m.metric for m in flat if m.vs_previous == "worse"]
    comparable = [m for m in flat if m.vs_previous != "unknown"]
    if not comparable:
        summary = "Not enough recorded days in both weeks to compare yet."
    else:
        summary = (f"Of {len(comparable)} comparable measures, {len(improved)} improved on the week before, "
                   f"{len(changed)} were further from their usual and "
                   f"{len(comparable) - len(improved) - len(changed)} stayed about the same.")
    early = any(m.early_baseline for m in flat)
    day_n = (end - data.first_day).days + 1 if data.first_day else 0
    if early:
        summary += f" Day {day_n} of the record: the usual is an early baseline, so read these with lower confidence."
    return PeriodComparison(this_week_start=start, this_week_end=end, previous_week_start=prev_start,
                            previous_week_end=prev_end, day_of_record=max(0, day_n), early_baseline=early,
                            summary=summary[:400], improved=improved, changed=changed,
                            groups=groups), drifts


# ------------------------------------------------------------------ learned routine
def help_effects(data: Any, early: bool = False) -> list[HelpEffect]:
    post = bandit.posteriors(data.nudge_outcomes, data.interventions)
    by_activity = {bandit.ARM_ACTIVITY[arm]: p for arm, p in post.items()}
    out = []
    for h in bandit.help_stats(data.nudge_outcomes, data.interventions):
        al, be, n = by_activity.get(h["activity"], (1.0, 1.0, 0))
        mean, low, high = h["mean_effect"], None, None
        if n and mean is not None:
            draws = np.random.default_rng(0).beta(al, be, 4000)  # fixed seed: the same record gives the same interval
            low = round(min(float(np.quantile(draws, 0.05)), mean), 3)
            high = round(max(float(np.quantile(draws, 0.95)), mean), 3)
        tries = int(h["tries"])
        certainty = "early" if tries < int(cfg("help_early_tries", 3)) or low is None else \
            "consistent" if not early and tries >= int(cfg("help_consistent_tries", 8)) and high - low <= 0.35 \
            else "building"
        if mean is None:
            text = f"{h['label']}: {tries} recorded attempt{'s' if tries != 1 else ''}, no usable before/after rating yet."
        else:
            lean = "above neutral" if mean > 0.55 else "below neutral" if mean < 0.45 else "near neutral"
            span = f", likely between {low:.2f} and {high:.2f}" if low is not None else ""
            text = (f"{h['label']}: reported response {lean} ({mean:.2f} on a 0–1 scale{span}) over {tries} "
                    f"attempt{'s' if tries != 1 else ''}. "
                    + {"early": "Too few attempts to rely on.", "building": "The estimate is still forming.",
                       "consistent": "Consistent across attempts, still a reported response rather than an "
                                     "established effect."}[certainty])
        out.append(HelpEffect(activity=h["activity"], label=h["label"], tries=tries, mean_effect=mean, low=low,
                              high=high, certainty=certainty, text=text[:240]))  # type: ignore[arg-type]
    return out


def learned_routine(r_list: list[Routine], helps: list[HelpEffect], day_n: int = 0, early: bool = False
                    ) -> LearnedRoutine:
    n = Counter(r.status for r in r_list)
    if not r_list:
        summary = "No repeated activity pattern found yet; a routine needs several recorded days."
    else:
        summary = (f"{len(r_list)} repeated pattern{'s' if len(r_list) != 1 else ''} found by code: {n['kept']} kept, "
                   f"{n['partly']} partly kept and {n['slipped']} slipped this week.")
    best = next((h for h in helps if h.mean_effect is not None and h.certainty != "early" and h.mean_effect > 0.55), None)
    if best:
        summary += f" Best reported response so far: {best.label.lower()} (not proof of cause)."
    caveat = ("Responses are what the person reported around an activity. Mood on the day, who accepts a suggestion "
              "and other things happening at the same time are mixed in, so they show a preference, not an effect.")
    if early:
        caveat = (f"Day {day_n} of the record. On a short record these scores can favour an activity that has no "
                  "effect; treat them as early preferences only. " + caveat)
    return LearnedRoutine(routines=r_list, helps=helps, kept=n["kept"], partly=n["partly"], slipped=n["slipped"],
                          summary=summary[:300], day_of_record=day_n, early_record=early, caveat=caveat[:300])


# ------------------------------------------------------------------ coverage
def coverage(events: list[dict[str, Any]], c: Consensus, data: Any, drifts: dict[str, MetricDrift], end: date
             ) -> DataCoverage:
    by_type: dict[str, dict[str, Any]] = {}
    days_all: set[date] = set()
    for e in events:
        ts = parse_ts(e["ts"])
        day = local_date(e["ts"])
        days_all.add(day)
        row = by_type.setdefault(e["type"], {"count": 0, "days": set(), "last": ts, "by": set(), "sim": 0})
        row["count"] += 1
        row["days"].add(day)
        row["last"] = max(row["last"], ts)
        row["by"].add(e["source"])
        row["sim"] += bool(e.get("sim"))

    def rows(types: list[str]) -> list[ObsTypeCoverage]:
        return [ObsTypeCoverage(type=t, label=OBS_LABEL.get(t, t.removeprefix("obs.").replace("_", " ")),
                                count=by_type[t]["count"], days=len(by_type[t]["days"]), last_at=by_type[t]["last"],
                                captured_by=sorted(by_type[t]["by"]), simulated=by_type[t]["sim"])
                for t in sorted(types, key=lambda t: -by_type[t]["count"])]

    verdict = {v.source: v for v in c.sources}
    groups = []
    for s in CONSENSUS_SOURCES:
        if s not in verdict:
            continue
        days = data.source_days.get(s, {})
        groups.append(GroupCoverage(
            source=s, label=SOURCE_LABELS[s], sufficient=verdict[s].verdict != "insufficient",  # type: ignore[arg-type]
            days_last_14=sum(1 for d in days if end - timedelta(days=13) <= d <= end),
            last_at=data.last_data_at.get(s), types=rows([t for t in by_type if SOURCE_OF.get(t) == s])))
    span = (max(days_all) - min(days_all)).days + 1 if days_all else 0
    ready = any(d.baseline is not None for d in drifts.values())
    enough = [g.label for g in groups if g.sufficient]
    missing = [g.label for g in groups if not g.sufficient]
    if not events:
        summary = "No observations recorded yet."
    else:
        summary = (f"{len(events)} observation{'s' if len(events) != 1 else ''} on {len(days_all)} of {span} "
                   f"day{'s' if span != 1 else ''}.")
        summary += " The usual is an early baseline (lower confidence)." if any(
            d.baseline is not None and d.baseline.early for d in drifts.values()) else \
            " Personal usual established for at least one measure." if ready else \
            " Personal usual is still forming; readings stay cautious until then."
        if missing:
            summary += f" Not enough recent data from {', '.join(missing)}."
        elif enough:
            summary += " Every signal group has enough recent data."
    return DataCoverage(
        first_day=min(days_all, default=None), last_day=max(days_all, default=None), span_days=span,
        recorded_days=len(days_all), observations=len(events), baseline_ready=ready, day_of_record=span,
        early_baseline=any(d.baseline is not None and d.baseline.early for d in drifts.values()),
        simulated=bool(data.sim), summary=summary[:300], groups=groups,
        other=rows([t for t in by_type if SOURCE_OF.get(t) not in CONSENSUS_SOURCES]))


# ------------------------------------------------------------------ permitted graph
def graph(patient_id: str, c: Consensus, comp: PeriodComparison, cov: DataCoverage, r_list: list[Routine],
          helps: list[HelpEffect], events: list[dict[str, Any]], episodes: list[dict[str, Any]], shared: bool,
          now: datetime, found: dict[str, Any] | None = None, actions: list[dict[str, Any]] | None = None,
          topics: dict[str, int] | None = None, end: date | None = None) -> InsightGraph:
    nodes: dict[str, InsightNode] = {}
    edges: list[InsightEdge] = []
    nodes["person"] = InsightNode(id="person", kind="person", label=service.display_name(patient_id, cov.first_day),
                                  detail=cov.summary[:240], evidence=cov.observations)
    group_cov = {g.source: g for g in cov.groups}
    for g in comp.groups:
        gid = f"group:{g.source}"
        gc = group_cov.get(g.source)
        nodes[gid] = InsightNode(id=gid, kind="signal_group", label=g.label, detail=g.meaning[:240],
                                 evidence=gc.days_last_14 if gc else 0, tone=TONE_OF_VERDICT[g.verdict])  # type: ignore[arg-type]
        edges.append(InsightEdge(src="person", dst=gid, rel="has_signal",
                                 label=g.verdict.replace("_", " "), weight=round(g.confidence, 3),
                                 evidence=gc.days_last_14 if gc else 0))
        for m in g.metrics:
            mid = f"measure:{m.metric}"
            tone = {"change_from_usual": "worse", "better_than_usual": "better", "as_usual": "similar",
                    "not_enough_data": "unknown"}[m.sustained]
            n_days = m.days_this_week + m.days_previous_week
            nodes[mid] = InsightNode(id=mid, kind="measure", label=m.label, detail=m.meaning[:240], evidence=n_days,
                                     tone=tone)  # type: ignore[arg-type]
            edges.append(InsightEdge(src=gid, dst=mid, rel="measures", label=m.sustained.replace("_", " "),
                                     weight=round(m.days_this_week / 7, 3), evidence=n_days))
    since = now - timedelta(days=mind_graph.EPISODE_DAYS)
    occ = week.occurrences([e for e in events if parse_ts(e["ts"]) >= since], None)
    talked: Counter[str] = Counter()
    if shared:
        for ep in episodes:
            if ep.get("outcome") == "completed" and ep.get("intent") in mind_graph.INTENT_ACTIVITY \
                    and parse_ts(ep["start"]) >= since:
                talked[mind_graph.INTENT_ACTIVITY[ep["intent"]]] += 1
    help_of = {h.activity: h for h in helps}
    for key in sorted({*occ, *talked}):
        if key == "sleep" or key not in week.ACTIVITIES:
            continue
        days = len({week._day_of(key, t) for t in occ.get(key, [])})
        aid = f"activity:{key}"
        detail = f"Recorded on {days} day{'s' if days != 1 else ''} in the last {mind_graph.EPISODE_DAYS} days."
        if talked[key]:
            detail += f" {talked[key]} shared conversation{'s' if talked[key] != 1 else ''} about it."
        h = help_of.get(key)
        tone = "better" if h and h.mean_effect is not None and h.certainty != "early" and h.mean_effect > 0.55 \
            else "unknown"
        nodes[aid] = InsightNode(id=aid, kind="activity", label=week.ACTIVITIES[key][1], detail=detail,
                                 evidence=days + talked[key], tone=tone)  # type: ignore[arg-type]
        edges.append(InsightEdge(src="person", dst=aid, rel="did", label=f"{days} days",
                                 weight=round(min(1.0, days / mind_graph.EPISODE_DAYS), 3), evidence=days + talked[key]))
        if h and h.mean_effect is not None:
            edges.append(InsightEdge(src=aid, dst="person", rel="helped", layer="learned",
                                     label=f"{h.certainty} reported response, {h.tries} attempts",
                                     weight=h.mean_effect, evidence=h.tries))
    for r in r_list:
        rid = f"routine:{r.activity}"
        name = "Asleep" if r.activity == "sleep" else course_mod.short(r.label)
        nodes[rid] = InsightNode(id=rid, kind="routine", layer="learned", label=f"{name} · around {r.usual_time}",
                                 detail=f"{r.label}: {r.text}"[:240],
                                 evidence=r.this_week,
                                 tone={"kept": "similar", "partly": "unknown", "slipped": "worse"}[r.status])  # type: ignore[arg-type]
        expected = 1.0 if r.cadence == "weekly" else max(r.usual_per_week, 1.0)
        edges.append(InsightEdge(src="person", dst=rid, rel="keeps", layer="learned",
                                 label=f"{r.status}: {r.this_week} of the last 7 days",
                                 weight=round(min(1.0, r.this_week / expected), 3), evidence=r.this_week))
        target = f"activity:{r.activity}" if f"activity:{r.activity}" in nodes else \
            "group:wearable" if r.activity == "sleep" and "group:wearable" in nodes else None
        if target:
            edges.append(InsightEdge(src=rid, dst=target, rel="of", label="pattern of", weight=1.0, evidence=r.this_week))
    if found:
        all_occ = week.occurrences(events, None)
        edges += course_mod.learned(found, actions or [], r_list, all_occ, end or now.astimezone(TZ).date(), nodes)
        for mc in found.values():  # a measure that took part in the course is something learned about this person
            mid = f"measure:{mc.metric.name}"
            if mid in nodes:
                nodes[mid] = nodes[mid].model_copy(update={"layer": "learned"})
    topic_label = {"people": "People in their notebook", "places": "Places in their notebook",
                   "likes": "Things they like", "helpers": "What they say helps", "plans": "Plans they mentioned"}
    for category, count in sorted((topics or {}).items()):
        if category in topic_label and count:
            tid = f"topic:{category}"
            nodes[tid] = InsightNode(id=tid, kind="shared_topic", layer="learned", label=topic_label[category],
                                     detail=f"{count} note{'s' if count != 1 else ''} the person told Kaiku. Shared as "
                                            "a count only: names and words stay private.", evidence=count)
            edges.append(InsightEdge(src="person", dst=tid, rel="has_signal", layer="learned", label="told Kaiku",
                                     weight=round(min(1.0, count / 5), 3), evidence=count))
    basis = ["observations", *(["shared_conversations"] if shared and (talked or topics) else [])]
    note = ("Built from recorded observations" + (" and shared conversation counts" if shared and talked else "")
            + ". People, places, preferences, plans, memories and conversation words are never shown here.")
    layers = sorted({n.layer for n in nodes.values()} | {e.layer for e in edges})
    return InsightGraph(nodes=list(nodes.values()), edges=edges, layers=layers, shared=shared, basis=basis,  # type: ignore[arg-type]
                        note=note)


# ------------------------------------------------------------------ evidence for the review
def review_evidence(refs: list[RecordCitation], c: Consensus, comp: PeriodComparison, drifts: dict[str, MetricDrift],
                    r_list: list[Routine], helps: list[HelpEffect], end: date, course: Course | None = None,
                    extra: list[tuple[RecordCitation, str]] | None = None
                    ) -> tuple[list[RecordCitation], dict[str, str]]:
    """Citable records with a code-computed direction each. Adds week-over-week and what-helps records."""
    tone: dict[str, str] = {}
    verdict = {v.source: v.verdict for v in c.sources}
    worse_when = {m.metric: m.worse_when for g in comp.groups for m in g.metrics}
    status = {r.activity: r.status for r in r_list}
    out = []
    for ref in refs:
        if ref.id.startswith("task:"):
            continue  # capture metadata is inspected in the task view; it carries no direction to interpret
        if ref.id.startswith("source:"):
            tone[ref.id] = TONE_OF_VERDICT[verdict.get(ref.source or "", "insufficient")]
        elif ref.id.startswith("metric:") and ref.metric in drifts:
            tone[ref.id] = TONE_OF_DRIFT[drifts[ref.metric].status]
        elif ref.id.startswith("pattern:") and ref.metric and ref.value is not None and ref.baseline is not None:
            tone[ref.id] = _trend(ref.value, ref.baseline, None, worse_when.get(ref.metric, "down"), ref.unit or "", 0.0)
        elif ref.id.startswith("routine:"):
            tone[ref.id] = {"kept": "similar", "slipped": "worse"}.get(status.get(ref.id.split(":", 1)[1], ""), "unknown")
        else:
            tone[ref.id] = "unknown"
        out.append(ref)
    for g in comp.groups:
        for m in g.metrics:
            if m.vs_previous == "unknown":
                continue
            rid = f"week:{m.metric}"
            out.append(RecordCitation(id=rid, label=course_mod.short(m.label), detail=m.meaning,
                                      metric=m.metric, source=m.source, observed_at=end, value=m.this_week,
                                      unit=m.unit, baseline=m.previous_week))
            tone[rid] = m.vs_previous
    for h in helps:
        rid = f"helps:{h.activity}"
        out.append(RecordCitation(id=rid, label=f"Response to {h.label.lower()}",
                                  detail=h.text + " A reported response, not proof of cause.", observed_at=end))
        tone[rid] = "better" if h.mean_effect is not None and h.certainty != "early" and h.mean_effect > 0.55 else "unknown"
    for record, direction in extra or []:
        out.append(record)
        tone[record.id] = direction
    if course:
        out.append(RecordCitation(id="course:summary", label="Course of change", detail=course.summary, observed_at=end))
        tone["course:summary"] = "unknown"
        n = 0
        for e in course.events:
            if e.kind == "lowest":
                continue  # shown on the timeline; onset and where it stands now carry the arc
            n += 1
            rid = f"course:{e.kind}:{e.metric_id or n}"
            out.append(RecordCitation(id=rid, label=e.label, detail=e.text, metric=e.metric_id, source=e.group,
                                      observed_at=e.date))
            tone[rid] = {"onset": "worse", "still_away": "worse", "back_in_range": "better", "reflection_low": "worse",
                         "reflection_lighter": "better"}.get(e.kind, "unknown")
    return out, tone


def shortlist(refs: list[RecordCitation], tone: dict[str, str], limit: int) -> list[RecordCitation]:
    """What the model reads: everything with a recorded change first, then context, bounded."""
    def rank(ref: RecordCitation) -> tuple[int, int]:
        kind = ref.id.split(":", 1)[0]
        if kind in ("consensus", "source", "course") or ref.id == "pattern:collection":
            return (0, 0)
        if kind in ("routine", "helps", "reflect", "obs"):
            return (1, 0)
        moved = tone.get(ref.id) in ("worse", "better")
        return (2 if moved else 3, {"week": 0, "pattern": 1, "metric": 2}.get(kind, 3))
    in_course = {r.metric for r in refs if r.id.startswith("course:") and r.metric}
    # A measure on the course timeline is already described twice (course + week): its latest-point and
    # first-vs-latest-week records would only repeat it.
    keep = [r for r in refs if not (r.id.split(":", 1)[0] in ("metric", "pattern") and r.metric in in_course)]
    return sorted(keep, key=rank)[:limit]


# ------------------------------------------------------------------ findings: validation + template
def fact_of(r: RecordCitation) -> str:
    """The record as one sentence. Sentences that already open with their own subject are not prefixed again."""
    if not r.detail:
        return r.label
    return r.detail if r.detail.startswith(r.label) or r.id.startswith("course:") else f"{r.label}: {r.detail}"


def _finding(theme: str, cites: list[RecordCitation], meaning: str, consider: str | None, by: str) -> ReviewFinding:
    labels = list(dict.fromkeys(r.label.split(":")[0].split(" (")[0] for r in cites))
    title = THEME_TITLE[theme] + (": " + ", ".join(labels[:3]) if labels else "")
    return ReviewFinding(theme=theme, title=title[:120], meaning=meaning[:400], consider=(consider or None) and consider[:300],  # type: ignore[arg-type]
                         facts=[fact_of(r) for r in cites],
                         cites=[r.id for r in cites], by=by)  # type: ignore[arg-type]


def sustained_ids(refs: list[RecordCitation], tone: dict[str, str], drifts: dict[str, MetricDrift]) -> set[str]:
    """Records that stand for a sustained change from usual by the rule engine (not a one-week difference)."""
    out = set()
    for r in refs:
        kind = r.id.split(":", 1)[0]
        if kind in ("source", "routine") and tone.get(r.id) == "worse":
            out.add(r.id)
        elif kind in ("metric", "week", "pattern", "course") and r.metric in drifts and drifts[r.metric].status == "drifting" \
                and tone.get(r.id) == "worse":
            out.add(r.id)
    return out


def prose_issue(prose: str) -> str | None:
    """Checks every sentence the model writes must pass, as a content-free category."""
    if _DIGIT.search(prose):
        return "numbers_in_prose"
    if contains_banned(prose) or _STATE.search(prose) or \
            wording.codes(wording.lint(prose, max_questions=None)) & _BAD_LINT:
        return "wording"
    if _CAUSAL.search(prose):
        return "causal_claim"
    if _OVERCLAIM.search(prose):
        return "overclaim"
    if _FILLER.search(prose):
        return "filler"
    return None


_BACK = re.compile(r"\b(back|return\w*|recover\w*|restor\w*|normali[sz]\w*|within (?:their |her |his )?usual|"
                   r"in range|came back|come back)\b", re.I)
_AWAY = re.compile(r"\b(still (?:away|below|above|low|lower|short|shorter|later|reduced|a change)|remain\w*|"
                   r"lag\w*|not (?:yet )?(?:back|returned|recovered)|has(?: not|n't) (?:come back|returned)|"
                   r"have(?: not|n't) (?:come back|returned)|yet to return|sustained change|persist\w*)\b", re.I)
_RULE_TALK = re.compile(r"\b(flag\w*|rule|consensus|counts?|scored days)\b", re.I)
_CLAUSE = re.compile(r"[.;:]|,? but |,? while |,? although |,? whereas |,? yet |,? though ", re.I)
_DIRECTIVE = re.compile(r"\b(increas\w*|decreas\w*|reduc\w*|should|must|needs? to|ought|more often|less often|"
                        r"more frequently|encourag\w*|make sure|get (?:her|him|them) to|try to|cut down|step up)\b", re.I)


def measure_terms(names: dict[str, str]) -> dict[str, set[str]]:
    """term -> metrics it can mean: the label without brackets, and its head word ('energy' for 'Energy dial')."""
    out: dict[str, set[str]] = defaultdict(set)
    skip = {"last", "first", "time", "middle", "daily", "steps", "late", "night", "drum", "the", "on", "in"}
    for metric, label in names.items():
        low = course_mod.short(label).lower()
        out[low].add(metric)
        for word in re.findall(r"[a-z]{4,}", low):
            if word not in skip and word != "dial":
                out[word].add(metric)
    return out


def consistency_issue(text: str, back: set[str], away: set[str], names: dict[str, str]) -> str | None:
    """A measure is either back within usual or still away, per the course. Reject prose that says a measure is
    away when the course has it back (or the reverse), or that says both about the same measure. A clause about
    the rule still flagging something is not a claim that the measure is away."""
    if not back and not away:
        return None
    terms = measure_terms(names)
    said: dict[str, set[str]] = defaultdict(set)
    for clause in _CLAUSE.split(text):
        low = clause.lower()
        is_back, is_away = bool(_BACK.search(low)), bool(_AWAY.search(low)) and not _RULE_TALK.search(low)
        if is_back == is_away:
            continue  # no claim, or a mixed clause we cannot split safely
        for term, metrics in terms.items():
            if re.search(rf"\b{re.escape(term)}\b", low):
                side = "back" if is_back else "away"
                said[term].add(side)
                if side == "away" and metrics <= back:
                    return "contradiction"
                if side == "back" and metrics <= away:
                    return "contradiction"
    return "contradiction" if any(len(sides) == 2 for sides in said.values()) else None


def specific(prose: str, cites: list[RecordCitation]) -> bool:
    """The words must be about these records: name a cited measure, or say something about order or timing."""
    low = prose.lower()
    stems = {w[:5] for r in cites for w in re.findall(r"[a-z]{4,}", r.label.lower()) if w not in _LABEL_NOISE}
    return any(stem in low for stem in stems) or bool(_SEQUENCE.search(prose))


def check_overview(item: Any, allowed: dict[str, RecordCitation], needs_course: bool,
                   truth: tuple[set[str], set[str], dict[str, str]] | None = None) -> tuple[str, list[str]] | str:
    if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not isinstance(item.get("cites"), list):
        return "invalid_shape"
    text = " ".join(item["text"].split())
    ids = list(dict.fromkeys(str(x).strip("[] ") for x in item["cites"]))[:8]
    if not 40 <= len(text) <= 700 or not ids:
        return "invalid_shape"
    if any(i not in allowed for i in ids):
        return "unknown_citation"
    issue = prose_issue(text) or (consistency_issue(text, *truth) if truth else None)
    if issue:
        return issue
    if needs_course and not (any(i.startswith("course:") for i in ids) and _SEQUENCE.search(text)):
        return "generic"
    if not specific(text, [allowed[i] for i in ids]):
        return "generic"
    return text, ids


def check_finding(item: Any, allowed: dict[str, RecordCitation], tone: dict[str, str],
                  sustained: set[str] | None = None,
                  truth: tuple[set[str], set[str], dict[str, str]] | None = None) -> ReviewFinding | str:
    """One model finding → a rendered finding, or the content-free category it was rejected for."""
    if not isinstance(item, dict):
        return "invalid_shape"
    theme, cites, meaning, consider = item.get("theme"), item.get("cites"), item.get("meaning"), item.get("consider")
    if theme not in THEMES or not isinstance(meaning, str) or not meaning.strip() or len(meaning) > 400 \
            or not isinstance(cites, list) or not cites or not all(isinstance(x, str) for x in cites) \
            or not (consider is None or (isinstance(consider, str) and len(consider) <= 300)):
        return "invalid_shape"
    ids = list(dict.fromkeys(x.strip("[] ") for x in cites))[:4]
    if any(i not in allowed for i in ids):
        return "unknown_citation"
    prose = f"{meaning} {consider or ''}"
    issue = prose_issue(prose) or (consistency_issue(meaning, *truth) if truth else None)
    if issue:
        return issue
    if consider and _DIRECTIVE.search(consider):
        return "directive"  # a consider line is a question to explore with the person, never an instruction
    if not specific(meaning, [allowed[i] for i in ids]):
        return "generic"
    if len(meaning.split()) < 8 or (len(meaning.split()) < 12 and not _SEQUENCE.search(meaning)):
        return "thin"  # restates one fact line: adds no order, timing or comparison
    # Where a measure started is history: it does not make a finding about what has come back a "worse" one.
    history = {i for i in ids if i.startswith("course:onset:")} if any(tone.get(i) == "better" for i in ids) else set()
    # Reflections and other recorded signals are supporting detail: they never decide a finding's theme.
    tones = [tone.get(i, "unknown") for i in ids if i not in history
             and not i.startswith(("reflect:", "obs:", "course:reflection_"))]
    if sustained is None:
        sustained = {i for i in ids if tone.get(i) == "worse" and i.split(":", 1)[0] in ("source", "metric", "routine")}
    ok = {"change": any(i in sustained for i in ids),
          "improvement": "better" in tones and "worse" not in tones,
          "steady": "worse" not in tones and ("similar" in tones or "better" in tones),
          "routine": any(i.startswith("routine:") for i in ids),
          "what_helps": any(i.startswith("helps:") and tone.get(i) == "better" for i in ids),
          "coverage": any(i.startswith("source:") and tone.get(i) == "unknown" for i in ids)
          or ("pattern:collection" in ids and "forming" in allowed["pattern:collection"].detail)}[theme]
    if not ok:
        return "direction_mismatch"
    directional = {t for t in tones if t in ("better", "worse")}
    if (directional == {"better"} and _WORSE_WORD.search(meaning)) or \
            (directional == {"worse"} and _BETTER_WORD.search(meaning)):
        return "direction_mismatch"
    return _finding(theme, [allowed[i] for i in ids], " ".join(meaning.split()), consider and " ".join(consider.split()),
                    "gemma")


def validate(raw: str, allowed: dict[str, RecordCitation], tone: dict[str, str], sustained: set[str] | None = None,
             needs_course: bool = False, parsed: dict[str, Any] | None = None,
             truth: tuple[set[str], set[str], dict[str, str]] | None = None
             ) -> tuple[list[ReviewFinding], dict[str, int]]:
    """Findings that pass, and rejection counts. `parsed` receives the checked overview under "overview"
    (a (text, cites) pair, or the category it was rejected for)."""
    raw = raw.strip()
    if raw.startswith("```") and raw.splitlines()[-1].strip() == "```":
        raw = "\n".join(raw.splitlines()[1:-1])
    data = json.loads(raw)
    items = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("invalid_object")
    if parsed is not None:
        parsed["overview"] = check_overview(data.get("overview"), allowed, needs_course, truth)
    kept: list[ReviewFinding] = []
    rejected: Counter[str] = Counter()
    seen: set[tuple[str, ...]] = set()
    for item in items[:8]:
        result = check_finding(item, allowed, tone, sustained, truth)
        if isinstance(result, str):
            rejected[result] += 1
        elif tuple(sorted(result.cites)) in seen:
            rejected["duplicate"] += 1
        else:
            seen.add(tuple(sorted(result.cites)))
            kept.append(result)
    return kept[:6], dict(rejected)


def template_findings(refs: list[RecordCitation], tone: dict[str, str], c: Consensus, comp: PeriodComparison,
                      routine: LearnedRoutine, cov: DataCoverage, arc: Course | None = None) -> list[ReviewFinding]:
    by_id = {r.id: r for r in refs}
    metrics = {m.metric: m for g in comp.groups for m in g.metrics}
    out: list[ReviewFinding] = []

    def pick(*ids: str) -> list[RecordCitation]:
        return [by_id[i] for i in ids if i in by_id][:4]

    for v in c.sources:
        if v.verdict != "worse":
            continue
        names = [e.metric for e in v.evidence if e.metric in metrics][:3]
        labels = ", ".join(course_mod.short(metrics[n].label).lower() for n in names)
        returned = {e.metric_id for e in (arc.events if arc else []) if e.kind == "back_in_range"}
        back = [course_mod.short(metrics[n].label).lower() for n in names if n in returned]
        meaning = f"{SOURCE_LABELS[v.source]}: sustained change from their usual over the last several days"
        meaning += f", mostly in {labels}." if labels else "."
        if back:
            meaning += f" On the latest days {', '.join(back)} {'are' if len(back) > 1 else 'is'} back within usual."
        out.append(_finding(
            "change", pick(f"source:{v.source}", *[f"week:{n}" if f"week:{n}" in by_id else f"metric:{n}" for n in names]),
            meaning, "Ask how the days around the change were, and whether it feels over; the record cannot say why."
            if back else "Worth a check-in about how these days have been; the record cannot say why.", "template"))
    better = [m for m in metrics.values() if m.sustained == "better_than_usual" or m.vs_previous == "better"][:3]
    if better:
        out.append(_finding(
            "improvement", pick(*[f"week:{m.metric}" if f"week:{m.metric}" in by_id else f"metric:{m.metric}" for m in better]),
            "Improved signs against the week before or this person's usual in "
            + ", ".join(m.label.lower() for m in better) + ".",
            "Worth asking what has been going well, so it can be kept up.", "template"))
    steady = [v for v in c.sources if v.verdict in ("as_usual", "better")]
    if steady:
        out.append(_finding(
            "steady", pick(*[f"source:{v.source}" for v in steady]),
            ", ".join(SOURCE_LABELS[v.source] for v in steady) + " stay within or better than this person's usual.",
            None, "template"))
    r_refs = pick(*[f"routine:{r.activity}" for r in sorted(routine.routines, key=lambda r: r.status != "slipped")][:3])
    if r_refs:
        slipped = [r.label.lower() for r in routine.routines if r.status == "slipped"]
        out.append(_finding(
            "routine", r_refs, routine.summary.split(" Best reported")[0],
            f"Worth asking how {slipped[0]} have been going." if slipped else None, "template"))
    best = next((h for h in routine.helps if h.mean_effect is not None and h.certainty != "early"
                 and h.mean_effect > 0.55), None)
    if best and f"helps:{best.activity}" in by_id:
        out.append(_finding(
            "what_helps", pick(f"helps:{best.activity}"),
            f"{best.label}: the best reported response so far. This is what the person reported around the "
            "activity, not proof that it helped.",
            f"Ask whether {best.label.lower()} still feel worth doing.", "template"))
    missing = [v for v in c.sources if v.verdict == "insufficient"]
    if missing or not cov.baseline_ready:
        out.append(_finding(
            "coverage", pick(*[f"source:{v.source}" for v in missing], "pattern:collection"),
            ("Not enough recent usable data from " + ", ".join(SOURCE_LABELS[v.source] for v in missing) + ". "
             if missing else "") + ("A personal usual is still forming. " if not cov.baseline_ready else "")
            + "Missing data is never read as being well.", None, "template"))
    return [f for f in out if f.cites][:6]


def headline(c: Consensus) -> str:
    """Code states where the consensus stands; the model never does."""
    worse = [SOURCE_LABELS[v.source] for v in c.sources if v.verdict == "worse"]
    usual = [SOURCE_LABELS[v.source] for v in c.sources if v.verdict in ("as_usual", "better")]
    missing = [SOURCE_LABELS[v.source] for v in c.sources if v.verdict == "insufficient"]
    lead = {"safety": "Safety flag on record: call today.", "needs_call": "Worth a check-in call.",
            "watch": "Worth a look at the next contact.", "stable": "In line with this person's usual."}[c.state]
    parts = [lead]
    if worse:
        parts.append("Change from usual in " + ", ".join(worse) + ".")
    if usual:
        parts.append(", ".join(usual) + (" are" if len(usual) > 1 else " is") + " as usual or better.")
    if missing:
        parts.append("Not enough recent data from " + ", ".join(missing) + ".")
    return " ".join(parts)[:240]


# ------------------------------------------------------------------ review with cache, cooldown and trace
def review(store: Store, settings: Settings, patient_id: str, c: Consensus, refs: list[RecordCitation],
           tone: dict[str, str], template: list[ReviewFinding], now: datetime, *, generate: bool, gen: Any = None,
           sustained: set[str] | None = None, day_n: int = 0, early: bool = False, needs_course: bool = False,
           truth: tuple[set[str], set[str], dict[str, str]] | None = None
           ) -> tuple[PatientReview, list[AgentStep]]:
    model = gemma.model_name()
    sent = shortlist(refs, tone, int(cfg("max_evidence", 60)))
    sustained = sustained or set()
    back_now, away_now, _names = truth or (set(), set(), {})
    context = [{"id": r.id, "label": r.label, "detail": r.detail, "direction": tone.get(r.id, "unknown"),
                "sustained": r.id in sustained,
                **({"now": "back within usual" if r.metric in back_now else "still away from usual"}
                   if r.metric in back_now | away_now else {})} for r in sent]
    record = {"day_of_record": day_n, "baseline": "early, lower confidence" if early else "established"}
    digest = hashlib.sha256(json.dumps([REVIEW_VERSION, context, early, model], sort_keys=True).encode()).hexdigest()
    head = headline(c)
    if early:
        head = (head + f" Day {day_n} of the record: early baseline, lower confidence.")[:240]
    select = AgentStep(step="select", label="Shortlist evidence", actor="code", status="ok", items=len(sent),
                       detail=f"{len(sent)} of {len(refs)} citable records, changes first, each with a recorded direction.")

    def fallback(reason: str, steps: list[AgentStep]) -> tuple[PatientReview, list[AgentStep]]:
        return PatientReview(headline=head, findings=template, by="template", fallback_reason=reason,
                             day_of_record=day_n, early_record=early, generated_at=now), steps

    key = f"insight-review:{patient_id}"
    with _LOCKS[f"{settings.db_path}:{patient_id}"]:
        cached = store.kv_get(key)
        if cached and cached.get("digest") == digest:
            saved = PatientReview.model_validate(cached["review"])
            steps = [AgentStep.model_validate(s) for s in cached["steps"]]
            if saved.by == "gemma":
                steps = [s.model_copy(update={"status": "cached", "cache_hit": True}) if s.step == "interpret" else s
                         for s in steps]
                return saved.model_copy(update={"cached": True, "headline": head}), [select, *steps]
        if not generate:
            return fallback("not_requested", [select, AgentStep(
                step="interpret", label="Gemma review", actor="template", status="skipped",
                detail="No model call was requested for this read; the deterministic review is shown.")])
        cooldown = float(cfg("cooldown_s", 60))
        last = store.kv_get(f"insight-review-last:{patient_id}")
        if last and (now - datetime.fromisoformat(last["ts"])).total_seconds() < cooldown:
            return fallback("cooldown", [select, AgentStep(
                step="interpret", label="Gemma review", actor="template", status="skipped",
                detail="A review was generated moments ago; new evidence is shown through the deterministic review "
                       "until the cooldown ends.")])
        store.kv_set(f"insight-review-last:{patient_id}", {"ts": now.isoformat()})
        gen = gen or gemma.generate
        allowed = {r.id: r for r in sent}
        refs_by_id = {r.id: r for r in refs}
        prompt = (_SYSTEM + "RECORD:\n" + json.dumps(record) + "\nEVIDENCE:\n"
                  + json.dumps(context, ensure_ascii=False))
        findings: list[ReviewFinding] = []
        rejected: Counter[str] = Counter()
        parsed: dict[str, Any] = {}
        reason, attempts, t0 = None, 0, time.perf_counter()
        for attempt in (1, 2):
            attempts = attempt
            try:
                raw = gen(prompt, timeout_s=float(cfg("timeout_s", 30)), task="insight_review", home_id=patient_id)
                findings, bad = validate(raw, allowed, tone, sustained, needs_course, parsed, truth)
                rejected.update(bad)
                if findings:
                    reason = None
                    break
                reason = "no_valid_findings"
            except LlmUnavailable:
                reason = "provider_unavailable"
                break
            except (ValueError, TypeError, AttributeError):
                reason = "invalid_json"
                rejected["invalid_json"] += 1
            prompt += ("\nYour previous response failed validation (" + ", ".join(sorted(rejected)) + "). Return one "
                       "complete JSON object, cite only the given ids, keep each theme consistent with the recorded "
                       "direction, name the measures and their order, and write no digits and no filler.")
        latency = _ms(t0)
        interpret = AgentStep(
            step="interpret", label="Gemma review", actor="gemma" if findings else "template",
            status="ok" if findings else "fallback", model=model or None, latency_ms=latency, items=len(findings),
            detail=(f"{gemma.provider_label()}: {attempts} call{'s' if attempts != 1 else ''}; interpretation only, "
                    "no numbers." if findings
                    else f"{gemma.provider_label()}: output not used ({reason}); the deterministic review is shown."))
        check = AgentStep(
            step="validate", label="Check every finding", actor="code",
            status="ok" if findings else "rejected", items=len(findings), rejected=dict(rejected),
            detail="Known citation ids, no digits, permitted wording, no causal claim, no filler, names a cited "
                   "measure or its timing, agrees with which measures are back or still away, consider is a "
                   "question not an instruction, theme consistent with the recorded direction.")
        seen = parsed.get("overview")
        overview = seen if isinstance(seen, tuple) and findings else None
        about = AgentStep(
            step="overview", label="Gemma's reading of the whole record", actor="gemma" if overview else "template",
            status="ok" if overview else "rejected" if isinstance(seen, str) and findings else "skipped",
            model=(model or None) if overview else None, items=len(overview[1]) if overview else 0,
            rejected={seen: 1} if isinstance(seen, str) and findings else {},
            detail=("Whole-record paragraph accepted: cites the course of change, agrees with which measures are "
                    "back or still away, and passed the same checks."
                    if overview else "No model paragraph is shown; the code-written course summary stands in its "
                                     "place."))
        added = 0
        if findings:
            # The model interprets; it cannot leave a recorded change out. Any signal group with a change from
            # usual that no accepted finding covers gets its deterministic finding.
            covered = {allowed[i].source for f in findings if f.theme == "change" for i in f.cites if i in allowed}
            for t in template:
                source = next((refs_by_id[i].source for i in t.cites if i.startswith("source:")), None)
                if t.theme == "change" and source not in covered and len(findings) < 8:
                    findings.append(t)
                    added += 1
            findings.sort(key=lambda f: THEMES.index(f.theme))
            if added:
                check.detail = (check.detail + f" Added {added} deterministic finding{'s' if added != 1 else ''} for "
                                "recorded change the model left out.")[:300]
        if not findings:
            ledger.record("template", "insight_review", ok=True, fallback=True, route=reason, home_id=patient_id)
            result = PatientReview(headline=head, findings=template, by="template", fallback_reason=reason,
                                   day_of_record=day_n, early_record=early, generated_at=now)
        else:
            ledger.record(model, "insight_review.route", ok=True, route="gemma", latency_ms=latency, home_id=patient_id)
            result = PatientReview(headline=head, findings=findings, by="gemma", model=model or None,
                                   overview=overview[0] if overview else None,
                                   overview_cites=overview[1] if overview else [],
                                   day_of_record=day_n, early_record=early, generated_at=now)
        steps = [interpret, about, check]
        store.kv_set(key, {"digest": digest, "review": result.model_dump(mode="json"),
                           "steps": [step.model_dump(mode="json") for step in steps]})
        return result, [select, *steps]


STATE_NAME = {"needs_call": "Needs a call", "watch": "Worth a look", "stable": "As usual", "safety": "Safety flag"}


def status_line(c: Consensus, replayed: list[Any], actions: list[dict[str, Any]], arc: Course, crit: Any,
                day_n: int, min_stable: int) -> str:
    """Why the record shows the state it shows, and how that sits with the course: when it was raised, what has come
    back since, and what keeps the state there. Every clause is read off the rule's own replay."""
    name = STATE_NAME[c.state]
    since = None
    for day in reversed(replayed):
        if day.state != c.state:
            break
        since = day.day
    on = f" on {course_mod.human_date(since)}" if since else ""
    last = replayed[-1] if replayed else None
    worse = [SOURCE_LABELS[v.source] for v in c.sources if v.verdict == "worse"]
    young = bool(min_stable) and day_n < min_stable
    back = (f" Since the low on {course_mod.human_date(arc.low_date)}, {arc.back} of {arc.moved} measures that moved "
            "away are back within their usual.") if arc.moved and arc.low_date else ""
    if c.state == "safety":
        return (f"{name} raised{on}. Kaiku showed the person the crisis numbers on their own device; it contacts "
                "nobody. It stays until the care team acknowledges it: call today.")
    if c.state == "needs_call":
        ack = next((a for a in actions if a["action"] == "acknowledge" and since
                    and parse_ts(a["ts"]).astimezone(TZ).date() >= since), None)
        out = f"{name} was raised{on} from the daily signals"
        out += (f" and acknowledged on {course_mod.human_date(parse_ts(ack['ts']).astimezone(TZ).date())}"
                + (f" by {ack['by']}" if ack.get("by") else "")) if ack else " and is not yet acknowledged"
        out += "." + back
        if last is not None and last.raw == "needs_call":
            out += (f" It still shows because {len(worse)} signal groups ({', '.join(worse)}) read as changed over "
                    "the last several scored days, not only the latest one.")
        else:
            out += (f" The groups are back; the flag is held until {crit.state.hysteresis_stable_days} as-usual days "
                    "in a row or an acknowledgement.")
        if young:
            out += f" On a young record (day {day_n} of {min_stable}) it cannot return to as usual before day {min_stable}."
        return out[:600]
    if c.state == "watch":
        if c.agreement == "low_coverage" and young and not worse:
            why = (f"Day {day_n} of {min_stable}: too early to call this as usual, whatever the measures show."
                   if sum(v.verdict != "insufficient" for v in c.sources) >= 2 else
                   "Fewer than two signal groups have enough recent data, and missing data is never read as being well.")
        elif c.agreement == "low_coverage":
            why = "Fewer than two signal groups have enough recent data, and missing data is never read as being well."
        else:
            why = (f"{', '.join(worse) or 'One group'} read{'s' if len(worse) == 1 else ''} as changed from usual; "
                   "one group alone does not raise a call.")
        return (f"{name} since{on.replace(' on', '')}. {why}{back}" if since else f"{name}. {why}{back}")[:600]
    return (f"{name}{' since' + on.replace(' on', '') if since else ''}: every signal group with enough data is "
            f"within or better than their usual.{back}")[:600]


# ------------------------------------------------------------------ the payload
def insight(store: Store, settings: Settings, patient_id: str, row: dict[str, Any], *, generate: bool = True,
            now: datetime | None = None, gen: Any = None) -> PatientInsight:
    now = now or datetime.now(UTC)
    t0 = time.perf_counter()
    c = Consensus.model_validate(row["consensus"])
    crit = service.active_criteria(store)
    events = store.events_for_home(patient_id)
    data = service.patient_data(store, patient_id, crit)
    end = week.week_end(events, now.astimezone(TZ).date())
    refs = clinician_chat.evidence(store, settings, patient_id, row, now)
    steps = [AgentStep(step="retrieve", label="Read the record", actor="code", status="ok", latency_ms=_ms(t0),
                       items=len(events), detail=f"{len(events)} observation{'s' if len(events) != 1 else ''} read; {len(refs)} citable records built "
                                                 "from the consensus, measures, routines and week patterns."),
             AgentStep(step="consensus", label="Deterministic consensus", actor="code", status="ok",
                       items=sum(v.verdict != "insufficient" for v in c.sources),
                       detail=f"Rule {c.rule_version}: {sum(v.verdict != 'insufficient' for v in c.sources)} of "
                              f"{len(c.sources)} signal groups had enough data to vote. No model takes part.")]
    t1 = time.perf_counter()
    comp, drifts = comparison(crit, data, c, end)
    shared = week.sharing(store, patient_id).share_with_care_team
    episodes = store.episodes(patient_id, (now - timedelta(days=7 * (int(week.cfg("usual_weeks", 3)) + 2))).isoformat()) \
        if shared else []
    r_list = week.routines(week.occurrences(events, episodes if shared else None), end, "care_team",
                           collection_start=min((local_date(e["ts"]) for e in events), default=None))
    cov = coverage(events, c, data, drifts, end)
    early = cov.early_baseline or not cov.baseline_ready or \
        cov.span_days < int(getattr(crit.state, "min_history_days_for_stable", 0) or 0)
    helps = help_effects(data, early)
    routine = learned_routine(r_list, helps, cov.day_of_record, early)
    steps.append(AgentStep(step="compare", label="Compare weeks and usual", actor="code", status="ok",
                           latency_ms=_ms(t1), items=sum(len(g.metrics) for g in comp.groups),
                           detail="Medians of recorded days: this week, the week before and the personal usual."))
    t_course = time.perf_counter()
    actions_raw = store.actions(patient_id)
    overview, talk_rows, talk_record, talk_tone = account.reflections(store, patient_id, now, shared)
    arc, found = course_mod.build(crit, data, c, actions_raw, end, human_value, cov.day_of_record, early,
                                  account.low_spell(talk_rows) if talk_rows else None)
    steps.append(AgentStep(
        step="course", label="Work out the course of change", actor="code", status="ok", latency_ms=_ms(t_course),
        items=len(arc.events),
        detail=f"Phase {arc.phase}: {len(found)} measure{'s' if len(found) != 1 else ''} moved away from usual; "
               "first day away, furthest day and return to range per measure, with care actions and PHQ-9 in order."))
    extra = [(r, "unknown") for r in account.generic_records(events, crit, data, end, OBS_LABEL)]
    if talk_record:
        extra.append((talk_record, talk_tone))
    min_stable = int(getattr(crit.state, "min_history_days_for_stable", 0) or 0)
    replayed = []
    if data.first_day and data.first_day <= service.today_local():
        # The same replay the consensus uses (hysteresis, acknowledgements, never stable while young).
        replayed = consensus_rule.replay(data, crit, service.today_local(), now)
    status = status_line(c, replayed, actions_raw, arc, crit, cov.day_of_record, min_stable)
    names = {name: mc.metric.label for name, mc in found.items()}
    back_now = {name for name, mc in found.items() if mc.back}
    away_now = set(found) - back_now
    extra.append((RecordCitation(id="status:line", label="Why the state shows", detail=status, observed_at=end),
                  "unknown"))
    if found:
        listed = lambda keys: ", ".join(sorted(course_mod.short(names[k]).lower() for k in keys)) or "none"  # noqa: E731
        extra.append((RecordCitation(id="course:back", label="Back within usual", observed_at=end,
                                     detail=f"Back within their usual on the latest scored days: {listed(back_now)}."),
                      "better" if back_now else "unknown"))
        extra.append((RecordCitation(id="course:still_away", label="Still away from usual", observed_at=end,
                                     detail=f"Still away from their usual: {listed(away_now)}."),
                      "worse" if away_now else "unknown"))
    all_refs, tone = review_evidence(refs, c, comp, drifts, r_list, helps, end, arc, extra)
    template = template_findings(all_refs, tone, c, comp, routine, cov, arc)
    result, review_steps = review(store, settings, patient_id, c, all_refs, tone, template, now, generate=generate,
                                  gen=gen, sustained=sustained_ids(all_refs, tone, drifts),
                                  day_n=cov.day_of_record, early=early, needs_course=bool(found),
                                  truth=(back_now, away_now, names))
    steps += review_steps
    t2 = time.perf_counter()
    topics = dict(Counter(m["category"] for m in store.memories(patient_id))) if shared else {}
    g = graph(patient_id, c, comp, cov, r_list, helps, events, episodes, shared, now, found, actions_raw, topics, end)
    extra_nodes, extra_edges = [], []
    for record, _direction in extra:
        if record.id.startswith("obs:") and f"group:{record.source}" in {n.id for n in g.nodes}:
            extra_nodes.append(InsightNode(id=record.id, kind="measure", label=record.label, detail=record.detail[:240],
                                           evidence=1))
            extra_edges.append(InsightEdge(src=f"group:{record.source}", dst=record.id, rel="measures",
                                           label="recorded, not scored", weight=0.3, evidence=1))
    for theme in (overview.themes if overview else []):
        tid = f"talk:{theme.label}"
        extra_nodes.append(InsightNode(id=tid, kind="shared_topic", layer="learned", label=f"Talked about: {theme.label}",
                                       detail="Came up in their reflections with Kaiku. A theme only; the words stay "
                                              "private.", evidence=int(theme.value)))
        extra_edges.append(InsightEdge(src="person", dst=tid, rel="talked_about", layer="learned",
                                       label=f"in {int(theme.value)} reflection{'s' if theme.value != 1 else ''}",
                                       weight=round(min(1.0, theme.value / 5), 3), evidence=int(theme.value)))
    g = g.model_copy(update={"nodes": [*g.nodes, *extra_nodes], "edges": [*g.edges, *extra_edges]})
    steps.append(AgentStep(step="graph", label="Organise the permitted graph", actor="code", status="ok",
                           latency_ms=_ms(t2), items=len(g.nodes),
                           detail=f"{len(g.nodes)} nodes and {len(g.edges)} links from "
                                  + " and ".join(b.replace("_", " ") for b in g.basis)
                                  + f"; {sum(e.layer == 'learned' for e in g.edges)} links are learned from this "
                                    "record (order in time, co-change, routines, responses), the rest is structure."))
    cited = {i for f in result.findings for i in f.cites} | set(result.overview_cites)
    history = []
    if replayed:
        for day in replayed:
            history.append(StateDay(date=day.day, state=day.state, agreement=day.agreement,  # type: ignore[arg-type]
                                    early=bool(min_stable) and (day.day - data.first_day).days + 1 < min_stable))
    # One truth about provenance: the envelopes' sim flag, on every record a practitioner can open.
    all_refs = [r.model_copy(update={"simulated": bool(data.sim)}) for r in all_refs]
    if found:
        moved = {name: mc for name, mc in found.items()}
        since = (f"{arc.back} of {arc.moved} measures that moved away are back within their usual"
                 + (f" since the low on {course_mod.human_date(arc.low_date)}." if arc.low_date else "."))
        comp = comp.model_copy(update={
            "since_low": since, "back_in_range": [n for n, mc in moved.items() if mc.back],
            "still_away": [n for n, mc in moved.items() if not mc.back],
            "summary": (since + " Week against week the medians still include the low days: " + comp.summary[0].lower()
                        + comp.summary[1:])[:400]})
    actions = [CareAction(ts=a["ts"], action=a["action"], note=a.get("note"), by=a.get("by")) for a in actions_raw]
    steps.append(AgentStep(step="render", label="Render verified facts", actor="code", status="ok",
                           items=sum(len(f.facts) for f in result.findings),
                           detail="Every number, date, unit and direction is printed by code from the cited records."))
    return PatientInsight(
        patient_id=patient_id, display_name=service.display_name(patient_id, cov.first_day), state=c.state,
        agreement=c.agreement, rule_version=c.rule_version,
        status_line=status, review=result, evidence=[r for r in all_refs if r.id in cited], trace=steps,
        comparison=comp, routine=routine, graph=g, coverage=cov, day_of_record=cov.day_of_record,
        min_history_days_for_stable=min_stable, early_record=early, course=arc,
        days=account.days(events, found, actions_raw, talk_rows, end, human_value, r_list), reflections=overview,
        state_history=history,
        actions=actions,
        computed_at=now)
