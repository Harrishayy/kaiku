"""Hosted Gemma via the Gemini API REST endpoint (AI Studio). Keeps the Gemma story alive if GPU serving fails.

Model id from config [models].gemma_hosted — VERIFY it in the Gemini docs before use. Needs GEMINI_API_KEY.
"""

from __future__ import annotations

import os

import httpx
from kaiku_contracts.config import get

from . import ledger
from .errors import LlmUnavailable

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def generate(prompt: str, timeout_s: float | None = None, *, task: str = "explain",
             home_id: str | None = None, max_output_tokens: int | None = None) -> str:
    timeout_s = timeout_s or float(get("gemma_hosted", "timeout_s", 45))
    model = get("models", "gemma_hosted", "")
    key = os.environ.get("GEMINI_API_KEY")
    if model and not model.startswith("VERIFY") and not key:
        # Gemini platform via ADC: same model through the shared client (metered + ledgered there)
        from . import gemini

        return gemini.generate(prompt, model=model, timeout_s=timeout_s, task=task, home_id=home_id)
    if not model or model.startswith("VERIFY") or not key:
        raise LlmUnavailable("gemma_hosted not configured (models.gemma_hosted / GEMINI_API_KEY or ADC)")
    from kaiku_contracts import budget

    try:
        cap = int(max_output_tokens or get("gemma_hosted", "max_output_tokens", 1200))
        est = budget.text_estimate(model, len(prompt), cap)
        with ledger.timed(model, task, home_id=home_id):
            # the cap travels only when a caller asked for its own (everyone else: the configured one, as before)
            return budget.metered("gemini", model, est, _call, model, key, prompt, timeout_s,
                                  *([cap] if max_output_tokens else []), task=task, component="cloud")
    except Exception as e:  # network, quota, shape — all mean "use the fallback"
        raise LlmUnavailable(f"gemma_hosted failed: {type(e).__name__}: {e}") from e


def _call(model: str, key: str, prompt: str, timeout_s: float, max_output_tokens: int | None = None) -> str:
    generation = {"temperature": 0.2,
                  "maxOutputTokens": int(max_output_tokens or get("gemma_hosted", "max_output_tokens", 1200)),
                  "thinkingConfig": {"thinkingLevel": str(get("gemma_hosted", "thinking_level", "minimal"))}}
    r = httpx.post(ENDPOINT.format(model=model), headers={"x-goog-api-key": key}, timeout=timeout_s,
                   json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                         "generationConfig": generation})
    r.raise_for_status()
    candidate = r.json()["candidates"][0]
    if candidate.get("finishReason") not in (None, "STOP"):
        raise LlmUnavailable("Gemma did not complete a response")
    text = "".join(p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought"))
    if not text.strip():
        raise LlmUnavailable("Gemma returned no response text")
    return text
