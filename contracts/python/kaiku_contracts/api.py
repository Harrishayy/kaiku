"""Cloud HTTP API request/response models (handoff §6.4, §6.7). Shared by cloud, hub, web (via TS)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .companion_tools import Intent, MemoryCategory, MindKind, Skill, Surface
from .criteria import Criteria
from .envelope import Envelope
from .payloads import Health, NudgeArm, PlaySession
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


class LastReflection(ApiModel):
    """How the latest talk with Kaiku went: a level and themes, never the words."""

    when: str = Field(description='e.g. "yesterday evening", "this morning"')
    valence: Literal["low", "neutral", "bright"] | None = None
    themes: list[str] = Field(default_factory=list, max_length=3)
    declined: bool = Field(default=False, description="they did not want to talk or asked to stop")


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
    others_present: bool = False
    dont_remember: bool = False


class CompanionSessionRequest(ApiModel):
    resume_session_id: str | None = Field(None, description="reuse an open session belonging to this home and surface")
    surface: Surface
    home_id: str
    intent: Intent = "talk"
    language: VoiceLang | None = Field(default=None, description="default: config/kaiku.toml [home].language")
    others_present: bool = False


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


class InsightNode(ApiModel):
    id: str
    kind: Literal["person", "signal_group", "measure", "activity", "routine", "care_action", "shared_topic"]
    layer: Literal["learned", "structure"] = Field(default="structure", description="learned = found in this "
                                                   "person's record; structure = how the record is organised")
    label: str = Field(max_length=120)
    detail: str | None = Field(default=None, max_length=240)
    evidence: int = Field(ge=0, description="recorded days / observations / attempts behind this node")
    tone: Trend = "unknown"


class InsightEdge(ApiModel):
    src: str
    dst: str
    rel: Literal["has_signal", "measures", "did", "keeps", "of", "helped", "moved_first", "followed",
                 "moved_together", "kept_through", "slipped_during", "after", "talked_about"]
    layer: Literal["learned", "structure"] = "structure"
    label: str = Field(max_length=80)
    weight: float = Field(ge=0, le=1)
    evidence: int = Field(ge=0)


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
    simulated: bool = Field(description="every observation in this record carries sim=true")
    summary: str = Field(max_length=300)
    groups: list[GroupCoverage] = Field(default_factory=list)
    other: list[ObsTypeCoverage] = Field(default_factory=list, description="activity responses, ritual steps, flags")


class CourseEvent(ApiModel):
    """One dated point in the course of change. Text, dates and numbers are written by code."""

    date: date
    kind: Literal["onset", "lowest", "care_action", "phq9", "back_in_range", "still_away"]
    group: ConsensusSource | None = None
    metric_id: str | None = None
    label: str = Field(max_length=120)
    text: str = Field(max_length=300)


class Course(ApiModel):
    """How the record has moved against the person's own usual: what moved first, what followed, what has come
    back, what has not. Temporal order only, never a cause. Computed by code from the daily series."""

    phase: Literal["settling", "steady", "dip", "recovering", "recovered"]
    summary: str = Field(max_length=700)
    events: list[CourseEvent] = Field(default_factory=list)


class DayAccount(ApiModel):
    """One day in plain words, built by code from every source: what was done, what was away from usual, how the
    reflection went (level and themes only, when shared)."""

    date: date
    text: str = Field(max_length=400)
    parts: list[str] = Field(default_factory=list)


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
    summary: str = Field(max_length=300)


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
