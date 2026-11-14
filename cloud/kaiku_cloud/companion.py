"""Person-facing companion bits of GET /v1/me (plan 02 §2, §5, §8): mascot mood, "Your days" highlights, garden.

All pure functions of (events, criteria, consensus state, local time) — one implementation, every client renders it.
- mascot: never sad or worried at the person. stable -> idle (happy if you did something together today/yesterday),
  watch -> cozy, needs_call -> cozy + the nurse-chat offer, safety -> "crisis" (clients show the scripted screen,
  no line). line_key always exists in config/voice_lines.toml (tested).
- highlights: good moments come from finished interactions; a "hard" note only from a metric whose
  `person_hard` sentence is set in config/criteria.toml (wording lives there, not in code) and only when that day was
  beyond the usual in its worse direction. Max 3 hard notes a week, at most one a day.
- garden: finished interactions in the last 14 days; resting after 3 quiet days. Never wilts, no streaks.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from kaiku_contracts.api import Garden, GardenDay, Highlight, Mascot
from kaiku_contracts.criteria import Criteria

from .analytics.data import PatientData
from .analytics.drift import baseline_of, worse_z
from .analytics.metrics import local_date

GARDEN_DAYS = 14
RESTING_AFTER_DAYS = 3
HIGHLIGHT_DAYS = 7
MAX_HARD = 3
MAX_HIGHLIGHTS = 12
PLAY_TEXT = {"firefly": "You caught fireflies together.", "breathe": "You breathed with Kaiku.",
             "tell": "You told Kaiku about your day.", "pebbles": "You played pebbles together."}


def time_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def mascot_for(state: str, hour: int, together_recently: bool) -> Mascot:
    """The ambient mood. A pure function: same inputs, same mascot, on every surface."""
    if state == "safety":
        return Mascot(mood="crisis", line_key=None)
    if state == "needs_call":
        return Mascot(mood="cozy", line_key="needs_call.offer")
    if state == "watch":
        return Mascot(mood="cozy", line_key="checkin.cozy")
    return Mascot(mood="happy" if together_recently else "idle", line_key=f"greet.{time_of_day(hour)}")


def interactions(events: list[dict[str, Any]]) -> list[tuple[date, str]]:
    """(local day, kind) for every finished interaction. A weather check off the robot counts once per day+channel
    (its three dial answers are one interaction); the robot dial is part of the ritual, already counted."""
    out: list[tuple[date, str]] = []
    checks: set[tuple[date, str]] = set()
    for e in events:
        t, p, day = e["type"], e["payload"], local_date(e["ts"])
        if t == "obs.ritual" and p.get("step") == "close" and p.get("status") == "completed":
            out.append((day, "ritual"))
        elif t in ("obs.drum_session", "obs.play_session", "obs.outing"):
            out.append((day, t.split(".", 1)[1]))
        elif t == "obs.friend_link" and p.get("direction") == "sent":
            out.append((day, "friend_link"))
        elif t == "obs.self_report" and p.get("channel", "robot") != "robot" and (day, p["channel"]) not in checks:
            checks.add((day, p["channel"]))
            out.append((day, "weather_check"))
    return out


def garden_for(events: list[dict[str, Any]], today: date) -> Garden:
    done = interactions(events)
    plants = sum(1 for d, _ in done if today - timedelta(days=GARDEN_DAYS) < d <= today)
    last = max((d for d, _ in done if d <= today), default=None)
    per: dict[date, list[str]] = {}
    for d, kind in done:
        if today - timedelta(days=GARDEN_DAYS) < d <= today:
            per.setdefault(d, []).append(kind)
    days = [GardenDay(date=d, count=len(per.get(d, [])), kinds=sorted(set(per.get(d, []))))
            for d in (today - timedelta(days=i) for i in range(GARDEN_DAYS - 1, -1, -1))]
    return Garden(plants=plants, resting=last is not None and (today - last).days >= RESTING_AFTER_DAYS, days=days)


def together_recently(events: list[dict[str, Any]], today: date) -> bool:
    return any((today - d).days <= 1 for d, _ in interactions(events) if d <= today)


def _good(events: list[dict[str, Any]], since: date, today: date) -> list[Highlight]:
    best: dict[tuple[date, str], Highlight] = {}
    walks: dict[date, dict[str, Any]] = {}
    for e in events:
        day = local_date(e["ts"])
        if not since <= day <= today:
            continue
        t, p = e["type"], e["payload"]
        if t == "obs.outing" and p.get("minutes", 0) >= 5:
            if day not in walks or p["minutes"] > walks[day]["minutes"]:
                walks[day] = p
        elif t == "obs.drum_session":
            best.setdefault((day, "drum"), Highlight(date=day, kind="good", text="You drummed with Kaiku.",
                                                     source="robot"))
        elif t == "obs.play_session" and p.get("game") in PLAY_TEXT:
            best.setdefault((day, p["game"]), Highlight(date=day, kind="good", text=PLAY_TEXT[p["game"]],
                                                        source="laptop"))
        elif t == "obs.friend_link" and p.get("direction") == "sent":
            best.setdefault((day, "friend"), Highlight(date=day, kind="good", text="You sent a glow to your friend.",
                                                       source="robot"))
        elif t == "obs.wearable_daily" and (p.get("sleep_min") or 0) >= 420:
            hours = round(p["sleep_min"] / 30) / 2
            best.setdefault((day, "sleep"), Highlight(date=day, kind="good",
                                                      text=f"A good long night's sleep, about {hours:g} hours.",
                                                      source="wearable"))
    for day, p in walks.items():
        text = f"A {round(p['minutes'])}-minute walk outside"
        if (p.get("daylight_min") or 0) >= 10:
            text += f", with {round(p['daylight_min'])} minutes of daylight"
        best[(day, "walk")] = Highlight(date=day, kind="good", text=text + ".", source="glasses")
    return list(best.values())


def _hard(data: PatientData, crit: Criteria, since: date, today: date) -> list[Highlight]:
    out: list[Highlight] = []
    seen: set[date] = set()
    for m in crit.metrics:
        if not (m.enabled and m.person_hard):
            continue
        series = data.series.get(m.name, {})
        thr = float(crit.param(m, "z_threshold"))
        for day in sorted(d for d in series if since <= d <= today):
            b = baseline_of(m, series, day, crit)
            if day in seen or b is None or worse_z(series[day], b, m.worse_when) < thr:
                continue
            seen.add(day)
            out.append(Highlight(date=day, kind="hard", text=m.person_hard, source=m.source))
    out.sort(key=lambda h: h.date, reverse=True)
    return out[:MAX_HARD]


def highlights_for(events: list[dict[str, Any]], data: PatientData, crit: Criteria, today: date) -> list[Highlight]:
    """Last 7 days, newest first; on each day the good moments come first."""
    since = today - timedelta(days=HIGHLIGHT_DAYS - 1)
    items = _good(events, since, today) + _hard(data, crit, since, today)
    items.sort(key=lambda h: (h.date, h.kind == "good"), reverse=True)
    return items[:MAX_HIGHLIGHTS]
