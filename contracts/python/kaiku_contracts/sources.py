"""Which consensus source each observation counts toward (plan 01 §6.1, §6.3; plan 02 §6).

Four independent sources each get a verdict: robot, glasses, laptop (display label "Apps": Mac app, browser apps
and games on any device), and the optional wearable (Apple Health daily summary). Some observations feed no
verdict (adherence / learner only); safety_flag overrides everything. Mapping is by message type,
so it is deterministic and the same in cloud, sims and tests.
To add a new source (a 4th touchpoint): add it to ConsensusSource + CONSENSUS_SOURCES, map its obs
types here, give it a `[sources.<name>]` block + metrics in config/criteria.toml. Nothing else changes.
"""

from __future__ import annotations

from typing import Any, Literal

ConsensusSource = Literal["robot", "glasses", "laptop", "wearable"]
CONSENSUS_SOURCES: tuple[str, ...] = ("robot", "glasses", "laptop", "wearable")
# Display labels (person + clinician UI). The key "laptop" stays for compatibility; it means "Apps" now.
SOURCE_LABELS: dict[str, str] = {"robot": "Home robot", "glasses": "Glasses", "laptop": "Apps", "wearable": "Watch"}

# obs type -> consensus source | "learner" | "adherence" | "override"
SOURCE_OF: dict[str, str] = {
    "obs.presence": "robot",
    "obs.self_report": "robot",  # whatever the channel (ear, phone, Mac, web, glasses voice): the daily dial
    "obs.hrv_session": "robot",
    "obs.drum_session": "robot",
    "obs.speech_features": "robot",
    "obs.light_level": "robot",
    "obs.friend_link": "robot",
    "obs.outing": "glasses",
    "obs.laptop_session": "laptop",
    "obs.screen_activity": "laptop",
    "obs.play_session": "laptop",  # games on phone, Mac or web all count toward "Apps"
    "obs.wearable_daily": "wearable",
    "obs.phq9": "laptop",  # counts toward laptop wherever it was completed; also the clinical anchor
    "obs.ritual": "adherence",
    "obs.intervention_response": "learner",
    "obs.nudge_offered": "learner",
    "obs.nudge_outcome": "learner",
    "obs.safety_flag": "override",
}


def consensus_source(type_or_env: Any) -> str:
    """Map an obs type (or envelope) to its consensus role. Raises KeyError for unmapped types."""
    t = type_or_env if isinstance(type_or_env, str) else type_or_env.type
    return SOURCE_OF[t]


def types_for(source: str) -> list[str]:
    return [t for t, s in SOURCE_OF.items() if s == source]
