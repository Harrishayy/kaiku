"""Immediate and next-day feedback must not turn one nudge attempt into two displayed tries."""
import pytest
from kaiku_cloud.analytics import bandit


def response(activity="walk"):
    return {"activity": activity, "pre": {"mood": 3}, "post": {"mood": 4}, "delta": {"mood": 1}}


def accepted(arm="daylight_walk"):
    return {"arm": arm, "accepted": True, "next_day": {"mood": 4, "energy": 4}}


def test_paired_feedback_uses_outcome_attempt_count_and_preserves_reward():
    outcomes, responses = [accepted()] * 9, [response()] * 9
    posterior = bandit.posteriors(outcomes, responses)["daylight_walk"]
    row = bandit.help_stats(outcomes, responses)[0]
    assert row["tries"] == 9
    assert row["mean_effect"] == pytest.approx(.75)
    assert row["mean_effect"] == pytest.approx((posterior[0]-1)/posterior[2])


def test_declines_are_attempts_and_do_not_need_an_immediate_response():
    rows = bandit.help_stats([accepted(), {"arm": "daylight_walk", "accepted": False}], [response()])
    assert rows[0]["tries"] == 2
    assert rows[0]["mean_effect"] == pytest.approx(.375)


def test_missing_immediate_half_uses_nudge_count_and_next_day_reward():
    row = bandit.help_stats([accepted()], [])[0]
    assert row["tries"] == 1 and row["mean_effect"] == pytest.approx(.75)


def test_missing_outcome_half_uses_response_count_and_immediate_reward():
    row = bandit.help_stats([], [response(), response()])[0]
    assert row["tries"] == 2 and row["mean_effect"] == pytest.approx(.75)


def test_mixed_unlinked_responses_do_not_invent_exact_pairing_or_extra_attempts():
    # The contract has no nudge/response link. One outcome plus five response records cannot prove six attempts.
    outcomes = [accepted(), {"arm": "daylight_walk", "accepted": False}]
    responses = [response()] * 5 + [response("breathe")] * 2
    by = {row["activity"]: row for row in bandit.help_stats(outcomes, responses)}
    assert by["walk"]["tries"] == 2  # Completed/declined outcomes take precedence for this activity.
    assert by["breathe"]["tries"] == 2  # Response-only activities still have a truthful fallback count.
