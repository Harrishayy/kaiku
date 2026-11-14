"""The knowledge graph as a map: what every node is about, what it has on each day, and what changed that day.

`enrich()` takes the permitted graph built by `insight.graph()` (signal groups, measures, activities, routines, care
actions, shared counts) and adds, all by code:

- domains     the neighbourhoods declared in config/kaiku.toml [graph] (id, label, place around the person) and a
              `domain` on every node: a measure by its name or by the observation type that feeds it
              (config/criteria.toml `obs`), an activity or routine by its key, a reflection theme and a notebook
              category by name. Nothing is guessed: an undeclared node has no domain.
- produces    activity -> the measures a session of it yields ([graph.produces] + criteria `obs`), only for days
              both were recorded.
- about       reflection theme -> the node it sits beside ([graph.about]); declared, never learned.
- node days   per node, per day: a measure's reading against that day's own usual (`course.readings` /
              `course.day_tone`: the same baseline and threshold as the trends band, the course and the daily
              account), an activity done with its time, a routine kept or missed (the daily account's own rule), a
              theme that came up (a count, never words), a care action logged.
- graph days  per day: how many measures were away from usual and what changed (moved away, came back, better,
              routine missed or kept, first record, care action), each pointing at its node, with its place in the
              order of the change when the course has one.

Order in time is never cause. Nothing here reads or changes the consensus.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from kaiku_contracts.api import (
    InsightChange,
    InsightDomain,
    InsightEdge,
    InsightGraph,
    InsightGraphDay,
    InsightNode,
    InsightNodeDay,
    Routine,
)
from kaiku_contracts.config import get

from . import account, week
from . import course as course_mod
from .analytics.metrics import local_date, parse_ts
from .settings import TZ

PLACES = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
CHANGE_ORDER = ("care", "moved_away", "came_back", "better", "missed", "first", "kept")
ONE_DAY = "this day only"  # outside the usual on one day: the trends chart marks it, the course does not count it


@dataclass(frozen=True)
class Atlas:
    """config/kaiku.toml [graph] as lookups: which neighbourhood each kind of thing belongs to."""

    domains: list[InsightDomain]
    activity: dict[str, str]
    measure: dict[str, str]
    obs: dict[str, str]
    theme: dict[str, str]
    topic: dict[str, str]
    kind: dict[str, str]
    produces: dict[str, list[str]]
    about: dict[str, list[str]]


def atlas() -> Atlas:
    """Read fail-soft: a neighbourhood without an id, a label or a free place is skipped, never an error."""
    domains: list[InsightDomain] = []
    maps: dict[str, dict[str, str]] = {k: {} for k in ("activities", "measures", "obs", "themes", "topics", "kinds")}
    taken: set[str] = set()
    for row in get("graph", "domain", []) or []:
        if not isinstance(row, dict):
            continue
        did, label, place = row.get("id"), row.get("label"), row.get("place")
        if not did or not label or place not in PLACES or place in taken or any(d.id == did for d in domains):
            continue
        taken.add(place)
        domains.append(InsightDomain(id=str(did), label=str(label)[:60], short=str(row.get("short") or label)[:24],
                                     place=place))
        for key, lookup in maps.items():
            for name in row.get(key) or []:
                lookup.setdefault(str(name), str(did))

    def lists(key: str) -> dict[str, list[str]]:
        table = get("graph", key, {}) or {}
        return {str(k): [str(x) for x in v] for k, v in table.items() if isinstance(v, list)} if isinstance(table, dict) else {}

    return Atlas(domains=domains, activity=maps["activities"], measure=maps["measures"], obs=maps["obs"],
                 theme=maps["themes"], topic=maps["topics"], kind=maps["kinds"], produces=lists("produces"),
                 about=lists("about"))


def domain_of(node: InsightNode, at: Atlas, metric_obs: dict[str, str]) -> str:
    kind, _, key = node.id.partition(":")
    if kind == "measure":
        return at.measure.get(key) or at.obs.get(metric_obs.get(key, ""), "")
    if kind == "obs":
        return at.obs.get(f"obs.{key}", "")
    if kind in ("activity", "routine"):
        return at.activity.get(key, "")
    if kind == "talk":
        return at.theme.get(key, "")
    if kind == "topic":
        return at.topic.get(key, "")
    return at.kind.get(node.kind, "")


def _hhmm(ts: datetime) -> str:
    return f"{ts.hour:02d}:{ts.minute:02d}"


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"


def theme_nodes(rows: list[dict[str, Any]]) -> tuple[list[InsightNode], list[InsightEdge]]:
    """Reflection themes as counts over the rows given (the graph's window). A theme only; never their words."""
    came: dict[str, list[date]] = defaultdict(list)
    for r in rows:
        for theme in r.get("themes") or []:
            came[theme].append(r["day"])
    nodes, edges = [], []
    for theme, days in sorted(came.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        tid = f"talk:{theme}"
        nodes.append(InsightNode(id=tid, kind="shared_topic", layer="learned", label=f"Talked about: {theme}",
                                 detail=f"Came up in {_n(len(days), 'reflection')} with Kaiku. A theme only; the "
                                        "words stay private.", evidence=len(days)))
        edges.append(InsightEdge(src="person", dst=tid, rel="talked_about", layer="learned",
                                 label=f"in {_n(len(days), 'reflection')}", weight=round(min(1.0, len(days) / 5), 3),
                                 evidence=len(days), on=sorted(set(days))))
    return nodes, edges


def measure_days(m: Any, series: dict[date, float], crit: Any, start: date, end: date, shown: Any
                 ) -> list[InsightNodeDay]:
    """One entry per recorded day: the reading against that day's own usual, in the measure's own terms."""
    out = []
    for day, value, p in course_mod.readings(m, series, crit, start, end, shown):
        tone = course_mod.day_tone(m, p, crit, shown)
        printed = shown(round(value, 3), m.unit)  # three decimals, as the trends chart prints its points and band
        usual = shown(round(p.base.median, 3), m.unit) if p else ""
        if p is None:
            text = f"{printed}; no personal usual yet"
        elif tone == "similar":
            text = f"{printed}, within their usual (around {usual})"
        else:
            text = f"{printed}, {course_mod._side(p, m.unit)} their usual {usual}"
        out.append(InsightNodeDay(date=day, tone=tone, value=printed[:32], text=text[:200]))  # type: ignore[arg-type]
    return out


def done_days(occ: dict[str, list[datetime]]) -> dict[str, dict[date, list[datetime]]]:
    """activity -> day -> the times it happened, earliest first (a sleep onset belongs to the evening before)."""
    out: dict[str, dict[date, list[datetime]]] = defaultdict(lambda: defaultdict(list))
    for key, stamps in occ.items():
        for ts in sorted(stamps):
            out[key][week._day_of(key, ts)].append(ts)
    return out


def routine_days(r: Routine, done: dict[date, list[datetime]], recorded: set[date], window: list[date]
                 ) -> list[InsightNodeDay]:
    """Kept on a day it was done; missed on a recorded day without it, for the daily routines the daily account
    names (`account.MISSING`). A night's sleep onset is shown with its time and not judged."""
    out = []
    for day in window:
        stamps = done.get(day)
        if stamps and r.activity == "sleep":
            out.append(InsightNodeDay(date=day, value=_hhmm(stamps[0]),
                                      text=f"asleep around {_hhmm(stamps[0])}; usually around {r.usual_time}"))
        elif stamps:
            out.append(InsightNodeDay(date=day, tone="similar", value=_hhmm(stamps[0]),
                                      text=f"done at {_hhmm(stamps[0])}; usually around {r.usual_time}"))
        elif r.cadence == "daily" and r.activity in account.MISSING and day in recorded:
            out.append(InsightNodeDay(date=day, tone="worse", value="missed",
                                      text=f"not recorded on this day; usually around {r.usual_time}"))
    return out


def enrich(g: InsightGraph, *, crit: Any, data: Any, events: list[dict[str, Any]], r_list: list[Routine],
           actions: list[dict[str, Any]], talk_rows: list[dict[str, Any]], end: date, shown: Any,
           found: dict[str, Any] | None = None, rows_cover_record: bool = False) -> InsightGraph:
    """`found`: the course's spells per metric (`course.build`), so a single day outside the usual is told apart
    from the start of a spell. `talk_rows`: reflection summaries inside the graph's window (empty unless the person
    shares). `rows_cover_record`: those rows reach back to the first day of the record, so a theme's first day is
    known."""
    at = atlas()
    recorded = {local_date(e["ts"]) for e in events}
    care_day = {f"care:{i}": parse_ts(a["ts"]).astimezone(TZ).date() for i, a in enumerate(actions)}
    care_by = {f"care:{i}": a.get("by") for i, a in enumerate(actions)}
    if not recorded:
        return g.model_copy(update={"domains": at.domains})
    record_start = min(recorded)
    last = max([end, *(d for d in care_day.values() if d <= end + timedelta(days=1))])
    start = max(record_start, last - timedelta(days=max(1, int(get("graph", "days", 28))) - 1))
    window = [start + timedelta(days=i) for i in range((last - start).days + 1)]
    in_window = set(window)
    metrics = {m.name: m for m in crit.metrics if m.enabled}
    metric_obs = {m.name: m.obs for m in crit.metrics}
    occ = week.occurrences(events, None)
    done = done_days(occ)
    by_type: dict[str, set[date]] = defaultdict(set)
    for e in events:
        by_type[e["type"]].add(local_date(e["ts"]))
    themes: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for r in talk_rows:
        for theme in r.get("themes") or []:
            themes[theme][r["day"]] += 1
    routine = {f"routine:{r.activity}": r for r in r_list}

    # ---- every node: its neighbourhood and its days
    first_seen: dict[str, date] = {}
    nodes: list[InsightNode] = []
    for node in g.nodes:
        kind, _, key = node.id.partition(":")
        days: list[InsightNodeDay] = []
        if kind == "measure" and key in metrics and data.series.get(key):
            days = measure_days(metrics[key], data.series[key], crit, start, last, shown)
            first_seen[node.id] = min(data.series[key])
        elif kind == "obs" and by_type.get(f"obs.{key}"):
            days = [InsightNodeDay(date=d, value="recorded", text="recorded")
                    for d in sorted(by_type[f"obs.{key}"] & in_window)]
            first_seen[node.id] = min(by_type[f"obs.{key}"])
        elif kind == "activity" and done.get(key):
            for d in sorted(set(done[key]) & in_window):
                stamps = done[key][d]
                text = f"recorded at {_hhmm(stamps[0])}" + (f", {len(stamps)} times that day" if len(stamps) > 1 else "")
                days.append(InsightNodeDay(date=d, value=_hhmm(stamps[0]), text=text))
            first_seen[node.id] = min(done[key])
        elif node.id in routine:
            days = routine_days(routine[node.id], done.get(key, {}), recorded, window)
        elif node.id in care_day and care_day[node.id] in in_window:
            who = f"logged by {care_by[node.id]}" if care_by.get(node.id) else "logged by the care team"
            days = [InsightNodeDay(date=care_day[node.id], value="logged", text=who[:200])]
        elif kind == "talk" and themes.get(key):
            days = [InsightNodeDay(date=d, value="came up", text=f"came up in {_n(n, 'reflection')} that day")
                    for d, n in sorted(themes[key].items()) if d in in_window]
            if rows_cover_record:
                first_seen[node.id] = min(themes[key])
        nodes.append(node.model_copy(update={"domain": domain_of(node, at, metric_obs), "days": days}))
    ids = {n.id: n for n in nodes}

    # ---- declared links: an activity and the measures a session of it yields; a theme and what it sits beside
    edges = list(g.edges)
    for key, targets in at.produces.items():
        src = f"activity:{key}" if f"activity:{key}" in ids else f"routine:{key}" if f"routine:{key}" in ids else None
        if not src or not done.get(key):
            continue
        # a night's onset is dated on the evening before; the watch summary it comes from on the morning after
        did = {d + timedelta(days=1) for d in done[key]} if key == "sleep" else set(done[key])
        for target in targets:
            if target.startswith("obs."):
                yields = [(f"measure:{m.name}", set(data.series.get(m.name) or {})) for m in metrics.values() if m.obs == target]
                yields.append((f"obs:{target[4:]}", by_type.get(target, set())))
            else:
                yields = [(f"measure:{target}", set(data.series.get(target) or {}))]
            for dst, have in yields:
                both = sorted(did & have)
                if dst in ids and both and dst != src:
                    edges.append(InsightEdge(src=src, dst=dst, rel="produces", label=f"recorded together on {_n(len(both), 'day')}",
                                             weight=round(min(1.0, len(both) / max(1, len(did))), 3), evidence=len(both),
                                             on=[d for d in both if d in in_window]))
    for theme, targets in at.about.items():
        tid = f"talk:{theme}"
        for dst in targets:
            if tid in ids and dst in ids:
                edges.append(InsightEdge(src=tid, dst=dst, rel="about", label="about the same part of life",
                                         weight=1.0, evidence=ids[tid].evidence, on=[d.date for d in ids[tid].days]))

    # ---- every day: how many measures were away, and what changed
    order_tag: dict[tuple[str, date], str] = {}
    first_change = min((e.on[0] for e in edges if e.rel == "moved_first" and e.on), default=None)
    for e in edges:
        if not e.on:
            continue
        if e.rel == "moved_first":
            order_tag[(e.dst, e.on[0])] = "first to move"
        elif e.rel == "followed" and first_change:
            order_tag[(e.dst, e.on[0])] = f"{_n((e.on[0] - first_change).days, 'day')} after the first change"
        elif e.rel == "after" and e.src in ids:
            what = ids[e.src].label.split(" · ")[0]
            what = what[0].lower() + what[1:]
            gap = (e.on[0] - care_day[e.src]).days if e.src in care_day else 0
            order_tag[(e.dst, e.on[0])] = f"the same day as the {what}" if gap <= 0 else f"{_n(gap, 'day')} after the {what}"
    changes: dict[date, list[InsightChange]] = defaultdict(list)
    away: dict[date, int] = defaultdict(int)

    def change(day: date, node: InsightNode, kind: str, text: str, tag: str = "") -> None:
        changes[day].append(InsightChange(node=node.id, kind=kind, text=text[:240],  # type: ignore[arg-type]
                                          tag=(order_tag.get((node.id, day)) or tag)[:80]))

    spells = {f"measure:{name}": mc.away_days for name, mc in (found or {}).items()}
    for node in nodes:
        kind = node.id.partition(":")[0]
        if kind == "measure":
            spell = spells.get(node.id, frozenset())
            before = None  # the tone on the previous day that could be read against a usual
            lasting = False  # that day was part of a spell the course counts, not a single day outside the usual
            for d in node.days:
                if d.tone == "unknown":
                    continue
                if d.tone == "worse":
                    away[d.date] += 1
                    if before != "worse":
                        change(d.date, node, "moved_away", d.text, "" if d.date in spell else ONE_DAY)
                    lasting = d.date in spell
                elif before == "worse" and lasting:
                    change(d.date, node, "came_back" if d.tone == "similar" else "better", d.text)
                elif d.tone == "better" and before == "similar":
                    change(d.date, node, "better", d.text)
                before = d.tone
        elif node.kind == "routine":
            for d in node.days:
                if d.tone in ("worse", "similar"):
                    change(d.date, node, "missed" if d.tone == "worse" else "kept", d.text)
        elif node.kind == "care_action":
            for d in node.days:
                change(d.date, node, "care", d.text)
        seen = first_seen.get(node.id)
        if seen and seen in in_window and seen != record_start:
            change(seen, node, "first", "first came up in a reflection" if kind == "talk" else "first recorded on this day")
    place = {n.id: i for i, n in enumerate(nodes)}
    days_out = []
    for day in window:
        todays = sorted(changes.get(day, []), key=lambda c: (CHANGE_ORDER.index(c.kind), place[c.node]))
        days_out.append(InsightGraphDay(date=day, recorded=day in recorded or day in care_day.values(),
                                        away=away.get(day, 0), changes=todays))
    return g.model_copy(update={"nodes": nodes, "edges": edges, "domains": at.domains, "days": days_out})
