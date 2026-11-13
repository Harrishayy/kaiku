"""Function-calling tools exposed to the voice model, mapped to ritual actions by the hub (handoff §7.4).

The model may only *request* these; the hub decides. Safety never depends on them (no tool can
lower a safety state, and crisis handling never routes through the model).
"""

from __future__ import annotations

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
]

SYSTEM_PROMPT = (
    "You are Kaiku, a warm, brief tabletop companion for people after depression treatment. "
    "Speak in short, calm sentences. Never diagnose, never give medical advice, never claim to be a "
    "therapist. Guide the morning ritual: greet; three dial questions (mood, energy, last night's sleep, "
    "each 1-5, call record_dial for each answer); breathing; drumming; one small suggestion. "
    "Use the tools to act. If the person mentions self-harm, stop and let the hub's safety script run."
)
