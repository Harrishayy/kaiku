"""Practitioner insight: Gemma interprets, code verifies and renders; deterministic fallback; no private data."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from kaiku_cloud import insight
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_cloud.llm import gemma_hosted
from kaiku_cloud.llm.errors import LlmUnavailable
from kaiku_contracts import make
from kaiku_contracts.api import PatientInsight

CARE = {"Authorization": "Bearer care"}


def seed(client, patient_id):
    spec = next(p for p in DEMO_PATIENTS if p.home_id == patient_id)
    events = generate(spec)
    for i in range(0, len(events), 400):
        r = client.post("/v1/events", json={"events": events[i:i + 400]})
        assert r.status_code == 200 and not r.json()["rejected"]


@pytest.fixture
def aino(client):
    seed(client, "demo-aino")
    return client


def get(client, patient_id="demo-aino", **params):
    r = client.get(f"/v1/patients/{patient_id}/insight", params=params)
    assert r.status_code == 200, r.text
    return PatientInsight.model_validate(r.json())


def reply(*findings):
    return json.dumps({"findings": list(findings)})


def test_template_insight_is_complete_without_a_model(aino, monkeypatch):
    monkeypatch.setattr(gemma_hosted, "generate", lambda *a, **k: pytest.fail("generate=false must not call a model"))
    out = get(aino, generate="false")
    assert out.state == "needs_call" and out.review.by == "template" and out.review.fallback_reason == "not_requested"
    assert out.review.headline.startswith("Worth a check-in call.")
    changes = [f for f in out.review.findings if f.theme == "change"]
    assert {f.cites[0] for f in changes} == {"source:robot", "source:laptop", "source:wearable"}
    cited = {i for f in out.review.findings for i in f.cites}
    assert cited == {e.id for e in out.evidence} and all(f.facts for f in out.review.findings)
    assert [s.step for s in out.trace] == ["retrieve", "consensus", "compare", "course", "select", "interpret", "graph", "render"]
    assert next(s for s in out.trace if s.step == "interpret").status == "skipped"
    # week over week, per signal group and per measure, with the rule engine's own reading kept apart
    groups = {g.source: g for g in out.comparison.groups}
    assert set(groups) == {"robot", "glasses", "laptop", "wearable"} and groups["robot"].trend == "worse"
    mood = next(m for m in groups["robot"].metrics if m.metric == "mood")
    assert mood.vs_previous == "worse" and mood.sustained == "change_from_usual" and mood.this_week_text.endswith("of 5")
    assert "mood" in out.comparison.changed and not out.comparison.improved
    # routine + what helps carry attempts and an interval
    assert out.routine.routines and out.routine.kept + out.routine.partly + out.routine.slipped == len(out.routine.routines)
    walk = next(h for h in out.routine.helps if h.activity == "walk")
    assert walk.tries > 0 and walk.low <= walk.mean_effect <= walk.high
    # graph a UI can draw: every edge joins two nodes that exist
    ids = {n.id for n in out.graph.nodes}
    assert "person" in ids and all(e.src in ids and e.dst in ids for e in out.graph.edges)
    assert {n.kind for n in out.graph.nodes} >= {"person", "signal_group", "measure", "activity", "routine"}
    assert out.coverage.observations > 0 and out.coverage.simulated and out.coverage.baseline_ready
    assert all(g.sufficient for g in out.coverage.groups)
    text = out.model_dump_json(exclude={"patient_id"}).lower()  # the id is the home's own key, not display text
    assert not any(w in text for w in ("diagnos", "relapse", "disorder", "demo"))


def test_gemma_findings_are_verified_rendered_and_cached(aino, monkeypatch):
    prompts = []

    def generate(prompt, *a, **k):
        prompts.append(prompt)
        return reply(
            {"theme": "change", "cites": ["source:robot", "week:mood"], "meaning": "Mood ratings have moved away "
             "from their usual alongside later mornings.", "consider": "Worth a check-in about how mornings feel."},
            {"theme": "change", "cites": ["metric:foreign"], "meaning": "Invented.", "consider": None},
            {"theme": "change", "cites": ["week:energy"], "meaning": "Energy fell to 2 of 5.", "consider": None},
            {"theme": "improvement", "cites": ["week:mood"], "meaning": "Mood is back up since the week before.", "consider": None},
            {"theme": "change", "cites": ["week:sleep"], "meaning": "Sleep changed because of late screens.",
             "consider": None},
            {"theme": "change", "cites": ["source:laptop"], "meaning": "This points to a relapse.", "consider": None},
            {"theme": "steady", "cites": ["source:glasses"], "meaning": "Walks have held at their usual level since the week before.",
             "consider": None})

    monkeypatch.setattr(gemma_hosted, "generate", generate)
    out = get(aino)
    assert out.review.by == "gemma" and not out.review.cached and len(prompts) == 1
    by_model = [f for f in out.review.findings if f.by == "gemma"]
    assert [f.cites for f in by_model] == [["source:robot", "week:mood"], ["source:glasses"]]
    assert any("of 5" in fact for fact in by_model[0].facts)  # numbers come from code, beside the model's words
    check = next(s for s in out.trace if s.step == "validate")
    assert check.rejected == {"unknown_citation": 1, "numbers_in_prose": 1, "direction_mismatch": 1,
                              "causal_claim": 1, "wording": 1}
    # the model left Apps and Watch out: code adds their recorded change, and says so
    added = [f for f in out.review.findings if f.by == "template"]
    assert {f.cites[0] for f in added} == {"source:laptop", "source:wearable"} and "Added 2" in check.detail
    assert [f.theme for f in out.review.findings] == ["change", "change", "change", "steady"]
    step = next(s for s in out.trace if s.step == "interpret")
    assert step.actor == "gemma" and step.status == "ok" and step.latency_ms is not None and not step.cache_hit
    again = get(aino)
    assert again.review.cached and len(prompts) == 1
    assert next(s for s in again.trace if s.step == "interpret").cache_hit
    # the prompt carries care evidence only
    assert "EVIDENCE:" in prompts[0] and "source:robot" in prompts[0]


def test_new_data_invalidates_the_cached_review(aino, monkeypatch):
    calls = []

    def generate(prompt, *a, **k):
        calls.append(1)
        return reply({"theme": "steady", "cites": ["source:glasses"], "meaning": "Walks have held at their usual level since the week before.",
                      "consider": None})

    monkeypatch.setattr(gemma_hosted, "generate", generate)
    assert get(aino).review.by == "gemma"
    e = make("obs.self_report", {"item": "mood", "value": 1}, source="hub", home_id="demo-aino")
    assert aino.post("/v1/events", json={"events": [e.model_dump(mode="json")]}).json()["accepted"] == 1
    stale = get(aino)  # evidence changed inside the cooldown: deterministic, never the older prose
    assert stale.review.by == "template" and stale.review.fallback_reason == "cooldown" and len(calls) == 1
    aino.app.state.store.kv_delete("insight-review-last:demo-aino")
    assert get(aino).review.by == "gemma" and len(calls) == 2


@pytest.mark.parametrize("failure, reason", [
    (LlmUnavailable("timeout"), "provider_unavailable"), ("not json", "invalid_json"),
    (json.dumps({"findings": [{"theme": "change", "cites": ["nope"], "meaning": "x"}]}), "no_valid_findings")])
def test_model_failures_fall_back_to_the_template(aino, monkeypatch, failure, reason):
    calls = []

    def generate(prompt, *a, **k):
        calls.append(prompt)
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(gemma_hosted, "generate", generate)
    out = get(aino)
    assert out.review.by == "template" and out.review.fallback_reason == reason and out.review.findings
    assert len(calls) == (1 if reason == "provider_unavailable" else 2)  # one corrective retry, never for an outage
    assert next(s for s in out.trace if s.step == "interpret").status == "fallback"
    rows = aino.app.state.store.model_calls("2000-01-01")
    assert any(r["task"] == "insight_review" and r["fallback"] and r["route"] == reason for r in rows)


def test_missing_sources_are_never_read_as_well(client, monkeypatch):
    seed(client, "sim-kaisa")  # robot only
    out = get(client, "sim-kaisa", generate="false")
    assert out.state == "watch" and out.agreement == "low_coverage"
    missing = [g for g in out.coverage.groups if not g.sufficient]
    assert {g.source for g in missing} == {"glasses", "laptop", "wearable"}
    assert all(g.trend == "unknown" and not g.metrics for g in out.comparison.groups if g.source != "robot")
    coverage = next(f for f in out.review.findings if f.theme == "coverage")
    assert "never read as being well" in coverage.meaning and "In line with" not in out.review.headline


def test_one_day_of_data_and_unknown_patient(client):
    e = make("obs.self_report", {"item": "mood", "value": 3}, source="phone", home_id="new-home")
    assert client.post("/v1/events", json={"events": [e.model_dump(mode="json")]}).status_code == 200
    out = get(client, "new-home", generate="false")
    assert out.state == "watch" and not out.coverage.baseline_ready and out.coverage.recorded_days == 1
    assert not out.routine.routines and not out.comparison.improved and not out.comparison.changed
    assert out.comparison.summary.startswith("Not enough recorded days")
    assert client.get("/v1/patients/nobody/insight").status_code == 404


def test_insight_is_care_team_only_and_reads_no_private_tables(make_client, monkeypatch):
    c = make_client(home_tokens={"a": "person"}, clinician_token="care", demo_mode=False)
    now = datetime.now(UTC)
    events = [make("obs.outing", {"minutes": 30, "steps": 2500, "method": "steps"}, source="phone", home_id="a",
                   ts=now - timedelta(days=d)) for d in range(12)]
    assert c.post("/v1/events", headers={"Authorization": "Bearer person"},
                  json={"events": [e.model_dump(mode="json", exclude_none=True) for e in events]}).status_code == 200
    store = c.app.state.store
    store.memory_insert("a", "people", "Private neighbour Tove", "private neighbour tove", "2026-11-14T00:00:00Z")
    assert c.get("/v1/patients/a/insight").status_code == 401
    assert c.get("/v1/patients/a/insight", headers={"Authorization": "Bearer person"}).status_code == 403
    prompts = []
    monkeypatch.setattr(gemma_hosted, "generate", lambda p, *a, **k: prompts.append(p) or "{}")
    for name in ("memories", "transcripts", "kg_nodes", "kg_edges", "episodes"):  # sharing is off
        monkeypatch.setattr(store, name, lambda *a, **kw: pytest.fail("insight read a private table"))
    r = c.get("/v1/patients/a/insight", headers=CARE)
    assert r.status_code == 200 and "Tove" not in r.text and prompts and "Tove" not in prompts[0]
    body = PatientInsight.model_validate(r.json())
    assert not body.graph.shared and body.graph.basis == ["observations"]
    assert any(n.id == "activity:walk" for n in body.graph.nodes)


def test_finding_checks_one_by_one():
    from kaiku_contracts.api import RecordCitation

    refs = {i: RecordCitation(id=i, label=i, detail="d") for i in ("source:robot", "week:mood", "helps:walk")}
    tone = {"source:robot": "worse", "week:mood": "better", "helps:walk": "unknown"}
    ok = {"theme": "improvement", "cites": ["week:mood"], "meaning": "Mood ratings are back up since the week before."}
    assert insight.check_finding(ok, refs, tone).by == "gemma"
    assert insight.check_finding({**ok, "meaning": "Mood ratings got worse since the week before."}, refs, tone) == "direction_mismatch"
    assert insight.check_finding({**ok, "cites": ["week:mood", "source:robot"]}, refs, tone) == "direction_mismatch"
    assert insight.check_finding({**ok, "meaning": "Mood is back and the consensus is fine."}, refs, tone) == "wording"
    assert insight.check_finding({**ok, "meaning": "Mood has remained a stable part of the day."}, refs, tone).theme == "improvement"
    assert insight.check_finding({**ok, "meaning": "A good part of the day."}, refs, tone) == "generic"
    assert insight.check_finding({**ok, "meaning": "Mood may impact their overall vitality."}, refs, tone) == "filler"
    assert insight.check_finding({"theme": "what_helps", "cites": ["helps:walk"], "meaning": "Walks have helped a little since the week before."},
                                 refs, tone) == "direction_mismatch"
    dip = {"theme": "change", "cites": ["week:mood"], "meaning": "Mood dipped against the week before, then held."}
    week_only = {**tone, "week:mood": "worse"}  # lower than last week but inside the usual range: not a change from usual
    assert insight.check_finding(dip, refs, week_only, set()) == "direction_mismatch"
    assert insight.check_finding(dip, refs, week_only, {"week:mood"}).theme == "change"
    assert insight.check_finding({**ok, "cites": []}, refs, tone) == "invalid_shape"
    assert insight.check_finding("text", refs, tone) == "invalid_shape"


def test_one_switch_moves_every_gemma_call_to_the_modal_app(aino, monkeypatch):
    from kaiku_cloud.llm import gemma, gemma_vllm
    from kaiku_contracts.config import load_config

    seen = []

    def modal(prompt, timeout_s=60.0, *, task="explain", home_id=None):
        seen.append(task)
        return reply({"theme": "steady", "cites": ["source:glasses"], "meaning": "Walks have held at their usual level since the week before."})

    monkeypatch.setattr(gemma_vllm, "generate", modal)
    monkeypatch.setattr(gemma_hosted, "generate", lambda *a, **k: pytest.fail("hosted provider was not selected"))
    assert gemma.provider() == "hosted"
    monkeypatch.setenv("KAIKU_GEMMA_PROVIDER", "modal")
    load_config.cache_clear()
    try:
        assert gemma.provider() == "modal" and gemma.model_name() == load_config()["models"]["gemma_hf_repo"]
        out = get(aino)
        step = next(s for s in out.trace if s.step == "interpret")
        assert out.review.by == "gemma" and out.review.model == gemma.model_name() and "Modal GPU" in step.detail
        asked = aino.post("/v1/patients/demo-aino/ask", json={"question": "What changed this week?"}).json()
        assert asked["by"] == "template" and seen == ["insight_review", "clinician_ask"]  # reached Modal; shape differs
    finally:
        monkeypatch.delenv("KAIKU_GEMMA_PROVIDER")
        load_config.cache_clear()  # the config is cached per process: later tests must see the hosted default


def test_stored_brief_is_retired_when_the_consensus_moves(aino):
    from kaiku_cloud.mind import brief

    store = aino.app.state.store
    first = aino.get("/v1/patients/demo-aino/brief").json()
    assert first["state"] == "needs_call" and "Check-ins & robot: change from their usual" in json.dumps(first)
    store.kv_set(brief.key("demo-aino"), {**first, "state": "stable", "by": "model", "model": "m",
                                           "sections": [{"text": "All steady.", "metrics": []}]})
    now = aino.get("/v1/patients/demo-aino/brief").json()
    assert now["state"] == "needs_call" and now["by"] == "template"
    store.kv_set(brief.key("demo-aino"), {**first, "by": "model", "model": "m"})
    assert aino.get("/v1/patients/demo-aino/brief").json()["by"] == "model"


def test_every_registered_observation_type_is_stored_and_reachable(client):
    """Storage audit: each obs.* type in the registry is accepted, kept in SQLite with its provenance, readable
    through the events API and counted in the practitioner's coverage. Raw streams and commands never are."""
    from kaiku_contracts import UPLINKABLE
    from kaiku_contracts.registry import EXAMPLES
    from kaiku_contracts.sources import SOURCE_OF

    obs = sorted(t for t in UPLINKABLE)
    assert obs and all(t.startswith("obs.") and t in SOURCE_OF for t in obs)
    events = [make(t, EXAMPLES[t], source="phone", home_id="audit", quality=0.9).model_dump(mode="json", exclude_none=True)
              for t in obs]
    result = client.post("/v1/events", json={"events": events}).json()
    assert result == {"accepted": len(obs), "duplicates": 0, "rejected": []}
    assert client.post("/v1/events", json={"events": events}).json()["duplicates"] == len(obs)  # idempotent retry
    stored = {e["type"]: e for e in client.get("/v1/events", params={"home_id": "audit", "limit": 1000}).json()["events"]}
    assert set(stored) == set(obs)
    assert all(stored[t]["payload"] and stored[t]["source"] == "phone" and stored[t]["quality"] == 0.9 for t in obs)
    cov = get(client, "audit", generate="false").coverage
    counted = {t.type for g in cov.groups for t in g.types} | {t.type for t in cov.other}
    assert counted == set(obs) and cov.observations == len(obs) and not cov.simulated
    assert all(t.label and not t.label.startswith("obs.") and t.captured_by == ["phone"]
               for g in cov.groups for t in [*g.types]) and all(t.label for t in cov.other)
    raw = make("raw.head.tap", EXAMPLES["raw.head.tap"], source="head", home_id="audit").model_dump(mode="json", exclude_none=True)
    refused = client.post("/v1/events", json={"events": [raw, {"type": "obs.outing", "payload": {"audio": "x"}}, "junk"]}).json()
    assert refused["accepted"] == 0 and len(refused["rejected"]) == 3


