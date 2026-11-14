"""The course of change, Gemma's whole-record overview, the learned graph layer, reflections as evidence, the daily
account, and a new robot signal reaching the review with no cloud code."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from kaiku_cloud import insight
from kaiku_cloud.llm import gemma_hosted
from kaiku_cloud.mind import affect
from kaiku_contracts import make
from kaiku_contracts.api import PatientInsight

NOW = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)


def post(client, events):
    rows = [e.model_dump(mode="json", exclude_none=True) for e in events]
    for i in range(0, len(rows), 400):
        assert not client.post("/v1/events", json={"events": rows[i:i + 400]}).json()["rejected"]


def story(home="mira", days=30):
    """Thirty steady days, then: late nights from day -8, mood down from day -7, both fine again from day -3."""
    out = []
    for d in range(days, 0, -1):
        ts = NOW - timedelta(days=d)
        late = 70 if 4 <= d <= 8 else 2
        mood = 2 if 4 <= d <= 7 else 4
        out += [make("obs.screen_activity", {"period_min": 240, "active_min": 100, "late_night_min": late,
                                             "category_min": {"communication": 30}, "switches_per_hour": 10,
                                             "longest_stretch_min": 20, "breaks": 2}, source="laptop", home_id=home, ts=ts),
                make("obs.self_report", {"item": "mood", "value": mood, "channel": "phone"}, source="phone",
                     home_id=home, ts=ts),
                make("obs.ritual", {"step": "close", "status": "completed"}, source="hub", home_id=home, ts=ts),
                make("obs.outing", {"minutes": 30, "steps": 3000, "method": "steps"}, source="phone", home_id=home, ts=ts)]
    return out


@pytest.fixture
def mira(client):
    post(client, story())
    when = (NOW - timedelta(days=5)).isoformat()
    assert client.post("/v1/patients/mira/actions", json={"action": "acknowledge", "by": "RS", "ts": when}).status_code == 200
    return client


def get(client, home="mira", **params):
    r = client.get(f"/v1/patients/{home}/insight", params=params)
    assert r.status_code == 200, r.text
    return PatientInsight.model_validate(r.json())


def test_course_orders_what_moved_first_what_followed_and_what_came_back(mira):
    out = get(mira, generate="false")
    c = out.course
    kinds = {(e.kind, e.metric_id): e for e in c.events}
    late, mood = kinds[("onset", "late_night")], kinds[("onset", "mood")]
    assert late.date == (NOW - timedelta(days=8)).date() and mood.date == late.date + timedelta(days=1)
    assert late.group == "laptop" and "first above their usual" in late.text and "1 h 10 min" in late.text
    assert ("back_in_range", "late_night") in kinds and ("back_in_range", "mood") in kinds
    care = next(e for e in c.events if e.kind == "care_action")
    assert late.date < care.date < kinds[("back_in_range", "mood")].date
    assert [e.date for e in c.events] == sorted(e.date for e in c.events)
    assert c.summary.startswith("First to move away from their usual: late-night screen time on ")
    assert "mood dial followed within 1 day" in c.summary and "Care team follow-up on" in c.summary
    assert "back within their usual" in c.summary and "T" not in c.summary.split("on ")[1][:8]  # 6 Nov, never ISO
    assert c.phase in ("recovering", "recovered") and (c.phase == "recovered") == (out.state == "stable")
    step = next(s for s in out.trace if s.step == "course")
    assert step.actor == "code" and step.items == len(c.events)


def test_quiet_and_young_records_never_claim_more_than_the_rule(client):
    e = [make("obs.self_report", {"item": "mood", "value": 4, "channel": "phone"}, source="phone", home_id="new",
              ts=NOW - timedelta(days=d)) for d in range(6, 0, -1)]
    post(client, e)
    young = get(client, "new", generate="false").course
    assert young.phase == "settling" and not young.events and "still forming" in young.summary


def test_overview_and_findings_must_be_about_this_record(mira, monkeypatch):
    def reply(prompt, **kw):
        return json.dumps({
            "overview": {"text": "Late-night screen time moved first and mood followed a day later. Both are back "
                                 "within usual since the care team's call.",
                         "cites": ["course:summary", "course:onset:late_night", "course:back_in_range:mood"]},
            "findings": [
                {"theme": "improvement", "cites": ["course:onset:late_night", "course:back_in_range:late_night",
                                                   "course:back_in_range:mood"],
                 "meaning": "Late-night screen time moved first and came back first; mood followed it down and then "
                            "back up after the care team's call.", "consider": "Ask what the late nights were about."},
                {"theme": "improvement", "cites": ["course:back_in_range:mood"],
                 "meaning": "This may impact their overall daily vitality.", "consider": None},
                {"theme": "improvement", "cites": ["course:back_in_range:mood"], "meaning": "Things are fine now.",
                 "consider": None},
                {"theme": "improvement", "cites": ["course:back_in_range:mood"], "meaning": "Mood is back.",
                 "consider": None},
                {"theme": "improvement", "cites": ["course:back_in_range:mood"],
                 "meaning": "Mood came back because the care team rang.", "consider": None}]})

    monkeypatch.setattr(gemma_hosted, "generate", reply)
    out = get(mira)
    assert out.review.by == "gemma" and out.review.overview.startswith("Late-night screen time moved first")
    assert out.review.overview_cites[0] == "course:summary" and {"course:summary"} <= {e.id for e in out.evidence}
    kept = [f for f in out.review.findings if f.by == "gemma"]
    assert len(kept) == 1 and kept[0].facts[0].startswith("Late-night screen time first above their usual on ")
    check = next(s for s in out.trace if s.step == "validate")
    assert check.rejected == {"filler": 1, "generic": 1, "thin": 1, "causal_claim": 1}
    assert next(s for s in out.trace if s.step == "overview").status == "ok"


def test_generic_overview_is_dropped_but_findings_stay(mira, monkeypatch):
    monkeypatch.setattr(gemma_hosted, "generate", lambda p, **kw: json.dumps({
        "overview": {"text": "The person had some changes recently and things look different in several ways now.",
                     "cites": ["consensus"]},
        "findings": [{"theme": "improvement", "cites": ["course:back_in_range:mood"],
                      "meaning": "Mood is back within usual since the care team's call, after the late nights.",
                      "consider": None}]}))
    out = get(mira)
    assert out.review.by == "gemma" and out.review.overview is None and out.review.findings
    step = next(s for s in out.trace if s.step == "overview")
    assert step.status == "rejected" and step.rejected == {"generic": 1}


def test_facts_read_as_plain_sentences_with_human_dates(mira):
    out = get(mira, generate="false")
    mood = next(m for g in out.comparison.groups for m in g.metrics if m.metric == "mood")
    assert mood.meaning.startswith("Mood dial ") and " this week" in mood.meaning and mood.meaning.endswith(".")
    assert "less favourable" not in out.model_dump_json() and "against this person" not in out.model_dump_json()
    asked = mira.post("/v1/patients/mira/ask", json={"question": "What changed in the routine this week?"}).json()
    year = str(NOW.year)
    assert f"{year}-" not in asked["answer"] and all(f"{year}-" not in c["detail"] for c in asked["citations"])


def test_graph_has_a_learned_layer_with_honest_labels(mira):
    g = get(mira, generate="false").graph
    assert g.layers == ["learned", "structure"]
    ids = {n.id: n for n in g.nodes}
    learned = [e for e in g.edges if e.layer == "learned"]
    rels = {e.rel for e in learned}
    assert {"moved_first", "followed", "kept_through", "after", "keeps"} <= rels
    first = next(e for e in learned if e.rel == "moved_first")
    assert first.dst == "measure:late_night" and first.label.startswith("first to move, ")
    follow = next(e for e in learned if e.rel == "followed")
    assert (follow.src, follow.dst) == ("measure:late_night", "measure:mood") and "order, not cause" in follow.label
    after = next(e for e in learned if e.rel == "after")
    assert ids[after.src].kind == "care_action" and "back within usual" in after.label and after.evidence >= 1
    routine = next(n for n in g.nodes if n.kind == "routine" and n.id == "routine:ritual")
    assert routine.label.startswith("Morning ritual · around ") and routine.layer == "learned"
    assert all(e.src in ids and e.dst in ids for e in g.edges) and ids["measure:late_night"].layer == "learned"
    assert all(e.rel not in ("moved_first", "followed", "moved_together", "after") for e in g.edges if e.layer == "structure")


def episode(client, home, days_ago, lines, outcome="completed", hour=19):
    start = (NOW - timedelta(days=days_ago)).replace(hour=hour) if days_ago else NOW - timedelta(minutes=30)
    body = {"home_id": home, "surface": "iphone", "intent": "talk", "start": start.isoformat(),
            "end": (start + timedelta(minutes=5)).isoformat(), "outcome": outcome, "tools_used": []}
    if lines:
        body["transcript"] = [{"role": "person", "text": t} for t in lines]
    r = client.post("/v1/companion/episode", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_reflections_become_summary_evidence_only_when_shared(mira, monkeypatch):
    low = ["It was a rough day, I was exhausted and I couldn't sleep again.", "I felt lonely tonight."]
    first = episode(mira, "mira", 3, low)
    episode(mira, "mira", 2, low)
    episode(mira, "mira", 1, ["Today was good, I enjoyed a walk in the park with my sister."])
    episode(mira, "mira", 0, None, outcome="ended_early", hour=8)
    rows = affect.rows(mira.app.state.store, "mira")
    assert rows[first]["valence"] == "low" and "sleep" in rows[first]["themes"] and rows[first]["by"] == "rule"
    assert "rough day" not in json.dumps(rows) and "exhausted" not in json.dumps(rows)  # a level and themes, never the words
    hidden = get(mira, generate="false")
    assert hidden.reflections is None and "reflect:" not in hidden.model_dump_json()
    assert "Talked about" not in hidden.model_dump_json() and "reflection low" not in hidden.model_dump_json()
    card = mira.post("/v1/companion/session", json={"home_id": "mira", "surface": "iphone", "intent": "talk"}).json()
    assert "did not feel like talking this " in card["context_card"]["recent_reflection"]
    assert "Last reflection:" in card["system_instruction"] and "rough day" not in card["system_instruction"]
    last = card["context_card"]["last_reflection"]
    assert last["when"].startswith("this ") and last["declined"] and last["valence"] is None and last["themes"] == []
    night = make("obs.self_report", {"item": "sleep", "value": 2, "channel": "phone"}, source="phone", home_id="mira")
    post(mira, [night])
    card = mira.post("/v1/companion/session", json={"home_id": "mira", "surface": "iphone", "intent": "talk"}).json()
    assert card["context_card"]["today_facts"] == ["a short night"]
    assert "Today, in their own ratings: a short night." in card["system_instruction"]

    assert mira.put("/v1/me/sharing", params={"home_id": "mira"}, json={"share_with_care_team": True}).status_code == 200
    prompts = []
    monkeypatch.setattr(gemma_hosted, "generate", lambda p, **kw: prompts.append(p) or json.dumps({"findings": [
        {"theme": "steady", "cites": ["source:glasses", "reflect:recent"],
         "meaning": "Walks held at their usual level while two of the evening reflections sounded low, with sleep "
                    "coming up.", "consider": "Ask about the evenings."}]}))
    out = get(mira)
    r = out.reflections
    assert (r.reflections, r.low, r.bright, r.declined) == (3, 2, 1, 1) and r.themes[0].label == "sleep"
    assert "their words are not shared" in r.summary and "rough day" not in out.model_dump_json() and "exhausted" not in out.model_dump_json()
    assert "reflect:recent" in prompts[0] and "rough day" not in prompts[0] and "lonely tonight" not in prompts[0]
    assert any("reflect:recent" in f.cites for f in out.review.findings)
    assert any(n.label == "Talked about: sleep" and n.layer == "learned" for n in out.graph.nodes)
    assert any(e.rel == "talked_about" for e in out.graph.edges)
    day = next(d for d in out.days if d.date == (NOW - timedelta(days=3)).date())
    assert "evening reflection low (sleep" in day.text
    # nightly: Gemma may relabel from the opted-in transcript, with the fixed lists only
    monkeypatch.setattr(gemma_hosted, "generate", lambda p, **kw: json.dumps({"valence": "neutral", "themes": ["family"]}))
    assert affect.nightly(mira.app.state.store, "mira")["labelled"] == 3
    monkeypatch.setattr(gemma_hosted, "generate", lambda p, **kw: json.dumps({"valence": "depressed", "themes": []}))
    assert affect.rows(mira.app.state.store, "mira")[first]["valence"] == "neutral"
    # deleting the transcript deletes what was derived from it; a crisis conversation never gets a summary
    assert mira.delete(f"/v1/me/transcripts/{first}", params={"home_id": "mira"}).status_code == 200
    assert first not in affect.rows(mira.app.state.store, "mira")


def test_daily_account_reads_like_a_day(mira):
    out = get(mira, generate="false")
    assert [d.date for d in out.days] == sorted((d.date for d in out.days), reverse=True) and len(out.days) == 14
    hard = next(d for d in out.days if d.date == (NOW - timedelta(days=6)).date())
    assert hard.text.startswith(f"{hard.date:%a} {hard.date.day} {hard.date:%b}: morning ritual, walk (30 min)")
    assert "mood 2 of 5" in hard.text and "away from usual: " in hard.text and "late-night screen time" in hard.text
    care = next(d for d in out.days if d.date == (NOW - timedelta(days=5)).date())
    assert "care team follow-up" in care.text
    calm = next(d for d in out.days if d.date == (NOW - timedelta(days=1)).date())
    assert "away from usual" not in calm.text and "mood 4 of 5" in calm.text


def test_a_new_robot_signal_reaches_the_review_without_cloud_code(mira, monkeypatch):
    """Register an obs type + map it in sources.py: that is all. It is stored, becomes a citable record from its
    payload, sits in the graph under its signal group, and Gemma can cite it."""
    from kaiku_contracts import registry, sources
    from pydantic import BaseModel, ConfigDict

    class HeadTilt(BaseModel):
        model_config = ConfigDict(extra="forbid")
        nods: int
        lean_forward_ratio: float
        tracked: bool

    monkeypatch.setitem(registry.OBS, "obs.head_tilt", HeadTilt)
    monkeypatch.setitem(registry.REGISTRY, "obs.head_tilt", HeadTilt)
    monkeypatch.setattr(registry, "UPLINKABLE", frozenset({*registry.UPLINKABLE, "obs.head_tilt"}), raising=False)
    monkeypatch.setitem(sources.SOURCE_OF, "obs.head_tilt", "robot")
    import kaiku_cloud.api.main as main

    monkeypatch.setattr(main, "UPLINKABLE", frozenset({*main.UPLINKABLE, "obs.head_tilt"}))
    post(mira, [make("obs.head_tilt", {"nods": 7, "lean_forward_ratio": 0.4, "tracked": True}, source="hub",
                     home_id="mira", ts=NOW - timedelta(hours=1))])
    post(mira, [make("obs.engagement", registry.EXAMPLES["obs.engagement"], source="hub", home_id="mira",
                     ts=NOW - timedelta(hours=1))])
    prompts = []
    monkeypatch.setattr(gemma_hosted, "generate", lambda p, **kw: prompts.append(p) or json.dumps({"findings": [
        {"theme": "routine", "cites": ["routine:ritual", "obs:head_tilt"],
         "meaning": "The morning ritual held through the week, and the robot kept recording head movement during it.",
         "consider": "Ask whether mornings with the robot still feel worthwhile."}]}))
    out = get(mira)
    assert '"id": "obs:head_tilt"' in prompts[0] and "nods 7" in prompts[0] and "obs:engagement" in prompts[0]
    cited = next(e for e in out.evidence if e.id == "obs:head_tilt")
    assert cited.label == "Head tilt" and "sent by hub" in cited.detail and "lean forward ratio 0.4" in cited.detail
    assert "tracked yes" in cited.detail and cited.source == "robot"
    assert any(f.by == "gemma" and "obs:head_tilt" in f.cites for f in out.review.findings)
    assert any(n.id == "obs:head_tilt" for n in out.graph.nodes)
    assert any(e.dst == "obs:head_tilt" and e.src == "group:robot" for e in out.graph.edges)
    assert any(t.type == "obs.head_tilt" for g in out.coverage.groups for t in g.types)
    pulse = insight.account.generic_records(mira.app.state.store.events_for_home("mira"),
                                            insight.service.active_criteria(mira.app.state.store),
                                            insight.service.patient_data(mira.app.state.store, "mira",
                                                                         insight.service.active_criteria(mira.app.state.store)),
                                            NOW.date(), insight.OBS_LABEL)
    assert any(r.id == "obs:hrv_session" and r.detail.startswith("Not measured") for r in pulse)
