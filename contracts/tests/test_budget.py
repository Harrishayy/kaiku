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


# ---------------------------------------------------------------- Live reservations settle to real talk time
MODEL = "gemini-3.8-live"


@pytest.fixture
def clock(monkeypatch):
    """The ledger's clock under test control (every row's ts, and "now" for a settlement)."""
    t = {"t": budget.now()}
    monkeypatch.setattr(budget, "now", lambda: t["t"])
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", "100")
    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", "100")
    return t


def reserve(minutes=5.0, session="s-1"):
    usd = budget.estimate(MODEL, audio_min=minutes)
    return budget.charge("gemini", MODEL, usd, task=budget.LIVE_RESERVATION, component="cloud",
                         units=budget.reservation_units(minutes, session))


def rows():
    import sqlite3

    c = sqlite3.connect(budget._db_path())
    try:
        return c.execute("SELECT ts, task, usd, units FROM spend ORDER BY rowid").fetchall()
    finally:
        c.close()


@pytest.mark.parametrize("used_s,minutes,billed", [(0, 5, 1), (1, 5, 1), (60, 5, 1), (61, 5, 2), (96, 5, 2),
                                                   (299, 5, 5), (300, 5, 5), (4000, 5, 5), (-30, 5, 1), (200, 2.5, 2.5),
                                                   (10, 0.5, 0.5)])
def test_a_reservation_bills_whole_started_minutes_at_least_one_at_most_what_it_reserved(used_s, minutes, billed):
    token = {"minutes": minutes, "usd": 0.12 * minutes}
    got = budget.bill(token, used_s)
    assert got["billed_min"] == billed and got["usd"] == pytest.approx(0.12 * billed)
    assert budget.bill(token, 0, min_minutes=0)["usd"] == 0  # only when a caller says nothing was started
    assert budget.bill({"minutes": 0, "usd": 0.6}, 30) == {"billed_min": 0, "usd": 0.6}  # unreadable: unchanged
    assert budget.bill(token, float("nan"))["usd"] == pytest.approx(0.12 * minutes)


def test_settling_appends_a_row_and_never_touches_the_reservation(clock):
    ts = reserve()
    before = rows()
    clock["t"] += 96
    done = budget.settle_session("s-1", via="close")
    assert [(d["billed_min"], d["delta"]) for d in done] == [(2, pytest.approx(-0.36))]
    after = rows()
    assert after[:1] == before and len(after) == 2  # append-only
    row = after[1]
    assert row[0] == ts and row[1] == budget.LIVE_SETTLEMENT and row[2] == pytest.approx(-0.36)
    for part in ("session=s-1", f"res_ts={ts!r}", "used_s=96", "billed_min=2", "reserved_min=5", "via=close", "at="):
        assert part in row[3], part
    assert budget.spent() == pytest.approx(0.24) and budget.report()["spent_usd"] == pytest.approx(0.24)
    assert budget.session_minutes("s-1") == 2


def test_a_second_settlement_changes_nothing_unless_it_shows_a_longer_conversation(clock):
    reserve()
    assert budget.settle_session("s-1", elapsed_s=70, via="end_session")[0]["billed_min"] == 2
    assert budget.settle_session("s-1", elapsed_s=70, via="close") == []  # a double close
    assert budget.settle_session("s-1", elapsed_s=5, via="close") == []   # shorter evidence never lowers it
    assert len(rows()) == 2 and budget.spent() == pytest.approx(0.24)
    more = budget.settle_session("s-1", elapsed_s=200, via="episode")     # the longest evidence wins
    assert more[0]["billed_min"] == 4 and more[0]["delta"] == pytest.approx(0.24) and budget.spent() == pytest.approx(0.48)
    budget.settle_session("s-1", elapsed_s=99999, via="close")
    assert budget.spent() == pytest.approx(0.60) and budget.session_minutes("s-1") == 5  # never above what was reserved
    assert budget.settle_session("s-1", elapsed_s=99999, via="close") == []


def test_zero_and_negative_lengths_cost_the_one_started_minute(clock):
    reserve(session="zero")
    clock["t"] += 1
    reserve(session="neg")
    assert budget.settle_session("zero", elapsed_s=0, via="close")[0]["billed_min"] == 1
    assert budget.settle_session("neg", elapsed_s=-500, via="close")[0]["billed_min"] == 1
    assert budget.spent() == pytest.approx(0.24)


def test_an_unknown_session_settles_nothing_and_a_lookup_never_creates_a_ledger(clock, tmp_path, monkeypatch):
    missing = tmp_path / "nowhere" / "spend.sqlite"
    monkeypatch.setenv("KAIKU_SPEND_DB", str(missing))
    assert budget.live_reservations() == [] and budget.settle_session("nobody", via="close") == []
    assert budget.settle(123.0, 10, via="backfill_episode") is None and budget.session_minutes("nobody") == 0
    assert not missing.exists() and not missing.parent.exists()
    monkeypatch.setenv("KAIKU_SPEND_DB", str(tmp_path / "spend.sqlite"))
    reserve(session="mine")
    assert budget.settle_session("someone-else", via="close") == [] and budget.settle_session("bad id!", via="close") == []
    assert budget.spent() == pytest.approx(0.60)  # one that never reports keeps its full reservation


