"""Hosted Gemma via the Gemini API REST endpoint (AI Studio). Keeps the Gemma story alive if GPU serving fails.

Model id: config [models].gemma_hosted (checked in the Gemini docs 2026-11-14; model names change, so re-check
before a deploy). Endpoint: config [endpoints].gemini_generate_content. Needs GEMINI_API_KEY (or ADC through
llm/gemini.py).
"""

from __future__ import annotations

import os

import httpx
from kaiku_contracts.config import get

from . import ledger
from .errors import LlmUnavailable


def _endpoint(model: str) -> str:
    url = str(get("endpoints", "gemini_generate_content", "") or "")
    if "{model}" not in url:
        raise LlmUnavailable("config/kaiku.toml [endpoints].gemini_generate_content is not set")
    return url.format(model=model)


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
    r = httpx.post(_endpoint(model), headers={"x-goog-api-key": key}, timeout=timeout_s,
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


def look(prompt: str, images: list[bytes], timeout_s: float | None = None, *, task: str = "vision_look",
         home_id: str | None = None) -> str:
    """Gemma looks at a few small JPEGs (D65; verified with a real call on 2026-11-15: `gemma-4-26b-a4b-it` takes
    `inlineData` images on `generateContent`, 258 tokens a picture). The pictures exist only in this call's
    arguments and in the one HTTPS request body; nothing here writes, logs or caches them, and a failure is reported
    by its TYPE only: an HTTP library's message or an exception chain could carry the request."""
    timeout_s = timeout_s or float(get("gemma_hosted", "timeout_s", 45))
    model = get("models", "gemma_hosted", "")
    key = os.environ.get("GEMINI_API_KEY")
    if not model or model.startswith("VERIFY"):
        raise LlmUnavailable("gemma_hosted not configured (models.gemma_hosted)")
    from kaiku_contracts import budget, genai_client

    if not key and not genai_client.available():
        raise LlmUnavailable("gemma_hosted not configured (GEMINI_API_KEY or ADC)")
    cap = int(get("vision_look", "max_output_tokens", 200))
    est = budget.estimate(model, in_tokens=len(prompt) // 3 + 50 + 258 * len(images), out_tokens=cap)
    kind = "unknown"
    try:
        with ledger.timed(model, task, home_id=home_id):
            fn = _look_rest if key else _look_platform
            return budget.metered("gemini", model, est, fn, model, key, prompt, images, timeout_s, cap,
                                  task=task, component="cloud")
    except Exception as e:  # noqa: BLE001 - every failure means "nothing was noted"
        kind = type(e).__name__
    raise LlmUnavailable(f"gemma_hosted look failed: {kind}")  # outside the except: no chain to the request


def _look_rest(model: str, key: str, prompt: str, images: list[bytes], timeout_s: float, cap: int) -> str:
    import base64

    parts: list[dict] = [{"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(i).decode()}}
                         for i in images]
    parts.append({"text": prompt})
    generation = {"temperature": 0.1, "maxOutputTokens": cap,
                  "thinkingConfig": {"thinkingLevel": str(get("gemma_hosted", "thinking_level", "minimal"))}}
    r = httpx.post(_endpoint(model), headers={"x-goog-api-key": key}, timeout=timeout_s,
                   json={"contents": [{"role": "user", "parts": parts}], "generationConfig": generation})
    del parts
    if r.status_code != 200:
        raise LlmUnavailable(f"HTTP {r.status_code}")
    candidate = r.json()["candidates"][0]
    if candidate.get("finishReason") not in (None, "STOP"):
        raise LlmUnavailable("Gemma did not complete a response")
    text = "".join(p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought"))
    if not text.strip():
        raise LlmUnavailable("Gemma returned no response text")
    return text


def _look_platform(model: str, _key: str | None, prompt: str, images: list[bytes], timeout_s: float, cap: int) -> str:
    """The same model through the Gemini platform (ADC) when there is no API key."""
    from google.genai import types
    from kaiku_contracts import genai_client

    client = genai_client.make_client(timeout_s=timeout_s)
    contents = [types.Part.from_bytes(data=i, mime_type="image/jpeg") for i in images] + [prompt]
    resp = client.models.generate_content(model=model, contents=contents,
                                          config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=cap))
    text = getattr(resp, "text", None) or ""
    if not text.strip():
        raise LlmUnavailable("Gemma returned no response text")
    return text
