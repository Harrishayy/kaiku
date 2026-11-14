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
    "obs.tap_back": p.TapBack,
    "obs.light_level": p.LightLevel,
    "obs.speech_features": p.SpeechFeatures,
    "obs.engagement": p.Engagement,
    "obs.ritual": p.Ritual,
    "obs.nudge_offered": p.NudgeOffered,
    "obs.nudge_outcome": p.NudgeOutcome,
    "obs.outing": p.Outing,
    "obs.friend_link": p.FriendLink,
    "obs.laptop_session": p.LaptopSession,
    "obs.screen_activity": p.ScreenActivity,
    "obs.play_session": p.PlaySession,
    "obs.face_signs": p.FaceSigns,
    "obs.wearable_daily": p.WearableDaily,
    "obs.phq9": p.Phq9,
    "obs.intervention_response": p.InterventionResponse,
    "obs.safety_flag": p.SafetyFlag,
}

RAW: dict[str, type[BaseModel]] = {
    "raw.head.tap": p.RawTap,
    "raw.head.ear": p.RawEar,
    "raw.head.pan": p.RawPan,
    "raw.head.button": p.RawButton,
    "raw.sensors.ppg": p.RawPpg,
    "raw.sensors.distance": p.RawDistance,
    "raw.sensors.light": p.RawLight,
    "raw.sensors.button": p.RawButton,
    "raw.sensors.hall": p.RawHall,
    "raw.hub.face": p.RawFace,
    "raw.hub.trace": p.HubTrace,
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
    "obs.self_report": {"item": "mood", "value": 3, "context": "ritual", "channel": "robot"},
    "obs.hrv_session": {"hr_bpm": 68.0, "rmssd_pre_ms": 31.0, "rmssd_post_ms": 42.0, "duration_s": 90.0, "breath_bpm": 6.0},
    "obs.drum_session": {"tempo_bpm": 96.0, "force_mean": 0.55, "duration_s": 45.0, "regularity": 0.8, "taps": 72},
    "obs.tap_back": {"levels": [
        {"level": 1, "target_bpm": 102.0, "tapped_bpm": 100.4, "error_pct": 1.6, "steadiness": 0.95, "taps": 8,
         "band": "perfect", "tries": 1, "beat": "beat"},
        {"level": 2, "target_bpm": 124.0, "tapped_bpm": 132.5, "error_pct": 6.9, "steadiness": 0.92, "taps": 8,
         "band": "great", "tries": 1, "beat": "beat"},
        {"level": 3, "target_bpm": 74.0, "tapped_bpm": 76.1, "error_pct": 2.8, "steadiness": 0.94, "taps": 12,
         "band": "perfect", "tries": 2, "beat": "beat"}],
        "levels_played": 3, "levels_passed": 3, "error_pct": 3.8, "steadiness": 0.94, "taps": 40, "rejected_taps": 0,
        "duration_s": 78.0, "song": "music"},
    "obs.light_level": {"lux_est": 240.0, "window_min": 60.0},
    "obs.speech_features": {"syllables_per_s": 3.9, "pause_ratio": 0.22, "duration_s": 30.0},
    "obs.engagement": {"session_id": "0199b2c4-ritual", "level": 0.58, "confidence": 0.71, "cues_available": 3,
                       "agreement": 0.8, "method": "robot-multicue-v1", "cues": [
                           {"cue": "dial", "available": True, "level": 0.5, "confidence": 1.0, "basis": "mood 3, energy 3"},
                           {"cue": "drum", "available": True, "level": 0.6, "confidence": 0.9, "basis": "1.8 taps/s, 41 taps"},
                           {"cue": "face", "available": True, "level": 0.7, "confidence": 0.6, "basis": "face in view 70% of 240 looks"},
                           {"cue": "pulse", "available": False, "confidence": 0.0, "basis": "not measured"}]},
    "obs.ritual": {"step": "drum", "status": "completed", "duration_s": 45.0},
    "obs.nudge_offered": {"arm": "daylight_walk", "reason": "Walks helped on 3 of your last 4 grey days."},
    "obs.nudge_outcome": {"arm": "daylight_walk", "accepted": True, "next_day": {"mood": 4, "energy": 3, "activity": 25.0}, "reward": 0.75},
    "obs.outing": {"minutes": 22.0, "steps": 2400, "method": "dat_imu", "cadence_spm": 104.0, "gait_regularity": 0.82,
                   "head_up_ratio": 0.64},
    "obs.friend_link": {"direction": "sent", "ack": True},
    "obs.laptop_session": {"speech_rate": 3.6, "pause_ratio": 0.24, "pitch_variability": 2.1, "expressivity_index": 0.55,
                           "reaction_ms_median": 312.0, "reaction_ms_iqr": 64.0, "lapses": 1, "duration_s": 118.0},
    "obs.screen_activity": {"period_min": 60.0, "active_min": 41.0, "late_night_min": 0.0,
                            "category_min": {"work": 22.0, "communication": 9.0, "social": 3.0, "video": 5.0, "news": 2.0,
                                             "games": 0.0, "other": 0.0},
                            "switches_per_hour": 18.0, "longest_stretch_min": 24.0, "breaks": 1, "paused": False},
    "obs.play_session": {"game": "firefly", "device": "phone", "duration_s": 60.0, "reaction_ms_median": 318.0,
                         "reaction_ms_iqr": 58.0, "lapses": 1, "false_taps": 0, "expressivity_index": 0.15,
                         "camera_face_coverage": 0.9, "camera_samples": 120, "camera_method": "vision_landmarks"},
    "obs.face_signs": {"task": "lantern", "device": "phone", "method": "arkit_blendshapes", "duration_s": 88.0,
                       "samples": 2640, "coverage": 0.94, "smile_share": 0.12, "smiles": 3, "brow_raise_share": 0.05,
                       "brow_furrow_share": 0.08, "mouth_open_share": 0.03, "blinks_per_min": 14.5,
                       "gaze_on_share": 0.91, "head_movement": 0.21, "expression_range": 0.34,
                       "ref": "0199b2c4-7c1e-7a55-9a3e-2f1d6b7c8e90"},
    "obs.wearable_daily": {"date": "2026-11-14", "sleep_min": 432.0, "sleep_midpoint_min": 195.0, "sleep_regularity": 0.81,
                           "resting_hr_bpm": 61.0, "hrv_sdnn_ms": 46.0, "steps": 6400, "exercise_min": 22.0,
                           "distance_km": 4.52, "daylight_min": 47.0, "walking_hr_bpm": 98.5,
                           "sleep_deep_min": 71.0, "sleep_rem_min": 96.0, "sleep_core_min": 265.0,
                           "sleep_awake_min": 34.0, "device": "apple_watch"},
    "obs.phq9": {"total": 7, "items": [1, 1, 1, 1, 1, 1, 1, 0, 0], "item9_positive": False, "mode": "laptop"},
    "obs.intervention_response": {"activity": "breathe", "pre": {"rmssd_ms": 31.0, "mood": 3},
                                  "post": {"rmssd_ms": 42.0, "mood": 4}, "delta": {"rmssd_ms": 11.0, "mood": 1.0}},
    "obs.safety_flag": {"trigger": "manual", "severity": "high", "handled_locally": True},
    "raw.head.tap": {"t_ms": 123456, "force": 1.8, "src": "imu"},
    "raw.head.ear": {"value": 4, "delta": 1, "pressed": False},
    "raw.head.pan": {"deg": -12.5, "homed": True, "moving": False},
    "raw.head.button": {"id": "head", "pressed": True},
    "raw.sensors.ppg": {"t0_ms": 1000, "fs_hz": 100.0, "samples": [512, 530, 561, 590, 600]},
    "raw.sensors.distance": {"cm": 58.0},
    "raw.sensors.light": {"raw": 410, "lux_est": 210.0},
    "raw.sensors.button": {"id": "top", "pressed": True},
    "raw.sensors.hall": {"at_home": True},
    "raw.hub.face": {"x_norm": -0.2, "y_norm": 0.1, "size": 0.3, "confidence": 0.93},
    "raw.hub.trace": {"kind": "said", "text": "How are you today?", "by": "live"},
    "cmd.head": {"eyes": "wide", "pan_mode": "track"},
    "cmd.sensors": {"ppg": "start"},
    "cmd.friendlink": {"ping": {"pattern": "glow"}},
    "cmd.hub": {"start_ritual": True},
    "health": {"status": "ok", "version": "0.1.0", "uptime_s": 12.0, "details": {}},
    "log": {"level": "warning", "event": "ppg_low_quality", "msg": "only 55% clean beats"},
}

