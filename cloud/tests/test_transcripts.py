"""Opt-in conversation transcripts: stored only when sent, never after a crisis, person-facing + deletable, never on
a clinician route, de-identified for the Gemma training export."""

from __future__ import annotations

import json

import pytest
from kaiku_cloud.jobs import transcripts_export
from kaiku_cloud.store.db import Store

TURNS = [{"role": "kaiku", "text": "Morning! How's the walk?"},
         {"role": "person", "text": "Lovely, I met Ritva by Lake Pyhäjärvi. Call me on +358 40 123 4567."},
         {"role": "kaiku", "text": "That sounds lovely, Aino."}]


def episode(c, eid, turns=None, outcome="completed", home="h1"):
    body = {"id": eid, "home_id": home, "surface": "glasses", "intent": "walk", "start": "2026-11-14T08:00:00Z",
            "end": "2026-11-14T08:20:00Z", "outcome": outcome, "tools_used": []}
    if turns is not None:
        body["transcript"] = turns
    r = c.post("/v1/companion/episode", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_no_transcript_without_opt_in(client):
    assert episode(client, "e0")["transcript_stored"] is False
    assert client.get("/v1/me/transcripts?home_id=h1").json()["transcripts"] == []


def test_opt_in_transcript_is_stored_listed_and_deletable(client):
    assert episode(client, "e1", TURNS)["transcript_stored"] is True
    assert episode(client, "e2", TURNS[:1])["transcript_stored"] is True
    got = client.get("/v1/me/transcripts?home_id=h1").json()["transcripts"]
    assert {t["episode_id"] for t in got} == {"e1", "e2"}
    assert next(t for t in got if t["episode_id"] == "e1")["turns"] == TURNS
    assert client.get("/v1/me/transcripts?home_id=other").json()["transcripts"] == []
    assert client.delete("/v1/me/transcripts/e1?home_id=other").status_code == 404   # not that home's
    assert client.delete("/v1/me/transcripts/e1?home_id=h1").json() == {"deleted": 1}
    assert client.delete("/v1/me/transcripts?home_id=h1").json() == {"deleted": 1}
    assert client.get("/v1/me/transcripts?home_id=h1").json()["transcripts"] == []


def test_crisis_conversations_are_never_stored(client):
    hard = [*TURNS, {"role": "person", "text": "Some days I want to die."}]
    assert episode(client, "e3", hard)["transcript_stored"] is False
    assert episode(client, "e4", TURNS, outcome="crisis")["transcript_stored"] is False
    assert client.get("/v1/me/transcripts?home_id=h1").json()["transcripts"] == []


def test_clinicians_never_see_transcripts(client):
    episode(client, "e5", TURNS)
    for path in ("/v1/patients", "/v1/patients/h1/consensus", "/v1/patients/h1/timeline", "/v1/patients/h1/phq9",
                 "/v1/patients/h1/brief", "/v1/events?home_id=h1", "/v1/health/intelligence"):
        r = client.get(path)
        assert "Ritva" not in r.text and "Pyhäjärvi" not in r.text, path


def test_training_export_is_de_identified(tmp_path):
    s = Store(str(tmp_path / "t.sqlite"))
    s.transcript_upsert({"episode_id": "x1", "home_id": "demo-aino", "surface": "glasses", "intent": "walk",
                         "start": "2026-11-14T08:00:00Z", "turns": TURNS})
    s.transcript_upsert({"episode_id": "x2", "home_id": "demo-aino", "surface": "iphone", "intent": "talk",
                         "start": "2026-11-14T09:00:00Z", "turns": [{"role": "person", "text": "hello?"}]})
    ids = {"Aino": "[NAME]", "Ritva": "[PERSON]", "Lake": "[PLACE]", "Pyhäjärvi": "[PLACE]"}
    rows = [r for t in s.transcripts() for r in [t]]
    assert len(rows) == 2
    out = transcripts_export.scrub(TURNS[1]["text"], ids)
    assert "Ritva" not in out and "Pyhäjärvi" not in out and "4567" not in out
    assert "[PERSON]" in out and "[PHONE]" in out
    assert transcripts_export.identifiers([{"category": "people", "text": "My sister Liisa"},
                                           {"category": "likes", "text": "Loves Moomins"}]) == {"Liisa": "[PERSON]"}
    exported = transcripts_export.export(s, "salt")
    assert len(exported) == 1                                    # a person-only conversation is useless: skipped
    row = exported[0]
    assert [m["role"] for m in row["messages"]] == ["model", "user", "model"]
    assert "demo-aino" not in json.dumps(row) and len(row["home"]) == 12
    assert "4567" not in json.dumps(row)
