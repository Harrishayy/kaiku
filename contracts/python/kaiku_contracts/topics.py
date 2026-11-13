"""MQTT topic helpers. Topic layout: kaiku/v1/<home_id>/<kind>/<name...>."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .envelope import Envelope

PREFIX = "kaiku/v1"
Kind = Literal["raw", "obs", "cmd", "health", "log"]

# QoS / retain per kind (section 5.2 of handoff.md)
QOS: dict[str, int] = {"raw": 0, "obs": 1, "cmd": 1, "health": 1, "log": 0}
RETAIN: dict[str, bool] = {"raw": False, "obs": False, "cmd": False, "health": True, "log": False}


def topic(home_id: str, kind: Kind, name: str = "#") -> str:
    """topic("demo-aino", "raw", "head/tap") -> "kaiku/v1/demo-aino/raw/head/tap"."""
    return f"{PREFIX}/{home_id}/{kind}/{name}"


def topic_for(env: Envelope[Any]) -> str:
    """The topic an envelope must be published on (derived from its type)."""
    kind, _, rest = env.type.partition(".")
    if kind in ("health", "log"):
        return topic(env.home_id, kind, env.source)  # type: ignore[arg-type]
    if kind not in ("raw", "obs", "cmd"):
        raise ValueError(f"cannot derive topic for type {env.type!r}")
    return topic(env.home_id, kind, rest.replace(".", "/"))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ParsedTopic:
    home_id: str
    kind: str
    name: str  # e.g. "head/tap", "drum_session", "head"

    @property
    def type(self) -> str:
        """Message type expected on this topic (health/log -> 'health'/'log')."""
        if self.kind in ("health", "log"):
            return self.kind
        return f"{self.kind}.{self.name.replace('/', '.')}"


def parse_topic(t: str) -> ParsedTopic:
    parts = t.split("/")
    if len(parts) < 5 or "/".join(parts[:2]) != PREFIX:
        raise ValueError(f"not a kaiku topic: {t!r}")
    return ParsedTopic(home_id=parts[2], kind=parts[3], name="/".join(parts[4:]))


def qos_for(env_or_type: Envelope[Any] | str) -> int:
    t = env_or_type if isinstance(env_or_type, str) else env_or_type.type
    return QOS[t.split(".")[0]]


def retain_for(env_or_type: Envelope[Any] | str) -> bool:
    t = env_or_type if isinstance(env_or_type, str) else env_or_type.type
    return RETAIN[t.split(".")[0]]
