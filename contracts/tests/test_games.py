"""obs.play_session for the research-inspired games (lantern, seeds, watering): examples validate, bounds hold,
no content fields, and the criteria count them conservatively (warm-up sessions excluded, low weights)."""

import pytest
from kaiku_contracts import SOURCE_OF, ContractError, validate
from kaiku_contracts.criteria import load_criteria
from kaiku_contracts.registry import PLAY_EXAMPLES

GAME_METRICS = ("lantern_speed", "lantern_variability", "seeds_throughput", "pebble_span", "watering_effort")


def _env(payload, source="phone", **kw):
    return {"home_id": "demo-aino", "source": source, "type": "obs.play_session", "payload": payload, **kw}


@pytest.mark.parametrize("name", sorted(PLAY_EXAMPLES))
def test_examples_validate_and_round_trip(name):
    env = validate(_env(PLAY_EXAMPLES[name], quality=0.9))
    assert env.payload.model_dump(mode="json", exclude_none=True) == PLAY_EXAMPLES[name]
    assert env.quality == 0.9


def test_trial_record_matches_trial_count():
    for name in ("lantern", "watering"):
        p = PLAY_EXAMPLES[name]
        assert len(p["rt_ms"]) == len(p["trial_codes"]) == p["trials_n"]


def test_bounds_and_no_content_fields():
    ok = PLAY_EXAMPLES["lantern"]
    for bad in ({**ok, "rt_ms": [20_000]}, {**ok, "rt_ms": [-1]}, {**ok, "rt_ms": [300] * 121},
                {**ok, "trial_codes": "h h"}, {**ok, "flags": ["cheated"]}, {**ok, "input": "voice"},
                {**ok, "response_speed": 11}, {**ok, "hard_choice_ratio": 1.2}, {**ok, "session_index": 0},
                {**ok, "transcript": "x"}, {**ok, "words": ["sad"]}):
        with pytest.raises(ContractError):
            validate(_env(bad))
    # older apps keep working: the first games carry none of the new fields
    validate(_env({"game": "pebbles", "device": "phone", "duration_s": 61, "span_max": 5, "accuracy": 0.8}))


def test_game_metrics_are_conservative():
    c = load_criteria()
    assert SOURCE_OF["obs.play_session"] == "laptop"
    for name in GAME_METRICS:
        m = c.metric(name)
        assert m.obs == "obs.play_session" and m.family in ("cognition", "motivation")
        assert m.where.get("warmup") is False, f"{name} must skip warm-up sessions (practice effects)"
        assert m.weight <= 0.5 and (m.baseline_min_days or 0) >= 5
        assert not m.person_hard, f"{name}: a game never tells the person they did badly"
    # one game alone can never turn the Apps source "worse": its metrics together stay under the threshold
    need = c.sources["laptop"].worse_min_weight
    for game in ("lantern", "seeds", "pebbles", "watering"):
        total = sum(m.weight for m in c.metrics_for("laptop") if m.where.get("game") == game)
        assert total < need, f"{game}: {total} >= {need}"
