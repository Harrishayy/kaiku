# The Gemini API in Kaiku

> Part of [the stack pages](INDEX.md). Read from the code on 15 November 2026. Model IDs live in
> [`config/kaiku.toml`](../../config/kaiku.toml). Module docs: [`hub/AGENTS.md`](../../hub/AGENTS.md),
> [`apps/apple/AGENTS.md`](../../apps/apple/AGENTS.md), [`cloud/AGENTS.md`](../../cloud/AGENTS.md).

**In one paragraph.** Gemini Live is Kaiku's one voice on four bodies: the iPhone, the Mac, the Meta glasses and
the desk robot. It is the only part of Kaiku that hears the person, and its function calls are how a
conversation does things: turn the robot's check-in forward, count a find on a walk, put an activity card on the
phone, tell Kaiku's mind that a sentence sounded heavy. Around it sit six more Gemini models, each with one job.
None of them decides a person's state or handles a crisis; that is code.

## Every model, and its one job

| Model | Job in Kaiku | Called from |
|---|---|---|
| `gemini-3.8-live` | Every spoken conversation, with function calling; glasses pictures on a walk | Robot: `google-genai` (`client.aio.live.connect`) in [`hub/kaiku_hub/live/gemini_live.py`](../../hub/kaiku_hub/live/gemini_live.py). Apps: a raw WebSocket in [`Talk/LiveSession.swift`](../../apps/apple/KaikuKit/Sources/KaikuKit/Talk/LiveSession.swift) |
| `gemini-3.8-flash-tts` | The fixed lines, in the same voice (`Sulafat`) as Live, rendered once and cached | [`cloud/kaiku_cloud/voice.py`](../../cloud/kaiku_cloud/voice.py) |
| `gemini-embedding-2` (768 dimensions) | A vector for each note she lets Kaiku keep, and for a question | [`mind/graph.py`](../../cloud/kaiku_cloud/mind/graph.py), [`llm/gemini.py`](../../cloud/kaiku_cloud/llm/gemini.py) |
| `lyria-realtime-exp` | The robot's drum music, steered in tempo while it plays | [`hub/kaiku_hub/live/lyria.py`](../../hub/kaiku_hub/live/lyria.py) |
| `gemini-3.8-flash` | Fallback behind Gemma for `ask_mind` | [`mind/router.py`](../../cloud/kaiku_cloud/mind/router.py) |
| `gemini-4-argon` | Escalation for care, emotional or conflicting questions (at most 20 a day per home); the weekly practitioner brief; the daily reflection | `mind/router.py`, `mind/brief.py`, `mind/reflect.py` |
| `gemini-3.1-flash-lite-image` | A postcard of a walk (at most 3 a day per home) | `mind/postcard.py` |

Hosted [Gemma](gemma.md) is also reached through the Gemini API. The SDK is `google-genai` everywhere in Python;
the legacy package is not used.

## Gemini Live, in depth

### The session

Both the hub and the apps open the same kind of session
(`live_config()` in `gemini_live.py`; `live_token.setup()` in
[`mind/live_token.py`](../../cloud/kaiku_cloud/mind/live_token.py)):

- **Audio out, with transcripts both ways.** `response_modalities: ["AUDIO"]`, input and output transcription
  on. The captions on screen, the crisis gate and the "Mute Kaiku" button all rest on those transcripts.
- **Barge-in.** `START_OF_ACTIVITY_INTERRUPTS`. The app flushes playback when the server says `interrupted`, and
  does not answer tool calls the interruption cancelled.
- **Voice activity tuned for the person.** End-of-speech sensitivity low and 900 ms of silence before a turn
  ends, because someone who is low speaks slowly and pauses. A headset (the glasses, AirPods) gets its own
  tuning: start sensitivity high and 800 ms, since those microphones are aimed at the wearer.
- **Long calls on short tokens.** `session_resumption` and sliding-window `context_window_compression`, so a
  30-minute walk survives both the provider's limits and a 5-minute token.
- **Proactive audio, on walks only.** It lets Kaiku answer a "look" nudge with silence when there is nothing
  worth saying. Everywhere else it is off (D49): with it on, a real check-in left plain statements unanswered.
- **Affective dialog: off.** Turning it on closed the session with error 1007 on the first turn (real calls,
  14 Nov), and a test now asserts the field is never sent.

### One persona, four bodies

The system instruction is assembled by code, never by a model
([`mind/assemble.py`](../../cloud/kaiku_cloud/mind/assemble.py)): the persona
([`config/persona.md`](../../config/persona.md)), then "your body right now" from
[`config/surfaces.toml`](../../config/surfaces.toml), then today's card. The body changes how Kaiku speaks:

| Body | Words per turn (target / most) | What is different |
|---|---|---|
| Robot | 20 / 30 | Can start breathing or the drum, turn its head, ask about its camera |
| Glasses | 8 / 16 | Never points at a screen; three walk styles (calm 8/16, playful 14/26, chatty 16/30) |
| iPhone, Mac | 20 / 35 | Can put a card in the chat |

