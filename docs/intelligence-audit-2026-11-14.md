# Kaiku intelligence architecture and audit

> **Banner, 2026-11-15: a point-in-time report of 14 Nov, kept for history.** Since then the robot lost its knock
> switch, display, LED grids and buttons (D54, D55: taps come from the head's orientation sensor), the head runs
> its own steps and the hub follows (D44), a phone can be the robot's microphone (D56), the camera asks first
> (D61), a press opens a talk (D66), Gemma can look at a few check-in pictures (D65) and the service is deployed
> on Modal with Gemma verified on our own GPU for two jobs. Current state: [`stack/INDEX.md`](stack/INDEX.md).

Audit date: 14 November 2026. This is a point-in-time report of the working tree, not a replacement for the module instructions, contracts or configuration. Existing uncommitted changes were preserved.

Kaiku has a working synthetic software path and a coherent shared intelligence layer. Full physical end-to-end readiness remains blocked by unfinished firmware/app paths and device acceptance. A successful simulation, model-list lookup or template fallback does not establish that a physical source or paid reasoning model worked.

## System design

```mermaid
flowchart TB
  subgraph edge[Devices and local orchestration]
    hardware[Robot camera, knob and knock drum]
    bench[Pulse adapter: quality/bench gate]
    hub[Hub attention and ritual state machines]
    apple[iPhone and Mac controllers]
    glasses[Glasses motion through iPhone DAT]
    watch[Apple Health daily aggregates]
    browser[Browser tasks and check-ins]
    hardware -->|Local MQTT raw streams| hub
    bench -.-> hub
    glasses --> apple
    watch --> apple
  end
  hub -->|Validated observations and durable retry| ingest
  apple -->|Validated observations and durable retry| ingest
  browser -->|Validated observations and durable retry| ingest
  subgraph cloud[Cloud API with one SQLite writer]
    ingest[Authenticate home and validate contracts]
    db[(Observations and derived caches)]
    rules[Quality, freshness, baseline and drift]
    consensus[Per-source verdicts and deterministic consensus]
    learner[Activity reward and nudge learner]
    notebook[(Private memories, episodes and open thread)]
    graph[(Derived graph and memory vectors)]
    context[Assemble permitted context card]
    tools[Validate and execute companion tools]
    router[Exact local recall then Gemma reasoning]
    fallback[Gemini fallback then fixed response]
    clinician[Care dashboard and grounded record assistant]
    safety[Deterministic crisis gate]
    ingest --> db --> rules --> consensus --> clinician
    db --> learner --> context
    notebook --> graph --> context
    consensus -->|Tone cue only| context
    context --> tools
    tools --> notebook
    tools --> router --> fallback
    router -->|Verified citations and wording| tools
    consensus --> safety
  end
  hub -->|Session bootstrap and tools| tools
  apple -->|Session bootstrap and tools| tools
  tools -->|Small context and short-lived app token| live[Gemini Live conversation]
  live <-->|Consented audio and tool results| hub
  live <-->|Consented audio and tool results| apple
  live -->|Tool request| tools
  live -->|Transcription fragments| safety
  safety -->|Stop capture and fixed crisis guidance| edge
```

The cloud is one logical service with internal modules, not a collection of independently deployed agents. The hub and Apple controllers orchestrate device activity. Cloud code orchestrates ingestion, scoring, context, tool permissions, model routing and persistence. Sensors, firmware and browser measurement tasks do not need their own LLMs.

The monitoring groups are Check-ins and robot, Walks and outings, Apps, and Watch. Group membership comes from observation type, not the hardware sending the envelope: a phone weather check belongs to the robot/check-in group; a phone game belongs to Apps; Health summaries belong to Watch. These are signal groups, not proof of statistical independence. Correlated self-reports have an explicit caveat in the rule configuration.

Ground truth: [source map](../contracts/python/kaiku_contracts/sources.py), [criteria](../config/criteria.toml), [cloud](../cloud/AGENTS.md), [hub](../hub/AGENTS.md), [Apple](../apps/apple/AGENTS.md), [web](../apps/web/AGENTS.md).

## What each input contributes

| Input | Local processing and saved observation | What the system learns or derives | Important boundary |
|---|---|---|---|
| Knob, buttons and app weather check | Mood, energy and reported sleep ratings; channel and context | Personal usual ratings and sustained changes | A phone check-in is not an additional independent source |
| Robot camera and presence | Face position/size and distance remain on the local bus; presence times become observations | First interaction timing and participation | No stored camera frames or identity recognition |
| Pulse during breathing | Local signal quality, HR and RMSSD before/after when valid | Optional immediate activity response | Robot pulse scoring is disabled in the current profile; the real cradle check remains open |
| Knock drum | Tap intervals, duration, tempo and variability | Usual engagement/tempo and change; before/after feedback | Knock switch has no force measurement; missing force must remain missing |
| Ambient light | Camera can estimate local luminance for the bench | None in the current hub profile | Light observation/context and scoring are disabled |
| Robot conversation | Live audio; bounded local energy summaries; received text for immediate commands/safety | Numeric speech features, explicit memories, activity feedback and session metadata | PCM is discarded; poor/interrupted windows are omitted; numeric speech metrics do not currently score |
| Glasses/phone walk | Outing duration, steps and, when actual DAT motion arrives, cadence/regularity/head-up summaries | Usual outings, activity participation and response | DAT camera/daylight capture is unavailable; standalone glasses web/Android modules are placeholders |
| Browser spoken/reaction task | Explicit legacy task can retain derived features | Historical inspection | Retired from default histories and active scoring; facial movement is not emotion recognition |
| Phone/Mac games | Aggregate reaction/game features, Pebbles memory span; optional local camera method/coverage/samples | Participation; configured Firefly metric contributes to Apps | Practice is unscored; optional camera methods are not pooled as equivalent measurements or assigned new consensus votes |
| Mac usage | Broad app categories, active/late-night minutes, switches and breaks | Usual activity rhythm and communication-category time | No window titles, URLs, keys, screenshots or content |
| Apple Health | Daily sleep, sleep midpoint/regularity, resting HR, SDNN, steps and exercise summaries | Configured Watch baseline metrics and corrections by measured date | Only configured metrics score; conversational prompts exclude private Health values |
| PHQ-9 | Nine item scores, total and item-9 flag | Direct configured rules and questionnaire history | Questionnaire scoring and item-9 safety are deterministic |
| Activity/nudge response | Accepted/declined, before/after differences and next-day outcome | Per-person activity reward and Thompson-sampling preferences | Observational personalisation does not establish treatment efficacy or causation |
| Explicit notebook tool | A permitted short fact, preference or plan | Recall and continuity across surfaces | Health-detail and crisis filters apply; no automatic transcript-to-memory extraction |

Accepted observation fields can be retained without currently affecting a verdict. The enabled metric/rule blocks in [criteria.toml](../config/criteria.toml) are the authoritative distinction between collection and scoring. Optional play-camera indices, for example, are descriptive capture data rather than new state evidence.

## How monitoring works

1. The authenticated ingestion route validates the shared envelope and payload, rejects raw streams and unknown fields, and deduplicates stable event IDs.
2. Numeric observations are grouped by the configured measured date, quality and daily aggregation. Future observations cannot move the scoring day.
3. Each configured metric gets a personal median/MAD baseline. The current defaults use a 14-day baseline window ending seven days before the scored day, with at least seven usable baseline days.
4. Direction-aware robust deviations identify sustained change. Defaults require three of the last five available readings, within the configured recent horizon, beyond the configured threshold; individual metrics may override this.
5. Each source combines metric weights/direct PHQ rules and checks confidence and freshness. A source can be worse, better, as usual or insufficient. Missing/stale data cannot vote as usual.
6. Consensus combines sufficient sources, with safety precedence and hysteresis. Insufficient coverage yields watch/low_coverage rather than stable. The exact thresholds, source weights and PHQ rules remain in the criteria file.
7. Gemma can explain the already computed result. Generated explanations, record answers and citations are validated. A failed model call leaves the deterministic result intact and produces an explicit fallback.

The models do not learn new weights from these observations. Baselines, routines, memory retrieval and activity rewards adapt through stored data and code. There is no running fine-tuning pipeline.

## How the companion intelligence works

A session begins with authenticated bootstrap. The cloud opens/reuses an episode, selects the surface tools, assembles persona plus a small context card, and returns the Gemini Live setup. App sessions obtain a short-lived token; the server-side hub adapter uses its own metered credential. No long-lived Gemini credential belongs in a browser or app bundle.

The context card includes permitted memories, recent activities, routines, an open thread, a suggestion, language and a tone cue. It excludes numeric monitoring scores, consensus labels and private Health measurements. Ordinary Live turns use this prepared context without a second reasoning-model request.

When Live requests `ask_mind`, the deterministic safety/permission/schema gates run first. Exact local memory recall is tried before paid semantic retrieval. Unresolved questions use hosted Gemma, with bounded validation retries and explicit Gemini fallback tiers, then a fixed response if unavailable. Citation IDs and wording are checked before returning a result. Conflicting notebook facts cause clarification rather than a guessed identity.

`remember`, `forget`, activity tools and `end_session` change state only through validated executors. The robot ritual remains a state machine even when Gemini supplies the conversation. The completed episode can carry a follow-up topic; retries must not overwrite a newer cross-device thread. Crisis fragments are scanned immediately, while actionable robot utterances are dispatched once at the completed-turn boundary.

Gemma also proposes bounded nightly graph merges/expirations. Code validates the proposals; the original confirmed notebook is not rewritten. Unchanged clean node sets are cached. Embeddings and one-hop graph recall support retrieval; they are not model training.

## Model allocation and cost

| Work | Current responsibility | Cost control |
|---|---|---|
| Monitoring, source state, safety, consent and tool effects | Deterministic code | No generation calls |
| Immediate spoken conversation | Gemini Live | Prepared context, duration bounds, VAD, barge-in and reconnect bounds |
| Exact known memory | Local FTS/rules | Skip generation and query embedding on an exact accepted hit |
| Deeper companion reasoning | Hosted Gemma primary; explicit Gemini fallback | Bounded output, validation, shared overall deadline and fallback |
| Clinician explanation/record question | Grounded Gemma backend when selected; deterministic fallback | Evidence/question cache and regeneration cooldown |
| Notebook organisation | Gemma proposals plus deterministic validation | Changed-node fingerprint and batch execution |
| Memory semantic retrieval | Gemini embeddings | Persist unchanged document vectors; lexical fallback |
| Keyed/dynamic speech | Gemini TTS | Cache by model/voice/language/text; per-attempt budget admission |
| Reflection and weekly brief | Configured Gemini flagship, with fallback | Scheduled work and per-home limits |
| Optional postcard/music | Separate image/Lyria adapters | Outside the required monitoring path; keep disabled until separately accepted |

The preferred optimisation is fewer paid calls on the normal path, compact grounding, reuse and explicit attribution. A model on every service would add latency and failure points. Hosted Gemma is implemented; a private always-warm Modal GPU deployment is not established by the hosted tests.

Budget admission now reserves the conservative estimate atomically before provider work. Threads/processes sharing one SQLite ledger cannot oversubscribe that ledger's estimate cap. Different hub/cloud ledgers still enforce different totals, and an estimate cap is not an account-wide provider invoice limit. A central reservation endpoint or allocated per-device allowances would be required for one distributed budget.

The lead subsequently authorised additional provider budget, persisted as total/daily ceilings of $25/$23.
The integrated pass ran bounded authored-data checks through the normal reservation path, without bypassing
those limits. Consult the dated progress entry for spend estimates and proof results; they are not invoices.

### Fine-tuning Gemma

It is possible to tune Gemma's open weights with LoRA/QLoRA. The useful initial target here would be better
evidence selection, valid structured tool/graph proposals, concise grounded support and consistent refusals.
Personal baselines and memories should remain retrieved data rather than being embedded in model weights.
Google documents [parameter-efficient tuning and held-out evaluation](https://ai.google.dev/gemma/docs/tune)
and a [QLoRA workflow](https://ai.google.dev/gemma/docs/core/huggingface_text_finetune_qlora).

No Kaiku adapter has been trained. Before spending GPU time: create reviewed authored task/evidence pairs,
split by person/scenario before training, include missing/conflicting data and refusal cases, compare against
the current hosted model on untouched tests, and retain numeric/safety validators. A candidate must improve
grounding and latency/cost without increasing unsupported claims. The optional Modal GPU adapter is a possible
deployment target only after compatibility and cold/warm inference are measured. Transcript retention alone
is not training consent; the export allowlist is a separate gate. Tuning is not required for each person's
routine or baseline to adapt.

### What is visible during early collection

The reproducible single-person fixture contains 16 days of supported observations and private continuity,
without invented conversation words. Observation routines use the actual collection horizon and retain an
emerging label until enough usual history exists. The care view shows permitted activity/routine edges,
first/latest-week comparisons and a real Gemma evidence selection. Cross-input mood, energy and outing
changes are explicitly associated observations, not causal evidence. Sharing that graph does not expose
private notebook people/places, episodes or transcripts.

## Where data and transcripts are saved

| Store | Contents and location | Retention/access |
|---|---|---|
| Observation database | Local `logs/kaiku.sqlite`; Modal volume `kaiku-data`, mounted as `/data/kaiku.sqlite` | `events` stores accepted observations; `homes`/`explanations` cache derived results. No general observation TTL was found |
| Private notebook | Same database: `memories`, FTS search index, `threads` | Person-authorised access; plans expire after seven days, open threads after three days |
| Session metadata | Same database: `episodes` | Surface, intent, times, tool names, outcome; metadata is separate from conversation words |
| Opted-in conversation words | Same database: `transcripts`, keyed by episode ID; `turns` is JSON role/text/optional completion metadata | Person routes can list/delete; no automatic transcript TTL was found; care routes do not read it |
| Local observations and controller state | Hub `logs/uplink_queue.sqlite` and `logs/hub_state.json`; Apple Application Support/Kaiku/`outbox.json`; browser localStorage keys scoped to API origin/home | Stable observation IDs support retry. These contain derived records/state, not captured audio/video. Apple queues are bounded, so prolonged offline use does not imply unlimited retention |
| Pending robot completion | `robot_episodes.sqlite` beside the configured hub uplink queue, normally `logs/robot_episodes.sqlite` | Can contain opted-in transcript text until successful delivery; raw audio is absent |
| Pending Apple completion | Application Support/Kaiku/`episodes-outbox.json` | Can contain opted-in transcript text; scoped to original server/home; iOS file protection; removed after successful delivery |
| Graph/search vectors | Main database: `kg_nodes`, `kg_edges`, `embeddings` and small caches in `kv` | Derived permitted notebook/activity information; deletion prunes derived memory references |
| Model usage | Main database `model_calls`; separate `logs/spend.sqlite` or `/data/spend.sqlite` | Task/model/latency/status and estimated costs; no transcript/prompt content. TTS spend is not fully represented in intelligence-health call telemetry |
| Generated output files | `logs/voice_cache` or `/data/voice_cache`; postcards under the configured postcard directory | Generated speech/images, not captured raw microphone/camera recordings. Dynamic TTS can encode caller-supplied personal text; apps also cache generated speech locally |

Transcript retention is off by default and separate from using Gemini to process speech. The device must omit transcript payloads unless consented; the cloud currently trusts that authenticated device choice rather than checking a server-side consent registry. Crisis suppression and deletion tombstones prevent delayed retries from resurrecting deleted conversation text. Deletion is logical application deletion; this does not demonstrate forensic erasure of SQLite pages, operating-system backups or provider state. Application-level field encryption and an independent backup/restore acceptance process were not established.

Native input/output transcription markers are independent from audio completion. Received words remain
unchanged: explicit final markers set `complete=true`, known interruption/truncation sets false, absent
provider/legacy status stays null. A real configured-provider probe returned no explicit final markers despite
completed audio and exact received-text persistence. The implementation preserves that uncertainty rather
than promising final speech-recognition accuracy. Saved conversations are accessible in the person's app.

The dynamic voice endpoint is an additional retention boundary: it accepts short authenticated text and caches the generated WAV by text hash under `voice_cache/say`. Its normal use is fixed app copy, but the API does not restrict callers to those strings. A personalised line can therefore survive as generated audio even when conversation transcript retention is off. No automatic TTL or linkage to transcript deletion exists. A real-person deployment needs a deliberate policy for per-home dynamic caching, expiry and erasure.

Training export is a separate CLI operation requiring a reviewed episode allowlist that attests separate training consent. Regex replacement is only an aid and does not prove anonymisation. No automated training job consumes these transcripts.

Google processing is another storage boundary. Stateless cloud Interactions requests now use `store=False`. Live resumption remains enabled for reconnect support: Google's documentation says a generated session handle can retain conversation state, including audio/text, for up to 24 hours. Paid API abuse-monitoring retention is a separate provider policy. Disabling Kaiku transcript retention or deleting its SQLite row does not delete Google's session state. See [Google data-retention documentation](https://ai.google.dev/gemini-api/docs/zdr) and [ephemeral-token documentation](https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens).

## Scheduling and failure behaviour

The Modal API is configured as one warm container with a single SQLite writer and a persistent volume. Successful API writes await volume commit. Per-event ingestion recomputes the affected home; a scheduled job also recomputes every 15 minutes. Nightly work runs at 03:00 Helsinki time, and weekly briefs Monday at 06:00 Helsinki time. Scheduled workers invoke the API rather than opening another SQLite writer. These are deployment definitions; this audit did not deploy or invoke remote schedules.

Local device controllers retain observations/episodes with stable IDs, retry and acknowledge commands only after application. Missing model credentials, budget, network or malformed generation must produce visible unavailability/fallback while deterministic monitoring continues. This does not make missing hardware data valid. Browser microphone/camera capture additionally requires HTTPS or localhost.

## Repairs and verification

This audit repaired the following concrete defects in isolated module workstreams:

- Robot transcript fragments could fill several dial/PHQ answers from one spoken answer. Safety still scans fragments immediately, but completed utterances are delivered once; named Live dial tools own dial writes. Advertised robot `express` now has a validated device implementation.
- Robot `end_session` dropped requested outcomes/follow-up topics. Durable completion now carries them, and cloud phase markers prevent retries from replacing a newer thread.
- Concurrent paid requests could oversubscribe one spend ledger. Atomic pre-call reservation now covers threads and processes, with per-attempt TTS admission and reservation before Live token minting.
- The Modal API image omitted NumPy. Its requirements now cover declared runtime dependencies, checked without contacting Modal.
- Reasoning retries/fallbacks could exceed the device wait. Provider tiers now share the available deadline and skip further calls when it is spent. This is bounded synchronous timeout handling, not preemptive cancellation of provider work.
- Exact memory questions could incur a query embedding before taking a deterministic answer. Local accepted recall now precedes paid retrieval.
- Stateless Gemini Interactions requests used default provider storage. Text/image/TTS requests now explicitly disable it.
- Apple global pause could leave Live capture active. Paused startup is refused, active capture stops, and unpausing requires an explicit new start.
- Walk recovery and delayed Health queries could cross a pairing change. Original home/server and pairing revisions now bind delivery; old private caches, visible conversation words and walk state are cleared at the household boundary.
- Browser manual retries created new UUIDs while the first copy remained in the outbox. Laptop tasks, PHQ-9 and weather checks now retain one captured batch. Person PHQ due information uses the person endpoint rather than a care-only history route.

Verification of the combined working tree:

- `make setup` and `make doctor`: no failures; default broker has no active-node heartbeat evidence. Sandbox-only socket/cache failures disappeared when rerun with the required local access.
- Final `make check`: Ruff clean, 636 Python tests passed, web typecheck passed, including contract freshness/module checks and real isolated MQTT tests.
- Web: 35 tests passed and Next.js production static export succeeded.
- Apple shared suite: 112 tests, four optional skips, zero failures. Final unsigned iPhone device build also succeeded (`/private/tmp/kaiku-audit-ios-build.log`); nothing was installed. Physical microphone, HealthKit/watch and Meta acceptance are not implied.
- Final `make smoke`: isolated temporary cloud/database, synthetic cohort, all four source verdicts, person API, shared context, exact recall and constellation passed.
- Full robot recording: 2,674 real MQTT messages through isolated broker/cloud, approach/greeting/explicit consent/dial/breathe/drum/suggestion/close and simulated glasses/laptop/Mac/phone posts. Cloud ended at the intended synthetic needs_call/disagree state and exact recall succeeded; no hub error logs. Evidence: `/private/tmp/kaiku-audit-20261114-robot`.
- No fresh paid inference call, physical capture, production database reset, service restart or remote deployment was performed.

## Remaining acceptance gates

- Atech individual bench projects were previously compiled, but its root robot project still reports a custom-module validation failure. Edwin's later real-board UNO Q sketch compilation and camera/knock/buzzer benches passed; reliable pulse in its cradle remains unverified. Friendlink has no implemented firmware and is excluded from the default path.
- The standalone glasses web/Android folders contain instructions only. The working intended glasses route is the iPhone DAT bridge; real registration, actual motion samples and Bluetooth microphone/speaker routing still need device acceptance. Camera/daylight is unavailable.
- Physical robot microphone/speaker, camera/pulse quality, motor/hall behaviour and voice quality need bench tests. The fitted head microphone is not the hub laptop's current audio edge.
- Robot `obs.speech_features` now uses bounded consented microphone energy summaries plus received user text, with poor-window rejection. Physical microphone/echo acceptance remains open and those metrics do not currently score. Optional Lyria has separate blocking/failure risks and has not passed device acceptance.
- Hosted Gemma evidence selection and synthetic native Live transport/storage have real provider proof. One native run did not select the requested reasoning tool; the final capability probe supplied no transcription-final markers. These are unresolved provider-behaviour limits, not passing end-to-end voice guarantees.
- Distributed budget authority, a retention/whole-home deletion policy, provider-retention choice and backup recovery require explicit completion before a real-person deployment claim.

Verification results and repaired defects are recorded in the accompanying dated [progress entry](progress.md). Read the module instructions for current behaviour after this audit date.
