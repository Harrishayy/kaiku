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
        assert not {"force_mean", "cadence_spm", "camera_method", "hr_before_bpm"} & row["payload"].keys()
        # daylight on a walk is not measured (no glasses camera): only the watch's whole-day total exists (D53)
        assert "daylight_min" not in row["payload"] or row["type"] == "obs.wearable_daily"
        if row["type"] == "obs.outing":
            assert row["source"] == "phone" and row["payload"]["method"] == "steps"
        if row["type"] == "obs.screen_activity":
            assert sum(row["payload"]["category_min"].values()) == row["payload"]["active_min"] <= 60
    # every consensus source and the learner are fed
    assert {"obs.self_report", "obs.drum_session", "obs.presence", "obs.speech_features", "obs.outing",
            "obs.screen_activity", "obs.play_session", "obs.wearable_daily", "obs.phq9", "obs.ritual",
            "obs.nudge_offered", "obs.nudge_outcome", "obs.intervention_response"} <= {row["type"] for row in rows}
    assert {r["payload"]["game"] for r in rows if r["type"] == "obs.play_session"} == {
        "firefly", "pebbles", "tell", "breathe", "lantern", "seeds", "watering"}


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
    assert [day_index(r) for r in rows if r["type"] == "obs.phq9"] == [1, 12, 15]  # fortnightly + one the evening of the call


# ---------------------------------------------------------------------------------------------- what the rule says
def test_the_real_rule_reaches_the_story_day_by_day(record):
    """Pinned on purpose: if the criteria or the record change, this says which day's reading moved.
    Days 1-10 the baseline is forming; day 11 the first source group is worse (worth a check-in); on day 12 the
    daily signals alone raise "needs a call", a day BEFORE the care team rings and the questionnaire is taken
    (day 13); the flag then holds, acknowledged, while the measures come back."""
    store, exported = record
    days = replay(store)
    assert [r.day for r in days] == [FIRST + timedelta(days=i) for i in range(17)]
    assert [r.state for r in days] == ["watch"] * 11 + ["needs_call"] * 6
    assert all(r.agreement == "low_coverage" and not worse(r) for r in days[:10])
    assert worse(days[10]) == {"laptop"}  # the late nights and missed calls show first
    assert {"robot", "laptop", "wearable"} <= worse(days[11])
    assert all(len(worse(r)) >= 3 for r in days[11:15]) and worse(days[15]) == {"robot", "wearable"}
    assert "glasses" not in worse(days[11]) and "glasses" in worse(days[12])  # walks lag by a day
    assert "laptop" in worse(days[14]) and "laptop" not in worse(days[15])  # late nights and calls are back first
    assert days[16].state == "needs_call" and days[16].acknowledged_by == single_person.CARE_BY
    # Lead time: the flag is raised on day 12 by the daily signals, with no questionnaire and no call yet.
    assert days[11].state == "needs_call" and days[10].state == "watch" and days[11].acknowledged_by is None
    high = next(r for r in single_person.build(END) if r["type"] == "obs.phq9" and r["payload"]["total"] >= 10)
    assert day_index(high) == 12 and single_person.CARE_DAY == 13  # the call and the PHQ-9 come the day after
    assert all(r.acknowledged_by is None for r in days[:12])
    assert all(r.acknowledged_by == single_person.CARE_BY for r in days[12:])
    assert store.actions("aino")[0]["ts"] == single_person.care_ts(FIRST + timedelta(days=15))
    assert exported["consensus"]["state"] == "needs_call" and not any(
        banned in json.dumps(exported["consensus"]).lower() for banned in ("diagnos", "relapse", "predict"))


