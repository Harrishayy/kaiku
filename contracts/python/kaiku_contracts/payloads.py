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


TapBackBand = Literal["perfect", "great", "nice", "again"]


class TapBackLevel(Strict):
    """One level of Tap it back: the song's tempo and the try that counted (the closer one when a level was replayed)."""

    level: int = Field(ge=1, le=9)
    target_bpm: float = Field(gt=0, le=400, description="the tempo of the song Kaiku played")
    tapped_bpm: float | None = Field(default=None, ge=0, le=400,
                                     description="median gap between her taps as a tempo; None = too few taps to call one")
    error_pct: float | None = Field(default=None, ge=0, description="|tapped - target| / target x 100, against the beat "
                                                                    "level named in `beat`; None with no tempo")
    steadiness: float | None = Field(default=None, ge=0, le=1, description="1 - spread of the gaps between taps")
    taps: int = Field(ge=0)
    band: TapBackBand
    tries: int = Field(ge=1, le=5, description="times the level was played (1 = no replay)")
    beat: Literal["beat", "half", "double"] = Field(
        "beat", description="half / double = she tapped every other beat, or two to a beat, and was compared with that")

    @model_validator(mode="after")
    def _tempo_and_error_go_together(self):
        if (self.tapped_bpm is None) != (self.error_pct is None):
            raise ValueError("tapped_bpm and error_pct are both measured or both missing")
        if self.tapped_bpm is None and self.band != "again":
            raise ValueError("a level with no tapped tempo has no band but `again`")
        return self


class TapBack(Strict):
    """Robot rhythm game "Tap it back" (D51): Kaiku plays a short song, it goes quiet, she taps its beat from memory.
    The tempo is given to her, so this is NOT her own spontaneous tempo (that is obs.drum_session) and no metric in
    config/criteria.toml reads it: it is stored for her own History and feeds no verdict."""

    levels: list[TapBackLevel] = Field(min_length=1, max_length=9)
    levels_played: int = Field(ge=1, le=9)
    levels_passed: int = Field(ge=0, le=9, description="levels whose band is nice, great or perfect")
    error_pct: float | None = Field(default=None, ge=0, description="mean over the levels that have a tapped tempo")
    steadiness: float | None = Field(default=None, ge=0, le=1, description="mean over the levels that have one")
    taps: int = Field(ge=0, description="taps counted over every try")
    rejected_taps: int | None = Field(default=None, ge=0, description="double-triggers dropped by the refractory window")
    duration_s: float = Field(ge=0, description="from the first song to the last band")
    song: Literal["music", "beat", "light"] = Field(
        "music", description="how the tempo was given: generated music, the hub's own plain beat, or the head's light only")

    @model_validator(mode="after")
    def _counts_match_the_levels(self):
        if self.levels_played != len(self.levels):
            raise ValueError("levels_played must count the levels")
        if self.levels_passed != sum(lv.band != "again" for lv in self.levels):
            raise ValueError("levels_passed must count the levels whose band is not `again`")
        return self


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


# photo_time: the robot's "Photo time!" moment (a few seconds in front of its camera; no picture is taken or kept).
FaceTask = Literal["firefly", "breathe", "tell", "pebbles", "lantern", "seeds", "watering", "check_in", "photo_time"]
FACE_TASKS: tuple[str, ...] = ("firefly", "breathe", "tell", "pebbles", "lantern", "seeds", "watering", "check_in",
                               "photo_time")
# haar_cascades: the robot's camera (OpenCV cascades on the UNO Q): smiles and head movement only, its own scale.
FaceMethod = Literal["arkit_blendshapes", "vision_landmarks", "haar_cascades"]
FaceDevice = Literal["phone", "mac", "web", "robot"]
FACE_SIGNS: tuple[str, ...] = ("smile_share", "smiles", "brow_raise_share", "brow_furrow_share", "mouth_open_share",
                               "blinks_per_min", "gaze_on_share", "head_movement", "expression_range")


