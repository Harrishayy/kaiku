"""Cloud HTTP API request/response models (handoff §6.4, §6.7). Shared by cloud, hub, web (via TS)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .companion_tools import (
    Activity,
    AgreeWhen,
    CheckinItem,
    Energy,
    Intent,
    MemoryCategory,
    MindKind,
    Purpose,
    Skill,
    Surface,
    Tone,
    Valence,
    WalkStyle,
)
from .criteria import Criteria
from .envelope import Envelope
from .payloads import FaceSigns, Health, NudgeArm, PlaySession
from .sources import ConsensusSource

State = Literal["stable", "watch", "needs_call", "safety"]
Verdict = Literal["better", "as_usual", "worse", "insufficient"]
Agreement = Literal["agree", "disagree", "low_coverage"]
ActionName = Literal["flag_booster", "flag_icbt_referral", "acknowledge", "send_message"]
STATE_RANK: dict[str, int] = {"safety": 0, "needs_call": 1, "watch": 2, "stable": 3}


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class APIDiscoveryResponse(ApiModel):
    """Public service identity, never a robot connection or authorization credential."""

    service: Literal["kaiku-api"] = "kaiku-api"
    schema_version: Literal[1] = 1
    mode: Literal["demo", "authenticated", "unconfigured"]
    auth_required: bool
    capabilities: list[Literal["companion_voice", "observations", "monitoring"]] = Field(default_factory=list)


class EventsBatch(ApiModel):
    events: list[Envelope[dict[str, Any]]] = Field(max_length=500)


class EventsResult(ApiModel):
    accepted: int
    duplicates: int
    rejected: list[dict[str, Any]] = Field(default_factory=list, description="[{id, error}]")


class CommandsResponse(ApiModel):
    commands: list[Envelope[dict[str, Any]]]


class CommandAckResult(ApiModel):
    """POST /v1/commands/{command_id}/ack?home_id= after successful application."""

    ok: bool
    id: UUID


class ClinicianAskRequest(ApiModel):
    question: str = Field(min_length=1, max_length=500)


class RecordCitation(ApiModel):
    id: str
    label: str
    detail: str = ""
    metric: str | None = None
    source: str | None = None
    observed_at: date | None = None
    value: float | None = None
    unit: str | None = None
    baseline: float | None = None
    simulated: bool = Field(default=False, description="rests on simulated observations")


class ClinicianAskResponse(ApiModel):
    patient_id: str
    answer: str = Field(max_length=2400)
    citations: list[RecordCitation] = Field(default_factory=list)
    by: Literal["gemma", "template"]
    model: str | None = None
    cached: bool = False
    computed_at: datetime


class TaskObservationsResponse(ApiModel):
    patient_id: str
    observations: list[Envelope[PlaySession]] = Field(default_factory=list, max_length=100)
    face_signs: list[Envelope[FaceSigns]] = Field(
        default_factory=list, max_length=100, description="obs.face_signs of the same window, newest first (D52): "
        "`payload.ref` names the task session each belongs to. Movements counted on the device; never an emotion")
    computed_at: datetime


# ----------------------------------------------------------------- consensus (handoff §6.4)
class VerdictEvidence(ApiModel):
    metric: str
    z: float | None = None
    direction: Literal["up", "down"]
    days: int = Field(ge=0, description="drifting days in the window")
    summary: str = ""


class SourceVerdict(ApiModel):
    home_id: str
    source: ConsensusSource
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    evidence: list[VerdictEvidence] = Field(default_factory=list)
    last_data_at: datetime | None = None
    computed_at: datetime


class SourceNote(ApiModel):
    source: ConsensusSource
    summary: str


class Explanation(ApiModel):
    """Plain-language explanation of a consensus. Gemma or template. An explanation, not a decision."""

    headline: str = Field(max_length=200)
    text: str = Field(max_length=1200)
    per_source: list[SourceNote] = Field(default_factory=list)
    disagreement_note: str | None = Field(default=None, max_length=400)
    suggested_actions: list[Literal["flag_booster", "flag_icbt_referral", "send_message", "check_in_call", "none"]]
    caveats: str = Field(max_length=600)
    by: Literal["gemma", "template"]
    model: str | None = None
    generated_at: datetime | None = None


class Consensus(ApiModel):
    home_id: str
    state: State
    rule_version: str
    sources: list[SourceVerdict]
    agreement: Agreement
    explanation: Explanation | None = None
    acknowledged_by: str | None = None
    safety_since: datetime | None = None
    simulated: bool = Field(default=False, description="the record contains simulated observations (provenance "
                                                       "flag; never written into headline or text)")
    computed_at: datetime


class SourceBadge(ApiModel):
    source: ConsensusSource
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    last_data_at: datetime | None = None


class PatientSummary(ApiModel):
    id: str
    display_name: str
    state: State
    agreement: Agreement
    headline: str
    sources: list[SourceBadge]
    last_activity_at: datetime | None = None
    safety_since: datetime | None = None
    acknowledged: bool = False
    sim: bool = False


class PatientsResponse(ApiModel):
    """Ranked: safety, needs_call, watch, stable (see STATE_RANK)."""

    patients: list[PatientSummary]
    rule_version: str


class TimelinePoint(ApiModel):
    date: date
    value: float | None
    baseline_median: float | None = None
    band_low: float | None = None
    band_high: float | None = None
    early: bool = Field(default=False, description="this day's baseline is a provisional one of a young record")


class MetricSeries(ApiModel):
    metric: str
    label: str
    unit: str = ""
    source: ConsensusSource
    worse_when: Literal["up", "down"]
    scored: bool = Field(default=True, description="false = shown and citable against the person's usual, never part "
                         "of the group's verdict (criteria `role = \"shown\"`, or weight 0)")
    points: list[TimelinePoint]


class TimelineResponse(ApiModel):
    patient_id: str
    series: list[MetricSeries]


class Phq9Entry(ApiModel):
    ts: datetime
    total: int = Field(ge=0, le=27)
    item9_positive: bool
    mode: Literal["spoken", "laptop"]


class Phq9History(ApiModel):
    patient_id: str
    entries: list[Phq9Entry]
    next_due: date | None = None


class ActionRequest(ApiModel):
    action: ActionName
    note: str | None = Field(default=None, max_length=500)
    by: str | None = Field(default=None, max_length=80, description="clinician name/initials (demo)")
    ts: datetime | None = Field(default=None, description="when the action really happened (default: now). Never in "
                                                          "the future; lets a call be logged after the fact")


class ActionResult(ApiModel):
    ok: bool
    patient_id: str
    action: ActionName
    state: State


class NudgeResponse(ApiModel):
    arm: NudgeArm
    reason: str
    probs: dict[str, float] = Field(default_factory=dict)


class HelpStat(ApiModel):
    activity: str
    label: str
    tries: int = Field(ge=0)
    mean_effect: float | None = Field(default=None, description="mean reward 0..1")


MascotMood = Literal["idle", "happy", "cozy", "crisis"]


class Mascot(ApiModel):
    """Kaiku's ambient mood (plan 02 §2): a pure function of the consensus state, computed once in the cloud so every
    surface shows the same thing. Never sad or worried at the person: stable -> idle/happy, watch -> cozy,
    needs_call -> cozy + the nurse-chat offer, safety -> "crisis" (clients show the scripted crisis screen from
    config/safety_phrases.toml: no animation, no character lines; line_key is then null)."""

    mood: MascotMood
    line_key: str | None = Field(default=None, description="key in config/voice_lines.toml (GET /v1/voice/{key})")


class Highlight(ApiModel):
    """One line for "Your days": a good moment or a gentle note about a harder day. Plain, friendly, never clinical."""

    date: date
    kind: Literal["good", "hard"]
    text: str = Field(max_length=200)
    source: ConsensusSource


class GardenDay(ApiModel):
    """One plot of the garden: what was done together that local day (kinds: ritual, drum_session, play_session,
    outing, friend_link, weather_check). A quiet day is an empty plot, never a wilted one."""

    date: date
    count: int = Field(0, ge=0)
    kinds: list[str] = Field(default_factory=list)


class Garden(ApiModel):
    """Reward only (no data). plants = finished interactions in the last 14 days; resting after 3 quiet days.
    It never wilts and there is no streak counter. `days` = the last 14 local days, oldest first (one plot each)."""

    plants: int = Field(0, ge=0)
    resting: bool = False
    days: list[GardenDay] = Field(default_factory=list)


class MeResponse(ApiModel):
    """Person-facing view. Plain language, never alarming."""

    home_id: str
    summary: str
    last_week: list[str] = Field(default_factory=list, description="short plain-language lines")
    what_helps: list[HelpStat] = Field(default_factory=list)
    next_suggestion: NudgeResponse | None = None
    phq9_due: bool = False
    mascot: Mascot = Field(default_factory=lambda: Mascot(mood="idle", line_key="greet.morning"))
    highlights: list[Highlight] = Field(default_factory=list, description="last 7 days, newest first")
    garden: Garden = Field(default_factory=Garden)
    sim: bool = False


VoiceLang = Literal["en", "fi", "sv"]


class Invitation(ApiModel):
    """One thing Kaiku would like to bring up or offer now. Chosen by code; `text` is a template from
    config/voice_lines.toml (`voice_key`) around the person's own stored words. On yes the device opens Talk
    (kind talk_about: the session card already carries the thread) or the screen for `activity`."""

    id: str = Field(description="send it back in the answer; an answered item is never offered again")
    kind: Literal["talk_about", "activity"]
    text: str = Field(max_length=200)
    voice_key: str = Field(description="the template used; speak `text` with POST /v1/voice/say")
    topic: str | None = Field(default=None, description="talk_about: what was left open")
    activity: Activity | None = Field(default=None, description="activity: which screen")


class InvitationResponse(ApiModel):
    """GET /v1/me/invitation — at most one invitation a day per home; null when there is nothing to offer, when
    today's was answered, or on an extra-gentle day with nothing to talk about."""

    home_id: str
    invitation: Invitation | None = None
    agreed: list[AgreedActivity] = Field(
        default_factory=list, description="what the person said yes to today, on any device (D50), oldest first. "
        "While one is open or started the invitation waits (`invitation` is null)")


