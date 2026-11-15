"""MQTT topic helpers. Topic layout: kaiku/v1/<home_id>/<kind>/<name...>."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .envelope import Envelope

PREFIX = "kaiku/v1"
Kind = Literal["raw", "obs", "cmd", "health", "log"]

# QoS / retain per kind (section 5.2 of docs/plans/01-foundation.md)
QOS: dict[str, int] = {"raw": 0, "obs": 1, "cmd": 1, "health": 1, "log": 0}
RETAIN: dict[str, bool] = {"raw": False, "obs": False, "cmd": False, "health": True, "log": False}


# Binary audio between the hub and the robot head, OUTSIDE the envelope families (plan 07 section 4): raw PCM, never
# an envelope, never an observation. Nothing may store, log, record, tail or uplink it (root rules 5 and 9).
#   kaiku/v1/<home>/audio/head/speaker   hub -> head: what the head's speaker plays (music, chimes, Kaiku's voice)
#   kaiku/v1/<home>/audio/head/mic       head -> hub: the head's microphone, only while `cmd.head {mic: open}` holds
#   kaiku/v1/<home>/audio/phone/mic      app -> hub: a phone or Mac beside the robot standing in for it (D56), same rule
# One message = AUDIO_FRAME_MS of signed 16-bit little-endian mono at AUDIO_RATE_HZ. A zero-length message on the
# speaker topic means "drop what you have buffered, now". QoS 0, not retained.
AUDIO = "audio"
AUDIO_RATE_HZ = 16_000
AUDIO_FRAME_MS = 20
AUDIO_FRAME_SAMPLES = AUDIO_RATE_HZ * AUDIO_FRAME_MS // 1000  # 320
AUDIO_FRAME_BYTES = AUDIO_FRAME_SAMPLES * 2  # 640
AUDIO_STREAMS: tuple[str, ...] = ("speaker", "mic")


def audio_topic(home_id: str, stream: str = "speaker", node: str = "head") -> str:
    """audio_topic("demo-aino") -> "kaiku/v1/demo-aino/audio/head/speaker"."""
    if stream not in AUDIO_STREAMS:
        raise ValueError(f"no such audio stream: {stream!r} (one of {', '.join(AUDIO_STREAMS)})")
    return f"{PREFIX}/{home_id}/{AUDIO}/{node}/{stream}"


def is_audio_topic(t: str) -> bool:
    """True for a binary audio topic: its payload is PCM, not a message. Every tool that walks topics skips these."""
    parts = t.split("/")
    return len(parts) >= 4 and "/".join(parts[:2]) == PREFIX and parts[3] == AUDIO


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
