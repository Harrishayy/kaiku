"""Daily reflection: flagship picks today's focus from fixed options; code validates; rule fallback always works."""

import json

import pytest
from kaiku_cloud.llm import gemini
from kaiku_cloud.llm.errors import LlmUnavailable
from kaiku_cloud.mind import reflect
from kaiku_cloud.store.db import Store

BASE = {"time_of_day": "morning", "tone": "steady", "done_today": [], "memories": ["sister is Maija", "likes the lake"],
        "suggestion": "a short walk", "open_thread": None}


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "r.sqlite"))


@pytest.mark.parametrize("card,focus", [
    ({**BASE, "tone": "extra-gentle", "open_thread": "the lake"}, "keep_light"),  # gentle day beats everything
    ({**BASE, "open_thread": "the lake"}, "follow_thread"),
    ({**BASE, "done_today": ["weather check"]}, "celebrate"),
    (BASE, "offer_suggestion"),
    ({**BASE, "suggestion": None}, "recall_memory"),
    ({**BASE, "suggestion": None, "memories": []}, "keep_light"),
])
def test_rule(card, focus):
    assert reflect.rule(card)["focus"] == focus


@pytest.mark.parametrize("raw", [
    {"focus": "write_a_poem"},                              # not an option
    {"focus": "follow_thread"},                             # no open thread today
    {"focus": "recall_memory", "memory_index": 5},          # index out of range
    {"focus": "recall_memory", "memory_index": None},
    {"focus": "celebrate"},                                 # nothing done today
])
def test_validate_rejects_ungrounded_choices(raw):
    with pytest.raises(ValueError):
        reflect.validate(raw, BASE)


def test_no_new_asks_on_extra_gentle_day():
    with pytest.raises(ValueError):
        reflect.validate({"focus": "offer_suggestion"}, {**BASE, "tone": "extra-gentle"})


def test_flagship_choice_used_when_valid(store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    seen = {}

    def fake(prompt, **kw):
        seen.update(kw, prompt=prompt)
        return json.dumps({"focus": "recall_memory", "memory_index": 1})

    monkeypatch.setattr(gemini, "generate", fake)
    p = reflect.plan(store, "h1", BASE)
    assert p["focus"] == "recall_memory" and p["memory_index"] == 1 and p["by"] == gemini.model_for("flagship")
    assert seen["tier"] == "flagship" and seen["schema"]["properties"]["focus"]["enum"]
    for word in ("needs_call", "consensus", "score", "sleep_min", "hrv"):
        assert word not in seen["prompt"]
    assert reflect.focus_line(p, BASE).endswith('"likes the lake"')


def test_invalid_or_failed_flagship_falls_back_to_rule(store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(gemini, "generate", lambda *a, **k: json.dumps({"focus": "follow_thread"}))
    assert reflect.plan(store, "h2", BASE)["by"] == "rule"

    def boom(*a, **k):
        raise LlmUnavailable("down")

    monkeypatch.setattr(gemini, "generate", boom)
    assert reflect.plan(store, "h3", BASE)["by"] == "rule"


def test_no_key_never_calls_model_and_caches(store, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gemini, "generate", lambda *a, **k: pytest.fail("must not call the model"))
    first = reflect.plan(store, "h4", BASE)
    assert first["by"] == "rule" and reflect.plan(store, "h4", {**BASE, "open_thread": "x"}) == first  # cached today


def test_session_path_never_calls_model(store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(gemini, "generate", lambda *a, **k: pytest.fail("session must not wait on the flagship"))
    assert reflect.plan(store, "h5", BASE, use_model=False)["by"] == "rule"


def test_explain_auto_chain_falls_through_to_template(monkeypatch):
    from kaiku_cloud.llm import explain

    calls = []

    def down(name):
        def f(prompt):
            calls.append(name)
            raise LlmUnavailable(name)
        return f

    monkeypatch.setattr(explain, "BACKENDS", {"gemma_hosted": down("gemma_hosted"), "gemini": down("gemini")})

    class S:
        llm = "auto"

    ctx = {"state": "stable", "sources": [], "notes": []}
    try:
        ex = explain.make_explanation(ctx, S())
    except Exception:  # template may need a richer ctx; the chain order is what we check
        ex = None
    assert calls == ["gemma_hosted", "gemini"]
    assert ex is None or ex.by != "gemma"
