"""The week and what Kaiku has learned (dashboard, D34): routines, going well, worth a look, knowledge graph view.

Everything here is deterministic code over data the cloud already has; no model decides or phrases anything, and
nothing here feeds the consensus.
- Routines: days with an activity in the usual weeks (`[week] usual_weeks` before the last 7 days) → daily /
  most days / a weekday rhythm, the usual local time (median), and how this week compares (kept / partly / slipped).
  Activities come from obs (ritual, walks, drum, breathing, weather checks, laptop check-in, games, sleep from the
  watch) and, for the person (or when they share), from finished conversations (episodes).
- Going well / worth a look: routines kept or slipped, per-metric drift against the person's own usual
  (`analytics.drift`, thresholds from `config/criteria.toml`), source verdicts, what helped (bandit), safety flags
  and PHQ-9 cadence (care team). The person sees warm sentences and never states, scores or z values.
- Knowledge graph: `mind/graph.py` nodes/edges plus obs-only activities and routine nodes, with evidence counts.
  The care team gets it only when the person shares (`/v1/me/sharing`, default off), and then only me /
  activities / what helps / routines: people, places, likes and plans are always withheld.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

from kaiku_contracts.api import (
    CareSharing,
    Consensus,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NextStep,
    Routine,
    SourceCount,
    SourceWeek,
    WeekItem,
    WeekSummary,
)
from kaiku_contracts.config import get
from kaiku_contracts.sources import SOURCE_LABELS

from . import companion, service
from .analytics import bandit
from .analytics.drift import drift_for
from .analytics.metrics import local_date, parse_ts
from .mind import graph as mind_graph
from .settings import TZ, Settings
from .store.db import Store

# activity key -> (person label, care-team label, consensus source it is observed by)
ACTIVITIES: dict[str, tuple[str, str, str | None]] = {
    "ritual": ("Morning ritual with Kaiku", "Morning ritual (robot)", "robot"),
    "walk": ("Walks and outings", "Walks and outings", "glasses"),
    "drum": ("Drumming with Kaiku", "Drum sessions (robot)", "robot"),
    "breathe": ("Breathing with Kaiku", "Guided breathing", "robot"),
    "checkin": ("Weather checks", "Self-report check-ins (apps)", "robot"),
    "laptop": ("Laptop check-in", "Laptop sessions", "laptop"),
    "play": ("Games with Kaiku", "Games (apps)", "laptop"),
    "sleep": ("Going to sleep", "Sleep onset (watch)", "wearable"),
}
EPISODE_ACTIVITY = {"walk": "walk", "breathe": "breathe", "break": "breathe", "ritual": "ritual",
                    "checkin": "checkin"}
GRAPH_LABEL = {"laptop": "the laptop check-in", "play": "games"}  # kg labels for obs-only activities
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CARE_TYPES = {"me", "activity", "routine"}  # free-text helpers may include private names/places
_SHARE_KEY = "share_care:{}"


def cfg(key: str, default: Any) -> Any:
    return get("week", key, default)


# ------------------------------------------------------------------ sharing (the person's choice, default off)
def sharing(store: Store, home_id: str) -> CareSharing:
    return CareSharing(share_with_care_team=bool(store.kv_get(_SHARE_KEY.format(home_id))))


def set_sharing(store: Store, home_id: str, body: CareSharing) -> CareSharing:
    if body.share_with_care_team:
        store.kv_set(_SHARE_KEY.format(home_id), True)
    else:
        store.kv_delete(_SHARE_KEY.format(home_id))
    return sharing(store, home_id)


# ------------------------------------------------------------------ occurrences
def occurrences(events: list[dict[str, Any]], episodes: list[dict[str, Any]] | None) -> dict[str, list[datetime]]:
    """activity -> local datetimes it happened (obs; plus completed episodes when given). Sleep = estimated onset."""
    out: dict[str, list[datetime]] = defaultdict(list)
    for e in events:
        t, p = e["type"], e["payload"]
        ts = parse_ts(e["ts"]).astimezone(TZ)
        key = None
        if t == "obs.ritual" and p.get("step") == "close" and p.get("status") == "completed":
            key = "ritual"
        elif t == "obs.outing" and (p.get("minutes") or 0) >= 5:
            key = "walk"
        elif t == "obs.drum_session":
            key = "drum"
        elif t == "obs.hrv_session" or (t == "obs.intervention_response" and p.get("activity") == "breathe"):
            key = "breathe"
        elif t == "obs.self_report" and p.get("channel") not in (None, "robot"):
            key = "checkin"
        elif t == "obs.laptop_session":
            key = "laptop"
        elif t == "obs.play_session":
            key = "play"
        elif t == "obs.wearable_daily" and p.get("sleep_midpoint_min") is not None and p.get("sleep_min"):
            day = date.fromisoformat(p["date"]) if p.get("date") else ts.date()
            onset = float(p["sleep_midpoint_min"]) - float(p["sleep_min"]) / 2  # minutes from that day's midnight
            ts = datetime(day.year, day.month, day.day, tzinfo=TZ) + timedelta(minutes=onset)
            key = "sleep"
        if key:
            out[key].append(ts)
    for ep in episodes or []:
        if ep.get("outcome") == "completed" and ep.get("intent") in EPISODE_ACTIVITY:
            out[EPISODE_ACTIVITY[ep["intent"]]].append(parse_ts(ep["start"]).astimezone(TZ))
    return out


def _day_of(key: str, ts: datetime) -> date:
    """Sleep onset after midnight still belongs to the evening before."""
    return (ts - timedelta(hours=12)).date() if key == "sleep" else ts.date()


def _minute(key: str, ts: datetime) -> int:
    m = ts.hour * 60 + ts.minute
    return m + 1440 if key == "sleep" and m < 12 * 60 else m  # 00:30 onset sorts after 23:30


def _hhmm(m: float) -> str:
    m = int(round(m)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _day_part(m: float) -> str:
    return companion.time_of_day(int(m) % 1440 // 60)


def week_end(events: list[dict[str, Any]], today: date) -> date:
    """The 7-day week ends today, or yesterday when nothing has arrived yet today."""
    if not events:
        return today
    d = max(local_date(e["ts"]) for e in events)
    return d if today - timedelta(days=1) <= d <= today else today


# ------------------------------------------------------------------ routines
def _routine_text(key: str, cadence: str, weekday: str | None, usual: str | None, part: str | None,
                  per_week: float, this_week: int, audience: str) -> str:
    """The routine in one line, without its label (the label is shown next to it)."""
    if audience == "person":
        if key == "sleep":
            return f"Usually around {usual}. {this_week} nights recorded this week."
        when = {"daily": "Every day", "most_days": "Most days"}.get(cadence) or f"On {weekday}s"
        at = f", usually in the {part} around {usual}" if usual else ""
        return f"{when}{at}. {this_week} day{'s' if this_week != 1 else ''} this week."
    if key == "sleep":
        return f"Usually asleep around {usual}; {this_week} nights recorded this week."
    when = {"daily": "Every day", "most_days": "Most days"}.get(cadence) or f"{weekday}s"
    return f"{when} around {usual}, usually {per_week:.1f} days a week; {this_week} of the last 7 days."


def routines(occ: dict[str, list[datetime]], end: date, audience: str, basis: dict[str, set[str]] | None = None,
             collection_start: date | None = None
             ) -> list[Routine]:
    weeks = int(cfg("usual_weeks", 3))
    week_start = end - timedelta(days=6)
    usual_start = week_start - timedelta(days=7 * weeks)
    collection_start = collection_start or min((ts.date() for stamps in occ.values() for ts in stamps), default=week_start)
    observed_start = max(usual_start, collection_start)
    n_usual = max(1, (week_start - observed_start).days)
    early = n_usual < 7 * weeks
    out: list[Routine] = []
    for key, stamps in occ.items():
        first: dict[date, datetime] = {}
        for ts in sorted(stamps):
            first.setdefault(_day_of(key, ts), ts)
        usual_days = {d for d in first if observed_start <= d < week_start}
        week_days = {d for d in first if week_start <= d <= end}
        if len(usual_days) < int(cfg("min_occurrences", 3)):
            continue
        share = len(usual_days) / n_usual
        cadence, weekday = None, None
        if share >= float(cfg("daily_share", 0.8)):
            cadence = "daily"
        elif share >= float(cfg("most_days_share", 0.45)):
            cadence = "most_days"
        else:
            by_wd = defaultdict(set)
            for d in usual_days:
                by_wd[d.weekday()].add((d - usual_start).days // 7)
            wd, wks = max(by_wd.items(), key=lambda kv: (len(kv[1]), -kv[0]))
            if len(wks) >= min(weeks, max(1, (n_usual + 6) // 7), int(cfg("weekday_min_weeks", 3))):
                cadence, weekday = "weekly", wd
        if cadence is None:
            continue
        mins = [_minute(key, first[d]) for d in sorted(usual_days)]
        usual_m = median(mins)
        if key == "sleep":
            this = [_minute(key, first[d]) for d in week_days]
            shift = (median(this) - usual_m) if this else None
            tol = float(cfg("sleep_shift_min", 45))
            status = "kept" if shift is not None and abs(shift) <= tol else "slipped" if shift is not None and \
                abs(shift) > 2 * tol else "partly"
            per_week = round(share * 7, 1)
        elif cadence == "weekly":
            per_week = round(len(usual_days) / (n_usual / 7), 1)
            on_day = any(d.weekday() == weekday for d in week_days)
            status = "kept" if on_day else "partly" if week_days else "slipped"
        else:
            per_week = round(share * 7, 1)
            ratio = len(week_days) / max(per_week, 1e-9)
            status = "kept" if ratio >= float(cfg("kept_ratio", 0.8)) else "partly" if ratio >= float(
                cfg("partly_ratio", 0.5)) else "slipped"
        wd_name = WEEKDAYS[weekday] if weekday is not None else None
        usual = _hhmm(usual_m)
        out.append(Routine(activity=key, label=ACTIVITIES[key][0 if audience == "person" else 1], cadence=cadence,
                           weekday=wd_name, day_part=_day_part(usual_m), usual_time=usual,
                           usual_per_week=min(7.0, per_week), this_week=min(7, len(week_days)), status=status,
                           text=(f"Emerging pattern: recorded on {len(usual_days)} of {n_usual} earlier days, "
                                 f"around {usual}. {len(week_days)} of 7 days this week."
                                 if early else _routine_text(key, cadence, wd_name, usual, _day_part(usual_m),
                                                           per_week, len(week_days), audience)),
                           basis=sorted((basis or {}).get(key, {"obs"}))))  # type: ignore[arg-type]
    order = {"daily": 0, "most_days": 1, "weekly": 2}
    out.sort(key=lambda r: (r.activity == "sleep", order[r.cadence], -r.usual_per_week))
    return out


# ------------------------------------------------------------------ the week
ONE = {"ritual": "morning ritual", "walk": "walk", "drum": "drum session", "breathe": "breathing round",
       "checkin": "weather check", "laptop": "laptop check-in", "play": "game"}
PERSON_HELP = {"breathe": "Breathing slowly with Kaiku", "walk": "A daylight walk", "drum": "Drumming",
               "friend_ping": "Sending a glow to a friend", "icbt": "Your iCBT exercises"}


def _helped(helps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The best-responding activities (bandit), at most two, above `[week] helped_min` with enough tries."""
    ok = [h for h in helps if h["mean_effect"] is not None and h["mean_effect"] >= float(cfg("helped_min", 0.4))
          and h["tries"] >= int(cfg("helped_min_tries", 3)) and h["activity"] != "icbt"]
    return sorted(ok, key=lambda h: -h["mean_effect"])[:2]


