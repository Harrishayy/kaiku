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
PlayGame = Literal["firefly", "breathe", "tell", "pebbles", "lantern", "seeds", "watering"]
PlayDevice = Literal["phone", "mac", "web"]
PlayInput = Literal["touch", "pointer", "keyboard", "mixed"]
PlayFlag = Literal["few_trials", "false_starts", "low_accuracy", "too_fast", "interrupted"]
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
    scale_10: int | None = Field(
        default=None, ge=1, le=10,
        description="the answer exactly as dialled when the device has a 1-10 dial (the standalone robot head); "
                    "`value` is then ceil(scale_10 / 2). Absent for 1-5 dials")

    @model_validator(mode="after")
    def _scale_10_matches_value(self):
        if self.scale_10 is not None and (self.scale_10 + 1) // 2 != self.value:
            raise ValueError("value must equal ceil(scale_10 / 2)")
        return self


class HrvSession(Strict):
    hr_bpm: float = Field(gt=0, lt=250)
    rmssd_pre_ms: float | None = Field(default=None, ge=0)
    rmssd_post_ms: float | None = Field(default=None, ge=0)
    duration_s: float = Field(ge=0)
    breath_bpm: float = Field(gt=0, le=30)
    method: Literal["finger", "camera"] | None = Field(
        default=None, description="finger = KY-039 cradle (HR + RMSSD); camera = forehead-green backup (HR only, "
                                  "never RMSSD: ~15 Hz is too coarse for beat-to-beat timing)")
    beats: int | None = Field(default=None, ge=0, description="heartbeats found in the recording")


class DrumSession(Strict):
    tempo_bpm: float = Field(ge=0, le=400)
    force_mean: float | None = Field(default=None, ge=0, le=1,
                                     description="None when the drum can't sense force (KY-031 knock switch)")
    duration_s: float = Field(ge=0)
    regularity: float = Field(ge=0, le=1)
    taps: int = Field(ge=0)
    tempo_start_bpm: float | None = Field(default=None, ge=0, le=400, description="tempo of the first third of the taps")
    tempo_end_bpm: float | None = Field(default=None, ge=0, le=400, description="tempo of the last third of the taps")
    taps_per_s: float | None = Field(default=None, ge=0, description="energy proxy that needs no force sensor")
    pauses: int | None = Field(default=None, ge=0, description="gaps > 2 s inside the session")
    rejected_taps: int | None = Field(default=None, ge=0, description="double-triggers dropped by the refractory window")


class LightLevel(Strict):
    lux_est: float = Field(ge=0)
    window_min: float = Field(gt=0)


class SpeechFeatures(Strict):
    """Robot-side speech features from the local mic. No audio, no transcript."""

    wpm: float | None = Field(default=None, ge=0)
    syllables_per_s: float | None = Field(default=None, ge=0)
    pause_ratio: float = Field(ge=0, le=1)
    duration_s: float = Field(ge=0)


EngagementCueName = Literal["face", "voice", "drum", "pulse", "dial", "ritual"]


class EngagementCue(Strict):
    """One cue of the robot's engagement summary. `available: false` = missing evidence (never a zero score)."""

    cue: EngagementCueName
    available: bool
    level: float | None = Field(default=None, ge=0, le=1, description="0-1 on a fixed reference range, not a baseline")
    confidence: float = Field(default=0, ge=0, le=1)
    basis: str = Field(default="", max_length=120, description="what it was computed from, or why it is missing")

    @model_validator(mode="after")
    def _missing_has_no_level(self):
        if self.available == (self.level is None):
            raise ValueError("an available cue needs a level; a missing cue has none")
        return self


