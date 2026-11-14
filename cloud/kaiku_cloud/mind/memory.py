"""Kaiku's notebook (plan 03 §6, plan 04 scope guard): memories, recall, routines, open thread. Deterministic rules.

Rules (each is a test in cloud/tests/test_mind.py):
- Only the categories in `kaiku_contracts.companion_tools.MEMORY_CATEGORIES`; anything else is rejected.
- Health details are never kept: a text the wording linter flags (clinical / state / medical / watch data) or that
  names medication, treatment, therapy, hospital ... is rejected.
- "don't remember that" (as a forget call, or as the text of a remember call) deletes the newest memory.
- The person can turn remembering off ("don't remember things" or `PUT /v1/me/memory_settings`): no more writes.
- Same fact twice (case / whitespace / trailing punctuation) -> one memory.
- `plans` expire after PLAN_DAYS days. Recall = FTS5 + recency, no embeddings.
- Routines: >= ROUTINE_MIN completed sessions of one intent on the same weekday in ROUTINE_WINDOW_DAYS.
- Clinicians never see any of this (no clinician route reads these tables).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from kaiku_contracts import wording
from kaiku_contracts.companion_tools import MEMORY_CATEGORIES, SKILL_OF_INTENT

from ..store.db import Store

PLAN_DAYS = 7
THREAD_DAYS = 3
ROUTINE_MIN = 3
ROUTINE_WINDOW_DAYS = 35
MAX_TEXT = 200
CARD_MEMORIES = 3

FORGET_LAST = re.compile(
    r"(?<!\w)(?:do not|don't|dont) (?:remember|keep|save) (?:that|this|it)|(?<!\w)forget (?:that|this|it)(?!\w)|"
    r"älä muista (?:sitä|tätä|tuota)|unohda (?:se|tuo|tämä)|kom inte ihåg det|glöm det")
REMEMBER_OFF = re.compile(
    r"(?<!\w)(?:do not|don't|dont) (?:remember|keep|save) (?:anything|things)|stop remembering|remember_off|"
    r"älä muista mitään|kom inte ihåg något")
HEALTH = re.compile(
    r"(?<!\w)(?:medic|meds(?!\w)|pill|tablet|antidepress|dose|dosage|tms(?!\w)|ect(?!\w)|treatment|therap|"
    r"hospital|psychiatr|diagnos|symptom|illness|sick(?!\w)|suicid|self[- ]harm|sleep|slept|heart rate|pulse|hrv|"
    r"lääk|hoito|sairaala|terapi|masenn|nukuin|syke|medicin|behandling|sjukhus|sömn|sov(?!\w))")
HEALTH_CODES = {"clinical_term", "state_talk", "medical_advice", "wearable_data"}
WEEKDAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
ROUTINE_VERB = {"walk": "walks", "ritual": "does the morning ritual", "checkin": "does the weather check",
                "breathe": "breathes with Kaiku", "break": "takes a short break with Kaiku"}
INTENT_TERMS = {"walk": ["walk", "outside", "lake", "park", "forest", "path", "green", "dog"],
                "ritual": ["morning", "coffee", "tea", "drum", "breakfast"],
                "breathe": ["breathe", "breath", "calm", "slow"], "break": ["break", "stretch", "tea", "coffee"],
                "checkin": [], "talk": []}


class MemoryRefused(ValueError):
    """A memory write that the rules refuse (reason is person-safe, no text echoed)."""


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).casefold()
    t = re.sub(r"\s+", " ", t).strip()
    return t.rstrip(" .!?,;:…")


def is_forget(text: str) -> bool:
    return bool(FORGET_LAST.search(norm(text)))


def is_remember_off(text: str) -> bool:
    return bool(REMEMBER_OFF.search(norm(text)))


def health_detail(text: str) -> bool:
    return bool(HEALTH.search(norm(text))) or bool(wording.codes(wording.lint(text, max_questions=None)) & HEALTH_CODES)


_WORD = re.compile(r"[^\W\d_]{3,}")
_FILLER = {"the", "and", "her", "his", "their", "she", "has", "have", "that", "with", "for", "likes", "like", "name",
           "named", "called", "person", "wants", "want", "said", "says", "going", "will", "every", "this", "are", "was"}


def grounded(text: str, said: str | None) -> bool:
    """True when at least half of the fact's content words occur in what the person said (same word stem)."""
    if not said or not said.strip():
        return False
    stems = {w[:5] for w in _WORD.findall(norm(said))}
    words = [w for w in _WORD.findall(norm(text)) if w not in _FILLER]
    if not words:
        return False
    return sum(w[:5] in stems for w in words) * 2 >= len(words)


# ------------------------------------------------------------------ settings
def _off_key(home_id: str) -> str:
    return f"remember_off:{home_id}"


def remembering(store: Store, home_id: str) -> bool:
    return not store.kv_get(_off_key(home_id))


