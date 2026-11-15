"""Gemini via the Interactions API (google-genai, current SDK) — the one place the cloud talks to Gemini text,
embedding and image models. Tiers map to config [models]: `fast` = gemini_fast (gemini-3.8-flash), `flagship` =
gemini_flagship (gemini-4-argon). Embeddings: [mind].embedding_model (gemini-embedding-2, `models.embed_content`).
Images: [mind].image_model (gemini-3.1-flash-lite-image = Nano Banana 2 Lite, `interactions.create` →
`output_image`). Needs GEMINI_API_KEY (read from .env); without it every call raises LlmUnavailable and callers use
their deterministic fallback. Every paid call goes through `kaiku_contracts.budget` (guard + metered; over the cap =
LlmUnavailable -> fallback) and writes one usage-ledger row (no content). Never decides state.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Any, Literal

from kaiku_contracts import budget
from kaiku_contracts.config import get

from . import ledger
from .errors import LlmUnavailable

Tier = Literal["fast", "flagship"]
_MODEL_KEY = {"fast": "gemini_fast", "flagship": "gemini_flagship"}


def model_for(tier: Tier) -> str:
    return str(get("models", _MODEL_KEY[tier], "") or "")


def embedding_model() -> str:
    return str(get("mind", "embedding_model", "") or "")


def image_model() -> str:
    return str(get("mind", "image_model", "") or "")


def _timeout(given: float | None, key: str, default: float) -> float:
    """A caller's own timeout, else config/kaiku.toml [cloud].<key>."""
    return float(given if given is not None else get("cloud", key, default))


def available() -> bool:
    from kaiku_contracts import genai_client

    return genai_client.available()


@lru_cache(maxsize=4)
def _client(backend: str, timeout_s: float):
    """`backend` is only the cache key; the factory picks API key or Gemini platform (ADC)."""
    from kaiku_contracts import genai_client

    return genai_client.make_client(timeout_s=timeout_s)


def _ready(model: str, what: str) -> str:
    from kaiku_contracts import genai_client

    key = genai_client.backend() if genai_client.available() else ""
    if not key or not model or model.startswith("VERIFY"):
        raise LlmUnavailable(f"gemini {what} not configured (GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT+ADC / model id)")
    return key


def generate(prompt: str, *, tier: Tier = "fast", system: str | None = None, schema: dict[str, Any] | None = None,
             timeout_s: float | None = None, task: str = "text", home_id: str | None = None,
             route: str | None = None, model: str | None = None) -> str:
    """Text (or JSON when `schema` is given) from a Gemini model. Raises LlmUnavailable on any failure.
    `timeout_s`: the caller's, else `[cloud].gemini_text_timeout_s`."""
    timeout_s = _timeout(timeout_s, "gemini_text_timeout_s", 30)
    model = model or model_for(tier)
    key = _ready(model, tier)
    kw: dict[str, Any] = {"model": model, "input": prompt, "store": False}
    if system:
        kw["system_instruction"] = system
    if schema:
        kw["response_format"] = {"type": "text", "mime_type": "application/json", "schema": schema}
    est = budget.text_estimate(model, len(prompt) + len(system or ""), 400 if schema else 800)
    try:
        budget.guard("gemini", model, est)  # over the spend cap: no call, no ledger row, caller falls back
        client = _client(key, timeout_s)
        with ledger.timed(model, task, route=route, home_id=home_id):
            out = budget.metered("gemini", model, est, lambda: client.interactions.create(**kw), task=task,
                                 component="cloud")
            text = getattr(out, "output_text", None)
            if not text:
                raise ValueError("empty output")
        return text
    except Exception as e:  # network, quota, safety block, shape — all mean "use the fallback"
        raise LlmUnavailable(f"gemini {tier} ({model}) failed: {type(e).__name__}: {e}") from e


def generate_fast(prompt: str, timeout_s: float | None = None) -> str:
    """Adapter with the explain-backend signature."""
    return generate(prompt, tier="fast", timeout_s=timeout_s, task="explain")


def embed(text: str, *, query: bool, task: str = "embed", home_id: str | None = None,
          timeout_s: float | None = None) -> list[float]:
    """One Gemini Embedding 2 vector. Asymmetric retrieval format from the docs: queries are prefixed
    `task: question answering | query: …`, documents `title: none | text: …`. Auto-normalised at any dimension."""
    timeout_s = _timeout(timeout_s, "gemini_embed_timeout_s", 20)
    model = embedding_model()
    key = _ready(model, "embedding")
    content = f"task: question answering | query: {text}" if query else f"title: none | text: {text}"
    est = budget.estimate(model, in_tokens=len(content) // 3 + 50)
    try:
        from google.genai import types

        budget.guard("gemini", model, est)
        client = _client(key, timeout_s)
        cfg = types.EmbedContentConfig(output_dimensionality=int(get("mind", "embedding_dim", 768)))
        with ledger.timed(model, task, home_id=home_id):
            res = budget.metered("gemini", model, est, lambda: client.models.embed_content(
                model=model, contents=content, config=cfg), task=task, component="cloud")
            values = list(res.embeddings[0].values)
            if not values:
                raise ValueError("empty embedding")
        return values
    except Exception as e:
        raise LlmUnavailable(f"gemini embedding ({model}) failed: {type(e).__name__}: {e}") from e


def image(prompt: str, *, task: str = "image", home_id: str | None = None, aspect_ratio: str = "4:3",
          timeout_s: float | None = None) -> tuple[bytes, str]:
    """(image bytes, mime type) from the image model via the Interactions API (`output_image`, base64)."""
    timeout_s = _timeout(timeout_s, "gemini_image_timeout_s", 60)
    model = image_model()
    key = _ready(model, "image")
    est = budget.estimate(model, images=1)
    try:
        budget.guard("gemini", model, est)
        client = _client(key, timeout_s)
        with ledger.timed(model, task, home_id=home_id):
            if key == "platform":  # image models aren't on the platform Interactions API → generate_content
                return budget.metered("gemini", model, est, _platform_image, client, model, prompt, aspect_ratio,
                                      task=task, component="cloud")
            out = budget.metered("gemini", model, est, lambda: client.interactions.create(
                model=model, input=prompt, store=False, response_format={"type": "image", "aspect_ratio": aspect_ratio}),
                task=task, component="cloud")
            img = getattr(out, "output_image", None)
            data = getattr(img, "data", None)
            if not data:
                raise ValueError("no image in output")
        return base64.b64decode(data), str(getattr(img, "mime_type", None) or "image/png")
    except Exception as e:
        raise LlmUnavailable(f"gemini image ({model}) failed: {type(e).__name__}: {e}") from e


def _platform_image(client: Any, model: str, prompt: str, aspect_ratio: str) -> tuple[bytes, str]:
    from google.genai import types

    resp = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"],
                                           image_config=types.ImageConfig(aspect_ratio=aspect_ratio)))
    for part in resp.candidates[0].content.parts:
        blob = getattr(part, "inline_data", None)
        if blob is not None and blob.data:
            data = blob.data if isinstance(blob.data, bytes) else base64.b64decode(blob.data)
            return data, blob.mime_type or "image/png"
    raise ValueError("no image in output")
