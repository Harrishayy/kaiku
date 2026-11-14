"""Plain-language views built by code for the practitioner insight:

- `generic_records`: every observation type that no enabled criteria metric already describes becomes a citable
  record straight from its payload (numbers, yes/no, short enums) and its registry label. This is how a NEW robot
  signal reaches Gemma's review with no cloud code: register the obs type, map it in `sources.py`, post it.
- `reflections`: reflection summaries (level + themes) as counts, only while the person shares.
- `days`: one line per day from all sources: what was done, what was away from usual, how the reflection went.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from kaiku_contracts.api import (
    DayAccount,
    RecordCitation,
    ReflectionDay,
    ReflectionOverview,
    Routine,
    SourceCount,
)
from kaiku_contracts.sources import CONSENSUS_SOURCES, SOURCE_OF

from . import week
from .analytics.metrics import local_date, parse_ts
from .course import ACTION_TEXT, MetricCourse, human_date, short
from .mind import affect
from .settings import TZ
from .store.db import Store

SKIP_ROLES = {"learner", "override"}  # shown through the learner ("what helps") and the safety path
SKIP_FIELDS = {"session_id", "episode_id", "id", "device", "method", "channel", "item", "date"}
ROBOT_SOURCES = {"hub", "head", "sensors"}


def obs_label(obs_type: str, labels: dict[str, str]) -> str:
    return labels.get(obs_type) or obs_type.removeprefix("obs.").replace("_", " ").capitalize()


def _fields(payload: dict[str, Any]) -> list[str]:
    out = []
    for key, value in payload.items():
        if key in SKIP_FIELDS or key.endswith("_id") or value is None:
            continue
        name = key.replace("_", " ")
        if isinstance(value, bool):
            out.append(f"{name} {'yes' if value else 'no'}")
        elif isinstance(value, int | float):
            out.append(f"{name} {value:g}")
        elif isinstance(value, str) and len(value) <= 24 and " " not in value:
            out.append(f"{name} {value.replace('_', ' ')}")
        if len(out) == 5:
            break
    return out


def generic_records(events: list[dict[str, Any]], crit: Any, data: Any, end: date, labels: dict[str, str]
                    ) -> list[RecordCitation]:
    covered = {m.obs for m in crit.metrics if m.enabled and data.series.get(m.name)}
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        role = SOURCE_OF.get(e["type"])
        if e["type"] not in covered and role not in SKIP_ROLES and e["type"] != "obs.phq9" and local_date(e["ts"]) <= end:
            by_type[e["type"]].append(e)
    out = []
    for obs_type, rows in sorted(by_type.items()):
        latest = max(rows, key=lambda e: e["ts"])
        week_days = {local_date(e["ts"]) for e in rows if end - timedelta(days=6) <= local_date(e["ts"]) <= end}
        senders = ", ".join(sorted({e["source"] for e in rows}))
        fields = _fields(latest["payload"])
        detail = (f"Recorded on {len(week_days)} of the last 7 days (sent by {senders}); latest on "
                  f"{human_date(local_date(latest['ts']))}" + (": " + ", ".join(fields) + "." if fields else "."))
        role = SOURCE_OF.get(obs_type)
        out.append(RecordCitation(id=f"obs:{obs_type.removeprefix('obs.')}", label=obs_label(obs_type, labels),
                                  detail=detail, source=role if role in CONSENSUS_SOURCES else None,
                                  observed_at=local_date(latest["ts"]), simulated=all(e.get("sim") for e in rows)))
    robot = any(e["source"] in ROBOT_SOURCES for e in events)
    if robot and not any(e["type"] == "obs.hrv_session" for e in events):
        out.append(RecordCitation(id="obs:hrv_session", label=obs_label("obs.hrv_session", labels), source="robot",
                                  detail="Not measured in this record: no pulse reading has passed the quality check.",
                                  observed_at=end))
    return out


def _top(rows: list[dict[str, Any]], k: int = 2) -> str:
    return ", ".join(t for t, _ in Counter(t for r in rows for t in r["themes"]).most_common(k))


def low_spell(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(reflections that sounded low, the rated ones after the last low one)."""
    rated = [r for r in rows if r["valence"]]
    low = [r for r in rated if r["valence"] == "low"]
    after = [r for r in rated if low and r["start"] > low[-1]["start"]]
    return low, after


