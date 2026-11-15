"""GET /v1/me/history — the person's own numbers, as a health app shows them (D48).

Every measure the home has produced, from every device, by local day, with the latest sessions of each. The list
of measures, their groups and their plain titles are `config/kaiku.toml [history]`. A measure that is a
`config/criteria.toml` metric is computed with the analytics' own reading rules (`analytics.metrics.extract`, the
same quality gate, filters, day and aggregation), so a day here is the number the practitioner side has for that
day; its usual range is the baseline the rule engine uses today (`analytics.drift.baseline_of`: median, plus and
minus one spread). Readings that are stored but that no metric scores (drum taps, ritual steps, the watch's
exercise minutes) are read the same way.

Two differences from the practitioner side, both on purpose. A day with no reading is absent here, where the rule
engine counts some measures as zero on such a day (it still does when it works out the usual range). And today's
running total (steps, minutes) is shown as it stands, where the practitioner side waits for the day to end.
A measure whose only sessions in the window are practice rounds comes back with its sessions and no days.

A third difference, also on purpose (D53): which day a number of the Apple Health summary stands under. The summary
is dated the morning it was made. Its sleep is the night that ended that morning; its steps, distance, daylight,
exercise, resting and walking heart rate and heart rate variability are the day before's, midnight to midnight.
The rule engine and the practitioner's timeline keep every one of them on the summary's date. Here a measure with
`day_offset = -1` in `[history]` stands on the day it is of, so yesterday's walking is never shown as today's.
Its session row is stamped at the end of that day (a daily total has no other moment) and lists only the numbers
of that day; a sleep row keeps the summary's own time and lists the night's numbers. The usual range is still the
rule engine's.

The `camera` group (D52) is what the phone or Mac counted of her face during a game or a check-in while "Camera
during activities" was on: the same numbers the practitioner side has, each session listed with how much of it the
camera could use. A session too thin to count (the criteria's `at_least` minimums) is listed and left out of the
day's value, like a doubtful game.

What this module must never put in the response: the consensus state, a verdict, a z-score, a flag, a weight, a
direction ("better", "worse", "up is good"), anything from the practitioner's review, a safety flag, a
questionnaire answer. It reads no verdict and no consensus at all, and `tests/test_history.py` checks the wire.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from kaiku_contracts.api import (
    HISTORY_GROUPS,
    HistoryDay,
    HistoryGroup,
    HistoryMeasure,
    HistorySession,
    HistoryUsual,
    HistoryValue,
    PersonHistory,
)
from kaiku_contracts.config import load_config
from kaiku_contracts.criteria import Criteria

from . import service
from .analytics import data
from .analytics.drift import baseline_of
from .analytics.metrics import AGG, daily_metrics, extract, observation_day, parse_ts
from .settings import TZ
from .store.db import Store

PER_DAY = {"mean": "average", "median": "average", "sum": "total", "max": "highest", "min": "lowest",
           "last": "latest", "first": "first", "count": "count"}
ROBOT_SOURCES = ("head", "sensors", "hub", "friendlink")
DEVICE_OF_SOURCE = {**dict.fromkeys(ROBOT_SOURCES, "robot"), "glasses": "glasses", "laptop": "mac", "phone": "phone"}
CHANNEL_DEVICE = {"robot": "robot", "phone": "phone", "mac": "mac", "web": "web", "glasses_voice": "glasses"}
PRACTICE = "warmup"  # a filter the day's value uses and the session list does not: practice sessions are listed
FORMATS = ("clock", "percent", "duration")  # how a value is to be read (HistoryFormat); anything else is a number


@dataclass(frozen=True)
class Spec:
    """One measure as the analytics read it. Quacks like a criteria MetricSpec for `extract`, `crit.param` and
    `baseline_of`, so a stored-but-unscored reading goes through exactly the same code."""

    name: str
    obs: str
    field: str
    agg: str
    where: dict[str, Any] = field(default_factory=dict)
    at_least: dict[str, float] = field(default_factory=dict)  # payload minimums a reading needs to count
    scored: bool = False  # a criteria metric: its days must equal the practitioner side's
    quality_min: float | None = None
    baseline_days: int | None = None
    baseline_min_days: int | None = None
    min_mad: float | None = None
    day_offset: int = 0  # days from the observation's own day to the day this number is of (-1: the day before)


def cfg() -> dict[str, Any]:
    return load_config().get("history", {})


def specs(crit: Criteria) -> list[tuple[dict[str, Any], Spec]]:
    """The measures to show, in config order, each with how it is read."""
    by_name = {m.name: m for m in crit.metrics}
    out = []
    for row in cfg().get("measure", []):
        if row.get("group") not in HISTORY_GROUPS:
            continue
        m = by_name.get(row["key"])
        if "obs" in row:
            spec = Spec(row["key"], row["obs"], row["field"], row.get("agg", "mean"), dict(row.get("where", {})),
                        dict(row.get("at_least", {})), min_mad=row.get("min_mad"))
        elif m is not None:
            spec = Spec(m.name, m.obs, m.field, m.agg, dict(m.where), dict(m.at_least), True, m.quality_min,
                        m.baseline_days, m.baseline_min_days, m.min_mad)
        else:
            continue  # names a metric the criteria no longer have
        out.append((row, replace(spec, day_offset=int(row.get("day_offset", 0)))))
    return out


def device_of(event: dict[str, Any]) -> str:
    """Where a reading came from: the envelope's real source (head, sensors and hub are all the robot), or the
    payload's own word for it where one device relays for another (the watch through the phone, a dial channel)."""
    t, p = event["type"], event["payload"]
    if t == "obs.wearable_daily":
        return "watch" if p.get("device") in ("apple_watch", "other_watch") else "phone"
    if t in ("obs.play_session", "obs.face_signs") and p.get("device") in ("phone", "mac", "web", "robot"):
        return p["device"]
    if t == "obs.self_report" and p.get("channel") in CHANNEL_DEVICE:
        return CHANNEL_DEVICE[p["channel"]]
    return DEVICE_OF_SOURCE.get(event["source"], "phone")


