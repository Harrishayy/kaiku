"""The person's own numbers (GET /v1/me/history, D48): the practitioner side's daily values, every device, the
latest sessions one tap away, and nothing the person must not be shown."""
import re
from datetime import UTC, date, datetime, time, timedelta

import pytest
from kaiku_cloud import history, service
from kaiku_cloud.analytics.drift import baseline_of
from kaiku_cloud.jobs import single_person
from kaiku_cloud.settings import TZ
from kaiku_cloud.store.db import Store
from kaiku_contracts import make
from kaiku_contracts.api import HISTORY_GROUPS, PersonHistory
from kaiku_contracts.config import load_config

END = date(2026, 11, 13)
TODAY = END + timedelta(days=1)
NOW = datetime.combine(TODAY, time(20, 0), TZ)

# What the person is never shown (D48): as a field name anywhere in the response, and as a word in any text.
FORBIDDEN_KEY = re.compile(r"state|verdict|consensus|(^|_)z(_|$)|zscore|flag|weight|worse|better|direction|review|"
                           r"finding|safety|phq|item9|confidence|agreement|drift|baseline|threshold|score|risk", re.I)
FORBIDDEN_WORD = re.compile(r"needs.{0,3}call|worth a check|\bstable\b|insufficient|worse|better|drift|improv|declin|"
                            r"relapse|diagnos|z-score|flag|phq|questionnaire answer|safety|consensus|verdict|weight|"
                            r"baseline|\bscore|review|risk|worr", re.I)
STATE_WORDS = {"stable", "watch", "needs_call", "insufficient", "same", "worse", "better"}
# D52: a face number is a movement. No title, unit or label may read a feeling or a judgement into it.
FEELING_WORD = re.compile(r"emotion|mood|feel|sad|happy|happi|unhapp|angry|anger|joy|cheer|gloom|affect|express|"
                          r"flat|blunt|tired|low\b|quiet|withdraw|engag|normal|healthy|good|bad\b", re.I)
NEVER_A_MEASURE = {"obs.phq9", "obs.safety_flag", "obs.engagement", "obs.intervention_response", "obs.nudge_outcome"}
# D53: what an Apple Health summary says of the day BEFORE its date (midnight to midnight), and of the night that
# ended on its date. History puts each on the day it is of.
PREVIOUS_DAY = {"resting_hr", "walking_hr", "hrv_sdnn", "daily_steps", "day_distance", "day_daylight", "exercise_min"}
THE_NIGHT = {"watch_sleep", "deep_sleep", "rem_sleep", "core_sleep", "awake_night", "sleep_midpoint"}


