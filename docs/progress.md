# Progress log (APPEND-ONLY)

Newest at the bottom. Never edit or delete old entries. One entry per work session, per module.

```
## 2026-11-14 03:40 — <agent or person> — <module>
- Did: <what changed, files>
- Verified: <tests run, sim/hardware checks>
- Contract changes: <none | details + version>
- Broken/blocked: <what, why>
- Next: <the next concrete step>
```

## Owners
A hardware/firmware · B hub/live · C cloud/ML/sim · D apps/demo/story (fill in names on the board).

---

## 2026-11-13 23:30 — Claude Code (setup agent) — all (Phase 0 + walking skeleton)
- Did: repo layout, AGENTS.md/CLAUDE.md/GEMINI.md, .mcp.json, Makefile, config/, contracts (pydantic → schemas + TS, shared Bus/config/jlog), sim nodes + keyboard, tools (tail/record/replay/doctor), hub (perception, ritual state machine, safety gate, uplink, cloud link, live adapters), cloud (FastAPI, SQLite, baselines/drift/corroboration/bandit, template + Gemma briefs, cohort eval, Modal app), apps/web (Next.js static export), docs, module READMEs, handoff.md updated (§16 quickstart).
- Verified: `make check` (ruff + 127 pytest incl. real-mosquitto integration); web typecheck + build + headless-browser check; end-to-end broker + cloud-local + seed + sims + hub: full ritual (greet→close), all obs uplinked, Aino amber / 7 others green, no errors in any log.
- Contract changes: initial v1. `type` fully qualified (D11). Added cmd.hub `start_ritual`/`say`; API models LiveEventsResponse, NodeHealthReport, HealthOverview.
- Broken/blocked: not deployed to Modal yet; Gemini Live / Lyria / vLLM paths untested against real services; all model IDs in config/kaiku.toml are `VERIFY-` placeholders; Atech adapter + camera are stubs pending spikes.
- Next: A — Atech + UNO Q spikes. B — verify Gemini Live/Lyria model IDs, live voice. C — `modal setup`, `make cloud-deploy`, Gemma serving. D — submit draft, book glasses, polish web, start glasses web app.

## 2026-11-14 00:30 — Claude Code (setup agent) — all (v2 migration, criteria, agent context)
- Did: v2 three-source consensus end to end (contracts v2 + `sources.py`; hub v2 ritual: dial ×3, before/after scores, spoken PHQ-9, phq9_due; glasses + laptop HTTPS twins; cloud consensus v1, live criteria override/preview, simulation with ablation; web /session /phq9 /me /consent /tune). Consensus criteria moved to `config/criteria.toml` (D19) with the first tuning pass (D20). One context file per module: `AGENTS.md` only, READMEs folded in, CLAUDE/GEMINI pointers removed, `.gemini/settings.json` (D21). `modules.toml` + `tools/agents_sync.py` enforce module docs, message flows and criteria producers.
- Verified: `make check` (lint + all Python tests incl. real-broker integration), web typecheck/test/build (13 routes), headless browser runs (web worker), full live run with pairing token on: 8 demo patients in intended states, live v2 ritual, 401 without token, live criteria preview.
- Contract changes: v2 types (see D17), `api.Criteria*`, criteria schema. Still `v: 1` (nothing deployed).
- Broken/blocked: nothing deployed to Modal; Gemini Live / Lyria / vLLM untested against real services; model IDs are `VERIFY-`; real-face expressivity untested; D20 lead-time vs precision trade-off needs a team decision; repo is private.
- Next: A — Atech/UNO Q spikes. B — real Gemini Live + Lyria. C — `modal deploy`, Gemma serving, tune with tester data. D — glasses web app, demo script, submission text (`docs/submission.md`).

## 2026-11-14 08:30 — Claude Code (workstream D) — design
- Did: new `design/` module (plan 02 §2–§3, D22–D23). Ground truth: `tokens.json` (paper/ink/clay/sage/sky/honey, warm-charcoal dark, crisis red only for crisis, glow-by-hour stops, radii, spacing, type Fredoka/Nunito/DM Mono + SF Pro Rounded, motion durations/easings/springs/blink/breath), `mascot.spec.json` (direction A "Pebble": named parts, pivots, clips, 10 states as pose + keyframe tracks + events, interactions, ambient-mood map, robot eye crop), `motion.md`. `gen.py` (stdlib) generates `mascot.svg`, `generated/tokens.css`, `generated/Tokens.swift` (`KaikuTokens`, swiftc-typechecked). `make design`; `design/tests` (freshness, named parts, spec consistency, AA contrast, motion budget) added to pytest testpaths; `modules.toml` + root AGENTS.md ground-truth row.
- Design artifact: https://claude.ai/artifact/BPXa6itqswDUpfzsdRE1MV (3 directions, all states animated from the spec, Reduce Motion toggle, tokens, Today / Weather check / Firefly / Breathe / Your days / Crisis, Dynamic Island + Lock Screen, Mac notch 01:10 + menu bar, receipt, /me, /clinician). Private until shared from its Share menu.
- Verified: `make check` green (220 passed), `gen.py --check` clean, artifact rendered in headless Chrome.
- Contract changes: none.
- Broken/blocked: none. Web/Apple have not adopted the tokens yet (their workstreams).
- Next: W imports `design/generated/tokens.css` + renders `mascot.svg` from the spec; A1 bundles `mascot.spec.json` + `Tokens.swift` in KaikuKit.

## 2026-11-14 — Claude Code (workstream I2) — config + tools (persona + companion evals)
- Did: `config/persona.md` (character bible, hard limits, hand-offs, en/fi/sv notes, 10 good/bad examples tagged with linter codes) and `config/surfaces.toml` (robot/glasses/iphone/mac/web: body, tools, activities, word/sentence caps, proactive limits, rules). `tools/companion_evals/`: `assemble.py` (reference system-instruction builder for the cloud; context card rejects state/score/wearable keys), `wording.py` (stdlib-only linter, incl. team decision "never mention watch/sleep data"), `safety.py` (hub gate duplicate + parity test), `tool_specs.py`, `run.py` (`--dry` canned replies; real mode person/Kaiku = gemini-3.8-flash text stand-in, judge = gemini-4-argon, IDs checked in Gemini docs, overridable by flag/env), 25 scenarios (morning_ritual, weather_check, walk_companion, breathe, look_up/hand-off, watch data, crisis en/fi/sv). `make eval-companion [DRY=1]`. PyYAML added to the root dev group.
- Verified: `make check`; dry run 25/25 pass (persona+<sha8> in scorecard); tests prove the linter flags every Bad persona example and the gate fires before any model call. No real pass yet (no key in this environment).
- Contract changes: none. `tool_specs.py` is a stand-in until `kaiku_contracts/companion_tools.py` (I1) lands; it is preferred automatically.
- Broken/blocked: none. I1 should port `assemble.py` + `wording.py` (copy verbatim to `kaiku_contracts/wording.py`) and keep the card key rules.
- Next: real pass with a key (`make eval-companion ARGS="--limit 5"`), add scenarios for remaining skills, record results in `docs/validation.md`.

## 2026-11-14 10:00 — Claude Code (workstream B) — contracts, cloud, sim, config (plan 02 §10)
- Did: plan-02 contract changes end to end. Contracts: envelope source `phone`; `SelfReport.channel`; `Outing`
  `dat_imu` + `cadence_spm`/`gait_regularity`/`head_up_ratio`; new `obs.screen_activity`, `obs.play_session`,
  `obs.wearable_daily`; 4th consensus source `wearable` + `SOURCE_LABELS` (laptop = "Apps"); `MeResponse.mascot`,
  `highlights`, `garden`; `VoiceLinesResponse`; criteria nested fields + `person_hard`. Cloud: `companion.py`
  (mascot/highlights/garden), `voice.py` + `GET /v1/voice`, `GET /v1/voice/{line_key}` (Gemini TTS
  `gemini-3.8-flash-tts`, voice `Sulafat`, disk cache, 503 + hint without a key), `make voice-prerender`,
  `google-genai` dep, template labels for 4 sources. Config: `[sources.wearable]` + 11 half-weight metrics (D29),
  `config/voice_lines.toml` (33 lines en/fi/sv), `kaiku.toml [voice]` + verified model IDs in `[models]`. Sims:
  laptop twin posts screen_activity + firefly, new `phone_sim` (watch summary, weather check, firefly, `--no-watch`),
  glasses twin posts the extended outing; synth: 4th source, Aino drifts robot+apps+watch with a sub-threshold
  cadence dip, Eero has no watch, 3 new eval scenarios (second RNG keeps plan-01 events/ids identical).
  Tools: `modules.toml [planned_producers]` lets the checker accept obs types whose real producer (apps/apple) is
  still being built; it fails once a real module emits them.
- Verified: `make check` green (lint + 233 tests); `make tune` (D29: needs_call P 0.97 / R 0.90, 0.03 false per
  patient-month, lead 6 d); local cloud + `make seed`: all 8 demo patients in intended states; `/v1/me?home_id=demo-aino`
  → mascot cozy/`needs_call.offer`, good + gentle hard highlights, garden 42 plants; `/v1/voice` 503 + hint without a key.
- Contract changes: additive (see above + `contracts/AGENTS.md`); `SCHEMA_VERSION` unchanged (nothing deployed).
- Broken/blocked: hub (owner B/live) doesn't pass `[voice].name` to Gemini Live yet, so the robot's voice may differ
  from the apps' until it does. `/v1/voice` not yet exercised against the real TTS API (no key here). fi/sv voice lines
  need a native-speaker read. Web `lib/format.ts` still labels `laptop` "Laptop" and has no `wearable` label (W: use
  `SOURCE_LABELS` from `contracts/ts`).
- Next: A1/A2/A3 + W build against these types and the local cloud; remove `[planned_producers]` lines as each real
  producer lands; pre-render voice once a key is set; decide wearable weights with tester data.

## 2026-11-14 10:40 — Claude Code (workstream D) — design (phase 2: full app UI)
- Did: `design/copy.json` (UI copy ground truth, en + fi, same keys), `design/ia.md` (tabs Today · Play · Talk · Your days · You; every screen with components, states, copy keys; onboarding, games, Mac window/menu bar/notch, island/Live Activity/glasses, /me, clinician), `design/layout.md` (overflow rules + stress case). Spec: new `speaking` state; dial map is now 1..5 (matches `SelfReport.value` and persona). Tokens: `crisis-ink` (dark-mode crisis button contrast). Tests: copy tables in sync + no clinical words + crisis contrast.
- Design artifact v2 (same URL): https://claude.ai/artifact/BPXa6itqswDUpfzsdRE1MV. Adds a component library (every state), app map, 27 iPhone screens, playable Firefly + Pebble path + Tell Kaiku (hold to talk), Talk states, a Mac window with a working sidebar, three notch states, a "Stress test" toggle (fi + long name + 1.35× + 320 pt), and a "Show build notes" toggle (off by default). Devices contain only end-user copy. Stress-testing found and fixed: list shrinking instead of scrolling, cramped composer, untranslated weekdays, empty state showing behind content.
- Verified: `make check` green (290 passed), `swiftc -typecheck` on Tokens.swift, headless Chrome render in light/dark/stress, scripted game smoke run.
- Contract changes: none. For B: please add `"pebbles"` to the `play_session` game enum; fields `span_max`, `accuracy`, `duration_s`.
- Broken/blocked: no Swedish UI copy yet.
- Next: A1/W build screens from `design/ia.md` + `copy.json`, check each against the `layout.md` stress case.

## 2026-11-14 — Claude Code (workstream I1, companion mind) — contracts, cloud, sim, tools/companion_evals, docs
- Did: scope-guard steps 2, 3, 7 on the cloud side. Contracts: `companion_tools.py` (12 tools: schema + surfaces +
  executor; `forget` added for "don't remember that"), `wording.py` moved here verbatim from the evals, `safety.py`
  (crisis matcher shared by cloud + evals), companion API models (`ContextCard`, session/tool/episode/memory), export
  of `schemas/companion_tools.json` + TS `COMPANION_TOOLS`; `obs.play_session` game `pebbles` (`span_max`, `accuracy`).
  Cloud `mind/`: `assemble.py` (ported; evals now import it), `card.py`, `memory.py` (FTS5 recall, dedupe, plan expiry,
  routines count rule, one open thread), `session.py`, `live_token.py`. Routes: `POST /v1/companion/session|tool|episode`,
  `GET/DELETE /v1/me/memories[/{id}]`, `PUT /v1/me/memory_settings`. Sim: phone twin plays pebbles; `make seed` gives
  Aino 5 memories, 3 Tuesday walks and an open thread ("the walk by the lake") through the real endpoints.
- Verified: `make check` green; `make smoke` green incl. the new session check (system instruction, tools, rich card,
  no state words) and `/v1/me/memories`. `cloud/tests/test_mind.py`: near-identical edge pairs (remember vs "don't
  remember that", dedupe vs different fact, plan 6 d vs 8 d, thread robot→glasses vs closed/expired, Tuesday×3 vs
  Tuesday×2 + Monday, crisis phrase vs "dye my hair", allowed vs refused categories / health texts, remember_off,
  Finnish with and without diacritics), tone per state incl. insufficient/low_coverage, card property test over all 8
  seeded patients × 5 surfaces, clinician routes never contain memories, live token mocked.
- Contract changes: additive only (new module + API models + `pebbles`); `SCHEMA_VERSION` unchanged.
- Broken/blocked: config (owner all): `config/surfaces.toml` tool lists don't name `forget` yet and its header +
  `config/persona.md` still point at `tools/companion_evals/{assemble,wording}.py` (now `kaiku_cloud/mind/assemble.py`,
  `kaiku_contracts/wording.py`). Ephemeral token not exercised against the real API (no key here) — null on failure.
- Next (hub / apps): call `POST /v1/companion/session` before Live; use `live_token.token` as the Live API key
  (v1beta) when present, else own fallback; forward `executor: cloud` tool calls to `/v1/companion/tool` with the
  `session_id`; on `crisis: true` stop Live and play `result.script`; post `/v1/companion/episode` for offline sessions.

