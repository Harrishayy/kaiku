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
- `GET /v1/me/history?home_id=&days=` → `PersonHistory` (the History tab: every measure by local day, each
  measure's latest sessions; numbers only). See "History".
- `GET /v1/me/invitation?home_id=&surface=iphone|mac` + `POST /v1/me/invitation/answer` (the one thing Kaiku would
  like to bring up or offer today: the card on Today). A walk's session request also carries `purpose: walk` and
  `walk_style`; its response's `walk` (`WalkGuide`) carries the nudge lines and seconds. See "Walking together".
- `GET /v1/me/stream?home_id=&surface=iphone|mac` (the home stream, Server-Sent Events: `hello`, `agreed`, `day`,
  `invitation`, `ping`) and `POST /v1/me/agreed/answer?home_id=&surface=` (`opened` | `put_aside`). The
  invitation read also carries `agreed`: what the person said yes to today in a conversation on any device.
  See "Agreed in one place, shown everywhere".
- `POST /v1/companion/session {surface: iphone|mac, intent: talk}` (Talk) or `{surface: glasses, intent: walk}`
  (the walk companion, through Meta glasses) → `live_token` (locks only the model) + `live_setup` (persona, voice,
  `[live]` turn detection) → Gemini Live WebSocket (`BidiGenerateContentConstrained?access_token=`); the device's own
  setup frame adds resumption, compression and tool behaviour, and on the loudspeaker takes the cloud's VAD.
  Reconnect bootstraps include `resume_session_id`; `max_session_seconds` ends capture at the cloud budget limit.
  `POST /v1/companion/tool` for `executor: cloud` tools (`ask_mind`, `recall`, `remember`… — the knowledge graph
  stays in the cloud); `POST /v1/companion/close {home_id, session_id, elapsed_s}` once when a conversation stops
  (the cloud settles its budget hold); `POST /v1/companion/episode` when the conversation closes (+ `transcript` only with the
  opt-in `transcripts` signal, D33). `GET /v1/me/transcripts` + `DELETE /v1/me/transcripts` (count + delete all in
  What Kaiku remembers). See "Conversation pipeline". Kaiku's voice outside Live is always Gemini TTS:
  `GET /v1/voice?lang=` (line texts), `GET /v1/voice/{key}?lang=` (prefetched on Wi-Fi, fetched on demand on a miss),
  `POST /v1/voice/say` (the app's own lines, cached by text hash). **Never an on-device synthesizer**: cloud
  unreachable AND nothing cached → silent, the text stays on screen.
- **When Kaiku speaks (2026-11-15): never by itself on a screen.** A spoken line needs an origin
  (`VoiceLines.play/say/playReporting(…, origin:)`, no default): `.pressed` = the person just pressed something to
  hear Kaiku or to talk; `.chat` = inside the check-in chat or Talk while that screen is showing
  (`VoiceLines.chat(_:showing:)`; a chat line that arrives after the person left stays silent). There is no origin
  for "the screen appeared", a timer or a state change. Opening the **Talk** tab no longer opens a call: it shows
  "Call Kaiku" (`TalkModel.Mode.ready`), and coming back to the app does not reopen one; a yes on Today's talk card
  sets `app.talkAsked` and Talk opens the call once. The check-in chat still opens its conversation as it appears.
  Onboarding's hello plays on "Hear Kaiku", and the "well done" line after the practice task is text only.
  DEBUG runs open the call on appear with `-kaikuTalkStart YES` (also a Talk demo or `-kaikuTalkSay`).
  `VoiceOriginTests` pin this. Still by itself: Kaiku's Live voice in a walk the person started, the Mac quick
  talk after its shortcut, and `walk.done` when a crisis ends a walk (crisis path left as it was).
- iPhone: Apple Health (read-only, HealthKit), Meta glasses via the DAT SDK (MWDAT 1.0.1, SPM; Motion = dev/beta
  channel), local notifications (no APNs), ActivityKit (no push), App Intents.
- All shapes: `contracts/schemas/` (mirrored in `KaikuKit/Model/Contracts.swift`).
- **The home robot's MQTT broker, only while Kaiku bot is on screen** (see "Kaiku bot"; read-only except the
  "Robot microphone" switch, D56, which also keeps the connection while it is on): subscribes to
  `kaiku/v1/<home>/raw/#`, `cmd/#`, `obs/#`, `health/#` (QoS 0) and reads `health`, `raw.head.*`, `raw.sensors.*`,
  `raw.hub.face`, `raw.hub.trace`, `cmd.head`, `cmd.sensors`, `cmd.hub`, `cmd.friendlink` and every `obs.*` the robot
  sends on. Never subscribes to `audio/#` or `kaiku/v1/#`. Publishes one thing only, with "Robot microphone" on and
  while the hub holds the robot's microphone open: this device's microphone as 640-byte PCM frames on
  `kaiku/v1/<home>/audio/phone/mic` (never an envelope, never a command).

## Emits (topics/endpoints)
`POST /v1/events` (source `phone` on iPhone, `laptop` on Mac), always through the offline queue:
- `obs.self_report` ×3 (`channel: phone|mac`) — the dials on the check-in chat ("That's it"); `record_dial` tool
  (`context: adhoc`) in the check-in chat and Talk.
- `obs.play_session` (`device: phone|mac`) — `firefly` (reaction median/IQR, lapses > 500 ms or missed, false
  taps), `pebbles` (`span_max`, `accuracy`), `breathe` (duration), `tell` (speech_rate, pause_ratio — only with the
  voice signal on). Sent only with the check-ins signal on and nothing paused.
  Measured games (`GameHistory.measured`): `lantern` (reaction median/IQR/CV, `response_speed`, lapses,
  `false_starts`), `seeds` (`throughput_per_min`, accuracy, time per packet), `watering` (`hard_choice_ratio`,
  `tap_rate_hz`), and `pebbles`; each with `trials_n`, `valid_n`, `input`, `session_index`, `warmup` (first 3
  sessions per game on this device), `valid` + `flags`, and the compact trial record `rt_ms` + `trial_codes`. The
  envelope `quality` is 0.2 for a doubtful session (criteria skip it), else the share of usable trials.
- `obs.face_signs` (`device: phone|mac`, `method: arkit_blendshapes|vision_landmarks`) — one per task (a game, or
  the check-in chat as `task: check_in`) in which the camera sampled, only with the choice "Camera during
  activities" on: smiles, brows, blinks, mouth opening, gaze toward the screen, head movement and range of
  expression as numbers, with `duration_s`, `samples`, `coverage` (= the envelope's `quality`) and `ref` = the id of
  the same game's `obs.play_session`. Frames are never stored or sent; no field names an emotion; a field the
  method cannot measure is left out. See "Face signs during tasks".
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
  with the Watch signal on. Equal snapshots deduplicate; late samples become newer observations. Since D53 the
  summary also carries `distance_km`, `daylight_min`, `walking_hr_bpm`, `sleep_deep_min`, `sleep_rem_min`,
  `sleep_core_min` and `sleep_awake_min`, each absent when Apple Health has nothing for it; a summary made of the
  debug sample data goes out `sim: true`. See "Apple Health summary".

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
Mac/NotchIsland.swift       one level-26 window from the screen top: one shape, collapsed → peek → expanded; the call
                            while quick talk is put away (state word, elapsed time, mute me, end)
Mac/QuickTalkPanel.swift    quick talk's AppKit side: the one non-activating window at the left screen edge (bar →
                            pill → popup), ⌥⇧Space + Esc (Carbon hot keys), the double tap (flagsChanged monitor),
                            the pointer (hover, mouse-through); DEBUG window probe. See "Quick talk on the Mac"
Mac/DebugSnapshot.swift     layout PNGs: -kaikuSnapshot (pane), -kaikuIslandSnapshot (island),
                            -kaikuQuickTalkSnapshot (quick talk: every stage and state, the island's call),
                            -kaikuWindowShots (the REAL main window: real switches, scrolled pages, sheets,
                            contact sheets, before | after sheets; see "You: settings as short rows"; also a game
                            while it is played, and the check-in on the scripted Live)
iOS/KaikuApp.swift          shell + app delegate: notification answers, kaiku:// links, BGAppRefresh, foreground sync
iOS/KaikuIntents.swift      App Intents + App Shortcuts (check in, walk, breathe, talk)
iOS/DATGlasses.swift        DAT adapter (MWDATCore/Motion/Camera; Mock Device Kit in DEBUG), DATControl (check screen),
                            GlassesChoice (-kaikuGlasses)
iOS/SurfaceSnapshots.swift  DEBUG: -kaikuSurfaceSnapshot <dir> → Live Activity / island / widget PNGs, small + large
iOS/Resources/              kaiku-chime.caf (0.8 s notification sound)
Shared/WalkIntents.swift    LiveActivityIntents Found one / End walk, and the call's Mute me / Mute Kaiku / End (compiled into app + widget extension)
Widgets/KaikuWidgets.swift  widget extension: Walk + Breathe + Call Live Activities, Kaiku widget (small/medium/lock)
iOSUITests/                 end-to-end against a local cloud (check-in chat dials → self_report, pebbles → play_session, memories);
                            DemoTourTests = the paced feature tour the demo recordings are made from;
                            FaceSignsUITests = the task camera's chip, question, consent screens and receipt on the stand-in source
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
  Net/HomeStream.swift      the home stream's connection: SSEParser (pure), HomeStreamEvent, StreamBackoff, StreamWatch
                            (heartbeat rule), HomeStreamClient (connect, read, reconnect with Last-Event-ID)
  Net/BotBus.swift          Kaiku bot's wire: BotTopics (the four filters, the audio guard), BotAddress (parse, the
                            local-network guess), MQTTOut (CONNECT/SUBSCRIBE/PING/DISCONNECT/acks: no PUBLISH),
                            MQTTDecoder (pure, fragments, malformed input throws), BotBusClient (NWConnection, keep-alive,
                            reconnect with backoff)
  Net/HomeUpdates.swift     when the stream runs (StreamGate, AppPresence) and what each event refreshes; the Mac's
                            answers to the agreed notification; `-kaikuStreamTrace`
  Safety/SafetyGate.swift   port of kaiku_contracts/safety.py + a tiny TOML reader
  Mascot/                   MascotSpec (decodes mascot.spec.json, SVG paths, easings), MascotView (Canvas)
  Components/               buttons, NotOK pill, screen/header, cards, rows, toggles, segmented, WeatherDial, toast,
                            bubbles, KChip, KChevron, Celebration (completion moment), empty/loading/offline/error states, RingStage; Polish.swift (KTone soft fills,
                            KPressStyle press/hover, KBackdrop time-of-day wash, MascotHalo, KAdaptiveColumns)
  Screens/                  TodayPath.swift (Today's path: weather → suggestion → game, on Today/Play/game ends;
                            GardenBeds day plots + DayPlant), Screens.swift (tabs, routes, parity list, root/tab bar/sidebar), Today, CheckInChatView (the check-in as a small chat + the dials),
                            Play, History (`History*.swift`, below; DaysView = Your days, a screen under it since
                            History took its tab), You (+ remembers, saw today, voice, quiet hours, devices, help),
                            Crisis, Onboarding (OnboardingFlow + SetupStep), EvidenceView (Today, so far), MenuBarPopover
  Games/                    Firefly, Pebble path, Breathe, Tell Kaiku (+ Composer, mic card); measured games:
                            LanternGame (simple reaction time), SeedGame (symbol–digit), WateringGame (effort
                            choice), each a pure engine + a field; GameKit (stats, input provenance, GameHistory
                            = session count / warm-up / quality, GameRotation, GameTrialLog = raw trials on device)
  Talk/                     Conversation (one spoken conversation: bootstrap, Live, tools, safety, resumption),
                            LiveSession (Gemini Live WS protocol: pure setup builder + frame parser),
                            ConversationAudio (mic + Kaiku's voice on one voice-processing engine, HFP glasses mic,
                            barge-in flush), MicDownsampler (any mic format → 16 kHz PCM16), TalkView/TalkModel (the call screen:
                            Kaiku in the centre, captions, the call bar), CallViews (CallStatus, CallBar, ActivityCard +
                            ActivityCardView), CallActivity (the call outside the app: KaikuCall, the Live Activity),
                            CheckInChat (the check-in as a small chat), TalkDemo (Debug: every call state on a scripted
                            Live), AudioCapture (Tell Kaiku)
  Platform/                 Haptics, platform constants, QR scanner (iOS), Sound (synthesised soft UI tones)
  Mac/                      pure Mac-extras logic (tested): MacIslandGeometry/Shape/Layout (the island), MacUsage (bundle-id → category table, aggregator,
                            ScreenActivity payload, MacUsageStore = the local aggregate), MacPeek (peek rules +
                            ledger, invitation time); quick talk (tested): QuickTalkTrigger (key combination, pure
                            double-tap detector), QuickTalkGeometry (stages, sizes, where, hover, meter level),
                            QuickTalkModel (settings, the display rule, moments, the ONE TalkModel shared with the
                            Talk screen), QuickTalkView (the surface, the card, reactions, the You settings card)
  Notify/                   NudgeScheduler (pure plan: quiet hours, windows, one invitation/day, snooze once,
                            done-on-any-surface), Notifier (UN requests, categories, answers, ignored after 4 h), DeepLink
  Voice/                    VoiceLines (Gemini TTS: keyed + /v1/voice/say, cached; silent when unavailable, never a synthesizer),
                            TalkAudio (HFP session, interruptions, routes), OnDeviceListener (Speech, on-device only:
                            safety backstop + SpokenDial; never shown or said), SpokenDial (en/fi/sv)
  Screens/TodayInvitation.swift  Today's invitation: where a yes leads, the two requests, InvitationModel, InvitationCard
  Screens/TodayAgreed.swift  what was agreed today, on Today: what an item is on this device, AgreedBoard (pure: one
                            card, the rest as lines), AgreedCard, AgreedRow, AgreedStack
  Screens/Bot*.swift        Kaiku bot: BotState (the pure reducer: envelopes → the screen), BotWords (plain words for
                            every bus word), BotModel (when it listens, the address, the Keychain password, the
                            DEBUG recording player), BotView (the page)
  Screens/History*.swift    the History tab: HistoryMath (pure: periods, roll-ups, a month as weeks, the sessions of a
                            day, the value axis, how a number is written), HistoryModel (the request's result, the
                            copy kept for offline), HistoryView (days block, groups of measure cards, sparkline),
                            HistoryMeasureView (range switch, Swift Charts, usual band, week by week, sessions)
  Walk/WalkCompanion.swift  pure walk rules: WalkStyle storage, WalkGoal (the spotting count), WalkNudger (when to nudge)
  Walk/WalkTyped.swift      DEBUG: a walk without a microphone (real Live, silent audio stand-in, typed lines)
  Walk/                     WalkModel (the walk: voice, style, goal, nudges, draft recovery), WalkView, GaitAnalyzer + DaylightCounter,
                            KaikuActivities (ActivityKit attributes + start/update/end)
  Glasses/                  GlassesAdapter protocol, MockGlasses + MockGait (synthetic IMU, synthetic frames);
                            GlassesDiagnostics (GlassesLog JSONL, GlassesVision, GlassesStatus, GlassesControl)
  TaskCapture/              the camera during tasks (see "Face signs during tasks"): FaceSigns.swift (pure: per-frame
                            readings → one summary; every threshold a named constant), FaceGeometry.swift (pure:
                            ratios on landmark points), TaskCamera.swift (the controller: begin / suspend / resume /
                            her off tap / finish; `TaskCameraSource`; the Vision source; the DEBUG stand-in source),
                            ARKitFaceSource.swift (iOS only: face tracking blendshapes, no view), CameraChoice.swift
                            (the wording agreed to, what was sent today, the payload, `AppModel` recording),
                            TaskCameraViews.swift (the chip, the one-time question, the in-front rule)
  Health/                   HealthSync (HealthKit queries, asking iOS again for kinds of data an update added, debug
                            sample data and its simulated mark, HealthAccess = the screens' one call),
                            WearableDailyBuilder (pure: sleep, stages, time awake, the day's totals, rounding)
  Widgets/                  WidgetSnapshot (App Group), SurfaceViews (LA/island/widget content), KaikuGlyph
KaikuKit/Tests/KaikuKitTests/  safety fixture parity, sync freshness, copy keys, contract shapes, UUIDv7,
                            pairing, game logic, speech features, mascot spec, offline queue, parity table;
                            MacExtrasTests (usage aggregation + payload privacy, peek rules, invitation time)
```

## Parity
One screen list (`KaikuScreen` in `Screens/Screens.swift`) rendered by both targets. Same tab names and order:
Today · Play · Talk · History · You, and on the Mac also Kaiku bot (before You). Five is what an iPhone tab bar shows
(a sixth puts the fifth and the sixth behind "More"), so History took the place of Your days on 2026-11-14 and Your
days is History's first block and a screen under it, and Kaiku bot is a screen under You on iPhone.

| screen | iPhone | Mac | notes |
|---|---|---|---|
| `onboardingWelcome` · `onboardingAbout` · `onboardingPair` · `onboardingConsent` · `onboardingPermissions` · `onboardingHello` | ✓ | ✓ | first-run setup (`SetupStep`, see "First-run setup"): welcome → what Kaiku is and isn't → nearby companion services (advanced account link for authenticated services) → choices → permissions in context → first hello + one practice task; Health and glasses rows on iPhone only |
| `today` · `weatherCheck` | ✓ | ✓ | haptic tick per dial step (trackpad on Mac) |
| `play` · `firefly` · `pebbles` · `tell` · `breathe` | ✓ | ✓ | Breathe also runs a Live Activity on iPhone |
| `lantern` · `seeds` · `watering` | ✓ | ✓ | measured games: touch on iPhone; Space / click, 1–9, ← → + Space on Mac |
| `walk` | ✓ | — | iPhone only: walk with Kaiku: Calm · Playful · Chatty, spotting game (+ glasses, Live Activity, Dynamic Island) |
| `talk` | ✓ | ✓ | a call on Gemini Live with a cloud token: mute me, mute Kaiku, captions always, typing behind the call bar; without a call one line + one action; iPhone: goes on outside the app (Lock Screen, Dynamic Island) |
| `history` · `historyMeasure` | ✓ | ✓ | the person's own numbers: one card per measure in groups (robot first), a measure's page with day · week · month; one column on iPhone, two columns of cards and chart beside sessions on Mac; `kaiku://history` |
| `bot` | ✓ | ✓ | Kaiku bot: what the robot at home hears and does, live (read-only, see "Kaiku bot"). A tab in the Mac sidebar; on iPhone a screen under You → Devices (`KaikuRoute.bot`, `kaiku://bot`), because a sixth tab puts the fifth and sixth behind "More" |
| `days` · `markDay` | ✓ | ✓ | under History (`KaikuRoute.days`, `kaiku://days`): this week's strip is History's first block; day marks are local (no contract yet) |
| `glasses` | ✓ | — | You → Glasses check: toolkit, sound route, Live and camera state, 20-second self-test, shareable log |
| `you` · `memories` · `saw` · `voice` · `quiet` · `devices` · `help` | ✓ | ✓ | Devices: glasses (ready / connected during a walk), watch (Health); debug "Try it out" section |
| `crisis` | ✓ | ✓ | full screen on iPhone, sheet on Mac |
| `menuBarPopover` | — | ✓ | platform-only; + notch island and quick talk (not screens: overlay panels, see Mac extras and "Quick talk on the Mac") |

## Conversation pipeline (Talk + glasses walk)
```
Meta glasses mics (HFP, beamformed) / phone / Mac mic
  → ConversationAudio: one AVAudioEngine, voice processing (echo cancel), 16 kHz PCM16 → LiveSession → Gemini Live
  ← Kaiku's voice 24 kHz ← Live, played on the same engine (glasses speakers over HFP)
person talks over Kaiku → server VAD → `interrupted` → queued voice flushed at once → Live listens (barge-in)
Live tool call → device tool (Conversation.deviceTool: express, record_dial, start_activity, set_walk_goal,
  log_walk_moment, look_at_this) or POST /v1/companion/tool (ask_mind → mind router: memory / knowledge graph / Flash / Argon;
  recall, remember, forget, suggest_nudge, end_session) → result back into the conversation
```
- Setup (`LiveSession.setup`, tested): server VAD with `START_OF_ACTIVITY_INTERRUPTS`; start sensitivity HIGH on a
  headset route (glasses), LOW on a loudspeaker (echo leftovers must not interrupt); end LOW + 800 ms silence
  (slow speakers with long pauses aren't cut off); affective dialog; proactive audio; input + output
  transcription; context-window sliding compression (walks > 15 min); session resumption. `ask_mind` is
  `NON_BLOCKING` (Kaiku keeps talking while the mind thinks; answer scheduled `WHEN_IDLE`).
- Context events: the walk sends `[walk started · …]` (a later conversation on the same walk: `[walk goes on · …]`),
  `[spotting game · trees · 2 of 3 found · 1 left]`, `[walk · 10 min]`, `[glasses disconnected · …]`; Talk sends `[the person just opened Talk]` (Kaiku greets in its live voice) and
  `[back after an interruption …]`. Same wording as the hub's `send_context`.
- Reconnect: `goAway` or a drop → reconnect with the last resumption handle; same token until 60 s before its
  `expires_at`, else a fresh token from `POST /v1/companion/session` (episode + tools keep the first session id).
  The token's end, a `goAway` and the first drop of a call that has a handle are quiet (nothing on screen
  changes: "Talk is a call" → Long calls). Three failures in a row → `unavailable` (Talk: one line + "Try again";
  walk: scripted voice lines).
- Safety: input transcripts (also joined with the previous partial) + the on-device listener (restarted every
  50 s) run `SafetyGate` first; a hit stops the conversation (`outcome: crisis`) and opens the crisis screen.
- Glasses: Ray-Ban Meta / Ray-Ban Display paired in the Meta AI app and connected to the iPhone over Bluetooth
  are the mic + speaker (HFP, `TalkAudio.preferHeadsetInput`). The DAT session (IMU, later camera) is separate and
  optional; the conversation works with Bluetooth alone. The Display web app has no mic (Meta docs), so speech
  never goes through it. The robot runs its own Live session in the hub; the same mind serves both.
- UI: Talk = a call (call bar: mute me, mute Kaiku, type, end; see "Talk is a call"). Walk screen:
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
  **A call** (`IslandModel.State.call`): while a quick-talk conversation is on and its popup is put away, the
  island shows it (Kaiku and the elapsed time in the wings, the call's state word, mute me, end; on a Mac without
  a notch all of it in the pill). It follows `QuickTalkModel.call`, stays as long as the call does (no timer
  folds it, no peek interrupts it), a click on it brings the popup back, and it folds away when the call ends.
  Not shown while Kaiku is the front app with Talk open (that screen is showing the call).
- **Seeing the island**: it comes by itself only by the peek rules below, so most days it is never out. Click
  the notch (hello: greeting, Talk, Open Kaiku; folds after 20 s), or use the Demo line below.
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
- **New measure in History:** nothing here. The service lists it (`config/kaiku.toml [history]`) and the tab draws
  any measure it is sent: unknown key, any unit, any group title. A new group key gets the default icon and tone
  until `HistoryGroup.symbol` / `.tone` name it; a new device word is left out of the "From" line until
  `HistoryDevice.name` names it.

## Invariants
- No inline user strings: every visible string is `T("key")`; `L10nTests` checks every literal key exists in en + fi.
- Only token colours; `crisis` only on the crisis screen. Crisis screen: no mascot, no motion, scripted text verbatim
  from `config/safety_phrases.toml`; "I'm not OK" on every screen (header on iPhone, sidebar + popover on Mac).
- Never on screen: scores, streaks, trends, state words, dev text. Firefly ends with a jar, never a number;
  the measured games end with the sky you lit, sprouts, a flower bed. No reaction time, count or "slow" anywhere
  **except in History**: by the lead's decision (docs/decisions.md D48) History is the one place in the apps where
  the person's numbers are shown (reaction times, tempo, counts, heart rate, each session's own numbers). Today,
  Play, the games' end screens, Your days, Talk and everything Kaiku says stay as they were. In History the
  numbers are shown plainly: no colour for good or bad (a group's tone only tells groups apart), no arrow, no
  "better" or "worse", no state word, no streak, nothing from the practitioner's side, and nothing derived on the
  device beyond sums and averages of the days the service sent. The person's own usual range (a soft band) is
  the only comparison.
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
  local day marks and activity ticks before refresh, and History: the numbers on screen and the copy kept for
  offline (`history.json`, which names its service and home, carries no credentials, and is never shown for
  another service or home). Language, voice pace and other device preferences remain.
  Pairing revisions reject late reads, write-result rollbacks and Health summaries from the previous pairing.
  Health delivery rechecks Watch consent after each awaited query and binds emitted envelopes to the original
  pairing. Active Live conversations close and clear visible words; active walk/finished state is cleared too.
- `ConversationAudio.onPCM` goes through the production `Conversation` controller to `LiveSession.sendAudio`.
  Setup must be ready; mute, pause, closed sessions and changed pairing block transmission. Old socket callbacks
  cannot affect a replacement socket. `end_session` and the session duration limit stop microphone capture.
  Global "Pause everything" also closes an active conversation without waiting for another audio frame and
  prevents bootstrap/capture while paused. Unpausing requires an explicit conversation restart.
- `record_dial` uses the same pause/consent/value checks as manual check-ins. Talk, the check-in chat and walks
  support it.
- `start_activity` runs only on the person's word: their latest words ask for it or say a clear yes
  (`TalkModel.asked`, en/fi/sv; "maybe" is not a yes), or they open the activity card. Otherwise the model is told no.
  Talk supports `start_phq9` and walking activities. PHQ-9 forwards pairing credentials in a consumed URL fragment.
- Mock adapters are explicit debug choices, never automatic fallbacks; their outings carry `sim=true` through
  normal completion and draft recovery. Real motion connection is shown only after a sample arrives.
- The local safety gate gives the same answer as `kaiku_contracts.safety` on `safety_cases.json` (tested).
- Notifications: at most one invitation a day + one check-in reminder + PHQ-9 once; never in quiet hours, never a
  crisis message, never time-sensitive; never mention Health/watch data. Rules live only in `NudgeScheduler`.
  An activity the person said yes to in a conversation gets one notification of its own, once per item, under
  the same quiet hours and pause (`NudgeScheduler.agreed`; see "Agreed in one place, shown everywhere").
- The on-device listener only runs with `requiresOnDeviceRecognition`; its partial transcripts are never kept or sent.
- Widgets and Live Activities never call the network: they read the App Group snapshot / activity state.
- Layout holds `design/layout.md`'s stress case (fi + long name + large text + 320 pt): text wraps, rows stack at
  accessibility sizes, headings cap their growth, fixed game screens give the field the room.
- One viewport: every tab, the weather check and every game fit without scrolling at the default Mac window
  (980 × 720, two columns ≥ 600 pt) and on iPhone 16 Pro at default text; scrolling is only the fallback (SE,
  accessibility sizes, the minimum window). History is the exception: a list of every measure scrolls, like the
  health app it is modelled on. Games: intro with a looping demo → play (scene, thin progress, no
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
Without a cloud the app runs offline: Today shows the sky banner, check-ins and games queue on disk, Talk says
the service can't be reached and offers "Try again". Launch arguments for dev/screenshots (UserDefaults argument domain):
`-kaikuSkipOnboarding YES`, `-kaikuPairLink "http://127.0.0.1:8000/?home=demo-aino"`, `-kaiku.lang fi`,
`-kaikuTab play`, `-kaikuRoute firefly`, `-kaikuAutostart YES` (skip a game intro), `-kaikuName Annemarie-Kristiina`
(layout stress), `-kaikuShowCrisis YES`, `-kaikuOnboardingStep 2`; Mac only: `-kaikuSnapshot /tmp/x.png`
(ImageRenderer PNG of a drawn sidebar + the pane; `-kaikuSnapshotSize 980x720` for the window size, default the
720 × 480 minimum; `-kaikuSnapshotPair <link>` pairs in memory only, never touching the Keychain or pairing file;
text fields/switches render as placeholders there),
`-kaikuWindowShots <dir>` (pictures of the REAL main window from inside the app, no Screen Recording permission:
real switches, pickers and scrolled pages; `-kaikuShotScreens you,memories,saw,voice,quiet,devices,help` (default;
also `today`, `play`, `history`, never Talk), `-kaikuShotSizes 980x720,720x480`, `-kaikuShotLook light|dark` (one
look a run), `-kaikuShotsOnline YES` with `-kaikuSnapshotPair "http://127.0.0.1:9/?home=snapshot"` (paired, the
offline banner off), `-kaikuShotName <tag>`, `-kaikuYouOpen sharing|service|quicktalk` (You with that sheet open),
`-kaikuShotCompare "<before dir>|<after dir>"` (before | after sheets); see "You: settings as short rows"),
`-kaikuSimulateLate YES` (the 01:10 peek + a sim screen_activity), `-kaikuIslandSnapshot /tmp/i.png` (PNG of a menu-bar slice
with the island collapsed, peeking and expanded, 2× + `.1x.png`, once it has peeked),
`-kaikuQuickTalkSnapshot <dir>` with `-kaikuSnapshot` (quick talk stills; add `-kaikuTalkDemo <state>` for the real
model on the scripted Live, or `-kaikuQuickTalkProbe YES` for the real window; see "Quick talk on the Mac").
iPhone (A2): `-kaikuRoute walk -kaikuAutostart YES` (start a walk), `-kaikuGlasses mock|datmock|dat|none`,
`-kaikuGlassesDropAfter 20` (glasses disconnect mid-walk), `-kaikuNotifyTest checkin|invite -kaikuNotifyDelay 8`
(the real notification in n s), `-kaikuHealthSample YES` (DEBUG: write a sample night and day to Health + sync;
the summary goes out `sim: true`, see "Apple Health summary"),
`-kaikuMute YES` (no voice), `-kaikuSurfaceSnapshot <dir>` (DEBUG: Live Activity / island / widget PNGs).
Talk (DEBUG): `-kaikuTab talk -kaikuTalkSay "text"` types one message once Live is up (real Live path, for
screenshots); `-kaikuTalkSayLater "one|two" -kaikuTalkSayDelay 85` types each of those that many seconds after the
one before, also in the background; `-kaikuCallTrace <file>` writes the call's connection events (no words);
`-kaikuTalkDemo connecting|live|speaking|muted|voicemuted|paused|denied|card|ended|closed` shows that call state on
a scripted Live (Talk, or the check-in with `-kaikuRoute weather`): no network, no microphone, no sound.
Walk (DEBUG): `-kaiku.walkStyle quiet|playful|chatty`, `-kaikuWalkTyped YES` (the walk's real conversation with no
microphone and no sound), `-kaikuWalkSay "10:first line|25:second line"` (typed lines, seconds after the one
before), `-kaikuWalkEndAfter 180`, `-kaikuWalkFound 2` (presses "Found one"). See "Walking together".
Kaiku bot: `-kaikuTab bot` (iPhone: You → Kaiku bot), `-kaikuBotAddress host[:port]`, `-kaiku.bot.home <id>`; DEBUG
`-kaikuBotReplay <file.jsonl>`, `-kaikuBotScroll <section>`, `-kaikuBotMic YES` (Robot microphone on at launch). See "Kaiku bot".
History: `-kaikuTab history`, `-kaikuRoute days` (Your days); DEBUG: `-kaikuHistoryMeasure drum_tempo` opens that
measure's page once History has loaded, `-kaikuHistoryRange day|week|month` picks its range. See "History".
Camera during activities (DEBUG): `-kaikuFaceSource scripted` (the stand-in source: no camera is opened, what it
yields is sent `sim: true`), `-kaiku.consents "<dict><key>camera</key><true/><key>checkins</key><true/></dict>"`
and `-kaiku.camera.wording 3` (the choice for this run only; a lower number = made under an older wording, so the
one-time question shows). With `-kaikuWindowShots` the Mac's games can be pictured while played (`-kaikuShotScreens
breathe -kaikuAutostart YES`), and the check-in on the scripted Live (`-kaikuShotScreens weather -kaikuTalkDemo
live`). See "Face signs during tasks".

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
How to record (modes, the cloud, cost, env, clips, post-processing) is written where it is kept current: the
header of [`scripts/record_app_demo.sh`](scripts/record_app_demo.sh), the top of
[`iOSUITests/DemoTourTests.swift`](iOSUITests/DemoTourTests.swift) (the flows, what is typed, `KAIKU_DEMO_*`) and
[`demo/AGENTS.md`](../../demo/AGENTS.md) → Recordings (which clips exist and what they may be shown as). Only
what the app itself provides for a recording is listed here:
- Debug launch arguments the tour drives conversations with, never the microphone: `-kaikuTalkSay "text"`,
  `-kaikuTalkSayLater "one|two"`, `-kaikuTalkSayDelay <s>` (typed into the real Live socket, also while locked);
  `-kaikuTalkDemo <state>` (the scripted Live: layout text, never a clip); `-kaikuCallTrace <file>` (one line per
  connection and turn event of a call, no words: what to attach when a take goes wrong).
- `-kaikuRoute`, `-kaikuTab`, `-kaikuPairLink`, `-kaikuSkipOnboarding`, `-kaikuMute`, and on the Mac `kaiku://`
  links and `-kaikuSnapshot` stills.
- Test-only accessibility identifiers, never spoken or shown: `lantern-lit` / `lantern-dark`, `seed-pot-<n>`, the
  call bar's `call.state` / `call.mic` / `call.voice` / `call.type` / `call.end`, `activity.card` / `card.open` /
  `card.aside`, `checkin.dials.done` ("That's it"), and the task camera's `task.camera.on` / `task.camera.stopped` /
  `task.camera.keepoff` / `task.camera.unavailable`, `camera.confirm` / `camera.confirm.keep` / `camera.confirm.off`.
- `KAIKU_SERVICE_URL` at build time (`KAIKU_BUILD_SERVICE=1` in the recorder) makes a fresh install connect by
  itself, so the first-run hello is spoken.
- Derived data for XCUITest runs must not live under `~/Documents`: macOS privacy protection stops a simulator
  app launched by XCUITest from loading the test dylibs there (white screen, then `kAXErrorServerNotFound`).
- The check-in's end screen leads on with "Up next" and leaves its stack when it is left (see "The check-in's
  end is the end" below), so a tour can follow the path through "Up next".

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
The camera choice's bookkeeping is UserDefaults `kaiku.camera.wording` (which wording was agreed to) and
`kaiku.camera.sent` (ids of today's face-sign envelopes from this device, for the day's receipt; no numbers).

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
The camera choice is off by default. What the camera does during tasks, when it runs and stops, what the person
sees and what is sent is in "Face signs during tasks" below; this section keeps what is older than that.

**The two older camera numbers** in `obs.play_session` (`expressivity_index`, `face_movement`, with
`camera_face_coverage`, `camera_samples`, `camera_method: vision_landmarks`) are still filled as before, by the same
controller: `TaskCameraFeatures`, five looks a second. Expressivity is the mean sample standard deviation of mouth
and eye height/width ratios; movement is mean adjacent face-centre displacement in normalized image coordinates
(it can include phone/camera motion). At least two valid samples are required for variability; insufficient
measurements stay nil. Exactly one face with usable lip and eye landmarks counts toward coverage; multiple faces,
missing faces and invalid geometry count as uncovered samples and break movement continuity. These are geometry
proxies, not emotions or diagnoses, and MUST NOT be pooled with MediaPipe blendshape indices. Baselines must
preserve task and method; they do not contribute new consensus votes without calibration. On an iPhone with a
TrueDepth camera the same Vision measure is taken from ARKit's own picture (`VisionFaceReader.geometry`), so the
word `vision_landmarks` stays true there (the contract's `camera_method` has no ARKit value); if Vision finds no
face in that picture the two numbers are simply absent.

Tell Kaiku starts its microphone only after both task/voice consent and an explicit press. Its energy-based
speech-rate estimate and pause ratio remain local until the task summary is emitted; no audio or words are
stored. Consent revocation, background, dismissal and cancellation stop and discard the capture. An active
walking Live conversation prevents a second Tell microphone session. Silent games do not open a microphone;
Firefly reaction latency/lapses and Pebbles span/accuracy remain task-derived measurements. Camera fields and
speech fields are scrubbed again at observation emission if the corresponding consent is no longer allowed.

`TaskCameraTests` covers stable/variable synthetic geometry, missing/multiple-face representation, coverage and
method-labelled contract payloads for the two older numbers. No test opens a physical camera. The iOS and Mac
camera usage strings live in project.yml (regenerate with xcodegen).
`KAIKU_TASK_CAPTURE_TEST_CLOUD=http://127.0.0.1:<port> swift test --filter
TaskCameraLifecycleTests/testSyntheticTaskMeasurementsPersistThroughActualRecorder` runs one task on the stand-in
source through the production controller, AppModel recorder, durable queue and real API against a dedicated
camera-integration home, everything `sim: true`. It checks that the game record keeps its numbers, that a service
which knows `obs.face_signs` stores it with `ref` = the game record's id (and that one which does not only
refuses it: nothing is left in the queue), and that with the camera choice withdrawn nothing of the camera is
sent. It passed on 2026-11-14 against a scratch service running the working tree (which stored the face signs),
without opening any sensor or model.

## Face signs during tasks (2026-11-14)
With the choice "Camera during activities" on (off by default), the device's front camera looks at the person's
face while a task runs, and one `obs.face_signs` a task goes out: what the face did, as numbers (the contract
is `contracts/schemas/obs/face_signs.schema.json`, mirrored as `FaceSigns` in `Model/Contracts.swift`).
**Nothing is recorded.** A frame is looked at in memory on the device and let go: no frame, face template or
identity is stored, logged or sent, and nothing of the camera goes to the Live conversation. **Signs, not
feelings.** A face does not reliably show what a person feels; no field names an emotion, and the numbers are
only comparable within the same task and `method`. No model weights are in the repo: both methods are Apple's
own on-device frameworks.

- **When it runs** (`TaskCamera`, one for each task screen): every game (`GameShell`: Play and Today's path, Tell
  and Breathe too) from Start to its end screen, and the check-in chat from its opening to its end screen
  (`CheckInChat.camera`), with or without a call on the line. Never in Talk and never on a walk, and not beside
  them either: `TaskCamera.busyElsewhere` (a walk, or a call that is not the check-in's own) is asked at every
  start and once a second while sampling, and closes the camera.
- **When it stops.** At once when the task ends, its screen is left, the choice or "Check-ins and games" is
  switched off, or everything is paused. A game: its scene no longer being active cancels the camera and puts
  the game back on its start screen, as before; on the Mac the app resigning active cancels the camera too,
  whatever the window's own phase says. Nothing of such a round's camera time is sent. The check-in:
  `keepsCameraInFront` suspends the camera (app not active, the Mac's display asleep, another user's session)
  and resumes it with the screen, going on from the numbers it had; time away is not counted as sampled. iOS
  also takes the camera from a background app by itself, so it cannot run behind a locked screen.
- **Permission.** The system's question comes the first time a task starts with the choice on: never at launch,
  never from setup. On the iPhone that question makes the app inactive, so the first game returns to its start
  screen and the camera opens with the next Start; the check-in simply goes on and the camera joins once the
  question is answered. No permission, no camera, a closed lid, the camera taken by another app: the state is
  `unavailable`, the chip says "Camera not in use right now", the task goes on, and what was sampled before the
  camera went away is still that task's.
- **What she sees** (`TaskCameraChip`, the design system's chip). While sampling: "Camera on: face movement only"
  and "Turn off" (to VoiceOver one button: "Camera on. Face movement only, as numbers made on this device. No
  pictures.", hint "Turns the camera off for this activity"; at very large text the chip shortens to "Camera
  on"). One tap turns it off for this task and throws away what was sampled in it. The chip then reads "Camera
  off for this activity" with "Keep it off", which switches the choice itself off (the same switch as You →
  Sharing and permissions; a toast says where to turn it on again). In a game the chip's row keeps its place for
  the whole round, so nothing on the field moves when the camera starts or stops. The chip has no motion.
- **Agreement** (`CameraChoice`, UserDefaults `kaiku.camera.wording`). The camera runs only for a choice made
  with the whole current text (`sig.camera.d`) on screen: setup's "Your choices" and You → Sharing and
  permissions (`AppModel.choiceBinding`). A choice from before this wording (it said "face movement and
  expression geometry"), or one switched on where only a short line shows (a game's start screen, the day's
  receipt), is put to her once with the whole text: `CameraConfirmCard` ("Keep it on" / "Turn it off") on a
  game's start screen and at the top of the check-in. Until she answers nothing is sampled
  (`AppModel.cameraNeedsConfirm`; `AppModel.cameraOn` is the one gate every task asks). The text's version is
  `CameraChoice.wording`, now 3: 3 added its last two sentences ("You see the numbers in History. Your care
  team sees them beside your record, and the numbers decide nothing."), so a choice made under 2 is asked once
  more under the new text. Raise the number whenever `sig.camera.d` changes what she agrees to.
- **What the copy may say** (`CopyWordingTests.swift`). The service's wording rule `face_talk`
  (`contracts/python/kaiku_contracts/wording.py`) is ported pattern for pattern as `FaceTalk`, and every line of
  `design/copy.json` and `copy.apple.json` is run through it: app copy never says Kaiku saw her or her face,
  never names a feeling read from a face, never says "emotion detected" or "looked sad". A line that says what
  Kaiku cannot see is allowed, as in the service. One test reads the Python source and fails when the two lists
  differ, so the port cannot drift.
- **Two sources** behind `TaskCameraSource` (`TaskCamera.standard()` picks; the Mac build contains no ARKit code):

  | | `arkit_blendshapes`: iPhone with a TrueDepth camera | `vision_landmarks`: Mac, other iPhones |
  |---|---|---|
  | how | `ARSession` with `ARFaceTrackingConfiguration`, no view, the lightest video format on offer, 30 looks a second | video-only `AVCaptureSession` (`.medium`), 15 looks a second, `VNDetectFaceLandmarksRequest` |
  | `coverage` | frames with a tracked face (ARKit follows at most one here) | frames with exactly one face that has eye and lip landmarks |
  | `smile_share`, `smiles` | mean of `mouthSmileLeft` / `Right` | not measured |
  | `brow_raise_share` | the larger of `browInnerUp` and the mean of `browOuterUpLeft` / `Right` | not measured |
  | `brow_furrow_share` | mean of `browDownLeft` / `Right` | not measured |
  | `mouth_open_share` | `jawOpen` − `mouthClose` (lips apart) | gap between the inner lips ÷ the mouth's width, both against the line of the eyes |
  | `blinks_per_min` | the smaller of `eyeBlinkLeft` / `Right` | each eye's opening against its own open level in this task (`OpenEyeLevel`), both eyes |
  | `gaze_on_share` | the look-at direction within 25° of the line from the eyes to the camera | not measured |
  | `head_movement` | degrees a second the head turns relative to the device | face widths a second the face moves in the picture |
  | `expression_range` | twice the mean standard deviation of smile, brow raise, brow furrow and mouth opening | the same over mouth opening, mouth width and brow height (ratios to the distance between the eyes) |

  Vision leaves smiles, brows and gaze out: flat landmarks give no resting face to compare with, and a threshold
  on mouth-corner or brow geometry could only have been "shown" on shapes drawn for the purpose, which shows
  nothing about faces. A field a method does not measure is never sent as a guess or a zero.
- **Thresholds** (`FaceSignRules`, `FaceSignLimits` in `TaskCapture/FaceSigns.swift`, each constant with its
  reason). A sign goes on at one level and off at a lower one, so a value hovering at the line is one event.

  | sign | ARKit on / off | Vision on / off |
  |---|---|---|
  | smile | 0.40 / 0.25 | none |
  | brow raise | 0.30 / 0.20 | none |
  | brow furrow | 0.30 / 0.20 | none |
  | mouth open | 0.20 / 0.10 | 0.12 / 0.07 |
  | eyes closed | 0.70 / 0.50 (looking down alone reaches 0.3 to 0.5) | 0.35 / 0.20 of the eye's own open level lost |

  A smile is counted once it has lasted 0.5 s; a blink is a closure of at most 0.5 s seen from its start to its
  end; a blink rate needs 20 s with a face; head poses are compared 0.2 s apart and need 2 s; a range of
  expression needs 10 face frames; a step of over 1 s between samples is not sampled time; a face that leaves
  the picture ends whatever was on without counting it. A share is of the frames with a face. Shares are sent to
  three places, the blink rate to one. When the coverage rounds to nothing, no sign is sent with it.
- **What is sent, and when** (`TaskCapture/CameraChoice.swift`). A game: `AppModel.recordPlay(_:camera:)` sends
  the game's `obs.play_session` and then `obs.face_signs` with `ref` = that envelope's id. The check-in:
  `recordFaceSigns(task: check_in)` when it ends, and only for a check-in that counted (she spoke, typed, dialled
  or opened the card); one that was only opened and left sends nothing. The choice is asked again at the moment
  of sending: switched off or paused meanwhile, nothing of the camera goes out. Everything goes through the
  offline queue like every observation.
- **A type the service does not know never holds the queue** (`Net/OfflineQueue.swift`). The Kaiku service
  answers 200 and names a refused envelope in `rejected`: the batch is done, the rest was stored. A service that
  refuses the whole batch (400 / 422) gets each envelope alone, and only the one refused alone is dropped.
- **Receipts.** "Today, so far" (Your days, What Kaiku saw today) has a line "Camera during activities:
  Activities with the camera on: n" with "Face signs as numbers, made on this device. No pictures."; What Kaiku
  saw today has the camera's own row with its switch. `DayEvidence.cameraTasks` counts each task once from what
  the service holds (`obs.face_signs`; a game record with camera numbers and no face signs) and from this
  device's own list of what it sent today (`CameraChoice.sent`: envelope ids only, UserDefaults
  `kaiku.camera.sent`, emptied when the home changes), so the line is true before a service knows the type.
- **History.** The service's group `camera` ("Camera during activities") gets `camera.fill` and the sage tone
  (`HistoryGroup.symbol` / `.tone`); a group key this build does not know is still drawn, with the neutral chart
  icon and ink tone.
- **Load.** ARKit tracks at its video format's frame rate whatever is read from it, so the source asks for the
  format with the lowest frame rate and fewest pixels, turns light estimation off and reads every other update;
  Vision looks at 15 of the camera's 30 frames a second and drops the rest unread. Energy use on a device has
  not been measured.
- **Stand-in source and picture runs** (DEBUG). `-kaikuFaceSource scripted` runs `ScriptedFaceSource`: it opens
  no camera, plays made-up readings, and whatever it yields is sent `sim: true` and shown as "Simulated". It is
  for layout pictures and UI tests, never a recording of the product at work. A picture run of the Mac app
  (`-kaikuWindowShots`, `-kaikuSnapshot`) and `-kaikuInspectOnly` never open a camera. `-kaiku.consents
  "<dict><key>camera</key><true/><key>checkins</key><true/></dict>" -kaiku.camera.wording 3` sets the choice
  for one run without writing it.
- **Tests.** `FaceSignsTests.swift`: `FaceSignsAccumulatorTests` (a still face, a blink train, eyes shut for
  long, looking down, two smiles and a syllable, a smile at the line, a face that leaves, broken numbers, one
  frame, time not sampled, head movement of both kinds, what Vision leaves out, the range, the gaze cone, the
  format choice), `FaceGeometryTests` (eye opening and mouth gap on drawn contours at any tilt and size, the
  open-eye level, a drawn face through the whole Vision arithmetic), `TaskCameraControllerTests` (choice off,
  no permission, a late permission, begin to finish, her off tap, leaving the front and coming back, a camera
  taken away, never beside a walk or a call, the stand-in's mark) and `FaceSignsFlowTests` (a game ends with one
  game record and one face-signs record that points at it; choice off, switched off or paused during the game;
  the off tap; the payload against the contract schema; the check-in: ended, dials only, opened and left, left
  after taking part, turned off, choice off, no permission; the older wording asked again; only a switch beside
  the whole text is agreement; the receipt before the service knows the type and without double counting; the
  queue with a service that names the type as rejected and one that refuses the batch; History's group).
  `iOSUITests/FaceSignsUITests.swift` on a simulator with the stand-in source: the chip in a game and its two
  taps, no chip with the choice off, the one-time question, the chip beside the scripted check-in call, the
  consent screens, and (with `KAIKU_FACE_CLOUD=<scratch service>`) the day's receipt. `CopyWordingTests.swift`:
  the wording rule above (what it refuses, what it lets through, the port against the Python source, every line
  of the app's copy).
- **Shown on 2026-11-14.** The arithmetic on made-up sequences and drawn shapes; the controller on a stand-in
  source; one task from the production controller and recorder into a scratch service, which stored
  `obs.face_signs` with its `ref`; the chip, the question, the consent screens and the receipt on an iPhone 17
  Pro simulator and in picture runs of the Mac app, all on the stand-in source; both schemes build (the iPhone
  one for the simulator and, unsigned, for a device); the Mac binary links Vision and AVFoundation and not
  ARKit, the iPhone binary links ARKit.
- **Not verified: needs a device and a face.** No camera was opened and no face was measured in building this.
  Open on a TrueDepth iPhone: that the view-less ARKit session starts and delivers; what the blendshape levels
  do on real faces (the thresholds are set from ARKit's 0 to 1 scale, not calibrated on people); the gaze cone;
  the head movement scale while the phone is held; whether Vision finds the face in ARKit's picture (if not,
  the two older numbers are absent there); the camera beside a live check-in call (one audio session, two
  capture pipelines), heat and battery. Open on a Mac and on an iPhone without TrueDepth: whether Vision's eye
  landmarks close enough on a real blink (the blink rate may read low), the mouth level on real faces, which
  camera the Mac picks when an iPhone or a second camera is attached, a closed lid. Open on both: the system's
  permission question in the middle of a first task, VoiceOver reading the chip, the Finnish text (English
  stands under the fi keys of every new or changed line; only the title "Kamera tehtävien aikana" is Finnish).

## Voice control visibility
(Replaced on 2026-11-14 by the call bar and the one line + one action of a state without a call: see "Talk is a
call". Still true: the distinct reasons, and pairing as an explicit sheet action.)
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
- `design/copy.json` still has the older Watch texts: `sig.watch.d` ("Sleep times, resting heart rate and steps
  from Apple Health.") and `saw.watch` name less than the app reads since D53. The overlay may not shadow a base key, so the app shows
  `sig.watch.s` (short line) and `sig.watch.full` (whole text) from `copy.apple.json` instead
  (`Signal.wholeKey`), and `saw.watch.read` / `saw.watch.none` on the receipt. Design owner: move the whole text
  into `sig.watch.d`, then delete `sig.watch.full` here; `wholeKey` falls back to `.d` by itself.
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
- `SpokenDial` is used for on-device transcripts (fills `record_dial` when Live omits the value), in Talk and in
  the check-in chat.
- Health background delivery is best effort (observer query); the simulator sample writes sleep, steps, resting HR
  and HRV (exercise minutes are Apple-computed and can't be written).
- Interactive widget (mood buttons) and Control Center control are STRETCH, not built. Lock Screen Live Activity
  has no buttons (Found one / End walk are in the expanded island), so Kaiku can fill the 160 pt height.
- The care-team call button shows a toast only (no "please call me" endpoint).
- Mac `-kaikuSnapshot` uses ImageRenderer (no ScrollView, toggles/text fields render as placeholders). For the
  real window use `-kaikuWindowShots` (the window's own views drawn into a bitmap, no screen-recording
  permission); a capture from outside the app still needs that permission.

## Invariants (layout on Mac)
- Non-scrolling panes (games, Talk) wrap in `fillsProposal()`: NavigationSplitView measures the detail at a tiny
  width, where vertically fixed wrapping text reports a huge minimum height; without it the split view outgrew
  the window (sidebar list under the traffic lights, crisis pill, game title and Start button clipped).
- Game scenes are a `.background`, never a layout sibling; on Mac they only extend under the toolbar, never under
  the sidebar. Mac pushed screens use the system toolbar back button + `navigationTitle`; Esc via `EscapeKey`.
- A scrolling screen is exactly as wide as it is offered (`KScreen`: the scrolled content is framed with
  `minWidth: 0`). A scroll view grows to its content's minimum width, and `kaikuPaneWidth` (which sizes the first
  of `KAdaptiveColumns`' two columns) is read from the screen's own width: content too wide for its column made
  the screen wider, the wider screen made the first column wider, and so on. With a week of full days and an
  empty today the Mac's Today never stopped laying out (2026-11-14). `PaneWidthTests` holds this.
- The garden's row of day plots (`GardenPlots`, a `Layout` in `Screens/TodayPath.swift`, used by Today and Your
  days) is as wide as it is offered and gives every plot the same width (`GardenRow.plotWidth`, pure). Under a
  plant, `PlotMarks` shows the day's icons at the largest of a few sizes that fit the plot, and a count only in a
  plot too narrow for the smallest; a plant's leaves stop at its plot's edge (`DayPlant.leafLength`). As an
  `HStack` the row could not be narrower than six days' icons (334 pt): Today was wider than a small phone's
  screen and the empty day had no width. `GardenFitTests`, `GardenRowTests` and `GardenPlotsTests` hold this.

## Native journey refinements
The current native UI and all companion bootstrap requests use English, regardless of an older language
preference; the language chooser is hidden. Multilingual crisis matching remains available internally.
Talk is a call screen (see "Talk is a call"). Transcript fragments update one bubble per speaker per Live turn, including interleaved
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
  anything; simulated records say "Simulated"; a safety flag is never a list item. The Health line names the
  kinds of numbers the day's summary held (`DayEvidence.healthNames`: "Last night and yesterday: sleep, sleep
  stages, time awake at night, …"), never a value and never a word about how the night was.
- Today hides robot suggestions (drum, friend light) unless a robot event arrived today.

## Design system use
Screens use `design/components.md`: one section gap (`Space.s5`), gutters 16/24 (`KaikuPlatform.sidePadding`),
`Size.contentMax` / `Size.paneMax` only, `KCard` padding `Space.s4`, `Size.rowMin` rows, `Size.iconTile`,
`KChip`, `KChevron`, `Bubble` (also Talk's), `Radius.md` buttons and bubbles, `Elevation` shadows, `Feedback`
timings, `KText.micro`, mascot sizes `mascotS|M|L`. `KScreen` shows the offline banner on every scrolling screen
and gives every tab root the same `PageHeader`, except Talk: a call has no page title, Kaiku is its top. Talk's
controls are the call bar (`CallBar`, also in the check-in chat). Not yet converted: `Games/`
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
- **Camera link over Bluetooth (2026-11-15)**: `UISupportedExternalAccessoryProtocols: [com.meta.ar.wearable]` and
  `external-accessory` in `UIBackgroundModes` (project.yml) let the toolkit stream over Bluetooth Classic. Without
  them it can only use the glasses' own Wi-Fi, which the phone cannot join while it is a Personal Hotspot: the
  stream stayed at `waitingForDevice`. Seen on the real glasses: self-test frame and 30 walk frames with the hotspot on.
- **Mute Kaiku on the walk**: Kaiku's voice mute is one saved choice (`kaiku.talk.voiceMuted`) shared by Talk,
  check-ins and the walk; the walk screen now has the same Mute Kaiku / Unmute Kaiku button (`walk.voice`).
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
  `iOSUITests/TalkComposerTests` (now types in a call on the scripted Live, `-kaikuTalkDemo live`).
- Talk says why voice is not there once (the one line of a state without a call). `TalkView.stateNote` adds "The
  connection dropped" only when the conversation really was live (`Conversation.wasLive`).
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

## The check-in as a passing chat, and "notice and act" (2026-11-14)
Today's first stop (`KaikuRoute.weather`, still titled "Weather check" on the path) opens `Screens/CheckInChatView`:
a small chat with Kaiku, not a form. `Talk/CheckInChat.swift` holds it: `CheckInState` (pure, tested) + `CheckInChat`
(the shared `TalkModel` + `Conversation` with `intent: checkin`, `purpose: check_in`).
- **Three ways to answer, all count.** Voice (Live), typing (the same Live socket: `sendText`), or the three dials
  under the chat ("Or just turn the dials": the same screen, never a gate). Kaiku's hello is on screen as text at
  once (`checkin.hello`); Live says its own hello over it when there is a voice; without Live the cached Gemini
  voice line plays (silent otherwise, never a synthesizer).
- **Brief or stay.** `chat_shape.depth` opens the chat, the latest `feel` plan's `depth` updates it. Brief: the
  model closes (`end_session` + its goodbye): the screen shows "Good to see you", ticks the stop
  (`AppModel.checkInDone()`, one completion moment) and offers the next stop / "Keep talking". Stay: the chat
  simply goes on ("No hurry"), nothing counts turns or sets a timer; "That's enough for now" is the calm way out.
  Leaving after taking part counts too; opening and leaving does not.
- **Dials only.** "That's it" → three `obs.self_report`, the stop is ticked, and Kaiku answers what was dialled in
  one warm line (`CheckInState.dialLine` → `checkin.dials.low|tired|mid|bright`, voice line + text). With Live
  open the model is told the dial words (never numbers) and its own answer takes the line's place; the microphone
  is muted on the end screen. Offline it all still works (queue + text).
- **`feel` (cloud tool, NON_BLOCKING).** Forwarded like every cloud tool, but never shows the thinking state
  (`Conversation.quietTools`); declared from `tools[].behavior`; answered with the result's `scheduling`
  (`LiveSession.toolResponse`). The plan (`FeelPlan`: `stance`, `depth`, `may_offer`, `offer_activity`) is published
  as `Conversation.plan` / `planCount`.
- **What the plan may offer** is an activity card (`ActivityCard(plan:)`, the same card as the `suggest_activity`
  tool: see "Talk is a call"): `offer_activity` decides what it opens. An offer with no screen on this device
  (`offer_activity` null, the robot's drum, a walk on the Mac) stays Kaiku's spoken words: no card. It appears from
  the person's next words on (Kaiku meets the feeling first) and is easy to ignore or put aside.
  `stance: celebrate` plays the completion sparkle once per conversation.
- **Typing without the microphone.** With microphone permission off, the conversation still opens with the
  microphone closed (`typedWithoutMic`, `ConversationAudio.setCapture(false)`: the input node is never touched)
  and Kaiku answers in its voice: the check-in chat and Talk alike (the call bar says "Microphone is off", typing
  is open).
- **The model's close.** `end_session` arrives before or after the goodbye (both seen live): listening stops at
  once, the goodbye is let play (`Conversation.closeGrace`, bounded), output after the goodbye turn is dropped as
  filler. Transcription markers (`<no speech>`, `{pause}`, a lone "-") never become lines (`Conversation.spoken`).
- **Never in a passing chat:** the two-weekly questionnaire (`start_phq9` is refused there).
- Tests: `CheckInChatTests` (state, plan, chat on the real engine with a fake Live + stubbed cloud),
  `KaikuFlowTests.testCheckInChatDialsOnly` (UI). Opt-in paid proof: `CheckInLiveTests` (typed, no microphone;
  `KAIKU_CHECKIN_LIVE_CLOUD`, `KAIKU_CHECKIN_LIVE_SCRIPT=ordinary|hard|good`, `KAIKU_CHECKIN_LIVE_OUT`).
- Not verified on a device: answering by voice in the check-in (microphone opens when the screen does, like
  Talk), the goodbye's sound at the close, the card on a real walk offer.

## Talk is a call (2026-11-14)
A conversation with Kaiku is a call, on iPhone and Mac, in Talk and in the check-in chat: you can mute yourself,
you can mute Kaiku, and the words of both keep coming as captions. Voice first: no page title, no welcome text, no
starters, no scripted replies on screen; a state that needs explaining gets one short line and one action.
- **Two mutes.** `Conversation.setMuted(_:)` closes the microphone (`micMuted`; Kaiku goes on answering what is
  typed). `Conversation.setVoiceMuted(_:)` / `voiceMuted` silences Kaiku at once, mid-sentence too
  (`ConversationAudio.setOutputMuted`: player volume 0). The audio modality stays on, so timing, barge-in and
  `kaikuSpeaking` do not change and the output transcription keeps arriving. The choice is remembered on the
  device (UserDefaults `kaiku.talk.voiceMuted`). `-kaikuMute YES` still silences everything.
- **One short state** (`CallStatus`, pure): connecting · listening · speaking · thinking · muted · micOff · paused
  → `call.state.*`; the same words on the call bar, the Lock Screen, the Dynamic Island and the Mac panel.
- **Call bar** (`CallBar`, `Talk/CallViews.swift`): elapsed time (`Conversation.liveSince`), the state, mute me,
  mute Kaiku, type (the composer is folded away until wanted, and open by itself when the microphone is not
  allowed), end (the words stay; "Call Kaiku" starts the next one). `TalkModel` is the one model behind every
  surface of a call: `status`, `micOn`, `voiceMuted`, `toggleMic()`, `toggleVoice()`, `end()`, `restart()`,
  `activityCard`, `openCard()`, `putCardAside()`. `TalkView(model:)` shows a model owned elsewhere (the Mac
  panel and the Mac Talk screen share one).
- **Without a call** `TalkView.idleState` (pure, tested) gives the one line and the one action: ready or ended →
  "Call Kaiku"; service or voice not there → "Try again"; not connected → "Connect"; paused → the line alone.
- **Activity card.** The device tool `suggest_activity {kind, line?}` answers `{ok, shown}` and shows an
  `ActivityCard` (`ActivityCardView`: icon, name, minutes when known, "Open", a small "Not now"). The `feel`
  plan's offer is the same card. One at a time, never two for the same kind, a card put aside does not come back
  in that conversation, nothing starts by itself. Open → Live is told "The person opened the <kind> card." and
  the app goes to that screen (leaving Talk ends the call, as always); aside → "The person put the <kind> card
  aside.". Kinds per device: `ActivityCard.route` (breathe, tell, walk [iPhone], lantern, seeds, watering,
  pebbles, firefly); `start_activity` uses the same table.
- **Outside the app (iPhone).** The call goes on in the background and with the phone locked
  (`UIBackgroundModes: audio`). `CallSurface` (`Talk/CallActivity.swift`) keeps a Live Activity
  (`CallActivityAttributes`; `CallLiveActivity` in `Widgets/KaikuWidgets.swift`) on the Lock Screen and in the
  Dynamic Island: elapsed time, the state with the microphone's true icon, the newest caption (its tail, from a
  word), and Mute / mute Kaiku / End. The buttons are `LiveActivityIntent`s (`Shared/WalkIntents.swift`) acting
  on the open call in the app's process (`KaikuCall` → `TalkModel.active`) without opening the app; End ends the
  session (`Conversation.stop`, which closes capture). Captions go out at most once a second; the bar is stale at
  the session's length limit, and one left by a killed process is taken down at launch
  (`KaikuCall.clearLeftovers()`). The fast way in: the "Talk to Kaiku" App Shortcut (`TalkIntent`: Siri,
  Shortcuts, Action button) and `kaiku://talk`. No Control Center control (that API is iOS 18; the target is 17.2).
- **A pocket must not listen for long.** In the background `TalkModel.backgrounded()` ends the call after the
  session's `idle_end_s` (180 s; `backgroundQuietLimit` when the cloud sends none) without the person saying or
  typing anything. `max_session_seconds` applies on top.
- **Long calls.** One Live token lasts five minutes, a talk up to thirty. `Conversation.scheduleTokenResume` →
  `plannedResume`: 45 s before `expires_at` (`resumeMargin`), between sentences, the device asks for the next
  token (`resume_session_id`, same surface, intent, purpose and walk style) and moves to a new socket with the
  resumption handle. Nothing on screen changes (phase, captions, the clock), it is not a failed attempt and
  `onReconnected` does not fire. A server `goAway` moves the same way. A socket that ends by itself mid-call
  (seen live: close 1008 "client inactivity" after about two minutes of sending nothing, i.e. muted or typing
  only) comes back the same quiet way once (`quietReconnect`, counted as an attempt); a second failure in a row
  is the visible reconnect ("Waking Kaiku up…"), three → unavailable. Text typed during a switch is held and
  sent when the new socket answers. The setup frame always carries `sessionResumption` and
  `contextWindowCompression` (the cloud's `live_setup` values when present). `proactivity` is sent only when the
  cloud's `live_setup` carries it (today a walk); otherwise the field is left out, never defaulted.
- **Language of what Kaiku hears (2026-11-15).** `LiveSession.setup` sends the cloud's
  `live_setup.inputAudioTranscription` (`{languageCodes: ["en-US"]}`) as it is, empty only when the cloud gave none:
  one path for Talk, the check-in chat and the walk through the glasses, on iPhone and Mac (`Conversation` →
  `POST /v1/companion/session` → `LiveSession.setup`). The on-device recogniser (`OnDeviceListener`, the safety
  gate and the spoken dial) is created with the app language's locale (`en-US`); the app language is English only.
- **Whose turn it is** (`Conversation.ModelTurn`). A model turn that answers the person plays at once: they
  spoke or typed, or did something on screen (`personDid(_:)`: a card, the dials, the walk's "Found one"), and
  the credit also covers a tool their words set off and the goodbye of a conversation the model closed. Every
  other model turn is Kaiku's own (it answers a context event, a nudge, a late tool result, or nothing): its
  audio is held until its transcription has a real word (`Heard`: a letter or digit outside `<…>` / `{…}`), then
  played from the start; a turn whose transcription is a marker, or that ends without a word, is never heard and
  shows no bubble. Measured live: the first transcription fragment arrives with the first audio, so the hold
  costs no time. A turn with no frame for 3 s is over (`turnGap`: the server does not always send
  `turnComplete` for a declined turn). `context(_:)` and `nudge(_:)` wait while Kaiku is speaking, a tool runs
  or the person is owed an answer (a client turn would cut the sentence off), at most `contextPatience` (20 s);
  events that waited together go out as one turn.
- **Markers never reach a line.** Every transcribed fragment of either speaker passes `Conversation.words`
  (`MarkerFilter`, `Talk/SpokenWords.swift`), which takes out `<no speech>`, `{pause}`, `<noise>` also when they
  arrive in pieces (`<no`, ` speech`, `>`: how the real model sends them); a line left with no letter or digit is
  removed when its turn closes; `Conversation.transcript` strips and drops them again before anything is stored.
  Typed lines are kept as typed (`Line.typed`).
- **One answer frame per call frame.** The calls of one `toolCall` frame (the parser marks it: `.toolFrame`)
  are answered in one `toolResponse` frame, device and cloud tools alike, each with its own scheduling; a
  cancelled call is left out. A result waits for the others of its frame at most `toolFramePatience` (10 s: the
  mind may think for two minutes, and a blocking device result must not wait that long); then what is there goes
  out and the rest follows. On a walk, `log_walk_moment` counts at most one find for one thing the person said
  (`WalkModel.lastFind`): a duplicated call gets the first's answer.
- **The end is reported.** Every way a conversation ends comes through `Conversation.stop`, which sends
  `POST /v1/companion/close {home_id, session_id, elapsed_s}` once (not awaited, any answer is fine), so the
  cloud's budget hold settles to the time really used.
- **Walk surfaces.** The walk's Lock Screen and island show the spotting game's own thing and target
  (`WalkGoalLine`: "Trees 1 of 3", dots for the target), and nothing about a game when none is on
  (`WalkActivityAttributes.ContentState.thing` / `target`).
- Tests: `CallTests` (two mutes, markers in pieces, whose turn plays, context queue, next token, quiet first
  drop, held typed text, one response frame, the close call), `CheckInChatTests` (card from both sources,
  `{ok, shown}`, put-aside final, pocket rule, `CallStatus`, `idleState`, caption tail), `LiveSessionTests`
  (long-call settings), `WalkOnAFakeLineTests.testOneFindCountsOnceForOneThingThePersonSaid`. UI on the scripted
  Live (`-kaikuTalkDemo`): `TalkComposerTests`, `CallOutsideTests` (call bar; the Dynamic Island and Lock
  Screen buttons mute and end the call without opening the app). Opt-in, paid, typed, no microphone:
  `CallOutsideTests.testARealCallGoesOnWhileThePhoneIsLocked` (`KAIKU_CALL_LIVE_CLOUD`; passed on the simulator
  2026-11-14: 4 min 48 s locked, three messages answered on the Lock Screen, the third after the move to the
  next token at 4 min 15 s, ended from the Lock Screen) and `GateLiveTests` (`KAIKU_GATE_LIVE_CLOUD`,
  `KAIKU_GATE_LIVE_OUT`; passed 2026-11-14: a dull view declined five times, 0 s played, no bubble).
- Not verified on a device: the real microphone in the background and behind the Lock Screen, Kaiku's voice
  through the speaker or glasses while locked, muting Kaiku by ear, the Lock Screen buttons on a phone with a
  passcode, the "not connected" screen (unit-tested only).

## The check-in's end is the end; a written line is always answered (2026-11-14)
Four faults from real recorded takes, and the rules that came out of them.
- **No conversation without its call bar.** `TalkModel.onScreen` is set by the screen that shows the call bar
  (`screenAppeared` / `screenDisappeared`; nil = no screen has claimed the model, which is the Mac's quick talk).
  While it is false `start`, `restart` and unmuting do nothing, and `screenDisappeared` ends the conversation. On
  the iPhone a tab that is not showing stays alive, and `scenePhase` changes reach it: Talk used to start a call
  from behind another tab when the app came back from the background.
- **An ended check-in never starts again.** `CheckInChat.start` refuses once `state.end` is set or the screen
  was left (`left`; the model is then retired for good, `TalkModel.retire`); only the person's "Keep talking"
  opens a new conversation. The screen leaves its stack when it is left: "Up next" dismisses before it goes on,
  `PhoneTabs` takes `.weather` off a tab's path as that tab is left, and a check-in that still reappears shows
  nothing and pops itself. (Before: a check-in left on Today's stack asked the service for a new conversation,
  with no call bar, every time the tab came back.)
- **An end screen has no open conversation behind it.** After the dials, Kaiku says its one line and the
  conversation closes itself (`Conversation.closeAfterAnswer`: microphone shut at once, never reopened while
  closing). A call ended away from the screen (End on the Lock Screen or in the Dynamic Island, the pocket rule)
  ends the check-in like "That's enough for now": the end screen, the stop ticked if she took part.
- **A line the person wrote is always answered.** (a) No proactive audio unless the cloud asks for it. (b) The
  gate cannot swallow the answer: a turn the person took over is closed for them at once (`supersededGap`), the
  `turnComplete` of a turn they interrupted does not use up their answer, every tool answer renews the wait
  (also the quiet `feel` and a tool that failed), and words after a non-speech sound in Kaiku's own turn are
  heard from there. (c) Silence is noticed: `awaitingAnswer` makes the bar say "Thinking" (a typed call used to
  say "Microphone is off" throughout); if no frame at all arrives within `answerPatience` (8 s) of a written
  line the socket is pinged (4 s): a dead one reconnects and the line is sent again, a live one gets the line
  once more as a whole user turn (`LiveSession.sendTurn`). (d) The line itself: a ping without a pong in 8 s
  and a frame that cannot be sent both report the socket closed; a resumption refused twice ends on a fresh
  line (new token, no handle) with the last six lines as context, instead of "Kaiku can't talk right now".
- **Dials only.** With no call on the line, the three dials and "That's it" are in view at once on a 6.3-inch
  screen at the default text size (Kaiku is smaller there, the button is pinned under the dials). On a touch
  screen a dial's track takes taps and sideways drags only (`TrackTouch`, a pan that begins only sideways on
  iOS 18 and later), so a thumb that lands on a dial still scrolls the page.
- **`-kaikuCallTrace <file>`** now also notes what was typed (sent or held), each model turn and whose it was,
  gate decisions (`turn_heard`, `turn_not_speech`, `turn_dropped_for_person`, `turn_complete_of_interrupted`,
  `after_a_dropped_turn`), tool calls and answers, an unanswered line and why a socket closed. No words.
- Tests: `CheckInChatTests` (ended check-in, left check-in, hidden screen, end from outside, dials close the
  conversation), `CallTests` (the six gate and answer cases, the fresh line), `LiveSessionTests` (no default
  proactivity, the whole-turn frame). UI on the scripted Live: `CheckInEndTests` (left for another tab, "Up
  next", mid-chat tab switch, End on the Lock Screen, "That's it" in view, drag on a dial). Opt-in, paid, typed:
  `CheckInEndTests.testARealCheckInAnswersPlainStatements` (`KAIKU_CHECKIN_TAKE_CLOUD`; passed on the simulator
  2026-11-14: four plain statements 20 s apart, each answered within a second, then the phone locked for half
  a minute and the call was still open on return) and `CheckInLiveTests` with
  `KAIKU_CHECKIN_LIVE_SCRIPT=plain` and `KAIKU_CHECKIN_LIVE_PACE`.
- Not reproduced: the take in which two statements got no answer and the line then dropped. Two real runs with
  proactive audio on (one on the engine as it was) and one with it off answered every statement. The engine
  did have ways to lose an answer (the person's credit used up by an interrupted turn's `turnComplete`, or run
  out during a slow tool, and then a reply that starts with a non-speech sound dropped whole); the first was
  seen happening in a real trace, with a reply that started with words. Those are closed; that they caused that
  take is not shown. A trace of the next such take will say which case it was.

## Walking together: style, nudges, spotting game; Today's invitation (2026-11-14)
On a walk Kaiku is company, not one fixed game. What it says is never decided on the device: a style's words, the
nudge lines and their seconds all come from the cloud (`config/persona.md` "Walking together",
`config/surfaces.toml [surface.glasses.styles.*]`, `config/kaiku.toml [walk.<style>]`).
- **Style.** `WalkStyle` quiet (shown as Calm, the default) · playful · chatty; `WalkModel.style`, stored in
  UserDefaults `kaiku.walkStyle`. Chosen where the walk starts, on the walk, and in You → Settings
  (`WalkStylePicker`: three words + the chosen style's one line). Sent as `walk_style` with `purpose: walk`
  (`Conversation.walkStyle`; the request for the next token repeats surface, intent, purpose and style, tested).
  Changing it on the walk starts the conversation again in the new style (`WalkModel.choose`): the walk, its
  minutes and its count go on, and the new conversation is told `[walk goes on · … · spotting game still on: …]`
  instead of being asked to greet. During a quiet (muted) walk the change waits until the person talks again.
- **Surface.** `glasses` when a glasses adapter or a hands-free headset is there, `iphone` when the walk runs on
  the phone's own speaker (the cloud serves the walk tools on both).
- **Nudges** (`WalkNudger`, pure, tested). A Live session only answers input, so once a second `WalkModel.nudge`
  asks whether the guide's `look_prompt` or `quiet_prompt` is due and sends it through `Conversation.nudge(_:)`,
  which holds the answer's audio until it has a real word (a declined nudge is otherwise a second of sound).
  Nothing is sent unless the conversation is simply listening (not while either side speaks or a tool runs, not
  muted, paused, connecting or ended). Silence runs from when both went quiet, or from the newest words if later.
  Quiet line: once per silence, after the full `quiet_after_s`. Look line: only while pictures are reaching the
  conversation (camera streaming and a frame in the last 3 s), every `look_every_s` of silence, counted from the
  later of the silence's start, the camera coming on and the last nudge. A nil value means no nudge. The timers
  live with the conversation, so a token renewal or a reconnect does not reset the guide.
- **Spotting game** (`WalkGoal`, pure, tested). `set_walk_goal {thing, target 1...5}` starts one (a new goal
  replaces the old) and returns `{thing, target, found, left}`; `log_walk_moment {kind}` counts one find whatever
  `kind` says, never past the target, and returns `{ok, thing, found, target, left}` (the last four null with no
  game on). The count is `WalkModel.goal`, for that walk only: nothing about what was seen is stored, logged
  (the log has numbers, never the thing) or sent anywhere but the live conversation. The fixed light hunt is
  one instance (`WalkGoal.lightHunt`, three): it starts when the person marks a find with no game on (walk
  screen, Dynamic Island, a tap on the glasses) or the model asks for `start_activity light_hunt`, and it is the
  game a walk without Kaiku's live voice has (its cached lines count to three). The person's own "Found one"
  tells Kaiku the count (`[spotting game · trees · 2 of 3 found · 1 left]`). The last find plays the completion
  moment (`AppModel.celebrate()`).
- **Walk screen**: Kaiku's state, where the sound goes, glasses, whether Kaiku can see right now, the three
  styles with the current one lit, and `WalkGoalCard` while a game is on ("Trees  1 of 3", one dot per thing,
  "Found one", a tick when finished; a long thing moves the button underneath).
- **Today's invitation** (`Screens/TodayInvitation.swift`). `InvitationModel.load` on appearing, pull to refresh
  and returning to the app; `InvitationCard` stands where Kaiku's line is (with a small Kaiku) on the phone and
  under the large Kaiku in the wide layout, so the day's path keeps its first stop on screen on a 4.7-inch
  phone. Yes posts the answer, then opens Talk (`talk_about`) or the activity's screen; Not now posts and Kaiku
  says it will be here. An answer that did not arrive is sent again before the next load and the card does not
  come back meanwhile; an answer the service refuses for good (404) is dropped. Not shown: an activity with no
  screen on this device (the robot's drum, a walk on the Mac), an empty sentence, an answer for another home.
  Never spoken by itself: the speaker button says `text` through `POST /v1/voice/say`.
- **A walk without a microphone** (DEBUG, `Walk/WalkTyped.swift`): `-kaikuWalkTyped YES` runs the walk's real
  `Conversation` on the real Live socket with `WalkSilentAudio` (captures nothing, plays nothing, keeps time like
  a speaker) and types `-kaikuWalkSay` lines. For the simulator, whose microphone is the Mac's.
- Tests: `WalkStyleTests`, `WalkGoalTests`, `WalkNudgerTests` (camera off, anyone speaking, muted, paused, not
  live, the full silence, words between two checks, a reconnect), `WalkOnAFakeLineTests` (the walk on a fake
  microphone, a fake Live socket and a stubbed service: style in the request, tool results through the real
  conversation, the completion moment, a style change mid-walk, looks only with pictures, nothing when muted or
  paused, the next token asked for as the same walk, compression + resumption in the setup frame),
  `InvitationShapeTests`, `InvitationModelTests`, `InvitationRequestTests`; opt-in `WalkRenderTests`
  (`KAIKU_WALK_RENDER_DIR`: layout pictures of the card pieces).
- One real walk (2026-11-14, simulator, Meta Mock Device Kit glasses with its generated feed, typed lines, an
  isolated cloud seeded with the one person, Playful): 3 min 6 s on one socket with 178 pictures sent; "What's
  that up there?" → "It looks like the sun in a very blue sky."; a favourite view → `remember`, and the next
  walk's card lists it under the outdoor things they like; a sad sentence mid-game → `feel`, and Kaiku left the
  game. Seen and not yet right: Kaiku proposed "three birds" in words and counted aloud without calling
  `set_walk_goal`, so no card appeared (its `log_walk_moment` got the no-game answer); both look nudges and the
  camera-on notice were answered with about a second of audio whose transcription was `<no speech>`, which
  played and showed as a bubble (a whole `<no speech>` fragment is filtered by `Conversation.spoken` and the
  nudge gate, so the marker probably arrives in pieces; not confirmed from the raw frames).
- Not verified: anything on the real glasses or with a microphone; the card for a goal Kaiku set in a real
  conversation; the completion sparkle on a screenshot; a style change during a real conversation; the
  invitation on the Mac window (logic and a layout picture only); the Live Activity still says "n of 3 found"
  (its views are not part of this change), so it is wrong for a goal with another target.

## History (2026-11-14)
The person's own numbers from every device, the way a health app shows them (docs/decisions.md D48). The numbers
and their titles, units and groups come from the service (`GET /v1/me/history?home_id=&days=56` → `PersonHistory`,
mirrored in `Model/Contracts.swift`; which measures exist is `config/kaiku.toml [history]`). The device draws them
and adds nothing but sums and averages of the days it was sent.
- **The tab** (`HistoryView`): first Your days in small (this week's strip, tap a day to mark it, and the row
  that opens the full Your days screen), then one card per measure in the service's groups and order (robot
  first): name, the devices it came from, the latest value with its day ("Today so far" for today, whose total may
  still grow), and the last seven days as a small chart. A measure with sessions and no counted day yet (a game's
  practice rounds) says so. Nothing recorded at all: one calm line. One column on iPhone; on the Mac two columns
  of cards with the cards of a row the same height.
- **A measure's page** (`HistoryMeasureView`): day · week · month (a week is the last seven days, a month the last
  28 so it reads as four weeks; arrows step to earlier periods as far as the service's window goes). Under the
  switch: what the period adds up to, a Swift Charts chart, the usual range as a soft band and in words, a month
  week by week, then the sessions of the period, newest first, each with its own numbers.
- **How a period is summed** (`HistoryMath`, pure): from `per_day`. A total or a count stays a total (with the
  average a day beside it); every other rule, and a time of day, is the average of the days that have a value. A
  day without a record is never a zero.
- **How a measure is drawn:** an amount (`per_day` total or count) is a bar standing on zero. A level (an average,
  a latest value, a time of day) is a dot at its height on an axis fitted to the person's own values and usual
  range, because a bar would say "this much" of something that is not an amount; a scale ("1 to 5") shows the
  whole scale. Day view draws that day's sessions on the day's clock.
- **A session's bar in day view:** the wire names a session's numbers by payload field and a measure by its own
  key, with no link between them. `HistoryMath.sessionKey` proves the link from the data (same unit and format,
  and on every fully listed day the measure's own per-day rule over that number gives the day's value). No proof,
  no chart: the day shows its value and its sessions, never a neighbouring number.
- **Wording of numbers** (`HistoryFormat`): the service's unit after the number; a unit that is a scale ("0 to 1")
  is said once on the page, not after every number; minutes from 60 up are written with hours, seconds with
  minutes; a session's unit that only repeats its title is left out. The service's `format` says how a value is
  read (`HistoryValueFormat`, on a measure and on each session number): `clock` = minutes after midnight, a time
  of day; `percent` = a share from 0 to 1, written as a percentage in the language's own way ("14%", and the unit
  after it when there is one: "14% of the time"; `decimals` are the percentage's); `duration` = minutes, written
  "45 min" and from an hour up "7 h 20 min", whatever the unit says. The same writing everywhere a value shows:
  the card and its VoiceOver value, the period's headline and average (a small average keeps one place: "4.5%",
  "7.5 min"), the lowest to highest ("10% – 18% of the time", "45 min – 1 h 15 min"), the usual range, the
  picked day, the weeks of a month, the session rows, and the chart's axis (`HistoryAxis.label`: percentages,
  hours from two hours up). A percentage's axis never leaves 0% to 100%. A format this build does not know is a
  plain number with its unit.
- **Nothing in the app lists the measures.** Which measures exist, their titles, units, decimals and per-day rule
  are the service's (`config/kaiku.toml [history]`); the app owns the group's icon and tone (by group key, a
  neutral chart and ink for a key it does not know), the devices' names, and the writing above. A new series or
  group draws without an app change (`HealthHistoryFormatTests`). A session's long number wraps inside its row
  (`FlowRow`) instead of running past the edge. A measure that has sessions and no counted day says "practice"
  only where a practice round is listed (`HistoryFormat.emptyKey`); otherwise "Nothing counted yet".
- **Simulated records** are labelled "Simulated" as in "Today, so far": on the card when the latest day is, by
  the period's summary when every counted day is, on each session; where a period mixes simulated and other days
  the simulated marks are drawn lighter and a line under the chart says so.
- **Offline** (`HistoryModel`, `HistoryCache`): the last answer is kept in `history.json` and shown at once on
  opening, with "Updated: …" under the list; when the service cannot be reached the line says so and gives when
  the numbers were last updated. See Invariants for what a pairing change does to it.
- **Links and routes:** `kaiku://history` (the tab), `kaiku://days` and `kaiku://history/days` (Your days). A
  measure's page is pushed by the tab itself (`HistoryRef`), not a `KaikuRoute`: a route has no room for a key.
- **Tests:** `HistoryTests.swift`: periods (month and year ends, the week the clocks change), roll-ups per rule, a
  month as weeks, a session's local day in the home's time zone, the proof of a session's number (and its
  refusals), the value axis, number and day wording, the models against the schemas and their enums, defaults and
  unknown words on decode, the kept copy (shown first, replaced, scoped to service and home, no credentials), the
  pairing change through `AppModel`, a late answer for the previous home, the request, tabs and links. Opt-in
  `HistoryRenderTests` draws the tab and measure pages to PNG from a saved real answer.
  `HistoryFormatWordsTests` (in `HealthSummaryTests.swift`): a share as a percentage, a percentage's range and
  average, minutes as a duration, a duration's range and average, a session's numbers in their own format, an
  unknown format as a plain number, the chart's axis in the measure's format, a duration that adds up, a
  measure without a counted day, a percentage in the language's own way.
- **Not verified:** on a real iPhone or Mac window by a person; VoiceOver over the charts; Finnish layout; a
  record longer than the 56 days asked for.

## Quick talk on the Mac (2026-11-14)
Talking to Kaiku from any app without opening its window: one small object at the left edge of the screen.
- **One shape that grows** (`QuickTalkStage`, `QuickTalkSurface`): at rest a thin clay bar (6 × 52 pt, 4 pt from
  the edge of the usable screen, vertically centred, on the screen the pointer is on); under the pointer a pill
  with exactly two round buttons (start speaking, open Kaiku; icons with tooltips); on the trigger the popup
  card (360 × 184; Kaiku left, the call's state word, captions, controls). It is one window and one rounded
  shape whose size, corner radius and colour animate (`Spring.gentle` to the popup, `gentleOut` for the hover;
  Reduce Motion: a crossfade, nothing grows). While a conversation is on and the popup is put away the bar is a
  little wider (12 × 64) and carries a voice meter (the person's level, a soft pulse while Kaiku speaks, dim
  while muted), and its pill's two buttons are show the conversation / end.
- **Triggers** (all need no permission; checked on macOS 26.5 with an app that has neither Accessibility nor
  Input Monitoring): ⌥⇧Space, a Carbon hot key (`QuickTalkHotKey`; not Spotlight, not input-source switching);
  a double tap of one modifier key, ⌃ Control by default, ⌥ Option or off in You (`QuickTalkDoubleTap`, pure:
  two lone taps, each held under 0.3 s, at most 0.4 s apart; another modifier, or any key or click in between,
  starts over; it reads modifier changes from a global `flagsChanged` monitor and the system's count of key and
  mouse presses, never which key); the pill's first button; "Talk now" in the menu bar popover. The trigger
  again, or Esc (a hot key only while the popup is open, so Esc is quick talk's in every app meanwhile), closes.
- **The conversation** is the Talk screen's: `QuickTalkModel.shared.talk` is the ONE `TalkModel` on the Mac
  (`TalkView(model: .forTalkScreen())` in `Screens.swift`), surface `mac`, purpose `talk`, microphone open, and
  the person speaks first (Talk's "just opened" event is not sent). A conversation that is already on (put away
  earlier, or the Talk screen's) is shown as it is and never restarted.
- **Three ways the popup goes away**: the chevron puts it away and the conversation goes on (the bar shows the
  voice, the notch island the call; with nobody talking it ends by itself after the session's `idle_end_s`, else
  `TalkModel.backgroundQuietLimit`); Esc or the trigger again ends it the way leaving Talk does, unless the main
  window is showing Talk (then that screen keeps it); End call ends it wherever it shows. "Continue in Kaiku"
  hands the same conversation to the Talk screen (and stops it if that screen never comes up). A crisis ends it
  and brings the main window forward, where the crisis screen is.
- **Honest states** (`QuickTalkDisplay.make`, pure; the most basic thing missing is the one said): setup not
  finished, not connected, paused, microphone access off, service / voice / audio unavailable, ended. Each is
  "Not listening", one calm line and the one action that helps (Open Kaiku, microphone settings, Try again, Call
  Kaiku). A state without an open call never shows an open microphone (tested over every input combination).
- **Kaiku reacts** (`QuickTalkMoment`, pure): its face follows the call (listening, thinking with three small
  dots, speaking, sleepy while the person is muted) and for a few seconds shows a moment with a small drawn
  glyph beside it (sparkle, heart, question hook; token colours, never emoji), only from something that
  happened: the model's `express` call, a new `feel` plan (celebrate = sparkle, explore = curious, comfort =
  cozy + heart, give_space = cozy), `recall` coming back with a memory. While the plan says the person is having
  a hard time there are no sparkles and no cheering. An activity card's Open ends the quick talk and opens the
  activity in the main window.
- **Settings** (You → Settings → Quick talk, Mac only: one row that says On or Off, `QuickTalkSettingsRow`, and
  opens a sheet with the four choices, `QuickTalkSettingsSheet`; UserDefaults
  `kaiku.quicktalk.on|bar|doubleTap|captions`): on/off, the bar at the screen edge (also a switch in the menu bar popover; off = nothing on screen at rest, the
  triggers still work, and a conversation put away still shows the bar), the double tap, captions (off = Kaiku
  alone with the controls, 176 × 198).
- **The window** (`Mac/QuickTalkPanel.swift`): borderless `.nonactivatingPanel`, level floating, every Space and
  beside full-screen apps, never key, no system shadow; a 12 Hz timer reads the pointer for the hover and makes
  the window take the mouse only on the pill and the popup card (the resting bar takes no clicks).
- **Snapshot runs are inert** (`QuickTalkModel.inert`, set when `-kaikuSnapshot` or `-kaikuInspectOnly` is
  given): no window, no hot key, no monitor, and the trigger starts nothing. `-kaikuQuickTalkSnapshot <dir>`
  writes every stage and state (light + dark), `sheet.png`, `reactions.png` and `island-call.png` from seeded
  displays; with `-kaikuTalkDemo <state>` also `demo-<state>*.png|txt` from the real model on the scripted Live
  (popup, put away, the app's own island following it, muted, ended); with `-kaikuQuickTalkProbe YES` instead
  `window-probe.txt` and `window-*.png` from the real window (made, placed, hovered with handed-in pointer
  positions, opened inert, closed).
- Tests: `QuickTalkTests.swift` (double tap; stages, sizes, hover, where on notch / Dock-left / external / tiny
  screens; the display rule; captions; moments; and the model on a stand-in microphone and socket: the person
  speaks first, the two mutes, put away / show / end, the quiet limit, the Talk screen keeping its conversation,
  the hand-over, nothing starting when it cannot listen or in an inert run, a crisis, reactions from real tool
  calls).
- Not verified (needs a person at the Mac): real key presses in the real app, a spoken conversation, how the
  growing feels, the bar beside a full-screen app and across Spaces and displays, tooltips on the pill (the
  window is never key), the click on the notch. Known: a check-in chat open in the main window is a second
  conversation (quick talk does not know about it); "Talk now" leaves the menu bar popover open; a double tap of
  ⌥ may also be another app's shortcut on the same Mac, which is why ⌃ is the default.

## You: settings as short rows (2026-11-14)
- **The page** (`Screens/YouView.swift`): four short sections of rows. Two columns on the Mac pane, where the
  whole page fits the 980 × 720 window; one column under 600 pt and on the phone. The gap between two sections
  in a column is the gap between sections everywhere (`Space.s5`, `KAdaptiveColumns(stack:)`).
  **Privacy**: Pause everything (switch) · Sharing and permissions ("2 of 5 on", opens the choices) · What Kaiku
  saw today. **Kaiku and you**: What Kaiku remembers · Help and crisis contacts · Run setup again ("Your choices
  and connection stay as they are" is its line on the phone and its tooltip on the Mac, where the line would
  wrap in the half-width column and push the page past the window).
  **Settings**: Voice · Quiet hours · phone: Glasses check, walk style · Mac: Quick talk ("On" / "Off", opens
  its sheet) · Little sounds (switch) · "Notifications are off" when they are. **Devices and service**: Devices ·
  Kaiku service ("Connected · host" or "No companion service"; opens `ServiceSheet`: where it is connected, Find
  nearby services, Unpair this device with the same confirmation as before).
- **The row rule**: a row is an icon tile, a short title, at most one short line and ONE control: a switch
  (`KToggleRow`) or a link (`KRow` with a chevron; `.link("On")` shows a short value before it) to the screen or
  sheet that holds the rest. Never a switch and a link in one row, never a paragraph in a row: longer text is a
  quiet line under the card or lives where the row leads. `KToggleRow` lays out its own row (icon, labels, the
  bare switch): a `Toggle` whose label has two lines is not given its height in a Mac `VStack`, and the text ran
  over the row's padding and the divider. VoiceOver hears the title and the line on the switch, as its label
  (as before: a consent text must not depend on hints being on).
  `KDivider(plain: true)` is the divider between rows without an icon tile. `KSheet(title, width:, height:)` is
  the sheet: title, Done (Esc), scrolling content with the section gap; the size applies on the Mac only.
- **Sharing** (`SharingRows`, `SharingInFull`): one row for each signal of this device (`Signal.forThisDevice`,
  the order, the bindings and the meaning of setup's "Your choices"): the tile is sage while the signal is on and
  grey while it is off (`Signal.symbol`), then the title, one line (`Signal.lineKey`: the signal's own text, or
  its short form `sig.<x>.s` where the text is a paragraph: camera, transcripts, see) and the switch. The whole
  text of every signal with a short form stands under the list ("In full"): consent text is shortened in a row,
  never dropped. The Mac opens the list as a sheet (`SharingSheet`, `Size.contentMax` wide: one line a row); the
  phone opens it in place under the row (the UI tests tap "Sharing and permissions", then look for the Walks
  switch and "Glasses check" on the same page; the row's accessibility label stays exactly that, its count is the
  value). Setup keeps the whole texts in its rows. Showing the list switches nothing (`YouSettingsTests`).
- **The screens You leads to**: What Kaiku remembers (the remember switch; the conversation-words switch whose
  line says how many talks are kept, the whole consent text under its card, then the buttons to read or delete
  them, as wide as their words on the Mac); What Kaiku saw today (one row a signal: tile, title, what was
  noticed line by line or "Paused by you", and its pause switch); Voice (one card: language, speaking pace).
- **Pictures of the real window** (`WindowShots` in `Mac/DebugSnapshot.swift`, DEBUG, `-kaikuWindowShots <dir>`,
  arguments under "Run standalone"): the window as a whole cannot draw itself into a bitmap on macOS 26 (blank),
  but its parts can, so a picture is put together from them: the page backdrop (`KBackdrop`, rendered afresh),
  each split-view column's hosting view, and every clip view at its place and scroll position
  (`cacheDisplay`). A pane longer than the window is scrolled a page at a time (`-p2`, `-p3`), an open sheet is
  pictured on its own (`-sheet`), and `shots-<look>.txt` says for each screen whether it fits ("scrolls: content
  790 pt, 668 pt show"). The 980 × 720 window shows 668 pt of pane under its title bar; the smallest window is
  720 × 532. Every run adds `sheet-<w>x<h>.png` (all pictures of that size in the folder), and
  `-kaikuShotCompare "<before>|<after>"` writes `compare-<w>x<h>-<look>.png` (same file names side by side).
  ```bash
  APP=<derived data>/Build/Products/Debug/Kaiku.app/Contents/MacOS/Kaiku
  for look in light dark; do "$APP" -kaikuWindowShots /tmp/you -kaikuShotLook $look -kaikuSkipOnboarding YES \
    -kaikuTab you -kaikuSnapshotPair "http://127.0.0.1:9/?home=snapshot" -kaikuShotsOnline YES; done
  ```
  The run is quiet and changes nothing: no Dock icon, never frontmost, the window at 1 % opacity and deaf to
  the mouse, no menu bar item (a second Kaiku status item beside a running Kaiku made the system quit the new
  instance), no usage sampling, no notification scheduling, quick talk inert, the pairing in memory, and it ends
  by itself. It reads the settings of the Kaiku on this Mac (the same defaults) and must never switch one.
  What a picture cannot show: the sidebar's and the title bar's glass (flat fills), the toolbar (a screen's back
  button and title), and the sage of a switch that is on (the window is never key, so switches are drawn in the
  grey of an inactive window).
- Not verified (needs a person at the Mac): a real click on a row opening its sheet and Esc / Done closing it,
  "Find nearby services" from the service sheet and the unpair confirmation, the switches' colour in an active
  window, VoiceOver on the new switch rows.

## Agreed in one place, shown everywhere (2026-11-14)
The person says yes to an activity in a conversation with Kaiku (the robot, a walk through the glasses, the
phone, the Mac). The model calls the cloud tool `agree_activity`, the cloud keeps the item for the day and tells
every open screen (D50; the rules are the cloud's: `cloud/AGENTS.md`). This is the iPhone and Mac side.
- **The tool** is forwarded like every `executor: cloud` tool (`POST /v1/companion/tool`). What the model gets
  back is `CompanionToolResult.forModel`: the result as it is, and for a refusal `{…result, ok: false, error}`,
  so the cloud's reason reaches the model and Kaiku does not promise what was not kept.
- **The home stream** (`Net/HomeStream.swift`, `Net/HomeUpdates.swift`): one `GET /v1/me/stream` for the
  pairing, read with `URLSession.bytes` and the app's own parser (`SSEParser`: chunks split anywhere, all three
  line ends, comments, several data lines).
  | event | what the app does |
  |---|---|
  | `agreed` | reads `GET /v1/me/invitation` again: the invitation and the agreed list arrive in one answer and `InvitationModel.shared` holds both; `removed` also takes the item off the screen at once |
  | `day` | `AppModel.refresh()` (Today's path, "Today, so far", the garden), and History's own reload when the History tab is open |
  | `invitation` | the invitation's card leaves |
  | `hello` | with `resync` (a first connection, or the cloud cannot go on from the last id): reads everything again |
  | `ping` | every 15 s; nothing to do |
  No frame at all for 37.5 s (two and a half heartbeats) is a dead connection: it is closed and opened again.
  Waits between tries are 1, 2, 4 … 30 s with jitter, and 45 to 60 s after an answer that will not get better
  by itself (401, 403, 404). `Last-Event-ID` is sent on every reconnect (kept in memory, for this pairing only).
  Events of a previous pairing are dropped (the stream's generation, the pairing revision, the hello's
  `home_id`), and unpairing empties the list.
- **When it runs** (`StreamGate`): paired, not "pause everything", and the app running. On the Mac that is
  always. On iPhone: in the foreground, and in the background only while a call or a walk keeps the app
  running. The stream never keeps the phone awake by itself and never opens the microphone.
- **Today** (`Screens/TodayAgreed.swift`, `TodayView`). `AgreedBoard` gives one item the card: the oldest open
  one this device can start, else the oldest open one. The card has the cloud's sentence, where it was agreed
  with the time ("With the robot · 14:05"), and Start / Not now; when this device cannot open it (`opens_here`
  false, or no screen for it here) there is no Start and a line says where it can be started. The other items
  are single lines under it (an open one with a small Start, "Started", "Done · 14:20"): two on a phone, three
  in the wide layout, the rest as "+1 more today"; put-aside items are not shown. Start opens the activity's
  screen at once and posts `opened`; Not now posts `put_aside`; a 404 just reads the list again. The app never
  posts done: an item turns done from the activity's own observation. An item that turns done while it was open
  or started on this screen plays `AppModel.celebrate()` once, also when it was done on another device (not a
  second time when this device's own completion just played it). The cloud holds the daily invitation back
  while an item is open or started, so there is one card with buttons at a time and the day's path keeps its
  first stop on screen on a 4.7-inch phone.
- **The notification** (the rule: `NudgeScheduler.agreed`; the bookkeeping: `Notifier.agreed`). One local
  notification per item: its name as the title, the cloud's sentence as the body (plus where it can be started
  when that is not here), and the actions Start and Not now, which do what the card's buttons do. It is posted
  when an item is open and has not been shown to the person on this device: not while the app is in front
  (iPhone: active; Mac: the main window is the key window), not on the device the yes was said on (the item's
  `surface`; a walk is `glasses`, so the phone in the pocket is notified), not in quiet hours and not while
  everything is paused (the card waits on Today, and a later read outside quiet hours may still post it once).
  Once per item id, remembered across launches. It is taken away when the item is no longer open (started, done,
  put aside, removed). On the Mac it is posted only if notifications are already allowed: nothing here ever
  asks for the permission. A picture run of the Mac app (`-kaikuWindowShots`, `-kaikuSnapshot`) posts nothing.
- **What is at once and what is not.** There is no Apple push in this app. At once: wherever the app is running
  with the stream open, which is the Mac, the iPhone in the foreground, and the iPhone in the pocket during a
  call or a walk. Not at once: an iPhone whose app is suspended or closed hears nothing. The item is on Today
  the next time the app comes to the foreground, and its notification comes late and only if the system grants
  a background refresh first (`KaikuAppDelegate.backgroundRefresh` → `HomeUpdates.catchUp` reads the list
  once; the system decides when, typically hours apart). Apple push was considered and left out on 2026-11-14.
- **Today's path is a separate record.** Its stops are ticked from what was done on this device (and the walk
  from the garden), so an activity finished on another device shows as the agreed line "Done · 14:20", in
  "Today, so far" and in the garden, but does not tick its stop on this device's path.
- **Debug:** `-kaikuStreamTrace <file>` (DEBUG) writes one line per step of the stream with its time (opened,
  hello, an event's kind and state, the list read): no words, no ids.
- **Tests:** `HomeStreamTests` (27: the parser, the events, the client against a scripted service and a
  `URLProtocol` stream, `HomeUpdates`) and `AgreedTests` (35: the shapes, the board, the model, the
  notification rule, the notifier, the tool forwarded from Talk, the check-in chat and the walk).
  `HomeStreamLiveTests` (opt-in, native on the Mac: `KAIKU_STREAM_CLOUD=http://127.0.0.1:<port> swift test
  --filter HomeStreamLiveTests`) runs the Mac's real stream, list and notification rule against a local cloud
  seeded with the one person; the notification centre is replaced, so nothing shows on the Mac.
  `iOSUITests/AgreedFlowTests.swift` (opt-in: `TEST_RUNNER_KAIKU_AGREED_CLOUD=`) has three flows on a simulator:
  a yes on the robot shows on an open Today and turns done; a yes during a call notifies on the Lock Screen and
  its Start opens the activity; a yes on a walk notifies the locked phone. It joins the `Kaiku iOS UITests`
  target with the next `xcodegen` (the project lists its files one by one).
- **Shown on 2026-11-14** (iPhone 17 Pro and iPhone SE simulators, iOS 26.2, and natively on the Mac, against
  a local cloud; the yes was the tool call a device forwards, posted to the service as the robot or the
  glasses): with Today open, the stream event was in the app 7 to 9 ms after the call was sent and the card's
  item 17 to 47 ms after it; with a call on and the phone locked, the list was read after 56 to 137 ms and the
  notification was on the Lock Screen when the test looked (1.6 s, most of it waking the screen); on the Mac
  the item was on the list and its notification handed over within 8 ms, and done 31 ms after the observation.
- **Not verified:** a real conversation in which the model itself calls `agree_activity` (the robot's and the
  glasses' ends); real devices; the Mac app's own window with the stream open and a real macOS banner with its
  two actions (the Mac was shown through `HomeStreamLiveTests` and a picture run of Today, which opens no
  stream); the late notification after a background refresh; how long iOS really keeps the app running in the
  background on a device during a call or a walk; fi/sv copy (English text under the fi keys).

## Apple Health summary (2026-11-14)
With the choice "Watch" on (off by default), the iPhone reads Apple Health and sends one `obs.wearable_daily` a
morning: daily totals and averages, never a single reading, and never a score. Apple's sleep score has no
HealthKit type, so the app sends the stages and the time awake it can read and makes nothing up. The Mac has no
Apple Health: `HealthSync` compiles for iOS only, so `swift test` on a Mac does not compile it and an iOS build
is the check that it still builds.

- **What each number is made of** (`Health/HealthSync.swift` reads, `Health/WearableDailyBuilder.swift` is the
  pure arithmetic). Two windows, both fixed by the morning so that a later sync gives the same numbers: the
  night = 18:00 the day before to 12:00, the day = the previous calendar day, 00:00 to 00:00.

  | field | from | how |
  |---|---|---|
  | `sleep_min`, `sleep_midpoint_min` | `.sleepAnalysis`, every "asleep" value | as before: intervals merged, whole minutes; the midpoint of first falling asleep to last waking |
  | `sleep_deep_min`, `sleep_rem_min`, `sleep_core_min` | `.sleepAnalysis` `.asleepDeep` / `.asleepREM` / `.asleepCore` | each stage's intervals inside the night merged, then summed, whole minutes. Any staged sample → all three (a stage not reached is 0); no staged sample → none of the three |
  | `sleep_awake_min` | `.sleepAnalysis` `.awake` | merged, cut to the span from first falling asleep to last waking, whole minutes. Absent when the source wrote neither stages nor "awake"; 0 when it wrote stages and no "awake" |
  | `steps` | `.stepCount` | sum over the day |
  | `distance_km` | `.distanceWalkingRunning` | sum over the day, km to 2 places, 0…300 |
  | `exercise_min` | `.appleExerciseTime` | sum over the day, whole minutes |
  | `daylight_min` | `.timeInDaylight` | sum over the day, whole minutes, 0…1440 |
  | `resting_hr_bpm` | `.restingHeartRate` | average over the day, 1 place, sent only above 20 and below 250 |
  | `walking_hr_bpm` | `.walkingHeartRateAverage` | average over the day, 1 place, sent only above 20 and below 250 |
  | `hrv_sdnn_ms` | `.heartRateVariabilitySDNN` | average over the day, 1 place |

  "In bed" is not read. A field Health holds nothing for is absent, never 0 (the stages' 0 above is the one
  exception, and it is a measured 0). A summary with no number at all is not sent. The envelope id hashes the
  whole summary, so the same snapshot is one observation and late samples make a newer one.
- **A nap.** The night's window starts at 18:00, so an evening nap inside it counts as sleep, and the span the
  time awake is cut to runs from the nap's start. Only what the source wrote as "awake" is counted in that span:
  the hours between the nap and the night are not turned into time awake.
- **Asking iOS** (`HealthSync.reviewAccess`, reached through `HealthAccess.review`). The read types are one set
  (`readTypes`). iOS shows its sheet only for kinds it has not asked about, and tells an app whether asking
  would show it (`statusForAuthorizationRequest` = `shouldRequest`), so a person who turned Watch on before an
  update is asked once for the added kinds, and the morning's summary is sent again with them. It is asked
  where she is looking at her own data or her choices: opening You → Sharing and permissions, turning the Watch
  switch on (there and on What Kaiku saw today), and when History loads. Never at launch and never from a sync,
  which can run in front of a task. iOS never says what the answer to a read request was: a refused kind is
  simply absent from the summary.
- **Sample data** (DEBUG: You → "Add a sample night to Health", `-kaikuHealthSample YES`). Writes one made-up night
  with stages and a quarter of an hour awake, and yesterday's steps, distance, time in daylight, resting heart
  rate and HRV, after deleting what it wrote for those hours before. HealthKit refuses an app's request to write
  `.appleExerciseTime` and `.walkingHeartRateAverage` (Apple's own sums), so sample data never has exercise
  minutes or a walking heart rate. A summary made of anything this app wrote goes out `sim: true`
  (`holdsSampleData`: samples whose source is this app), so stand-in numbers never count as a person's.
  Release builds ask for no write access at all (`shareTypes` is empty).
- **What she is told** (copy ground truth; English first, English under the fi keys). The switch's short line
  `sig.watch.s`, the whole text `sig.watch.full` (shown in setup's "Your choices" and You → Sharing and
  permissions → in full, through `Signal.wholeKey`), setup's permission row `setup.perm.health.d`, and
  `NSHealthShareUsageDescription` in `project.yml` (the system's sheet) each name what is read and say it is
  daily totals. See Known issues for the older `sig.watch.d` in `design/copy.json`.
- **Her own data.** History draws whatever measures the service lists (group `sleep_body`, "Sleep and body"),
  by day and week, with the service's unit and format: nothing in the app names a Health measure, so a new one
  shows without a change here. The receipts name the kinds of numbers the day's summary held in plain words
  (`health.name.*`): "Today, so far" ("Last night and yesterday: sleep, sleep stages, time awake at night, …")
  and the Watch row of What Kaiku saw today ("Apple Health, as daily totals: …", or "Apple Health: nothing read
  yet today"). No value and no word about how a night or a day was.
- **Tests.** `HealthSummaryTests.swift`: `HealthSummaryBuilderTests` (each stage merged before summing, a
  night without stages, a stage never reached, a stage sample outside the window, awake only between first
  falling asleep and last waking, an awake sample cut at the night's edge, awake without stages, awake only
  outside the night, awake without any sleep, an evening nap inside the window and one before it, a sample that
  only touches the window, rounding, the ranges, one new number alone is an observation, the wire names, a
  summary without the new numbers written as before, the payload against the contract schema),
  `HealthDeliveryMarkTests` (sample data goes out simulated, a person's does not, the choice switched off
  meanwhile sends nothing), `HealthReceiptTests` (the receipt names every kind the summary holds and only
  those, no number and no judgement, sample data is labelled, the choice's text names everything read),
  `HealthHistoryFormatTests` (km with the service's decimals, long minutes as hours and minutes, beats a
  minute, a week of a new series, a series this build never heard of decodes and draws) and
  `HistoryFormatWordsTests` (see "History"). `iOSUITests/HealthSummaryUITests.swift` (opt-in:
  `TEST_RUNNER_KAIKU_HEALTH_CLOUD=<scratch service>`, with `TEST_RUNNER_KAIKU_HEALTH_HOME=<seeded home>` for
  earlier days and `TEST_RUNNER_KAIKU_SHOT_DIR=<folder>` for pictures) has two flows on a simulator. One: the
  sample data is written, read back through the same queries a phone uses and sent as one simulated summary
  whose numbers the test checks at the service; History and both receipts are then pictured. Two: History's
  "Sleep and body" and "Camera during activities" groups and the pages of the measures named in
  `TEST_RUNNER_KAIKU_HEALTH_MEASURES=day_distance:week,deep_sleep:day,…` are pictured from the seeded home.
- **Shown on 2026-11-14** (iPhone 17 Pro simulator, iOS 26.2, a scratch service on the working tree): the
  system's sheet listing the kinds of data; the sample night and day read back as sleep 460 min, deep 60, REM
  90, core 310, awake 15 (the 7 minutes after the last waking left out), distance 4.66 km, daylight 53 min,
  steps 6 400, stored `sim: true` with no walking heart rate; History (the group, and by day and week the
  pages of distance, time in daylight, deep sleep, time awake and walking heart rate, the last from a seeded
  simulated record) and the receipts on the iPhone, and the same in picture runs of the Mac app from the same
  service; both schemes build (the iPhone one for the simulator and, unsigned, for a device).
- **Not verified: needs a phone and a watch.** No real Apple Health data was read in building this. Open: what
  a real Apple Watch night gives (stages, "awake" samples, the device read as `apple_watch`); the walking
  heart rate average and exercise minutes, which only a watch writes; time in daylight from a watch; the
  system's sheet for the added kinds on a phone that already allowed the older ones; background delivery; a
  phone without a watch (steps and distance only); a third-party sleep app that writes no stages; the Finnish
  text.

## Kaiku bot (2026-11-14)
What the robot at home hears and does, live, on the person's own iPhone and Mac: the robot's parts (head, sensor
board, hub) already talk over the MQTT broker on the home network in contract envelopes; this page listens to that
broker while it is on screen and draws what arrives. A tab in the Mac's sidebar (before You); on iPhone a screen
under You → Devices and services (`KaikuRoute.bot`, `kaiku://bot`), because an iPhone tab bar shows five and a sixth
puts the fifth AND the sixth (You) behind "More" (seen on the iPhone SE simulator, iOS 26.2).
- **What it listens to** (`Net/BotBus.swift`): MQTT 3.1.1 over TCP (`NWConnection`, no package): CONNECT with a clean
  session and a random client id, keep-alive 30 s (PINGREQ every 15 s; nothing heard for 45 s = reconnect), SUBSCRIBE
  QoS 0 to exactly `kaiku/v1/<home>/raw/#`, `cmd/#`, `obs/#`, `health/#` (`+` for the home when none is known),
  reconnect with backoff 1 · 2 · 4 · 8 · 15 s (× 4 after a refused name/password), DISCONNECT on stop. A QoS 1/2
  delivery is acknowledged; a packet larger than 1 MB or malformed drops the connection. `BotTopics.allowed` drops
  anything that is not one of those four kinds for that home before it is decoded.
- **The page, simplified (2026-11-15; this replaces the layout described under "The page" below):** three cards on
  top, always: the connection line with the robot's parts, "Robot microphone", and Now (once something was heard).
  Under them two lines that open on a tap (`BotMore`): "Where the robot is" (the address and the sign-in; open by
  itself only while there is no address, nobody answers or the broker refuses) and "Everything the robot sends"
  (Senses, Voice and mind, Sent on to your record, the feed; closed by default).
- **Nothing to configure in the usual case:** the address is the paired service's host; a typed address that does
  not answer falls back to that one and back (`BotModel.tryOtherAddress`). The home id is no longer taken from the
  pairing (the boards may publish under another id than the person's record, `demo-aino` vs `aino`): the page
  listens to any home on the broker and keeps to the first one heard (`heardHome`); `kaiku.bot.home` still names one.
- **Robot microphone (D56, 2026-11-15):** the first card under the connection line, one switch, "Use this device as
  the robot's microphone", off by default and off again at every launch (`BotModel.micOn`, never stored). On:
  microphone permission is asked if needed, `AudioCapture` runs (memory only), its 16 kHz PCM is cut into 640-byte
  frames (`BotMicFramer`) and each frame is published QoS 0 on `kaiku/v1/<home>/audio/phone/mic` (`BotMicWire`,
  `MQTTOut.micFrame`: the only PUBLISH there is, it refuses any other topic or size) **only while the hub holds the
  robot's microphone open** (`BotState.micHeld`: a `cmd.head {mic: open}` in the last 5 s and no close since);
  otherwise the frames are dropped in the app. The home in the topic is the paired home, else the home the last
  `cmd.head` came on. While on, the connection stays up when the page is left or the app goes to the background
  (iPhone: background audio, and the screen is kept awake). The hub mutes it while the robot's speaker plays
  (hub `AGENTS.md`), so the status line reads waiting / Kaiku is speaking / listening through this device.
- **What it never does:** publish anything but those microphone frames (no envelope, no command), subscribe to `audio/#` (the head's microphone and
  speaker frames) or `kaiku/v1/#`, store or send on anything it heard (memory only: the last 300 feed lines, 40
  records, until the app quits), show the person's words (`heard` carries none; a typed `cmd.hub say` is "not
  shown"), show `feel`'s manner cue (only the tool's name), show a safety flag's details ("Safety flag" in the
  records; "Help numbers shown on the robot" while `cmd.head {show: help}` holds), or use a state, verdict or score
  word (`BotStateTests.testNoStateOrVerdictWordInTheTabsCopy`).
- **When it listens:** the page is on screen AND the app is in front (iPhone: scene active; Mac: app active, display
  awake, session active). Leaving the page, the background, another app in front or the display sleeping closes the
  connection at once (`BotModel.setVisible` / `setInFront`). A Mac picture run (`AppPresence.pictureRun`) counts as
  in front.
- **The address:** "The robot's address" on the page (`host` or `host:port`, port 1883 by default), remembered in
  UserDefaults `kaiku.bot.address`; empty = the guess: the paired companion service's host when it is loopback or a
  private / link-local / `.local` address (a cloud host is never guessed). Optional name and password ("Name and
  password, if the robot asks"): the name in UserDefaults `kaiku.bot.user`, the password in the Keychain
  (`fi.kaiku.robotbus`; Mac debug builds keep it for the run only, like `PairingStore`). The home id is the paired
  home, except a profile the app made for itself on a nearby service (`device-<uuid>`, which no robot publishes
  under): then any home on the broker (`+`). `kaiku.bot.home` (e.g. `-kaiku.bot.home demo-aino`) names the home
  when the boards publish under another one (the hub's `KAIKU_HUB_ROBOT_HOME_ID` case).
- **The page** (`Screens/BotView.swift`, all words `bot.*` in `copy.apple.json`, English under fi): nothing heard
  yet = "The robot" (the connection line, one plain sentence when nobody answers, the parts, the address field);
  once something came: the connection line, then **Now** (the microphone first and large: open while the hub's
  `cmd.head {mic: open}` is fresh, under the head's own 10 s limit, or while the head's heartbeat says
  `audio.mic_open`; the ritual step from `obs.ritual` / `health/hub` `ritual` / `health/head` `step`, who runs it,
  eyes, chest light, movement), **Senses** (ear dial value, taps with a dot per tap and the tempo of the last few,
  the camera as a frame with a dot at the face position and its size as nearness, someone / nobody in view,
  distance, room light, the caption "No picture leaves the robot's camera", pulse, button), **Voice and mind**
  (conversation open / closed, Kaiku's last lines with how they were spoken, "You spoke" as a count, each tool call
  in plain words with who answered and how long, Tap it back: song, level, turn, band), **Sent on to your record**
  (the `obs.*`), **Everything, as it comes** (newest first, time · part · one line, ×n for a flood updated in place:
  face frames, distance, pan, pulse samples, a run of taps, a held microphone, heartbeats per part and status;
  Pause; All / Senses / Body / Voice and mind / Records), then the parts and the address. Unknown types and fields
  are one plain line. Mac: two columns from 640 pt.
- **Run it against the sims** (no hardware, no model): `make broker`, `make sim NODES=head,sensors`,
  `KAIKU_VOICE=off KAIKU_ATTENTION_FACE_SOURCE=off make hub` (the second keeps the Mac's own camera closed), then open
  Kaiku bot and type the computer's address (`127.0.0.1` on the same Mac; its LAN address from an iPhone on the same
  Wi-Fi). The hub-driven greeting waits for an ear press; in the run below nobody pressed, so it was skipped. Tap it back with the hub's own beat
  on its own broker: `make tap-back BEAT=1 ARGS="--broker-port 18831"` and `-kaikuBotAddress 127.0.0.1:18831
  -kaiku.bot.home tap-back-check`.
- **Launch arguments:** `-kaikuBotAddress host[:port]` (this run only, never remembered), `-kaiku.bot.home <id>`;
  DEBUG: `-kaikuBotReplay <file.jsonl>` plays a recording made by `BotRobotRunTests` instead of the network (the page
  says "Playing back a recording"), `-kaikuBotScroll now|senses|voice|records|feed|robot` and `-kaikuYouScroll
  devices` (iPhone pictures of the rest of a page). Mac pictures: `-kaikuWindowShots <dir> -kaikuShotScreens bot`.
- **Tests** (`BotTests.swift`): the wire (CONNECT / SUBSCRIBE bytes, no PUBLISH, remaining length at every boundary,
  packets in any pieces, QoS 1/2, malformed and random input), the filters and the audio guard, the address and the
  guess, the reducer on every example of `contracts/schemas/examples.json` and on `raw.hub.trace` as `HubTrace`
  defines it, the microphone rule, floods as one line, 300 lines, unknown types, the copy (no state words, every
  word family and registry tool has words), when it listens, and the real client on a throwaway mosquitto
  (`BotBrokerTests`, skipped without mosquitto: retained heartbeat, audio frames and another home never arrive,
  QoS 1, the broker restarting, stop). Opt-in: `KAIKU_BOT_TEST_BROKER=127.0.0.1:<port> [KAIKU_BOT_TEST_HOME=<home>]
  [KAIKU_BOT_TEST_SECONDS=60] [KAIKU_BOT_TEST_RECORD=<file.jsonl>] swift test --filter BotRobotRunTests` listens to
  real robot software and prints what the page made of it.
- **Shown working (2026-11-14, this Mac, no hardware, no model, cloud off):** (1) the repo's Tap it back check
  (`tools/drum_music_check.py --tap-back --beat --broker-port 18831`: the real hub + the head twin on a throwaway
  broker) with the sensors twin on the same broker: `BotRobotRunTests` received 915 envelopes in one ritual (health
  47, raw.hub.face 327, raw.sensors.distance 346, raw.head.pan 38, raw.head.tap 40, raw.head.ear 8, raw.hub.trace 47,
  cmd.head 27, cmd.sensors 13, cmd.hub 1, obs.ritual 12, obs.self_report 4, obs.tap_back 1, obs.presence 1,
  obs.engagement 1, obs.intervention_response 1, obs.nudge_offered 1), 0 audio frames although the hub sent 1773 on
  `audio/head/speaker` meanwhile; (2) the hub-driven ritual with `make sim NODES=head,sensors` and the real hub
  (voice off, camera off, own broker on 18832, own files): 436 envelopes (health, raw.hub.face, raw.sensors.distance,
  raw.head.pan, cmd.head, obs.ritual, obs.presence, two `raw.hub.trace` lines). Setup (1) was run again three times
  with the app itself connected live: the iPhone SE simulator (light and dark) and the Mac picture run drew it.
- **Not verified:** a real robot (Atech head, UNO Q, hub on the venue Wi-Fi) has NOT been connected; an iPhone on
  the LAN (local-network permission prompt, a LAN address) has not been tried, only the simulator on loopback; a
  broker with a name and password; a `raw.hub.trace` `tool` or `heard` line, an open microphone and the help
  screen from real software (no Live conversation was run: those are covered by the reducer tests only);
  VoiceOver and Dynamic Type at accessibility sizes by a person; the Finnish text (English under the fi keys).

## Let Kaiku's model look (2026-11-15, D65)
- **Choice:** `Signal.look` ("Let Kaiku's model look"), off by default, on You and in onboarding beside the camera
  choice; `AppModel.lookOn` = that choice AND `cameraOn`. Copy `sig.look.t/.d/.s` (fi is the English text for now).
- **Code:** `TaskCapture/VisionLook.swift`: `VisionLookRules` (from the session's `vision_look`), `VisionLookSampler`
  (pure: settle, interval, count, a face in the frame), `VisionPicture.jpeg` (downscale in memory),
  `VisionLookBatch`, `VisionLookRequest`. `TaskCameraSource.lookFor(_:)` is implemented by `ARKitFaceSource` and
  `VisionTaskCamera`; `TaskCamera.lookRules`/`onPicture`; only `CheckInChat` sets them.
- **Sending:** `CheckInChat.sendPictures()` at the end of a check-in she took part in: `APIClient.visionLook`, once,
  `retry: false`. Dropped unsent when she left without taking part, turned a choice off, or left the screen.
- **Invariant:** a picture lives only in `VisionLookBatch` (memory). Never a file, never `OfflineQueue`, never a log,
  never a second send. `VisionLookTests` holds this; games, Talk and walks never make pictures.
- **Not verified:** on a real iPhone or Mac camera. The package builds and its tests pass; the app needs a new
  install and the service a restart before the switch does anything.