FaceCueKind = Literal["lower", "tense", "brighter"]
FACE_CUE_KINDS: tuple[str, ...] = ("lower", "tense", "brighter")


class FaceCueCount(Strict):
    """How often and for how long one kind of visible expression cue held in a task (D60)."""

    n: int = Field(ge=1, le=1000, description="separate stretches in which it held for the configured time or longer")
    seconds: float = Field(ge=0, le=86_400, description="seconds it held, over those stretches")


class FaceSigns(Strict):
    """Face signs during one task (D52), with the person's opt-in "Camera during activities": movements of the face
    that the phone's or Mac's own camera could count while a game or the check-in chat ran. One per task session in
    which the camera sampled. Frames are looked at in memory on that device and never stored or sent; only these
    numbers leave it. They are observable movements (smiles, brows, blinks, mouth, gaze, head, range of expression),
    not emotions: nothing here says what the person felt, and no field may. Values are comparable only within one
    `method` (and best within one task): never pool the two methods into one usual. A sign the method cannot
    measure is None, never a zero: the landmark method sends no smile, brow or gaze sign, and blinks, head movement
    and expression range come from both methods on different scales. The apps also leave out blinks under 20 s of
    face time, head movement under 2 s and expression range under 10 face frames, and send nothing at all when
    coverage rounds to 0. A record with `coverage` 0 is still valid here (provenance only) and carries no sign.
    Counts toward the "laptop" (display: Apps) group beside the task; config/criteria.toml reads it as shown, not
    scored."""

    task: FaceTask = Field(description="the task it belongs to: a game (PlayGame), the check-in chat, or the "
                                       "robot's Photo time")
    device: FaceDevice
    method: FaceMethod = Field(description="arkit_blendshapes: TrueDepth face tracking coefficients (iPhone); "
                                           "vision_landmarks: 2-D face landmarks (Mac, other iPhones); "
                                           "haar_cascades: OpenCV cascades on the robot's camera")
    duration_s: float = Field(ge=0, le=86_400, description="seconds the camera sampled")
    samples: int = Field(ge=1, description="frames looked at; none is kept")
    coverage: float = Field(ge=0, le=1, description="share of sampled frames with exactly one usable face")
    smile_share: float | None = Field(default=None, ge=0, le=1,
                                      description="share of face frames with a smile above the method's threshold")
    smiles: int | None = Field(default=None, ge=0, description="distinct smiles")
    brow_raise_share: float | None = Field(default=None, ge=0, le=1, description="share of face frames with raised brows")
    brow_furrow_share: float | None = Field(default=None, ge=0, le=1, description="share of face frames with lowered, drawn brows")
    mouth_open_share: float | None = Field(default=None, ge=0, le=1, description="share of face frames with the mouth open")
    blinks_per_min: float | None = Field(default=None, ge=0, description="blinks per minute of face time")
    gaze_on_share: float | None = Field(default=None, ge=0, le=1, description="share of face frames looking toward the screen")
    head_movement: float | None = Field(default=None, ge=0, description="how much the head moved; the scale belongs to the method")
    expression_range: float | None = Field(default=None, ge=0, le=1,
                                           description="overall variability of expression over the session")
    cues: dict[FaceCueKind, FaceCueCount] | None = Field(
        default=None,
        description="visible expression cues in this task (D60): a kind of expression that held for a while, against "
                    "this person's own level earlier in the same task. lower = less smiling with the mouth corners "
                    "down or the inner brows up; tense = brows drawn down with the lips pressed or the eyes "
                    "narrowed; brighter = sustained smiling. Named for what is seen, never for what is felt: a "
                    "movement of the face is not proof of a feeling. Absent = none held (or the method cannot tell). "
                    "Shown and citable, not scored")
    ref: str | None = Field(default=None, min_length=1, max_length=64,
                            description="id of the obs.play_session (or other record) of the same task")

    @model_validator(mode="after")
    def _no_face_no_signs(self):
        if self.coverage == 0 and any(getattr(self, name) is not None for name in FACE_SIGNS):
            raise ValueError("a session with no usable face (coverage 0) carries no face sign")
        if self.coverage == 0 and self.cues:
            raise ValueError("a session with no usable face (coverage 0) carries no expression cue")
        if self.cues is not None and not self.cues:
            raise ValueError("cues is absent when none held, never an empty object")
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
    # More of the day from Apple Health (D53): every one optional and absent when Health holds nothing for it, never
    # a zero in its place. Daily totals only. There is no sleep score: Apple gives apps none, and none is invented.
    distance_km: float | None = Field(default=None, ge=0, le=300, description="walking + running distance over the "
                                      "previous day (00:00 to 00:00 local, the window of steps), km")
    daylight_min: float | None = Field(default=None, ge=0, le=1440, description="time in daylight over the previous "
                                       "day, minutes (Apple Watch only; absent otherwise)")
    walking_hr_bpm: float | None = Field(default=None, gt=20, lt=250,
                                         description="average walking heart rate over the previous day")
    sleep_deep_min: float | None = Field(default=None, ge=0, le=1440, description="minutes of deep sleep last night; "
                                         "the three stages are sent together or not at all (0 allowed)")
    sleep_rem_min: float | None = Field(default=None, ge=0, le=1440, description="minutes of REM sleep last night")
    sleep_core_min: float | None = Field(default=None, ge=0, le=1440, description="minutes of core sleep last night")
    sleep_awake_min: float | None = Field(default=None, ge=0, le=1440, description="minutes awake between first "
                                          "falling asleep and the last waking; absent when the source wrote none")
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


