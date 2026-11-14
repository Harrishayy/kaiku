#!/usr/bin/env bash
# Record demo videos of the Kaiku Apple apps against a local seeded cloud (no paid calls: template LLM, no Live).
#   apps/apple/scripts/record_app_demo.sh [ios|mac|post|all]      (default all)
# Env: KAIKU_TEST_CLOUD (default http://127.0.0.1:18020, must be seeded: python -m sim.seed_demo --reset),
#      SIM_UDID (a booted-or-bootable iPhone simulator; default: one named "Kaiku Demo 17 Pro", created if missing),
#      OUT (default demo/recordings), DERIVED (xcodebuild derived data, default $OUT/.dd).
# ios : DemoTourTests (iOSUITests/DemoTourTests.swift), one raw simulator recording per test method.
# mac : launches Kaiku Mac paired to the cloud and records the real screen (ffmpeg avfoundation, needs Screen
#       Recording permission for the terminal) while switching tabs/games with -kaikuTab/-kaikuRoute relaunches,
#       then -kaikuSimulateLate for the notch island peek. No Accessibility permission needed.
# post: title card + trim + speed-up + ≤1080p h264 (< 25 MB) and a contact sheet PNG + preview GIF per clip.
set -eu   # no pipefail: ffmpeg -i / -list_devices exit non-zero by design
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
APPLE="$ROOT/apps/apple"
CLOUD="${KAIKU_TEST_CLOUD:-http://127.0.0.1:18020}"
OUT="${OUT:-$ROOT/demo/recordings}"
RAW="$OUT/raw"
DERIVED="${DERIVED:-$OUT/.dd}"
FFMPEG="${FFMPEG:-$(command -v ffmpeg || echo /opt/homebrew/bin/ffmpeg)}"
FONT="/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"
[ -f "$FONT" ] || FONT="/System/Library/Fonts/Helvetica.ttc"
mkdir -p "$RAW"
what="${1:-all}"

curl -fsS "$CLOUD/healthz" >/dev/null || { echo "cloud not reachable at $CLOUD (start it + seed first)"; exit 1; }

now() { python3 -c 'import time; print(f"{time.time():.2f}")'; }

sim_udid() {
  if [ -n "${SIM_UDID:-}" ]; then echo "$SIM_UDID"; return; fi
  local u
  u=$(xcrun simctl list devices available | sed -n 's/.*Kaiku Demo 17 Pro (\([0-9A-F-]*\)).*/\1/p' | head -1)
  [ -n "$u" ] || u=$(xcrun simctl create "Kaiku Demo 17 Pro" "iPhone 17 Pro")
  echo "$u"
}

record_ios() {
  local udid; udid=$(sim_udid)
  xcrun simctl boot "$udid" 2>/dev/null || true
  xcrun simctl bootstatus "$udid" -b >/dev/null
  open -a Simulator --args -CurrentDeviceUDID "$udid" || true
  xcrun simctl status_bar "$udid" override --time 9:41 --batteryState charged --batteryLevel 100 --wifiBars 3 || true
  (cd "$APPLE" && xcodegen -q)
  xcodebuild -project "$APPLE/Kaiku.xcodeproj" -scheme "Kaiku iOS" -destination "platform=iOS Simulator,id=$udid" \
    -derivedDataPath "$DERIVED" build-for-testing -quiet
  xcrun simctl uninstall "$udid" fi.kaiku.app 2>/dev/null || true      # fresh first launch → onboarding
  for t in test1Tour:iphone-tour test2GlassesWalk:iphone-glasses-walk test3Notification:iphone-notifications test4Health:iphone-health; do
    local m="${t%%:*}" name="${t##*:}"
    xcrun simctl io "$udid" recordVideo --codec h264 --force "$RAW/$name.mp4" & local rec=$!
    local t0; t0=$(now)
    sleep 2
    TEST_RUNNER_KAIKU_TEST_CLOUD="$CLOUD" xcodebuild -project "$APPLE/Kaiku.xcodeproj" -scheme "Kaiku iOS" \
      -destination "platform=iOS Simulator,id=$udid" -derivedDataPath "$DERIVED" test-without-building \
      -only-testing:"Kaiku iOS UITests/DemoTourTests/$m" 2>&1 | tee "$RAW/$name.log" | grep -E "DEMO-|passed|failed" || true
    kill -INT "$rec"; wait "$rec" 2>/dev/null || true
    # trim the home-screen wait before the app's first step (DEMO-STEP <name> <epoch>)
    awk -v t0="$t0" '/DEMO-STEP/ {printf "%.2f\n", ($3 - t0 > 3 ? $3 - t0 - 3 : 0); exit}' "$RAW/$name.log" > "$RAW/$name.trim"
  done
}