### What the voice knows, and what it never sees

The voice starts from a **context card** built by code with no model call
([`mind/card.py`](../../cloud/kaiku_cloud/mind/card.py)): her first name, the time of day, what she has done
today in words, activities she agreed to, up to three memories she chose to share, an open thread from last
time, and one sentence of tone. The card is capped at about 400 tokens.

It never contains a score, a state or a measurement. The assembler refuses any card key that looks like one
(`state`, `score`, `verdict`, `consensus`, `baseline`, `risk`, `heart`, `steps`, `face`, `camera` and more). The
only thing the consensus contributes is the tone: steady, gentle or extra-gentle. So the voice can be kinder on
a harder week without ever being able to say why, or to say a number (D35).

### Short-lived tokens

The apps never hold the API key. `POST /v1/companion/session` on the cloud mints an ephemeral token:
one use, one minute to start a session, at most five minutes of life, locked to the model. The app renews it
without the person noticing: 45 seconds before expiry it waits for a gap between sentences, asks the cloud for a
new token for the same session, opens a second socket with the resumption handle and closes the first. The
robot's hub runs on the team's own machine and uses the key directly.

Every mint reserves its cost in a spend ledger first and settles to the minutes really used (D46). If the cap
is reached, or the mint fails, the microphone simply stays closed.

### Function calling: the voice has hands

The tool list is one registry
([`contracts/python/kaiku_contracts/companion_tools.py`](../../contracts/python/kaiku_contracts/companion_tools.py));
each body gets the tools that make sense for it.

| Tool | Runs on | What it does |
|---|---|---|
| `feel` | cloud, **non-blocking** | Tells Kaiku's mind what the voice heard (kind, tone, energy). Code answers with a plan: comfort, celebrate, explore or give space; brief or stay; at most one offer per conversation |
| `ask_mind` | cloud | A question for the record: her notebook first, then [Gemma](gemma.md), then Gemini, then a fixed line |
| `remember`, `recall`, `forget` | cloud | The notebook she controls |
| `agree_activity` | cloud | Her yes becomes a card on the phone and Mac, whatever body heard it (D50) |
| `suggest_activity`, `start_activity` | device | One card in the chat; an activity on this device |
| `record_dial` | device | A mood, energy or sleep answer said aloud |
| `set_walk_goal`, `log_walk_moment`, `look_at_this` | device (walk) | The spotting game; a check that Kaiku can really see right now |
| `checkin`, `turn_head`, `camera_choice`, `photo_time` | robot hub | Start, pause or continue the robot's check-in; turn the head; her answer about the camera |
| `express`, `end_session`, `start_phq9`, `suggest_nudge` | mixed | Eyes or mascot; closing with an open thread; the questionnaire; today's suggestion |

`feel` is the one we would point a judge at. It uses Live's asynchronous function calling
(`behavior: NON_BLOCKING`, answered with `scheduling: WHEN_IDLE`, or `SILENT` when the plan is late or
unavailable), so the conversation never stalls while the mind works. The plan itself is code, measured at 5 to
6 ms: regexes over the person's own words can outrank the model's label, and the one offer is the activity her
own record says she responds to.

### Code decides what counts as her yes

A model that can act must not be the one that decides it was asked to. Each tool call is checked by code:

- **On the cloud**, in order: the session belongs to this home; the crisis gate over every string argument; the
  tool exists and is allowed on this body; the arguments fit the schema. Only the tool's name is logged.
- **`remember`** needs the note to be grounded in what she said: more than half of its content words, and every
  name, day and number, must appear in her own words. Health details are refused.
- **`agree_activity`** needs her words to match a yes or an ask with no hedge; "maybe" keeps nothing, and on an
  extra-gentle day only her own ask counts.
- **`start_activity` in the apps** needs a clear yes in her last line. This exists because the real model once
  opened an activity on a sad sentence and once on a "maybe".
- **On the robot**, the model's `start_activity` only arms the head for 20 seconds; a physical press of the ear
  starts it (D58).
- **On a walk**, the phone keeps the spotting count, one find per thing she said; the model only says it.

A detail learned from real sessions (D47): all calls that arrive in one `toolCall` frame must be answered in one
`toolResponse` frame. Answered one by one, the model repeated `log_walk_moment` in 3 of 3 sessions.

### Pictures on a walk (D43)

With "Let Kaiku see through the glasses during walks" on (off by default), the iPhone sends at most one JPEG a
second (longest side 640 px) from the glasses camera to that walk's Live session as `realtimeInput.video`, and to
no Kaiku service. A frame goes only while the conversation is open, unmuted and not paused. The model is told in
words when the camera turns on and off, and `look_at_this` answers "you cannot see" unless a frame from the last
three seconds was really sent. Details: [Meta glasses](meta-glasses.md).

### The robot's audio path (D51, D56)

The hub has no sound card of its own. Live's 24 kHz voice is resampled to 16 kHz and sent to the head's speaker
as 20 ms frames over MQTT; the microphone comes back the same way, or from a phone standing in for it. See
[Atech](atech.md).

### Safety sits outside the model

