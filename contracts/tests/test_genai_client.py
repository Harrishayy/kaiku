"""Backend selection for every Gemini client: API key, Gemini platform (ADC), or none."""

import pytest
from kaiku_contracts import genai_client as g


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_CLOUD_PROJECT", "KAIKU_GENAI_BACKEND"):
        monkeypatch.delenv(k, raising=False)


def test_none_configured():
    assert g.backend() == "none" and not g.available()
    with pytest.raises(RuntimeError):
        g.make_client()


def test_auto_prefers_key_then_platform(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    assert g.backend() == "platform" and g.available() and not g.supports_ephemeral_tokens()
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert g.backend() == "api_key" and g.supports_ephemeral_tokens()


def test_forced_platform_without_project_is_unavailable(monkeypatch):
    monkeypatch.setenv("KAIKU_GENAI_BACKEND", "platform")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert g.backend() == "platform" and not g.available()