class InvitationAnswer(ApiModel):
    """POST /v1/me/invitation/answer — yes: the device opens it. not_now: final. Either way the item is settled."""

    id: str
    answer: Literal["yes", "not_now"]


# ------------------------------------------------------------------ an activity agreed in one place (D50)
AgreedState = Literal["open", "started", "done", "put_aside"]


class AgreedActivity(ApiModel):
    """One activity the person said yes to in a conversation, held by the cloud for that local day so every
    screen shows the same thing (tool `agree_activity`). `text` is a template from config/voice_lines.toml
    (`voice_key`) around the activity's name and where it was agreed: never the person's words. It becomes
    `done` by itself when an observation for that activity arrives the same day; a device reports `started`
    (opened) or `put_aside` with POST /v1/me/agreed/answer. Gone after local midnight."""

    id: str = Field(description="send it back in the answer; also the id in the stream's `agreed` events")
    kind: Activity
    name: str = Field(max_length=40, description='how the activity is called on a screen ("Lantern", "a walk")')
    text: str = Field(max_length=200, description="the sentence for the card and the notification")
    voice_key: str = Field(description="the template used; speak `text` with POST /v1/voice/say")
    line: str | None = Field(default=None, max_length=80, description="Kaiku's own short line from the "
                             "conversation, when it gave one and it passed the wording rules")
    surface: Surface = Field(description="where it was agreed")
    at: datetime = Field(description="when it was agreed")
    day: date = Field(description="the local day it belongs to; it is not shown on any other day")
    when: AgreeWhen = Field(default="now", description="now: they want to do it now, on another device. later: "
                            "some time today")
    state: AgreedState
    state_at: datetime | None = Field(default=None, description="when it was opened, done or put aside")
    on: list[Surface] = Field(default_factory=list, description="the person's screens that can open it")
    opens_here: bool = Field(default=False, description="the asking device (`surface` in the query) has a "
                             "screen for it; false: show it without an open button")


class AgreedAnswer(ApiModel):
    """POST /v1/me/agreed/answer — opened: this device opened the activity's screen (state started). put_aside:
    the person put it aside (final for today). Done needs no answer: the activity's own observation does it."""

    id: str
    answer: Literal["opened", "put_aside"]


class AgreedResult(ApiModel):
    """Result of the `agree_activity` tool when the yes was kept. A refusal is `ok=false` with `error` (a reason
    the model can say) and `result {agreed: false, reason}`; nothing is stored then."""

    agreed: Literal[True] = True
    id: str
    kind: Activity
    name: str = Field(max_length=40)
    when: AgreeWhen = "now"
    on: list[Surface] = Field(description="the person's screens that now show it and can open it")
    where: str = Field(max_length=60, description='say it this way: "your phone and your Mac"')
    already: bool = Field(default=False, description="this activity was already agreed and open today: nothing "
                          "new was added")
    listening: list[Surface] = Field(default_factory=list, description="screens whose app is open right now "
                                     "(the stream is connected): it appeared there this second. The others show "
                                     "it when the app is next opened")


class StreamHello(ApiModel):
    """GET /v1/me/stream, first frame of every connection (SSE `event: hello`, no id). `resync: true`: the
    `Last-Event-ID` the client sent could not be continued (another process, or too long ago), so events may
    have been missed: read `/v1/me`, `/v1/me/invitation` and whatever else the screen shows again."""

    home_id: str
    heartbeat_s: float = Field(gt=0, description="a `ping` at least this often; no frame for well over twice "
                               "this long means the connection is dead: reconnect with Last-Event-ID")
    last_id: str | None = Field(default=None, description="id of the newest event for this home, if any")
    resync: bool = False
    replayed: int = Field(default=0, ge=0, description="events sent again right after this frame")


class StreamAgreed(ApiModel):
    """SSE `event: agreed` — an agreed activity appeared or changed. Ids and kinds only: read the sentence with
    GET /v1/me/invitation. `open`: just agreed (show it, post the notification). `removed`: it is gone (take the
    card and any pending notification away)."""

    id: str
    kind: Activity
    state: AgreedState | Literal["removed"]
    surface: Surface = Field(description="where it was agreed")
    when: AgreeWhen = "now"
    on: list[Surface] = Field(default_factory=list, description="screens that can open it")
    day: date


class StreamDay(ApiModel):
    """SSE `event: day` — new observations were stored for this home: what a screen shows about today may have
    changed (a check-in on the robot, a walk, a game). Types and senders only, never a value."""

    day: date = Field(description="the local day the newest of them belongs to")
    types: list[str] = Field(default_factory=list, description='observation types, e.g. "obs.self_report"')
    sources: list[str] = Field(default_factory=list, description='who sent them, e.g. "hub", "phone"')


class StreamInvitation(ApiModel):
    """SSE `event: invitation` — today's invitation was answered on some device: take its card away."""

    id: str
    state: Literal["answered"] = "answered"


# ------------------------------------------------------------------ the person's own history (D48)
HistoryGroupKey = Literal["robot", "games", "walks", "checkins", "sleep_body", "mac", "camera"]
HISTORY_GROUPS: tuple[str, ...] = ("robot", "games", "walks", "checkins", "sleep_body", "mac", "camera")
HistoryDevice = Literal["robot", "phone", "mac", "glasses", "watch", "web"]
# How a History value is to be read (the practitioner side prints its own numbers and does not use this):
# number = as it is, with its unit · clock = minutes after local midnight · percent = a share from 0 to 1, shown
# times 100 with "%" (`unit` says what it is a share of, or is empty; `decimals` are the percent number's) ·
# duration = minutes, shown as hours and minutes from 60 on (`unit` empty). A client that does not know a format
# shows a plain number.
HistoryFormat = Literal["number", "clock", "percent", "duration"]
HistoryPerDay = Literal["average", "total", "highest", "lowest", "latest", "first", "count"]


class HistoryDay(ApiModel):
    """One local day of one measure."""

    date: date
    value: float
    sessions: int = Field(ge=1, description="readings that day that the value is made from")
    sim: bool = Field(default=False, description="some of that day's readings are simulated")


class HistoryUsual(ApiModel):
    """The person's own usual range for a measure, from their own earlier days. A range and nothing else."""

    low: float
    high: float


class HistoryValue(ApiModel):
    """One number of one session, ready to show."""

    key: str = Field(description="payload field, e.g. tempo_bpm")
    title: str
    value: float
    unit: str = ""
    format: HistoryFormat = "number"


class HistorySession(ApiModel):
    """One recorded session (a drum session, one game, a breathing round, a walk, one dial answer, one morning's
    watch summary) with its own numbers."""

    id: str = Field(description="the observation's id")
    ts: datetime
    device: HistoryDevice
    sim: bool = False
    warmup: bool | None = Field(default=None, description="games: a practice session, left out of the day's value")
    label: str | None = Field(default=None, description="which kind of session, where one measure lists several "
                                                        "(a ritual step: Breathing, Drumming)")
    values: list[HistoryValue] = Field(default_factory=list, max_length=16)


class HistoryMeasure(ApiModel):
    """One measure over the window: its days, the person's usual range when there is one, and its latest sessions."""

    key: str = Field(description="stable key; for a measure the practitioner side also computes, the same name")
    title: str
    unit: str = ""
    format: HistoryFormat = Field(default="number", description="clock: minutes after local midnight; percent: a "
                                  "share 0..1 shown as a percentage; duration: minutes shown as hours and minutes. "
                                  "`usual` is in the same format")
    decimals: int = Field(default=0, ge=0, le=2, description="how many decimals the value is worth showing with")
    per_day: HistoryPerDay = Field(description="how one day's value is made from that day's sessions")
    devices: list[HistoryDevice] = Field(description="where its readings came from in this window, most first "
                                                     "(head, sensors and hub are all the robot)")
    days: list[HistoryDay] = Field(description="days with a value, oldest first; a day without data is absent")
    usual: HistoryUsual | None = None
    sessions: list[HistorySession] = Field(default_factory=list, max_length=30, description="newest first")
    sim: bool = False


