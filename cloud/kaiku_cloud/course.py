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

A metric the criteria declare `role = "shown"` (camera face signs, D52) gets its own events, each ending "Shown only:
no vote in the consensus.", and one closing sentence in the summary. It never leads: what moved first, the phase, the
low day and the counts of what moved and what is back are the scored measures', because they explain the state.
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


SHOWN_NOTE = " Shown only: no vote in the consensus."


def shown_only(m: Any) -> bool:
    """A metric the criteria declare `role = "shown"`: compared, charted and citable, never part of a verdict."""
    return getattr(m, "role", "scored") == "shown"


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


def readings(m: Any, series: dict[date, float], crit: Any, start: date, end: date, shown: Any = None
             ) -> list[tuple[date, float, Point | None]]:
    """Every recorded day in the window: (day, value, the day against that day's own usual, or None while there is
    no baseline). The one per-day reading behind the course, the daily account and the graph's days; it uses the
    baseline and threshold the trends band is drawn from. `shown(value, unit)`: how a value is printed. A day that
    prints the same as the usual is never "away"."""
    out: list[tuple[date, float, Point | None]] = []
    for day in sorted(d for d in series if start <= d <= end):
        base = baseline_of(m, series, day, crit)
        point = None
        if base is not None:
            z = worse_z(series[day], base, m.worse_when)
            if shown and shown(series[day], m.unit) == shown(base.median, m.unit):
                z = min(z, 0.0)
            point = Point(day, series[day], base, z)
        out.append((day, series[day], point))
    return out


def day_tone(m: Any, p: Point | None, crit: Any, shown: Any = None) -> str:
    """One day against that day's usual: worse = away from usual, better = beyond it on the favourable side (only
    for measures that may count as better), similar = within usual, unknown = no personal usual yet."""
    if p is None:
        return "unknown"
    thr = float(crit.param(m, "z_threshold"))
    if p.z >= thr:
        return "worse"
    same = bool(shown) and shown(p.value, m.unit) == shown(p.base.median, m.unit)
    return "better" if p.z <= -thr and m.counts_for_better and not same else "similar"


def metric_course(m: Any, series: dict[date, float], crit: Any, start: date, end: date, shown: Any = None
                  ) -> MetricCourse | None:
    """`shown(value, unit)`: how a value is printed. A day that prints the same as the usual is never "away"."""
    thr = float(crit.param(m, "z_threshold"))
    points = [p for _day, _value, p in readings(m, series, crit, start, end, shown) if p is not None]
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


def _tone(r: dict[str, Any]) -> str:
    """' Tone: words flat; voice flat and quiet (as heard by the voice model).' — a model's observation."""
    h = r.get("heard") or {}
    words = [*(h.get("tone") or [])[:2], *([{"low": "quiet", "high": "lively"}[h["energy"]]] if h.get("energy") in ("low", "high") else [])]
    parts = ([f"words {' and '.join(r['tone'][:2])}"] if r.get("tone") else []) + (
        [("voice " if h.get("provenance") == "model_heard" else "read as ") + " and ".join(words)
         + (" (as heard by the voice model)" if h.get("provenance") == "model_heard" else " (by the model, from typed words)")]
        if words else [])
    return f" Tone: {'; '.join(parts)}." if parts else ""


NAMED = 3  # how many measures the course summary names before "and N more"
LIMIT = 900  # api.Course.summary


