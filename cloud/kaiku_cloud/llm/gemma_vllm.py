"""Gemma 4 served with vLLM on a Modal GPU (class `Gemma` in cloud/app.py, deployed only when
KAIKU_LLM=gemma_modal at deploy time). This adapter looks the deployed class up by name.
"""

from __future__ import annotations

import os

from .errors import LlmUnavailable

APP_NAME = os.environ.get("KAIKU_MODAL_APP", "kaiku")


def generate(prompt: str, timeout_s: float = 60.0) -> str:
    try:
        import modal

        Gemma = modal.Cls.from_name(APP_NAME, "Gemma")
        return Gemma().generate.remote(prompt)
    except Exception as e:  # not deployed, cold-start failure, not on Modal…
        raise LlmUnavailable(f"gemma_modal failed: {type(e).__name__}: {e}") from e
