# hub — AGENTS.md

> Read the root `AGENTS.md` first. Owner B · kind node · consensus source 1 of 3 ("robot"). Update this file in the
> same commit as any change to the hub's interface, structure or invariants (and `modules.toml` if what it
> emits/consumes changes).

## Purpose
The robot's brain, running on the hub laptop. Turns local raw streams into derived `obs.*` (perception), runs the
morning ritual state machine `IDLE → GREET → DIAL(mood, energy, sleep) → BREATHE → DRUM(+ post-activity mood) →
[PHQ9 if due] → NUDGE → CLOSE`, runs the deterministic crisis gate (no LLM), drives the voice/music adapters, and
ships observations to the cloud (offline-safe). Raw data never leaves the home. Glasses and laptop apps do NOT come
through the hub — they post to the cloud directly.

## Boundaries
May import `kaiku_contracts` + third-party libs only — never `cloud`, `sim`, `apps`, `tools`.

## Consumes (topics/endpoints)
| Topic / endpoint | Used for |
|---|---|
| `kaiku/v1/<home>/raw/head/tap` | drum step (tempo, force, regularity) |
| `kaiku/v1/<home>/raw/head/ear` | dial answers (`value` = dial position 1–5, each `pressed` answers the current question: mood → energy → sleep); post-drum mood; spoken PHQ-9 (dial 1→0 … 4–5→3); press when idle → ad-hoc mood |
| `kaiku/v1/<home>/raw/sensors/ppg` | breathe step HRV (only streamed between `cmd/sensors {ppg:start/stop}`) |
| `kaiku/v1/<home>/raw/sensors/distance` | presence → arrival → ritual start |
| `kaiku/v1/<home>/raw/sensors/light` | `obs/light_level` (hourly mean) |
| `kaiku/v1/<home>/raw/sensors/button` (`id: "top"`) | short press → start ritual; hold ≥ 2 s → crisis (manual) |
| `kaiku/v1/<home>/raw/hub/face` | greet step: head looks at the face |
| `kaiku/v1/<home>/cmd/hub` | `start_ritual`, `say` (text utterance, safety-gated), `suggest_nudge`, `set_ritual_time`, `clinician_message`, `phq9_due` |
| `kaiku/v1/<home>/cmd/friendlink` | `ping` → LoRa gateway |
| `kaiku/v1/<home>/obs/#` (non-hub sources) | `obs/phq9` with `item9_positive` → crisis; relays other local obs (e.g. friendlink sim) to the cloud |
| `kaiku/v1/<home>/health/+` | node heartbeats → `PUT /v1/health/{home}` |
| `GET /v1/commands?home_id&since` | cloud → hub commands (republished on `cmd/hub`) |
| `GET /v1/nudge?home_id` | bandit arm (falls back to clinician suggestion, then uniform random) |

## Emits (topics/endpoints)
| Topic / endpoint | When |
|---|---|
| `obs/ritual` | every step: `started` then `completed` / `skipped` / `aborted` with `duration_s` |
| `obs/presence` | confirmed arrival (`first_of_day` = get-up proxy) |
| `obs/self_report` | dial step ×3 (`item: mood/energy/sleep`, `context: ritual`), after drumming (`mood`, `post_activity`), ear press when idle (`mood`, `adhoc`) |
| `obs/intervention_response` | breathe (`pre/post rmssd_ms + hr_bpm`, first/last 30 s of PPG) and drum (`pre/post mood`) |
| `obs/phq9` | spoken PHQ-9 (`mode: spoken`) when due and `[ritual] phq9_mode` is `spoken`/`both`; item 9 > 0 → crisis path |
| `obs/hrv_session` | breathe step, if PPG passes the quality gate (`quality` = clean-beat ratio) |
| `obs/drum_session` | drum step with ≥ 4 taps, emitted when drumming ends (before the post-activity mood question) |
| `obs/nudge_offered`, `obs/nudge_outcome` | nudge step; outcome after the next day's dial (`next_day{mood, energy}`, reward in 0–1) |
| `obs/light_level` | each light window |
| `obs/friend_link` | LoRa ping sent/received |
| `obs/safety_flag` | any crisis trigger (priority uplink, deduped per trigger for 60 s) |
| `cmd/head`, `cmd/sensors` | eyes, pan, chest, purr; `ppg: start/stop` |
| `health/hub` | retained heartbeat every 5 s (ritual state, uplink queue/lag/error, adapters) |
| `POST /v1/events` | batched obs (Bearer `KAIKU_HOME_TOKEN` if set) |
| `PUT /v1/health/{home_id}` | every 10 s: all node heartbeats + uplink queue/lag |

