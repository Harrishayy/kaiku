"""Dashboard routes (D34): the week (routines, going well, worth a look) and "What Kaiku has learned" (graph), for the
person and for the care team, plus the person's sharing switch. Registered by api/main.py; logic in week.py."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from kaiku_contracts.api import CareSharing, KnowledgeGraph, WeekSummary

from .. import week
from ..settings import Settings
from ..store.db import Store


def register(app: FastAPI, store: Store, settings: Settings, known_home: Callable[[str], Any]) -> None:
    # ---- person-facing
    @app.get("/v1/me/week", response_model=WeekSummary)
    def me_week(home_id: str) -> WeekSummary:
        """This week in warm words: routines, what went well, what's worth a gentle look. No states or scores."""
        return week.week(store, settings, home_id, "person")

    @app.get("/v1/me/graph", response_model=KnowledgeGraph)
    def me_graph(home_id: str) -> KnowledgeGraph:
        """"What Kaiku has learned": people, places, likes, what helps, activities and routines, with evidence."""
        return week.graph(store, settings, home_id, "person")

    @app.get("/v1/me/sharing", response_model=CareSharing)
    def me_sharing(home_id: str) -> CareSharing:
        return week.sharing(store, home_id)

    @app.put("/v1/me/sharing", response_model=CareSharing)
    def me_set_sharing(home_id: str, body: CareSharing) -> CareSharing:
        """The person's switch: show the care team activities, what helps and routines (default off)."""
        return week.set_sharing(store, home_id, body)

    # ---- care team
    @app.get("/v1/patients/{patient_id}/week", response_model=WeekSummary)
    def patient_week(patient_id: str) -> WeekSummary:
        """Routines from observations (+ conversations only when shared), going well / worth a look from per-metric
        drift, verdicts, the bandit, safety flags and PHQ-9 cadence. Deterministic; never changes the consensus."""
        known_home(patient_id)
        return week.week(store, settings, patient_id, "care_team")

    @app.get("/v1/patients/{patient_id}/graph", response_model=KnowledgeGraph)
    def patient_graph(patient_id: str) -> KnowledgeGraph:
        """Empty with `shared: false` unless the person shares; then activities, what helps and routines only."""
        known_home(patient_id)
        return week.graph(store, settings, patient_id, "care_team")
