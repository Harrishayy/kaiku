# Privacy

| Data | Where it goes | Stored? |
|---|---|---|
| Robot camera frames (USB camera in the head, read on the UNO Q, D32) | processed in memory on the UNO Q (or the hub laptop's camera) into face position (`raw.hub.face`: x, y, size) and a distance estimate. Only as backups: mean room luminance and the mean green of the forehead patch (`raw.sensors.ppg`) | never; frames never written, logged or transmitted; the camera mic is never opened |
| Robot pulse (camera forehead green on the UNO Q; the KY-039/KY-053 path is not fitted, D48) | ~15 Hz brightness samples, computed in memory from camera frames, on the local bus only during the breathing step (`raw.sensors.ppg`) → HR / HRV numbers in `obs.hrv_session` | samples never uplinked; numbers only |
| Robot knob, button and knock drum | dial values 1–5, press/tap timing → `obs.self_report`, `obs.drum_session`; the knock switch does not measure force | numbers only |
| Laptop webcam frames (`/session`) | processed in the browser for a facial-expressivity number only | never; never transmitted |
| Microphone audio | streamed only to Gemini Live during an active, consented conversation | never by us |
| Speech | consented robot conversation: bounded in-memory microphone energy summaries and received user text derive `obs.speech_features`; silent, clipped, interrupted or incomplete windows are discarded. Legacy browser spoken tasks retain their explicit task path | numeric features only; retained conversation words require the separate opt-in below |
| Reaction task | phone/Mac Firefly reaction median, IQR and lapses in `obs.play_session`; legacy browser session remains available explicitly | numbers only |
| Glasses walks | minutes, steps (location from the paired phone, not stored as a track) in `obs.outing` | numbers only |
| Glasses IMU (DAT SDK, beta) | cadence, gait regularity, head-up ratio computed on the iPhone; raw motion never leaves it | numbers only |
| Glasses camera (DAT camera stream, opt-in "Let Kaiku see through the glasses during walks", off by default, D43) | 360 × 640 frames over the Meta toolkit to the iPhone; about one a second is JPEG-encoded in memory and sent straight to the open Gemini Live conversation of that walk, only while it is open, unmuted and not paused. The walk screen shows when frames flow, with Pause; the camera permission is granted separately in the Meta AI app. Bystanders may be in view: the persona forbids describing or identifying people | never by us: no frame is written, logged, queued or sent to the Kaiku cloud; no observation is derived from frames (the brightness number stays on the phone, shown only in the self-test). The diagnostic log holds counts and sizes only. Google's own Live retention applies as for audio (below) |
| Glasses mic / spoken answers | Bluetooth audio route for the paired iPhone's active, consented Gemini Live conversation; optional on-device safety recognition and speech features are separate | no audio stored by Kaiku; conversation words follow the explicit transcript opt-in below |
| Mac usage rhythm (opt-in, pausable) | frontmost app's **bundle id → broad category on the Mac**, idle time; hourly `obs.screen_activity` (minutes per category, late-night minutes, switches, longest stretch, breaks) | numbers only. **Never** window titles, URLs, keystrokes, screenshots or content (the contract rejects extra fields) |
| Games (Firefly, Pebbles, breathe, tell, Lantern, Seed shelf, Watering) | task-specific reaction, memory-span or speech features; optional camera facial geometry variability computed locally, with method, usable-face coverage and sample count in `obs.play_session`. Pebbles practice is unscored | aggregates only; no frames, audio or inferred emotion labels |
| Watch / Apple Health (optional) | daily summary on the iPhone: sleep minutes + midpoint + regularity, resting HR, HRV, steps, exercise (`obs.wearable_daily`) | daily aggregates only; no raw samples, no location |
| Weather check on phone / Mac / web | three dial values (`obs.self_report`, `channel`) | numbers only |
| Kaiku's notebook (memories) | short facts the person chose to tell Kaiku (`remember`: name, people, places, likes, what helps, plans, preference) in the cloud SQLite | yes, until the person deletes them ("What Kaiku remembers": delete one / all, "don't remember things"); plans expire after 7 days. **Never** health details (refused by rule), never shown to clinicians |
| Episodes | one row per conversation: surface, intent, start/end, tool names, how it ended | yes; **no audio** |
| Conversation transcripts (opt-in, D33) | received words (person + Kaiku), sent by the device only when the person turned "Keep our conversations" on (off by default); optional completion metadata distinguishes explicitly finished, known incomplete and unknown turns | yes, in the cloud, until the person deletes them (saved conversations or delete all); **never** after a crisis (dropped whole), never shown to clinicians, never logged; training export is disabled unless an episode has a separate training-consent and reviewed allowlist entry; automatic redaction is assistive, not proof of de-identification |
| Open thread | one short topic to pick up next time on any device ("the walk by the lake"), expires after 3 days | yes |
| Invitation (one a day) | the open thread or an activity the person has responded to, chosen by rule and worded from a template around their own stored topic; their answer (yes / not now) | the id of answered items only, so the same one is not asked again |
| Walk style (Calm / Playful / Chatty) and spotting goal | the style is a setting on the phone, sent with the walk conversation request; a goal's thing and count live on the phone for that walk only. A find counts when the person says it; nothing is derived from a picture (D43, D45) | the style on the phone; the goal is not stored |
| Kaiku's mind (`ask_mind`) | the question Live asks + ≤ a few clean facts (the person's own memories, approved care passages, words for what they did today) → Gemma primary, with explicit Gemini fallback in the cloud | **no**: nothing stored; only a contentless ledger row |
| Graph memory + vectors | nodes/edges built from the notebook, sessions and what helped; Gemini Embedding 2 vectors of memory text | yes, derived from the notebook; deleting a memory deletes its node and vector; never shown to clinicians, except the shared subset below (D33) |
| Week summary + "What Kaiku has learned" for the care team (D34) | routines from observations, going well / worth a look from the consensus metrics (care team already sees these). Only when the person turns on **Share with my care team** (`/me`, default **off**): the graph's activities and routines (free-text helper notes remain private), plus routines learned from conversations | derived on request, not stored; switching sharing off hides it at once. **Never** people, places, likes, plans, the memories list, episodes or transcripts |
| Usage ledger (`model_calls`) | which model, task, route, latency, ok, fallback | yes; **no content, no text** |
| Walk postcard | a length word, light-hunt find words and a weather word → Nano Banana 2 Lite (fixed style, no people/faces) | the image (cached, shared by everyone with the same walk shape); never photos |
| Weekly clinician brief | consensus metric ids + verdicts → Gemini Argon | yes (clinician-facing); never memories or conversations |
| Kaiku's voice (`/v1/voice`) | fixed script text → Gemini TTS in the cloud | rendered audio of the script only (no personal data) |
| Dynamic voice (`POST /v1/voice/say`) | authenticated short text → Gemini TTS | rendered WAV cached by model/voice/language/text hash under `voice_cache/say`; text may contain personal details supplied by the caller. No automatic TTL or linkage to transcript deletion exists; native apps also cache generated speech locally |
| Raw sensor streams (`raw/*`) | local MQTT on the home network | never uplinked (cloud rejects them) |
| Observations (`obs/*`) | uplinked to the Modal cloud | yes: derived numbers, ritual metadata |
| PHQ-9 | total, 9 item scores, item-9 flag (`obs.phq9`) | yes |
| Verdicts, consensus, explanations | computed in the cloud from derived numbers | yes |
| Clinician briefs | generated in the cloud from derived numbers | yes |

