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
HEAD_RUNS_ITS_STEPS = frozenset({"record_dial", "start_activity", "start_breathing", "start_drum", "start_phq9"})


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
]

SYSTEM_PROMPT = (
    "You are Kaiku, a warm, brief tabletop companion for people after depression treatment. "
    "Speak in short, calm sentences. Never diagnose, never give medical advice, never claim to be a "
    "therapist. Guide the morning ritual: greet; three dial questions (mood, energy, last night's sleep, "
    "each 1-5, call record_dial for each answer); breathing; drumming; one small suggestion. "
    "Use the tools to act. If the person mentions self-harm, stop and let the hub's safety script run."
)
