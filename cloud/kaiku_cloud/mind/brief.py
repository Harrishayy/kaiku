"""Weekly clinician brief (plan 06 §2): the flagship writes a short brief grounded in metric IDs; code validates.

Input: the deterministic consensus only (state, agreement, per-source verdicts and their drifting metrics). Never the
person's memories, episodes or conversations (clinician routes don't read the notebook). Output JSON
{sections: [{text, metrics[]}]}: every metric must be one the consensus evidence names, every section needs one
(except a single overview section), wording linter (explain.BANNED + wording clinical/promise codes). Invalid,
unavailable or over budget -> the deterministic template. The brief explains; it never changes `state`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from kaiku_contracts import wording
from kaiku_contracts.api import BriefSection, ClinicianBrief, Consensus
from kaiku_contracts.sources import SOURCE_LABELS

from ..llm import gemini, ledger
from ..llm.errors import LlmUnavailable
from ..llm.explain import contains_banned
from ..settings import TZ
from ..store.db import Store
from . import router

SCHEMA = {"type": "object", "required": ["sections"], "properties": {"sections": {"type": "array", "items": {
    "type": "object", "required": ["text", "metrics"],
    "properties": {"text": {"type": "string"}, "metrics": {"type": "array", "items": {"type": "string"}}}}}}}
SYSTEM = (
    "You write a weekly brief for a clinician about one person after TMS treatment, from a deterministic "
    "consensus. 2-4 short sections. Each section rests on metric ids from the facts (list them in metrics). Say "
    "'change from their usual', 'worth a check-in', 'consensus'. Never diagnose, never predict, never say relapse. "
    "Do not restate or change the state. JSON only."
)
BAD = {"clinical_term", "promise", "medical_advice"}


def week_of(now: datetime) -> str:
    y, w, _ = now.astimezone(TZ).isocalendar()
    return f"{y}-W{w:02d}"


def facts(c: Consensus) -> dict[str, Any]:
    return {"state": c.state, "agreement": c.agreement,
            "sources": [{"source": v.source, "verdict": v.verdict,
                         "metrics": [{"id": e.metric, "direction": e.direction, "days": e.days} for e in v.evidence]}
                        for v in c.sources]}


def template(c: Consensus, labels: dict[str, str] | None = None) -> list[BriefSection]:
    labels = labels or {}
    out = [BriefSection(text=f"Consensus this week: {c.state.replace('_', ' ')} ({c.agreement.replace('_', ' ')}).")]
    for v in c.sources:
        if v.evidence:
            names = [e.metric for e in v.evidence]
            shown = ", ".join(labels.get(n, n.replace("_", " ")).lower() for n in names)
            out.append(BriefSection(text=f"{SOURCE_LABELS[v.source]}: change from their usual in {shown}.",
                                    metrics=names))
    if len(out) == 1:
        out.append(BriefSection(text="No source shows a change from their usual this week."))
    return out


def validate(raw: str, allowed: set[str]) -> list[BriefSection]:
    data = json.loads(raw)
    secs = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(secs, list) or not 1 <= len(secs) <= 5:
        raise ValueError("sections")
    out = []
    for i, s in enumerate(secs):
        text, metrics = str(s.get("text", "")).strip(), s.get("metrics") or []
        if not text or len(text) > 600 or not isinstance(metrics, list):
            raise ValueError("section shape")
        if set(metrics) - allowed:
            raise ValueError(f"unknown metric ids {sorted(set(metrics) - allowed)}")
        if not metrics and (i > 0 or len(secs) == 1) and allowed:
            raise ValueError("section without a metric")
        if contains_banned(text) or wording.codes(wording.lint(text, max_questions=None)) & BAD:
            raise ValueError("wording")
        out.append(BriefSection(text=text, metrics=[str(m) for m in metrics]))
    return out


def generate(store: Store, home_id: str, c: Consensus, *, now: datetime | None = None, use_model: bool = True,
             gen: Any = None) -> ClinicianBrief:
    now = now or datetime.now(UTC)
    gen = gen or gemini.generate
    allowed = {e.metric for v in c.sources for e in v.evidence}
    from .. import service  # local import: service imports the explainers

    labels = {m.name: m.label for m in service.active_criteria(store).metrics}
    sections, by, model = template(c, labels), "template", None
    if use_model and gemini.available() and router.argon_left(store, home_id, now):
        try:
            raw = gen(json.dumps(facts(c), indent=1), tier="flagship", system=SYSTEM, schema=SCHEMA, timeout_s=60,
                      task="weekly_brief", home_id=home_id, route="argon")
            sections, by, model = validate(raw, allowed), "model", gemini.model_for("flagship")
        except (LlmUnavailable, ValueError, json.JSONDecodeError, AttributeError):
            ledger.record("template", "weekly_brief", ok=True, fallback=True, route="fallback", home_id=home_id)
    return ClinicianBrief(patient_id=home_id, week=week_of(now), state=c.state, rule_version=c.rule_version,
                          sections=sections, by=by, model=model, generated_at=now)  # type: ignore[arg-type]


def key(home_id: str) -> str:
    return f"brief:{home_id}"


def current(cached: Any, c: Consensus, now: datetime | None = None) -> ClinicianBrief | None:
    """A stored brief is shown only while it still describes this week's consensus. New data that moves the state,
    a new rule version or a new week retires it, so prose never contradicts the deterministic result beside it."""
    if not cached:
        return None
    b = ClinicianBrief.model_validate(cached)
    fresh = b.week == week_of(now or datetime.now(UTC)) and b.state == c.state and b.rule_version == c.rule_version
    return b if fresh else None
