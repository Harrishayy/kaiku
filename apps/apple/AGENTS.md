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
  `POST /v1/companion/episode` when Talk closes (no transcript). `GET /v1/voice/{key}` (voice sample).
- All shapes: `contracts/schemas/` (mirrored in `KaikuKit/Model/Contracts.swift`).

## Emits (topics/endpoints)
`POST /v1/events` (source `phone` on iPhone, `laptop` on Mac), always through the offline queue:
- `obs.self_report` ×3 (`channel: phone|mac`, `context: adhoc`) — weather check; `record_dial` tool in Talk.
- `obs.play_session` (`device: phone|mac`) — `firefly` (reaction median/IQR, lapses > 500 ms or missed, false
  taps), `pebbles` (`span_max`, `accuracy`), `breathe` (duration), `tell` (speech_rate, pause_ratio — only with the
  voice signal on). Sent only with the check-ins signal on and nothing paused.
- `obs.safety_flag {trigger: manual|phrase, handled_locally: true}` — "I'm not OK" or a crisis phrase typed/spoken
  on this device (docs/safety.md: the care team is told).

## Map
```
project.yml                 XcodeGen: KaikuKit package + "Kaiku iOS" (17+) + "Kaiku iOS UITests" + "Kaiku Mac" (14+)
scripts/sync_design.sh      copy design/ + config/safety_phrases.toml into KaikuKit (plain copies)
iOS/KaikuApp.swift          shell: WindowGroup + pairing deep link
Mac/KaikuMacApp.swift       shell: Window (min 720×480) + MenuBarExtra popover; DebugSnapshot.swift (layout PNGs)
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
KaikuKit/Tests/KaikuKitTests/  safety fixture parity, sync freshness, copy keys, contract shapes, UUIDv7,
                            pairing, game logic, speech features, mascot spec, offline queue, parity table
```

## Parity
One screen list (`KaikuScreen` in `Screens/Screens.swift`) rendered by both targets. Same tab names and order.

| screen | iPhone | Mac | notes |
|---|---|---|---|
| `onboardingWelcome` · `onboardingPair` · `onboardingConsent` · `onboardingNotifications` · `onboardingMeet` | ✓ | ✓ | pair: QR scan on iPhone (paste fallback), paste link on Mac; consent lists this device's signals |
| `today` · `weatherCheck` | ✓ | ✓ | haptic tick per dial step (trackpad on Mac) |
| `play` · `firefly` · `pebbles` · `tell` · `breathe` | ✓ | ✓ | Light hunt → A2 (glasses) |
| `talk` | ✓ | ✓ | Live only with a cloud token; scripted typed path otherwise |
| `days` · `markDay` | ✓ | ✓ | day marks are local (no contract yet) |
| `you` · `memories` · `saw` · `voice` · `quiet` · `devices` · `help` | ✓ | ✓ | glasses/watch rows show "Not set up" until A2 adapters |
| `crisis` | ✓ | ✓ | full screen on iPhone, sheet on Mac |
| `menuBarPopover` | — | ✓ | platform-only; notch island → A3 |

## Extension points
- **New screen:** add a `KaikuRoute` (+ `destination`), a `KaikuScreen` case and a row in the parity table above
  (`ParityTests` checks). Copy keys go to `design/copy.json` (or `copy.apple.json` until upstreamed).
- **New game:** a view using `GameShell` (intro → play → gentle end) that calls `finish(PlaySession)`; add its
  card in `PlayView`. New `play_session` fields are a contract change first.
- **New device tool (Talk):** handle it in `TalkModel.tool`; cloud tools need nothing here.
- **New look:** change `design/`, `make design`, `apps/apple/scripts/sync_design.sh`.

## Invariants
- No inline user strings: every visible string is `T("key")`; `L10nTests` checks every literal key exists in en + fi.
- Only token colours; `crisis` only on the crisis screen. Crisis screen: no mascot, no motion, scripted text verbatim
  from `config/safety_phrases.toml`; "I'm not OK" on every screen (header on iPhone, sidebar + popover on Mac).
