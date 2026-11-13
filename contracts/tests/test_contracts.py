import json
from datetime import UTC, datetime

import pytest
from kaiku_contracts import (
    EXAMPLES,
    REGISTRY,
    UPLINKABLE,
    ContractError,
    example,
    make,
    parse_topic,
    to_json,
    topic_for,
    uuid7,
    validate,
)
from kaiku_contracts.export import main as export_main
from kaiku_contracts.payloads import DrumSession


@pytest.mark.parametrize("type_", sorted(REGISTRY))
def test_every_type_round_trips(type_):
    env = example(type_)
    text = to_json(env)
    again = validate(text)
    assert again == env
    assert again.payload.model_dump(mode="json", exclude_none=True) == EXAMPLES[type_]
    # topic derivation is reversible
    assert parse_topic(topic_for(env)).type == type_
    assert parse_topic(topic_for(env)).home_id == env.home_id


def test_make_with_model_and_topic():
    env = make("obs.drum_session", DrumSession(tempo_bpm=96, force_mean=0.5, duration_s=40, regularity=0.8, taps=60),
               source="hub", home_id="demo-aino")
    assert topic_for(env) == "kaiku/v1/demo-aino/obs/drum_session"
    assert env.v == 1 and env.id.version == 7


def test_raw_topic_uses_type_not_source():
    env = make("raw.head.tap", {"t_ms": 1, "force": 1.0}, source="head", sim=True)
    assert topic_for(env).endswith("/raw/head/tap")
    h = make("health", EXAMPLES["health"], source="sensors")
    assert topic_for(h).endswith("/health/sensors")


def test_ts_is_utc_millis_z():
    env = make("obs.self_report", {"item": "mood", "value": 3}, source="hub", ts=datetime(2026, 11, 14, 8, 12, 3, 120456, tzinfo=UTC))
    assert json.loads(to_json(env))["ts"] == "2026-11-14T08:12:03.120Z"


@pytest.mark.parametrize(
    "type_,payload",
    [
        ("obs.self_report", {"item": "mood", "value": 9}),
        ("obs.self_report", {"item": "mood", "value": 3, "extra_field": 1}),
        ("obs.self_report", {"item": "hunger", "value": 3}),
        ("obs.phq9", {"total": 5, "items": [1, 1, 1, 1, 1, 1, 1, 0, 0], "item9_positive": False, "mode": "laptop"}),
        ("obs.phq9", {"total": 1, "items": [0, 0, 0, 0, 0, 0, 0, 0, 1], "item9_positive": False, "mode": "laptop"}),
        ("obs.mood_dial", {"value": 3}),
        ("obs.checkin", {"phq9_total": 3, "item9_positive": False}),
        ("cmd.head", {}),
        ("cmd.hub", {"set_ritual_time": "25:00"}),
        ("obs.does_not_exist", {}),
    ],
)
def test_invalid_payloads_rejected(type_, payload):
    with pytest.raises(ContractError):
        make(type_, payload, source="hub")


def test_envelope_rejects_unknown_source_and_bad_home():
    with pytest.raises(ContractError):
        validate({"home_id": "demo", "source": "toaster", "type": "obs.self_report", "payload": {"item": "mood", "value": 3}})
    with pytest.raises(ContractError):
        validate({"home_id": "Bad Home!", "source": "hub", "type": "obs.self_report", "payload": {"item": "mood", "value": 3}})


def test_only_obs_uplinkable():
    assert all(t.startswith("obs.") for t in UPLINKABLE)
    assert "raw.hub.face" not in UPLINKABLE


def test_uuid7_is_time_ordered():
    ids = [uuid7() for _ in range(50)]
    assert all(u.version == 7 for u in ids)
    assert [u.int >> 80 for u in ids] == sorted(u.int >> 80 for u in ids)


def test_schemas_on_disk_are_current():
    assert export_main(["--check"]) == 0, "run `make contracts` and commit contracts/schemas"


def test_every_obs_type_has_a_consensus_role():
    from kaiku_contracts import OBS, SOURCE_OF

    assert set(OBS) == set(SOURCE_OF), "map every obs type in kaiku_contracts/sources.py"
    assert set(SOURCE_OF.values()) <= {"robot", "glasses", "laptop", "wearable", "learner", "adherence", "override"}


def test_api_consensus_round_trip():
    from datetime import UTC, datetime

    from kaiku_contracts.api import Consensus

    c = Consensus.model_validate({
        "home_id": "demo-aino", "state": "needs_call", "rule_version": "consensus-v1", "agreement": "disagree",
        "computed_at": datetime.now(UTC),
        "sources": [{"home_id": "demo-aino", "source": "robot", "verdict": "worse", "confidence": 0.9,
                     "evidence": [{"metric": "rmssd", "z": -2.1, "direction": "down", "days": 4}],
                     "computed_at": datetime.now(UTC)}],
    })
    assert Consensus.model_validate_json(c.model_dump_json()) == c
