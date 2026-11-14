"""How a reflection with Kaiku went, as a level, a tone and themes. Never the words.

One compact summary per finished conversation: valence (low | neutral | bright), up to two tone tags and an energy
level from fixed lists, up to three theme tags, and whether the person asked to stop or did not want to talk.
Two separate readings, each with its provenance:
- from their WORDS (`valence`, `tone`, `energy`, `themes`; `by` = "rule" or the Gemma model name): only when the
  device sent the conversation text (the person's transcript opt-in). Deterministic keyword rules at episode end;
  Gemma relabels from the same fixed lists right after the episode and in the nightly job; anything else is
  rejected and the rule result stands.
- as the model in the conversation reported it (`heard`; provenance `model_heard` when the native-audio voice
  model heard them speak, `model_read` when it went by typed words): written by the `feel` tool (mind/feel.py)
  while the person lets Kaiku remember things. Enums only. An observation by a model, not a measurement.
Without either, only `declined` is known, from the episode outcome. A crisis conversation gets no summary.
Deleting a transcript deletes its summary.
Who sees it: the person's own companion (context card: "yesterday evening sounded low; sleep came up") and, only
while the person shares with the care team, the practitioner as counts ("low on 4 of the last 5; themes: sleep").
None of it is a state or feeds the consensus.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from kaiku_contracts.companion_tools import ENERGIES, TONES, VALENCES
from kaiku_contracts.config import get

from ..analytics.metrics import parse_ts
from ..llm import gemma, ledger
from ..llm.errors import LlmUnavailable
from ..settings import TZ
from ..store.db import Store

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
TONE_WORDS = {
    "flat": r"numb|empty|nothing (?:much|really|good)|whatever|don'?t care|pointless|no point|can'?t be bothered",
    "tense": r"worr\w*|anxious|nervous|on edge|stress\w*|tense|scared|afraid|overwhelm\w*|can'?t (?:relax|stop thinking)",
    "tearful": r"cry\w*|cried|tears?|sobb\w*|heartbroken|griev\w*|died|funeral|miss (?:her|him|them) so",
    "irritable": r"angry|annoy\w*|furious|fed up|sick of|irritat\w*|hate\w*|unfair|stupid",
    "warm": r"grateful|thankful|lovely|so kind|love[ds]?|glad|hug\w*|sweet of|touched",
    "playful": r"haha|funny|laugh\w*|joke\w*|silly|hilarious|giggl\w*",
    "calm": r"calm\w*|peaceful|relaxed|rested|content|settled|at ease|quiet (?:day|evening|morning)",
}
ENERGY_LOW = re.compile(r"\b(?:exhausted|tired|worn out|drained|no energy|sleepy|sluggish|heavy|"
                        r"couldn'?t get up|can'?t be bothered)\b", re.I)
ENERGY_HIGH = re.compile(r"\b(?:excited|buzzing|can'?t wait|full of energy|wired|thrilled|over the moon)\b|!", re.I)
KEEP = 90
MOMENTS = 12
PROVENANCE = ("model_heard", "model_read")
_SYSTEM = (
    "You label how one conversation with a companion went, from the person's own lines. Return ONLY JSON: "
    "{\"valence\": \"low|neutral|bright\", \"themes\": [up to three of: " + ", ".join(THEMES) + "], "
    "\"tone\": [up to two of: " + ", ".join(TONES) + "], \"energy\": \"low|medium|high\" or null}. "
    "valence is how the person sounded about their day, not a clinical judgement. tone and energy are how their "
    "words read; leave tone empty and energy null when the words do not show it. Use only the listed values; "
    "empty lists are fine. No other text."
)


def _key(home_id: str) -> str:
    return f"affect:{home_id}"


def _person_text(turns: list[dict[str, Any]]) -> str:
    return " ".join(t["text"] for t in turns if t.get("role") == "person")[:4000]


def tone_rule(turns: list[dict[str, Any]], valence: str | None) -> tuple[list[str], str | None]:
    """(up to two tone tags, energy) from the person's words. Empty / None when the words do not show it."""
    mine = [t["text"] for t in turns if t.get("role") == "person" and t.get("text", "").strip()]
    text = " ".join(mine)[:4000]
    hits = Counter({tone: len(re.findall(rf"\b(?:{words})", text, re.I)) for tone, words in TONE_WORDS.items()})
    tone = [t for t, n in hits.most_common(2) if n]
    if not tone and len(mine) >= 2 and valence != "bright" and sum(len(m.split()) for m in mine) <= 3 * len(mine):
        tone = ["flat"]  # several answers of a word or two, and nothing glad in them
    low, high = len(ENERGY_LOW.findall(text)), len(ENERGY_HIGH.findall(text))
    energy = "low" if low > high else "high" if high > low else None
    return tone, energy


