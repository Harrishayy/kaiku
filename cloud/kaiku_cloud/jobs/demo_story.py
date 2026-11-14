"""Export reproducible, wholly synthetic demo trajectories without reading any existing database.

Run: uv run python -m kaiku_cloud.jobs.demo_story --out /private/tmp/kaiku-demo-story
events.jsonl can be posted in batches to an isolated demo API. report.json is calculated by the real
monitoring/week code, never a hard-coded AI success story. A single poor task must not equal a state change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from kaiku_contracts import validate

from .. import service, week
from ..settings import TZ, Settings
from ..store.db import Store
from .synth import PatientSpec, generate

PROFILES = (
    PatientSpec("story-improving", 18, "Repeated improving measurements", improving=True, onset=17),
    PatientSpec("story-changing", 11, "Sustained change in several signal groups",
                drift=frozenset({"robot", "laptop", "wearable"}), onset=17),
    PatientSpec("story-missing", 15, "Only one signal group; insufficient coverage",
                present=frozenset({"robot"})),
    PatientSpec("story-outlier", 12, "One slow reaction task; other measurements remain usual"),
)


def events(end: date) -> list[dict]:
    rows = []
    for profile in PROFILES:
        for row in generate(profile, end):
            # Cohort seeds also exist in the standard demo. UUIDs are globally unique across households,
            # so a copied seed must never cause another profile's observations to be ignored on ingestion.
            row["id"] = str(uuid5(NAMESPACE_URL, f"kaiku-story:{profile.home_id}:{end}:{row['id']}"))
            rows.append(row)
        # Separate fixture identity stream: enriching the demo never perturbs the underlying cohort RNG.
        for back in range(8):
            day = end - timedelta(days=back)
            slow = profile.home_id == "story-outlier" and back == 0
            payload = {"game": "firefly", "device": "phone", "duration_s": 60,
                       "reaction_ms_median": 850 if slow else 320,
                       "reaction_ms_iqr": 180 if slow else 55, "lapses": 7 if slow else 1}
            env = validate({"id": str(uuid5(NAMESPACE_URL, f"kaiku-story:{profile.home_id}:{day}:task")),
                            "ts": datetime.combine(day, time(18), TZ).astimezone(UTC),
                            "home_id": profile.home_id, "source": "phone", "type": "obs.play_session",
                            "payload": payload, "quality": 0.9, "sim": True})
            # A missing-source story must not silently acquire Apps evidence through fixture enrichment.
            if "laptop" in profile.present:
                rows.append(env.model_dump(mode="json", exclude_none=True))
    return sorted(rows, key=lambda r: (r["ts"], r["id"]))


def report(rows: list[dict], end: date) -> dict:
    store = Store(":memory:")
    store.insert_events(rows)
    settings = Settings(db_path=":memory:", demo_mode=True, llm="template", home_tokens={},
                        home_token=None, admin_token=None, clinician_token=None)
    now = datetime.combine(end + timedelta(days=1), time(0, 1), TZ)
    stories = []
    for profile in PROFILES:
        row = service.recompute_home(store, settings, profile.home_id, today=end)
        summary = week.week(store, settings, profile.home_id, "care_team", now=now)
        stories.append({"home_id": profile.home_id, "synthetic": True, "scenario": profile.scenario,
                        "state": row["summary"]["state"], "sources": row["summary"]["sources"],
                        "week": summary.model_dump(mode="json"),
                        "events": sum(e["home_id"] == profile.home_id for e in rows)})
    return {"synthetic": True, "measured_through": str(end), "rule_version": service.active_criteria(store).rule_version,
            "event_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            "stories": stories,
            "limits": ["Synthetic demonstration, not clinical validation or treatment efficacy.",
                       "A slow task alone does not establish deterioration; more samples and context are needed.",
                       "Camera movement is observational; missing capture is unknown, not zero expression.",
                       "An outing record does not establish outdoor location or a connected glasses camera."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--end", type=date.fromisoformat, default=datetime.now(TZ).date() - timedelta(days=1))
    args = parser.parse_args()
    rows = events(args.end)
    result = report(rows, args.end)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in rows))
    (args.out / "report.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"out": str(args.out), "events": len(rows),
                      "states": {s["home_id"]: s["state"] for s in result["stories"]}}))


if __name__ == "__main__":
    main()
