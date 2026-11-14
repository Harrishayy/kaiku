"""Assemble Kaiku's system instruction: config/persona.md + one surface of config/surfaces.toml + a context card.

Used by `POST /v1/companion/session` (plan 03 §3) and by the companion evals (tools/companion_evals imports this
module, so evals test exactly what the cloud serves). Pure: text in, text out; file loading only in `load_files`.

Context card (built deterministically by the cloud, ≤ 400 tokens). Allowed keys:
    language        "en" | "fi" | "sv"
    intent          e.g. "ritual", "walk", "talk"
    time_of_day     "morning" | "afternoon" | "evening" | "night"
    weather_word    one word, e.g. "grey"
    first_name      only if the person shared it
    done_today      list of short strings ("weather check on the phone")
    suggestion      today's bandit suggestion (phrase it, don't change it)
    phq9_due        bool
    memories        up to 3 short strings the person chose to share
    routines        up to 2 short strings ("usually walks on Tuesdays"), from episodes (count rule, no ML)
    open_thread     a topic left open on any surface ("the walk by the lake")
    tone            "steady" | "gentle" | "extra-gentle"  (soft cue from consensus — never the state itself)
    care_info       an approved passage from the care team (the only source for treatment facts)
    others_present  bool (a second person is in the room)
    dont_remember   bool (the person said "don't remember things")
    purpose         "talk" | "check_in" | "walk" | "ritual" (why the device opened the session, when it said so)
    chat_depth      "brief" | "stay" (how the chat should open; rule in mind/card.py)
    open_items      check-in dials not answered today ("mood" | "energy" | "sleep"); at most one is woven in
The shape of a check-in (`render_shape`) is its own short section, outside the card's token budget.
Anything that looks like state, scores or data about the person is rejected: the model never sees it.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path
from typing import Any

from kaiku_contracts.config import find_repo_file

_PERSONA = find_repo_file("config/persona.md")
ROOT = _PERSONA.parents[1] if _PERSONA else Path.cwd()

CARD_KEYS = {"language", "intent", "time_of_day", "weather_word", "first_name", "done_today", "suggestion",
             "phq9_due", "source_context", "memories", "routines", "open_thread", "tone", "care_info", "focus", "others_present", "dont_remember",
             "recent_reflection", "last_reflection", "today_facts", "purpose", "chat_depth", "open_items"}
DEPTHS = {"brief", "stay"}
OPEN_ITEMS = {"mood": "how they feel", "energy": "their energy", "sleep": "how they slept"}
FEEL_RULE = ("`feel`: call it once per clear shift in how they feel or clear news, and keep talking while it runs. Its "
             "answer shapes your next turns: how to meet it (`stance`, `reflect_hint`), one thing to bring in lightly "
             "(`recall`), at most one thing to offer once after they feel heard (`may_offer`; a no is final), and "
             "whether to keep it small or stay (`depth`).")
TONES = {"steady", "gentle", "extra-gentle"}
LANGUAGES = {"en", "fi", "sv"}
FORBIDDEN_KEY = re.compile(r"state|score|verdict|consensus|needs_call|phq9_total|z_|baseline|metric|trend|risk|"
                           r"sleep|heart|hrv|steps|watch|wearable", re.I)
MAX_CARD_TOKENS = 400  # ~4 chars per token
NOT_FOR_MODEL = {"About this file", "Examples", "Per-language notes"}
TONE_TEXT = {
    "steady": "Be your usual warm self.",
    "gentle": "Be a little gentler and slower today; offer less, listen more.",
    "extra-gentle": "Be extra gentle today: very short turns, no suggestions unless they ask, and make it easy to "
                    "talk to their care team if they want to.",
}


# ---------------------------------------------------------------- persona
def persona_version(persona_text: str) -> str:
    return "persona+" + hashlib.sha256(persona_text.encode()).hexdigest()[:8]


def _split(text: str, level: str) -> list[tuple[str, str]]:
    parts = re.split(rf"^{level} (.+)$", text, flags=re.M)
    return [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]


def parse_persona(text: str) -> dict[str, Any]:
    sections = dict(_split(text, "##"))
    languages = dict(_split(sections.get("Per-language notes", ""), "###"))
    examples = []
    for head, body in _split(sections.get("Examples", ""), "###"):
        num, surface, skill = (p.strip() for p in head.split("·"))
        ex: dict[str, Any] = {"n": int(num), "surface": surface, "skill": skill}
        for label, value in re.findall(r"^\*\*(.+?):\*\*\s*(.+)$", body, flags=re.M):
            if label.startswith("Bad"):
                ex["bad"], ex["bad_code"] = value, re.search(r"\((.+)\)", label).group(1)
            else:
                ex[label.lower()] = value
        examples.append(ex)
    return {"sections": sections, "languages": languages, "examples": examples}


# ---------------------------------------------------------------- surfaces
def parse_surfaces(text: str) -> dict[str, dict[str, Any]]:
    return tomllib.loads(text)["surface"]


def render_surface(name: str, s: dict[str, Any], tools: list[str] | None = None) -> str:
    """`tools`: the tool names actually served on this surface (registry); default: the surface table's list."""
    tools = list(s["tools"]) if tools is None else tools
    body = ", ".join(k.replace("_", " ") for k, v in s["body"].items() if v is True) or "voice only"
    lines = [
        f"Right now you are {s['label']} ({name}, {s['modality']}). Your body here: {body}.",
        f"Aim for about {s['target_words']} words per turn; never more than {s['max_words']} words or "
        f"{s['max_sentences']} sentences, and at most one question.",
        f"A typical session here lasts about {s['session_minutes']} minutes.",
        f"Tools you may use here: {', '.join(tools)}.",
    ]
    if "start_activity" in tools:
        lines.append(f"Activities you can start here: {', '.join(s['activities'])}. Start one only when the person "
                     "asks for it or says yes to your offer; when a conversation opens, greet them first.")
    lines += [f"- {r}" for r in s.get("rules", [])]
    if "feel" in tools:
        lines.append(f"- {FEEL_RULE}")
    return "\n".join(lines)