class HistoryGroup(ApiModel):
    key: HistoryGroupKey
    title: str
    measures: list[HistoryMeasure]


class PersonHistory(ApiModel):
    """GET /v1/me/history?home_id=&days= — the person's own numbers, as a health app shows them: every measure
    the home has produced, from every device, by local day, with the latest sessions one tap away. Groups come in
    a fixed order (robot, games, walks, checkins, sleep_body, mac, camera); a group or measure with no data in the
    window is left out. `camera` holds the face signs counted with "Camera during activities" on (D52): her own
    numbers like every other group, never a word for what they might mean. It is the one person-facing place where numbers are shown (D48), and it carries numbers only:
    never a state, a verdict, a score against the usual, a flag, a weight, a direction word, anything from the
    practitioner's review, a safety flag or a questionnaire answer."""

    home_id: str
    days: int = Field(ge=1, le=90, description="the window asked for")
    first_day: date
    last_day: date
    timezone: str
    groups: list[HistoryGroup]
    sim: bool = Field(default=False, description="the window contains simulated readings")
    generated_at: datetime


# ------------------------------------------------------------------ one day, for developers (GET /v1/debug/day)
class DebugEvent(ApiModel):
    """One stored envelope of the day."""

    id: str
    ts: datetime
    local_time: str = Field(description="HH:MM:SS in the home's timezone")
    source: str = Field(description="the envelope's own source (head, sensors, hub, phone, laptop, glasses, ...)")
    type: str
    sim: bool
    quality: float | None = None
    payload: dict[str, Any] = Field(description="compact: long lists are cut to their first items plus a count")
    metrics: list[str] = Field(default_factory=list, description="metrics this envelope counted toward")
    day: date | None = Field(default=None, description="the local day this envelope counts toward (a daily summary "
                                                       "can be stamped on the day after the one it measures)")


class DebugBaseline(ApiModel):
    median: float
    spread: float = Field(description="max(1.4826 x MAD, min_mad): what one z unit is")
    days: int = Field(ge=0, description="days the baseline is made from")
    early: bool = Field(default=False, description="provisional baseline of a young record")


class DebugMetric(ApiModel):
    """One criteria metric on that day, beside its baseline."""

    id: str = Field(description="citable id: metric:<name>")
    metric: str
    label: str
    unit: str = ""
    source: ConsensusSource
    obs: str
    value: float | None = Field(default=None, description="the day's value; null = no data that day")
    partial: bool = Field(default=False, description="today's running total of a summed or counted measure: shown, "
                                                     "but not compared or scored until the day is over (no z)")
    readings: int = Field(default=0, ge=0, description="envelopes that day that counted toward it")
    baseline: DebugBaseline | None = None
    z: float | None = Field(default=None, description="(value - median) / spread, as measured")
    worse_z: float | None = Field(default=None, description="the same, signed so that positive is the worse direction")
    direction: Literal["up", "down"] = Field(description="criteria worse_when")
    z_threshold: float
    beyond_today: bool = Field(default=False, description="this day alone is beyond the threshold in the worse direction")
    status: Literal["drifting", "improved", "normal", "insufficient"]
    worse_days: int = Field(default=0, ge=0)
    better_days: int = Field(default=0, ge=0)
    scored_days: int = Field(default=0, ge=0, description="days in the drift window that had a baseline")
    drift_days_needed: int = Field(ge=1)
    weight: float = Field(ge=0)
    enabled: bool
    scored: bool = Field(description="false = observe-only (disabled, weight 0, or criteria role shown): charted, "
                                     "never a vote")
    flagged: bool = Field(default=False, description="counted toward its group's worse weight that day")
    event_ids: list[str] = Field(default_factory=list, max_length=20)


class DebugVerdict(ApiModel):
    """One signal group's verdict that day with what made it."""

    id: str = Field(description="citable id: source:<name>")
    source: ConsensusSource
    label: str
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    min_confidence: float
    worse_weight: float = Field(ge=0, description="sum of the weights of its drifting metrics")
    worse_min_weight: float
    better_weight: float = Field(ge=0)
    better_min_weight: float
    rules_fired: list[str] = Field(default_factory=list)
    evidence: list[VerdictEvidence] = Field(default_factory=list)
    days_with_data: int = Field(default=0, ge=0, description="in the baseline window up to that day")
    last_data_at: datetime | None = None
    previous: Verdict | None = Field(default=None, description="its verdict the day before")
    insufficient_reason: Literal["stale", "low_confidence", "no_usable_metric"] | None = Field(
        default=None, description="only when the verdict is insufficient, in the rule's own order: stale = nothing "
        "newer than the group's max_age_days; low_confidence = confidence below min_confidence; no_usable_metric = "
        "no scored measure has a usable baseline and no rule fired")


class DebugConsensus(ApiModel):
    id: Literal["consensus:state"] = "consensus:state"
    state: State
    raw_state: State = Field(description="what the rule gives for that day alone, before hysteresis")
    held: bool = Field(default=False, description="needs_call kept by hysteresis")
    agreement: Agreement
    rule_version: str
    reasons: list[str] = Field(default_factory=list, description="by code: why the rule gives this state")
    previous_state: State | None = None
    changed: list[str] = Field(default_factory=list, description="by code: what differs from the day before")
    acknowledged_by: str | None = None
    safety_since: datetime | None = None
    state_since: date | None = None


class DebugFeel(ApiModel):
    """One `feel` call: enums only, never what was said."""

    ts: datetime
    kind: str
    valence: str
    energy: str | None = None
    tone: list[str] = Field(default_factory=list)
    via: str | None = None
    stance: str | None = Field(default=None, description="the plan's stance; null for calls stored before it was kept")
    depth: str | None = None
    offered: bool | None = Field(default=None, description="the plan carried an offer")


class DebugConversation(ApiModel):
    """One companion conversation that started that day. Never transcripts, topics or words."""

    session_id: str
    surface: Surface
    intent: Intent
    start: datetime
    end: datetime | None = None
    minutes: float | None = None
    outcome: EpisodeOutcome | None = Field(default=None, description="how it ended; null = never closed")
    tools: list[str] = Field(default_factory=list, description="tool names: in call order while the conversation "
                                                               "is open, one of each once the device has uploaded it")
    tools_in_order: bool | None = Field(default=None, description="true = `tools` is the call order (repeats kept); "
                                        "false = the device's upload replaced it with one of each, sorted by name; "
                                        "null = cannot be told (a conversation uploaded before this was recorded)")
    feel: list[DebugFeel] = Field(default_factory=list)
    billed_minutes: float | None = Field(default=None, description="Live minutes the budget ledger counts for it")
    transcript_kept: bool = False


class DebugModelCall(ApiModel):
    ts: datetime
    provider: str = Field(description="gemini | gemma-hosted | modal | none (a deterministic or template answer)")
    model: str
    task: str
    route: str | None = None
    ok: bool
    fallback: bool = False
    latency_ms: float | None = None
    tokens_in: int | None = Field(default=None, description="not recorded by the ledger today: null")
    tokens_out: int | None = None
    est_usd: float | None = Field(default=None, description="the spend ledger's estimate for this call, when one "
                                                            "row matches it by model, task and time")
    cache_hit: bool | None = Field(default=None, description="null: the ledger does not record cache hits")


class DebugFact(ApiModel):
    """One verified line the day read may cite. Ids: metric:<name>, source:<name>, consensus:state,
    missing:<source or metric>, tomorrow:<name>, event:<envelope id>."""

    id: str
    kind: Literal["metric", "source", "consensus", "missing", "tomorrow", "event"]
    label: str
    detail: str = Field(description="written by code from the day's data; every number in it is the data's")
    numbers: list[float] = Field(default_factory=list, description="the numbers a claim citing this may use")
    flags: dict[str, bool] = Field(default_factory=dict, description="the yes/no facts a claim citing this may state, "
                                   "checked like the numbers: held, acknowledged, safety (consensus), enough_data "
                                   "(a signal group), scored (a measure)")


class DebugClaim(ApiModel):
    text: str = Field(max_length=500)
    cites: list[str] = Field(min_length=1, max_length=8, description="DebugFact ids (the model is asked for six at most)")
    by_code: bool = Field(default=False, description="inside a Gemma read: this line is code's own, put there because "
                                                     "the model left the measure out or its sentence failed a check")


DebugReading = Literal["as_usual", "slight_shift", "clear_shift", "not_enough_data"]


