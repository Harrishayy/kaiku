# Plan 02 — Kaiku the companion: one character on every surface · ⏹ SUPERSEDED BY 08 (what was built is in `docs/progress.md`)

> ⚠️ **Scope guard:** build order and cuts in [`04-mind-depth.md`](04-mind-depth.md) override this plan where they conflict.

> Builds on [`01-foundation.md`](01-foundation.md) (✅ done). Read the root `AGENTS.md` first; this plan adds
> surfaces, data points and a character, it does **not** change the consensus principle, the safety path or
> the privacy rules. Decisions are recorded as D22–D28 in `docs/decisions.md`.
> Status 2026-11-14: everything here is built against the **sims first**. Real glasses / watch / phone are
> adapters selected by config (golden rule 3), swapped in once the sim path works.

## 1. What we are adding (one paragraph)

Kaiku stops being "a robot plus some web pages" and becomes **one companion character that lives on every
surface**: the robot on the desk, a voice in the Meta glasses on walks, the iPhone (app, Dynamic Island,
widgets, optional watch data), the Mac (menu bar + notch island, gentle usage sensing) and the web
dashboards (person `/me`, clinician `/clinician`). Same face, same voice, same words, same data, everywhere.
Every interaction is short, warm and optional — and each one quietly yields a data point for the consensus.
The character never judges, never nags, never mirrors decline back at the person.

## 2. The character — Kaiku (D22)

- **It is the robot.** The mascot is the robot's face: the same two soft oval eyes as the head's eye display,
  the same single floppy **ear** (the robot's ear encoder is the dial), the same warm **chest glow** (chest
  LEDs). Body: a round, slightly squashed pebble, cream with a warm shadow. No mouth by default; expression
  lives in eyes, ear and glow (a tiny mouth appears only for "happy" and "sleepy-yawn").
- **Single source of the look:** `design/` module (tokens + `mascot.svg` with named parts + `motion.md`).
  Web renders the SVG; Swift draws the same geometry (shapes copied from `design/mascot.spec.json`, never
  redrawn by eye). The robot eye display uses the same eye shapes.
- **States** (transient, set by the interaction in progress):
  `idle` · `listening` (head tilt, ear up) · `thinking` · `happy` (bounce, sparkle) · `cheering` (after a game) ·
  `breathing` (body scales with the breath guide) · `sleepy` (late night: half-lidded, slow blink, "z") ·
  `walking` (Live Activity / glasses card) · `cozy` (wrapped in a scarf: "I'm here") · `peek` (half out of the
  notch / island edge).
- **Ambient mood** (persistent, from the cloud): `GET /v1/me` returns `mascot: {mood, line_key}` computed by a
  **pure function** of state in the cloud (one implementation, all clients render it). Mapping rule: the mascot
  never looks sad or worried at the person. `stable`→`idle/happy`, `watch`→`cozy`, `needs_call`→`cozy` + offers
  "want me to let your nurse know you'd like a chat?", `safety`→ the scripted crisis screen (no animation, no
  character jokes; `docs/safety.md`).
- **Idle life (the little things):** blink every 3–7 s (random, double-blink 1 in 6), breathing scale 1.00→1.025
  over 4 s, ear twitch when tapped, eyes follow the cursor on Mac / tilt with the phone (CoreMotion, small),
  yawns after 23:00, glow colour follows time of day (dawn peach → day cream → dusk amber → night dim blue),
  greets by time of day, remembers the last thing you did together ("same walk as Tuesday?").
- **Motion budget:** springy but slow (≥ 300 ms, gentle overshoot), nothing flashes, all animation respects
  Reduce Motion (falls back to cross-fades). Haptics on iPhone: soft `.light` tick on dial steps, `.success` on
  completion.

## 3. Design direction (D23)

Warm, simple, quiet. **Not** clinical-blue, **not** gamified neon.
- Palette: paper cream background, ink-brown text, one clay/terracotta accent, sage for "going well",
  soft sky for calm. Dark mode = warm charcoal, never pure black. No red anywhere except the crisis screen.