def _person_week(r_list: list[Routine], helps: list[dict[str, Any]], occ_week: dict[str, int], good_moments: int,
                 hard: list[tuple[str, str, str]]) -> tuple[list[WeekItem], list[WeekItem]]:
    well: list[WeekItem] = []
    look: list[WeekItem] = []
    for r in r_list:
        src = ACTIVITIES[r.activity][2]
        name = r.label[0].lower() + r.label[1:]
        one = ONE.get(r.activity, name)
        if r.status == "kept" and r.activity == "sleep":
            well.append(WeekItem(kind="routine", source=src,
                                 text=f"Your bedtime stayed close to your usual, around {r.usual_time}."))
        elif r.status == "kept":
            well.append(WeekItem(kind="routine", source=src, text=f"You kept up {name}: {r.this_week} "
                                 f"day{'s' if r.this_week != 1 else ''} this week."))
        elif r.status == "slipped" and r.activity == "sleep":
            if not any(s == "wearable" for _m, _t, s in hard):  # the sleep sentences below already say it
                look.append(WeekItem(kind="routine", source=src, text="Bedtimes moved away from your usual this "
                                     "week. A calm evening routine can help."))
        elif r.status == "slipped" and r.cadence == "weekly":
            look.append(WeekItem(kind="routine", source=src, text=f"No {r.weekday} {one} this week. Maybe one soon?"))
        elif r.status == "slipped":
            look.append(WeekItem(kind="routine", source=src, text=f"Fewer days with a {one} than your usual this "
                                 f"week ({r.this_week}). A small one still counts."))
    for h in _helped(helps):
        label = PERSON_HELP.get(h["activity"], h["label"])
        n = occ_week.get(h["activity"], 0)
        when = f" You did it on {n} day{'s' if n != 1 else ''} this week." if n else ""
        well.append(WeekItem(kind="helped", text=f"{label} seems to help you most.{when}"))
    if good_moments:
        well.append(WeekItem(kind="moments", text=f"{good_moments} good moment{'s' if good_moments != 1 else ''} "
                             "together this week."))
    for metric, sentence, src in hard:
        look.append(WeekItem(kind="metric", metric=metric, source=src,  # type: ignore[arg-type]
                             text=f"A few days this week: {sentence[0].lower() + sentence[1:]}"))
    return well, look


