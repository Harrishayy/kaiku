"""Hard spend cap: never cross the total or daily limit; fallbacks take over."""

import pytest
from kaiku_contracts import budget


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIKU_SPEND_DB", str(tmp_path / "spend.sqlite"))
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", "1.0")
    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", "0.5")


def test_estimates_use_config_prices_by_prefix():
    assert budget.estimate("gemini-4-argon", in_tokens=1_000_000) == pytest.approx(6.0)
    assert budget.estimate("gemini-3.8-live", audio_min=10) == pytest.approx(1.2)
    assert budget.estimate("modal-H100", gpu_s=3600) == pytest.approx(4.5)
    assert budget.estimate("unknown-model", out_tokens=1_000_000) == pytest.approx(30.0)  # conservative default


def test_flash_tts_not_priced_as_flash():
    assert budget.price("gemini-3.8-flash-tts")["out_per_m"] == 25.0


def test_guard_blocks_at_daily_then_total():
    budget.guard("gemini", "x", 0.49)
    budget.charge("gemini", "x", 0.49)
    budget.guard("gemini", "x", 0.01)                 # exactly at the daily cap is allowed
    with pytest.raises(budget.BudgetExceeded, match="daily"):
        budget.guard("gemini", "x", 0.02)


def test_total_cap(monkeypatch):
    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", "100")
    budget.charge("modal", "modal-H100", 0.95)
    with pytest.raises(budget.BudgetExceeded, match="total"):
        budget.guard("gemini", "gemini-4-argon", 0.06)
    r = budget.report()
    assert r["spent_usd"] == pytest.approx(0.95) and r["remaining_usd"] == pytest.approx(0.05)


def test_concurrent_calls_reserve_before_provider_work(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", "1")
    started, release = Event(), Event()

    def provider():
        started.set()
        assert release.wait(5)
        return "first"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(budget.metered, "fake", "x", 0.75, provider)
        try:
            assert started.wait(5)
            second = pool.submit(budget.metered, "fake", "x", 0.75,
                                 lambda: pytest.fail("unadmitted provider must never run"))
            with pytest.raises(budget.BudgetExceeded):
                second.result(timeout=5)
            assert budget.spent() == pytest.approx(0.75)
        finally:
            release.set()
        assert first.result(timeout=5) == "first"


def test_processes_share_atomic_admission(monkeypatch):
    import os
    import subprocess
    import sys

    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", "1")
    # Independent Python processes have independent threading locks but share the SQLite reservation.
    code = """
from kaiku_contracts import budget
try:
    budget.charge('fake', 'x', 0.75)
except budget.BudgetExceeded:
    raise SystemExit(3)
"""
    children = [subprocess.Popen([sys.executable, "-c", code], env=os.environ.copy()) for _ in range(3)]
    try:
        results = sorted(p.wait(timeout=10) for p in children)
        assert results == [0, 3, 3]
        assert budget.spent() == pytest.approx(0.75)
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
                process.wait()


def test_failed_provider_keeps_reservation():
    def provider():
        raise TimeoutError("possibly billed")

    with pytest.raises(TimeoutError):
        budget.metered("fake", "x", 0.25, provider)
    assert budget.spent() == pytest.approx(0.25)


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf")])
def test_invalid_estimate_cannot_reduce_reserved_spend(cost):
    with pytest.raises(ValueError):
        budget.charge("fake", "x", cost)
    assert budget.spent() == 0


def test_dotenv_never_loaded_under_pytest(tmp_path, monkeypatch):
    from kaiku_contracts import config

    env = tmp_path / ".env"
    env.write_text("KAIKU_TEST_SECRET=leak\n")
    monkeypatch.delenv("KAIKU_TEST_SECRET", raising=False)
    config.load_dotenv(env)
    import os

    assert "KAIKU_TEST_SECRET" not in os.environ
