"""Payload models for every message type. Edit here, then run `make contracts`.

Rules: additive changes (new optional field / new type) need no version bump.
Breaking changes bump SCHEMA_VERSION (envelope `v`). Always note changes in docs/progress.md.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- shared enums
RitualStep = Literal["greet", "dial", "breathe", "drum", "phq9", "nudge", "close"]
DialItem = Literal["mood", "energy", "sleep"]
DIAL_ITEMS: tuple[str, ...] = ("mood", "energy", "sleep")
NudgeArm = Literal["breathe", "drum", "daylight_walk", "friend_ping", "icbt_exercise"]
NUDGE_ARMS: tuple[str, ...] = ("breathe", "drum", "daylight_walk", "friend_ping", "icbt_exercise")
Activity = Literal["breathe", "drum", "walk", "friend_ping", "icbt"]
Eyes = Literal["neutral", "happy", "sleepy", "wide", "listening", "thinking", "soft"]


# --------------------------------------------------------------------------- obs/* (uplinked)
class Presence(Strict):
    distance_cm: float = Field(ge=0)
    first_of_day: bool
    dwell_s: float = Field(ge=0)


class SelfReport(Strict):
    """One dial answer (turn the ear). The ritual asks mood, energy, last night's sleep."""

    item: DialItem
    value: int = Field(ge=1, le=5)
    context: Literal["ritual", "adhoc", "post_activity"] = "ritual"


class HrvSession(Strict):
    hr_bpm: float = Field(gt=0, lt=250)
    rmssd_pre_ms: float | None = Field(default=None, ge=0)
    rmssd_post_ms: float | None = Field(default=None, ge=0)
    duration_s: float = Field(ge=0)
    breath_bpm: float = Field(gt=0, le=30)


class DrumSession(Strict):
    tempo_bpm: float = Field(ge=0, le=400)
    force_mean: float = Field(ge=0, le=1)
    duration_s: float = Field(ge=0)
    regularity: float = Field(ge=0, le=1)
    taps: int = Field(ge=0)


class LightLevel(Strict):
    lux_est: float = Field(ge=0)
    window_min: float = Field(gt=0)


class SpeechFeatures(Strict):
    """Robot-side speech features from the local mic. No audio, no transcript."""

    wpm: float | None = Field(default=None, ge=0)
    syllables_per_s: float | None = Field(default=None, ge=0)
    pause_ratio: float = Field(ge=0, le=1)
    duration_s: float = Field(ge=0)


class Ritual(Strict):
    step: RitualStep
    status: Literal["started", "completed", "skipped", "aborted"]
    duration_s: float | None = Field(default=None, ge=0)


class NudgeOffered(Strict):
    arm: NudgeArm
    reason: str = Field(max_length=280)


class NextDay(Strict):
    mood: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)
    activity: float | None = Field(default=None, ge=0, description="active minutes that day (outings)")


class NudgeOutcome(Strict):
    arm: NudgeArm
    accepted: bool
    next_day: NextDay | None = None
    reward: float | None = Field(default=None, ge=0, le=1)


class Outing(Strict):
    """A walk / time outdoors. daylight_min only from the optional DAT camera app."""

    minutes: float = Field(ge=0)
    steps: int | None = Field(default=None, ge=0)
    method: Literal["location", "steps", "dat_camera"]
    daylight_min: float | None = Field(default=None, ge=0)


class FriendLink(Strict):
    direction: Literal["sent", "received"]
    ack: bool


class LaptopSession(Strict):
    """2-minute laptop session. All features computed in the browser; nothing recorded.
    Any feature may be None if that part was skipped or unsupported (e.g. no webcam)."""

    speech_rate: float | None = Field(default=None, ge=0, description="syllables per second")
    pause_ratio: float | None = Field(default=None, ge=0, le=1)
    pitch_variability: float | None = Field(default=None, ge=0, description="semitones SD")
    expressivity_index: float | None = Field(default=None, ge=0, le=1)
    reaction_ms_median: float | None = Field(default=None, ge=0)
    reaction_ms_iqr: float | None = Field(default=None, ge=0)
    lapses: int | None = Field(default=None, ge=0, description="responses > 500 ms or misses")
    duration_s: float = Field(ge=0)


class Phq9(Strict):
    """PHQ-9 (every 14 days). items[8] is item 9; > 0 triggers the safety path."""

    total: int = Field(ge=0, le=27)
    items: list[int] = Field(min_length=9, max_length=9)
    item9_positive: bool
    mode: Literal["spoken", "laptop"]

    @model_validator(mode="after")
    def _consistent(self):
        if any(not 0 <= i <= 3 for i in self.items):
            raise ValueError("PHQ-9 items must be 0..3")
        if sum(self.items) != self.total:
            raise ValueError("total must equal the sum of items")
        if (self.items[8] > 0) != self.item9_positive:
            raise ValueError("item9_positive must equal items[8] > 0")
        return self