def rule(turns: list[dict[str, Any]]) -> dict[str, Any] | None:
    text = _person_text(turns)
    if not text.strip():
        return None
    low, bright = len(LOW.findall(text)), len(BRIGHT.findall(text))
    valence = "low" if low > bright else "bright" if bright > low else "neutral"
    declined = bool(STOP.search(text))
    if declined and not low and not bright and len(text.split()) <= 12:
        valence = None  # they only said they did not want to talk: nothing to read a mood from
    hits = Counter({theme: len(re.findall(rf"\b(?:{words})", text, re.I)) for theme, words in THEME_WORDS.items()})
    themes = [theme for theme, n in hits.most_common(3) if n]
    tone, energy = tone_rule(turns, valence) if valence else ([], None)
    return {"valence": valence, "themes": themes, "tone": tone, "energy": energy, "declined": declined, "by": "rule"}


def checked(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```") and raw.splitlines()[-1].strip() == "```":
        raw = "\n".join(raw.splitlines()[1:-1])
    data = json.loads(raw)
    themes = data.get("themes") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("valence") not in VALENCES or not isinstance(themes, list) \
            or len(themes) > 3 or any(t not in THEMES for t in themes):
        raise ValueError("invalid affect label")
    tone, energy = data.get("tone") or [], data.get("energy")
    if not isinstance(tone, list) or len(tone) > 2 or any(t not in TONES for t in tone) \
            or energy not in (None, *ENERGIES):
        raise ValueError("invalid tone label")
    return {"valence": data["valence"], "themes": list(dict.fromkeys(themes)), "tone": list(dict.fromkeys(tone)),
            "energy": energy}


def _most(values: list[Any]) -> Any:
    """Most frequent; the later one wins a tie (how the conversation ended up)."""
    counts = Counter(v for v in values if v)
    best = max(counts.values(), default=0)
    return next((v for v in reversed(values) if v and counts[v] == best), None)


def heard_of(moments: list[dict[str, Any]]) -> dict[str, Any]:
    """One reading for the conversation from what the model reported, moment by moment."""
    tones = Counter(t for m in moments for t in m.get("tone") or [])
    return {"valence": _most([m.get("valence") for m in moments]), "energy": _most([m.get("energy") for m in moments]),
            "tone": [t for t, _ in tones.most_common(2)],
            "provenance": "model_heard" if any(m.get("via", "voice") == "voice" for m in moments) else "model_read",
            "moments": len(moments)}


def note_heard(store: Store, home_id: str, episode_id: str, *, start: str, surface: str, intent: str,
               moment: dict[str, Any]) -> dict[str, Any]:
    """The `feel` tool reported how a moment sounded. Enums only; kept with the conversation's summary."""
    all_rows = rows(store, home_id)
    row = all_rows.get(episode_id) or {"start": start, "surface": surface, "intent": intent, "valence": None,
                                       "themes": [], "declined": False, "by": None}
    row["heard_moments"] = [*row.get("heard_moments", []), {k: moment.get(k) for k in ("valence", "energy", "tone", "via")}][-MOMENTS:]
    row["heard"] = heard_of(row["heard_moments"])
    if row.get("by") in (None, *PROVENANCE):  # no reading from their words: the reported one is the only level
        row.update(valence=row["heard"]["valence"], by=row["heard"]["provenance"])
    all_rows[episode_id] = row
    _save(store, home_id, all_rows)
    return row["heard"]


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
    old = all_rows.get(episode_id) or {}
    reported = {k: old[k] for k in ("heard", "heard_moments") if k in old}  # what `feel` noted stays with it
    row = {"start": start, "surface": surface, "intent": intent, "valence": summary["valence"] if summary else None,
           "themes": summary["themes"] if summary else [], "tone": summary["tone"] if summary else [],
           "energy": summary["energy"] if summary else None, "declined": declined,
           "by": summary["by"] if summary else "outcome", **reported}
    if reported and not row["valence"]:
        row.update(valence=reported["heard"]["valence"], by=reported["heard"]["provenance"])
    all_rows[episode_id] = row
    _save(store, home_id, all_rows)


def label_episode(store: Store, home_id: str, episode_id: str, gen: Any = None) -> bool:
    """Right after an episode: one Gemma call relabels its rule summary (valence, themes, tone, energy) from the
    opted-in transcript. Validated enums or the rule result stands. True when the label was replaced."""
    row = rows(store, home_id).get(episode_id)
    if not row or row.get("by") != "rule" or not row.get("valence") \
            or not get("insight", "reflection_label_at_episode_end", True):
        return False
    turns = next((t["turns"] for t in store.transcripts(home_id) if t["episode_id"] == episode_id), None)
    if not turns:
        return False
    try:
        label = checked((gen or gemma.generate)(_SYSTEM + "\nPERSON:\n" + _person_text(turns),
                                                task="reflection_affect", home_id=home_id))
    except (LlmUnavailable, ValueError, TypeError, AttributeError):
        ledger.record("rule", "reflection_affect", ok=True, fallback=True, home_id=home_id)
        return False
    all_rows = rows(store, home_id)  # re-read: the call took a while and `feel` may have written meanwhile
    if episode_id not in all_rows:
        return False
    all_rows[episode_id].update(label, by=gemma.model_name())
    _save(store, home_id, all_rows)
    return True


def forget(store: Store, home_id: str, episode_id: str | None = None) -> None:
    """The person deleted a transcript (or all of them): the summary derived from it goes too."""
    if episode_id is None:
        store.kv_delete(_key(home_id))
        return
    all_rows = rows(store, home_id)
    if all_rows.pop(episode_id, None) is not None:
        _save(store, home_id, all_rows)


def forget_heard(store: Store, home_id: str) -> None:
    """The person asked Kaiku to forget everything: the tone the companion reported goes, and so does the
    conversation timeline it came from. Summaries of opted-in transcripts are deleted with their transcript."""
    kept = {}
    for eid, row in rows(store, home_id).items():
        if row.get("by") in PROVENANCE:
            continue  # the reported reading was all this row had
        kept[eid] = {k: v for k, v in row.items() if k not in ("heard", "heard_moments")}
    _save(store, home_id, kept) if kept else store.kv_delete(_key(home_id))
    store.kv_delete(f"feel:{home_id}")


def nightly(store: Store, home_id: str, gen: Any = None) -> dict[str, int]:
    """Gemma relabels rule summaries that still have their opted-in transcript. Validated enums or nothing."""
    gen = gen or gemma.generate
    all_rows = rows(store, home_id)
    transcripts = {t["episode_id"]: t["turns"] for t in store.transcripts(home_id)}
    done = failed = 0
    limit = int(get("insight", "reflection_labels_per_night", 4))  # newest first; the rest keep their rule label
    for episode_id, row in sorted(all_rows.items(), key=lambda kv: kv[1]["start"], reverse=True):
        if done >= limit:
            break
        if row.get("by") != "rule" or episode_id not in transcripts or not row.get("valence"):
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
    out = [{**row, "id": eid, "day": parse_ts(row["start"]).astimezone(TZ).date(), "part": _part(row["start"])}
           for eid, row in rows(store, home_id).items() if since <= parse_ts(row["start"]) <= now]
    return sorted(out, key=lambda r: r["start"])


def public_heard(row: dict[str, Any]) -> dict[str, Any] | None:
    return dict(row["heard"]) if row.get("heard") else None


def heard_words(h: dict[str, Any] | None) -> str | None:
    """'flat and quiet': the reported reading as plain words (tone tags, then quiet / lively)."""
    if not h:
        return None
    words = [*(h.get("tone") or [])[:2],
             *([{"low": "quiet", "high": "lively"}[h["energy"]]] if h.get("energy") in ("low", "high") else [])]
    words = words or [w for w in [{"low": "low", "bright": "bright", "neutral": "even"}.get(h.get("valence") or "")] if w]
    return " and ".join(words) or None


def sounded(row: dict[str, Any]) -> str | None:
    """'sounded flat and quiet (as heard by the voice model)'."""
    h = row.get("heard")
    words = heard_words(h)
    if not h or not words:
        return None
    who = "as heard by the voice model" if h["provenance"] == "model_heard" else "as the model read their words"
    return f"sounded {words} ({who})"


def is_low(row: dict[str, Any]) -> bool:
    """A talk that sounded low, or flat without anything glad in it (their words or the reported reading)."""
    h = row.get("heard") or {}
    flat = "flat" in [*(row.get("tone") or []), *(h.get("tone") or [])]
    return "low" in (row.get("valence"), h.get("valence")) or (flat and "bright" not in (row.get("valence"), h.get("valence")))


def heavy_days(store: Store, home_id: str, now: datetime, days: int = 7) -> int:
    """On how many of the last `days` local days a talk sounded low or flat."""
    return len({r["day"] for r in recent(store, home_id, now, days=days) if is_low(r)})


def last_was_low(store: Store, home_id: str, now: datetime | None = None) -> bool:
    """The latest reflection of the last two days sounded low: tomorrow opens gently."""
    now = now or datetime.now(UTC)
    row = next((r for r in reversed(recent(store, home_id, now, days=2)) if r["valence"] or r["declined"]), None)
    return bool(row and is_low(row))


def latest(store: Store, home_id: str, now: datetime | None = None, exclude: str | None = None
           ) -> dict[str, Any] | None:
    """The latest reflection of the last two days: {when, valence, themes, declined, tone, energy, heard}.
    `exclude`: the conversation going on right now."""
    now = now or datetime.now(UTC)
    row = next((r for r in reversed(recent(store, home_id, now, days=2))
                if (r["valence"] or r["declined"]) and r["id"] != exclude), None)
    if row is None:
        return None
    today = now.astimezone(TZ).date()
    when = f"this {row['part']}" if row["day"] == today else f"yesterday {row['part']}" \
        if row["day"] == today - timedelta(days=1) else f"the {row['part']} before last"
    return {"when": when, "valence": row["valence"], "themes": row["themes"][:3], "declined": row["declined"],
            "tone": (row.get("tone") or [])[:2], "energy": row.get("energy"), "heard": public_heard(row)}


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
    after = {"low": "Be gentle; do not quote it back.", "bright": "You may be glad about it with them; do not quote it back."}
    h = row.get("heard") or {}
    how = [*(row["tone"] or h.get("tone") or [])[:2],
           *([{"low": "quiet", "high": "lively"}[e] for e in [row["energy"] or h.get("energy")] if e in ("low", "high")])]
    shade = f" ({', '.join(how)})" if how else ""
    return f"The talk {when} {level[row['valence']]}{shade}{about}. {after.get(row['valence'], 'Do not quote it back.')}"
