"""Kaiku's own model looks at a few pictures (D65): only what it noted is stored, as closed word lists; a picture is
never in the database file, a log line, an answer or an error; every failure stores nothing; no other model is used;
the note is shown and citable and has no vote."""
import base64
import json
from datetime import UTC, date, datetime

import pytest
from kaiku_cloud import account, vision
from kaiku_cloud.llm import gemma, gemma_hosted
from kaiku_cloud.llm.errors import LlmUnavailable
from kaiku_cloud.mind import face_cue
from kaiku_contracts import make
from kaiku_contracts.sources import CONSENSUS_SOURCES, SOURCE_OF

MARK = b"KAIKU-PICTURE-MARK-7f3a91c2-do-not-keep"
PICTURE = b"\xff\xd8\xff\xe0" + MARK * 20 + b"\xff\xd9"       # passes as a small JPEG; the marker is its "pixels"
B64 = base64.b64encode(PICTURE).decode()
GOOD = ('Here you go: {"face_visible": true, "expression": "lowered", "gaze": "away", "posture": "slumped", '
        '"lighting": "dim", "confidence": 0.82}')
BODY = {"task": "check_in", "device": "phone", "frames": [B64, B64]}


def notes(client, home="t-home"):
    return [e for e in client.get("/v1/events", params={"home_id": home, "limit": 50}).json()["events"]
            if e["type"] == "obs.vision_note"]


@pytest.fixture
def seen(monkeypatch):
    calls: list[tuple[str, int]] = []

    def look(prompt, images, **kw):
        assert all(i == PICTURE for i in images)                  # the model got the pictures themselves, in memory
        calls.append((prompt, len(images)))
        return GOOD

    monkeypatch.setattr(vision.gemma, "look", look)
    monkeypatch.setattr(vision.gemma, "model_name", lambda: "gemma-test")
    return calls


def test_only_the_note_is_stored_and_the_picture_is_nowhere(client, seen, tmp_path, capfd, caplog):
    r = client.post("/v1/vision/look", params={"home_id": "t-home"}, json=BODY)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] and out["stored"] and out["note"] == {
        "task": "check_in", "device": "phone", "model": "gemma-test", "frames_n": 2, "face_visible": True,
        "expression": "lowered", "gaze": "away", "posture": "slumped", "lighting": "dim", "confidence": 0.82,
        "not_a_diagnosis": True}
    (note,) = notes(client)
    assert note["source"] == "cloud" and note["payload"] == out["note"] and note["quality"] == 0.82
    assert seen == [(vision.PROMPT.format(n=2, s="s"), 2)]
    # the picture: not in the database file (or its journal), not in what was logged, not in the answer
    printed = capfd.readouterr()
    haystacks = [p.read_bytes() for p in tmp_path.iterdir() if p.is_file()]
    haystacks += [printed.out.encode(), printed.err.encode(), caplog.text.encode(), r.content]
    assert haystacks and all(MARK not in h and B64[:60].encode() not in h for h in haystacks)
    assert not any(p.suffix in (".jpg", ".jpeg", ".tmp") for p in tmp_path.rglob("*"))


@pytest.mark.parametrize("answer", [
    "I cannot help with that.", "{not json", '{"face_visible": true}',
    '{"face_visible": true, "expression": "sad", "gaze": "away", "posture": "slumped", "lighting": "dim", "confidence": 0.9}',
    '{"face_visible": "yes", "expression": "neutral", "gaze": "away", "posture": "upright", "lighting": "dim", "confidence": 0.9}',
    '{"face_visible": true, "expression": "neutral", "gaze": "away", "posture": "upright", "lighting": "dim", "confidence": "high"}',
])
def test_an_answer_outside_the_closed_lists_stores_nothing(client, monkeypatch, answer):
    monkeypatch.setattr(vision.gemma, "look", lambda *a, **k: answer)
    r = client.post("/v1/vision/look", params={"home_id": "t-home"}, json=BODY).json()
    assert r == {"ok": True, "stored": False, "reason": "the model's answer could not be used", "note": None}
    assert notes(client) == []


def test_a_model_that_is_down_stores_nothing_and_its_error_text_goes_nowhere(client, monkeypatch, capfd, caplog):
    def down(*a, **k):
        raise LlmUnavailable(f"request failed, body was {B64}")   # a library that quotes what it was sent

    monkeypatch.setattr(vision.gemma, "look", down)
    r = client.post("/v1/vision/look", params={"home_id": "t-home"}, json=BODY)
    assert r.json() == {"ok": True, "stored": False, "reason": "the model is not available right now", "note": None}
    printed = capfd.readouterr()
    assert notes(client) == [] and B64[:60] not in printed.out + printed.err + caplog.text + r.text


def test_no_face_means_nothing_about_a_face(client, monkeypatch):
    monkeypatch.setattr(vision.gemma, "look", lambda *a, **k: json.dumps({
        "face_visible": False, "expression": "tense", "gaze": "away", "posture": "unclear", "lighting": "dark",
        "confidence": 0.9}))
    note = client.post("/v1/vision/look", params={"home_id": "t-home"}, json=BODY).json()["note"]
    assert note["face_visible"] is False and note["expression"] == "unclear" and note["gaze"] == "unclear"