class RawFaceSigns(Strict):
    """What the robot's camera counted in one "Photo time" window (`cmd.sensors face_signs_s`): numbers only, made
    in the camera thread; no frame leaves it. The hub turns it into `obs.face_signs` (task photo_time, device robot,
    method haar_cascades). A sign the cascades could not measure is None, never a zero; coverage 0 carries none."""

    duration_s: float = Field(ge=0, le=60, description="seconds the camera sampled")
    samples: int = Field(ge=1, description="frames looked at; none is kept")
    coverage: float = Field(ge=0, le=1, description="share of sampled frames with exactly one face")
    smile_share: float | None = Field(default=None, ge=0, le=1, description="share of face frames with a smile")
    smiles: int | None = Field(default=None, ge=0, description="distinct smiles")
    head_movement: float | None = Field(default=None, ge=0, description="face-centre travel per second, in face widths")


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


class HubTranscript(Strict):
    """`raw.hub.transcript`: what the person just said, as the Live voice's input transcription gives it, for the
    transcript page of the phone or Mac that is standing in as the robot's microphone (D63). Sent ONLY while such
    a device is sending its microphone (the sound of these words is then already crossing the home network from
    that device), never after a crisis phrase, never uplinked, never stored by the hub, and no bus tool records or
    prints it. `raw.hub.trace` still never carries her words."""

    who: Literal["person"] = "person"
    text: str = Field(min_length=1, max_length=500)


