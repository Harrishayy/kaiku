"""Companion tool registry (plan 03 §4) — ground truth for every tool a Kaiku conversation may request.

The model *requests*; the device or cloud *decides*. Every tool here has a JSON-schema `parameters` block (Gemini
function-declaration shape) and the surfaces it may be used on. `make contracts` exports it to
`contracts/schemas/companion_tools.json` (+ `COMPANION_TOOLS` in `contracts/ts/index.ts`) for Swift/TS clients.

Who executes what (`executor`):
    cloud   remember, forget, recall, suggest_nudge, end_session, ask_mind, feel, agree_activity — devices forward the call to
            `POST /v1/companion/tool` and hand the result back to the model
    device  record_dial, start_activity, suggest_activity, set_walk_goal, log_walk_moment, send_friend_ping,
            start_phq9, express, look_at_this — the device runs the deterministic effect (it may still forward
            the call so the episode logs it). Result shapes the device returns: api.ActivityCardResult
            (suggest_activity), api.WalkGoalResult (set_walk_goal), api.WalkMomentResult (log_walk_moment).
`walk_only_on`: surfaces where a tool is served only in a walk session (purpose or intent `walk`).
`behavior: NON_BLOCKING` (Gemini Live asynchronous function calling): the model keeps talking while the tool runs;
the device declares the function with that behaviour and answers with the `scheduling` the result carries.
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
# Screens a conversation can lead to. `tell` is the journal entry "Tell Kaiku"; lantern, seeds, watering, pebbles and
# firefly are the games on the phone and Mac; drum is the robot's; light_hunt is the walk's spotting game.
# Which of them a surface really has: `activities` in config/surfaces.toml.
Activity = Literal["breathe", "tell", "walk", "lantern", "seeds", "watering", "pebbles", "firefly", "drum", "light_hunt"]
ACTIVITIES: tuple[str, ...] = get_args(Activity)
# How Kaiku walks with the person (CompanionSessionRequest.walk_style; what each means: config/persona.md
# "Walking together"; limits and nudge timings per style: config/surfaces.toml and config/kaiku.toml [walk]).
WalkStyle = Literal["quiet", "playful", "chatty"]
WALK_STYLES: tuple[str, ...] = get_args(WalkStyle)
# An activity the person said yes to somewhere else than where it is done (`agree_activity`): do they want it
# now, on another device, or later today? What an agreed activity is: docs/decisions.md D50.
AgreeWhen = Literal["now", "later"]
AGREE_WHEN: tuple[str, ...] = get_args(AgreeWhen)
Feeling = Literal["happy", "curious", "sleepy", "cozy", "proud"]
MindKind = Literal["fact", "care", "memory", "plan", "emotional"]
# How a moment sounded, as a model in the conversation reports it (an observation, never a measurement or a state).
Valence = Literal["low", "neutral", "bright"]
VALENCES: tuple[str, ...] = get_args(Valence)
Energy = Literal["low", "medium", "high"]
ENERGIES: tuple[str, ...] = get_args(Energy)
Tone = Literal["flat", "tense", "tearful", "irritable", "warm", "playful", "calm"]
TONES: tuple[str, ...] = get_args(Tone)
FeelKind = Literal["sad_news", "good_news", "flat", "angry", "worried", "lonely", "proud", "relief", "other"]
FEEL_KINDS: tuple[str, ...] = get_args(FeelKind)
Purpose = Literal["talk", "check_in", "walk", "ritual"]
CheckinItem = Literal["mood", "energy", "sleep"]
CHECKIN_ITEMS: tuple[str, ...] = get_args(CheckinItem)

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
    "suggest_activity": {
        "description": "Put one card in the conversation that leads to an activity's screen: a game, the journal "
                       "entry (tell), breathing or a walk. Call it in the same turn in which you suggest that "
                       "activity. It opens nothing: the person taps the card or says yes. One card at a time; "
                       "after a no, none again in this conversation. Returns {ok, shown}.",
        "executor": "device", "surfaces": ["iphone", "mac"],
        "parameters": {"type": "object", "required": ["kind"], "properties": {
            "kind": {"type": "string", "enum": list(ACTIVITIES)},
            "line": {"type": "string", "maxLength": 80}}}},
    "agree_activity": {
        "description": "The person has just clearly said yes to doing an activity that is not starting right here "
                       "and now on this device: a game or the journal entry (tell) agreed while talking with the "
                       "robot or on a walk, a walk agreed for later. Call it once, with the kind and, in `said`, "
                       "their own words of that yes. It puts the activity on their phone and Mac straight away. "
                       "Then say where it is in a few words, the way the result's `where` gives it (\"It's on your "
                       "phone and your Mac.\"). Not for a maybe, a hesitation or a silence; not when "
                       "`start_activity` starts it here or a card already shows it on this screen; never the "
                       "questionnaire. If the result says nothing was kept, do not say it is anywhere. when: now "
                       "(they want it now, on another device) or later (default now). line: optional, the few "
                       "words you would put on the reminder. Returns {agreed, name, where, on, already}.",
        "executor": "cloud", "surfaces": _ALL,
        "parameters": {"type": "object", "required": ["kind"], "properties": {
            "kind": {"type": "string", "enum": list(ACTIVITIES)},
            "said": {"type": "string", "maxLength": 300},
            "line": {"type": "string", "maxLength": 80},
            "when": {"type": "string", "enum": list(AGREE_WHEN)}}}},
    "set_walk_goal": {
        "description": "Start one small spotting game on the walk: `target` of `thing` to find, something that is "
                       "really around (from what they said or what is in view). Call it FIRST, the moment a game "
                       "is taken up: they said yes to the game you proposed, or simply reported a first find "
                       "after it. Use the thing and the target you proposed. Proposing a game sets nothing; "
                       "without this call there is no game and no count. The device keeps the count and returns "
                       "{thing, target, found, left}. One goal at a time; a new one replaces the old.",
        "executor": "device", "surfaces": ["glasses", "iphone"], "walk_only_on": ["iphone"],
        "parameters": {"type": "object", "required": ["thing", "target"], "properties": {
            "thing": {"type": "string", "maxLength": 30},
            "target": {"type": "integer", "minimum": 1, "maximum": 5}}}},
    "log_walk_moment": {
        "description": "One find in the spotting game: the person said they found one, or said yes to \"is that "
                       "one?\". Only after `set_walk_goal`: when a first find comes before the goal is set, call "
                       "`set_walk_goal` and then this, in that order. Exactly one call per find they tell you "
                       "about, never two for the same find. kind: what it was. Returns {ok, thing, found, "
                       "target, left, note}. Say how many are found or left only as this result gives it; if it "
                       "says no goal is set (`note`), set the goal and log the find again before saying a count.",
        "executor": "device", "surfaces": ["glasses", "iphone"], "walk_only_on": ["iphone"],
        "parameters": {"type": "object", "required": ["kind"], "properties": {"kind": {"type": "string"}}}},
    "remember": {
        "description": "Keep a short fact the person told you and wants kept (stored only if allowed; they can see "
                       "and delete it). Never health details. In a conversation always pass `said`: the person's "
                       "own words it comes from. Without it, or if it does not contain the fact, nothing is stored.",
        "executor": "cloud", "surfaces": _ALL,
        "parameters": {"type": "object", "required": ["category", "text"], "properties": {
            "category": {"type": "string", "enum": list(MEMORY_CATEGORIES)},
            "text": {"type": "string", "maxLength": 200},
            "said": {"type": "string", "maxLength": 300}}}},
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
        "description": "Ask Kaiku's shared Gemma mind for missing or conflicting personal knowledge, planning, care "
                       "or deeper emotional reasoning. Use prepared context directly when sufficient. Returns an answer to say in your own words (may say to ask the "
                       "person or the care team). kind: fact | care | memory | plan | emotional.",
        "executor": "cloud", "surfaces": _ALL,
        "parameters": {"type": "object", "required": ["question", "kind"], "properties": {
            "question": {"type": "string", "maxLength": 300},
            "kind": {"type": "string", "enum": list(get_args(MindKind))}}}},
    "feel": {
        "description": "Tell Kaiku's mind about a clear feeling or a piece of news in what the person just said or "
                       "how they sounded. Once per clear shift, never every turn; keep talking warmly while it "
                       "runs. Returns how to meet it for this person: stance, depth (brief = an ordinary moment, "
                       "keep the chat small; stay = do not close, stay as long as they want), one thing the "
                       "record knows (recall) and at most one small thing you may offer once (may_offer). "
                       "heard.via: voice when you heard them say it, text when it was typed. about: the topic in "
                       "a few words, the way you would say it to them (\"your sister's visit\", \"the library job\").",
        "executor": "cloud", "surfaces": _ALL, "behavior": "NON_BLOCKING",
        "parameters": {"type": "object", "required": ["kind", "heard"], "properties": {
            "kind": {"type": "string", "enum": list(FEEL_KINDS)},
            "heard": {"type": "object", "required": ["valence"], "properties": {
                "valence": {"type": "string", "enum": list(VALENCES)},
                "energy": {"type": "string", "enum": list(ENERGIES)},
                "tone": {"type": "array", "maxItems": 2, "items": {"type": "string", "enum": list(TONES)}},
                "via": {"type": "string", "enum": ["voice", "text"]}}},
            "about": {"type": "string", "maxLength": 80},
            "said": {"type": "string", "maxLength": 300}}}},
    "send_friend_ping": {
        "description": "Light the friend's lamp.",
        "executor": "device", "surfaces": ["robot"], "parameters": _EMPTY},
    "photo_time": {
        "description": "Photo time: the robot's camera counts smiles and how much the face moves for a few seconds. "
                       "No picture is taken or kept. Call it when the person says \"photo time\" or asks for it; "
                       "the robot says \"Photo time!\" itself, so say nothing until the result comes back.",
        "executor": "device", "surfaces": ["robot"], "parameters": _EMPTY},
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
        "description": "Check whether you can see through the glasses camera right now, and get one fresh picture "
                       "if you can. Only works while the person has turned on Let Kaiku see; otherwise the result "
                       "says you cannot see.",
        "executor": "device", "surfaces": ["glasses"], "parameters": _EMPTY},
}

assert all(set(t["surfaces"]) <= set(SURFACES) for t in TOOLS.values())


def for_surface(surface: str, walk: bool | None = None) -> list[dict[str, Any]]:
    """Function declarations ({name, description, parameters}) the model may use on this surface, registry order.
    `walk`: is this a walk session? None = every tool the surface can ever serve (what `allowed` checks)."""
    if surface not in SURFACES:
        raise KeyError(f"unknown surface {surface!r}")
    return [{"name": n, "description": t["description"], "parameters": t["parameters"]}
            | ({"behavior": t["behavior"]} if t.get("behavior") else {})
            for n, t in TOOLS.items()
            if surface in t["surfaces"] and (walk is not False or surface not in t.get("walk_only_on", ()))]


def allowed(name: str, surface: str) -> bool:
    return name in TOOLS and surface in TOOLS[name]["surfaces"]


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """Tiny JSON-schema subset check (object, required, enum, string, integer, min/max, maxLength, nested object,
    array of enum strings with maxItems). Returns problems (empty = valid)."""
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
        if t == "array":
            item = spec.get("items", {})
            if not isinstance(val, list):
                problems.append(f"{key} not array")
            elif len(val) > spec.get("maxItems", len(val)):
                problems.append(f"{key} has too many items")
            elif any(not isinstance(v, str) or "enum" in item and v not in item["enum"] for v in val):
                problems.append(f"{key} has an item outside its enum")
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
            "skill_of_intent": SKILL_OF_INTENT, "memory_categories": list(MEMORY_CATEGORIES),
            "activities": list(ACTIVITIES), "walk_styles": list(WALK_STYLES),
            "agree_when": list(AGREE_WHEN), "tools": TOOLS}
