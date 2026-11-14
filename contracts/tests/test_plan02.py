"""Plan 02 contract changes: phone source, self_report channel, extended outing, screen_activity, play_session,
wearable_daily, the wearable consensus source, nested criteria fields, MeResponse companion fields."""

import tomllib

import pytest
from kaiku_contracts import EXAMPLES, SOURCE_OF, ContractError, validate
from kaiku_contracts.api import MeResponse
from kaiku_contracts.criteria import criteria_path, load_criteria, parse_criteria
from kaiku_contracts.sources import CONSENSUS_SOURCES
from pydantic import ValidationError


def _env(type_, payload, source="phone"):
    return {"home_id": "demo-aino", "source": source, "type": type_, "payload": payload}


def test_phone_source_and_self_report_channel():
    env = validate(_env("obs.self_report", {"item": "mood", "value": 4, "channel": "phone"}))
    assert env.source == "phone" and env.payload.channel == "phone"
    assert validate(_env("obs.self_report", {"item": "mood", "value": 4})).payload.channel == "robot"
    with pytest.raises(ContractError):
        validate(_env("obs.self_report", {"item": "mood", "value": 4, "channel": "fax"}))


def test_screen_activity_bounds_and_no_content_fields():
    ok = dict(EXAMPLES["obs.screen_activity"])
    validate(_env("obs.screen_activity", ok, "laptop"))
    for bad in ({**ok, "active_min": 61.0}, {**ok, "window_title": "x"},
                {**ok, "category_min": {**ok["category_min"], "work": 60.0}},
                {**ok, "category_min": {**ok["category_min"], "url": 1}}):
        with pytest.raises(ContractError):
            validate(_env("obs.screen_activity", bad, "laptop"))


def test_wearable_play_outing_bounds():
    validate(_env("obs.wearable_daily", {"date": "2026-11-14", "device": "phone_only", "steps": 100}))
    ok = dict(EXAMPLES["obs.wearable_daily"])
    for bad in ({**ok, "sleep_midpoint_min": 900}, {**ok, "device": "ring"}, {**ok, "raw_samples": []}):
        with pytest.raises(ContractError):
            validate(_env("obs.wearable_daily", bad))
    with pytest.raises(ContractError):
        validate(_env("obs.play_session", {"game": "chess", "device": "phone", "duration_s": 1}))
    with pytest.raises(ContractError):
        validate(_env("obs.outing", {"minutes": 10, "method": "dat_imu", "gait_regularity": 1.5}, "glasses"))


def test_source_map():
    assert "wearable" in CONSENSUS_SOURCES
    assert SOURCE_OF["obs.wearable_daily"] == "wearable"
    assert SOURCE_OF["obs.screen_activity"] == SOURCE_OF["obs.play_session"] == "laptop"


def test_nested_criteria_field_and_conservative_new_metrics():
    c = load_criteria()
    m = c.metric("communication_min")
    assert m.field == "category_min.communication" and m.source == "laptop"
    assert c.sources["wearable"].expected_per_week == 7
    assert all(x.weight == 0.5 for x in c.metrics_for("wearable"))
    raw = tomllib.loads(criteria_path().read_text())
    next(x for x in raw["metric"] if x["name"] == "communication_min")["field"] = "category_min.nope"
    with pytest.raises(ValidationError, match="no field"):
        parse_criteria(raw)


def test_me_response_defaults_are_additive():
    me = MeResponse(home_id="h", summary="s")
    assert me.mascot.mood == "idle" and me.highlights == [] and me.garden.plants == 0


def test_task_camera_requires_provenance_and_rejects_raw_media():
    base = {"game": "firefly", "device": "phone", "duration_s": 60}
    # Not seen is missing, not a zero movement score.
    validate(_env("obs.play_session", {**base, "camera_face_coverage": 0, "camera_samples": 100,
                                       "camera_method": "vision_landmarks"}))
    camera = {**base, "expressivity_index": 0.15, "camera_face_coverage": 0.9,
              "camera_samples": 100, "camera_method": "vision_landmarks"}
    validate(_env("obs.play_session", camera))
    for bad in ({**camera, "camera_method": None}, {**camera, "camera_face_coverage": 0},
                {**camera, "camera_samples": 0}, {**camera, "frames": ["raw"]},
                {**camera, "emotion": "happy"}, {**camera, "audio": "raw"}):
        with pytest.raises(ContractError):
            validate(_env("obs.play_session", bad))
