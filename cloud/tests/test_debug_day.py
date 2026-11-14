"""One local day of one home for developers (GET /v1/debug/day): the rule's own numbers for that day, the home's
timezone, conversations without a word of them, a cited read whose every number comes from the data, the cache."""
import json
from datetime import UTC, date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from kaiku_cloud import debug_day, service
from kaiku_cloud.analytics import consensus
from kaiku_cloud.api.main import create_app
from kaiku_cloud.jobs import single_person
from kaiku_cloud.llm import ledger
from kaiku_cloud.llm.errors import LlmUnavailable
from kaiku_cloud.settings import TZ, Settings
from kaiku_cloud.store.db import Store
from kaiku_contracts import budget, make
from kaiku_contracts.api import DebugDay, DebugFact
from kaiku_contracts.config import load_config

END = date(2026, 11, 13)
TODAY = END + timedelta(days=1)
NOW = datetime.combine(TODAY, time(20, 0), TZ)
FLAG_DAY = date(2026, 11, 9)  # the authored record's first "needs a call" day
SETTINGS = Settings(db_path=":memory:", llm="template")


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.fixture
def aino():
    store = Store(":memory:")
    single_person.populate(store, single_person.build(END), END)
    return store


def at(day: date, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm, ss), TZ).astimezone(UTC)


def put(store: Store, kind: str, payload: dict, ts: datetime, source: str = "phone", home: str = "h",
        quality: float | None = None) -> str:
    row = make(kind, payload, source=source, home_id=home, quality=quality, ts=ts).model_dump(mode="json")
    store.insert_events([row])
    return row["id"]


def day_of(store, day=FLAG_DAY, **kw) -> DebugDay:
    return debug_day.build(store, SETTINGS, "aino", day, now=kw.pop("now", NOW), **kw)


def claims(read):
    return [read.summary, *read.moved, *read.missing, *read.tomorrow, *([read.rule_check] if read.rule_check else [])]


# ------------------------------------------------------------------------------------------ shape and the rule's numbers
def test_the_flag_day_shows_the_rules_own_numbers(aino):
    d = day_of(aino)
    DebugDay.model_validate(d.model_dump(mode="json"))
    crit = service.active_criteria(aino)
    data = service.patient_data(aino, "aino", crit, TODAY)
    replayed = consensus.replay(data, crit, FLAG_DAY, d.day_end)
    assert (d.date, d.timezone, d.is_today, d.sim) == (FLAG_DAY, str(TZ), False, True)
    assert (d.consensus.state, d.consensus.raw_state, d.consensus.previous_state) == ("needs_call", "needs_call", "watch")
    assert d.consensus.state == replayed[-1].state and d.consensus.agreement == replayed[-1].agreement
    assert d.consensus.rule_version == crit.rule_version and d.consensus.state_since == FLAG_DAY
    assert "state watch -> needs_call" in d.consensus.changed and "robot: as_usual -> worse" in d.consensus.changed
    assert d.consensus.reasons[0].startswith("3 of 4 signal groups with enough data are worse (robot, laptop, wearable)")
    assert [v.id for v in d.verdicts] == [f"source:{s}" for s in crit.active_sources()]
    assert {v.source: v.verdict for v in d.verdicts} == {v.source: v.verdict for v in replayed[-1].verdicts}
    robot = next(v for v in d.verdicts if v.source == "robot")
    assert robot.worse_weight >= robot.worse_min_weight and robot.previous == "as_usual" and robot.evidence
    assert len(d.metrics) == len([m for m in crit.metrics if m.source in crit.active_sources()])
    mood = next(m for m in d.metrics if m.metric == "mood")
    assert (mood.id, mood.value, mood.baseline.median, mood.z, mood.worse_z) == ("metric:mood", 2.0, 4.0, -4.0, 4.0)
    assert mood.beyond_today and mood.flagged and mood.scored and mood.status == "drifting" and mood.readings == 1
    assert mood.baseline.early and mood.direction == "down" and len(mood.event_ids) == 1
    for m in d.metrics:  # the day's value is the practitioner side's value for that day
        if m.enabled and m.value is not None:
            assert data.series[m.metric][FLAG_DAY] == pytest.approx(m.value), m.metric
        assert m.flagged == (m.scored and m.status == "drifting") and (m.z is None) == (m.worse_z is None)
    force = next(m for m in d.metrics if m.metric == "drum_force")
    assert not force.enabled and not force.scored and not force.flagged  # observe-only: listed, never a vote
    # 22 envelopes of that day plus what the camera counted during its one game, the lantern (obs.face_signs, D52)
    assert [e.ts for e in d.events] == sorted(e.ts for e in d.events) and d.events_total == len(d.events) == 23
    assert [e.type for e in d.events].count("obs.face_signs") == 1
    assert all(d.day_start <= e.ts < d.day_end for e in d.events)
    counted = next(e for e in d.events if e.id == mood.event_ids[0])
    assert counted.type == "obs.self_report" and "mood" in counted.metrics and counted.source == "hub"
    assert d.first_day == data.first_day == END - timedelta(days=single_person.N_DAYS - 1)
    assert all(e.day == FLAG_DAY for e in d.events)
    assert all(v.insufficient_reason is None for v in d.verdicts)  # every group has enough data on that day
    early = day_of(aino, d.first_day)
    assert {v.verdict for v in early.verdicts} == {"insufficient"}
    assert {v.insufficient_reason for v in early.verdicts} <= {"low_confidence", "no_usable_metric"}
    assert day_of(aino, d.first_day - timedelta(days=1)).first_day == d.first_day  # the picker's first day, from any day