## 2026-11-14 — Claude Code (workstream I3) — hub, sim, config [attention] (robot: see → greet → talk)
- Did: plan 04 build steps 1–2. `hub/kaiku_hub/attention.py`: pure attention ladder nobody → appeared → approaching →
  at_desk → glance (eyes) → purr → keyed greeting by time of day (`greet.*`) → ritual offer; head pan toward the face
  (EMA + deadband + ≤ 5 Hz), eyes `look`; cooldowns in new `config/kaiku.toml [attention]` (re-greet 3 h, night
  23:00–07:00, "not now" quiet 2 h, two faces → `greet.two` with no offer, done today → no offer, flicker < 2 s).
  Face sources: `laptop` (existing OpenCV tracker, now one message per face) or `unoq_yolo`
  (`devices/unoq_yolo.py`: consumes UNO Q `raw.hub.face` boxes, `camera_enable`, `box_to_face`; interface in
  `hub/AGENTS.md`). `live/lines.py`: keyed lines from `GET /v1/voice/{key}` with `say`/text fallback. GREET offers
  instead of greeting twice; "no"/"not now" ends the ritual. Gemini Live: `gemini-3.8-live`, `[voice].name`,
  v1beta, `enable_affective_dialog`, `proactivity.proactive_audio` (checked in geminiDocs + validated against
  installed google-genai 3.3.0 types); one session per ritual, instruction/tools from `POST /v1/companion/session`
  with fallback to local `tools.py`; 4 s stall → scripted line locally. Sim: sensors twin publishes face boxes that
  grow on approach (`--two`, key `2`).
- Verified: `make check` green. End to end on an isolated broker/cloud (seeded): sim person walks up → `attention`
  nobody→appeared→approaching→at_desk, `cmd.head` eyes wide → purr → pan 13.9°→9.1° + look tracking → greeting
  (cloud voice 503 without key → text fallback) → `ritual_start attention` → offer → full ritual completed, obs
  uplinked, no errors. Real clock was 23:20 → default config correctly only glanced/tracked; `--two` → "te kaksi",
  no offer. No real Live smoke: no GEMINI_API_KEY here.
- Contract changes: none.
- Broken/blocked: config owner — add `[greet.two]` (en/fi/sv) to `config/voice_lines.toml` (hub uses a built-in
  fallback until then). Contracts — `HeadCmd` has no ear command ("ear up" = `eyes: listening` for now). A — UNO Q
  App Lab YOLO publisher per `devices/unoq_yolo.py`; pan sign convention. I1 — hub expects
  `POST /v1/companion/session` → `{system_instruction, tools?, model?, voice?, persona_version?}`.
- Next: real Live smoke with a key; MediaPipe face detector for the laptop path; body sync while speaking.

## 2026-11-14 — Claude Code (workstream W) — web [person + clinician dashboards on the design system]
- Did: `apps/web` adopts `design/`: `design/generated/tokens.css` imported (not copied) + Fredoka/Nunito/DM Mono; legacy
  CSS names mapped onto `--k-*`; new `app/kaiku.css` (look book components, em sizing with `--ts`). `<Mascot>` renders
  `design/mascot.spec.json` directly (all 11 states, blink modes, yawn event, tap ear flick, glow by hour from tokens,
  Reduce Motion). Person copy via `useCopy()` from `design/copy.json` (+ `lib/copy-web.json` for missing keys), en/fi.
  `/me` redesigned per `design/ia.md` + look book (ambient mascot from `/v1/me` mood, `crisis` → crisis screen, weather
  check → `obs.self_report` channel web, good & hard moments, garden, pairing QR + link, suggestion, what helps, What
  Kaiku remembers with delete one/all + remembering switch, What Kaiku saw today receipt, PHQ-9 card). New
  `/play/firefly/` (go/no-go, jar ending, `obs.play_session` firefly/web). Clinician list + patient view rebuilt (consensus
  chip wording, 4 source cards with sparklines, "No watch connected", evidence table, summary "not a decision",
  timeline grid, PHQ-9, actions; no memories). Nav: For you · Clinician · small Team menu (/live, /health, /eval, /tune).
- Verified: Playwright matrix /me, /clinician, /clinician/patient/?id=demo-aino, /play/firefly at 320/390/768/1280 ×
  light/dark × en/fi × 1.0/1.35 text against `make cloud-local` + seed: no horizontal page scroll or clipped text
  (fixed: "English" segment breaking mid-word, cramped evidence table → full-width row, side-tab borders removed).
  Weather check, memory delete/switch, I'm not OK and a full firefly round posted to the local cloud. `pnpm typecheck`,
  `pnpm test` (21), `pnpm build`, `ui_copy_check`, `make check` (410), `make smoke` green.
- Contract changes: none. `modules.toml` web: emits + memories endpoints; removed the `obs.play_session` planned producer.
- Broken/blocked: design (D) — move `apps/web/lib/copy-web.json` keys into `design/copy.json`. Cloud (C) — highlights /
  what-helps / suggestion reasons are English only; per-signal pause for the receipt has no endpoint.

## 2026-11-14 — Claude Code (workstream A1, Apple core) — apps/apple (+ modules.toml entry)
- Did: `apps/apple/` XcodeGen project (`Kaiku iOS` 17+, `Kaiku Mac` 14+, `Kaiku iOS UITests`) around the shared
  package `KaikuKit`: contracts mirror, async API client (timeouts, retry/backoff), offline queue on disk (UUIDv7 ids,
  idempotent), pairing (`?home=&t=` link, QR on iPhone, paste on Mac, Keychain), local safety gate (port of
  `kaiku_contracts.safety`), Canvas mascot drawn from `mascot.spec.json` (all 11 states, blink schedule, yawn, tap
  ear flick, dial ear, cursor look on Mac, time-of-day glow, Reduce Motion poses), component library, crisis screen,
  onboarding, tabs Today · Play · Talk · Your days · You per `design/ia.md` (Mac: sidebar window + menu bar popover).
  Games: Firefly (go/no-go 60 s), Pebble path (Corsi, 2 misses), Breathe (6/min), Tell Kaiku (energy VAD speech
  rate + pause ratio, no audio kept). Talk: companion session → Gemini Live WebSocket with the ephemeral token
  (protocol from geminiDocs) or, with no token, an honest offline card + typed path with scripted lines.
  Emits `obs.self_report` (channel phone|mac), `obs.play_session`, `obs.safety_flag`. Removed `obs.play_session`
  from `[planned_producers]`.
- Verified: `swift test` (25 tests incl. `safety_cases.json` parity, contract shapes vs schemas, copy keys en+fi),
  both targets build, `make check` green. UITests against a seeded local cloud: weather check → 3 `obs.self_report`
  `channel: phone`, pebbles → `obs.play_session`, memories list loads; Today shows "…, Aino" with the cozy mascot.
  Screenshots on iPhone SE (3rd gen) + 16 Pro Max, en + fi, default / XXXL / AX-XL, long name: fixed mid-word breaks,
  header/back overflow, Talk and game screens overflowing at large text, onboarding Help overlap.
- Contract changes: none.
- Broken/blocked: design (D) — please upstream `apps/apple/KaikuKit/Sources/KaikuKit/Resources/copy.apple.json`
  (~50 keys copy.json lacks) into `design/copy.json`. Cloud (C) — `/v1/me` highlights are English-only. No contract
  for good/hard day marks (kept on device). Live not exercised against the real API (no key).
- Next: A2 (Live Activity, HealthKit, glasses, light hunt), A3 (notch island, usage sampler); real Live smoke.

## 2026-11-14 01:30 — Claude Code — hardware (A)
- Did: downloaded the datasheets for UNO Q, Arduino USB Camera TPX00246 and Modulino Buzzer ABX00108, plus the chip datasheet for each Atech module, into `hardware/datasheets/` (now gitignored; `SOURCES.md` inside lists the URLs). Added `hardware/dimensions.md`, the single file for part dimensions, with photo estimates (±5 %) for the Atech motherboard (~127 × 68), the DC motor (~23 × 23 × 44, 3 mm shaft) and the module cubes (~22 mm).
- Verified: every PDF opens and has the right title or page count.
- Contract changes: none
- Broken/blocked: Atech publishes no mechanical dimensions, so the Atech rows are photo estimates or MEASURE. The TPX00246 camera has a USB-A plug, so the UNO Q needs a USB-C hub or adapter. Atech's IMU module ID is `icm40608_imu`, but its docs name the chip as the LSM6DSOX.
- Next: A — measure the Atech modules and the UNO Q stack height with calipers, then fill in dimensions.md before modelling the shell.

## 2026-11-14 04:30 — Claude Code — hardware (A)
- Did: robot CAD around the real hardware, all generated by `hardware/cad/kaiku_cad.py` (build123d, uv inline
  script). The "cathedral radio" head is built around the Arduino USB Camera, with the display eyes and knob ear.
  The neck is a pan base + 40:12 ring gear + hall homing. The body holds the UNO Q, Atech board, LED grids,
  speaker and purr motor. Two motors (pan, purr): D30. Added `render.py` (Blender), `slice.py` (Bambu Studio
  CLI, P1S + P2S, picks the fastest preset per plate), `cardboard.py` (template + cut list) and `overview.py`
  (local `out/overview.html`). Docs: `hardware/cad/README.md` (design, print plan, provenance) and
  `hardware/assembly.md` (build steps, 12-port budget). Updated bom/wiring/dimensions. `hardware/cad/out/` is
  gitignored.
- Verified: fit check reports no clashes between any printed part and any bought-in envelope. All print STLs
  are watertight. Sliced: MVP 3 h 23 min (P1S) / 3 h 19 min (P2S), full printed robot 5 h 55 min / 5 h 47 min,
  every plate single-colour with no supports. `ruff check` is clean.
- Contract changes: none
- Broken/blocked: the knob, IMU and button module sizes are ASSUMED (`dimensions.md`); the display is a photo
  estimate (42 × 21 × 10, head raised to 134 mm for its cable plugs). The motor D-shaft is unverified. The 12 Atech ports fit Microphone *or* Speaker,
  not both.
- Next: A — measure the ASSUMED modules, print plate 2 (neck) and bench-test the pan, then the head; cut the
  cardboard body.

## 2026-11-14 06:00 — Claude Code — hardware (A) + docs
- Did: reconciled `docs/kaiku_robot_electronics_specs.md` with the printed CAD (D23). Both boards are in the body;
  the camera, display, knob, mic and KY-031 are in the head. The eyes are the Atech display and the dial is the
  Knob. KY-039/053/054/035 kept; all 12 Atech ports allocated, so there is 1 motor (pan) and no IMU. Added the
  Modulino Buzzer and KY-031 to the CAD fit check, and the PD hub (external) to the BOM/wiring. Updated
  `assembly.md`, `bom.md`, `wiring.md` and the CAD README.
- Verified: fit check clean; all 19 printed STLs unchanged (nothing to reprint).
- Contract changes: none (the spec's MQTT topics still need mapping onto `contracts/`).
- Broken/blocked: `firmware/atech-head/AGENTS.md` (IMU taps, purr) and handoff §8 now disagree with D23. Hub
  location (UNO Q in the spec, laptop in handoff §5.1) is undecided. Owners: A for firmware, B for hub.
- Next: A — flash the Atech port plan; B — decide the hub location and map the spec's topics onto `contracts/`.

## 2026-11-14 — Claude Code — contracts, hub, sim, tools, firmware/atech-head, firmware/unoq-sensors, hardware, docs [robot electronics, plan 06]
- Did: Xavier's electronics spec mapped onto our layers → `docs/plans/06-robot-electronics.md` + **D31** (supersedes
  D30's electronics; hub + broker stay on the laptop, voice on the laptop in v1, 2 s long press stays safety, name
  `unoq-sensors` kept; UNO Q hub/broker and head audio over MQTT kept open in plan 06 §4). Contracts (additive):
  `raw.head.button`, `cmd.head.gesture`, `cmd.sensors.chime`, optional `raw.head.tap.force` / `drum_session.force_mean`.
  Hub: head button = same handling as the top button + `perception/presses.py` (1–5 presses = one dial answer),
  button-build prompts, chimes, `drum_sway`, knock taps without force; `config/kaiku.toml [robot]` + `[unoq]`.
  Firmware: `atech-head` (`project.yaml` + `kaiku_link/` C++: Wi-Fi/MQTT envelope + UUIDv7 + NTP, button, open-loop
  pan motor with ramp/home/gestures, purr, hub-silence watchdog). `unoq-sensors` sketch (eyes, buzzer, knock,
  **KY-039 at 100 Hz**) + Python app (Bridge ↔ Bus, camera faces/distance/light, **camera pulse as KY-039 backup**,
  `ppg_source = auto|ky039|camera`). **Bench tests:** `tools/bench.py` + `firmware/*/bench/<part>/` for every part
  (matrix, buzzer, knock, ky039, camera, button, motor, speaker, mic) + one MQTT link bench per board;
  `make bench-list`, `make bench PART=... FROM=...`, `make unoq-app`. Sims: head_sim `dial="button"` (presses +
  knocks), key `b`. Docs: wiring.md, bom.md, privacy.md, module AGENTS.md ×2, hub/sim/tools/contracts/hardware docs.
- Verified: `make check` green (448). End to end on a throwaway broker (hub + head/sensors sims, button build): greet →
  dial by presses (3/2/2) → HRV → knock drum (`force_mean` null) → post-drum mood → nudge → close, no errors.
  Bench checker tested on saved logs (knock pass / bounce fail, KY-039 pass / flat fail).
- Contract changes: additive, `SCHEMA_VERSION` 1; `make contracts` run.
- Broken/blocked: **nothing compiled for the boards** (no Atech/App Lab toolchain here): every `VERIFY` in both
  firmware AGENTS.md "Known issues" needs a first build. A (hardware) — `hardware/assembly.md` + `cad/` still
  describe D30's Color Display / Knob / LED grids; the eyes are now the UNO Q matrix. D (web) — drum detail prints
  `force —` when `force_mean` is null; consider hiding it. Config — `config/voice_lines.toml` has no button-build
  dial lines (hub uses built-in strings in `rituals/steps.py`).
- Next: A — network spike (plan 06 §2.1), then single-part benches on the real boards, then the link benches.

