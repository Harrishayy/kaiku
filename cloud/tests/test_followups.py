"""Follow-ups from integration: backdated care actions, per-home reset, capability-aware suggestions, the remember
guard, incomplete-day totals, provenance as a flag, and the first-run voice lines."""
from datetime import UTC, datetime, timedelta

import pytest
from kaiku_cloud import service, voice
from kaiku_cloud.analytics.drift import drift_for
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_contracts import make
from kaiku_contracts.api import PatientInsight


def post(client, events):
    rows = [e if isinstance(e, dict) else e.model_dump(mode="json", exclude_none=True) for e in events]
    for i in range(0, len(rows), 400):
        assert not client.post("/v1/events", json={"events": rows[i:i + 400]}).json()["rejected"]


def seed(client, home):
    post(client, generate(next(p for p in DEMO_PATIENTS if p.home_id == home)))


def test_care_action_can_be_logged_on_the_day_it_happened(client):
    seed(client, "demo-aino")
    then = (datetime.now(UTC) - timedelta(days=4)).replace(microsecond=0)
    url = "/v1/patients/demo-aino/actions"
    assert client.post(url, json={"action": "acknowledge", "note": "Rang.", "by": "RS", "ts": then.isoformat()}).status_code == 200
    assert client.post(url, json={"action": "send_message", "note": "See you Tuesday."}).status_code == 200
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    assert client.post(url, json={"action": "acknowledge", "ts": future}).status_code == 422
    out = PatientInsight.model_validate(client.get("/v1/patients/demo-aino/insight", params={"generate": "false"}).json())
    assert [(a.action, a.by) for a in out.actions] == [("acknowledge", "RS"), ("send_message", None)]
    assert out.actions[0].ts == then and out.actions[1].ts > then + timedelta(days=3)


def test_reset_of_one_home_leaves_the_others(client):
    seed(client, "demo-aino")
    seed(client, "sim-eero")
    live = make("obs.self_report", {"item": "mood", "value": 3}, source="phone", home_id="demo-aino")
    post(client, [live])
    before = client.get("/v1/patients/sim-eero/consensus").json()["state"]
    assert client.post("/v1/admin/reset", params={"home_id": "demo-aino"}).json()["deleted"] > 0
    left = client.get("/v1/events", params={"home_id": "demo-aino", "limit": 1000}).json()["events"]
    assert [e["id"] for e in left] == [str(live.id)]  # the real recording stays
    assert client.get("/v1/events", params={"home_id": "sim-eero", "limit": 5}).json()["events"]
    assert client.get("/v1/patients/sim-eero/consensus").json()["state"] == before


def test_a_home_without_a_robot_is_never_offered_drumming(client):
    now = datetime.now(UTC)
    post(client, [make("obs.nudge_outcome", {"arm": "drum", "accepted": True, "next_day": {"mood": 5, "energy": 5}},
                       source="phone", home_id="phone-only", ts=now - timedelta(days=d)) for d in range(1, 9)])
    store = client.app.state.store
    assert "drum" not in service.nudge_arms(store, "phone-only")
    for _ in range(25):  # the best-scoring arm is drumming, and it is still never chosen
        n = client.get("/v1/nudge", params={"home_id": "phone-only"}).json()
        assert n["arm"] != "drum" and "drum" not in n["probs"]
    assert client.get("/v1/me", params={"home_id": "phone-only"}).json()["next_suggestion"]["arm"] != "drum"
    tool = client.post("/v1/companion/tool", json={"home_id": "phone-only", "surface": "iphone", "name": "suggest_nudge"})
    assert tool.json()["result"]["arm"] != "drum"
    post(client, [make("obs.drum_session", {"taps": 40, "duration_s": 60, "tempo_bpm": 90, "regularity": 0.8},
                       source="hub", home_id="phone-only")])
    assert "drum" in service.nudge_arms(store, "phone-only")  # a robot that has reported makes it possible again


