"""The week + knowledge graph view (D34): routines, going well / worth a look, sharing gate, wording."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from kaiku_cloud import week
from kaiku_cloud.api.main import create_app
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_cloud.llm.explain import contains_banned
from kaiku_cloud.settings import TZ, Settings

END = date(2026, 11, 13)  # a Friday


def test_source_record_counts_corrected_watch_snapshots_by_measured_day():
    rows = [
        {"type": "obs.wearable_daily", "ts": "2026-11-13T08:00:00Z",
         "payload": {"date": "2026-11-12", "steps": 1000, "sleep_min": 400}},
        {"type": "obs.wearable_daily", "ts": "2026-11-13T09:00:00Z",
         "payload": {"date": "2026-11-12", "steps": 2000, "sleep_min": 420}},
        {"type": "obs.wearable_daily", "ts": "2026-11-13T10:00:00Z",
         "payload": {"date": "2026-11-13", "steps": 3000}},
    ]
    watch = next(s for s in week.source_week(rows, END - timedelta(days=6), END) if s.source == "wearable")
    counts = {c.label: c.value for c in watch.counts}
    assert watch.per_day == [0, 0, 0, 0, 0, 1, 1]
    assert counts["nights of sleep"] == 1 and counts["steps a day"] == 2500


def test_app_checkin_is_attributed_to_shared_checkin_group_without_claiming_outdoors():
    rows = [{"type": "obs.self_report", "ts": "2026-11-13T08:00:00Z", "payload": {"channel": "phone"}},
            {"type": "obs.outing", "ts": "2026-11-13T15:00:00Z", "payload": {"minutes": 12}}]
    by = {s.source: s for s in week.source_week(rows, END - timedelta(days=6), END)}
    assert any(c.label == "weather checks" for c in by["robot"].counts)
    assert not any(c.label == "weather checks" for c in by["laptop"].counts)
    assert not any("outside" in c.label for c in by["glasses"].counts)


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)


# ---------------------------------------------------------------- routines (pure)
def test_daily_weekly_and_slipped_routines():
    occ: dict[str, list[datetime]] = {"ritual": [], "walk": [], "drum": []}
    for i in range(28):
        d = END - timedelta(days=i)
        occ["ritual"].append(at(d, 7, 30 + i % 3))            # every day ~07:31
        if d.weekday() == 1:                                   # Tuesdays
            occ["walk"].append(at(d, 15))
        if i >= 7:                                             # drum every day... until this week
            occ["drum"].append(at(d, 7, 45))
    by = {r.activity: r for r in week.routines(occ, END, "person")}
    assert by["ritual"].cadence == "daily" and by["ritual"].status == "kept" and by["ritual"].usual_time == "07:31"
    assert by["ritual"].day_part == "morning" and by["ritual"].this_week == 7
    assert by["walk"].cadence == "weekly" and by["walk"].weekday == "Tuesday" and by["walk"].status == "kept"
    assert by["drum"].status == "slipped" and by["drum"].this_week == 0


def test_too_few_days_is_not_a_routine_and_sleep_after_midnight_belongs_to_the_evening():
    occ = {"play": [at(END - timedelta(days=10), 20)],
           "sleep": [at(END - timedelta(days=i), 0, 20) for i in range(28)]}
    by = {r.activity: r for r in week.routines(occ, END, "care_team")}
    assert "play" not in by
    assert by["sleep"].usual_time == "00:20" and by["sleep"].status == "kept"


# ---------------------------------------------------------------- API over the seeded cohort
@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    s = Settings(demo_mode=True, db_path=str(tmp_path_factory.mktemp("week") / "t.sqlite"), web_dir=None)
    c = TestClient(create_app(s))
    for p in DEMO_PATIENTS:
        ev = generate(p)
        for i in range(0, len(ev), 400):
            assert c.post("/v1/events", json={"events": ev[i:i + 400]}).status_code == 200
    return c


def remember(c, home, category, text):
    r = c.post("/v1/companion/tool", json={"home_id": home, "surface": "web", "name": "remember",
                                           "args": {"category": category, "text": text}})
    assert r.json()["ok"], r.text


PERSON_FORBIDDEN = re.compile(r"\bz\b|z [+-]|needs a call|needs_call|\bstable\b|consensus|verdict|score|phq|"
                              r"confidence|baseline|worse", re.I)


@pytest.mark.parametrize("p", DEMO_PATIENTS, ids=lambda p: p.home_id)
def test_person_week_is_warm_and_never_states_or_scores(cohort, p):
    w = cohort.get(f"/v1/me/week?home_id={p.home_id}").json()
    assert w["audience"] == "person" and w["by"] == "rule" and w["rule_version"] is None
    texts = [r["text"] for r in w["routines"]] + [i["text"] for i in w["going_well"] + w["worth_a_look"]]
    assert texts, p.home_id
    for t in texts:
        assert not contains_banned(t), t
        assert not PERSON_FORBIDDEN.search(t), t


def test_care_week_for_aino_lists_drift_and_routines(cohort):
    w = cohort.get("/v1/patients/demo-aino/week").json()
    assert w["audience"] == "care_team" and w["rule_version"].startswith("consensus-v1")
    assert any(i["kind"] == "metric" and i["metric"] for i in w["worth_a_look"])
    assert {r["activity"] for r in w["routines"]} >= {"ritual", "walk"}
    assert all(r["basis"] == ["obs"] for r in w["routines"])  # conversations stay out unless shared
    for i in w["going_well"] + w["worth_a_look"]:
        assert not contains_banned(i["text"]), i["text"]


def test_safety_flag_this_week_is_first_for_the_care_team(cohort):
    w = cohort.get("/v1/patients/sim-lauri/week").json()
    assert w["worth_a_look"][0]["kind"] == "safety"
    assert cohort.get("/v1/patients/nobody/week").status_code == 404


def test_care_graph_needs_sharing_and_never_shows_people_or_places(cohort):
    remember(cohort, "sim-eero", "people", "Neighbour Ritva bakes pulla")
    remember(cohort, "sim-eero", "places", "Likes the library on Saturdays")
    remember(cohort, "sim-eero", "what_helps", "A sauna with Maija in Helsinki on Sunday evening helps")
    assert cohort.get("/v1/me/sharing?home_id=sim-eero").json() == {"share_with_care_team": False}  # default off
    off = cohort.get("/v1/patients/sim-eero/graph").json()
    assert off["shared"] is False and off["nodes"] == [] and off["edges"] == []
    assert "Ritva" not in cohort.get("/v1/patients/sim-eero/week").text

    mine = cohort.get("/v1/me/graph?home_id=sim-eero").json()  # the person always sees everything
    assert {"person", "place", "helper", "activity", "routine"} <= {n["type"] for n in mine["nodes"]}
    assert any("Ritva" in n["label"] for n in mine["nodes"])

    assert cohort.put("/v1/me/sharing?home_id=sim-eero", json={"share_with_care_team": True}).json() == \
        {"share_with_care_team": True}
    on = cohort.get("/v1/patients/sim-eero/graph")
    assert all(private not in on.text for private in ("Ritva", "library", "Maija", "Helsinki"))
    g = on.json()
    assert g["shared"] and {"person", "place"} <= set(g["withheld"])
    assert {n["type"] for n in g["nodes"]} <= {"me", "activity", "helper", "routine"}
    assert "helper" in g["withheld"]
    assert not any(n["type"] == "helper" for n in g["nodes"])
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["src"] in ids and e["dst"] in ids for e in g["edges"])
    assert all(n["evidence"] > 0 for n in g["nodes"])
    cohort.put("/v1/me/sharing?home_id=sim-eero", json={"share_with_care_team": False})
    assert cohort.get("/v1/patients/sim-eero/graph").json()["nodes"] == []


def test_graph_links_routines_to_activities_with_evidence(cohort):
    g = cohort.get("/v1/me/graph?home_id=sim-onni").json()
    nodes = {n["id"]: n for n in g["nodes"]}
    of = [e for e in g["edges"] if e["rel"] == "of"]
    assert of and all(nodes[e["src"]]["type"] == "routine" and nodes[e["dst"]]["type"] == "activity" for e in of)
    did = [e for e in g["edges"] if e["rel"] == "did"]
    assert did and all(e["evidence"] > 0 for e in did)


def test_empty_home_has_an_empty_week_and_graph(cohort):
    w = cohort.get("/v1/me/week?home_id=nobody-yet").json()
    assert w["routines"] == [] and w["going_well"] == [] and w["worth_a_look"] == []
    g = cohort.get("/v1/me/graph?home_id=nobody-yet").json()
    assert g["edges"] == [] and len(g["nodes"]) <= 1


def test_week_is_deterministic(cohort):
    a = cohort.get("/v1/patients/demo-aino/week").json()
    b = cohort.get("/v1/patients/demo-aino/week").json()
    a.pop("computed_at"), b.pop("computed_at")
    assert a == b


def test_one_record_shows_what_each_source_added(cohort):
    w = cohort.get("/v1/me/week?home_id=demo-aino").json()
    by = {s["source"]: s for s in w["sources"]}
    assert set(by) == {"robot", "glasses", "laptop", "wearable"}
    assert all(len(s["per_day"]) == 7 and s["days"] == sum(1 for v in s["per_day"] if v) for s in by.values())
    assert any(c["label"] == "morning rituals" for c in by["robot"]["counts"])
    assert any(c["label"] == "outings" for c in by["glasses"]["counts"])
    assert w["next_steps"] == []  # suggested steps are for the care team only
    eero = {s["source"]: s for s in cohort.get("/v1/me/week?home_id=sim-eero").json()["sources"]}
    assert eero["wearable"]["days"] == 0 and eero["wearable"]["counts"] == []  # no watch: nothing invented


@pytest.mark.parametrize("home,first", [("sim-lauri", "Call today."), ("demo-aino", "Worth a check-in call this week."),
                                        ("sim-onni", "No action needed this week.")])
def test_suggested_next_steps_follow_the_state(cohort, home, first):
    steps = cohort.get(f"/v1/patients/{home}/week").json()["next_steps"]
    assert steps[0]["text"] == first
    for s in steps:
        assert not contains_banned(s["text"] + " " + s["why"]), s
    if home == "demo-aino":
        # care-process steps only: nothing a practitioner would read as a treatment recommendation
        assert {s["action"] for s in steps} <= {None, "send_message"}
        assert "Ask about sleep and evenings." in [s["text"] for s in steps]
    assert not any(w in (s["text"] + s["why"]).lower() for s in steps for w in ("icbt", "booster", "referral", "tms"))
