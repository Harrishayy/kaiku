"""Gemma 4 served with vLLM on a Modal GPU — the separate scale-to-zero app `kaiku-gemma` (cloud/gemma_app.py).
This adapter looks the deployed class up by name; works from Modal and from `make cloud-local` (Modal auth).
"""

from __future__ import annotations

import math
import os
import time
from contextlib import suppress

from . import ledger
from .errors import LlmUnavailable

APP_NAME = os.environ.get("KAIKU_GEMMA_APP", "kaiku-gemma")


def generate(prompt: str, timeout_s: float = 60.0, *, task: str = "explain", home_id: str | None = None) -> str:
    from kaiku_contracts import budget
    from kaiku_contracts.config import get

    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise LlmUnavailable("gemma_modal requires a finite positive timeout")
    deadline = time.monotonic() + timeout_s
    gpu = "modal-" + str(get("gemma_modal", "gpu", "H100"))
    est = budget.estimate(gpu, gpu_s=float(get("gemma_modal", "scaledown_s", 60)) + 240)  # cold start + idle tail
    try:
        budget.guard("modal", gpu, est)
        budget.charge("modal", gpu, est, task="gemma", component="cloud")
        import modal

        with ledger.timed(f"modal:{APP_NAME}", task, home_id=home_id):
            Gemma = modal.Cls.from_name(APP_NAME, "Gemma")
            call = Gemma().generate.spawn(prompt)
            try:
                return call.get(timeout=max(0.0, deadline - time.monotonic()))
            except TimeoutError:
                # A result-wait timeout does not cancel GPU work. Request cancellation without terminating
                # the shared container; retain the reservation because dispatched work can still be billed.
                with suppress(Exception):
                    call.cancel(terminate_containers=False)
                raise
    except Exception as e:  # not deployed, cold-start failure, not on Modal…
        raise LlmUnavailable(f"gemma_modal failed: {type(e).__name__}") from e