def test_the_deterministic_read_is_the_same_shape_and_cites_only_what_exists(aino):
    d = day_of(aino)
    ids = [f.id for f in d.facts]
    assert len(ids) == len(set(ids)) and {"consensus:state", "source:robot", "metric:mood"} <= set(ids)
    assert {f.kind for f in d.facts} == {"consensus", "source", "metric", "missing", "tomorrow", "event"}
    r = d.read
    assert (r.by, r.fallback_reason, r.model, r.cached, r.reading) == ("deterministic", "not_requested", None, False,
                                                                       "clear_shift")
    by_id = {f.id: f for f in d.facts}
    assert r.moved and r.tomorrow and r.rule_check and r.rule_check.cites[0] == "consensus:state"
    for c in claims(r):
        assert set(c.cites) <= set(ids) and debug_day.numbers_ok(c.text, [by_id[i] for i in c.cites]), c.text
    assert "metric:mood" in {i for c in r.moved for i in c.cites}
    assert any(c.cites == ["tomorrow:state"] and "acknowledges" in c.text for c in r.tomorrow)
    assert not any(c.by_code for c in claims(r)) and (r.failed, r.attempts, r.latency_ms, r.est_usd) == (False, 0, None, None)
    early = day_of(aino, date(2026, 11, 1))  # day four: no baseline yet, nothing to compare
    assert early.read.reading == "not_enough_data" and early.read.moved == [] and early.consensus.state == "watch"
    assert all(m.baseline is None and m.z is None for m in early.metrics)
    assert "never stable" in " ".join(early.consensus.reasons)
    quiet = day_of(aino, TODAY)  # nothing recorded today yet
    assert quiet.is_today and quiet.events == [] and quiet.consensus.acknowledged_by == single_person.CARE_BY
    assert {f.id for f in quiet.facts if f.kind == "missing"} >= {"missing:robot", "missing:wearable"}
    before = day_of(aino, date(2026, 10, 1))  # before the record began
    assert before.events == [] and before.consensus.previous_state is None and before.read.reading == "not_enough_data"


def test_every_line_code_writes_passes_the_checks_a_models_line_must_pass(aino):
    first = END - timedelta(days=single_person.N_DAYS - 1)
    for n in range((TODAY - first).days + 1):
        d = day_of(aino, first + timedelta(days=n))
        facts, metrics = {f.id: f for f in d.facts}, {m.id: m for m in d.metrics}
        for f in d.facts:  # a fact ends where a sentence ends: never cut in the middle of an item
            assert f.detail.endswith(".") and not f.detail.rstrip(".").endswith((":", ",", ";")), (d.date, f.id, f.detail[-40:])
        r = d.read
        for section, lines in (("summary", [r.summary]), ("moved", r.moved), ("missing", r.missing),
                               ("tomorrow", r.tomorrow), ("rule_check", [r.rule_check] if r.rule_check else [])):
            for c in lines:
                got = debug_day.check_claim(c.model_dump(), facts, section, metrics)
                assert not isinstance(got, str), (d.date, section, got, c.text)


def test_the_consensus_fact_lists_whole_items_and_states_every_yes_or_no(aino):
    d = day_of(aino)  # the flag day: more than twelve things changed since the day before
    fact = next(f for f in d.facts if f.id == "consensus:state")
    assert len(d.consensus.changed) > 12 and d.consensus.changed[0] == "state watch -> needs_call"
    listed = fact.detail.split("changed since the day before: ")[1].rstrip(".").split("; ")
    assert len(listed) == 13 and listed[12] == f"and {len(d.consensus.changed) - 12} more measures"
    # by label, as a sentence would name them; the keys stay in consensus.changed
    assert listed[:2] == ["state watch -> needs_call", "Check-ins & robot: as_usual -> worse"]
    assert "Mood dial: normal -> drifting" in listed and "mood: normal -> drifting" in d.consensus.changed
    assert "the state is not held by hysteresis; it is not acknowledged; no safety flag is open" in fact.detail
    assert "17 beyond their threshold in the worse direction, 0 in the better" in fact.detail
    assert fact.detail.count("the day itself reads as a clear shift") == 1
    assert fact.flags == {"held": False, "acknowledged": False, "safety": False, "beyond": True, "within": True}
    later = day_of(aino, END)
    fact = next(f for f in later.facts if f.id == "consensus:state")
    assert fact.flags["acknowledged"] and f"it is acknowledged by {single_person.CARE_BY}" in fact.detail
    ahead = next(f for f in later.facts if f.id == "tomorrow:state")
    # an acknowledgement ends the hold (analytics/consensus.py): the fact says what the state does from here
    assert ahead.flags == {"acknowledged": True, "held": False}
    assert ahead.detail == (f"needs_call is acknowledged by {single_person.CARE_BY}, so it is not held: from here the "
                            "state is what the day itself gives. It stays needs_call while 2 groups are worse; 2 are "
                            "worse now. 2 of them could leave worse tomorrow (Check-ins & robot, Watch); the state then "
                            "leaves needs_call.")
    assert next(f for f in d.facts if f.id == "tomorrow:state").detail == (
        "needs_call stays until a clinician acknowledges it or the rule gives stable on 3 days in a row; it is not "
        "acknowledged.")
    assert next(f for f in later.facts if f.id == "source:robot").flags == {"enough_data": True}
    assert next(f for f in later.facts if f.id == "consensus:state").flags["beyond"] is False  # nothing beyond on that day
    assert next(f for f in d.facts if f.id == "metric:mood").flags == {"scored": True, "beyond": True, "within": False}
    assert next(f for f in later.facts if f.id == "metric:mood").flags == {"scored": True, "beyond": False, "within": True}
    unscored = next(m for m in later.metrics if not m.scored and m.value is not None)  # observe-only, with a value
    assert next(f for f in later.facts if f.id == unscored.id).flags["scored"] is False


# ------------------------------------------------------------------------------------------ the day is the home's local day
def test_day_boundaries_are_local_midnights():
    store = Store(":memory:")
    day = date(2026, 11, 10)
    start, end = debug_day.bounds(day)
    assert (start, end) == (datetime(2026, 11, 9, 22, 0, tzinfo=UTC), datetime(2026, 11, 10, 22, 0, tzinfo=UTC))
    assert debug_day.bounds(date(2026, 7, 1))[0] == datetime(2026, 6, 30, 21, 0, tzinfo=UTC)  # summer time
    mood = {"item": "mood", "value": 3, "channel": "phone"}
    first = put(store, "obs.self_report", mood, at(day, 0, 0, 20))           # 22:00:20Z the evening before
    last = put(store, "obs.self_report", mood, at(day, 23, 59, 40))
    put(store, "obs.self_report", mood, at(day - timedelta(days=1), 23, 59, 40))
    after = put(store, "obs.self_report", mood, at(day + timedelta(days=1), 0, 0, 20))
    late = put(store, "obs.wearable_daily", {"date": str(day), "sleep_min": 400, "device": "apple_watch"},
               at(day + timedelta(days=1), 8))                              # the watch reports this day next morning
    d = debug_day.build(store, SETTINGS, "h", day, now=at(day + timedelta(days=2), 12))
    assert [e.id for e in d.events] == [first, last, late] and (d.day_start, d.day_end) == (start, end)
    assert [e.local_time for e in d.events] == ["00:00:20", "23:59:40", "08:00:00"]
    assert next(m for m in d.metrics if m.metric == "mood").readings == 2
    sleep = next(m for m in d.metrics if m.metric == "watch_sleep")
    assert sleep.value == 400 and sleep.event_ids == [late]
    nxt = debug_day.build(store, SETTINGS, "h", day + timedelta(days=1), now=at(day + timedelta(days=2), 12))
    assert [e.id for e in nxt.events] == [after, late]  # stamped that morning, but it measures the day before
    assert next(m for m in nxt.metrics if m.metric == "watch_sleep").value is None
    assert next(e for e in nxt.events if e.id == late).metrics  # and still says which measures it counts toward
    assert [e.day for e in nxt.events] == [day + timedelta(days=1), day] and d.first_day == day - timedelta(days=1)


