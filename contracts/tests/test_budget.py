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
