"""The context card (plan 03 §3.3): a small deterministic summary of today for the model.

Never the consensus state, scores, numbers or watch data. The only consensus-derived field is `tone`:
stable -> steady · watch -> gentle · needs_call / safety -> extra-gentle · not enough data (no row yet, or
`low_coverage`) -> steady (missing data never makes anyone look worse). A talk that sounded low (mind/affect.py)
also makes a steady day gentle: that comes from their own conversation, not from the consensus. So does a face
that was clearly quieter than their own usual in today's games or check-in (mind/face_cue.py, D52): the card then
carries which kind of task as an enum (`quieter_in`), never a number and never a word about how they looked.

When the device names a `purpose`, the card also shapes the chat: `chat_depth` (brief: a passing chat; stay: the
last talk was hard or it has been a heavy few days) and, for a check-in, `open_items`: the dials not answered
today, of which at most one is woven into the conversation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from kaiku_contracts.api import ContextCard, LastReflection
from kaiku_contracts.companion_tools import CHECKIN_ITEMS

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
        "pebbles": "the pebbles game", "lantern": "the lantern game", "seeds": "the seed shelf game",
        "watering": "the watering game"}
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


def today_facts(events: list[dict[str, Any]], now: datetime) -> list[str]:
    """Plain facts from what the person recorded themselves today. Their own ratings in everyday words: never a
    number, never a judgement, never watch data."""
    today = now.astimezone(TZ).date()
    mine = [e for e in events if datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).astimezone(TZ).date() == today]
    facts: list[str] = []
    night = [e["payload"]["value"] for e in mine if e["type"] == "obs.self_report" and e["payload"].get("item") == "sleep"]
    if night:
        facts.append("a short night" if night[-1] <= 2 else "a good night" if night[-1] >= 4 else "an ordinary night")
    days = sorted({datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).astimezone(TZ).date() for e in events})
    if mine and len(days) >= 2 and (today - days[-2]).days >= 3:
        facts.append(f"back after {(today - days[-2]).days - 1} quiet days")
    return facts[:4]


def open_items(events: list[dict[str, Any]], now: datetime) -> list[str]:
    """Check-in dials with no answer yet today, on any device. Last night's sleep first in the morning."""
    today = now.astimezone(TZ).date()
    answered = {e["payload"].get("item") for e in events if e["type"] == "obs.self_report"
                and datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).astimezone(TZ).date() == today}
    order = ("sleep", "mood", "energy") if now.astimezone(TZ).hour < 12 else ("mood", "energy", "sleep")
    return [i for i in order if i in CHECKIN_ITEMS and i not in answered]


def build_card(store: Store, settings: Settings, home_id: str, *, intent: str = "talk", language: str | None = None,
               others_present: bool = False, now: datetime | None = None, purpose: str | None = None,
               walk_style: str | None = None) -> ContextCard:
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
    arm = service.suggest(store, home_id, data, now).arm  # after a low talk: the best recorded one, not a draw
    # This release is English-only, including requests from clients with a previously saved locale.
    lang = "en"
    from .router import source_facts

    prepared_sources = {} if others_present else {f["id"].split("-")[1]: f["text"]
                                                   for f in source_facts(store, home_id, now)}
    card = ContextCard(
        language=lang if lang in ("en", "fi", "sv") else "en", intent=intent, time_of_day=time_of_day(local.hour),
        first_name=memory.first_name(store, home_id),
        done_today=done_today(events, store.episodes(home_id), now),
        source_context=list(prepared_sources.values())[:4],
        suggestion=SUGGESTION.get(arm),
        # not in a check-in: it is a passing chat, and the device refuses start_phq9 there
        phq9_due=purpose != "check_in" and service.phq9_due(data, settings.phq9_every_days, local.date()),
        memories=[m["text"] for m in mems], routines=memory.routines(store, home_id, now, TZ),
        open_thread=thread["topic"] if thread and not others_present else None,
        tone=tone_for(row), others_present=others_present, dont_remember=not memory.remembering(store, home_id))
    if known and not others_present:
        from . import reflect

        d = card.model_dump(mode="json")
        card.focus = reflect.focus_line(reflect.plan(store, home_id, d, now=now, use_model=False), d)
        from . import affect

        card.recent_reflection = affect.card_line(store, home_id, now)
        last = affect.latest(store, home_id, now)
        card.last_reflection = LastReflection(**last) if last else None
        card.today_facts = today_facts(events, now)
        hard = affect.last_was_low(store, home_id, now)
        if hard and card.tone == "steady":
            card.tone = "gentle"
        from . import face_cue

        card.quieter_in = face_cue.today(crit, data, events, now)  # type: ignore[assignment]
        if card.quieter_in and card.tone == "steady":
            card.tone = "gentle"
        if purpose in ("check_in", "talk"):
            from .feel import HEAVY_DAYS

            card.chat_depth = "stay" if hard or affect.heavy_days(store, home_id, now) >= HEAVY_DAYS else "brief"
        if purpose == "check_in":
            card.open_items = open_items(events, now)  # type: ignore[assignment]
    if walk_style:
        from . import walk

        card.walk_style = walk_style  # type: ignore[assignment]
        card.outdoor_likes = walk.outdoor_likes(store, home_id) if keep else []
    if purpose:
        card.purpose = purpose  # type: ignore[assignment]
        if purpose in ("check_in", "talk") and card.chat_depth is None:
            card.chat_depth = "brief"
    return card


def settings_language() -> str:
    from kaiku_contracts.config import load_config

    return str(load_config().get("home", {}).get("language", "en"))


def card_dict(card: ContextCard) -> dict[str, Any]:
    """The keys render_card expects (empty/None/False dropped; tone and language always present)."""
    d = card.model_dump(mode="json")
    return {k: v for k, v in d.items() if k in ("tone", "language") or v not in (None, [], False, "")}