- Type: SF Pro Rounded on Apple; on web a rounded humanist sans from Google Fonts (pick in the design artifact).
- Shapes: big radii, generous spacing, one primary action per screen, large tap targets (≥ 44 pt).
- Copy: second person, short, never clinical (see root `AGENTS.md` wording rules). Every number shown to the
  person has a plain sentence next to it.
- Deliverables: a published **design artifact** (directions, mascot sheet with all states animated, key screens
  for iPhone / Mac / island / Live Activity / glasses card / `/me` / `/clinician`) and the `design/` module that
  code consumes (`tokens.json` → generated `tokens.css` + `Tokens.swift`).

## 4. Surfaces and parity (D24)

Native Apple app = **one SwiftUI multiplatform project** `apps/apple/` (XcodeGen), shared package `KaikuKit`
(models, API client, pairing, offline queue, mascot view, games, voice player, tokens). iOS and macOS show the
**same screens with the same names**; platform-only features are marked.

| Feature | iPhone | Mac | Web `/me` | Robot | Glasses |
|---|---|---|---|---|---|
| Pair to home (QR / link `?home=&t=`) | ✓ scan | ✓ link | shows QR | — | via iPhone |
| Today (mascot, greeting, one suggestion) | ✓ | ✓ window + menu bar | ✓ | ritual | voice |
| Weather check (daily 3-dial: mood/energy/sleep) | ✓ | ✓ | ✓ | ✓ ear dial | ✓ voice |
| Games (§5) | ✓ | ✓ | ✓ firefly only | drum | walk games |
| Breathe with Kaiku | ✓ (+ watch HR) | ✓ | — | ✓ PPG | ✓ audio |
| Your days (good & hard days, garden) | ✓ | ✓ | ✓ | — | — |
| PHQ-9 (every 14 days) | ✓ | ✓ | ✓ | spoken | — |
| Nudges | local notif + Live Activity | notch island + notif | — | head turn | ear voice |
| Live Activity / Dynamic Island | ✓ walk, breathe, check-in | notch island (same layouts) | — | — | — |
| Widgets | ✓ home/lock | ✓ desktop | — | — | — |
| Watch / Health data | ✓ HealthKit (optional) | — | — | — | — |
| Usage rhythm sensing | — (no Screen Time entitlement) | ✓ opt-in | — | — | — |
| Glasses bridge (DAT SDK) | ✓ | — | — | — | — |
| "What Kaiku saw today" + pause | ✓ | ✓ | ✓ | — | — |
| Crisis / "I'm not OK" button | ✓ always visible | ✓ | ✓ | top button | voice phrase |

Parity is enforced by a shared screen list in `KaikuKit/Screens.swift` (an enum both targets render) and by the
`apps/apple/AGENTS.md` parity table — a feature isn't done until both columns are ✓ or marked platform-only.

## 5. Interactions and games — each one is warm, short, optional, and yields data

| Name | What the person does | Surface | Data yielded (obs) | Time |
|---|---|---|---|---|
| **Weather check** | "How's the weather inside?" — three soft dials (sun↔cloud mood, battery energy, moon sleep); Kaiku's ear turns with the dial | all | `obs.self_report` ×3 (`channel`) | 15 s |
| **Firefly** | Tap when a firefly glows; don't tap the moth (go/no-go) | iPhone, Mac, web | `obs.play_session` reaction median/IQR, lapses, false taps | 60 s |
| **Tell Kaiku** | Answer one gentle prompt aloud ("what was the best bit of yesterday?"); Kaiku listens with ear up | iPhone, Mac, web, glasses | speech rate, pauses, pitch variability (on device) → `obs.laptop_session` / `obs.play_session` | 30 s |
| **Breathe with Kaiku** | Kaiku's body grows/shrinks 6 breaths/min; with a watch, HR before/after | all | `obs.hrv_session` (robot) or `obs.play_session{game:"breathe"}` + `obs.wearable_daily` HRV | 1–3 min |
| **Drum** | Drum on the robot's head along with a Lyria groove | robot | `obs.drum_session` (exists) | 1–2 min |
| **Light hunt** (walk) | On a walk, Kaiku in your ear: "find three things that are green" — tap the glasses to "collect" | glasses (Gen 2) + iPhone | `obs.outing` (minutes, cadence, gait regularity, daylight, head-up ratio) | walk |
| **Garden** | Every finished interaction plants/waters something in Kaiku's garden. It **rests** when you're away, never dies, no streak counter | iPhone, Mac, `/me` | none (reward only) | — |
| **Postcard** | After a walk, Kaiku "writes" a postcard of it (steps, minutes, a doodle) — shareable with the friend lamp (friendlink) | iPhone | `obs.friend_link` (sent) | 5 s |