class DebugRead(ApiModel):
    """A developer-facing reading of the day, written from the structured data above. Gemma's when `by` is gemma
    (every claim cites facts, every number is one of theirs); otherwise the same shape written by code. It never
    changes the consensus."""

    by: Literal["gemma", "deterministic"]
    model: str | None = None
    cached: bool = False
    fallback_reason: str | None = Field(default=None, description="why the deterministic read is shown: "
                                        "not_requested | provider_unavailable | over_budget | invalid_json | "
                                        "no_valid_claims | cooldown")
    failed: bool = Field(default=False, description="the model was asked about exactly this day's data and nothing "
                         "valid came back; kept with its reason and rejections until the day's data, the rule or the "
                         "instruction changes, and not asked (or paid for) again before that")
    attempts: int = Field(default=0, ge=0, description="model calls this ask made (0 = the model was not asked)")
    latency_ms: float | None = Field(default=None, description="how long the ask took, all attempts together")
    est_usd: float | None = Field(default=None, description="the spend ledger's estimate for the ask: its rows for "
                                                            "this task and model while the ask ran")
    reading: DebugReading = Field(description="by code, from the day's metrics: never the model's call")
    summary: DebugClaim
    moved: list[DebugClaim] = Field(default_factory=list, description="which measures moved, and by how much")
    missing: list[DebugClaim] = Field(default_factory=list, description="what the day lacks")
    tomorrow: list[DebugClaim] = Field(default_factory=list, description="what would change the state tomorrow")
    rule_check: DebugClaim | None = Field(default=None, description="whether the rule's answer looks right")
    rejected: dict[str, int] = Field(default_factory=dict, description="validator category -> claims dropped, over "
                                                                        "all attempts of the ask")
    digest: str = Field(description="hash of the read version, the instruction, rule version, model and the day's data")
    generated_at: datetime


class DebugDay(ApiModel):
    """GET /v1/debug/day?home_id=&date=&generate= — everything about one local day of one home, for developers.
    Not for a practitioner and never for the person. Closed like /v1/admin on a deployed service. `generate`
    defaults to false: a plain GET never calls a model; `generate=true` asks for Gemma's read of the day."""

    home_id: str
    date: date
    timezone: str
    day_start: datetime = Field(description="local midnight that starts the day, in UTC")
    day_end: datetime = Field(description="local midnight that ends it, in UTC")
    is_today: bool = False
    first_day: date | None = Field(default=None, description="the first local day of the home's record (a day picker "
                                                             "has nothing before it); null = no record yet")
    sim: bool = False
    events: list[DebugEvent] = Field(description="every stored envelope stamped inside the day, plus a daily summary "
                                                  "that measures this day but arrived later; oldest first")
    events_total: int = Field(ge=0)
    metrics: list[DebugMetric]
    verdicts: list[DebugVerdict]
    consensus: DebugConsensus
    conversations: list[DebugConversation] = Field(default_factory=list)
    model_calls: list[DebugModelCall] = Field(default_factory=list)
    facts: list[DebugFact] = Field(default_factory=list, description="everything the read may cite")
    read: DebugRead
    computed_at: datetime


class VoiceLinesResponse(ApiModel):
    """GET /v1/voice?lang= — every keyed line Kaiku says (config/voice_lines.toml), for captions and offline use.
    Audio for one line: GET /v1/voice/{line_key}?lang= (audio/wav, cached; 503 + JSON hint without a TTS key)."""

    lang: VoiceLang
    voice: str = Field(description="Gemini prebuilt voice name (config/kaiku.toml [voice])")
    model: str
    lines: dict[str, str]


class VoiceSayRequest(ApiModel):
    """POST /v1/voice/say — any short line (not in voice_lines.toml) in Kaiku's one voice → audio/wav. Cached by
    (model, voice, lang, text, style); home token required. A crisis phrase in `text` → 422 (the crisis script is
    shown verbatim, never voiced from here)."""

    text: str = Field(min_length=1, max_length=400)
    lang: VoiceLang = "en"


class StateScore(ApiModel):
    precision: float | None
    recall: float | None


class EvalResult(ApiModel):
    """Simulation on synthetic patients with known onset. Not clinical accuracy."""

    n_patients: int
    rule_version: str
    per_state: dict[str, StateScore]
    false_needs_call_per_patient_month: float
    median_lead_time_days: float | None
    ablation: dict[str, StateScore] = Field(default_factory=dict, description="needs_call score with one source removed")
    generated_at: datetime
    sim: bool = True


class Healthz(ApiModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    schema_version: int
    db: bool
    llm: str
    time: datetime


class LiveEventsResponse(ApiModel):
    """GET /v1/events?home_id=&since=&limit= — recent obs for the /live page."""

    events: list[Envelope[dict[str, Any]]]


class NodeHealthReport(ApiModel):
    """PUT /v1/health/{home_id} — hub reports its nodes' heartbeats (derived status only)."""

    nodes: dict[str, Health]
    uplink_queue: int = 0
    uplink_lag_s: float | None = None
    reported_at: datetime


class HealthOverview(ApiModel):
    """GET /v1/health — every home's last NodeHealthReport, for the /health page."""

    homes: dict[str, NodeHealthReport]


# ----------------------------------------------------------------- criteria tuning (config/criteria.toml)
class CriteriaResponse(ApiModel):
    """GET /v1/admin/criteria — the criteria in effect (file default, or a live override)."""

    criteria: Criteria
    rule_version: str
    origin: Literal["file", "override"]
    updated_at: datetime | None = None
    updated_by: str | None = None


class CriteriaUpdate(ApiModel):
    """PUT /v1/admin/criteria (apply) and POST /v1/admin/criteria/preview (dry run). criteria=None resets to file."""

    criteria: Criteria | None
    by: str | None = Field(default=None, max_length=80)


class PreviewChange(ApiModel):
    patient_id: str
    display_name: str
    from_state: State
    to_state: State
    from_sources: dict[str, Verdict]
    to_sources: dict[str, Verdict]


class CriteriaPreview(ApiModel):
    """Who would change state under the candidate criteria (nothing is saved)."""

    current_rule_version: str
    candidate_rule_version: str
    changes: list[PreviewChange]
    unchanged: int
    eval: EvalResult | None = Field(default=None, description="simulation under the candidate, if requested")


# ----------------------------------------------------------------- companion mind (plan 03 §3–§6, plan 04 scope guard)
ToneCue = Literal["steady", "gentle", "extra-gentle"]
EpisodeOutcome = Literal["completed", "skipped", "ended_early", "crisis", "offline"]


ChatDepth = Literal["brief", "stay"]
Stance = Literal["comfort", "celebrate", "steady", "explore", "give_space"]


class HeardTone(ApiModel):
    """How a conversation sounded to the model that was in it, reported through the `feel` tool. An observation
    by a model, never a measurement and never a state. `model_heard`: the native-audio voice model heard the
    person speak. `model_read`: it went by their typed or transcribed words only."""

    valence: Valence | None = None
    energy: Energy | None = None
    tone: list[Tone] = Field(default_factory=list, max_length=2)
    provenance: Literal["model_heard", "model_read"]
    moments: int = Field(default=1, ge=1, description="how many times a feeling was noticed in that conversation")


class LastReflection(ApiModel):
    """How the latest talk with Kaiku went: a level and themes, never the words."""

    when: str = Field(description='e.g. "yesterday evening", "this morning"')
    valence: Valence | None = None
    themes: list[str] = Field(default_factory=list, max_length=3)
    declined: bool = Field(default=False, description="they did not want to talk or asked to stop")
    tone: list[Tone] = Field(default_factory=list, max_length=2, description="from their words (rules or Gemma)")
    energy: Energy | None = None
    heard: HeardTone | None = None


class FeelPlan(ApiModel):
    """Result of the `feel` tool: how to meet what the person just shared. Chosen by code from this person's own
    record; hints for the companion's own words, never a script. Nothing here is a state or changes one."""

    stance: Stance
    depth: ChatDepth = Field(description="brief: an ordinary moment, the chat may stay small. stay: a strong "
                             "feeling either way, repeated heaviness, or they keep talking: never close first")
    reflect_hint: str = Field(max_length=300)
    recall: str | None = Field(default=None, max_length=240, description="one thing the record knows that fits")
    may_offer: str | None = Field(default=None, max_length=120, description="one small thing to offer once, or null")
    offer_note: str | None = Field(default=None, max_length=240, description="why that one, and how to offer it")
    offer_activity: Activity | None = Field(default=None, description="start_activity kind, only after a clear yes")
    offer_elsewhere: Activity | None = Field(default=None, description="the offer has no screen on this device but "
                                             "one on their phone or Mac: after a clear yes call agree_activity "
                                             "with this kind (D50)")
    follow_up_saved: bool = Field(default=False, description="a thread to ask about next time was kept")
    manner: str | None = Field(default=None, max_length=240, description="a words-only cue for how to carry "
                               "yourself in this conversation (go more gently), never something to say, and never "
                               "a number, a state or where the cue came from (D52)")
    scheduling: Literal["INTERRUPT", "WHEN_IDLE", "SILENT"] = Field(
        default="WHEN_IDLE", description="Live FunctionResponse scheduling for this non-blocking tool: send it as "
        "`response.scheduling` so the model answers with the plan as soon as it is idle")


class WalkGuide(ApiModel):
    """CompanionSessionResponse.walk: how the device keeps a walk going. A Live session only answers input, so the
    device nudges: it sends `look_prompt` as a context text turn every `look_every_s` while the camera is on and
    nobody is speaking, and `quiet_prompt` once after `quiet_after_s` without anyone speaking. Null = that nudge
    is not used in this style. Values: config/kaiku.toml [walk].
    Kaiku answers a nudge in words only when there is something to say. A declined nudge has no words but is not
    always silent (real sessions: often a second or two of non-speech sound, transcribed `<no speech>` or `×`),
    so the device holds the audio of a nudge's reply until its first output transcription fragment and plays it
    only when that fragment has a real word."""

    style: WalkStyle
    look_every_s: int | None = Field(default=None, ge=1)
    look_prompt: str | None = None
    quiet_after_s: int | None = Field(default=None, ge=1)
    quiet_prompt: str | None = None


class ActivityCardResult(ApiModel):
    """What the device returns for `suggest_activity`. shown=false: a card is already up, or they said no before."""

    ok: bool
    shown: bool = False


class WalkGoalResult(ApiModel):
    """What the device returns for `set_walk_goal`: the count it keeps."""

    thing: str = Field(max_length=30)
    target: int = Field(ge=1, le=5)
    found: int = Field(default=0, ge=0)
    left: int = Field(ge=0)


class WalkMomentResult(ApiModel):
    """What the device returns for `log_walk_moment` (one find). Without a goal: ok=true, the counts null, and
    `note` tells the model that nothing was counted and to call `set_walk_goal` first, then log the find again."""

    ok: bool
    thing: str | None = None
    found: int | None = Field(default=None, ge=0)
    target: int | None = None
    left: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, description="for the model, when there was no goal to count against")


