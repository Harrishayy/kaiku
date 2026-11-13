"""Regressions found in the end-to-end run (2026-11-13)."""

import tomllib
from datetime import UTC, datetime
from pathlib import Path

from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_contracts.criteria import criteria_path


def test_synthetic_history_is_never_in_the_future():
    now = datetime.now(UTC)
    for spec in DEMO_PATIENTS:
        for e in generate(spec):
            assert datetime.fromisoformat(e["ts"].replace("Z", "+00:00")) <= now, (spec.home_id, e["ts"])


def test_preview_disabling_a_source_only_lists_real_changes(client):
    events = [e for spec in DEMO_PATIENTS for e in generate(spec)]
    for i in range(0, len(events), 500):
        assert client.post("/v1/events", json={"events": events[i:i + 500]}).status_code == 200
    raw = tomllib.loads(Path(criteria_path()).read_text())
    raw["sources"]["glasses"]["enabled"] = False
    r = client.post("/v1/admin/criteria/preview", json={"criteria": raw})
    assert r.status_code == 200, r.text
    body = r.json()
    for c in body["changes"]:
        common = c["from_sources"].keys() & c["to_sources"].keys()
        assert c["from_state"] != c["to_state"] or any(c["from_sources"][k] != c["to_sources"][k] for k in common), c
    assert body["unchanged"] >= 1
