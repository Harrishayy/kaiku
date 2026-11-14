"""More of the day from Apple Health (D53): distance walked, time in daylight, walking heart rate, sleep stages and
time awake. Stored with the daily summary, shown to her in History and to the practitioner beside the record,
citable by the review under the same rule as the face signs, and never a vote."""
import json
import re
from datetime import UTC, date, datetime, time, timedelta

import pytest
from kaiku_cloud import clinician_chat, course, debug_day, history, insight, service
from kaiku_cloud.analytics import consensus
from kaiku_cloud.jobs import single_person
from kaiku_cloud.settings import TZ, Settings
from kaiku_cloud.store.db import Store
from kaiku_contracts import make
from kaiku_contracts.api import PersonHistory

END = date(2026, 11, 13)
FIRST = END - timedelta(days=15)
TODAY = END + timedelta(days=1)
NOW = datetime.combine(TODAY, time(20, 0), TZ)
SETTINGS = Settings(db_path=":memory:", llm="template")
NEW = ("distance_km", "daylight_min", "walking_hr_bpm", "sleep_deep_min", "sleep_rem_min", "sleep_core_min",
       "sleep_awake_min")
HEALTH = ("day_distance", "day_daylight", "walking_hr", "deep_sleep", "rem_sleep", "awake_night")
VOTING = ("watch_sleep", "sleep_midpoint", "resting_hr", "hrv_sdnn", "daily_steps")
NOTE = "Shown only: no vote in the consensus."
STATE_WORD = re.compile(r"\b(worse|better|usual|flag|drift|score[ds]?|verdict|state|low|poor|good|bad)\b", re.I)


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.fixture(scope="module")
def rows():
    return single_person.build(END)


@pytest.fixture
def aino(rows):
    store = Store(":memory:")
    single_person.populate(store, rows, END)
    return store


def without_new(rows, extreme=False):
    """The same record with the new fields taken out of every summary (or pushed to their extremes)."""
    wild = {"distance_km": 0.0, "daylight_min": 0.0, "walking_hr_bpm": 200.0, "sleep_deep_min": 0.0,
            "sleep_rem_min": 0.0, "sleep_core_min": 0.0, "sleep_awake_min": 600.0}
    out = []
    for r in rows:
        if r["type"] == "obs.wearable_daily":
            payload = {k: v for k, v in r["payload"].items() if k not in NEW} | (wild if extreme else {})
            r = {**r, "payload": payload}
        out.append(r)
    return out


def story(store):
    crit = service.active_criteria(store)
    replayed = consensus.replay(service.patient_data(store, "aino", crit), crit, TODAY, NOW)
    return [(r.day, r.state, r.raw, r.agreement, r.held, r.acknowledged_by,
             {v.source: (v.verdict, v.confidence, v.last_data_at, [e.model_dump() for e in v.evidence])
              for v in r.verdicts}) for r in replayed]


def insight_of(store, **kw):
    row = service.recompute_home(store, SETTINGS, "aino", TODAY)
    return insight.insight(store, SETTINGS, "aino", row, generate=kw.pop("generate", False), now=NOW, **kw)


# ------------------------------------------------------------------------------------------------- the record
def test_her_days_carry_the_new_fields_and_they_follow_the_days_she_had(rows):
    watch = {(date.fromisoformat(r["payload"]["date"]) - FIRST).days: r["payload"] for r in rows
             if r["type"] == "obs.wearable_daily"}
    assert sorted(set(range(16)) - set(watch)) == [10]  # the day the watch stayed on the charger: nothing from it
    for p in watch.values():
        assert set(NEW) <= set(p) and p["device"] == "apple_watch"
        assert p["sleep_deep_min"] + p["sleep_rem_min"] + p["sleep_core_min"] == p["sleep_min"]  # stages of that night
        assert 0.55 <= p["distance_km"] * 1000 / p["steps"] <= 0.75  # the same walking the steps count
        assert 30 <= p["walking_hr_bpm"] - p["resting_hr_bpm"] <= 44
    usual, hard, back = [watch[i] for i in range(8)], [watch[i] for i in (9, 11, 12)], [watch[i] for i in (14, 15)]
    assert all(p["distance_km"] > 3.8 and p["daylight_min"] >= 30 and p["sleep_deep_min"] > 60
               and p["sleep_awake_min"] < 46 for p in usual)
    assert all(p["distance_km"] < 2.2 and p["daylight_min"] <= 22 and p["sleep_deep_min"] < 46
               and p["sleep_awake_min"] > 52 for p in hard)  # indoors, short broken nights
    assert all(p["distance_km"] > 4.3 and p["daylight_min"] >= 45 and p["sleep_deep_min"] > 60
               and p["sleep_awake_min"] < 50 for p in back)  # back toward her usual at the end
    for kind in ("good", "rough"):
        today = next(r for r in single_person.today_events(TODAY, kind, now=NOW) if r["type"] == "obs.wearable_daily")
        assert set(NEW) <= set(today["payload"])


