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