def test_remember_in_a_conversation_needs_the_persons_own_words(client):
    session = client.post("/v1/companion/session", json={"home_id": "h", "surface": "iphone", "intent": "talk"}).json()

    def remember(text, said=None, sid=session["session_id"]):
        args = {"category": "likes", "text": text, **({"said": said} if said is not None else {})}
        return client.post("/v1/companion/tool", json={"home_id": "h", "surface": "iphone", "session_id": sid,
                                                       "name": "remember", "args": args}).json()

    unsolicited = remember("Likes sailing on the lake")
    assert not unsolicited["ok"] and "not stored" in unsolicited["error"] and not unsolicited["crisis"]
    assert not remember("Likes sailing on the lake", said="It was a long day at work.")["ok"]  # not what they said
    assert client.get("/v1/me/memories", params={"home_id": "h"}).json()["memories"] == []
    kept = remember("Likes sailing on the lake", said="Please remember that I like sailing on the lake.")
    assert kept["ok"] and kept["result"]["action"] == "stored"
    assert [m["text"] for m in client.get("/v1/me/memories", params={"home_id": "h"}).json()["memories"]] == [
        "Likes sailing on the lake"]
    assert remember("Likes rye bread", sid=None)["ok"]  # the app's own "keep this" button has no conversation


def test_todays_running_total_is_not_scored_or_charted(client):
    """Steps and minutes add up over the day. At noon they read low; the day counts once it is over."""
    now = datetime.now(UTC)
    events = [make("obs.outing", {"minutes": 40, "steps": 4000, "method": "steps"}, source="phone", home_id="walker",
                   ts=now - timedelta(days=d, hours=1)) for d in range(1, 30)]
    events.append(make("obs.outing", {"minutes": 2, "steps": 150, "method": "steps"}, source="phone", home_id="walker",
                       ts=now - timedelta(minutes=1)))
    post(client, events)
    store = client.app.state.store
    crit = service.active_criteria(store)
    today = service.today_local()
    data = service.patient_data(store, "walker", crit)
    steps = next(m for m in crit.metrics if m.name == "steps")
    assert steps.agg == "sum" and today not in data.series["steps"] and max(data.series["steps"]) < today
    drift = drift_for(steps, data.series["steps"], today, crit)
    assert drift.status == "normal" and drift.value_last == 4000
    points = client.get("/v1/patients/walker/timeline", params={"metrics": "steps"}).json()["series"][0]["points"]
    assert points[-1]["value"] is None and points[-2]["value"] == 4000
    mood = next(m for m in crit.metrics if m.name == "mood")
    assert mood.agg not in service.CUMULATIVE  # ratings are complete the moment they are given


def test_simulation_is_a_flag_not_a_word_in_the_text(client):
    seed(client, "demo-aino")
    c = client.get("/v1/patients/demo-aino/consensus").json()
    listed = client.get("/v1/patients").json()["patients"][0]
    assert c["simulated"] is True and listed["sim"] is True
    asked = client.post("/v1/patients/demo-aino/ask", json={"question": "What changed?"}).json()
    insight = client.get("/v1/patients/demo-aino/insight", params={"generate": "false"}).json()
    for text in (str(c), str(listed), str(asked), str(insight["review"]), str(insight["evidence"])):
        assert "SIMULATED" not in text.upper().replace("'SIMULATED': TRUE", "").replace("'SIMULATED': FALSE", "")
    assert "icbt" not in str(c).lower() and "booster" not in str(c).lower()
    assert c["explanation"]["suggested_actions"] == ["check_in_call", "send_message"]


@pytest.mark.parametrize("key", ["welcome.hello", "welcome.done"])
def test_first_run_voice_lines_are_servable(client, monkeypatch, tmp_path, key):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("KAIKU_VOICE_CACHE", str(tmp_path))
    for lang in ("en", "fi", "sv"):
        assert client.get("/v1/voice", params={"lang": lang}).json()["lines"][key]
    missing = client.get(f"/v1/voice/{key}")
    assert missing.status_code == 503 and "hint" in missing.json()  # known key, no TTS: text fallback, never 404
    path = voice.cache_path(key, "en")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF....WAVE")
    served = client.get(f"/v1/voice/{key}")
    assert served.status_code == 200 and served.headers["content-type"] == "audio/wav"