Obs are marked `sim: true` when they were derived from sim inputs in the last 60 s.

## Map
```
kaiku_hub/
  main.py          Hub: wiring + RitualContext impl (say/head/sensors/emit/get_nudge), bus handlers,
                   crisis(); emit() is the ONLY way obs leave (validate -> bus -> uplink; PHQ-9 safety check)
  settings.py      config/kaiku.toml + env -> Settings dataclass (all timings/thresholds/model IDs)
  state.py         small persistent JSON: last arrival, today's dial, pending nudge, phq9_due, ritual time
  rituals/
    machine.py     generic step runner: applies / enter / handle / on_deadline / on_timeout / exit, skip,
                   abort, hard cap, stop_ritual, broken-step isolation
    steps.py       Greet, Dial, Breathe, Drum, Phq9, Nudge, Close + default_steps(settings)
  perception/      taps.py, hrv.py (PpgBuffer.pre_post / session), presence.py, light.py, speech.py, face.py
  safety/gate.py   SafetyGate (phrases en/fi/sv, PHQ-9 item 9), ButtonLongPress, CrisisScript (verbatim)
  live/            base.py (Voice/Music interfaces), factory.py (env -> adapter), text.py, gemini_live.py,
                   lyria.py, local_audio.py, tools.py (function-calling tools + system prompt)
  devices/         atech_adapter.py (stub), lora_serial.py (friend link), camera.py
  uplink.py        SQLite offline queue, batches, backoff, safety_flag priority lane, obs-only
  cloudlink.py     command polling (since), nudge lookup with fallback, node-health reports
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
  `live/factory.py` by `KAIKU_VOICE` / `KAIKU_MUSIC`. Must fail soft (fall back to text/local). Model IDs in
  `config/kaiku.toml [models]` only. Tool names/semantics live in `live/tools.py`; `Hub.on_tool` maps them.
- **Add a device adapter:** `devices/<vendor>.py` converting vendor I/O ↔ contract messages, selected by env
  (`KAIKU_HEAD=atech|sim` style), with a sim twin in `sim/nodes/`.
- **Remove a piece:** steps, adapters and perception modules are independent; delete + drop from
  `default_steps()` / `factory.py` / `Hub.__init__`, then `make test`.

## Invariants
- **Safety runs first and is deterministic:** every utterance goes through `SafetyGate.check_text` before
  anything else; every `obs.phq9` passing through `emit()`/`on_obs()` is checked for item 9. `safety/` imports
  no LLM/network code (a test enforces it). The crisis message is spoken verbatim from `config/safety_phrases.toml`.
- **Every emitted message validates** (`make()` in `emit()`); `test_hub.py` greps all `emit("obs.*")` calls
  against the contracts registry.
- **Never block the event loop**; network calls have timeouts; a dead broker/cloud/voice never crashes the hub.
- **Raw never leaves the home:** the uplink sends `obs.*` only.
- **Dial protocol** (head firmware + `sim/nodes/head_sim.py` depend on it): each ear *press* answers the current
  question with the dial position at that moment (order mood → energy → sleep); the post-activity mood is
  asked right AFTER `obs.drum_session` is emitted; spoken PHQ-9 accepts presses (dial 1→0, 2→1, 3→2, 4–5→3).
- A PHQ-9 is only emitted when all 9 items are answered (never partial).

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
KAIKU_VOICE=text make hub      # terminal 3 — sims walk up, the ritual starts; or type `start`
make tail TOPIC='kaiku/v1/+/obs/#'   # terminal 4
```

