"""Companion tool schemas (plan 03 §4) used by the evals.

Ground truth will be `kaiku_contracts/companion_tools.py` (workstream I1). Until it exists this local copy is
used; once it does, `load()` prefers it so evals test what the cloud really serves.
"""

from __future__ import annotations

from typing import Any

_EMPTY: dict[str, Any] = {"type": "object", "properties": {}}

TOOLS: dict[str, dict[str, Any]] = {
    "record_dial": {"description": "Record the person's 1-5 answer to a dial question.",
                    "parameters": {"type": "object", "required": ["item", "value"], "properties": {
                        "item": {"type": "string", "enum": ["mood", "energy", "sleep"]},
                        "value": {"type": "integer", "minimum": 1, "maximum": 5}}}},
    "start_activity": {"description": "Start a short activity on this device (the device runs it).",
                       "parameters": {"type": "object", "required": ["kind"], "properties": {
                           "kind": {"type": "string",
                                    "enum": ["breathe", "drum", "firefly", "tell", "walk", "light_hunt"]}}}},
    "log_walk_moment": {"description": "The person found something on the light hunt (e.g. something green).",
                        "parameters": {"type": "object", "required": ["kind"], "properties": {
                            "kind": {"type": "string"}}}},
    "remember": {"description": "Propose keeping a short fact the person agreed to share.",
                 "parameters": {"type": "object", "required": ["category", "text"], "properties": {
                     "category": {"type": "string",
                                  "enum": ["name", "people", "places", "likes", "what_helps", "plans"]},
                     "text": {"type": "string"}}}},
    "recall": {"description": "Look up up to 3 things the person told Kaiku before.",
               "parameters": {"type": "object", "required": ["topic"], "properties": {"topic": {"type": "string"}}}},
    "suggest_nudge": {"description": "Get today's one small suggestion (phrase it, never change it).",
                      "parameters": _EMPTY},
    "send_friend_ping": {"description": "Light the friend's lamp.", "parameters": _EMPTY},
    "start_phq9": {"description": "Start the two-weekly questionnaire (read items verbatim; code scores it).",
                   "parameters": _EMPTY},
    "express": {"description": "Show a feeling on Kaiku's face and body.",
                "parameters": {"type": "object", "required": ["feeling"], "properties": {
                    "feeling": {"type": "string", "enum": ["happy", "curious", "sleepy", "cozy", "proud"]}}}},
    "end_session": {"description": "Close the session politely.", "parameters": _EMPTY},
    "look_at_this": {"description": "Ask for ONE camera frame from the glasses (person holds the tap).",
                     "parameters": _EMPTY},
}


def load() -> dict[str, dict[str, Any]]:
    try:  # pragma: no cover - depends on workstream I1
        from kaiku_contracts import companion_tools  # type: ignore[attr-defined]

        reg = getattr(companion_tools, "TOOLS", None)
        if isinstance(reg, dict) and reg:
            return reg
    except ImportError:
        pass
    return TOOLS


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """Tiny JSON-schema subset check (object, required, enum, string, integer, min/max). Returns problems."""
    problems: list[str] = []
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
        if t == "integer" and (not isinstance(val, int | float) or int(val) != val):
            problems.append(f"{key} not integer")
            continue
        if t == "string" and not isinstance(val, str):
            problems.append(f"{key} not string")
            continue
        if "enum" in spec and val not in spec["enum"]:
            problems.append(f"{key}={val!r} not in enum")
        if "minimum" in spec and val < spec["minimum"] or "maximum" in spec and val > spec["maximum"]:
            problems.append(f"{key}={val} out of range")
    return problems
