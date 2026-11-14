"""Payload models for every message type. Edit here, then run `make contracts`.

Rules: additive changes (new optional field / new type) need no version bump.
Breaking changes bump SCHEMA_VERSION (envelope `v`). Always note changes in docs/progress.md.
"""

from __future__ import annotations

import re
from datetime import date as date_
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
SelfReportChannel = Literal["robot", "phone", "mac", "web", "glasses_voice"]
PlayGame = Literal["firefly", "breathe", "tell", "pebbles"]
PlayDevice = Literal["phone", "mac", "web"]
SCREEN_CATEGORIES: tuple[str, ...] = ("work", "communication", "social", "video", "news", "games", "other")


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
    channel: SelfReportChannel = Field(
        "robot", description="where the dial was answered: robot ear, phone/Mac/web weather check, or spoken on the "
                             "glasses (parsed on the phone, no transcript kept). Always counts toward the robot source")


class HrvSession(Strict):
    hr_bpm: float = Field(gt=0, lt=250)
    rmssd_pre_ms: float | None = Field(default=None, ge=0)
    rmssd_post_ms: float | None = Field(default=None, ge=0)
    duration_s: float = Field(ge=0)
    breath_bpm: float = Field(gt=0, le=30)


class DrumSession(Strict):
    tempo_bpm: float = Field(ge=0, le=400)
    force_mean: float | None = Field(default=None, ge=0, le=1,
                                     description="None when the drum can't sense force (KY-031 knock switch)")
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
    """A walk / time outdoors. Everything is computed on the phone / glasses; only these numbers are uplinked.

    daylight_min only with a camera (DAT camera app or the iPhone DAT bridge: sparse frames -> brightness, frames
    discarded). cadence / gait / head-up come from the glasses IMU via the DAT SDK (`method: dat_imu`, beta)."""

    minutes: float = Field(ge=0)
    steps: int | None = Field(default=None, ge=0)
    method: Literal["location", "steps", "dat_camera", "dat_imu"]
    daylight_min: float | None = Field(default=None, ge=0)
    cadence_spm: float | None = Field(default=None, ge=0, le=250, description="walking cadence, steps per minute")
    gait_regularity: float | None = Field(default=None, ge=0, le=1, description="step-interval regularity, 1 = metronome")
    head_up_ratio: float | None = Field(default=None, ge=0, le=1, description="share of walking time looking ahead/up")


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


class ScreenCategoryMinutes(Strict):
    """Minutes by broad category, from a LOCAL bundle-id -> category table on the Mac. Never titles/URLs/content."""

    work: float = Field(0, ge=0)
    communication: float = Field(0, ge=0)
    social: float = Field(0, ge=0)
    video: float = Field(0, ge=0)
    news: float = Field(0, ge=0)
    games: float = Field(0, ge=0)
    other: float = Field(0, ge=0)


class ScreenActivity(Strict):
    """Usage rhythm (D26), one per period (hourly) from the Mac app. Computed on the Mac from the frontmost app's
    bundle id + idle time only: no window titles, URLs, keystrokes or screenshots ever leave it (or are kept).
    `paused: true` = the person paused sensing for (part of) this period; the numbers then cover the rest only."""

    period_min: float = Field(gt=0, le=1440, description="length of the period this summarises (60 = hourly)")
    active_min: float = Field(ge=0, le=1440, description="minutes with input activity (not idle)")
    late_night_min: float = Field(0, ge=0, le=1440, description="active minutes between 00:00 and 05:00 local")
    category_min: ScreenCategoryMinutes = Field(default_factory=ScreenCategoryMinutes)
    switches_per_hour: float = Field(0, ge=0, le=3600, description="frontmost-app switches per active hour")
    longest_stretch_min: float = Field(0, ge=0, le=1440, description="longest unbroken active stretch")
    breaks: int = Field(0, ge=0, description="idle gaps >= 5 min")
    paused: bool = False

    @model_validator(mode="after")
    def _within_period(self):
        tol = 0.5
        for name in ("active_min", "late_night_min", "longest_stretch_min"):
            if getattr(self, name) > self.period_min + tol:
                raise ValueError(f"{name} cannot exceed period_min")
        if sum(getattr(self.category_min, c) for c in SCREEN_CATEGORIES) > self.period_min + tol:
            raise ValueError("category minutes cannot add up to more than period_min")
        return self