def _side(m: Any) -> str:
    """Which way the unhelpful direction points, in the measure's own terms (a time of day is later/earlier)."""
    if m.unit in ("min after midnight", "min from midnight"):
        return "later" if m.worse_when == "up" else "earlier"
    return "higher" if m.worse_when == "up" else "lower"


def _z(d: Any) -> float | None:
    """The z of the days that actually voted (drift.z_flag); the latest day's z only when nothing was flagged."""
    return d.z_flag if getattr(d, "z_flag", None) is not None else d.z_last


def _care_week(r_list: list[Routine], helps: list[dict[str, Any]], c: Consensus, drifts: list[tuple[Any, Any]],
               data: Any, settings: Settings, week_start: date, end: date) -> tuple[list[WeekItem], list[WeekItem]]:
    well: list[WeekItem] = []
    look: list[WeekItem] = []
    for ts in data.safety_flags:
        if week_start <= local_date(ts) <= end:
            look.append(WeekItem(kind="safety", text=f"Safety flag on {local_date(ts):%a %d %b}: call today."))
    worse = sorted((md for md in drifts if md[1].status == "drifting"), key=lambda md: -(_z(md[1]) or 0))
    top = int(cfg("max_metric_items", 3))
    for m, d in worse[:top]:
        z = f"z {_z(d):+.1f}, " if _z(d) is not None else ""
        look.append(WeekItem(kind="metric", metric=m.name, source=m.source,
                             text=f"{m.label.replace(' (later = up)', '')}: change from usual ({_side(m)}), "
                                  f"{z}{d.worse_days} of {d.scored_days} recent days."))
    if len(worse) > top:
        rest = ", ".join(m.label for m, _d in worse[top:top + 3]) + ("…" if len(worse) > top + 3 else "")
        look.append(WeekItem(kind="metric", text=f"{len(worse) - top} more metrics changed from usual: {rest}."))
    for r in r_list:
        if r.status == "slipped":
            look.append(WeekItem(kind="routine", source=ACTIVITIES[r.activity][2],  # type: ignore[arg-type]
                                 text=f"Fewer than usual: {r.label}, {r.this_week}/7 days (usual "
                                      f"{r.usual_per_week:.1f}/wk)." if r.activity != "sleep" else
                                 f"Shifted: {r.label} this week, away from the usual ~{r.usual_time}."))
    # Put specific improving measurements ahead of generic maintained-source/routine messages so the
    # bounded summary cannot hide the evidence a practitioner needs when comparing progress.
    for m, d in [md for md in drifts if md[1].status == "improved"][:2]:
        well.append(WeekItem(kind="metric", metric=m.name, source=m.source,
                             text=f"{m.label}: better than usual on {d.better_days} of {d.scored_days} recent days."))
    for v in c.sources:
        if v.verdict == "insufficient" and v.source in data.last_data_at:
            look.append(WeekItem(kind="source", source=v.source,
                                 text=f"{SOURCE_LABELS[v.source]}: not enough recent data (last "
                                      f"{local_date(data.last_data_at[v.source]):%d %b})."))
    if c.agreement == "disagree":
        look.append(WeekItem(kind="source", text="Sources disagree: check each source card before deciding."))
    every = settings.phq9_every_days
    if not data.phq9:
        look.append(WeekItem(kind="phq9", text="No PHQ-9 on record yet."))
    elif (age := (end - data.phq9[-1].day).days) >= every:
        look.append(WeekItem(kind="phq9", text=f"PHQ-9 due: last one {age} days ago (every {every})."))

    for v in c.sources:
        if v.verdict in ("as_usual", "better"):
            well.append(WeekItem(kind="source", source=v.source,
                                 text=f"{SOURCE_LABELS[v.source]}: {'better than usual' if v.verdict == 'better' else 'within the usual range'} "
                                      f"(confidence {v.confidence:.2f})."))
    for r in r_list:
        if r.status == "kept":
            well.append(WeekItem(kind="routine", source=ACTIVITIES[r.activity][2],  # type: ignore[arg-type]
                                 text=f"Kept: {r.label}, {r.this_week}/7 days (usual {r.usual_per_week:.1f}/wk)."
                                 if r.activity != "sleep" else f"Kept: {r.label} near the usual ~{r.usual_time}."))
    for h in _helped(helps):
        well.append(WeekItem(kind="helped", text=f"Best response: {h['label']}, mean effect {h['mean_effect']:.2f} "
                                                 f"over {h['tries']} tries (bandit)."))
    return well, look


