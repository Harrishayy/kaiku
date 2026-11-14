"""The invitation: at most one thing a day that Kaiku would like to bring up or offer (GET /v1/me/invitation).

Chosen by code, never by a model:
1. talk_about: the open thread, i.e. something the person said on any surface that was left open (a `feel`
   follow-up, a follow-up from `end_session`, a thread an episode left). Allowed on every day.
2. activity: the suggestion with the best recorded response for this person (service.best_response: posterior
   mean, no sampling) when this device has a screen for it, else the game they have come back to most. Never one
   they already did today, and never on an extra-gentle day.
The sentence is a template from config/voice_lines.toml (`invite.*`) around the person's own stored topic.
One invitation per local day: the first read picks and pins it, later reads return the same one until it is
answered, and after an answer there is none until tomorrow. An answered item never comes back: a not-now is final,
and a yes was taken up.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from kaiku_contracts.api import Invitation

from .. import service, voice
from ..analytics.metrics import parse_ts
from ..settings import TZ
from ..store.db import Store
from . import assemble, memory
from .card import GAME, tone_for
from .feel import ARM_ACTIVITY, FOLLOW

GOOD, HARD = "their good news: ", "something hard: "
assert {GOOD, HARD} == set(FOLLOW.values())
ANSWERED_KEPT = 50
MIN_PLAYS = 2  # a game counts as theirs once they have come back to it
_OWN = re.compile(r"^(?:her|his|their|my)\b", re.I)
_SUBJECT = re.compile(r"^(?:she|he|they|i) (?:got|has|have|had) ", re.I)
_THIRD = re.compile(r"^(?:she|he|they)\b", re.I)  # still about "her": cannot be said to them as it stands


def _key(home_id: str) -> str:
    return f"invite:{home_id}"


def to_them(topic: str) -> str:
    """A stored topic as it reads when said to the person: "her sister's visit" -> "your sister's visit"."""
    topic = _SUBJECT.sub("", topic.strip())
    return _OWN.sub("your", topic)


def _line(key: str, **words: str) -> str:
    return voice.all_lines()[key]["en"].format(**words)  # this release speaks English only


def _talk(thread: dict[str, Any], today: Any) -> Invitation:
    topic = thread["topic"]
    key = "invite.talk.good" if topic.startswith(GOOD) else "invite.talk.hard" if topic.startswith(HARD) else "invite.talk.open"
    said = to_them(topic.removeprefix(GOOD).removeprefix(HARD))
    if _THIRD.match(said):
        key = "invite.talk.plain"  # the sentence without the topic rather than a wrong one; `topic` still carries it
    days = (today - parse_ts(thread["created"]).astimezone(TZ).date()).days
    when = " earlier today" if days <= 0 else " yesterday" if days == 1 else " the other day"
    return Invitation(id=f"thread:{thread['id']}", kind="talk_about", text=_line(key, topic=said, when=when)[:200],
                      voice_key=key, topic=said)


def _played(store: Store, home_id: str, today: Any) -> tuple[Counter, set[str]]:
    """How often each game was played, and everything already done today (games, a walk, breathing)."""
    count: Counter = Counter()
    done: set[str] = set()
    for e in store.events_for_home(home_id):
        if e["type"] == "obs.play_session":
            count[e["payload"].get("game")] += 1
            if parse_ts(e["ts"]).astimezone(TZ).date() == today:
                done.add(e["payload"].get("game"))
    for ep in store.episodes(home_id):
        if ep["outcome"] == "completed" and parse_ts(ep["start"]).astimezone(TZ).date() == today:
            done.add(ep["intent"])
    return count, done


def _activity(store: Store, home_id: str, surface: str, today: Any, declined: list[str]) -> Invitation | None:
    can = assemble.surface_activities(surface)
    data = service.patient_data(store, home_id, service.active_criteria(store))
    count, done = _played(store, home_id, today)
    best = service.best_response(data, service.nudge_arms(store, home_id))  # posterior mean, no sampling
    kinds = [ARM_ACTIVITY.get(best["arm"]) if best else None]
    kinds += [g for g, n in sorted(count.items(), key=lambda kv: (-kv[1], str(kv[0]))) if n >= MIN_PLAYS]
    for kind in kinds:
        ident = f"activity:{kind}:{today.isoformat()}"
        if not kind or kind not in can or kind in done or ident in declined:
            continue
        key = f"invite.activity.{kind}" if f"invite.activity.{kind}" in voice.all_lines() else "invite.activity.game"
        return Invitation(id=ident, kind="activity", text=_line(key, game=GAME.get(kind, kind))[:200],
                          voice_key=key, activity=kind)  # type: ignore[arg-type]
    return None


def select(store: Store, home_id: str, surface: str, now: datetime, declined: list[str]) -> Invitation | None:
    today = now.astimezone(TZ).date()
    thread = memory.current_thread(store, home_id, now) if memory.remembering(store, home_id) else None
    if thread and f"thread:{thread['id']}" not in declined:
        return _talk(thread, today)
    if home_id not in store.home_ids() or tone_for(store.home_summary(home_id)) == "extra-gentle":
        return None  # an extra-gentle day gets no offers; talking about something of theirs is the exception above
    return _activity(store, home_id, surface, today, declined)


def current(store: Store, home_id: str, surface: str = "iphone", now: datetime | None = None) -> Invitation | None:
    now = now or datetime.now(UTC)
    today = now.astimezone(TZ).date().isoformat()
    state = store.kv_get(_key(home_id)) or {}
    if state.get("day") == today:
        if state.get("answer") or not state.get("item"):
            return None
        item = Invitation.model_validate(state["item"])
        thread = memory.current_thread(store, home_id, now) if memory.remembering(store, home_id) else None
        if item.kind == "talk_about" and (not thread or f"thread:{thread['id']}" != item.id):
            return None  # it was talked about (or forgotten) since: nothing else today
        return item
    item = select(store, home_id, surface, now, state.get("declined", []))
    if item:  # a day with nothing to offer is not used up: something may come up later
        store.kv_set(_key(home_id), {"day": today, "item": item.model_dump(mode="json"), "answer": None,
                                     "declined": state.get("declined", [])})
    return item


def answer(store: Store, home_id: str, ident: str, reply: str, now: datetime | None = None) -> None:
    """yes: the device opens it. not_now: final. Either way that item never returns and there is no other today."""
    now = now or datetime.now(UTC)
    state = store.kv_get(_key(home_id)) or {}
    if (state.get("item") or {}).get("id") != ident or state.get("day") != now.astimezone(TZ).date().isoformat():
        raise KeyError(ident)
    store.kv_set(_key(home_id), {**state, "answer": reply, "declined": [*state.get("declined", []), ident][-ANSWERED_KEPT:]})
