"""Small helpers shared by the tools (raw aiomqtt access: tools must see invalid messages too)."""

from __future__ import annotations

import json
import os
from typing import Any

from kaiku_contracts.config import load_dotenv


def mqtt_kwargs() -> dict[str, Any]:
    load_dotenv()
    return {
        "hostname": os.environ.get("MQTT_HOST", "localhost"),
        "port": int(os.environ.get("MQTT_PORT", 1883)),
        "username": os.environ.get("MQTT_USER") or None,
        "password": os.environ.get("MQTT_PASS") or None,
    }


def decode(payload: Any) -> Any:
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    try:
        return json.loads(payload)
    except (TypeError, ValueError):
        return payload


TRACE_TYPE = "raw.hub.trace"


def without_trace_text(topic: str, msg: Any) -> Any | None:
    """What a recording may keep of a message. `raw.hub.trace` carries what Kaiku said, for the apps' live "Kaiku
    bot" tab; nothing stores those words: its `text` is dropped and only the kind and the machine words stay. A
    message on that topic that cannot be read as one is not kept at all (None). Everything else: unchanged."""
    on_trace_topic = topic.split("/")[3:] == ["raw", "hub", "trace"]
    if not isinstance(msg, dict):
        return None if on_trace_topic else msg
    if not on_trace_topic and msg.get("type") != TRACE_TYPE:
        return msg
    payload = msg.get("payload")
    if not isinstance(payload, dict):
        return None
    return {**msg, "payload": {k: v for k, v in payload.items() if k != "text"}}