def test_todays_running_total_is_shown_and_not_compared():
    store = Store(":memory:")
    today = date(2026, 11, 14)
    for n in range(12, 0, -1):
        put(store, "obs.outing", {"minutes": 30, "steps": 3000, "method": "steps"}, at(today - timedelta(days=n), 14))
    put(store, "obs.outing", {"minutes": 4, "steps": 300, "method": "steps"}, at(today, 9))
    d = debug_day.build(store, SETTINGS, "h", None, now=at(today, 10))
    out = next(m for m in d.metrics if m.metric == "outing_min")
    assert d.date == today and d.is_today and (out.value, out.partial, out.z, out.beyond_today) == (4.0, True, None, False)
    assert out.baseline is not None and "running total" in next(f for f in d.facts if f.id == "metric:outing_min").detail
    done = debug_day.build(store, SETTINGS, "h", today, now=at(today + timedelta(days=1), 10))
    out = next(m for m in done.metrics if m.metric == "outing_min")
    assert not out.partial and out.z is not None and out.beyond_today  # the same day, once it is over


# ------------------------------------------------------------------------------------------ conversations: never words
WORDS = ("zebra", "umbrella", "Liisa", "cancelled", "harbour", "marzipan")


def test_conversations_are_enums_and_names_never_words(client):
    home = "h1"
    s = client.post("/v1/companion/session", json={"home_id": home, "surface": "iphone", "intent": "talk",
                                                    "purpose": "talk"}).json()
    sid = s["session_id"]

    def tool(name, **args):
        r = client.post("/v1/companion/tool", json={"home_id": home, "surface": "iphone", "session_id": sid,
                                                    "name": name, "args": args})
        assert r.status_code == 200 and r.json()["ok"], r.text
        return r.json()["result"]

    tool("remember", category="likes", text="She likes marzipan from the harbour", said="I like marzipan from the harbour")
    plan = tool("feel", kind="sad_news", heard={"valence": "low", "energy": "low", "tone": ["tearful"], "via": "voice"},
                about="her sister Liisa cancelled", said="My sister Liisa cancelled the zebra umbrella trip again.")
    put(client.app.state.store, "obs.self_report", {"item": "energy", "value": 3, "channel": "phone"}, datetime.now(UTC), home=home)
    (open_talk,) = client.get("/v1/debug/day", params={"home_id": home}).json()["conversations"]
    assert open_talk["tools"] == ["remember", "feel"] and open_talk["tools_in_order"] is True  # as they were called
    assert open_talk["end"] is None and open_talk["outcome"] is None
    now = datetime.now(UTC)
    r = client.post("/v1/companion/episode", json={
        "home_id": home, "surface": "iphone", "intent": "talk", "id": sid, "start": (now - timedelta(minutes=3)).isoformat(),
        "end": now.isoformat(), "tools_used": ["feel", "remember"], "outcome": "completed",
        "transcript": [{"role": "person", "text": "My sister Liisa cancelled the zebra umbrella trip again."},
                       {"role": "kaiku", "text": "Liisa cancelled. That sounds lonely."}]})
    assert r.status_code == 200 and r.json()["transcript_stored"] is True, r.text
    assert client.post("/v1/events", json={"events": [make("obs.self_report", {"item": "mood", "value": 2, "channel": "phone"},
                                                           source="phone", home_id=home).model_dump(mode="json")]}).status_code == 200
    r = client.get("/v1/debug/day", params={"home_id": home, "generate": False})
    assert r.status_code == 200, r.text
    body = r.json()
    (talk,) = body["conversations"]
    assert (talk["session_id"], talk["surface"], talk["intent"], talk["outcome"]) == (sid, "iphone", "talk", "completed")
    assert talk["tools"] == ["feel", "remember"] and talk["transcript_kept"] is True and talk["end"] is not None
    assert talk["tools_in_order"] is False  # the device's upload: one of each, by name
    (moment,) = talk["feel"]
    assert moment == {"ts": moment["ts"], "kind": "sad_news", "valence": "low", "energy": "low", "tone": ["tearful"],
                      "via": "voice", "stance": plan["stance"], "depth": plan["depth"],
                      "offered": plan.get("may_offer") is not None}
    assert moment["stance"] == "comfort" and moment["depth"] == "stay"
    text = json.dumps(body).lower()
    assert not [w for w in WORDS if w.lower() in text]  # not what was said, what it was about, or what was kept
    assert {c["task"] for c in body["model_calls"]} <= {"feel", "remember", "live_reservation", "reflection_affect"}


# ------------------------------------------------------------------------------------------ the model-call ledger of the day
def test_model_calls_are_this_homes_rows_with_the_spend_estimate_when_one_matches(client):
    store = client.app.state.store
    home = "h1"
    put(store, "obs.self_report", {"item": "mood", "value": 3, "channel": "phone"}, datetime.now(UTC), home=home)
    usd = budget.text_estimate("gemma-4-26b-a4b-it", 3000, 1200)
    budget.charge("gemini", "gemma-4-26b-a4b-it", usd, task="insight_review", component="cloud")
    ledger.record("gemma-4-26b-a4b-it", "insight_review", ok=True, latency_ms=900.0, home_id=home)
    ledger.record("gemma-4-26b-a4b-it", "insight_review", ok=False, latency_ms=50.0, home_id=home)  # no second reservation
    ledger.record("template", "insight_review", ok=True, fallback=True, route="invalid_json", home_id=home)
    ledger.record("gemini-3.8-flash", "ask_mind", ok=True, latency_ms=300.0, home_id="someone-else")
    calls = client.get("/v1/debug/day", params={"home_id": home, "generate": False}).json()["model_calls"]
    assert [(c["provider"], c["model"], c["ok"], c["fallback"], c["route"]) for c in calls] == [
        ("gemma-hosted", "gemma-4-26b-a4b-it", True, False, None), ("gemma-hosted", "gemma-4-26b-a4b-it", False, False, None),
        ("none", "template", True, True, "invalid_json")]
    assert calls[0]["est_usd"] == pytest.approx(usd) and calls[1]["est_usd"] is None and calls[2]["est_usd"] is None
    assert all(c["tokens_in"] is None and c["tokens_out"] is None and c["cache_hit"] is None for c in calls)
    assert debug_day.provider_of("google/gemma-4-26B-A4B-it") == "modal" and debug_day.provider_of("gemini-3.8-live") == "gemini"