def test_the_new_fields_decide_nothing_on_any_day(rows):
    """The same daily states, verdicts, confidence, evidence and freshness with the new fields, without them, and
    with every one of them at an extreme; under the same rule version."""
    told = {}
    for name, version in (("with", rows), ("without", without_new(rows)), ("extreme", without_new(rows, extreme=True))):
        store = Store(":memory:")
        single_person.populate(store, version, END)
        crit = service.active_criteria(store)
        told[name] = (story(store), crit.rule_version, service.patient_data(store, "aino", crit, TODAY).source_days)
    assert told["with"] == told["without"] == told["extreme"]
    assert told["with"][1] == "consensus-v1+db93b715"
    assert [state for _day, state, *_rest in told["with"][0]] == ["watch"] * 11 + ["needs_call"] * 6
    plain, full = Store(":memory:"), Store(":memory:")
    single_person.populate(plain, without_new(rows), END)
    single_person.populate(full, rows, END)
    a, b = insight_of(full), insight_of(plain)
    assert a.status_line == b.status_line and (a.course.moved, a.course.back, a.course.low_date, a.course.phase) == \
        (b.course.moved, b.course.back, b.course.low_date, b.course.phase)
    assert a.comparison.improved == b.comparison.improved and a.comparison.changed == b.comparison.changed


# ----------------------------------------------------------------------------------------- the practitioner side
def test_trends_carry_them_marked_as_not_scored(client, rows):
    assert client.post("/v1/events", json={"events": rows}).json()["accepted"] == len(rows)
    series = {s["metric"]: s for s in client.get("/v1/patients/aino/timeline").json()["series"]}
    for name in HEALTH:
        assert series[name]["scored"] is False and series[name]["source"] == "wearable", name
        assert sum(p["value"] is not None for p in series[name]["points"]) >= 13, name
    assert all(series[name]["scored"] is True for name in VOTING)
    assert (series["day_distance"]["unit"], series["deep_sleep"]["unit"], series["walking_hr"]["unit"]) == ("km", "min", "bpm")


def test_the_week_the_course_and_the_graph_tell_them_and_count_only_what_the_verdict_reads(aino):
    out = insight_of(aino)
    watch = next(g for g in out.comparison.groups if g.source == "wearable")
    shown = [m for m in watch.metrics if m.metric in HEALTH]
    assert len(shown) == 6 and all(m.meaning.endswith(NOTE) for m in shown)
    assert "6 more are shown without a vote." in watch.meaning
    assert not {m.metric for m in shown} & {*out.comparison.improved, *out.comparison.changed}
    events = {(e.metric_id, e.kind): e for e in out.course.events if e.metric_id in HEALTH}
    assert events[("deep_sleep", "onset")].text == \
        "Deep sleep first below their usual on 7 Nov: 40 min (usual 1 h 11 min). Shown only: no vote in the consensus."
    assert events[("day_distance", "onset")].text.startswith("Distance walked first below their usual on 7 Nov: 1.61 km")
    assert events[("awake_night", "onset")].text.startswith("Awake in the night first above their usual on 7 Nov")
    assert ("day_daylight", "back_in_range") in events and all(e.text.endswith(NOTE) for e in events.values())
    assert not any(e.metric_id in HEALTH for e in out.course.events if e.kind == "lowest")
    told = re.search(r"Shown, not scored: ([^.]+) were away from their usual", out.course.summary)
    assert told and "distance walked" in told.group(1)
    nodes = {n.id: n for n in out.graph.nodes}
    assert {nodes[f"measure:{m}"].domain for m in ("day_distance", "day_daylight", "walking_hr")} == {"movement"}
    assert {nodes[f"measure:{m}"].domain for m in ("deep_sleep", "rem_sleep", "awake_night")} == {"sleep"}
    labels = {e.dst: e.label for e in out.graph.edges if e.rel == "measures"}
    assert all(labels[f"measure:{m}"].endswith("shown not scored") for m in HEALTH)
    assert "shown" not in labels["measure:daily_steps"]
    assert out.review.by == "template"
    assert not any((r.metric or "") in HEALTH for f in out.review.findings for r in out.evidence if r.id in f.cites)


