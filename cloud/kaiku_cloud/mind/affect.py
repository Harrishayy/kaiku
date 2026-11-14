"""How a reflection with Kaiku went, as a level and themes. Never the words.

One compact summary per finished conversation: valence (low | neutral | bright), up to three theme tags from a fixed
list, and whether the person asked to stop or did not want to talk. It is computed from the conversation text only
when the device sent one (the person's transcript opt-in); otherwise only `declined` is known, from the episode
outcome. A crisis conversation gets no summary. Deleting a transcript deletes its summary.

- at episode end: deterministic keyword rules (always available);
- in the nightly job: Gemma re-reads the stored opted-in transcript and returns {valence, themes} from the same
  fixed lists; anything else is rejected and the rule result stands.
Who sees it: the person's own companion (context card: "yesterday evening sounded low; sleep came up") and, only
while the person shares with the care team, the practitioner as counts ("low on 4 of the last 5; themes: sleep").
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from ..analytics.metrics import parse_ts
from ..llm import gemma, ledger
from ..llm.errors import LlmUnavailable
from ..settings import TZ
from ..store.db import Store

VALENCES = ("low", "neutral", "bright")
THEMES = ("sleep", "being alone", "family", "friends", "work", "body", "outdoors", "routine", "worry", "plans")
THEME_WORDS = {
    "sleep": r"sleep|slept|awake|insomnia|tired|nap|night|bed\b|uni|nukku|sömn",
    "being alone": r"alone|lonely|nobody|no one|by myself|isolated|yksin|ensam",
    "family": r"sister|brother|mother|mum|mom|father|dad|daughter|son\b|family|husband|wife|grandchild|sisko|äiti",
    "friends": r"friend|neighbou?r|visit|called me|ystävä",
    "work": r"work|job|boss|office|colleague|deadline|shift",
    "body": r"pain|ache|headache|stomach|appetite|eat|ate|hungry|heavy|dizzy|sick|body",
    "outdoors": r"walk|outside|park|lake|forest|fresh air|garden|sun|daylight",
    "routine": r"routine|morning ritual|drum|breath|habit|every day|check-?in",
    "worry": r"worr|anxious|afraid|scared|nervous|stress|overwhelm|can't stop thinking",
    "plans": r"tomorrow|next week|plan|going to|looking forward|appointment",
}
LOW = re.compile(r"\b(bad|rough|hard|awful|terrible|low|down|sad|empty|exhausted|tired|flat|heavy|worse|"
                 r"can't|couldn't|didn't want|no energy|not great|not good|lonely|numb|pointless|struggl\w*)\b", re.I)
BRIGHT = re.compile(r"\b(good|great|better|nice|lovely|happy|glad|enjoy\w*|fun|proud|rested|calm|lighter|"
                    r"looking forward|laugh\w*|well)\b", re.I)
STOP = re.compile(r"\b(stop|not now|don't want to talk|leave me|go away|enough for (today|now)|later)\b", re.I)
KEEP = 90
_SYSTEM = (
    "You label how one conversation with a companion went, from the person's own lines. Return ONLY JSON: "
    "{\"valence\": \"low|neutral|bright\", \"themes\": [up to three of: " + ", ".join(THEMES) + "]}. "
    "valence is how the person sounded about their day, not a clinical judgement. Use only the listed themes; "
    "an empty list is fine. No other text."
)


def _key(home_id: str) -> str:
    return f"affect:{home_id}"


def _person_text(turns: list[dict[str, Any]]) -> str:
    return " ".join(t["text"] for t in turns if t.get("role") == "person")[:4000]


def rule(turns: list[dict[str, Any]]) -> dict[str, Any] | None:
    text = _person_text(turns)
    if not text.strip():
        return None
    low, bright = len(LOW.findall(text)), len(BRIGHT.findall(text))
    valence = "low" if low > bright else "bright" if bright > low else "neutral"
    hits = Counter({theme: len(re.findall(rf"\b(?:{words})", text, re.I)) for theme, words in THEME_WORDS.items()})
    themes = [theme for theme, n in hits.most_common(3) if n]
    return {"valence": valence, "themes": themes, "declined": bool(STOP.search(text)), "by": "rule"}


def checked(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```") and raw.splitlines()[-1].strip() == "```":
        raw = "\n".join(raw.splitlines()[1:-1])
    data = json.loads(raw)
    themes = data.get("themes") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("valence") not in VALENCES or not isinstance(themes, list) \
            or len(themes) > 3 or any(t not in THEMES for t in themes):
        raise ValueError("invalid affect label")
    return {"valence": data["valence"], "themes": list(dict.fromkeys(themes))}


def _save(store: Store, home_id: str, rows: dict[str, Any]) -> None:
    newest = sorted(rows.items(), key=lambda kv: kv[1]["start"])[-KEEP:]
    store.kv_set(_key(home_id), dict(newest))


def rows(store: Store, home_id: str) -> dict[str, Any]:
    return store.kv_get(_key(home_id)) or {}


def on_episode(store: Store, home_id: str, episode_id: str, *, start: str, surface: str, intent: str, outcome: str,
               turns: list[dict[str, Any]] | None, crisis: bool) -> None:
    """Called when an episode is recorded. `turns` only when a transcript was sent and may be kept."""
    all_rows = rows(store, home_id)
    if crisis:
        if all_rows.pop(episode_id, None) is not None:
            _save(store, home_id, all_rows)
        return
    summary = rule(turns or []) if turns else None
    declined = outcome in ("skipped", "ended_early") or bool(summary and summary["declined"])
    if summary is None and not declined:
        return
    all_rows[episode_id] = {"start": start, "surface": surface, "intent": intent,
                            "valence": summary["valence"] if summary else None,
                            "themes": summary["themes"] if summary else [], "declined": declined,
                            "by": summary["by"] if summary else "outcome"}
    _save(store, home_id, all_rows)


def forget(store: Store, home_id: str, episode_id: str | None = None) -> None:
    """The person deleted a transcript (or all of them): the summary derived from it goes too."""
    if episode_id is None:
        store.kv_delete(_key(home_id))
        return
    all_rows = rows(store, home_id)
    if all_rows.pop(episode_id, None) is not None:
        _save(store, home_id, all_rows)


def nightly(store: Store, home_id: str, gen: Any = None) -> dict[str, int]:
    """Gemma relabels rule summaries that still have their opted-in transcript. Validated enums or nothing."""
    gen = gen or gemma.generate
    all_rows = rows(store, home_id)
    transcripts = {t["episode_id"]: t["turns"] for t in store.transcripts(home_id)}
    done = failed = 0
    for episode_id, row in all_rows.items():
        if row.get("by") != "rule" or episode_id not in transcripts:
            continue
        try:
            label = checked(gen(_SYSTEM + "\nPERSON:\n" + _person_text(transcripts[episode_id]),
                                task="reflection_affect", home_id=home_id))
            row.update(label, by=gemma.model_name())
            done += 1
        except (LlmUnavailable, ValueError, TypeError, AttributeError):
            failed += 1
            ledger.record("rule", "reflection_affect", ok=True, fallback=True, home_id=home_id)
            if failed >= 2:  # the provider is down or misbehaving: keep the rule labels, stop spending
                break
    if done:
        _save(store, home_id, all_rows)
    return {"labelled": done, "kept_rule": failed}


def _part(start: str) -> str:
    hour = parse_ts(start).astimezone(TZ).hour
    return "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"


def recent(store: Store, home_id: str, now: datetime, days: int = 7) -> list[dict[str, Any]]:
    since = now - timedelta(days=days)
    out = [{**row, "day": parse_ts(row["start"]).astimezone(TZ).date(), "part": _part(row["start"])}
           for row in rows(store, home_id).values() if since <= parse_ts(row["start"]) <= now]
    return sorted(out, key=lambda r: r["start"])


def latest(store: Store, home_id: str, now: datetime | None = None) -> dict[str, Any] | None:
    """The latest reflection of the last two days: {when, valence, themes, declined}."""
    now = now or datetime.now(UTC)
    row = next((r for r in reversed(recent(store, home_id, now, days=2)) if r["valence"] or r["declined"]), None)
    if row is None:
        return None
    today = now.astimezone(TZ).date()
    when = f"this {row['part']}" if row["day"] == today else f"yesterday {row['part']}" \
        if row["day"] == today - timedelta(days=1) else f"the {row['part']} before last"
    return {"when": when, "valence": row["valence"], "themes": row["themes"][:3], "declined": row["declined"]}


def card_line(store: Store, home_id: str, now: datetime | None = None) -> str | None:
    """For Kaiku itself: the latest reflection of the last two days, as a level and themes."""
    row = latest(store, home_id, now)
    if row is None:
        return None
    when = row["when"]
    about = f"; {' and '.join(row['themes'][:2])} came up" if row["themes"] else ""
    if row["declined"] and not row["valence"]:
        return f"They did not feel like talking {when}. No pressure today."
    level = {"low": "sounded like a hard one", "bright": "sounded like a good one", "neutral": "was an ordinary one"}
    return f"The talk {when} {level[row['valence']]}{about}. Be gentle; do not quote it back."