## 2026-11-14 — Claude Code — contracts, hub, sim, firmware/*, hardware, docs [electronics reconciled with Edwin's printed design]
- Did: embedded Edwin's reconciliation of Xavier's spec (`docs/kaiku_robot_electronics_specs.md`, from `main` 503d96e)
  into this branch. His decision becomes **D31** here (it was D23 on `main`); the software mapping is **D32**, which
  replaces the earlier-session "D31". The plan moved to **`docs/plans/07-robot-electronics.md`** (06 is the
  Gemini-first mind), and the previous entry's "plan 06 / D31" now mean plan 07 / D32. The retired copy is
  `docs/Kaiku robot electronics spec.md`. Hardware: the Atech board drives the display eyes, Knob dial
  (`raw.head.ear`), lid button, LED grids (chest), pan motor homed on the KY-035 (it subscribes to `raw.sensors.hall`)
  and speaker. The UNO Q sketch reads the knock, hall (A1, analog), KY-054 light and KY-039 via the KY-053 ADS1115
  (raw I2C), plays the buzzer, and drives a status matrix; the Python app publishes hall/light. Contracts: gesture
  `look_left|look_right|shake`. Hub: `[attention] camera_on_head` (camera pans with the head), `dial_input = "ear"`,
  `drum_input` for the sims. Benches: + display, knob, leds, hall, light; ky039 via ADS1115; matrix bench removed.
  Edwin's `assembly.md`, `cad/README.md` and `kaiku_cad.py` were merged in; wiring.md and bom.md were rewritten from
  his pins/parts plus the bench checks.
- Verified: `make check` green (449). Sims unchanged in behaviour; bench checker tests updated.
- Contract changes: additive, `SCHEMA_VERSION` 1.
- Broken/blocked: nothing compiled for the boards (VERIFY lists in both firmware AGENTS.md). A — the KY-035 is on A1 (analog);
  the spec said D3: confirm with `bench/hall`. Pan sign and knob counts per click are open.
- Next: A — network spike, then the single-part benches, then the link benches (plan 07 §2).

## 2026-11-14 05:00 — Claude Code — hub (B) · I5 live context + thinking body
- Did: plan 06 §4 (T5) on the robot. `hub/kaiku_hub/live/context_events.py` has a fixed vocabulary
  (`[drumming · lively|steady|gentle]` relative to this ritual's first taps, `[breathing · heart calmer]`,
  `[second person nearby]`, `[person stepped away]`, `[light · dim|bright]`, `[it's late]`). Events are ≥ 20 s
  apart, ≤ 8 per ritual and deduped; with no session they are dropped. Added `Voice.send_context`: Gemini Live uses
  `send_client_content` mid-session (checked in the geminiDocs Live capabilities guide), text mode prints it, off
  does nothing. Every `executor: cloud` tool (so `ask_mind` once it is in the registry) now runs with
  `eyes: thinking` + an upward glance and restores the eyes afterwards, but not after a crisis. After 8 s it says
  "Let me think about that later." and the ritual goes on. The sim head now speeds up its drumming over the step,
  and in the sim the heart rate drops about 4 bpm during breathing. Spend cap: `live/meter.py` meters Gemini Live
  and Lyria RealTime on the shared `budget` ledger. Before opening it checks the cost of 5 minutes, then it charges
  each started minute. Over the cap it doesn't open (or closes politely) and the ritual falls back to scripted lines
  / the local click.
- Verified: `hub/tests/test_context_events.py` (19 s vs 20 s, 9th dropped, no-session no-op, digit/state-word
  property test, thinking set/cleared incl. timeout + crisis). `make check` green. Hub + sims + `KAIKU_VOICE=text`:
  `[it's late]`, `[light · dim]`, `[drumming · steady]` then `[drumming · lively]` in the log. In one run
  `[breathing · heart calmer]` was dropped by the 20 s gap after the light event, so light events now fire only
  during greet/dial. `hub/tests/test_budget.py` uses a temp `KAIKU_SPEND_DB`.
- Contract changes: none (the `ask_mind` registry entry comes from I4/contracts).
- Broken/blocked: config (all) — the context thresholds (lux, late hours, drum ±15 %, 20 s / 8) are constants in
  `context_events.py`; they could move to `config/kaiku.toml`. The hub passes `timeout_s` to
  `CloudLink.companion_tool` (9 s), so a slow cloud tool now waits up to 8 s instead of 4 s.
- Next: a real Live smoke test of `send_context` with a key; port the same vocabulary to the iPhone/glasses.

## 2026-11-14 06:00 — Claude Code — cloud (C) · workstream I4 (plan 06 §1–§3, Gemini-first mind)
- Did: `ask_mind(question, kind)` tool (registry, executor cloud, all surfaces) → `mind/router.py`: memory/graph/today
  answered by code → Gemini 3.8 Flash JSON {answer, confidence, cites} → Gemini 4 Argon on low confidence / care /
  emotional / conflicting notes / Flash failure; Argon capped per home per day (`[budget].argon_per_home_day`).
  Grounding: cite ids verified + stripped, wording linted, conflicts must ask; scripted fallback. Usage ledger
  `model_calls` (no content) + `GET /v1/health/intelligence`. Graph memory `kg_nodes/kg_edges` (memories, episodes,
  bandit `helped` edges with effect + event ids), Gemini Embedding 2 vectors (on write + nightly backfill, FTS fallback),
  1-hop recall used by the context card and ask_mind, `GET /v1/me/constellation`. `POST /v1/admin/nightly-mind`
  (rebuild, backfill, validated consolidation diffs, pre-render list), `POST /v1/admin/weekly` + `GET
  /v1/patients/{id}/brief` (Argon, metric-id grounded, template fallback). Walk postcard `POST /v1/companion/postcard`
  + `GET /v1/me/postcards/{id}` (Nano Banana 2 Lite `gemini-3.1-flash-lite-image`, cached; 503 + hint otherwise).
  Every new paid call goes through `kaiku_contracts.budget` (rebased onto d2ec847). Modal: nightly also calls
  nightly-mind, new Monday `weekly` cron, postcards + spend ledger on the Volume.
- Verified: 34 new edge-case tests (`cloud/tests/test_mind_router.py`, SDK client mocked, temp spend DB); `make check`
  465 passed; `make smoke` green incl. ask_mind memory route, /v1/health/intelligence, constellation. API shapes checked
  in the geminiDocs MCP (Interactions `response_format` text/JSON + image, `output_image`; `models.embed_content` with
  `gemini-embedding-2` + task prefixes).
- Contract changes: tool `ask_mind`; API `MindAnswer`, `ModelUsageRow`, `IntelligenceHealth`, `Constellation*`,
  `PostcardRequest/Response`, `BriefSection`, `ClinicianBrief` (additive, no SCHEMA_VERSION bump). `make contracts` run.
- Broken/blocked: no GEMINI_API_KEY in this env → no real call made on any new path (Flash/Argon JSON, Embedding 2,
  image). Argon eval-judge sample not run in the cloud (tools/ not importable by cloud; use `make eval-companion`).
  `config/surfaces.toml` + `persona.md` don't mention `ask_mind` yet (owner: add "ask_mind when unsure"). Hub (I5) and
  apps: forward `ask_mind` like other cloud tools, show "thinking" while in flight, speak `result.answer`, ask the
  person when `ask_person`; apps: constellation view, postcard after walks, Intelligence card on /health.
- Next: one real call per new model path once a key is available; web panels.

## 2026-11-14 01:00 — Claude Code — apple (A3, Mac extras)
- Did: notch island (borderless panel above the menu bar, top centre of the active screen, notch and non-notch;
  hidden/click-through → peek → expanded; soft springs, Reduce Motion crossfade). After lead feedback Kaiku is big
  (136/156 pt), hangs half out of the island, and the sleepy z's draw light on black so they read at 1×
  (`design/layout.md` + `motion.md` → Mac notch island). Deterministic peek rules in `KaikuKit/Mac/MacPeek.swift`
  (late night 01:00–05:00 + active, stretch > 90 min, max 3/day, one late peek a night, snooze 1 h/today as
  wall-clock dates, never paused/full-screen/call app). Usage-rhythm sampler (D26, opt-in): frontmost bundle id →
  category on the spot + idle seconds + switch count every 30 s → local aggregate → hourly `obs.screen_activity`
  via the offline queue; "What Kaiku saw today" reads the same aggregate. Daily invitation notification outside
  quiet hours. Debug "Simulate a late evening" (+ `-kaikuSimulateLate YES`) for the 01:10 peek any time.
  modules.toml: apple emits `obs.screen_activity` (planned producer removed).
- Verified: `swift test` 40/40 (15 new: aggregation, payload = numbers + category keys only, 00:59/01:00, 89/91 min,
  4th peek, snooze across sleep/wake, paused); Mac target builds; against a local cloud + seed (demo-aino) the
  simulated evening peeked and `obs.screen_activity` (source laptop, sim, late_night_min 60) landed in
  `/v1/events`; island checked via in-app snapshot at 1× and 2× (screen capture not permitted here).
  `make check` green, `tools/ui_copy_check.py` clean.
- Contract changes: none
- Broken/blocked: design (D) — upstream the new `mac.*`/`saw.mac.*` keys in `copy.apple.json`; config — no
  `voice_lines.toml` key for the stretch line yet. A2 — swap `DailyInvitation` for the shared scheduler when it lands.
- Next: nudge peek + breathing slim state on the island; real screen capture of the island on a notch Mac.

## 2026-11-14 01:50 — Claude Code — apple (A3, notch island as part of the menu bar)
- Did: after user feedback ("overlaps menu bar items") rebuilt the island the way notch apps do it: pure
  `MacIslandGeometry` (notch from auxiliaryTopLeft/RightArea + safeAreaInsets.top on the notch screen, else main);
  a collapsed strip at level 26, exactly menu-bar tall, notch + ≤ 60 pt wings (glyphs only while Kaiku is out,
  mouse-through except the notch hover zone, click → hello); peek/expanded in a level-25 panel that grows
  downward below the menu bar (pill under the menu bar on non-notch screens), shadow only when expanded.
- Verified: on this MacBook (1512 × 982, notch 665…850) CGWindowList shows the strip at (605, 0, 305, 32),
  layer 26, and the drop panel at y ≥ 32, so nothing covers menu titles (end < 605) or status items (start > 910);
  menu-bar slice snapshots (collapsed/peek/expanded, 1× + 2×) read; a sim `obs.screen_activity` landed again.
  `swift test` 44/44 (+4 geometry tests), `make check` green, ui copy clean.
- Contract changes: none
- Broken/blocked: screencapture is not permitted in this session, so the island is checked by in-app snapshot.
- Next: nudge peek + breathing slim state; a live check on a second (external) display.

## 2026-11-14 02:20 — Claude Code — apple (A3, one-shape notch island)
- Did: after two more rounds of user feedback ("the avatar drops below the thing", "not an island, there's a gap")
  the island is ONE level-26 window from the top of the screen drawing ONE `MacIslandShape`: the menu-bar band is
  never wider than notch ± 60 pt wings, concave shoulders flare into a compact body (440 × 172 / 460 × 188 content)
  below the menu bar, one spring morphs collapsed → peek → expanded, pure black, shadow under the bottom only.
  Kaiku (124/128 pt) and its z's sit inside the body, content clipped to the shape; mouse-through except inside
  the drawn shape. Pure `MacIslandGeometry` / `MacIslandShape` / `MacIslandLayout` in KaikuKit.
