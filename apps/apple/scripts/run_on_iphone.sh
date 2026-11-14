#!/usr/bin/env bash
# Build, sign, install and launch Kaiku on a USB/Wi-Fi-paired iPhone, paired to a cloud on this Mac's network.
# Usage: KAIKU_TEAM=<team id> apps/apple/scripts/run_on_iphone.sh [home_id]
#   Needs: Apple PLA accepted for the team, iPhone paired + Developer Mode on, the cloud listening on the LAN:
#   uv run --package kaiku-cloud uvicorn kaiku_cloud.api.local:app --host 0.0.0.0 --port 8000   (+ make seed)
#   KAIKU_APP_GROUP=<group> + KAIKU_ENTITLEMENTS_SUFFIX="" once that App Group is assigned to the team's App IDs;
#   default ".nogroup" = no App Group (everything works except the home-screen widget, which shows a placeholder).
set -euo pipefail
cd "$(dirname "$0")/.."
HOME_ID="${1:-demo-aino}"
TEAM="${KAIKU_TEAM:?set KAIKU_TEAM to your Apple team id}"
SUFFIX="${KAIKU_ENTITLEMENTS_SUFFIX-.nogroup}"
IP="$(ipconfig getifaddr en0 || ipconfig getifaddr en1)"
DD="${TMPDIR:-/tmp}/kaiku-device-dd"
DEVICE="$(xcrun devicectl list devices 2>/dev/null | awk '/available \(paired\)/ && /iPhone/ {print $3; exit}')"
[ -n "$DEVICE" ] || { echo "no available paired iPhone (cable/unlock/trust/Developer Mode)"; exit 1; }
curl -sf "http://$IP:8000/healthz" >/dev/null || { echo "cloud not reachable at http://$IP:8000 (start it with --host 0.0.0.0)"; exit 1; }
xcodegen -q
xcodebuild -project Kaiku.xcodeproj -scheme "Kaiku iOS" -destination "generic/platform=iOS" -configuration Debug \
  -derivedDataPath "$DD" -allowProvisioningUpdates DEVELOPMENT_TEAM="$TEAM" CODE_SIGN_STYLE=Automatic \
  CODE_SIGN_IDENTITY="Apple Development" KAIKU_ENTITLEMENTS_SUFFIX="$SUFFIX" ${KAIKU_APP_GROUP:+KAIKU_APP_GROUP=$KAIKU_APP_GROUP} \
  build -quiet
xcrun devicectl device install app --device "$DEVICE" "$DD/Build/Products/Debug-iphoneos/Kaiku.app"
xcrun devicectl device process launch --device "$DEVICE" --terminate-existing fi.kaiku.app \
  -kaikuSkipOnboarding YES -kaikuPairLink "http://$IP:8000/?home=$HOME_ID"
echo "Kaiku running on $DEVICE, paired to http://$IP:8000 (home $HOME_ID)"