def test_each_token_of_a_long_conversation_is_used_until_the_next_one_or_the_end(clock):
    first = reserve()
    clock["t"] += 255  # the device moves to its next token 45 s before the first one ends
    assert [d["billed_min"] for d in budget.settle_session("s-1", via="resume")] == [5]  # 255 s is the fifth minute
    second = reserve()
    clock["t"] += 100
    third = reserve()  # a reconnect that asked for a fresh token early
    done = budget.settle_session("s-1", elapsed_s=255 + 100 + 20, via="close")
    assert [(d["token"]["ts"], d["billed_min"]) for d in done] == [(second, 2), (third, 1)]
    assert first not in [d["token"]["ts"] for d in done]  # settled at the resume, and nothing longer is known
    assert budget.session_minutes("s-1") == 8 and budget.spent() == pytest.approx(0.12 * 8)
    # one pure function decides it: the same answer without a ledger
    tokens = [{"ts": 0.0, "minutes": 5.0, "usd": 0.6, "settled": False, "billed_min": None, "cost": 0.6},
              {"ts": 255.0, "minutes": 5.0, "usd": 0.6, "settled": False, "billed_min": None, "cost": 0.6}]
    plan = budget.plan_session(tokens, 290.0)
    assert [(p["used_s"], p["billed_min"]) for p in plan] == [(255.0, 5), (35.0, 1)]
    assert [p["billed_min"] for p in budget.plan_session(tokens, 30.0, floor_ts=200.0)] == [4, 1]  # known alive at 200 s


def test_the_caps_read_the_settled_total(clock, monkeypatch):
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", "1.0")
    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", "1.0")
    reserve(session="a")
    with pytest.raises(budget.BudgetExceeded):
        reserve(session="b")  # 0.60 held + 0.60 > 1.00
    budget.settle_session("a", elapsed_s=30, via="close")  # really one minute: 0.12
    clock["t"] += 60
    reserve(session="b")  # 0.12 + 0.60 fits
    with pytest.raises(budget.BudgetExceeded):
        reserve(session="c")
    budget.settle_session("b", elapsed_s=230, via="close")  # really four minutes: 0.48
    assert budget.spent() == pytest.approx(0.60)
    with pytest.raises(budget.BudgetExceeded):
        reserve(session="c")  # the real total, 0.60, plus a new reservation is still over the cap
    with pytest.raises(budget.BudgetExceeded):
        budget.guard("gemini", MODEL, 0.41)
    budget.guard("gemini", MODEL, 0.40)


def test_a_settlement_moves_the_day_its_reservation_was_made_on(clock):
    today = clock["t"]
    clock["t"] = today - 2 * 86400
    old = reserve(session="old")
    clock["t"] = today
    budget.settle_session("old", elapsed_s=30, via="backfill_episode")
    assert budget.spent() == pytest.approx(0.12) and budget.spent(budget._day_start()) == 0  # nothing of it is today's
    assert rows()[1][0] == old and f"at={today:.0f}" in rows()[1][3]  # the day it counts on, and when it was written


def test_old_rows_without_a_session_are_settled_by_their_own_timestamp_only(clock):
    ts = budget.charge("gemini", MODEL, 0.6, task=budget.LIVE_RESERVATION, component="cloud",
                       units="reserved_audio_minutes=5")  # how rows looked before conversations were named
    tok = budget.live_reservations()[0]
    assert tok["session"] is None and tok["minutes"] == 5 and not tok["settled"]
    assert budget.settle(ts + 1, 30, via="backfill_episode") is None  # not that reservation
    got = budget.settle(ts, 96, via="backfill_episode")
    assert got["billed_min"] == 2 and budget.spent() == pytest.approx(0.24)
    assert budget.settle(ts, 96, via="backfill_episode") is None and len(rows()) == 2
    assert "session=- " in rows()[1][3] and budget.live_reservations()[0]["settled"]


def test_two_reservations_with_one_timestamp_are_left_alone(clock):
    reserve(session="twin")
    reserve(session="twin")  # the clock did not move: they cannot be told apart
    assert budget.live_reservations() == [] and budget.settle_session("twin", elapsed_s=10, via="close") == []
    assert budget.spent() == pytest.approx(1.20)


def test_only_a_safe_session_id_is_written_on_a_reservation():
    assert budget.reservation_units(5, "01a1d83a-0529-7284") == "reserved_audio_minutes=5 session=01a1d83a-0529-7284"
    assert budget.reservation_units(2.5) == "reserved_audio_minutes=2.5"
    assert budget.reservation_units(5, "x via=close res_ts=1") == "reserved_audio_minutes=5"  # cannot forge fields
