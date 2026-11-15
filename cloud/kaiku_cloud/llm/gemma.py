"""The one place the cloud picks where Gemma runs. Every Gemma call (practitioner review, record questions, the
companion's shared mind, nightly graph organisation, consensus explanations in the `auto` chain) goes through
`generate`, so the provider is one switch and telemetry names what really answered.

`config/kaiku.toml [gemma].provider` (env `KAIKU_GEMMA_PROVIDER`):
- `hosted` (default, verified with real calls): Gemma through the Gemini API (`[models].gemma_hosted`).
- `modal`: our own vLLM app `kaiku-gemma` on a Modal GPU (`cloud/gemma_app.py`, scale-to-zero). It must be deployed
  separately; a cold start takes minutes, so callers with short deadlines fall back.
There is no silent switch between providers: a failure raises `LlmUnavailable` and the caller uses its deterministic
fallback. An optional LoRA adapter (`[gemma_modal].adapter_repo`) is served only by the Modal app.
"""

from __future__ import annotations

from kaiku_contracts.config import get

from . import gemma_hosted, gemma_vllm
from .errors import LlmUnavailable

PROVIDERS = ("hosted", "modal")


def provider() -> str:
    value = str(get("gemma", "provider", "hosted"))
    return value if value in PROVIDERS else "hosted"


def model_name() -> str:
    """The model that answers under the selected provider, as shown in traces and `by`/`model` fields."""
    if provider() == "modal":
        adapter = str(get("gemma_modal", "adapter_repo", "") or "")
        return str(get("models", "gemma_hf_repo", "")) + (f"+{adapter}" if adapter else "")
    return str(get("models", "gemma_hosted", ""))


def provider_label() -> str:
    return {"hosted": "Gemma via the Gemini API", "modal": "Gemma on our Modal GPU (vLLM)"}[provider()]


def generate(prompt: str, timeout_s: float | None = None, *, task: str = "explain", home_id: str | None = None,
             max_output_tokens: int | None = None) -> str:
    """`max_output_tokens`: a caller whose answer is longer than the provider's configured cap allows (the
    developers' day read) says so; both adapters reserve and ask for that much."""
    more = {"max_output_tokens": int(max_output_tokens)} if max_output_tokens else {}
    if provider() == "modal":
        return gemma_vllm.generate(prompt, timeout_s=timeout_s or float(get("gemma_modal", "timeout_s", 60)), task=task,
                                   home_id=home_id, **more)
    return gemma_hosted.generate(prompt, timeout_s=timeout_s, task=task, home_id=home_id, **more)


__all__ = ["LlmUnavailable", "generate", "model_name", "provider", "provider_label"]
