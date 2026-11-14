"""Gemma is the primary reasoning tier; grounded source facts update on every production tool call."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from kaiku_cloud.llm import gemini, gemma_hosted
from kaiku_cloud.llm.errors import LlmUnavailable
from kaiku_contracts import make
from kaiku_contracts.config import load_config


@pytest.fixture(autouse=True)
def primary(monkeypatch, tmp_path):
    monkeypatch.setenv("KAIKU_MIND_PRIMARY", "gemma_hosted")
    monkeypatch.setenv("KAIKU_SPEND_DB", str(tmp_path / "spend.sqlite"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    load_config.cache_clear()
    yield
    load_config.cache_clear()


def ask(client, kind="fact", question="Which interfaces have sent activities?"):
    return client.post("/v1/companion/tool", json={"home_id": "a", "surface": "iphone", "name": "ask_mind",
                                                 "args": {"question": question, "kind": kind}}).json()


def test_gemma_reads_new_source_context_and_no_private_payloads(client, monkeypatch):
    prompts = []
    def primary(prompt, **kw):
        prompts.append(prompt)
        facts = json.loads(prompt.split("INPUT:\n")[1])["facts"]
        fact = next(f for f in facts if f["id"].startswith("doc:source-"))
        return json.dumps({"answer": fact["text"] + f" [{fact['id']}]", "confidence": .9, "cites": [fact["id"]]})
    monkeypatch.setattr(gemma_hosted, "generate", primary)
    monkeypatch.setattr(gemini, "generate", lambda *a, **kw: pytest.fail("Gemini must not run when Gemma succeeds"))
    mood = make("obs.self_report", {"item": "mood", "value": 2, "context": "adhoc"}, source="phone", home_id="a")
    client.post("/v1/events", json={"events": [mood.model_dump(mode="json")]})
    first = ask(client)["result"]
    assert first["route"] == "gemma" and first["model"] == load_config()["models"]["gemma_hosted"]
    assert "phone app" in first["answer"] and "[" not in first["answer"]
    outing = make("obs.outing", {"minutes": 12, "daylight_min": 8, "method": "dat_camera"}, source="glasses", home_id="a")
    client.post("/v1/events", json={"events": [outing.model_dump(mode="json")]})
    ask(client)
    assert "glasses interface" not in prompts[0] and "glasses interface" in prompts[1]
    assert all(secret not in prompts[-1] for secret in ('"value"', '"daylight_min"', '"minutes"'))
    assert client.get("/v1/health/intelligence").json()["routes"]["gemma"] == 2


@pytest.mark.parametrize("kind", ["fact", "memory", "plan", "care", "emotional"])
def test_every_nondeterministic_kind_tries_gemma_first(client, monkeypatch, kind):
    calls = []
    def primary(prompt, **kw):
        calls.append("gemma")
        return json.dumps({"answer": "I'm here with you.", "confidence": .9, "cites": []})
    def fallback(*args, **kwargs):
        calls.append("gemini")
        raise LlmUnavailable("test unavailable")
    monkeypatch.setattr(gemma_hosted, "generate", primary)
    monkeypatch.setattr(gemini, "generate", fallback)
    result = ask(client, kind, "Could you think this through with me?")["result"]
    assert calls[0] == "gemma"
    if kind == "emotional":
        assert calls == ["gemma"] and result["route"] == "gemma"
    else:
        assert result["route"] == "fallback"  # uncited factual output is rejected, never silently accepted


def test_gemma_failure_keeps_validated_gemini_fallback_explicit(client, monkeypatch):
    monkeypatch.setattr(gemma_hosted, "generate", lambda *a, **kw: (_ for _ in ()).throw(LlmUnavailable("down")))
    monkeypatch.setattr(gemini, "generate", lambda *a, **kw: json.dumps(
        {"answer": "I'm here with you.", "confidence": .9, "cites": []}))
    result = ask(client, "emotional", "I would like some company.")["result"]
    assert result["route"] == "argon" and result["model"] == gemini.model_for("flagship")


def test_crisis_never_reaches_gemma(client, monkeypatch):
    monkeypatch.setattr(gemma_hosted, "generate", lambda *a, **kw: pytest.fail("crisis reached model"))
    result = ask(client, "emotional", "I want to die")
    assert result["crisis"] and not result["ok"]


def test_source_facts_ignore_stale_and_future_inputs(client):
    from kaiku_cloud.mind.router import source_facts
    now = datetime.now(UTC)
    for days in (-10, 2):
        envelope = make("obs.self_report", {"item": "mood", "value": 3, "context": "adhoc"}, source="phone",
                        home_id="a", ts=now + timedelta(days=days))
        client.post("/v1/events", json={"events": [envelope.model_dump(mode="json")]})
    assert source_facts(client.app.state.store, "a", now) == []


def test_hosted_adapter_collects_final_parts_and_rejects_truncation(monkeypatch):
    response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"thought": True, "text": "private reasoning"}, {"text": '{"answer":'}, {"text": '"hello"}'}]}}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Response(
        200, json=response, request=httpx.Request("POST", "https://provider.invalid")))
    assert gemma_hosted._call("model", "key", "synthetic", 1) == '{"answer":"hello"}'
    response["candidates"][0]["finishReason"] = "MAX_TOKENS"
    with pytest.raises(LlmUnavailable):
        gemma_hosted._call("model", "key", "synthetic", 1)


def test_gemma_organises_graph_once_and_bootstrap_uses_prepared_context(client, monkeypatch):
    from kaiku_cloud.mind import graph, memory, nightly
    store = client.app.state.store
    now = datetime.now(UTC)
    for text in ("Likes walking by the lake", "Enjoys a walk beside the lake"):
        memory.remember(store, "a", "places", text, now)
    graph.rebuild(store, "a", now)
    places = [n for n in store.kg_nodes("a") if n["type"] == "place"]
    calls = []
    def organise(prompt, **kw):
        calls.append(kw)
        return json.dumps({"diffs": [{"op": "merge", "keep": f"kg:{places[0]['id']}",
                                      "drop": f"kg:{places[1]['id']}"}]})
    monkeypatch.setattr(gemma_hosted, "generate", organise)
    first = nightly.consolidate(store, "a", now)
    assert first["applied"] == 1 and first["by"][-1] == load_config()["models"]["gemma_hosted"]
    assert nightly.consolidate(store, "a", now)["cached"] and len(calls) == 1
    e = make("obs.self_report", {"item": "mood", "value": 3, "context": "adhoc"}, source="phone", home_id="a", sim=True)
    client.post("/v1/events", json={"events": [e.model_dump(mode="json")]})
    bootstrap = client.post("/v1/companion/session", json={"home_id": "a", "surface": "robot"}).json()
    assert len(calls) == 1  # preparation, ingestion and bootstrap do not call the organiser again
    assert bootstrap["context_card"]["memories"] == [places[0]["label"]]
    assert bootstrap["context_card"]["source_context"] == ["Simulated: The phone app reported a personal check-in today."]
    assert "Simulated: The phone app" in bootstrap["system_instruction"]
    assert len(store.memories("a")) == 2  # model never edits the confirmed notebook
    public = client.post("/v1/companion/session", json={"home_id": "a", "surface": "robot", "others_present": True}).json()
    assert public["context_card"]["source_context"] == [] and public["context_card"]["memories"] == []


def test_graph_organisation_cannot_merge_different_people(client):
    from kaiku_cloud.mind import graph, memory
    store = client.app.state.store
    for text in ("Her sister is Maija", "Her sister is Mia"):
        memory.remember(store, "a", "people", text, datetime.now(UTC))
    graph.rebuild(store, "a")
    people = [n for n in store.kg_nodes("a") if n["type"] == "person"]
    assert graph.validate_diffs(store, "a", [{"op": "merge", "keep": f"kg:{people[0]['id']}",
                                           "drop": f"kg:{people[1]['id']}"}]) == []


@pytest.mark.parametrize("retrieval_seconds,expected", [(0, [45, 45, 20, 5]), (20, [45, 45, 5])])
def test_reasoning_chain_shares_device_deadline(client, monkeypatch, retrieval_seconds, expected):
    from kaiku_cloud.mind import router

    clock, timeouts = [0.0], []
    monkeypatch.setattr(router.time, "monotonic", lambda: clock[0])

    def recall(*args, **kwargs):
        clock[0] += retrieval_seconds
        return []

    def primary(prompt, **kwargs):
        timeouts.append(kwargs["timeout_s"])
        clock[0] += kwargs["timeout_s"]
        return "invalid JSON"

    def fallback(*args, **kwargs):
        timeouts.append(kwargs["timeout_s"])
        clock[0] += kwargs["timeout_s"]
        raise LlmUnavailable("synthetic provider timeout")

    monkeypatch.setattr(router.graph, "recall", recall)
    monkeypatch.setattr(gemma_hosted, "generate", primary)
    monkeypatch.setattr(gemini, "generate", fallback)
    result = ask(client, "fact", "Please think this through.")["result"]
    assert result["route"] == "fallback"
    assert timeouts == expected and clock[0] == 115
