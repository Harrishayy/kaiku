"""The knowledge graph as a map: declared neighbourhoods, what an activity produces, per-day node data and what
changed, checked against the trends band, the course and the daily account for the seeded person."""
import json
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from kaiku_cloud import account, graph_map, week
from kaiku_cloud.api.main import create_app
from kaiku_cloud.clinician_chat import human_value
from kaiku_cloud.course import short
from kaiku_cloud.jobs import single_person
from kaiku_cloud.mind import affect
from kaiku_cloud.settings import TZ, Settings
from kaiku_contracts.api import PatientInsight, TimelineResponse
from kaiku_contracts.companion_tools import MEMORY_CATEGORIES
from kaiku_contracts.criteria import load_criteria
from kaiku_contracts.registry import OBS


# ---------------------------------------------------------------------------------------------- the declaration
def test_every_measure_activity_theme_and_topic_has_one_declared_neighbourhood():
    at = graph_map.atlas()
    assert len(at.domains) == 8 and len({d.place for d in at.domains}) == 8 and len({d.id for d in at.domains}) == 8
    known = {d.id for d in at.domains}
    crit = load_criteria()
    obs_of = {m.name: m.obs for m in crit.metrics}
    for m in crit.metrics:  # disabled ones too: enabling a metric must not leave it without a place
        home = at.measure.get(m.name) or at.obs.get(m.obs, "")
        assert home in known, f"metric {m.name} ({m.obs}) has no neighbourhood in config/kaiku.toml [graph]"
    assert set(week.ACTIVITIES) <= set(at.activity), "an activity without a neighbourhood"
    assert set(affect.THEMES) == set(at.theme), "reflection themes and [graph] themes must be the same list"
    assert {c for c in MEMORY_CATEGORIES if c in ("people", "places", "likes", "helpers", "plans")} <= set(at.topic)
    assert set(at.kind) == {"care_action"}
    assert all(v in known for lookup in (at.activity, at.measure, at.obs, at.theme, at.topic, at.kind) for v in lookup.values())
    # what an activity produces: an activity the cloud knows, and observation types or metric names that exist
    assert set(at.produces) <= set(week.ACTIVITIES)
    for targets in at.produces.values():
        assert targets and all(t in OBS if t.startswith("obs.") else t in obs_of for t in targets)
    assert set(at.about) <= set(affect.THEMES)
    assert all(re.fullmatch(r"(activity|routine|measure):[a-z_]+", t) for targets in at.about.values() for t in targets)


def test_a_malformed_declaration_is_skipped_never_an_error(monkeypatch):
    rows = [{"id": "a", "label": "A", "place": "n", "themes": ["sleep"]}, {"id": "b", "label": "B", "place": "n"},
            {"id": "a", "label": "Again", "place": "s"}, {"label": "no id", "place": "e"}, "nonsense",
            {"id": "c", "label": "C", "place": "nowhere"}]
    monkeypatch.setattr(graph_map, "get", lambda section, key, default=None: {"domain": rows, "produces": "x"}.get(key, default))
    at = graph_map.atlas()
    assert [(d.id, d.place) for d in at.domains] == [("a", "n")] and at.theme == {"sleep": "a"} and at.produces == {}


# ---------------------------------------------------------------------------------------------- the seeded person
def yesterday() -> date:
    return datetime.now(TZ).date() - timedelta(days=1)


@pytest.fixture
def aino(tmp_path, monkeypatch):
    client = TestClient(create_app(Settings(db_path=str(tmp_path / "home.sqlite"), demo_mode=True, web_dir=None,
                                            llm="template")))

    @contextmanager
    def connection(**_kwargs):
        yield client

    monkeypatch.setattr(single_person.httpx, "Client", connection)
    single_person.seed("http://localhost:18061", single_person.build(yesterday()))
    return client


def insight(client) -> PatientInsight:
    r = client.get("/v1/patients/aino/insight", params={"generate": "false"})
    assert r.status_code == 200, r.text
    return PatientInsight.model_validate(r.json())


