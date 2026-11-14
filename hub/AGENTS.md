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
| `kaiku/v1/<home>/raw/head/tap` | drum step (tempo, force, regularity); `force` absent for the KY-031 knock switch → `force_mean: null` |
| `kaiku/v1/<home>/raw/head/ear` | dial answers (`value` = dial position 1–5, each `pressed` answers the current question: mood → energy → sleep); post-drum mood; spoken PHQ-9 (dial 1→0 … 4–5→3); press when idle → ad-hoc mood |
| `kaiku/v1/<home>/raw/sensors/ppg` | breathe step pulse (only streamed between `cmd/sensors {ppg:start/stop}`): KY-039 100 Hz → HR + RMSSD (`method: finger`); camera backup ~15 Hz at a wobbling measured rate → resampled, HR only (`method: camera`, quality ≤ 0.6) |
| `kaiku/v1/<home>/raw/sensors/distance` | presence → `obs/presence` + the attention ladder (no camera = presence alone means "at desk"). On the build it is the UNO Q's estimate from the face box (`far_cm` = no face): a face turned away for `[hub] presence_leave_s` = left; no reading for `presence_stale_s` = unknown, not "here" |
| `kaiku/v1/<home>/raw/sensors/light` | `obs/light_level` (hourly mean) |
| `kaiku/v1/<home>/raw/sensors/button` (`id: "top"`), `raw/head/button` (`id: "head"`) | short press idle → start ritual; hold ≥ 2 s → crisis (manual); button build (`[robot] dial_input = "button"`): short presses during a ritual → one dial answer per run (`perception/presses.py`, `press_window_s`), fed as the ear event below |
| `kaiku/v1/<home>/raw/hub/face` (source ≠ `hub`) | attention ladder (one message per face per frame; UNO Q YOLO or sim) + greet step looks at the face |
| `kaiku/v1/<home>/cmd/hub` | `start_ritual`, `say` (text utterance, safety-gated), `suggest_nudge`, `set_ritual_time`, `clinician_message`, `phq9_due` |
| `kaiku/v1/<home>/cmd/friendlink` | `ping` → LoRa gateway |
| `kaiku/v1/<home>/obs/#` (non-hub sources) | `obs/phq9` with `item9_positive` → crisis; relays other local obs (e.g. friendlink sim) to the cloud |
| `kaiku/v1/<home>/health/+` | node heartbeats → `PUT /v1/health/{home}` |
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
| `obs/drum_session` | drum step with ≥ 4 taps, emitted when drumming ends (before the post-activity mood question): tempo, regularity, taps, first/last-third tempo, `taps_per_s`, `pauses`, `rejected_taps`; `quality` = share of triggers that were real taps |
| `obs/engagement` | once at the end of a ritual whose conversation the person accepted (never after a crisis): the multi-cue summary (Invariants → Engagement summary) |
| `obs/nudge_offered`, `obs/nudge_outcome` | nudge step; outcome after the next day's dial (`next_day{mood, energy}`, reward in 0–1) |
| `obs/light_level` | legacy opt-in only (`[perception] light_enabled=true`), capture-ordered usable light window; actual capture timestamp and lowest reported sensor quality retained |
| `obs/speech_features` | completed consented user speech: numeric pace/pause features only; silence, clipping, speaker overlap or capture gaps remain missing |
| `obs/friend_link` | LoRa ping sent/received |
| `obs/safety_flag` | any crisis trigger (priority uplink, deduped per trigger for 60 s) |
| `cmd/head`, `cmd/sensors` | attention: `eyes` glance/`listening`, `look` + `pan{target_deg}` tracking (smoothed, deadband, ≤ 5 Hz), `purr`, `home`; ritual: eyes, pan_mode, chest, purr; `ppg: start/stop`; `camera_enable` (unoq_yolo) |
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
    steps.py       Greet, Dial, Breathe, Drum, Phq9, Nudge, Close + default_steps(settings)
  perception/      taps.py, hrv.py (PpgBuffer.pre_post / session), presence.py, light.py, speech.py, face.py,
                   engagement.py (EngagementTracker + fuse: the multi-cue summary, pure)
  store.py         SessionStore: local SQLite of each ritual's raw numbers + emitted obs (never uplinked)
  safety/gate.py   SafetyGate (phrases en/fi/sv, PHQ-9 item 9), ButtonLongPress, CrisisScript (verbatim)
  live/            base.py (Voice/Music interfaces; open_session/close_session per ritual), factory.py,
                   text.py, gemini_live.py (configured model, automatic VAD/barge-in, bounded resumption, [voice].name),
                   lines.py (keyed cloud Gemini cache + dynamic Gemini TTS -> visible text), lyria.py, local_audio.py,
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
- **Thinking body:** while any `executor: cloud` tool (e.g. `ask_mind`) is in flight → `cmd.head {eyes: thinking,
  look: up}`; restored to the last eyes after (not after a crisis — the crisis body stays). > 8 s
  (`THINK_TIMEOUT_S`; `ask_mind` uses `[live] mind_timeout_s` for Gemma reasoning) → the tool answers `{ok: false}`, Kaiku says "Let me think about that later." and the ritual
  goes on.

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
  `presence_leave_s`, `presence_stale_s`, `engagement_enabled` (env e.g. `KAIKU_HUB_STORE_PATH`).
