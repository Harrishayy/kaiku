"""Explanation of a consensus: structured context -> api.Explanation. Gemma explains; it never decides.

The state is computed deterministically by analytics/consensus.py and is never changed here. LLM output must
be strict JSON, is validated with pydantic, retried once, and checked against a banned-word list. Any failure
(not configured, unreachable, invalid JSON twice, banned wording) falls back to the deterministic template.
Swap/add a backend: add a `generate(prompt) -> str` adapter and register it in BACKENDS (key = KAIKU_LLM value).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kaiku_contracts.api import Explanation
from kaiku_contracts.config import get

from ..settings import Settings
from . import gemini, gemma_hosted, gemma_vllm
from .errors import LlmUnavailable
from .template import CAVEATS, template_explanation

BANNED = ("diagnos", "relapse detected", "predicts", "predict relapse", "disorder", "suffering from",
          "symptoms of", "is depressed", "mentally ill", "psychotic")
PROMPT = (Path(__file__).parent / "prompts" / "explain.md").read_text()
BACKENDS = {"gemma_hosted": gemma_hosted.generate, "gemma_modal": gemma_vllm.generate, "gemini": gemini.generate_fast}
MODEL_KEY = {"gemma_hosted": "gemma_hosted", "gemma_modal": "gemma_hf_repo", "gemini": "gemini_fast"}
# KAIKU_LLM=auto: Gemma first (open model), then Gemini fast, then the deterministic template. gemma_modal is not in
# the auto chain on purpose — a cold GPU start takes minutes; select it explicitly when it's warm for a demo.
CHAINS = {"auto": ("gemma_hosted", "gemini")}


def contains_banned(text: str) -> str | None:
    low = text.lower()
    return next((w for w in BANNED if w in low), None)


def _extract_json(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in LLM output")
    return json.loads(m.group(0))


def _from_llm(raw: str, ctx: dict[str, Any], backend: str) -> Explanation:
    data = _extract_json(raw)
    known = {v["source"] for v in ctx["sources"]}
    ex = Explanation(
        headline=str(data["headline"])[:200], text=str(data.get("text") or data["headline"])[:1200],
        per_source=[p for p in (data.get("per_source") or []) if isinstance(p, dict) and p.get("source") in known],
        disagreement_note=(str(data["disagreement_note"])[:400] if data.get("disagreement_note") else None),
        suggested_actions=data.get("suggested_actions") or ["none"],
        caveats=str(data.get("caveats") or CAVEATS)[:600], by="gemma",
        model=str(get("models", MODEL_KEY[backend], "")) or None, generated_at=datetime.now(UTC))
    bad = contains_banned(ex.model_dump_json())
    if bad:
        raise ValueError(f"banned phrase in LLM output: {bad!r}")
    if ctx["state"] == "safety" and ex.suggested_actions[0] != "check_in_call":
        ex.suggested_actions = ["check_in_call", *[a for a in ex.suggested_actions if a != "check_in_call"]]
    if "correlated_only" in ctx.get("notes", []) and "not independent" not in ex.caveats.lower():
        ex.caveats = ("The only worse signals come from correlated measures, which are not independent. "
                      + ex.caveats)[:600]
    return ex


def make_explanation(ctx: dict[str, Any], settings: Settings | None = None, log: Any = None) -> Explanation:
    choice = (settings or Settings()).llm
    prompt = PROMPT + json.dumps(ctx, default=str, indent=1)
    for backend in CHAINS.get(choice, (choice,)):
        gen = BACKENDS.get(backend)
        if gen is None:
            continue
        for attempt in (1, 2):
            try:
                return _from_llm(gen(prompt), ctx, backend)
            except LlmUnavailable as e:
                if log:
                    log.warning("llm_unavailable", str(e))
                break
            except Exception as e:  # invalid JSON / schema / banned words → retry once, then next backend
                if log:
                    log.warning("llm_invalid_explanation", f"{backend} attempt {attempt}: {e}")
    ex = template_explanation(ctx)
    assert contains_banned(ex.model_dump_json()) is None
    return ex
