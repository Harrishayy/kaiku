"""Companion tool registry (plan 03 §4) — ground truth for every tool a Kaiku conversation may request.

The model *requests*; the device or cloud *decides*. Every tool here has a JSON-schema `parameters` block (Gemini
function-declaration shape) and the surfaces it may be used on. `make contracts` exports it to
`contracts/schemas/companion_tools.json` (+ `COMPANION_TOOLS` in `contracts/ts/index.ts`) for Swift/TS clients.

Who executes what (`executor`):
    cloud   remember, forget, recall, suggest_nudge, end_session, ask_mind — devices forward the call to
            `POST /v1/companion/tool` and hand the result back to the model
    device  record_dial, start_activity, log_walk_moment, send_friend_ping, start_phq9, express, look_at_this —
            the device runs the deterministic effect (it may still forward the call so the episode logs it)
No tool lowers a safety state, reads state numbers, contacts a clinician or changes criteria.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

Surface = Literal["robot", "glasses", "iphone", "mac", "web"]
SURFACES: tuple[str, ...] = get_args(Surface)
Intent = Literal["ritual", "checkin", "walk", "breathe", "talk", "break"]
INTENTS: tuple[str, ...] = get_args(Intent)
Skill = Literal["morning_ritual", "weather_check", "walk_companion", "breathe"]
SKILLS: tuple[str, ...] = get_args(Skill)
MemoryCategory = Literal["name", "people", "places", "likes", "what_helps", "plans", "preference"]
MEMORY_CATEGORIES: tuple[str, ...] = get_args(MemoryCategory)
Activity = Literal["breathe", "drum", "firefly", "pebbles", "tell", "walk", "light_hunt"]
Feeling = Literal["happy", "curious", "sleepy", "cozy", "proud"]
MindKind = Literal["fact", "care", "memory", "plan", "emotional"]

#: which skill an intent runs (talk = free chat, no skill)
SKILL_OF_INTENT: dict[str, str | None] = {"ritual": "morning_ritual", "checkin": "weather_check",
                                          "walk": "walk_companion", "breathe": "breathe", "break": "breathe",
                                          "talk": None}

_EMPTY: dict[str, Any] = {"type": "object", "properties": {}}
_ALL = list(SURFACES)

TOOLS: dict[str, dict[str, Any]] = {
    "record_dial": {
        "description": "Record the person's 1-5 answer to a dial question.",
        "executor": "device", "surfaces": _ALL,
        "parameters": {"type": "object", "required": ["item", "value"], "properties": {
            "item": {"type": "string", "enum": ["mood", "energy", "sleep"]},
            "value": {"type": "integer", "minimum": 1, "maximum": 5}}}},
    "start_activity": {
        "description": "Start a short activity on this device (the device runs it; data comes from sensors).",
        "executor": "device", "surfaces": _ALL,
        "parameters": {"type": "object", "required": ["kind"], "properties": {
            "kind": {"type": "string", "enum": list(get_args(Activity))}}}},
    "log_walk_moment": {
        "description": "The person found something on the light hunt (e.g. something green).",
        "executor": "device", "surfaces": ["glasses"],
        "parameters": {"type": "object", "required": ["kind"], "properties": {"kind": {"type": "string"}}}},
    "remember": {
        "description": "Keep a short fact the person agreed to share (stored only if allowed; they can see and "
                       "delete it). Never health details.",
        "executor": "cloud", "surfaces": _ALL,
        "parameters": {"type": "object", "required": ["category", "text"], "properties": {
            "category": {"type": "string", "enum": list(MEMORY_CATEGORIES)},
            "text": {"type": "string", "maxLength": 200}}}},
    "forget": {
        "description": "The person said \"don't remember that\" (scope last) or wants everything forgotten (all).",
        "executor": "cloud", "surfaces": _ALL,
        "parameters": {"type": "object", "required": ["scope"], "properties": {
            "scope": {"type": "string", "enum": ["last", "all"]}}}},
    "recall": {
        "description": "Look up to 3 things the person told Kaiku before about a topic.",
        "executor": "cloud", "surfaces": _ALL,
        "parameters": {"type": "object", "required": ["topic"], "properties": {"topic": {"type": "string"}}}},
    "suggest_nudge": {
        "description": "Get today's one small suggestion (phrase it, never change it).",
        "executor": "cloud", "surfaces": _ALL, "parameters": _EMPTY},
    "ask_mind": {
        "description": "Ask Kaiku's mind when unsure, when you need a fact the person told you before, or for a care "
                       "or hard emotional question. Returns an answer to say in your own words (may say to ask the "
                       "person or the care team). kind: fact | care | memory | plan | emotional.",
        "executor": "cloud", "surfaces": _ALL,
        "parameters": {"type": "object", "required": ["question", "kind"], "properties": {
            "question": {"type": "string", "maxLength": 300},
            "kind": {"type": "string", "enum": list(get_args(MindKind))}}}},
    "send_friend_ping": {
        "description": "Light the friend's lamp.",
        "executor": "device", "surfaces": ["robot", "iphone"], "parameters": _EMPTY},
    "start_phq9": {
        "description": "Start the two-weekly questionnaire (read items verbatim; code scores it).",
        "executor": "device", "surfaces": ["robot", "iphone", "mac", "web"], "parameters": _EMPTY},
    "express": {
        "description": "Show a feeling on Kaiku's face and body.",
        "executor": "device", "surfaces": _ALL,
        "parameters": {"type": "object", "required": ["feeling"], "properties": {
            "feeling": {"type": "string", "enum": list(get_args(Feeling))}}}},
    "end_session": {
        "description": "Close the session politely. Optionally leave one open thread to pick up next time on any "
                       "device (e.g. skill walk_companion, topic \"the walk by the lake\").",
        "executor": "cloud", "surfaces": _ALL,
        "parameters": {"type": "object", "properties": {
            "outcome": {"type": "string", "enum": ["completed", "skipped", "ended_early"]},
            "follow_up": {"type": "object", "required": ["skill", "topic"], "properties": {
                "skill": {"type": "string", "enum": list(SKILLS)},
                "topic": {"type": "string", "maxLength": 80}}}}}},
    "look_at_this": {
        "description": "Ask for ONE camera frame from the glasses (only while the person holds the tap).",
        "executor": "device", "surfaces": ["glasses"], "parameters": _EMPTY},
}

assert all(set(t["surfaces"]) <= set(SURFACES) for t in TOOLS.values())


def for_surface(surface: str) -> list[dict[str, Any]]:
    """Function declarations ({name, description, parameters}) the model may use on this surface, registry order."""
    if surface not in SURFACES:
        raise KeyError(f"unknown surface {surface!r}")
    return [{"name": n, "description": t["description"], "parameters": t["parameters"]}
            for n, t in TOOLS.items() if surface in t["surfaces"]]


def allowed(name: str, surface: str) -> bool:
    return name in TOOLS and surface in TOOLS[name]["surfaces"]


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """Tiny JSON-schema subset check (object, required, enum, string, integer, min/max, maxLength, nested object).
    Returns problems (empty = valid)."""
    problems: list[str] = []
    if not isinstance(args, dict):
        return ["args not an object"]
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in args:
            problems.append(f"missing {key}")
    for key, val in args.items():
        spec = props.get(key)
        if spec is None:
            problems.append(f"unknown arg {key}")
            continue
        t = spec.get("type")
        if t == "object":
            problems += [f"{key}.{p}" for p in validate_args(spec, val)]
            continue
        if t == "integer" and (isinstance(val, bool) or not isinstance(val, int | float) or int(val) != val):
            problems.append(f"{key} not integer")
            continue
        if t == "string" and not isinstance(val, str):
            problems.append(f"{key} not string")
            continue
        if "enum" in spec and val not in spec["enum"]:
            problems.append(f"{key}={val!r} not in enum")
        if "minimum" in spec and val < spec["minimum"] or "maximum" in spec and val > spec["maximum"]:
            problems.append(f"{key}={val} out of range")
        if "maxLength" in spec and isinstance(val, str) and len(val) > spec["maxLength"]:
            problems.append(f"{key} too long")
    return problems


def export() -> dict[str, Any]:
    """JSON for non-Python clients (contracts/schemas/companion_tools.json)."""
    return {"surfaces": list(SURFACES), "intents": list(INTENTS), "skills": list(SKILLS),
            "skill_of_intent": SKILL_OF_INTENT, "memory_categories": list(MEMORY_CATEGORIES), "tools": TOOLS}