# ------------------------------------------------------------------ the one record: what each source added
def _count(label: str, value: float) -> SourceCount | None:
    return SourceCount(label=label, value=round(value, 1)) if value else None


def source_week(events: list[dict[str, Any]], week_start: date, end: date) -> list[SourceWeek]:
    """Per consensus source: observations per day (7), days with data, a few plain counts. Numbers only."""
    from kaiku_contracts.sources import CONSENSUS_SOURCES, SOURCE_OF

    per: dict[str, list[int]] = {s: [0] * 7 for s in CONSENSUS_SOURCES}
    last: dict[str, datetime] = {}
    c: dict[str, float] = defaultdict(float)
    walk_days: set[date] = set()
    # Health summaries are revisable snapshots for a measured date, not additive nights/step readings.
    snapshots = {}
    for e in events:
        if e["type"] == "obs.wearable_daily":
            key = e["payload"].get("date") or str(local_date(e["ts"]))
            if key not in snapshots or parse_ts(e["ts"]) > parse_ts(snapshots[key]["ts"]):
                snapshots[key] = e
    effective = [e for e in events if e["type"] != "obs.wearable_daily"] + list(snapshots.values())
    for e in effective:
        src = "robot" if e["type"] == "obs.ritual" else SOURCE_OF.get(e["type"])  # the ritual happens on the robot
        if src not in per:
            continue
        ts = parse_ts(e["ts"])
        d = date.fromisoformat(e["payload"]["date"]) if e["type"] == "obs.wearable_daily" and e["payload"].get("date") else local_date(ts)
        if not week_start <= d <= end:
            continue
        per[src][(d - week_start).days] += 1
        if src not in last or ts > last[src]:
            last[src] = ts
        t, p = e["type"], e["payload"]
        if t == "obs.ritual" and p.get("step") == "close" and p.get("status") == "completed":
            c["rituals"] += 1
        elif t == "obs.drum_session":
            c["drum"] += 1
        elif t == "obs.hrv_session":
            c["breathe"] += 1
        elif t == "obs.speech_features":
            c["talks"] += 1
        elif t == "obs.outing":
            c["walks"] += 1
            c["walk_min"] += float(p.get("minutes") or 0)
            c["daylight"] += float(p.get("daylight_min") or 0)
            walk_days.add(d)
        elif t == "obs.play_session":
            c["games"] += 1
        elif t == "obs.face_signs":
            c["face"] += 1
        elif t == "obs.laptop_session":
            c["laptop"] += 1
        elif t == "obs.self_report" and p.get("channel") not in (None, "robot"):
            c["checks"] += 1
        elif t == "obs.screen_activity":
            c["screen_days"] += 0  # counted below as days
        elif t == "obs.wearable_daily":
            if p.get("sleep_min") is not None:
                c["nights"] += 1
            if p.get("steps") is not None:
                c["step_days"] += 1
                c["steps"] += float(p["steps"])
    screen_days = len({local_date(e["ts"]) for e in events if e["type"] == "obs.screen_activity"
                       and week_start <= local_date(e["ts"]) <= end})
    counts = {
        "robot": [_count("morning rituals", c["rituals"]), _count("drum sessions", c["drum"]),
                  _count("breathing rounds", c["breathe"]), _count("chats", c["talks"]), _count("weather checks", c["checks"])],
        "glasses": [_count("outings", c["walks"]), _count("outing minutes", c["walk_min"]),
                    _count("minutes of daylight", c["daylight"])],
        "laptop": [_count("games", c["games"]), _count("laptop check-ins", c["laptop"]),
                   _count("days of Mac rhythm", screen_days), _count("camera readings during tasks", c["face"])],
        "wearable": [_count("nights of sleep", c["nights"]),
                     _count("steps a day", c["steps"] / c["step_days"] if c["step_days"] else 0)],
    }
    return [SourceWeek(source=s, per_day=per[s], days=sum(1 for v in per[s] if v),  # type: ignore[arg-type]
                       counts=[x for x in counts.get(s, []) if x], last_at=last.get(s)) for s in per]


