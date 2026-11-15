"""Gemma selects source/evidence priority; deterministic code renders the practitioner explanation.

Only supplied source and metric IDs are accepted. Provider prose, numbers, directions, actions and device claims
never reach the output. Invalid selection retries once, then uses the deterministic order. State never changes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kaiku_contracts.api import Explanation
from kaiku_contracts.config import get
from kaiku_contracts.jlog import get_logger

from ..settings import Settings
from . import gemini, gemma, gemma_hosted, gemma_vllm, ledger
from .errors import LlmUnavailable
from .template import template_explanation

BANNED = ("diagnos", "relapse detected", "predicts", "predict relapse", "disorder", "suffering from",
          "symptoms of", "is depressed", "mentally ill", "psychotic")
PROMPT = (Path(__file__).parent / "prompts" / "explain.md").read_text()
# "gemma" = the provider selected in config [gemma].provider (llm/gemma.py); the two explicit keys force one.
BACKENDS = {"gemma": gemma.generate, "gemma_hosted": gemma_hosted.generate, "gemma_modal": gemma_vllm.generate,
            "gemini": gemini.generate_fast}
# Which [models] key names the model behind a backend (shown in `Explanation.model` and the ledger). A backend
# registered only in BACKENDS is named by its own key.
MODEL_KEY = {"gemma_hosted": "gemma_hosted", "gemma_modal": "gemma_hf_repo", "gemini": "gemini_fast"}
_log = get_logger("cloud.explain")


def _model_of(backend: str) -> str:
    if backend == "gemma":
        return gemma.model_name() or backend
    key = MODEL_KEY.get(backend)
    return (str(get("models", key, "")) if key else "") or backend
# KAIKU_LLM=auto: Gemma first (open model), then Gemini fast, then the deterministic template. gemma_modal is not in
# the auto chain on purpose — a cold GPU start takes minutes; select it explicitly when it's warm for a demo.
CHAINS = {"auto": ("gemma", "gemini")}


def contains_banned(text: str) -> str | None:
    low = text.lower()
    return next((w for w in BANNED if w in low), None)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip() if lines[-1].strip() == "```" else text
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected one JSON object")
    return data


def _from_llm(raw: str, ctx: dict[str, Any], backend: str) -> Explanation:
    data = _extract_json(raw)
    known = {v["source"] for v in ctx["sources"]}
    order, focus = data.get("source_order"), data.get("focus_metrics")
    metrics = {e["metric"] for v in ctx["sources"] for e in v.get("evidence", [])}
    if not isinstance(order, list) or not all(isinstance(s, str) for s in order) or len(order) != len(known) or set(order) != known:
        raise ValueError("invalid source selection")
    if not isinstance(focus, list) or len(focus) > 5 or not all(isinstance(m, str) and m in metrics for m in focus):
        raise ValueError("invalid metric selection")
    priority = {metric: i for i, metric in enumerate(focus)}
    sources = [{**v, "evidence": sorted(v.get("evidence", []), key=lambda e: priority.get(e["metric"], len(focus)))}
               for v in ctx["sources"]]
    sources.sort(key=lambda v: order.index(v["source"]))
    ex = template_explanation({**ctx, "sources": sources})
    ex.by = "gemma"
    ex.model = _model_of(backend)
    ex.generated_at = datetime.now(UTC)
    if contains_banned(ex.model_dump_json()):  # the same wording check as the template path; fails -> template
        raise ValueError("banned wording")
    return ex


def make_explanation(ctx: dict[str, Any], settings: Settings | None = None, log: Any = None) -> Explanation:
    choice = (settings or Settings()).llm
    log = log or _log
    prompt = PROMPT + json.dumps(ctx, default=str, indent=1)
    for backend in CHAINS.get(choice, (choice,)):
        gen = BACKENDS.get(backend)
        if gen is None:
            continue
        for attempt in (1, 2):
            try:
                result = _from_llm(gen(prompt), ctx, backend)
                ledger.record(result.model or backend, "explain.route", ok=True, route=backend,
                              home_id=ctx.get("home_id"))
                return result
            except LlmUnavailable as e:  # the type only: a provider's message can carry the request
                log.warning("llm_unavailable", f"{backend}: {type(e.__cause__ or e).__name__}")
                break
            except Exception as e:  # invalid JSON / schema / banned words → retry once, then next backend
                ledger.record(_model_of(backend), "explain.validation", ok=False,
                              route=type(e).__name__, home_id=ctx.get("home_id"))
                prompt += ("\nYour previous response failed validation. Return one complete JSON object only, "
                           "with only source_order and focus_metrics, selecting provided IDs only. Do not include prose, "
                           "reasoning, new facts or markdown.")
                log.warning("llm_invalid_explanation", f"{backend} attempt {attempt}: {type(e).__name__}")
    ex = template_explanation(ctx)
    if choice != "template":  # an LLM was selected but none answered: count the fallback
        ledger.record("template", "explain", ok=True, fallback=True, route="fallback", home_id=ctx.get("home_id"))
    bad = contains_banned(ex.model_dump_json())
    if bad:
        # The fixed sentences are tested; the variable parts are the evidence summaries (criteria) and the name.
        # Leave the evidence summaries out and say so in the log rather than fail the request.
        log.error("explanation_banned_wording", "template", home=ctx.get("home_id"))
        ex = template_explanation({**ctx, "sources": [{**v, "evidence": []} for v in ctx["sources"]]})
        if contains_banned(ex.model_dump_json()):
            log.error("explanation_banned_wording", "template without evidence", home=ctx.get("home_id"))
    return ex
