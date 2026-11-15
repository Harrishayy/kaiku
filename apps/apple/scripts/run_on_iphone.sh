#!/usr/bin/env bash
# Build, sign, install and launch Kaiku on a USB/Wi-Fi-paired iPhone, configured for a companion service on this Mac's network.
# Usage: KAIKU_TEAM=<team id> apps/apple/scripts/run_on_iphone.sh [--install-only] [home_id]
#   Works on a LOCKED paired phone: installing succeeds while locked; launching needs it unlocked, so a locked
#   phone is reported as "installed; opens with the new build next time the phone is unlocked" (exit 0).
#   --install-only  build + install, never try to launch.
#   The install is an upgrade in place: the stored profile, pairing, choices and Meta registration are kept
#   (nothing is uninstalled, reprovisioned or wiped). The lock is never bypassed.
#   Needs: Apple PLA accepted for the team, iPhone paired + Developer Mode on, the cloud listening on the LAN:
#   make cloud-local   (explicit demo configuration for automatic local enrollment; no seed or robot required)
#   KAIKU_APP_GROUP=<group> + KAIKU_ENTITLEMENTS_SUFFIX="" once that App Group is assigned to the team's App IDs;
#   default ".nogroup" = no App Group (everything works except the home-screen widget, which shows a placeholder).
set -euo pipefail
cd "$(dirname "$0")/.."
INSTALL_ONLY=0
if [ "${1:-}" = "--install-only" ]; then INSTALL_ONLY=1; shift; fi
TASK_HOME_ID="${1:-}"  # Optional explicit profile; otherwise retain stored profile or create a fresh demo identity.
TEAM="${KAIKU_TEAM:?set KAIKU_TEAM to your Apple team id}"
SUFFIX="${KAIKU_ENTITLEMENTS_SUFFIX-.nogroup}"
IP="$(ipconfig getifaddr en0 || ipconfig getifaddr en1)"
DD="${TMPDIR:-/tmp}/kaiku-device-dd"
DEVICE="$(xcrun devicectl list devices 2>/dev/null | awk '/available \(paired\)|connected/ && /iPhone/ {print $3; exit}')"
[ -n "$DEVICE" ] || { echo "no available paired iPhone (cable/unlock/trust/Developer Mode)"; exit 1; }
if ! curl -sf "http://$IP:8000/healthz" >/dev/null; then
  # Installing does not need the service; only a launch that should connect does.
  if [ "$INSTALL_ONLY" = 1 ]; then echo "note: companion service not healthy at http://$IP:8000 right now; installing anyway"
  else echo "cloud not reachable at http://$IP:8000 (start it with --host 0.0.0.0)"; exit 1; fi
fi
xcodegen -q
xcodebuild -project Kaiku.xcodeproj -scheme "Kaiku iOS" -destination "generic/platform=iOS" -configuration Debug \
  -derivedDataPath "$DD" -allowProvisioningUpdates DEVELOPMENT_TEAM="$TEAM" CODE_SIGN_STYLE=Automatic \
  CODE_SIGN_IDENTITY="Apple Development" KAIKU_SERVICE_URL="http://$IP:8000" KAIKU_ENTITLEMENTS_SUFFIX="$SUFFIX" ${KAIKU_APP_GROUP:+KAIKU_APP_GROUP=$KAIKU_APP_GROUP} \
  build -quiet
xcrun devicectl device install app --device "$DEVICE" "$DD/Build/Products/Debug-iphoneos/Kaiku.app"
if [ "$INSTALL_ONLY" = 1 ]; then
  echo "Kaiku installed on $DEVICE (not launched). Profile and pairing kept. Companion service: http://$IP:8000."
  exit 0
fi
LAUNCH_ARGS=(-kaikuTab today -kaikuAutostart NO)
if [ -n "$TASK_HOME_ID" ]; then
  LAUNCH_ARGS+=(-kaikuPairLink "http://$IP:8000/?home=$TASK_HOME_ID")
fi
LAUNCH_LOG="$(mktemp)"
if xcrun devicectl device process launch --device "$DEVICE" --terminate-existing fi.kaiku.app -- "${LAUNCH_ARGS[@]}" >"$LAUNCH_LOG" 2>&1; then
  echo "Kaiku installed and launched on $DEVICE. Companion service: http://$IP:8000; connection is verified in the app."
elif awk 'BEGIN{IGNORECASE=1} tolower($0) ~ /locked|passcode|unlock/ {found=1} END{exit !found}' "$LAUNCH_LOG"; then
  # A locked phone refuses to launch apps; that is expected and not a failure of the install.
  echo "Kaiku installed on $DEVICE; it opens with the new build next time the phone is unlocked. (Launch skipped: the phone is locked.)"
else
  cat "$LAUNCH_LOG" >&2
  echo "Kaiku installed on $DEVICE, but launching failed for another reason (see above). Open it on the phone." >&2
  rm -f "$LAUNCH_LOG"
  exit 2
fi
rm -f "$LAUNCH_LOG"
