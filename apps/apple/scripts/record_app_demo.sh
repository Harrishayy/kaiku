#!/usr/bin/env bash
# Record demo videos of the Kaiku Apple apps against a local seeded cloud (no paid calls: template LLM, no Live).
#   apps/apple/scripts/record_app_demo.sh [ios|mac|mac-snap|post|all]      (default all = ios mac post)
# Env: KAIKU_TEST_CLOUD (default http://127.0.0.1:18020; must be seeded with the one person:
#        uv run python -m kaiku_cloud.jobs.single_person --url $KAIKU_TEST_CLOUD), KAIKU_TEST_HOME (default aino),
#      TESTS (ios: space-separated method:clip pairs; default the five flows a–e; extras: testF_Firefly:iphone-6-firefly
#        testG_GlassesWalkSimulated:iphone-7-glasses-walk-simulated), SPEED (post: default 1 = real time), SHOTS (dir
#        for step screenshots, default $OUT/shots), KAIKU_BUILD_SERVICE=1 (ios: build with $KAIKU_TEST_CLOUD as the
#        app's configured service: first run connects by itself and the hello line is spoken),
#      SIM_UDID (a booted-or-bootable iPhone simulator; default: one named "Kaiku Demo 17 Pro", created if missing),
#      OUT (default demo/recordings), DERIVED (xcodebuild derived data, default ~/Library/Caches/kaiku-record-dd).
# ios : DemoTourTests (iOSUITests/DemoTourTests.swift), one raw simulator recording per test method. The cloud is
#       advertised over Bonjour as "$SERVICE_NAME" for the length of the run, so first-run setup finds it nearby.
# mac : launches Kaiku Mac paired to the cloud and records the real screen (ffmpeg avfoundation, needs Screen
#       Recording permission for the terminal) while switching tabs/games with -kaikuTab/-kaikuRoute relaunches,
#       then -kaikuSimulateLate for the notch island peek. No Accessibility permission needed.
# mac-snap: no screen permission needed: in-app PNGs of the Mac panes → $OUT/mac-snapshots/ (stills, not video).
# post: title card + trim + ≤1080p h264 (< 25 MB), a contact sheet PNG, a preview GIF and <clip>-steps.txt (the
#       time code of every DEMO-STEP chapter in the final clip) per clip.
set -eu   # no pipefail: ffmpeg -i / -list_devices exit non-zero by design
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
APPLE="$ROOT/apps/apple"
CLOUD="${KAIKU_TEST_CLOUD:-http://127.0.0.1:18020}"
HOME_ID="${KAIKU_TEST_HOME:-aino}"
SERVICE_NAME="${KAIKU_TEST_SERVICE_NAME:-Kaiku home service}"
TESTS="${TESTS:-testA_FirstRun:iphone-1-first-run testB_TodayPath:iphone-2-today-path testC_TodaySoFar:iphone-3-today-so-far testD_Talk:iphone-4-talk testE_YouAndGlassesCheck:iphone-5-you-glasses-check}"
OUT="${OUT:-$ROOT/demo/recordings}"
RAW="$OUT/raw"
# Build products must live outside ~/Documents, ~/Desktop and ~/Downloads: a simulator app launched by XCUITest loads
# test dylibs from the build folder, and macOS privacy protection blocks that open() forever (white screen, then
# "Setting up automation session" times out after 60 s with kAXErrorServerNotFound).
DERIVED="${DERIVED:-$HOME/Library/Caches/kaiku-record-dd}"
FFMPEG="${FFMPEG:-$(command -v ffmpeg || echo /opt/homebrew/bin/ffmpeg)}"
FONT="/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"
[ -f "$FONT" ] || FONT="/System/Library/Fonts/Helvetica.ttc"
SHOTS="${SHOTS:-$OUT/shots}"
mkdir -p "$RAW" "$SHOTS"
what="${1:-all}"