class ChatShape(ApiModel):
    """How this conversation should run, for the device: the same guidance the model reads in its instruction."""

    purpose: Purpose
    depth: ChatDepth
    open_items: list[CheckinItem] = Field(default_factory=list, description="check-in dials not answered today")


class ContextCard(ApiModel):
    source_context: list[str] = Field(default_factory=list, max_length=4, description="prepared source-labelled activity facts; no clinical metrics or raw content")
    """What the model is told about today — deterministic, small, built by the cloud. Never the consensus state,
    scores, numbers or watch data: `tone` is the only (soft) cue derived from the consensus."""

    language: VoiceLang = "en"
    intent: Intent = "talk"
    time_of_day: Literal["morning", "afternoon", "evening", "night"]
    weather_word: str | None = None
    first_name: str | None = Field(default=None, description="only if the person told Kaiku their name")
    done_today: list[str] = Field(default_factory=list, max_length=4, description="on any surface")
    suggestion: str | None = Field(default=None, description="today's bandit suggestion, phrased")
    phq9_due: bool = False
    memories: list[str] = Field(default_factory=list, max_length=3)
    routines: list[str] = Field(default_factory=list, max_length=2, description='e.g. "usually walks on Tuesdays"')
    open_thread: str | None = Field(default=None, description="topic left open on any surface")
    tone: ToneCue = "steady"
    care_info: str | None = None
    focus: str | None = Field(default=None, description="today's focus, chosen by the daily reflection from fixed options")
    last_reflection: LastReflection | None = None
    today_facts: list[str] = Field(default_factory=list, max_length=4, description='plain facts the person recorded '
                                   'themselves today, in everyday words ("a short night"); never a number or a judgement')
    recent_reflection: str | None = Field(default=None, description="how the latest reflection with Kaiku went, as a "
                                          "level and themes only (never the words), so Kaiku can be gentle about it")
    purpose: Purpose | None = Field(default=None, description="set when the device said why it opened the session")
    chat_depth: ChatDepth | None = Field(default=None, description="check-in sessions: how the chat should open")
    open_items: list[CheckinItem] = Field(default_factory=list, max_length=3, description="check-in sessions: dials "
                                          "not answered today; at most one is woven into the chat")
    walk_style: WalkStyle | None = Field(default=None, description="walk sessions: how Kaiku walks with them")
    outdoor_likes: list[str] = Field(default_factory=list, max_length=4, description="walk sessions: outdoor things "
                                     "and places the person told Kaiku they like, in their words (notebook)")
    agreed: list[str] = Field(default_factory=list, max_length=3, description="activities they said yes to today "
                              "on any device and whether each is done (D50); each is carried once per state, so "
                              "Kaiku is glad or asks gently once")
    quieter_in: list[Literal["games", "check_in"]] = Field(
        default_factory=list, max_length=2, description="today's tasks in which the face signs counted with their "
        "opt-in were clearly below their own usual (D52, rule in mind/face_cue.py). An enum and nothing else: the "
        "instruction turns it into a cue to go gently and never to mention their face or a camera; no number, no "
        "state and no word about how they looked ever crosses")
    others_present: bool = False
    dont_remember: bool = False


class CompanionSessionRequest(ApiModel):
    resume_session_id: str | None = Field(None, description="reuse an open session belonging to this home and surface")
    surface: Surface
    home_id: str
    intent: Intent = "talk"
    language: VoiceLang | None = Field(default=None, description="default: config/kaiku.toml [home].language")
    others_present: bool = False
    purpose: Purpose | None = Field(default=None, description="why the conversation was opened. check_in: a small "
                                    "passing chat alongside the periodic check-in (see chat_shape). Omitted = "
                                    "today's behaviour for the intent")
    walk_style: WalkStyle | None = Field(default=None, description="with purpose walk: quiet (mostly listens), "
                                         "playful (one small game at a time) or chatty (keeps a gentle "
                                         "conversation going). Omitted = config/kaiku.toml [walk].default_style")


class LiveToken(ApiModel):
    """Gemini Live ephemeral token: use `token` as the API key for ONE Live session (v1beta). Start within
    `new_session_expires_at`; the session may run until `expires_at`."""

    token: str
    expires_at: datetime
    new_session_expires_at: datetime


class CompanionTool(ApiModel):
    name: str
    description: str
    parameters: dict[str, Any]
    behavior: Literal["NON_BLOCKING"] | None = Field(default=None, description="Live asynchronous function calling: "
                                                     "declare it so and answer with the result's `scheduling`")


class CompanionSessionResponse(ApiModel):
    """POST /v1/companion/session — everything a device needs to open Gemini Live as Kaiku. `live_token` is null
    when Live is unavailable: the device reports unavailability and keeps the microphone closed."""

    session_id: str = Field(description="pass to /v1/companion/tool and /v1/companion/episode")
    context_refresh_seconds: int | None = Field(None, ge=1, description="poll interval for consented source updates during an active conversation")
    max_session_seconds: int | None = Field(None, ge=1, description="client-enforced maximum active session duration")
    model: str
    voice: str
    system_instruction: str
    tools: list[CompanionTool]
    context_card: ContextCard
    persona_version: str
    safety_phrases_version: str
    live_token: LiveToken | None = None
    live_setup: dict[str, Any] | None = Field(
        default=None, description="Kaiku's recommended Live BidiGenerateContentSetup (REST camelCase; the token locks only the model): model, "
        "voice, system instruction, tools, automatic VAD + barge-in, transcriptions. Send it as the first frame "
        "{setup: live_setup}; clients must apply this complete setup.")
    chat_shape: ChatShape | None = Field(default=None, description="present when the request named a purpose")
    walk: WalkGuide | None = Field(default=None, description="present when the purpose is walk")
    idle_end_s: int | None = Field(default=None, ge=1, description="the device ends the conversation by itself after "
                                   "this long with nobody speaking (an open microphone in a pocket); longer on a walk")


class CompanionToolCall(ApiModel):
    home_id: str
    surface: Surface
    session_id: str | None = None
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class CompanionToolResult(ApiModel):
    """`ok=false` + `error` when the call was refused (not on this surface, bad args, memory rule). `crisis=true`:
    a crisis phrase was in the arguments — nothing was stored, obs.safety_flag was raised; stop the session and
    show/say `result.script` verbatim. `executor=device`: the device performs the effect itself."""

    ok: bool
    name: str
    executor: Literal["cloud", "device"] = "cloud"
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    crisis: bool = False


class Memory(ApiModel):
    id: int
    category: MemoryCategory
    text: str
    created: datetime
    last_used: datetime | None = None


class MemoriesResponse(ApiModel):
    """GET /v1/me/memories — "What Kaiku remembers". Person-facing only; no clinician route returns memories."""

    home_id: str
    remember: bool = Field(description="false = the person turned remembering off")
    memories: list[Memory]


class MemorySettings(ApiModel):
    remember: bool


class DeletedResponse(ApiModel):
    deleted: int


class ThreadIn(ApiModel):
    skill: Skill
    topic: str = Field(max_length=80)


