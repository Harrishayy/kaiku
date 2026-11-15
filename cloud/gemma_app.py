"""Gemma 4 on Modal (vLLM) — a separate app, `kaiku-gemma`, so the API deploys without a GPU and Gemma costs
nothing until it is called. Scale-to-zero: min_containers=0, short scaledown window, max one GPU.

    cd cloud && uv run modal run gemma_app.py::download     # once: weights -> Volume, CPU only (no GPU time)
    cd cloud && uv run modal deploy gemma_app.py            # register the class (no container starts)
    cd cloud && uv run modal run gemma_app.py::smoke        # ONE cold call (~2-4 min of GPU), then scales to zero

Callers (cloud/kaiku_cloud/llm/gemma_vllm.py) look it up with modal.Cls.from_name("kaiku-gemma", "Gemma").
Config: config/kaiku.toml [models].gemma_hf_repo, [gemma_modal] gpu / scaledown_s / max_model_len.
Weights are gated: the Modal secret `huggingface` must hold HF_TOKEN for an account that accepted the Gemma terms.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
_LOCAL = modal.is_local()
_CFG = tomllib.loads((ROOT / "config" / "kaiku.toml").read_text()) if _LOCAL else {}
_G = _CFG.get("gemma_modal", {})


def _cfg(section: str, key: str, in_container: str | int) -> str | int:
    """config/kaiku.toml is the only source of these values. It is read on the machine that runs `modal deploy`
    / `modal run` (the image does not carry config/), where a missing key stops the deploy with a clear message.
    Inside the container this module is imported again without the file: what the model needs travels in the
    image env (GEMMA_REPO, GEMMA_MAX_LEN, GEMMA_ADAPTER), and the decorator arguments below were fixed at deploy
    time, so `in_container` is only a placeholder there. It is kept equal to the config value on purpose."""
    if not _LOCAL:
        return in_container
    value = _CFG.get(section, {}).get(key)
    if value in (None, ""):
        raise SystemExit(f"config/kaiku.toml [{section}].{key} is missing: set it before deploying kaiku-gemma")
    return value


REPO = os.environ.get("KAIKU_GEMMA_REPO") or str(_cfg("models", "gemma_hf_repo", "google/gemma-4-26B-A4B-it"))
GPU = os.environ.get("KAIKU_GEMMA_GPU") or str(_cfg("gemma_modal", "gpu", "H100"))
SCALEDOWN_S = int(os.environ.get("KAIKU_GEMMA_SCALEDOWN_S") or _cfg("gemma_modal", "scaledown_s", 300))
MAX_LEN = int(_cfg("gemma_modal", "max_model_len", 16384))
# Optional LoRA adapter (HF repo) applied on top of the base weights. Empty = base model. Not yet run on a GPU.
ADAPTER = os.environ.get("KAIKU_GEMMA_ADAPTER") or _G.get("adapter_repo", "")
HF_SECRET = os.environ.get("KAIKU_HF_SECRET", "huggingface")
CACHE = "/root/.cache/huggingface"

app = modal.App(os.environ.get("KAIKU_GEMMA_APP", "kaiku-gemma"))
hf_cache = modal.Volume.from_name("kaiku-hf-cache", create_if_missing=True)
secrets = [modal.Secret.from_name(HF_SECRET)]
env = {"GEMMA_REPO": REPO, "GEMMA_MAX_LEN": str(MAX_LEN), "GEMMA_ADAPTER": ADAPTER, "HF_HUB_ENABLE_HF_TRANSFER": "1"}

dl_image = modal.Image.debian_slim(python_version="3.12").pip_install("huggingface_hub[hf_transfer]").env(env)
# CUDA *devel* base: vLLM's flashinfer sampler JIT-compiles with nvcc at first use; on debian_slim the engine died
# at warmup with "Could not find nvcc" (seen 2026-11-14). The env switch keeps the torch sampler as a second guard.
vllm_image = (modal.Image.from_registry("nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12").entrypoint([])
              .pip_install("vllm", "huggingface_hub[hf_transfer]")
              .env({**env, "VLLM_USE_FLASHINFER_SAMPLER": "0"}))


def _token() -> str | None:
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")


@app.function(image=dl_image, volumes={CACHE: hf_cache}, secrets=secrets, timeout=3600, cpu=2)
def download() -> str:
    """CPU-only: pull the weights into the shared Volume so GPU containers start without downloading."""
    from huggingface_hub import snapshot_download

    path = snapshot_download(REPO, token=_token(), ignore_patterns=["*.gguf", "original/*"])
    adapter = os.environ.get("GEMMA_ADAPTER")
    if adapter:
        path += " + " + snapshot_download(adapter, token=_token())
    hf_cache.commit()
    return f"{REPO} -> {path}"


@app.cls(image=vllm_image, gpu=GPU, volumes={CACHE: hf_cache}, secrets=secrets, min_containers=0, max_containers=1,
         scaledown_window=SCALEDOWN_S, timeout=900, startup_timeout=900)
class Gemma:
    @modal.enter()
    def load(self) -> None:
        os.environ["HF_HUB_OFFLINE"] = "1"  # weights come from the Volume (run `download` first)
        from vllm import LLM

        adapter = os.environ.get("GEMMA_ADAPTER")
        self.llm = LLM(model=os.environ["GEMMA_REPO"], max_model_len=int(os.environ["GEMMA_MAX_LEN"]),
                       enable_lora=bool(adapter))
        self.lora = None
        if adapter:
            from huggingface_hub import snapshot_download
            from vllm.lora.request import LoRARequest

            self.lora = LoRARequest("kaiku-adapter", 1, snapshot_download(adapter))

    @modal.method()
    def generate(self, prompt: str, max_tokens: int = 800, temperature: float = 0.2, system: str | None = None) -> str:
        from vllm import SamplingParams

        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        out = self.llm.chat(msgs, SamplingParams(temperature=temperature, max_tokens=max_tokens), lora_request=self.lora)
        return out[0].outputs[0].text


@app.local_entrypoint()
def smoke() -> None:
    """One cold call to prove the source works. Prints latency; the container scales to zero afterwards."""
    import time

    t = time.time()
    text = Gemma().generate.remote("In one short, warm sentence, say good morning to someone named Aino.", max_tokens=60)
    print(f"[{REPO} on {GPU}] {time.time() - t:.1f}s -> {text!r}")
