"""The measured games (lantern, seeds, watering, pebbles) in the metric pipeline: warm-up sessions and doubtful
sessions never count; a valid session lands in its metric's daily series."""

from datetime import UTC, datetime, timedelta

from kaiku_cloud.analytics.metrics import daily_metrics
from kaiku_contracts import make
from kaiku_contracts.criteria import load_criteria
from kaiku_contracts.registry import PLAY_EXAMPLES


def _event(payload: dict, day: int, quality: float | None = None) -> dict:
    ts = datetime(2026, 11, 1, 15, 0, tzinfo=UTC) + timedelta(days=day)
    return make("obs.play_session", payload, source="phone", home_id="t", quality=quality, ts=ts).model_dump(mode="json")


def test_valid_sessions_count_warmup_and_doubtful_do_not():
    crit = load_criteria()
    lantern = PLAY_EXAMPLES["lantern"]
    events = [
        _event({**lantern, "session_index": 2, "warmup": True, "response_speed": 1.0}, day=0, quality=1.0),  # warm-up
        _event({**lantern, "response_speed": 3.2}, day=1, quality=0.96),
        _event({**lantern, "response_speed": 9.0, "valid": False, "flags": ["few_trials"]}, day=1, quality=0.2),  # doubtful
        _event({**lantern, "response_speed": 3.0, "reaction_ms_cv": 0.25}, day=2),
        _event({**PLAY_EXAMPLES["seeds"]}, day=2, quality=0.95),
        _event({**PLAY_EXAMPLES["watering"]}, day=2, quality=1.0),                                           # warm-up
        _event({**PLAY_EXAMPLES["watering"], "warmup": False, "session_index": 5}, day=3, quality=1.0),
        _event({"game": "pebbles", "device": "phone", "duration_s": 70, "span_max": 6, "accuracy": 0.9,
                "warmup": False, "valid": True, "session_index": 4}, day=3, quality=1.0),
        _event({"game": "pebbles", "device": "phone", "duration_s": 70, "span_max": 5, "accuracy": 0.8}, day=4),  # old app
    ]
    series = daily_metrics(events, crit)
    speed = sorted(series["lantern_speed"].items())
    assert [v for _, v in speed] == [3.2, 3.0]                   # day 0 (warm-up) and the doubtful 9.0 are not there
    assert sorted(series["lantern_variability"].values()) == [0.19, 0.25]
    assert list(series["seeds_throughput"].values()) == [26.0]
    assert list(series["watering_effort"].values()) == [0.625]   # only the non-warm-up session
    assert list(series["pebble_span"].values()) == [6.0]         # a session without warmup=false does not count
    # the games never touch the older firefly metric
    assert "firefly_reaction" not in series