# ---------------------------------------------------------------- context card
def validate_card(card: dict[str, Any]) -> None:
    bad = [k for k in card if k not in CARD_KEYS or FORBIDDEN_KEY.search(k) and k != "phq9_due"]
    if bad:
        raise ValueError(f"context card keys not allowed (the model never sees state/data): {sorted(bad)}")
    if card.get("tone", "steady") not in TONES:
        raise ValueError(f"tone must be one of {sorted(TONES)}")
    if card.get("language", "en") not in LANGUAGES:
        raise ValueError(f"language must be one of {sorted(LANGUAGES)}")
    if len(card.get("memories", [])) > 3:
        raise ValueError("at most 3 memories")
    if len(card.get("routines", [])) > 2:
        raise ValueError("at most 2 routines")
    if card.get("chat_depth", "brief") not in DEPTHS:
        raise ValueError(f"chat_depth must be one of {sorted(DEPTHS)}")
    if set(card.get("open_items", [])) - set(OPEN_ITEMS):
        raise ValueError(f"open_items must be among {sorted(OPEN_ITEMS)}")


def render_card(card: dict[str, Any]) -> str:
    validate_card(card)
    c = card
    lines = [f"Language: speak {({'en': 'English', 'fi': 'Finnish', 'sv': 'Swedish'})[c.get('language', 'en')]}."]
    if c.get("time_of_day"):
        lines.append(f"It is {c['time_of_day']}" + (f", and the weather is {c['weather_word']}." if c.get("weather_word") else "."))
    if c.get("first_name"):
        lines.append(f"Their name is {c['first_name']}.")
    if c.get("intent"):
        lines.append(f"This session: {c['intent']}.")
    if c.get("done_today"):
        lines.append("Already done today: " + "; ".join(c["done_today"]) + ".")
    if c.get("source_context"):
        lines.append("Recent input context (presence only): " + " ".join(c["source_context"]))
    if c.get("suggestion"):
        lines.append(f"Today's suggestion (if it fits): {c['suggestion']}.")
    if c.get("phq9_due"):
        lines.append("The two-weekly questionnaire is due: you may offer it once, gently. Call start_phq9 only "
                     "after a clear yes.")
    if c.get("routines"):
        lines.append("Their rhythm: " + "; ".join(c["routines"]) + ".")
    if c.get("open_thread"):
        lines.append(f"Left open last time (on any device): {c['open_thread']}. Pick it up gently if it fits.")
    if c.get("focus"):
        lines.append(f"Today's focus, if it fits naturally: {c['focus']}.")
    if c.get("today_facts"):
        lines.append("Today, in their own ratings: " + ", ".join(c["today_facts"]) + ". Mention it only if it helps.")
    if c.get("recent_reflection"):
        lines.append(f"Last reflection: {c['recent_reflection']}")
    if c.get("dont_remember"):
        lines.append("They asked you not to remember things: never call remember.")
    elif c.get("memories"):
        lines.append("Things they told you before: " + "; ".join(c["memories"]) + ".")
    if c.get("others_present"):
        lines.append("Someone else is in the room: be friendly, ask nothing personal, remember nothing.")
    lines.append(TONE_TEXT[c.get("tone", "steady")])
    if c.get("care_info"):
        lines.append(f'Care team information (the ONLY source for treatment facts): "{c["care_info"]}"')
    else:
        lines.append("No care team information today: hand any treatment question to the care team.")
    text = "\n".join(lines)
    if len(text) / 4 > MAX_CARD_TOKENS:
        raise ValueError(f"context card too long (~{len(text) // 4} tokens > {MAX_CARD_TOKENS})")
    return text


