#!/usr/bin/env bash
# The robot on its own: the broker and the hub on the Arduino UNO Q's Linux side, so no laptop or phone is in the
# robot's path (docs/robot-network-handover.md -> "The robot on its own: no laptop").
#
# NOT RUN ON A BOARD YET (2026-11-14). Written from this repo and Arduino's UNO Q documentation (Debian trixie on
# arm64, user `arduino`, `sudo apt`, App Lab apps in Docker). Read what each step prints; nothing here hides errors.
#
# Run ON the UNO Q (ssh arduino@<board>.local), from the copy of the repo on the board:
#   ./scripts/unoq_robot_setup.sh check      changes nothing: what is there and what is missing (default)
#   ./scripts/unoq_robot_setup.sh install    mosquitto with a LAN listener, uv + the hub's packages, the hub as a
#                                            service that starts at boot; safe to run again
#   ./scripts/unoq_robot_setup.sh status     broker + hub state, and the addresses for the head and the sensors app
#   ./scripts/unoq_robot_setup.sh uninstall  stops and removes the hub service and the broker listener file
#
# It never writes, prints or asks for a key. GEMINI_API_KEY lives in <repo>/.env ON THE BOARD (gitignored, mode 600):
# you put it there yourself (the last lines of `install` say how). This repo is public.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO/.env"
UNIT=/etc/systemd/system/kaiku-hub.service
BROKER_CONF=/etc/mosquitto/conf.d/kaiku.conf
BROKER_PASSWD=/etc/mosquitto/kaiku.passwd   # optional: create it and the broker asks for a user + password

say() { printf '\033[1m== %s\033[0m\n' "$*"; }
ok() { printf '  ok    %s\n' "$*"; }
miss() { printf '  MISS  %s\n' "$*"; }
have() { command -v "$1" > /dev/null 2>&1; }

# True when .env has a non-empty value for KEY (names only: a value is never printed).
env_has() { [ -f "$ENV_FILE" ] && grep -Eq "^[[:space:]]*$1[[:space:]]*=[[:space:]]*[^[:space:]#]" "$ENV_FILE"; }

# Adds KEY=VALUE to .env unless the key already has a value. For settings only, never for a secret.
ensure_env() {
  if env_has "$1"; then echo "  kept  $1 (already set in .env)"; return 0; fi
  printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
  echo "  set   $1=$2"
}

lan_ip() {   # the board's address on the Wi-Fi: not loopback, not Docker's 172.x bridges
  hostname -I 2> /dev/null | tr ' ' '\n' | grep -Ev '^(127\.|172\.(1[6-9]|2[0-9]|3[01])\.|$)' | grep -v ':' | head -1 | grep .
}

docker_gw() { ip -4 -o addr show docker0 2> /dev/null | awk '{print $4}' | cut -d/ -f1 | grep .; }

need_linux() {
  [ "$(uname -s)" = Linux ] || { echo "this runs ON the UNO Q (Linux), not on $(uname -s)" >&2; exit 2; }
}

