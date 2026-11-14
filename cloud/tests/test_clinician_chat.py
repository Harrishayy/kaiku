"""Record questions use only care evidence, carry verifiable citations, and never disclose private notebook data."""
import json
from datetime import UTC, datetime

import pytest
from kaiku_cloud import clinician_chat
from kaiku_cloud.llm import gemma_hosted
from kaiku_cloud.llm.errors import LlmUnavailable
from kaiku_contracts import make


def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def record(make_client):
    c = make_client(home_tokens={"a": "person"}, clinician_token="care")
    e = make("obs.wearable_daily", {"date": datetime.now(UTC).date().isoformat(), "device": "apple_watch",
                                  "sleep_min": 450, "sleep_midpoint_min": 210}, source="phone", home_id="a")
    assert c.post("/v1/events", headers=headers("person"), json={"events": [e.model_dump(mode="json")]}).status_code == 200
    # Directly seed private content; production clinician call must never read it.
    c.app.state.store.memory_insert("a", "people", "Private neighbour Tove", "private neighbour tove", "2026-11-14T00:00:00Z")
    return c


def test_care_role_required_for_record_question(record):
    body = {"question": "What is going well and what needs review?"}
    assert record.post("/v1/patients/a/ask", json=body).status_code == 401
    assert record.post("/v1/patients/a/ask", headers=headers("person"), json=body).status_code == 403
    assert record.post("/v1/patients/a/ask", headers=headers("care"), json={"question": "x" * 501}).status_code == 422


def test_record_chat_uses_real_units_and_never_private_context(record, monkeypatch):
    prompts = []
    def generate(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps({"answer": "The latest recorded sleep duration is 7 h 30 min [metric:watch_sleep]. "
                           "There is not enough recent usable evidence for a broader comparison [source:wearable].",
                           "cites": ["metric:watch_sleep", "source:wearable"]})
    monkeypatch.setattr(gemma_hosted, "generate", generate)
    for name in ("memories", "episodes", "transcripts"):
        monkeypatch.setattr(record.app.state.store, name, lambda *a, **kw: pytest.fail("clinician read private table"))
    question = {"question": "What is going well and what needs review?"}
    r = record.post("/v1/patients/a/ask", headers=headers("care"), json=question)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["patient_id"] == "a" and body["by"] == "gemma" and not body["cached"]
    assert "Tove" not in prompts[0] and "Tove" not in r.text
    sleep = next(c for c in body["citations"] if c["id"] == "metric:watch_sleep")
    assert sleep["value"] == 450 and sleep["unit"] == "min" and "7 h 30 min" in sleep["detail"]
    repeat = record.post("/v1/patients/a/ask", headers=headers("care"), json=question).json()
    assert repeat["cached"] and len(prompts) == 1
    different = record.post("/v1/patients/a/ask", headers=headers("care"), json={"question": "Any other change?"}).json()
    assert different["by"] == "template" and len(prompts) == 1


@pytest.mark.parametrize("reply", [
    {"answer": "A made-up record [metric:foreign].", "cites": ["metric:foreign"]},
    {"answer": "Sleep is 999 minutes [metric:watch_sleep].", "cites": ["metric:watch_sleep"]},
    {"answer": "A relapse detected [source:wearable].", "cites": ["source:wearable"]},
])
def test_unknown_citations_fall_back_and_unsolicited_prose_is_never_displayed(record, monkeypatch, reply):
    monkeypatch.setattr(gemma_hosted, "generate", lambda *a, **kw: json.dumps(reply))
    body = record.post("/v1/patients/a/ask", headers=headers("care"), json={"question": "What changed?"}).json()
    assert body["by"] == ("template" if "metric:foreign" in reply["cites"] else "gemma")
    assert body["citations"]
    assert "999" not in body["answer"] and "relapse" not in body["answer"]


def test_unavailable_model_is_explicit_and_cached(record, monkeypatch):
    calls = []
    def down(*a, **kw):
        calls.append(True)
        raise LlmUnavailable("offline")
    monkeypatch.setattr(gemma_hosted, "generate", down)
    for _ in range(2):
        body = record.post("/v1/patients/a/ask", headers=headers("care"), json={"question": "What changed?"}).json()
        assert body["by"] == "template" and body["model"] is None
    assert len(calls) == 1


def test_citation_clock_and_duration_formatting():
    assert clinician_chat.human_value(210, "min from midnight") == "03:30"
    assert clinician_chat.human_value(-30, "min from midnight") == "23:30"
    assert clinician_chat.human_value(450, "min") == "7 h 30 min"
    assert clinician_chat.human_value(.6, "ratio") == "60%"


def test_verified_selection_cannot_reverse_direction_or_expose_prose():
    from kaiku_contracts.api import RecordCitation
    refs = [RecordCitation(id="metric:hr", label="Resting heart rate (Check-ins & robot)",
                           detail="Latest: 71.5 bpm. Personal usual: 66.05 bpm. Latest value is higher than their usual.",
                           value=71.5, baseline=66.05, unit="bpm")]
    raw = json.dumps({"answer": "Resting heart rate is lower than usual [metric:hr].", "cites": ["metric:hr"]})
    answer, selected = clinician_chat._validated(raw, refs)
    assert "higher than their usual" in answer and "lower" not in answer
    assert "Check-ins & robot" in answer and selected == refs


def test_selection_ignores_naked_uuid_in_unsolicited_prose():
    from kaiku_contracts.api import RecordCitation
    cid = "task:01941abc-7761-7877-8712-941299999999"
    refs = [RecordCitation(id=cid, label="Firefly task", detail="Usable-face capture coverage: 80%.")]
    answer, _ = clinician_chat._validated(json.dumps({"answer": f"Task {cid} had 80% coverage.", "cites": [cid]}), refs)
    assert answer == "Firefly task: Usable-face capture coverage: 80%." and cid not in answer


def test_whole_units_round_half_up_like_browser():
    assert clinician_chat.human_value(3984.5, "steps") == "3,985 steps"
    assert clinician_chat.human_value(6.5, "min") == "7 min"
    assert clinician_chat.human_value(210.5, "min from midnight") == "03:31"
    assert clinician_chat.human_value(-30.5, "min from midnight") == "23:30"
