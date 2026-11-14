"""Gemma 4 served with vLLM on a Modal GPU — the separate scale-to-zero app `kaiku-gemma` (cloud/gemma_app.py).
This adapter looks the deployed class up by name; works from Modal and from `make cloud-local` (Modal auth).
"""

from __future__ import annotations

import os

from .errors import LlmUnavailable

APP_NAME = os.environ.get("KAIKU_GEMMA_APP", "kaiku-gemma")


def generate(prompt: str, timeout_s: float = 60.0) -> str:
    try:
        import modal

        Gemma = modal.Cls.from_name(APP_NAME, "Gemma")
        return Gemma().generate.remote(prompt)
    except Exception as e:  # not deployed, cold-start failure, not on Modal…
        raise LlmUnavailable(f"gemma_modal failed: {type(e).__name__}: {e}") from e