check() {
  say "board"
  echo "  $(. /etc/os-release 2> /dev/null && echo "${PRETTY_NAME:-unknown OS}"), $(uname -m), host $(hostname)"
  [ "$(uname -m)" = aarch64 ] && ok "arm64" || miss "not arm64: the wheel check for the hub was done for aarch64 Linux only"
  have python3 && ok "$(python3 --version 2>&1) (uv installs its own 3.12 for the hub; this one is not used)" || miss "python3"
  echo "  memory: $(free -m 2> /dev/null | awk '/^Mem:/ {print $2 " MB total, " $7 " MB available"}')"
  echo "  disk:   $(df -h "$REPO" | awk 'NR==2 {print $4 " free on " $6}')"
  say "network"
  echo "  Wi-Fi address: $(lan_ip || true)   (the head's secrets.h: MQTT_HOST \"$(hostname).local\", MQTT_HOST_IP = this address)"
  echo "  Docker bridge: $(docker_gw || true)   (the sensors app runs in a container: its .env MQTT_HOST = this or the Wi-Fi address)"
  if have curl; then
    curl -sS -o /dev/null -m 8 -w '  Gemini API reachable: HTTP %{http_code}\n' https://generativelanguage.googleapis.com/ || miss "no route to generativelanguage.googleapis.com (Live voice and the songs need it)"
  else
    miss "curl (install does it)"
  fi
  say "broker"
  have mosquitto && ok "mosquitto installed" || miss "mosquitto (install does it)"
  [ -f "$BROKER_CONF" ] && ok "$BROKER_CONF" || miss "$BROKER_CONF: without it Debian's mosquitto listens on localhost only"
  if have ss; then ss -ltn 2> /dev/null | grep -q ':1883 ' && ok "something listens on :1883" || miss "nothing listens on :1883"; fi
  say "hub"
  have uv || [ -x "$HOME/.local/bin/uv" ] && ok "uv" || miss "uv (install does it)"
  [ -x "$REPO/.venv/bin/python" ] && ok ".venv ($("$REPO/.venv/bin/python" --version 2>&1))" || miss ".venv with the hub's packages (install does it)"
  [ -f "$UNIT" ] && ok "$UNIT ($(systemctl is-enabled kaiku-hub 2> /dev/null || true), $(systemctl is-active kaiku-hub 2> /dev/null || true))" || miss "$UNIT (install does it)"
  say ".env on the board (names only)"
  if [ -f "$ENV_FILE" ]; then
    for k in GEMINI_API_KEY KAIKU_HOME_ID KAIKU_HUB_ROBOT_HOME_ID KAIKU_CLOUD_URL KAIKU_HOME_TOKEN MQTT_HOST KAIKU_VOICE KAIKU_VOICE_AUDIO KAIKU_MUSIC KAIKU_MUSIC_OUT; do
      env_has "$k" && ok "$k" || miss "$k"
    done
    [ "$(stat -c %a "$ENV_FILE" 2> /dev/null)" = 600 ] && ok "mode 600" || miss "chmod 600 $ENV_FILE"
  else
    miss "$ENV_FILE"
  fi
  say "sensors app"
  have arduino-app-cli && ok "arduino-app-cli" || miss "arduino-app-cli (App Lab's tool; without it start the app from App Lab)"
  [ -d "$HOME/ArduinoApps/kaiku-sensors" ] && ok "~/ArduinoApps/kaiku-sensors" || miss "~/ArduinoApps/kaiku-sensors (make unoq-app on a computer, then copy firmware/unoq-sensors there)"
}