def test_young_record_is_labelled_early_everywhere_and_responses_are_not_effects(client, monkeypatch):
    """Day 12: provisional baseline. Review, comparison, routine and coverage all say so; what-helps stays uncertain."""
    now = datetime.now(UTC)
    events = []
    for d in range(12):
        ts = now - timedelta(days=d)
        events += [make("obs.self_report", {"item": "mood", "value": 2 if d < 4 else 4, "channel": "phone"},
                        source="phone", home_id="young", ts=ts),
                   make("obs.nudge_outcome", {"arm": "daylight_walk", "accepted": True,
                                              "next_day": {"mood": 4, "energy": 4}}, source="phone", home_id="young", ts=ts)]
    assert client.post("/v1/events", json={"events": [e.model_dump(mode="json", exclude_none=True) for e in events]}
                       ).json()["accepted"] == len(events)
    prompts = []

    def generate(prompt, **kw):
        prompts.append(prompt)
        return reply({"theme": "what_helps", "cites": ["helps:walk"], "meaning": "Walks are proven to work for them."},
                     {"theme": "what_helps", "cites": ["helps:walk"],
                      "meaning": "Walks have an early reported response above neutral; the baseline is still early."})

    monkeypatch.setattr(gemma_hosted, "generate", generate)
    out = get(client, "young")
    assert out.state != "stable" and out.coverage.day_of_record == 12
    assert out.review.early_record and out.review.day_of_record == 12 and "Day 12 of the record" in out.review.headline
    assert out.routine.early_record and "short record" in out.routine.caveat
    walk = next(h for h in out.routine.helps if h.activity == "walk")
    assert walk.tries == 12 and walk.certainty == "building" and walk.low < walk.high  # never "consistent" this early
    mood = next(m for g in out.comparison.groups for m in g.metrics if m.metric == "mood")
    if mood.usual is not None:
        assert mood.early_baseline and mood.baseline_days and "early baseline" in mood.meaning
        assert out.comparison.early_baseline and out.coverage.early_baseline
    assert '"baseline": "early, lower confidence"' in prompts[0]
    check = next(s for s in out.trace if s.step == "validate")
    assert check.rejected.get("overclaim") == 1 and [f.by for f in out.review.findings if f.theme == "what_helps"] == ["gemma"]


def test_state_history_actions_and_exact_early_flags(aino):
    assert aino.post("/v1/patients/demo-aino/actions", json={"action": "send_message", "note": "Call you Tuesday.",
                                                             "by": "RN"}).status_code == 200
    out = get(aino, generate="false")
    days = [d.date for d in out.state_history]
    assert days == sorted(days) and len(days) == len(set(days)) >= 28 and days[-1] == datetime.now(UTC).astimezone().date() \
        or days[-1] >= out.comparison.this_week_end
    assert out.state_history[-1].state == out.state and out.state_history[-1].agreement == out.agreement
    assert out.min_history_days_for_stable > 0 and out.day_of_record == out.coverage.day_of_record
    young = [d for d in out.state_history if d.early]
    assert all(d.state != "stable" for d in young)
    assert len(young) <= out.min_history_days_for_stable and not out.state_history[-1].early
    assert [(a.action, a.note, a.by) for a in out.actions] == [("send_message", "Call you Tuesday.", "RN")]
    points = aino.get("/v1/patients/demo-aino/timeline", params={"metrics": "mood", "days": 45}).json()["series"][0]["points"]
    assert all("early" in p for p in points) and not points[-1]["early"]
    assert all(p["baseline_median"] is not None for p in points if p["early"])