def test_the_review_is_given_them_as_unscored_and_may_cite_one_only_beside_a_scored_record(aino):
    sent = {}

    def gen(prompt, **_kw):
        context = json.loads(prompt.split("EVIDENCE:\n", 1)[1].split("\nYour previous response")[0])
        sent["context"] = {c["id"]: c for c in context}
        sent["prompt"] = prompt
        return json.dumps({"findings": [
            {"theme": "change", "cites": ["source:wearable", "course:onset:sleep_midpoint", "course:onset:deep_sleep"],
             "meaning": "The middle of the night's sleep moved later first, and deep sleep dropped below their usual "
                        "on the days that followed.",
             "consider": "Ask how the nights were that week."},
            {"theme": "change", "cites": ["course:onset:deep_sleep", "course:onset:awake_night"],
             "meaning": "Deep sleep dropped first and the time awake in the night rose on the same days."},
        ]})

    out = insight_of(aino, generate=True, gen=gen)
    ctx = sent["context"]
    for record in ("course:onset:deep_sleep", "course:onset:day_distance", "course:onset:awake_night"):
        assert ctx[record]["scored"] is False and ctx[record]["sustained"] is False, record
    assert "scored" not in ctx["course:onset:sleep_midpoint"]
    scored_part = [c for c in ctx.values() if c.get("scored") is not False]
    assert 0 < len(ctx) - len(scored_part) <= int(insight.cfg("max_shown_evidence", 8)) and len(scored_part) <= 60
    assert "distance walked, time in daylight, deep sleep" in sent["prompt"]
    kept = [f for f in out.review.findings if f.by == "gemma"]
    assert len(kept) == 1 and "course:onset:deep_sleep" in kept[0].cites
    assert "Deep sleep first below their usual on 7 Nov: 40 min (usual 1 h 11 min). Shown only: no vote in the consensus." \
        in kept[0].facts
    check = next(s for s in out.trace if s.step == "validate")
    assert check.rejected.get("unscored_only") == 1
    assert out.state == "needs_call" and out.rule_version == "consensus-v1+db93b715"


def test_record_chat_states_them_as_shown(aino):
    row = service.recompute_home(aino, SETTINGS, "aino", TODAY)
    refs = {r.id: r for r in clinician_chat.evidence(aino, SETTINGS, "aino", row, now=NOW)}
    deep = refs["metric:deep_sleep"]
    assert deep.label == "Deep sleep (watch) (Watch)" and deep.detail.endswith(NOTE) and deep.unit == "min"
    assert refs["metric:day_distance"].detail.startswith("4.78 km on 13 Nov") and refs["metric:day_distance"].detail.endswith(NOTE)
    assert refs["pattern:day_daylight"].detail.endswith(NOTE)
    assert NOTE not in refs["metric:watch_sleep"].detail and NOTE not in refs["metric:daily_steps"].detail


def test_the_debug_day_lists_them_as_observe_only_and_scored_measures_keep_their_places(aino):
    d = debug_day.build(aino, SETTINGS, "aino", FIRST + timedelta(days=11), now=NOW)  # 9 Nov, a hard day
    mine = {m.metric: m for m in d.metrics if m.metric in HEALTH}
    assert set(mine) == set(HEALTH)
    for m in mine.values():
        assert not m.scored and not m.flagged and m.beyond_today and m.value is not None, m.metric
    facts = {f.id: f for f in d.facts}
    assert facts["metric:deep_sleep"].detail.endswith("observe-only, never a vote.")
    assert facts["metric:deep_sleep"].flags == {"scored": False, "beyond": True, "within": False}
    watch = next(v for v in d.verdicts if v.source == "wearable")
    assert watch.worse_weight == pytest.approx(sum(m.weight for m in d.metrics if m.source == "wearable" and m.scored
                                                   and m.status == "drifting"))
    moved = [i for c in d.read.moved for i in c.cites]
    assert moved and not any(i.removeprefix("metric:") in HEALTH for i in moved)  # scored measures are told first
    summary = next(e for e in d.events if e.type == "obs.wearable_daily")
    assert {"deep_sleep", "day_distance", "watch_sleep"} <= set(summary.metrics)


