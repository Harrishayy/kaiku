#!/usr/bin/env bash
# One command to a full dashboard: broker + local API (serving the built dashboard) + Aino's sixteen-day record.
#   make demo                 start what is not running yet, seed, print the links, stay up (Ctrl-C stops what it started)
#   make demo-reset           drop simulated data on that API and seed again (live recordings stay)
# Safe to run twice: a healthy API or broker that is already up is reused, and seeding adds nothing the second time.
# Options (env): KAIKU_DEMO_PORT=8000  KAIKU_DEMO_MQTT_PORT=1883  KAIKU_DB_PATH=logs/kaiku.sqlite
#                KAIKU_DEMO_ONCE=1 (seed, print, exit: for scripts)  KAIKU_DEMO_SKIP_WEB=1 (do not build the dashboard)
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${KAIKU_DEMO_PORT:-8000}"
MQTT_PORT="${KAIKU_DEMO_MQTT_PORT:-1883}"
RESET="${1:-}"
URL="http://127.0.0.1:$PORT"
LOGS="logs/demo"
mkdir -p "$LOGS"
STARTED=()

say()  { printf '%s\n' "$*"; }
fail() { printf '\n✗ %s\n' "$1" >&2; shift; for line in "$@"; do printf '  %s\n' "$line" >&2; done; exit 1; }
listening() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
cleanup() {
  if [ "${#STARTED[@]}" -gt 0 ]; then
    for pid in "${STARTED[@]}"; do kill "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

command -v uv >/dev/null || fail "uv is not installed." "Install it: curl -LsSf https://astral.sh/uv/install.sh | sh   (or: make bootstrap)"
command -v curl >/dev/null || fail "curl is not installed."
[ -d .venv ] || fail "Python dependencies are not installed yet." "Run: make setup"
[ -f .env ] || say "· no .env yet: running without model keys (voice and Gemma use their built-in fallbacks). \`make env\` creates one."

# ---------------------------------------------------------------- 1. broker (only the robot and its twins need it)
if listening "$MQTT_PORT"; then
  say "✓ MQTT broker already on :$MQTT_PORT"
else
  MOSQUITTO="$(command -v mosquitto 2>/dev/null || ls /opt/homebrew/sbin/mosquitto /usr/local/sbin/mosquitto /usr/sbin/mosquitto 2>/dev/null | head -1 || true)"
  if [ -n "$MOSQUITTO" ]; then
    CONF="$LOGS/mosquitto.conf"
    sed "s/^listener .*/listener $MQTT_PORT/" config/mosquitto.conf > "$CONF"
    "$MOSQUITTO" -c "$CONF" >"$LOGS/mosquitto.log" 2>&1 &
    STARTED+=("$!")
    say "✓ MQTT broker started on :$MQTT_PORT"
  else
    say "· mosquitto not found: the dashboard and apps work without it; the robot and \`make sim\` need it (brew install mosquitto | apt install mosquitto)"
  fi
fi

# ---------------------------------------------------------------- 2. dashboard build + API
api_mode() { curl -fsS -m 3 "$URL/v1/discovery" 2>/dev/null | sed -n 's/.*"mode":"\([a-z]*\)".*/\1/p'; }
MODE="$(api_mode || true)"
if [ -n "$MODE" ]; then
  [ "$MODE" = "demo" ] || fail "A Kaiku API is already on :$PORT but it is in '$MODE' mode, so it will not accept a seeded record." \
    "Stop it, or choose another port: KAIKU_DEMO_PORT=8010 make demo"
  say "✓ Kaiku API already on :$PORT (reusing it)"
elif listening "$PORT"; then
  fail "Port $PORT is in use by something that is not a Kaiku API." "Free it, or run: KAIKU_DEMO_PORT=8010 make demo"
else
  if [ ! -f apps/web/out/index.html ] && [ -z "${KAIKU_DEMO_SKIP_WEB:-}" ]; then
    if command -v pnpm >/dev/null && command -v node >/dev/null; then
      say "· building the dashboard (first run only, about a minute)…"
      (cd apps/web && pnpm install --silent && pnpm build) >"$LOGS/web-build.log" 2>&1 \
        || fail "The dashboard build failed." "See $LOGS/web-build.log (last lines below)." "$(tail -5 "$LOGS/web-build.log")"
    else
      say "· Node 20 + pnpm not found: starting the API without the dashboard pages (install them, then \`make web-build\`)"
    fi
  fi
  KAIKU_DEMO_MODE=1 uv run --quiet python tools/cloud_local.py --port "$PORT" >"$LOGS/api.log" 2>&1 &
  STARTED+=("$!")
  for _ in $(seq 1 120); do
    [ "$(api_mode || true)" = "demo" ] && break
    kill -0 "${STARTED[${#STARTED[@]}-1]}" 2>/dev/null || break
    sleep 0.5
  done
  [ "$(api_mode || true)" = "demo" ] || fail "The API did not come up on :$PORT." "Last lines of $LOGS/api.log:" "$(tail -8 "$LOGS/api.log")" "Then try: make doctor"
  say "✓ Kaiku API started on :$PORT"
fi

# ---------------------------------------------------------------- 3. the record
SEED_ARGS=(--url "$URL")
[ "$RESET" = "--reset" ] && SEED_ARGS+=(--reset)
SUMMARY="$(uv run --quiet python -m kaiku_cloud.jobs.single_person "${SEED_ARGS[@]}")" || fail "Seeding the record failed (reason above)."
ADDED="$(printf '%s' "$SUMMARY" | sed -n 's/.*"accepted": \([0-9]*\).*/\1/p')"
STATE="$(printf '%s' "$SUMMARY" | sed -n 's/.*"state": "\([a-z_]*\)".*/\1/p')"
if [ "${ADDED:-0}" = "0" ]; then say "✓ Aino's record is already there (nothing added)"; else say "✓ Aino's sixteen days seeded ($ADDED observations)"; fi

LAN="$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true)"
say ""
if curl -fsS -m 3 -o /dev/null "$URL/" 2>/dev/null; then
  say "  Dashboard        $URL/"
else
  say "  Dashboard        not built (API only). Build it with: make web-build, then restart make demo"
fi
say "  API docs         $URL/docs"
say "  Current reading  ${STATE:-unknown}  (curl $URL/v1/patients/aino/consensus)"
say "  Link a device    ${LAN:+http://$LAN:$PORT/?home=aino}   (iPhone: KAIKU_TEAM=<team> apps/apple/scripts/run_on_iphone.sh aino; see README)"
say "  Try a day        uv run python scripts/live_day.py        (good vs rough day, on a throwaway copy)"
say ""

if [ "${#STARTED[@]}" -eq 0 ] || [ -n "${KAIKU_DEMO_ONCE:-}" ]; then
  exit 0
fi
say "Running. Ctrl-C stops what this command started. Logs: $LOGS/"
wait
