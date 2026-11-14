# apple — AGENTS.md

> Read the root `AGENTS.md` first. Owner A (workstreams A1 core · A2 iPhone extras · A3 Mac extras) · kind app.
> This is the module's only doc. Update it in the same commit as any change to the module's interface, structure
> or invariants (and `modules.toml` if what it emits/consumes changes). Each fact once — link, don't copy.

## Purpose
The native iPhone and Mac apps (plan 02 §4–§5, scope-guard step 3): the same Kaiku as the robot, in your pocket and
on your desk. One XcodeGen project, one shared Swift package `KaikuKit` (contracts, API client, offline queue,
pairing, safety gate, mascot, components, every screen and game); the iOS and Mac targets are thin shells. Look,
screens and copy are implemented from `design/` (`ia.md`, `layout.md`, `motion.md`, `copy.json`,
`mascot.spec.json`, `generated/Tokens.swift`) — never re-picked by eye.

## Boundaries
Imports nothing from the repo at build time. Ground-truth files are **copied** into KaikuKit by
`scripts/sync_design.sh` (`design/generated/Tokens.swift`, `design/copy.json`, `design/mascot.spec.json`,
`config/safety_phrases.toml`); `SyncFreshnessTests` fails when a copy is stale. Talks to the cloud over HTTPS only.
Never holds a Gemini key: Live uses the cloud-minted ephemeral token (root rule 5).

## Consumes (topics/endpoints)
- `GET /v1/me` (mascot mood, garden, highlights, next suggestion), `GET /v1/nudge` (the one suggestion),
  `GET /v1/events?home_id=&since=` (today's receipt + robot connection state).
- `GET /v1/me/memories`, `DELETE /v1/me/memories[/{id}]`, `PUT /v1/me/memory_settings` (What Kaiku remembers).
- `POST /v1/companion/session {surface: iphone|mac, intent: talk}` → `live_token` → Gemini Live WebSocket
  (`BidiGenerateContentConstrained?access_token=`); `POST /v1/companion/tool` for `executor: cloud` tools;
  `POST /v1/companion/episode` when Talk closes (no transcript). `GET /v1/voice?lang=` (all line texts) +
  `GET /v1/voice/{key}?lang=` (audio, prefetched on Wi-Fi into Caches; 503/offline → on-device synthesizer).
- iPhone: Apple Health (read-only, HealthKit), Meta glasses via the DAT SDK (MWDAT 1.0.1, SPM; Motion = dev/beta
  channel), local notifications (no APNs), ActivityKit (no push), App Intents.
- All shapes: `contracts/schemas/` (mirrored in `KaikuKit/Model/Contracts.swift`).

## Emits (topics/endpoints)
`POST /v1/events` (source `phone` on iPhone, `laptop` on Mac), always through the offline queue:
- `obs.self_report` ×3 (`channel: phone|mac`, `context: adhoc`) — weather check; `record_dial` tool in Talk.
- `obs.play_session` (`device: phone|mac`) — `firefly` (reaction median/IQR, lapses > 500 ms or missed, false
  taps), `pebbles` (`span_max`, `accuracy`), `breathe` (duration), `tell` (speech_rate, pause_ratio — only with the
  voice signal on). Sent only with the check-ins signal on and nothing paused.
- `obs.safety_flag {trigger: manual|phrase, handled_locally: true}` — "I'm not OK" or a crisis phrase typed/spoken
  on this device (docs/safety.md: the care team is told).
- Mac only: `obs.screen_activity` hourly (usage rhythm, D26) — only with the `mac` signal on; `paused: true` for an
  hour that was (partly) paused. Numbers + category keys only (see Mac extras).
  on this device (docs/safety.md: the care team is told). Spoken = the on-device Speech gate during Talk.
- iPhone (A2): `obs.self_report {item: mood, value: 4|3|2}` from the check-in reminder's Good · Okay · Low buttons;
  `obs.nudge_outcome {arm, accepted}` — Let's go / tap = true, Not today or no answer within 4 h = false ("Later"
  sends nothing: the final answer counts); `obs.outing {method: dat_imu | steps}` at walk end (cadence, gait
  regularity, head-up ratio from the glasses IMU; daylight minutes only when brightness readings arrive), a walk the
  app never finished is posted on the next launch with the same id; `obs.wearable_daily` once per local morning
  (id = UUIDv8 of home + date → a re-sync is a duplicate), only with the Watch signal on.

