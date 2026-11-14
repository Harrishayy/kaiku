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
- `GET /v1/me` (mascot mood, garden + `garden.days` = one plot per local day for 14 days, highlights, next suggestion), `GET /v1/nudge` (the one suggestion),
  `GET /v1/events?home_id=&since=` (today's receipt + robot connection state).
- `GET /v1/me/memories`, `DELETE /v1/me/memories[/{id}]`, `PUT /v1/me/memory_settings` (What Kaiku remembers).
- `POST /v1/companion/session {surface: iphone|mac, intent: talk}` (Talk) or `{surface: glasses, intent: walk}`
  (the walk companion, through Meta glasses) → `live_token` (locks only the model) + `live_setup` (persona, voice,
  `[live]` turn detection) → Gemini Live WebSocket (`BidiGenerateContentConstrained?access_token=`); the device's own
  setup frame adds resumption, compression and tool behaviour, and on the loudspeaker takes the cloud's VAD.
  Reconnect bootstraps include `resume_session_id`; `max_session_seconds` ends capture at the cloud budget limit.
  `POST /v1/companion/tool` for `executor: cloud` tools (`ask_mind`, `recall`, `remember`… — the knowledge graph
  stays in the cloud); `POST /v1/companion/episode` when the conversation closes (+ `transcript` only with the
  opt-in `transcripts` signal, D33). `GET /v1/me/transcripts` + `DELETE /v1/me/transcripts` (count + delete all in
  What Kaiku remembers). See "Conversation pipeline". Kaiku's voice outside Live is always Gemini TTS:
  `GET /v1/voice?lang=` (line texts), `GET /v1/voice/{key}?lang=` (prefetched on Wi-Fi, fetched on demand on a miss),
  `POST /v1/voice/say` (the app's own lines, cached by text hash). **Never an on-device synthesizer**: cloud
  unreachable AND nothing cached → silent, the text stays on screen.
- iPhone: Apple Health (read-only, HealthKit), Meta glasses via the DAT SDK (MWDAT 1.0.1, SPM; Motion = dev/beta
  channel), local notifications (no APNs), ActivityKit (no push), App Intents.
- All shapes: `contracts/schemas/` (mirrored in `KaikuKit/Model/Contracts.swift`).

## Emits (topics/endpoints)
`POST /v1/events` (source `phone` on iPhone, `laptop` on Mac), always through the offline queue:
- `obs.self_report` ×3 (`channel: phone|mac`, `context: adhoc`) — weather check; `record_dial` tool in Talk.
- `obs.play_session` (`device: phone|mac`) — `firefly` (reaction median/IQR, lapses > 500 ms or missed, false
  taps), `pebbles` (`span_max`, `accuracy`), `breathe` (duration), `tell` (speech_rate, pause_ratio — only with the
  voice signal on). Sent only with the check-ins signal on and nothing paused.
  Measured games (`GameHistory.measured`): `lantern` (reaction median/IQR/CV, `response_speed`, lapses,
  `false_starts`), `seeds` (`throughput_per_min`, accuracy, time per packet), `watering` (`hard_choice_ratio`,
  `tap_rate_hz`), and `pebbles`; each with `trials_n`, `valid_n`, `input`, `session_index`, `warmup` (first 3
  sessions per game on this device), `valid` + `flags`, and the compact trial record `rt_ms` + `trial_codes`. The
  envelope `quality` is 0.2 for a doubtful session (criteria skip it), else the share of usable trials.
- `obs.safety_flag {trigger: manual|phrase, handled_locally: true}` — "I'm not OK" or a crisis phrase typed/spoken
  on this device. A stored flag does not confirm care-team delivery; the crisis screen says to contact them directly.
- Mac only: `obs.screen_activity` hourly (usage rhythm, D26) — only with the `mac` signal on; `paused: true` for an
  hour that was (partly) paused. Numbers + category keys only (see Mac extras).
- iPhone (A2): `obs.self_report {item: mood, value: 4|3|2}` from the check-in reminder's Good · Okay · Low buttons;
  `obs.nudge_outcome {arm, accepted}` — Let's go / tap = true, Not today or no answer within 4 h = false ("Later"
  sends nothing: the final answer counts); `obs.outing {method: dat_imu | steps}` at walk end (cadence, gait
  regularity, head-up ratio from the glasses IMU; daylight minutes only when brightness readings arrive), a walk the
  app never finished is posted on the next launch with the same id and `sim` flag only when its original home
  and server are paired. Drafts persist destination identity without credentials; unscoped legacy drafts stay
  quarantined. Active walk completion also checks its starting destination. `obs.wearable_daily` on changed
  Health snapshots (id hashes home + summary; timestamp is capture time, payload.date is the target day), only
  with the Watch signal on. Equal snapshots deduplicate; late samples become newer observations.

## Map
```
project.yml                 XcodeGen: KaikuKit + MWDAT (SPM) + "Kaiku iOS" (17.2+) + "Kaiku Widgets" (extension) +
                            "Kaiku iOS UITests" + "Kaiku Mac" (14+); entitlements: HealthKit, App Group group.fi.kaiku
scripts/sync_design.sh      copy design/ + config/safety_phrases.toml into KaikuKit (plain copies)
scripts/make_app_icon.sh    app icons from MascotView (AppIconRenderTests, opt-in) → iOS + Mac AppIcon sets
scripts/run_on_iphone.sh    sign (KAIKU_TEAM), install [+ launch] on a paired iPhone; works on a locked phone (`--install-only`,
                            or a locked-launch refusal is reported, not fatal); profile and pairing are kept
scripts/live_e2e.sh         paid real Gemini Live check (barge-in, graph tool, opt-in transcript) → demo/recordings
iOS|Mac/Assets.xcassets     AppIcon (generated; light + dark on iOS) · */PrivacyInfo.xcprivacy (App Store manifests)
iOS|Widgets/*.entitlements  plain files picked by CODE_SIGN_ENTITLEMENTS (+ `.nogroup` variants, see Config & env)
scripts/record_app_demo.sh  demo videos of both apps (DemoTourTests + Mac screen capture); demo_mouse.swift helper
iOS/KaikuApp.swift          shell: WindowGroup + pairing deep link
Mac/KaikuMacApp.swift       shell: Window (min 720×480) + MenuBarExtra popover (+ debug "simulate a late evening")
Mac/MacCompanion.swift      Mac extras: usage sampler (NSWorkspace + CGEventSource idle, 30 s), peek evaluation,
                            full-screen/call-app check, DailyInvitation (UNUserNotificationCenter)
Mac/NotchIsland.swift       one level-26 window from the screen top: one shape, collapsed → peek → expanded
Mac/DebugSnapshot.swift     layout PNGs: -kaikuSnapshot (pane), -kaikuIslandSnapshot (island)
iOS/KaikuApp.swift          shell + app delegate: notification answers, kaiku:// links, BGAppRefresh, foreground sync
iOS/KaikuIntents.swift      App Intents + App Shortcuts (check in, walk, breathe, talk)
iOS/DATGlasses.swift        DAT adapter (MWDATCore/Motion/Camera; Mock Device Kit in DEBUG), DATControl (check screen),
                            GlassesChoice (-kaikuGlasses)
iOS/SurfaceSnapshots.swift  DEBUG: -kaikuSurfaceSnapshot <dir> → Live Activity / island / widget PNGs, small + large
iOS/Resources/              kaiku-chime.caf (0.8 s notification sound)
Shared/WalkIntents.swift    LiveActivityIntents Found one / End walk (compiled into app + widget extension)
Widgets/KaikuWidgets.swift  widget extension: Walk + Breathe Live Activities, Kaiku widget (small/medium/lock)
iOSUITests/                 end-to-end against a local cloud (weather → self_report, pebbles → play_session, memories);
                            DemoTourTests = the paced feature tour the demo recordings are made from
KaikuKit/Sources/KaikuKit/
  Design/Tokens.swift       COPY of design/generated/Tokens.swift (never edit here)
  Design/Theme.swift        Dynamic Type for token styles (@ScaledMetric, heading caps), stacksMascot
  Copy/L10n.swift           T("key") over copy.json + copy.apple.json (overlay of keys copy.json lacks)
  Model/Contracts.swift     Envelope, SelfReport, PlaySession, SafetyFlag, Me/Memories/Companion API models
  Model/UUID7.swift         envelope ids (made once, kept through the queue)
  Model/AppModel.swift      @Observable app state, settings, recording, crisis
  Net/APIClient.swift       async client: timeouts, retry + backoff + jitter, Bearer home token
  Net/OfflineQueue.swift    origin/home-scoped observation outbox; batch flush; idempotent by id
  Net/EpisodeOutbox.swift   origin/home-scoped durable completions and opt-in transcript retry
  Net/Pairing.swift         ?home=&t= link parser; Keychain storage (file fallback for unsigned sim builds)
  Safety/SafetyGate.swift   port of kaiku_contracts/safety.py + a tiny TOML reader
  Mascot/                   MascotSpec (decodes mascot.spec.json, SVG paths, easings), MascotView (Canvas)
  Components/               buttons, NotOK pill, screen/header, cards, rows, toggles, segmented, WeatherDial, toast,
                            bubbles, KChip, KChevron, Celebration (completion moment), empty/loading/offline/error states, RingStage; Polish.swift (KTone soft fills,
                            KPressStyle press/hover, KBackdrop time-of-day wash, MascotHalo, KAdaptiveColumns)
  Screens/                  TodayPath.swift (Today's path: weather → suggestion → game, on Today/Play/game ends;
                            GardenBeds day plots + DayPlant), Screens.swift (tabs, routes, parity list, root/tab bar/sidebar), Today, Weather check,
                            Play, Your days, You (+ remembers, saw today, voice, quiet hours, devices, help),
                            Crisis, Onboarding (OnboardingFlow + SetupStep), EvidenceView (Today, so far), MenuBarPopover
  Games/                    Firefly, Pebble path, Breathe, Tell Kaiku (+ Composer, mic card); measured games:
                            LanternGame (simple reaction time), SeedGame (symbol–digit), WateringGame (effort
                            choice), each a pure engine + a field; GameKit (stats, input provenance, GameHistory
                            = session count / warm-up / quality, GameRotation, GameTrialLog = raw trials on device)
  Talk/                     Conversation (one spoken conversation: bootstrap, Live, tools, safety, resumption),
                            LiveSession (Gemini Live WS protocol: pure setup builder + frame parser),
                            ConversationAudio (mic + Kaiku's voice on one voice-processing engine, HFP glasses mic,
                            barge-in flush), MicDownsampler (any mic format → 16 kHz PCM16), TalkView/TalkModel (compact header Kaiku = tap to mute/unmute,
                            full-width transcript, TalkBubble ≤ 80 %, welcome + starters), AudioCapture (Tell Kaiku)
  Platform/                 Haptics, platform constants, QR scanner (iOS), Sound (synthesised soft UI tones)
  Mac/                      pure Mac-extras logic (tested): MacIslandGeometry/Shape/Layout (the island), MacUsage (bundle-id → category table, aggregator,
                            ScreenActivity payload, MacUsageStore = the local aggregate), MacPeek (peek rules +
                            ledger, invitation time)
  Notify/                   NudgeScheduler (pure plan: quiet hours, windows, one invitation/day, snooze once,
                            done-on-any-surface), Notifier (UN requests, categories, answers, ignored after 4 h), DeepLink
  Voice/                    VoiceLines (Gemini TTS: keyed + /v1/voice/say, cached; silent when unavailable, never a synthesizer),
                            TalkAudio (HFP session, interruptions, routes), OnDeviceListener (Speech, on-device only:
                            safety backstop + SpokenDial; never shown or said), SpokenDial (en/fi/sv)
  Walk/                     WalkModel (light hunt walk, draft recovery), WalkView, GaitAnalyzer + DaylightCounter,
                            KaikuActivities (ActivityKit attributes + start/update/end)
  Glasses/                  GlassesAdapter protocol, MockGlasses + MockGait (synthetic IMU, synthetic frames);
                            GlassesDiagnostics (GlassesLog JSONL, GlassesVision, GlassesStatus, GlassesControl)
  TaskCapture/TaskCamera.swift  video-only AVFoundation + Vision, scalar geometry accumulator, consent/lifecycle controller
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
| `onboardingWelcome` · `onboardingAbout` · `onboardingPair` · `onboardingConsent` · `onboardingPermissions` · `onboardingHello` | ✓ | ✓ | first-run setup (`SetupStep`, see "First-run setup"): welcome → what Kaiku is and isn't → nearby companion services (advanced account link for authenticated services) → choices → permissions in context → first hello + one practice task; Health and glasses rows on iPhone only |
| `today` · `weatherCheck` | ✓ | ✓ | haptic tick per dial step (trackpad on Mac) |
| `play` · `firefly` · `pebbles` · `tell` · `breathe` | ✓ | ✓ | Breathe also runs a Live Activity on iPhone |
| `lantern` · `seeds` · `watering` | ✓ | ✓ | measured games: touch on iPhone; Space / click, 1–9, ← → + Space on Mac |
| `walk` | ✓ | — | iPhone only: Light hunt walk (+ glasses, Live Activity, Dynamic Island) |
| `talk` | ✓ | ✓ | continuous Gemini Live with a cloud token (tap Kaiku to talk/stop, typing too); scripted typed path otherwise |
| `days` · `markDay` | ✓ | ✓ | day marks are local (no contract yet) |
| `glasses` | ✓ | — | You → Glasses check: toolkit, sound route, Live and camera state, 20-second self-test, shareable log |
| `you` · `memories` · `saw` · `voice` · `quiet` · `devices` · `help` | ✓ | ✓ | Devices: glasses (ready / connected during a walk), watch (Health); debug "Try it out" section |
| `crisis` | ✓ | ✓ | full screen on iPhone, sheet on Mac |
| `menuBarPopover` | — | ✓ | platform-only; + notch island (not a screen: an overlay panel, see Mac extras) |

## Conversation pipeline (Talk + glasses walk)
```
Meta glasses mics (HFP, beamformed) / phone / Mac mic
  → ConversationAudio: one AVAudioEngine, voice processing (echo cancel), 16 kHz PCM16 → LiveSession → Gemini Live
  ← Kaiku's voice 24 kHz ← Live, played on the same engine (glasses speakers over HFP)
person talks over Kaiku → server VAD → `interrupted` → queued voice flushed at once → Live listens (barge-in)
Live tool call → device tool (Conversation.deviceTool: express, record_dial, start_activity, log_walk_moment,
  look_at_this) or POST /v1/companion/tool (ask_mind → mind router: memory / knowledge graph / Flash / Argon;
  recall, remember, forget, suggest_nudge, end_session) → result back into the conversation
```
- Setup (`LiveSession.setup`, tested): server VAD with `START_OF_ACTIVITY_INTERRUPTS`; start sensitivity HIGH on a
  headset route (glasses), LOW on a loudspeaker (echo leftovers must not interrupt); end LOW + 800 ms silence
  (slow speakers with long pauses aren't cut off); affective dialog; proactive audio; input + output
  transcription; context-window sliding compression (walks > 15 min); session resumption. `ask_mind` is
  `NON_BLOCKING` (Kaiku keeps talking while the mind thinks; answer scheduled `WHEN_IDLE`).
- Context events: the walk sends `[walk started · …]`, `[found one · n of 3]`, `[walk · 10 min]`, `[glasses
  disconnected · …]`; Talk sends `[the person just opened Talk]` (Kaiku greets in its live voice) and
  `[back after an interruption …]`. Same wording as the hub's `send_context`.
- Reconnect: `goAway` or a drop → reconnect with the last resumption handle; same token until 60 s before its
  `expires_at`, else a fresh token from `POST /v1/companion/session` (episode + tools keep the first session id).
  Three failures in a row → `unavailable` (Talk: typed scripted path; walk: scripted voice lines).
- Safety: input transcripts (also joined with the previous partial) + the on-device listener (restarted every
  50 s) run `SafetyGate` first; a hit stops the conversation (`outcome: crisis`) and opens the crisis screen.
- Glasses: Ray-Ban Meta / Ray-Ban Display paired in the Meta AI app and connected to the iPhone over Bluetooth
  are the mic + speaker (HFP, `TalkAudio.preferHeadsetInput`). The DAT session (IMU, later camera) is separate and
  optional; the conversation works with Bluetooth alone. The Display web app has no mic (Meta docs), so speech
  never goes through it. The robot runs its own Live session in the hub; the same mind serves both.
- UI: Talk = open conversation; tap Kaiku to stop / start listening (`talk.live`, `talk.muted`). Walk screen:
  "Quiet walk" / "Talk with Kaiku".

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
  card in `PlayView`. New `play_session` fields are a contract change first. A game that measures something:
  a pure engine with the time passed in (see `LanternEngine`), practice trials inside the field, balanced trials
  from the system generator (never a fixed seed), validity flags, `GameTrialLog` for the raw trials, its id in
  `GameHistory.measured` (+ `GameRotation.cycle` to be in Today's path), a `[[metric]]` with `warmup = false`,
  and a paragraph in `docs/validation.md` → Games saying what it can and cannot say.
- **New device tool:** handle it in the surface's `Conversation.deviceTool` (`TalkModel.deviceTool`,
  `WalkModel.walkTool`); cloud tools need nothing here.
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
- Never on screen: scores, streaks, trends, state words, dev text. Firefly ends with a jar, never a number;
  the measured games end with the sky you lit, sprouts, a flower bed. No reaction time, count or "slow" anywhere.
- Today's path = weather → suggestion → Lantern (daily) → one rotating game (`GameRotation`: seed shelf, pebble
  path, watering): about three minutes of games a day. Reaction times use the monotonic clock and touch-down,
  not touch-up; the lantern's flame is the one thing that appears at once (design/motion.md → Game feedback).
- No raw audio or camera frame is stored. During an explicitly opened Live conversation, audio streams to Gemini
  using a cloud-minted token; cloud tools can receive the text needed for their request. Saving conversation
  words in an episode's `transcript` separately requires the opt-in `transcripts` signal (off by default), never
  after a crisis (D33). Numeric task capture does not upload audio or words.
- Every obs goes through `OfflineQueue` with an id fixed at creation (retries are duplicates the cloud ignores).
  Entries retain server origin and home; re-pairing cannot deliver them to a different destination. Legacy entries
  without origin remain quarantined on disk. `EpisodeOutbox` durably stores metadata and opt-in transcript at stop,
  before starting delivery; foreground/reconnect retries it. Turning transcript consent off or forgetting
  conversations strips pending words. Crisis completions never carry words. No credentials are written there.
- Changing the paired home or cloud clears cached person summaries, notebook, transcript count, Health status,
  local day marks and activity ticks before refresh. Language, voice pace and other device preferences remain.
  Pairing revisions reject late reads, write-result rollbacks and Health summaries from the previous pairing.
  Health delivery rechecks Watch consent after each awaited query and binds emitted envelopes to the original
  pairing. Active Live conversations close and clear visible words; active walk/finished state is cleared too.
- `ConversationAudio.onPCM` goes through the production `Conversation` controller to `LiveSession.sendAudio`.
  Setup must be ready; mute, pause, closed sessions and changed pairing block transmission. Old socket callbacks
  cannot affect a replacement socket. `end_session` and the session duration limit stop microphone capture.
  Global "Pause everything" also closes an active conversation without waiting for another audio frame and
  prevents bootstrap/capture while paused. Unpausing requires an explicit conversation restart.
- `record_dial` uses the same pause/consent/value checks as manual check-ins. Both Talk and walks support it.
  Talk supports `start_phq9` and walking activities. PHQ-9 forwards pairing credentials in a consumed URL fragment.
- Mock adapters are explicit debug choices, never automatic fallbacks; their outings carry `sim=true` through
  normal completion and draft recovery. Real motion connection is shown only after a sample arrives.
- The local safety gate gives the same answer as `kaiku_contracts.safety` on `safety_cases.json` (tested).
- Notifications: at most one invitation a day + one check-in reminder + PHQ-9 once; never in quiet hours, never a
  crisis message, never time-sensitive; never mention Health/watch data. Rules live only in `NudgeScheduler`.
- The on-device listener only runs with `requiresOnDeviceRecognition`; its partial transcripts are never kept or sent.
- Widgets and Live Activities never call the network: they read the App Group snapshot / activity state.
- Layout holds `design/layout.md`'s stress case (fi + long name + large text + 320 pt): text wraps, rows stack at
  accessibility sizes, headings cap their growth, fixed game screens give the field the room.
- One viewport: every tab, the weather check and every game fit without scrolling at the default Mac window
  (980 × 720, two columns ≥ 600 pt) and on iPhone 16 Pro at default text; scrolling is only the fallback (SE,
  accessibility sizes, the minimum window). Games: intro with a looping demo → play (scene, thin progress, no
  score) → warm end; every tap answered in ≤ 100 ms (design/motion.md → Game feedback), hover + keyboard on Mac
  (Space catches a firefly / toggles Tell Kaiku, 1–9 or arrows + Space on pebbles, ←/→ on dials, Return starts,
  Esc goes back). Sounds respect You → Little sounds and the silent switch.

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
(ImageRenderer PNG of a drawn sidebar + the pane; `-kaikuSnapshotSize 980x720` for the window size, default the
720 × 480 minimum; `-kaikuSnapshotPair <link>` pairs in memory only, never touching the Keychain or pairing file;
text fields/switches render as placeholders there),
`-kaikuSimulateLate YES` (the 01:10 peek + a sim screen_activity), `-kaikuIslandSnapshot /tmp/i.png` (PNG of a menu-bar slice
with the island collapsed, peeking and expanded, 2× + `.1x.png`, once it has peeked).
iPhone (A2): `-kaikuRoute walk -kaikuAutostart YES` (start a walk), `-kaikuGlasses mock|datmock|dat|none`,
`-kaikuGlassesDropAfter 20` (glasses disconnect mid-walk), `-kaikuNotifyTest checkin|invite -kaikuNotifyDelay 8`
(the real notification in n s), `-kaikuHealthSample YES` (DEBUG: write a sample night to Health + sync),
`-kaikuMute YES` (no voice), `-kaikuSurfaceSnapshot <dir>` (DEBUG: Live Activity / island / widget PNGs).
Talk: `-kaikuTab talk -kaikuTalkSay "text"` types one message once Live is up (real Live path, for screenshots).

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

## Recording a demo
`apps/apple/scripts/record_app_demo.sh [ios|mac|mac-snap|post|all]` against a local cloud seeded with the one
person (no keys, so no paid calls: where Kaiku's voice would play its words are on screen):
```
KAIKU_NO_DOTENV=1 KAIKU_LLM=template KAIKU_VOICE=text KAIKU_DEMO_MODE=1 KAIKU_DB_PATH=/tmp/k.db \
  uv run uvicorn kaiku_cloud.api.main:app --port 18020 &
uv run python -m kaiku_cloud.jobs.single_person --url http://127.0.0.1:18020
KAIKU_TEST_CLOUD=http://127.0.0.1:18020 apps/apple/scripts/record_app_demo.sh ios    # then: ... post
```
- **ios**: `iOSUITests/DemoTourTests`, one method = one flow = one `simctl io recordVideo` clip, driven at a
  person's pace on a dedicated "Kaiku Demo 17 Pro" simulator: `testA_FirstRun` (fresh install + Keychain reset →
  the six setup steps → Today), `testB_TodayPath` (weather dials → Kaiku's suggestion → Lantern played → the
  rotating game played → "All done for today"), `testC_TodaySoFar` (Your days → Today, so far → What Kaiku saw
  today), `testD_Talk` (the voice control, the voice-unavailable state, a typed message and the scripted reply),
  `testE_YouAndGlassesCheck` (sharing choices, Glasses check, self-test). Extras through `TESTS=method:clip ...`:
  `testF_Firefly`, `testG_GlassesWalkSimulated` (`-kaikuGlasses mock`). A missing control logs `DEMO-MISSING` plus
  what was on screen and the flow goes on; `DEMO-STEP` lines become chapter time codes; step screenshots land in
  `demo/recordings/shots/`. The games are played through two test-only accessibility identifiers that are never
  spoken or shown: `lantern-lit` / `lantern-dark` on the lantern field and `seed-pot-<n>` on the seed packet.
- Build products go to `~/Library/Caches/kaiku-record-dd` (`DERIVED`). Not under `~/Documents`: macOS privacy
  protection blocks a simulator app launched by XCUITest from loading the test dylibs there (white screen, then
  "Setting up automation session" times out with `kAXErrorServerNotFound`).
- **mac**: one launch of the Debug build; `kaiku://` links switch screens (the Mac shell follows them like
  iPhone; `kaiku://you/<memories|saw|voice|quiet|devices|help>`), keys play the games, the menu bar popover's debug
  "Simulate a late evening" makes the island peek, `scripts/demo_mouse.swift` hovers/clicks it. Needs Screen
  Recording + Accessibility for the terminal (without them ffmpeg and osascript just hang). The full-screen
  capture is cropped to the Kaiku window + notch (`mac-tour`) and the popover (`mac-menubar`) and then deleted.
