"""Function-calling tools exposed to the voice model, mapped to ritual actions by the hub (handoff §7.4).

The model may only *request* these; the hub decides. Safety never depends on them (no tool can
lower a safety state, and crisis handling never routes through the model).
"""

from __future__ import annotations

from kaiku_contracts.companion_tools import TOOLS as REGISTRY


def from_registry(name: str) -> dict:
    """A shared-registry tool as a function declaration (same shape the cloud bootstrap sends), incl. `behavior`."""
    t = REGISTRY[name]
    assert "robot" in t["surfaces"], f"{name} is not a robot tool"
    return {"name": name, "description": t["description"], "parameters": t["parameters"],
            **({"behavior": t["behavior"]} if t.get("behavior") else {})}


# A head that runs its own ritual (standalone firmware, follow mode) moves through its steps by itself and takes its
# dial answers from its own knob: these tools would promise the model something the hub cannot do there.
# `record_dial` is honoured there: she may answer a dial question in words or with the ear (the hub records the
# spoken answer and moves the head on). `start_activity` comes back as asking twice (below).
HEAD_RUNS_ITS_STEPS = frozenset({"start_activity", "start_breathing", "start_drum", "start_phq9"})


# Asking twice (D58): on a head that runs its own ritual the person can ask for an activity in words. The words alone
# start nothing: the hub arms the head and only a press of its ear inside ASK_TWICE_S starts it.
ASK_TWICE_S = 20.0
ASK_TWICE_KINDS: dict[str, str] = {"breathe": "the breathing", "drum": "the drums"}
ASK_TWICE_TOOL: dict = {
    "name": "start_activity",
    "description": "The person has just asked, in their own words, to do an activity with you now: breathe = slow "
                   "breathing together, drum = the drums (the rhythm game Tap it back). Calling this does NOT start "
                   "it: it gets the robot ready, and only a press of your ear in the next 20 seconds starts it. "
                   "Right after calling, say one short line that names the activity and asks them to press your ear "
                   "to start, for example \"The drums? Press my ear and we start.\" Call it only when they asked "
                   "for it or clearly said yes to your suggestion; never because you think it would do them good, "
                   "never for a maybe. If the result is not ok, tell them plainly it cannot start now and why. You "
                   "will be told if the ear was not pressed. Returns {ok, started: false, waiting_for, seconds}.",
    "parameters": {"type": "object", "required": ["kind"], "properties": {
        "kind": {"type": "string", "enum": list(ASK_TWICE_KINDS)}}},
}


# The camera, asked once per conversation (D61). The ROBOT asks, in a fixed line, when a conversation opens; the
# voice only reports the answer. It must never ask about the camera itself: that is how the question would come
# back every turn.
CAMERA_LINE = "Before we start: shall I have my camera on while we talk? Yes or no."
CAMERA_ON_LINE = "Camera on. Only numbers, never a picture."
CAMERA_OFF_LINE = "Okay, the camera stays off."
CAMERA_RING, REST_RING = "#28dc5a", "#ff8c28"  # the ear ring: green while the camera counts, orange at rest
CAMERA_WAIT_S = 12.0
CAMERA_TOOL: dict = {
    "name": "camera_choice",
    "description": "The robot itself has just asked, once, whether its camera may be on for this conversation. Call "
                   "this with their answer: on true for a clear yes, false for a no or anything unsure. It holds for "
                   "this whole conversation. NEVER ask about the camera yourself, not at the start and not later: "
                   "the robot asks once and only once. Call it again only if they bring it up themselves and ask "
                   "for the camera to be turned on or off. With the camera on, the robot counts smiles and how much "
                   "the face moves (numbers only, no picture), and photo time is possible. Returns {ok, camera}.",
    "parameters": {"type": "object", "required": ["on"], "properties": {"on": {"type": "boolean"}}},
}


# A visible change in expression during a conversation with the camera on (D60, the robot's part): one private
# context turn for the voice. A prompt to ask, never a conclusion.
EXPRESSION_CUE: dict[str, str] = {
    "lower": "For a little while their expression has looked lower than earlier in this conversation: they were "
             "smiling before and are not now. If it fits the moment, ask one short, open question about how they "
             "are doing right now. Do not say you saw their face or mention a camera; do not name a feeling for "
             "them; do not repeat this later.",
    "brighter": "For a little while they have been smiling. If it fits the moment, one warm, light remark or question "
                "is welcome. Do not say you saw their face or mention a camera; do not repeat this later.",
}