# ------------------------------------------------------------------ suggested next steps (care team, by rule)
CARE_HELP = {"walk": "walks", "breathe": "guided breathing", "drum": "drumming",
             "friend_ping": "lighting a friend's lamp", "icbt": "iCBT exercises"}


def next_steps(c: Consensus, r_list: list[Routine], helps: list[dict[str, Any]], drifts: list[tuple[Any, Any]],
               data: Any, settings: Settings, week_start: date, end: date) -> list[NextStep]:
    steps: list[NextStep] = []
    if any(week_start <= local_date(ts) <= end for ts in data.safety_flags) or c.state == "safety":
        steps.append(NextStep(when="today", text="Call today.",
                              why="A safety flag was raised; the person was shown the crisis numbers on their device."))
    worse = [m.label.lower() for m, d in sorted(drifts, key=lambda md: -(_z(md[1]) or 0)) if d.status == "drifting"]
    about = " and ".join(worse[:2])
    if c.state == "needs_call":
        steps.append(NextStep(when="this_week", text="Worth a check-in call this week.",
                              why=f"Several sources show a change from the usual{f', mostly {about}' if about else ''}."))
    elif c.state == "watch":
        steps.append(NextStep(when="next_contact", text="Worth a check-in at the next contact.",
                              why="One source shows a change from the usual; nothing needs a call yet."
                              if c.agreement != "low_coverage" else "Too little recent data to say more."))
    # Care-process steps only: what to ask about or look at. Treatment choices are never suggested by code.
    flagged = [m for m, d in sorted(drifts, key=lambda md: -(_z(md[1]) or 0)) if d.status == "drifting"]
    sleep = [m.label.lower() for m in flagged if "sleep" in m.name]
    if sleep:
        steps.append(NextStep(when="next_contact" if c.state != "needs_call" else "this_week",
                              text="Ask about sleep and evenings.",
                              why=f"Change from the usual in {' and '.join(sleep[:2])}."))
    if c.state == "needs_call":
        steps.append(NextStep(when="this_week", action="send_message", text="Send a short message before the call.",
                              why="So the person expects the call; it is shown on their own device."))
    every = settings.phq9_every_days
    if not data.phq9 or (end - data.phq9[-1].day).days >= every:
        steps.append(NextStep(when="next_contact", text="Ask for a PHQ-9.",
                              why="None on record yet." if not data.phq9 else
                              f"The last one was {(end - data.phq9[-1].day).days} days ago (every {every})."))
    for r in r_list:
        if r.status == "slipped" and r.activity != "sleep":
            steps.append(NextStep(when="next_contact", text=f"Ask how {r.label.lower()} have been going.",
                                  why=f"{r.this_week}/7 days this week, usually {r.usual_per_week:.1f} a week."))
            break
    best = _helped(helps)
    if best and c.state != "stable":
        h = best[0]
        steps.append(NextStep(when="next_contact",
                              text=f"Ask whether {CARE_HELP.get(h['activity'], h['label'].lower())} still feel worth doing.",
                              why=f"The best response so far ({h['tries']} tries, mean effect {h['mean_effect']:.2f})."))
    if c.agreement == "disagree":
        same = [SOURCE_LABELS[v.source].lower() for v in c.sources if v.verdict == "as_usual"]
        if same:
            steps.append(NextStep(when="next_contact", text="Look at the source cards before deciding.",
                                  why=f"Still as usual: {', '.join(same)}."))
    if not steps:
        steps.append(NextStep(when="next_contact", text="No action needed this week.",
                              why="Everything looks like this person's usual."))
    return steps[:6]


