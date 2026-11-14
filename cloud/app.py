"""Kaiku on Modal: API + static web app, 15-min recompute, nightly simulation fan-out, Gemma is a separate app (gemma_app.py).

    cd cloud && uv run modal serve app.py     # dev, hot reload  (make cloud-dev)
    cd cloud && uv run modal deploy app.py    # public URL       (make cloud-deploy)

Deploy-time env (read on your laptop when you run modal deploy):
    KAIKU_LLM=template|gemma_hosted|gemma_modal   (gemma_modal also deploys the vLLM GPU class)
    KAIKU_MODAL_SECRET=kaiku-secrets              (optional; skipped with a warning if it doesn't exist)
"""

from __future__ import annotations

import os
from pathlib import Path

import modal

APP_NAME = os.environ.get("KAIKU_MODAL_APP", "kaiku")
ROOT = Path(__file__).resolve().parents[1]
WEB_OUT = ROOT / "apps" / "web" / "out"
LLM = os.environ.get("KAIKU_LLM", "template")
SECRET_NAME = os.environ.get("KAIKU_MODAL_SECRET", "kaiku-secrets")
DATA = "/data"

app = modal.App(APP_NAME)
volume = modal.Volume.from_name("kaiku-data", create_if_missing=True)


def _secrets() -> list[modal.Secret]:
    """Attach the secret only if it exists, so a first deploy works with zero setup.
    The decision is made locally and carried into the container via KAIKU_HAS_SECRET."""
    if not modal.is_local():
        return [modal.Secret.from_name(SECRET_NAME)] if os.environ.get("KAIKU_HAS_SECRET") == "1" else []
    try:
        s = modal.Secret.from_name(SECRET_NAME)
        s.hydrate()
        return [s]
    except Exception:
        print(f"[kaiku] Modal secret {SECRET_NAME!r} not found — deploying without it (auth off, template explanations). "
              f"Create it with: modal secret create {SECRET_NAME} KAIKU_HOME_TOKEN=... GEMINI_API_KEY=...")
        return []


SECRETS = _secrets()
ENV = {
    "KAIKU_DB_PATH": f"{DATA}/kaiku.sqlite",
    "KAIKU_CONFIG": "/root/config/kaiku.toml",
    "KAIKU_CRITERIA": "/root/config/criteria.toml",
    "KAIKU_WEB_DIR": "/root/web",  # Next.js static export; API serves a JSON root if it wasn't built
    "KAIKU_VOICE_CACHE": f"{DATA}/voice_cache",  # rendered TTS audio survives restarts (Volume)
    "KAIKU_MIND_POSTCARD_DIR": f"{DATA}/postcards",  # walk postcards (Nano Banana 2 Lite), cached on the Volume
    "KAIKU_SPEND_DB": f"{DATA}/spend.sqlite",  # hard spend cap ledger survives restarts
    "KAIKU_LLM": LLM,
    "KAIKU_MODAL_APP": APP_NAME,
    "KAIKU_HAS_SECRET": "1" if SECRETS else "0",
}

# Build steps first; add_local_* must be the last layers.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("pydantic>=2.7", "fastapi>=0.115", "httpx>=0.27", "tzdata>=2024.1", "google-genai>=2.25")
    .env(ENV)
    .add_local_dir(ROOT / "config", "/root/config")  # kaiku.toml + criteria.toml (live overrides live in the DB)
    .add_local_python_source("kaiku_contracts", "kaiku_cloud")
)
if modal.is_local() and WEB_OUT.is_dir():
    image = image.add_local_dir(WEB_OUT, "/root/web")
elif modal.is_local():
    print("[kaiku] apps/web/out not found — deploying API only (run `make web-build` first for the dashboard)")


@app.function(image=image, timeout=600)
def simulate_shard(args: tuple[int, int]) -> list[dict]:
    """One shard of the consensus simulation (fan-out target for .map)."""
    from kaiku_cloud.jobs.simulate import run_shard

    return run_shard(args)


@app.function(image=image, volumes={DATA: volume}, secrets=SECRETS, min_containers=1, max_containers=1,
              timeout=600)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    """API + static web app. Exactly one container: SQLite has a single writer."""
    from kaiku_cloud.api.main import create_app
    from kaiku_cloud.jobs.simulate import run_eval

    def eval_runner(criteria):
        return run_eval(n_patients=72, shards=8, mapper=lambda xs: simulate_shard.map(xs), criteria=criteria)

    return create_app(eval_runner=eval_runner, after_write=volume.commit)


def _call_recompute(with_eval: bool) -> None:
    """Recompute runs INSIDE the API container (keeps one SQLite writer); scheduled functions just call it."""
    import httpx

    url = web.get_web_url()
    headers = {}
    if os.environ.get("KAIKU_ADMIN_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['KAIKU_ADMIN_TOKEN']}"
    r = httpx.post(f"{url}/v1/admin/recompute", params={"eval": str(with_eval).lower()}, headers=headers, timeout=600)
    r.raise_for_status()
    print(r.json().get("recomputed"), "patients recomputed", "+ simulation" if with_eval else "")


@app.function(image=image, secrets=SECRETS, schedule=modal.Period(minutes=15))
def recompute():
    """Consensus for every patient every 15 min (also recomputed on every ingest)."""
    _call_recompute(with_eval=False)


@app.function(image=image, secrets=SECRETS, schedule=modal.Cron("0 3 * * *", timezone="Europe/Helsinki"))
def nightly():
    """Recompute + refresh the simulation shown on /eval, then the daily reflection (flagship; rule without a key)."""
    _call_recompute(with_eval=True)
    _call_reflect()
    _call_admin("nightly-mind")  # graph rebuild, Embedding 2 backfill, validated consolidation, pre-render list


@app.function(image=image, secrets=SECRETS, schedule=modal.Cron("0 6 * * 1", timezone="Europe/Helsinki"))
def weekly():
    """Monday 06:00: clinician briefs (flagship, grounded in metric ids; template fallback)."""
    _call_admin("weekly")


def _call_admin(path: str) -> None:
    import httpx

    headers = {"Authorization": f"Bearer {os.environ['KAIKU_ADMIN_TOKEN']}"} if os.environ.get("KAIKU_ADMIN_TOKEN") else {}
    r = httpx.post(f"{web.get_web_url()}/v1/admin/{path}", headers=headers, timeout=900)
    r.raise_for_status()
    print(path, "ok")


def _call_reflect() -> None:
    import httpx

    headers = {"Authorization": f"Bearer {os.environ['KAIKU_ADMIN_TOKEN']}"} if os.environ.get("KAIKU_ADMIN_TOKEN") else {}
    r = httpx.post(f"{web.get_web_url()}/v1/admin/reflect", headers=headers, timeout=900)
    r.raise_for_status()
    print(r.json().get("reflected"), "homes reflected")


# Gemma 4 lives in its own scale-to-zero Modal app: cloud/gemma_app.py (`make gemma-deploy`).


@app.local_entrypoint()
def main():
    """`modal run app.py` — run the simulation with a Modal fan-out and print the result."""
    from kaiku_cloud.jobs.simulate import run_eval

    print(run_eval(n_patients=72, shards=8, mapper=lambda xs: simulate_shard.map(xs)))