# ------------------------------------------------------------------------------------------ the read: every claim checked
FACTS = {f.id: f for f in (
    debug_day._fact("metric:mood", "metric", "Mood dial (1–5)", "2 on this day from 1 reading; usual 4 with spread 0.5; "
                    "4 spreads below usual (z -4), threshold 1.5; 3 of the last 4 scored days."),
    debug_day._fact("metric:watch_sleep", "metric", "Sleep (min)", "322 on this day; usual 428.5 with spread 24.67."),
    debug_day._fact("consensus:state", "consensus", "Consensus", "state needs_call; 3 of 4 signal groups are worse."),
    debug_day._fact("missing:glasses", "missing", "No walks data", "Walks sent nothing; its last day was 2 days before."),
    debug_day._fact("tomorrow:state", "tomorrow", "The state tomorrow", "needs_call stays until acknowledged."))}


@pytest.mark.parametrize("item,section,expected", [
    ({"text": "Mood is 2 against a usual 4, 4 spreads below.", "cites": ["metric:mood"]}, "moved", None),
    ({"text": "Sleep was 322 against a usual of about 430.", "cites": ["metric:watch_sleep"]}, "moved", "number_not_in_data"),
    ({"text": "Sleep was 322 against a usual of about 428.", "cites": ["metric:watch_sleep"]}, "moved", None),  # rounded as written
    ({"text": "Sleep was 322 against a usual of 428.5, spread 24.7.", "cites": ["metric:watch_sleep"]}, "moved", None),
    ({"text": "Mood fell to 7.", "cites": ["metric:mood"]}, "moved", "number_not_in_data"),
    ({"text": "Sleep was 322.", "cites": ["metric:mood"]}, "moved", "number_not_in_data"),  # the number is another fact's
    ({"text": "Mood is 2.", "cites": ["metric:hrv"]}, "moved", "unknown_citation"),
    ({"text": "Mood is 2.", "cites": []}, "moved", "invalid_shape"),
    ({"text": "Mood is 2.", "cites": [*FACTS, "a", "b", "c", "d"]}, "moved", "too_many_cites"),
    ({"text": "Mood is 2.", "cites": [*FACTS, "metric:mood"]}, "moved", None),  # the same id twice is one citation
    ({"text": "The state is needs_call.", "cites": ["consensus:state"]}, "moved", "wrong_section"),
    ({"text": "Walks sent nothing.", "cites": ["metric:mood"]}, "missing", "wrong_section"),
    ({"text": "Walks sent nothing for 2 days.", "cites": ["missing:glasses"]}, "missing", None),
    ({"text": "It stays until acknowledged.", "cites": ["tomorrow:state"]}, "tomorrow", None),
    ({"text": "3 of 4 groups are worse, so needs_call follows.", "cites": ["consensus:state", "metric:mood"]}, "rule_check", None),
    ({"text": "This looks like a relapse.", "cites": ["consensus:state"]}, "rule_check", "wording"),
    ({"text": "Mood 2 proves the walk is effective.", "cites": ["metric:mood"]}, "moved", "overclaim"),
    ({"text": "Overall, mood is 2.", "cites": ["metric:mood"]}, "moved", "filler"),
    ({"text": "x" * 501, "cites": ["metric:mood"]}, "moved", "too_long"),
    ("Mood is 2.", "moved", "invalid_shape"),
])
def test_each_claim_is_checked_by_code(item, section, expected):
    got = debug_day.check_claim(item, FACTS, section)
    assert (got if isinstance(got, str) else None) == expected, got


def test_a_number_must_sit_in_its_own_role_when_a_sentence_is_about_one_measure(aino):
    d = day_of(aino)
    facts, metrics = {f.id: f for f in d.facts}, {m.id: m for m in d.metrics}
    mid = metrics["metric:sleep_midpoint"]  # 300 on the day, usual 181: 119 above, 7.93 spreads above

    def check(text, cites=("metric:sleep_midpoint",)):
        got = debug_day.check_claim({"text": text, "cites": list(cites)}, facts, "moved", metrics)
        return got if isinstance(got, str) else None

    assert (mid.value, mid.baseline.median, mid.z) == (300.0, 181.0, 7.93)
    assert check("Sleep midpoint is 300 against a usual of 181: 119 above, 7.93 spreads above.") is None
    assert check("Sleep midpoint is 119 min above usual, 66% above.") is None
    assert check("Sleep midpoint is 300 above usual 181.") == "number_in_wrong_role"      # the value is not the distance
    assert check("Sleep midpoint is 119 below usual.") == "number_in_wrong_role"          # the wrong side
    assert check("Sleep midpoint is 119 spreads above usual.") == "number_in_wrong_role"  # the distance is not the spreads
    assert check("Mood is 2 against a usual of 4: 2 below, 4 spreads below.", ("metric:mood",)) is None
    assert check("Mood is 4 below usual.", ("metric:mood",)) == "number_in_wrong_role"
    # its own counts, weight, status and side of the threshold (3 of its last 3 scored days, weight 0.5, drifting)
    assert (mid.worse_days, mid.scored_days, mid.weight, mid.status, mid.beyond_today) == (3, 3, 0.5, "drifting", True)
    assert check("Sleep midpoint: beyond its threshold; beyond on 3 of the last 3 scored days (drifting); scored, weight 0.5.") is None
    assert check("Sleep midpoint: beyond on 2 of the last 3 scored days.") == "number_in_wrong_role"
    assert check("Sleep midpoint: beyond on 3 of the last 5 scored days.") == "number_in_wrong_role"
    assert check("Sleep midpoint is scored, weight 1.") == "number_in_wrong_role"
    assert check("Sleep midpoint is 300 (normal).") == "status_mismatch"
    assert check("Sleep midpoint is 300, within its threshold on this day.") == "yes_no_mismatch"
    assert check("Sleep midpoint is observe-only.") == "yes_no_mismatch"
    assert check("Sleep midpoint is not scored.") == "yes_no_mismatch" and check("Sleep midpoint is scored.") is None
    # the fact's own words for the days' count are not a statement about this day
    assert check("First interaction time: beyond its threshold in the worse direction on 2 of the last 3 scored days.",
                 ("metric:getup",)) is None
    calm = next(m for m in d.metrics if m.scored and m.worse_z is not None and abs(m.worse_z) < m.z_threshold)
    assert check("This measure is beyond its threshold.", (calm.id,)) == "yes_no_mismatch"  # within it on this day
    assert check("This measure is not beyond its threshold.", (calm.id,)) is None
    # several measures in one sentence: one of the cited must be on the side the sentence says
    assert check("Sleep midpoint and this measure are beyond their thresholds.", ("metric:sleep_midpoint", calm.id)) is None
    assert check("Both measures are within their thresholds.", ("metric:sleep_midpoint", "metric:mood")) == "yes_no_mismatch"
    assert check(f"It was beyond its threshold on {calm.worse_days} of the last {calm.scored_days} scored days.",
                 (calm.id,)) is None
    getup = metrics["metric:getup"]  # beyond on the day, 2 of 3 days: not a drift yet
    assert (getup.status, getup.worse_days, getup.scored_days) == ("normal", 2, 3)
    assert check("First interaction time is beyond its threshold; beyond on 2 of the last 3 scored days (drifting).",
                 ("metric:getup",)) == "status_mismatch"
    assert check("First interaction time is beyond its threshold; beyond on 2 of the last 3 scored days (normal).",
                 ("metric:getup",)) is None
    lantern = metrics["metric:lantern_speed"]  # its first compared day: counted although one day is too few to say
    assert (lantern.status, lantern.worse_days, lantern.scored_days, lantern.beyond_today) == ("insufficient", 1, 1, True)
    # about two measures at once: the roles cannot be told apart, the numbers still have to exist
    assert check("Mood is 2 below usual and sleep midpoint 119 above.", ("metric:mood", "metric:sleep_midpoint")) is None