def _session_values(event: dict[str, Any], t_local: datetime, offset: int = 0,
                    offsets: dict[str, int] | None = None) -> list[HistoryValue]:
    """The numbers of one session. `offsets` = payload field -> day offset of the measure that reads it: a row
    lists only the numbers that stand under its own day (`offset`), so a night's sleep and the day before's
    walking, which arrive in one Apple Health summary, are never shown under each other's day."""
    out: list[HistoryValue] = []
    for row in cfg().get("session", {}).get(event["type"], []):
        key, title, unit = row[0], row[1], row[2]
        if (offsets or {}).get(key, 0) != offset:
            continue
        v: Any = t_local.hour * 60 + t_local.minute if key == "@local_minutes" else event["payload"].get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        fmt = row[4] if len(row) > 4 and row[4] in FORMATS else "number"
        places = (int(row[3]) if len(row) > 3 else 0) + (2 if fmt == "percent" else 0)  # a share keeps its percent's decimals
        out.append(HistoryValue(key=key, title=title, value=round(float(v), places), unit=unit, format=fmt))
    return out[:int(cfg().get("session_values", 12))]


def _stamp(day: date, later: int) -> datetime:
    """When a session row of a measure with a day offset is said to be: the end of the day its number is of. The
    summary itself was made the next morning, and a day's total has no other moment. `later` = how many later
    summaries of the same day stand before this one: each earlier one is a second earlier, so they keep the order
    they arrived in and the day's latest stays the latest."""
    return (datetime.combine(day, time(23, 59, 59), tzinfo=TZ) - timedelta(seconds=later)).astimezone(UTC)


def _session_label(event: dict[str, Any]) -> str | None:
    row = cfg().get("session_label", {}).get(event["type"])
    return row[1].get(str(event["payload"].get(row[0]))) if row else None