- Verified: `swift test` 49/49 (shape: band width == collapsed width at every menu-bar row, body width, shoulder
  > 0; mascot + z's inside the content rect at 1×/2×; geometry for notch / non-notch / external screens).
  CGWindowList on this MacBook: island window (500, 0, 516, 266), layer 26, top at y = 0, centred on the notch
  (665…850); band 605…910 so titles (< 605) and status items (> 910) are clear. In-app snapshots of collapsed,
  mid-morph, peek and expanded at 1× and 2× read; a sim `obs.screen_activity` landed.
- Contract changes: none
- Broken/blocked: screencapture not permitted in this session (in-app snapshots instead).
- Next: nudge peek + breathing slim state; check on an external display live.

## 2026-11-14 01:20 — Claude Code — apple (A2 iPhone extras + glasses)
- Did: plan 05 MUST items in `apps/apple/`. Deterministic `NudgeScheduler` (quiet hours, windows, one
  invitation/day, Later once, done on any surface, PHQ-9 once, DST/timezone-safe ids) + `Notifier` (categories
  Let's go · Later · Not today / Good · Okay · Low, voice-line titles, mascot attachment, chime, ignored after 4 h)
  + `kaiku://` deep links. Voice: prefetched `/v1/voice` cache with AVSpeechSynthesizer fallback, Talk audio session
  with Bluetooth HFP, interruption/route handling, reconnect, on-device Speech safety gate + spoken dial parser
  (en/fi/sv). Walk (Light hunt) with `GlassesAdapter` (`MockGlasses`, `DATGlasses` on MWDAT 1.0.1 via SPM), gait
  analyzer → `obs.outing{method: dat_imu}`, draft recovery after a kill. Widget extension: Walk + Breathe Live
  Activities (Dynamic Island + Lock Screen, bigger Kaiku + `KaikuGlyph` for compact/minimal per lead feedback) and
  the Kaiku widget (small/medium/lock). App Intents + App Shortcuts. HealthKit → `obs.wearable_daily` (idempotent id).
- Verified: `swift test` 46/46; iOS + Mac builds green; `ExtrasFlowTests` on the iPhone 17 Pro simulator against a
  seeded local cloud: real compact + expanded Dynamic Island and Lock Screen Live Activity screenshots, notification
  Low → `obs.self_report{value: 2, channel: phone}`, Not today → `obs.nudge_outcome{accepted: false}`, mock-glasses
  walk → `obs.outing{dat_imu, cadence 108, regularity 0.97, head_up 0.89}`, Health sample →
  `obs.wearable_daily{2026-11-14}` (second sync = same id, one row). Surface snapshots at 375/440 pt, en + fi, no
  overflow (Lock Screen title truncates in fi, as design allows). `ui_copy_check` clean.
- Contract changes: none (producers only). modules.toml: apple emits obs.outing, obs.wearable_daily,
  obs.nudge_outcome; `obs.wearable_daily` removed from planned producers.
- Broken/blocked: DAT with Mock Device Kit → `createSession` = `noEligibleDevice` in the simulator (walk falls back
  to the phone); not tried on real glasses. iOS deployment raised to 17.2 (MWDAT binaries). Design (D): ~40 more
  keys in `copy.apple.json` to upstream (notif.*, walk.*, la.*, widget.*); `KaikuGlyph` sizes live in
  `SurfaceViews.swift` (`SurfaceSize`), not tokens — move to `design/layout.md` if you want them as ground truth.
- Next: DAT on real Ray-Ban Display (Developer Mode registration), camera brightness → daylight, interactive mood
  widget (STRETCH), notification content extension (STRETCH).

## 2026-11-14 02:40 — Claude Code — apple + design (UX polish of the main window, tabs and games)
- Audit (before; iPhone 16 Pro + SE sims, Mac via ImageRenderer at 980×720 and 720×480): header wasted a row
  (pill above the title); Play, Your days, You and the weather check needed scrolling on a 16 Pro (Done button and
  last rows below the tab bar); Mac panes were one 680 pt column with a tiny Kaiku and an empty right half; icon
  tiles used `tint.opacity(0.14)` instead of the soft tokens and the weather icon was honey not sky; no surface
  depth (flat cards, flat bg); Firefly was a grey-blue box with a beige moth and no feedback at all on a catch;
  Pebble path was flat ellipses on sky-soft with no right/wrong feedback; games kept the tab bar, had no "how to
  play" demo; no hover/pointer states or keyboard in games on Mac; no sounds.
- Did: tokens: game scene colours (`night-a/b`, `night-ink`, `firefly`, `moth`, `pond-a/b`, `pebble`,
  `pebble-edge`, from the look book) in `design/tokens.json` (+ gen + sync). Components: `KTone` soft fills for
  icon tiles/tinted cards, `KPressStyle` (0.98 press, hover shade, pointing hand), KButton press 0.97 + hover +
  lifted primary, `KBackdrop` (paper + time-of-day glow wash), `MascotHalo`/`GlowingMascot`, `KAdaptiveColumns`
  (two columns ≥ 600 pt), compact `ScreenHeader` (title + pill one row; round back button, Esc), scroll only when
  needed (`scrollBounceBehavior(.basedOnSize)`), new `WeatherDial` (value chip, tick marks, grip knob, open hand,
  ←/→, tick sound). Screens: Today (glowing Kaiku + bubble, sky/sage rows, look-book garden), Play (illustrated game
  tiles, minutes chips, 2×2 on Mac), Weather check, Your days, You (+ "Little sounds" switch), Talk halo,
  onboarding backdrop. Games: `GameShell` = scene + top bar (tab bar hidden) → intro with a looping demo → play →
  warm end. Firefly: night scene, catch burst + flight into a live jar + chime + haptic, moth wobble + puff,
  missed trail, Space. Pebble path: pond, lumpy pebbles with press/glow/ripple/shake, Kaiku hops in arcs, rising
  pentatonic notes, 1–9/arrows. Breathe: glow pool, phase countdown ring + seconds, breath dots, soft tones. Tell
  Kaiku: tap-to-start/tap-to-stop (hold still works), mic-level halo, 30 s ring, Space. `KSound`: synthesised soft
  tones (no assets), ambient session, You switch. Reduce Motion fallbacks for all of it. Docs: `design/layout.md`
  (one-viewport rule, colour roles), `design/motion.md` (direct-feedback exception, game feedback table, RM), apple
  AGENTS.md. Mac `-kaikuSnapshotSize` / `-kaikuSnapshotPair` (in-memory pairing, no Keychain).
- Verified (after, same sizes): every tab, the weather check and every game fit one viewport on the 16 Pro and at
  980×720 on Mac; SE and the 720×480 window fall back to scrolling. `swift test` 70 green, both builds green,
  `ui_copy_check` clean, `make check` 509 passed, iOS UI tests 5/5 (incl. pebbles + weather + A2 extras).
- Contract changes: none.
- Broken/blocked: design (D) — upstream `tell.tap/start/done`, `you.sounds(.d)`, `you.unpair.short` from
  `copy.apple.json`. Mac snapshots draw the sidebar themselves and can't render toggles/text fields; the 720×480
  static render clips the header (real window scrolls). Menu bar popover / island untouched (owned by A3).
- Next: real-device pass on haptics + sound levels; iPhone tilt → eyes.

## 2026-11-14 03:45 — Claude Code — demo capture (robot sim replay + web recordings)
- Did: `scripts/record_robot_demo.sh` records one key-less end-to-end sim run (own broker/cloud on free ports, temp
  DB, seeded cohort, head/sensors twins driven by `scripts/robot_demo_driver.py`, hub in text voice, glasses/laptop/
  Mac/phone posts) to `demo/recordings/robot-sim/` (bus JSONL, stamped hub log, markers, cloud responses).
  `scripts/record_web_demo.sh` records /me, /clinician, the patient view and /play/firefly as MP4s (Playwright 1.58.0).
  `demo/recordings/` is gitignored; how to regenerate is in `demo/AGENTS.md`. A progress page (claude.ai artifact)
  replays the run (pan, eyes, knocks, button dial, chest breathing + pulse, lines, context chips) next to the cloud
  results and a plan 01–07 status table.
- Fixed (hub, owner B please review): with the current knock build (`drum_input = knock`, no `force`) every
  `raw.head.tap` during DRUM raised `TypeError` in `Hub.on_raw` (`float(None)`), so `[drumming · …]` never reached
  Live. `DrumFeel.add` now takes `force=None` and uses tempo alone; test `test_drum_feel_knock_switch_has_no_force`.
- Verified: full ritual completed (greet → dial ×3 by button presses → breathe 60 s → drum 42 knocks → suggestion →
  close); context events `[it's late]`, `[light · dim]`, `[breathing · heart calmer]`, `[drumming · lively]`; Aino's
  consensus `needs_call` with 4 sources; context card has no state words; `ask_mind` memory route in the ledger.
- Contract changes: none
- Broken/blocked: text voice opens no Live session, so no model tool calls happen in the hub (the script calls
  `ask_mind` itself). In a shorter run (breathe 40 s) the heart-rate delta was +0.1 bpm and no `heart calmer` event
  fired, yet the scripted line still said "Your heart settled nicely" (the line doesn't follow the same rule).
  Recorded at night, so the greeting is the Finnish night line. The firefly flow must not click the first button
  ("I'm not OK" is first).
- Next: upload the app recordings into the page's video slots.

## 2026-11-14 02:30 — Claude Code — apple (conversation pipeline: real-time talk through Meta glasses)
- Did: one conversation engine for every Apple surface (`Talk/Conversation.swift`): cloud bootstrap
  (`POST /v1/companion/session`) → Gemini Live with **server VAD + barge-in** (`START_OF_ACTIVITY_INTERRUPTS`;
  `interrupted` flushes Kaiku's queued voice at once), affective dialog, proactive audio, sliding context
  compression, session resumption (reconnect on `goAway`/drop with the handle; same token until it expires, then a
  fresh one), `ask_mind` as a `NON_BLOCKING` tool (`WHEN_IDLE`), safety gate on every transcript + on-device
  listener. `LiveSession` is now the pure protocol layer (setup builder + parser, unit-tested);
  `ConversationAudio` puts mic + playback on one voice-processing engine (echo cancel) and prefers the glasses'
  HFP mic. Talk = open conversation (tap Kaiku to stop/start listening), no more hold-to-talk. The walk opens a
  live companion on the `glasses` surface (walking persona, `log_walk_moment` → Found one) and feeds it context
  events (`[found one · 2 of 3]`, `[walk · 10 min]`, glasses lost); "Quiet walk" toggle. Field names checked in
  the Gemini docs + installed SDK converters; Meta audio path per the DAT "Microphones and speakers" guide.
- Verified: `swift test` 80/80 (10 new in `LiveSessionTests`); iOS simulator, iOS device (MWDAT linked) and Mac
  builds green. Local cloud (key-less): `{surface: glasses, intent: walk}` session for demo-aino returns the
  walking persona, 11 tools and graph memories in the card; `ask_mind` "Where does Aino like to walk?" → route
  memory, cite `mem:3`; care question → "ask your care team"; `recall rain` → the seeded memory.
- Contract changes: none.
- Broken/blocked: **not yet run against real Gemini Live or real glasses** (no key in `.env`). VAD tuning is in
  `LiveSession.Tuning` (code) until a session-response field carries it (contracts owner). `look_at_this` says the
  camera isn't connected (DAT camera stream not wired). The Display web app has no mic, so it is not in the
  speech path.
- Next: paste `GEMINI_API_KEY`, run on an iPhone with Ray-Ban Meta connected, tune VAD on a real walk.

## 2026-11-14 02:45 — Claude Code — apple + cloud (Live verified for real; no robotic voice)
- Did: **cloud** `mind/live_token.py`: the token request used `liveConnectConstraints` (SDK name; the REST API
  rejects it → every app/glasses session silently fell back to scripted). Now `bidiGenerateContentSetup: {model}` +
  `fieldMask: "model"` (as google-genai's tokens.py; without the mask the token would lock every setup field and
  drop the device's persona/tools). **apple**: `enableAffectiveDialog` removed from the Live setup (gemini-3.8-live
  closes with 1007 "invalid argument" when it is true — bisected live, SDK + raw key too); close reason kept on
  `LiveSession`; opt-in paid `LiveIntegrationTests` + `scripts/live_e2e.sh`. Voice: the on-device synthesizer is
  gone (`VoiceLines`): cached Gemini TTS, else fetched on demand, else silent; glasses-lost notice is a toast.
- Verified (real Gemini, ~1 min each): iphone + glasses surfaces — setup accepted, Kaiku speaks, spoken
  interruption → `interrupted` (+ pending tool cancelled), transcription, `recall(walking)` → graph → "You like
  walking by the lake, Aino." Evidence: `demo/recordings/live-e2e/glasses/timeline.png` (+ wav, events).
  `swift test` 81 (1 skipped = the paid test), iOS + Mac builds green, cloud mind tests green.
- Broken/blocked: **hub (owner B)**: `gemini_live.live_config` sets `enable_affective_dialog=True` → every robot
  Live session closes with 1007 (reproduced with the SDK + key). Also the hub's offline voice is macOS `say` /
  espeak and `.env` has `KAIKU_VOICE=text` → robotic; lead's rule: never a synthesizer, use cached `/v1/voice`.
  **Budget**: daily cap $4 hit ($3.98, mostly evals) → only 1 of 99 voice lines pre-rendered; apps stay silent for
  uncached lines until `make voice-prerender` runs with budget. **Signing**: accept the Apple PLA for team
  the lead's team; iPhone 14 shows "unavailable" in devicectl.

## 2026-11-14 02:50 — Claude Code — contracts + cloud + apple (opt-in transcripts, D33; voice lines rendered)
- Did: contract `EpisodeIn.transcript` (optional, non-breaking) + `TranscriptTurn`, `Transcript`,
  `TranscriptsResponse`, `EpisodeResult.transcript_stored`; `make contracts`. Cloud: `transcripts` table, stored only
  when sent and never after a crisis (outcome or any crisis-phrase turn), `GET/DELETE /v1/me/transcripts[/{id}]`,
  `jobs/transcripts_export.py` (de-identified Gemma chat JSONL). Apple: `transcripts` signal (off by default) in
  onboarding, What Kaiku remembers (switch, count, delete all) and What Kaiku saw today; `Conversation.stop` sends
  the transcript only with consent. Budget `daily_usd` 4 → 6 (lead); `make voice-prerender`: all lines × en/fi/sv
  rendered, 0 failed (spend total $5.45 / $10).
- Verified: `make check` 516 passed; `swift test` 82 (+1 paid skipped); iOS + Mac builds green. Real Gemini Live
  glasses runs: 3 of 4 pass (one run Kaiku stayed silent on the opener — proactive audio); transcript stored via the
  real episode route and exported (`demo/recordings/live-e2e/glasses/gemma_train.jsonl`, home id hashed).
- Broken/blocked: **config (persona)**: on the glasses surface Kaiku once said "I'm a little robot" — the glasses
  label in `config/surfaces.toml` says "a voice in the person's glasses"; persona owner please check. Robot hub,
  glasses web app and web /me don't send transcripts yet. Per-conversation reading in the app not built (API has it).

## 2026-11-14 02:35 — Claude Code — apple + cloud (Mac window bugs, garden per day, Today's path)
- Did: Mac: fixed the game window breaking (root cause: the split view measured the non-scrolling game pane at a
  tiny width → fixed-vertical text → ~1000–1600 pt minimum → pane outgrew the window, clipping the sidebar list,
  "I'm not OK", title and Start). `fillsProposal()` on non-scrolling panes; scene backgrounds no longer tint the
  sidebar; one back button (system toolbar) + the screen's title in the toolbar; bigger game previews; brand Start
  button everywhere. Verified at 980×720 and full screen. Garden: `Garden.days` (14 local days: count + kinds,
  additive contract field) → day plots that grow with what was done, kind icons + legend, tap a day to read it;
  Today shows 7 days, Your days 14. Today's path (Duolingo-style): weather check → Kaiku's suggestion → a game,
  ticks per day, one lit "Start here / Next" button, on Today, Play and every game's end ("Up next: …").
- Verified: cloud + contracts pytest green, `swift test` 70 green, ui_copy_check clean, Mac + iOS builds, screenshots
  against a seeded local cloud (demo-aino).
- Contract changes: `GardenDay` + `Garden.days` (additive, no version bump); `make contracts` run.
- Broken/blocked: design (D) — upstream `path.*`, `garden.*`, `play.all` from copy.apple.json.

## 2026-11-14 04:40 — Claude Code — one Gemini voice in the apps: continuous Live, TTS everywhere, Talk layout
- Did: cloud mints the apps' Live token with Kaiku's whole setup locked in (`bidiGenerateContentSetup`: persona,
  Sulafat voice, tools, automatic VAD + barge-in, transcriptions, resumption, sliding window) and returns it as
  `live_setup`; VAD knobs in `config/kaiku.toml [live]`. New `POST /v1/voice/say` (any short app line in the same
  Gemini voice, cached by hash, never a crisis line). Apps: Talk is a continuous conversation (tap Kaiku to open the
  mic, Gemini takes turns, talking or typing over Kaiku interrupts it, tap again to stop) on one audio engine with
  voice processing (echo cancellation); every line outside Live (greeting, "I'm back", scripted replies) is Gemini
  TTS from the cloud, the on-device synthesizer only when offline with nothing cached. Talk layout: header-sized
  Kaiku on a clear background + status line + mic button, the transcript gets the rest; bubbles up to 80 % width,
  never squeezed; pinned to the newest line, also when the keyboard opens. `make e2e-intelligence` added.
- Fixed: the old token request used `liveConnectConstraints` (the SDK's name); the REST API answers 400, so every
  mint failed soft to null and the apps always fell back to scripted lines + Apple's voice.
- Verified (real calls, key from .env + ADC): `make e2e-intelligence` ALL PASS — token minted, setupComplete 1.3 s,
  typed turn 5.3 s audio + transcript, spoken turn (macOS `say` → 16 kHz) ended by automatic VAD with input
  transcript + audio answer, a model tool call forwarded to the cloud, barge-in → `interrupted`; TTS keyed line and
  /v1/voice/say wav (cached on repeat); ask_mind "What is my sister called?" → Maija; nightly-mind graph 7 nodes /
  7 edges → constellation non-empty. iOS simulator against a local cloud: typed turn → Kaiku's real Live reply as a
  bubble. `make check` 513 passed, `swift test` 74 green, iOS sim + Mac builds green, ui_copy_check clean.
- Contract changes: `CompanionSessionResponse.live_setup` (optional, additive), `VoiceSayRequest`; `make contracts`.
- Broken/blocked: `enableAffectiveDialog` makes constrained sessions fail (1007 on the first turn) → off. Mic + echo
  cancellation need a real-device pass (simulator mic). Live output transcripts sometimes join words (API text).
  Ephemeral tokens need GEMINI_API_KEY (Developer API); ADC alone can't mint them — the hub path is unchanged.
- Next: real-device Talk pass (iPhone speaker + AirPods + glasses, Mac built-in mic).

## 2026-11-14 — Claude Code — contracts, cloud, web, sim, config, docs [dashboard: the week + What Kaiku has learned]
- Did: `cloud/kaiku_cloud/week.py` + `api/dashboard.py`: `GET /v1/me/week`, `GET /v1/me/graph`, `GET|PUT /v1/me/sharing`,
  `GET /v1/patients/{id}/week`, `GET /v1/patients/{id}/graph`. Routines (daily / most days / weekday rhythm, usual time,
  kept/partly/slipped) from obs (ritual, walks, drum, breathing, check-ins, laptop, games, sleep onset) + episodes
  (person, or care team when shared); going well / worth a look from per-metric drift, verdicts, bandit, safety flags,
  PHQ-9 cadence; graph view with obs-only activities, routine nodes and evidence counts. Web: `components/LearnedGraph.tsx`
  (column layout, click → labelled links) and `components/WeekPanels.tsx` on `/me` (warm, en/fi headings) and the
  clinician patient page. Seed: Aino gets 10 memories, Monday/Thursday check-ins, sharing on. D33 (privacy: care team
  sees the graph only when the person shares; default off; never people/places/likes/plans).
- Verified: `make check` green (527); `pnpm build`; Playwright screenshots of /me and the patient page (desktop + 390 px).
- Contract changes: additive (`CareSharing`, `WeekSummary`, `Routine`, `WeekItem`, `KnowledgeGraph`, `GraphNode`,
  `GraphEdge`), `SCHEMA_VERSION` 1; `make contracts` run.
- Broken/blocked: none. Week sentences are English only (fi shows them as-is). Apple apps don't show the week/graph yet (A).

## 2026-11-14 — Claude Code — contracts, cloud, web, docs [dashboard demo-readability: one record, next steps, audit fixes]
- Did: `WeekSummary.sources` (one record: what robot / phone & Mac / glasses / watch added per day + counts) and
  `WeekSummary.next_steps` (care team, fixed rules, allowed wording, optional action button). Web: `RecordStrip` on /me
  and the patient page; "Suggested next steps" panel. Audit fixes: usual range clamped at 0 for never-negative
  metrics; evidence "How unusual" in words (+ z explained) instead of a mono z column; direction coloured
  clay (change) / sage (other way) with arrows; chart axis text readable (smaller viewBox, 12.5 px), dates "16 Oct";
  chart caption "Latest 543 min" + a "change from usual" pill; a legend under every chart; timeline groups get a
  chevron + "Show / hide"; brand mascot on a clay-soft tile; clinician list names larger, SIMULATED quiet; rule line
  and "What Kaiku saw today" in the body font; /me no longer prints the raw pairing URL (copy button only) and shows
  the name memory as "Kaiku calls you Aino" instead of a deletable memory row; `num()` no longer turns 8900 into 89.
- Verified: `make check` green; `pnpm build`; Playwright screenshots of /me, /clinician, patient page (desktop + 390 px).
- Contract changes: additive (`SourceWeek`, `SourceCount`, `NextStep`), `SCHEMA_VERSION` 1; `make contracts` run.
- Broken/blocked: none.

## 2026-11-14 03:00 — Claude Code — integration (ui-lead + conversation engine + dashboard into companion-apps)
- Did: merged three parallel streams. One Live engine on Apple: `Conversation` / `ConversationAudio` / the pure
  `LiveSession` protocol layer (resumption, compression, non-blocking tools, glasses walk companion, opt-in
  transcripts); the voice agent's `LiveAudio` and its locked-setup Talk model were dropped. Talk keeps the new
  layout (header-sized Kaiku = tap to mute/unmute, full-width chat, bubbles ≤ 80 %, welcome + starters) on top of
  `Conversation`. Cloud tokens lock only the model (`fieldMask: model`) so device setup fields aren't silently
  ignored; `live_setup` is still returned and the loudspeaker VAD comes from `config/kaiku.toml [live]`.
  `VoiceLines` = Gemini TTS keyed + `/v1/voice/say`, never a synthesizer. Two D33s: transcripts keep D33, the
  dashboard sharing decision is now D34 (references updated).
- Verified: `make check` 538 passed; `swift test` 84 (1 paid skip); iOS + Mac builds; web build; ui_copy_check clean.
- Contract changes: none beyond the merged branches (`make contracts` re-run).

## 2026-11-14 — Codex — docs (independent integration audit)
- Did: read-only implementation audit across cloud/contracts, Apple/web/glasses, hub/firmware and sims, with three
  independent reviewers. Inspected the running clinician list and patient record in the local in-app browser.
  No application fixes, deployment, real-user data, or changes to existing work; this entry records the audit.
  The working tree changed externally during review (latest observed base f5165b1); findings were rechecked.
- Verified: `make check` passed (ruff, 538 Python tests including real-MQTT tests, web typecheck); web's 21 tests
  and production static build passed. Latest Swift suite: 83 passed, one opt-in Live test skipped (84 total).
  Initial sandbox socket failures disappeared with permitted local-network execution. `make setup` could sync
  Python but pnpm's noninteractive modules-directory prompt aborted; installed web dependencies built successfully.
  `make doctor` verified credentials and all six configured model metadata endpoints, but the default broker and
  cloud were not running. Isolated services were used for the integration runs instead.
- Verified: `make smoke` passed all 17 API checks. `scripts/record_robot_demo.sh` completed greet/dial/breathe/drum/
  nudge/close and glasses/laptop/Mac/phone posts (2,776 recorded bus messages); cloud consensus remained the expected
  needs_call for synthetic Aino. This harness uses text voice, no music, and manually invokes ask_mind.
  `make e2e-intelligence` passed real ephemeral-token Live typed/spoken turns, automatic VAD, barge-in, keyed/dynamic
  TTS/cache, deterministic memory recall and graph generation. It bypasses the production Apple microphone and hub
  voice adapters. A separate real ask_mind emotional request returned the Argon route. Hosted Gemma explanation
  fell back after two outputs failed validation; a third direct adapter/validator probe succeeded. A fresh actual
  hub-config Live probe was blocked before networking by the existing five-minute budget reservation; caps unchanged.
- Verified: `make tune N=40`: synthetic needs_call precision 0.972 / recall 0.904; false calls 0.031 per patient-month;
  median lead 6 days. Removing robot data dropped synthetic needs_call recall to 0.167. Not clinical validation.
- Broken/blocked (Apple A): Conversation.startAudio never assigns ConversationAudio.onPCM; no production caller of
  LiveSession.sendAudio, so real microphone speech never reaches Gemini. Native crisis UI promises team contact
  independent of upload/delivery; care-team button only shows a toast. Talk/walk record_dial bypass check-in consent.
  Mock glasses readings use the normal sim=false envelope. Advertised PHQ-9/friend tools and Talk-started walk are
  unhandled. Episode finalization is not durable offline; same-day Health summary IDs prevent later corrections.
- Broken/blocked (hub B): reproduced spoken-crisis self-cancellation in GeminiLiveVoice.close_session, before script
  or safety_flag (CancelledError, zero flags). end_ritual/end_session skip only the current step instead of stopping.
  Attention-triggered sessions open the microphone before affirmative ritual consent. Hub still enables affective
  dialogue despite the earlier recorded 1007 rejection. Normal ritual completion does not finalize a cloud episode.
- Broken/blocked (cloud C): reproduced unauthenticated record reads, sharing changes, transcript deletion, and
  Safety -> Watch acknowledgement even with both tokens configured. Tokens do not bind a home identity. Reproduced
  stable consensus seven days after every source stopped. Source votes map by observation type, not physical device,
  so phone reports/walks/games can appear as robot/glasses/Apps. Crisis transcript updates leave older transcripts
  stored and completed retries overwrite crisis; export retains names/places absent from the notebook. Shared
  what-helps labels can include names despite the clinician graph's promise to withhold people/places. App-direct
  Live usage bypasses the claimed universal budget/usage ledger. No outbound care-team alert/delivery workflow found.
- Broken/blocked (D/hardware A): web has no chat/Live companion client; both standalone glasses app folders and
  friendlink firmware remain documentation-only. Full Atech firmware validation and UNO Q compilation are still
  documented as blocked/unverified; physical glasses/audio/sensor integration was not established by this audit.
  No external personal messaging integration found. Web safety uploads have no persistent retry queue.
- Contract changes: none.
- Next: owners fix microphone wiring, robot crisis/stop/consent, API authorization/home isolation, stale-data policy
  and honest alert delivery before claiming end-to-end readiness. Acceptance must exercise actual device controllers
  across two surfaces, tool effects, fresh observations on the dashboard, and offline/crisis recovery; socket-only
  Live tests and seeded dashboards cannot substitute for that pass. Full findings delivered in the audit chat.
- Live (real, after the merge): `make e2e-intelligence` ALL PASS (token locks only the model; `live_setup` frame);
  `apps/apple/scripts/live_e2e.sh iphone` failed once — the model opened Talk by calling `start_activity(tell)`
  instead of greeting (the app would have left Talk for the game). Fixed both ways: the persona's surface lines say
  "start one only when the person asks… greet them first" (`mind/assemble.py`), and TalkModel refuses
  `start_activity` until the person has spoken. Re-run: passed (greeting → barge-in → recall → spoken answer).

### 2026-11-14 — Codex audit addendum: check-in ingestion is not check-in monitoring
- Reproduced with 35 days of synthetic mood/energy/sleep answers (4 for 28 days, then 1 for seven): Apple/default
  and web `context=adhoc` produce zero mood/energy/sleep metric points, robot verdict insufficient, confidence 1.0.
  Identical `context=ritual` answers produce all three series and a worse robot verdict. Current criteria filter
  all three metrics to ritual, while Apple SelfReport defaults to adhoc and web MeView explicitly sends adhoc.
  Ordinary app weather checks reach the record/garden/routines but their values do not affect these monitoring
  metrics. Owners C/A/D: align the intended criteria with producers and test resulting verdicts, not just ingest.
- Clarification: type-only source mapping demonstrates misleading device labels, not that a phone's present
  weather producer alone creates a sufficient robot vote. The missing metrics above prevent that specific claim.
- Final combined `make check` rerun passed: 538 tests + lint/typecheck. Other active edits were not changed by this audit.

## 2026-11-14 03:10 — Claude Code — apple (iPhone signing, app icon, store prep)
- Did: device signing with the lead's paid team (passed on the command line, not committed): entitlements are plain
  files chosen by `CODE_SIGN_ENTITLEMENTS`, `KAIKU_APP_GROUP` / `KAIKU_ENTITLEMENTS_SUFFIX` build settings (CLI
  signing can't assign an App Group → `.nogroup` variant; widget shows its placeholder until the group is assigned
  in the portal). `scripts/run_on_iphone.sh`. App icon from the real MascotView (`AppIconRenderTests`, opt-in;
  glow pinned via `GlowClock.fixedHour` so the icon doesn't depend on build time): iOS light + dark 1024, Mac set
  16–1024 on the macOS grid (`scripts/make_app_icon.sh`). Privacy manifests (app, widget, Mac), export compliance
  flag, local-network + updated mic usage strings. App Store Connect app is "Kaikuu" (name taken).
- Verified: signed device build OK; icon + manifests present in the built .app bundles (iOS + Mac).
- Broken/blocked: install on the iPhone waits for Developer Mode on the phone. Cloud for the phone runs on the LAN
  (`uvicorn kaiku_cloud.api.local:app --host 0.0.0.0 --port 8000`).

### 2026-11-14 — Codex hub integration repairs
- Fixed: consented robot microphone startup (attention/cloud invitations stay mic-off; incidental speech,
  rotation and timeout do not consent); authorized cloud bootstrap required. end_session/end_ritual stop
  all remaining steps; breathe/drum selection targets the named step. Spoken crisis no longer cancels its
  own receive task before the fixed visible script and priority safety flag; split transcription phrases
  are checked cumulatively. No local say/espeak fallback remains; normal fallback is Gemini audio or text.
- Fixed: callback PCM copies before device buffer reuse; callback playback avoids blocking Live receive,
  barge-in clears queued audio while tools run; bounded session resumption and explicit-stop cancellation;
  session duration bound; affective dialogue disabled. Source-labelled bounded robot context only during
  consented conversations. PPG keeps sensor quality and timestamps; gaps restart the contiguous window.
- Persistence: robot episode completion uses a SQLite outbox with stable IDs and retries; opt-in transcripts
  are off by default and erased on crisis. Cloud commands repeat until acknowledged after local application.
  Ground truth hub/AGENTS.md updated; parent owns config/contracts/modules sync. Demo driver now explicitly
  presses the simulated button to accept (parent-authorized scripts/robot_demo_driver.py exception).
- Verified: hub unit/controller suites (151 non-MQTT tests; latest focused changes 27 passing), isolated real
  mosquitto ritual test. Production Gemini adapter with injected model/audio edges covers PCM upload,
  consent timeout/acceptance, spoken crisis, exact activity/stop, barge-in during a blocked cloud tool,
  auth failure, reconnect/stop race, expiry, transcript completion and command ack retries.
- Verified: scripts/record_robot_demo.sh /private/tmp/kaiku-integration-fixed-robot completed 2,671 real
  MQTT messages with greeting/explicit consent/dial/breathe/drum/nudge/close, and successful synthetic
  glasses/laptop/Mac/phone posts. Seeded consensus remains needs_call/disagree. Separate actual HTTP
  production Hub/outbox test stored an opted-in synthetic transcript exactly once, retrieved it through
  /v1/me/transcripts, and proved command redelivery before acknowledgement and removal afterward.
- Remaining: physical microphone/speaker, robot firmware/motor/sensors and audible voice quality need
  bench validation. Fixed crisis guidance is visible; a deterministic pre-recorded crisis audio asset is
  not supplied. These simulations do not establish physical hardware readiness. Real-model adapter probe
  is being coordinated separately; no paid call or budget change was part of the tests above.

### 2026-11-14 — Codex hub real voice adapter verification
- Real probe exposed that global platform/enterprise backend tried the configured Developer API Live model
  on Vertex global and failed1008. Fixed the Live edge to prefer GEMINI_API_KEY when present, independently
  of the global text/TTS backend; injected edges remain testable. Added regression coverage.
- Verified actual GeminiLiveVoice + Hub against the current isolated real cloud:489,920 bytes of generated
  synthetic16kHzPCM passed through the production microphone callback; input transcription arrived;333,122
  outputPCM bytes received; automatic ask_mind returned ok(route=argon); episode and opted-in transcript
  were stored and retrieved through the realAPI. No physical audio device was used. Runtime authorized
  budget overrides only; no cap change written. Log:/private/tmp/kaiku-hub-live-real.log.
- Added configured bounded ask_mind timeout for longer reasoning while keeping other tools short; Live
  receive/barge-in/safety remain concurrent. Explicit stop during a reconnect handshake is regression-tested
  to close the newly returned socket without reopening the microphone. No claim of Gemma success is made
  from the argon route; cloud owner is verifying whether that result was Gemini fallback.

### 2026-11-14 — Codex Apple integration repairs and real controller verification
- Fixed the missing production microphone edge: ConversationAudio.onPCM now reaches LiveSession through
  Conversation after setup acknowledgement. Mute, pause, session expiry, pairing changes and stale sockets
  cannot stream; route-restart failures close honestly. end_session closes capture and preserves its outcome.
  Cloud duration/context-refresh/resume-session fields are mirrored; reconnect keeps the original episode.
- Added origin/home-scoped durable EpisodeOutbox for metadata and opt-in transcripts, plus scoped observation
  queues. Completion survives restart/offline delivery. Consent-off and forget remove pending words; crisis
  never stores words. Legacy observation entries without an origin are quarantined rather than guessed.
  record_dial now respects pause/consent/range; PHQ-9 and walking tools dispatch correctly; PHQ auth uses a
  consumed token fragment. Health late samples now produce distinct snapshot IDs with capture timestamps.
- Added bounded authenticated active-source refresh: whitelisted completed-activity/source labels only,
  never Health metrics/scores/free text; deduplicated and delivered when quiet, with consent rechecked.
  Gemini uses the prepared context and asks the cloud mind for deeper interpretation; ask_mind allows120s.
  No AVSpeechSynthesizer voice fallback: Gemini Live or cached/cloud Gemini TTS, otherwise honest unavailable.
- Meta DAT now starts real registration, handles distinct registration/motion states, and claims motion
  connected only when actual samples arrive. You → Devices → Glasses → Set up opens Meta AI registration
  without microphone capture. Developer Mode supports MetaAppID=0. Automatic mock fallback removed;
  explicit debug mock outings and recovered drafts carry sim=true. Camera/daylight remains unavailable.
- Verified:95 shared Swift tests,3 opt-in skips,0 failures; final signed iPhone build and Mac build succeeded.
  Production Conversation tests cover PCM/playback/barge-in, mute/pause, consent, crisis, route failure,
  duration, resume, durable completion, source refresh and cross-server isolation.
- Verified real model/database flow in13.903s against isolated cloud18031 using a validated5.392s synthetic
  speech fixture: Conversation→real LiveSession→input transcript and Gemini audio; typed ask_mind→successful
  route=gemma result→Gemini audio AFTER that result; same episode completion/transcript saved and retrieved.
  Evidence:/private/tmp/kaiku-controller-real.log. First probe had an empty sandbox-generated speech fixture;
  corrected fixture validation now runs before token minting. No ambient microphone was opened.
- Physical blocker: signed installer ready at/private/tmp/kaiku-apple-signed/Build/Products/Debug-iphoneos/Kaiku.app.
  Installation attempted twice; CoreDevice reports paired iPhone14 unavailable. Xcode independently reports
  it offline, while macOS USB Host inventory shows only buses and no phone; DDI is usable. Actual iPhone
  microphone/HFP, Meta Gen2 registration/motion and HealthKit therefore remain unverified. Existing icon and
  Mascot edits were preserved; Apple AGENTS updated. Parent runs global check and cross-module demo acceptance.

### 2026-11-14 — Codex cloud integration, Gemma preparation and clinician record chat
- Security: protected routes now fail closed. Pairing tokens bind one home; clinician/admin roles are separate and
  cannot read private person routes. Credential-free local demos require explicit KAIKU_DEMO_MODE=1. Mixed-home
  event batches reject before any write. Health readiness validates the effective criteria schema and returns 503
  on invalid configuration instead of reporting a healthy service while monitoring routes fail.
- Monitoring/persistence: criteria-driven source freshness makes old inputs insufficient; cached summaries refresh
  on day/rule changes. Future input cannot move the scoring day. Daily watch snapshots use the configured measured
  date and latest capture ordering. Commands remain queued until application acknowledgement. Crisis status,
  transcript removal and retry tombstones are atomic; delayed completion uploads and deleted transcripts cannot
  resurrect content. Explicit opt-in remains required; training export additionally needs reviewed, separately
  training-consented episode IDs. Shared care graphs omit free-text helpers that may name people or places.
- Voice admission: apps reserve the configured Live duration in the existing spend ledger, with usage visible in
  intelligence health. Robot bootstrap intentionally does not mint a second token: the authorized robot adapter
  meters its own key. Resume requests reuse only an open same-home/surface episode and retain the original duration.
  Source context is prepared from actual input-source metadata, marks synthetic events and excludes private metrics.
- Gemma: on-demand ask_mind now uses hosted Gemma before explicit Gemini fallback; exact memory lookup and crisis
  remain deterministic. The existing nightly organiser uses validated Gemma graph proposals, caches unchanged
  clean node sets, never rewrites the notebook and cannot merge different people. Bootstrap excludes consolidated
  nodes and supplies compact prepared context so ordinary Gemini Live turns need no reasoning-model call.
  The documented minimal-thinking setting fixed truncated responses and reduced the real primary response to 2.22 s.
- Clinician record chat: POST /v1/patients/{id}/ask is clinician/admin only, grounded in deterministic consensus and
  numeric observation timelines. Citation IDs, numeric claims and wording are validated; private memories, episodes
  and transcripts are never read. Human-unit citation details include hours/minutes, clock times, percentages and
  whole steps. Question/evidence caching and cooldown bound paid calls; unavailable/invalid answers fall back visibly.
  Clinician explanation caching also ignores mere arrival timestamps and applies a failure/regeneration cooldown.
- Durability: successful responses await volume commits, including GET routes that update summaries/explanations/
  usage and voice caches. Failed commits return 503 for safe queued event/episode retries. No database was reset.
- Verified: cloud ruff clean; full cloud suite 242 passed before the final readiness regression, then all 14 runtime
  integration tests (including readiness) passed, covering all 243 current cloud tests. Production HTTP/SQLite tests
  cover auth, restart/offline retries, timestamps, deletion/crisis monotonicity, source privacy and provider budgets.
- Real-provider proofs using synthetic data and the existing spend DB: Gemma primary tool answer 2.22 s with a
  verified phone-source citation; four-source clinician explanation 6.27 s; Gemma graph organisation 1.93 s with one
  semantic merge, organised bootstrap and unchanged original notebook, repeated organisation cached; clinician
  record question 6.16 s with 13 verified citations (11 human-unit metrics), repeat cached, unauthorized requests
  rejected. Gemini Live microphone/speaker/Meta hardware validation is owned by the app/hub workstreams, not implied
  by these API proofs. Hosted Gemma is verified; no private Modal GPU deployment or persistent warm GPU is claimed.
- Ground truth: cloud/AGENTS.md updated. Parent owns contracts/config/modules regeneration, system-wide make check,
  demo service restarts and deployment decisions. Runtime budget overrides followed the user's approved test limits;
  no higher budget cap or credential was written into repository files.

### 2026-11-14 — Codex web clinician and optional task capture
- Reworked the care workspace around dated, searchable measurements, priority changes, preserved routines and
  coverage limits. Source cards, evidence rows and validated record-chat citations navigate the same metric explorer.
  Duration values use hours/minutes; minute-of-day metrics use HH:mm; steps and milliseconds use whole numbers.
  Missing values and missing baselines are explicit. Synthetic records have visible labels and a record-type filter.
- Added clinician-only Ask this record against the new cloud contract with clear generated/fallback attribution,
  evidence citations, retry states and memory-only chat cleared on access changes. No clinician request reads the
  person's private notebook or transcript endpoints. Routine comparisons now use a structured table; the relationship
  graph is secondary supporting context rather than the main evidence view.
- Added a recent task inspector using authorized GET /v1/patients/{id}/tasks: actual dates/device, timing, optional
  spoken features and camera method/coverage. Facial features are described as experimental movement only, never
  emotions, independent signal groups or comparable baselines across different capture methods.
- Firefly camera capture is explicit opt-in and off by default, with visible preview/indicator and Stop control.
  MediaPipe runs locally; only numeric movement/sample/coverage features are sent. The separate spoken session
  measures microphone pace/pauses/pitch and now defaults its camera off. Silence returns missing speech evidence.
  Leaving, backgrounding, cancellation or crisis releases capture; late permission grants are stopped. Interrupted
  reaction tasks are discarded. Failed audio initialization releases the microphone.
- Verified: web TypeScript check, all 32 tests, and production static export pass. New tests cover human units and
  dated baseline evidence, silent speech, late and pre-cancelled permission requests, empty camera samples, and audio
  setup cleanup. Final export includes the renamed signal groups and same-origin API (no integration port embedded).
  Parent owns browser/device smoke verification, service restart for the new endpoint and combined make check.
  No physical webcam/microphone, iPhone or Meta recording is claimed from these automated tests.
- Ground truth: apps/web/AGENTS.md updated. Parent owns contracts/modules manifest regeneration; no cloud/config or
  contract files were edited by this web workstream. Existing auth, durable outbox and safety delivery changes retained.

### 2026-11-14 — Codex cloud optional task-capture integration
- Added clinician/admin-only GET /v1/patients/{id}/tasks?days=7, returning the latest 100 typed PlaySession
  envelopes within a validated 1–30 day window, newest first. Original date/source/device/method/sim/quality and
  aggregate reaction, speech and optional camera features survive ingestion and retrieval unchanged. Future and
  out-of-window observations are excluded; no private conversation tables are read.
- Optional local facial methods remain observational and uncalibrated. No camera feature metric, cross-method
  baseline pooling or new state vote was added. Zero-face capture metadata can be retained with no facial indices;
  raw audio, frames, video and task transcripts remain invalid and unpersisted.
- Record-chat task citations expose only participation, capture coverage and sample/method provenance. Facial
  expressivity and movement index values are not included in Gemma's evidence, and the prompt forbids emotional
  interpretation. Citation IDs retain the task event UUID for the clinician inspection panel.
- Verified: all 249 cloud tests pass; Ruff clean. Six new production-route regressions cover web MediaPipe and
  phone Vision round trips, roles/home isolation, time/100-row limits, optional capture/raw-media rejection,
  unchanged analytic inputs and bounded record-chat evidence. These API tests do not claim physical camera or
  microphone validation; app owners handle local permissions, capture and HTTPS/browser prerequisites.
- Updated cloud/AGENTS.md. Parent owns contracts/config/modules regeneration and service restarts; no existing
  LAN service, production database, deployment, secret or budget cap was changed by this workstream.

### 2026-11-14 — Codex web capture origin preflight
- Added a capability check before device capture: HTTP LAN addresses now explicitly require HTTPS or localhost;
  secure browsers without media APIs get a separate unsupported-access explanation. Camera toggles and Start
  speaking stay disabled when unavailable. Camera-free Firefly and skipping to the reaction game remain usable.
- Verified TypeScript, all 33 web tests (including secure/insecure/unsupported origin cases), and production static
  export. Confirmed prerequisite copy is bundled and no integration API port is embedded. No public service was
  deployed. Module AGENTS updated; parent owns browser smoke verification on the LAN address.

### 2026-11-14 — Codex web grounded-answer attribution correction
- Updated Ask this record attribution to “Evidence selected by Gemma; facts checked by code” to match the cloud's
  deterministic fact/direction rendering. Response contract and UI behavior are unchanged. Module AGENTS updated.
- Verified TypeScript and successful production static export. Cloud owns model/direction regression tests.

### 2026-11-14 — Codex native task sensing, physical installation and visible voice control
- Added explicit default-off Camera consent and a visible activity-intro toggle, capture indicator and Stop
  camera action. AVFoundation captures video only; Vision derives scalar facial geometry locally. Frames are
  never saved or uploaded. Background, Back, cancellation, consent revocation and monitoring pause stop and
  discard capture; late permission grants and late frames cannot reopen it. Camera failure leaves play usable.
- Native play summaries now carry optional expressivity_index, face_movement, camera_face_coverage,
  camera_samples and camera_method=vision_landmarks. Missing/ambiguous faces report coverage and no invented
  metric. Geometry variability is not emotion recognition; Vision and MediaPipe values must not be pooled.
  No new consensus vote was enabled. Existing Firefly reaction/lapse and Pebbles performance metrics remain.
- Tell Kaiku microphone capture now requires explicit voice/task consent and a press; background/revocation/
  dismissal stop it. Silent games do not capture audio; a walking Live session blocks a second Tell microphone.
  Camera does not modify the Live audio session. Observation emission scrubs revoked sensor fields again.
- Verified 104 Swift tests, 4 optional skips, zero failures; signed iPhone and Mac builds passed. New tests
  cover geometry/coverage, no-data gaps, method-labelled contract fields, default-off, denied/late permission,
  cancellation and late frames. Free actual AppModel recorder -> scoped outbox -> isolated cloud/database
  test passed in 0.032 seconds: synthetic camera/task fields persisted; consent-off removed camera fields
  while keeping reaction results. Dedicated camera-integration home, sim=true; no sensor/model opened.
- Physical progress: USB discovery recovered and iPhone Developer Mode was enabled. Kaiku was installed,
  then the camera-capable update installed over it and launched successfully, preserving data/pairing. User
  confirmed Meta registration/connection. This does not yet prove actual IMU, glasses HFP or camera quality.
- User reported no mic button. Found Talk hid its mic icon until Live already connected. Replaced that with
  an always-visible labelled voice control (Start voice conversation / Mute microphone / Resume microphone),
  plus explicit pairing and microphone-settings actions. Failure text distinguishes connection, pairing,
  unavailable voice and audio startup; active iPhone voice shows the actual output-route name. This signed
  fix was installed successfully. Parent is guiding the physical voice check; no further reinstall while
  the person tests. Physical microphone/camera were not activated autonomously by the agent.
- Evidence: /private/tmp/kaiku-camera-db-integration.log, /private/tmp/kaiku-apple-camera-tests.log,
  /private/tmp/kaiku-apple-voice-button-build.log, /private/tmp/kaiku-apple-camera-mac-build.log.
  Ground truth updated in apps/apple/AGENTS.md and project.yml; parent owns shared schema/config/view sync.

### 2026-11-14 — Codex verified practitioner evidence rendering
- Investigated task-chat fallback without retaining model prose. Existing contentless usage showed a successful
  provider call followed by validation fallback. A newly authored synthetic fixture reproduced the cause: naked
  task UUID fragments in unsolicited answer text were mistaken for unsupported numerical claims.
- Gemma now selects relevance-ranked known citation IDs; code renders every practitioner fact, number, source
  label and latest-versus-personal-usual direction. Unsolicited model prose is discarded, including cited claims
  that reverse a numeric comparison. Unknown/malformed selections still fall back with a contentless reason.
  Task answers retain actual coverage and explicitly mark absent camera capture as unknown.
- Consensus explanations use the same boundary: Gemma prioritises supplied sources/metric IDs, while deterministic
  code renders verdicts, recorded directions, caveats and scripted actions. Aggregate source labels do not claim
  connected robot/Meta hardware. Semantic cache versions invalidate the older free-form answers.
- Whole-unit/clock rounding now matches browser Math.round, including negative clock offsets. Added regressions
  for reversed heart-rate claims, unsolicited UUID prose, source-group attribution and half-unit rounding.
- Verified: full cloud suite passed and Ruff clean. Fresh authored-fixture real-provider proof: task-specific
  selection rendered all three tasks, 80% coverage and unknown missing capture in 3.36 s; four-source consensus
  selection rendered verified group labels in 1.82 s; repeated question used cache. No existing records were sent.
- Automatic approval review rejected an earlier DB-snapshot provider probe because of potential sensitive-record
  export. That action did not run. The approved replacement opened no existing database and used newly invented
  in-memory fixtures only. Parent owns LAN service restarts and the final actual-HTTP/browser acceptance checks.

### 2026-11-14 — Codex independent API discovery
- Added public contract-backed GET /v1/discovery for the separate _kaiku-api._tcp service. It returns only
  service/schema identity, effective demo/authenticated/unconfigured mode, auth requirement and supported API
  capabilities; never home identifiers, credentials or a Live token. Configured credentials override demo mode.
- A fresh app-generated installation home can bootstrap companion voice and ingest its first observation in
  explicit demo mode without a robot, QR flow, seeded patient or new enrollment endpoint. Authenticated mode
  retains existing per-home provisioning; an unconfigured deployment remains closed. Provider/budget gates
  are unchanged, so discovery alone does not promise voice readiness.
- Verified production-route tests cover all modes, credential privacy, fail-closed private routes and a fresh
  home session followed by phone observation persistence. Full cloud test suite and Ruff passed. Parent owns
  service restart and DNS-SD advertisement; Apple owns nearby API discovery and stable installation identity.


### 2026-11-14 — Codex architecture audit — contracts
- Did: atomic pre-provider budget reservation across threads/processes; metered failures retain estimates, invalid costs are rejected. guard is advisory. Updated contracts/AGENTS; no message/schema changes.
- Verified: 11 budget regressions including blocked-provider concurrency and independent-process contention; final make check Ruff clean, 636 Python tests passed, web typecheck and generated/module checks passed.
- Broken/blocked: independent ledgers are not a distributed billing limit; estimates are not invoices. No paid budget override used.

### 2026-11-14 — Codex architecture audit — cloud
- Did: added NumPy to Modal image with runtime-dependency parity check; exact accepted local recall precedes paid embeddings; provider tiers share remaining tool wait; Live mint/TTS attempts reserve before network; stateless Interactions use store=false. Durable atomic episode thread phase markers prevent retries replacing newer cross-device threads. Updated cloud/AGENTS.
- Verified: final combined 636-test check and isolated make smoke pass, including current cloud suite. No paid inference or remote deployment.
- Broken/blocked: TTS spend is recorded but TTS calls are absent from intelligence-health model_calls. Synchronous timeouts do not preemptively cancel provider work.

### 2026-11-14 — Codex architecture audit — hub
- Did: fixed partial transcripts consuming several dial/PHQ answers. Safety scans fragments immediately; completed utterances dispatch once; named Live dial tools own writes. Preserved end_session outcome/follow-up in durable completion; refused follow-ups cannot block delivery. Added validated consented express eye commands preserving ritual/thinking/crisis control. Updated hub/AGENTS.
- Verified: final make check includes real MQTT; full isolated robot recording completed 2,674 MQTT messages across all ritual stages and synthetic glasses/laptop/Mac/phone posts, intended needs_call/disagree, exact mind recall and no hub errors. Evidence: /private/tmp/kaiku-audit-20261114-robot.
- Broken/blocked: Atech root validation, uncompiled UNO Q sketch, absent friendlink firmware, unwired robot speech features, missing deterministic audible crisis asset and physical audio/sensor/motor/Lyria acceptance remain.

### 2026-11-14 — Codex architecture audit — apps/apple
- Did: global pause refuses/stops Live capture; unpausing requires explicit restart. Walks/recovered drafts bind original home/server without credentials; legacy drafts quarantined. Pairing revisions reject stale reads/rollbacks, clear private cached person data/visible words/walk state; Health delivery rechecks pairing/revision/consent after awaits. Updated Apple AGENTS.
- Verified: 112 shared Swift tests, four optional skips, zero failures; unsigned generic-iPhone build succeeded. Logs: /private/tmp/kaiku-audit-apple-isolation-tests.log and /private/tmp/kaiku-audit-ios-build.log. No installation/capture/paid calls.
- Broken/blocked: physical iPhone/HealthKit/DAT motion/HFP acceptance; DAT camera/daylight unavailable; standalone glasses web/Android modules are placeholders.

### 2026-11-14 — Codex architecture audit — apps/web
- Did: laptop, PHQ-9 and weather retries retain captured envelopes/home/API origin, preventing manual/background duplicate records. Weather answers lock after first submission. Person PHQ due uses /v1/me rather than a care-only history route. Updated web AGENTS.
- Verified: TypeScript, 35 tests, production static export and whitespace checks pass, with lost-response/manual/background and scope/payload regressions. No browser capture or public deployment.

### 2026-11-14 — Codex architecture audit — docs
- Did: saved docs/intelligence-audit-2026-11-14.md with architecture chart, each input, orchestration/model boundaries, learning versus training, storage/transcripts and acceptance gates. Updated privacy ground truth for Google resumption state and dynamic TTS audio retention separate from transcript deletion.
- Verified: setup/doctor zero failures (default-broker heartbeats absent); final make check 636 tests; final smoke; web 35 tests/build; Apple 112 tests and iPhone compile; full MQTT robot simulation. Existing dirty work preserved; no live service restart, deployment or production DB reset.
- Broken/blocked: local estimated spend about $7.39 today versus configured $6 daily cap; no fresh paid proof or cap increase. Earlier real-model proofs remain historical evidence. No general transcript TTL, server consent registry, dynamic personal TTS erasure linkage or backup/forensic-erasure acceptance established. Physical/placeholder gates prevent an all-services-ready claim.

### 2026-11-14 — Codex coordinated integration acceptance and architecture correction
- Diagnosed the LAN website failure: an old API process loaded contracts that rejected newer criteria fields.
  Restarted the existing port8000 service against the same database; no records were reset. Readiness now validates
  effective criteria. The final static web export is served same-origin, and the task-owned Next development server
  was stopped. Browser proof covers loaded care records, searched evidence, seven-day charts, human time units,
  real Gemma evidence selection and corrected higher-than-usual heart-rate facts. Screenshot is in the temporary
  acceptance artifacts, not committed user data.
- Shared contracts/config now include source freshness and measured-day ordering, command acknowledgements,
  bounded Live context/session controls, clinician citations, provenance-bearing task capture and public API
  discovery. Generated schemas/TS and the module index were regenerated from their ground truth. No camera
  feature was added to the consensus. Canonical source labels describe signal groups, not physical-device proof.
- Architecture D35/D37/D38: Gemma organises permitted knowledge and selects/reasons over grounded evidence;
  Gemini Live speaks from prepared context and calls Gemma only when needed. Deterministic code computes state,
  validates graph proposals and renders clinician numeric facts. A real browser test caught a reversed heart-rate
  claim in otherwise valid generated prose; model-authored clinical prose was replaced with bounded evidence
  selection and deterministic fact rendering. Source groups no longer imply connected hardware.
- Real HTTP task pipeline passed: three synthetic phone/web tasks accepted, three duplicate retries suppressed,
  method/coverage retained in SQLite and read back, insufficient baseline never labelled stable, source context
  marked simulated, and real Gemma selected all three task citations. Actual native Conversation→Gemini audio→
  Gemma tool→new Gemini audio→consented transcript persistence passed separately; synthetic native task recorder
  →outbox→HTTP→database passed. No physical microphone/camera success is inferred from injected audio/features.
- Full make check passed: 636 Python tests plus web typecheck, lint and generated consistency checks. Web suite
  passed 33 tests and production build. Native suite at the voice-button milestone: 100 passed, four optional
  cases skipped; the paid controller and real-DB task cases were separately executed successfully. Shared persona
  changes passed 25/25 dry scenarios and 3/3 bounded real-provider scenarios (text stand-in, not Live audio).
- Prior robot proof: real hub adapter with synthetic PCM/Gemini and MQTT hardware twins, plus full ritual and
  multi-source simulations. The lead subsequently deferred physical robot work; phone/glasses voice remains
  independent and cannot claim robot-only capabilities. Meta registration was confirmed by the lead, while
  physical audio routing/task capture still need actual-device acceptance.
- Added a local API harness that advertises only the dedicated _kaiku-api._tcp service after readiness. Real
  isolated HTTP lifecycle and SIGTERM cleanup passed; the running LAN service's advertisement was observed with
  DNS-SD. No home ID or credential is advertised. Authenticated deployments still require scoped credentials;
  only explicit demo mode permits new local installation profiles without QR/provisioning. Native discovery UI
  installation is in progress after the lead reported the prior launch was not visibly updated.
- The additional $15 budget approval is now persisted as $25 total/$23 daily ceilings, avoiding a normal restart
  reverting to the already-exhausted old daily cap. Estimates were about $7.40 during this acceptance pass;
  this is not provider billing reconciliation. Hosted Gemma is the verified path; no warm private Modal GPU or
  deployed public API is claimed. HTTP LAN browser capture needs HTTPS or localhost, now explained before capture.
- Updated architecture, privacy, track/submission claims and tester feedback. Remaining external boundaries:
  no SMS/WhatsApp connector or external clinician notification, no verified physical robot bench, no iPhone DAT
  camera stream, and no production multi-user enrollment/public HTTPS deployment. These are not silently mocked.

### 2026-11-14 — Codex Apple: independent voice service discovery, no QR/robot prerequisite
- Replaced QR-first onboarding with nearby companion services and advanced account access, plus separate service host/settings in You. `_kaiku-api._tcp` discovery validates public descriptors without sending credentials or profile data. Only a build-configured, verified explicit-demo service can automatically provision; Bonjour candidates require selection, production authorization is retained, origins get stable distinct device homes, existing profiles survive, and explicit disconnect prevents silent reprovisioning. Robot telemetry and Meta registration remain independent.
- Updated developer install script to retain a profile/create a fresh device identity by default instead of silently using seeded demo-aino; launch arguments use the required separator. Existing explicit account links remain supported. New discovery contract mirrored in Swift, Apple AGENTS updated.
- Validation: 121 Swift cases reported, 116 passed / 5 optional skipped / 0 failures (`/private/tmp/kaiku-discovery-tests.log`); optional real native discovery → new home → /me integration separately passed0.031s (`/private/tmp/kaiku-discovery-integration.log`) without paid model or capture. Signed iOS build4 succeeded; Mac build passed before final in-flight coalescing update and final rebuild running. Skips are icon export, paid controller, old raw LiveSession, task DB integration, and discovery HTTP integration; controller/task DB/discovery have separate successful evidence.
- Physical evidence: one Kaiku app in device inventory, fi.kaiku.app build3; initial launch rejected specifically because iPhone locked. After unlock/local-network approval, parent observed phone10.0.38.179 GET /v1/discovery200 and /v1/me200 on LAN8000, distinct from Mac test traffic. Final build4 installed preserving profile/Meta and successfully launched You at03:56:10, without opening mic/camera. User-started phone/glasses voice acceptance pending; no further reinstall while they test. Parent owns global checks (636 passed before these final native changes).

- Apple follow-up: final Mac rebuild including concurrent descriptor coalescing passed (`/private/tmp/kaiku-discovery-mac-build.log`); final signed iOS build4 passed (`/private/tmp/kaiku-discovery-ios-build.log`).

### 2026-11-14 — Codex web new-record coverage wording
- Replaced the watch-state hint with neutral coverage-first wording that also remains accurate when zero sources
  have adequate data. Consensus states and chips are unchanged. TypeScript and production static export passed.

## 2026-11-14 06:00 — Claude Code — hardware + firmware (A): UNO Q bring-up on the real board
- Did: drove the UNO Q bench tests from the laptop (`arduino-app-cli` over adb, then SSH over Wi-Fi once the board
  moved onto the PD hub; monitor read on the board's router port 7500 because the USB serial relay drops characters).
  Board updated to App Lab 0.12 / zephyr core 1.1.0 / kernel 7.0. Python env on the board: `~/kaiku-venv` (uv, no sudo).
  Fixes: knock bench uses an interrupt; buzzer address 0x1E (7-bit); `bench/sketch.yaml` pins every library
  dependency; OpenCV < 5; `Camera.stop()` joins its thread (process abort on exit); main sketch compile error
  (`Note` used in an auto-prototype) fixed; KY-039 bench detects real beats (30–220 bpm, 0 when not steady).
  D39: no KY-054 (camera light), no KY-035 (power-on home, `HAS_HALL 0` in both firmwares, ±80° soft limit),
  `camera_index = 2`.
- Verified: buzzer PASS, knock PASS (5/5), camera PASS (opens, faces, distance, light, pulse batches), KY-053 found
  and stable at 100 Hz; main UNO Q sketch compiles (16 % flash); new KY-039 bench compiles and runs; `make check`.
- Contract changes: none.
- Broken/blocked: KY-039 found no heartbeat in open room light (Garmin 44 bpm vs a ~117 bpm flicker artefact):
  retest in the printed finger cradle. `kaiku_link` (Atech main firmware) still not ported to the SDK module format,
  so the `HAS_HALL` change there is uncompiled. The Wi-Fi allows device-to-device traffic (SSH to the board works).
- Next: A: Atech board bench tests (display, knob, button, LEDs, speaker, mic, motor), then port `kaiku_link`.

## 2026-11-14 — Xavier — firmware/atech-head [first builds on the real Atech board, Windows]
- Did: built the single-part benches with espressif32 6.9.0 and fixed what the first runs showed. Motor: `brake()`
  (both lines HIGH) kept the real motor spinning, so the bench and `HeadIO.motorBrake` use `stop()`. Display: the
  driver draws to a canvas until `display()`, so the bench calls it and the firmware uses direct mode. Speaker:
  `playTone`/`playRTTTL` interrupt, so the bench queues the ladder with `playNote`. New `bench/mic_record`: 3 s
  recording over USB to a local .wav (recordings gitignored).
- Verified: mic bench on hardware (levels rise with sound). Motor, display, speaker, mic_record benches build;
  their fixes still need a run on the board.
- Contract changes: none.
- Broken/blocked: `make` is not on Windows; atech-setup done by hand (see module AGENTS.md).
- Next: run the motor/display/speaker/mic_record benches on the board, then the link bench.

## 2026-11-14 — Xavier — firmware/atech-head, hardware [new port layout; full firmware compiles]
- Did: ports now match the build: motor 13, LED grids 11/14, button 7 (project.yaml, benches, wiring.md, module
  AGENTS.md). The full firmware compiles for the first time: `kaiku_link` is a PlatformIO library linked in place
  (`libraries: symlink://`, new `kaiku_link/library.json`; `module.yaml` removed), since an Atech module must sit on a
  real port. Knob: acceleration off (one count per click) in the bench and the firmware; the bench starts with the
  ring off. Corrected the earlier motor note: the "won't stop" run had the motor on 13 while the code drove 7.
- Verified: motor/leds/button/knob benches and the full firmware build. LED bench on hardware: grid lights on port 14,
  stays dark on port 11.
- Contract changes: none.
- Broken/blocked: port 11 (GPIO43/44, UART0) did not light the LED grid: keep a grid off it or find out why.
  Uploads sometimes fail at esptool's switch to 460800 baud; flash with `upload_speed = 115200` via
  `pio run -d build -t upload` when that happens. Knob bench not yet run on hardware.
- Next: knob bench on hardware, then the motor bench on port 13, then secrets.h + the link bench.

## 2026-11-14 07:15 — Claude Code — integration pass (all modules, lead-coordinated agents)
- Did (per module; details in each module's AGENTS.md):
  - **cloud + contracts:** `GET /v1/patients/{id}/insight` (Gemma review with per-finding validators and code-rendered
    facts, real agent trace, course of change, Gemma overview, week/usual comparison, learned routine with intervals,
    learned-layer knowledge graph, daily account, shared-only reflection summaries, coverage, state history, action
    log). One Gemma provider switch (`[gemma].provider`); deployed admin routes always need the admin token; backdated
    care actions; per-home reset; capability-aware suggestions; `remember` guard; incomplete-day totals unscored;
    context card `last_reflection` / `today_facts`; a new robot obs needs only registry + `sources.py`.
  - **calibration:** `make calibrate`; provisional early baseline from day 9 (≥5 days, lag 3, labelled), never
    "stable" before day 21, weight-0 observe-only metrics; evidence direction now comes from the days that voted.
    Numbers and limits in `docs/validation.md`. Nothing is clinically validated.
  - **games (apple, contracts, criteria, sim):** Lantern (simple reaction time), Seed shelf (symbol–digit), Watering
    (effort for reward), Pebble path kept; warm-up sessions excluded; raw trials stay on the device.
  - **apple:** mic down-mix/Bluetooth truncation/engine restart/keepalive fixes; six-step resumable setup; "Today,
    so far"; design-audit fixes; `run_on_iphone.sh --install-only` (works on a locked phone). Glasses: session start
    order fixed (`noEligibleDevice`), HFP route shown, opt-in camera frames to Gemini Live only (D43), You → Glasses
    check with self-test; test script `docs/glasses-test.md`.
  - **persona + evals:** "Meeting the feeling" attunement rules, reflection openers, `attunement.yaml`.
  - **hub + sim + tools:** pulse measured-or-missing gates, camera backup HR, drum change features, face-derived
    presence, `obs.engagement` multi-cue summary, local raw-number session store + `tools/session.py`; observations
    are queued for the cloud before the bus publish (a stop mid-publish lost one).
  - **web:** the website is the practitioner dashboard only: header strip + 9 movable/collapsible panels built on
    the insight API; person-facing web routes removed.
  - **design:** tokens v1.1.0 (state, chart, elevation, component sizes), `design/components.md`.
  - **data + bring-up:** one person's authored 16-day record through the real routes; `make demo`, `make demo-reset`,
    `make live-day`. **docs:** `track-readiness.md`, `demo-narrative.md`, tracks/submission rewritten to what the code
    supports. Merged Edwin's and Xavier's robot commits (their D35 renumbered D39).
- Verified: `make check` 794 passed; web typecheck/lint/tests/build; `swift test` 179 (8 skips); real hosted Gemma
  reviews; one real Gemini Live call with injected speech + picture; one cold Gemma call on the Modal H100
  (215 s, after giving the image the CUDA toolkit); Playwright at 1280×720, 1440×900, 1920×1080.
- Contract changes: additive only (`PatientInsight` family, `obs.engagement`, `obs.play_session` game fields, optional
  drum/pulse fields, criteria knobs, context-card fields). `SCHEMA_VERSION` unchanged.
- Broken/blocked: nothing run on the real glasses, real microphones, HealthKit or the physical robot; pulse gates
  tuned on synthetic signals; Modal GPU proven by one smoke call only (default provider stays hosted); challenge
  PDFs with venue credentials were in earlier commits of this public repo (now untracked; history not rewritten).
- Next: lead runs `docs/glasses-test.md`; redeploy the Modal API; record the video (`docs/demo-narrative.md`).

## 2026-11-14 07:25 — Claude Code — reflections end to end + daily account on the dashboard
- Did: cloud: `reflections.days[]`, fortnight summary, `course.events` kinds `reflection_low` / `reflection_lighter`,
  daily account parts with side-of-usual qualifiers and missing routines; the seeded record gains 11 short
  reflections through the episode route (labels from the rule labeller, sequence pinned in a test). web: Daily
  account panel (replaces Evidence by day) with a reflections strip; graph tile shows the top learned items.
  Modal: API redeployed (authenticated mode; admin and patient routes return 401 without a token).
- Verified: `make check` 794 passed; web typecheck/lint/25 tests/build; Playwright at three sizes; live LAN service
  restarted on this code and the record reseeded with per-home reset.
- Contract changes: additive (`reflections.days`, two course event kinds).
- Broken/blocked: no Gemma-written overview citing reflections has been observed yet (no paid call this round);
  the deployed API is not seeded (its secret holds tokens this machine does not have).

## 2026-11-14 08:30 — Claude Code — judge-review fixes, recordings, app bugs found by driving it as a user
- Did: cloud: one `status_line` reconciling rule state and course; `comparison.since_low`; seeded record reshaped
  so the flag (9 Nov, daily signals) precedes the care call and PHQ-9 (10 Nov); human names for unnamed records;
  one provenance value. web: status line under the state, since-low comparison first. demo: five paced iPhone
  simulator clips + a dashboard clip (`demo/recordings/`, git-ignored), `demo/video_shotlist.md` maps shots to clips.
  apple: Talk hang fixed (a lazy stack with a state-writing sentinel looped while the keyboard was up), honest
  voice-unavailable states, completed path stops persist, Motion asked only when a walk starts, top safe-area
  backdrop, readable Glasses check, "Continue without connecting" as the primary setup action.
- Verified: `make check`; `swift test` 183 (8 skips); the five `DemoTourTests` flows and `TalkComposerTests` on the
  simulator; install-only on the locked iPhone.
- Broken/blocked: independent review scored the entry 36–70 per challenge as it stands: no video or deck, nothing
  run on real glasses, robot or microphone, one tester. Mac screen video needs Screen Recording permission.
- Next (humans): Atech Discord post + live loop on the board; film `docs/glasses-test.md` and a real voice exchange;
  five outside testers; video (≤ 2:00) and deck; seed the Modal deployment (needs its tokens).

## 2026-11-14 09:30 — Claude Code — closing pass: public record, deck, draft cut, on-screen fixes
- Did: Modal public demo seeded (`/?id=aino`; separate secret `kaiku-demo-runtime`, volume `kaiku-demo-data`,
  spend cap $3, admin routes closed; the seed accepts our own deployed demo only when named in `KAIKU_SEED_REMOTE`
  with the admin credential). Review rejects self-contradicting overviews and directive "consider" lines;
  time-of-day measures read later/earlier. Deck `demo/deck/kaiku-deck.pdf` (12 slides, two photo placeholders).
  Draft cut builder `demo/draft_cut.py` + narration (14 s of placeholder cards for real-device shots). apple: top
  safe-area strip on every scrolling screen, newest Talk reply above the composer with the keyboard up, sprouts on
  the Seed shelf end picture, design-system rows in "What Kaiku saw".
- Verified: `make check`; `swift test` 183; simulator screenshots of each fixed screen; a Gemma-written review
  citing reflections on the live record; public URL checked from outside (dashboard 200, admin 401).
- Broken/blocked: nothing run on real glasses, robot, Atech board or a real microphone; no outside testers; the
  draft cut and deck carry placeholders; credential PDFs remain in older commits (history not rewritten).

## 2026-11-14 06:30 — Claude Code — firmware (A): both boards together on the broker
- Did: first joint run, both boards on the venue Wi-Fi, broker on the laptop, both powered from the PD hub.
  Fixes: Atech `Serial.setTxTimeoutMs(0)` after `kaiku::begin` re-inits Serial (with no host reading USB, println
  stalled the loop and MQTT keep-alive timed out); UNO Q `requirements.txt` without OpenCV/numpy (App Lab's container
  ships its own OpenCV 4.13 build, and asking for one failed the whole install, so no aiomqtt); camera index
  `-1` = auto via `/dev/v4l/by-id` (the UNO Q renumbers video0-3 between boots); exposure lock falls back to OpenCV
  when `v4l2-ctl` is missing (container). Atech flashing on this Mac needs `--no-stub` at 115200 (esptool lost the
  flash chip otherwise).
- Verified on hardware: UNO Q health ok (camera_ok, mcu_ok), knock taps, faces + distance, room light, buzzer
  chimes on `cmd.sensors`; Atech health, pan reports, button, knob press + turns, display eyes on `cmd.head`;
  Atech stays connected powered from the hub's charge-only port.
- Contract changes: none.
- Broken/blocked: knob steps feel short (tune `KNOB_COUNTS_PER_STEP` with bench/knob). Camera ring light is only
  switchable by its own touch button (datasheet §5.3), not from software. Not yet run together: pan motor (needs
  `make hub`), LED grids (port 11 dark earlier), speaker, KY-039 in the cradle.
- Next: `make hub` and the motor/LED/speaker round; tune the knob; pulse retest in the printed cradle.

## 2026-11-14 09:30 — Claude Code — firmware (A): pan motor round
- Did: two clock bugs in `kaiku_link` fixed: `tick()` read `now` before `mqtt.loop()`, so stamps set while handling
  messages (lastHubSeen, segStart, homeStart) were newer than `now` and the unsigned difference wrapped: the head
  called the hub "silent" after every heartbeat and skipped every motor segment as "already done". `now` is now read
  after `mqtt.loop()`. Softer motor start (ramp 400 ms, gesture speed 110, look 450 ms) after the speed-160 run dropped
  the Wi-Fi on the hub's charge-only port.
- Verified: after the fix the firmware runs pan / home / look / shake (dead-reckoned deg moves to +-40 and back), no
  Wi-Fi drop-outs, hub watchdog stays ok.
- Broken/blocked (Xavier): **no motor turns at all, not even a hum.** Tried 2 DC Motor modules, ports 13 and 9
  (mic unplugged, test build), 2 cables (one taken from the working button), board on the Mac's USB, and Atech's own
  `atech send motor_speed 255 / -255 / motor_brake` (our code out of the loop; board answers ok each time). Your bench
  is the only time a motor ran: how was the board powered and which port/cable/firmware? Next check needs a meter:
  Line B to GND on the motor port during `motor_speed 255` (expect ~3.3 V). The button's light is always on, so it
  can't serve as a test lamp.
- Next: find the motor power/signal fault; then pan on the hub port with the softer start.

## 2026-11-14 10:30 — Claude Code — firmware (A): standalone head firmware active (D44)
- Did: the Atech website agent's firmware (was `firmware/temp/`) is now `firmware/atech-head/standalone/`, `src/`
  verbatim; `project.yaml` lists its modules so `atech build` fetches every driver (incl. the orientation sensor and
  `i2c_software`), `build.sh` overlays `src/` and adds include shims. `make atech-standalone [FLASH=1]` (active) and
  `make atech-mqtt [FLASH=1]` (MQTT firmware, kept intact for the next stage). Both build.
- Verified on the board: flashed (`make atech-standalone FLASH=1`); boot reports all 7 modules ok (orientation
  sensor answers on 13); full ritual by hand: knob press -> greet -> mood/energy/sleep dials -> breathing -> drum ->
  done. **Only while a USB host keeps reading its serial output**: with nobody reading, the drivers' debug prints
  (`[NeoPixel] Brightness set...` many times a second) stall the loop and knob presses are missed. Opening the port
  resets the board. MQTT firmware still builds; `make check` passes.
- Broken/blocked: standalone expects an LED grid on port 7 (the button sits there now) and the motor on 11 (only
  reverse turns there); the orientation sensor on 13 is unconfirmed (asked Atech's agent).
