"""Aino's first sixteen days: the authored record is coherent across sources, the REAL rule reaches the story's
states day by day, today's recordings move it either way, and private continuity never reaches a care route."""
import json
import re
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from statistics import fmean

import pytest
from fastapi.testclient import TestClient
from kaiku_cloud import clinician_chat, service, week
from kaiku_cloud.analytics import bandit, consensus
from kaiku_cloud.api.main import create_app
from kaiku_cloud.jobs import single_person
from kaiku_cloud.settings import TZ, Settings
from kaiku_cloud.store.db import Store
from kaiku_contracts import validate

END = date(2026, 11, 13)
FIRST = END - timedelta(days=15)
TODAY = END + timedelta(days=1)
NOW = datetime.combine(TODAY, time(20, 0), TZ)
DIP = range(9, 13)  # story days 10-13 (0-based 9..12): the short nights


@pytest.fixture(scope="module")
def rows():
    return single_person.build(END)


@pytest.fixture
def record(rows):
    store = Store(":memory:")
    return store, single_person.populate(store, rows, END)


def day_index(row) -> int:
    payload = row["payload"]
    day = date.fromisoformat(payload["date"]) if row["type"] == "obs.wearable_daily" else week.local_date(row["ts"])
    return (day - FIRST).days


def by_day(rows, kind, field, where=None) -> dict[int, float]:
    out: dict[int, list[float]] = {}
    for row in rows:
        if row["type"] == kind and all(row["payload"].get(k) == v for k, v in (where or {}).items()):
            out.setdefault(day_index(row), []).append(row["payload"][field])
    return {i: fmean(v) for i, v in out.items()}


def replay(store, today=TODAY, now=NOW):
    crit = service.active_criteria(store)
    return consensus.replay(service.patient_data(store, "aino", crit), crit, today, now)


def worse(result) -> set[str]:
    return {v.source for v in result.verdicts if v.verdict == "worse"}


# ---------------------------------------------------------------------------------------------- the record itself
def test_record_is_reproducible_valid_and_ends_yesterday_with_today_empty(rows):
    assert rows == single_person.build(END)
    assert len(rows) == len({row["id"] for row in rows}) > 330
    assert {week.local_date(row["ts"]) for row in rows} == {FIRST + timedelta(days=i) for i in range(16)}
    assert {row["home_id"] for row in rows} == {"aino"}
    assert {"hub", "phone", "laptop"} == {row["source"] for row in rows}
    for row in rows:
        validate(row)
        assert row["sim"] is True  # the envelope stays truthful
        assert row["type"] not in {"obs.light_level", "obs.laptop_session", "obs.friend_link", "obs.safety_flag",
                               "obs.hrv_session"}  # robot pulse is not measured yet: never guessed
        assert not {"force_mean", "daylight_min", "cadence_spm", "camera_method", "hr_before_bpm"} & row["payload"].keys()
        if row["type"] == "obs.outing":
            assert row["source"] == "phone" and row["payload"]["method"] == "steps"
        if row["type"] == "obs.screen_activity":
            assert sum(row["payload"]["category_min"].values()) == row["payload"]["active_min"] <= 60
    # every consensus source and the learner are fed
    assert {"obs.self_report", "obs.drum_session", "obs.presence", "obs.speech_features", "obs.outing",
            "obs.screen_activity", "obs.play_session", "obs.wearable_daily", "obs.phq9", "obs.ritual",
            "obs.nudge_offered", "obs.nudge_outcome", "obs.intervention_response"} <= {row["type"] for row in rows}
    assert {r["payload"]["game"] for r in rows if r["type"] == "obs.play_session"} == {"firefly", "pebbles", "tell", "breathe"}


def test_nothing_a_screen_could_show_says_it_is_made_up():
    shown = [single_person.HOME, single_person.CARE_BY, single_person.CARE_NOTE, *(t for _c, t in single_person.NOTES),
             *(line for _s, _t, lines in single_person.TALKS.values() for line in lines),
             *(topic for _skill, topic in single_person.THREADS.values()), *single_person.REASONS.values(),
             *(d.note for d in single_person.DAYS)]
    assert not [text for text in shown if re.search(r"demo|test|\bsim|synthetic|fake|fixture", text, re.I)]


