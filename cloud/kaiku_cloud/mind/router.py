"""Source-aware companion reasoning: exact memory lookup → hosted Gemma → Gemini fallback → scripted response.

Gemma is the primary reasoning tier for all nondeterministic kinds, including care and emotional questions.
Every answer is validated for allowed citations, conflict handling and prohibited language before speaking.
Fresh source metadata comes from current DB observations on every invocation; raw measurements, state, transcripts
and private health data are never included. The deterministic crisis gate runs before this router.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from kaiku_contracts import wording
from kaiku_contracts.api import MindAnswer
from kaiku_contracts.config import get, load_config

from ..llm import gemini, gemma, ledger
from ..llm.errors import LlmUnavailable
from ..settings import TZ, Settings
from ..store.db import Store
from . import graph, memory

TAG = re.compile(r"\[((?:mem|kg|doc):[\w-]+)\]")
BAD_CODES = {"clinical_term", "state_talk", "medical_advice", "wearable_data", "promise", "pretends_human"}
FACT_CODES = {"clinical_term", "state_talk", "medical_advice", "wearable_data"}
STATE_WORDS = re.compile(r"needs_call|needs a call|\bstable\b|consensus|verdict|\bphq|\bhrv\b|rmssd|baseline|"
                         r"\bscore|resting_hr|sleep_|wearable|low_coverage", re.I)
TODAY_Q = re.compile(r"\btoday\b|\bdid i\b|\bhave i\b|tänään|idag", re.I)
SCRIPTED = {
    "fact": "I'm not sure about that one. Could you tell me?",
    "memory": "I don't think you've told me that yet. Would you like to tell me?",
    "plan": "I'm not sure what the plan is. Shall we decide together?",
    "care": "I'm not sure about that one. It's a good question for your care team.",
    "emotional": "I'm here with you. Would you like to tell me a little more?",
}
CONFLICT_LINE = "I have two different notes about that, and I don't want to guess. Can you tell me which is right?"
SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "one or two short sentences; cite facts inline like [mem:3]"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "cites": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "confidence", "cites"],
}
SYSTEM = (
    "You are the quiet mind behind Kaiku, a small warm companion for someone at home after depression treatment. "
    "Kaiku's voice asked you a question. Answer ONLY from FACTS; cite every fact you use inline with its tag, e.g. "
    "[mem:3], and list the tags in cites. If FACTS don't answer it, say you're not sure and give confidence below "
    "0.4. Never pick between CONFLICTING notes: ask the person which is right, citing both. Care questions: only "
    "what a [doc:...] passage says, otherwise suggest asking the care team. Never mention health details, scores, "
    "states, sleep, heart or watch data; never give medical advice; no promises. Short, warm, plain words. "
    "Source facts say only which interface reported an activity, not how the person feels. Never infer wellness, "
    "emotion or a diagnosis from source presence. Missing sources mean you do not know; never pretend a device "
    "is connected or observing right now. Answer with JSON only."
)

Gen = Callable[..., str]
OUTCOME_TASK = "ask_mind" + ledger.OUTCOME  # one outcome row per question (which route answered)


class Rejected(ValueError):
    pass


def rejection_code(error: Rejected) -> str:
    """Contentless bounded reason for validation telemetry and corrective prompts."""
    text = str(error)
    for prefix, code in (("not JSON", "invalid_json"), ("missing cite", "missing_citation"),
                         ("unverifiable cite", "unknown_citation"), ("wording", "wording"),
                         ("picked one", "conflict")):
        if text.startswith(prefix):
            return code
    return "invalid_shape"


# ------------------------------------------------------------------ facts
def clean_fact(text: str, *, approved: bool = False) -> bool:
    """A fact may enter a prompt only without numbers, state words or wearable/health details. Approved care
    passages skip the notebook's health-word rule (they are care-team text) but not the rest."""
    if not text or re.search(r"\d", text) or STATE_WORDS.search(text):
        return False
    if wording.codes(wording.lint(text, max_questions=None)) & FACT_CODES:
        return False
    return approved or not memory.health_detail(text)


def care_passages() -> dict[str, str]:
    return {str(k): str(v) for k, v in (load_config().get("care_passages") or {}).items()}


