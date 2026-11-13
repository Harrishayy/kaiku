"""Hosted Gemma via the Gemini API REST endpoint (AI Studio). Keeps the Gemma story alive if GPU serving fails.

Model id from config [models].gemma_hosted — VERIFY it in the Gemini docs before use. Needs GEMINI_API_KEY.
"""

from __future__ import annotations

import os

import httpx
from kaiku_contracts.config import get

from .errors import LlmUnavailable

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def generate(prompt: str, timeout_s: float = 20.0) -> str:
    model = get("models", "gemma_hosted", "")
    key = os.environ.get("GEMINI_API_KEY")
    if not model or model.startswith("VERIFY") or not key:
        raise LlmUnavailable("gemma_hosted not configured (models.gemma_hosted / GEMINI_API_KEY)")
    try:
        r = httpx.post(ENDPOINT.format(model=model), headers={"x-goog-api-key": key}, timeout=timeout_s,
                       json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                             "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800}})
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:  # network, quota, shape — all mean "use the fallback"
        raise LlmUnavailable(f"gemma_hosted failed: {type(e).__name__}: {e}") from e