## Map
```
project.yml                 XcodeGen: KaikuKit + MWDAT (SPM) + "Kaiku iOS" (17.2+) + "Kaiku Widgets" (extension) +
                            "Kaiku iOS UITests" + "Kaiku Mac" (14+); entitlements: HealthKit, App Group group.fi.kaiku
scripts/sync_design.sh      copy design/ + config/safety_phrases.toml into KaikuKit (plain copies)
iOS/KaikuApp.swift          shell: WindowGroup + pairing deep link
Mac/KaikuMacApp.swift       shell: Window (min 720×480) + MenuBarExtra popover (+ debug "simulate a late evening")
Mac/MacCompanion.swift      Mac extras: usage sampler (NSWorkspace + CGEventSource idle, 30 s), peek evaluation,
                            full-screen/call-app check, DailyInvitation (UNUserNotificationCenter)
Mac/NotchIsland.swift       one level-26 window from the screen top: one shape, collapsed → peek → expanded
Mac/DebugSnapshot.swift     layout PNGs: -kaikuSnapshot (pane), -kaikuIslandSnapshot (island)
iOS/KaikuApp.swift          shell + app delegate: notification answers, kaiku:// links, BGAppRefresh, foreground sync
iOS/KaikuIntents.swift      App Intents + App Shortcuts (check in, walk, breathe, talk)
iOS/DATGlasses.swift        DAT adapter (MWDATCore/Motion; Mock Device Kit in DEBUG) + GlassesChoice (-kaikuGlasses)
iOS/SurfaceSnapshots.swift  DEBUG: -kaikuSurfaceSnapshot <dir> → Live Activity / island / widget PNGs, small + large
iOS/Resources/              kaiku-chime.caf (0.8 s notification sound)
Shared/WalkIntents.swift    LiveActivityIntents Found one / End walk (compiled into app + widget extension)
Widgets/KaikuWidgets.swift  widget extension: Walk + Breathe Live Activities, Kaiku widget (small/medium/lock)
iOSUITests/                 end-to-end against a local cloud (weather → self_report, pebbles → play_session, memories)
KaikuKit/Sources/KaikuKit/
  Design/Tokens.swift       COPY of design/generated/Tokens.swift (never edit here)
  Design/Theme.swift        Dynamic Type for token styles (@ScaledMetric, heading caps), stacksMascot
  Copy/L10n.swift           T("key") over copy.json + copy.apple.json (overlay of keys copy.json lacks)
  Model/Contracts.swift     Envelope, SelfReport, PlaySession, SafetyFlag, Me/Memories/Companion API models
  Model/UUID7.swift         envelope ids (made once, kept through the queue)
  Model/AppModel.swift      @Observable app state, settings, recording, crisis
  Net/APIClient.swift       async client: timeouts, retry + backoff + jitter, Bearer home token
  Net/OfflineQueue.swift    outbox.json in Application Support; batch flush; idempotent by id
  Net/Pairing.swift         ?home=&t= link parser; Keychain storage (file fallback for unsigned sim builds)
  Safety/SafetyGate.swift   port of kaiku_contracts/safety.py + a tiny TOML reader
  Mascot/                   MascotSpec (decodes mascot.spec.json, SVG paths, easings), MascotView (Canvas)
  Components/               buttons, NotOK pill, screen/header, cards, rows, toggles, segmented, dial, toast,
                            bubbles, empty/loading/offline/error states, RingStage
  Screens/                  Screens.swift (tabs, routes, parity list, root/tab bar/sidebar), Today, Weather check,
                            Play, Your days, You (+ remembers, saw today, voice, quiet hours, devices, help),
                            Crisis, Onboarding, MenuBarPopover
  Games/                    Firefly, Pebble path, Breathe, Tell Kaiku (+ Composer, mic card)
  Talk/                     TalkView/TalkModel, LiveSession (Gemini Live WS), AudioCapture (+ SpeechFeatures VAD)
  Platform/                 Haptics, platform constants, QR scanner (iOS)
  Mac/                      pure Mac-extras logic (tested): MacIslandGeometry/Shape/Layout (the island), MacUsage (bundle-id → category table, aggregator,
                            ScreenActivity payload, MacUsageStore = the local aggregate), MacPeek (peek rules +
                            ledger, invitation time)
  Notify/                   NudgeScheduler (pure plan: quiet hours, windows, one invitation/day, snooze once,
                            done-on-any-surface), Notifier (UN requests, categories, answers, ignored after 4 h), DeepLink
  Voice/                    VoiceLines (cache + synthesizer fallback), TalkAudio (HFP session, interruptions, routes),
                            OnDeviceListener (Speech, on-device only → safety gate + SpokenDial), SpokenDial (en/fi/sv)
  Walk/                     WalkModel (light hunt walk, draft recovery), WalkView, GaitAnalyzer + DaylightCounter,
                            KaikuActivities (ActivityKit attributes + start/update/end)
  Glasses/                  GlassesAdapter protocol, MockGlasses + MockGait (synthetic IMU)
  Health/                   HealthSync (HealthKit queries, debug sample data), WearableDailyBuilder (pure)
  Widgets/                  WidgetSnapshot (App Group), SurfaceViews (LA/island/widget content), KaikuGlyph
KaikuKit/Tests/KaikuKitTests/  safety fixture parity, sync freshness, copy keys, contract shapes, UUIDv7,
                            pairing, game logic, speech features, mascot spec, offline queue, parity table;
                            MacExtrasTests (usage aggregation + payload privacy, peek rules, invitation time)
```