def walk(node, key=""):
    """Every (field name, value) of a JSON document, at any depth."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from walk(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v, key)
    else:
        yield key, node


def assert_numbers_only(body: dict) -> None:
    for key, value in walk(body):
        assert not FORBIDDEN_KEY.search(key), key
        if isinstance(value, str) and key not in ("device", "devices", "id", "home_id"):
            assert value not in STATE_WORDS, (key, value)  # "watch" is a device here, never a state
            assert not FORBIDDEN_WORD.search(value), (key, value)


def measures(h) -> dict:
    body = h if isinstance(h, dict) else h.model_dump(mode="json")
    return {m["key"]: m for g in body["groups"] for m in g["measures"]}


def day_offsets() -> dict[str, timedelta]:
    """Per History measure: how far its day is from the day the rule engine files the same number under (D53)."""
    return {row["key"]: timedelta(days=row.get("day_offset", 0)) for row in load_config()["history"]["measure"]}


def at(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), TZ).astimezone(UTC)


def put(store: Store, kind: str, payload: dict, ts: datetime, source: str = "phone", home: str = "h", sim: bool = False,
        quality: float | None = None) -> str:
    row = make(kind, payload, source=source, home_id=home, quality=quality, sim=sim, ts=ts).model_dump(mode="json")
    store.insert_events([row])
    return row["id"]


@pytest.fixture(scope="module")
def aino():
    store = Store(":memory:")
    single_person.populate(store, single_person.build(END), END)
    return store


# ------------------------------------------------------------------------------------------ the seeded sixteen days
def test_seeded_record_has_every_group_in_order_with_robot_days(aino):
    h = history.build(aino, "aino", 30, now=NOW)
    assert [g.key for g in h.groups] == list(HISTORY_GROUPS)
    assert (h.first_day, h.last_day, h.days, h.timezone, h.sim) == (TODAY - timedelta(days=29), TODAY, 30, str(TZ), True)
    m = measures(h)
    robot = [x["key"] for x in h.model_dump(mode="json")["groups"][0]["measures"]]
    assert robot == ["drum_tempo", "drum_taps", "drum_regularity", "drum_duration", "ritual_steps", "getup",
                     "speech_rate", "speech_pauses"]
    assert all(m[k]["devices"] == ["robot"] for k in robot)
    assert len(m["drum_tempo"]["days"]) == 13 and len(m["ritual_steps"]["days"]) == 15  # no robot on story day 11
    assert len(m["mood"]["days"]) == 16 and m["mood"]["devices"] == ["robot", "phone"]  # the phone check-in that day
    assert m["watch_sleep"]["devices"] == ["watch"] and m["active_min"]["devices"] == ["mac"]
    assert m["getup"]["format"] == "clock" and 6 * 60 < m["getup"]["days"][0]["value"] < 9 * 60
    # nothing the record does not hold: no robot pulse, no room light, no drum force, no glasses readings
    assert not {"hr", "rmssd", "hrv_after", "breath_pace", "light", "drum_force", "cadence", "daylight_min"} & m.keys()
    games = [x["key"] for x in h.model_dump(mode="json")["groups"][1]["measures"]]
    assert games == ["lantern_speed", "lantern_variability", "seeds_throughput", "pebble_span", "watering_effort",
                     "firefly_reaction", "tell_pace", "breathe_time"]
    lantern = m["lantern_speed"]  # every day but the one she stayed in bed; the first three rounds are practice
    assert len(lantern["sessions"]) == 15 and len(lantern["days"]) == 12 and lantern["devices"] == ["phone"]
    assert [s["warmup"] for s in reversed(lantern["sessions"])] == [True] * 3 + [False] * 12
    assert lantern["usual"] is not None and lantern["usual"]["low"] < lantern["days"][-1]["value"] < lantern["usual"]["high"]
    assert m["seeds_throughput"]["usual"] is None and m["watering_effort"]["usual"] is None  # too few counted rounds yet
    for x in m.values():
        assert x["days"] == sorted(x["days"], key=lambda d: d["date"]) and all(d["sessions"] >= 1 for d in x["days"])
        assert [s["ts"] for s in x["sessions"]] == sorted((s["ts"] for s in x["sessions"]), reverse=True)
        assert len(x["sessions"]) <= load_config()["history"]["sessions_per_measure"]


def test_days_are_the_numbers_the_practitioner_side_computes(aino):
    crit = service.active_criteria(aino)
    care = service.patient_data(aino, "aino", crit, today=TODAY).series  # what the timeline and the rule read
    m = measures(history.build(aino, "aino", 30, now=NOW))
    shared = [k for k in m if k in care]
    assert len(shared) >= 22 and {"lantern_speed", "lantern_variability", "seeds_throughput", "watering_effort"} <= set(shared)
    back = day_offsets()
    assert {k for k, v in back.items() if v} == PREVIOUS_DAY  # only the Health summary's totals of the day before
    for key in shared:
        # the same numbers; a total of the day before stands on that day here and on the summary's date over there
        mine = {date.fromisoformat(d["date"]) - back[key]: d["value"] for d in m[key]["days"]}
        assert mine and all(care[key][d] == pytest.approx(v) for d, v in mine.items()), key
        # the only days the practitioner side has and the person does not: days it counts as zero for want of data
        assert all(v == 0 for d, v in care[key].items() if d not in mine), key
        spec = crit.metric(key)
        base = baseline_of(spec, care[key], TODAY, crit)
        assert m[key]["usual"] == (base and {"low": round(max(0.0, base.median - base.scale), 2),
                                             "high": round(base.median + base.scale, 2)}), key


def test_sessions_carry_their_own_numbers_and_practice_rounds_are_marked(aino):
    m = measures(history.build(aino, "aino", 30, now=NOW))
    pebbles = m["pebble_span"]
    assert [s["warmup"] for s in reversed(pebbles["sessions"])] == [True] * 3 + [False] * 8
    assert len(pebbles["days"]) == 8  # the three practice rounds are listed and left out of the days
    assert {v["key"]: v["value"] for v in pebbles["sessions"][0]["values"]} == {"span_max": 5, "accuracy": .83,
                                                                                "duration_s": 75}
    drum = m["drum_tempo"]["sessions"][0]
    assert drum["device"] == "robot" and drum["warmup"] is None and drum["sim"] is True
    assert [v["key"] for v in drum["values"]] == ["tempo_bpm", "taps", "regularity", "duration_s"]
    assert {s["label"] for s in m["ritual_steps"]["sessions"]} == {"Breathing", "Goodbye"}  # the steps the record has
    hello = m["getup"]["sessions"][0]["values"][0]
    assert hello["format"] == "clock" and hello["value"] == m["getup"]["days"][-1]["value"]
    assert m["drum_taps"]["per_day"] == "total" and m["drum_taps"]["days"][3]["sessions"] == 2  # two sessions that day


def test_the_usual_range_does_not_depend_on_the_window_asked_for(aino):
    week, month = (measures(history.build(aino, "aino", n, now=NOW)) for n in (7, 30))
    assert week.keys() <= month.keys() and len(week["drum_tempo"]["days"]) == 3
    for key in week:
        assert week[key]["usual"] == month[key]["usual"], key
        assert week[key]["usual"] is None or set(week[key]["usual"]) == {"low", "high"}
    assert week["drum_taps"]["usual"] is not None  # a reading no metric scores has its usual range too


# ---------------------------------------------------------------------------------------------- reading rules
def test_real_envelope_source_decides_the_device():
    def event(kind, source, **payload):
        return {"type": kind, "source": source, "payload": payload}

    assert {history.device_of(event("obs.drum_session", s)) for s in ("head", "sensors", "hub")} == {"robot"}
    assert history.device_of(event("obs.outing", "glasses")) == "glasses"
    assert history.device_of(event("obs.screen_activity", "laptop")) == "mac"
    assert history.device_of(event("obs.wearable_daily", "phone", device="apple_watch")) == "watch"
    assert history.device_of(event("obs.wearable_daily", "phone", device="phone_only")) == "phone"
    assert history.device_of(event("obs.play_session", "laptop", device="web")) == "web"
    assert history.device_of(event("obs.self_report", "glasses", channel="glasses_voice")) == "glasses"
    assert history.device_of(event("obs.self_report", "hub", channel="robot")) == "robot"


def test_only_measures_with_data_in_the_window_and_real_readings_are_not_called_simulated():
    store = Store(":memory:")
    put(store, "obs.hrv_session", {"hr_bpm": 64, "rmssd_pre_ms": 30, "rmssd_post_ms": 41, "breath_bpm": 6,
                                   "duration_s": 90, "beats": 92}, at(TODAY, 8), source="sensors", quality=.9)
    put(store, "obs.light_level", {"lux_est": 180, "window_min": 10}, at(TODAY, 8, 5), source="sensors")
    put(store, "obs.drum_session", {"tempo_bpm": 96, "duration_s": 40, "regularity": .8, "taps": 64, "force_mean": .5},
        at(TODAY - timedelta(days=40), 8), source="head")  # older than the window
    put(store, "obs.outing", {"minutes": 22, "steps": 2100, "cadence_spm": 104, "daylight_min": 15, "method": "dat_imu"},
        at(TODAY, 13), source="glasses", sim=True)
    h = history.build(store, "h", 30, now=NOW)
    m = measures(h)
    assert [g.key for g in h.groups] == ["robot", "walks"] and h.sim is True
    assert set(m) == {"hr", "rmssd", "hrv_after", "breath_pace", "light", "outing_min", "steps", "cadence",
                      "daylight_min"}
    assert m["hr"]["sim"] is False and m["hr"]["devices"] == ["robot"] and m["hr"]["usual"] is None
    assert m["hrv_after"]["days"] == [{"date": str(TODAY), "value": 41.0, "sessions": 1, "sim": False}]
    assert m["cadence"]["sim"] is True and m["cadence"]["devices"] == ["glasses"]
    assert history.build(store, "nobody", 30, now=NOW).groups == []


def test_a_game_with_only_practice_rounds_lists_its_sessions_and_has_no_days_yet():
    store = Store(":memory:")
    for n in (1, 2):
        put(store, "obs.play_session", {"game": "lantern", "device": "phone", "duration_s": 60, "response_speed": 2.6,
                                        "reaction_ms_cv": .2, "trials_n": 24, "valid_n": 24, "session_index": n,
                                        "warmup": True, "valid": True}, at(TODAY - timedelta(days=n), 18), quality=.9)
    lantern = measures(history.build(store, "h", 30, now=NOW))["lantern_speed"]
    assert lantern["days"] == [] and [s["warmup"] for s in lantern["sessions"]] == [True, True]
    assert lantern["devices"] == ["phone"] and lantern["usual"] is None


def test_a_doubtful_reading_is_listed_and_left_out_of_the_day_as_the_rule_leaves_it_out():
    store = Store(":memory:")
    put(store, "obs.drum_session", {"tempo_bpm": 100, "duration_s": 40, "regularity": .8, "taps": 66}, at(TODAY, 8),
        source="head", quality=.9)
    put(store, "obs.drum_session", {"tempo_bpm": 40, "duration_s": 5, "regularity": .2, "taps": 3}, at(TODAY, 9),
        source="head", quality=.2)
    tempo = measures(history.build(store, "h", 30, now=NOW))["drum_tempo"]
    assert tempo["days"] == [{"date": str(TODAY), "value": 100.0, "sessions": 1, "sim": False}]
    assert len(tempo["sessions"]) == 2


# ------------------------------------------------------------------------------------------- what it never carries
def test_config_never_lists_a_questionnaire_or_a_flag_and_camera_numbers_stay_in_their_own_group():
    """D52 opened one door in D48: with her switch on, what the camera counted of her face is hers to see, in the
    `camera` group and nowhere else, as plain names for movements. Never a word for a feeling."""
    cfg = load_config()["history"]
    crit = service.file_criteria()
    names = {m.name: m for m in crit.metrics}
    for row in cfg["measure"]:
        obs = row.get("obs") or names[row["key"]].obs
        assert obs not in NEVER_A_MEASURE, row["key"]
        assert not FORBIDDEN_WORD.search(row["title"] + " " + row.get("unit", "")), row["key"]
        assert (obs == "obs.face_signs") == (row["group"] == "camera"), row["key"]
        assert obs != "obs.face_signs" or not FEELING_WORD.search(row["title"] + " " + row.get("unit", "")), row["key"]
    for obs, fields in cfg["session"].items():
        assert obs not in NEVER_A_MEASURE
        for f in fields:
            assert not re.search(r"item|total", f[0]), f
            assert obs == "obs.face_signs" or not re.search(r"express|face|camera|smil|blink|brow|gaze", f[0]), f
            assert not FORBIDDEN_WORD.search(f[1] + " " + f[2]), f
            assert obs != "obs.face_signs" or not FEELING_WORD.search(f[1] + " " + f[2]), f
    assert cfg["groups"]["camera"] == "Camera during activities"
    assert not FEELING_WORD.search(" ".join(cfg["session_label"]["obs.face_signs"][1].values()))


def test_contract_has_no_field_for_anything_forbidden():
    def names(schema):
        for k, v in schema.items():
            if k == "properties":
                yield from v
            if isinstance(v, dict):
                yield from names(v)

    fields = set(names(PersonHistory.model_json_schema()))
    assert {"groups", "measures", "days", "usual", "sessions", "values"} <= fields
    assert not [f for f in fields if FORBIDDEN_KEY.search(f)]


def test_route_for_a_home_in_needs_a_call_carries_numbers_only(client):
    """The seeded record ends in "needs a call" with PHQ-9s, a care note and a review. None of it is in here, and
    a safety flag on top changes nothing either."""
    end = datetime.now(TZ).date() - timedelta(days=1)
    rows = single_person.build(end)
    single_person.seed("http://127.0.0.1:8000", rows, reset=True, jobs=False, client=client)
    assert client.get("/v1/patients/aino/consensus").json()["state"] == "needs_call"
    assert client.get("/v1/patients/aino/phq9").json()["entries"]

    r = client.get("/v1/me/history", params={"home_id": "aino"})
    assert r.status_code == 200, r.text
    body = r.json()
    PersonHistory.model_validate(body)
    assert body["days"] == 30 and [g["key"] for g in body["groups"]] == list(HISTORY_GROUPS)
    assert_numbers_only(body)
    never = {e["id"] for e in rows if e["type"] in NEVER_A_MEASURE}
    shown = {s["id"] for m in measures(body).values() for s in m["sessions"]}
    assert len(never) > 20 and shown and not shown & never
    # the same numbers the practitioner's timeline has, on the wire
    series = {s["metric"]: s for s in client.get("/v1/patients/aino/timeline", params={"days": 30}).json()["series"]}
    m = measures(body)
    today = str(datetime.now(TZ).date())
    assert len(series.keys() & m.keys()) >= 18
    back = day_offsets()
    for key in series.keys() & m.keys():
        care_days = {p["date"]: p["value"] for p in series[key]["points"] if p["value"] is not None}
        mine = {str(date.fromisoformat(d["date"]) - back[key]): d["value"] for d in m[key]["days"] if d["date"] != today}
        assert mine and all(care_days[d] == pytest.approx(v, abs=1e-3) for d, v in mine.items()), key

    flag = make("obs.safety_flag", {"trigger": "manual", "severity": "high", "handled_locally": True}, source="hub",
                home_id="aino", sim=True, ts=datetime.now(UTC)).model_dump(mode="json")
    assert client.post("/v1/events", json={"events": [flag]}).json()["accepted"] == 1
    assert client.get("/v1/patients/aino/consensus").json()["state"] == "safety"
    flagged = client.get("/v1/me/history", params={"home_id": "aino"}).json()
    assert_numbers_only(flagged)
    assert {k: v for k, v in flagged.items() if k != "generated_at"} == {k: v for k, v in body.items() if k != "generated_at"}


def test_days_bounds_default_and_home_scope(make_client):
    c = make_client(home_tokens={"a": "alpha", "b": "beta"}, clinician_token="care", admin_token="admin")

    def get(token=None, **params):
        return c.get("/v1/me/history", params={"home_id": "a", **params},
                     headers={"Authorization": f"Bearer {token}"} if token else {})

    assert get().status_code == 401
    assert [get(t).status_code for t in ("beta", "care", "admin")] == [403, 403, 403]  # the person's own, only
    assert get("alpha").json()["days"] == 30 and get("alpha", days=90).json()["days"] == 90
    assert [get("alpha", days=n).status_code for n in (0, 91, 365)] == [422, 422, 422]
    empty = get("alpha", days=7).json()
    assert empty["groups"] == [] and empty["sim"] is False
    assert_numbers_only(empty)


# ------------------------------------------------------------------- D53: which day a Health number stands under
SUMMARY = {"sleep_min": 419.0, "sleep_deep_min": 67.0, "sleep_rem_min": 87.0, "sleep_core_min": 265.0,
           "sleep_awake_min": 38.0, "sleep_midpoint_min": 195.0, "resting_hr_bpm": 63.0, "walking_hr_bpm": 100.4,
           "hrv_sdnn_ms": 39.0, "steps": 7200, "distance_km": 4.78, "daylight_min": 59.0, "exercise_min": 32.0,
           "device": "apple_watch"}
NIGHT_FIELDS = ["sleep_min", "sleep_deep_min", "sleep_rem_min", "sleep_core_min", "sleep_awake_min", "sleep_midpoint_min"]
DAY_FIELDS = ["resting_hr_bpm", "walking_hr_bpm", "hrv_sdnn_ms", "steps", "distance_km", "daylight_min", "exercise_min"]


def test_one_health_summary_puts_the_night_on_its_morning_and_the_day_before_on_the_day_before(client):
    """One posted summary, as the iPhone sends it: `date` is the morning. Its sleep is the night that ended that
    morning; its steps, distance, daylight, exercise and heart numbers are the day before's. Her History shows each
    on the day it is of. The practitioner's timeline, which the rule reads, keeps all of them on the summary's date."""
    morning = datetime.now(TZ).date() - timedelta(days=1)
    before = morning - timedelta(days=1)

    def post(hh: int, mm: int, **changed) -> str:
        row = make("obs.wearable_daily", {"date": str(morning), **SUMMARY, **changed}, source="phone", home_id="one",
                   ts=at(morning, hh, mm)).model_dump(mode="json", exclude_none=True)
        assert client.post("/v1/events", json={"events": [row]}).json()["accepted"] == 1
        return row["id"]

    first = post(7, 40)
    rule = client.get("/v1/patients/one/consensus").json()["rule_version"]
    m = measures(client.get("/v1/me/history", params={"home_id": "one"}).json())
    assert set(m) == THE_NIGHT | PREVIOUS_DAY
    for key in THE_NIGHT:
        assert [d["date"] for d in m[key]["days"]] == [str(morning)], key
        (row,) = m[key]["sessions"]  # the summary as it arrived, with the night's numbers only
        assert row["id"] == first and datetime.fromisoformat(row["ts"]) == at(morning, 7, 40), key
        assert [v["key"] for v in row["values"]] == NIGHT_FIELDS, key
    for key in PREVIOUS_DAY:
        assert [(d["date"], d["sessions"]) for d in m[key]["days"]] == [(str(before), 1)], key
        (row,) = m[key]["sessions"]  # the same summary, said of the day it counts: that day's end, that day's numbers
        assert row["id"] == first and [v["key"] for v in row["values"]] == DAY_FIELDS, key
        assert datetime.fromisoformat(row["ts"]).astimezone(TZ) == datetime.combine(before, time(23, 59, 59), TZ), key
    assert m["daily_steps"]["days"][0]["value"] == 7200 and m["day_distance"]["days"][0]["value"] == 4.78
    assert m["watch_sleep"]["days"][0]["value"] == 419 and m["deep_sleep"]["days"][0]["value"] == 67
    # nothing of it stands under today, and no number is listed under a day it is not of
    today = str(datetime.now(TZ).date())
    assert not any(d["date"] == today for x in m.values() for d in x["days"])

    # the practitioner side is unchanged: every number of the summary on the summary's date, one rule version
    series = client.get("/v1/patients/one/timeline", params={"days": 7}).json()["series"]
    dated = {s["metric"]: [p["date"] for p in s["points"] if p["value"] is not None] for s in series}
    for key in (THE_NIGHT | PREVIOUS_DAY) & dated.keys():
        assert dated[key] == [str(morning)], key
    assert {"daily_steps", "resting_hr", "hrv_sdnn", "day_distance", "watch_sleep"} <= dated.keys()

    # the phone sends the morning's summary again when Health has more: the later one is the day's number, and the
    # two rows of that day keep the order they arrived in
    second = post(12, 5, steps=7350, distance_km=4.9)
    m = measures(client.get("/v1/me/history", params={"home_id": "one"}).json())
    steps = m["daily_steps"]
    assert [(d["date"], d["value"], d["sessions"]) for d in steps["days"]] == [(str(before), 7350, 2)]
    assert [r["id"] for r in steps["sessions"]] == [second, first]
    stamps = [datetime.fromisoformat(r["ts"]).astimezone(TZ) for r in steps["sessions"]]
    assert stamps == [datetime.combine(before, time(23, 59, 59), TZ), datetime.combine(before, time(23, 59, 58), TZ)]
    assert [next(v["value"] for v in r["values"] if v["key"] == "steps") for r in steps["sessions"]] == [7350, 7200]
    sleep = m["watch_sleep"]
    assert [(d["date"], d["value"], d["sessions"]) for d in sleep["days"]] == [(str(morning), 419, 2)]
    assert [datetime.fromisoformat(r["ts"]) for r in sleep["sessions"]] == [at(morning, 12, 5), at(morning, 7, 40)]
    assert client.get("/v1/patients/one/consensus").json()["rule_version"] == rule


def test_a_session_row_is_never_cut_short_and_only_health_totals_move_a_day():
    cfg = load_config()["history"]
    most = PersonHistory.model_json_schema()["$defs"]["HistorySession"]["properties"]["values"]["maxItems"]
    assert cfg["session_values"] <= most
    assert all(len(rows) <= cfg["session_values"] for rows in cfg["session"].values())
    moved = {row["key"]: row for row in cfg["measure"] if row.get("day_offset")}
    assert set(moved) == PREVIOUS_DAY and {row["day_offset"] for row in moved.values()} == {-1}
    crit = service.active_criteria(Store(":memory:"))
    reads = {spec.name: (spec.obs, spec.field) for _row, spec in history.specs(crit)}
    assert {reads[k][0] for k in PREVIOUS_DAY} == {"obs.wearable_daily"}
    assert {reads[k][1] for k in PREVIOUS_DAY} == set(DAY_FIELDS) and {reads[k][1] for k in THE_NIGHT} == set(NIGHT_FIELDS)