assert set(EXAMPLES) == set(REGISTRY), "every registered type needs an example"

# One obs.play_session example per research-inspired game (docs/validation.md -> Games). rt_ms + trial_codes are the
# compact per-trial record; warmup marks the first sessions on a device (practice effects), valid/flags the doubt.
PLAY_EXAMPLES: dict[str, dict[str, Any]] = {
    "lantern": {"game": "lantern", "device": "phone", "duration_s": 92.4, "reaction_ms_median": 312.0,
                "reaction_ms_iqr": 61.0, "reaction_ms_cv": 0.19, "response_speed": 3.18, "lapses": 1, "false_starts": 1,
                "trials_n": 24, "valid_n": 23, "input": "touch", "session_index": 6, "warmup": False, "valid": True,
                "rt_ms": [298, 331, 0, 287, 305, 322, 356, 301, 290, 344, 512, 309, 296, 318, 327, 283, 315, 300, 341,
                          294, 336, 308, 299, 325],
                "trial_codes": "hhahhhhhhhlhhhhhhhhhhhhh"},
    "seeds": {"game": "seeds", "device": "mac", "duration_s": 104.0, "throughput_per_min": 26.0, "accuracy": 0.951,
              "reaction_ms_median": 2105.0, "reaction_ms_iqr": 640.0, "trials_n": 41, "valid_n": 39, "input": "keyboard",
              "session_index": 4, "warmup": False, "valid": True,
              "rt_ms": [2400, 2210, 1980, 2105, 2300, 1890, 2050, 2600], "trial_codes": "ccccxccc"},
    "watering": {"game": "watering", "device": "phone", "duration_s": 81.0, "hard_choice_ratio": 0.625,
                 "tap_rate_hz": 5.4, "trials_n": 8, "valid_n": 8, "input": "touch", "session_index": 2, "warmup": True,
                 "valid": True, "rt_ms": [1840, 1320, 990, 1410, 1200, 1105, 980, 1250], "trial_codes": "HEHHEHEH"},
    "doubtful": {"game": "lantern", "device": "phone", "duration_s": 60.0, "lapses": 14, "false_starts": 2,
                 "trials_n": 24, "valid_n": 9, "input": "touch", "session_index": 7, "warmup": False, "valid": False,
                 "flags": ["few_trials", "interrupted"]},
}


