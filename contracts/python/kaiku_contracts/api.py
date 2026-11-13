"""Cloud HTTP API request/response models (handoff §6.4, §6.7). Shared by cloud, hub, web (via TS)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .criteria import Criteria
from .envelope import Envelope
from .payloads import Health, NudgeArm
from .sources import ConsensusSource

State = Literal["stable", "watch", "needs_call", "safety"]
Verdict = Literal["better", "as_usual", "worse", "insufficient"]
Agreement = Literal["agree", "disagree", "low_coverage"]
ActionName = Literal["flag_booster", "flag_icbt_referral", "acknowledge", "send_message"]
STATE_RANK: dict[str, int] = {"safety": 0, "needs_call": 1, "watch": 2, "stable": 3}


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventsBatch(ApiModel):
    events: list[Envelope[dict[str, Any]]] = Field(max_length=500)


class EventsResult(ApiModel):
    accepted: int
    duplicates: int
    rejected: list[dict[str, Any]] = Field(default_factory=list, description="[{id, error}]")


class CommandsResponse(ApiModel):
    commands: list[Envelope[dict[str, Any]]]


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


class Garden(ApiModel):
    """Reward only (no data). plants = finished interactions in the last 14 days; resting after 3 quiet days.
    It never wilts and there is no streak counter."""

    plants: int = Field(0, ge=0)
    resting: bool = False


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