def fortnight(rows: list[dict[str, Any]]) -> str:
    """The last 14 days of reflections in one or two sentences: when they sounded low, since when lighter, and
    what came up in each stretch. Level and themes only."""
    rated = [r for r in rows if r["valence"]]
    declined = [r for r in rows if r["declined"]]
    if not rated and not declined:
        return "No reflection summaries in the last 14 days."
    low, after = low_spell(rows)
    parts = []
    if low:
        first, final = low[0]["day"], low[-1]["day"]
        span = [r for r in rated if low[0]["start"] <= r["start"] <= low[-1]["start"]]
        when = human_date(first) if first == final else f"{human_date(first)} and {human_date(final)}"
        parts.append(f"Reflections with Kaiku sounded low in {len(low)} of {len(span)} between {when}"
                     if first != final else f"A reflection with Kaiku sounded low on {when}")
        if after:
            parts[-1] += f"; lighter since the {after[0]['part']} of {human_date(after[0]['day'])}"
        parts[-1] += "."
        was, now_ = _top(low), _top(after)
        if was or now_:
            parts.append("Themes: " + (was or "none named") + (f", then {now_}" if after and now_ else "") + ".")
    else:
        n = Counter(r["valence"] for r in rated)
        parts.append(f"{len(rated)} reflection{'s' if len(rated) != 1 else ''} with Kaiku in the last 14 days: "
                     f"{n['neutral']} ordinary, {n['bright']} bright, none low.")
        if _top(rated, 3):
            parts.append(f"Themes: {_top(rated, 3)}.")
    if declined:
        days_ = ", ".join(human_date(r["day"]) for r in declined[:3])
        parts.append(f"Did not want to talk on {days_}.")
    parts.append("Level and themes only; their words are not shared.")
    return " ".join(parts)


def tone_summary(rows: list[dict[str, Any]]) -> str | None:
    """How the reflections sounded, by provenance: the tone of their words (rules or Gemma, opted-in text only) and
    the tone the model in the conversation reported. Counts of fixed tags; never their words."""
    worded = [r for r in rows if r.get("tone") or r.get("energy")]
    heard = [r["heard"] for r in rows if r.get("heard")]
    if not worded and not heard:
        return None

    def tags(counter: Counter) -> str:
        return ", ".join(f"{t} in {n}" for t, n in counter.most_common(3)) or "no tone tag"

    parts = []
    if worded:
        low = sum(1 for r in worded if r.get("energy") == "low")
        parts.append(f"Tone of their words in {len(worded)} reflection{'s' if len(worded) != 1 else ''}: "
                     + tags(Counter(t for r in worded for t in r.get("tone") or []))
                     + (f"; energy read low in {low}." if low else "."))
    if heard:
        voice = sum(1 for h in heard if h["provenance"] == "model_heard")
        who = "As heard by the voice model" if voice == len(heard) else \
            "As the model read their typed words" if not voice else "As the model in the conversation reported"
        low = sum(1 for h in heard if h.get("energy") == "low")
        parts.append(f"{who} in {len(heard)}: " + tags(Counter(t for h in heard for t in h.get("tone") or []))
                     + (f"; sounded quiet in {low}." if low else "."))
    parts.append("Tone is a model's observation of a conversation, not a measurement.")
    return " ".join(parts)


def talk_part(r: dict[str, Any]) -> str:
    """'evening reflection low (sleep), voice flat and quiet': one reflection in a day's account."""
    text = f"{r['part']} reflection {'ordinary' if r['valence'] == 'neutral' else r['valence']}"
    if r["themes"]:
        text += f" ({', '.join(r['themes'][:2])})"
    if r.get("tone"):
        text += f", words {' and '.join(r['tone'][:2])}"
    words = affect.heard_words(r.get("heard"))
    if words:
        text += (", voice " if r["heard"]["provenance"] == "model_heard" else ", read as ") + words
    return text


def reflections(store: Store, home_id: str, now: datetime, shared: bool
                ) -> tuple[ReflectionOverview | None, list[dict[str, Any]], RecordCitation | None, str]:
    """(overview, rows of the last 14 days, citable record, direction). Nothing at all unless the person shares."""
    if not shared:
        return None, [], None, "unknown"
    rows = affect.recent(store, home_id, now, days=14)
    last = [r for r in rows if r["day"] >= now.astimezone(TZ).date() - timedelta(days=6)]
    rated = [r for r in last if r["valence"]]
    n = Counter(r["valence"] for r in rated)
    declined = sum(1 for r in last if r["declined"])
    themes = Counter(t for r in last for t in r["themes"])
    summary = fortnight(rows)
    overview = ReflectionOverview(
        shared=True, reflections=len(rated), low=n["low"], neutral=n["neutral"], bright=n["bright"],
        declined=declined, themes=[SourceCount(label=t, value=c) for t, c in themes.most_common(5)],
        days=[ReflectionDay(date=r["day"], part=r["part"], valence=r["valence"], themes=r["themes"],
                            declined=r["declined"], tone=(r.get("tone") or [])[:2], energy=r.get("energy"),
                            heard=affect.public_heard(r)) for r in rows],
        summary=summary[:400], tone_summary=tone_summary(rows))
    tone = "unknown"
    if len(rated) >= 2:
        tone = "worse" if n["low"] * 2 > len(rated) else "better" if n["bright"] * 2 > len(rated) else "similar"
    record = RecordCitation(id="reflect:recent", label="Reflections with Kaiku",
                            detail=" ".join(x for x in (summary, overview.tone_summary) if x),
                            observed_at=rows[-1]["day"]) if rows else None
    return overview, rows, record, tone


