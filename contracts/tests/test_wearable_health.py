"""More of the day from Apple Health on obs.wearable_daily (D53): optional daily totals, never a sleep score; the
six measures that read them are shown and not scored; and the two ways a History value may be read since then
(percent, duration)."""
import tomllib
from typing import get_args

import pytest
from kaiku_contracts import make, validate
from kaiku_contracts.api import HistoryFormat, HistoryMeasure, HistorySession, HistoryValue
from kaiku_contracts.criteria import criteria_path, load_criteria, parse_criteria
from kaiku_contracts.payloads import WearableDaily
from kaiku_contracts.registry import EXAMPLES
from pydantic import ValidationError

NEW = ("distance_km", "daylight_min", "walking_hr_bpm", "sleep_deep_min", "sleep_rem_min", "sleep_core_min",
       "sleep_awake_min")
HEALTH = ("day_distance", "day_daylight", "walking_hr", "deep_sleep", "rem_sleep", "awake_night")
VOTING = ("watch_sleep", "sleep_midpoint", "resting_hr", "hrv_sdnn", "daily_steps")
EXAMPLE = EXAMPLES["obs.wearable_daily"]


def _raw():
    return tomllib.loads(criteria_path().read_text())


def test_the_new_fields_are_optional_and_an_older_summary_is_still_valid():
    assert set(NEW) <= set(EXAMPLE)
    full = WearableDaily.model_validate(EXAMPLE)
    assert full.sleep_deep_min + full.sleep_rem_min + full.sleep_core_min == full.sleep_min  # stages of that night
    older = {k: v for k, v in EXAMPLE.items() if k not in NEW}
    was = WearableDaily.model_validate(older)
    assert all(getattr(was, name) is None for name in NEW)  # absent stays absent: never a zero in its place
    env = make("obs.wearable_daily", EXAMPLE, source="phone", sim=True)
    assert validate(env.model_dump(mode="json", exclude_none=True)).payload == full
    phone_only = WearableDaily.model_validate({"date": "2026-11-14", "steps": 5200, "distance_km": 3.54,
                                               "device": "phone_only"})
    assert phone_only.daylight_min is None and phone_only.sleep_deep_min is None
    # a night with stages may have none of one of them: 0 is a value, absent is absent
    WearableDaily.model_validate({**EXAMPLE, "sleep_deep_min": 0.0})


@pytest.mark.parametrize("bad", [
    {"distance_km": -0.1}, {"distance_km": 301}, {"daylight_min": -1}, {"daylight_min": 1441},
    {"walking_hr_bpm": 20}, {"walking_hr_bpm": 250}, {"sleep_deep_min": -1}, {"sleep_rem_min": 1441},
    {"sleep_core_min": -5}, {"sleep_awake_min": 1500},
])
def test_out_of_range_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        WearableDaily.model_validate({**EXAMPLE, **bad})


@pytest.mark.parametrize("field", ["sleep_score", "sleep_quality", "readiness", "stress", "samples", "heart_rate_series",
                                   "route", "location", "workouts"])
def test_there_is_no_score_no_raw_sample_and_no_place(field):
    """Apple gives apps no sleep score, so there is no field for one; and only daily totals may travel."""
    assert field not in WearableDaily.model_fields
    with pytest.raises(ValidationError):
        WearableDaily.model_validate({**EXAMPLE, field: 80})


def test_the_six_health_measures_are_shown_and_the_five_keep_voting_as_before():
    c = load_criteria()
    mine = [c.metric(name) for name in HEALTH]
    assert [m.field for m in mine] == ["distance_km", "daylight_min", "walking_hr_bpm", "sleep_deep_min",
                                       "sleep_rem_min", "sleep_awake_min"]
    for m in mine:
        assert m.obs == "obs.wearable_daily" and m.source == "wearable" and m.role == "shown" and m.enabled, m.name
        assert not m.votes and m.day_field == "date" and m.agg == "last" and not m.counts_for_better, m.name
        assert c.param(m, "z_threshold") == 2.0 and c.param(m, "min_mad") > 0 and not m.person_hard, m.name
    assert [m.name for m in c.shown_for("wearable")] == list(HEALTH)
    assert [m.name for m in c.metrics_for("wearable")] == list(VOTING)  # what the Watch verdict reads: unchanged
    assert all(c.metric(name).weight == 0.5 and c.metric(name).votes for name in VOTING)
    # the summary still counts as Watch data (scored measures read it): only a type nothing scored reads adds no coverage
    assert "obs.wearable_daily" not in c.shown_types
    # even with every role line deleted, the new measures alone could not turn the group worse
    assert sum(m.weight for m in mine) < c.sources["wearable"].worse_min_weight
    # no direction that could be argued: no vote even without the role line
    assert {m.name for m in mine if m.weight == 0} == {"day_distance", "walking_hr", "rem_sleep"}
    assert "sleep_core_min" not in {m.field for m in c.metrics}  # stored and listed for the person, read by no metric


def test_adding_them_changed_no_hash_and_one_line_would():
    c = load_criteria()
    assert c.rule_version == "consensus-v1+db93b715"
    raw = _raw()
    raw["metric"] = [m for m in raw["metric"] if m["name"] not in HEALTH]
    assert parse_criteria(raw).rule_version == c.rule_version
    one_line = _raw()
    del next(m for m in one_line["metric"] if m["name"] == "deep_sleep")["role"]
    voting = parse_criteria(one_line)
    assert voting.rule_version != c.rule_version and voting.metric("deep_sleep").votes
    assert voting.metric("deep_sleep") in voting.metrics_for("wearable")
    still = _raw()
    del next(m for m in still["metric"] if m["name"] == "rem_sleep")["role"]
    assert not parse_criteria(still).metric("rem_sleep").votes  # weight 0: charted, never a vote, role line or not


def test_history_values_may_be_a_percent_or_a_duration_and_stay_plain_numbers_on_the_wire():
    assert get_args(HistoryFormat) == ("number", "clock", "percent", "duration")
    share = HistoryValue(key="smile_share", title="Smiling", value=0.14, unit="of the time", format="percent")
    assert share.value == 0.14  # the share itself travels; the app writes 14 %
    night = HistoryValue(key="sleep_min", title="Sleep", value=440.0, format="duration")
    assert night.unit == "" and night.value == 440.0  # minutes travel; the app writes 7 h 20 min
    assert HistoryMeasure.model_fields["format"].annotation is HistoryFormat
    HistorySession.model_validate({"id": "x", "ts": "2026-11-14T06:00:00Z", "device": "watch",
                                   "values": [night.model_dump()] * 16})
    with pytest.raises(ValidationError):
        HistoryValue(key="k", title="t", value=1.0, format="score")
