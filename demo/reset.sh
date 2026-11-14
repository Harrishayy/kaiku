#!/usr/bin/env bash
# Reset in < 30 s: clear the hub's offline queue, drop simulated data on the local API and seed Aino's sixteen
# days again so they end yesterday. Live recordings (sim: false) stay. Stop the hub first so its queue is free.
# Port: KAIKU_DEMO_PORT (default 8000). Starts the API/broker if they are not running.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -f logs/uplink_queue.sqlite
KAIKU_DEMO_ONCE="${KAIKU_DEMO_ONCE-1}" exec ./scripts/demo.sh --reset