[ "$what" = post ] || curl -fsS "$CLOUD/healthz" >/dev/null || { echo "cloud not reachable at $CLOUD (start it + seed first)"; exit 1; }

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
  # KAIKU_BUILD_SERVICE=1 builds the app with this cloud as its configured service (KAIKU_SERVICE_URL), so a fresh
  # install connects by itself during setup and Kaiku's hello is spoken (cached voice lines cost nothing).
  xcodebuild -project "$APPLE/Kaiku.xcodeproj" -scheme "Kaiku iOS" -destination "platform=iOS Simulator,id=$udid" \
    -derivedDataPath "$DERIVED" build-for-testing -quiet ${KAIKU_BUILD_SERVICE:+KAIKU_SERVICE_URL="$CLOUD"}
  # the recording cloud shows up on the "nearby services" step (Bonjour carries no home ID and no credentials)
  local port="${CLOUD##*:}"; port="${port%%/*}"
  dns-sd -R "$SERVICE_NAME" _kaiku-api._tcp local. "$port" service=kaiku-api path=/v1/discovery scheme=http v=1 >/dev/null 2>&1 & local adv=$!
  trap "kill $adv 2>/dev/null || true" EXIT
  for t in $TESTS; do
    local m="${t%%:*}" name="${t##*:}"
    case "$m" in testA_*)                                                  # fresh install → first run
      xcrun simctl uninstall "$udid" fi.kaiku.app 2>/dev/null || true
      # a pairing lives in the Keychain and survives an uninstall: clear it, on the dedicated simulator only
      [ -n "${SIM_UDID:-}" ] || xcrun simctl keychain "$udid" reset 2>/dev/null || true;;
    esac
    xcrun simctl io "$udid" recordVideo --codec h264 --force "$RAW/$name.mp4" 2>"$RAW/$name.rec" & local rec=$!
    # the first frame is written several seconds after the command starts: time zero is "Recording started"
    for _ in $(seq 1 150); do grep -q "Recording started" "$RAW/$name.rec" 2>/dev/null && break; sleep 0.2; done
    # The recording only gets going once the screen has changed: without this the first seconds of the app
    # (the welcome screen) are missing from the video. Flip the appearance and back, on the home screen.
    xcrun simctl ui "$udid" appearance dark 2>/dev/null || true; sleep 1.5
    xcrun simctl ui "$udid" appearance light 2>/dev/null || true; sleep 1.5
    local t0; t0=$(now)
    TEST_RUNNER_KAIKU_TEST_CLOUD="$CLOUD" TEST_RUNNER_KAIKU_TEST_HOME="$HOME_ID" TEST_RUNNER_KAIKU_SHOT_DIR="$SHOTS" \
      TEST_RUNNER_KAIKU_TEST_SERVICE_NAME="$SERVICE_NAME" xcodebuild -project "$APPLE/Kaiku.xcodeproj" -scheme "Kaiku iOS" \
      -destination "platform=iOS Simulator,id=$udid" -derivedDataPath "$DERIVED" test-without-building \
      -only-testing:"Kaiku iOS UITests/DemoTourTests/$m" 2>&1 | tee "$RAW/$name.log" | grep -E "DEMO-|passed|failed" || true
    sleep 1
    kill -INT "$rec"; wait "$rec" 2>/dev/null || true
    awk -v t0="$t0" '/DEMO-STEP/ {printf "%s %.2f\n", $2, $3 - t0}' "$RAW/$name.log" > "$RAW/$name.steps"
    # the test's last moment in the app (after it, the recording shows the home screen): post cuts there
    awk -v t0="$t0" '/DEMO-END/ {printf "%.2f\n", $2 - t0 - 0.3}' "$RAW/$name.log" > "$RAW/$name.end"
    # trim the home-screen wait before the app's first step (DEMO-STEP <name> <epoch>)
    awk -v t0="$t0" '/DEMO-STEP/ {printf "%.2f\n", ($3 - t0 > 3 ? $3 - t0 - 3 : 0); exit}' "$RAW/$name.log" > "$RAW/$name.trim"
  done
  kill "$adv" 2>/dev/null || true
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
  "$app/Contents/MacOS/Kaiku" -kaikuSkipOnboarding YES -kaikuPairLink "$CLOUD/?home=$HOME_ID" -kaiku.lang en \
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