## Parity
One screen list (`KaikuScreen` in `Screens/Screens.swift`) rendered by both targets. Same tab names and order.

| screen | iPhone | Mac | notes |
|---|---|---|---|
| `onboardingWelcome` · `onboardingPair` · `onboardingConsent` · `onboardingNotifications` · `onboardingMeet` | ✓ | ✓ | pair: QR scan on iPhone (paste fallback), paste link on Mac; consent lists this device's signals |
| `today` · `weatherCheck` | ✓ | ✓ | haptic tick per dial step (trackpad on Mac) |
| `play` · `firefly` · `pebbles` · `tell` · `breathe` | ✓ | ✓ | Breathe also runs a Live Activity on iPhone |
| `walk` | ✓ | — | iPhone only: Light hunt walk (+ glasses, Live Activity, Dynamic Island) |
| `talk` | ✓ | ✓ | Live only with a cloud token; scripted typed path otherwise |
| `days` · `markDay` | ✓ | ✓ | day marks are local (no contract yet) |
| `you` · `memories` · `saw` · `voice` · `quiet` · `devices` · `help` | ✓ | ✓ | Devices: glasses (ready / connected during a walk), watch (Health); debug "Try it out" section |
| `crisis` | ✓ | ✓ | full screen on iPhone, sheet on Mac |
| `menuBarPopover` | — | ✓ | platform-only; + notch island (not a screen: an overlay panel, see Mac extras) |

