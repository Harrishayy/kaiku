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

from kaiku_contracts.api import DayAccount, RecordCitation, ReflectionOverview, SourceCount
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
    if not last:
        summary = "No reflection summaries in the last 7 days."
    else:
        parts = []
        if rated:
            parts.append(f"{len(rated)} reflection{'s' if len(rated) != 1 else ''} with Kaiku in the last 7 days: "
                         f"{n['low']} sounded low, {n['neutral']} ordinary, {n['bright']} bright")
        if declined:
            parts.append(f"{declined} time{'s' if declined != 1 else ''} they did not want to talk or asked to stop")
        summary = "; ".join(parts) + "."
        if themes:
            summary += " Came up most: " + ", ".join(t for t, _ in themes.most_common(3)) + "."
        summary += " Level and themes only; their words are not shared."
    overview = ReflectionOverview(shared=True, reflections=len(rated), low=n["low"], neutral=n["neutral"],
                                  bright=n["bright"], declined=declined,
                                  themes=[SourceCount(label=t, value=c) for t, c in themes.most_common(5)],
                                  summary=summary[:300])
    tone = "unknown"
    if len(rated) >= 2:
        tone = "worse" if n["low"] * 2 > len(rated) else "better" if n["bright"] * 2 > len(rated) else "similar"
    record = RecordCitation(id="reflect:recent", label="Reflections with Kaiku", detail=summary,
                            observed_at=last[-1]["day"]) if last else None
    return overview, rows, record, tone


def days(events: list[dict[str, Any]], found: dict[str, MetricCourse], actions: list[dict[str, Any]],
         reflection_rows: list[dict[str, Any]], end: date, human_value: Any, n: int = 14) -> list[DayAccount]:
    occ = week.occurrences(events, None)
    done: dict[date, list[str]] = defaultdict(list)
    for key, stamps in occ.items():
        if key == "sleep":
            continue
        for day in {week._day_of(key, t) for t in stamps}:
            done[day].append(week.ONE.get(key, key))
    out_min: dict[date, float] = defaultdict(float)
    mood: dict[date, list[float]] = defaultdict(list)
    first_day = min((local_date(e["ts"]) for e in events), default=end)
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
            talks[r["day"]].append(f"{r['part']} reflection {'ordinary' if r['valence'] == 'neutral' else r['valence']}"
                                   + (f" ({', '.join(r['themes'][:2])})" if r["themes"] else ""))
        elif r["declined"]:
            talks[r["day"]].append(f"did not want to talk in the {r['part']}")
    out = []
    for i in range(n):
        day = end - timedelta(days=i)
        if day < first_day:
            break
        parts = []
        acts = sorted(set(done.get(day, [])), key=lambda a: (a != "morning ritual", a))
        if day in out_min and "walk" in acts:
            acts = [f"walk ({human_value(out_min[day], 'min')})" if a == "walk" else a for a in acts]
        if acts:
            parts.append(", ".join(acts))
        if mood.get(day):
            parts.append(f"mood {human_value(sum(mood[day]) / len(mood[day]), '1–5')}")
        away = sorted((mc for mc in found.values() if day in mc.away_days), key=lambda mc: -mc.metric.weight)
        if away:
            names = list(dict.fromkeys(short(mc.metric.label).lower() for mc in away))
            parts.append("away from usual: " + ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else ""))
        parts += talks.get(day, []) + care.get(day, [])
        if not parts:
            parts = ["nothing recorded"]
        out.append(DayAccount(date=day, text=(f"{day:%a} {human_date(day)}: " + "; ".join(parts) + ".")[:400], parts=parts))
    return out
