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


def with_ask_twice(tools: list[dict]) -> list[dict]:
    """The follow-mode tool list plus the ask-twice `start_activity`, in the list's own shape."""
    if any(isinstance(t, dict) and "function_declarations" in t for t in tools):
        return [*tools, {"function_declarations": [ASK_TWICE_TOOL]}]
    return [*tools, ASK_TWICE_TOOL]


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
