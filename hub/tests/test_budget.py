"""Spend cap on streaming sessions (Gemini Live, Lyria RealTime) via kaiku_contracts.budget, on a temp ledger."""

import asyncio

import pytest
from kaiku_contracts import budget
from kaiku_hub.live.meter import SessionMeter

LIVE = "gemini-3.8-live"


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIKU_SPEND_DB", str(tmp_path / "spend.sqlite"))
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", "10")
    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", "10")
    return tmp_path


def test_open_guards_five_minutes_and_charges_first():
    m = SessionMeter("gemini", LIVE)
    m.open()
    assert m.minutes == 1
    assert budget.spent() == pytest.approx(budget.estimate(LIVE, audio_min=1))


def test_open_refused_when_a_session_could_cross_the_cap(monkeypatch):
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", str(budget.estimate(LIVE, audio_min=4.9)))
    with pytest.raises(budget.BudgetExceeded):
        SessionMeter("gemini", LIVE).open()
    assert budget.spent() == 0


async def test_charges_per_started_minute_then_closes_on_cap(monkeypatch):
    per_min = budget.estimate(LIVE, audio_min=1)
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", str(per_min * 6.5))  # room for open + 5 more minutes
    closed = asyncio.Event()

    async def on_exceeded():
        closed.set()

    m = SessionMeter("gemini", LIVE, minute_s=0.01)
    m.open()
    m.start(on_exceeded)
    await asyncio.wait_for(closed.wait(), 2)
    assert m.minutes == 6
    assert budget.spent() == pytest.approx(per_min * 6)
    assert budget.spent() <= budget.limits()["total"]


async def test_stop_ends_charging():
    m = SessionMeter("gemini", LIVE, minute_s=0.01)
    m.open()

    async def never():
        raise AssertionError

    m.start(never)
    m.stop()
    await asyncio.sleep(0.05)
    assert m.minutes == 1


def test_lyria_prices_as_lyria_realtime():
    assert budget.price("lyria-realtime-exp") == budget.price("lyria-realtime")


async def test_gemini_live_does_not_open_over_budget(monkeypatch):
    gl = pytest.importorskip("kaiku_hub.live.gemini_live")
    if gl.genai is None:
        pytest.skip("google-genai not installed")
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-a-key")
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", "0.01")
    voice = gl.GeminiLiveVoice(LIVE)

    def connect(**kw):
        raise AssertionError("must not connect over budget")

    monkeypatch.setattr(voice.client.aio.live, "connect", connect)
    assert await voice.open_session("hi", []) is False
    assert voice._session is None and budget.spent() == 0