- **mac-snap**: no permission needed: `-kaikuSnapshot` stills of the panes → `demo/recordings/mac-snapshots/`
  (layout checks, not demo footage: no scrolling, switches and text fields are placeholders).
- **post**: trims the wait before the app and the home screen after it, real speed (`SPEED`), ≤ 1080 p h264, plus
  `<clip>-sheet.png`, `<clip>.gif` and `<clip>-steps.txt` (chapter time codes). A title card is added only when
  ffmpeg has `drawtext`.

## Config & env
- Signing / store: App Store Connect name **Kaikuu** (Kaiku was taken), bundle `fi.kaiku.app`; home-screen name
  stays "Kaiku". Build settings `KAIKU_APP_GROUP` (default `group.fi.kaiku`; App Group ids are unique across Apple
  teams) and `KAIKU_ENTITLEMENTS_SUFFIX` (`.nogroup` = sign without the App Group until one is assigned to the
  team's App IDs in the developer portal — command-line signing can't assign it; the widget then shows its
  placeholder). The team id is passed on the command line (`KAIKU_TEAM`), never committed.
  `ITSAppUsesNonExemptEncryption = NO` (TLS only).
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
`cd apps/apple/KaikuKit && swift test` (`LiveSessionTests` = Live setup + frame parsing; `LiveTalkTests` = say-cache key, cloud VAD on the loudspeaker): safety fixture parity with the Python matcher, every phrase hits,
scripts verbatim; design copies fresh; copy keys exist (en + fi, placeholders match, overlay never shadows
copy.json); payloads ⊆ schema properties and required present, enums and device tools match the registry;
UUIDv7 layout; pairing links; pebble span/miss/accuracy, firefly scoring, median/IQR, speech features VAD;
`GamesTests` (measured games: balanced trial generation, scoring, validity flags, warm-up numbering + quality,
rotation fits 3–5 min, raw trial log, payloads ⊆ schema + enums, envelope quality); mascot
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