TranscriptRole = Literal["person", "kaiku"]


class TranscriptTurn(ApiModel):
    role: TranscriptRole
    text: str = Field(max_length=2000)
    complete: bool | None = Field(
        default=None,
        description="true when transcription explicitly finished; false when interrupted/not final; null or absent for unknown legacy status. Audio turnComplete does not establish transcription completion.")


class EpisodeIn(ApiModel):
    """POST /v1/companion/episode — one finished session (also for sessions run offline). Never audio.
    `transcript` only when the person opted in (device consent `transcripts`, off by default); the cloud drops it
    if the outcome is `crisis` or any turn matches a crisis phrase."""

    home_id: str
    surface: Surface
    intent: Intent = "talk"
    id: str | None = Field(default=None, description="session_id (or a client UUID); idempotent")
    start: datetime
    end: datetime | None = None
    tools_used: list[str] = Field(default_factory=list)
    outcome: EpisodeOutcome = "completed"
    open_thread: ThreadIn | None = None
    close_thread: bool = False
    transcript: list[TranscriptTurn] | None = Field(
        default=None, max_length=600,
        description="opt-in only; person-facing + deletable; never on a clinician route; de-identified for training")


class EpisodeResult(ApiModel):
    ok: bool
    id: str
    transcript_stored: bool = False


class SessionClose(ApiModel):
    """POST /v1/companion/close — the device says a conversation stopped and how long it ran. The cloud never
    sees the audio socket, so this is what brings the Live budget reservation down to the time really used
    (whole started minutes, at least one, never more than was reserved). Send it once when the conversation
    ends, whatever ended it; sending it again is harmless. It changes nothing else about the session."""

    home_id: str
    session_id: str = Field(description="CompanionSessionResponse.session_id")
    elapsed_s: float = Field(ge=0, le=86400, description="seconds from the conversation's start to its end, "
                                                         "across every token it used")


class SessionCloseResult(ApiModel):
    ok: bool
    session_id: str
    settled: int = Field(description="Live reservations this call settled or corrected (0: nothing to change)")
    billed_minutes: float = Field(description="started minutes now counted for this conversation")


class Transcript(ApiModel):
    """One stored conversation (opt-in). Person-facing only: no clinician route returns transcripts."""

    episode_id: str
    surface: Surface
    intent: Intent
    start: datetime
    turns: list[TranscriptTurn]


class TranscriptsResponse(ApiModel):
    """GET /v1/me/transcripts — the person's own stored conversations, newest first."""

    home_id: str
    transcripts: list[Transcript]


# ----------------------------------------------------------------- Gemini-first mind (plan 06 §1–§3)
MindRoute = Literal["memory", "gemma", "flash", "argon", "fallback"]


class MindAnswer(ApiModel):
    """`result` of the `ask_mind` tool (CompanionToolResult.result). `answer` is ready to say: citation tags are
    verified and stripped by code. `ask_person=true`: Kaiku found conflicting notes and should ask, not pick.
    `route`: memory = answered by code (no model) · flash · argon · fallback = scripted hand-off line."""

    answer: str
    kind: MindKind
    route: MindRoute
    confidence: float = Field(ge=0, le=1)
    cites: list[str] = Field(default_factory=list, description="verified ids: mem:<id> | kg:<id> | doc:<id>")
    ask_person: bool = False
    model: str | None = None


class ModelUsageRow(ApiModel):
    day: date
    model: str
    task: str
    calls: int = Field(ge=0)
    ok: int = Field(ge=0)
    fallbacks: int = Field(ge=0)
    p50_ms: float | None = None
    p95_ms: float | None = None


class IntelligenceHealth(ApiModel):
    """GET /v1/health/intelligence — usage ledger summary (no content is ever logged): which models ran, how often,
    how fast, how often we fell back. `routes` counts ask_mind outcomes (memory/flash/argon/fallback)."""

    since: date
    days: int
    rows: list[ModelUsageRow]
    per_model: dict[str, int]
    routes: dict[str, int]
    calls: int
    fallback_rate: float = Field(ge=0, le=1)
    p50_ms: float | None = None
    p95_ms: float | None = None


ConstellationType = Literal["me", "person", "place", "like", "helper", "plan", "activity"]


class ConstellationNode(ApiModel):
    id: int
    type: ConstellationType
    label: str


class ConstellationEdge(ApiModel):
    src: int
    dst: int
    rel: Literal["knows", "goes_to", "likes", "helped_by", "plans", "did", "helped", "about"]
    weight: float = Field(ge=0, le=1, description="0..1, for line thickness only")


class ConstellationResponse(ApiModel):
    """GET /v1/me/constellation — person-facing "Your constellation": people, places, activities, what helps.
    Built from what the person told Kaiku and what they did. Never health data, scores or states."""

    home_id: str
    nodes: list[ConstellationNode]
    edges: list[ConstellationEdge]


WeatherWord = Literal["sunny", "cloudy", "rainy", "snowy", "windy", "foggy", "grey", "frosty", "clear"]


class PostcardRequest(ApiModel):
    home_id: str
    minutes: int = Field(ge=0, le=600)
    finds: list[str] = Field(default_factory=list, max_length=5,
                             description="light-hunt finds as short words, e.g. 'green', 'bird'")
    weather_word: WeatherWord = "cloudy"


class PostcardResponse(ApiModel):
    """POST /v1/companion/postcard — an illustrated walk postcard (no photos, no faces). 503 + {detail, reason,
    hint} when image generation is unavailable: the app shows its own static card."""

    id: str
    url: str = Field(description="GET this path for the image")
    cached: bool
    model: str


class BriefSection(ApiModel):
    text: str = Field(max_length=600)
    metrics: list[str] = Field(default_factory=list, description="criteria metric names this sentence rests on")


class ClinicianBrief(ApiModel):
    """GET /v1/patients/{id}/brief — weekly clinician brief (flagship, grounded in metric ids; template fallback).
    Explains the consensus; never changes it."""

    patient_id: str
    week: str = Field(description="ISO week, e.g. 2026-W46")
    state: State
    rule_version: str
    sections: list[BriefSection]
    by: Literal["model", "template"]
    model: str | None = None
    generated_at: datetime


# ------------------------------------------------------------------ dashboard: the week + what Kaiku has learned
Audience = Literal["person", "care_team"]


class CareSharing(ApiModel):
    """GET/PUT /v1/me/sharing — the person's choice to show their care team what Kaiku has learned (the knowledge
    graph and routines from conversations). Default off (D34). People, places, likes and plans are never shared."""

    share_with_care_team: bool = False


class Routine(ApiModel):
    """A rhythm found BY CODE in the last weeks (obs, and conversations for the person or when shared)."""

    activity: str = Field(description="ritual | walk | drum | breathe | checkin | laptop | play | sleep")
    label: str
    cadence: Literal["daily", "most_days", "weekly"]
    weekday: str | None = Field(default=None, description="for weekly routines, e.g. 'Tuesday'")
    day_part: Literal["morning", "afternoon", "evening", "night"] | None = None
    usual_time: str | None = Field(default=None, description="local HH:MM (median of the usual weeks)")
    usual_per_week: float = Field(ge=0, le=7)
    this_week: int = Field(ge=0, le=7, description="days with it in the last 7 days")
    status: Literal["kept", "partly", "slipped"]
    text: str = Field(max_length=200, description="worded for the audience")
    basis: list[Literal["obs", "episodes"]] = Field(default_factory=list)


class WeekItem(ApiModel):
    kind: Literal["routine", "helped", "metric", "source", "phq9", "safety", "moments"]
    text: str = Field(max_length=240)
    source: ConsensusSource | None = None
    metric: str | None = Field(default=None, description="criteria metric name this rests on")


class SourceCount(ApiModel):
    label: str = Field(description="e.g. 'walks', 'minutes outside', 'drum sessions'")
    value: float = Field(ge=0)


class SourceWeek(ApiModel):
    """What one source added to the record in the last 7 days (counts only, no content)."""

    source: ConsensusSource
    per_day: list[int] = Field(min_length=7, max_length=7, description="observations per day, oldest first")
    days: int = Field(ge=0, le=7, description="days with data")
    counts: list[SourceCount] = Field(default_factory=list)
    last_at: datetime | None = None


class NextStep(ApiModel):
    """A suggested next step for the care team, chosen by fixed rules (never a model). Allowed wording only."""

    text: str = Field(max_length=240)
    why: str = Field(default="", max_length=240)
    when: Literal["today", "this_week", "next_contact"]
    action: ActionName | None = Field(default=None, description="the dashboard action that does it, if any")