MISSING = {"ritual": "morning ritual skipped", "walk": "no walk", "drum": "no drumming", "play": "no game"}
DONE = {"ritual": "morning ritual done", "drum": "drum session", "breathe": "breathing round", "play": "game",
        "checkin": "weather check", "laptop": "laptop check-in"}


def _qualifier(mc: MetricCourse, day: date) -> str:
    """'drum tempo below usual': the measure and which side of the person's usual it was on that day."""
    m = mc.metric
    side = ("later than" if m.worse_when == "up" else "earlier than") if m.unit in ("min after midnight", "min from midnight") \
        else ("above" if m.worse_when == "up" else "below")
    return f"{short(m.label).lower()} {side} usual"


def days(events: list[dict[str, Any]], found: dict[str, MetricCourse], actions: list[dict[str, Any]],
         reflection_rows: list[dict[str, Any]], end: date, human_value: Any, r_list: list[Routine] | None = None,
         n: int = 14) -> list[DayAccount]:
    occ = week.occurrences(events, None)
    done: dict[date, set[str]] = defaultdict(set)
    for key, stamps in occ.items():
        for day in {week._day_of(key, t) for t in stamps}:
            done[day].add(key)
    out_min: dict[date, float] = defaultdict(float)
    mood: dict[date, list[float]] = defaultdict(list)
    recorded = {local_date(e["ts"]) for e in events}
    first_day = min(recorded, default=end)
    for e in events:
        day = local_date(e["ts"])
        if e["type"] == "obs.outing":
            out_min[day] += float(e["payload"].get("minutes") or 0)
        elif e["type"] == "obs.self_report" and e["payload"].get("item") == "mood":
            mood[day].append(float(e["payload"]["value"]))
    care = defaultdict(list)
    for a in actions:
        care[parse_ts(a["ts"]).astimezone(TZ).date()].append(ACTION_TEXT.get(a["action"], "Care team action").lower())
    talks = defaultdict(list)
    for r in reflection_rows:
        if r["valence"]:
            talks[r["day"]].append(talk_part(r))
        elif r["declined"]:
            talks[r["day"]].append(f"did not want to talk in the {r['part']}")
    usual = [r.activity for r in (r_list or []) if r.cadence == "daily" and r.activity in MISSING]
    out = []
    for i in range(n):
        day = end - timedelta(days=i)
        if day < first_day:
            break
        parts = []
        did = done.get(day, set())
        if day in recorded:
            for key in ("ritual", "drum", "breathe"):
                if key in did:
                    parts.append(DONE[key])
                elif key in usual:
                    parts.append(MISSING[key])
            if "walk" in did:
                parts.append(f"out for {human_value(out_min[day], 'min')}")
            elif "walk" in usual:
                parts.append(MISSING["walk"])
            parts += [DONE[k] for k in ("play", "checkin", "laptop") if k in did]
            parts += [MISSING[k] for k in ("play",) if k in usual and k not in did]
        away = sorted((mc for mc in found.values() if day in mc.away_days),
                      key=lambda mc: -mc.metric.weight * max(mc.lowest.z, 0.1))
        phrases = list(dict.fromkeys(_qualifier(mc, day) for mc in away))
        parts += phrases[:4]
        if len(phrases) > 4:
            more = len(phrases) - 4
            parts.append(f"{more} more measure{'s' if more != 1 else ''} away from usual")
        if mood.get(day):
            parts.append(f"mood {human_value(sum(mood[day]) / len(mood[day]), '1–5')}")
        parts += talks.get(day, []) + care.get(day, [])
        if not parts:
            parts = ["nothing recorded"]
        out.append(DayAccount(date=day, text=(f"{day:%a} {human_date(day)}: " + "; ".join(parts) + ".")[:400], parts=parts))
    return out