## Optional task camera and microphone
The Camera signal is off by default. Every activity intro shows its toggle; camera permission is requested only
after the person explicitly starts an activity with that signal enabled. A visible camera status and Stop camera
button remain while capturing. Back, dismissal, background/inactive state, monitoring pause and consent
revocation stop capture and discard unfinished camera measurements. A permission dialog that resolves after
cancellation cannot start the camera. Camera unavailability leaves the task usable.

`TaskCamera` owns this lifecycle through an injectable `TaskCameraSource`; `VisionTaskCamera` uses a video-only
AVFoundation session and on-device Vision face landmarks. It does not configure the application's audio session.
Frames remain inside the serial capture queue/autorelease pool; no images, facial templates or identity are
stored or transmitted. Exactly one face with usable lip and eye landmarks counts toward coverage. Multiple
faces, missing faces and invalid geometry count as uncovered samples and break movement continuity.

`TaskCameraFeatures` samples at 5 Hz. For `camera_method=vision_landmarks`, expressivity is the mean sample
standard deviation of mouth and eye height/width ratios; movement is mean adjacent face-centre displacement
in normalized image coordinates. Movement can include phone/camera motion. At least two valid samples are
required for variability; insufficient measurements stay nil. Sample count and usable-face coverage accompany
the optional `obs.play_session` camera fields (contracts remain the shape authority). These are geometry proxies,
not emotions or diagnoses, and MUST NOT be pooled with MediaPipe blendshape indices. Baselines must preserve
task and method; they do not contribute new consensus votes without calibration.