class PlaySession(Strict):
    """One short game with Kaiku (firefly go/no-go, breathe, tell-Kaiku, pebbles memory span) on the phone, Mac or
    web. Every feature is
    computed on the device; no audio, video or transcript is stored or sent. Fields a game doesn't produce are None.
    Counts toward the "laptop" (display: Apps) source wherever it was played."""

    game: PlayGame
    device: PlayDevice
    duration_s: float = Field(ge=0, le=3600)
    reaction_ms_median: float | None = Field(default=None, ge=0, le=5000, description="firefly: correct taps")
    reaction_ms_iqr: float | None = Field(default=None, ge=0, le=5000)
    lapses: int | None = Field(default=None, ge=0, description="firefly: responses > 500 ms or missed fireflies")
    false_taps: int | None = Field(default=None, ge=0, description="firefly: taps on a moth (no-go)")
    speech_rate: float | None = Field(default=None, ge=0, le=15, description="tell: syllables per second")
    pause_ratio: float | None = Field(default=None, ge=0, le=1, description="tell")
    pitch_variability: float | None = Field(default=None, ge=0, le=20, description="tell: semitones SD")
    hr_before_bpm: float | None = Field(default=None, gt=0, lt=250, description="breathe, with a watch")
    hr_after_bpm: float | None = Field(default=None, gt=0, lt=250, description="breathe, with a watch")
    span_max: int | None = Field(default=None, ge=0, le=20, description="pebbles: longest sequence repeated correctly")
    accuracy: float | None = Field(default=None, ge=0, le=1, description="pebbles: share of rounds repeated correctly")


class WearableDaily(Strict):
    """Daily summary from Apple Health (HealthKit) on the iPhone: Apple Watch or any watch that writes to Apple Health.
    Posted once per morning; `date` = that local morning: sleep = the night that ended this morning, steps /
    exercise / resting HR / HRV = the previous 24 h. Only these aggregates leave the phone (no raw samples).
    Optional source: people without a watch simply never send it."""

    date: date_
    sleep_min: float | None = Field(default=None, ge=0, le=1440, description="minutes asleep last night")
    sleep_midpoint_min: float | None = Field(
        default=None, ge=-720, le=720,
        description="midpoint of last night's sleep, minutes from local midnight (-30 = 23:30, 210 = 03:30)")
    sleep_regularity: float | None = Field(default=None, ge=0, le=1, description="1 = same sleep times every night")
    resting_hr_bpm: float | None = Field(default=None, gt=20, lt=250)
    hrv_sdnn_ms: float | None = Field(default=None, ge=0, le=500)
    steps: int | None = Field(default=None, ge=0, le=200_000)
    exercise_min: float | None = Field(default=None, ge=0, le=1440)
    device: Literal["apple_watch", "other_watch", "phone_only"]


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
    force: float | None = Field(default=None, ge=0, description="peak acceleration, g; None for a knock switch")
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


Gesture = Literal["look_left", "look_right", "shake"]  # the head only pans: no nod
Chime = Literal["wake", "ok", "start_drum", "end_drum", "alert"]


class HeadCmd(_AtLeastOne):
    """Robot face + body, all on the Atech head node: eyes/look (Color Display), chest/color/bpm (LED grids),
    pan/home/gesture (pan motor, hall homing), purr (speaker tone; no purr motor on the current build)."""

    eyes: Eyes | None = None
    look: LookAt | None = None
    pan: PanTarget | None = None
    pan_mode: Literal["track", "still", "sway"] | None = None
    home: bool | None = None
    chest: Literal["off", "breathe", "glow", "pulse"] | None = None
    bpm: float | None = Field(default=None, gt=0, le=300, description="for pan_mode=sway or chest=breathe")
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    purr: Purr | None = None
    gesture: Gesture | None = Field(default=None, description="timed motor pulse, then home (no position feedback)")


class SensorsCmd(_AtLeastOne):
    ppg: Literal["start", "stop"] | None = None
    camera_enable: bool | None = None
    chime: Chime | None = Field(default=None, description="short cue on the Modulino Buzzer; alert = device fault only")


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