Every transcript fragment, including interim ones, passes a deterministic phrase gate before anything else
([`hub/kaiku_hub/safety/gate.py`](../../hub/kaiku_hub/safety/gate.py), `SafetyGate` in the apps, and again on
the cloud for every tool argument). On a hit the microphone closes first, the Live session is closed, and a
fixed script is shown. The script is never sent to a model and never rendered by TTS
(`POST /v1/voice/say` answers 422 for it). In the apps a second, on-device speech recogniser runs beside Live for
the same gate. A test parses the safety package and fails if it imports any model or network code.

### Failing softly

- No token, no key or no budget: the microphone stays closed and Kaiku shows text. **Never a synthesizer**
  (there is no on-device speech fallback anywhere in the code).
- A dropped socket: the app pings every 20 s, reconnects quietly with the resumption handle, and on a third
  failure opens a fresh line carrying the last six lines as context.
- A typed line that gets no answer in 8 seconds: the app checks the connection, then sends the line again as a
  complete turn.
- A tool that is slow: `feel` falls silent; `ask_mind` on the robot says "Let me think about that later."

## TTS, embeddings, music

- **TTS** renders the lines Kaiku says the same way every time (the ritual's steps, invitations). The style goes
  in `speech_metadata`, because the model spoke a "Say in a warm voice:" prefix aloud. Audio is cached on the
  Volume by a hash of model, voice, language, text and style; the hub pre-warms its lines at start. Measured:
  4.1 to 4.5 s to render, 5 ms from cache.
- **Embeddings** index her notebook entries and the activities in the knowledge graph, with asymmetric
  question/document prefixes. Recall is cosine similarity, then one hop along the graph, top three. They feed
  `ask_mind`'s facts and the card's memories; the `recall` tool itself uses full-text search. Without a key
  everything falls back to full-text search. Measured: 341 ms a note (108 calls), 629 ms a question.
- **Lyria RealTime** plays in the robot's rhythm game, Tap it back: a short song at a set tempo, then her taps
  are compared with it. In free drumming it follows her instead: a tempo change of 6 bpm or more, at most every
  4 seconds, re-steers the music. We chose the realtime model because only a streaming model can change tempo
  while it plays. Off unless the hub's music is switched on.

## What has run

All with real provider calls, 14 to 15 November, on a simulated record.

| What | Result |
|---|---|
| End of her speech to Kaiku's first sound | 2.3 s median over 5 turns (1.5 to 2.6); 2.1 s through the robot head's software twin |
| Session bootstrap including the token; Live ready | 845 ms median (3 runs); 1.2 s |
| `make e2e-intelligence` | All pass: token, typed turn, spoken turn ended by voice activity, tool call, barge-in, TTS, `ask_mind` |
| A call across a token renewal | 4 min 48 s on the simulator while locked; the reply arrived on the Lock Screen |
| Walk with pictures as the view | A dull road got no words; a lone tree got "Is that your favourite tree up there?" |
| Check-in and Talk with proactive audio off | 3 of 3 answered each |
| Lyria | Opened in 0.38 to 0.71 s; one whole game, 66.6 s, with taps from the head's twin |
| Real glasses (15 Nov) | The glasses microphone and camera reached Live: 30 frames in one walk, the wearer heard twice |
| Real robot (15 Nov) | An ear press opened a Live session through the head's speaker, with a phone as the microphone; her spoken yes to the camera arrived as a tool call 8 s after the session opened |

Tests: `hub/tests/test_live_integration.py`, `test_feel.py`, `test_safety.py`; `cloud/tests/test_mind.py`,
`test_mind_router.py`, `test_walk.py`, `test_agree.py`; Swift `LiveSessionTests`, `ConversationControllerTests`,
`CallTests`, `WalkCompanionTests`. Persona and wording evals: `make eval-companion` (15 scenario files; they test
a text stand-in, not the audio model).

## Is this the best we could have done?

**Why Live is essential here.** Depression takes away the initiative to type a report. A check-in that happens
by voice, can be interrupted, and can act, is the product: without Live there is no ritual and no walk companion.
And because the voice is the only part that hears her, the `feel` call is the only honest way to let how
something was said shape what Kaiku does next.

**Choices we would defend.** One voice everywhere and silence over a robotic fallback. A card instead of a
second model call in front of every greeting. Tokens locked to the model only: locking the whole setup would
silently override the device's resumption handle and tools. Proactive audio only where silence is a valid
answer.

## How it joins the rest

- **Live → Modal.** Every cloud tool call lands on the one [Modal](modal.md) container, crisis gate first.
- **Live → Gemma.** `ask_mind` is how the voice reaches [Gemma](gemma.md)'s reasoning without waiting on it for
  every sentence.
- **Live → the glasses.** The same conversation continues in the ear, with opt-in pictures
  ([Meta glasses](meta-glasses.md)).
- **Live → the robot.** Tool calls move the head's check-in; the voice comes out of the
  [Atech](atech.md) head; the [UNO Q](arduino-uno-q.md)'s camera is on only after her spoken yes.