Tell Kaiku starts its microphone only after both task/voice consent and an explicit press. Its energy-based
speech-rate estimate and pause ratio remain local until the task summary is emitted; no audio or words are
stored. Consent revocation, background, dismissal and cancellation stop and discard the capture. An active
walking Live conversation prevents a second Tell microphone session. Silent games do not open a microphone;
Firefly reaction latency/lapses and Pebbles span/accuracy remain task-derived measurements. Camera fields and
speech fields are scrubbed again at observation emission if the corresponding consent is no longer allowed.

`TaskCameraTests` covers stable/variable synthetic geometry, missing/multiple-face representation, coverage,
method-labelled contract payloads, default-off and denied permission, late permission after cancellation,
completion, revocation and late-frame rejection. No test opens a physical camera. The iOS and Mac camera
usage strings live in project.yml (regenerate with xcodegen).
`KAIKU_TASK_CAPTURE_TEST_CLOUD=http://127.0.0.1:18031 swift test --filter
TaskCameraLifecycleTests/testSyntheticTaskMeasurementsPersistThroughActualRecorder` uses the production
AppModel recorder, durable queue and real API against a dedicated camera-integration home with sim=true.
It verifies method/index/coverage/reaction metrics persist, then camera consent revocation removes camera
fields while preserving task results. It passed on 2026-11-14 without opening any sensor or model.

