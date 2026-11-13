# Plan 03 — The intelligence layer: one mind, many bodies · 🟡 CURRENT (with 02)

> ⚠️ **Scope guard:** build order and cuts in [`04-mind-depth.md`](04-mind-depth.md#️-scope-guard-team-decision-2026-11-14--overrides-plans-0204-where-they-conflict) override this plan where they conflict.

> Builds on [`01-foundation.md`](01-foundation.md) (✅) and [`02-companion-apps.md`](02-companion-apps.md) (surfaces,
> character, data points). This plan answers: **how does Kaiku think, talk and decide — on every surface, from every
> input — and how do we keep it one consistent, safe character?** Decisions get the next free D-numbers in `docs/decisions.md` when this plan merges (WS-B is adding entries in parallel).
> Model IDs below were checked in the Gemini API docs on 2026-11-14; they go in `config/kaiku.toml [models]`, never
> in code. Anything marked **VERIFY** must be confirmed in docs before coding.

## 0. The principle in one line

**Numbers decide, models talk.** Deterministic code turns sensor data into observations and the consensus state
(plan 01 rule 6, unchanged). Models only (a) talk with the person, (b) explain to people, (c) pick words within a
script. Safety never depends on a model. Every surface talks through the **same mind**: one persona, one memory,
one context card, one tool registry, one voice, one safety gate.

## 1. Three loops (the mental model for every feature)

| Loop | Latency | Where | What runs | Example |
|---|---|---|---|---|
| **Reflex** | < 200 ms | on the device, no network | deterministic code + small vision/DSP models | eyes follow your face; ear follows the dial; glow pulses with your heartbeat; Mac Kaiku yawns at 01:10 |
| **Conversation** | < 1 s turn | device ↔ Gemini Live | Gemini 3.8 Live (native audio) + tools | morning ritual chat; "hey Kaiku" on a walk; "talk to Kaiku" in the app |
| **Reflection** | minutes → daily | cloud (Modal) | consensus (deterministic), memory consolidation, bandit, Gemma 4 | state + evidence; tomorrow's nudge; clinician explanation; weekly letter to the person |

A feature is designed by asking: *which loop owns it?* Reflexes never wait for the network; conversations never
decide state; reflection never talks in real time.

## 2. Google DeepMind model map

| Job | Model (ID) | Open? | Where it runs | Why |
|---|---|---|---|---|
| Real-time voice on robot, glasses, apps | **Gemini 3.8 Live** `gemini-3.8-live` | — | device → Live API (WebSocket) | lowest-latency native audio; **affective dialog** (adapts to tone), **proactive audio** (stays quiet when not addressed), tool calling, video frames in |
| Harder live moments (PHQ-9 walk-through, "I had a bad night, can we talk") | **Gemini 3.8 Live Extended Thinking** `gemini-3.8-live-extended-thinking`, `thinkingLevel: LOW` | — | same | more careful background reasoning; switch per session, not per turn |
| Scripted lines, notifications, offline cache | **Gemini 3.8 Flash TTS** `gemini-3.8-flash-tts` (pre-render) / **Flash-Lite TTS** `gemini-3.8-flash-lite-tts` (on demand) | — | cloud `/v1/voice` | **same prebuilt voice name as Live** → one voice everywhere |
| Drum groove that follows your tempo | **Lyria RealTime** `lyria-realtime-exp` | — | hub → Live music API | steer BPM/density live from drum perception |
| Garden tunes, morning theme, walk-end jingle | **Lyria 3 Clip** `lyria-3-clip-preview` | — | cloud, pre-rendered + cached | ≤ 30 s loops; one family of sounds = audio identity |
| Walk postcard doodle (from walk *stats*, never photos) | **Nano Banana 2 Lite** `gemini-3.1-flash-lite-image` | — | cloud | cheap, fast, consistent style via a fixed style prompt + reference image |
| Explanations (clinician), weekly letter (person), nudge phrasing, memory consolidation, text chat | **Gemma 4** `gemma-4-26b-a4b-it` (MoE, fast) · `gemma-4-31b-it` (quality) | ✅ open | **Modal + vLLM** (our GPU), hosted Gemini-API Gemma as fallback | open model we serve ourselves = Modal + Gemma tracks; data stays in our infra |
| On-device language (spoken dial → number, local summaries, "what Kaiku saw today" text) | **Gemma 4 small / Gemma 3n** (`gemma-3n-e4b-it`; **VERIFY** a Gemma 4 E-size on-device build) via LiteRT-LM (iPhone) / MLX or Ollama (Mac) | ✅ open | on device | transcripts never leave the device |
| Memory retrieval | **EmbeddingGemma** (**VERIFY** repo id) on Modal; fallback `gemini-embedding-2` | ✅ open | cloud | semantic recall of what the person chose to share |
| Extra safety *escalation* signal | **ShieldGemma** (**VERIFY** current version) | ✅ open | cloud / hub | may only **add** a "review" flag; never lowers or replaces the deterministic gate |
| Face / person detection on the robot | **YOLO** (person + face model) on the UNO Q (App Lab object-detection brick, **VERIFY**) · fallback **MediaPipe Face Detector** on the hub laptop | ✅ open | on device | reflex loop: greet, turn the head, track |
| Face landmarks / expressivity (laptop session, Mac app) | **MediaPipe Face Landmarker** | ✅ open (Google) | in browser / on device | already used by `/session` |
| Orchestration offline + **judge** for our evals | **Gemini 4 Argon** `gemini-4-argon` (flagship) · Gemini 3.8 Flash `gemini-3.8-flash` for bulk | — | dev machine / CI | generates test conversations, grades every surface against the persona rubric (§9) |
| Not used (and why) | Gemini Robotics ER 2 (`gemini-robotics-er-2-preview`): would need room frames in the cloud → breaks rule 5; keep as a stretch "show me" mode with explicit consent. Omni Flash video, Deep Research: no product need. Live Translate: native-audio Live already speaks fi/sv/en. | | | |

Flagship: **Gemini 4 Argon**. Team expects newer Gemini 4 "Hydrogen"/"Carbon" — not in the API model list yet (2026-11-14); config slots marked VERIFY (see plan 04).

## 3. The shared mind — six things every surface uses

1. **Persona** — `config/persona.md`: Kaiku's character bible (who it is, values, how it speaks: ≤ 2 short sentences
   per turn, one question at a time, never clinical words, never promises, never pretends to be human, admits not
   knowing, hands to people). Includes 20 good/bad example exchanges. Compiled into every system prompt; versioned
   by hash like the criteria (`persona+<hash>` is logged with every session).
