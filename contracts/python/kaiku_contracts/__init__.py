"""Kaiku message contracts. The ONLY code modules may share.

Quick use:
    from kaiku_contracts import make, validate, topic_for, to_json
    from kaiku_contracts.payloads import DrumSession

    env = make("obs.drum_session", DrumSession(tempo_bpm=96, force_mean=.5, duration_s=40,
               regularity=.8, taps=60), source="hub")
    client.publish(topic_for(env), to_json(env))
    env2 = validate(incoming_bytes)          # raises ContractError if invalid
"""

from . import api, companion_tools, criteria, payloads, sources, wording
from .envelope import SCHEMA_VERSION, SOURCES, Envelope, default_home_id, make, utcnow, uuid7
from .registry import (
    CMD,
    EXAMPLES,
    OBS,
    RAW,
    REGISTRY,
    UPLINKABLE,
    ContractError,
    example,
    payload_model,
    to_json,
    validate,
)
from .sources import CONSENSUS_SOURCES, SOURCE_OF, consensus_source
from .topics import (
    PREFIX,
    ParsedTopic,
    audio_topic,
    is_audio_topic,
    parse_topic,
    qos_for,
    retain_for,
    topic,
    topic_for,
)

__all__ = [
    "api", "companion_tools", "criteria", "wording", "payloads", "sources", "CONSENSUS_SOURCES", "SOURCE_OF", "consensus_source", "SCHEMA_VERSION", "SOURCES", "Envelope", "default_home_id", "make", "utcnow",
    "uuid7", "CMD", "EXAMPLES", "OBS", "RAW", "REGISTRY", "UPLINKABLE", "ContractError", "example",
    "payload_model", "to_json", "validate", "PREFIX", "ParsedTopic", "parse_topic", "qos_for",
    "retain_for", "topic", "topic_for", "audio_topic", "is_audio_topic",
]
