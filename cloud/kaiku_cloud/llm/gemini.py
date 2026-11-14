"""Gemini via the Interactions API (google-genai, current SDK) — the one place the cloud mind talks to Gemini text
models. Tiers map to config [models]: `fast` = gemini_fast (e.g. gemini-3.8-flash), `flagship` = gemini_flagship
(gemini-4-argon; Hydrogen/Carbon when they are listed). Needs GEMINI_API_KEY (read from .env); without it every
call raises LlmUnavailable and callers use their deterministic fallback. Never decides a person's state.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Literal

from kaiku_contracts.config import get

from .errors import LlmUnavailable

Tier = Literal["fast", "flagship"]
_MODEL_KEY = {"fast": "gemini_fast", "flagship": "gemini_flagship"}


def model_for(tier: Tier) -> str:
    return str(get("models", _MODEL_KEY[tier], "") or "")


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


@lru_cache(maxsize=1)
def _client(key: str, timeout_s: float):
    from google import genai

    return genai.Client(api_key=key, http_options={"timeout": int(timeout_s * 1000)})


def generate(prompt: str, *, tier: Tier = "fast", system: str | None = None, schema: dict[str, Any] | None = None,
             timeout_s: float = 30.0) -> str:
    """Text (or JSON when `schema` is given) from a Gemini model. Raises LlmUnavailable on any failure."""
    key, model = os.environ.get("GEMINI_API_KEY"), model_for(tier)
    if not key or not model or model.startswith("VERIFY"):
        raise LlmUnavailable(f"gemini {tier} not configured (GEMINI_API_KEY / models.{_MODEL_KEY[tier]})")
    kw: dict[str, Any] = {"model": model, "input": prompt}
    if system:
        kw["system_instruction"] = system
    if schema:
        kw["response_format"] = {"type": "text", "mime_type": "application/json", "schema": schema}
    try:
        out = _client(key, timeout_s).interactions.create(**kw)
        text = getattr(out, "output_text", None)
        if not text:
            raise ValueError("empty output")
        return text
    except Exception as e:  # network, quota, safety block, shape — all mean "use the fallback"
        raise LlmUnavailable(f"gemini {tier} ({model}) failed: {type(e).__name__}: {e}") from e


def generate_fast(prompt: str, timeout_s: float = 30.0) -> str:
    """Adapter with the explain-backend signature."""
    return generate(prompt, tier="fast", timeout_s=timeout_s)