def marked(items: list[MetricCourse]) -> list[MetricCourse]:
    """Most marked first: how far from usual at the furthest day, by the metric's weight. The order the course
    summary names measures in, and the order the graph links them in."""
    return sorted(items, key=lambda mc: -mc.lowest.z * max(mc.metric.weight, 0.25))


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
        if m is not None and shown_only(m):
            text += SHOWN_NOTE
        events.append((day, order, CourseEvent(date=day, kind=kind, group=m.source if m else None,  # type: ignore[arg-type]
                                               metric_id=m.name if m else None, label=label[:120], text=text[:300])))

    scored = {name: mc for name, mc in found.items() if not shown_only(mc.metric)}
    deepest = {mc.metric.name for mc in sorted(scored.values(), key=lambda mc: -mc.lowest.z)[:5]}
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
            + (f"; {' and '.join(r['themes'][:2])} came up." if r["themes"] else ".") + _tone(r))
        if lighter:
            r = lighter[0]
            add(r["day"], 3, "reflection_lighter", "Reflections with Kaiku",
                f"Reflections with Kaiku sounded lighter from the {r['part']} of {human_date(r['day'])}"
                + (f"; {' and '.join(r['themes'][:2])} came up." if r["themes"] else ".") + _tone(r))
    events.sort(key=lambda e: (e[0], e[1]))

    def names(items: list[MetricCourse]) -> str:
        """The most marked changes by name (how far from usual at the furthest day), then how many more."""
        return _join([naming[mc.metric.name] for mc in marked(items)], NAMED)

    labels = [short(mc.metric.label).lower() for mc in found.values()]
    naming = {mc.metric.name: (short(mc.metric.label).lower() if labels.count(short(mc.metric.label).lower()) == 1
                               else mc.metric.label.lower()) for mc in found.values()}
    onsets = sorted(scored.values(), key=lambda mc: mc.onset.day)
    back = [mc for mc in onsets if mc.back]
    still = [mc for mc in onsets if not mc.back]
    rule_worse = any(v.verdict == "worse" for v in c.sources)
    beside = sorted((mc for mc in found.values() if shown_only(mc.metric)), key=lambda mc: mc.onset.day)
    also: list[str] = []  # the sentence for shown measures, long form then short: the first that fits is used
    if beside:
        since = human_date(beside[0].onset.day)
        returned = [mc for mc in beside if mc.back]
        many = len(beside) > 1
        count = f"{len(beside)} measure{'s' if many else ''} shown without a vote"
        if len(returned) == len(beside):
            also = [f"Shown, not scored: {names(beside)} {'were' if many else 'was'} away from "
                    f"{'their' if many else 'its'} usual from {since} and {'are' if many else 'is'} back within it.",
                    f"{count} also moved away from {since} and {'are' if many else 'is'} back."]
        elif returned:
            also = [f"Shown, not scored: {names(beside)} moved away from their usual from {since}; "
                    f"{names(returned)} {'are' if len(returned) > 1 else 'is'} back within it.",
                    f"{count} also moved away from {since}; {len(returned)} of them {'are' if len(returned) > 1 else 'is'} back."]
        else:
            also = [f"Shown, not scored: {names(beside)} {'have' if many else 'has'} been away from "
                    f"{'their' if many else 'its'} usual since {since}.",
                    f"{count} {'have' if many else 'has'} also been away from usual since {since}."]

    def told(parts: list[str], at: int | None = None) -> str:
        """The summary with the shown measures' sentence where it belongs, in the longest form that fits."""
        for extra in also:
            text = " ".join([*parts[:at], extra, *parts[at:]] if at is not None else [*parts, extra])
            if len(text) <= LIMIT:
                return text
        return " ".join(parts)[:LIMIT]
    if not onsets:
        phase = "settling" if early else "steady"
        kind = "scored measure" if beside else "measure"
        summary = told([f"Day {day_of_record} of the record: the personal usual is still forming, and no {kind} has "
                        "moved away from it for more than a day so far." if early else
                        f"No {kind} has stayed away from their usual in the last {(end - start).days + 1} days."])
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
        beside_at = len(parts)  # shown measures are told after the scored ones and before the context sentences
        if low_talks:
            parts.append(f"Their reflections with Kaiku sounded low from {human_date(low_talks[0]['day'])}"
                         + (f" and lighter from {human_date(lighter[0]['day'])}." if lighter else "."))
        if early:
            parts.append(f"Day {day_of_record} of the record: this rests on an early baseline, so read it with lower "
                         "confidence.")
        summary = told(parts, beside_at)
        if not back:
            phase = "dip"
        elif still or rule_worse or early or c.state != "stable":
            phase = "recovering"  # the consensus has not returned to stable (or cannot yet): not "recovered"
        else:
            phase = "recovered"
    away_on = Counter(day for mc in scored.values() for day in mc.away_days)
    low_date = max(away_on, key=lambda d: (away_on[d], d)) if away_on else None
    return Course(phase=phase, low_date=low_date, moved=len(scored), back=len(back) if onsets else 0,  # type: ignore[arg-type]
                  summary=summary[:LIMIT], events=[e for _d, _o, e in events]), found