def test_every_node_has_a_neighbourhood_and_the_declared_links_are_there(aino):
    out = insight(aino)
    g = out.graph
    nodes = {n.id: n for n in g.nodes}
    known = {d.id for d in g.domains}
    assert [d.id for d in g.domains] == [d.id for d in graph_map.atlas().domains]
    for n in g.nodes:
        assert (n.domain == "") == (n.kind in ("person", "signal_group")), n.id
        assert n.domain in known | {""}
    where = {n.id: n.domain for n in g.nodes}
    assert where["measure:mood"] == "mood" and where["measure:sleep"] == "sleep" and where["measure:daily_steps"] == "movement"
    assert where["measure:communication_min"] == "people" and where["measure:late_night"] == "screens"
    assert where["activity:walk"] == where["routine:walk"] == where["talk:outdoors"] == "movement"
    assert where["routine:sleep"] == where["talk:sleep"] == "sleep" and where["topic:people"] == "people"
    assert where["care:0"] == "care" and where["topic:likes"] == "notebook"
    assert all(e.src in nodes and e.dst in nodes for e in g.edges)
    produces = {(e.src, e.dst): e for e in g.edges if e.rel == "produces"}
    # an activity -> the measures a session of it yields: config [graph.produces] + criteria `obs`
    for pair in [("activity:walk", "measure:outing_min"), ("activity:walk", "measure:steps"),
                 ("activity:drum", "measure:drum_tempo"), ("activity:ritual", "measure:mood"),
                 ("activity:ritual", "measure:getup"), ("activity:checkin", "measure:mood"),
                 ("activity:play", "measure:firefly_reaction"), ("routine:sleep", "measure:watch_sleep")]:
        assert pair in produces, pair
    assert ("activity:walk", "measure:daily_steps") not in produces and ("routine:sleep", "measure:daily_steps") not in produces
    crit = load_criteria()
    obs_of = {f"measure:{m.name}": m.obs for m in crit.metrics}
    declared = graph_map.atlas().produces
    for (src, dst), e in produces.items():
        key = src.split(":")[1]
        assert nodes[src].kind in ("activity", "routine") and e.layer == "structure" and e.evidence >= 1
        assert obs_of.get(dst) in declared[key] or dst.split(":")[1] in declared[key] or f"obs.{dst.split(':')[1]}" in declared[key]
        assert re.fullmatch(r"recorded together on \d+ days?", e.label) and len(e.on) <= e.evidence
        # only for days both were recorded
        assert set(e.on) <= {d.date for d in nodes[dst].days}
    about = {(e.src, e.dst) for e in g.edges if e.rel == "about"}
    assert ("talk:outdoors", "activity:walk") in about and ("talk:sleep", "routine:sleep") in about
    # the order of the change: everything that moved on the first day moved first; the rest followed the ones the
    # course summary names, never one picked by the alphabet
    first = [e for e in g.edges if e.rel == "moved_first"]
    onsets = [e for e in out.course.events if e.kind == "onset"]
    day0 = min(e.date for e in onsets)
    assert {e.dst for e in first} == {f"measure:{e.metric_id}" for e in onsets if e.date == day0}
    assert all(e.on == [day0] and e.tag == "first" for e in first)
    followed = [e for e in g.edges if e.rel == "followed"]
    leads = list(dict.fromkeys(e.src for e in followed))
    assert leads == [e.dst for e in first][:3] and 1 <= len(leads) <= 3
    named = out.course.summary.split(" on ")[0].removeprefix("First to move away from their usual: ")
    for lead in leads:
        assert short(nodes[lead].label).lower() in named, (lead, named)
    onset_day = {f"measure:{e.metric_id}": e.date for e in onsets}
    for e in followed:
        gap = (onset_day[e.dst] - day0).days
        assert 1 <= gap <= 3 and e.on == [onset_day[e.dst]] and e.tag == f"+{gap} day{'s' if gap != 1 else ''}"
        assert e.label.endswith("(order, not cause)")
    # every measure that came back within a week of the care action is tied to it, on the day it came back
    back = {f"measure:{e.metric_id}": e.date for e in out.course.events if e.kind == "back_in_range"}
    care_day = next(e.date for e in out.course.events if e.kind == "care_action")
    after = {e.dst: e for e in g.edges if e.rel == "after"}
    assert set(after) == {m for m, d in back.items() if 0 <= (d - care_day).days <= 7} and len(after) >= 12
    assert all(e.on == [back[m]] and nodes[e.src].kind == "care_action" for m, e in after.items())
    together = [e for e in g.edges if e.rel == "moved_together"]
    assert together and all(len(e.on) == e.evidence >= 2 for e in together)
    assert [e.weight for e in together] == sorted((e.weight for e in together), reverse=True), "closest overlaps first"