def set_remembering(store: Store, home_id: str, on: bool) -> None:
    if on:
        store.kv_delete(_off_key(home_id))
    else:
        store.kv_set(_off_key(home_id), True)


# ------------------------------------------------------------------ write / delete
def remember(store: Store, home_id: str, category: str, text: str, now: datetime | None = None) -> dict[str, Any]:
    """Apply the rules and store. Returns {action: stored|duplicate|forgot|remember_off, id?}. Raises MemoryRefused."""
    now = now or datetime.now(UTC)
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if is_forget(text):  # "don't remember that" sent as a remember call: obey it
        gone = store.memory_delete_last(home_id)
        return {"action": "forgot", "id": gone["id"] if gone else None}
    if is_remember_off(text):
        set_remembering(store, home_id, False)
        return {"action": "remember_off"}
    if not remembering(store, home_id):
        raise MemoryRefused("remembering is turned off")
    if category not in MEMORY_CATEGORIES:
        raise MemoryRefused(f"category {category!r} is not kept")
    if not text:
        raise MemoryRefused("empty")
    if len(text) > MAX_TEXT:
        raise MemoryRefused("too long")
    if health_detail(text):
        raise MemoryRefused("health details are not kept")
    mid, new = store.memory_insert(home_id, category, text, norm(text), iso(now))
    return {"action": "stored" if new else "duplicate", "id": mid}


def forget(store: Store, home_id: str, scope: str) -> dict[str, Any]:
    if scope == "all":
        return {"action": "forgot_all", "deleted": store.memory_delete(home_id)}
    gone = store.memory_delete_last(home_id)
    return {"action": "forgot", "id": gone["id"] if gone else None}


# ------------------------------------------------------------------ read
def expire(store: Store, home_id: str, now: datetime) -> None:
    store.memory_expire(home_id, "plans", iso(now - timedelta(days=PLAN_DAYS)))


def listing(store: Store, home_id: str, now: datetime | None = None) -> list[dict[str, Any]]:
    expire(store, home_id, now or datetime.now(UTC))
    return store.memories(home_id)


def _terms(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", norm(text)) if len(w) > 2]


def recall(store: Store, home_id: str, topic: str, *, limit: int = 3, intent: str | None = None,
           fill: bool = False, exclude: tuple[str, ...] = (), now: datetime | None = None) -> list[dict[str, Any]]:
    """Best matches for the topic (+ the intent's words), newest first on ties; `fill` tops up with recent ones."""
    now = now or datetime.now(UTC)
    expire(store, home_id, now)
    terms = _terms(topic) + (INTENT_TERMS.get(intent or "", []))
    hits = [m for m in store.memory_search(home_id, terms, limit + 8) if m["category"] not in exclude]
    if fill:
        seen = {m["id"] for m in hits}
        hits += [m for m in store.memories(home_id) if m["id"] not in seen and m["category"] not in exclude]
    out = hits[:limit]
    store.memory_touch([m["id"] for m in out], iso(now))
    return out


def first_name(store: Store, home_id: str) -> str | None:
    names = [m for m in store.memories(home_id) if m["category"] == "name"]
    if not names:
        return None
    text = names[0]["text"]
    m = re.search(r"(?:name is|call me|i'm|i am|nimeni on|olen|jag heter)\s+(\w+)", text, re.I)
    if m:
        return m.group(1)
    return text if len(text.split()) <= 2 else None


# ------------------------------------------------------------------ routines + thread
def routines(store: Store, home_id: str, now: datetime, tz) -> list[str]:
    since = iso(now - timedelta(days=ROUTINE_WINDOW_DAYS))
    counts: Counter[tuple[str, int]] = Counter()
    for ep in store.episodes(home_id, since):
        if ep["outcome"] == "completed" and ep["intent"] in ROUTINE_VERB:
            counts[(ep["intent"], datetime.fromisoformat(ep["start"]).astimezone(tz).weekday())] += 1
    found = sorted(((n, k) for k, n in counts.items() if n >= ROUTINE_MIN), key=lambda x: (-x[0], x[1]))
    return [f"usually {ROUTINE_VERB[intent]} on {WEEKDAYS[wd]}" for _, (intent, wd) in found[:2]]


def open_thread(store: Store, home_id: str, skill: str, topic: str, now: datetime) -> int:
    topic = re.sub(r"\s+", " ", topic).strip()
    if not topic or health_detail(topic):
        raise MemoryRefused("thread topic not kept")
    return store.thread_open(home_id, skill, topic, iso(now), iso(now + timedelta(days=THREAD_DAYS)))


def current_thread(store: Store, home_id: str, now: datetime) -> dict[str, Any] | None:
    return store.thread_current(home_id, iso(now))


def close_threads_for(store: Store, home_id: str, intent: str, now: datetime) -> int:
    """A completed session of the thread's skill closes it (the thread was picked up)."""
    skill = SKILL_OF_INTENT.get(intent)
    return store.thread_close(home_id, iso(now), skill) if skill else 0
