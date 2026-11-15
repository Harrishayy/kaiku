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
_last_answer: float | None = None  # monotonic time of this process's last answer from the GPU


def _warm(scaledown: float) -> bool:
    """The container that answered this process is still inside its scaledown window."""
    return _last_answer is not None and time.monotonic() - _last_answer < scaledown


def generate(prompt: str, timeout_s: float = 60.0, *, task: str = "explain", home_id: str | None = None,
             max_output_tokens: int | None = None) -> str:
    """`max_output_tokens`: the caller's cap, else `[gemma_modal].max_output_tokens`. The prompt plus this cap must
    fit `[gemma_modal].max_model_len`, or vLLM refuses the request and the caller falls back."""
    global _last_answer
    from kaiku_contracts import budget
    from kaiku_contracts.config import get

    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise LlmUnavailable("gemma_modal requires a finite positive timeout")
    deadline = time.monotonic() + timeout_s
    gpu = "modal-" + str(get("gemma_modal", "gpu", "H100"))
    scaledown = float(get("gemma_modal", "scaledown_s", 300))
    cold_s = float(get("gemma_modal", "cold_start_s", 240))
    margin_s = float(get("gemma_modal", "warm_margin_s", 30))
    # Cold (measured 235 s to a first answer, 2026-11-15): the start plus one idle tail. Warm: the idle time since
    # the last answer plus this call; the tail was reserved with the cold call.
    warm = _warm(scaledown)
    est = budget.estimate(gpu, gpu_s=(time.monotonic() - _last_answer + margin_s) if warm else (cold_s + scaledown))
    cap = int(max_output_tokens or get("gemma_modal", "max_output_tokens", 1200))
    try:
        budget.guard("modal", gpu, est)
        budget.charge("modal", gpu, est, task="gemma", component="cloud")
        import modal

        with ledger.timed(f"modal:{APP_NAME}", task, home_id=home_id):
            Gemma = modal.Cls.from_name(APP_NAME, "Gemma")
            call = Gemma().generate.spawn(prompt, max_tokens=cap)
            try:
                text = call.get(timeout=max(0.0, deadline - time.monotonic()))
                _last_answer = time.monotonic()
                return text
            except TimeoutError:
                # A result-wait timeout does not cancel GPU work; the reservation stays because it can still bill.
                # Warm: ask for cancellation without terminating the shared container. Cold: leave the call alone.
                # It is what starts the GPU (minutes, longer than any caller waits), so the caller falls back now
                # and a call inside the scaledown window after the start is answered.
                if warm:
                    with suppress(Exception):
                        call.cancel(terminate_containers=False)
                raise
    except Exception as e:  # not deployed, cold-start failure, not on Modal…
        raise LlmUnavailable(f"gemma_modal failed: {type(e).__name__}") from e
