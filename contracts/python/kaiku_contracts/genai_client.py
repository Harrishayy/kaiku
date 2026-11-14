"""One way to build a google-genai client for every Kaiku component (cloud, hub, evals, tools).

Two backends, chosen by `KAIKU_GENAI_BACKEND` (default `auto`):
  platform  Gemini platform (Google Cloud) with Application Default Credentials — `gcloud auth application-default
            login`; needs GOOGLE_CLOUD_PROJECT (+ GOOGLE_CLOUD_LOCATION, default "global"). Billing + budgets on that
            Cloud project. No API key anywhere.
  api_key   Gemini Developer API with GEMINI_API_KEY (needed for Live ephemeral tokens for the phone/Mac apps).
  auto      api_key if GEMINI_API_KEY is set, else platform if GOOGLE_CLOUD_PROJECT is set, else unavailable.
"""

from __future__ import annotations

import os
from typing import Any


def backend() -> str:
    b = (os.environ.get("KAIKU_GENAI_BACKEND") or "auto").strip().lower()
    if b in ("platform", "api_key"):
        return b
    if os.environ.get("GEMINI_API_KEY"):
        return "api_key"
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return "platform"
    return "none"


def available() -> bool:
    b = backend()
    return (b == "api_key" and bool(os.environ.get("GEMINI_API_KEY"))) or (
        b == "platform" and bool(os.environ.get("GOOGLE_CLOUD_PROJECT")))


def make_client(timeout_s: float | None = None, api_version: str | None = None) -> Any:
    """A configured genai.Client. Raises RuntimeError when no backend is configured."""
    from google import genai

    http: dict[str, Any] = {}
    if timeout_s:
        http["timeout"] = int(timeout_s * 1000)
    b = backend()
    if api_version and b == "api_key":  # the platform picks its own API version
        http["api_version"] = api_version
    if b == "api_key" and os.environ.get("GEMINI_API_KEY"):
        return genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=http or None)
    if b == "platform" and os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return genai.Client(enterprise=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"), http_options=http or None)
    raise RuntimeError("no Gemini backend: set GEMINI_API_KEY, or GOOGLE_CLOUD_PROJECT + ADC (gcloud auth "
                       "application-default login)")


def supports_ephemeral_tokens() -> bool:
    """Live ephemeral tokens are a Gemini Developer API feature (api_key backend only)."""
    return backend() == "api_key" and bool(os.environ.get("GEMINI_API_KEY"))
