"""Gemma 4 served with vLLM on a Modal GPU — the separate scale-to-zero app `kaiku-gemma` (cloud/gemma_app.py).
This adapter looks the deployed class up by name; works from Modal and from `make cloud-local` (Modal auth).
"""

from __future__ import annotations

import os

from . import ledger
from .errors import LlmUnavailable

APP_NAME = os.environ.get("KAIKU_GEMMA_APP", "kaiku-gemma")


def generate(prompt: str, timeout_s: float = 60.0) -> str:
    from kaiku_contracts import budget
    from kaiku_contracts.config import get

    gpu = "modal-" + str(get("gemma_modal", "gpu", "H100"))
    est = budget.estimate(gpu, gpu_s=float(get("gemma_modal", "scaledown_s", 60)) + 240)  # cold start + idle tail
    try:
        budget.guard("modal", gpu, est)
        budget.charge("modal", gpu, est, task="gemma", component="cloud")
        import modal

        Gemma = modal.Cls.from_name(APP_NAME, "Gemma")
        with ledger.timed(f"modal:{APP_NAME}", "explain"):
            return Gemma().generate.remote(prompt)
    except Exception as e:  # not deployed, cold-start failure, not on Modal…
        raise LlmUnavailable(f"gemma_modal failed: {type(e).__name__}: {e}") from e