Rules: nothing is ever required; one invitation per surface per day max (the bandit picks which, existing
`/v1/nudge`); skipping is a first-class button ("not today" → Kaiku: "okay, I'll be here"). No streaks, no
scores shown as grades — the firefly game shows "your fireflies today" art, not a number.

## 6. Data points per source (D25, D26)

Consensus sources become **four**: `robot`, `glasses`, `laptop` (display label "Apps"), new optional
`wearable`. A missing source is just "insufficient" (it is not counted), so the optional watch never hurts.

| Source | New / changed signals | How (all on device; only derived numbers uplinked) |
|---|---|---|
| glasses (Ray-Ban Meta Gen 2 via DAT SDK in the iPhone app) | walk `cadence_spm`, `gait_regularity`, `head_up_ratio` (IMU, beta); `daylight_min` (sparse camera frames → brightness/sky ratio, frames discarded); walk minutes from phone location; spoken answers via on-device Speech (beta) → dial values parsed locally, **no transcript stored**; mic (HFP 8 kHz) speech features during "Tell Kaiku" | `obs.outing` extended; `method` adds `dat_imu` |
| laptop / "Apps" (Mac app) | **usage rhythm** (D26): active minutes, late-night minutes (00–05), minutes by broad category (work, communication, social, video, news, games, other) from the **frontmost app's bundle id only**; app switches per hour; longest unbroken stretch; breaks. No window titles, no URLs, no keystrokes, no screenshots | `obs.screen_activity` hourly |
| laptop / "Apps" (games anywhere) | firefly / breathe / tell-Kaiku from iPhone or Mac | `obs.play_session` |
| wearable (new, optional) | sleep minutes, sleep midpoint, sleep regularity, resting HR, HRV (SDNN), steps, exercise minutes — from **HealthKit**, so Apple Watch *and* any watch that writes to Apple Health (Garmin, Oura, Fitbit, Withings…) | `obs.wearable_daily` once per morning |
| robot | dial can now also come from phone/Mac/glasses voice (`self_report.channel`); still counts as the daily-dial instrument | `obs.self_report` + `channel` |

Why usage rhythm and not content (D26): the useful signal is *when* and *how* the laptop is used (late nights,
fewer active hours, passive vs active use, withdrawal from communication), not *what* someone reads. Content
analysis is invasive, hard to consent to, and adds little. Categories are computed from a local bundle-id table
and only minute counts leave the Mac. Every signal is opt-in on the consent screen, pausable from the menu bar,
and listed in "What Kaiku saw today". New code written at the event (no code from any earlier project).

## 7. Unified voice (D27)

- **One voice**: one Gemini prebuilt voice name in `config/kaiku.toml [voice]`, used by Gemini Live on the robot
  and by the cloud TTS endpoint for everything else.
- **One script**: `config/voice_lines.toml` — every line Kaiku says, keyed (`greet.morning`, `walk.light_hunt.1`,
  `checkin.thanks`, …), with en/fi/sv. Apps, glasses and robot use keys, never their own wording.
