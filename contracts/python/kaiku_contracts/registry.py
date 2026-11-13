"""Type registry: message type -> payload model, plus validate() and one example per type."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from . import payloads as p
from .envelope import Envelope

OBS: dict[str, type[BaseModel]] = {
    "obs.presence": p.Presence,
    "obs.self_report": p.SelfReport,
    "obs.hrv_session": p.HrvSession,
    "obs.drum_session": p.DrumSession,
    "obs.light_level": p.LightLevel,
    "obs.speech_features": p.SpeechFeatures,
    "obs.ritual": p.Ritual,
    "obs.nudge_offered": p.NudgeOffered,
    "obs.nudge_outcome": p.NudgeOutcome,
    "obs.outing": p.Outing,
    "obs.friend_link": p.FriendLink,
    "obs.laptop_session": p.LaptopSession,
    "obs.phq9": p.Phq9,
    "obs.intervention_response": p.InterventionResponse,
    "obs.safety_flag": p.SafetyFlag,
}

RAW: dict[str, type[BaseModel]] = {
    "raw.head.tap": p.RawTap,
    "raw.head.ear": p.RawEar,
    "raw.head.pan": p.RawPan,
    "raw.sensors.ppg": p.RawPpg,
    "raw.sensors.distance": p.RawDistance,
    "raw.sensors.light": p.RawLight,
    "raw.sensors.button": p.RawButton,
    "raw.sensors.hall": p.RawHall,
    "raw.hub.face": p.RawFace,
}

CMD: dict[str, type[BaseModel]] = {
    "cmd.head": p.HeadCmd,
    "cmd.sensors": p.SensorsCmd,
    "cmd.friendlink": p.FriendlinkCmd,
    "cmd.hub": p.HubCmd,
}

OTHER: dict[str, type[BaseModel]] = {"health": p.Health, "log": p.Log}

REGISTRY: dict[str, type[BaseModel]] = {**OBS, **RAW, **CMD, **OTHER}

# Only these types may ever leave the home (cloud rejects everything else).
UPLINKABLE: frozenset[str] = frozenset(OBS)


class ContractError(ValueError):
    """Raised when a message violates the contract."""


def payload_model(type_: str) -> type[BaseModel]:
    try:
        return REGISTRY[type_]
    except KeyError:
        raise ContractError(f"unknown message type {type_!r}") from None


def validate(msg: dict[str, Any] | str | bytes | Envelope[Any]) -> Envelope[Any]:
    """Validate a message (dict, JSON text, or Envelope). Returns Envelope with a typed payload."""
    try:
        if isinstance(msg, Envelope):
            msg = msg.model_dump(mode="json")
        if isinstance(msg, (str, bytes, bytearray)):
            env = Envelope[dict].model_validate_json(msg)
        else:
            env = Envelope[dict].model_validate(msg)
        model = payload_model(env.type)
        typed = model.model_validate(env.payload)
        return Envelope[model].model_validate({**env.model_dump(), "payload": typed})  # type: ignore[valid-type]
    except ValidationError as e:
        raise ContractError(str(e)) from e


def to_json(env: Envelope[Any]) -> str:
    return env.model_dump_json(exclude_none=True)


# One valid example payload per type. Used by tests, sims, docs and the TS round-trip.
EXAMPLES: dict[str, dict[str, Any]] = {
    "obs.presence": {"distance_cm": 62.0, "first_of_day": True, "dwell_s": 14.0},
    "obs.self_report": {"item": "mood", "value": 3, "context": "ritual"},
    "obs.hrv_session": {"hr_bpm": 68.0, "rmssd_pre_ms": 31.0, "rmssd_post_ms": 42.0, "duration_s": 90.0, "breath_bpm": 6.0},
    "obs.drum_session": {"tempo_bpm": 96.0, "force_mean": 0.55, "duration_s": 45.0, "regularity": 0.8, "taps": 72},
    "obs.light_level": {"lux_est": 240.0, "window_min": 60.0},
    "obs.speech_features": {"syllables_per_s": 3.9, "pause_ratio": 0.22, "duration_s": 30.0},
    "obs.ritual": {"step": "drum", "status": "completed", "duration_s": 45.0},
    "obs.nudge_offered": {"arm": "daylight_walk", "reason": "Walks helped on 3 of your last 4 grey days."},
    "obs.nudge_outcome": {"arm": "daylight_walk", "accepted": True, "next_day": {"mood": 4, "energy": 3, "activity": 25.0}, "reward": 0.75},
    "obs.outing": {"minutes": 22.0, "steps": 2400, "method": "location"},
    "obs.friend_link": {"direction": "sent", "ack": True},
    "obs.laptop_session": {"speech_rate": 3.6, "pause_ratio": 0.24, "pitch_variability": 2.1, "expressivity_index": 0.55,
                           "reaction_ms_median": 312.0, "reaction_ms_iqr": 64.0, "lapses": 1, "duration_s": 118.0},
    "obs.phq9": {"total": 7, "items": [1, 1, 1, 1, 1, 1, 1, 0, 0], "item9_positive": False, "mode": "laptop"},
    "obs.intervention_response": {"activity": "breathe", "pre": {"rmssd_ms": 31.0, "mood": 3},
                                  "post": {"rmssd_ms": 42.0, "mood": 4}, "delta": {"rmssd_ms": 11.0, "mood": 1.0}},
    "obs.safety_flag": {"trigger": "manual", "severity": "high", "handled_locally": True},
    "raw.head.tap": {"t_ms": 123456, "force": 1.8, "src": "imu"},
    "raw.head.ear": {"value": 4, "delta": 1, "pressed": False},
    "raw.head.pan": {"deg": -12.5, "homed": True, "moving": False},
    "raw.sensors.ppg": {"t0_ms": 1000, "fs_hz": 100.0, "samples": [512, 530, 561, 590, 600]},
    "raw.sensors.distance": {"cm": 58.0},
    "raw.sensors.light": {"raw": 410, "lux_est": 210.0},
    "raw.sensors.button": {"id": "top", "pressed": True},
    "raw.sensors.hall": {"at_home": True},
    "raw.hub.face": {"x_norm": -0.2, "y_norm": 0.1, "size": 0.3, "confidence": 0.93},
    "cmd.head": {"eyes": "wide", "pan_mode": "track"},
    "cmd.sensors": {"ppg": "start"},
    "cmd.friendlink": {"ping": {"pattern": "glow"}},
    "cmd.hub": {"start_ritual": True},
    "health": {"status": "ok", "version": "0.1.0", "uptime_s": 12.0, "details": {}},
    "log": {"level": "warning", "event": "ppg_low_quality", "msg": "only 55% clean beats"},
}

assert set(EXAMPLES) == set(REGISTRY), "every registered type needs an example"


def example(type_: str, *, home_id: str = "demo-aino", source: str | None = None, sim: bool = True) -> Envelope[Any]:
    """A valid example envelope of the given type (handy in tests)."""
    if source is None:
        parts = type_.split(".")
        source = parts[1] if parts[0] == "raw" else ("hub" if parts[0] in ("obs", "health", "log") else "cloud")
    return validate({"home_id": home_id, "source": source, "type": type_, "payload": EXAMPLES[type_], "sim": sim})
