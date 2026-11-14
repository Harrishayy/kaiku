"""The context card (plan 03 §3.3): a small deterministic summary of today for the model.

Never the consensus state, scores, numbers or watch data. The only consensus-derived field is `tone`:
stable -> steady · watch -> gentle · needs_call / safety -> extra-gentle · not enough data (no row yet, or
`low_coverage`) -> steady (missing data never makes anyone look worse).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from kaiku_contracts.api import ContextCard

from .. import service
from ..companion import time_of_day
from ..settings import TZ, Settings
from ..store.db import Store
from . import graph, memory

TONE_OF_STATE = {"stable": "steady", "watch": "gentle", "needs_call": "extra-gentle", "safety": "extra-gentle"}
SUGGESTION = {"breathe": "a few slow breaths together", "drum": "a short drum jam with the robot",
              "daylight_walk": "a short walk in daylight", "friend_ping": "lighting a friend's lamp",
              "icbt_exercise": "one small exercise from the care team's programme"}
WHERE = {"hub": "with the robot", "head": "with the robot", "sensors": "with the robot", "phone": "on the phone",
         "glasses": "on the glasses", "laptop": "on the computer"}
SURFACE_WHERE = {"robot": "with the robot", "iphone": "on the phone", "glasses": "on the glasses",
                 "mac": "on the computer", "web": "on the computer"}
GAME = {"firefly": "the firefly game", "breathe": "breathing", "tell": "telling Kaiku about the day",
        "pebbles": "the pebbles game"}
EPISODE_TEXT = {"walk": "a walk", "ritual": "the morning ritual", "checkin": "a weather check",
                "breathe": "breathing together", "break": "a short break", "talk": "a chat"}
MAX_DONE = 4


def tone_for(row: dict[str, Any] | None) -> str:
    summary = (row or {}).get("summary") or {}
    if not summary or summary.get("agreement") == "low_coverage":
        return "steady"
    return TONE_OF_STATE.get(summary.get("state", ""), "steady")


def done_today(events: list[dict[str, Any]], episodes: list[dict[str, Any]], now: datetime) -> list[str]:
    """What they already did today, on any surface — words only, no numbers."""
    today = now.astimezone(TZ).date()
    out: list[str] = []

    def add(text: str) -> None:
        if text not in out:
            out.append(text)

    for e in events:
        if datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).astimezone(TZ).date() != today:
            continue
        t, p, where = e["type"], e["payload"], WHERE.get(e["source"], "")
        if t == "obs.ritual" and p.get("step") == "close" and p.get("status") == "completed":
            add("the morning ritual with the robot")
        elif t == "obs.self_report" and p.get("channel", "robot") != "robot":
            add(f"a weather check {where}".strip())
        elif t == "obs.outing":
            add(f"a walk {where}".strip() if e["source"] == "glasses" else "a walk")
        elif t == "obs.play_session" and p.get("game") in GAME:
            add(f"{GAME[p['game']]} {where}".strip())
        elif t == "obs.drum_session":
            add("drumming with the robot")
        elif t == "obs.friend_link" and p.get("direction") == "sent":
            add("lit a friend's lamp")
    for ep in episodes:
        if ep["outcome"] == "completed" and datetime.fromisoformat(ep["start"]).astimezone(TZ).date() == today:
            add(f"{EPISODE_TEXT.get(ep['intent'], 'a chat')} {SURFACE_WHERE.get(ep['surface'], '')}".strip())
    return out[:MAX_DONE]


def build_card(store: Store, settings: Settings, home_id: str, *, intent: str = "talk", language: str | None = None,
               others_present: bool = False, now: datetime | None = None) -> ContextCard:
    now = now or datetime.now(UTC)
    local = now.astimezone(TZ)
    known = home_id in store.home_ids()
    row = store.home_summary(home_id) if known else None
    if known and row is None:
        row = service.recompute_home(store, settings, home_id)
    crit = service.active_criteria(store)
    data = service.patient_data(store, home_id, crit)
    events = store.events_for_home(home_id) if known else []
    keep = memory.remembering(store, home_id) and not others_present
    mems = graph.card_memories(store, home_id, intent, now) if keep else []
    thread = memory.current_thread(store, home_id, now)
    arm = service.nudge(store, settings, home_id).arm
    lang = language or str(settings_language())
    card = ContextCard(
        language=lang if lang in ("en", "fi", "sv") else "en", intent=intent, time_of_day=time_of_day(local.hour),
        first_name=memory.first_name(store, home_id),
        done_today=done_today(events, store.episodes(home_id), now),
        suggestion=SUGGESTION.get(arm), phq9_due=service.phq9_due(data, settings.phq9_every_days, local.date()),
        memories=[m["text"] for m in mems], routines=memory.routines(store, home_id, now, TZ),
        open_thread=thread["topic"] if thread and not others_present else None,
        tone=tone_for(row), others_present=others_present, dont_remember=not memory.remembering(store, home_id))
    if known and not others_present:
        from . import reflect

        d = card.model_dump(mode="json")
        card.focus = reflect.focus_line(reflect.plan(store, home_id, d, now=now, use_model=False), d)
    return card


def settings_language() -> str:
    from kaiku_contracts.config import load_config

    return str(load_config().get("home", {}).get("language", "en"))


def card_dict(card: ContextCard) -> dict[str, Any]:
    """The keys render_card expects (empty/None/False dropped; tone and language always present)."""
    d = card.model_dump(mode="json")
    return {k: v for k, v in d.items() if k in ("tone", "language") or v not in (None, [], False, "")}