# ------------------------------------------------------------------------------------------------ her own data
def test_history_shows_them_with_sleep_and_body_in_plain_words_and_readable_formats(aino):
    h = history.build(aino, "aino", days=30, now=NOW)
    body = next(g for g in h.groups if g.key == "sleep_body")
    assert [(m.key, m.title, m.unit, m.format, m.decimals) for m in body.measures] == [
        ("watch_sleep", "Sleep", "", "duration", 0), ("deep_sleep", "Deep sleep", "", "duration", 0),
        ("rem_sleep", "REM sleep", "", "duration", 0), ("core_sleep", "Core sleep", "", "duration", 0),
        ("awake_night", "Awake in the night", "", "duration", 0),
        ("sleep_midpoint", "Middle of the night's sleep", "", "clock", 0),
        ("resting_hr", "Resting heart rate", "bpm", "number", 0), ("walking_hr", "Walking heart rate", "bpm", "number", 0),
        ("hrv_sdnn", "Heart rate variability", "ms", "number", 0), ("daily_steps", "Steps", "steps", "number", 0),
        ("day_distance", "Distance walked", "km", "number", 1), ("day_daylight", "Time in daylight", "", "duration", 0),
        ("exercise_min", "Exercise", "min", "number", 0)]
    m = {x.key: x for x in body.measures}
    for key in ("deep_sleep", "rem_sleep", "core_sleep", "awake_night", "walking_hr", "day_distance", "day_daylight"):
        assert len(m[key].days) == 15 and m[key].devices == ["watch"] and m[key].per_day == "latest", key
        assert m[key].usual is not None and m[key].usual.low < m[key].usual.high, key
        assert m[key].sim and not STATE_WORD.search(m[key].title + " " + m[key].unit), key
    # her days are the practitioner side's numbers. The night stands on the summary's date on both sides; a total
    # of the day before (distance, daylight, walking heart rate) stands on that day here, a day earlier than there
    crit = service.active_criteria(aino)
    series = service.patient_data(aino, "aino", crit, TODAY).series
    one = timedelta(days=1)
    for key in HEALTH:
        back = one if key in ("day_distance", "day_daylight", "walking_hr") else timedelta(0)
        assert {d.date: d.value for d in m[key].days} == {d - back: v for d, v in series[key].items()}, key
    assert [d.value for d in m["deep_sleep"].days[-3:]] == [42.0, 64.0, 67.0]  # minutes on the wire; the app writes 1 h 7 min
    assert (m["deep_sleep"].usual.low, m["deep_sleep"].usual.high) == (61.0, 81.0)  # the same format as the values
    assert (m["deep_sleep"].days[-1].date, m["day_distance"].days[-1].date) == (END, END - one)
    assert m["day_distance"].days[-1].value == 4.78 and m["daily_steps"].days[-1].date == END - one
    # a summary's row lists the numbers of its own day, each ready to read: the night's under the morning ...
    values = {v.key: v for v in m["deep_sleep"].sessions[0].values}
    assert len(values) == 6 and (values["sleep_deep_min"].value, values["sleep_deep_min"].format) == (67.0, "duration")
    assert values["sleep_midpoint_min"].format == "clock" and values["sleep_core_min"].title == "Core sleep"
    # ... and the day before's under the day before, stamped at that day's end
    row = m["day_distance"].sessions[0]
    values = {v.key: v for v in row.values}
    assert len(values) == 7 and row.ts.astimezone(TZ) == datetime.combine(END - one, time(23, 59, 59), TZ)
    assert (values["distance_km"].value, values["distance_km"].unit, values["distance_km"].format) == (4.8, "km", "number")
    assert values["daylight_min"].format == "duration" and values["walking_hr_bpm"].unit == "bpm"
    wire = json.dumps(h.model_dump(mode="json"))
    assert "shown only" not in wire.lower() and "no vote" not in wire.lower() and "consensus" not in wire.lower()
    assert not {"z", "verdict", "direction", "scored", "role", "weight"} & set(
        PersonHistory.model_json_schema()["$defs"]["HistoryMeasure"]["properties"])