class Measures(Strict):
    rmssd_ms: float | None = Field(default=None, ge=0)
    hr_bpm: float | None = Field(default=None, gt=0, lt=250)
    mood: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)


class MeasuresDelta(Strict):
    rmssd_ms: float | None = None
    hr_bpm: float | None = None
    mood: float | None = None
    energy: float | None = None


class InterventionResponse(Strict):
    """Immediate before/after effect of one activity (feeds the bandit learner)."""

    activity: Activity
    pre: Measures = Field(default_factory=Measures)
    post: Measures = Field(default_factory=Measures)
    delta: MeasuresDelta = Field(default_factory=MeasuresDelta)


class SafetyFlag(Strict):
    trigger: Literal["phq9_item9", "phrase", "manual"]
    severity: Literal["high"] = "high"
    handled_locally: bool


# --------------------------------------------------------------------------- raw/* (local only)
class RawTap(Strict):
    t_ms: int = Field(ge=0)
    force: float = Field(ge=0, description="peak acceleration, g")
    src: Literal["imu", "knock"] = "imu"


class RawEar(Strict):
    value: int
    delta: int
    pressed: bool = False


class RawPan(Strict):
    deg: float
    homed: bool
    moving: bool


class RawPpg(Strict):
    t0_ms: int = Field(ge=0)
    fs_hz: float = Field(gt=0, le=1000)
    samples: list[int] = Field(min_length=1, max_length=1000)


class RawDistance(Strict):
    cm: float = Field(ge=0)


class RawLight(Strict):
    raw: int
    lux_est: float = Field(ge=0)


class RawButton(Strict):
    id: str = Field(min_length=1, max_length=32)
    pressed: bool


class RawHall(Strict):
    at_home: bool


class RawFace(Strict):
    """Face position only. Images are never published, stored or transmitted."""

    x_norm: float = Field(ge=-1, le=1)
    y_norm: float = Field(ge=-1, le=1)
    size: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)


# --------------------------------------------------------------------------- cmd/*
class LookAt(Strict):
    x: float = Field(ge=-1, le=1)
    y: float = Field(ge=-1, le=1)


class PanTarget(Strict):
    target_deg: float
    speed: float = Field(default=0.5, ge=0, le=1)


class Purr(Strict):
    ms: int = Field(gt=0, le=10_000)


class _AtLeastOne(Strict):
    @model_validator(mode="after")
    def _not_empty(self):
        if not any(v is not None for v in self.__dict__.values()):
            raise ValueError("command must set at least one field")
        return self


class HeadCmd(_AtLeastOne):
    eyes: Eyes | None = None
    look: LookAt | None = None
    pan: PanTarget | None = None
    pan_mode: Literal["track", "still", "sway"] | None = None
    home: bool | None = None
    chest: Literal["off", "breathe", "glow", "pulse"] | None = None
    bpm: float | None = Field(default=None, gt=0, le=300, description="for pan_mode=sway or chest=breathe")
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    purr: Purr | None = None


class SensorsCmd(_AtLeastOne):
    ppg: Literal["start", "stop"] | None = None
    camera_enable: bool | None = None


class FriendPing(Strict):
    pattern: str = Field(default="glow", max_length=32)


class FriendlinkCmd(_AtLeastOne):
    ping: FriendPing | None = None


class SuggestNudge(Strict):
    arm: NudgeArm


class ClinicianMessage(Strict):
    text: str = Field(min_length=1, max_length=500)


class HubCmd(_AtLeastOne):
    suggest_nudge: SuggestNudge | None = None
    set_ritual_time: str | None = None
    clinician_message: ClinicianMessage | None = None
    start_ritual: bool | None = None
    phq9_due: bool | None = Field(default=None, description="ask PHQ-9 in the next ritual (spoken mode)")
    say: str | None = Field(default=None, max_length=500, description="text-mode user utterance (sim/demo)")

    @field_validator("set_ritual_time")
    @classmethod
    def _hhmm(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("set_ritual_time must be HH:MM")
        return v


# --------------------------------------------------------------------------- health / log
class Health(Strict):
    status: Literal["ok", "degraded", "down"]
    version: str
    uptime_s: float = Field(ge=0)
    last_error: str | None = None
    details: dict = Field(default_factory=dict)


class Log(Strict):
    level: Literal["debug", "info", "warning", "error"]
    event: str
    msg: str = ""