# Stills when the terminal may not record the screen: the Debug build draws each pane itself (-kaikuSnapshot,
# ImageRenderer: no real window, switches and text fields are placeholders) with an in-memory pairing, then quits.
snap_mac() {
  (cd "$APPLE" && xcodegen -q)
  xcodebuild -project "$APPLE/Kaiku.xcodeproj" -scheme "Kaiku Mac" -destination "platform=macOS" \
    -derivedDataPath "$DERIVED" build -quiet
  local app; app="$(mac_app)"; local dir="$OUT/mac-snapshots"; mkdir -p "$dir"
  for v in today:today: play:play: lantern:play:lantern seeds:play:seeds talk:talk: days:days: you:you:; do
    local name tab route; IFS=: read -r name tab route <<<"$v"
    "$app/Contents/MacOS/Kaiku" -kaikuSnapshot "$dir/mac-$name.png" -kaikuSnapshotSize 980x720 \
      -kaikuSnapshotPair "$CLOUD/?home=$HOME_ID" -kaikuSkipOnboarding YES -kaiku.lang en -AppleLanguages "(en)" \
      -kaikuMute YES -kaikuInspectOnly YES -kaikuTab "$tab" ${route:+-kaikuRoute "$route"} >/dev/null 2>&1 &
    local pid=$!
    for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    kill "$pid" 2>/dev/null || true
    [ -f "$dir/mac-$name.png" ] && echo "$dir/mac-$name.png" || echo "no snapshot for $name"
  done
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
      iphone-1-first-run) title="Kaiku — first run";;
      iphone-2-today-path) title="Kaiku — today's path";;
      iphone-3-today-so-far) title="Kaiku — Your days, today so far";;
      iphone-4-talk) title="Kaiku — Talk";;
      iphone-5-you-glasses-check) title="Kaiku — You, sharing choices and Glasses check";;
      iphone-6-firefly) title="Kaiku — Firefly";;
      iphone-7-glasses-walk-simulated) title="Kaiku — walk with glasses (simulated glasses)";;
      mac-tour) title="Kaiku — Mac app and notch island";;
      mac-menubar) title="Kaiku — Mac menu bar";;
      *) title="Kaiku — $name";;
    esac
    local trim=0; [ -s "$RAW/$name.trim" ] && trim=$(cat "$RAW/$name.trim")
    # Wall clock → video time. The video runs some seconds ahead of the clock the test prints (about 2 to 10 s,
    # different for every take, and not steady during the first seconds). The one sure mark is the end: the home screen comes
    # back when the test ends (DEMO-END), which is the last big scene change in the video. Chapter marks are
    # printed after a step's tap and pause, so a chapter starts a second or two after its screen appears.
    local lag=0 cut=""
    if [ -s "$RAW/$name.end" ] && [ -s "$RAW/$name.steps" ]; then
      local still; still=$("$FFMPEG" -i "$f" -vf "select='gt(scene,0.2)',showinfo" -an -f null - 2>&1 | sed -n 's/.*pts_time:\([0-9.]*\).*/\1/p' | tail -1)
      if [ -n "$still" ]; then
        lag=$(awk -v e="$(cat "$RAW/$name.end")" -v h="$still" 'BEGIN { d = e + 0.4 - h; printf "%.2f", (d > 0 ? d : 0) }')
        cut=":end=$(awk -v h="$still" 'BEGIN { printf "%.2f", h - 0.2 }')"
        trim=$(awk -v l="$lag" 'NR == 1 { t = $2 - l - 3; printf "%.2f", (t > 0 ? t : 0) }' "$RAW/$name.steps")
      fi
    fi
    local note="Simulated record · no model calls in this take · Kaiku words are on screen"
    # 2.5 s title card, then the clip (speed ${SPEED:-1}x), scaled to ≤1080 high, h264 CRF tuned for < 25 MB
    local vf="scale=-2:'min(1080,ih)',setpts=PTS/${SPEED:-1},fps=30,format=yuv420p"
    local size; size=$("$FFMPEG" -i "$f" 2>&1 | sed -n 's/.*Video:.* \([0-9]\{3,\}\)x\([0-9]\{3,\}\).*/\1 \2/p' | head -1)
    local w h; read -r w h <<<"$size"
    local card=2.5
    if "$FFMPEG" -hide_banner -filters 2>/dev/null | grep -q " drawtext "; then
      "$FFMPEG" -y -loglevel error -i "$f" -f lavfi -i "color=c=0xF6EFE4:s=${w}x${h}:d=2.5:r=30" -filter_complex \
        "[1:v]drawtext=fontfile='$FONT':text='$title':fontcolor=0x3B2F2A:fontsize=h/22:x=(w-text_w)/2:y=(h-text_h)/2,\
drawtext=fontfile='$FONT':text='$note':fontcolor=0x7A6A60:fontsize=h/55:x=(w-text_w)/2:y=(h/2)+h/14,$vf[t];\
[0:v]trim=start=$trim$cut,setpts=PTS-STARTPTS,$vf[c];[t][c]concat=n=2:v=1[v]" \
        -map "[v]" -c:v libx264 -preset slow -crf "${CRF:-28}" -movflags +faststart "$OUT/$name.mp4"
    else                                   # this ffmpeg has no drawtext (built without freetype): no title card
      card=0
      "$FFMPEG" -y -loglevel error -i "$f" -vf "trim=start=$trim$cut,setpts=PTS-STARTPTS,$vf" \
        -c:v libx264 -preset slow -crf "${CRF:-28}" -movflags +faststart "$OUT/$name.mp4"
    fi
    # contact sheet (12 frames) + short GIF preview
    local dur; dur=$("$FFMPEG" -i "$OUT/$name.mp4" 2>&1 | sed -n 's/.*Duration: \([0-9:.]*\).*/\1/p' | awk -F: '{print $1*3600+$2*60+$3}')
    "$FFMPEG" -y -loglevel error -i "$OUT/$name.mp4" -vf "fps=12/$dur,scale=-2:480,tile=6x2:padding=6:color=white" -frames:v 1 "$OUT/$name-sheet.png"
    "$FFMPEG" -y -loglevel error -ss 3 -t 12 -i "$OUT/$name.mp4" -vf "fps=8,scale=-2:400:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer" "$OUT/$name.gif"
    if [ -s "$RAW/$name.steps" ]; then      # chapter → time code in the final clip (title card, trim, speed)
      awk -v trim="$trim" -v sp="${SPEED:-1}" -v card="$card" -v lag="$lag" '{t = card + ($2 - lag - trim) / sp; if (t < card) t = card; printf "%d:%04.1f  %s\n", int(t / 60), t - 60 * int(t / 60), $1}' \
        "$RAW/$name.steps" > "$OUT/$name-steps.txt"
    fi
    echo "$name: $(du -h "$OUT/$name.mp4" | cut -f1) ${dur}s"
  done
}

case "$what" in
  ios) record_ios;; mac) record_mac;; mac-snap) snap_mac;; post) post;;
  all) record_ios; record_mac; post;;
  *) echo "usage: $0 [ios|mac|mac-snap|post|all]"; exit 2;;
esac