def render_grounding(card: dict[str, Any]) -> str:
    """What may be said as fact. The persona is full of quoted example lines ("You've been out already…"); a model
    reused one as a fact about a day with nothing recorded. This section says which is which, every session."""
    today = bool(card.get("done_today") or card.get("today_facts")) or any(
        " today" in f for f in card.get("source_context", []))
    lines = ["Quoted lines anywhere in these instructions show how to speak. They are never facts about this person "
             "or this day: do not reuse one unless \"Today\" above or the person's own words make it true.",
             "Say that they went out, slept a certain way, did an activity or were somewhere only if \"Today\" lists "
             "it for today or they just told you. Something listed for yesterday or earlier is not about today."]
    if not today:
        lines.append("Nothing is recorded for today yet: do not say or imply that they have done anything today.")
    if not card.get("weather_word"):
        lines.append("You are not told the weather: do not describe it.")
    return "\n".join(lines)


def render_shape(card: dict[str, Any]) -> str | None:
    """How a check-in conversation runs: a passing chat that stays small on an ordinary day and stays on a very
    good or very hard one. Only when the device opened the session as a check-in."""
    if card.get("purpose") != "check_in":
        return None
    if card.get("chat_depth") == "stay":
        lines = ["This check-in is in no hurry: the last talk was a hard one, or it has been a heavy few days. Open "
                 "gently with something real, follow them, and never be the one to close."]
    else:
        lines = ["This check-in is a passing chat, like meeting someone you like on the street. Open with something "
                 "real that \"Today\" above actually lists (what was left open last time, the weather if it is "
                 "given); if it lists nothing, a plain greeting and one open question. Give back what you hear, and "
                 "close warmly and lightly within about four exchanges, in words like \"Good to see you. I'm "
                 "around later.\" Call `end_session` with your goodbye.",
                 "If it turns out to be a very good or a very hard day, call `feel`; when its `depth` is stay, or "
                 "they keep talking or ask for more, stay as long as they want. Never keep someone talking, and "
                 "never rush someone who needs it."]
    items = [OPEN_ITEMS[i] for i in card.get("open_items", [])]
    if items:
        lines.append("Not answered yet today: " + ", ".join(items) + ". You may weave ONE of these into the chat as "
                     "an ordinary question (\"How did you sleep?\"), never as a scale. Call `record_dial` only if "
                     "they offer a number from one to five themselves; never ask for a number, never go through "
                     "them like a form, and recording none is fine: the dials on screen still work.")
    return "\n".join(lines)


# ---------------------------------------------------------------- assemble
def assemble(persona_text: str, surfaces: dict[str, dict[str, Any]], surface: str, card: dict[str, Any],
             max_examples: int = 4, tools: list[str] | None = None) -> str:
    """The full system instruction for one session. Deterministic: same inputs → same string."""
    if surface not in surfaces:
        raise KeyError(f"unknown surface {surface!r}; known: {sorted(surfaces)}")
    p = parse_persona(persona_text)
    lang = card.get("language", "en")
    out = [f"## {h}\n{b}" for h, b in p["sections"].items() if h not in NOT_FOR_MODEL]
    if lang in p["languages"]:
        out.append(f"## Language notes ({lang})\n{p['languages'][lang]}")
    out.append("## Your body right now\n" + render_surface(surface, surfaces[surface], tools))
    out.append("## Today\n" + render_card(card))
    out.append("## What you may say as fact\n" + render_grounding(card))
    shape = render_shape(card)
    if shape:
        out.append("## The shape of this conversation\n" + shape)
    exs = sorted(p["examples"], key=lambda e: e["surface"] != surface)[:max_examples]
    if exs:
        out.append("## Examples (say it like Good, never like Bad)\n" + "\n".join(
            f"Person: {e['person']}\nGood: {e['good']}\nBad: {e['bad']}" for e in exs))
    return "\n\n".join(out)


def load_files(root: Path | None = None) -> tuple[str, dict[str, dict[str, Any]]]:
    root = root or ROOT
    return (root / "config" / "persona.md").read_text(), parse_surfaces((root / "config" / "surfaces.toml").read_text())


def assemble_from_files(surface: str, card: dict[str, Any], root: Path | None = None) -> str:
    persona, surfaces = load_files(root)
    return assemble(persona, surfaces, surface, card)
