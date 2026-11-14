"""The course of change, by code: what moved away from the person's own usual first, what followed, what has come
back within it and what has not, with care actions and PHQ-9 on the same timeline.

Per enabled metric, each recorded day is compared with that day's baseline (the provisional early baseline on a young
record) using the metric's own `z_threshold` from `config/criteria.toml`:
- onset         the first day away from usual that is followed by another away day within the next two scored days
                (one odd day is not a spell);
- lowest        the day furthest from usual since the onset;
- back_in_range the last two scored days are both within usual (dated from the first day back);
- still_away    otherwise, dated on the latest scored day.
Order in time is all this says. It never claims that one thing caused another, and the phase never says more than the
deterministic consensus supports: a young record is "settling" or "recovering", never "steady" or "recovered".
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from kaiku_contracts.api import Consensus, Course, CourseEvent, InsightEdge, InsightNode, Routine
from kaiku_contracts.config import get

from . import week
from .analytics.baseline import Baseline
from .analytics.drift import baseline_of, worse_z
from .analytics.metrics import parse_ts
from .settings import TZ

ACTION_TEXT = {"acknowledge": "Care team follow-up", "send_message": "Care team message",
               "flag_booster": "Care team flagged a booster review", "flag_icbt_referral": "Care team flagged a referral"}
CLOCK_UNITS = ("min after midnight", "min from midnight")


@dataclass(frozen=True)
class Point:
    day: date
    value: float
    base: Baseline
    z: float  # worse-signed: positive = away from usual in the unfavourable direction


@dataclass(frozen=True)
class MetricCourse:
    metric: Any  # criteria MetricSpec
    onset: Point
    lowest: Point
    last: Point
    last_away: Point  # the most recent day that was away from usual
    back: Point | None  # first day back within usual, when the latest two scored days are in range
    away_days: frozenset[date]

    @property
    def early(self) -> bool:
        return self.onset.base.early or self.last.base.early


def short(label: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", label).strip()


def human_date(day: date) -> str:
    return f"{day.day} {day:%b}"


def _join(names: list[str], limit: int = 4) -> str:
    names = list(dict.fromkeys(names))
    more = len(names) - limit
    names = names[:limit] + ([f"{more} more"] if more > 0 else [])
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _side(p: Point, unit: str) -> str:
    if unit in CLOCK_UNITS:
        return "later than" if p.value > p.base.median else "earlier than"
    return "above" if p.value > p.base.median else "below"


def metric_course(m: Any, series: dict[date, float], crit: Any, start: date, end: date, shown: Any = None
                  ) -> MetricCourse | None:
    """`shown(value, unit)`: how a value is printed. A day that prints the same as the usual is never "away"."""
    thr = float(crit.param(m, "z_threshold"))
    points = []
    for day in sorted(d for d in series if start <= d <= end):
        base = baseline_of(m, series, day, crit)
        if base is not None:
            z = worse_z(series[day], base, m.worse_when)
            if shown and shown(series[day], m.unit) == shown(base.median, m.unit):
                z = min(z, 0.0)
            points.append(Point(day, series[day], base, z))
    first = next((i for i, p in enumerate(points) if p.z >= thr and any(q.z >= thr for q in points[i + 1:i + 3])), None)
    if first is None:
        return None
    spell = points[first:]
    last_away = max(i for i, p in enumerate(spell) if p.z >= thr)
    tail = spell[last_away + 1:]
    return MetricCourse(metric=m, onset=spell[0], lowest=max(spell, key=lambda p: p.z), last=spell[-1],
                        last_away=spell[last_away],
                        back=tail[0] if len(tail) >= 2 else None,
                        away_days=frozenset(p.day for p in spell if p.z >= thr))


def build(crit: Any, data: Any, c: Consensus, actions: list[dict[str, Any]], end: date, human_value: Any,
          day_of_record: int, early: bool, reflections: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None
          ) -> tuple[Course, dict[str, MetricCourse]]:
    """`reflections`: (those that sounded low, the rated ones after the last low one), only when shared."""
    start = end - timedelta(days=int(get("insight", "course_days", 28)) - 1)
    found: dict[str, MetricCourse] = {}
    for m in crit.metrics:
        series = data.series.get(m.name)
        if m.enabled and series:
            mc = metric_course(m, series, crit, start, end, human_value)
            if mc:
                found[m.name] = mc
    events: list[tuple[date, int, CourseEvent]] = []

    def add(day: date, order: int, kind: str, label: str, text: str, m: Any = None) -> None:
        events.append((day, order, CourseEvent(date=day, kind=kind, group=m.source if m else None,  # type: ignore[arg-type]
                                               metric_id=m.name if m else None, label=label[:120], text=text[:300])))

    deepest = {mc.metric.name for mc in sorted(found.values(), key=lambda mc: -mc.lowest.z)[:5]}
    for mc in found.values():
        m, name = mc.metric, short(mc.metric.label)

        def val(p: Point, m: Any = m) -> str:
            return human_value(p.value, m.unit)

        usual = human_value(mc.onset.base.median, m.unit)
        add(mc.onset.day, 0, "onset", name, f"{name} first {_side(mc.onset, m.unit)} their usual on "
            f"{human_date(mc.onset.day)}: {val(mc.onset)} (usual {usual}).", m)
        if mc.lowest.day != mc.onset.day and mc.metric.name in deepest:
            add(mc.lowest.day, 1, "lowest", name, f"{name} furthest from their usual on {human_date(mc.lowest.day)}: "
                f"{val(mc.lowest)}.", m)
        if mc.back:
            add(mc.back.day, 3, "back_in_range", name, f"{name} back within their usual from "
                f"{human_date(mc.back.day)}; {val(mc.last)} on {human_date(mc.last.day)}.", m)
        else:
            # Always quote a day that WAS away. One in-range day since is said as such, never as "still below".
            p = mc.last_away
            text = (f"{name} {'still' if p.day == mc.last.day else 'last'} {_side(p, m.unit)} their usual on "
                    f"{human_date(p.day)}: {val(p)} (usual {human_value(p.base.median, m.unit)})")
            if p.day != mc.last.day:
                text += f"; within usual on {human_date(mc.last.day)}, one day so far"
            add(p.day, 4, "still_away", name, text + ".", m)
    care_days = []
    for a in actions:
        day = parse_ts(a["ts"]).astimezone(TZ).date()
        if start <= day <= end + timedelta(days=1):
            care_days.append(day)
            title = ACTION_TEXT.get(a["action"], "Care team action")
            add(day, 2, "care_action", title, f"{title} on {human_date(day)}" + (f" by {a['by']}." if a.get("by") else "."))
    for p in data.phq9:
        if start <= p.day <= end:
            add(p.day, 2, "phq9", "PHQ-9", f"PHQ-9 total {p.total} of 27 on {human_date(p.day)}.")
    low_talks, lighter = reflections or ([], [])
    low_talks = [r for r in low_talks if start <= r["day"] <= end]
    if low_talks:
        r = low_talks[0]
        add(r["day"], 2, "reflection_low", "Reflections with Kaiku",
            f"Reflections with Kaiku first sounded low on the {r['part']} of {human_date(r['day'])}"
            + (f"; {' and '.join(r['themes'][:2])} came up." if r["themes"] else "."))
        if lighter:
            r = lighter[0]
            add(r["day"], 3, "reflection_lighter", "Reflections with Kaiku",
                f"Reflections with Kaiku sounded lighter from the {r['part']} of {human_date(r['day'])}"
                + (f"; {' and '.join(r['themes'][:2])} came up." if r["themes"] else "."))
    events.sort(key=lambda e: (e[0], e[1]))

    def names(items: list[MetricCourse]) -> str:
        """The most marked changes by name (how far from usual at the furthest day), then how many more."""
        ranked = sorted(items, key=lambda mc: -mc.lowest.z * max(mc.metric.weight, 0.25))
        return _join([naming[mc.metric.name] for mc in ranked], 3)

    labels = [short(mc.metric.label).lower() for mc in found.values()]
    naming = {mc.metric.name: (short(mc.metric.label).lower() if labels.count(short(mc.metric.label).lower()) == 1
                               else mc.metric.label.lower()) for mc in found.values()}
    onsets = sorted(found.values(), key=lambda mc: mc.onset.day)
    back = [mc for mc in onsets if mc.back]
    still = [mc for mc in onsets if not mc.back]
    rule_worse = any(v.verdict == "worse" for v in c.sources)
    if not onsets:
        phase = "settling" if early else "steady"
        summary = (f"Day {day_of_record} of the record: the personal usual is still forming, and no measure has moved "
                   "away from it for more than a day so far." if early else
                   f"No measure has stayed away from their usual in the last {(end - start).days + 1} days.")
    else:
        first_day = onsets[0].onset.day
        first = [mc for mc in onsets if mc.onset.day == first_day]
        near = [mc for mc in onsets if first_day < mc.onset.day <= first_day + timedelta(days=3)]
        parts = [f"First to move away from their usual: {names(first)} on {human_date(first_day)}"]
        if near:
            gap = (max(mc.onset.day for mc in near) - first_day).days
            parts[0] += f"; {names(near)} followed within {gap} day{'s' if gap != 1 else ''}"
        parts[0] += "."
        after_care = sorted(d for d in care_days if d >= first_day)
        if after_care:
            parts.append(f"Care team follow-up on {human_date(after_care[0])}.")
        lead = "Since then " if after_care else f"By {human_date(end)} "
        if back and still:
            parts.append(f"{lead}{names(back)} {'are' if len(back) > 1 else 'is'} back within their usual; "
                         f"{names(still)} {'are' if len(still) > 1 else 'is'} still away from it.")
        elif back:
            parts.append(f"{lead}{names(back)} {'are' if len(back) > 1 else 'is'} back within their usual.")
        else:
            parts.append(f"{lead}{names(still)} {'are' if len(still) > 1 else 'is'} still away from their usual.")
        if back and rule_worse:
            parts.append("The consensus still reads a change from usual, because it counts the last several days, "
                         "not only the latest.")
        if low_talks:
            parts.append(f"Their reflections with Kaiku sounded low from {human_date(low_talks[0]['day'])}"
                         + (f" and lighter from {human_date(lighter[0]['day'])}." if lighter else "."))
        if early:
            parts.append(f"Day {day_of_record} of the record: this rests on an early baseline, so read it with lower "
                         "confidence.")
        summary = " ".join(parts)
        if not back:
            phase = "dip"
        elif still or rule_worse or early or c.state != "stable":
            phase = "recovering"  # the consensus has not returned to stable (or cannot yet): not "recovered"
        else:
            phase = "recovered"
    away_on = Counter(day for mc in found.values() for day in mc.away_days)
    low_date = max(away_on, key=lambda d: (away_on[d], d)) if away_on else None
    return Course(phase=phase, low_date=low_date, moved=len(found), back=len(back) if onsets else 0,  # type: ignore[arg-type]
                  summary=summary[:700], events=[e for _d, _o, e in events]), found


# ------------------------------------------------------------------ what was learned, as graph links
def learned(found: dict[str, MetricCourse], actions: list[dict[str, Any]], r_list: list[Routine],
            occ: dict[str, list[datetime]], end: date, nodes: dict[str, InsightNode]) -> list[InsightEdge]:
    """Links found in this person's record. Order in time and co-occurrence only; evidence = days behind each."""
    edges: list[InsightEdge] = []
    onsets = sorted(found.values(), key=lambda mc: (mc.onset.day, mc.metric.name))
    if not onsets:
        return edges

    def node(mc: MetricCourse) -> str:
        return f"measure:{mc.metric.name}"

    first_day = onsets[0].onset.day
    leaders = [mc for mc in onsets if mc.onset.day == first_day][:2]
    for mc in leaders:
        if node(mc) in nodes:
            edges.append(InsightEdge(src="person", dst=node(mc), rel="moved_first", layer="learned",
                                     label=f"first to move, {human_date(first_day)}", weight=1.0,
                                     evidence=len(mc.away_days)))
    lead = leaders[0]
    for mc in [m for m in onsets if m.onset.day > first_day][:6]:
        gap = (mc.onset.day - first_day).days
        if node(mc) in nodes and node(lead) in nodes:
            edges.append(InsightEdge(src=node(lead), dst=node(mc), rel="followed", layer="learned",
                                     label=f"moved {gap} day{'s' if gap != 1 else ''} later (order, not cause)",
                                     weight=round(max(0.2, 1 - gap / 7), 3), evidence=len(mc.away_days)))
    pairs = []
    for i, a in enumerate(onsets):
        for b in onsets[i + 1:]:
            shared = len(a.away_days & b.away_days)
            if a.metric.source != b.metric.source and shared >= 2:
                pairs.append((shared, a, b))
    for shared, a, b in sorted(pairs, key=lambda p: -p[0])[:6]:
        if node(a) in nodes and node(b) in nodes:
            span = len(a.away_days | b.away_days)
            edges.append(InsightEdge(src=node(a), dst=node(b), rel="moved_together", layer="learned",
                                     label=f"away from usual on the same {shared} days", weight=round(shared / span, 3),
                                     evidence=shared))
    spell_days = sorted(set().union(*(mc.away_days for mc in onsets)))
    spell = [spell_days[0] + timedelta(days=i) for i in range((min(end, spell_days[-1]) - spell_days[0]).days + 1)]
    for r in r_list:
        rid = f"routine:{r.activity}"
        if rid not in nodes or r.activity == "sleep" or len(spell) < 3:
            continue
        done = len({week._day_of(r.activity, t) for t in occ.get(r.activity, [])} & set(spell))
        expected = (1.0 if r.cadence == "weekly" else r.usual_per_week) / 7 * len(spell)
        if expected < 1:
            continue
        ratio = done / expected
        rel = "kept_through" if ratio >= 0.8 else "slipped_during" if ratio < 0.5 else None
        if rel:
            edges.append(InsightEdge(src="person", dst=rid, rel=rel, layer="learned",
                                     label=f"{done} of {len(spell)} days while measures were away from usual",
                                     weight=round(min(1.0, ratio), 3), evidence=done))
    for i, a in enumerate(actions):
        day = parse_ts(a["ts"]).astimezone(TZ).date()
        if day < first_day:
            continue
        cid = f"care:{i}"
        title = ACTION_TEXT.get(a["action"], "Care team action")
        nodes[cid] = InsightNode(id=cid, kind="care_action", layer="learned", label=f"{title} · {human_date(day)}",
                                 detail="Logged by the care team. What came back afterwards is order in time, not "
                                        "proof of effect.", evidence=1)
        edges.append(InsightEdge(src="person", dst=cid, rel="has_signal", layer="learned", label="care action",
                                 weight=1.0, evidence=1))
        returned = sorted((mc for mc in onsets if mc.back and mc.back.day >= day and node(mc) in nodes),
                          key=lambda mc: (mc.back.day, -mc.lowest.z))[:6]  # type: ignore[union-attr]
        for mc in returned:
            if mc.back:
                gap = (mc.back.day - day).days
                edges.append(InsightEdge(src=cid, dst=node(mc), rel="after", layer="learned",
                                         label=f"back within usual {gap} day{'s' if gap != 1 else ''} after",
                                         weight=round(max(0.2, 1 - gap / 10), 3), evidence=1))
    return edges