# ------------------------------------------------------------------ what was learned, as graph links
def learned(found: dict[str, MetricCourse], actions: list[dict[str, Any]], r_list: list[Routine],
            occ: dict[str, list[datetime]], end: date, nodes: dict[str, InsightNode]) -> list[InsightEdge]:
    """Links found in this person's record. Order in time and co-occurrence only; evidence = days behind each, and
    `on` = the days a link is about. Care actions become nodes whether or not anything moved."""
    edges: list[InsightEdge] = []
    start = end - timedelta(days=int(get("insight", "course_days", 28)) - 1)
    follow = int(get("graph", "follow_days", 3))
    care: list[tuple[date, str]] = []
    for i, a in enumerate(actions):
        day = parse_ts(a["ts"]).astimezone(TZ).date()
        if not start <= day <= end + timedelta(days=1):
            continue
        cid = f"care:{i}"
        title = ACTION_TEXT.get(a["action"], "Care team action")
        nodes[cid] = InsightNode(id=cid, kind="care_action", layer="learned", label=f"{title} · {human_date(day)}",
                                 detail="Logged by the care team. What came back afterwards is order in time, not "
                                        "proof of effect.", evidence=1)
        edges.append(InsightEdge(src="person", dst=cid, rel="has_signal", layer="learned", label="care action",
                                 weight=1.0, evidence=1, on=[day]))
        care.append((day, cid))
    onsets = sorted(found.values(), key=lambda mc: (mc.onset.day, mc.metric.name))
    if not onsets:
        return edges
    # What moved first is said of the scored measures (as the course summary says it). A shown measure can follow,
    # move on the same days or come back after a care action: order in time, never a cause and never a vote.
    leading = [mc for mc in onsets if not shown_only(mc.metric)] or onsets

    def node(mc: MetricCourse) -> str:
        return f"measure:{mc.metric.name}"

    def days(n: int) -> str:
        return f"{n} day{'s' if n != 1 else ''}"

    # Everything that moved on the first day moved first; what moved within `follow` days of it followed. The
    # links run from the first movers the course summary names (the most marked ones), never from an arbitrary one.
    first_day = leading[0].onset.day
    first = [mc for mc in marked([mc for mc in leading if mc.onset.day == first_day]) if node(mc) in nodes]
    for mc in first:
        edges.append(InsightEdge(src="person", dst=node(mc), rel="moved_first", layer="learned",
                                 label=f"first to move, {human_date(first_day)}", weight=1.0,
                                 evidence=len(mc.away_days), on=[first_day], tag="first"))
    later = [mc for mc in onsets if first_day < mc.onset.day <= first_day + timedelta(days=follow) and node(mc) in nodes]
    for lead in first[:NAMED]:
        for mc in later:
            gap = (mc.onset.day - first_day).days
            edges.append(InsightEdge(src=node(lead), dst=node(mc), rel="followed", layer="learned",
                                     label=f"moved {days(gap)} later (order, not cause)",
                                     weight=round(max(0.2, 1 - gap / 7), 3), evidence=len(mc.away_days),
                                     on=[mc.onset.day], tag=f"+{days(gap)}"))
    # Away from usual on the same days, in different signal groups: the closest overlaps first.
    pairs = []
    for i, a in enumerate(onsets):
        for b in onsets[i + 1:]:
            both = a.away_days & b.away_days
            if a.metric.source != b.metric.source and len(both) >= 2 and node(a) in nodes and node(b) in nodes:
                pairs.append((len(both) / len(a.away_days | b.away_days), len(both), a, b))
    pairs.sort(key=lambda p: (-p[0], -p[1], p[2].metric.name, p[3].metric.name))
    for overlap, n, a, b in pairs[:int(get("graph", "together", 6))]:
        edges.append(InsightEdge(src=node(a), dst=node(b), rel="moved_together", layer="learned",
                                 label=f"away from usual on the same {n} days", weight=round(overlap, 3), evidence=n,
                                 on=sorted(a.away_days & b.away_days), tag=f"{n} days"))
    spell_days = sorted(set().union(*(mc.away_days for mc in onsets)))
    spell = [spell_days[0] + timedelta(days=i) for i in range((min(end, spell_days[-1]) - spell_days[0]).days + 1)]
    for r in r_list:
        rid = f"routine:{r.activity}"
        if rid not in nodes or r.activity == "sleep" or len(spell) < 3:
            continue
        kept = {week._day_of(r.activity, t) for t in occ.get(r.activity, [])} & set(spell)
        done = len(kept)
        expected = (1.0 if r.cadence == "weekly" else r.usual_per_week) / 7 * len(spell)
        if expected < 1:
            continue
        ratio = done / expected
        rel = "kept_through" if ratio >= 0.8 else "slipped_during" if ratio < 0.5 else None
        if rel:
            edges.append(InsightEdge(src="person", dst=rid, rel=rel, layer="learned",
                                     label=f"{done} of {len(spell)} days while measures were away from usual",
                                     weight=round(min(1.0, ratio), 3), evidence=done, on=sorted(kept),
                                     tag=f"{done} of {len(spell)}"))
    # What came back after a care action: each measure is tied to the latest action on or before its return.
    back_days = int(get("graph", "back_days", 7))
    for mc in sorted((mc for mc in onsets if mc.back and node(mc) in nodes),
                     key=lambda mc: (mc.back.day, -mc.lowest.z)):  # type: ignore[union-attr]
        before = [(day, cid) for day, cid in care if first_day <= day <= mc.back.day]  # type: ignore[union-attr]
        if not before:
            continue
        day, cid = max(before)
        gap = (mc.back.day - day).days  # type: ignore[union-attr]
        if gap > back_days:
            continue
        edges.append(InsightEdge(src=cid, dst=node(mc), rel="after", layer="learned",
                                 label="back within usual the same day" if gap == 0
                                 else f"back within usual {days(gap)} after",
                                 weight=round(max(0.2, 1 - gap / 10), 3), evidence=1, on=[mc.back.day],  # type: ignore[union-attr]
                                 tag="same day" if gap == 0 else f"+{days(gap)}"))
    return edges