class WeekSummary(ApiModel):
    """GET /v1/me/week (person wording) · GET /v1/patients/{id}/week (care team). Derived deterministically from
    obs, per-metric drift against the person's own usual, the bandit and (person / shared only) conversations.
    No model decides anything here; it never changes the consensus."""

    home_id: str
    audience: Audience
    week_start: date
    week_end: date
    routines: list[Routine]
    going_well: list[WeekItem]
    worth_a_look: list[WeekItem]
    shared: bool = Field(description="the person shares what Kaiku learned with the care team")
    rule_version: str | None = Field(default=None, description="care team only")
    sources: list[SourceWeek] = Field(default_factory=list, description="the one record: what each source added")
    next_steps: list[NextStep] = Field(default_factory=list, description="care team only")
    by: Literal["rule"] = "rule"
    computed_at: datetime


GraphNodeType = Literal["me", "person", "place", "like", "helper", "plan", "activity", "routine"]
GraphRel = Literal["knows", "goes_to", "likes", "helped_by", "plans", "did", "helped", "about", "keeps", "of"]


class GraphNode(ApiModel):
    id: int = Field(description="graph node id; negative = derived for this view (routines, obs-only activities)")
    type: GraphNodeType
    label: str
    evidence: int = Field(ge=0, description="how many observations / sessions / memories back this node")
    detail: str | None = Field(default=None, max_length=200)


class GraphEdge(ApiModel):
    src: int
    dst: int
    rel: GraphRel
    weight: float = Field(ge=0, le=1)
    evidence: int = Field(ge=0)


class KnowledgeGraph(ApiModel):
    """GET /v1/me/graph ("What Kaiku has learned") · GET /v1/patients/{id}/graph (only when the person shares;
    then activities, what helps and routines — never people, places, likes or plans: listed in `withheld`).
    Never health data, scores or states."""

    home_id: str
    audience: Audience
    shared: bool
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    withheld: list[GraphNodeType] = Field(default_factory=list)
    computed_at: datetime


# ------------------------------------------------------------------ practitioner insight (the intelligence layer)
Trend = Literal["better", "worse", "similar", "unknown"]
InsightActor = Literal["code", "gemma", "template"]


class ReviewFinding(ApiModel):
    """One claim in the review. `meaning`/`consider` are interpretation (Gemma when `by` = gemma: validated, no
    numbers, no state words); `facts` are rendered by code from the cited records and carry every number."""

    theme: Literal["change", "improvement", "steady", "routine", "what_helps", "coverage"]
    title: str = Field(max_length=120)
    meaning: str = Field(max_length=400, description="what it likely means, in plain words")
    consider: str | None = Field(default=None, max_length=300, description="what the practitioner could consider")
    facts: list[str] = Field(default_factory=list, description="verified record facts, numbers rendered by code")
    cites: list[str] = Field(default_factory=list, description="ids into PatientInsight.evidence")
    by: Literal["gemma", "template"]


class PatientReview(ApiModel):
    """Gemma's review of the person: what changed, what it likely means, what to consider. Never decides state."""

    headline: str = Field(max_length=240)
    overview: str | None = Field(default=None, max_length=700, description="Gemma's reading of the whole record: "
                                 "what started, what followed, what has come back, what has not. Null when the "
                                 "template answered; `PatientInsight.course.summary` is the code-written arc")
    overview_cites: list[str] = Field(default_factory=list, description="evidence ids the overview rests on")
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=8)
    by: Literal["gemma", "template"]
    model: str | None = None
    cached: bool = False
    day_of_record: int = Field(default=0, ge=0, description="calendar days since the first observation")
    early_record: bool = Field(default=False, description="baselines are provisional or missing: read every "
                                                         "comparison with lower confidence")
    fallback_reason: str | None = Field(
        default=None, description="content-free category when the template answered instead of the model, e.g. "
                                  "not_requested | provider_unavailable | invalid_json | no_valid_findings | cooldown")
    generated_at: datetime


class AgentStep(ApiModel):
    """One step the cloud really ran to build this insight. Counts and categories only; never record content."""

    step: Literal["retrieve", "consensus", "compare", "course", "select", "interpret", "overview", "validate",
                  "graph", "render"]
    label: str = Field(max_length=80)
    actor: InsightActor
    status: Literal["ok", "cached", "skipped", "rejected", "fallback"]
    model: str | None = None
    latency_ms: float | None = None
    cache_hit: bool = False
    items: int | None = Field(default=None, ge=0, description="how many records / findings / nodes this step handled")
    rejected: dict[str, int] = Field(default_factory=dict, description="validator category -> count")
    detail: str = Field(default="", max_length=300)


class MetricComparison(ApiModel):
    """One measure: this week vs the week before vs the person's own usual. Medians of recorded days."""

    metric: str
    label: str
    unit: str = ""
    source: ConsensusSource
    worse_when: Literal["up", "down"]
    this_week: float | None = None
    previous_week: float | None = None
    usual: float | None = Field(default=None, description="personal baseline median for the latest scored day")
    early_baseline: bool = Field(default=False, description="the usual is a provisional baseline of a young record")
    baseline_days: int | None = Field(default=None, ge=0, description="recorded days behind the usual")
    this_week_text: str | None = None
    previous_week_text: str | None = None
    usual_text: str | None = None
    days_this_week: int = Field(ge=0, le=7)
    days_previous_week: int = Field(ge=0, le=7)
    vs_previous: Trend
    vs_usual: Trend
    sustained: Literal["change_from_usual", "better_than_usual", "as_usual", "not_enough_data"] = Field(
        description="the rule engine's reading over recent days (criteria thresholds), not a one-week difference")
    meaning: str = Field(max_length=300)


class GroupComparison(ApiModel):
    source: ConsensusSource
    label: str
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    days_this_week: int = Field(ge=0, le=7)
    days_previous_week: int = Field(ge=0, le=7)
    trend: Trend = Field(description="this week vs the week before across this group's measures")
    meaning: str = Field(max_length=300)
    metrics: list[MetricComparison] = Field(default_factory=list)


class PeriodComparison(ApiModel):
    this_week_start: date
    this_week_end: date
    previous_week_start: date
    previous_week_end: date
    day_of_record: int = Field(default=0, ge=0)
    early_baseline: bool = Field(default=False, description="at least one usual here is a provisional baseline")
    summary: str = Field(max_length=400)
    since_low: str = Field(default="", max_length=240, description="against the spell's low point, e.g. '12 of 18 "
                           "measures back within usual since the low on 8 Nov'; empty when nothing moved")
    back_in_range: list[str] = Field(default_factory=list, description="metric names back within usual after a spell")
    still_away: list[str] = Field(default_factory=list, description="metric names still away from usual")
    improved: list[str] = Field(default_factory=list, description="metric names better than the week before")
    changed: list[str] = Field(default_factory=list, description="metric names worse than the week before")
    groups: list[GroupComparison] = Field(default_factory=list)


class HelpEffect(ApiModel):
    """What the learner has seen for one activity. A reported response, not proof that the activity caused it."""

    activity: str
    label: str
    tries: int = Field(ge=0)
    mean_effect: float | None = Field(default=None, ge=0, le=1, description="mean reward 0..1 (0.5 = neutral)")
    low: float | None = Field(default=None, ge=0, le=1, description="90% interval of the learner's estimate")
    high: float | None = Field(default=None, ge=0, le=1)
    certainty: Literal["early", "building", "consistent"]
    text: str = Field(max_length=240)


class LearnedRoutine(ApiModel):
    routines: list[Routine] = Field(default_factory=list)
    helps: list[HelpEffect] = Field(default_factory=list)
    kept: int = Field(ge=0)
    partly: int = Field(ge=0)
    slipped: int = Field(ge=0)
    summary: str = Field(max_length=300)
    day_of_record: int = Field(default=0, ge=0)
    early_record: bool = False
    caveat: str = Field(default="", max_length=300, description="how far the reported responses can be trusted")


class InsightNodeDay(ApiModel):
    """What one graph node has on one day of the record, by the same code as the course, the trends band and the
    daily account. A day with nothing for the node has no entry."""

    date: date
    tone: Trend = Field(default="unknown", description="measure: that day's reading against that day's own usual "
                        "(worse = away from usual, better = beyond usual on the favourable side, similar = within "
                        "usual, unknown = no personal usual yet); routine: similar = kept, worse = missed on a "
                        "recorded day; every other kind: unknown (recorded, not judged)")
    value: str = Field(default="", max_length=32, description="short printed form: '2 of 5', '07:22', 'missed'")
    text: str = Field(max_length=200, description="one plain clause by code: '2 of 5, below their usual 4 of 5'")


class InsightDomain(ApiModel):
    """A neighbourhood of the graph: what a group of nodes is about, and where it sits around the person. Declared
    once in config/kaiku.toml [graph]; the same for every person."""

    id: str
    label: str = Field(max_length=60)
    short: str = Field(max_length=24)
    place: Literal["n", "ne", "e", "se", "s", "sw", "w", "nw"]


class InsightChange(ApiModel):
    """One thing that is different on a day, pointing at its node. Text and order are written by code."""

    node: str
    kind: Literal["care", "moved_away", "came_back", "better", "missed", "first", "kept"]
    text: str = Field(max_length=240)
    tag: str = Field(default="", max_length=80, description="where it sits in the order of the change, when the "
                     "course has one: 'first to move', '1 day after the first change' (order in time, never cause)")