# Things she can ask the robot's body for in words (D62). Small and harmless, so one ask is enough.
LIGHT_COLOURS: dict[str, str] = {"white": "#ffffff", "orange": "#ff8c28", "yellow": "#ffd21e", "green": "#28dc5a",
                                 "blue": "#28a0ff", "purple": "#a050ff", "pink": "#ff5aa0", "red": "#ff2814"}
LIGHT_TOOL: dict = {
    "name": "set_light",
    "description": "Change the colour of the light ring on your ear because they asked for it (\"make your light "
                   "white\"). It stays that colour until they ask for another. While you are listening the ring "
                   "gently breathes in that colour. Returns {ok, colour}.",
    "parameters": {"type": "object", "required": ["colour"], "properties": {
        "colour": {"type": "string", "enum": list(LIGHT_COLOURS)}}},
}
TURN_TOOL: dict = {
    "name": "turn_head",
    "description": "Turn your head a little to their left or right because they asked (\"look this way\", \"turn "
                   "left\"). Your motor and your speaker never run together, so the head turns just after you stop "
                   "speaking: say a very short line or nothing. Left and right are as THEY see you. Returns {ok}.",
    "parameters": {"type": "object", "required": ["direction"], "properties": {
        "direction": {"type": "string", "enum": ["left", "right"]}}},
}


def with_ask_twice(tools: list[dict]) -> list[dict]:
    """The follow-mode tool list plus the hub's own tools there (the ask-twice `start_activity`, the camera
    answer), in the list's own shape."""
    if any(isinstance(t, dict) and "function_declarations" in t for t in tools):
        return [*tools, {"function_declarations": [ASK_TWICE_TOOL, CAMERA_TOOL, LIGHT_TOOL, TURN_TOOL]}]
    return [*tools, ASK_TWICE_TOOL, CAMERA_TOOL, LIGHT_TOOL, TURN_TOOL]


def without(tools: list[dict], names: frozenset[str] | set[str]) -> list[dict]:
    """The tool list minus some names, in either shape (plain declarations, or Gemini `function_declarations` blocks)."""
    out: list[dict] = []
    for t in tools:
        if isinstance(t, dict) and "function_declarations" in t:
            kept = [d for d in t["function_declarations"] if d.get("name") not in names]
            if kept:
                out.append({**t, "function_declarations": kept})
        elif not (isinstance(t, dict) and t.get("name") in names):
            out.append(t)
    return out


TOOLS: list[dict] = [
    {"name": "record_dial", "description": "Record the person's 1-5 answer to a dial question (mood, energy, "
     "or last night's sleep).",
     "parameters": {"type": "object", "properties": {
         "item": {"type": "string", "enum": ["mood", "energy", "sleep"]},
         "value": {"type": "integer", "minimum": 1, "maximum": 5}},
         "required": ["item", "value"]}},
    {"name": "start_breathing", "description": "Move on to the paced breathing step.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "start_drum", "description": "Move on to the drumming step.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "start_phq9", "description": "The person wants to do their two-weekly questionnaire now.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "suggest_nudge", "description": "Move on to today's one small suggestion.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "send_friend_ping", "description": "Light the friend's lamp via the friend link.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "end_ritual", "description": "End today's ritual politely.", "parameters": {"type": "object", "properties": {}}},
    # Notice and act (cloud `feel`): the companion reports a clear feeling or news and gets back how to meet it.
    # Declared from the shared registry, NON_BLOCKING: Kaiku keeps listening and talking while it runs.
    from_registry("feel"),
    # An activity agreed with the robot shows up on the phone and Mac at once (cloud `agree_activity`, D50): the
    # robot has no screen for games, the journal or a walk, so a clear yes is forwarded and the cloud keeps it.
    from_registry("agree_activity"),
    # Photo time: the sensors board counts face signs for a few seconds (rituals/photo_time.py). No picture.
    from_registry("photo_time"),
]

SYSTEM_PROMPT = (
    "You are Kaiku, a warm, brief tabletop companion for people after depression treatment. "
    "Speak in short, calm sentences. Never diagnose, never give medical advice, never claim to be a "
    "therapist. Guide the morning ritual: greet; three dial questions (mood, energy, last night's sleep, "
    "each 1-5, call record_dial for each answer); breathing; drumming; one small suggestion. "
    "Use the tools to act. If the person mentions self-harm, stop and let the hub's safety script run."
)