def test_what_a_real_read_once_got_wrong_about_the_day_itself(aino):
    d = day_of(aino, END)  # a slight shift: nothing is beyond its threshold on the day, several were on the days before
    facts, metrics = {f.id: f for f in d.facts}, {m.id: m for m in d.metrics}
    moved = ["metric:outing_min", "metric:steps", "metric:getup", "metric:resting_hr", "metric:hrv_sdnn"]
    assert d.read.reading == "slight_shift" and not any(metrics[i].beyond_today for i in moved)

    def check(text, cites, section="summary"):
        got = debug_day.check_claim({"text": text, "cites": list(cites)}, facts, section, metrics, d.read.reading)
        return got if isinstance(got, str) else got.text

    assert check("The day is a slight shift, carried by several measures being beyond their threshold in the worse "
                 "direction.", moved) == "yes_no_mismatch"
    assert check("The day is a slight shift: 0 of 22 scored measures are beyond their threshold.", ["consensus:state"]) \
        == "The day is a slight shift: 0 of 22 scored measures are beyond their threshold."
    assert check("Several measures are beyond their threshold.", ["consensus:state"]) == "yes_no_mismatch"
    assert check("The day is a clear shift.", ["consensus:state"]) == "reading_mismatch"
    # ids and metric keys are for `cites`: a written-in citation is taken out, a bare one is not accepted
    assert check("2 of 4 signal groups with enough data are worse [consensus:state].", ["consensus:state"]) \
        == "2 of 4 signal groups with enough data are worse."
    assert check("The day itself is a slight shift [DAY.reading] (consensus:state).", ["consensus:state"]) \
        == "The day itself is a slight shift."
    assert check("Two groups are worse, as the consensus:state says.", ["consensus:state"]) == "id_in_text"
    assert check("It is carried by outing_min and resting_hr.", moved) == "id_in_text"
    assert check("It is carried by Outing duration and Resting heart rate.", moved) \
        == "It is carried by Outing duration and Resting heart rate."


def test_numbers_must_be_written_in_a_cited_fact():
    mood = [FACTS["metric:mood"]]
    assert FACTS["metric:mood"].numbers == [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]  # every number the fact prints, no other
    assert debug_day.numbers_ok("z -4 on 3 of 4 days, threshold 1.5", mood)
    assert not debug_day.numbers_ok("z -4.2", mood) and not debug_day.numbers_ok("about 40%", mood)
    sleep = [FACTS["metric:watch_sleep"]]
    assert debug_day.numbers_ok("spread 24.7", sleep) and debug_day.numbers_ok("spread 24.67", sleep)
    assert debug_day.numbers_ok("spread 25", sleep)  # rounded to the decimals the sentence writes
    assert not debug_day.numbers_ok("spread 24.6", sleep) and not debug_day.numbers_ok("spread 26", sleep)
    assert isinstance(FACTS["metric:mood"], DebugFact)


def good(d: DebugDay) -> str:
    """A model answer built from the day's own facts (with one made-up number and one unknown id among them)."""
    f = {x.id: x for x in d.facts}
    mood = next(m for m in d.metrics if m.metric == "mood")
    return json.dumps({
        "summary": {"text": "A clear shift on this day: the mood dial and sleep carry it, and the rule gives needs_call.",
                    "cites": ["consensus:state", "metric:mood", "metric:watch_sleep"]},
        "moved": [{"text": f"Mood dial is {debug_day._n(mood.value)} against a usual of {debug_day._n(mood.baseline.median)}.",
                   "cites": ["metric:mood"]},
                  {"text": "Energy fell to 0.123 today.", "cites": ["metric:energy"]},
                  {"text": "Drum tempo is lower.", "cites": ["metric:made_up"]}],
        "missing": [{"text": "No drum tempo on this day.", "cites": ["missing:drum_tempo"]}],
        "tomorrow": [{"text": "The state stays until a clinician acknowledges it.", "cites": ["tomorrow:state"]}],
        "rule_check": {"text": "Three groups are worse, so the state should really be stable.", "cites": ["consensus:state"]},
    }) if f else ""


def moved_of(prompt: str) -> list[str]:
    return json.loads(prompt.split("\nDAY:\n")[1].split("\nFACTS:\n")[0])["moved"]