- Never on screen: scores, streaks, trends, state words, dev text. Firefly ends with a jar, never a number.
- No audio, transcript, typed text or camera frame is stored or sent. Speech features are computed in memory.
- Every obs goes through `OfflineQueue` with an id fixed at creation (retries are duplicates the cloud ignores).
- The local safety gate gives the same answer as `kaiku_contracts.safety` on `safety_cases.json` (tested).
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
(ImageRenderer PNG of the pane at the minimum window size; text fields/switches render as placeholders there).

## Run with sim
```
make cloud-local & make seed                   # demo-aino with memories, highlights, garden
cd apps/apple && xcodegen
xcodebuild test -project Kaiku.xcodeproj -scheme "Kaiku iOS" -destination "platform=iOS Simulator,name=<iPhone>"
#   UITests pair to $KAIKU_TEST_CLOUD (default http://127.0.0.1:8000; pass TEST_RUNNER_KAIKU_TEST_CLOUD=...)
xcrun simctl launch booted fi.kaiku.app -kaikuSkipOnboarding YES -kaikuPairLink "http://127.0.0.1:8000/?home=demo-aino"
```
Expect: Today greets Aino with the cozy (scarf) mascot; the weather check lands in `GET /v1/events` as three
`obs.self_report` with `channel: phone`; a game posts `obs.play_session`; You → What Kaiku remembers lists the
seeded memories. With `KAIKU_HOME_TOKEN` set on the cloud, add `&t=<token>` to the pairing link.

## Config & env
No `config/*.toml` keys are read at runtime. Bundled copies: `design/copy.json`, `design/mascot.spec.json`,
`design/generated/Tokens.swift`, `config/safety_phrases.toml`. Pairing (cloud URL, home id, token) is in the
Keychain; settings (language, consents, pauses, quiet hours, day marks) in UserDefaults. Info.plist usage strings
(mic, camera) mirror `perm.mic.d` and live in `project.yml`.

## Health signal
The app has no heartbeat (not a bus node). You → "Paired with Kaiku at home" + "n things waiting to be sent" shows
the queue; the offline banner shows when the cloud is unreachable. Builds green + `swift test` green = healthy.

## Tests
`cd apps/apple/KaikuKit && swift test` (25 tests): safety fixture parity with the Python matcher, every phrase hits,
scripts verbatim; design copies fresh; copy keys exist (en + fi, placeholders match, overlay never shadows
copy.json); payloads ⊆ schema properties and required present, enums and device tools match the registry;
UUIDv7 layout; pairing links; pebble span/miss/accuracy, firefly scoring, median/IQR, speech features VAD; mascot
spec (all states, ear map, blink modes, parts); offline queue (dedupe, persists across restart, flushes once
online); parity table. UI: `Kaiku iOS UITests` (needs a seeded cloud).

## Known issues
- Gemini Live path is written to the documented WebSocket protocol but **not exercised against the real API** (no
  key in dev; the cloud returns `live_token: null`). Output audio plays 24 kHz PCM; barge-in = `interrupted`.
- `copy.apple.json` holds ~50 keys `design/copy.json` lacks (no-name greetings, suggestion lines per nudge arm,
  offline Talk, scripted replies, receipt lines with numbers, pairing errors, a11y labels). Design owner: upstream
  them, then delete them here. Also `days.sheet.title`, `saw.*`, `mem.1..3`, `talk.say1` in copy.json are demo
  values the app does not use.
- `/v1/me` highlights text is English-only from the cloud (shows in Finnish UI).
- Day marks (good/hard) are stored on the device only: no contract carries them yet.
- `tell` pitch_variability not computed (nil). iPhone tilt → eyes (CoreMotion) not wired; Mac cursor look is.
- Light hunt, Live Activity/Dynamic Island, widgets, HealthKit, glasses (A2) and notch island, usage sampler (A3)
  are not here yet; Devices shows glasses/watch as "Not set up".
- The care-team call button shows a toast only (no "please call me" endpoint).
- Mac `-kaikuSnapshot` uses ImageRenderer (no ScrollView, toggles/text fields render as placeholders); real
  window capture needs screen-recording permission.
