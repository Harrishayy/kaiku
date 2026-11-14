#!/usr/bin/env bash
# Record the web app (/me, /clinician, patient view, /play/firefly) as MP4s against a throwaway seeded cloud.
#   scripts/record_web_demo.sh [OUT_DIR]     default demo/recordings (gitignored). No keys, template LLM.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${1:-demo/recordings}; shift || true
PORT=${DEMO_WEB_CLOUD_PORT:-18011}
TMP=$(mktemp -d)
export KAIKU_NO_DOTENV=1 KAIKU_LLM=template KAIKU_DB_PATH="$TMP/cloud.sqlite" KAIKU_CLOUD_URL="http://127.0.0.1:$PORT"
unset GEMINI_API_KEY GOOGLE_API_KEY KAIKU_HOME_TOKEN KAIKU_ADMIN_TOKEN
[ -f apps/web/out/index.html ] || make web-build
uv run --quiet uvicorn kaiku_cloud.api.main:app --port "$PORT" --log-level warning >"$TMP/cloud.log" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null || true; rm -rf "$TMP"' EXIT
for _ in $(seq 1 60); do curl -fsS "$KAIKU_CLOUD_URL/healthz" >/dev/null 2>&1 && break; sleep 0.5; done
uv run --quiet python -m sim.seed_demo --reset >/dev/null
uv run --quiet --with playwright==1.58.0 python scripts/record_web_demo.py --base "$KAIKU_CLOUD_URL" --out "$OUT" "$@"