def whole(prompt: str) -> str:
    """An answer with nothing to reject: a line for every fact code wants one for, and every part."""
    sent = json.loads(prompt.split("\nFACTS:\n")[1].split("\nYour previous response")[0])
    groups = [f["id"] for f in sent if f["id"].startswith("tomorrow:group_")]
    return json.dumps({
        "summary": {"text": "A clear shift on this day; the rule gives needs_call.", "cites": ["consensus:state"]},
        "moved": [{"text": "This measure is away from its usual.", "cites": [i]} for i in moved_of(prompt)],
        "missing": [],
        "tomorrow": [{"text": "The state stays until a clinician acknowledges it.", "cites": ["tomorrow:state"]},
                     *({"text": "This group's verdict could change.", "cites": [i]} for i in groups)],
        "rule_check": {"text": "The state is not held by hysteresis and not acknowledged.", "cites": ["consensus:state"]}})


def test_a_generated_read_keeps_only_valid_claims_and_never_touches_the_consensus(aino):
    plain = day_of(aino)
    before = aino.home_summary("aino")
    prompts = []

    def gen(prompt, **kw):
        prompts.append((prompt, kw))
        return "```json\n" + good(plain) + "\n```"

    d = day_of(aino, generate=True, gen=gen)
    r = d.read
    assert (r.by, r.fallback_reason, r.cached, r.failed, r.reading) == ("gemma", None, False, False, "clear_shift")
    assert r.model == load_config()["models"]["gemma_hosted"] and r.digest == plain.read.digest
    # two claims failed a check, so the model was asked once more (the same answer here): what was dropped is counted
    # over both attempts, and the measures it gave no valid line for have code's own line, marked
    assert len(prompts) == 2 and r.attempts == 2 and r.latency_ms is not None and r.est_usd is None  # no ledger row in a test
    wanted = moved_of(prompts[0][0])
    assert r.rejected == {"number_not_in_data": 2, "unknown_citation": 2, "moved_left_out": 2 * len(wanted),
                          "tomorrow_left_out": 2}
    # code's six first, in code's order; the model's valid line about another measure follows them
    assert [c.cites for c in r.moved] == [*([i] for i in wanted), ["metric:mood"]] and "metric:mood" not in wanted
    facts = {f.id: f for f in d.facts}
    for c in r.moved:
        assert c.by_code == (c.cites != ["metric:mood"])
        if c.by_code:
            assert c.text.startswith(facts[c.cites[0]].label) and "0.123" not in c.text
    # the same for tomorrow: the state's line is the model's, the group's line it left out is code's
    assert [(c.cites, c.by_code) for c in r.tomorrow] == [(["tomorrow:state"], False), (["tomorrow:group_glasses"], True)]
    assert len(r.missing) == 1 and r.rule_check is not None and not r.summary.by_code
    assert all(set(c.cites) <= set(facts) for c in claims(r))
    assert prompts[0][1] == {"timeout_s": 60.0, "task": "debug_read", "home_id": "aino", "max_output_tokens": 2400}
    prompt = prompts[0][0]
    assert '"reading": "clear_shift"' in prompt and '"id": "metric:mood"' in prompt and "FACTS:" in prompt
    assert wanted[:2] == ["metric:late_night", "metric:sleep_midpoint"] and len(wanted) == 6  # which moved is code's call
    # a group's own line about tomorrow stands for its measures: the model is not sent each of them again
    assert '"id": "tomorrow:group_glasses"' in prompt and '"id": "tomorrow:outing_min"' not in prompt
    assert '"id": "tomorrow:getup"' in prompt and "tomorrow:outing_min" in facts
    assert single_person.CARE_NOTE[:20] not in prompt and "Maija" not in prompt  # no care note, no notebook, no words
    retry = prompts[1][0][len(prompt):]  # what was wrong, as categories and ids, then the standing note from the config
    assert "failed validation (no valid moved item for metric:late_night" in retry
    assert "no valid tomorrow item citing tomorrow:group_glasses" in retry
    assert "number_not_in_data; unknown_citation" in retry and "every yes or no" in retry and "0.123" not in retry
    # whatever the read says about the state, the rule's answer is untouched and nothing was recomputed or saved
    assert (d.consensus.state, d.consensus.raw_state) == (plain.consensus.state, plain.consensus.raw_state) == ("needs_call",) * 2
    assert aino.home_summary("aino") == before and d.metrics == plain.metrics and d.verdicts == plain.verdicts