- `config/kaiku.toml [robot]`: `dial_input = ear|button` (prompts + press counting), `press_window_s`, `drum_sway`
  (`drum_input` is for the sims). `[attention] camera_on_head`, `pan_limit_deg`.
- `config/kaiku.toml`: `[ritual]` timings (`greet_s`, `dial_s`, `breathe_s`, `drum_s`, `drum_idle_end_s`,
  `post_mood_s`, `hrv_window_s`, `nudge_s`, `cooldown_s`, `phq9_mode`, `phq9_every_days`), `[perception]`
  thresholds (incl. `tap_force_max_g`, `light_window_min`), `[uplink]`, `[music]` BPM clamp, `[models]` IDs
  (`VERIFY-` placeholders — the Gemini/Lyria adapters refuse to start until they're real), `[safety]` numbers.
  Override any key with `KAIKU_<SECTION>_<KEY>` (e.g. `KAIKU_RITUAL_DRUM_S=10`).
- `config/safety_phrases.toml`: crisis phrases (en/fi/sv) + verbatim scripts; the gate refuses to start without it.
- `.env`: `KAIKU_HOME_ID`, `KAIKU_CLOUD_URL`, `KAIKU_HOME_TOKEN`, `MQTT_*`, `GEMINI_API_KEY`,
  `KAIKU_HEAD=atech|sim`, `KAIKU_SENSORS=unoq|sim`, `KAIKU_VOICE=gemini|text|off`, `KAIKU_MUSIC=lyria|local|off`,
  `KAIKU_DEMO_MODE=1` (offer on each arrival after cooldown; acceptance still required).
- Hub-only env: `KAIKU_HUB_STATE_PATH` (default `logs/hub_state.json`), `KAIKU_LORA_PORT`, `KAIKU_LOCAL_TTS=1`
  (legacy switch enables cached Gemini audio playback, never OS speech), `KAIKU_LOCAL_CLICK=1`.
- Optional deps: `uv sync --extra live` (google-genai, sounddevice), `--extra camera` (OpenCV), `--extra lora`
  (pyserial). Missing extras fall back softly (gemini → text, lyria → local, camera → off).

## Health signal
`kaiku/v1/<home>/health/hub` (retained, every 5 s; last will = `down`). `details`: `ritual` (current step or
`idle`), `uplink_queue`, `uplink_lag_s`, `uplink_error`, `voice`, `music`, `cloud`, `episodes_queue`,
`store` (`ok|off|error`), `dropped` (bus publishes
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
- `test_robot_data.py`: pulse measured vs not measured (flat, noise, flicker artefact, low sensor quality), camera
  backup at a wobbling frame rate (HR only), finger→camera switch, drum change features, very fast drumming
  (capped + low quality), face-derived presence (brief look-away vs silence), engagement rules (face alone gives no
  level, face share cap, missing ≠ zero, two faces, determinism), store (raw kept, obs linked, pruning, size cap,
  fail soft, no media fields), and through the Hub: stored + summarised ritual, no summary without consent or
  after a crisis, nothing stored outside a ritual, offline nudge limited to `enabled_nudges`.
- `test_integration.py`: real mosquitto + fake head/sensors (dial protocol) → full v2 ritual → self_report ×4,
  hrv, drum, intervention_response, nudge obs.

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

## Active sensing profile
Light capture is disabled by default (`[perception] light_enabled=false`): light raw messages cause no observation
or conversation context. The legacy numeric adapter remains for explicit future opt-in. Current build uses knob
ratings, knock timing (no force), camera-derived presence, and quality-gated pulse when available. A failed pulse
window remains missing; it is not synthesised. Spoken features require actual consented user audio and pass the
experimental quality gates described above. Removed hardware is never inferred as a connected source.