## Mac extras (A3)
- **Notch island** (`Mac/NotchIsland.swift`, design/ia.md → Mac extras): ONE non-activating borderless window at
  level statusBar + 1 (26), top edge at the top of the screen, centred on the notch of the notch screen (else main;
  recomputed on screen-parameter, Space and wake changes), drawing ONE `MacIslandShape`: in the menu bar band it is
  never wider than notch + ≤ 60 pt wings (never over menu titles or status items); below it flares out (concave
  shoulders) into the body. Collapsed ↔ peek ↔ expanded is one spring on the shape. Peek = Kaiku + one line + two
  buttons; expanded = + "Not today", Talk; click the notch while collapsed = "hello" (greeting, Talk, Open).
  Everything is inside the shape (content clipped to it). Mouse-through except inside the drawn shape. No notch →
  the body is a pill under the menu bar. Pure logic in KaikuKit/Mac (tested): `MacIslandGeometry` (where),
  `MacIslandShape` (silhouette), `MacIslandLayout` (inner layout). Sizes: `design/layout.md`; springs:
  `design/motion.md`. `MascotView` uses `.kaikuMascotOnDark` there (light, larger z's on black); `cycleStart`
  anchors any loop (the snapshot pins the sleepy loop where the z's show).
- **Peek rules** (`KaikuKit/Mac/MacPeek.swift`, plan 03 §5.4, pure + tested): late night 01:00–05:00 while active
  (input in the last 60 s) → `mac.late` sleepy Kaiku, one per night; a stretch > 90 active min without a 5-min
  break → `mac.stretch`, again only 90 min later; max 3 a day; snooze 1 h ("Five more minutes"/"Later") or today
  ("Not today"), stored as wall-clock dates in UserDefaults (`kaiku.mac.peeks`), so it holds across
  sleep/wake and relaunch. Never while paused, never with a full-screen window or a call app in front (best effort:
  window bounds via CGWindowList, no titles). Quiet hours silence the stretch peek; the late peek is the bedtime
  nudge itself, so it is the one quiet hours don't silence.
- **Usage rhythm** (D26, `MacCompanion.tick` + `KaikuKit/Mac/MacUsage.swift`): opt-in (`mac` signal). Every 30 s:
  frontmost app's bundle id → broad category on the spot (bundled table; browsers and unknown apps are `other`;
  the id is never stored), system idle seconds, a count of app switches. Aggregated locally into
  `Application Support/Kaiku/mac_usage.json` (numbers + category keys only); each closed hour →
  `obs.screen_activity` via the offline queue. Pause (menu bar "Pause for 1 hour", You → pause everything) marks
  the hour `paused` and counts nothing. "What Kaiku saw today" shows the same local aggregate (active minutes,
  after-midnight minutes, minutes by app type).
- **Daily invitation**: one local notification with today's suggestion line at 17:00, moved to the end of quiet
  hours when it falls inside them; replanned when the suggestion changes; nothing while paused or unpaired.
  `DailyInvitation.schedule(app:)` is the interface to swap for a shared scheduler (A2) later.
- **Demo**: menu bar → "Simulate a late evening" (debug builds) or launch with `-kaikuSimulateLate YES` feeds a
  synthetic 00:00–01:10 through the same aggregator and rules: the island peeks at once and the closed hour goes to
  the cloud as `obs.screen_activity` with `sim: true` (the real aggregate and peek ledger are untouched).

## Extension points
- **New screen:** add a `KaikuRoute` (+ `destination`), a `KaikuScreen` case and a row in the parity table above
  (`ParityTests` checks). Copy keys go to `design/copy.json` (or `copy.apple.json` until upstreamed).
- **New game:** a view using `GameShell` (intro → play → gentle end) that calls `finish(PlaySession)`; add its
  card in `PlayView`. New `play_session` fields are a contract change first.
- **New device tool (Talk):** handle it in `TalkModel.tool`; cloud tools need nothing here.
- **New look:** change `design/`, `make design`, `apps/apple/scripts/sync_design.sh`.
- **New notification kind:** a `NudgeScheduler.Kind` + rule in `plan` (+ tests), a category in `Notifier`.
- **New glasses / wearable vendor:** a `GlassesAdapter` (events: state, imu, brightness, tap), chosen in
  `GlassesChoice`; the walk and its outing don't change.
- **New Live Activity:** attributes in `Walk/KaikuActivities.swift`, content view in `Widgets/SurfaceViews.swift`,
  configuration in `Widgets/KaikuWidgets.swift`, a snapshot in `iOS/SurfaceSnapshots.swift`.

## Invariants
- No inline user strings: every visible string is `T("key")`; `L10nTests` checks every literal key exists in en + fi.
- Only token colours; `crisis` only on the crisis screen. Crisis screen: no mascot, no motion, scripted text verbatim
  from `config/safety_phrases.toml`; "I'm not OK" on every screen (header on iPhone, sidebar + popover on Mac).
- Never on screen: scores, streaks, trends, state words, dev text. Firefly ends with a jar, never a number.
- No audio, transcript, typed text or camera frame is stored or sent. Speech features are computed in memory.
- Every obs goes through `OfflineQueue` with an id fixed at creation (retries are duplicates the cloud ignores).
- The local safety gate gives the same answer as `kaiku_contracts.safety` on `safety_cases.json` (tested).
- Notifications: at most one invitation a day + one check-in reminder + PHQ-9 once; never in quiet hours, never a
  crisis message, never time-sensitive; never mention Health/watch data. Rules live only in `NudgeScheduler`.
- The on-device listener only runs with `requiresOnDeviceRecognition`; transcripts are never kept or sent.
- Widgets and Live Activities never call the network: they read the App Group snapshot / activity state.
- Layout holds `design/layout.md`'s stress case (fi + long name + large text + 320 pt): text wraps, rows stack at
  accessibility sizes, headings cap their growth, fixed game screens give the field the room.

## Run standalone
```
cd apps/apple && xcodegen                      # → Kaiku.xcodeproj (not committed)
(cd KaikuKit && swift test)                    # unit tests (macOS)
xcodebuild -project Kaiku.xcodeproj -scheme "Kaiku iOS" -destination "generic/platform=iOS Simulator" build
xcodebuild -project Kaiku.xcodeproj -scheme "Kaiku Mac" -destination "platform=macOS" build
```
Without a cloud the app runs offline: Today shows the sky banner, check-ins and games queue on disk, Talk offers
the typed scripted path. Launch arguments for dev/screenshots (UserDefaults argument domain):
`-kaikuSkipOnboarding YES`, `-kaikuPairLink "http://127.0.0.1:8000/?home=demo-aino"`, `-kaiku.lang fi`,
`-kaikuTab play`, `-kaikuRoute firefly`, `-kaikuAutostart YES` (skip a game intro), `-kaikuName Annemarie-Kristiina`
(layout stress), `-kaikuShowCrisis YES`, `-kaikuOnboardingStep 2`; Mac only: `-kaikuSnapshot /tmp/x.png`
(ImageRenderer PNG of the pane at the minimum window size; text fields/switches render as placeholders there),
`-kaikuSimulateLate YES` (the 01:10 peek + a sim screen_activity), `-kaikuIslandSnapshot /tmp/i.png` (PNG of a menu-bar slice
with the island collapsed, peeking and expanded, 2× + `.1x.png`, once it has peeked).
iPhone (A2): `-kaikuRoute walk -kaikuAutostart YES` (start a walk), `-kaikuGlasses mock|datmock|dat|none`,
`-kaikuGlassesDropAfter 20` (glasses disconnect mid-walk), `-kaikuNotifyTest checkin|invite -kaikuNotifyDelay 8`
(the real notification in n s), `-kaikuHealthSample YES` (DEBUG: write a sample night to Health + sync),
`-kaikuMute YES` (no voice), `-kaikuSurfaceSnapshot <dir>` (DEBUG: Live Activity / island / widget PNGs).

## Run with sim
```
make cloud-local & make seed                   # demo-aino with memories, highlights, garden
cd apps/apple && xcodegen
xcodebuild test -project Kaiku.xcodeproj -scheme "Kaiku iOS" -destination "platform=iOS Simulator,name=<iPhone>"
#   UITests pair to $KAIKU_TEST_CLOUD (default http://127.0.0.1:8000; pass TEST_RUNNER_KAIKU_TEST_CLOUD=...)
xcrun simctl launch booted fi.kaiku.app -kaikuSkipOnboarding YES -kaikuPairLink "http://127.0.0.1:8000/?home=demo-aino"
```
Mac: `defaults write fi.kaiku.mac kaiku.consents -dict mac -bool true checkins -bool true`, then run
`Kaiku.app/Contents/MacOS/Kaiku -kaikuSkipOnboarding YES -kaikuPairLink "http://127.0.0.1:8000/?home=demo-aino"
-kaikuSimulateLate YES` → the island peeks with sleepy Kaiku; `GET /v1/events?home_id=demo-aino` shows an
`obs.screen_activity` (source `laptop`, `sim: true`, `late_night_min: 60`).
A2 end to end (real lock screen, island, notification actions, Health sheet):
`TEST_RUNNER_KAIKU_TEST_CLOUD=http://127.0.0.1:8000 TEST_RUNNER_KAIKU_SHOT_DIR=/tmp/shots xcodebuild test ...
-only-testing:"Kaiku iOS UITests/ExtrasFlowTests"` → `obs.self_report` (Low = 2), `obs.nudge_outcome`,
`obs.outing {method: dat_imu}`, `obs.wearable_daily` land in `GET /v1/events`.
Expect: Today greets Aino with the cozy (scarf) mascot; the weather check lands in `GET /v1/events` as three
`obs.self_report` with `channel: phone`; a game posts `obs.play_session`; You → What Kaiku remembers lists the
seeded memories. With `KAIKU_HOME_TOKEN` set on the cloud, add `&t=<token>` to the pairing link.

## Config & env
No `config/*.toml` keys are read at runtime. Bundled copies: `design/copy.json`, `design/mascot.spec.json`,
`design/generated/Tokens.swift`, `config/safety_phrases.toml`. Pairing (cloud URL, home id, token) is in the
Keychain; settings (language, consents, pauses, quiet hours, day marks) in UserDefaults. Info.plist usage strings
(mic, camera, speech, Health, motion, Bluetooth) and the `MWDAT` dictionary (Developer Mode: `MetaAppID 0`,
callback `kaiku://`, analytics opt-out) live in `project.yml`. Widgets read `group.fi.kaiku` (UserDefaults suite).
Notification bookkeeping (delivered, answered, snooze, usual check-in time) is UserDefaults `kaiku.notify`.

## Health signal
The app has no heartbeat (not a bus node). You → "Paired with Kaiku at home" + "n things waiting to be sent" shows
the queue; the offline banner shows when the cloud is unreachable. Builds green + `swift test` green = healthy.

## Tests
`cd apps/apple/KaikuKit && swift test` (49 tests): safety fixture parity with the Python matcher, every phrase hits,
scripts verbatim; design copies fresh; copy keys exist (en + fi, placeholders match, overlay never shadows
copy.json); payloads ⊆ schema properties and required present, enums and device tools match the registry;
UUIDv7 layout; pairing links; pebble span/miss/accuracy, firefly scoring, median/IQR, speech features VAD; mascot
spec (all states, ear map, blink modes, parts); offline queue (dedupe, persists across restart, flushes once
online); parity table; Mac extras: category table = schema categories, hourly aggregation (minutes by category,
late night, breaks, sleep gap, longest stretch, switches/h, paused), payload = numbers + category keys only (no
ids), receipt reads the persisted aggregate, peek edges (00:59 vs 01:00, 89/90 vs 91 min, the 4th peek, one late
peek a night, snooze across sleep/wake, paused/blocked), invitation time vs quiet hours, island geometry (notch screen = the lead's 1512 × 982 MacBook, wings clamped to
the gap, non-notch, external display, screen picking), island shape (band = collapsed width at every row
of the menu bar, body = expanded width, concave shoulders, collapsed = strip, pill), Kaiku + its z's inside the
body's 16 pt content rect in peek and expanded at 1× and 2×. UI: `Kaiku iOS UITests` (needs a seeded cloud).
online); parity table. A2 (+21): scheduler §7 cases (21:59 vs 22:00 quiet, walked on glasses, check-in on the
robot, Later once, Not today / delivered final, timezone change keeps ids, DST day, paused, PHQ-9 once, weekend
sleep-in), deep links, spoken dial en/fi/sv + on-device gate en/fi/sv, gait (cadence/regularity/head-up on the
mock walk, standing still), daylight, wearable builder (merge, midpoint, no data → no obs, idempotent id), A2
payloads ⊆ schemas. UI: `Kaiku iOS UITests` (needs a seeded cloud): `KaikuFlowTests` + `ExtrasFlowTests`.