class Engagement(Strict):
    """Robot ritual, once at the end and only when the person accepted the conversation: a deterministic summary of
    how animated the session was, fused from every available cue (face presence + movement from box positions,
    speech pace/pauses, drum energy, pulse, dial answers, steps completed). No single cue decides and the face share
    is capped; fewer than 2 cues -> `level` is None. It is an observation feature with provenance: not an emotion,
    not a diagnosis, and it feeds no verdict. Computed from numbers only; no image or audio is stored or sent."""

    session_id: str | None = Field(default=None, max_length=64, description="the ritual's episode id")
    level: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    cues_available: int = Field(ge=0, le=6)
    agreement: float | None = Field(default=None, ge=0, le=1, description="1 - spread of the available cue levels")
    cues: list[EngagementCue] = Field(max_length=6)
    method: Literal["robot-multicue-v1"] = "robot-multicue-v1"

    @model_validator(mode="after")
    def _needs_two_cues(self):
        if sum(c.available for c in self.cues) != self.cues_available:
            raise ValueError("cues_available must count the available cues")
        if (self.cues_available < 2) != (self.level is None):
            raise ValueError("level needs at least 2 available cues (no single cue decides)")
        return self


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
    accuracy: float | None = Field(default=None, ge=0, le=1,
                                   description="pebbles: share of taps that were right; seeds: share of answers right")
    # --- research-inspired games (docs/validation.md -> Games): lantern = simple reaction time / vigilance (PVT-style),
    # seeds = symbol-digit substitution (processing speed), watering = effort-for-reward choice. Not validated tests.
    trials_n: int | None = Field(default=None, ge=0, le=300, description="scored trials presented (practice excluded)")
    valid_n: int | None = Field(default=None, ge=0, le=300, description="trials with a usable response")
    input: PlayInput | None = Field(default=None, description="how the person answered (provenance for timing)")
    session_index: int | None = Field(default=None, ge=1, le=100_000,
                                      description="nth finished session of this game on this device (1 = first)")
    warmup: bool | None = Field(default=None, description="true for the first sessions of a game on a device "
                                "(practice effects): criteria metrics filter warmup = false")
    valid: bool | None = Field(default=None, description="false when the validity rules failed (see flags); the "
                               "envelope quality is then < 0.5 so the metric skips it")
    flags: list[PlayFlag] | None = Field(default=None, max_length=5, description="why a session is doubtful")
    false_starts: int | None = Field(default=None, ge=0, le=300,
                                     description="lantern: taps before the light or faster than 100 ms")
    response_speed: float | None = Field(default=None, ge=0, le=10,
                                         description="lantern: mean of 1000 / RT ms over valid trials (1/s)")
    reaction_ms_cv: float | None = Field(default=None, ge=0, le=5, description="lantern: SD / mean of valid RTs")
    throughput_per_min: float | None = Field(default=None, ge=0, le=300, description="seeds: correct answers per minute")
    hard_choice_ratio: float | None = Field(default=None, ge=0, le=1,
                                            description="watering: share of rounds the bigger, harder plant was chosen")
    tap_rate_hz: float | None = Field(default=None, ge=0, le=20, description="watering: median taps per second")
    rt_ms: list[int] | None = Field(default=None, max_length=120, description="per-trial response time in order, ms "
                                    "(0 = no response); the compact raw data behind the summary numbers")
    trial_codes: str | None = Field(default=None, max_length=120, pattern=r"^[a-zA-Z0-9]*$",
                                    description="one character per trial, same order as rt_ms. lantern: h hit, "
                                    "l lapse (>= 500 ms), m missed, a anticipation; seeds: c correct, x wrong; "
                                    "watering: H hard chosen, E easy chosen (lowercase = not finished in time)")
    expressivity_index: float | None = Field(default=None, ge=0, le=1, description="optional local facial movement variability; not an emotion or wellbeing score")
    face_movement: float | None = Field(default=None, ge=0, le=1, description="optional normalised face position movement during the task")
    camera_face_coverage: float | None = Field(default=None, ge=0, le=1, description="fraction of sampled frames containing one usable face")
    camera_samples: int | None = Field(default=None, ge=0, description="number of sampled camera frames; frames are never stored")
    camera_method: Literal["mediapipe_blendshapes", "vision_landmarks"] | None = None

    @field_validator("rt_ms")
    @classmethod
    def _rt_range(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and any(x < 0 or x > 10_000 for x in v):
            raise ValueError("rt_ms values must be 0..10000")
        return v

    @model_validator(mode="after")
    def _camera_provenance(self):
        if self.expressivity_index is not None or self.face_movement is not None:
            if self.camera_method is None or not self.camera_face_coverage or not self.camera_samples:
                raise ValueError("camera features require method, face coverage and a positive sample count")
        return self


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
