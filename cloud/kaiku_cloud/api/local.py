"""`make cloud-local` entry point: loads the repo `.env` (GEMINI_API_KEY, KAIKU_LLM, tokens...) and then serves the
same app as Modal. Tests and `make smoke` import `kaiku_cloud.api.main:app` directly, so they never read `.env`
and never make paid model calls."""

from kaiku_contracts.config import load_dotenv

load_dotenv()

from .main import app  # noqa: E402

__all__ = ["app"]