## Voice control visibility
Talk always displays a labelled voice control, including before a Live connection exists. It says Start voice
conversation, Mute microphone, Resume microphone, Open microphone settings, or Connect Kaiku for voice as
appropriate. Unpaired/unauthorized, unreachable service, unavailable voice and microphone startup failure are
distinct statuses. Pairing is an explicit sheet action and is never silently changed. A live iPhone session
shows Speaking through plus the actual AVAudioSession output name. The mascot remains a secondary shortcut.

## Meta setup and integration verification
Use the real DAT adapter on a physical iPhone. In Meta AI, pair the glasses and enable Developer Mode for this
hackathon build. In Kaiku, You → Devices → Glasses → Set up starts registration without opening the microphone
or starting a walk. A walk also requests registration when needed. `Wearables.startRegistration()` opens Meta AI for approval; Kaiku's URL
callback completes registration. `MetaAppID=0` is the SDK's supported developer-mode configuration (no production
credentials required). Production release channels require Meta-issued application configuration; never commit
client tokens. [Official Meta setup](https://github.com/meta/meta-wearables-dat-ios/blob/main/samples/CameraAccess/README.md).
Registration, device discovery, motion availability and receiving samples are separate states. Unsupported
motion stays unavailable; the phone can still count steps. Microphone/speaker audio uses Bluetooth HFP and is
independent of DAT motion. The camera is opt-in (next section); without it the model is told it cannot see.
Simulator defaults to phone-only; `-kaikuGlasses mock|datmock` explicitly enables debug simulation.

`ConversationControllerTests` exercises the actual Conversation with injected capture/transport and authenticated
HTTP: PCM forwarding, voice playback, barge-in, mute/pause, deterministic crisis, end-session, cloud duration,
resume episode identity, consent, transcript retry after process restart, and cross-server isolation.
While Live is active, the cloud-provided `context_refresh_seconds` controls authenticated source-event refresh.
Only whitelisted completion labels and source provenance are injected when both sides are quiet; permission is
checked again at delivery. No Health metrics, scores, free text or simulated observations are announced. The
voice session is told to ask `ask_mind` for interpretation; its request allows 120 seconds for bounded reasoning. A paid test
uses the production LiveSession and a synthetic PCM fixture (no ambient microphone):
```
KAIKU_CONTROLLER_TEST_CLOUD=http://127.0.0.1:18031 \
KAIKU_CONTROLLER_TEST_SPEECH=/private/tmp/synthetic-16k.pcm \
  swift test --filter ConversationControllerTests/testRealCloudAndGeminiThroughActualController
```
Optional `KAIKU_CONTROLLER_TEST_HOME` and `KAIKU_CONTROLLER_TEST_TOKEN` configure authenticated testing. The test
checks returned voice and person transcript, closes the episode, flushes the durable queue, and reads transcripts
from the real database. It requires a successful `ask_mind` result with `route=gemma` and Gemini audio arriving
after that result; this passed against the isolated real cloud on 2026-11-14 (13.903 seconds). The synthetic
fixture is validated before minting a token. Shared suite after task camera, voice controls, privacy pause,
walk-scope, home-isolation and service-discovery regressions: 121 tests, 5 optional skips, zero failures. The default suite performs no physical capture
or paid integration.
Keep existing cloud model budgets; a budget refusal is not permission to raise them.

## Companion service discovery (phone and glasses do not require a robot)

`Net/ServiceDiscovery.swift` browses `_kaiku-api._tcp` and validates public `GET /v1/discovery` against the shared
API contract. Discovery sends no home identifier, token, queued observation or transcript. Nearby candidates
require the person to select Connect. Only the explicitly configured `KAIKU_SERVICE_URL` build setting can
bootstrap automatically, and only after a valid schema-1 descriptor says `mode=demo`, `auth_required=false`
and advertises `companion_voice`. Production still needs an explicitly supplied account access link; service
advertising never grants credentials. Unconfigured services fail honestly.

Each service origin gets a persisted random `device-<UUID>` home, never a seeded patient. Existing Keychain
profiles are retained and adopted into this map; discovery cannot silently replace them. Explicit switching
uses the existing revision invalidation and outbox scoping. Disconnect disables automatic reprovisioning.
`PairStep` is now the nearby-service picker on both platforms; You → Companion service exposes the current
service host and Find nearby services. QR is absent from onboarding. Meta registration and robot telemetry
remain independent hardware states. `KAIKU_SERVICE_URL` defaults empty; a developer can supply a nonsecret
verified LAN URL during the build. Local network permission is necessary for LAN discovery and API access.

`ServiceDiscoveryTests` covers descriptor/auth/schema gates, explicit selection, stable separate home identities,
existing credential preservation, concurrent probes and disconnect behavior. The optional integration test
`KAIKU_DISCOVERY_TEST_CLOUD=http://127.0.0.1:8000 swift test --filter ServiceDiscoveryTests/testRealDiscoveryAndFreshProfileReadWithoutRobot`
passed against the real demo API without a robot, seeded home, microphone, or paid model request. It is a native
Mac test, not proof of physical iPhone networking. Signed build 3 was verified through the device app inventory (only one Kaiku bundle, `fi.kaiku.app`).
After the user unlocked the phone and enabled local network access, the real LAN server observed successful
`/v1/discovery` and `/v1/me` requests from the distinct phone address. Final signed build 4 was installed over
the existing app and explicitly launched on You without capture. This proves phone-to-backend connectivity;
physical microphone/HFP voice acceptance remains a separate user-started check.

## Known issues
- Measured games (Lantern, Seed shelf, Watering): engines are unit-tested and both targets build; the Mac intro
  screens and Play cards were checked with `-kaikuSnapshot`, but the play fields have not been played on a real
  iPhone yet (touch latency, one-viewport fit on small phones, fi wording by a native speaker). Play now has seven
  cards and Today's path four stops, so the Play tab scrolls on the default Mac window. `GameTrialLog` (raw trials
  on the device) is not shown in "What Kaiku saw today" yet. No fi/sv voice lines for the new games.