- The robot has a physical camera shutter and status LED; the camera is enabled only when someone is near.
- Consent is collected in the native apps' onboarding and Settings, one switch per signal. There is no separate
  glasses app: glasses registration is an explicit action on the iPhone that does not open the microphone.
- Every plan-02 signal is opt-in per signal, pausable (Mac menu bar), and listed in "What Kaiku saw today".
- A missing source (no watch, no Mac) is simply not counted; it never makes the consensus look worse.
- Browser apps never hold the Gemini key; they authenticate with a pairing token (D16).
- **Memory (plan 03 §6):** Kaiku only keeps what the person tells it and agrees to. "Don't remember that" deletes
  the newest memory; "don't remember things" (or the switch on `/me`) stops all writes until turned back on.
  Categories outside the list, and any text naming medication, treatment, therapy, sleep/heart data, diagnoses or
  similar, are refused. A crisis phrase in any tool call stores nothing and raises the deterministic safety path.
  Clinician routes never read memories, episodes or threads (tested). The model only sees ≤ 3 memories, a name,
  routines and the open thread in the context card — never the consensus state, scores or watch data (`tone`
  `steady|gentle|extra-gentle` is the only soft cue).
- All demo data is synthetic and labelled SIMULATED (`sim: true`).
- No real patient data is used at the hackathon.

- **Current capture profile:** no light observations/context, robot pulse scoring, force, hall sensor, retired browser
  task scoring or unavailable glasses camera/IMU features are fabricated in the default records. The camera can
  still produce a local luminance estimate for bench use; the hub's light path is disabled by configuration.
  Robot pulse requires a successful cradle/quality check before it can be treated as measured. Optional Apple
  Health aggregates are a separate provenance-bearing input. See `config/criteria.toml` and module instructions.
- **Transcript completion is not speech recognition accuracy.** Audio `turnComplete` does not prove that input
  or output transcription is finished. Native turns record `complete=true` only on an explicit provider marker,
  `false` on known interruption/truncation, and `null` when unknown. The current real-provider probe supplied no
  explicit markers; retained text is exactly the received text, with no guessed words or silent rewriting.

- **Provider retention is separate from Kaiku transcript storage.** Stateless cloud Gemini Interactions calls
  explicitly set `store=false`. Live session resumption remains enabled for reconnect support; Google documents
  that a generated session handle can retain conversation state, including audio and text, for up to 24 hours.
  Turning off "Keep our conversations" or deleting a Kaiku transcript removes neither that provider state nor
  any separately applicable provider abuse-monitoring retention. See [Google's retention documentation](https://ai.google.dev/gemini-api/docs/zdr).
  Kaiku has no automatic transcript TTL; authenticated devices currently decide whether to include opted-in
  words in completion uploads. Pending opted-in words can also remain in the device's durable episode outbox
  until delivered. Application deletion is not a guarantee of forensic erasure from SQLite pages or backups.

- D35: Gemma proposes graph organisation on changed clean notebook nodes in a batch, validated by code.
  Session cards are assembled without a generation call; bounded source labels may refresh during an active,
  consented session. The clinician record assistant sees only authorised monitoring evidence, never the notebook
  or conversations. The verified hosted-model demo uses synthetic records; hosted execution is not a private
  Modal GPU claim.