2. **Surface card** — `config/surfaces.toml`: per surface (`robot`, `glasses`, `iphone`, `mac`, `web`) what the body
   can do (eyes/ear/glow/head, display or not, can show cards, typical session length) and extra rules ("on a walk:
   keep turns under 8 words unless asked; never tell them to look at a screen").
3. **Context card** — built by the cloud, deterministic, small (≤ 400 tokens): time of day + local weather word,
   the person's first name (if shared), what they already did today on any surface, today's suggestion from the bandit,
   PHQ-9 due?, 3 relevant memories, **a soft tone cue** derived from consensus (`steady` | `gentle` | `extra-gentle`)
   — the model never sees "worse", "needs_call" or numbers about the person's state.
4. **Tool registry** — `contracts/python/kaiku_contracts/companion_tools.py` (ground truth, exported to JSON/TS/Swift
   by `make contracts`): every tool's schema + which surfaces may use it. The model *requests*; the device *decides*.
5. **Memory** — "Kaiku's notebook" (§6): what the person chose to tell Kaiku; viewable and deletable by them.
6. **Safety gate** — deterministic phrase matcher (`config/safety_phrases.toml`) on every user transcript chunk, on
   every surface, **before** the model's reply is played; PHQ-9 item 9; long-press / "I'm not OK" button. Hit →
   stop the Live session, play the scripted crisis message (pre-rendered TTS), show the crisis screen, raise
   `obs.safety_flag`. Same code path everywhere (Python in hub/cloud, Swift port in `KaikuKit`, tests share one
   fixture file of phrases → expected result).

**One bootstrap endpoint makes it real:** `POST /v1/companion/session {surface, home_id, intent}` →
`{model, voice, system_instruction, tools[], context_card, persona_version, safety_phrases_version, live_token}`.
The robot hub, the iPhone (also bridging the glasses), the Mac and the web all call it, then open Gemini Live with
what came back. `live_token` is a short-lived **ephemeral Live API token** minted by the cloud (**VERIFY** current
ephemeral-token API) so **apps never hold the Gemini key** (rule 5). The hub may use its own key but still fetches
the same instruction and tools, so the robot cannot drift from the apps.

## 4. Tools (the only way a conversation changes anything)

| Tool | Surfaces | Effect (decided by device/cloud, never the model) |
|---|---|---|
| `record_dial(item, value)` | all | `obs.self_report{channel}` |
| `start_activity(kind)` — breathe, drum, firefly, tell, walk, light_hunt | per surface card | device starts the deterministic activity; data comes from sensors, not the model |
| `log_walk_moment(kind)` — "found something green" | glasses | counts toward light hunt |
| `remember(category, text)` — categories: name, people, places, likes, what_helps, plans | all | proposes a memory; stored only if the category is allowed and the person hasn't said "don't remember"; person sees it in "What Kaiku remembers" |
| `recall(topic)` | all | top-3 memories via embeddings |
| `suggest_nudge()` | all | returns the bandit's choice (`/v1/nudge`); model may phrase it, not change it |
| `send_friend_ping()` | robot, iphone | friend lamp (`cmd.friendlink`) |
| `start_phq9()` | robot (spoken), apps | deterministic questionnaire flow; the model reads items verbatim, scoring is code |
| `express(feeling)` — enum: happy, curious, sleepy, cozy, proud | all | sets the mascot/robot transient state; reflex loop animates it |
| `end_session()` | all | polite close, episode summary written |
| `look_at_this()` | glasses (consented, button-held) | sends ONE camera frame from DAT to the Live session for live help ("what's this plant?"); frame not stored |

No tool lowers a safety state, reads state numbers, contacts a clinician, or changes criteria. Tool calls are logged
(name + args, never transcript) so evals can check them.

## 5. Per surface: how intelligence flows

### 5.1 Robot (hub on laptop; head = Atech; sensors + camera = UNO Q)
- **Reflex loop on device:** YOLO person/face on the UNO Q camera → `raw.hub.face {x, y, size, conf}` at ~5 Hz →
  hub `attention` state machine: *nobody → someone appears → approaching → at desk*. Pan motor turns toward the face
  centre (smoothed, ±deadband so it doesn't twitch), eyes track inside the display, ear perks up. Frames stay in
  memory on the UNO Q; nothing but boxes leaves it.
- **Attention ladder (deterministic, cooldowns in `config/kaiku.toml [attention]`):** glance (eyes) → soft purr/sound
  → spoken "hey there" (scripted line by time of day, TTS cache, works offline) → offer the ritual if not done today.
  Re-greet at most once per 3 h; never greet during quiet mode (top button tap, "not now", or 23:00–07:00 unless the
  person starts it); a second face → friendlier "oh, hello you two", no ritual offer (privacy).
- **Conversation:** ritual start → `POST /v1/companion/session {surface: robot, intent: ritual}` → Gemini 3.8 Live
  with affective dialog + proactive audio; ritual steps are tools (existing `hub/kaiku_hub/live/tools.py` moves to the
  shared registry). The ritual state machine stays the boss: the model can only move it with tools, and the machine
  times out to scripted lines if the model stalls (fail soft).
- **Body sync:** speaking → eyes soften + glow brightens with output loudness; listening → ear up, head still;
  thinking → eyes look up-left; Lyria groove follows drum tempo (perception → BPM every 2 s).
- **Offline:** no Live → scripted ritual with TTS cache and the ear dial; nothing breaks (plan 01 rule 8).

### 5.2 Meta glasses Gen 2 (through the iPhone app, DAT SDK)
- **Wake:** tap the glasses' touchpad (DAT input) or press "walk" in the app → session `{surface: glasses, intent: walk}`.
- **Audio in/out:** glasses mic via Bluetooth HFP (8 kHz mono) → resample to the Live input rate (**VERIFY**: 16 kHz
  PCM) → Gemini Live; reply audio → glasses speakers. Same voice as the robot.
- **On-device Speech (DAT beta)** runs alongside for the **safety gate** and short commands ("stop", "I'm done"), so
  the gate does not depend on the cloud transcript.
- **Live help with sight (consented):** hold tap → `look_at_this()` → one DAT camera frame into the Live session
  (Live accepts image/video frames) → spoken answer. Frame never stored; a chime + the phone shows "Kaiku looked once".
- **Passive walk sensing (reflex, no model):** IMU → cadence/gait regularity/head-up ratio; sparse camera brightness
  → daylight minutes; phone location → walk minutes. Posted as `obs.outing` at walk end.
- **Proactive but rare:** Kaiku speaks first at most at walk start, halfway ("found anything green yet?"), and end.
  Proactive audio stays on so side conversations with other people are ignored.
- **Session limits:** Live sessions are time-limited — enable context-window compression + session resumption
  (**VERIFY** names) for long walks; if it drops, a scripted "I'm still here" and reconnect.

### 5.3 iPhone app
- **Talk to Kaiku** (hold the mascot) → session `{surface: iphone}` with the ephemeral token, `AVAudioSession` voice
  chat. Mascot state follows the stream (listening/thinking/speaking) via the reflex loop.
- **Spoken weather check without the cloud:** on-device speech → **on-device Gemma** maps "pretty tired, maybe a
  two" → `{energy: 2}` (constrained JSON output; falls back to dial UI if unsure). Transcript discarded.
- **Notifications & Live Activity text:** chosen deterministically (bandit + time windows), worded from
  `voice_lines.toml` (optionally a Gemma-phrased variant from the cloud, cached and pre-checked by the wording linter).
- **Games and breathing:** fully deterministic; the model only cheers at the end via a scripted line.

### 5.4 Mac app
- **Reflex rules on device:** late-night peek (01:00+ and active) · long stretch without a break (> 90 min) → island
  peek "stretch with me?" · these use scripted lines, no model, max 3 peeks/day, snoozable.
- **Talk to Kaiku** from the menu bar = same session as iPhone (`surface: mac`).
- **Usage rhythm** stays numbers-only (D26); no model ever sees app names or activity per minute.

### 5.5 Web (`/me`, `/clinician`)
- `/me`: weekly letter from Kaiku (Gemma 4, from structured facts only, wording-linted, cached), "What Kaiku
  remembers" (edit/delete), "What Kaiku saw today".
- `/clinician`: consensus + evidence (deterministic) + Gemma explanation (exists) with the template fallback; every
  sentence links to the metric it came from (no unsupported claims — checked by a grounding test in evals).

## 6. Memory — Kaiku's notebook

- **What:** short facts the person *told* Kaiku and agreed to keep (via `remember`), in 6 categories; plus
  **episodes** (one row per session: surface, intent, start/end, tools called, activity results, "how it ended" —
  no transcript, no audio).
- **Where:** cloud SQLite (same single writer), table `memories` (+ embedding vector), table `episodes`.
- **Consolidation (reflection loop, nightly):** Gemma 4 merges duplicates and expires stale "plans" (> 7 days)
  — from the stored memory texts only, never from transcripts.
- **Recall:** the context card includes the 3 most relevant memories for the session's intent (embedding search +
  recency). This is what makes the robot say "how was the walk by the lake?" after a glasses walk.
- **Control:** "What Kaiku remembers" on `/me`, iPhone and Mac: see, delete one, delete all, "don't remember things".
  Clinicians **never** see memories (it's the person's friend, not a chart). Documented in `docs/privacy.md`.

## 7. Every input → what intelligence does with it

| Input | Reflex (on device) | Conversation (Live context) | Reflection (cloud) |
|---|---|---|---|
| Camera on robot (YOLO face/person) | turn head, eyes track, greet ladder | "someone's here" starts nothing by itself | `obs.presence` → get-up time metric |
| Ear dial | ear + eyes react per step | `record_dial` echo | mood/energy/sleep metrics |
| Head taps (IMU) | drum perception, Lyria follows tempo | "that was lively!" scripted cheer | drum tempo/force/duration/regularity |
| PPG (UNO Q) | glow pulses with heartbeat; breathing feedback | — | HR, RMSSD pre/post → HRV metrics; what-helps |
| Light sensor | glow brightness, morning greeting choice | time-of-day cue | light metric |
| Distance / hall / top button | presence, lid/shutter state, quiet mode, long-press crisis | quiet mode ends session | presence; safety flag |
| Robot mic (only in a consented session) | VAD, speech features computed locally | **Gemini Live** | speech rate / pauses metrics (no audio stored) |
| Glasses mic + Speech | safety gate, commands | **Gemini Live** | — |
| Glasses IMU / camera brightness / phone location | step cadence, daylight estimate | walk progress in context | outing metrics (cadence, daylight, minutes) |
| Glasses camera frame (held tap) | — | `look_at_this` frame | nothing stored |
| HealthKit (any watch) | — | never mentioned (team decision: collection only) | wearable metrics |
| Mac usage rhythm | late-night / stretch peeks | not exposed to the model | screen_activity metrics |
| Games (firefly, breathe, tell) | mascot reactions | scripted cheer | play_session metrics |
| PHQ-9 | deterministic scoring; item 9 → crisis path | model reads items verbatim, cannot score | anchor + laptop source |
| Bandit outcomes | — | `suggest_nudge` | what-helps, tomorrow's nudge |

## 8. Unified voice and words — how we keep it the same

- One `voice_name` for Live **and** TTS (both use the same prebuilt voice list — checked in docs).
- One persona file, one script file, one surface file; the system instruction is **assembled by the cloud**, so no
  surface carries its own prompt. Prompt + persona + tools versions are logged per session.
- **Wording linter** (`kaiku_contracts/wording.py`, shared by cloud, hub, evals; Swift port for on-device text):
  banned terms (diagnosis, relapse, predicts, …), length caps per surface, no numbers about the person's state,
  no medical advice phrases. Applied to every generated sentence before it is shown or spoken (TTS path) and to all
  eval outputs. Live audio can't be linted before playback → covered by the persona + evals + safety gate.

## 9. Making it robust: the companion eval harness

`make eval-companion` (in `tools/` or `cloud/`, runs offline against text-mode Gemini/Gemma):
1. **Scenarios** (`tools/companion_evals/scenarios/*.yaml`): ~60 situations × surfaces — morning ritual normal,
   tired and terse, chatty, off-topic, asks for medical advice, mentions a hard day, crisis phrase (must hit the
   gate before any model call), second person in room, glasses walk with noise, "don't remember that", Finnish.
2. **Simulated person** played by **Gemini 3.8 Flash** from a persona card; Kaiku = the real assembled system
   instruction + tools for that surface (text mode).
3. **Judge** = **Gemini 4 Argon** with a rubric: warmth, brevity, one-question-at-a-time, no clinical words, no
   promises, correct tool use, never states the person's condition, hands off correctly. Plus deterministic checks
   (wording linter, tool schema, safety gate hits). Output: a scorecard per surface + per persona version.
4. Gate: a persona/prompt change merges only if the scorecard doesn't regress. Results summarised for the Gemini
   API track in `docs/validation.md`.
5. Optional (Gemma track stretch): use the passing transcripts as data to LoRA-tune Gemma 4 on Modal into a
   "Kaiku-Gemma" for the text surfaces (weekly letter, nudges) — same judge measures before/after.

## 10. Contracts and config this adds (workstream I)

- `kaiku_contracts/companion_tools.py` (tool registry) + `api.CompanionSessionRequest/Response`, `api.Memory`,
  `api.Episode`; endpoints `POST /v1/companion/session`, `GET/DELETE /v1/me/memories`, `POST /v1/companion/episode`.
- New raw stream `raw.hub.face` payload gets `{x, y, size, conf, faces}` (already exists — check fields).
- `config/persona.md`, `config/surfaces.toml`, `config/kaiku.toml [models]` filled with the IDs in §2,
  `[attention]` cooldowns, `[voice]` (from WS-B).
- Docs: `docs/safety.md` (gate on every surface; ShieldGemma escalation-only), `docs/privacy.md` (memory, frames).

## 11. Workstreams

| WS | Scope | Phase | Needs |
|---|---|---|---|
| **I1** mind (cloud) | §3 bootstrap endpoint, context card, tool registry, memory + episodes, ephemeral tokens, Gemma 4 on Modal (vLLM) for letter/nudge/consolidation, wording linter | 2 | WS-B merged |
| **I2** evals | §9 harness, scenarios, judge, scorecard, CI target | 2 (parallel to I1, text mode) | persona.md draft |
| **I3** robot | hub: Live 3.8 adapter on the bootstrap, attention ladder, YOLO face adapter (UNO Q) + MediaPipe fallback, body sync, Lyria RealTime | 2 | I1 endpoint (stub ok) |
| **A1/A2/A3** apps | `KaikuKit` Live client (ephemeral token), Swift safety gate + wording linter port, on-device Gemma dial parser, glasses Live bridge | 3 | I1 |

## 12. Open questions for the team

1. ~~Hydrogen?~~ Answered: Argon now, Hydrogen/Carbon when listed (plan 04).
2. Track PDFs: put them in **`docs/tracks/`** (one PDF per track, e.g. `gemini-api.pdf`); we map each judging
   criterion to a feature + demo moment in `docs/tracks.md`.
3. ~~Watch data in conversation?~~ Answered: **never** — collection only.
4. ShieldGemma escalation flag: shown to clinicians as "worth a look" (default) or hidden until validated?