def test_the_graph_the_trends_band_and_the_daily_account_agree_day_by_day(aino):
    out = insight(aino)
    g = out.graph
    nodes = {n.id: n for n in g.nodes}
    days = {d.date: d for d in g.days}
    assert [d.date for d in g.days] == sorted(days) and len(g.days) == 16 and all(d.recorded for d in g.days)
    assert g.days[-1].date == yesterday(), "the latest day with data closes the scrubber"
    for n in g.nodes:
        assert [d.date for d in n.days] == sorted({d.date for d in n.days}) and {d.date for d in n.days} <= set(days)

    # 1. the trends chart: a measure is "away" on a day exactly when its point is outside the band the chart draws
    #    on the unfavourable side (a value that prints the same as the usual is never away)
    timeline = TimelineResponse.model_validate(aino.get("/v1/patients/aino/timeline", params={"days": 60}).json())
    assert timeline.series
    checked = away_points = 0
    for s in timeline.series:
        node = nodes[f"measure:{s.metric}"]
        tone = {d.date: d for d in node.days}
        for p in s.points:
            if p.value is None or p.date not in days:
                assert p.date not in tone
                continue
            d = tone[p.date]
            assert d.value == human_value(p.value, s.unit), (s.metric, p.date)
            if p.band_low is None:
                assert d.tone == "unknown" and "no personal usual yet" in d.text
                continue
            outside = p.value >= p.band_high if s.worse_when == "up" else p.value <= p.band_low
            same = human_value(p.value, s.unit) == human_value(p.baseline_median, s.unit)
            assert (d.tone == "worse") == (outside and not same), (s.metric, p.date, d, p)
            assert human_value(p.baseline_median, s.unit) in d.text
            checked += 1
            away_points += d.tone == "worse"
    assert checked > 100 and away_points > 40
    for day in g.days:
        assert day.away == sum(1 for n in g.nodes if n.kind == "measure" and any(d.date == day.date and d.tone == "worse" for d in n.days))

    # 2. the daily account: every measure it names as away is away in the graph that day; what the graph has on top
    #    are single days outside the usual (the course does not count them as a spell), each marked as such
    measure_nodes = [n for n in g.nodes if n.id.startswith("measure:")]
    missing = {"no walk": "routine:walk", "morning ritual skipped": "routine:ritual", "no drumming": "routine:drum",
               "no game": "routine:play"}
    assert set(missing) == set(account.MISSING.values())
    assert len(out.days) == 14
    for line in out.days:
        text = " ".join(line.parts)
        more = re.search(r"(\d+) more measures? away from usual", text)
        named = [p for p in line.parts if p.endswith(" usual") and "more measure" not in p]
        by_phrase = {f"{short(n.label).lower()} {side} usual": n for n in measure_nodes
                     for side in ("above", "below", "later than", "earlier than")}
        for phrase in named:
            n = by_phrase[phrase]
            assert next(d for d in n.days if d.date == line.date).tone == "worse", (line.date, phrase)
        counted = len(named) + (int(more.group(1)) if more else 0)
        one_day = [c for c in days[line.date].changes if c.kind == "moved_away" and c.tag == graph_map.ONE_DAY]
        assert days[line.date].away - counted in range(0, len(one_day) + 1), (line.date, days[line.date].away, counted)
        for phrase, rid in missing.items():
            entry = next((d for d in nodes[rid].days if d.date == line.date), None)
            assert (phrase in line.parts) == bool(entry and entry.tone == "worse"), (line.date, phrase)
            assert (phrase in line.parts) == any(c.kind == "missed" and c.node == rid for c in days[line.date].changes)
    assert sum(1 for d in g.days for c in d.changes if c.tag == graph_map.ONE_DAY) >= 1

    # 3. the course: where it dates a first day away, a return or a care action, the graph has that change that day
    changes = {(c.node, d.date): c for d in g.days for c in d.changes if c.kind != "kept"}
    onsets = [e for e in out.course.events if e.kind == "onset"]
    day0 = min(e.date for e in onsets)
    for e in onsets:
        c = changes[(f"measure:{e.metric_id}", e.date)]
        gap = (e.date - day0).days
        assert c.kind == "moved_away"
        assert c.tag == ("first to move" if gap == 0 else f"{gap} day{'s' if gap != 1 else ''} after the first change")
    care_day = next(e.date for e in out.course.events if e.kind == "care_action")
    for e in out.course.events:
        if e.kind == "back_in_range":
            c = changes[(f"measure:{e.metric_id}", e.date)]
            assert c.kind in ("came_back", "better")
            gap = (e.date - care_day).days
            assert c.tag == ("the same day as the care team follow-up" if gap == 0 else
                             f"{gap} day{'s' if gap != 1 else ''} after the care team follow-up")
    assert changes[("care:0", care_day)].kind == "care" and single_person.CARE_BY in changes[("care:0", care_day)].text
    assert [d.date for d in nodes["care:0"].days] == [care_day]
    # the first day a measure can be read against a usual is not announced as a return, and nothing is "new" on day one
    assert not any(c.kind == "first" for c in g.days[0].changes)
    order = list(graph_map.CHANGE_ORDER)
    for d in g.days:
        assert [order.index(c.kind) for c in d.changes] == sorted(order.index(c.kind) for c in d.changes)

    # 4. the consensus is the rule's alone: nothing in the graph states or changes it
    assert out.state == aino.get("/v1/patients/aino/consensus").json()["state"] == "needs_call"
    said = json.dumps(g.model_dump(mode="json")).lower()
    assert not re.search(r"needs[_ ]call|needs a call|worth a check-in|insufficient|diagnos|relapse|predict", said)