def week(store: Store, settings: Settings, home_id: str, audience: str, now: datetime | None = None) -> WeekSummary:
    now = now or datetime.now(UTC)
    today = now.astimezone(TZ).date()
    events = store.events_for_home(home_id)
    end = week_end(events, today)
    week_start = end - timedelta(days=6)
    shared = sharing(store, home_id).share_with_care_team
    with_eps = audience == "person" or shared
    eps = store.episodes(home_id, (now - timedelta(days=7 * (int(cfg("usual_weeks", 3)) + 2))).isoformat()) \
        if with_eps else []
    occ = occurrences(events, eps)
    basis: dict[str, set[str]] = defaultdict(set)
    for k in occurrences(events, None):
        basis[k].add("obs")
    for k in occurrences([], eps):
        basis[k].add("episodes")
    r_list = routines(occ, end, audience, basis, min((local_date(e["ts"]) for e in events), default=None))
    occ_week = {k: len({_day_of(k, t) for t in v if week_start <= _day_of(k, t) <= end}) for k, v in occ.items()}
    crit = service.active_criteria(store)
    data = service.patient_data(store, home_id, crit)
    helps = bandit.help_stats(data.nudge_outcomes, data.interventions)
    # the week view speaks of what the rule reads: a metric that is shown and not scored (camera face signs, D52)
    # is in Trends, the course and the review, and is never a reason given here
    drifts = [(m, drift_for(m, data.series.get(m.name, {}), end, crit)) for m in crit.metrics
              if m.enabled and m.role == "scored" and data.series.get(m.name)]
    rule_version = None
    steps: list[NextStep] = []
    if audience == "person":
        hl = companion.highlights_for(events, data, crit, end)
        good = sum(1 for h in hl if h.kind == "good" and h.date >= week_start)
        hard: list[tuple[str, str, str]] = []
        for m, d in drifts:
            if d.status == "drifting" and m.person_hard and m.person_hard not in {h[1] for h in hard}:
                hard.append((m.name, m.person_hard, m.source))
        well, look = _person_week(r_list, helps, occ_week, good, hard)
    else:
        row = store.home_summary(home_id) or service.recompute_home(store, settings, home_id)
        c = Consensus.model_validate(row["consensus"])
        rule_version = c.rule_version
        well, look = _care_week(r_list, helps, c, drifts, data, settings, week_start, end)
        steps = next_steps(c, r_list, helps, drifts, data, settings, week_start, end)
    cap = int(cfg("max_items", 6))
    return WeekSummary(home_id=home_id, audience=audience, week_start=week_start, week_end=end, routines=r_list,  # type: ignore[arg-type]
                       going_well=well[:cap], worth_a_look=look[:cap], shared=shared, rule_version=rule_version,
                       sources=source_week(events, week_start, end), next_steps=steps,
                       computed_at=now)