@pytest.mark.parametrize(("kind", "state", "worse_sources"), [("good", "watch", set()),
                                                              ("rough", "needs_call", {"robot", "wearable"})])
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
    assert len(declined) == 4 and set(declined) <= set(DIP)  # she said no on the hard days
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
    assert stats["walk"]["tries"] == 7 and stats["walk"]["mean_effect"] > max(
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
    assert "mood 4 of 5 → 2 of 5" in refs["pattern:daily_context"].detail
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
    reflections = sum(len(v) for v in single_person.REFLECTIONS.values())
    assert len(single_person.TALKS) == 5 and len(store.transcripts("aino")) == 5 + reflections == 17
    # How each talk sounded comes from the cloud's own labeller reading the seeded words, never from a hand-set
    # field. Pinned by day of the sixteen: settled, flat on the first late night, low through the dip (one evening
    # she did not want to talk), lighter from the evening of the care call, steady at the end.
    from kaiku_cloud.mind import affect

    first = yesterday() - timedelta(days=15)
    heard = sorted(affect.rows(store, "aino").values(), key=lambda r: r["start"])
    assert all(r["by"] == "rule" for r in heard)  # no model key in tests: the nightly relabel kept the rules
    sequence = [((affect.parse_ts(r["start"]).astimezone(affect.TZ).date() - first).days + 1, affect._part(r["start"]),
                 r["valence"], r["declined"]) for r in heard]
    assert sequence == [
        (1, "evening", "bright", False), (2, "evening", "neutral", False), (3, "evening", "neutral", False),
        (5, "evening", "bright", False), (7, "evening", "neutral", False), (8, "evening", "bright", False),
        (9, "evening", "neutral", False),
        (10, "evening", "low", False), (11, "morning", "low", False), (11, "evening", None, True),
        (12, "morning", "low", False), (13, "morning", "low", False), (13, "evening", "bright", False),
        (14, "evening", "bright", False), (15, "evening", "bright", False), (16, "morning", "bright", False),
        (16, "evening", "neutral", False)]
    themes = {(day, part): r["themes"] for (day, part, _v, _d), r in zip(sequence, heard, strict=True)}
    assert themes[(10, "evening")] == ["sleep", "being alone"] and "sleep" in themes[(12, "morning")]
    assert "being alone" in themes[(13, "morning")] and "friends" in themes[(15, "evening")]
    assert "family" in themes[(16, "morning")]
    insight = api.get("/v1/patients/aino/insight", params={"generate": "false"}).json()
    talk = insight["reflections"]
    assert talk["summary"].startswith("Reflections with Kaiku sounded low in 4 of 4 between ")
    assert "lighter since the evening of" in talk["summary"] and "Themes: sleep, being alone, then " in talk["summary"]
    assert "Did not want to talk on" in talk["summary"] and len(talk["days"]) >= 14
    kinds = [e["kind"] for e in insight["course"]["events"]]
    assert "reflection_low" in kinds and "reflection_lighter" in kinds
    assert "reflections with Kaiku sounded low from" in insight["course"]["summary"]
    dip = {d["date"]: d for d in insight["days"]}
    low_day = dip[str(first + timedelta(days=9))]
    assert "evening reflection low (sleep, being alone)" in low_day["parts"]
    assert any(p.endswith(" usual") for p in low_day["parts"]) and "no walk" in low_day["parts"]
    assert "did not want to talk in the evening" in dip[str(first + timedelta(days=10))]["parts"]
    assert "barely slept" not in json.dumps(insight) and "Leave me be" not in json.dumps(insight)
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


def _invitation(api):
    return api.get("/v1/me/invitation", params={"home_id": "aino"}).json()["invitation"]


def test_a_reset_and_reseed_on_the_same_day_brings_her_open_thread_and_invitation_back(api):
    """A reset deletes her episodes and threads. The re-seed has the same episode ids, so the markers that say
    "this episode already opened its thread" must go with them, and so must the day's answered invitation:
    otherwise the seeded person has nothing left open and no invitation (the lead's database, 2026-11-14)."""
    rows = single_person.build(yesterday())
    single_person.seed("http://localhost:18061", rows, jobs=False)
    first = _invitation(api)
    assert first["kind"] == "talk_about" and first["topic"] == "the long lake loop with Leena on Saturday"
    assert first["text"] == "We left off at the long lake loop with Leena on Saturday. Want to pick it up?"
    assert api.post("/v1/me/invitation/answer", params={"home_id": "aino"},
                    json={"id": first["id"], "answer": "not_now"}).status_code == 200
    assert _invitation(api) is None
    store = api.app.state.store
    other = "episode-thread:aino-elsewhere:some-episode:open"  # a home whose id merely starts the same way
    store.kv_set(other, {"result": 9})
    single_person.seed("http://localhost:18061", rows, reset=True, jobs=False)
    again = _invitation(api)
    assert again is not None and again["topic"] == first["topic"] and again["id"] != first["id"]
    topics = [t["topic"] for t in [store.thread_current("aino", datetime.now(TZ).isoformat())] if t]
    assert topics == ["the long lake loop with Leena on Saturday"] and store.kv_get(other) == {"result": 9}
    single_person.seed("http://localhost:18061", rows, jobs=False)  # seeding again without a reset adds nothing
    assert _invitation(api) == again


# ---------------------------------------------------------------------------------------------- today's path games
MEASURED = ("lantern", "seeds", "watering", "pebbles")
GAME_METRICS = ("lantern_speed", "lantern_variability", "seeds_throughput", "watering_effort", "pebble_span")


def played(rows, game):
    return [r for r in rows if r["type"] == "obs.play_session" and r["payload"]["game"] == game]


def test_measured_games_are_in_the_record_as_the_apps_send_them(rows):
    for game in MEASURED:
        sessions = played(rows, game)
        index = [r["payload"]["session_index"] for r in sessions]
        assert index == list(range(1, len(sessions) + 1)), game           # counted per game, in order
        assert [r["payload"]["warmup"] for r in sessions] == [n <= 3 for n in index], game  # the first three are practice
    for game in ("lantern", "seeds", "watering"):
        for r in played(rows, game):
            p = r["payload"]
            assert (r["source"], p["device"], p["input"], p["valid"]) == ("phone", "phone", "touch", True)
            assert len(p["rt_ms"]) == len(p["trial_codes"]) == p["trials_n"] and "flags" not in p
            assert r["quality"] == round(max(.6, min(1.0, p["valid_n"] / p["trials_n"])), 2)  # GameHistory.quality
    lantern = played(rows, "lantern")
    assert [day_index(r) for r in lantern] == [i for i in range(16) if i != 10]  # every day but the one spent in bed
    for r in lantern:  # the summary is what the trial record gives (LanternGame.session)
        p = r["payload"]
        answered = [x for x, code in zip(p["rt_ms"], p["trial_codes"], strict=True) if code in "hl"]
        assert p["trials_n"] == 24 and p["valid_n"] == len(answered) >= 16
        assert all((code == "l") == (x >= 500) for x, code in zip(p["rt_ms"], p["trial_codes"], strict=True) if code in "hl")
        assert all(x == 0 for x, code in zip(p["rt_ms"], p["trial_codes"], strict=True) if code in "ma")
        assert p["lapses"] == sum(c in "lm" for c in p["trial_codes"]) and p["false_starts"] == p["trial_codes"].count("a")
        assert p["response_speed"] == round(fmean(1000 / x for x in answered), 3)
        assert p["reaction_ms_median"] == sorted(answered)[len(answered) // 2] or len(answered) % 2 == 0
    # the second game of the day comes by the calendar, as on the phone (GameRotation): seed shelf, pebbles, watering
    turn = {"seeds": 0, "watering": 2}
    lantern_days = {day_index(r) for r in lantern}
    for game, slot in turn.items():
        sessions = played(rows, game)
        assert 4 <= len(sessions) <= 6
        for r in sessions:
            assert (FIRST + timedelta(days=day_index(r))).timetuple().tm_yday % 3 == slot and day_index(r) in lantern_days
    seeds = played(rows, "seeds")
    assert all(r["payload"]["throughput_per_min"] == round(r["payload"]["valid_n"] / 1.5, 2) for r in seeds)
    assert all(r["payload"]["hard_choice_ratio"] == r["payload"]["trial_codes"].count("H") / 8 for r in played(rows, "watering"))
    # the first lantern rounds that count come before the short nights, so there is a usual to compare them with
    counted = [day_index(r) for r in lantern if not r["payload"]["warmup"]]
    assert counted[:5] == [3, 4, 5, 6, 7] and max(counted[:5]) < min(DIP)
    speed = {day_index(r): r["payload"]["response_speed"] for r in lantern}
    usual, short = [speed[i] for i in range(3, 8)], [speed[i] for i in DIP if i in speed]
    assert max(short) < min(usual) - .2 and speed[15] > min(usual) - .05  # slower after short nights, back by the end


def test_the_new_games_are_charted_and_decide_nothing(rows):
    """Lantern, seed shelf and watering add measures to Trends and History. The story does not move: with these
    sessions taken out again, the rule gives the same state and the same verdict for every group on every day."""
    with_games, without = Store(":memory:"), Store(":memory:")
    single_person.populate(with_games, rows, END)
    single_person.populate(without, [r for r in rows if not (r["type"] == "obs.play_session"
                                                             and r["payload"]["game"] in ("lantern", "seeds", "watering"))], END)

    def story(store):
        return [(r.day, r.state, r.raw, r.agreement, r.held, r.acknowledged_by, {v.source: v.verdict for v in r.verdicts})
                for r in replay(store)]

    assert story(with_games) == story(without)
    crit = service.active_criteria(with_games)
    data = service.patient_data(with_games, "aino", crit, TODAY)
    assert set(GAME_METRICS) <= data.series.keys() and all(crit.metric(m).enabled for m in GAME_METRICS)
    assert len(data.series["lantern_speed"]) == 12 and len(data.series["pebble_span"]) == 8
    from kaiku_cloud.analytics.drift import drift_for
    seen = set()
    for i in range(17):
        day = FIRST + timedelta(days=i)
        for name in GAME_METRICS:
            status = drift_for(crit.metric(name), data.series[name], day, crit).status
            assert status in ("normal", "insufficient"), (name, day)  # never a vote in this record
            seen.add((name, status))
    assert ("lantern_speed", "normal") in seen                    # the lantern does have a usual and is compared
    assert ("seeds_throughput", "normal") not in seen and ("watering_effort", "normal") not in seen  # too few rounds yet


FACE_METRICS = ("face_range", "face_smiles", "face_blinks", "face_range_chat", "face_smiles_chat")
# Pinned on purpose (D52): the states the real rule reaches on Aino's seventeen days. The camera's numbers are in
# the record now; if a line here ever has to change because of them, face signs have started to decide something.
STORY_STATES = ["watch"] * 11 + ["needs_call"] * 6
STORY_WORSE = {10: {"laptop"}, 15: {"robot", "wearable"}}


def test_face_signs_are_in_the_story_and_decide_nothing(rows):
    """With "Camera during activities" on, every game and phone check-in also has what the camera counted of her
    face: quieter on the low days, back toward her usual after. The rule cannot see any of it: the same state, the
    same verdict, the same confidence and the same evidence for every group on every day with and without those
    records, and under the same rule version."""
    faces = [r for r in rows if r["type"] == "obs.face_signs"]
    assert len(faces) == 57 and all(r["sim"] and r["source"] == "phone" for r in faces)
    assert all(r["quality"] == r["payload"]["coverage"] for r in faces)
    assert {r["payload"]["method"] for r in faces} == {"arkit_blendshapes"}
    assert {r["payload"]["task"] for r in faces} == {"firefly", "pebbles", "lantern", "seeds", "watering", "tell", "check_in"}
    games = {r["id"] for r in rows if r["type"] == "obs.play_session"}
    assert all((r["payload"].get("ref") in games) == (r["payload"]["task"] != "check_in") for r in faces)
    # the authored arc: a quieter face on story days 10-13, half-way back on day 14, her usual on days 15-16
    smiles = by_day([r for r in faces if r["payload"]["task"] != "check_in" and r["payload"]["coverage"] >= .6],
                    "obs.face_signs", "smile_share")
    spread = by_day([r for r in faces if r["payload"]["task"] != "check_in" and r["payload"]["coverage"] >= .6],
                    "obs.face_signs", "expression_range")
    usual = fmean(smiles[i] for i in range(9))
    assert all(smiles[i] < usual * .45 for i in DIP) and usual * .45 < smiles[13] < usual * .8
    assert all(smiles[i] > usual * .8 for i in (14, 15)) and all(spread[i] < spread[0] * .7 for i in DIP)

    with_faces, without = Store(":memory:"), Store(":memory:")
    single_person.populate(with_faces, rows, END)
    single_person.populate(without, [r for r in rows if r["type"] != "obs.face_signs"], END)

    def story(store):
        return [(r.day, r.state, r.raw, r.agreement, r.held, r.acknowledged_by,
                 {v.source: (v.verdict, v.confidence, v.last_data_at, [e.model_dump() for e in v.evidence])
                  for v in r.verdicts}) for r in replay(store)]

    told = story(with_faces)
    assert told == story(without)
    assert [state for _day, state, *_rest in told] == STORY_STATES
    assert all({s for s, v in told[i][6].items() if v[0] == "worse"} == want for i, want in STORY_WORSE.items())
    crit = service.active_criteria(with_faces)
    assert crit.rule_version == service.active_criteria(without).rule_version
    assert service.patient_data(with_faces, "aino", crit, TODAY).source_days == \
        service.patient_data(without, "aino", crit, TODAY).source_days  # no coverage, no freshness from the camera

    # They ARE compared with her own usual, and what the comparison finds is the authored arc.
    data = service.patient_data(with_faces, "aino", crit, TODAY)
    assert set(FACE_METRICS) <= data.series.keys() and not any(crit.metric(m).votes for m in FACE_METRICS)
    from kaiku_cloud import course
    from kaiku_cloud.analytics.drift import drift_for
    away = {name: sorted((d - FIRST).days for _d, _v, p in course.readings(crit.metric(name), data.series[name], crit,
                                                                            FIRST, END)
                         for d in [_d] if p is not None and p.z >= crit.param(crit.metric(name), "z_threshold"))
            for name in ("face_range", "face_smiles", "face_blinks")}
    assert away == {"face_range": [9, 10, 11, 12], "face_smiles": [9, 10, 11, 12], "face_blinks": [9, 10, 11, 12]}
    assert drift_for(crit.metric("face_smiles"), data.series["face_smiles"], FIRST + timedelta(days=12), crit).status == "drifting"
    assert drift_for(crit.metric("face_smiles"), data.series["face_smiles"], END, crit).status == "normal"
    # five check-ins on the phone are too few for a usual: shown as numbers, compared with nothing
    assert len(data.series["face_smiles_chat"]) == 5
    assert drift_for(crit.metric("face_smiles_chat"), data.series["face_smiles_chat"], END, crit).status == "insufficient"
    # the session with too little of her face in view is stored and feeds nothing; the game in which her face was
    # never in view has no face record at all (the apps send nothing when coverage rounds to 0)
    assert all(r["payload"]["coverage"] > 0 for r in faces)
    games_day_3 = {r["payload"]["game"] for r in rows if r["type"] == "obs.play_session" and day_index(r) == 3}
    faces_day_3 = {r["payload"]["task"] for r in faces if day_index(r) == 3}
    assert "firefly" in games_day_3 and "firefly" not in faces_day_3
    # a check-in has no task record to point at; a game's face record points at its obs.play_session
    ids = {r["id"]: r for r in rows}
    assert all("ref" not in r["payload"] for r in faces if r["payload"]["task"] == "check_in")
    assert all(ids[r["payload"]["ref"]]["type"] == "obs.play_session"
               and ids[r["payload"]["ref"]]["payload"]["game"] == r["payload"]["task"]
               for r in faces if r["payload"]["task"] != "check_in")
    thin = next(r for r in faces if 0 < r["payload"]["coverage"] < .6)
    day = FIRST + timedelta(days=day_index(thin))
    same_day = [r["payload"]["smile_share"] for r in faces if day_index(r) == day_index(thin)
                and r["payload"]["task"] != "check_in" and r["payload"]["coverage"] >= .6]
    assert data.series["face_smiles"][day] == pytest.approx(fmean(same_day))


def test_any_face_record_at_all_leaves_every_verdict_alone(rows):
    """Not only the authored ones: face records before the record starts, on days with nothing else, with any
    quality, in bulk. The rule reads none of it."""
    from kaiku_contracts.registry import FACE_EXAMPLES

    def face(day, hour, payload, quality, n):
        stamp = datetime.combine(day, time(hour, n % 60), TZ)
        return validate({"home_id": "aino", "source": "phone", "type": "obs.face_signs", "payload": payload,
                         "sim": True, "quality": quality, "ts": stamp}).model_dump(mode="json", exclude_none=True)

    extra, n = [], 0
    for back in range(-5, 17):  # five days before her first day, through the last
        for payload, quality in ((FACE_EXAMPLES["check_in"], .97), (FACE_EXAMPLES["landmarks"], .5),
                                 (FACE_EXAMPLES["no_face"], 0.0), ({**FACE_EXAMPLES["check_in"], "task": "lantern",
                                                                   "expression_range": 0.0, "smile_share": 0.0}, 1.0)):
            n += 1
            extra.append(face(FIRST + timedelta(days=back), 6 + n % 16, payload, quality, n))
    plain, loaded = Store(":memory:"), Store(":memory:")
    single_person.populate(plain, [r for r in rows if r["type"] != "obs.face_signs"], END)
    single_person.populate(loaded, [*rows, *extra], END)

    def story(store):
        return [(r.day, r.state, r.raw, r.agreement, r.held,
                 {v.source: (v.verdict, v.confidence, [e.model_dump() for e in v.evidence]) for v in r.verdicts})
                for r in replay(store)]

    assert story(loaded) == story(plain)
    crit = service.active_criteria(loaded)
    assert service.patient_data(loaded, "aino", crit, TODAY).first_day == FIRST  # the record still starts with her


def test_another_persons_record_has_the_same_days_and_none_of_ainos_words():
    """`--home harrish`: the sixteen days under his id, his own notebook, and nothing Aino said or named."""
    end = date(2026, 11, 14)
    rows = single_person.build(end, "harrish")
    assert {r["home_id"] for r in rows} == {"harrish"} and all(r["sim"] for r in rows)
    store = Store(":memory:")
    single_person.populate(store, rows, end)
    kept = [m["text"] for m in store.memories("harrish")]
    assert set(kept) == {text for _c, text in single_person.OTHER_NOTES["harrish"]}
    assert any("protein" in k for k in kept) and any("Chips" in k for k in kept)
    assert not any(e.transcript for e in single_person.episodes(end, "harrish"))
    told = json.dumps([store.actions("harrish"), kept])
    assert not any(name in told for name in ("Aino", "Maija", "Leena", "Eetu"))
    with pytest.raises(ValueError):
        single_person.notes_for("someone-else")