def test_capture_is_mostly_complete_with_a_few_real_gaps(rows):
    cells = {"ritual": by_day(rows, "obs.ritual", "duration_s", {"step": "close"}),
             "walk": by_day(rows, "obs.outing", "minutes"), "watch": by_day(rows, "obs.wearable_daily", "steps"),
             "game": by_day(rows, "obs.play_session", "reaction_ms_median", {"game": "firefly"}),
             "drum": by_day(rows, "obs.drum_session", "tempo_bpm"),
             "mac": {i: 1 for i in range(16) if single_person.DAYS[i].mac}}
    share = sum(len(v) for v in cells.values()) / (16 * len(cells))
    assert .85 <= share <= .95
    assert all(len(v) < 16 for v in cells.values())  # every stream has at least one missing day
    assert len(by_day(rows, "obs.self_report", "value", {"item": "mood"})) == 16  # a dial every day, robot or phone


def test_sources_agree_with_each_other_on_the_same_day(rows):
    sleep = by_day(rows, "obs.wearable_daily", "sleep_min")
    midpoint = by_day(rows, "obs.wearable_daily", "sleep_midpoint_min")
    up = {day_index(r): week.parse_ts(r["ts"]).astimezone(TZ).hour * 60 + week.parse_ts(r["ts"]).astimezone(TZ).minute
          for r in rows if r["type"] == "obs.presence"}
    dial = by_day(rows, "obs.self_report", "value", {"item": "sleep", "context": "ritual"})
    game = by_day(rows, "obs.play_session", "reaction_ms_median", {"game": "firefly"})
    late = {i: 0.0 for i in range(16)} | {
        i: v * n for (i, v), n in zip(by_day(rows, "obs.screen_activity", "late_night_min").items(),
                                      [sum(1 for r in rows if r["type"] == "obs.screen_activity" and day_index(r) == i)
                                       for i in by_day(rows, "obs.screen_activity", "late_night_min")], strict=True)}

    def corr(a, b):
        keys = sorted(a.keys() & b.keys())
        xs, ys = [a[k] for k in keys], [b[k] for k in keys]
        mx, my = fmean(xs), fmean(ys)
        return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (
            sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** .5

    assert corr(sleep, up) < -.8        # a short night -> a later first visit to the robot
    assert corr(sleep, dial) > .8       # ... and a lower sleep dial that morning
    assert corr(sleep, game) < -.6      # ... and a slower reaction game (it lags a day, so weaker)
    assert corr(late, midpoint) > .8    # minutes on the Mac after midnight are the same night's later sleep
    usual, dip = range(0, 8), DIP
    for series, lower in ((sleep, True), (by_day(rows, "obs.outing", "minutes"), True),
                          (by_day(rows, "obs.drum_session", "tempo_bpm"), True), (game, False),
                          (by_day(rows, "obs.wearable_daily", "resting_hr_bpm"), False)):
        a = fmean(series[i] for i in usual if i in series)
        b = fmean(series[i] for i in dip if i in series)
        assert (b < a) if lower else (b > a)
    # nobody walks forty minutes after sleeping five hours: values stay in a human range
    assert all(300 <= v <= 460 for v in sleep.values()) and all(55 <= v <= 70 for v in
                                                                 by_day(rows, "obs.wearable_daily", "resting_hr_bpm").values())
    assert [r["payload"]["total"] for r in rows if r["type"] == "obs.phq9"] == [5, 11, 8]
    assert [day_index(r) for r in rows if r["type"] == "obs.phq9"] == [1, 11, 15]  # fortnightly + one after the call


# ---------------------------------------------------------------------------------------------- what the rule says
def test_the_real_rule_reaches_the_story_day_by_day(record):
    """Pinned on purpose: if the criteria or the record change, this says which day's reading moved.
    Days 1-10 the baseline is forming; day 11 the first source group is worse (worth a check-in); from day 12
    several agree (needs a call) and stay so; today opens acknowledged, waiting for new recordings."""
    store, exported = record
    days = replay(store)
    assert [r.day for r in days] == [FIRST + timedelta(days=i) for i in range(17)]
    assert [r.state for r in days] == ["watch"] * 11 + ["needs_call"] * 6
    assert all(r.agreement == "low_coverage" and not worse(r) for r in days[:10])
    assert worse(days[10]) == {"laptop"}  # the late nights and missed calls show first
    assert {"robot", "laptop", "wearable"} <= worse(days[11])
    assert all(len(worse(r)) >= 3 for r in days[11:16])
    assert "glasses" not in worse(days[11]) and "glasses" in worse(days[12])  # walks lag by a day
    assert "glasses" not in worse(days[16])  # ... and are back first
    assert days[16].state == "needs_call" and days[16].acknowledged_by == single_person.CARE_BY
    # the call is logged on the day it happened (day 12), not at seed time
    assert all(r.acknowledged_by is None for r in days[:11])
    assert all(r.acknowledged_by == single_person.CARE_BY for r in days[11:])
    assert store.actions("aino")[0]["ts"] == single_person.care_ts(FIRST + timedelta(days=15))
    assert exported["consensus"]["state"] == "needs_call" and not any(
        banned in json.dumps(exported["consensus"]).lower() for banned in ("diagnos", "relapse", "predict"))


@pytest.mark.parametrize(("kind", "state", "worse_sources"), [("good", "watch", set()),
                                                              ("rough", "needs_call", {"robot", "laptop", "wearable"})])
def test_todays_recordings_move_the_reading_either_way(record, kind, state, worse_sources):
    store, _exported = record
    before = replay(store)[-1]
    store.insert_events(single_person.today_events(TODAY, kind))
    after = replay(store)[-1]
    assert after.day == TODAY and after.state == state and worse(after) == worse_sources
    assert len(worse(after)) <= len(worse(before))
    if kind == "good":  # a young record is never called stable: it is "as usual so far"
        assert after.raw == "stable" and after.agreement == "low_coverage"


def test_one_rough_morning_in_the_settled_week_would_not_have_raised_anything(rows):
    store = Store(":memory:")
    store.insert_events([r for r in rows if day_index(r) < 8])
    day8 = FIRST + timedelta(days=8)
    store.insert_events(single_person.today_events(day8, "rough"))
    assert not worse(replay(store, day8, datetime.combine(day8, time(20), TZ))[-1])


# ---------------------------------------------------------------------------------------------- learner and views
def test_what_helps_is_learned_from_coherent_attempts(record, rows):
    store, exported = record
    offers = [r for r in rows if r["type"] == "obs.nudge_offered"]
    outcomes = [r for r in rows if r["type"] == "obs.nudge_outcome"]
    responses = [r for r in rows if r["type"] == "obs.intervention_response"]
    assert len(offers) == 16 and len(outcomes) == 15  # yesterday's offer is answered this morning
    declined = [day_index(r) for r in outcomes if not r["payload"]["accepted"]]
    assert len(declined) == 3 and set(declined) <= set(DIP)  # she said no on the hard days
    for r in responses:
        p = r["payload"]
        assert all(p["delta"][k] == p["post"][k] - p["pre"][k] for k in ("mood", "energy"))
        arm = "daylight_walk" if p["activity"] == "walk" else p["activity"]
        assert any(o["payload"]["arm"] == arm and day_index(o) == day_index(r) and o["ts"] < r["ts"] for o in offers)
    for r in outcomes:
        p = r["payload"]
        assert "reward" not in p  # the learner derives its own score
        if p["accepted"]:
            i = day_index(r)
            assert any(o["payload"]["arm"] == p["arm"] and day_index(o) == i - 1 for o in offers)
            assert (p["next_day"]["mood"], p["next_day"]["energy"]) == single_person.DAYS[i].dial[:2]
    data = service.patient_data(store, "aino", service.active_criteria(store))
    stats = {h["activity"]: h for h in bandit.help_stats(data.nudge_outcomes, data.interventions)}
    assert stats["walk"]["tries"] == 8 and stats["walk"]["mean_effect"] > max(
        stats["drum"]["mean_effect"], stats["breathe"]["mean_effect"])
    helped = [e for e in exported["graph"]["edges"] if e["rel"] == "helped"]
    nodes = {n["id"]: n for n in exported["graph"]["nodes"]}
    assert [nodes[e["dst"]]["label"] for e in helped] == ["walks"]


def test_week_view_reads_as_a_harder_second_week_and_keeps_private_notes_out(record, monkeypatch):
    store, exported = record
    routines = {r["activity"]: r for r in exported["week"]["routines"]}
    assert {"ritual", "walk", "drum", "play", "sleep"} <= routines.keys()
    assert "Emerging pattern" in routines["walk"]["text"]  # sixteen days is not yet an established usual
    graph = exported["graph"]
    assert {n["type"] for n in graph["nodes"]} == {"me", "activity", "routine"}
    private = ("Leena", "Maija", "Eetu", "market hall", "sauna", "buns", "clinic rang")
    care = json.dumps([exported["week"], exported["graph"], exported["consensus"]])
    assert not any(word in care for word in private)
    week.set_sharing(store, "aino", week.CareSharing(share_with_care_team=False))
    assert week.graph(store, Settings(db_path=":memory:"), "aino", "care_team", now=NOW).nodes == []
    for name in ("memories", "episodes", "transcripts"):
        monkeypatch.setattr(store, name, lambda *a, **kw: pytest.fail("care evidence read private records"))
    refs = {r.id: r for r in clinician_chat.evidence(store, Settings(db_path=":memory:"), "aino",
                                                     store.home_summary("aino"), NOW)}
    assert "16 days of collection" in refs["pattern:collection"].detail
    assert "mood 4 of 5 → 3 of 5" in refs["pattern:daily_context"].detail
    assert not any(word in json.dumps([r.model_dump(mode="json") for r in refs.values()]) for word in private)


# ---------------------------------------------------------------------------------------------- seeding an API
@pytest.fixture
def api(tmp_path, monkeypatch):
    client = TestClient(create_app(Settings(db_path=str(tmp_path / "home.sqlite"), demo_mode=True, web_dir=None,
                                            llm="template")))

    @contextmanager
    def connection(**_kwargs):
        yield client

    monkeypatch.setattr(single_person.httpx, "Client", connection)
    return client


def yesterday() -> date:
    return datetime.now(TZ).date() - timedelta(days=1)


@pytest.mark.parametrize("url", ["https://example.com", "http://user:secret@localhost", "http://localhost/?reset=1"])
def test_seeder_refuses_nonlocal_or_ambiguous_origins(url, rows):
    with pytest.raises(ValueError, match="local API origin"):
        single_person.seed(url, rows)


def test_seeding_twice_through_the_real_routes_adds_nothing_the_second_time(api):
    rows = single_person.build(yesterday())
    first = single_person.seed("http://localhost:18061", rows)
    second = single_person.seed("http://localhost:18061", rows)
    assert first["accepted"] == len(rows) and second["accepted"] == 0 and second["duplicates"] == len(rows)
    assert first["state"] == second["state"] == "needs_call"
    assert first["jobs"] == {"nightly-mind": "ok", "weekly": "ok"}
    store = api.app.state.store
    assert len(store.events_for_home("aino")) == len(rows)
    assert len(store.memories("aino")) == len(single_person.NOTES)
    assert len(store.transcripts("aino")) == len(single_person.TALKS) == 5
    assert len(store.episodes("aino")) == len(single_person.episodes(yesterday()))
    assert [(a["action"], a["by"]) for a in store.actions("aino")] == [("acknowledge", single_person.CARE_BY)]
    assert week.sharing(store, "aino").share_with_care_team
    assert api.get("/v1/patients").json()["patients"][0]["display_name"] == "Aino"
    card = api.post("/v1/companion/session", json={"home_id": "aino", "surface": "iphone", "intent": "talk"}).json()
    assert card["context_card"]["first_name"] == "Aino" and "Leena" in json.dumps(card["context_card"])
    # practitioner routes are full on first load and never carry the notebook or the conversations
    for path in ("consensus", "week", "graph", "phq9", "timeline", "brief", "tasks"):
        body = api.get(f"/v1/patients/aino/{path}")
        assert body.status_code == 200 and "Leena" not in body.text and "clinic rang" not in body.text


def test_seeder_refuses_a_record_from_an_earlier_day_until_reset(api):
    single_person.seed("http://localhost:18061", single_person.build(yesterday() - timedelta(days=1)), jobs=False)
    rows = single_person.build(yesterday())
    with pytest.raises(single_person.SeedError, match="make demo-reset"):
        single_person.seed("http://localhost:18061", rows, jobs=False)
    done = single_person.seed("http://localhost:18061", rows, reset=True, jobs=False)
    assert done["accepted"] == len(rows) == len(api.app.state.store.events_for_home("aino"))


def test_live_recordings_change_what_the_practitioner_api_returns(api):
    single_person.seed("http://localhost:18061", single_person.build(yesterday()), jobs=False)
    before = api.get("/v1/patients/aino/consensus").json()
    now = datetime.now(TZ)
    posted = api.post("/v1/events", json={"events": single_person.today_events(now.date(), "good", now=now)}).json()
    assert posted["accepted"] and not posted["rejected"]
    after = api.get("/v1/patients/aino/consensus").json()
    assert before["state"] == "needs_call" and after["state"] == "watch"
    assert not [s for s in after["sources"] if s["verdict"] == "worse"]
    # a later seed keeps today's recordings and does not call them stale
    assert single_person.seed("http://localhost:18061", single_person.build(yesterday()), jobs=False)["accepted"] == 0