class InsightGraphDay(ApiModel):
    """One day of the graph's record: what changed that day and how many measures were away from usual."""

    date: date
    recorded: bool = Field(description="at least one observation or care action that day")
    away: int = Field(ge=0, description="measures away from their usual that day")
    changes: list[InsightChange] = Field(default_factory=list)


class InsightNode(ApiModel):
    id: str
    kind: Literal["person", "signal_group", "measure", "activity", "routine", "care_action", "shared_topic"]
    layer: Literal["learned", "structure"] = Field(default="structure", description="learned = found in this "
                                                   "person's record; structure = how the record is organised")
    label: str = Field(max_length=120)
    detail: str | None = Field(default=None, max_length=240)
    evidence: int = Field(ge=0, description="recorded days / observations / attempts behind this node")
    tone: Trend = "unknown"
    domain: str = Field(default="", description="id of the `InsightGraph.domains` entry this node is about; empty "
                        "for the person and the signal groups (who sent it is not what it is about)")
    days: list[InsightNodeDay] = Field(default_factory=list, description="oldest first, within `InsightGraph.days`")


class InsightEdge(ApiModel):
    src: str
    dst: str
    rel: Literal["has_signal", "measures", "did", "keeps", "of", "helped", "moved_first", "followed",
                 "moved_together", "kept_through", "slipped_during", "after", "talked_about", "produces", "about"]
    layer: Literal["learned", "structure"] = "structure"
    label: str = Field(max_length=80)
    weight: float = Field(ge=0, le=1)
    evidence: int = Field(ge=0)
    on: list[date] = Field(default_factory=list, description="the days this link is about, oldest first: the day "
                           "a measure followed, the days two measures were away together, the day it came back")
    tag: str = Field(default="", max_length=24, description="a few words for a badge: '+1 day', 'first'")


class InsightGraph(ApiModel):
    """What a practitioner may see of what Kaiku has learned: signal groups, measures, observed activities, routines
    and what helped. Built from observations; conversation counts join only when the person shares. Never people,
    places, likes, plans, memories or transcripts."""

    nodes: list[InsightNode] = Field(default_factory=list)
    edges: list[InsightEdge] = Field(default_factory=list)
    layers: list[Literal["learned", "structure"]] = Field(default_factory=list, description="layers present")
    shared: bool = Field(description="the person shares conversation-derived activity counts with the care team")
    basis: list[Literal["observations", "shared_conversations"]] = Field(default_factory=list)
    note: str = Field(default="", max_length=240)
    domains: list[InsightDomain] = Field(default_factory=list, description="the neighbourhoods, in declared order")
    days: list[InsightGraphDay] = Field(default_factory=list, description="every calendar day from the first to "
                                        "the last day with data inside the graph's window, oldest first")


class ObsTypeCoverage(ApiModel):
    type: str = Field(description="obs.* type")
    label: str
    count: int = Field(ge=0)
    days: int = Field(ge=0)
    last_at: datetime | None = None
    captured_by: list[str] = Field(default_factory=list, description="envelope sources that sent it (hub, phone, …)")
    simulated: int = Field(default=0, ge=0, description="how many of these observations carry sim=true")


class GroupCoverage(ApiModel):
    source: ConsensusSource
    label: str
    sufficient: bool = Field(description="enough recent usable data for this group to give a verdict")
    days_last_14: int = Field(ge=0, le=14)
    last_at: datetime | None = None
    types: list[ObsTypeCoverage] = Field(default_factory=list)


class DataCoverage(ApiModel):
    first_day: date | None = None
    last_day: date | None = None
    span_days: int = Field(ge=0)
    recorded_days: int = Field(ge=0)
    observations: int = Field(ge=0)
    baseline_ready: bool = Field(description="at least one measure has a personal baseline")
    day_of_record: int = Field(default=0, ge=0, description="calendar days since the first observation")
    early_baseline: bool = Field(default=False, description="baselines in use are provisional (young record)")
    simulated: bool = Field(description="the record contains simulated observations (envelope sim flag); the same "
                                        "value as Consensus.simulated and RecordCitation.simulated; per-type counts "
                                        "show how many")
    summary: str = Field(max_length=300)
    groups: list[GroupCoverage] = Field(default_factory=list)
    other: list[ObsTypeCoverage] = Field(default_factory=list, description="activity responses, ritual steps, flags")


class CourseEvent(ApiModel):
    """One dated point in the course of change. Text, dates and numbers are written by code."""

    date: date
    kind: Literal["onset", "lowest", "care_action", "phq9", "back_in_range", "still_away", "reflection_low",
                  "reflection_lighter"]
    group: ConsensusSource | None = None
    metric_id: str | None = None
    label: str = Field(max_length=120)
    text: str = Field(max_length=300)


class Course(ApiModel):
    """How the record has moved against the person's own usual: what moved first, what followed, what has come
    back, what has not. Temporal order only, never a cause. Computed by code from the daily series."""

    phase: Literal["settling", "steady", "dip", "recovering", "recovered"]
    low_date: date | None = Field(default=None, description="the day most measures were away from usual")
    moved: int = Field(default=0, ge=0, description="measures that moved away from usual in this spell")
    back: int = Field(default=0, ge=0, description="of those, how many are back within usual")
    summary: str = Field(max_length=900)
    events: list[CourseEvent] = Field(default_factory=list)


class DayAccount(ApiModel):
    """One day in plain words, built by code from every source: what was done, what was away from usual, how the
    reflection went (level and themes only, when shared)."""

    date: date
    text: str = Field(max_length=400)
    parts: list[str] = Field(default_factory=list)


class ReflectionDay(ApiModel):
    date: date
    part: Literal["morning", "afternoon", "evening"]
    valence: Literal["low", "neutral", "bright"] | None = None
    themes: list[str] = Field(default_factory=list)
    declined: bool = False
    tone: list[Tone] = Field(default_factory=list, max_length=2, description="from their words (rules or Gemma)")
    energy: Energy | None = None
    heard: HeardTone | None = Field(default=None, description="as reported by the model in the conversation")


class ReflectionOverview(ApiModel):
    """Reflections with Kaiku at summary level: how many sounded low / neutral / bright and what they were about.
    Present only when the person shares with the care team. Never their words."""

    shared: bool
    reflections: int = Field(ge=0, description="reflections with a summary in the last 7 days")
    low: int = Field(ge=0)
    neutral: int = Field(ge=0)
    bright: int = Field(ge=0)
    declined: int = Field(ge=0, description="the person asked to stop or did not want to talk")
    themes: list[SourceCount] = Field(default_factory=list, description="theme -> reflections it came up in")
    days: list[ReflectionDay] = Field(default_factory=list, description="the last 14 days, oldest first")
    summary: str = Field(max_length=400, description="the fortnight in one or two sentences; counts are 7 days")
    tone_summary: str | None = Field(default=None, max_length=400, description="how they sounded, by provenance: "
                                     "tone of their words, and tone as reported by the model in the conversation")


class StateDay(ApiModel):
    """The deterministic consensus replayed for one day of the record."""

    date: date
    state: State
    agreement: Agreement
    early: bool = Field(description="fewer days on record than min_history_days_for_stable: never stable yet")


class CareAction(ApiModel):
    ts: datetime
    action: ActionName
    note: str | None = None
    by: str | None = None


class PatientInsight(ApiModel):
    """GET /v1/patients/{id}/insight — everything the intelligence layer knows that a practitioner may see, in one
    payload: Gemma's evidence-cited review, the steps that produced it, week-over-week comparison, the learned
    routine, the permitted graph and data coverage. State comes from the deterministic consensus only."""

    patient_id: str
    display_name: str
    state: State
    agreement: Agreement
    rule_version: str
    status_line: str = Field(default="", max_length=600, description="one statement by code that reconciles the "
                             "rule state with the course: when it was raised, what has come back, why it still shows")
    review: PatientReview
    evidence: list[RecordCitation] = Field(default_factory=list, description="every record a finding cites")
    trace: list[AgentStep] = Field(default_factory=list)
    comparison: PeriodComparison
    routine: LearnedRoutine
    graph: InsightGraph
    coverage: DataCoverage
    day_of_record: int = Field(default=0, ge=0, description="calendar days since the first observation")
    min_history_days_for_stable: int = Field(default=0, ge=0, description="criteria: days before `stable` is possible")
    early_record: bool = Field(default=False, description="provisional or missing baselines: lower confidence")
    course: Course | None = None
    days: list[DayAccount] = Field(default_factory=list, description="the last 14 days, newest first")
    reflections: ReflectionOverview | None = None
    state_history: list[StateDay] = Field(default_factory=list, description="oldest first, one row per day replayed")
    actions: list[CareAction] = Field(default_factory=list, description="care-team action log, oldest first")
    computed_at: datetime
