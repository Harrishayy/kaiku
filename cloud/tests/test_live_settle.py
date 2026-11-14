"""Live budget reservations settle to real talk time: the close route, the `end_session` tool, a resume, a
recorded episode; the bounds; the caps; and the one-off command for rows that were never settled."""
import functools
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from kaiku_cloud.jobs import settle_live
from kaiku_cloud.mind import live_token
from kaiku_cloud.mind import session as mind_session
from kaiku_cloud.store.db import Store
from kaiku_contracts import budget
from kaiku_contracts.api import SessionClose, SessionCloseResult
from kaiku_contracts.config import load_config

HOME = "vera"
PER_MIN = budget.estimate("gemini-3.8-live", audio_min=1)
TOKEN_MIN = load_config()["live"]["token_minutes"]
FULL = PER_MIN * TOKEN_MIN


@pytest.fixture
def clock(monkeypatch):
    t = {"t": budget.now()}
    monkeypatch.setattr(budget, "now", lambda: t["t"])
    return t


@pytest.fixture
def live(client, clock, monkeypatch):
    """Real minting code, a provider that answers from memory (no network, no key in the environment), a private
    ledger with room, and the ledger's clock in the test's hands."""
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", "50")
    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", "50")
    provider = httpx.MockTransport(lambda request: httpx.Response(200, json={"name": "auth_tokens/test"}))
    mint = functools.partial(live_token.mint, api_key="test", transport=provider)
    monkeypatch.setattr(mind_session.start_session, "__defaults__", (None, mint))
    return client


