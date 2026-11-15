# Plan 05 — iPhone extras: notifications, voice, Live Activities, Siri, watch, glasses · ✅ DONE (the MUST items, built 2026-11-14; see `docs/progress.md`)

> Builds on [`02-companion-apps.md`](02-companion-apps.md) §4–§5 and [`03-intelligence.md`](03-intelligence.md) §5.2–5.3.
> Scope guard ([`04-mind-depth.md`](04-mind-depth.md)) applies: every item is **MUST** (demo path) or **STRETCH**.
> Workstream **A2**, folder `apps/apple/` (iOS target + extensions only; `KaikuKit` changes coordinated with A1's code).

## 1. Notifications — gentle, rare, useful (MUST)

**Local notifications only** (no APNs: needs a paid developer account + push key; not worth it for the demo).
- **What gets scheduled:** at most **one invitation a day** (the nudge from `GET /v1/nudge`, e.g. "A short walk while
  it's light?") + **one check-in reminder** if no weather check by the person's usual time (learned from episodes;
  default 10:00) + **PHQ-9 due** card once (day 14). Nothing else. Never a crisis message by notification.
- **When:** inside the person's windows only; never in quiet hours (default 22:00–08:00, set in You → Quiet hours);
  respects iOS Focus (`interruptionLevel = .passive` for reminders, `.active` for the invitation; never
  `.timeSensitive`). Skip if the person already did the thing today on *any* surface (robot, Mac, glasses — read
  from `/v1/me` / context card).
- **How it's refreshed:** on app foreground, after pairing, and via `BGAppRefreshTask` (best effort) — fetch
  `/v1/nudge` + `/v1/me`, cancel stale requests, schedule the next ones. Deterministic scheduler in `KaikuKit`
  (pure function: `(now, windows, done_today, nudge, quiet) -> [Notification]`) so it's unit-tested.
- **Actions without opening the app** (category buttons): invitation → **Let's go** (opens the activity) · **Later**
  (+2 h, once) · **Not today**. Check-in reminder → **Good · Okay · Low** quick buttons → `obs.self_report{item: mood,
  value: 4|3|2, channel: phone, context: adhoc}` sent from the notification extension (queued if offline).
- **Learning:** every outcome → `obs.nudge_outcome` (accepted / later / declined / ignored after 4 h), so the bandit
  learns what this person likes (existing contract).
- **Look & sound:** title is the line from `design/copy.json` / `config/voice_lines.toml` (same words as Kaiku says
  aloud); a small mascot attachment image matching the time of day; one soft custom chime (`kaiku-chime.caf`, ≤ 1 s).
  STRETCH: a Notification Content Extension showing the animated mascot + the 3 mood buttons.
- **Deep links:** `kaiku://today`, `kaiku://play/firefly`, `kaiku://checkin`, `kaiku://walk`, `kaiku://phq9` — taps
  land on the exact screen.
- **Permission:** asked in onboarding *after* explaining ("I'll nudge you at most once a day"), optional; denied →
  the app works fully, You → Notifications shows a calm "turned off" row with a Settings link.

## 2. Voice — one Kaiku, on the phone and in your ear (MUST)

- **Scripted lines:** `GET /v1/voice/{key}?lang=` audio, **prefetched** for all keys after pairing (on Wi-Fi) into the
  app cache; played with `AVAudioPlayer`. Offline / 503 → on-device `AVSpeechSynthesizer` with a fixed voice close to
  Kaiku's (rate/pitch tuned once), so there is always a voice. Same line keys as the robot.
- **Talk (Gemini Live):** `AVAudioSession` `.playAndRecord`, mode `.voiceChat`, options `.allowBluetoothHFP,
  .defaultToSpeaker` (so Meta glasses work as mic + speaker). Mic 16 kHz PCM in, 24 kHz out (**VERIFY** in Live docs).
  Echo cancellation via voice-processing I/O. Barge-in: Live's `interrupted` stops playback immediately.
- **On-device listening alongside Live:** `SFSpeechRecognizer` with `requiresOnDeviceRecognition = true` runs the
  **safety gate** on partial transcripts (same phrase list + fixture as the hub), and parses spoken weather-check
  answers ("pretty tired, maybe a two") with a rule-based number/word parser (en/fi/sv). Transcripts are never stored
  or sent. (On-device Gemma parser = plan 04 G1, STRETCH.)
- **Session handling:** interruptions (phone call, Siri, alarm) → pause Live, mascot "listening paused", resume or end
  politely; route changes (glasses connect/disconnect, AirPods) → keep going on the new route, tell the person once;
  app backgrounded during Talk → end the session cleanly after 30 s (audio background mode only during an active
  walk/talk). Live session time limits → resume/reconnect with "I'm still here".
- **Accessibility:** every control has a VoiceOver label from copy.json; Talk has a "type instead" path; captions of
  Kaiku's reply shown only while speaking (from Live output transcription, not stored).

## 3. Live Activities & Dynamic Island (MUST: walk · breathe; STRETCH: check-in)

- Widget extension with ActivityKit: **Walk** (compact: tiny walking Kaiku + minutes; minimal: Kaiku; expanded:
  minutes, steps, light-hunt dots, End / Pause buttons via App Intents) and **Breathe** (Kaiku breathing, breaths left).
- Updated locally from the app while it runs (walk keeps location in the background only during the walk) — no push.
- Ends cleanly on walk end, app termination (stale date + dismissal policy), or 4 h max.
- Layouts per the design artifact (Dynamic Island compact/expanded + Lock Screen).

## 4. Siri, Shortcuts, widgets, controls (MUST: App Intents + one widget; rest STRETCH)

- **App Intents:** "Check in with Kaiku" (opens weather check), "Start a walk with Kaiku", "Breathe with Kaiku",
  "Talk to Kaiku" — exposed as App Shortcuts (Siri phrases in en/fi/sv where supported), usable from the Action button.
- **Widgets:** small/medium Home Screen widget (mascot in its ambient mood + today's suggestion) and a Lock Screen
  widget (mascot + "check in"). STRETCH: interactive widget with Good/Okay/Low buttons; Control Center control
  "Talk to Kaiku" (iOS 18+).
- Widgets read a small shared snapshot (App Group) written by the app — never call the network themselves.

## 5. Watch / Health data (MUST, collection only)

- HealthKit read-only: sleep analysis, resting HR, HRV SDNN, steps, exercise minutes. Asked only if the person turns
  on "Watch & Health" in consent; any watch that writes to Apple Health works.
- `HKObserverQuery` + background delivery (daily) and on foreground → one `obs.wearable_daily` per date (idempotent:
  envelope id derived from date), queued offline. **Never mentioned in conversation or notifications** (team decision).
- Simulator: a debug-only "Add sample Health data" button writes realistic samples, so the path is demo-able.

## 6. Glasses (Gen 2, DAT SDK) (MUST with Mock Device Kit; real glasses when available)

- `GlassesAdapter` protocol with `DATGlasses` (MWDAT SDK via SPM) and `MockGlasses` (Mock Device Kit / CSV replay).
- Walk companion: start from the app, the Live Activity, Siri, or a glasses tap; audio over HFP (§2); IMU → cadence,
  gait regularity, head-up ratio; sparse camera brightness → daylight minutes (frames discarded); phone location →
  minutes → `obs.outing{method: dat_imu, ...}` at walk end. "Look at this" (held tap) sends one frame to Live.
- Connection states shown in You → Devices (searching / connected / battery low / disconnected mid-walk → the walk
  continues on the phone).

## 7. Edge cases to test (moderate, complete; unit tests for the pure parts + one simulator pass)

| Case | Expected |
|---|---|
| Nudge would fire at 21:59 vs 22:00 (quiet starts 22:00) | 21:59 scheduled · 22:00 moved to next window |
| Already walked today on the glasses | no walk invitation |
| Check-in done on the robot at 08:05 | no check-in reminder |
| "Later" twice | second "Later" not offered (one snooze max) |
| Quick "Low" from the notification while offline | queued, sent once on reconnect (same envelope id) |
| Notification permission denied | app fully usable; You shows "Notifications are off" + Settings link |
| Phone call during Talk | Live paused, mascot paused state, resumes or ends politely |
| Glasses disconnect mid-walk | walk continues on phone, one spoken notice, outing still posted |
| App killed during a walk | Live Activity ends within its stale date; partial outing posted on next launch |
| Timezone change / DST | windows recomputed in local time; no duplicate notifications |
| Spoken crisis phrase during Talk (en/fi/sv) | on-device gate stops Live before the reply, crisis screen + scripted line |
| Spoken "maybe a two" / "kakkonen" / "en tvåa" in weather check | energy = 2 |
| HealthKit denied / no watch | no wearable obs; consensus shows "No watch connected"; nothing breaks |
| Same Health day synced twice | one `wearable_daily` (idempotent id) |
| Voice line 503 / offline | on-device synthesiser speaks the same line |

## 8. Done when

Walk Live Activity + Dynamic Island visible in the simulator with a mock-glasses walk; a scheduled invitation and a
quick "Low" reply land as obs in the sim cloud; Talk plays a cached Kaiku line and handles an interruption;
"Check in with Kaiku" works from Shortcuts; wearable_daily posts from sample Health data; all §7 unit tests green;
screenshots of island/lock screen/widget at small + large sizes reviewed for overflow.
