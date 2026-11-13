#!/usr/bin/env bash
# Install what can be automated for a role, print what's left. Safe to re-run.
#   ./scripts/bootstrap.sh all|hub|cloud|web|firmware|glasses-web|glasses-dat
set -uo pipefail
ROLE="${1:-all}"
cd "$(dirname "$0")/.."
TODO=()
have() { command -v "$1" >/dev/null 2>&1; }
step() { printf '\033[1m▸ %s\033[0m\n' "$*"; }
todo() { TODO+=("$*"); }
is() { [[ "$ROLE" == all || " $* " == *" $ROLE "* ]]; }

case "$ROLE" in all|hub|cloud|web|firmware|glasses-web|glasses-dat) ;; *)
  echo "unknown role '$ROLE' (all|hub|cloud|web|firmware|glasses-web|glasses-dat)"; exit 2 ;;
esac

step "core: uv + Python env"
if ! have uv; then
  curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH="$HOME/.local/bin:$PATH"
fi
uv sync || todo "uv sync failed — read the error above"
[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }

if is hub firmware; then
  step "mosquitto"
  if ! have mosquitto && [ ! -x /opt/homebrew/sbin/mosquitto ] && [ ! -x /usr/local/sbin/mosquitto ] && [ ! -x /usr/sbin/mosquitto ]; then
    if have brew; then brew install mosquitto; else todo "sudo apt install -y mosquitto mosquitto-clients"; fi
  fi
fi

if is hub; then
  step "hub extras (Gemini Live / camera / LoRa)"
  uv sync --package kaiku-hub --extra live --extra camera --extra lora --inexact \
    || todo "hub extras failed (sounddevice may need: brew install portaudio / apt install libportaudio2)"
  todo "put GEMINI_API_KEY in .env (AI Studio) — never commit it"
  todo "Gemini skills: npx skills add google-gemini/gemini-skills --skill gemini-live-api-dev"
fi

if is cloud; then
  step "modal"
  uv run modal token info >/dev/null 2>&1 || todo "uv run modal setup   (browser auth; redeem credits on the Junction Modal challenge page)"
  todo "modal secret create kaiku-secrets GEMINI_API_KEY=... HF_TOKEN=... KAIKU_HOME_TOKEN=... KAIKU_ADMIN_TOKEN=..."
fi

if is web glasses-web; then
  step "node + pnpm"
  if ! have node; then todo "install Node >= 20 (nvm install 20)"; fi
  if ! have pnpm; then corepack enable 2>/dev/null || todo "install pnpm: corepack enable  (or brew install pnpm)"; fi
  if have pnpm && [ -f apps/web/package.json ]; then (cd apps/web && pnpm install) || todo "pnpm install in apps/web failed"; fi
fi

if is glasses-web; then
  todo "Chrome: install the MRBD Simulator extension (link in apps/glasses-webapp/AGENTS.md)"
  todo "Claude Code: /plugin marketplace add https://github.com/meta/meta-wearables-webapp && /plugin install meta-wearables-webapp@meta-wearables"
fi

if is glasses-dat; then
  todo "Android Studio + Kotlin 2.2; claude plugin marketplace add facebook/meta-wearables-dat-android; see apps/glasses-dat-android/AGENTS.md"
fi

if is firmware; then
  todo "Chrome/Edge for atech.dev WebSerial; data-capable USB cable; Linux: sudo usermod -aG dialout \$USER"
  todo "uv pip install atech  (agent-driven Atech work); Arduino App Lab for the UNO Q"
fi

todo "restart your coding agent so it loads .mcp.json (geminiDocs, wearables)"

step "doctor"
uv run --quiet python tools/doctor.py --offline || true

if ((${#TODO[@]})); then
  printf '\n\033[1mStill to do by hand:\033[0m\n'
  for t in "${TODO[@]}"; do printf '  • %s\n' "$t"; done
fi