def start(client, surface="iphone", intent="talk", home=HOME, **kw):
    r = client.post("/v1/companion/session", json={"home_id": home, "surface": surface, "intent": intent, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def close(client, sid, elapsed_s, home=HOME):
    return client.post("/v1/companion/close", json={"home_id": home, "session_id": sid, "elapsed_s": elapsed_s})


def tool(client, sid, name, home=HOME, surface="iphone", **args):
    r = client.post("/v1/companion/tool", json={"home_id": home, "surface": surface, "session_id": sid, "name": name,
                                                "args": args})
    assert r.status_code == 200, r.text
    return r.json()


def ledger():
    if not budget._db_path().is_file():
        return []
    c = sqlite3.connect(budget._db_path())
    try:
        return c.execute("SELECT task, usd, units FROM spend ORDER BY rowid").fetchall()
    finally:
        c.close()


def settlements():
    return [r for r in ledger() if r[0] == budget.LIVE_SETTLEMENT]


# ---------------------------------------------------------------- the reservation
def test_a_mint_reserves_the_whole_token_and_names_its_conversation(live):
    s = start(live)
    assert s["live_token"]["token"] == "auth_tokens/test"
    assert ledger() == [(budget.LIVE_RESERVATION, pytest.approx(FULL), f"reserved_audio_minutes={TOKEN_MIN:g} session={s['session_id']}")]
    start(live, surface="robot", intent="ritual")  # the robot's adapter meters its own key
    assert len(ledger()) == 1
    assert budget.spent() == pytest.approx(FULL)  # a conversation that never reports keeps its full reservation


# ---------------------------------------------------------------- the device's close
def test_close_settles_to_the_started_minutes(live, clock):
    sid = start(live)["session_id"]
    clock["t"] += 80
    r = close(live, sid, 73)
    assert r.status_code == 200 and SessionCloseResult.model_validate(r.json())
    assert r.json() == {"ok": True, "session_id": sid, "settled": 1, "billed_minutes": 2}
    assert budget.spent() == pytest.approx(2 * PER_MIN)
    assert [(usd, "via=close" in units, "used_s=73" in units) for _t, usd, units in settlements()] == [
        (pytest.approx(-(FULL - 2 * PER_MIN)), True, True)]


def test_a_double_close_and_a_shorter_one_change_nothing_a_longer_one_corrects(live):
    sid = start(live)["session_id"]
    assert close(live, sid, 73).json()["settled"] == 1
    again = close(live, sid, 73).json()
    assert again["settled"] == 0 and again["billed_minutes"] == 2 and len(settlements()) == 1
    assert close(live, sid, 5).json() == {"ok": True, "session_id": sid, "settled": 0, "billed_minutes": 2}
    longer = close(live, sid, 185).json()
    assert longer["settled"] == 1 and longer["billed_minutes"] == 4 and budget.spent() == pytest.approx(4 * PER_MIN)


@pytest.mark.parametrize("elapsed,minutes", [(0, 1), (0.4, 1), (59.9, 1), (60.1, 2), (TOKEN_MIN * 60, TOKEN_MIN),
                                             (TOKEN_MIN * 60 + 900, TOKEN_MIN), (86400, TOKEN_MIN)])
def test_close_is_bounded_by_one_minute_and_by_the_token(live, elapsed, minutes):
    sid = start(live)["session_id"]
    assert close(live, sid, elapsed).json()["billed_minutes"] == minutes
    assert budget.spent() == pytest.approx(minutes * PER_MIN)  # never less than a minute, never more than reserved


@pytest.mark.parametrize("bad", [-1, -0.001, 86401, "soon", None])
def test_a_length_that_makes_no_sense_is_refused_and_settles_nothing(live, bad):
    sid = start(live)["session_id"]
    assert close(live, sid, bad).status_code == 422
    assert settlements() == [] and budget.spent() == pytest.approx(FULL)
    assert close(live, sid, 30).json()["settled"] == 1  # a proper close still works afterwards


def test_close_for_an_unknown_session_or_another_home_is_not_found(live):
    sid = start(live)["session_id"]
    assert close(live, "no-such-session", 30).status_code == 404
    assert close(live, sid, 30, home="someone-else").status_code == 404
    assert settlements() == [] and budget.spent() == pytest.approx(FULL)
    with pytest.raises(KeyError):
        mind_session.close_session(live.app.state.store, SessionClose(home_id="x", session_id=sid, elapsed_s=1))


def test_close_without_a_reservation_is_harmless(live):
    robot = start(live, surface="robot", intent="ritual")["session_id"]
    assert close(live, robot, 120).json() == {"ok": True, "session_id": robot, "settled": 0, "billed_minutes": 0}
    assert ledger() == [] and not budget._db_path().exists()  # a close never creates a ledger


def test_a_claimed_length_never_ends_the_conversation_before_the_last_tool_call(live, clock):
    sid = start(live)["session_id"]
    clock["t"] += 200
    assert tool(live, sid, "feel", kind="other", heard={"valence": "neutral", "via": "voice"})["ok"]
    assert live.app.state.store.kv_get(f"live:{sid}") == {"last": clock["t"]}
    assert close(live, sid, 30).json()["billed_minutes"] == 4  # it was alive at 200 s, whatever the device says
    assert "used_s=200" in settlements()[0][2]


# ---------------------------------------------------------------- what the cloud sees itself
def test_end_session_settles_and_a_later_episode_can_only_add(live, clock):
    sid = start(live)["session_id"]
    clock["t"] += 40
    assert tool(live, sid, "end_session", outcome="completed")["ok"]
    grace = load_config()["live"]["settle_grace_s"]
    assert [("via=end_session" in u, f"used_s={40 + grace}" in u) for _t, _usd, u in settlements()] == [(True, True)]
    assert budget.spent() == pytest.approx(PER_MIN)
    now = datetime.now(UTC)
    ep = {"home_id": HOME, "id": sid, "surface": "iphone", "intent": "talk", "outcome": "completed",
          "start": (now - timedelta(seconds=200)).isoformat(), "end": now.isoformat()}
    assert live.post("/v1/companion/episode", json=ep).status_code == 200  # the talk went on after the goodbye
    assert budget.spent() == pytest.approx(4 * PER_MIN) and "via=episode" in settlements()[-1][2]
    assert live.post("/v1/companion/episode", json=ep).status_code == 200  # a retried episode post
    assert len(settlements()) == 2


def test_a_recorded_episode_settles_by_the_devices_own_start_and_end(live, clock):
    sid = start(live)["session_id"]
    clock["t"] += 3600  # posted from the offline queue an hour later: its own times still say how long it ran
    start_at = datetime.now(UTC) - timedelta(hours=1)
    ep = {"home_id": HOME, "id": sid, "surface": "iphone", "intent": "talk", "outcome": "completed",
          "start": start_at.isoformat(), "end": (start_at + timedelta(seconds=96)).isoformat()}
    assert live.post("/v1/companion/episode", json=ep).status_code == 200
    assert budget.spent() == pytest.approx(2 * PER_MIN) and "used_s=96" in settlements()[0][2]
    offline = {**ep, "id": "offline-only-episode"}  # one that never had a token
    assert live.post("/v1/companion/episode", json=offline).status_code == 200 and len(settlements()) == 1


def test_a_crisis_stop_settles_too(live, clock):
    sid = start(live)["session_id"]
    clock["t"] += 20
    out = tool(live, sid, "remember", category="people", text="I want to kill myself")
    assert out["crisis"] and "via=crisis" in settlements()[0][2] and budget.spent() == pytest.approx(PER_MIN)


def test_a_resume_settles_the_token_before_it_and_the_close_settles_the_last(live, clock):
    first = start(live, purpose="talk")
    sid = first["session_id"]
    assert first["max_session_seconds"] == 1800
    clock["t"] += 100  # a dropped socket asks for a fresh token early
    again = live.post("/v1/companion/session", json={"home_id": HOME, "surface": "iphone", "intent": "talk",
                                                     "purpose": "talk", "resume_session_id": sid})
    assert again.status_code == 200 and again.json()["session_id"] == sid
    tasks = [(t, round(usd, 2), u.split(" via=")[-1].split(" ")[0] if "via=" in u else "") for t, usd, u in ledger()]
    assert tasks == [(budget.LIVE_RESERVATION, FULL, ""), (budget.LIVE_SETTLEMENT, round(2 * PER_MIN - FULL, 2), "resume"),
                     (budget.LIVE_RESERVATION, FULL, "")]  # settled before the next one was reserved
    assert budget.spent() == pytest.approx(2 * PER_MIN + FULL)
    clock["t"] += 130
    assert close(live, sid, 230).json() == {"ok": True, "session_id": sid, "settled": 1, "billed_minutes": 5}
    assert budget.spent() == pytest.approx(5 * PER_MIN)  # 100 s on the first token, 130 s on the second


def test_a_token_used_to_its_end_before_the_resume_keeps_its_full_amount(live, clock):
    sid = start(live, purpose="talk")["session_id"]
    clock["t"] += TOKEN_MIN * 60 - 45
    live.post("/v1/companion/session", json={"home_id": HOME, "surface": "iphone", "intent": "talk", "purpose": "talk",
                                             "resume_session_id": sid})
    assert settlements()[0][1] == 0 and "via=resume" in settlements()[0][2]  # written, so it is settled; releases nothing
    assert budget.spent() == pytest.approx(2 * FULL)


# ---------------------------------------------------------------- the caps
def test_a_settled_conversation_makes_room_and_the_real_total_still_refuses(live, clock, monkeypatch):
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", str(FULL + 2 * PER_MIN))
    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", str(FULL + 2 * PER_MIN))
    one = start(live)
    assert one["live_token"] and start(live, home="b")["live_token"] is None  # the held reservation is in the way
    clock["t"] += 60
    close(live, one["session_id"], 50)  # really one minute
    two = start(live, home="b")
    assert two["live_token"] is not None  # one minute + a new reservation fits
    clock["t"] += 60
    assert start(live, home="c")["live_token"] is None
    close(live, two["session_id"], 170, home="b")  # really three minutes: the real total is four minutes
    assert budget.spent() == pytest.approx(4 * PER_MIN)
    assert start(live, home="c")["live_token"] is None  # four minutes + a new reservation is over the cap: refused
    assert budget.spent() == pytest.approx(4 * PER_MIN)  # and a refused mint reserves nothing


def test_the_meter_never_breaks_a_conversation(live, monkeypatch):
    sid = start(live)["session_id"]

    def broken(*a, **kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(budget, "settle_session", broken)
    monkeypatch.setattr(budget, "session_minutes", broken)
    assert tool(live, sid, "end_session", outcome="completed")["ok"]
    assert close(live, sid, 30).json() == {"ok": True, "session_id": sid, "settled": 0, "billed_minutes": 0}
    assert budget.spent() == pytest.approx(FULL)  # nothing settled: the reservation simply stays


# ---------------------------------------------------------------- the one-off command for old rows
def old_row(clock, at):
    """A reservation as rows looked before conversations were named."""
    clock["t"] = at
    return budget.charge("gemini", "gemini-3.8-live", FULL, task=budget.LIVE_RESERVATION, component="cloud",
                         units=f"reserved_audio_minutes={TOKEN_MIN:g}")


def iso(ts):
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def cloud_db(path, sessions, extra_mints=()):
    """A cloud database that logged these conversations: (id, home, surface, reserved_at, seconds | None)."""
    store = Store(str(path))
    for sid, home, surface, at, seconds in sessions:
        store.episode_upsert({"id": sid, "home_id": home, "surface": surface, "intent": "talk", "start": iso(at - 0.4),
                              "end": iso(at - 0.4 + seconds) if seconds is not None else None, "tools": [],
                              "outcome": "completed" if seconds is not None else None})
        store.model_call_insert({"ts": datetime.fromtimestamp(at + 0.6, UTC).isoformat(), "home_id": home,
                                 "model": "gemini-3.8-live", "task": "live_reservation", "ok": True})
    for at, home in extra_mints:
        store.model_call_insert({"ts": datetime.fromtimestamp(at + 0.6, UTC).isoformat(), "home_id": home,
                                 "model": "gemini-3.8-live", "task": "live_reservation", "ok": True})
    return path


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def run(capsys, *args):
    assert settle_live.main([str(a) for a in args]) == 0
    return capsys.readouterr().out


def test_the_one_off_command_prints_first_and_writes_only_when_told(clock, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KAIKU_BUDGET_TOTAL_USD", "30")
    monkeypatch.setenv("KAIKU_BUDGET_DAILY_USD", "28")
    base = float(int(budget.now())) - 3000
    a, b, c, d = (old_row(clock, base + i * 400) for i in range(4))
    db = cloud_db(tmp_path / "cloud.sqlite", [("ep-a", "h1", "iphone", a, 96), ("ep-b", "h2", "mac", b, 14),
                                              ("ep-c", "h1", "iphone", c, None)])  # c never reported; d: no record
    file = budget._db_path()
    before = md5(file)
    out = run(capsys, "--ledger", file, "--db", db, "--since", "2000-01-01")
    assert md5(file) == before  # a dry run reads only
    assert "dry run: nothing was written" in out and "would release $0.84 from 2 reservation(s); 2 left alone" in out
    assert f"before: total ${4 * FULL:.2f} of $30.00" in out and f"after:  total ${4 * FULL - 0.84:.2f} of $30.00" in out
    assert "96 s used, 2 min counted, $0.24 (releases $0.36)" in out and "14 s used, 1 min counted, $0.12 (releases $0.48)" in out
    assert "left alone: episode ep-c iphone/talk in cloud.sqlite: no recorded end" in out
    assert "left alone: no record of this conversation in the databases given" in out
    assert "h1" not in out and "h2" not in out  # no home ids in what it prints
    applied = run(capsys, "--ledger", file, "--db", db, "--since", "2000-01-01", "--apply")
    assert "released $0.84 from 2 reservation(s)" in applied and "dry run" not in applied.split("\n", 1)[1]
    assert budget.spent() == pytest.approx(4 * FULL - 0.84)
    rows = settlements()
    assert len(rows) == 2 and all("via=backfill_episode" in u and "session=- " in u for _t, _usd, u in rows)
    again = run(capsys, "--ledger", file, "--db", db, "--since", "2000-01-01", "--apply")
    assert "released $0.00 from 0 reservation(s); 2 left alone" in again and len(settlements()) == 2  # safe to repeat
    assert budget.live_reservations()[3]["ts"] == d and not budget.live_reservations()[3]["settled"]


def test_a_database_that_belongs_to_another_ledger_cannot_settle_a_row_by_coincidence(clock, tmp_path, capsys):
    base = float(int(budget.now())) - 3000
    mine = old_row(clock, base)
    # another instance started a conversation in the same second, and logged more mints that this ledger never saw
    other = cloud_db(tmp_path / "other.sqlite", [("ep-x", "h9", "iphone", mine + 0.3, 20)],
                     extra_mints=[(base + 500, "h9")])
    out = run(capsys, "--ledger", budget._db_path(), "--db", other, "--since", "2000-01-01", "--apply")
    assert "other.sqlite: IGNORED for unnamed rows" in out and "released $0.00 from 0 reservation(s); 1 left alone" in out
    assert settlements() == [] and budget.spent() == pytest.approx(FULL)


def test_two_conversations_at_one_moment_and_a_resumed_token_are_left_alone(clock, tmp_path, capsys):
    base = float(int(budget.now())) - 3000
    a = old_row(clock, base)
    resumed = old_row(clock, base + 255)
    args = ("--ledger", budget._db_path(), "--since", "2000-01-01")
    # more logged mints than this ledger has reservations: the database is not trusted at all
    crowd = cloud_db(tmp_path / "crowd.sqlite", [("ep-1", "h1", "iphone", a, 30), ("ep-2", "h1", "mac", a, 40)],
                     extra_mints=[(resumed, "h1")])
    out = run(capsys, *args, "--db", crowd)
    assert "crowd.sqlite: IGNORED for unnamed rows" in out and "would release $0.00 from 0 reservation(s); 2 left alone" in out
    # one mint, but the same home opened two conversations in that second (one got no token): which one is it?
    both = cloud_db(tmp_path / "both.sqlite", [("ep-1", "h1", "iphone", a, 30)], extra_mints=[(resumed, "h1")])
    Store(str(both)).episode_upsert({"id": "ep-2", "home_id": "h1", "surface": "mac", "intent": "talk",
                                     "start": iso(a - 1.4), "end": iso(a + 40), "tools": [], "outcome": "completed"})
    out = run(capsys, *args, "--db", both)
    assert "2 conversations started at that moment in both.sqlite: cannot tell which" in out
    assert "would release $0.00 from 0 reservation(s); 2 left alone" in out
    # the plain case: one conversation settles, and the token minted for its resume keeps its full amount
    one = cloud_db(tmp_path / "one.sqlite", [("ep-1", "h1", "iphone", a, 30)], extra_mints=[(resumed, "h1")])
    out = run(capsys, *args, "--db", one)
    assert "30 s used, 1 min counted" in out and "no conversation started with it (a resumed one keeps its full amount)" in out
    # the robot's own conversation in that second is never the one a token was minted for
    robot = cloud_db(tmp_path / "robot.sqlite", [("ep-r", "h1", "robot", a, 30)], extra_mints=[(resumed, "h1")])
    assert "would release $0.00 from 0 reservation(s); 2 left alone" in run(capsys, *args, "--db", robot)
    # and the same conversation found in two databases is no evidence either
    assert "2 databases logged a mint at that moment: cannot tell which" in run(capsys, *args, "--db", one, "--db", robot)


def test_named_conversations_settle_by_episode_next_mint_and_only_on_request_by_last_tool_call(clock, tmp_path, capsys):
    base = float(int(budget.now())) - 4000

    def named(session, at):
        clock["t"] = at
        return budget.charge("gemini", "gemini-3.8-live", FULL, task=budget.LIVE_RESERVATION, component="cloud",
                             units=budget.reservation_units(TOKEN_MIN, session))

    ended = named("ended", base)
    long_1 = named("long", base + 400)
    named("long", long_1 + 255)  # its second token: nothing says when that one stopped
    quiet = named("quiet", base + 1200)
    db = cloud_db(tmp_path / "cloud.sqlite", [("ended", "h1", "iphone", ended, 130), ("long", "h1", "iphone", long_1, None),
                                              ("quiet", "h2", "iphone", quiet, None)], extra_mints=[(long_1 + 255, "h1")])
    Store(str(db)).kv_set("live:quiet", {"last": quiet + 70})
    clock["t"] = base + 4000
    args = ("--ledger", budget._db_path(), "--db", db, "--since", "2000-01-01")
    out = run(capsys, *args)
    assert "130 s used, 3 min counted" in out and "[episode ended iphone/talk in cloud.sqlite, recorded end]" in out
    assert f"255 s used, {TOKEN_MIN:g} min counted" in out and "the conversation's next token was minted then" in out
    assert out.count("left alone:") == 2 and "would release $0.24 from 2 reservation(s); 2 left alone" in out
    out = run(capsys, *args, "--last-tool-call", "--apply")
    assert "70 s used, 2 min counted" in out and "last tool call the cloud saw (a lower bound)" in out
    assert "released $0.60 from 3 reservation(s); 1 left alone" in out
    assert {u.split(" via=")[1].split(" ")[0] for _t, _usd, u in settlements()} == {
        "backfill_episode", "backfill_next_mint", "backfill_last_tool"}


def test_the_command_refuses_a_missing_file_and_a_file_that_is_not_a_cloud_database(tmp_path, capsys):
    assert settle_live.main(["--ledger", str(tmp_path / "none.sqlite")]) == 2
    budget.charge("gemini", "gemini-3.8-live", FULL, task=budget.LIVE_RESERVATION, component="cloud",
                  units="reserved_audio_minutes=5")
    with pytest.raises(SystemExit, match="not a Kaiku cloud database"):
        settle_live.main(["--ledger", str(budget._db_path()), "--db", str(budget._db_path())])