@pytest.mark.parametrize("body,status", [
    ({"task": "check_in", "device": "phone", "frames": []}, 422),
    ({"task": "check_in", "device": "phone", "frames": [B64] * 9}, 422),
    ({"task": "check_in", "device": "toaster", "frames": [B64]}, 422),
    ({"task": "juggling", "device": "phone", "frames": [B64]}, 422),
    ({"task": "check_in", "device": "phone", "frames": ["not base64 !!"]}, 422),
    ({"task": "check_in", "device": "phone", "frames": [base64.b64encode(b"GIF89a" + MARK).decode()]}, 422),
    ({"task": "check_in", "device": "phone", "frames": [base64.b64encode(b"\xff\xd8\xff" + b"x" * 90_000).decode()]}, 413),
    ([B64], 400),
])
def test_a_request_that_is_not_one_is_refused_without_echoing_it(client, seen, body, status):
    r = client.post("/v1/vision/look", params={"home_id": "t-home"}, json=body)
    assert r.status_code == status and B64[:60] not in r.text and MARK.decode() not in r.text
    assert seen == [] and notes(client) == []


def test_only_so_many_looks_a_day_and_off_means_off(client, seen, monkeypatch):
    real = vision.cfg
    monkeypatch.setattr(vision, "cfg", lambda k, d: 2 if k == "max_per_day" else real(k, d))
    for _ in range(2):
        assert client.post("/v1/vision/look", params={"home_id": "t-home"}, json=BODY).json()["stored"]
    r = client.post("/v1/vision/look", params={"home_id": "t-home"}, json=BODY).json()
    assert r["stored"] is False and r["reason"] == "enough looks for today" and len(seen) == 2
    monkeypatch.setattr(vision, "cfg", lambda k, d: False if k == "enabled" else real(k, d))
    assert client.post("/v1/vision/look", params={"home_id": "t-home"}, json=BODY).status_code == 503


def test_another_home_s_credential_cannot_send_pictures(make_client, seen):
    c = make_client(demo_mode=False, home_tokens={"a-home": "tok-a", "b-home": "tok-b"})
    auth = {"authorization": "Bearer tok-a"}
    assert c.post("/v1/vision/look", params={"home_id": "b-home"}, json=BODY, headers=auth).status_code == 403
    assert c.post("/v1/vision/look", params={"home_id": "a-home"}, json=BODY).status_code == 401
    assert seen == []
    assert c.post("/v1/vision/look", params={"home_id": "a-home"}, json=BODY, headers=auth).json()["stored"]


def test_there_is_no_other_model_behind_it(monkeypatch):
    monkeypatch.setattr(gemma, "provider", lambda: "modal")
    with pytest.raises(LlmUnavailable, match="text only"):
        gemma.look("p", [PICTURE])
    monkeypatch.setattr(gemma, "provider", lambda: "hosted")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("kaiku_contracts.genai_client.available", lambda: False)
    with pytest.raises(LlmUnavailable, match="not configured"):
        gemma.look("p", [PICTURE])


def test_a_failed_call_reports_its_kind_and_never_its_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    def boom(*a, **k):
        raise RuntimeError(f"sent {B64}")

    monkeypatch.setattr(gemma_hosted, "_look_rest", boom)
    with pytest.raises(LlmUnavailable) as e:
        gemma_hosted.look("p", [PICTURE])
    assert str(e.value) == "gemma_hosted look failed: RuntimeError" and e.value.__cause__ is None
    assert e.value.__context__ is None                               # no chain back to the request


def test_the_note_has_no_vote_is_one_careful_record_and_makes_the_next_talk_gentler():
    assert SOURCE_OF["obs.vision_note"] == "adherence" and SOURCE_OF["obs.vision_note"] not in CONSENSUS_SOURCES
    now = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    payload = {"task": "check_in", "device": "phone", "model": "gemma-test", "frames_n": 3, "face_visible": True,
               "expression": "lowered", "gaze": "away", "posture": "slumped", "lighting": "dim", "confidence": 0.8,
               "not_a_diagnosis": True}
    event = make("obs.vision_note", payload, source="cloud", home_id="h", ts=now).model_dump(mode="json")
    rec = account.vision_record([event], date(2026, 11, 15))
    assert rec is not None and rec.id == "obs:vision_note" and rec.source is None
    text = rec.detail.lower()
    assert "what the model noted from the camera" in text and "a lowered expression" in text and "not scored" in text
    assert "the pictures were not kept" in text and not any(w in text for w in ("sad", "depress", "diagnos", "emotion"))
    assert account.vision_record([], date(2026, 11, 15)) is None
    assert face_cue.cued([event], now) == ["check_in"]                # the same enum as the expression cue (D60)
    unsure = {**event, "payload": {**payload, "confidence": 0.3}}
    smiling = {**event, "payload": {**payload, "expression": "smiling"}}
    assert face_cue.cued([unsure], now) == [] and face_cue.cued([smiling], now) == []