def test_routines_themes_and_care_carry_their_days_and_nothing_private_is_added(aino):
    out = insight(aino)
    g = out.graph
    nodes = {n.id: n for n in g.nodes}
    ritual = nodes["routine:ritual"].days
    assert all(re.fullmatch(r"\d\d:\d\d", d.value) and d.tone == "similar" for d in ritual if d.value != "missed")
    assert [d.tone for d in ritual if d.value == "missed"] == ["worse"] and "usually around" in ritual[0].text
    assert all(d.tone == "unknown" and re.fullmatch(r"\d\d:\d\d", d.value) for d in nodes["routine:sleep"].days)
    assert all(d.tone == "unknown" and re.fullmatch(r"\d\d:\d\d", d.value) for d in nodes["activity:walk"].days)
    # a theme: the days it came up, as a count; its node counts the same reflections
    sleep = nodes["talk:sleep"]
    assert sleep.evidence == len(sleep.days) >= 3 and all("came up in" in d.text for d in sleep.days)
    talked = next(e for e in g.edges if e.rel == "talked_about" and e.dst == "talk:sleep")
    assert talked.on == [d.date for d in sleep.days] and talked.label == f"in {sleep.evidence} reflections"
    reflected = {d.date for d in out.reflections.days if "sleep" in d.themes}
    assert reflected <= {d.date for d in sleep.days}
    assert nodes["topic:people"].days == [] and nodes["person"].days == []
    text = json.dumps(g.model_dump(mode="json"))
    for _category, note in single_person.NOTES[1:]:
        assert note not in text
    for word in ("Leena", "Maija", "Eetu", "sauna", "Sibelius", "barely slept"):
        assert word not in text
    assert "never shown here" in g.note
    # the same record gives the same graph
    again = insight(aino).graph
    assert again.model_dump(mode="json") == g.model_dump(mode="json")
    # without sharing: no themes, no notebook counts; neighbourhoods and days stay
    assert aino.put("/v1/me/sharing", params={"home_id": "aino"}, json={"share_with_care_team": False}).status_code == 200
    private = insight(aino).graph
    assert not any(n.kind == "shared_topic" for n in private.nodes) and not any(e.rel in ("talked_about", "about") for e in private.edges)
    assert len(private.days) == 16 and len(private.domains) == 8 and any(n.days for n in private.nodes if n.kind == "measure")


def test_a_record_with_no_spell_still_has_its_care_action_and_its_days(client):
    from kaiku_contracts import make

    now = datetime.now(TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    events = []
    for d in range(6, 0, -1):
        ts = now - timedelta(days=d)
        events += [make("obs.self_report", {"item": "mood", "value": 4, "channel": "phone"}, source="phone", home_id="noa", ts=ts),
                   make("obs.outing", {"minutes": 30, "steps": 3000, "method": "steps"}, source="phone", home_id="noa", ts=ts)]
    rows = [e.model_dump(mode="json", exclude_none=True) for e in events]
    assert not client.post("/v1/events", json={"events": rows}).json()["rejected"]
    when = (now - timedelta(days=2)).isoformat()
    assert client.post("/v1/patients/noa/actions", json={"action": "send_message", "by": "RS", "ts": when}).status_code == 200
    r = client.get("/v1/patients/noa/insight", params={"generate": "false"})
    assert r.status_code == 200, r.text
    g = PatientInsight.model_validate(r.json()).graph
    nodes = {n.id: n for n in g.nodes}
    care = next(n for n in g.nodes if n.kind == "care_action")
    assert care.domain == "care" and [d.date for d in care.days] == [(now - timedelta(days=2)).date()]
    assert not any(e.rel in ("moved_first", "followed", "after") for e in g.edges)
    assert len(g.days) == 6 and all(d.away == 0 for d in g.days)
    assert all(d.tone == "unknown" for d in nodes["measure:mood"].days) and len(nodes["measure:mood"].days) == 6
    assert ("activity:walk", "measure:steps") in {(e.src, e.dst) for e in g.edges if e.rel == "produces"}
    assert any(c.kind == "care" for d in g.days for c in d.changes)