def build(store: Store, home_id: str, days: int, now: datetime | None = None) -> PersonHistory:
    now = now or datetime.now(UTC)
    crit = service.active_criteria(store)
    last = now.astimezone(TZ).date()
    first = last - timedelta(days=days - 1)
    events = store.events_for_home(home_id)
    wanted = specs(crit)
    by_type: dict[str, list[Spec]] = defaultdict(list)
    # payload fields that stand under another day than their observation's own, per observation type (D53)
    offsets: dict[str, dict[str, int]] = defaultdict(dict)
    for _row, spec in wanted:
        by_type[spec.obs].append(spec)
        if spec.day_offset:
            offsets[spec.obs][spec.field] = spec.day_offset

    # one pass: every day's readings of every measure, and the sessions of the window each measure lists
    readings: dict[str, dict[date, list[tuple[datetime, float, bool]]]] = defaultdict(lambda: defaultdict(list))
    sessions: dict[str, list[tuple[datetime, dict[str, Any], date]]] = defaultdict(list)
    devices: dict[str, Counter[str]] = defaultdict(Counter)
    for e in events:
        for spec in by_type.get(e["type"], ()):
            t = parse_ts(e["ts"]).astimezone(TZ)
            # the day the number is of: the rule engine's day, moved for a measure that says so (the usual range
            # below still comes from the rule engine's own series, on its own days)
            day = observation_day(e, crit) + timedelta(days=spec.day_offset)
            shown = first <= day <= last
            listed = {k: v for k, v in spec.where.items() if k != PRACTICE}
            if shown and extract(replace(spec, where=listed, at_least={}), e["payload"], t) is not None:  # type: ignore[arg-type]
                sessions[spec.name].append((t, e, day))  # a practice round or a thin capture is a session too
                devices[spec.name][device_of(e)] += 1
            q = e.get("quality")
            if q is not None and q < crit.param(spec, "quality_min"):  # type: ignore[arg-type]
                continue
            v = extract(spec, e["payload"], t)  # type: ignore[arg-type]
            if v is not None:
                readings[spec.name][day].append((t, v, bool(e.get("sim"))))

    # the usual range comes from the series the rule engine itself scores (days without data filled as it does)
    span_days = data.build(home_id, events, crit).source_days
    spans = {s: (min(v), max(v)) for s, v in span_days.items() if v}
    scored = daily_metrics(events, crit, spans, include_disabled=True)
    limit, scale = int(cfg().get("sessions_per_measure", 30)), float(cfg().get("usual_scale", 1.0))
    titles = cfg().get("groups", {})
    groups: dict[str, list[HistoryMeasure]] = defaultdict(list)
    for row, spec in wanted:
        all_days = {d: float(AGG[spec.agg]([v for _t, v, _s in sorted(vals)]))
                    for d, vals in readings.get(spec.name, {}).items()}
        out_days = [HistoryDay(date=d, value=all_days[d], sessions=len(vals), sim=any(s for _t, _v, s in vals))
                    for d, vals in sorted(readings.get(spec.name, {}).items()) if first <= d <= last]
        latest = sorted(sessions.get(spec.name, []), key=lambda x: x[0], reverse=True)[:limit]
        if not out_days and not latest:
            continue  # nothing recorded in the window: the measure is left out
        base = baseline_of(spec, (scored.get(spec.name) if spec.scored else all_days) or {}, last, crit)  # type: ignore[arg-type]
        rows: list[HistorySession] = []
        seen: Counter[date] = Counter()  # summaries of one day already listed (newest first)
        for t, e, day in latest:  # newest first
            ts = parse_ts(e["ts"])
            if spec.day_offset:
                ts, seen[day] = _stamp(day, seen[day]), seen[day] + 1
            rows.append(HistorySession(id=str(e["id"]), ts=ts, device=device_of(e),  # type: ignore[arg-type]
                                       sim=bool(e.get("sim")),
                                       warmup=e["payload"].get(PRACTICE) if e["type"] == "obs.play_session" else None,
                                       label=_session_label(e),
                                       values=_session_values(e, t, spec.day_offset, offsets.get(e["type"]))))
        groups[row["group"]].append(HistoryMeasure(
            key=spec.name, title=row["title"], unit=row.get("unit", ""), format=row.get("format", "number"),
            decimals=int(row.get("decimals", 0)), per_day=PER_DAY[spec.agg],  # type: ignore[arg-type]
            devices=[d for d, _n in devices[spec.name].most_common()],  # type: ignore[misc]
            days=out_days,
            # every measure here is a count, a time or a 0-and-up reading: the range never dips below nothing
            usual=HistoryUsual(low=round(max(0.0, base.median - scale * base.scale), 2),
                               high=round(base.median + scale * base.scale, 2)) if base is not None else None,
            sessions=rows,
            sim=any(d.sim for d in out_days) or any(bool(e.get("sim")) for _t, e, _d in latest)))
    out_groups = [HistoryGroup(key=g, title=str(titles.get(g, g)), measures=groups[g])  # type: ignore[arg-type]
                  for g in HISTORY_GROUPS if groups.get(g)]
    return PersonHistory(home_id=home_id, days=days, first_day=first, last_day=last, timezone=str(TZ), groups=out_groups,
                         sim=any(m.sim for g in out_groups for m in g.measures), generated_at=now)