- `GET /v1/voice/{line_key}?lang=` → audio (cloud TTS, cached on disk; pre-rendered for the demo so it works
  offline). Apps cache audio locally. Browser apps never hold the Gemini key.
- Glasses (Gen 2) speak through the iPhone app's audio session (Bluetooth), so it is literally the same voice in
  your ear as on the desk. The crisis message stays the scripted text in `config/safety_phrases.toml`.

## 8. The little things (what the demo video will linger on)

1. Kaiku peeks out of the MacBook notch when it's 01:10: half-lidded, yawns, "it's late — I'm going to sleep, you too?"
2. Dynamic Island during a walk: tiny Kaiku walking, minutes ticking; expanded: three "light hunt" dots filling.
3. Robot turns its head → the phone's Kaiku turns the same way at the same moment (both follow the same event).
4. Weather check: dragging the dial turns Kaiku's ear in sync, with a haptic tick per step.
5. Garden grows a sprout after each interaction; after 3 quiet days it shows "resting", never wilting.
6. Breathe: phone, Mac, robot glow all breathe in sync if open together.
7. Eyes follow the cursor on Mac; tap Kaiku → ear flick + tiny sound.
8. Time-of-day glow across every surface. Night mode dims everything warmly.
9. "What Kaiku saw today" — a calm receipt-style list, with a pause switch per signal.
10. Clinician side: the same character appears only as a small icon; the clinician view is calm and dense.

## 9. Architecture changes

```
iPhone app ─┬─ KaikuKit (shared) ─ HTTPS /v1/events, /v1/me, /v1/nudge, /v1/voice
            ├─ adapters/glasses: DATGlasses (real, MWDAT SDK) | MockGlasses (Mock Device Kit or our CSV replay)
            ├─ adapters/health: HealthKitSource | SimHealthSource
            └─ Live Activity + widgets extension (ActivityKit/WidgetKit)
Mac app ────┬─ KaikuKit (shared)
            ├─ adapters/usage: FrontmostAppSampler (NSWorkspace + idle time) | SimUsage
            └─ notch island window + menu bar extra
web ─────────  /me (redesign + garden + good/hard days + pairing QR), /clinician (new sources, polish)
cloud ───────  new obs types stored + in criteria; /v1/me gains mascot + highlights; /v1/voice; 4th source
design/ ─────  tokens.json, mascot.svg + mascot.spec.json, motion.md → tokens.css, Tokens.swift (generated)
```
The cloud's SQLite stays the one database (D24): every device pairs to the same `home_id` and reads `/v1/me`,
which is how phone, Mac and web stay in sync. Offline: each app queues envelopes (idempotent by `id`).

## 10. Contract changes (workstream B does these first; `SCHEMA_VERSION` unchanged — nothing deployed)

- `envelope.Source` += `phone`.
- `payloads.SelfReport` += `channel: Literal["robot","phone","mac","web","glasses_voice"] = "robot"`.
- `payloads.Outing`: `method` += `dat_imu`; optional `cadence_spm`, `gait_regularity` (0–1), `head_up_ratio` (0–1).
- New `obs.screen_activity` (source `laptop`): `period_min`, `active_min`, `late_night_min`,
  `category_min: {work, communication, social, video, news, games, other}`, `switches_per_hour`,
  `longest_stretch_min`, `breaks`, `paused: bool`.
- New `obs.play_session` (source `phone|laptop`): `game: firefly|breathe|tell`, `device: phone|mac|web`,
  `duration_s`, optional `reaction_ms_median`, `reaction_ms_iqr`, `lapses`, `false_taps`, `speech_rate`,
  `pause_ratio`, `pitch_variability`, `hr_before_bpm`, `hr_after_bpm`.
- New `obs.wearable_daily` (source `phone`): `date`, optional `sleep_min`, `sleep_midpoint_min`,
  `sleep_regularity` (0–1), `resting_hr_bpm`, `hrv_sdnn_ms`, `steps`, `exercise_min`, `device: apple_watch|other_watch|phone_only`.
