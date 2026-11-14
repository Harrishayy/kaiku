"""Task aggregate inspection: real phone/web envelopes, retained provenance, privacy and no camera-state inference."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from kaiku_cloud import service
from kaiku_cloud.analytics.data import build
from kaiku_cloud.llm import gemma_hosted
from kaiku_contracts import make


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def task(*, home="a", device="web", method="mediapipe_blendshapes", at=None, simulated=False, camera=True):
    payload = {"game": "tell", "device": device, "duration_s": 30, "speech_rate": 3.2, "pause_ratio": .2}
    if camera:
        payload.update(expressivity_index=.245, face_movement=.116, camera_face_coverage=.8,
                       camera_samples=25, camera_method=method)
    return make("obs.play_session", payload, source="phone" if device == "phone" else "laptop", home_id=home,
                quality=.9, sim=simulated, ts=at or datetime.now(UTC)).model_dump(mode="json")


@pytest.fixture
def c(make_client):
    return make_client(home_tokens={"a": "person-a", "b": "person-b"}, clinician_token="care")


def test_phone_and_web_tasks_roundtrip_with_capture_provenance(c):
    rows = [task(simulated=True), task(device="phone", method="vision_landmarks")]
    assert c.post("/v1/events", headers=auth("person-a"), json={"events": rows}).json()["accepted"] == 2
    response = c.get("/v1/patients/a/tasks?days=7", headers=auth("care"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["patient_id"] == "a" and body["computed_at"]
    received = {e["id"]: e for e in body["observations"]}
    assert received.keys() == {e["id"] for e in rows}
    for sent in rows:
        observed = received[sent["id"]]
        for key in ("source", "sim", "quality", "ts", "home_id"):
            assert observed[key] == sent[key]
        for key, value in sent["payload"].items():
            assert observed["payload"][key] == value
    assert {e["payload"]["camera_method"] for e in received.values()} == {"vision_landmarks", "mediapipe_blendshapes"}


def test_task_inspection_role_and_home_ownership(c):
    assert c.post("/v1/events", headers=auth("person-a"), json={"events": [task(home="b")]}).status_code == 403
    c.post("/v1/events", headers=auth("person-a"), json={"events": [task()]})
    c.post("/v1/events", headers=auth("person-b"), json={"events": [task(home="b")]})
    assert c.get("/v1/patients/a/tasks").status_code == 401
    assert c.get("/v1/patients/a/tasks", headers=auth("person-a")).status_code == 403
    assert c.get("/v1/patients/a/tasks", headers=auth("person-b")).status_code == 403
    observed = c.get("/v1/patients/a/tasks", headers=auth("care")).json()["observations"]
    assert len(observed) == 1 and observed[0]["home_id"] == "a"
    for days in (0, 31):
        assert c.get(f"/v1/patients/a/tasks?days={days}", headers=auth("care")).status_code == 422


def test_tasks_are_recent_bounded_newest_first_and_exclude_future(c):
    now = datetime.now(UTC)
    rows = [task(at=now - timedelta(minutes=i)) for i in range(102)]
    rows += [task(at=now - timedelta(days=8)), task(at=now + timedelta(days=1))]
    assert c.post("/v1/events", headers=auth("person-a"), json={"events": rows}).json()["accepted"] == len(rows)
    observed = c.get("/v1/patients/a/tasks?days=7", headers=auth("care")).json()["observations"]
    assert len(observed) == 100
    assert [e["id"] for e in observed] == [e["id"] for e in rows[:100]]


def test_camera_metadata_is_optional_and_no_raw_media_is_accepted(c):
    plain = task(camera=False)
    none_seen = task(camera=False)
    none_seen["payload"].update(camera_face_coverage=0, camera_samples=20, camera_method="vision_landmarks")
    invalid = []
    for field in ("audio", "video", "camera_frame", "transcript"):
        event = task()
        event["payload"][field] = "synthetic raw content must not be retained"
        invalid.append(event)
    result = c.post("/v1/events", headers=auth("person-a"), json={"events": [plain, none_seen, *invalid]}).json()
    assert result["accepted"] == 2 and len(result["rejected"]) == 4
    stored = c.get("/v1/patients/a/tasks", headers=auth("care"))
    assert "synthetic raw content" not in stored.text
    assert all(e["payload"]["expressivity_index"] is None for e in stored.json()["observations"])


def test_facial_methods_do_not_enter_criteria_or_add_votes(c):
    crit = service.active_criteria(c.app.state.store)
    plain = task(camera=False)
    rich = task()
    rich["ts"] = plain["ts"]
    a = build("a", [plain], crit)
    b = build("a", [rich], crit)
    assert a.series == b.series and a.source_days == b.source_days
    assert not any(m.obs == "obs.play_session" and m.field in {"expressivity_index", "face_movement"} for m in crit.metrics)


def test_record_chat_task_facts_contain_participation_and_coverage_only(c, monkeypatch):
    event = task()
    c.post("/v1/events", headers=auth("person-a"), json={"events": [event]})
    prompts = []
    citation = f"task:{event['id']}"
    def generate(prompt, **kw):
        prompts.append(prompt)
        return json.dumps({"answer": f"A tell task was recorded with 80% usable-face capture coverage [{citation}].",
                           "cites": [citation]})
    monkeypatch.setattr(gemma_hosted, "generate", generate)
    result = c.post("/v1/patients/a/ask", headers=auth("care"), json={"question": "What tasks were captured?"}).json()
    assert result["by"] == "gemma" and result["citations"][0]["id"] == citation
    assert "mediapipe_blendshapes" in prompts[0] and "Sampled frames: 25" in prompts[0]
    assert all(value not in prompts[0] for value in ("expressivity_index", "face_movement", "0.245", "0.116"))
    assert result["citations"][0]["value"] == .8 and result["citations"][0]["unit"] == "ratio"
