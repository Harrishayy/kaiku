#!/usr/bin/env bash
# Reset demo state in < 30 s: clear the hub's offline queue, re-seed simulated history, recompute.
# Works against local or Modal cloud (KAIKU_CLOUD_URL). Stop the hub first so its queue isn't in use.
set -euo pipefail
cd "$(dirname "$0")/.."
CLOUD="${KAIKU_CLOUD_URL:-http://localhost:8000}"
echo "resetting demo against $CLOUD"
rm -f logs/uplink_queue.sqlite
uv run --quiet python -m sim.seed_demo --reset   # --reset drops SIMULATED data only, re-anchors history to today
echo "done. Open $CLOUD/clinician/"