def test_a_yes_or_no_is_checked_against_the_cited_fact_like_a_number(aino):
    d = day_of(aino)  # the flag day: needs_call by the day itself (not held), not acknowledged, no safety flag
    assert (d.consensus.held, d.consensus.acknowledged_by, d.consensus.safety_since) == (False, None, None)
    facts, metrics = {f.id: f for f in d.facts}, {m.id: m for m in d.metrics}

    def check(text, cites=("consensus:state",), section="rule_check", using=facts):
        got = debug_day.check_claim({"text": text, "cites": list(cites)}, using, section, metrics)
        return got if isinstance(got, str) else None

    assert check("The state is held and not acknowledged.") == "yes_no_mismatch"  # what a real read once said
    assert check("The state is not held and not acknowledged.") is None
    assert check("The state is needs_call, not held by hysteresis, and nobody has acknowledged it.") is None
    assert check("It is neither held nor acknowledged, and no safety flag is open.") is None
    assert check("The state is not held or acknowledged.") is None
    assert check("The state is acknowledged by the clinician.") == "yes_no_mismatch"
    assert check("The state is unacknowledged.") is None and check("There is no acknowledgement yet.") is None
    assert check("A safety flag is open.") == "yes_no_mismatch" and check("No safety flag is open.") is None
    # a condition or a wish states nothing about this day
    assert check("The state stays until it is acknowledged or the rule gives stable on 3 days in a row.") is None
    assert check("Whether the state is held depends on the day before.") is None
    assert check("It is awaiting acknowledgement.") is None
    # the consensus's own three cannot be stated on a fact that does not carry them
    assert check("Mood is 2 and the state is not held.", ("metric:mood",), "moved") == "yes_no_mismatch"
    assert check("It is not acknowledged.", ("tomorrow:state",), "tomorrow") is None
    # what the state does next is said on the state's own fact, never on a group's or a measure's
    assert check("The state could change if this group stays within threshold.", ("tomorrow:group_glasses",),
                 "tomorrow") == "state_not_cited"
    assert check("needs_call could end if it crosses again.", ("tomorrow:getup",), "tomorrow") == "state_not_cited"
    assert check("Walks & outings could turn worse tomorrow.", ("tomorrow:group_glasses",), "tomorrow") is None
    assert check("The state stays, and Walks & outings could turn worse.", ("tomorrow:state", "tomorrow:group_glasses"),
                 "tomorrow") is None
    assert check("It is acknowledged.", ("tomorrow:state",), "tomorrow") == "yes_no_mismatch"
    # a group's enough data, against the group's own fact; a count of some groups states nothing about one
    assert check("Check-ins & robot has enough data and is worse.", ("consensus:state", "source:robot")) is None
    assert check("Check-ins & robot does not have enough data.", ("consensus:state", "source:robot")) == "yes_no_mismatch"
    assert check("Check-ins & robot is insufficient.", ("consensus:state", "source:robot")) == "yes_no_mismatch"
    assert check("3 of 4 signal groups with enough data are worse.") is None
    assert check("Fewer than 2 signal groups have enough data.", ("consensus:state", "source:robot")) is None
    young = day_of(aino, d.first_day)  # every group insufficient on the first day
    yf = {f.id: f for f in young.facts}
    assert yf["source:robot"].flags == {"enough_data": False} and "it does not have enough data" in yf["source:robot"].detail
    assert check("Check-ins & robot has enough data.", ("consensus:state", "source:robot"), using=yf) == "yes_no_mismatch"
    assert check("Check-ins & robot is insufficient: too little data.", ("consensus:state", "source:robot"), using=yf) is None
    # a measure's own status word is not a statement about a group
    lantern = metrics["metric:lantern_speed"]
    assert lantern.status == "insufficient"
    assert check("Lantern response speed has status insufficient; scored, weight 0.5.", ("metric:lantern_speed",), "moved") is None
    # the same day as the rule would describe it if needs_call were only kept from the days before
    crit = service.active_criteria(aino)
    kept = d.consensus.model_copy(update={"held": True, "raw_state": "watch", "acknowledged_by": "R. S."})
    fact = debug_day.consensus_fact(kept, d.metrics, FLAG_DAY, service.patient_data(aino, "aino", crit, TODAY))
    assert fact.flags == {"held": True, "acknowledged": True, "safety": False, "beyond": True, "within": True}
    assert "the state is held by hysteresis; it is acknowledged by R. S.; no safety flag is open" in fact.detail
    hf = {**facts, fact.id: fact}
    assert check("The state is held by hysteresis and acknowledged.", using=hf) is None
    assert check("The state is not held.", using=hf) == "yes_no_mismatch"
    assert check("Nobody has acknowledged it.", using=hf) == "yes_no_mismatch"
    assert debug_day.stated("held, then not held; never a vote") == [("held", True), ("held", False), ("scored", False)]


def test_a_read_whose_moved_lines_all_failed_is_still_gemmas_with_codes_lines_marked(aino):
    seen = []

    def gen(prompt, **kw):
        seen.append(prompt)
        return '{"summary": {"text": "A clear shift.", "cites": ["consensus:state"]}, "moved": []}'

    r = day_of(aino, generate=True, gen=gen).read
    assert (r.by, r.failed, r.attempts, len(seen)) == ("gemma", False, 2, 2) and r.summary.text == "A clear shift."
    assert len(r.moved) == 6 and all(c.by_code for c in r.moved)
    assert r.rejected == {"moved_left_out": 12, "tomorrow_left_out": 4}
    assert [(c.cites, c.by_code) for c in r.tomorrow] == [(["tomorrow:state"], True), (["tomorrow:group_glasses"], True)]
    assert r.rule_check.by_code and r.rule_check.cites[0] == "consensus:state" and "rule_check missing or rejected" in seen[1]
    assert r.rule_check.text.startswith("3 of 4 signal groups with enough data are worse (robot, laptop, wearable)")


def test_a_read_is_cached_by_home_date_rule_version_and_the_days_data(aino):
    calls = []

    def gen(prompt, **kw):
        calls.append(prompt)
        return whole(prompt)

    first = day_of(aino, generate=True, gen=gen)
    again = day_of(aino, generate=True, gen=gen, now=NOW + timedelta(hours=1))
    quiet = day_of(aino, generate=False)
    assert len(calls) == 1 and first.read.by == again.read.by == quiet.read.by == "gemma"
    assert (first.read.attempts, first.read.rejected, [c.by_code for c in first.read.moved]) == (1, {}, [False] * 6)
    assert (first.read.cached, again.read.cached, quiet.read.cached) == (False, True, True)
    assert again.read.digest == first.read.digest and again.read.summary == first.read.summary
    assert again.read.attempts == 1 and again.read.latency_ms == first.read.latency_ms  # the ask's own numbers are kept
    other = day_of(aino, END, generate=False)                      # another date of the same home: its own read
    assert other.read.by == "deterministic" and other.read.digest != first.read.digest
    put(aino, "obs.self_report", {"item": "mood", "value": 1, "channel": "phone"}, at(FLAG_DAY, 21), home="aino")
    changed = day_of(aino, generate=False)                         # the day's data changed: the old read is not shown
    assert changed.read.by == "deterministic" and changed.read.digest != first.read.digest
    soon = day_of(aino, generate=True, gen=gen, now=NOW + timedelta(seconds=20))
    assert (soon.read.by, soon.read.fallback_reason) == ("deterministic", "cooldown") and len(calls) == 1
    later = day_of(aino, generate=True, gen=gen, now=NOW + timedelta(seconds=90))
    assert later.read.by == "gemma" and not later.read.cached and len(calls) == 2
    crit = service.active_criteria(aino)
    edited = crit.model_copy(update={"name": crit.name + "-edited"})
    aino.kv_set(service.OVERRIDE_KEY, {"criteria": edited.model_dump(mode="json"), "updated_at": NOW.isoformat(), "by": "t"})
    ruled = day_of(aino, generate=False)
    assert ruled.consensus.rule_version != first.consensus.rule_version
    assert ruled.read.by == "deterministic" and ruled.read.digest != later.read.digest  # another rule version