- `sources.py`: `ConsensusSource` += `wearable`; `screen_activity`, `play_session` → `laptop`; `wearable_daily` → `wearable`.
- `api.MeResponse` += `mascot: {mood, line_key}`, `highlights: [{date, kind: good|hard, text, source}]`, `garden: {plants, resting}`.
- `config/criteria.toml`: `[sources.wearable]` + metrics (sleep_min down, sleep_midpoint up=later, resting_hr up,
  hrv down, steps down); laptop metrics `late_night_min` up, `active_min` down, `communication_min` down,
  `firefly_reaction` up; glasses `cadence` down, `daylight_min` down. All new metrics start conservative
  (`weight = 0.5`), re-run `make tune`, record numbers as a new D-entry.
- Sims: `laptop_sim` emits screen_activity + play_session, new `phone_sim` emits wearable_daily + phone self_report,
  `glasses_sim` emits the extended outing; synthetic patients get the new signals (Aino: later sleep midpoint,
  more late-night minutes, lower cadence from ~day 18).

## 11. Workstreams (parallel; one agent each, own git worktree, one module folder)

| WS | Scope (folders) | Phase | Needs | Done when |
|---|---|---|---|---|
| **B** backend | contracts, sim, config (criteria, voice), cloud | 1 | — | §10 merged, `make check` green, `make tune` numbers in decisions |
| **D** design | `design/` (new module) + published design artifact | 1 | — | tokens + mascot spec + motion spec merged, artifact link in progress log |
| **A1** Apple core | `apps/apple/` KaikuKit + iOS & macOS app shells, Today, Weather check, Firefly, Breathe, Your days, pairing, offline queue | 2 | B, D | both apps run in sim against `make cloud-local`, parity table ✓ for core rows |
| **W** web | `apps/web/` `/me` redesign, garden, highlights, pairing QR, clinician new sources, tokens | 2 | B, D | `/me` and `/clinician` show all 4 sources on seeded patients |
| **A2** iPhone extras | `apps/apple/iOS*`, extension targets: Live Activity + Dynamic Island, widgets, HealthKit adapter, DAT glasses adapter (Mock Device Kit), light hunt | 3 | A1 | walk Live Activity in simulator, wearable_daily + outing posted from sim/mock |
| **A3** Mac extras | `apps/apple/macOS*`: notch island, menu bar, usage sampler, late-night peek, notifications | 3 | A1 | island peeks on nudge, screen_activity posted, pause works |
| HW | CAD + firmware (teammate) | — | — | per plan 01 §8 |

Each agent: work in its worktree, `make check` before finishing, update its module `AGENTS.md` + `modules.toml`,
append to `docs/progress.md`, never edit another workstream's folders (leave a `Broken/blocked` line instead).

## 12. Demo video beats added by this plan (fit into plan 01 §14)

0:00 Mac notch peek at night → 0:08 morning: robot turns head, iPhone Kaiku turns too → 0:15 weather check on the
phone (ear dial, haptics) → 0:25 walk with glasses: Dynamic Island walking Kaiku, "light hunt" in the ear →
0:40 firefly game → 0:50 `/me` garden + good/hard days → 1:00 clinician view: four sources, consensus, explanation.

## 13. What we need from people (not blocking the sim build)

- **Meta:** nothing now (Mock Device Kit). Before real glasses: register the iOS app in the Wearables Developer
  Center (app ID), turn on Developer Mode in the Meta AI app, glasses on recent firmware. Motion + Speech are
  dev/beta-channel only — fine for the demo, say so in the submission.
- **Apple:** a free personal team is enough for simulator + own device. HealthKit and Live Activities run in the
  simulator (we write sample Health data in debug). Real watch data needs an iPhone with a paired watch.
- **Team:** pick the mascot direction in the design artifact (default: the first one if nobody answers in 30 min).