- Gemini Live verified against the real API (2026-11-14, `scripts/live_e2e.sh iphone|glasses`, paid ~1 min):
  setup accepted, barge-in (`interrupted` + tool cancellation), input transcription, `recall` → cloud graph →
  spoken answer. Evidence in `demo/recordings/live-e2e/<surface>/` (events.jsonl, kaiku.wav, person.wav,
  timeline.png). `enableAffectiveDialog` is NOT sent: gemini-3.8-live closes with 1007 when it is true.
  Signed physical-iPhone installation succeeded after enabling iPhone Developer Mode. The user confirmed
  Meta registration/connection; this does not establish live IMU samples, HFP audio routing or camera quality. VAD tuning lives in `LiveSession.Tuning` (device code, not config) until a
  contract field carries it. Reconnects reuse the existing open episode through `resume_session_id`.
  `look_at_this` answers "camera not connected" (no DAT camera stream yet).
- `make e2e-intelligence` (repo root, paid, a few cents): token → typed, spoken (automatic VAD) and barge-in turns,
  Gemini TTS keyed + `/v1/voice/say`, `ask_mind` from memory, graph rebuild. Live's output transcript sometimes
  joins words ("itpeaceful"): that text comes from the API as-is.
- `copy.apple.json` holds ~90 keys `design/copy.json` lacks (no-name greetings, suggestion lines per nudge arm, A2 notification / walk / widget / Live Activity lines,
  offline Talk, scripted replies, receipt lines with numbers, pairing errors, a11y labels). Design owner: upstream
  them, then delete them here. Also `days.sheet.title`, `saw.*`, `mem.1..3`, `talk.say1` in copy.json are demo
  values the app does not use.
- `/v1/me` highlights text is English-only from the cloud (shows in Finnish UI).
- Day marks (good/hard) are stored on the device only: no contract carries them yet.
- `tell` pitch_variability not computed (nil). iPhone tilt → eyes (CoreMotion) not wired; Mac cursor look is.
- Light hunt, Live Activities, widgets, HealthKit and the DAT adapter exist. Physical phone microphone routing,
  HealthKit permission/data and Gen 2 glasses registration still require an on-device acceptance test.
