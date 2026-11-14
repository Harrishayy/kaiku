#!/usr/bin/env bash
# Record one end-to-end sim run of the robot (no keys, no paid calls) for the progress page / demo replay.
#   scripts/record_robot_demo.sh [OUT_DIR]        default OUT_DIR = demo/recordings/robot-sim (gitignored)
# Starts its own broker + cloud on free ports with a temp DB, seeds the demo cohort, runs the head + sensors twins
# with a scripted person (scripts/robot_demo_driver.py), the hub in text voice, and records:
#   bus.jsonl      every MQTT message (tools/record.py)
#   hub.log        hub stderr, each line prefixed with epoch seconds (spoken lines, context events, JSON logs)
#   markers.jsonl  story moments (approach, greeting, dial, ...) from the driver
#   cloud/*.json   what the cloud saw afterwards (/v1/me, consensus, companion session, intelligence, constellation)
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=${1:-demo/recordings/robot-sim}
BROKER_PORT=${DEMO_BROKER_PORT:-18832}
CLOUD_PORT=${DEMO_CLOUD_PORT:-18010}
HOME_ID=${KAIKU_HOME_ID:-demo-aino}
TMP=$(mktemp -d)
mkdir -p "$OUT/cloud"
OUT=$(cd "$OUT" && pwd)

# Never load the repo .env (real credentials): template LLM, text voice, no music.
export KAIKU_NO_DOTENV=1 KAIKU_LLM=template KAIKU_VOICE=text KAIKU_MUSIC=off PYTHONUNBUFFERED=1
unset GEMINI_API_KEY GOOGLE_API_KEY KAIKU_HOME_TOKEN KAIKU_ADMIN_TOKEN
export MQTT_HOST=127.0.0.1 MQTT_PORT=$BROKER_PORT KAIKU_CLOUD_URL="http://127.0.0.1:$CLOUD_PORT" KAIKU_HOME_ID=$HOME_ID
export KAIKU_DB_PATH="$TMP/cloud.sqlite" KAIKU_SPEND_DB="$TMP/spend.sqlite" KAIKU_HUB_STATE_PATH="$TMP/hub_state.json"
export KAIKU_UPLINK_QUEUE_PATH="$TMP/uplink.sqlite"
# Short, demo-paced ritual; button dial (the knob-out build); faces from the sensors twin, never the webcam.
export KAIKU_ROBOT_DIAL_INPUT=button KAIKU_ATTENTION_FACE_SOURCE=unoq_yolo
export KAIKU_ATTENTION_NIGHT_START=00:00 KAIKU_ATTENTION_NIGHT_END=00:00 KAIKU_ATTENTION_REGREET_H=0
export KAIKU_RITUAL_GREET_S=6 KAIKU_RITUAL_DIAL_S=40 KAIKU_RITUAL_BREATHE_S=60 KAIKU_RITUAL_HRV_WINDOW_S=15
export KAIKU_RITUAL_DRUM_S=34 KAIKU_RITUAL_NUDGE_S=8 KAIKU_RITUAL_POST_MOOD_S=10

PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT
stamp() { perl -MTime::HiRes=time -ne '$|=1; printf "%.3f %s", time, $_'; }

MOSQ=$(command -v mosquitto || ls /opt/homebrew/sbin/mosquitto /usr/local/sbin/mosquitto /usr/sbin/mosquitto 2>/dev/null | head -1)
printf 'listener %s 127.0.0.1\nallow_anonymous true\npersistence false\n' "$BROKER_PORT" >"$TMP/mosq.conf"
"$MOSQ" -c "$TMP/mosq.conf" >"$TMP/broker.log" 2>&1 & PIDS+=($!)

uv run --quiet uvicorn kaiku_cloud.api.main:app --port "$CLOUD_PORT" --log-level warning >"$OUT/cloud.log" 2>&1 & PIDS+=($!)
for _ in $(seq 1 60); do curl -fsS "$KAIKU_CLOUD_URL/healthz" >/dev/null 2>&1 && break; sleep 0.5; done
uv run --quiet python -m sim.seed_demo --reset >"$OUT/seed.log" 2>&1

: >"$OUT/bus.jsonl"
uv run --quiet python tools/record.py 'kaiku/v1/#' -o "$OUT/bus.jsonl" >/dev/null 2>&1 & PIDS+=($!)
mkfifo "$TMP/hub_in"; exec 3<>"$TMP/hub_in"  # keeps the hub's stdin open (text voice) without typing
uv run --quiet python -m kaiku_hub.main <"$TMP/hub_in" > >(stamp >"$OUT/hub.log") 2>&1 & PIDS+=($!)
for _ in $(seq 1 120); do  # wait for the hub (uv start-up can take ~20 s)
  if [[ -s "$OUT/hub.log" && "$(<"$OUT/hub.log")" == *hub_started* ]]; then break; fi; sleep 0.5
done
sleep 2
uv run --quiet python scripts/robot_demo_driver.py --markers "$OUT/markers.jsonl" 2>&1 | stamp >"$OUT/driver.log"
sleep 4  # last uplink batch

# Text voice has no model, so nothing calls tools: ask the mind once like Live would (memory route, no model call).
curl -fsS -X POST "$KAIKU_CLOUD_URL/v1/companion/tool" -H 'content-type: application/json' \
  -d "{\"home_id\":\"$HOME_ID\",\"surface\":\"robot\",\"name\":\"ask_mind\",\"args\":{\"question\":\"What's my sister's name?\",\"kind\":\"memory\"}}" \
  -o "$OUT/cloud/ask_mind.json" || true
get() { curl -fsS "$KAIKU_CLOUD_URL$1" -o "$OUT/cloud/$2.json" || echo "GET $1 failed"; }
curl -fsS -X POST "$KAIKU_CLOUD_URL/v1/admin/recompute" >/dev/null || true
get "/v1/me?home_id=$HOME_ID" me
get "/v1/patients/$HOME_ID/consensus" consensus
get "/v1/patients" patients
get "/v1/me/constellation?home_id=$HOME_ID" constellation
get "/v1/me/memories?home_id=$HOME_ID" memories
get "/v1/health/intelligence?days=1" intelligence
curl -fsS -X POST "$KAIKU_CLOUD_URL/v1/companion/session" -H 'content-type: application/json' \
  -d "{\"home_id\":\"$HOME_ID\",\"surface\":\"robot\",\"intent\":\"ritual\"}" -o "$OUT/cloud/companion_session.json" || true
echo "recorded $(wc -l <"$OUT/bus.jsonl") bus messages -> $OUT"
