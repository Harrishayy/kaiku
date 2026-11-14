#!/usr/bin/env bash
# Real Gemini Live end-to-end check of the app's conversation client (paid: one short Live session, ~1 min).
# Starts a throwaway local cloud with the repo .env (GEMINI_API_KEY), seeds demo-aino, makes a spoken
# interruption with macOS `say`, and runs LiveIntegrationTests: setup accepted → Kaiku speaks → the person cuts in
# (barge-in → `interrupted`) → asks a memory question → ask_mind/recall answered by the cloud mind → Kaiku answers.
# The run is stored as an opt-in transcript and exported de-identified (gemma_train.jsonl) — synthetic persona only.
# Evidence → demo/recordings/live-e2e/<surface>/ (events.jsonl, kaiku.wav, person.wav, transcript.json,
# gemma_train.jsonl, tools.txt, cloud.log). Gitignored.
# Usage: apps/apple/scripts/live_e2e.sh [iphone|glasses]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SURFACE="${1:-iphone}"
PORT="${KAIKU_LIVE_PORT:-18040}"
OUT="$ROOT/demo/recordings/live-e2e/$SURFACE"
TMP="$(mktemp -d)"
mkdir -p "$OUT"
cd "$ROOT"

export KAIKU_DB_PATH="$TMP/kaiku.db"
uv run --package kaiku-cloud uvicorn kaiku_cloud.api.local:app --port "$PORT" >"$OUT/cloud.log" 2>&1 &
CLOUD=$!
trap 'kill $CLOUD 2>/dev/null || true; rm -rf "$TMP"' EXIT
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null && break; sleep 0.5; done
KAIKU_CLOUD_URL="http://127.0.0.1:$PORT" uv run python -m sim.seed_demo --reset >/dev/null

say -v Samantha -r 165 -o "$TMP/cut.aiff" "Kaiku, wait a second. Where do I like to go walking? Do you remember?"
afconvert -f WAVE -d LEI16@16000 -c 1 "$TMP/cut.aiff" "$TMP/cut.wav"
uv run python -I -c 'import sys,wave; w=wave.open(sys.argv[1]); open(sys.argv[2],"wb").write(w.readframes(w.getnframes()))' \
  "$TMP/cut.wav" "$TMP/cut.pcm"
cp "$TMP/cut.wav" "$OUT/person.wav"

cd "$ROOT/apps/apple/KaikuKit"
KAIKU_LIVE_TEST_CLOUD="http://127.0.0.1:$PORT" KAIKU_LIVE_TEST_SPEECH="$TMP/cut.pcm" KAIKU_LIVE_TEST_OUT="$OUT" \
KAIKU_LIVE_TEST_SURFACE="$SURFACE" swift test --filter LiveIntegrationTests 2>&1 | tee "$OUT/test.log" | \
  grep -E "error:|passed|failed|skipped" || true
cd "$ROOT"
uv run --package kaiku-cloud python -m kaiku_cloud.jobs.transcripts_export "$OUT/gemma_train.jsonl" 2>&1 | tail -1
echo "evidence: $OUT"