def _overlap(a: str, b: str) -> int:
    ta, tb = set(graph.terms(a)), set(graph.terms(b))
    return len({x for x in ta for y in tb if x == y or (len(x) > 3 and len(y) > 3 and (x.startswith(y) or y.startswith(x)))})


def facts_for(store: Store, home_id: str, question: str, kind: str, done_today: list[str]) -> list[dict[str, str]]:
    facts = [{"id": h["ref"], "text": h["text"]} for h in graph.recall(store, home_id, question)]
    if kind == "care":
        ps = care_passages()
        ranked = sorted(ps, key=lambda k: -_overlap(question, ps[k]))
        facts += [{"id": f"doc:{k}", "text": ps[k]} for k in ranked]
    if done_today and TODAY_Q.search(question):
        facts.append({"id": "doc:today", "text": "Done today: " + "; ".join(done_today)})
    seen: set[str] = set()
    out = []
    for f in facts:
        if f["id"] not in seen and clean_fact(f["text"], approved=f["id"].startswith("doc:")):
            seen.add(f["id"])
            out.append(f)
    return out


def source_facts(store: Store, home_id: str, now: datetime) -> list[dict[str, str]]:
    """Fresh source provenance and activity presence only; no raw observations, numbers or state leave this edge."""
    oldest = now - timedelta(days=int(get("mind", "source_context_days", 7)))
    labels = {"phone": "phone app", "laptop": "laptop app", "glasses": "glasses interface", "hub": "home robot"}
    activities = {"obs.outing": "an outing", "obs.self_report": "a personal check-in",
                  "obs.play_session": "a game", "obs.laptop_session": "an activity summary",
                  "obs.intervention_response": "feedback on an activity", "obs.ritual": "a companion activity",
                  "obs.wearable_daily": "an optional daily summary", "obs.drum_session": "a drum activity",
                  "obs.hrv_session": "a breathing activity", "obs.speech_features": "a conversation activity"}
    latest: dict[tuple[str, str], dict[str, str]] = {}
    for event in store.events_for_home(home_id):
        source, kind = event["source"], event["type"]
        ts = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
        if source not in labels or kind not in activities or not oldest <= ts <= now:
            continue
        key = (source, kind)
        ago = (now.astimezone(TZ).date() - ts.astimezone(TZ).date()).days
        # Always say when: an undated "recently" was read as "today" by the voice model (real run 2026-11-14).
        recent = "today" if ago <= 0 else "yesterday" if ago == 1 else "earlier this week"  # words: no numbers here
        latest[key] = {"id": f"doc:source-{source}-{kind.removeprefix('obs.').replace('_', '-')}",
                       "text": ("Simulated: " if event.get("sim") else "") +
                       f"The {labels[source]} reported {activities[kind]} {recent}."}
    return list(latest.values())