def test_shares_of_time_read_as_percent_and_long_minutes_as_duration(aino):
    h = history.build(aino, "aino", days=30, now=NOW)
    every = {m.key: m for g in h.groups for m in g.measures}
    percent = {k for k, m in every.items() if m.format == "percent"}
    duration = {k for k, m in every.items() if m.format == "duration"}
    assert percent == {"speech_pauses", "face_smiles", "face_smiles_chat"}
    assert duration == {"watch_sleep", "deep_sleep", "rem_sleep", "core_sleep", "awake_night", "day_daylight", "active_min"}
    for key in percent:  # the share itself travels (0..1); the unit says what it is a share of
        assert every[key].unit == "of the time" and every[key].decimals == 0
        assert all(0 <= d.value <= 1 for d in every[key].days), key
    smiles = every["face_smiles"]
    assert (smiles.usual.low, smiles.usual.high) == (0.1, 0.18) and round(smiles.days[-1].value, 3) == 0.135
    assert all(every[key].unit == "" for key in duration)
    assert max(d.value for d in every["active_min"].days) > 60 and max(d.value for d in every["watch_sleep"].days) > 400
    # an index that merely runs from 0 to 1 is not a share of time: a number, with a unit a person can read
    assert (every["face_range"].format, every["face_range"].unit) == ("number", "out of 1")
    face = {v.key: v for v in smiles.sessions[0].values}
    assert (face["smile_share"].format, face["smile_share"].unit, face["smile_share"].value) == ("percent", "of the time", 0.14)
    assert face["coverage"].format == "percent" and face["expression_range"].format == "number"
    pauses = {v.key: v for v in every["speech_pauses"].sessions[0].values}
    assert pauses["pause_ratio"].format == "percent" and 0 <= pauses["pause_ratio"].value <= 1


def test_a_phone_without_a_watch_shows_steps_and_distance_and_nothing_it_did_not_measure(client):
    events = []
    for back in range(1, 11):
        day = (datetime.now(UTC) - timedelta(days=back))
        payload = {"date": str(day.astimezone(TZ).date()), "steps": 5000 + 100 * back, "distance_km": 3.3 + back / 10,
                   "device": "phone_only"}
        events.append(make("obs.wearable_daily", payload, source="phone", home_id="solo", sim=True, ts=day)
                      .model_dump(mode="json", exclude_none=True))
    assert client.post("/v1/events", json={"events": events}).json()["accepted"] == 10
    body = next(g for g in client.get("/v1/me/history", params={"home_id": "solo"}).json()["groups"]
                if g["key"] == "sleep_body")
    assert [(m["key"], m["devices"]) for m in body["measures"]] == [("daily_steps", ["phone"]), ("day_distance", ["phone"])]
    series = {s["metric"] for s in client.get("/v1/patients/solo/timeline").json()["series"]
              if any(p["value"] is not None for p in s["points"])}
    assert {"daily_steps", "day_distance"} <= series and not {"deep_sleep", "day_daylight", "walking_hr"} & series


def test_what_is_told_to_the_companion_has_none_of_it(aino):
    from kaiku_cloud.mind import assemble, card

    aino.insert_events(single_person.today_events(TODAY, "rough", now=NOW))
    service.recompute_home(aino, SETTINGS, "aino", TODAY)
    built = card.build_card(aino, SETTINGS, "aino", intent="talk", purpose="talk", now=NOW)
    said = assemble.render_card(card.card_dict(built)).lower()
    for word in ("deep sleep", "rem sleep", "time in daylight", "distance walked", " km", "heart rate",
                 "awake in the night", "sleep stage", "apple health"):
        assert word not in said, word  # ("a short walk in daylight" is a suggestion Kaiku may make; no number is)
    wire = json.dumps(card.card_dict(built)).lower()
    assert not any(key in wire for key in ("distance_km", "daylight_min", "sleep_deep", "sleep_rem", "walking_hr"))
    assert course.SHOWN_NOTE.strip().lower() not in said