# ------------------------------------------------------------------ knowledge graph view
def graph(store: Store, settings: Settings, home_id: str, audience: str, now: datetime | None = None
          ) -> KnowledgeGraph:
    now = now or datetime.now(UTC)
    shared = sharing(store, home_id).share_with_care_team
    if audience == "care_team" and not shared:
        return KnowledgeGraph(home_id=home_id, audience="care_team", shared=False, nodes=[], edges=[], computed_at=now)
    mind_graph.rebuild(store, home_id, now)
    kg_nodes = [n for n in store.kg_nodes(home_id) if n["status"] == "active"
                and n["type"] in mind_graph.CONSTELLATION_TYPES]
    ids = {n["id"] for n in kg_nodes}
    kg_edges = [e for e in store.kg_edges(home_id) if e["src"] in ids and e["dst"] in ids]

    since = now - timedelta(days=mind_graph.EPISODE_DAYS)
    eps = store.episodes(home_id, since.isoformat())
    ep_count: dict[str, int] = defaultdict(int)
    for e in eps:
        if e["outcome"] == "completed" and e["intent"] in mind_graph.INTENT_ACTIVITY:
            ep_count[mind_graph.INTENT_ACTIVITY[e["intent"]]] += 1
    data = service.patient_data(store, home_id, service.active_criteria(store)) if home_id in store.home_ids() \
        else None
    helps = {h["activity"]: h for h in (bandit.help_stats(data.nudge_outcomes, data.interventions) if data else [])}

    nodes: dict[int, dict[str, Any]] = {n["id"]: {"id": n["id"], "type": n["type"], "label": n["label"],
                                                  "norm": n["norm"], "detail": None} for n in kg_nodes}
    edges: list[dict[str, Any]] = []
    for e in kg_edges:
        dst = nodes[e["dst"]]
        if e["rel"] == "did":
            ev = ep_count.get(dst["norm"], len(e["evidence"]))
        elif e["rel"] == "helped":
            ev = int(helps.get(dst["norm"], {}).get("tries") or len(e["evidence"]))
        else:
            ev = len(e["evidence"])
        edges.append({"src": e["src"], "dst": e["dst"], "rel": e["rel"], "weight": e["weight"], "evidence": ev})
    me = next((n for n in nodes.values() if n["type"] == "me"), None)
    if me is None:
        return KnowledgeGraph(home_id=home_id, audience=audience, shared=shared, nodes=[], edges=[],  # type: ignore[arg-type]
                              computed_at=now)
    if audience == "care_team":
        me["label"] = service.display_name(home_id)
    # obs-derived activities (35 days) + routines
    all_events = store.events_for_home(home_id)
    events = [e for e in all_events if parse_ts(e["ts"]) >= since]
    occ_obs = occurrences(events, None)
    by_norm = {n["norm"]: n for n in nodes.values() if n["type"] == "activity"}
    vid = [0]

    def virtual() -> int:
        vid[0] -= 1
        return vid[0]

    def activity_node(key: str) -> dict[str, Any] | None:
        if key == "sleep":
            return None
        if key not in by_norm:
            label = mind_graph.ACTIVITY_LABEL.get(key) or GRAPH_LABEL.get(key, key)
            n = {"id": virtual(), "type": "activity", "label": label, "norm": key, "detail": None}
            nodes[n["id"]] = n
            by_norm[key] = n
        return by_norm[key]

    obs_days: dict[str, int] = {}
    for key, stamps in occ_obs.items():
        n = activity_node(key)
        if n is None:
            continue
        days = len({_day_of(key, t) for t in stamps})
        obs_days[key] = days
        did = next((e for e in edges if e["rel"] == "did" and e["dst"] == n["id"]), None)
        if did:
            did["evidence"] += days
            did["weight"] = round(max(did["weight"], min(1.0, days / mind_graph.EPISODE_DAYS)), 3)
        else:
            edges.append({"src": me["id"], "dst": n["id"], "rel": "did",
                          "weight": round(min(1.0, days / mind_graph.EPISODE_DAYS), 3), "evidence": days})
    with_eps = audience == "person" or shared
    today = now.astimezone(TZ).date()
    observed = occurrences(all_events, eps if with_eps else None)
    end = week_end(all_events, today)
    r_list = routines(observed, end, audience,
                      collection_start=min((local_date(e["ts"]) for e in all_events), default=None))
    for r in r_list:
        cad = {"daily": "daily", "most_days": "most days"}.get(r.cadence) or f"{r.weekday}s"
        rid = virtual()
        nodes[rid] = {"id": rid, "type": "routine", "norm": f"routine:{r.activity}", "detail": f"{r.label}: {r.text}",
                      "label": (f"asleep around {r.usual_time}" if r.activity == "sleep" else f"{cad} · {r.usual_time}")}
        expected = 1.0 if r.cadence == "weekly" else max(r.usual_per_week, 1.0)
        edges.append({"src": me["id"], "dst": rid, "rel": "keeps", "weight": round(min(1.0, r.this_week / expected), 3),
                      "evidence": len({_day_of(r.activity, ts) for ts in observed[r.activity]
                                       if end - timedelta(days=7 * (int(cfg("usual_weeks", 3)) + 1) - 1)
                                       <= _day_of(r.activity, ts) <= end})})
        a = activity_node(r.activity)
        if a is not None:
            edges.append({"src": rid, "dst": a["id"], "rel": "of", "weight": 1.0, "evidence": r.this_week})
    # details
    for n in nodes.values():
        if n["type"] == "activity":
            k = n["norm"]
            parts = []
            if obs_days.get(k):
                parts.append(f"on {obs_days[k]} days in the last 5 weeks")
            if ep_count.get(k):
                parts.append(f"{ep_count[k]} conversation{'s' if ep_count[k] != 1 else ''} about it")
            h = helps.get(k)
            if h and h["mean_effect"] is not None and h["mean_effect"] > 0.5:
                parts.append(f"helped on average ({h['mean_effect']:.2f} over {h['tries']} tries)"
                             if audience == "care_team" else "it seems to help you")
            n["detail"] = ("Seen " + "; ".join(parts) + ".") if parts else None
        elif n["type"] == "me":
            n["detail"] = "What Kaiku has learned, from what you told it and what you did." if audience == "person" \
                else "Shared by the person. Activities, what helps and routines only."
        elif n["type"] in mind_graph.CONSTELLATION_TYPES and n["detail"] is None:
            n["detail"] = "You told Kaiku this." if audience == "person" else "The person told Kaiku this."
    withheld: set[str] = set()
    if audience == "care_team":
        withheld = {n["type"] for n in nodes.values() if n["type"] not in CARE_TYPES}
        nodes = {i: n for i, n in nodes.items() if n["type"] in CARE_TYPES}
        edges = [e for e in edges if e["src"] in nodes and e["dst"] in nodes]
    ev_by_node: dict[int, int] = defaultdict(int)
    for e in edges:
        ev_by_node[e["dst"]] += e["evidence"]
        if e["rel"] != "of":
            ev_by_node[e["src"]] += e["evidence"]
    keep = {me["id"]} | {e["dst"] for e in edges} | {e["src"] for e in edges}
    return KnowledgeGraph(
        home_id=home_id, audience=audience, shared=shared,  # type: ignore[arg-type]
        nodes=[GraphNode(id=n["id"], type=n["type"], label=n["label"][:120], evidence=ev_by_node.get(n["id"], 0),
                         detail=(n["detail"] or None) and n["detail"][:200]) for n in nodes.values() if n["id"] in keep],
        edges=[GraphEdge(**e) for e in edges], withheld=sorted(withheld), computed_at=now)  # type: ignore[arg-type]

