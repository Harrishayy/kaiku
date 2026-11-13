"""Seed the cloud with the simulated demo cohort (Aino + 7 others) across all three sources. Idempotent:
event ids are deterministic per patient, and the cloud dedupes by id. Sends the pairing token as Bearer when
KAIKU_HOME_TOKEN is set (and the admin token for reset/recompute when KAIKU_ADMIN_TOKEN is set).
Also gives Aino a few memories, three Tuesday walks and an open thread (through the real companion endpoints), so
the demo context card reads "the lake, like we said".

    uv run python -m sim.seed_demo                      # KAIKU_CLOUD_URL or http://localhost:8000
    uv run python -m sim.seed_demo --url https://<modal-url>
    uv run python -m sim.seed_demo --reset              # delete simulated data first, re-anchor to today
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta

import httpx
from kaiku_contracts.config import load_dotenv

from sim.patients import DEMO_PATIENTS, demo_events

BATCH = 200
DEMO_HOME = "demo-aino"
AINO_MEMORIES = [("name", "Aino"), ("people", "Her sister is Maija"), ("places", "Likes walking by the lake"),
                 ("what_helps", "A cup of tea on the balcony helps"), ("likes", "Loves the smell of rain")]
AINO_THREAD = {"skill": "walk_companion", "topic": "the walk by the lake"}


def seed_companion(client: httpx.Client, url: str, now: datetime | None = None) -> None:
    """Aino's notebook: memories via the tool endpoint (same rules as a live chat), 3 Tuesday walks (routine) and a
    thread left open by yesterday's robot ritual. Idempotent (memories dedupe; episode ids are fixed per date)."""
    now = now or datetime.now(UTC)
    for category, text in AINO_MEMORIES:
        r = client.post(f"{url}/v1/companion/tool", json={"home_id": DEMO_HOME, "surface": "iphone",
                                                          "name": "remember",
                                                          "args": {"category": category, "text": text}})
        r.raise_for_status()
    last_tue = now - timedelta(days=(now.weekday() - 1) % 7 or 7)
    eps = [{"id": f"seed-walk-{(last_tue - timedelta(days=7 * k)).date()}", "surface": "glasses", "intent": "walk",
            "start": (last_tue - timedelta(days=7 * k)).replace(hour=15, minute=0).isoformat(),
            "end": (last_tue - timedelta(days=7 * k)).replace(hour=15, minute=25).isoformat(),
            "tools_used": ["start_activity", "log_walk_moment"], "outcome": "completed"} for k in range(3)]
    y = now - timedelta(days=1)
    eps.append({"id": f"seed-ritual-{y.date()}", "surface": "robot", "intent": "ritual",
                "start": y.replace(hour=6, minute=30).isoformat(), "end": y.replace(hour=6, minute=36).isoformat(),
                "tools_used": ["record_dial", "start_activity", "end_session"], "outcome": "completed",
                "open_thread": AINO_THREAD})
    for ep in eps:
        client.post(f"{url}/v1/companion/episode", json={"home_id": DEMO_HOME, **ep}).raise_for_status()


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
        seed_companion(client, url)
        patients = client.get(f"{url}/v1/patients").json()["patients"]

    print(f"seeded {len(DEMO_PATIENTS)} patients: {accepted} new events, {dupes} duplicates (already there)")
    expected = {p.home_id: p.expected_state for p in DEMO_PATIENTS}
    for p in patients:
        mark = "" if expected.get(p["id"], p["state"]) == p["state"] else f"   (expected {expected[p['id']]})"
        print(f"  {p['state']:10} {p['agreement']:12} {p['id']:12} {p['headline']}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