@pytest.mark.parametrize("answers,reason,tries,kept", [
    ([LlmUnavailable("gemma_hosted not configured")], "provider_unavailable", 1, False),
    ([LlmUnavailable("gemma_hosted failed: BudgetExceeded: daily budget $4.00 reached")], "over_budget", 1, False),
    (["not json", "{still not"], "invalid_json", 2, True),
    (["not json", LlmUnavailable("gemma_hosted failed: TimeoutError")], "provider_unavailable", 2, False),
    (['{"summary": {"text": "Mood is 77.", "cites": ["metric:mood"]}, "moved": []}'] * 2, "no_valid_claims", 2, True),
    (['{"moved": []}'] * 2, "no_valid_claims", 2, True),
])
def test_without_a_valid_read_code_writes_the_same_shape_and_says_why(aino, answers, reason, tries, kept):
    seen = []

    def gen(prompt, **kw):
        seen.append(prompt)
        out = answers[len(seen) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    d = day_of(aino, generate=True, gen=gen)
    assert (d.read.by, d.read.fallback_reason, d.read.model) == ("deterministic", reason, None) and len(seen) == tries
    assert d.read.moved and d.read.rule_check and d.read.reading == "clear_shift"
    assert (d.read.attempts, d.read.failed, d.read.cached) == (tries, kept, False) and d.read.latency_ms is not None
    if tries == 2:
        assert "failed validation" in seen[1] and d.read.rejected
    stored = aino.kv_get(f"debug-read:aino:{FLAG_DAY}")
    assert (stored is not None) == kept and (stored is None or "read" not in stored)  # never kept as the day's read


def test_a_failed_ask_is_kept_and_not_paid_for_again_until_the_day_changes(aino):
    seen = []

    def gen(prompt, **kw):
        seen.append(prompt)
        return ('{"summary": {"text": "Mood is 77.", "cites": ["metric:mood"]}, "moved": [], '
                '"rule_check": {"text": "The state is held and not acknowledged.", "cites": ["consensus:state"]}}')

    first = day_of(aino, generate=True, gen=gen).read
    assert (first.by, first.fallback_reason, first.failed, first.cached, first.attempts) == (
        "deterministic", "no_valid_claims", True, False, 2)
    assert first.rejected == {"number_not_in_data": 2, "yes_no_mismatch": 2, "moved_left_out": 12,
                              "tomorrow_left_out": 4} and len(seen) == 2
    for generate, when in ((False, NOW + timedelta(minutes=5)), (True, NOW + timedelta(hours=2))):
        again = day_of(aino, generate=generate, gen=gen, now=when).read  # a reload, then another ask: neither calls the model
        assert (again.by, again.fallback_reason, again.failed, again.cached) == ("deterministic", "no_valid_claims", True, True)
        assert (again.rejected, again.attempts, again.latency_ms, again.digest) == (
            first.rejected, 2, first.latency_ms, first.digest)
        assert again.generated_at == first.generated_at and again.moved == first.moved and len(seen) == 2
    put(aino, "obs.self_report", {"item": "mood", "value": 1, "channel": "phone"}, at(FLAG_DAY, 21), home="aino")
    fresh = day_of(aino, generate=False, now=NOW + timedelta(hours=3)).read  # the day's data changed: nothing is held over
    assert (fresh.fallback_reason, fresh.failed, fresh.cached, fresh.rejected) == ("not_requested", False, False, {})
    asked = day_of(aino, generate=True, gen=lambda prompt, **kw: whole(prompt), now=NOW + timedelta(hours=3)).read
    assert (asked.by, asked.failed, asked.attempts) == ("gemma", False, 1)  # and it can be asked again


def test_an_ask_shows_its_own_cost_from_the_spend_ledger(aino):
    usd = budget.text_estimate("gemma-4-26b-a4b-it", 9000, 2400)

    def gen(prompt, **kw):
        budget.charge("gemini", "gemma-4-26b-a4b-it", usd, task=kw["task"], component="cloud")
        budget.charge("gemini", "gemma-4-26b-a4b-it", 0.5, task="insight_review", component="cloud")  # someone else's call
        return whole(prompt)

    r = day_of(aino, generate=True, gen=gen).read
    assert (r.by, r.attempts) == ("gemma", 1) and r.est_usd == pytest.approx(usd) and r.latency_ms >= 0
    assert day_of(aino, generate=False).read.est_usd == pytest.approx(usd)  # kept with the read


def test_the_route_has_no_key_no_model_and_still_answers(client):
    put(client.app.state.store, "obs.self_report", {"item": "mood", "value": 3, "channel": "phone"}, datetime.now(UTC), home="h1")
    body = client.get("/v1/debug/day", params={"home_id": "h1"}).json()  # a plain GET never asks a model
    assert (body["read"]["by"], body["read"]["fallback_reason"], body["read"]["attempts"]) == ("deterministic", "not_requested", 0)
    assert body["is_today"] and body["date"] == str(datetime.now(TZ).date()) and body["events_total"] == 1
    assert body["first_day"] == body["date"] and body["events"][0]["day"] == body["date"]
    asked = client.get("/v1/debug/day", params={"home_id": "h1", "generate": True}).json()["read"]  # no key in tests
    assert (asked["by"], asked["fallback_reason"], asked["failed"]) == ("deterministic", "provider_unavailable", False)
    assert client.get("/v1/debug/day", params={"home_id": "nobody"}).status_code == 404
    tomorrow = str(datetime.now(TZ).date() + timedelta(days=1))
    assert client.get("/v1/debug/day", params={"home_id": "h1", "date": tomorrow}).status_code == 422
    assert client.get("/v1/debug/day", params={"home_id": "h1", "date": "yesterday"}).status_code == 422


# ------------------------------------------------------------------------------------------ who may open it
def test_closed_like_admin_routes_and_open_only_in_a_local_demo(tmp_path):
    def app(name, **kw):
        base = {"db_path": str(tmp_path / f"{name}.sqlite"), "web_dir": None, "home_token": None, "admin_token": None,
                "clinician_token": None, "home_tokens": {}, "demo_mode": False, "llm": "template"}
        c = TestClient(create_app(Settings(**{**base, **kw})))
        put(c.app.state.store, "obs.self_report", {"item": "mood", "value": 3, "channel": "phone"}, datetime.now(UTC), home="a")
        return c

    def get(c, token=None):
        return c.get("/v1/debug/day", params={"home_id": "a", "generate": False},
                     headers={"Authorization": f"Bearer {token}"} if token else {}).status_code

    assert get(app("local-demo", demo_mode=True)) == 200
    roles = app("roles", home_tokens={"a": "person"}, clinician_token="care", admin_token="admin")
    assert [get(roles, t) for t in (None, "person", "care", "admin")] == [401, 403, 403, 200]
    assert get(app("deployed-closed", deployed=True)) == 401
    public = app("deployed-demo", deployed=True, demo_mode=True, admin_token="admin")  # reads are open, this is not
    assert public.get("/v1/patients").status_code == 200
    assert [get(public), get(public, "wrong"), get(public, "admin")] == [401, 401, 200]
    assert get(app("deployed-demo-no-admin", deployed=True, demo_mode=True)) == 401