Fast ritual for testing: `KAIKU_RITUAL_GREET_S=2 KAIKU_RITUAL_DIAL_S=20 KAIKU_RITUAL_BREATHE_S=15 KAIKU_RITUAL_DRUM_S=10 make hub`.
Spoken PHQ-9: `KAIKU_RITUAL_PHQ9_MODE=spoken` and send `cmd.hub {phq9_due: true}` (or say "start_phq9" via Gemini).
Start immediately: `make hub ARGS=--start`.

## Config & env
- `config/kaiku.toml`: `[ritual]` timings (`greet_s`, `dial_s`, `breathe_s`, `drum_s`, `drum_idle_end_s`,
  `post_mood_s`, `hrv_window_s`, `nudge_s`, `cooldown_s`, `phq9_mode`, `phq9_every_days`), `[perception]`
  thresholds (incl. `tap_force_max_g`, `light_window_min`), `[uplink]`, `[music]` BPM clamp, `[models]` IDs
  (`VERIFY-` placeholders — the Gemini/Lyria adapters refuse to start until they're real), `[safety]` numbers.
  Override any key with `KAIKU_<SECTION>_<KEY>` (e.g. `KAIKU_RITUAL_DRUM_S=10`).
- `config/safety_phrases.toml`: crisis phrases (en/fi/sv) + verbatim scripts; the gate refuses to start without it.
- `.env`: `KAIKU_HOME_ID`, `KAIKU_CLOUD_URL`, `KAIKU_HOME_TOKEN`, `MQTT_*`, `GEMINI_API_KEY`,
  `KAIKU_HEAD=atech|sim`, `KAIKU_SENSORS=unoq|sim`, `KAIKU_VOICE=gemini|text|off`, `KAIKU_MUSIC=lyria|local|off`,
  `KAIKU_DEMO_MODE=1` (start a ritual on every arrival after the cooldown).
- Hub-only env: `KAIKU_HUB_STATE_PATH` (default `logs/hub_state.json`), `KAIKU_LORA_PORT`, `KAIKU_LOCAL_TTS=1`
  (macOS `say` / `espeak` for scripted lines), `KAIKU_LOCAL_CLICK=1`.
- Optional deps: `uv sync --extra live` (google-genai, sounddevice), `--extra camera` (OpenCV), `--extra lora`
  (pyserial). Missing extras fall back softly (gemini → text, lyria → local, camera → off).

## Health signal
`kaiku/v1/<home>/health/hub` (retained, every 5 s; last will = `down`). `details`: `ritual` (current step or
`idle`), `uplink_queue`, `uplink_lag_s`, `uplink_error`, `voice`, `music`, `cloud`, `dropped` (bus publishes
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
- `test_integration.py`: real mosquitto + fake head/sensors (dial protocol) → full v2 ritual → self_report ×4,
  hrv, drum, intervention_response, nudge obs.

## Known issues
- `gemini_live.py` / `lyria.py` are written against the google-genai SDK as we understand it but are
  **untested**: verify model IDs, method names and audio formats in current docs before the demo.
- `devices/atech_adapter.py` is a stub until the Atech spike (D6) says whether the head can speak MQTT.
- `speech.py` is rough (energy VAD); it only tracks change against the person's own baseline.
  The hub doesn't capture mic audio for it yet (Gemini Live owns the mic). TODO: tap the same audio stream.
- `local_audio.py` has no pre-recorded lines or music loop yet; offline mode prints (and optionally TTS-speaks) lines.
- Face tracking emits `look` targets during greet only. Pan control and homing belong to the head firmware.
- The phrase list will miss things and can false-trigger on quoted speech. See `docs/safety.md`.
- Ritual-time invitations (`set_ritual_time`) only fire while the hub is running, checked every 20 s.
- Env overrides (`KAIKU_RITUAL_DRUM_S=…`) only work for keys that exist in `config/kaiku.toml`.
- `obs.*` are flagged `sim: true` for 60 s after any sim input arrives.
- Step deadlines are re-checked after every event; a multi-phase step must move `deadline()` forward in
  `on_deadline()` or the machine ends it.
- `state.json` persists `phq9_due` and the pending nudge across restarts; delete `logs/hub_state.json` to reset.
