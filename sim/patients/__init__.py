"""Synthetic 30-day patients across robot, glasses and laptop sources (8 incl. Aino). All `sim: true`.

Scenarios (cloud/kaiku_cloud/jobs/synth.py DEMO_PATIENTS): Aino needs_call (robot + laptop drift, glasses as
usual), stable, noisy-but-fine, robot-only drift (watch), low coverage (watch), PHQ-9 item 9 (safety),
glasses-only drift (watch), improving (stable).

The generator itself lives in kaiku_cloud.jobs.synth because the cloud's cohort evaluation uses the
same model on Modal. sim/ is a dev harness, so importing a module here is allowed.

    uv run python -m sim.patients            # summary of what would be seeded
    uv run python -m sim.patients --jsonl logs/patients.jsonl
"""

from __future__ import annotations

from datetime import date
from typing import Any

from kaiku_cloud.jobs.synth import DEMO_PATIENTS, PatientSpec, generate

__all__ = ["DEMO_PATIENTS", "PatientSpec", "generate", "demo_events"]


def demo_events(end: date | None = None) -> dict[str, list[dict[str, Any]]]:
    """{home_id: [envelope dicts]} for every demo patient."""
    return {p.home_id: generate(p, end=end) for p in DEMO_PATIENTS}