## Known issues
- Gemini Live path is written to the documented WebSocket protocol but **not exercised against the real API** (no
  key in dev; the cloud returns `live_token: null`). Output audio plays 24 kHz PCM; barge-in = `interrupted`.
- `copy.apple.json` holds ~90 keys `design/copy.json` lacks (no-name greetings, suggestion lines per nudge arm, A2 notification / walk / widget / Live Activity lines,
  offline Talk, scripted replies, receipt lines with numbers, pairing errors, a11y labels). Design owner: upstream
  them, then delete them here. Also `days.sheet.title`, `saw.*`, `mem.1..3`, `talk.say1` in copy.json are demo
  values the app does not use.
- `/v1/me` highlights text is English-only from the cloud (shows in Finnish UI).
- Day marks (good/hard) are stored on the device only: no contract carries them yet.
- `tell` pitch_variability not computed (nil). iPhone tilt → eyes (CoreMotion) not wired; Mac cursor look is.
- Light hunt, Live Activity/Dynamic Island, widgets, HealthKit, glasses (A2) are not here yet; Devices shows
  glasses/watch as "Not set up".
- Mac extras: the stretch line has no `config/voice_lines.toml` key yet (text only, `copy.apple.json`); "screen
  sharing" is guessed from a call app being frontmost (macOS gives no public sharing flag); the notch island's
  breathing slim state and the nudge peek (`mac.nudge`, design/ia.md) are not built; the daily invitation is a
  local scheduler (swap for A2's when it lands); notifications need the person to allow them (onboarding step).
  The island was verified by in-app snapshot (`-kaikuIslandSnapshot`); a real screen capture needs permission.
- Notch island, usage sampler (A3) are not here yet.
- DAT: `DATGlasses` builds and links MWDAT 1.0.1 (Core + Motion + MockDevice) but has **not run against real
  glasses**; with Mock Device Kit in the simulator `createSession` returns `noEligibleDevice` (the walk then goes
  on with the phone, as designed). `MockGlasses` (pure Swift synthetic IMU) is the default in the simulator.
  Camera brightness (daylight minutes) and "Look at this" frames are not wired to DAT yet; glasses taps are.
- Phone-only walks post `method: steps` with CMPedometer steps (nil in the simulator); no background location.
- Notifications answer in the app process (UNUserNotificationCenter delegate; iOS launches the app in the
  background), not a notification extension; no Notification Content Extension (STRETCH). "Later" sends no obs.
- `SpokenDial` is used for on-device Talk transcripts (fills `record_dial` when Live omits the value); there is no
  spoken path on the weather-check screen yet.
- Health background delivery is best effort (observer query); the simulator sample writes sleep, steps, resting HR
  and HRV (exercise minutes are Apple-computed and can't be written).
- Interactive widget (mood buttons) and Control Center control are STRETCH, not built. Lock Screen Live Activity
  has no buttons (Found one / End walk are in the expanded island), so Kaiku can fill the 160 pt height.
- The care-team call button shows a toast only (no "please call me" endpoint).
- Mac `-kaikuSnapshot` uses ImageRenderer (no ScrollView, toggles/text fields render as placeholders); real
  window capture needs screen-recording permission.