# obs.face_signs beside the main example (D52): what the landmark method sends (signs it cannot measure are absent,
# never zero), and a session in which no usable face was seen (provenance only).
FACE_EXAMPLES: dict[str, dict[str, Any]] = {
    "landmarks": {"task": "firefly", "device": "mac", "method": "vision_landmarks", "duration_s": 58.0, "samples": 870,
                  "coverage": 0.88, "mouth_open_share": 0.04, "blinks_per_min": 12.5, "head_movement": 0.031,
                  "expression_range": 0.27},  # no smile, brow or gaze sign from this method; other scales than ARKit
    "check_in": {"task": "check_in", "device": "phone", "method": "arkit_blendshapes", "duration_s": 142.0,
                 "samples": 4260, "coverage": 0.97, "smile_share": 0.21, "smiles": 6, "brow_raise_share": 0.11,
                 "brow_furrow_share": 0.04, "mouth_open_share": 0.38, "blinks_per_min": 19.0, "gaze_on_share": 0.83,
                 "head_movement": 0.33, "expression_range": 0.52},
    "no_face": {"task": "pebbles", "device": "phone", "method": "arkit_blendshapes", "duration_s": 74.0,
                "samples": 2220, "coverage": 0.0},
}

# cmd.head beside the main example (D51): what only a hub sends. The drum hold for a head that runs its own ritual,
# the microphone hold of an open conversation, and the help screen of the crisis path (numbers the head has compiled
# in; never a sound).
TRACE_EXAMPLES: dict[str, dict[str, Any]] = {
    "said_script": {"kind": "said", "text": "Your turn.", "by": "cached_voice"},
    "heard": {"kind": "heard"},
    "tool": {"kind": "tool", "tool": "feel", "by": "rule", "ms": 412, "ok": True},
    "session_open": {"kind": "session", "detail": "open"},
    "game_band": {"kind": "game", "detail": "band:great"},
    "game_level": {"kind": "game", "detail": "level:2", "bpm": 126.0},
    "music_song": {"kind": "music", "detail": "song", "bpm": 100.0},
}

HEAD_EXAMPLES: dict[str, dict[str, Any]] = {
    "drum_hold": {"drum": "hold", "eyes": "soft", "pan_mode": "sway", "bpm": 96.0},
    "drum_end": {"drum": "end", "pan_mode": "still"},
    "mic_open": {"mic": "open"},
    "mic_close": {"mic": "close"},
    "help_shown": {"show": "help"},
    "help_cleared": {"show": "none"},
}


def example(type_: str, *, home_id: str = "demo-aino", source: str | None = None, sim: bool = True) -> Envelope[Any]:
    """A valid example envelope of the given type (handy in tests)."""
    if source is None:
        parts = type_.split(".")
        source = parts[1] if parts[0] == "raw" else ("hub" if parts[0] in ("obs", "health", "log") else "cloud")
    return validate({"home_id": home_id, "source": source, "type": type_, "payload": EXAMPLES[type_], "sim": sim})
