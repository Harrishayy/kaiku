#!/usr/bin/env bash
# Record the practitioner dashboard as an MP4 against a throwaway cloud seeded with the one person (Aino).
#   scripts/record_web_demo.sh [OUT_DIR] [record_web_demo.py options]    default demo/recordings (gitignored)
# No keys, template LLM, temp DB, own port: runs beside other dev servers. To record a service that is already
# running (read-only, no model calls), call the Python script directly:
#   uv run --with playwright python scripts/record_web_demo.py --url http://127.0.0.1:8000/?id=aino
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${1:-demo/recordings}; shift || true
PORT=${DEMO_WEB_CLOUD_PORT:-18011}
TMP=$(mktemp -d)
export KAIKU_NO_DOTENV=1 KAIKU_LLM=template KAIKU_VOICE=text KAIKU_DEMO_MODE=1 KAIKU_DB_PATH="$TMP/cloud.sqlite"
unset GEMINI_API_KEY GOOGLE_API_KEY KAIKU_HOME_TOKEN KAIKU_ADMIN_TOKEN
URL="http://127.0.0.1:$PORT"
[ -f apps/web/out/index.html ] || make web-build
uv run --quiet uvicorn kaiku_cloud.api.main:app --port "$PORT" --log-level warning >"$TMP/cloud.log" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null || true; rm -rf "$TMP"' EXIT
for _ in $(seq 1 60); do curl -fsS "$URL/healthz" >/dev/null 2>&1 && break; sleep 0.5; done
uv run --quiet python -m kaiku_cloud.jobs.single_person --url "$URL" >/dev/null
uv run --quiet --with playwright python scripts/record_web_demo.py --url "$URL" --out "$OUT" "$@"