- Mac extras: the stretch line has no `config/voice_lines.toml` key yet (text only, `copy.apple.json`); "screen
  sharing" is guessed from a call app being frontmost (macOS gives no public sharing flag); the notch island's
  breathing slim state and the nudge peek (`mac.nudge`, design/ia.md) are not built; the daily invitation is a
  local scheduler (swap for A2's when it lands); notifications need the person to allow them (onboarding step).
  The island was verified by in-app snapshot (`-kaikuIslandSnapshot`); a real screen capture needs permission.
- Notch island and usage sampler exist; remaining Mac limitations are listed above.
- DAT: with Mock Device Kit the session, Motion and the camera stream run in the simulator. On the real glasses
  only registration and "connected" are confirmed; session start, Motion samples, camera frames, the hands-free
  route and the Wi-Fi camera transport still need the physical test in `docs/glasses-test.md`.
  `MockGlasses` (pure Swift) requires the explicit debug `mock` choice; simulator default is phone-only.
  `daylight_min` is never filled from frames (D43). Glasses taps are not wired to the toolkit's Inputs capability.
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

## Invariants (layout on Mac)
- Non-scrolling panes (games, Talk) wrap in `fillsProposal()`: NavigationSplitView measures the detail at a tiny
  width, where vertically fixed wrapping text reports a huge minimum height; without it the split view outgrew
  the window (sidebar list under the traffic lights, crisis pill, game title and Start button clipped).
- Game scenes are a `.background`, never a layout sibling; on Mac they only extend under the toolbar, never under
  the sidebar. Mac pushed screens use the system toolbar back button + `navigationTitle`; Esc via `EscapeKey`.

## Native journey refinements
The current native UI and all companion bootstrap requests use English, regardless of an older language
preference; the language chooser is hidden. Multilingual crisis matching remains available internally.
Talk uses a compact avatar/status/actual output-route header and an accessible microphone control beside
the text composer. Transcript fragments update one bubble per speaker per Live turn, including interleaved
speaker fragments and cumulative prefixes; completed turns remain separate. Safety still scans partial text
immediately. Scrollback stops following incoming words until the person chooses Latest messages or sends.
Offline scripted reply tasks are cancelled on leaving Talk; pairing changes clear the visible conversation.

The final onboarding page shows service connection, microphone access and chosen conversation retention,
explains optional devices, and offers an explicit Try a voice conversation action. It does not mint a token
or open a microphone merely to check readiness. Voice readiness is established only when starting Live.
You exposes sharing/permission switches together, without requiring a visit to the observation receipt.
What Kaiku remembers links to a person-only saved-conversation reader with retry/empty states and confirmed
delete-all. Cached words clear immediately on household/server changes; mismatched-home responses are refused.

Pebble path begins with a separate practice round that can be skipped. Successful practice resets all engine
counts before the unchanged scored protocol starts; scored duration excludes practice. The end shows the actual
longest reproduced path. Optional camera geometry describes the overall activity, including practice; it is not
part of the memory score or a consensus vote. In-flight round playback is cancelled on leaving, and skip uses a
revision guard so old animation tasks cannot overwrite the scored round. This is a playful memory task, not a
validated clinical test or a diagnostic result.

Debug UI inspection: launch the Mac debug build with `-kaikuInspectOnly YES` to disable every Talk-model
bootstrap/retry path before service connection or microphone permission. This permits actual window/navigation
inspection without capture. It does not simulate a connected voice session. The existing ImageRenderer snapshot
is incomplete for ScrollView content and must not be used as proof of chat layout/keyboard behaviour.
The optional actual-controller provider test accepts `KAIKU_CONTROLLER_TEST_SURFACE=iphone|mac` and requires
validated synthetic PCM; it checks primary Gemma attribution, audio after the tool result, and exact retained
turn text/speaker boundaries through real HTTP storage. Never feed ambient recordings or an existing patient DB.
Audio `turnComplete` does not finish transcription. The parser preserves separate input/output transcription
`finished` markers, including marker-only frames. Ordered transport-event delivery keeps late text on its original
speaker bubble across an audio turn boundary and new typed input. Typed input does not steal the pending audio
input stream. An interruption marks the local bubble but late received text is still retained unchanged.
Stored `TranscriptTurn.complete` is true only for explicitly finished (or locally complete typed) text, false
for interrupted/unfinished/truncated text, and nil for unknown older records. The reader labels false as Incomplete
transcript; it makes no completion claim for nil. Bounded text prefixes never claim completeness.
Real-controller proofs must observe both audio turn completion and independent input/output transcription
completion, then wait for the ordered controller callbacks to consume those markers before storing. No arbitrary
settling sleep, ASR correction, or fabricated missing words establishes completeness. Missing markers remain
unknown and cause the strict optional finality proof to fail within its bounded deadline.
For older providers that omit `finished`, the next physical user-transcription after an audio turn boundary
separates prior streams with completion unknown (nil), rather than merging every subsequent spoken turn or
claiming old text is final. Typed input does not force that fallback: a delayed final output can still complete
its original bubble. Without provider final markers/turn IDs there is ambiguity in late old versus new input;
raw text is preserved and unknown completion is not presented as finished. The targeted optional
`testRealTranscriptionFinalityThroughActualController` verifies only audio/transcription completion and exact
persistence; it makes no Gemma/tool-selection claim and does not replace the strict full intelligence test.
A new model-media frame after audio completion separates the prior legacy output generation with unknown
completion, while late output text arriving between new typed input and that next generation stays with its
original bubble. Parsing delivers input text before the generation boundary, then output text/media. Explicit
interruption or known text truncation always stays false, overriding unknown provider status.
The 2026-11-14 synthetic provider capability probe observed audio turn completion but no input/output `finished`
markers. The strict targeted finality test failed as intended; ordinary no-marker records carry nil rather than
being labelled complete or definitively incomplete. This provider boundary is not hidden as a passing proof.

## Speech path hardening (2026-11-14)
- `MicDownsampler` (shared by `ConversationAudio` and `AudioCapture`): takes channel 0 only and feeds
  `AVAudioConverter` exactly the frames it requests. Two defects are covered by `MicDownsamplerTests` with
  synthetic buffers (no microphone): a Mac voice-processing input with 3–9 channels has no converter down-mix,
  and on the no-resampling / upsampling paths (8 and 16 kHz Bluetooth HFP) the converter consumes at most 4096
  frames per call, so larger tap buffers were silently cut.
- `ConversationAudio`: route-change restarts run off the notification thread and reactivate the session;
  `resumeAfterInterruption()` restarts the engine after a phone call / Siri (`Conversation.resume` calls it; the
  session alone does not restart capture); the player is never started on a stopped engine; 120 ms of silence
  leads Kaiku's first chunk after idling (clipped first syllables).
- `LiveSession`: WebSocket ping every 20 s; a failed ping reports `closed` so a silently dead network reconnects.
- `Conversation`: `setupComplete` must arrive within `readyTimeout` (12 s) or the attempt counts as a drop;
  three failures end in `unavailable` with a reason (`voice` before any working turn, `connection` after), never
  an endless "connecting". Talk then shows the reason, keeps the words so far and offers the voice button.
- `OfflineQueue` / `EpisodeOutbox`: a flush that finds another flush running returns success (it used to raise
  the offline banner on a healthy connection).
- Paid proof without a microphone (`RealSpeechPathTests`, 48 kHz fixture → production downsampler →
  `Conversation` + `LiveSession` → real cloud + Gemini Live; twice, with and without the transcripts opt-in):
  `KAIKU_SPEECH_TEST_CLOUD=http://127.0.0.1:<port> KAIKU_SPEECH_TEST_WAV48=<48 kHz mono PCM16>
  [KAIKU_SPEECH_TEST_SURFACE=mac|iphone] swift test --filter RealSpeechPathTests`. Passed on the Mac surface
  2026-11-14 against an isolated cloud (temp DB): person transcript, Kaiku audio 6.3 s + Kaiku transcript, both
  turns stored with the opt-in, nothing stored without it. It does not prove echo cancellation, the physical
  microphone, loudspeaker level or Bluetooth routing: those need a person and a device.

## First-run setup
`SetupStep` (pure, tested) orders the flow: welcome → about (what Kaiku is and is not: not a medical opinion, not
emergency care, 112 and MIELI shown; never skippable) → connect (`PairStep`; skippable, the app works offline) →
choices (signals incl. transcripts, Health, Mac rhythm; reversible in You) → permissions (one row each, asked only
from its own button: microphone, notifications, Apple Health when the Watch choice is on, Meta glasses when the
iOS shell provides `connectGlasses`; asking for the microphone never opens it) → hello (voice line `welcome.hello`
in Kaiku's Gemini voice, silent with the words on screen when there is no service; a practice dial that is not
recorded; completion moment + `welcome.done`) → Today. `AppModel.setupStep` persists the step (resume after a
relaunch), `finishSetup()` lands on Today, `restartSetup()` is You → "Run setup again" (choices, pairing and data
untouched). `-kaikuOnboardingStep <0…5>` jumps to a step; `-kaiku.onboarded NO` shows setup on an onboarded build.
UI: `iOSUITests/SetupFlowTests` (full flow, resume, run again; never presses the microphone row).

## Completion moment and today's evidence
- `AppModel.celebrate()` bumps `celebration`; `KaikuRootView` plays `Components/Celebration.swift` once per bump
  (weather check, any game, a finished walk, the setup task): soft sparks rise and fade over 1.4 s, deterministic,
  never over touches; Reduce Motion gets one quiet badge; never on the crisis screen. New completions need only
  call `celebrate()`.
- `DayEvidence.build` (pure, tested) turns today's stored observations + this device's finished-conversation count
  into "Today, so far" (Your days, and on top of What Kaiku saw today): time outside (minutes, steps, daylight
  only when measured), check-ins, activities, conversations, Health, robot, Mac rhythm; each with its devices and
  what is shared. A `dat_imu` walk says the glasses carried the voice and counted movement and did not see
  anything; simulated records say "Simulated"; a safety flag is never a list item.
- Today hides robot suggestions (drum, friend light) unless a robot event arrived today.

## Design system use
Screens use `design/components.md`: one section gap (`Space.s5`), gutters 16/24 (`KaikuPlatform.sidePadding`),
`Size.contentMax` / `Size.paneMax` only, `KCard` padding `Space.s4`, `Size.rowMin` rows, `Size.iconTile`,
`KChip`, `KChevron`, `Bubble` (also Talk's), `Radius.md` buttons and bubbles, `Elevation` shadows, `Feedback`
timings, `KText.micro`, mascot sizes `mascotS|M|L`. `KScreen` shows the offline banner on every scrolling screen
and gives every tab root (Talk included) the same `PageHeader`. Talk has one voice control: a full-width button
while the microphone is closed, the composer's microphone button while it is open. Not yet converted: `Games/`
and `PlayView.swift` (games work in progress), hand-drawn card backgrounds in `DaysView` / `TodayPath` /
`GardenCard` (same inset and shadow tokens, not yet `KCard`), widget/Live Activity text styles, the Mac popover
mascot (64), Mac sheet size literals.

## Walk with Kaiku: voice in the ear, seeing, Glasses check (2026-11-14)
What the Meta toolkit gives an iOS app (wearables docs v1.0, MWDAT 1.0.1): registration and the camera permission
through the Meta AI app; a device session (`idle → starting → started ⇄ paused → stopped`; folding the glasses stops
it, taking them off pauses it); a camera stream (`addCamera` → `camera.stream`: 360 × 640 / 504 × 896 / 720 × 1280 at
2, 7, 15, 24 or 30 fps; `.raw` frames only while the app is in the foreground); Motion (experimental); Mock Device Kit.
Microphone and speakers are not toolkit features: they are Bluetooth hands-free audio through `AVAudioSession`
(mono, 8 or 16 kHz), and that route must be settled before the session and its stream start.
- **Order of a walk** (`WalkModel.begin`): Live conversation + audio engine → `TalkAudio.settleHeadset()` (≤ 3 s) →
  route written down → toolkit session → camera only if wanted. `DATGlasses.makeSession()` waits for the selector's
  active device first: creating the session at once threw `noEligibleDevice` (the reason the mock, and likely the
  real glasses, never got past "connected").
- **Seeing** (`Signal.see`, off by default; D43): `applyVision()` turns the stream on only with the choice on, not
  paused, and an open unmuted conversation. `DATGlasses` passes about one frame a second (JPEG ≤ 640 px, in memory)
  → `WalkModel.take` → `Conversation.sendFrame` → `LiveSession.sendVideo` (`realtimeInput.video`). Kaiku is told
  `[glasses camera on …]` / `[glasses camera off …]`; `look_at_this` answers "cannot see" unless a frame from the
  last 3 s went out. No frame is stored or sent to the cloud; no observation comes from frames. With the phone
  locked the voice continues and seeing pauses (walk screen says so after 8 s without frames).
- **Walk screen**: Kaiku's state in words, where the sound goes (`In your ear: <device>` or phone), glasses line
  (incl. taken off), seeing line + Pause, the last six lines of both sides, a reason + "Talk again" when the voice
  stops (the cloud's session limit is `[live] session_max_minutes`, currently 5), and an end summary that says
  whether the outing was saved (under one minute it is not).
- **Glasses check** (You → Glasses check, `GlassesCheckView`): registration, device, worn, camera permission (+ ask),
  microphone permission, hands-free device, current route, service, Live state, last heard / last spoke, frames
  sent and per second, last problem; `GlassesSelfTest` (Kaiku line through the route → 3 s microphone level → one
  frame thumbnail, nothing kept); `GlassesLog` = `Application Support/Kaiku/glasses-log.jsonl` (states, counts,
  errors; never audio, pictures or words) with Share.
- **Info.plist / entitlements for the camera**: `_bonjour._tcp` in `NSBonjourServices`, local-network text,
  `NSBluetoothAlwaysUsageDescription`, `bluetooth-central`, and `com.apple.developer.networking.HotspotConfiguration`
  (the toolkit streams over Wi-Fi hosted by the glasses). While the phone is on that Wi-Fi a LAN-only Kaiku service
  may be unreachable: observations queue, Live itself needs mobile data.
- Launch arguments: `-kaikuRoute glasses`, `-kaikuGlassesSelfTest YES` (run the self-test on opening),
  `-kaikuGlasses datmock` (simulated glasses incl. a generated h265 camera feed).
- Tests: `GlassesVisionTests` (frame format, encode, brightness, log, route words), `GlassesFrameGateTests`
  (frames only with the choice, open, unmuted, unpaused), paid `RealGlassesVisionTests`
  (`KAIKU_VISION_TEST_CLOUD` + `KAIKU_VISION_TEST_WAV48`; passed 2026-11-14 against an isolated cloud: the spoken
  question was transcribed and Kaiku named the word on the generated sign). New copy keys have English text in
  the `fi` table for now (English first).

## Fixes from the simulator walkthrough (2026-11-14)
- **Talk hang** (tapping the message field with voice unavailable): the transcript was a `LazyVStack` with a 1 pt
  bottom sentinel whose `onAppear`/`onDisappear` wrote view state. With the keyboard up the viewport is shorter
  than the welcome content, the sentinel sat on the edge, and every state write rebuilt the lazy stack and toggled
  it again: an endless update cycle on the main thread. Now a plain `VStack`; following the newest line comes from
  geometry through `TalkFollow` (dead band, always true with no lines). Never write state from a lazy child's
  appear/disappear in a scroll view that is anchored to the bottom. Tests: `RecordingBugTests`,
  `iOSUITests/TalkComposerTests` (needs a key-less cloud: `KAIKU_NO_DOTENV=1`).
- Talk says why voice is not there once (header). `TalkView.stateNote` adds "The connection dropped" only when
  the conversation really was live (`Conversation.wasLive`).
- Today's path: `AppModel.suggestedStep` keeps a completed suggestion stop when the nudge changes later that day.
- Little moments: the cloud's highlight source `laptop` is the apps signal group (phone or Mac), shown as
  "Kaiku app" (`source.apps`), never "Mac". The cloud should send the real envelope source.
- Core Motion is touched only when a walk starts (`WalkModel.pedometer` is created then): `stopUpdates()` during a
  pairing change used to raise the Motion & Fitness question in setup.
- Setup: `VoiceLines.playReporting` tells the hello step whether audio really started ("That was my voice" only
  then; otherwise "Kaiku's voice isn't available right now…"). Connect step: "Continue without connecting" is the
  primary action with one line on what works offline; the address field stays under Advanced.
- `kTopEdgeBackdrop()` (in `KScreen` and setup pages) fills the top safe area so scrolled content does not run
  under the clock. Glasses check shows results as rows only; raw log lines travel with "Share log"; the speaker
  step reports "played" only when audio started.
