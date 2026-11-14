"""Daily reflection: the flagship model (Gemini 4 Argon) picks *today's focus* for Kaiku from options code offers.

Input is structured only (what was done this week per surface, the person's own memories, routines, the open thread,
today's suggestion) — never transcripts, state words, scores or watch data. Output is constrained JSON: an option ID
from the list we give it, plus which memory index (if any) is worth bringing up. Code validates every field; anything
invalid or unavailable (no key, timeout) → the deterministic rule. The result is cached per home per local day and
becomes one line of the context card (`focus`). It can never change state, nudges, tools or safety.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from ..llm import gemini
from ..llm.errors import LlmUnavailable
from ..settings import TZ
from ..store.db import Store

OPTIONS = {
    "follow_thread": "pick up the thing left open last time",
    "offer_suggestion": "offer today's suggestion",
    "recall_memory": "bring up one thing they told you before, warmly",
    "keep_light": "keep it light and short; no new asks",
    "celebrate": "notice something they already did today",
}
SCHEMA = {
    "type": "object",
    "properties": {
        "focus": {"type": "string", "enum": list(OPTIONS)},
        "memory_index": {"type": ["integer", "null"], "description": "index into memories, only for recall_memory"},
    },
    "required": ["focus"],
}
SYSTEM = (
    "You plan the day for Kaiku, a gentle companion for someone recovering at home after depression treatment. "
    "Choose ONE focus from the given options that would feel most natural and kind today. Prefer continuity "
    "(open threads, their routines) and never pile on asks when the tone is extra-gentle. Answer with JSON only."
)


def _week_summary(store: Store, home_id: str, now: datetime) -> dict[str, int]:
    since = (now - timedelta(days=7)).isoformat()
    return dict(Counter(f"{e.get('surface')}:{e.get('intent')}" for e in store.episodes(home_id, since=since)))


def rule(card: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback (and the shape the flagship must match)."""
    if card.get("tone") == "extra-gentle":
        return {"focus": "keep_light", "memory_index": None, "by": "rule"}
    if card.get("open_thread"):
        return {"focus": "follow_thread", "memory_index": None, "by": "rule"}
    if card.get("done_today"):
        return {"focus": "celebrate", "memory_index": None, "by": "rule"}
    if card.get("suggestion"):
        return {"focus": "offer_suggestion", "memory_index": None, "by": "rule"}
    if card.get("memories"):
        return {"focus": "recall_memory", "memory_index": 0, "by": "rule"}
    return {"focus": "keep_light", "memory_index": None, "by": "rule"}


def validate(raw: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    focus = raw.get("focus")
    if focus not in OPTIONS:
        raise ValueError(f"focus {focus!r} not an option")
    if focus == "follow_thread" and not card.get("open_thread"):
        raise ValueError("follow_thread without an open thread")
    if focus == "offer_suggestion" and not card.get("suggestion"):
        raise ValueError("offer_suggestion without a suggestion")
    if focus == "celebrate" and not card.get("done_today"):
        raise ValueError("celebrate with nothing done today")
    idx = raw.get("memory_index")
    if focus == "recall_memory":
        if not isinstance(idx, int) or not 0 <= idx < len(card.get("memories") or []):
            raise ValueError("recall_memory needs a valid memory_index")
    else:
        idx = None
    if card.get("tone") == "extra-gentle" and focus in ("offer_suggestion", "recall_memory"):
        raise ValueError("no new asks on an extra-gentle day")
    return {"focus": focus, "memory_index": idx}


def plan(store: Store, home_id: str, card: dict[str, Any], *, now: datetime | None = None, use_model: bool = True,
         log: Any = None) -> dict[str, Any]:
    """Today's focus for this home. Cached per local day; flagship when available, otherwise the rule."""
    now = now or datetime.now(UTC)
    key = f"reflect:{home_id}:{now.astimezone(memory_tz()).date().isoformat()}"
    cached = store.kv_get(key)
    if isinstance(cached, dict) and cached.get("focus") in OPTIONS:
        return cached
    out = rule(card)
    if use_model and gemini.available():
        facts = {k: card.get(k) for k in ("time_of_day", "done_today", "suggestion", "memories", "routines",
                                          "open_thread", "tone")}
        facts["this_week"] = _week_summary(store, home_id, now)
        prompt = "Options:\n" + json.dumps(OPTIONS, indent=1) + "\nFacts:\n" + json.dumps(facts, default=str, indent=1)
        try:
            raw = json.loads(gemini.generate(prompt, tier="flagship", system=SYSTEM, schema=SCHEMA, timeout_s=40))
            out = {**validate(raw, card), "by": gemini.model_for("flagship")}
        except (LlmUnavailable, ValueError, json.JSONDecodeError) as e:
            if log:
                log.warning("reflect_fallback", f"{type(e).__name__}: {e}")
    store.kv_set(key, out)
    return out


def focus_line(p: dict[str, Any], card: dict[str, Any]) -> str | None:
    """One plain line for the context card (rendered into the system instruction)."""
    f = p.get("focus")
    if f == "recall_memory" and p.get("memory_index") is not None:
        mems = card.get("memories") or []
        if p["memory_index"] < len(mems):
            return f'{OPTIONS[f]} — e.g. "{mems[p["memory_index"]]}"'
    return OPTIONS.get(f)


def memory_tz():
    return TZ