# --- Mac -------------------------------------------------------------------------------------------------------------
# One launch, driven like a person would: kaiku:// links switch screens, keys play the games (Return starts, Space
# catches, 1–9 taps pebbles, ←/→ turn dials, Esc goes back), the mouse hovers/clicks the notch island. The raw
# capture is the whole screen; post() crops it to the Kaiku window + the notch (and the status item for the popover),
# so nothing else on the desktop ends up in the video. Needs Screen Recording + Accessibility for the terminal.
mac_app() { echo "$DERIVED/Build/Products/Debug/Kaiku.app"; }
ax() { osascript -e "tell application \"System Events\" to tell process \"Kaiku\" to $1" 2>/dev/null || true; }
# window_at X Y → index of the Kaiku window whose frame contains the point (screen points)
window_at() {
  ax 'get {position, size} of every window' | tr -d ' ' | python3 -c '
import sys
v = [int(float(t)) for t in sys.stdin.read().replace("{", "").replace("}", "").split(",") if t]
x, y = int(sys.argv[1]), int(sys.argv[2])
for i in range(0, len(v) - 3, 4):
    if v[i] <= x <= v[i] + v[i+2] and v[i+1] <= y <= v[i+1] + v[i+3]: print(i // 4 + 1); break' "$1" "$2"
}
key() {
  osascript -e 'tell application "System Events"' -e 'set frontmost of process "Kaiku" to true' -e 'delay 0.05' \
    -e 'if name of first process whose frontmost is true is "Kaiku" then' -e "$1" -e 'end if' -e 'end tell' 2>/dev/null || true
}

record_mac() {
  (cd "$APPLE" && xcodegen -q)
  xcodebuild -project "$APPLE/Kaiku.xcodeproj" -scheme "Kaiku Mac" -destination "platform=macOS" \
    -derivedDataPath "$DERIVED" build -quiet
  swiftc -O -o "$DERIVED/demo_mouse" "$APPLE/scripts/demo_mouse.swift"
  local mouse="$DERIVED/demo_mouse" app; app="$(mac_app)"
  : > "$RAW/mac-tour.meta"
  defaults write fi.kaiku.mac kaiku.consents -dict mac -bool true checkins -bool true walks -bool true
  defaults write fi.kaiku.mac kaiku.onboarded -bool true
  pkill -x Kaiku 2>/dev/null || true; sleep 1
  "$app/Contents/MacOS/Kaiku" -kaikuSkipOnboarding YES -kaikuPairLink "$CLOUD/?home=demo-aino" -kaiku.lang en \
    -AppleLanguages "(en)" -kaikuMute YES >/dev/null 2>&1 &
  sleep 3
  open -a "$app" "kaiku://today"           # a relaunch may not restore the window; a link always opens it
  for _ in $(seq 1 20); do [ -n "$(ax 'get name of (first window whose name is "Kaiku")')" ] && break; sleep 0.5; done
  local W H; read -r W H < <(osascript -e 'tell application "Finder" to get bounds of window of desktop' | awk -F', ' '{print $3, $4}')
  local wx=$(( (W - 980) / 2 )) wy=40
  ax "set position of (first window whose name is \"Kaiku\") to {$wx, $wy}"
  ax "set size of (first window whose name is \"Kaiku\") to {980, 720}"
  ax 'set frontmost to true'
  local screen; screen=$("$FFMPEG" -f avfoundation -list_devices true -i "" 2>&1 | sed -n 's/.*\[\([0-9]*\)\] Capture screen 0.*/\1/p' | head -1)
  "$FFMPEG" -y -loglevel error -f avfoundation -capture_cursor 1 -framerate 30 -i "${screen}:none" \
    -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p "$RAW/mac-tour.mkv" & local rec=$!
  local t0; t0=$(now)
  sleep 2
  go() { open -a "$app" "kaiku://$1"; ax 'set frontmost to true'; sleep "${2:-3}"; }
  "$mouse" move $(( wx + 700 )) $(( wy + 600 ))
  go today 5
  go weather 2
  key 'key code 48'; for _ in 1 2 3; do key 'key code 124'; sleep 0.4; done; sleep 0.6   # Tab → mood dial, →
  key 'key code 48'; for _ in 1 2; do key 'key code 124'; sleep 0.4; done; sleep 0.6
  key 'key code 48'; key 'key code 123'; sleep 0.4; key 'key code 124'; sleep 0.4; key 'key code 124'; sleep 0.8
  key 'key code 48'; sleep 0.3; key 'key code 36'; sleep 3                               # Tab → That's it, Return
  go play 3
  go play/firefly 3; key 'key code 36'; sleep 1
  for _ in $(seq 1 16); do key 'keystroke " "'; sleep 0.8; done
  key 'key code 53'; sleep 1.5
  go play/pebbles 3; key 'key code 36'; sleep 4
  for _ in $(seq 1 14); do key 'keystroke "1"'; sleep 0.9; done; sleep 3                 # wrong paths end the game
  key 'key code 53'; sleep 1
  go play/breathe 3; key 'key code 36'; sleep 12; key 'key code 53'; sleep 1.5
  go play/tell 4; key 'key code 53'; sleep 1
  go talk 3
  ax 'set focused of (first text area of entire contents of (first window whose name is "Kaiku")) to true'
  ax 'set focused of (first text field of entire contents of (first window whose name is "Kaiku")) to true'
  key 'keystroke "I walked to the lake today."'; sleep 0.8; key 'key code 36'; sleep 4
  go days 4
  go you 3
  go you/memories 4
  go you/saw 4
  go you/devices 3
  # the menu bar popover, then its debug "Simulate a late evening" → the notch island peeks (sleepy Kaiku)
  local mb; mb=$(ax 'get {position, size} of menu bar item 1 of menu bar 2' | tr -d ' ')
  echo "popover_start=$(python3 -c "print(round($(now)-$t0,2))") menubar_item=$mb" >> "$RAW/mac-tour.meta"
  ax 'click menu bar item 1 of menu bar 2'; sleep 4
  # find the popover: the Kaiku window whose frame holds the status item's x (the island and main window don't)
  local pi; pi=$(ax 'get {name, position} of every window' | python3 -c '
import sys
t = [x.strip() for x in sys.stdin.read().split(",")]
n = len(t) // 3
names, pos = t[:n], t[n:]
for i in range(n):
    if names[i] != "Kaiku" and int(float(pos[2*i+1])) > 0: print(i + 1); break' || true)
  if [ -n "$pi" ]; then
    echo "popover_window=$(ax "get {position, size} of window $pi" | tr -d ' ')" >> "$RAW/mac-tour.meta"
    ax "click last button of entire contents of window $pi" || true      # debug: "Simulate a late evening"
    sleep 1
  fi
  echo "popover_end=$(python3 -c "print(round($(now)-$t0,2))")" >> "$RAW/mac-tour.meta"
  key 'key code 53'; sleep 4                                                     # peek
  local cx=$(( W / 2 ))
  "$mouse" move "$cx" 70; sleep 4                                              # hover → expanded
  "$mouse" move $(( wx + 700 )) $(( wy + 600 )); sleep 3                          # away → back to the peek
  "$mouse" move "$cx" 70; sleep 2
  local ii gx gy; ii=$(window_at $(( W / 2 )) 5)
  read -r gx gy < <(ax "get position of button 1 of entire contents of window ${ii:-1}" | awk -F', ' '{print $1+20, $2+10}') || true
  if [ -n "${gx:-}" ]; then "$mouse" click "$gx" "$gy"; fi; sleep 5                          # Goodnight → reply, then hides
  "$mouse" move $(( wx + 700 )) $(( wy + 600 )); sleep 3
  kill -INT "$rec"; wait "$rec" 2>/dev/null || true
  echo "window=$wx,$wy,980,720 screen=$W,$H" >> "$RAW/mac-tour.meta"
  mac_crop
}

# Full-screen capture → two clips that show only Kaiku: the window + the notch above it (mac-tour), and the
# menu bar popover under its status item (mac-menubar). Scale = captured pixels / screen points (2 on Retina).
mac_crop() {
  local meta="$RAW/mac-tour.meta" px
  px=$("$FFMPEG" -i "$RAW/mac-tour.mkv" 2>&1 | sed -n 's/.*Video:.* \([0-9]\{3,\}\)x[0-9]\{3,\}.*/\1/p' | head -1)
  python3 - "$meta" "$px" > "$RAW/mac-crop.env" <<'PY'
import re, sys
m = dict(re.findall(r"(\w+)=(\S+)", open(sys.argv[1]).read()))
wx, wy, ww, wh = map(int, m["window"].split(","))
W, H = map(int, m["screen"].split(","))
k = int(sys.argv[2]) / W
ev = lambda n: int(n * k) // 2 * 2
x0 = max(0, wx - 10); print(f"MAIN_CROP={ev(ww + 20)}:{ev(wy + wh + 10)}:{ev(x0)}:0")
nums = [int(float(v)) for v in re.findall(r"-?\d+(?:\.\d+)?", m.get("popover_window", ""))]
if len(nums) >= 4:
    px_, py_, pw_, ph_ = nums[:4]
    x = max(0, px_ - 20); w = min(W - x, pw_ + 40)
    print(f"POP_CROP={ev(w)}:{ev(py_ + ph_ + 20)}:{ev(x)}:0")
print(f"POP_START={float(m.get('popover_start', 0)):.2f}")
print(f"POP_END={float(m.get('popover_end', 0)) + 1:.2f}")
PY
  # shellcheck disable=SC1091
  . "$RAW/mac-crop.env"
  "$FFMPEG" -y -loglevel error -i "$RAW/mac-tour.mkv" -vf "crop=$MAIN_CROP" -c:v libx264 -preset fast -crf 16 "$RAW/mac-tour.mp4"
  if [ -n "${POP_CROP:-}" ]; then
    "$FFMPEG" -y -loglevel error -ss "$POP_START" -to "$POP_END" -i "$RAW/mac-tour.mkv" -vf "crop=$POP_CROP" \
      -c:v libx264 -preset fast -crf 16 "$RAW/mac-menubar.mp4"
  fi
  rm -f "$RAW/mac-tour.mkv"      # the full-screen capture may show other windows: never keep it
}

# --- post-processing -------------------------------------------------------------------------------------------------
post() {
  local f name title
  for f in "$RAW"/*.mp4; do
    [ -f "$f" ] || continue
    name=$(basename "${f%.*}")
    case "$name" in
      iphone-tour) title="Kaiku — iPhone tour";;
      iphone-glasses-walk) title="Kaiku — walk with Meta glasses (simulated)";;
      iphone-notifications) title="Kaiku — check-in reminder";;
      iphone-health) title="Kaiku — Apple Health sample sync";;
      mac-tour) title="Kaiku — Mac app and notch island";;
      mac-menubar) title="Kaiku — Mac menu bar";;
      *) title="Kaiku — $name";;
    esac
    local trim=0; [ -s "$RAW/$name.trim" ] && trim=$(cat "$RAW/$name.trim")
    local note="Local demo cloud · no Gemini key: Talk uses the typed offline path"
    # 2.5 s title card, then the clip (speed ${SPEED:-1.25}x), scaled to ≤1080 high, h264 CRF tuned for < 25 MB
    local vf="scale=-2:'min(1080,ih)',setpts=PTS/${SPEED:-1.25},fps=30,format=yuv420p"
    local size; size=$("$FFMPEG" -i "$f" 2>&1 | sed -n 's/.*Video:.* \([0-9]\{3,\}\)x\([0-9]\{3,\}\).*/\1 \2/p' | head -1)
    local w h; read -r w h <<<"$size"
    "$FFMPEG" -y -loglevel error -i "$f" -f lavfi -i "color=c=0xF6EFE4:s=${w}x${h}:d=2.5:r=30" -filter_complex \
      "[1:v]drawtext=fontfile='$FONT':text='$title':fontcolor=0x3B2F2A:fontsize=h/22:x=(w-text_w)/2:y=(h-text_h)/2,\
drawtext=fontfile='$FONT':text='$note':fontcolor=0x7A6A60:fontsize=h/55:x=(w-text_w)/2:y=(h/2)+h/14,$vf[t];\
[0:v]trim=start=$trim,setpts=PTS-STARTPTS,$vf[c];[t][c]concat=n=2:v=1[v]" \
      -map "[v]" -c:v libx264 -preset slow -crf "${CRF:-28}" -movflags +faststart "$OUT/$name.mp4"
    # contact sheet (12 frames) + short GIF preview
    local dur; dur=$("$FFMPEG" -i "$OUT/$name.mp4" 2>&1 | sed -n 's/.*Duration: \([0-9:.]*\).*/\1/p' | awk -F: '{print $1*3600+$2*60+$3}')
    "$FFMPEG" -y -loglevel error -i "$OUT/$name.mp4" -vf "fps=12/$dur,scale=-2:480,tile=6x2:padding=6:color=white" -frames:v 1 "$OUT/$name-sheet.png"
    "$FFMPEG" -y -loglevel error -ss 3 -t 12 -i "$OUT/$name.mp4" -vf "fps=8,scale=-2:400:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer" "$OUT/$name.gif"
    echo "$name: $(du -h "$OUT/$name.mp4" | cut -f1) ${dur}s"
  done
}

case "$what" in
  ios) record_ios;; mac) record_mac;; post) post;;
  all) record_ios; record_mac; post;;
  *) echo "usage: $0 [ios|mac|post|all]"; exit 2;;
esac
