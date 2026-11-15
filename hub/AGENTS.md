# hub — AGENTS.md

> Read the root `AGENTS.md` first. Owner B · kind node · consensus source 1 of 3 ("robot"). Update this file in the
> same commit as any change to the hub's interface, structure or invariants (and `modules.toml` if what it
> emits/consumes changes).

## Purpose
The robot's brain, running on the hub laptop. Notices people with a deterministic **attention ladder**
(`nobody → appeared → approaching → at_desk`: glance → purr → keyed greeting → ritual offer), turns local raw
streams into derived `obs.*` (perception), runs the morning ritual state machine `IDLE → GREET → DIAL(mood, energy, sleep) → BREATHE → DRUM(+ post-activity mood) →
[PHQ9 if due] → NUDGE → CLOSE`, runs the deterministic crisis gate (no LLM), drives the voice/music adapters, and
ships observations to the cloud (offline-safe). Raw data never leaves the home. Glasses and laptop apps do NOT come
through the hub — they post to the cloud directly.

## Boundaries
May import `kaiku_contracts` + third-party libs only — never `cloud`, `sim`, `apps`, `tools`.

## Consumes (topics/endpoints)
| Topic / endpoint | Used for |
|---|---|
| `kaiku/v1/<home>/raw/head/tap` | drum step (tempo, force, regularity); `force` absent for the KY-031 knock switch → `force_mean: null`. Tap it back: her turn's taps. A tap may be reported by two boards (UNO Q knock, source `sensors`, and the head's motion sensor, `src: imu`) on two clocks that cannot be compared: the hub takes the first source it hears and ignores the other until that one has been quiet for 3 s (`perception/tap_back.OneTapSource`), so one tap is never counted twice |
| `kaiku/v1/<home>/raw/head/ear` | dial answers (`value` = dial position 1–5, each `pressed` answers the current question: mood → energy → sleep); post-drum mood; spoken PHQ-9 (dial 1→0 … 4–5→3); press when idle → ad-hoc mood. Every press also stops what Kaiku is saying at that moment (`GeminiLiveVoice.quiet`): the robot's microphone is shut while its speaker plays, so she cannot talk over Kaiku there |
| `kaiku/v1/<home>/raw/sensors/ppg` | breathe step pulse (only streamed between `cmd/sensors {ppg:start/stop}`): KY-039 100 Hz → HR + RMSSD (`method: finger`); camera backup ~15 Hz at a wobbling measured rate → resampled, HR only (`method: camera`, quality ≤ 0.6) |
| `kaiku/v1/<home>/raw/sensors/distance` | presence → `obs/presence` + the attention ladder (no camera = presence alone means "at desk"). On the build it is the UNO Q's estimate from the face box (`far_cm` = no face): a face turned away for `[hub] presence_leave_s` = left; no reading for `presence_stale_s` = unknown, not "here" |
| `kaiku/v1/<home>/raw/sensors/light` | `obs/light_level` (hourly mean) |
| `kaiku/v1/<home>/raw/sensors/button` (`id: "top"`), `raw/head/button` (`id: "head"`) | short press idle → start ritual; hold ≥ 2 s → crisis (manual); button build (`[robot] dial_input = "button"`): short presses during a ritual → one dial answer per run (`perception/presses.py`, `press_window_s`), fed as the ear event below |
| `kaiku/v1/<home>/raw/sensors/face_signs` | Photo time (`rituals/photo_time.py`): started by the voice tool `photo_time` or `cmd/hub {photo_time: true}`; the hub says "Photo time!", sends `cmd/sensors {face_signs_s}` (`[photo_time] seconds`), and turns the board's one answer into `obs.face_signs` (task `photo_time`, device `robot`, method `haar_cascades`). No picture; no face in the window is a normal result; the voice model is never told how the face looked. Tests: `tests/test_photo_time.py`. Not yet run on the robot |
| `kaiku/v1/<home>/raw/hub/face` (source ≠ `hub`) | attention ladder (one message per face per frame; UNO Q YOLO or sim) + greet step looks at the face |
| `kaiku/v1/<home>/audio/head/mic` (**binary, not an envelope**) | the head's microphone: 640-byte frames (16 kHz mono 16-bit, 20 ms), only while the hub holds it open for a consented Live conversation; passed to Gemini Live and nowhere else. Frames that come while no conversation holds it open are dropped unread |
| `kaiku/v1/<home>/audio/phone/mic` (**binary, not an envelope**) | a phone or Mac beside the robot standing in for the head's microphone (D56; the app's "Robot microphone" switch): the same 640-byte frames, sent by the app only while the hub holds the microphone open. `HeadAudio.on_phone_frame`: dropped unread with no conversation open; dropped while the head's speaker has sound of ours and `[voice] phone_mic_tail_ms` (400) after, so Kaiku never hears herself; while phone frames arrive (the last 2 s) the head's own frames are ignored. `health/hub` `details.mic_source`: `phone` or `head`. |
| `kaiku/v1/<home>/cmd/hub` | `start_ritual`, `say` (text utterance, safety-gated), `suggest_nudge`, `set_ritual_time`, `clinician_message`, `phq9_due` |
| `kaiku/v1/<home>/cmd/friendlink` | `ping` → LoRa gateway |
| `kaiku/v1/<home>/obs/#` (non-hub sources) | `obs/phq9` with `item9_positive` → crisis; relays other local obs (e.g. friendlink sim) to the cloud |
| `kaiku/v1/<home>/health/+` | node heartbeats → `PUT /v1/health/{home}`; `health/head` with `details.firmware: standalone` switches the hub to **follow mode** and `details.step` is the head's ritual step |
| `kaiku/v1/<home>/cmd/sensors` (source `head`) | follow mode: the standalone head's chimes mark its step changes (`wake` = greet, `start_drum`, `end_drum`) |
| `kaiku/v1/+/health/head` | a head publishing under another home id → one `head_on_other_home` warning naming the setting |
| `GET /v1/commands?home_id` | pending cloud commands; apply locally, then acknowledge; repeated delivery is deduped |
| `GET /v1/nudge?home_id` | bandit arm (falls back to clinician suggestion, then uniform random) |
| `GET /v1/voice/{key}?lang=` | greeting audio in the one Kaiku voice (404/503/offline → visible text) |
| `POST /v1/companion/session` | `{surface: robot, home_id, intent: ritual}` → authorized Live bootstrap + duration; missing/unauthorized bootstrap keeps microphone closed |
| `POST /v1/voice/say` | scripted non-crisis fallback in the same Gemini voice; unavailable → visible text |
| `POST /v1/companion/tool` | registry tools with `executor: cloud` (incl. `ask_mind`); `end_session` uses durable episode completion instead; body shows `thinking` while in flight, 8 s cap except configured Gemma mind timeout |