install() {
  say "packages (sudo): mosquitto, its clients, PortAudio (so 'import sounddevice' cannot fail; no sound device is used), curl"
  sudo apt-get update
  sudo apt-get install -y mosquitto mosquitto-clients libportaudio2 curl ca-certificates

  say "broker: a listener for the Wi-Fi ($BROKER_CONF)"
  # Debian's mosquitto 2 listens on localhost only until a listener is configured. set_tcp_nodelay: 50 small audio
  # messages a second must not wait for each other's ACKs.
  {
    echo "# Kaiku robot broker. Written by scripts/unoq_robot_setup.sh."
    echo "listener 1883"
    echo "set_tcp_nodelay true"
    if sudo test -f "$BROKER_PASSWD"; then
      echo "allow_anonymous false"
      echo "password_file $BROKER_PASSWD"
    else
      echo "allow_anonymous true"
    fi
  } | sudo tee "$BROKER_CONF" > /dev/null
  if sudo test -f "$BROKER_PASSWD"; then
    echo "  the broker asks for a user and password ($BROKER_PASSWD): put MQTT_USER / MQTT_PASS into .env here,"
    echo "  into the sensors app's .env and into the head's secrets.h"
  else
    echo "  ANONYMOUS broker (D14), as on the dev laptops. On a shared Wi-Fi anyone on it can then publish to the robot,"
    echo "  including {mic: open}. For a password: sudo mosquitto_passwd -c $BROKER_PASSWD kaiku ; then run install again."
  fi
  sudo systemctl enable mosquitto
  sudo systemctl restart mosquitto

  say "uv + the hub's Python packages (.venv in $REPO; the first time downloads Python 3.12, numpy, scipy: minutes)"
  if ! have uv && [ ! -x "$HOME/.local/bin/uv" ]; then curl -LsSf https://astral.sh/uv/install.sh | sh; fi
  export PATH="$HOME/.local/bin:$PATH"
  # Only the hub and what it needs: not the cloud, the tools or the dev group. --frozen = exactly uv.lock.
  (cd "$REPO" && uv sync --package kaiku-hub --extra live --no-dev --frozen)
  (cd "$REPO" && KAIKU_NO_DOTENV=1 .venv/bin/python -c 'import kaiku_hub.main, google.genai, numpy, scipy; print("  hub imports fine")')

  say ".env on the board (settings only; the key is yours to add)"
  if [ ! -f "$ENV_FILE" ]; then
    : > "$ENV_FILE"
    echo "  created an empty $ENV_FILE"
  fi
  chmod 600 "$ENV_FILE"
  ensure_env MQTT_HOST localhost          # the broker is on this board
  ensure_env KAIKU_VOICE_AUDIO head       # [voice] audio: Kaiku speaks and listens through the head
  ensure_env KAIKU_MUSIC_OUT head         # [music] out: the songs and cues come out of the head

  say "the hub as a service ($UNIT): starts at boot, restarts if it stops"
  sudo tee "$UNIT" > /dev/null << EOF
[Unit]
Description=Kaiku hub on the robot (ritual, tap it back, voice)
After=network-online.target mosquitto.service
Wants=network-online.target mosquitto.service

[Service]
User=$(id -un)
WorkingDirectory=$REPO
Environment=PYTHONUNBUFFERED=1
ExecStart=$REPO/.venv/bin/python -m kaiku_hub.main
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable kaiku-hub
  sudo systemctl restart kaiku-hub

  say "left for you"
  cat << EOF
  1. The key and the person's record, in $ENV_FILE (never in git, never in a message):
       nano $ENV_FILE      GEMINI_API_KEY=...   KAIKU_HOME_ID=...   KAIKU_HUB_ROBOT_HOME_ID=demo-aino
                           KAIKU_CLOUD_URL=...  KAIKU_HOME_TOKEN=... KAIKU_VOICE=gemini   KAIKU_MUSIC=lyria
     then: sudo systemctl restart kaiku-hub
  2. The sensors app (a container: "localhost" there is the container, not this board):
       ~/ArduinoApps/kaiku-sensors/.env   MQTT_HOST=$(docker_gw || echo '<docker0 address>')   (or the Wi-Fi address $(lan_ip || echo '<address>'))
       arduino-app-cli properties set default user:kaiku-sensors     # starts it at every boot
       arduino-app-cli app start user:kaiku-sensors
  3. The head: firmware/atech-head/kaiku_link/secrets.h   MQTT_HOST "$(hostname).local"   MQTT_HOST_IP "$(lan_ip || echo '<address>')"
     then flash it once (make atech-standalone FLASH=1).
  4. ./scripts/unoq_robot_setup.sh status
EOF
}

status() {
  say "broker"
  systemctl is-active mosquitto || true
  ss -ltn 2> /dev/null | grep ':1883 ' || echo "  nothing listens on :1883"
  say "hub"
  systemctl is-enabled kaiku-hub || true
  systemctl is-active kaiku-hub || true
  journalctl -u kaiku-hub -n 15 --no-pager 2> /dev/null || true
  say "who is on the bus (5 s; health messages are retained)"
  if have mosquitto_sub; then
    timeout 5 mosquitto_sub -h localhost -t 'kaiku/v1/+/health/+' -v 2> /dev/null | cut -c1-200 || true
  fi
  say "addresses"
  echo "  head secrets.h:    MQTT_HOST \"$(hostname).local\"   MQTT_HOST_IP \"$(lan_ip || true)\""
  echo "  sensors app .env:  MQTT_HOST=$(docker_gw || true)   (or $(lan_ip || true))"
  echo "  follow the hub:    journalctl -u kaiku-hub -f"
}

uninstall() {
  sudo systemctl disable --now kaiku-hub 2> /dev/null || true
  sudo rm -f "$UNIT" "$BROKER_CONF"
  sudo systemctl daemon-reload
  sudo systemctl restart mosquitto 2> /dev/null || true
  echo "removed the hub service and the broker listener (mosquitto itself, .venv and .env are left as they are)"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-check}" in
    check) need_linux; check ;;
    install) need_linux; install; echo; status ;;
    status) need_linux; status ;;
    uninstall) need_linux; uninstall ;;
    *) sed -n '2,17p' "$0"; exit 2 ;;
  esac
fi