def build_prompt(question: str, kind: str, facts: list[dict[str, str]], conflict_ids: list[str]) -> str:
    body: dict[str, Any] = {"question": question, "kind": kind, "facts": facts}
    if conflict_ids:
        body["conflicting"] = conflict_ids
    return json.dumps(body, ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ validation
def validate(raw: str, kind: str, allowed: set[str], conflict_ids: list[str], route: str, model: str) -> MindAnswer:
    try:
        text = raw.strip()
        if text.startswith("```") and text.splitlines()[-1].strip() == "```":
            text = "\n".join(text.splitlines()[1:-1]).strip()
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise Rejected("not JSON") from e
    if not isinstance(data, dict):
        raise Rejected("not an object")
    answer, conf, cites = data.get("answer"), data.get("confidence"), data.get("cites") or []
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 400:
        raise Rejected("bad answer")
    if not isinstance(conf, int | float) or isinstance(conf, bool) or not 0 <= conf <= 1:
        raise Rejected("bad confidence")
    if not isinstance(cites, list) or not all(isinstance(c, str) for c in cites):
        raise Rejected("bad cites")
    used = set(TAG.findall(answer)) | {c.strip("[]") for c in cites}
    unknown = used - allowed
    if unknown:
        raise Rejected(f"unverifiable cite {sorted(unknown)}")
    if kind != "emotional" and not used:
        raise Rejected("missing cite")
    text = re.sub(r"\s+([.,!?;:])", r"\1", re.sub(r"\s{2,}", " ", TAG.sub("", answer))).strip()
    if not text:
        raise Rejected("empty after stripping")
    if (re.search(r"\d", text) or wording.codes(wording.lint(text, max_questions=1)) & BAD_CODES
            or STATE_WORDS.search(text)):
        raise Rejected("wording")
    ask = False
    if conflict_ids:
        if "?" not in text or len(used & set(conflict_ids)) < 2:
            raise Rejected("picked one of conflicting notes")
        ask = True
    return MindAnswer(answer=text, kind=kind, route=route, confidence=float(conf), cites=sorted(used),
                      ask_person=ask, model=model)


# ------------------------------------------------------------------ budget
def argon_left(store: Store, home_id: str, now: datetime) -> bool:
    cap = int(get("budget", "argon_per_home_day", 20))
    used = store.model_calls_count(home_id, gemini.model_for("flagship"), ledger.day_start_utc(now, TZ))
    return used < cap


# ------------------------------------------------------------------ deterministic route
def deterministic(store: Store, home_id: str, question: str, kind: str, facts: list[dict[str, str]],
                  done_today: list[str]) -> MindAnswer | None:
    if kind not in ("fact", "memory", "plan"):
        return None
    if done_today and TODAY_Q.search(question) and not graph.terms(question.replace("today", "")):
        return MindAnswer(answer="Today you've done " + " and ".join(done_today[:3]) + ".", kind=kind,
                          route="memory", confidence=1.0, cites=["doc:today"])
    mems = [f for f in facts if f["id"].startswith("mem:")]
    scored = sorted(((_overlap(question, f["text"]), f) for f in mems), key=lambda x: -x[0])
    if not scored or scored[0][0] == 0 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None
    q_terms = graph.terms(question)
    if scored[0][0] < max(1, (len(q_terms) + 1) // 2):  # at least half the question's content words match
        return None
    best = scored[0][1]
    return MindAnswer(answer=f'You told me: "{best["text"]}"', kind=kind, route="memory", confidence=1.0,
                      cites=[best["id"]])


# ------------------------------------------------------------------ the router
def ask(store: Store, settings: Settings, home_id: str, question: str, kind: str, *, done_today: list[str] | None = None,
        now: datetime | None = None, gen: Gen | None = None, gemma_gen: Gen | None = None) -> MindAnswer:
    now = now or datetime.now(UTC)
    gen = gen or gemini.generate
    # Retrieval, validation retries and fallback tiers share the device's single tool wait.
    # Leave time for serialization, durable commit and the response to reach the device.
    deadline = time.monotonic() + max(0.0, float(get("live", "mind_timeout_s", 120)) - 5.0)

    def remaining_timeout(limit: float) -> float:
        return max(0.0, min(limit, deadline - time.monotonic()))

    question = re.sub(r"\s+", " ", question or "").strip()[:300]
    done_today = done_today or []
    graph.rebuild(store, home_id, now)
    clash = graph.conflicts(store, home_id, question)
    if question and not clash:
        # Exact notebook matches need no query embedding or reasoning-model call. Respect graph consolidation
        # before consulting the local FTS index, so a merged/expired note cannot reappear through this shortcut.
        inactive = {n["origin"] for n in store.kg_nodes(home_id) if n["status"] != "active"}
        lexical = [{"id": f"mem:{m['id']}", "text": m["text"]}
                   for m in memory.recall(store, home_id, question, now=now)
                   if f"memory:{m['id']}" not in inactive and clean_fact(m["text"])]
        hit = deterministic(store, home_id, question, kind, lexical, done_today)
        if hit:
            ledger.record("deterministic", OUTCOME_TASK, ok=True, route="memory", home_id=home_id)
            return hit
    facts = facts_for(store, home_id, question, kind, done_today)
    facts.extend(source_facts(store, home_id, now))
    conflict_ids = [f"mem:{m['id']}" for m in clash]
    for m in clash:  # both notes must be in the facts so the model can cite them
        if f"mem:{m['id']}" not in {f["id"] for f in facts} and clean_fact(m["text"]):
            facts.append({"id": f"mem:{m['id']}", "text": m["text"]})
    conflict_ids = [c for c in conflict_ids if c in {f["id"] for f in facts}]
    if len(conflict_ids) < 2:
        conflict_ids = []

    if question and not conflict_ids:
        hit = deterministic(store, home_id, question, kind, facts, done_today)
        if hit:
            ledger.record("deterministic", OUTCOME_TASK, ok=True, route="memory", home_id=home_id)
            return hit

    allowed = {f["id"] for f in facts}
    prompt = build_prompt(question, kind, facts, conflict_ids)
    threshold = float(get("mind", "escalate_below", 0.6))
    timeout = float(get("mind", "timeout_s", 20))
    argon_first = kind in ("care", "emotional") or bool(conflict_ids)
    tried_argon = False
    flash_ans: MindAnswer | None = None

    def call(tier: str, route: str) -> MindAnswer | None:
        remaining = remaining_timeout(timeout)
        if remaining <= 0:
            return None
        try:
            raw = gen(prompt, tier=tier, system=SYSTEM, schema=SCHEMA, timeout_s=remaining, task="ask_mind",
                      home_id=home_id, route=route)
            ans = validate(raw, kind, allowed, conflict_ids, route, gemini.model_for(tier))  # type: ignore[arg-type]
        except (LlmUnavailable, Rejected):
            return None
        return ans

    def done(ans: MindAnswer) -> MindAnswer:
        ledger.record(ans.model or "?", OUTCOME_TASK, ok=True, route=ans.route, home_id=home_id)
        return ans

    if question:
        if get("mind", "primary", "gemma_hosted") == "gemma_hosted":
            primary = gemma_gen or gemma.generate
            model = gemma.model_name()
            gemma_prompt = SYSTEM + "\nJSON SCHEMA:\n" + json.dumps(SCHEMA) + "\nINPUT:\n" + prompt
            for _attempt in range(2):
                remaining = remaining_timeout(float(get("gemma_hosted", "timeout_s", 45)))
                if remaining <= 0:
                    break
                try:
                    raw = primary(gemma_prompt, timeout_s=remaining, task="ask_mind", home_id=home_id)
                    answer = validate(raw, kind, allowed, conflict_ids, "gemma", model)
                    return done(answer)
                except LlmUnavailable:
                    ledger.record(model, "ask_mind.validation", ok=False, route="unavailable", home_id=home_id)
                    break
                except Rejected as rejected:
                    reason = rejection_code(rejected)
                    ledger.record(model, "ask_mind.validation", ok=False, route=reason, home_id=home_id)
                    gemma_prompt += ("\nThe previous response failed validation. Return a complete JSON object with "
                                     "answer, confidence and cites. Keep the answer under four hundred characters. "
                                     "Use only provided citation IDs, and no health measurements or state claims. "
                                     "Every factual plan must cite a supplied fact inline, for example [mem:1] only if that ID exists. "
                                     "Do not use digits in the answer text, do not invent facts, and ask only one question. "
                                     f"Validation issue: {reason}.")
        if argon_first and argon_left(store, home_id, now):
            tried_argon = True
            if ans := call("flagship", "argon"):
                return done(ans)
        flash_ans = call("fast", "flash")
        if flash_ans and (flash_ans.confidence >= threshold or tried_argon):
            return done(flash_ans)
        if not tried_argon and argon_left(store, home_id, now):
            if ans := call("flagship", "argon"):
                return done(ans)
        if flash_ans:  # Argon unavailable / over budget / invalid: the valid (low-confidence) Flash answer stands
            return done(flash_ans)
    return scripted(store, home_id, question, kind, conflict_ids)


def scripted(store: Store, home_id: str, question: str, kind: str, conflict_ids: list[str]) -> MindAnswer:
    ledger.record("scripted", OUTCOME_TASK, ok=True, route="fallback", fallback=True, home_id=home_id)
    if conflict_ids:
        return MindAnswer(answer=CONFLICT_LINE, kind=kind, route="fallback", confidence=0.0, cites=conflict_ids,
                          ask_person=True)
    if kind == "care":
        ps = care_passages()
        best = max(ps, key=lambda k: _overlap(question, ps[k]), default=None)
        if best and _overlap(question, ps[best]) > 0:
            return MindAnswer(answer=ps[best], kind=kind, route="fallback", confidence=0.5, cites=[f"doc:{best}"])
    return MindAnswer(answer=SCRIPTED.get(kind, SCRIPTED["fact"]), kind=kind, route="fallback", confidence=0.0)