## Emits (topics/endpoints)
| Topic / endpoint | When |
|---|---|
| `obs/ritual` | every step: `started` then `completed` / `skipped` / `aborted` with `duration_s` |
| `obs/presence` | confirmed arrival (`first_of_day` = get-up proxy) |
| `obs/self_report` | dial step ×3 (`item: mood/energy/sleep`, `context: ritual`), after drumming (`mood`, `post_activity`), ear press when idle (`mood`, `adhoc`) |
| `obs/intervention_response` | breathe (`pre/post rmssd_ms + hr_bpm`, first/last 30 s of PPG) and drum (`pre/post mood`) |
| `obs/phq9` | spoken PHQ-9 (`mode: spoken`) when due and `[ritual] phq9_mode` is `spoken`/`both`; item 9 > 0 → crisis path |
| `obs/hrv_session` | breathe step, only if the recording is a pulse (see Invariants → PPG integrity); `quality` = min(clean-beat ratio, sensor quality); `method`, `beats`. Otherwise nothing: "not measured" |
| `obs/tap_back` | drum step when it was the game "Tap it back" (D51), once, when the game ends and before the post-activity mood question: per level the song's tempo, her tempo, the error in percent, steadiness, taps, band, tries; `levels_played/passed`, `duration_s`, `song` (`music`/`beat`/`light`). Only if at least one level was played to its turn. A game day emits **no** `obs/drum_session` |
| `obs/drum_session` | free drumming only: drum step with ≥ 4 taps, emitted when drumming ends (before the post-activity mood question): tempo, regularity, taps, first/last-third tempo, `taps_per_s`, `pauses`, `rejected_taps`; `quality` = share of triggers that were real taps |
| `obs/engagement` | once at the end of a ritual whose conversation the person accepted (never after a crisis): the multi-cue summary (Invariants → Engagement summary) |
| `obs/nudge_offered`, `obs/nudge_outcome` | nudge step; outcome after the next day's dial (`next_day{mood, energy}`, reward in 0–1) |
| `obs/light_level` | legacy opt-in only (`[perception] light_enabled=true`), capture-ordered usable light window; actual capture timestamp and lowest reported sensor quality retained |
| `obs/speech_features` | completed consented user speech: numeric pace/pause features only; silence, clipping, speaker overlap or capture gaps remain missing |
| `obs/friend_link` | LoRa ping sent/received |
| `obs/safety_flag` | any crisis trigger (priority uplink, deduped per trigger for 60 s) |
| `cmd/head`, `cmd/sensors` | attention: `eyes` glance/`listening`, `look` + `pan{target_deg}` tracking (smoothed, deadband, ≤ 5 Hz), `purr`, `home`; ritual: eyes, pan_mode, chest, purr; `ppg: start/stop`; `camera_enable` (unoq_yolo). Tap it back: `eyes` + `chest: pulse` + `bpm` + `pan_mode: sway` while the song plays, `eyes: wide` + `pan_mode: still` for her turn, the band's face; `cmd.sensors {chime: start_drum}` at "your turn", `ok` / `end_drum` with the band. `cmd.head {mic: open}` every 2 s while a Live conversation uses the head's microphone, `{mic: close}` after (and for the whole of a Tap it back game). Crisis: `cmd.head {show: help}` (the head's own help screen), `{show: none}` when the next ritual starts. Follow mode: `cmd.head {drum: hold, ...}` at least every 3 s while the hub runs the head's drum step, `{drum: end, pan_mode: still}` after (the only `cmd.head` a self-running head gets, besides `mic`, `show` and the calm eyes of a crisis) |
| `raw/hub/trace` (**local only**, QoS 0, never uplinked or stored) | what Kaiku says and does, live, for the "Kaiku bot" tab of the person's own apps: Kaiku's own lines (`said`), that she spoke (`heard`, nothing else), the name of a tool the voice called (`tool`), a conversation opening or closing (`session`), the game's cues and bands (`game`), music (`music`). See Invariants → Trace |
| `kaiku/v1/<home>/audio/head/speaker` (**binary, not an envelope**) | everything the robot sounds: the drum music, the game's chimes, Kaiku's Live voice, the scripted lines in the cached voice. 640-byte frames (16 kHz mono 16-bit, 20 ms), one every 20 ms, 80 ms ahead of real time; a zero-length message = "drop what you have buffered" |
| Live context events (not a topic) | `Voice.send_context("[drumming · lively]")` into the open Live session — fixed vocabulary, see Invariants |
| `health/hub` | retained heartbeat every 5 s (ritual state, uplink queue/lag/error, adapters) |
| `POST /v1/companion/episode` | durable completion outbox, stable id, outcome/tools; transcripts only with explicit `[live] hub_transcripts` consent, never on crisis |
| `POST /v1/commands/{id}/ack?home_id=` | acknowledge after local application; retry ack on redelivery without applying twice |
| `POST /v1/events` | batched obs (Bearer `KAIKU_HOME_TOKEN` if set) |
| `PUT /v1/health/{home_id}` | every 10 s: all node heartbeats + uplink queue/lag |

Obs are marked `sim: true` when they were derived from sim inputs in the last 60 s.

## Map
```
kaiku_hub/
  main.py          Hub: wiring + RitualContext impl (say/head/sensors/emit/get_nudge), bus handlers,
                   crisis(); emit() is the ONLY way obs leave (validate -> bus -> uplink; PHQ-9 safety check)
  settings.py      config/kaiku.toml + env -> Settings dataclass (all timings/thresholds/model IDs)
  attention.py     attention ladder (pure, deterministic): faces + presence + quiet + time -> head/say/offer actions
  state.py         small persistent JSON: last arrival, today's dial, pending nudge, phq9_due, ritual time
  rituals/
    machine.py     generic step runner: applies / enter / handle / on_deadline / on_timeout / exit, skip,
                   abort, exact named-step selection, hard cap, stop_ritual, broken-step isolation
    steps.py       Greet, Dial, Breathe, Drum (free drumming, or the game), Phq9, Nudge, Close + default_steps(settings)
    tap_back.py    Game: the flow of Tap it back and every line it says; no clock of its own (tick / on_tap), run by
                   the Drum step and by Hub._follow_game (a head that runs its own ritual)
  perception/      taps.py, hrv.py (PpgBuffer.pre_post / session), presence.py, light.py, speech.py, face.py,
                   engagement.py (EngagementTracker + fuse: the multi-cue summary, pure),
                   tap_back.py (Tap it back, pure: TapBackConfig, level_plan by date, score_try -> band,
                   the obs.tap_back payload, OneTapSource)
  store.py         SessionStore: local SQLite of each ritual's raw numbers + emitted obs (never uplinked)
  follow.py        HeadFollower (pure): shadow of a standalone head's ritual -> the same obs, held dial answers,
                   partial rituals; Hub._follow_do executes its actions. STEP_LINES: what Kaiku says at each of
                   the head's steps in a follow-mode conversation
  safety/gate.py   SafetyGate (phrases en/fi/sv, PHQ-9 item 9), ButtonLongPress, CrisisScript (verbatim)
  live/            base.py (Voice/Music interfaces; open_session/close_session per ritual), factory.py,
                   text.py, gemini_live.py (configured model, automatic VAD/barge-in, bounded resumption, [voice].name),
                   lines.py (keyed cloud Gemini cache + dynamic Gemini TTS -> the head's speaker or this machine's
                   player -> visible text), lyria.py, local_audio.py,
                   player.py (PlayedMusic: the queue-and-play loop every music adapter shares, song/hush/chime, WavOut),
                   sounds.py (the game's chimes and the hub's own beat, synthesised),
                   head_audio.py (the head's speaker and microphone over the bus: Resampler, HeadSpeaker = the one
                   paced sender, HeadStream in sounddevice's two shapes, HeadMic, HeadAudio, AutoAudio),
                   tools.py (local fallback tools + system prompt),
                   context_events.py (T5: fixed vocabulary, rate limit/dedupe, DrumFeel, breathing/light/late rules),
                   meter.py (SessionMeter: Live/Lyria spend on the kaiku_contracts.budget ledger)
  devices/         atech_adapter.py (stub), lora_serial.py (friend link), camera.py,
                   unoq_yolo.py (face source: UNO Q App Lab boxes; interface for owner A + box_to_face)
  uplink.py        SQLite offline queue, batches, backoff, safety_flag priority lane, obs-only
  cloudlink.py     command polling/ack, nudge lookup with fallback, node-health reports
  episodes.py      SQLite completion outbox next to uplink DB; idempotent replay after restart
tests/             unit + contract tests per area; test_integration.py = full ritual over a real mosquitto
```

## Extension points
- **Add a ritual step:** subclass `rituals.machine.Step` in `steps.py`; `name` must be a contracts
  `RitualStep` (add it there first, `make contracts`); implement `enter/handle/exit` (+ `applies` if
  conditional, `on_deadline` for multi-phase steps); add to `default_steps()`; add its timing to
  `[ritual]` in `config/kaiku.toml` + `settings.py`; tests in `test_rituals.py`. Steps only use the context —
  no bus/HTTP — so they stay unit-testable with `FakeCtx` (`tests/conftest.py`).
- **Add a perception module:** pure function/class in `perception/` (no I/O), fed from `Hub.on_raw`, emits via
  `Hub.emit("obs.<type>", payload)`. New obs type → contracts first (root rule 4).
- **Swap voice/music vendor:** implement `live/base.Voice` / `Music` in a new file, select it in
  `live/factory.py` by `KAIKU_VOICE` / `KAIKU_MUSIC`. Must fail soft (fall back to cached Gemini audio/visible text). Model IDs in
  `config/kaiku.toml [models]` only. Tool names/semantics live in `live/tools.py`; `Hub.on_tool` maps them.
- **New face source:** anything that publishes `raw.hub.face` (one message per face per frame, source ≠ `hub`)
  works with no hub change; select local sources by `[attention] face_source` in `Hub.__init__`.
- **Add a device adapter:** `devices/<vendor>.py` converting vendor I/O ↔ contract messages, selected by env
  (`KAIKU_HEAD=atech|sim` style), with a sim twin in `sim/nodes/`.
- **Remove a piece:** steps, adapters and perception modules are independent; delete + drop from
  `default_steps()` / `factory.py` / `Hub.__init__`, then `make test`.

## Invariants
- **Safety runs first and is deterministic:** every utterance goes through `SafetyGate.check_text` before
  anything else; every `obs.phq9` passing through `emit()`/`on_obs()` is checked for item 9. `safety/` imports
  no LLM/network code (a test enforces it). The crisis message is displayed verbatim from `config/safety_phrases.toml`; it is never sent to generative TTS.
  OS synthetic speech is removed. A deterministic pre-recorded crisis audio asset is still needed for audible crisis guidance.
- **Cues are never spoken** (`live/gemini_live.py`): a line for Live to say goes out only as `[say] <line>`, a
  senses event as `(context from Kaiku's senses, …) <event>`, and every session's system instruction gets `CUE_RULES`
  (cues are private; never read, quote or describe the instructions). An answer whose transcription repeats a cue or
  the instructions (`LEAK`) is cut at once and the `say` line is said in the cached voice instead (`gemini_cue_leak`).
- **Every emitted message validates** (`make()` in `emit()`); `test_hub.py` greps all `emit("obs.*")` calls
  against the contracts registry.
- **Never block the event loop**; network calls have timeouts; a dead broker/cloud/voice never crashes the hub.
- **Raw never leaves the home:** the uplink sends `obs.*` only.
- **Robot build** (D31/D32, plan 07): the dial is the Atech Knob (`raw.head.ear`, `dial_input = "ear"`). If the knob
  is out, `dial_input = "button"` takes 1–5 short presses within `press_window_s` as one ear press with `value` =
  count; a long press never counts (safety). Chimes on `cmd.sensors` (`wake` greet, `ok` each dial answer,
  `start_drum` / `end_drum`). `drum_sway = false` keeps the head still while drumming (knocks are muted while the motor
  moves). The camera sits in the head: `[attention] camera_on_head = true` makes pan targets relative to the last
  `raw.head.pan` (clamped to `pan_limit_deg`).
- **Dial protocol** (head firmware + `sim/nodes/head_sim.py` depend on it): each ear *press* answers the current
  question with the dial position at that moment (order mood → energy → sleep); the post-activity mood is
  asked right AFTER `obs.drum_session` is emitted; spoken PHQ-9 accepts presses (dial 1→0, 2→1, 3→2, 4–5→3).
- A PHQ-9 is only emitted when all 9 items are answered (never partial).
- **Attention ladder** (`attention.py`, numbers in `[attention]`): greet at most once per `regreet_h`; no purr or
  greeting in quiet mode ("not now"/"quiet", `quiet_h`) or in `[night_start, night_end)` unless the person started
  (spoke, pressed ear/button); ≥ 2 faces → `greet.two`, never a ritual offer; ritual done today → greeting, no
  offer (demo mode ignores "done today"); face lost < `lost_s` doesn't end the visit; while a ritual runs the ladder
  sends nothing (the ritual owns the body). Offer = ritual starts with `ritual_reason="attention"`: GREET asks
  instead of greeting twice. Only a pressed ear/button or affirmative text accepts the invitation; timeout,
  incidental speech, and dial rotation do not consent. "no"/"not now" ends it (`skipped`).
- **Gemini Live is consented per ritual:** explicit terminal/CLI start or a short button press starts it;
  attention and cloud invitations leave the microphone off until accepted. Healthy home-authorized cloud bootstrap
  is mandatory. Robot uses its server-side key + SessionMeter (cloud does not mint a second paid token for robot).
  When GEMINI_API_KEY exists, Live uses the Developer API independently of the global text/TTS backend;
  otherwise it uses the shared configured backend (which must support the configured Live model).
  The microphone callback copies PCM before PortAudio reuses the buffer. Output callback drains bounded audio
  without blocking receive; barge-in clears pending audio even while cloud tools are running. Affective dialogue
  is disabled. Resumable disconnects retry within `[live] reconnect_attempts`; explicit stop cancels reconnection.
  Streaming transcription fragments (including interim transcripts) are safety-scanned immediately; only completed
  utterances reach ritual controls (`Transcription.finished`, or a model-turn boundary for older responses).
  During Live, named `record_dial` tools alone write dial/post-drum answers: numeric transcripts cannot also advance
  to another question. Physical/text inputs retain numeric parsing; spoken PHQ-9 consumes completed utterances once.
  `[live] session_max_minutes` / bootstrap `max_session_seconds` caps the active session. Closing from a receive/tool
  callback never cancels that same callback: the deterministic crisis script + safety flag must finish.
  `end_session` / `end_ritual` abort all remaining steps; `start_activity` selects breathe/drum exactly, and unsupported
  activities return an error. No OS `say`/`espeak`: unavailable Live uses Gemini TTS/cached keyed audio, then visible text.
  The registry `express` tool requires an active consented conversation and validates its feeling enum. It changes
  only eyes (happy/proud → happy, curious → listening, sleepy → sleepy, cozy → soft), preserving ritual chest pacing
  and motor ownership. Thinking keeps visual priority; expressions cannot override the crisis body after consent closes.
- **Episode persistence:** completed/skipped/ended-early/crisis outcomes are queued in `robot_episodes.sqlite` next
  to the uplink DB before network delivery. IDs stay stable on retries. Transcript collection is off by default;
  `[live] hub_transcripts=true` is only set after the person explicitly opts in. Crisis clears transient text and
  queues no transcript. Audio is never retained. Queue survives process restart; failed HTTP requests retain records.
  `end_session` closes capture immediately and queues its validated outcome plus optional `follow_up` as the existing
  episode `open_thread` field, preserving cross-device continuity through offline delivery. Crisis removes the thread.
  If cloud notebook policy rejects a follow-up (422), the outbox retries completion without the rejected thread,
  logging only the refusal type so later completions are not blocked.
  Transcript turns retain optional completion status: explicit per-speaker `Transcription.finished` marks true,
  known model interruption or bounded-text truncation marks false, and marker-free audio completion stays unknown
  (`null`). Audio `turn_complete` is not proof that ASR finished. A later final marker cannot hide truncation.
- **PPG integrity:** preserve envelope quality and sensor `t0_ms`; discontinuous batches restart the signal window.
  Bad sensor quality cannot become a high-quality HRV observation just because its synthetic rhythm is regular.
  A pulse is **measured or missing, never guessed** (D39). `PpgBuffer.session` returns nothing, with a `reason`, when:
  the signal is flat; its heart-band power is not ≥ 3× the noise just above the band (band-passed noise always shows
  "beats"); < 70 % of beats are clean; the sensor's own quality is < `[perception] quality_min`; or a finger
  recording is metronomic (RMSSD < 5 ms over ≥ 8 beats: the mains-flicker artefact seen on the bench; heuristic,
  VERIFY in the cradle). The camera backup never yields RMSSD. Finger and camera batches are never mixed: a
  switch restarts the window. The reason is logged (`pulse_not_measured`) and stored with the session.
- **Engagement summary** (`perception/engagement.py`, `obs.engagement`, `[hub] engagement_enabled`): deterministic,
  numbers only. Cues: dial (mood + energy), voice (pause ratio of `obs.speech_features`), drum (taps/s), face (share
  of 5 Hz looks with exactly one face box in view + its movement; box positions, never an image or an expression
  label), pulse (HR, only when measured), ritual (steps completed). Each has `available`, a 0–1 `level` on a fixed
  range, a `confidence` and a `basis`. A cue without evidence is missing, never zero (face coverage < 20 %, two
  people in view, no speech, pulse not measured). Fused level = share-weighted mean, share ∝ weight × confidence
  (weights dial .30, voice .20, drum .20, face .15, pulse .10, ritual .05); the face share is capped at 25 % and,
  with ≥ 3 cues, no cue above 50 %; **< 2 cues → no level**. `agreement` = 1 − spread. Only for a ritual whose
  conversation was accepted; never after a crisis. Maps to `adherence` in `sources.py`: it feeds no verdict.
- **Follow mode** (`follow.py`, `[hub] head_mode = auto|follow|drive`, D44; details in "Robot bring-up with the
  standalone head"): with `auto`, a `health/head` saying `firmware: standalone` makes the hub follow, anything else
  (the MQTT firmware, the sim head) makes it drive as before; a hub-driven ritual in progress is ended when a
  standalone head appears. While following: `start_ritual` is refused, the attention ladder acts on nothing, and
  **no ritual or attention `cmd.head` is sent** (the head turns every `pan` into a 600 ms motor run); what it does
  get: `drum: hold|end` for the game, `mic: open|close` for the conversation, and on a crisis `{eyes: soft}` and
  `{show: help}`. `raw.head.ear` is never an ad-hoc mood (a press outside a dial carries a stale 1–10
  value). Dial answers are held until the head confirms the hub's shadow; the head's 1–10 value is kept in
  `scale_10`, `value` = ceil(v / 2). A head that goes `down` or silent for `head_stale_s` → open step `aborted`,
  episode `ended_early`. Recording stops on a crisis until the next greeting. A ritual joined mid-way is not
  consented (no engagement summary, no conversation). The conversation in follow mode: next bullet but one.
- **Two home ids:** the bus home (`[hub] robot_home_id`, default = the home id) is what the boards publish on;
  every observation is stamped with the person's record (`KAIKU_HOME_ID`) for the uplink and the local store, and
  echoed on the bus under the robot's home. Cloud commands, nudges and the episode use the person's record.
- **Local session store** (`store.py`, `[hub] store_*`): while a ritual runs, every validated `raw.*` message
  (tap times, pulse samples, distances, face boxes, dial turns, button edges, pan) and every emitted `obs.*` is
  written to `logs/hub_sessions.sqlite`, linked by the ritual id (+ the episode id the cloud knows; obs rows carry
  the envelope id = the cloud's event id). Nothing outside a ritual is stored; nothing from it is uplinked; the
  bus carries no image or audio, so neither can the store. Retention by age and size at the next ritual start.
  Store errors disable it and never touch the ritual. Audit / export / replay: `tools/session.py`.
- **Live context events (plan 06 §4, `live/context_events.py`):** source-labelled `[source: robot]`, only while the conversation is consented; only keys of the fixed `VOCAB` can be sent
  (`[drumming · lively|steady|gentle]` relative to this ritual's first 6 taps, `[breathing · heart calmer]` from
  the breathe `obs.intervention_response` delta, `[second person nearby]` (≥ 2 faces), `[person stepped away]`
  (presence lost), `[light · dim|bright]` (< 50 / ≥ 1000 lux, greet/dial steps only), `[it's late]` (ritual start 23:00–03:59)) — never
  numbers or state words (a property test checks). ≥ 20 s apart, ≤ 8 per ritual, each once per ritual; the
  "session" is the ritual (open at start, closed at the end and on crisis); dropped silently otherwise.
  Gemini: `send_client_content(turn_complete=True)` mid-session; text voice prints `· context: …`; off = no-op.
- **Spend cap (`live/meter.py`, `kaiku_contracts/budget.py`):** Gemini Live and Lyria RealTime only open if
  `budget.guard(estimate(model, audio_min=5))` passes; then one `budget.charge(audio_min=1)` per started minute.
  Over the cap → Live isn't opened (scripted ritual) or closes politely mid-session (one visible/cached Gemini line, ritual
  continues scripted); Lyria → local click only. Ledger `logs/spend.sqlite` (`KAIKU_SPEND_DB`), `make spend`.
- **Drum music (`live/lyria.py`, `live/player.py`, `KAIKU_MUSIC=lyria`, off by default):** Lyria RealTime
  (`lyria-realtime-exp`), the streaming model, because its tempo can be steered while it plays; Lyria 3.5 makes a
  finished song per request and cannot. Developer API only: it takes `GEMINI_API_KEY` at this edge (the platform
  backend refuses live music), else local. Two uses. *Free drumming:* it follows her (prompt from the mood dial, a
  click on each tap, the tempo of her last 8 taps via `set_tempo`: a change of 6 bpm or more, at most every 4 s,
  always the full config, then `reset_context`). *Tap it back:* it leads (`song(bpm)`: full config at that tempo,
  `reset_context`, `play`; `hush()`: `pause` and drop what is queued; `chime(name)`: a cue on the same output).
  `Music.can_play_songs` is true only while the session is open and its receive task alive: a stream that died
  (logged `lyria_stream_ended`) makes it false, so the game falls back instead of waiting on silence. Playback
  rules, unchanged: Lyria streams about 4 s ahead of real time and adds a burst after each tempo change, so audio
  queued before a change is dropped (30 ms fades) and writes are a quarter second each, off the event loop.
  **Where it is heard is `[music] out`** (default `head`): the robot head's own speaker (below), this machine's
  sound card (`speaker`, needs `uv sync --extra live`), or a WAV on the wall clock (`file`, or
  `KAIKU_MUSIC_FILE=<path.wav>`, which wins). Measured on 2026-11-14 against the real model: `pause` stops the
  chunks at once; after `pause`, a new config + `reset_context` + `play` gives the first chunk about 0.7 s later, at
  the new tempo; connects took 0.38 s in the runs and 8.7 s once (the adapter's timeout is 10 s). Shown with `make
  drum-music` (free drumming, sound into a file) and `make tap-back` (the game, sound through the sim head twin's
  speaker). Not shown: any real speaker, real taps, and nobody has listened to it beyond the saved files.
- **Tap it back (D51; `rituals/tap_back.py`, `perception/tap_back.py`, config `[tap_back]`):** the drum step as a
  three-level rhythm game. `mode = "auto"` (default) plays it when `music.can_play_songs` after `music.start()`,
  else free drumming exactly as before; `tap_back` forces it (the hub's own beat through `LocalMusic`, or the chest
  light alone with no output); `free` never plays it. Flow, as built: (1) Kaiku says it will play a song; (2) level
  n: `music.song(bpm)`, head `eyes: listening, chest: pulse, bpm, pan_mode: sway`; the listen time (`listen_s` 8,
  a replay `replay_listen_s` 6) counts audio really handed to the output (`music.heard_s()`), not wall time; (3)
  `music.hush()`, head `eyes: wide, pan_mode: still, chest: glow`, the `your_turn` chime on the same speaker, the
  buzzer `start_drum`, "Your turn."; (4) her turn opens after the fade, the chime, the spoken words and
  `cue_clear_s` (0.4), and not before the head's speaker is really quiet (`Hub.speaker_busy`): the head sends no tap
  while its speaker plays or its motor moves, so that wait is never counted against her; taps before it are ignored,
  not judged; (5) the turn ends when she has made the level's taps (the band comes at once), or `idle_end_s` 2.5
  after her last tap, or `first_tap_s` 8 with none, or `turn_s` 25; (6) `score_try`: tempo = 60000 / median gap,
  error in percent of the song's tempo (also against half and double, `half_double`), steadiness = 1 − CV of the
  gaps; bands perfect ≤ 4 %, great ≤ 8 %, nice ≤ 15 %, else again; steadiness under `steady_min` 0.85 lowers perfect
  and great one band; fewer than `min_taps` 4 = no tempo = again; (7) the band lands three ways: eyes (happy /
  soft / neutral), a chime on the speaker (four, three, two rising notes; one soft low note), the buzzer (`ok` /
  `end_drum`), and a line ("Perfect! You kept its beat." / "Great! That was very close." / "Nice! You caught its
  feel." / "Oh, not quite. Let's try that one again."); (8) again → the same level once more (`retries` 1), then
  "That one was tricky. Let's leave it there."; no taps at all → "No rush. Listen once more, then tap when you're
  ready.", and after two silent turns the game ends without a word about it; (9) "Here's the next one. It's a
  little faster." / "Last one. It's slower, so take your time."; (10) one closing line that names only what she
  matched ("Three songs, and you found the beat in every one."), `obs.tap_back`, then the unchanged post-activity
  mood question (skipped when no level was played to its turn). Levels: `level_bpm` [100, 126, 76] moved by up to
  `level_vary_bpm` [6, 8, 4] by the date (deterministic, never the same two days running), `level_taps` [8, 8, 12].
  If the song is lost mid-game in `auto`: "My song got lost. Let's just drum together, any rhythm you like." and
  free drumming for the rest of the step. The step's hard cap grows to cover the game (`Step.hard_cap_s`,
  `max_s` 170). Drum-feel context events are not sent during a game (the tempo is not hers). Lines pass
  `kaiku_contracts.wording` with the robot's caps; no number is ever said.
- **The robot is its own body for sound (`live/head_audio.py`; config `[music] out`, `[voice] audio`):** with
  both on `head` the hub opens no sound device and imports without `sounddevice` (tested in a subprocess), so it
  can run on the UNO Q. `HeadSpeaker` is the one sender on `audio/head/speaker`: Lyria's 48 kHz stereo and Live's
  24 kHz mono are down-mixed and resampled to 16 kHz mono (one windowed-sinc low-pass, 97 taps for 48 → 16: flat to
  about 6.5 kHz, more than 60 dB down from 8.5 kHz; gain `head_gain` 0.8), cut into 640-byte frames and sent on the
  hub's clock: four frames at once when a sound starts, then one every 20 ms, `head_lead_ms` 80 ahead (never more
  than 120); the end of a sound is its faded tail, the wait for it to play out, then a zero-length "drop" message.
  One stream holds the speaker while it sounds and 150 ms after; another stream's audio waits (it is delayed, never
  mixed in), so frames of two sources never interleave. One exception: Kaiku's voice (and a scripted line) never
  waits behind music: it takes the speaker at once, the head is told to drop the music it has buffered, and the
  music goes on after. `HeadAudio` gives the Live adapter the head's speaker and microphone in `sounddevice`'s
  shapes: the microphone exists only between `cmd.head {mic: open}` (again every 2 s) and `{mic: close}`; frames
  arrive in bursts and are regrouped into 100 ms blocks. The head is half-duplex, so: no voice barge-in on the
  robot (an ear press stops Kaiku: `quiet()` drops what is playing and the rest of that answer); a gap in the
  microphone is never filled with silence (it would look like the end of her turn); after `[live] mic_gap_end_s`
  1.0 without a frame the server is told once that the stream paused (`audio_stream_end`), and the next frame
  resumes it. `[voice] audio = "auto"` picks the head when a real head is alive as a conversation opens (a
  simulated head does not count: a developer's machine with `make sim` keeps its own sound card), and always when
  this machine has no sound card; for both directions at once. Scripted lines in the cached voice (`lines.py`) go
  the same way out; they used to be played by this machine's `afplay`/`aplay`. Audio is never stored, logged or
  uplinked; `HeadSpeaker.stats()` keeps counts and timings only (`health/hub` shows `music_out`, `voice_audio`).
- **Tap it back while following a head that runs its own ritual (`Hub._follow_game`, `follow.py`):** when the head
  says it entered its drum step (`chime: start_drum` or `health/head details.step`; never assumed earlier) the hub
  starts the music; if a song can play it sends `cmd.head {drum: hold, ...}` with every game command and a bare one
  at least every `hold_every_s` 3, runs the same `Game` with the taps the boards report (not while the head says its
  motor moves), and ends with `{drum: end, pan_mode: still}`. Faces are the standalone's five: the calm one during
  the song (its wide eyes are kept for "your turn") and the happy one for every band she matched. No song: nothing
  is sent and the head's own free drumming is followed as before. The head leaving its drum step, a crisis or the
  hub stopping ends the game; a game with a played level is recorded as `obs.tap_back`, never also as a drum
  session; nothing of a game is recorded after a crisis. A forced game with no sound at all says "Watch me sway to
  a beat" on this head (it ignores `chest`; the hub-driven head is told to watch its light).
  **On this robot every cue is sound and motion** (no screen, no light: `eyes` and `chest` are accepted and do
  nothing): the song and the sway while she listens, stillness and the two-note chime and "Your turn." for her
  turn, the band's chime and word, and the UNO Q's buzzer. **Her taps come only from the head's own orientation
  sensor** (`raw.head.tap {src: imu, force}` from `head`, D55; the knock switch is gone): the head sends none while
  its motor turns or 0.4 s after, none within 120 ms of the last, none while its speaker plays, which is why her
  turn opens only when the sway has stopped and the speaker is quiet. **The game is started only on a head that
  can lend its drum step** (`health/head details.drum_held` present): the firmware before sound would leave its
  drum step on its own timer in the middle of a level and sound its own tap tones; there the head's free drumming
  is followed and recorded as before.
- **The conversation in follow mode (the same consent rule as drive mode, nothing new):** drive mode opens the Live
  conversation when the person started the ritual themselves; on a head that runs its own ritual that is her press
  of the ear at the head's greeting, which the hub records as `follower.consented`. The hub opens the conversation
  on the follower's `begin` then, and otherwise on **the first press of the ear it sees in that ritual, whatever step
  the head is in** (D57, `_follow_press_opens_talk`: a missed greeting or a ritual joined mid-way no longer leaves
  the robot deaf). One conversation per ritual: after a crisis or after she asked to stop talking, a press is only
  a press. No press seen = no microphone. `health/hub` `details.talk`: `open` | `opening` | `closed`. At the head's greeting (not yet a ritual) Kaiku's invitation is said once in the cached voice, at most
  every `[hub] follow_offer_every_s` 300 (the head greets a face about once a minute); nothing is listened to
  before her press. The session uses the cloud's existing `ritual` intent (`POST /v1/companion/session`); the tools
  that would run a step are taken out of what the model is offered and refused if called
  (`live/tools.py HEAD_RUNS_ITS_STEPS`: `record_dial`, `start_activity`, `start_breathing`, `start_drum`,
  `start_phq9`), because this head runs its own steps and she answers on its ear. Kaiku accompanies: when the head
  enters a step, the hub has the voice say that step's line (`follow.STEP_LINES`, written for THIS head, which has
  no screen and no light: the dial starts in the middle and she cannot see its number, so the line gives a
  direction ("clockwise for lighter, the other way for heavier"), and the breathing is paced by Kaiku's words, not
  by a light; tested: no line points at something she would have to see), and she can answer or say anything. It closes when the head's
  ritual ends (after "See you tomorrow", with the microphone already closed), when she asks to stop talking
  (`end_session`: the head's ritual and its record go on), on the session's own limits, and at once on a crisis.
  Speech features and the engagement summary stay as they were (drive mode's rules).
- **The robot hears the configured language (2026-11-15).** `live_config(..., language=)` sets
  `input_audio_transcription.language_codes` to the code of `[home] language` from `[voice] lang_codes` (en →
  `en-US`; `gemini_live.transcription`), so her speech is not left to automatic language detection (English came
  back as German). `[live] transcription_language_hint = false` turns it off. A hint to the recogniser, not a lock;
  the instruction from the cloud says the same in words.
- **The game and the voice in one ritual, the same in both modes:** `Game` closes the open conversation's microphone
  when it begins (`ctx.listening(False)` → `Voice.listen`: `cmd.head {mic: close}`, the keep-alive stops, frames
  that still arrive are dropped, the server is told once that the stream paused) and opens it again when the game
  is over, at its closing line, or when it falls back to free drumming, or when the drum step is left for any
  reason (`Game.leave`). Closed for the WHOLE game, not only for the song and her turn: the song and her taps are
  not speech, the gaps between levels are under two seconds, a half-heard word there would make Kaiku answer over
  the next song, and the head sends no tap while it speaks. Kaiku still says every line of the game. The engine is
  shared, so drive mode (`steps.Drum`) and follow mode (`Hub._follow_game`) behave identically. Never reopened
  after the conversation ended (`Hub.listening` needs `conversation_consented`).
- **Kaiku never talks over itself (`GeminiLiveVoice.say`):** to the Live server a new request is an interruption.
  With the real model a line asked for right after another cut it: the game's closing line never came out because
  the goodbye followed it, and band lines lost their last syllables. Lines are said one at a time (a lock), and a
  line waits until the words received so far have been played (+ 0.25 s, and up to 0.8 s more for the server to
  close that turn), at most 12 s. **A press of the ear stops what Kaiku is saying and also a line that is on its
  way and has not sounded yet** (`quiet()`); a step's line is checked when it can be said, not when it was asked
  for (`Voice.after_speech`), so a step she has already left gets no line.
- **A song waits for Kaiku's words; it is not "lost" while they hold the speaker (`Game`):** the room left for a
  spoken line is an estimate (`[tap_back] word_s`). With the real models together the Live voice said the game's
  first line for 11 s where 5 were planned, the song could not sound behind it on the one speaker, and after
  `song_wait_s` the game said "My song got lost" and fell back to free drumming. Now the next thing after a spoken
  line (a song, the next line) starts only when the head's speaker is quiet (`speaker_busy`, at most 15 s past the
  planned time), and while nothing of a song has sounded and the speaker is busy, the lost-song clock does not run.
  On a sound card (`speaker_busy` unknown) the estimates alone apply, as before.
- **Help screen on a crisis (`cmd.head {show: help}`, both firmwares, both modes):** after the conversation is
  closed, the music stopped and the eyes calmed, and before the script is printed, `Hub.crisis` sends
  `{show: "help"}` (forced through in follow mode): the head then shows the helpline's name and number and the
  emergency number on its own screen, from constants compiled into its firmware (the hub can send no text), never
  a sound. During a game on a self-running head it goes in ONE message with the end of the hold
  (`{drum: end, pan_mode: still, show: help}`, the first thing the head hears), so that head ends its ritual quietly
  with no end chime and no "done" screen before the numbers. **Nothing opens the microphone after a crisis:** it is
  closed as the first act of the path, its keep-alive stops, and `listening(True)` is refused; the firmware does not
  guard a late `mic: open` under the help screen, so the hub must not send one (tested). Clearing: the hub sends
  `{show: "none"}` when the next ritual starts (drive: `start_ritual`; follow: the head's `begin`); the standalone
  also takes it down itself when her ear press starts a new greeting, both after 10 minutes. `cmd.head` is not
  retained: if the head's next `health/head` says `details.help_shown: false` within those 10 minutes and it never
  said `true`, the command is sent ONCE more (a head that showed it and took it down is left alone).
- **Trace (`raw.hub.trace`, `Hub.trace`, `[hub] trace = true`):** for the apps' live "Kaiku bot" tab, on the home
  broker only (`raw.*`: QoS 0, not retained, the cloud rejects it, `tools/record.py` drops its text). `said`:
  Kaiku's own words, cut at 300 characters: a scripted line (`by: script`, or `cached_voice` when the cached
  Gemini voice speaks it) or a finished reply of the Live voice as its output transcription gives it (`by: live`;
  inside an open conversation the scripted line is not traced, what the voice really said is; a reply she
  interrupted or stopped with the ear is not reported). `heard`: she spoke, and nothing else. `tool`: the NAME of
  a tool the voice called, `ms`, `ok`, and `by` only when the cloud's result names who answered. `session`:
  `open` / `close`. `game`: `level:<n>` (+ `bpm`), `your_turn`, `band:<band>`. `music`: `start`, `song` (+ `bpm`),
  `hush`, `stop`. **Never her words, a system instruction, a tool's arguments or result** (the contract refuses
  `text` outside `said` and anything beside the kind on `heard`). After a crisis nothing is traced but the script
  line (`said`, `by: script`) until the next ritual starts. Sent from its own task with a 2 s cap: it never holds
  up or fails what Kaiku does.
- **`feel` (notice and act):** declared in `live/tools.py` from the shared registry with `behavior: NON_BLOCKING`,
  so the robot's Live session offers it even on the local fallback tool list. `Hub.on_tool` runs the local crisis
  gate on its `said` / `about` words **before** anything is forwarded (the cloud gates again), then forwards it with
  **no thinking pose, no glance and no spoken "think later" line**: the eyes stay what the ritual set. The Live
  adapter answers a NON_BLOCKING call on its own (never behind a blocking tool of the same message) with the
  result's `scheduling` (default `WHEN_IDLE`; `SILENT` when the plan is unavailable, late or refused). On the
  platform (Vertex) backend `behavior` is dropped and `feel` is an ordinary blocking call with the 8 s cap.
- **`agree_activity` (D50):** declared in `live/tools.py` from the shared registry, blocking. The robot has no
  screen for a walk, a game or the journal: when the person clearly says yes to one, the model calls it and
  `Hub.on_tool` forwards it like every `executor: cloud` tool (thinking body, 8 s cap); the cloud decides and
  keeps it, and the answer (`where`: "your phone") goes back to the model so Kaiku says where it is. A refusal
  comes back as `{ok: false, error}`; the cloud's crisis answer runs the robot's crisis path. Nothing about the
  ritual changes and no observation is emitted. The same in a follow-mode conversation.
- **Thinking body:** while any `executor: cloud` tool (e.g. `ask_mind`) is in flight → `cmd.head {eyes: thinking,
  look: up}`; restored to the last eyes after (not after a crisis — the crisis body stays). > 8 s
  (`THINK_TIMEOUT_S`; `ask_mind` uses `[live] mind_timeout_s` for Gemma reasoning) → the tool answers `{ok: false}`, Kaiku says "Let me think about that later." and the ritual
  goes on.

## Robot bring-up with the standalone head
The Atech head currently runs the **standalone** firmware (D44): the ritual runs on the head, and its `kaiku_net`
publishes only status, the knob and chimes (`docs/robot-network-handover.md`). The hub **follows** it
(`follow.py`, `[hub] head_mode = "auto"`): it never starts its own ritual and sends the head no ritual command
(only `drum: hold|end` for the game, `mic: open|close` for the conversation her press opened, and the crisis
path's calm eyes and `show: help`).

### Tonight: the real robot on the laptop
The robot is the head on the STANDALONE firmware (no screen, no light, taps from its own orientation sensor: D54,
D55) and the UNO Q (camera, buzzer). The broker, the cloud and the hub run on this Mac; the boards publish on
`demo-aino`, the person's record is `aino`. The hub follows the head by itself.
```bash
make broker                                   # 1: mosquitto :1883 on this Mac (the boards point at this Mac's IP)
make cloud-local                              # 2: API + dashboard on http://localhost:8000
# 3: the hub, everything through the head: Live voice, Lyria songs, Tap it back, the conversation her press opens
KAIKU_HOME_ID=aino KAIKU_HUB_ROBOT_HOME_ID=demo-aino KAIKU_CLOUD_URL=http://localhost:8000 MQTT_HOST=localhost KAIKU_VOICE=gemini KAIKU_VOICE_AUDIO=head KAIKU_MUSIC=lyria KAIKU_MUSIC_OUT=head KAIKU_TAP_BACK_MODE=auto make hub
make tail TOPIC='kaiku/v1/demo-aino/#'        # 4: everything the robot and the hub say
```
**The fallback, when the head's sound firmware is not flashed or misbehaves** (the demo must not depend on it): the
same hub with Kaiku's voice and the songs on this Mac's own speaker and microphone. It needs a sound-card library
the shared environment does not have, so it is run with one added for that process only:
```bash
KAIKU_HOME_ID=aino KAIKU_HUB_ROBOT_HOME_ID=demo-aino KAIKU_CLOUD_URL=http://localhost:8000 MQTT_HOST=localhost KAIKU_VOICE=gemini KAIKU_VOICE_AUDIO=local KAIKU_MUSIC=lyria KAIKU_MUSIC_OUT=speaker KAIKU_TAP_BACK_MODE=auto uv run --with sounddevice python -m kaiku_hub.main
```
- `GEMINI_API_KEY` comes from `.env` (never typed, never printed). The hub log's first lines say what it got:
  `voice gemini`, `music lyria`, and `health/hub` details show `voice_audio`, `music_out`, `head_mode: follow`.
- **What the hub decides from the head's own `health/head`, so one firmware or the other never breaks the demo:**
  `firmware: standalone` → follow mode. `drum_held` present → the head can lend its drum step, so Tap it back is
  played there; absent (the firmware before sound) → no game, the head's own free drumming is recorded as before
  (the hub logs `tap_back … cannot lend its drum step`). With `KAIKU_VOICE_AUDIO=auto` the voice goes through the
  head only when its health has the `audio` block, else through this Mac.
- **Asking twice (D58):** in follow mode the voice is offered `start_activity {breathe | drum}` (`tools.ASK_TWICE_TOOL`).
  `_ask_twice` arms the head (`cmd.head {activity}`), `_ask_twice_press` takes the next press of the ear within
  `ASK_TWICE_S` (20) as the yes (that press is not fed to the follower; `follower.asked` lets the head go to that
  step, also backwards, inside the same ritual), `_ask_twice_expire` disarms and tells Kaiku.
- **Words or the ear, and stop (D59):** `record_dial` is honoured in follow mode for the question the head asks now
  (`_follow_spoken_dial`, `follower.spoken_dial`, then `cmd.head {ritual: next}`); `end_session` / `end_ritual` send
  `cmd.head {ritual: end}` so the head goes back to rest and `_follow_end` keeps the episode as ended early.
- **The camera, once per conversation (D61):** `_ask_camera_once` (the fixed `tools.CAMERA_LINE`, after the Live
  session opens in follow mode, only when `health/sensors` says `camera_ok`), `camera_choice` → `_camera_choice`,
  `_camera_show` (opens or closes the board's camera with `cmd.sensors {camera_enable}`, repeated on the board's heartbeat; buzzer `ok` for a yes), `_camera_windows` (windows of `cmd.sensors {face_signs_s}` while yes, `obs.face_signs` task check_in), reset
  by `_camera_reset` at every ritual begin and end and on a crisis. `photo_time` needs the yes and marks the day
  (`state.photo_time_done_on`).
- **Her asks of the body (D62, D66):** `turn_head` → `cmd.head {pan: {target_deg: ±40, speed: 1.0}}` (forced through
  in follow mode); `_follow_track` nudges the head toward a face at the edge of the picture (`[follow_track]`:
  `nudge_deg` 10 at `speed` 1.0; the size of `target_deg` is the length of the nudge, not an angle). The light
  colour (`set_light`) was removed.
- **A press opens a talk; the check-in only when asked (D66):** `follow.HEAD_STEPS` has `talk` (not a ritual step);
  the press at the greeting leads there (`AFTER_PRESS`), `begin` still fires at that press and the conversation
  lives from it until the head is idle. Tool `checkin {start | continue | pause}` (`tools.CHECKIN_TOOL`) →
  `_checkin` → `cmd.head {ritual: start | resume | pause}`; `_paused_step` is the step that waits. Entering `talk`
  from the greeting says `STEP_LINES["talk"]` once; entering it after a pause says nothing. `_talk_idle_check`
  (every attention tick) ends a talk after `[hub] talk_idle_end_s` (180) without a word, a press, a tool call or
  a step change. The wake's record ends `completed` (the whole check-in), `ended_early` (started, not finished)
  or `skipped` (only talked). The invitation is `follow.TALK_OFFER_LINE`.
- Fixed lines in the cached voice (the invitation, the step lines, Tap it back's lines, the goodbye) are fetched
  when the hub starts (`LinePlayer.prewarm`, log `voice_prewarm n/n lines ready`, up to a minute after a cloud
  restart or a render change) and kept in memory: a line the cloud has not rendered yet takes longer than the 3 s a
  spoken line may wait and would not be said.
- The conversation opens on the first press of the ear the hub sees in a ritual (hub log `follow_conversation
  opening`, D57). Until then the log says `not open yet: her next press of the ear opens it`.
- The fallback line was NOT run by the agent who wrote it (it would have opened this Mac's microphone and speaker):
  it is the drive-mode sound path that existed before, plus `--with sounddevice`. Through a laptop speaker and
  microphone Kaiku can hear itself; use headphones or keep the laptop away from the robot if it answers its own
  voice. In the game the microphone is closed, so the songs are not listened to.
- Rehearsed without the robot on 2026-11-14 with the real models (`make head-voice FOLLOW=1 ARGS=--robot`): twins
  on `demo-aino`, record `aino`, taps from the head's own sensor only. See Known issues for what that does not show.

**What to watch, sensor by sensor** (`make tail TOPIC='kaiku/v1/demo-aino/#'`; one sensor at a time: add the path,
e.g. `TOPIC='kaiku/v1/demo-aino/raw/head/ear'`):

| part | do this | this proves it works |
|---|---|---|
| Both boards alive | power them | `health/head` with `"firmware":"standalone"`, `"step":"idle"` (and `drum_held`, `audio` once the sound firmware is on it); `health/sensors` with `camera_ok: true`, `mcu_ok: true`; `health/hub` `head_mode: follow`, `ritual: head:idle` |
| Ear dial | in a dial step turn it, then press | `raw/head/ear {value 1-10, delta, pressed: false}` per click, then `{pressed: true}`; from the hub `obs/self_report {item, value 1-5, scale_10}` once the head moves on |
| Ear press (start) | press at idle, then at the greeting | `cmd/sensors {chime: wake}` from `head`, then `obs/ritual greet … completed` and `dial started` from `hub`; with the voice on: hub log `follow_conversation opening`, `cmd/head {mic: open}` |
| Button | (none on the standalone head: the ear press is the button) | `raw/sensors/button` only if the UNO Q's top button is fitted |
| Taps | in the head's drum step tap the top of the head | `raw/head/tap {t_ms, force, src: "imu"}` from `head`, one per tap (none while the motor turns or 0.4 s after, none while its speaker plays). No `src: knock` exists on this robot |
| Face | sit in front of the camera | `raw/hub/face {x_norm, y_norm, size, confidence}` from `sensors` about 5 a second; at idle the head greets (`chime: wake`) |
| Distance | lean in and back | `raw/sensors/distance {cm}` changing; the far value when nobody is there; from the hub `obs/presence` on arrival |
| Room light | cover the camera, uncover | `raw/sensors/light {raw, lux_est}` every 10 s changing (camera, locked exposure) |
| Camera pulse | let the breathing step run with your face in view (do not press to skip) | `cmd/sensors {ppg: start}` from `hub`, then `raw/sensors/ppg {fs_hz ~15, samples}` with `quality` about 0.6, `{ppg: stop}`; `obs/hrv_session` only if the signal was good enough, else the hub logs `pulse_not_measured` (never a made-up number) |
| Buzzer | start a ritual | `cmd/sensors {chime: wake}` (and `start_drum`, `end_drum`, `ok` in the game) on the bus AND the sound from the UNO Q. The sound itself has not been confirmed on this robot |
| Motor | the head's greeting purr; in the game the sway | `raw/head/pan {moving: true}` then `false`; in the game `cmd/head {drum: hold, pan_mode: sway, bpm}` from `hub` and the head swaying on the beat |
| Speaker (head) | the hub's first spoken line or a song | `cmd/head {mic: …}` aside, sound is not a message: `make tail` prints one line a second `audio (not shown) demo-aino/audio/head/speaker N frames`; `health/head` `audio.rx` rising, `audio.dry` and `audio.drop` near zero. `make head-audio ARGS='check --host localhost --home demo-aino'` judges the stream |
| Microphone (head) | press the ear at the greeting, then talk | `cmd/head {mic: open}` every 2 s from `hub`; `audio (not shown) demo-aino/audio/head/mic N frames` only then; `health/head` `audio.mic_open: true`, `mic_tx` rising; `raw/hub/trace {kind: heard}` when you stop, then `{kind: said, by: live, text}` with Kaiku's answer. In the game: `{mic: close}` and no mic frames |
| Microphone (phone, D56) | Kaiku bot → "Robot microphone" on, phone beside the robot, press the ear at the greeting, then talk | `audio (not shown) demo-aino/audio/phone/mic N frames` only while `cmd/head {mic: open}` repeats; `health/hub` `mic_source: "phone"`; the app's line says "The robot is listening through this device" |
| The game | the head's drum step with the voice and music on | `raw/hub/trace {kind: music, detail: song, bpm}`, `{kind: game, detail: level:1 …}`, `your_turn`, your `raw/head/tap`s, `band:…`; at the end `obs/tap_back` from `hub` and `cmd/head {drum: end}` |
| Data on the pages | after the ritual | `health/hub` `uplink_queue: 0`; `http://localhost:8000` → the practitioner dashboard shows `aino`'s new check-in, and History in the apps shows the game |

**See a knob turn become a line on the dashboard** (laptop on the venue Wi-Fi; its IP is `MQTT_HOST_IP` in the head's
`kaiku_link/secrets.h` and `MQTT_HOST` in the UNO Q's `.env`):
```bash
make broker                                   # 1: mosquitto :1883
make cloud-local                              # 2: API + dashboard on :8000 (or use the deployed cloud URL below)
KAIKU_HOME_ID=aino KAIKU_HUB_ROBOT_HOME_ID=demo-aino KAIKU_CLOUD_URL=http://localhost:8000 KAIKU_VOICE=off make hub   # 3
make tail TOPIC='kaiku/v1/+/#'                # 4
```
- `KAIKU_HOME_ID` = the person's record the data lands on (`aino`). `KAIKU_HUB_ROBOT_HOME_ID` = the home the boards
  publish on (`KAIKU_HOME_ID` in `secrets.h` and in the UNO Q `.env`; both ship as `demo-aino`). Leave it out when
  they are the same. If the hub logs `head_on_other_home`, it tells you the value to set.
- What to look for, in order: `health/head` with `"firmware":"standalone"` → hub log `head_mode follow` and
  `health/hub` details `head_mode: follow`, `ritual: head:idle`. Knock or show a face → `cmd/sensors {chime: wake}`.
  Press the ear → `obs/ritual greet` + `dial started` from `hub`. Turn the knob → `raw/head/ear {value: 1-10}`; press
  → within 5 s (the head's next heartbeat) `obs/self_report {item: mood, value, scale_10}`. After the drum:
  `obs/drum_session`, `obs/ritual close completed`, `obs/engagement`.
- Dashboard: `http://localhost:8000/?id=aino` → Daily account ("morning ritual done; drum session; mood 4 of 5"),
  or `curl 'localhost:8000/v1/patients/aino/insight?generate=false'`. Locally: `uv run python tools/session.py show last`.
- No hardware: `KAIKU_HOME_ID=demo-aino make sim NODES=head,sensors ARGS='--standalone --fast 4'` instead of the boards.
- Back to the hub-driven ritual: flash `make atech-mqtt` (the hub switches by itself), or force `KAIKU_HUB_HEAD_MODE=drive`.

**Head step → what the hub records** (from `standalone/src/main.cpp`; the head's own results go to USB serial only):

| Head step (`details.step`) | The head sends | The hub records |
|---|---|---|
| `greet` | `cmd.sensors {chime: wake}` on entering; a press starts the ritual; 60 s without one → `idle` | `obs.ritual greet` started/completed once the person presses (consent); an unanswered greeting → `greet skipped`, at most once per `[attention] regreet_h` |
| `mood`, `energy`, `sleep` | turns `raw.head.ear {value 1–10, pressed: false}`; the press `{value, pressed: true}` confirms that dial | `obs.ritual dial`; one `obs.self_report {item, value: ceil(v/2), scale_10: v, context: ritual}` per press, after the head confirms the hub's shadow of its step (next heartbeat or expected chime). A mismatch drops the held answers (`dial_unattributed`), never relabels them |
| `breathe` | nothing (6 × 4 s in / 6 s out; a press skips it); then `chime: start_drum` | `obs.ritual breathe` completed (timed) or skipped (press). The hub asks the UNO Q for the pulse (`cmd.sensors ppg`): `obs.hrv_session` only if it passes every gate, else `pulse_not_measured` |
| `drum` | `chime: start_drum` … `chime: end_drum` (20 s after the first tap, 60 s without one, or a press) | UNO Q knocks (`raw.head.tap`) received meanwhile, not while `raw.head.pan.moving` → `obs.drum_session` (≥ 4 knocks) or `drum skipped` |
| `done` | (8 s, then `idle`) | `obs.ritual close`, the episode, `obs.engagement` if the hub saw the starting press |

**Not derivable today** (so never emitted): a post-drum mood and the drum before/after response (the head doesn't
ask), drum force and the head's own motion-sensor taps (serial only), breathing cycles, PHQ-9, a suggestion.
Step changes without a chime (greet → idle, done → idle) are seen up to 5 s late.

**What the firmware would need to send for a richer record** (owner A; nothing here blocks the loop above):
1. ~~`health/head` at every step change~~ **done in the firmware source (compiled 2026-11-14, not flashed)**:
   `health/head` goes out at once when the step changes, with `drum_held`, `loop_max_ms` and `audio{...}` counters.
2. The results it already prints on USB serial: `dial {item, value}`, `drum {taps, tempo_bpm, force_avg_g,
   force_max_g}`, `breathe {completed, cycles}`, `ritual_done`. A contract type can be added when the fields are fixed.
3. ~~Its motion-sensor taps as `raw.head.tap {t_ms, force, src: "imu"}`~~ **done in the firmware source (compiled,
   not flashed)**: at most one per 80 ms, none while the motor turns or sways nor 150 ms after, none while PCM
   plays nor 150 ms after. The hub takes one tap source per run (`OneTapSource`), so a tap felt by both boards
   counts once.
4. A greeting cooldown: with a face in view it greets again 3 s after returning to idle, about once a minute.
5. `cmd.head` → `idle` / `ritual`: a cloud invitation can't start a ritual on the head. ~~The crisis path can't
   stop the head's ritual~~ **done in the firmware source (compiled, not flashed):** `cmd.head {show: help}` ends
   whatever runs, quietly, and shows the helpline's numbers (Invariants → Help screen).
6. Optional: a post-drum mood dial, for the before/after response.
`kaiku_net` is built but not flashed or tested yet: all of this is proven against the sim twin only.

**What the hub assumes of the head for sound and the game (agreed with the firmware owner 2026-11-14; shown against
the sim twin and the firmware's own host check `make head-audio ARGS='check ...'`, not on a flashed head):**
playback starts once 120 ms is buffered or 120 ms after the first frame; a 0.5 s ring, the newest frame dropped when
full, silence when dry; a zero-length message empties the ring (up to 128 ms already in the driver still play); no
tap is sent while PCM plays or the motor moves, nor for about 0.3 s after; the microphone sends one or two frames
every 32 ms, only while `mic: open` is fresh (10 s) and never while the speaker sounds or 250 ms after; the MQTT
firmware honours `mic: open` only with a live `health/hub`; a `drum: hold` counts only in the head's own drum step
and lapses after 10 s; the standalone shows one face for `soft` and `neutral`, wide eyes for `listening`, and
ignores `chest`. `show: help`: both firmwares stop the motor and their own tones and shut the microphone; the
standalone also ends its ritual straight to idle with no chime and drops a `drum: end` in the same message, nothing
wakes it and it does not move while the screen is up; PCM sent to the speaker still plays; `health/head` reports
`details.help_shown`; down on `show: none` or after 10 minutes, the standalone also when an ear press starts a
greeting. Neither firmware refuses a `mic: open` under the help screen.

## Run standalone
```bash
uv sync                                   # from repo root
KAIKU_VOICE=text make hub                 # no broker? it keeps retrying, never crashes
# type: start | skip | 1-5 (dial) | 0-3 (PHQ-9) | yes | no | anything (goes through the safety gate)
```

Without a broker the hub runs but sees no sensors. Without `KAIKU_CLOUD_URL` it queues obs in
`logs/uplink_queue.sqlite` and sends them once the cloud is configured and reachable.

## Run with sim
```bash
make broker                    # terminal 1
make sim                       # terminal 2 (head + sensors + friendlink sims; glasses/laptop post to the cloud)
KAIKU_VOICE=text make hub      # terminal 3 — a sim person walks up: head turns, greeting, ritual offer; or type `start`
make tail TOPIC='kaiku/v1/+/obs/#'   # terminal 4
```

Fast ritual for testing: `KAIKU_RITUAL_GREET_S=2 KAIKU_RITUAL_DIAL_S=20 KAIKU_RITUAL_BREATHE_S=15 KAIKU_RITUAL_DRUM_S=10 make hub`.
Spoken PHQ-9: `KAIKU_RITUAL_PHQ9_MODE=spoken` and send `cmd.hub {phq9_due: true}` (or say "start_phq9" via Gemini).
Start immediately: `make hub ARGS=--start`.
Greeting at night (23:00–07:00 is quiet by default): `KAIKU_ATTENTION_NIGHT_START=00:00 KAIKU_ATTENTION_NIGHT_END=00:00`.
Re-greet within 3 h for demos: `KAIKU_ATTENTION_REGREET_H=0`. Two people: `make sim ARGS=--two` (or key `2`).
Attention log lines: `attention` (state changes + face count), `voice_line` (key, `source: cloud|cache|text`),
`ritual_start attention`, `live_session` (`cloud` instruction).

## Config & env
- `config/kaiku.toml [attention]`: `face_source = laptop|unoq_yolo|off`, ladder sizes, `lost_s`, `frame_s`,
  `two_face_min_sep`, `camera_hfov_deg`, pan deadband/smoothing/speed, `track_hz`, `regreet_h`, night window,
  `quiet_h`, `voice_timeout_s`. `[voice] name` (one voice) is passed to Gemini Live.
- `config/kaiku.toml [live]`: VAD, context compression, `hub_transcripts` (off until explicit opt-in),
  `reconnect_attempts`, `session_max_minutes`.
- `config/kaiku.toml [hub]`: `store_enabled`, `store_path`, `store_retention_days`, `store_max_mb`,
  `presence_leave_s`, `presence_stale_s`, `engagement_enabled`, `head_mode`, `robot_home_id`, `head_stale_s`,
  `follow_offer_every_s` (the spoken invitation at a self-running head's greeting, at most this often), `trace`
  (`raw.hub.trace` on the home broker; `false` = nothing is published)
  (env e.g. `KAIKU_HUB_STORE_PATH`, `KAIKU_HUB_HEAD_MODE`, `KAIKU_HUB_ROBOT_HOME_ID`).
- `config/kaiku.toml [robot]`: `dial_input = ear|button` (prompts + press counting), `press_window_s`, `drum_sway`
  (`drum_input` is for the sims). `[attention] camera_on_head`, `pan_limit_deg`.
- `config/kaiku.toml`: `[ritual]` timings (`greet_s`, `dial_s`, `breathe_s`, `drum_s`, `drum_idle_end_s`,
  `post_mood_s`, `hrv_window_s`, `nudge_s`, `cooldown_s`, `phq9_mode`, `phq9_every_days`), `[perception]`
  thresholds (incl. `tap_force_max_g`, `light_window_min`), `[uplink]`, `[music]` BPM clamp, `[models]` IDs
  (`VERIFY-` placeholders — the Gemini/Lyria adapters refuse to start until they're real), `[safety]` numbers.
  Override any key with `KAIKU_<SECTION>_<KEY>` (e.g. `KAIKU_RITUAL_DRUM_S=10`).
- `config/kaiku.toml [tap_back]`: the whole game (mode, levels, listen and turn times, bands, retries; listed in
  `config/AGENTS.md`). `[music] out = head|speaker|file`, `head_lead_ms`, `head_gain`; `[voice] audio =
  auto|head|local`; `[live] mic_gap_end_s`. Env: `KAIKU_TAP_BACK_MODE`, `KAIKU_MUSIC_OUT`, `KAIKU_VOICE_AUDIO`,
  `KAIKU_MUSIC_FILE=<path.wav>` (music into a file, wins over `[music] out`).
- `config/safety_phrases.toml`: crisis phrases (en/fi/sv) + verbatim scripts; the gate refuses to start without it.
- `.env`: `KAIKU_HOME_ID`, `KAIKU_CLOUD_URL`, `KAIKU_HOME_TOKEN`, `MQTT_*`, `GEMINI_API_KEY`,
  `KAIKU_HEAD=atech|sim`, `KAIKU_SENSORS=unoq|sim`, `KAIKU_VOICE=gemini|text|off`, `KAIKU_MUSIC=lyria|local|off`,
  `KAIKU_DEMO_MODE=1` (offer on each arrival after cooldown; acceptance still required).
- Hub-only env: `KAIKU_HUB_STATE_PATH` (default `logs/hub_state.json`), `KAIKU_LORA_PORT`, `KAIKU_LOCAL_TTS=1`
  (legacy switch enables cached Gemini audio playback, never OS speech), `KAIKU_LOCAL_CLICK=1`.
- Optional deps: `uv sync --extra live` (google-genai, sounddevice), `--extra camera` (OpenCV), `--extra lora`
  (pyserial). Missing extras fall back softly (gemini → text, lyria → local, camera → off). `sounddevice` is only
  needed for `[music] out = "speaker"` and `[voice] audio = "local"`; with the head's audio the hub needs `numpy`
  and `google-genai` only.

## Health signal
`kaiku/v1/<home>/health/hub` (retained, every 5 s; last will = `down`). `details`: `ritual` (current step or
`idle`), `uplink_queue`, `uplink_lag_s`, `uplink_error`, `voice`, `music`, `cloud`, `episodes_queue`,
`music_out`, `voice_audio` (`head|local|auto|none`), `store` (`ok|off|error`), `head_mode` (`follow|drive`; following: `ritual` = `head:<step>`), `head_cmds_held`, `dropped` (bus publishes
dropped while offline). `degraded` signals: growing `uplink_queue`, non-null `uplink_error`.

## Tests
```bash
uv run pytest hub/tests      # ~10 s; the MQTT integration test needs mosquitto installed (skips otherwise)
```

- `test_perception.py`: tap tempo/regularity/refractory, HRV RMSSD on synthetic PPG with known IBIs, quality
  gate, presence first-of-day, light windows, speech features.
- `test_safety.py`: every trigger (en/fi/sv phrases, curly apostrophes, PHQ-9 item 9, long-press), no false
  positives on ordinary lines, verbatim script, and an AST check that `safety/` imports no LLM/network code.
- `test_rituals.py`: step order (PHQ9 only when due + spoken), dial ×3 (ear / voice / tool / timeout), drum
  session + post-activity mood + intervention_response, breathe HRV + intervention_response, spoken PHQ-9
  (complete, item 9 stops the ritual, never partial), skip, abort, broken-step isolation, hard cap, nudge outcome.
- `test_uplink.py`: obs-only, dedupe, offline queue survives restart, 5xx/network retry + backoff, auth keeps
  data, poison batch dropped, safety flag first + immediate.
- `test_cloudlink.py`, `test_hub.py`: commands dedupe/`since`, nudge fallback, crisis paths through the Hub
  (and that they load no LLM modules), sim flag propagation, contract check of every emitted obs type.
- `test_attention.py`: full ladder order (glance → purr → greeting → offer), state steps, greeting by time of day,
  flicker (< 2 s no reset, > 2 s homes), two faces (+ one-face jitter ≠ two), quiet mode, night boundaries
  (22:59/23:00/06:59/07:00), person-started at night, re-greet 2:59 vs 3:01, ritual done today, ritual running,
  presence without camera, pan smoothing + deadband, track rate limit, TOML time env overrides.
- `test_greeting.py`: voice lines (cloud audio, memory cache, 404/503/offline → text, fallback keys), companion
  session (404/ok/offline), Live config fields (+ validated by the installed `google-genai` types), UNO Q box →
  RawFace, Hub: approach → greeting + offer → "not now" ends it + quiet; two people no offer; done today no offer;
  own `raw.hub.face` echo ignored.
- `test_context_events.py`: vocabulary/format, no digits/state words (seeded property test), rate limit 19 s vs
  20 s, dedupe, 9th event dropped, no-session no-op, DrumFeel relative to start, breathing/light/late rules, voice
  no-ops + text print, Hub: breathing event from its own obs, thinking set/cleared, 8 s timeout line + ritual
  continues, crisis keeps the crisis body.
- `test_budget.py` (temp `KAIKU_SPEND_DB`): open guards 5 min + charges minute 1, refused near the cap, per-minute
  charges until the cap then `on_exceeded`, stop ends charging, Live doesn't connect over budget.
- `test_live_integration.py`: actual Gemini adapter + Hub with injected audio/model edges: PCM upload, explicit
  consent/timeout, crisis self-cancellation regression, exact activity selection/stop, barge-in during tool calls,
  authentication refusal, reconnect/stop race, expiry, transcript finalization, ack retry and PPG envelope quality.
  Streaming regressions cover fragment/final boundaries, one PHQ-9 answer per completed utterance, both tool/transcript
  arrival orders, duplicate named tools, immediate partial-speech crisis and durable end-session outcome/follow-up.
- `test_episodes.py`: durable offline completion survives restart/retry; PPG timing discontinuities.
- `test_feel.py` (+ two cases in `test_live_integration.py`): `feel` declared NON_BLOCKING from the registry and
  accepted by the installed SDK, no thinking body while it runs, silent when unavailable/slow/invalid, crisis words
  never forwarded, the cloud's crisis answer handled, its own response with `scheduling`, blocking on Vertex.
- `test_agree.py`: `agree_activity` declared from the registry as a blocking tool and accepted by the installed
  SDK, forwarded with surface `robot` and the model's arguments, the cloud's `where` handed back, a refusal and a
  dead cloud as `{ok: false}`, the cloud's crisis answer running the crisis path.
- `test_follow.py`: the follower alone (whole ritual → obs, 1–10 → 1–5 with `scale_10`, press skips, a lost press
  drops answers instead of relabelling, head gone mid-drum, unanswered greetings rate-limited, knocks muted while
  moving, stale retained health) and through the Hub (no `cmd.head`, `start_ritual` refused, record home vs robot
  home, store + episode, fallback to drive for the MQTT firmware / sim head, `head_mode` overrides, a standalone head
  appearing mid hub ritual, head lost, crisis, head on another home). The broker loop is in `sim/tests`.
- `test_robot_data.py`: pulse measured vs not measured (flat, noise, flicker artefact, low sensor quality), camera
  backup at a wobbling frame rate (HR only), finger→camera switch, drum change features, very fast drumming
  (capped + low quality), face-derived presence (brief look-away vs silence), engagement rules (face alone gives no
  level, face share cap, missing ≠ zero, two faces, determinism), store (raw kept, obs linked, pruning, size cap,
  fail soft, no media fields), and through the Hub: stored + summarised ritual, no summary without consent or
  after a crisis, nothing stored outside a ritual, offline nudge limited to `enabled_nudges`.
- `test_integration.py`: real mosquitto + fake head/sensors (dial protocol) → full v2 ritual → self_report ×4,
  hrv, drum, intervention_response, nudge obs.
- `test_tap_back.py`: the bands and their edges, half and double beat, steadiness, too few taps, the level plan by
  date (deterministic, different the next day, inside the music's range), the payload, every line through the
  wording rules, and the whole step on fakes: a full game → `obs.tap_back` and the mood question, again then
  move on, silence, taps outside her turn never counted, her turn opening only once the speaker is quiet, `auto`
  with and without a song, a song lost mid-game → free drumming, forced mode with the beat and with the light
  only, the hard cap, one tap from two boards counted once.
- `test_tap_back_follow.py`: the hub holding a self-running head's drum step (the `hold` in every command and
  between them, the game, `end`), no song → no command, the head leaving mid-game, a crisis mid-game (one message
  with the end of the hold and the help screen).
- `test_follow_voice.py`: the conversation on a self-running head with the production Live adapter (model, cloud
  and bus faked): her press opens it (intent `ritual`, step tools neither offered nor run), each step's line said
  through the head, goodbye then microphone and session closed; a ritual joined mid-way or started unseen opens
  nothing; the invitation not repeated at every greeting; `end_session` leaves the ritual; the microphone closed
  for the whole game in follow and in drive mode and never left closed; `Voice.listen`; a line waiting for
  Kaiku's own words; the sway line; a crisis in a follow-mode and in a drive-mode conversation (microphone closed
  first and never reopened, keep-alive stopped, speaker dropped, help screen first or with the drum end, one
  safety flag, nothing of the game recorded, `show: none` at the next ritual); the one re-send of the help screen
  (never to a head with no screen); no game on a head that cannot hold its drum step; `auto` takes the head for
  sound only when its firmware can sound; her taps as the head's own sensor reports them.
- `test_trace.py`: a ritual with the voice publishes `said` / `heard` / `tool` / `session` / `game` / `music`
  with the right fields and none of her words, the instruction or a tool's arguments; scripted lines and how they
  were spoken; only the script line after a crisis; a stuck or failing publish never holds up a line;
  `[hub] trace = false`; what the contract refuses.
- `test_head_audio.py`: the resampler (passband, stop band, in pieces = in one go, 24 → 16 kHz), 640-byte frames
  with headroom, one frame per 20 ms a little ahead and never far, the faded end then the drop message, a sound
  that starts while Kaiku speaks waits whole, Kaiku's voice never waits behind music and the two never interleave,
  cutting the voice, the microphone held open by commands, `auto`, and a hub that imports and builds with no
  `sounddevice` for music and voice (subprocess).
- `test_head_voice.py`: the production Live adapter on the real `HeadAudio` with the model faked: listening and
  speaking through the head only, a microphone gap that is never filled with silence and told to the server once,
  the ear press that stops Kaiku and the rest of that answer, the hub calling it, music and voice sharing the
  speaker, a scripted line heard from the head and never from this machine's player.
- `test_lyria.py`: the music adapter on a fake session: `song` / `hush` / `chime`, `can_play_songs`, a dead
  stream, the hub's own beat, the realtime WAV.

## Known issues
- Real physical robot microphone/speaker, motor, sensors and voice quality still need bench validation. The actual
  production adapter/controller is tested with fake model/audio edges and with a real Gemini session fed generated
  synthetic PCM through its microphone callback; actual Gemini output, ask_mind and transcript persistence passed.
  Isolated real MQTT and synthetic cloud flows test data persistence. These do not establish hardware readiness. `lyria.py` remains unverified on physical audio.
- Cloud bootstrap failures leave voice unavailable; there is no local-key bypass. The fixed crisis script remains
  visible; no pre-recorded deterministic crisis audio asset is bundled yet.
- `greet.two` is not in `config/voice_lines.toml` yet: the hub speaks a built-in fallback text
  (`live/lines.py FALLBACK_TEXT`) and the cloud returns 404 for its audio until the config owner adds it.
- `HeadCmd` has no ear command: "ear up" is approximated with `eyes: listening`. Pan sign: `+target_deg` = toward
  the camera image's right; the head firmware maps it to its motor direction.
- **UNO Q face boxes (owner A):** see `devices/unoq_yolo.py` docstring — one `raw.hub.face` per box per frame at
  ~5 Hz, source `sensors`, `x_norm/y_norm` = box centre in −1..1, `size` = box width / frame width (use
  `box_to_face`), obey `cmd.sensors {camera_enable}`, never send frames. Then set `[attention] face_source = "unoq_yolo"`.
- The laptop face source (`perception/face.py`) is OpenCV Haar (`uv sync --extra camera`), not MediaPipe yet.
- `devices/atech_adapter.py` is a stub until the Atech spike (D6) says whether the head can speak MQTT.
- `speech.py` is rough energy VAD, not a validated absolute speech measure. The existing consented Live microphone
  feeds bounded 20 ms RMS summaries only (no retained PCM). A completed input transcription gates one numeric
  observation; speaker overlap, audio gaps, clipping, silence and overlong turns suppress it. Older provider
  responses without input-finished markers may lose usable metrics when speaker output overlaps; missing is honest.
  `[perception] speech_window_s`, `speech_min_voiced_s`, `speech_clip_fraction` control bounds/quality.
  Camera luminance follows the current `[unoq]` configuration; no physical hall/light sensor is assumed. Light
  windows reject out-of-order/low-quality samples and retain capture timing rather than receive/upload timing.
- `local_audio.py` has no pre-recorded crisis audio or music loop; offline speech failure displays text.
- Pan motor control and homing belong to the head firmware; the hub sends absolute targets only.
- The phrase list will miss things and can false-trigger on quoted speech. See `docs/safety.md`.
- Ritual-time invitations (`set_ritual_time`) only fire while the hub is running, checked every 20 s.
- Env overrides (`KAIKU_RITUAL_DRUM_S=…`) only work for keys that exist in `config/kaiku.toml`.
- Context-event thresholds (light lux, late hours, drum ±15 %, 20 s / 8) are constants in `context_events.py`, not
  yet in `config/kaiku.toml` (config owner). Rate-limited events are dropped, not queued.
- `obs.*` are flagged `sim: true` for 60 s after any sim input arrives.
- Step deadlines are re-checked after every event; a multi-phase step must move `deadline()` forward in
  `on_deadline()` or the machine ends it.
- `state.json` persists `phq9_due` and the pending nudge across restarts; delete `logs/hub_state.json` to reset.

- Robot pulse stays "not measured" on hardware until the finger-cradle retest passes (D39). The gates above were
  tuned on synthetic signals and the one bench artefact; no real finger recording has passed through them yet.
- The engagement summary's reference ranges and weights are fixed design numbers, not validated against any
  outcome. Voice is only present with a real consented Live microphone (never in sim/text mode).
- A sensor-node clock reset mid-drum (`t_ms` going backwards) starts a new tap run: earlier taps are dropped.
- **Sound and the game were shown through the sim head twin only** (2026-11-14): real Lyria and real Gemini Live,
  no sound device, the firmware's wire check on the hub's stream. Not shown: a flashed head, its speaker in a room,
  real taps, a person. Open on hardware: whether the speaker's sound or the sway reaches the tap sensors beyond the
  firmware's mutes, the head's real buffering against Wi-Fi jitter (frames are QoS 0: a lost one is 20 ms of
  silence), the level of `head_gain`, and how Live's turn detection behaves with the head's real microphone.
- **Crisis on THIS robot (its head has no screen, D54): nothing is shown or said to the person beyond everything
  stopping.** The crisis path closes the conversation, the head's microphone (`mic: close`, never reopened), the
  music and whatever the speaker held, and sends `cmd.head {show: help}`; this head cannot show the helpline's
  numbers (it reports `help_screen: "none"`) and takes the command as "stop": its ritual ends quietly, with no
  chime. The script with the helpline's name and number and the emergency number is printed on the hub's terminal
  only, which is the laptop beside the robot tonight; it is never spoken (`say_verbatim` has no sound: no
  pre-recorded crisis audio is bundled, as above). The safety flag is emitted as before (`obs.safety_flag` on the
  uplink's priority lane, queued durably while offline): it reaches the practitioner's dashboard when the uplink
  reaches the cloud, not before. A head with a screen (the MQTT firmware's build, a future head) shows the numbers
  on `show: help`; that is in the firmware source and the twins, **never flashed, never seen on hardware**; such a
  head that was off the broker gets the command once more if it comes back within 10 minutes.
- **The follow-mode conversation was shown through the standalone head TWIN with the real Live model** (2026-11-14,
  `make head-voice FOLLOW=1`), not on a flashed head: her press, Live and the microphone opening on it, a spoken
  question answered through the head's speaker, the dials, Tap it back with the hub's own beat in the same ritual
  with the microphone closed, goodbye, everything closed. The first real run found Kaiku's lines cutting each
  other (fixed; the second run heard every line). **Not shown with the real models: the Lyria game and the Live
  voice together.** The one real run of the robot's exact configuration (`ARGS=--robot`: Live and Lyria through
  the head, record `aino`, boards on `demo-aino`) had the conversation right and LOST THE GAME: the voice held the
  speaker past the song wait (see Invariants → A song waits for Kaiku's words). That is fixed and passes with a
  stand-in voice that speaks the line for 11 s and the hub's own beat (all three levels, taps from the head's own
  sensor only, the record uplinked under `aino`); it has not been run again with the real models (the budget for
  this work was spent). Real Lyria through the head twin was shown earlier the same day with the voice off. Open
  on hardware: everything in the bullet above on sound, plus whether a person hears the invitation out before
  pressing (it is about 13 s long in the cached voice as rendered today), how the model's spoken lines sit with the
  head's own chimes, and whether the model again says a line twice (it did once: 11 s for one sentence).
- **Music that follows her free drumming cannot come out of the head's own speaker on this robot:** her taps are
  felt only by the head's orientation sensor (D55), and the head sends none while its speaker plays. Tap it back is
  built around that (she taps in silence), and in follow mode the hub plays no music for free drumming. In drive
  mode (the twin, a future MQTT build) with `[music] out = "head"` the music would mute the taps it follows: use
  `[music] out = "speaker"` there, or the game.
- `Game` leaves room for spoken words by a per-word estimate (`[tap_back] word_s`) because `say` returns when the
  Live voice starts, not when it ends; on the head the real end is also waited for (`speaker_busy`), on a sound
  card it is the estimate alone.
- With `[voice] audio = "local"` and `[music] out = "speaker"` on one laptop, the song would be heard by the
  open Live microphone. Not tested; the head is half-duplex and does not have this.

## Active sensing profile
Light capture is disabled by default (`[perception] light_enabled=false`): light raw messages cause no observation
or conversation context. The legacy numeric adapter remains for explicit future opt-in. Current build uses knob
ratings, knock timing (no force), camera-derived presence, and quality-gated pulse when available. A failed pulse
window remains missing; it is not synthesised. Spoken features require actual consented user audio and pass the
experimental quality gates described above. Removed hardware is never inferred as a connected source.