class HubTrace(Strict):
    """`raw.hub.trace`: what Kaiku just did, live, for the "Kaiku bot" tab of the person's own apps on the home
    network. Local only (raw.* never leaves the home; QoS 0, not retained, not stored). It carries Kaiku's OWN
    lines and the names of the tools the voice called. Never the person's words, a system instruction, or a tool's
    arguments or result: `text` exists for `said` alone and `heard` carries nothing but its kind (validated)."""

    kind: Literal["said", "heard", "tool", "session", "game", "music"]
    text: str | None = Field(default=None, max_length=300,
                             description="said only: Kaiku's own words (a scripted line, or the Live voice's reply "
                                         "as its output transcription gives it), cut at 300 characters")
    tool: str | None = Field(default=None, max_length=40, description="tool only: the name of the tool the voice called")
    by: Literal["script", "live", "cached_voice", "notebook", "gemma", "flash", "argon", "rule"] | None = Field(
        default=None, description="said: how it was spoken (script | live | cached_voice). tool: who answered, only "
                                  "when the cloud's result says so")
    ms: int | None = Field(default=None, ge=0, description="tool: how long the call took")
    ok: bool | None = None
    detail: str | None = Field(default=None, max_length=80,
                               description="a short machine word. session: open | close. music: start | song | hush | "
                                           "stop. game: level:<n> | your_turn | band:<perfect|great|nice|again>")
    bpm: float | None = Field(default=None, gt=0, description="music song / game level: its tempo")

    @model_validator(mode="after")
    def _only_what_its_kind_may_carry(self) -> HubTrace:
        if self.text is not None and self.kind != "said":
            raise ValueError("text is only for kind 'said' (Kaiku's own words)")
        if self.tool is not None and self.kind != "tool":
            raise ValueError("tool is only for kind 'tool'")
        if self.kind == "heard" and self.model_dump(exclude_none=True) != {"kind": "heard"}:
            raise ValueError("'heard' carries nothing but its kind: the person's words never travel on the bus")
        if self.kind == "said" and self.by not in (None, "script", "live", "cached_voice"):
            raise ValueError("said: by is script | live | cached_voice")
        return self


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
    drum: Literal["hold", "end"] | None = Field(
        default=None, description="only for a head that runs its own ritual (standalone firmware): hold = the hub runs "
                                  "the drum phase now (stay in the drum step, keep reporting taps, no own timer, obey "
                                  "eyes / pan_mode sway / bpm); end = it is over, go on. Re-sent at least every 5 s; "
                                  "10 s without one = back to the head's own timer. Ignored by a hub-driven head")
    mic: Literal["open", "close"] | None = Field(
        default=None, description="open = send the head's microphone as PCM frames on audio/head/mic (only while a "
                                  "conversation the person started is open); close = stop. Re-sent at least every "
                                  "3 s; the head closes by itself after 10 s without one. Half-duplex: no frames while "
                                  "its speaker plays and about 250 ms after")
    ritual: Literal["next", "end"] | None = Field(
        default=None, description="only for a head that runs its own ritual (standalone firmware): next = go on to "
                                  "the next step now (she answered the dial question in words instead of with the "
                                  "ear); end = she asked to stop: back to idle now, quietly. Ignored while idle")
    activity: Literal["breathe", "drum", "none"] | None = Field(
        default=None, description="only for a head that runs its own ritual (standalone firmware), the second half of "
                                  "asking twice (D58): the person asked Kaiku in words for this activity; for the next "
                                  "20 s a press of the ear starts it (the head goes straight to that step) instead of "
                                  "doing what a press does in the current step. none = no longer. Ignored while idle")
    show: Literal["help", "none"] | None = Field(
        default=None, description="help = the head shows the helpline's name and number and the emergency number on "
                                  "its own screen, from constants compiled into the firmware, until `none`, a new "
                                  "ritual, or 10 minutes; never a sound. Sent by the hub's crisis path only")


class SensorsCmd(_AtLeastOne):
    ppg: Literal["start", "stop"] | None = None
    camera_enable: bool | None = None
    chime: Chime | None = Field(default=None, description="short cue on the Modulino Buzzer; alert = device fault only")
    face_signs_s: float | None = Field(
        default=None, gt=0, le=30, description="Photo time: count face signs for this many seconds, then send one "
                                               "raw.sensors.face_signs. Nothing is recorded; ignored without a camera")


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
    photo_time: bool | None = Field(default=None, description="start the robot's Photo time now (a button or a tool; "
                                                               "the same thing as saying it to Kaiku)")

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
