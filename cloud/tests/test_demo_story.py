from datetime import date

from kaiku_cloud.jobs import demo_story
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate


def test_old_saved_locale_does_not_switch_live_back_from_english(client):
    result = client.post("/v1/companion/session", json={"home_id": "fresh-install", "surface": "robot",
                                                     "intent": "talk", "language": "fi"})
    assert result.status_code == 200
    assert result.json()["context_card"]["language"] == "en"


def test_unimplemented_nudges_cannot_be_selected_even_with_old_positive_history():
    import random

    from kaiku_cloud.analytics import bandit

    old = [{"arm": "friend_ping", "accepted": True, "reward": 1.0}] * 100
    result = bandit.choose(old, rng=random.Random(2))
    assert result["arm"] in {"breathe", "drum", "daylight_walk"}
    assert set(result["probs"]) == {"breathe", "drum", "daylight_walk"}


def test_reasoning_rejection_telemetry_never_keeps_model_text():
    from kaiku_cloud.mind.router import Rejected, rejection_code

    assert rejection_code(Rejected("unverifiable cite ['private-secret']")) == "unknown_citation"
    assert rejection_code(Rejected("arbitrary untrusted output")) == "invalid_shape"


def test_demo_stories_are_reproducible_and_never_collide_with_existing_cohort():
    end = date(2026, 11, 13)
    rows = demo_story.events(end)
    assert rows == demo_story.events(end)
    ids = {e["id"] for e in rows}
    assert len(ids) == len(rows) and all(e["sim"] for e in rows)
    assert not ids & {e["id"] for p in DEMO_PATIENTS for e in generate(p, end)}
    assert not any(e["type"] in {"obs.light_level", "obs.laptop_session", "obs.hrv_session"} for e in rows)
    assert all(e["payload"].get("force_mean") is None for e in rows if e["type"] == "obs.drum_session")
    assert all("daylight_min" not in e["payload"] for e in rows if e["type"] == "obs.outing")


def test_recorded_demo_batch_uses_real_rules_and_does_not_overinterpret_one_poor_task(client):
    rows = demo_story.events(date(2026, 11, 13))
    for start in range(0, len(rows), 400):
        response = client.post("/v1/events", json={"events": rows[start:start + 400]})
        assert response.status_code == 200 and response.json()["accepted"] == len(rows[start:start + 400])
    repeated = client.post("/v1/events", json={"events": rows[:400]}).json()
    assert repeated["accepted"] == 0 and repeated["duplicates"] == 400
    report = demo_story.report(rows, date(2026, 11, 13))
    by = {s["home_id"]: s for s in report["stories"]}
    assert by["story-changing"]["state"] == "needs_call"
    assert by["story-missing"]["state"] == "watch"
    assert by["story-outlier"]["state"] == "stable"
    assert any(s["verdict"] == "better" for s in by["story-improving"]["sources"])
    assert any(i["kind"] == "metric" for i in by["story-improving"]["week"]["going_well"])
    assert all(e["source"] == "hub" for e in rows if e["home_id"] == "story-missing")
