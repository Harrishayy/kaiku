"""Seed the cloud with the simulated demo cohort (Aino + 7 others) across all three sources. Idempotent:
event ids are deterministic per patient, and the cloud dedupes by id. Sends the pairing token as Bearer when
KAIKU_HOME_TOKEN is set (and the admin token for reset/recompute when KAIKU_ADMIN_TOKEN is set).

    uv run python -m sim.seed_demo                      # KAIKU_CLOUD_URL or http://localhost:8000
    uv run python -m sim.seed_demo --url https://<modal-url>
    uv run python -m sim.seed_demo --reset              # delete simulated data first, re-anchor to today
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
from kaiku_contracts.config import load_dotenv

from sim.patients import DEMO_PATIENTS, demo_events

BATCH = 200


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=os.environ.get("KAIKU_CLOUD_URL") or "http://localhost:8000")
    ap.add_argument("--reset", action="store_true", help="delete simulated data first (re-anchors history to today)")
    args = ap.parse_args(argv)
    url = args.url.rstrip("/")
    headers = {}
    if os.environ.get("KAIKU_HOME_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['KAIKU_HOME_TOKEN']}"
    admin = {"Authorization": f"Bearer {os.environ['KAIKU_ADMIN_TOKEN']}"} if os.environ.get("KAIKU_ADMIN_TOKEN") else {}

    try:
        httpx.get(f"{url}/healthz", timeout=10).raise_for_status()
    except Exception as e:
        print(f"cloud not reachable at {url}: {e}\n  start it with `make cloud-local` or set KAIKU_CLOUD_URL", file=sys.stderr)
        return 1

    accepted = dupes = 0
    with httpx.Client(timeout=60, headers=headers) as client:
        if args.reset:
            r = client.post(f"{url}/v1/admin/reset", headers=admin)
            r.raise_for_status()
            print(f"reset: deleted {r.json()['deleted']} simulated events")
        for home_id, events in demo_events().items():
            for i in range(0, len(events), BATCH):
                r = client.post(f"{url}/v1/events", json={"events": events[i:i + BATCH]})
                if r.status_code != 200:
                    print(f"{home_id}: HTTP {r.status_code} {r.text[:300]}", file=sys.stderr)
                    return 1
                res = r.json()
                accepted += res["accepted"]
                dupes += res["duplicates"]
                if res["rejected"]:
                    print(f"{home_id}: rejected {res['rejected'][:3]}", file=sys.stderr)
                    return 1
        client.post(f"{url}/v1/admin/recompute", headers=admin).raise_for_status()
        patients = client.get(f"{url}/v1/patients").json()["patients"]

    print(f"seeded {len(DEMO_PATIENTS)} patients: {accepted} new events, {dupes} duplicates (already there)")
    expected = {p.home_id: p.expected_state for p in DEMO_PATIENTS}
    for p in patients:
        mark = "" if expected.get(p["id"], p["state"]) == p["state"] else f"   (expected {expected[p['id']]})"
        print(f"  {p['state']:10} {p['agreement']:12} {p['id']:12} {p['headline']}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
