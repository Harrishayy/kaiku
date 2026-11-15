# contracts — AGENTS.md

> Read the root `AGENTS.md` first. This module is the ground truth for every message in Kaiku. Owner: all (agree
> changes in the team) · kind library. Any change here is a contract change: follow root rule 4 and update every
> producer and consumer in the same commit.

## Purpose
The only package every other module may import (`kaiku_contracts`): message models, topics, validation, the
consensus source map, the criteria schema, and a tiny shared kit (MQTT `Bus`, config loader, JSON logging).
Pydantic v2 models are authoritative; JSON Schema and TypeScript are generated from them for non-Python modules.

## Boundaries
Imports only pydantic (+ `aiomqtt`, lazily, inside `bus.py`). Never imports hub, cloud, sim, tools or apps.
Business logic (perception, analytics, the consensus itself) does not belong here.

## Consumes (topics/endpoints)
Nothing (library).

## Emits (topics/endpoints)
Defines all of them. The topic is derived from the fully-qualified `type`:

| type | topic | QoS | retained |
|---|---|---|---|
| `obs.<name>` | `kaiku/v1/<home>/obs/<name>` | 1 | no |
| `raw.<source>.<stream>` | `kaiku/v1/<home>/raw/<source>/<stream>` | 0 | no |
| `cmd.<target>` | `kaiku/v1/<home>/cmd/<target>` | 1 | no |
| `health` | `kaiku/v1/<home>/health/<envelope.source>` | 1 | yes |
| `log` | `kaiku/v1/<home>/log/<envelope.source>` | 0 | no |

Only `obs.*` may be uplinked (`UPLINKABLE`). Glasses, laptop/Mac and phone apps send the same envelopes over
`POST /v1/events`.

`GET /v1/discovery` returns `APIDiscoveryResponse`: service identity `kaiku-api`, schema version, explicit
demo/authenticated/unconfigured mode, whether credentials are required, and supported API capabilities.
It exposes no home IDs or credentials. Native discovery uses `_kaiku-api._tcp`, separate from robot discovery;
discovering a service never grants access to an existing person's record.

Plan 02 additions (all computed on the device; only derived numbers): envelope source `phone` ·
`obs.self_report.channel` (`robot|phone|mac|web|glasses_voice`, default `robot`; always the robot source's daily
dial) · `obs.outing` `method: dat_imu` + `cadence_spm`, `gait_regularity`, `head_up_ratio` ·
`obs.screen_activity` (Mac usage rhythm: `period_min`, `active_min`, `late_night_min`, `category_min{work,
communication, social, video, news, games, other}`, `switches_per_hour`, `longest_stretch_min`, `breaks`, `paused`;
no titles/URLs/keystrokes — `extra=forbid` rejects them) · `obs.play_session` (`game: firefly|breathe|tell`,
`device: phone|mac|web`, reaction/speech/HR features) · `obs.wearable_daily` (`date` = the morning; sleep, sleep
midpoint in min from local midnight, regularity, resting HR, HRV SDNN, steps, exercise, `device`; since D53 also
the day's distance, time in daylight, walking heart rate, sleep stages and time awake: see "More of the day from
Apple Health" below).
Clinician record assistant: `ClinicianAskRequest`, `ClinicianAskResponse`, `RecordCitation` define
`POST /v1/patients/{id}/ask`: scoped care-team access, grounded evidence citations, no private notebook.
`ContextCard.source_context` carries at most four prepared source-labelled activity facts into Live;
`CompanionSessionResponse` includes session duration and context-refresh bounds.
Command delivery: `GET /v1/commands` peeks pending commands; `POST /v1/commands/{command_id}/ack?home_id=`
returns `CommandAckResult {ok, id}` after the device successfully applies the command.
API: `MeResponse.mascot {mood: idle|happy|cozy|crisis, line_key}`, `highlights [{date, kind: good|hard, text,
source}]`, `garden {plants, resting}`; `VoiceLinesResponse` (`GET /v1/voice`).
Companion mind (plan 03 §3–§6, workstream I1): `companion_tools.py` = the tool registry (12 tools: JSON-schema
`parameters`, `surfaces`, `executor` cloud|device; plus `Surface`, `Intent`, `Skill`, `MemoryCategory`,
`SKILL_OF_INTENT`) → `schemas/companion_tools.json` + `COMPANION_TOOLS` in `ts/index.ts` (Swift/TS read these).
`wording.py` = the deterministic wording linter (stdlib only, port verbatim to Swift). `safety.py` = the crisis
phrase matcher (same as the hub gate, reads `config/safety_phrases.toml`). API: `CompanionSessionRequest/Response`,
`ContextCard` (no state/score/wearable fields by construction; `tone` is the only consensus cue), `LiveToken`
(+ `CompanionSessionResponse.live_setup`: the Live setup locked into it), `VoiceSayRequest` (`POST /v1/voice/say`),
`CompanionToolCall/Result`, `Memory`, `MemoriesResponse`, `MemorySettings`, `DeletedResponse`, `EpisodeIn/Result`,
`ThreadIn`. `obs.play_session.game` adds `pebbles` (`span_max`, `accuracy`).
Robot electronics (plan 07, D32; additive): `raw.head.button` (`RawButton`, `id: "head"`) · `cmd.head.gesture`
(`look_left|look_right|shake`; the head only pans) · `cmd.sensors.chime` (`wake|ok|start_drum|end_drum|alert`) · `raw.head.tap.force` and
`obs.drum_session.force_mean` optional (`None` for a knock switch, never invented).
Gemini-first mind (plan 06, workstream I4): tool `ask_mind {question ≤ 300, kind: fact|care|memory|plan|emotional}`
(executor cloud, all surfaces; 13 tools) → result = `MindAnswer {answer, kind, route: memory|flash|argon|fallback,
confidence, cites[], ask_person, model}`. API: `IntelligenceHealth` + `ModelUsageRow` (`GET /v1/health/intelligence`),
`ConstellationResponse/Node/Edge` (`GET /v1/me/constellation`, no health fields by construction),
`PostcardRequest/Response` (`WeatherWord`), `ClinicianBrief` + `BriefSection` (`GET /v1/patients/{id}/brief`).
Dashboard (D34, additive): `CareSharing {share_with_care_team=false}`, `WeekSummary {audience: person|care_team,
week_start/end, routines: Routine[], going_well/worth_a_look: WeekItem[], shared, rule_version?, by: rule}`, `Routine`
(`cadence daily|most_days|weekly`, `weekday`, `day_part`, `usual_time`, `usual_per_week`, `this_week`,
`status kept|partly|slipped`, `text`, `basis obs|episodes`), `WeekItem {kind, text, source?, metric?}`,
`WeekSummary.sources: SourceWeek[]` (the one record: per source `per_day[7]`, `days`, `counts: SourceCount[]
{label, value}`, `last_at`) and `WeekSummary.next_steps: NextStep[]` (care team: `{text, why, when: today|this_week|
next_contact, action: ActionName?}`), `KnowledgeGraph {audience, shared, nodes: GraphNode[], edges: GraphEdge[], withheld}` (`GraphNode.type` adds
`routine`; `GraphEdge.rel` adds `keeps`, `of`; both carry `evidence` counts; negative node ids = derived for the view).
Practitioner insight (additive): `PatientInsight {review: PatientReview{headline, findings: ReviewFinding[], by,
model, cached, fallback_reason}, evidence: RecordCitation[], trace: AgentStep[], comparison: PeriodComparison
{groups: GroupComparison[{metrics: MetricComparison[]}], improved, changed}, routine: LearnedRoutine{routines,
helps: HelpEffect[], kept/partly/slipped}, graph: InsightGraph{nodes: InsightNode[], edges: InsightEdge[]},
coverage: DataCoverage{groups: GroupCoverage[{types: ObsTypeCoverage[]}], other}}` for
`GET /v1/patients/{id}/insight`. `Trend = better|worse|similar|unknown` is always relative to the person's own data.

Measured games (additive, `SCHEMA_VERSION` 1): `obs.play_session.game` adds `lantern` (simple reaction time), `seeds`
(symbol–digit), `watering` (effort choice); new optional fields `trials_n`, `valid_n`, `input`
(`touch|pointer|keyboard|mixed`), `session_index`, `warmup`, `valid`, `flags[]` (`few_trials|false_starts|low_accuracy|
too_fast|interrupted`), `false_starts`, `response_speed`, `reaction_ms_cv`, `throughput_per_min`, `hard_choice_ratio`,
`tap_rate_hz`, and the compact trial record `rt_ms[≤120]` + `trial_codes`. One example per game:
`registry.PLAY_EXAMPLES`. A doubtful session is sent with envelope `quality` 0.2. Why: `docs/validation.md` → Games.
Story of the record (additive): `PatientInsight.course: Course {phase, summary, events: CourseEvent[]}`,
`.days: DayAccount[] {date, text, parts}`, `.reflections: ReflectionOverview | null`, `PatientReview.overview` +
`.overview_cites`, `InsightNode.layer` / `InsightEdge.layer` (`learned|structure`) + `InsightGraph.layers`, new
edge rels `moved_first|followed|moved_together|kept_through|slipped_during|after|talked_about`, node kinds
`care_action|shared_topic`, `AgentStep.step` adds `course|overview`. `ContextCard.last_reflection: LastReflection
{when, valence, themes, declined}`, `.today_facts[]`, `.recent_reflection`. `ActionRequest.ts`, `Consensus.simulated`,
`RecordCitation.simulated`, `TimelinePoint.early`; tool `remember` takes optional `said`.
The graph as a map (additive): `InsightNode.domain` (the declared neighbourhood, "" for the person and signal
groups) and `.days: InsightNodeDay[] {date, tone: Trend, value, text}`; `InsightEdge.on: date[]` (the days a link
speaks of) and `.tag` (a few words for the picture), new edge rels `produces|about`; `InsightGraph.domains:
InsightDomain[] {id, label, short, place: n|ne|e|se|s|sw|w|nw}` and `.days: InsightGraphDay[] {date, recorded,
away, changes: InsightChange[] {node, kind: care|moved_away|came_back|better|missed|first|kept, text, tag}}`.
All default to empty, so an older producer still validates.
Generated references: `schemas/index.json` (type → schema, topic, model), `schemas/examples.json` (one example per
type), `schemas/sources.json` (obs type → consensus source).

## Map
```
python/kaiku_contracts/
  envelope.py   Envelope, Source, make(), uuid7()           sources: head|sensors|hub|friendlink|glasses|laptop|phone|cloud|sim
  payloads.py   every payload model (obs/raw/cmd/health/log)
  registry.py   type -> model (OBS/RAW/CMD), UPLINKABLE, validate(), EXAMPLES (one per type, required)
  sources.py    obs type -> consensus source (robot|glasses|laptop|wearable) or learner|adherence|override;
                SOURCE_LABELS (laptop is shown as "Apps", wearable as "Watch")
  criteria.py   schema + loader for config/criteria.toml; rule_version = name + hash; nested fields
                (`category_min.communication`); per-metric `person_hard` sentence for /me
  api.py        cloud HTTP models: Consensus, SourceVerdict, Explanation, PatientSummary, Timeline, PHQ-9, Me (+ Mascot,
                Highlight, Garden), VoiceLinesResponse, Eval, Criteria*
  companion_tools.py  tool registry (schema + surfaces + executor + optional `behavior: NON_BLOCKING`), for_surface(),
                validate_args() (also arrays of enum strings with maxItems), export(); the tone enums
                (Valence, Energy, Tone, FeelKind), Purpose, CheckinItem
  wording.py    wording linter (clinical terms, state talk/numbers, medical advice, promises, watch data, caps)
  safety.py     crisis phrase matcher (config/safety_phrases.toml) shared by cloud + evals
  topics.py     topic(), topic_for(), parse_topic(), QoS/retain
  bus.py        async MQTT client: validates both ways, reconnects, heartbeat + last-will
  config.py     config/kaiku.toml + KAIKU_<SECTION>_<KEY> env overrides, .env loader
  jlog.py       JSON-lines logging
  export.py     writes schemas/ + ts/index.ts (make contracts); --check for tests
schemas/  ts/   GENERATED — never edit by hand
tests/          round trips, rejections, topics, source map, criteria validation, bus on a real broker, stale schemas,
                test_plan02.py (new types, bounds, no content fields)
```

## Extension points
- **New obs type:** model in `payloads.py` → register in `registry.py` (`OBS` + an `EXAMPLES` entry) → map it in
  `sources.py` → `make contracts` → a producer and a consumer in `modules.toml` (the checker insists) → sims.
- **New consensus source:** add to `ConsensusSource`/`CONSENSUS_SOURCES`, map its obs types, add `[sources.<name>]`
  + metrics in `config/criteria.toml`. Cloud verdict/consensus code is source-agnostic.
- **New criteria knob:** a field in `criteria.py` with a default + description (existing files stay valid), used in
  cloud analytics, explained in the `config/criteria.toml` header.
- **New companion tool:** add it to `companion_tools.TOOLS` (schema, surfaces, executor), list it in the surface's
  `tools` in `config/surfaces.toml`, handle it in `cloud/kaiku_cloud/mind/session.py` if `executor = "cloud"`,
  `make contracts`, add an eval scenario.
- **New API field:** additive optional fields need no version bump; removing/renaming = breaking → bump `SCHEMA_VERSION`.

## Invariants
- `extra="forbid"` on every model: an unknown field is a contract violation, on purpose.
- Every registered type has an example; every obs type has a consensus role (tests enforce both).
- `type` is fully qualified and decides the topic — never build topics by hand (`topic_for(env)`).
- Sims keep the real `source` (e.g. `head`) and set `sim: true`.
- `obs.phq9` validates its own consistency (total = sum(items), item9_positive = items[8] > 0).
- Generated files are committed and must be current (`make test` fails otherwise).

## Run standalone
```python
from kaiku_contracts import make, validate, topic_for, to_json
env = make("obs.self_report", {"item": "mood", "value": 4}, source="hub")   # validates; raises ContractError
topic_for(env)  # 'kaiku/v1/demo-aino/obs/self_report'

from kaiku_contracts.bus import Bus
async with Bus("head", sim=True) as bus:
    await bus.publish("raw.head.tap", {"t_ms": 10, "force": 1.7})
```
Non-Python (firmware, glasses): read `schemas/` or `ts/` and publish JSON matching the envelope; generate the UUIDv7
on the device (or let the hub adapter fill it).

## Run with sim
`make sim` uses these models; `make tail` validates every message live and shows violations in red.

## Config & env
`MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`, `KAIKU_HOME_ID` (Bus defaults) · `KAIKU_CONFIG` (another
`kaiku.toml`) · `KAIKU_CRITERIA` (another criteria file) · `KAIKU_<SECTION>_<KEY>` overrides any `kaiku.toml` key.

## Health signal
`Bus` publishes `health/<node>` every 5 s (retained) and a `down` last-will on disconnect.

## Tests
`make test-contracts`

## Known issues
`make contracts` needs Node for the TS step; commit `schemas/` + `ts/` together with the model change.

Paid-call admission: `budget.charge()` checks and reserves the conservative estimate in one SQLite
`BEGIN IMMEDIATE` transaction before provider work. `metered()` uses that reservation and retains it after
failures because dispatched requests may bill. `guard()` is advisory only. Concurrent processes sharing
one ledger cannot oversubscribe its configured estimate cap; separate device/cloud ledgers enforce separate
caps, and estimates are not a provider invoice or an account-wide billing limit.

Task sensing: optional `PlaySession.expressivity_index`, `face_movement`, `camera_face_coverage`,
`camera_samples`, `camera_method` describe local aggregate geometry only. Features require positive coverage
and samples plus a named method; no-face sessions may retain coverage zero with no derived facial features.
MediaPipe blendshapes and Vision landmarks must not be pooled as equivalent measurements. These new camera
features are descriptive and have no consensus weight until separately calibrated.
`TaskObservationsResponse` serves the last 100 typed task envelopes to authorised care teams.

Conversation completion metadata: `TranscriptTurn.complete` is optional `bool | null` for upload and person-only
readback. `true` means transcription explicitly finished; `false` means interrupted/not final; absent/null means
unknown for legacy records. Audio `turnComplete` does not establish transcription completion. Producers retain
the received words unchanged; completion metadata never authorises transcript retention or raw-media upload.

## Notice and act, tone and the check-in shape (2026-11-14, additive)
- Tool `feel` (cloud, every surface, `behavior: NON_BLOCKING`): `kind`, `heard {valence, energy?, tone[≤2]?, via?}`,
  `about?`, `said?`. Its result is `api.FeelPlan {stance, depth: brief|stay, reflect_hint, recall?, may_offer?,
  offer_note?, offer_activity?, follow_up_saved, scheduling}`.
- `CompanionSessionRequest.purpose?` (`talk | check_in | walk | ritual`); `CompanionSessionResponse.chat_shape?`
  (`ChatShape {purpose, depth, open_items[]}`); `CompanionTool.behavior?`; `ContextCard.purpose?`, `.chat_depth?`,
  `.open_items[]` (`mood | energy | sleep`).
- `HeardTone {valence?, energy?, tone[≤2], provenance: model_heard|model_read, moments}`; `LastReflection` and
  `ReflectionDay` gain `tone[]`, `energy?`, `heard?`; `ReflectionOverview.tone_summary?`.
- Tone is an observation by a model, never a state and never an input to the consensus.

## Walk styles, activity cards, call length and the invitation (2026-11-14, additive, D45)
- `companion_tools`: `Activity` = `breathe | tell | walk | lantern | seeds | watering | pebbles | firefly | drum |
  light_hunt` (`ACTIVITIES`, the screens that exist; each surface lists its own in `config/surfaces.toml`);
  `WalkStyle` = `quiet | playful | chatty` (`WALK_STYLES`). Both are in `export()` (`activities`, `walk_styles`).
- Device tools: `suggest_activity {kind: Activity, line? ≤ 80}` (iphone, mac) → `api.ActivityCardResult {ok, shown}`;
  `set_walk_goal {thing ≤ 30, target 1..5}` → `api.WalkGoalResult {thing, target, found, left}`; `log_walk_moment
  {kind}` → `api.WalkMomentResult {ok, thing?, found?, target?, left?, note?}` (`note`: for the model when no goal
  was set, so nothing was counted; glasses; iphone only on a walk:
  `walk_only_on`, `for_surface(surface, walk=True|False|None)`).
- `CompanionSessionRequest.walk_style?`; `CompanionSessionResponse.walk?` (`WalkGuide {style, look_every_s?,
  look_prompt?, quiet_after_s?, quiet_prompt?}`) and `.idle_end_s?`; `ContextCard.walk_style?`, `.outdoor_likes[≤4]`.
- `Invitation {id, kind: talk_about|activity, text ≤ 200, voice_key, topic?, activity?}`, `InvitationResponse
  {home_id, invitation?}`, `InvitationAnswer {id, answer: yes|not_now}`.

## Live reservations settle to real talk time (2026-11-14, additive, D46)
- `api.SessionClose {home_id, session_id, elapsed_s 0..86400}` → `api.SessionCloseResult {ok, session_id, settled,
  billed_minutes}` (`POST /v1/companion/close`).
- `budget`: `charge` returns the row's `ts`; `reservation_units(minutes, session)`, `live_reservations(path?)`
  (read-only), `bill` and `plan_session` (pure), `settle_session(session, end_ts|elapsed_s, floor_ts, via)`,
  `settle(res_ts, used_s, via)`, `session_minutes(session)`. The `spend` table is unchanged (no new column: other
  processes keep writing seven values); a settlement is one more row, task `live_settlement`, usd below zero for a
  release and above for a correction. `charge` still refuses a negative amount.

## The person's history and the developers' day (2026-11-14, additive, D48)
- `GET /v1/me/history`: `PersonHistory {home_id, days, first_day, last_day, timezone, groups: HistoryGroup[], sim,
  generated_at}`; `HistoryGroup {key: robot|games|walks|checkins|sleep_body|mac, title, measures}`;
  `HistoryMeasure {key, title, unit, format: number|clock|percent|duration (`HistoryFormat`, D53), decimals, per_day: average|total|highest|lowest|latest|
  first|count, devices: (robot|phone|mac|glasses|watch|web)[], days: HistoryDay[], usual: HistoryUsual?, sessions:
  HistorySession[≤ 30], sim}`; `HistoryDay {date, value, sessions, sim}`; `HistoryUsual {low, high}`;
  `HistorySession {id, ts, device, sim, warmup?, label?, values: HistoryValue[≤ 16]}`; `HistoryValue {key, title,
  value, unit, format}`. `days` may be empty (only practice rounds so far). No model here has a field for a state,
  a verdict, a score against the usual, a flag, a weight or a direction: keep it that way (tested on the schema).
- `GET /v1/debug/day` (`generate` defaults to false: a plain GET never calls a model): `DebugDay {home_id, date,
  timezone, day_start, day_end, is_today, first_day?, sim, events:
  DebugEvent[], events_total, metrics: DebugMetric[], verdicts: DebugVerdict[], consensus: DebugConsensus,
  conversations: DebugConversation[], model_calls: DebugModelCall[], facts: DebugFact[], read: DebugRead,
  computed_at}`. `DebugEvent.day` is the local day the envelope counts toward. `DebugMetric.partial` marks today's
  running total (no z). `DebugVerdict.insufficient_reason?: stale|low_confidence|no_usable_metric`.
  `DebugConversation` and `DebugFeel` carry enums and tool names only; `tools_in_order?: bool` says whether
  `tools` is the call order. `DebugFact {id, kind: metric|source|consensus|missing|tomorrow|event, label,
  detail, numbers, flags{held|acknowledged|safety|enough_data|scored|beyond|within: bool}}`; `DebugClaim {text ≤
  500, cites: 1..8 fact ids, by_code}` (`by_code`: a line code wrote inside a Gemma read); `DebugRead {by:
  gemma|deterministic, model, cached, fallback_reason, failed, attempts, latency_ms?, est_usd?, reading:
  as_usual|slight_shift|clear_shift|not_enough_data, summary, moved[], missing[], tomorrow[], rule_check?,
  rejected{category: count}, digest, generated_at}` (`failed`: a kept ask that gave nothing valid; not asked
  again until the day's data changes).
- `budget.rows(since, until, path?)`: ledger rows in a time window, read-only (never creates or writes the file).
- `[live].proactive_audio_purposes` replaces `[live].proactive_audio`: `CompanionSessionResponse.live_setup` has
  the `proactivity` key only for a walk (D49); for every other purpose the key is absent, which means off.

## An activity agreed in one place, and the home's stream (2026-11-14, additive, D50)
- `companion_tools`: tool `agree_activity {kind: Activity, said? ≤ 300, line? ≤ 80, when?: now|later}` (executor
  cloud, every surface, blocking); `AgreeWhen` / `AGREE_WHEN`, exported as `agree_when`. List it in a surface's
  `tools` in `config/surfaces.toml` (all five do).
- Its result: `api.AgreedResult {agreed: true, id, kind, name, when, on: Surface[], where, already, listening:
  Surface[]}`. A refusal is the ordinary `CompanionToolResult {ok: false, error, result: {agreed: false, reason}}`.
- `InvitationResponse.agreed: AgreedActivity[]` (default empty): `AgreedActivity {id, kind, name, text ≤ 200,
  voice_key, line?, surface, at, day, when, state: AgreedState, state_at?, on: Surface[], opens_here}`;
  `AgreedState` = `open | started | done | put_aside`. `AgreedAnswer {id, answer: opened|put_aside}`
  (`POST /v1/me/agreed/answer`, answered with an `InvitationResponse`).
- `GET /v1/me/stream` frames (Server-Sent Events; the models describe each frame's `data`): `StreamHello {home_id,
  heartbeat_s, last_id?, resync, replayed}`, `StreamAgreed {id, kind, state: AgreedState | removed, surface, when,
  on, day}`, `StreamDay {day, types[], sources[]}`, `StreamInvitation {id, state: answered}`; `ping` carries `{}`.
  No frame model has a field for words, a value or a state of the person: keep it that way.
- `ContextCard.agreed: string[] ≤ 3`; `FeelPlan.offer_elsewhere?: Activity`.

## Face signs: counted on the device, shown and citable, not scored (2026-11-14, additive, D52)
- **`obs.face_signs`** (`payloads.FaceSigns`, uplinkable, signal group `laptop` = "Apps", beside `obs.play_session`):
  what the phone or Mac camera counted during ONE task. `task` (`FaceTask`: every `PlayGame` value + `check_in`),
  `device` (as `PlaySession.device`), `method` (`arkit_blendshapes | vision_landmarks`), `duration_s`, `samples`
  (≥ 1, frames looked at: about 30 a second with `arkit_blendshapes`, 15 with `vision_landmarks`), `coverage` (0–1, share of them with one usable face); optional signs, each null when the
  method cannot measure it (`FACE_SIGNS`): `smile_share`, `smiles`, `brow_raise_share`, `brow_furrow_share`,
  `mouth_open_share`, `blinks_per_min`, `gaze_on_share`, `head_movement`, `expression_range`; optional `ref` (the
  envelope id of the task record it belongs to). Envelope `quality` = `coverage`.
- **What it cannot carry** (`extra=forbid`, tested): an emotion or mood label, a frame, per-frame coefficients or
  landmarks, an embedding, an identity. A session with `coverage` 0 must carry no sign at all (validator): no
  face in view is missing evidence, never a zero. Values are comparable only within one `method`: the landmark
  method sends no smile, brow or gaze sign, and blinks, head movement and expression range come from both
  methods on different scales. The apps send nothing when coverage rounds to 0 and leave out blinks under 20 s
  of face time, head movement under 2 s and expression range under 10 face frames; a check-in has no `ref`.
- `PlaySession` keeps its older camera fields (`expressivity_index`, `face_movement`, `camera_*`) for producers
  that still send them; nothing reads them into a metric. Examples: `registry.EXAMPLES["obs.face_signs"]` and
  `registry.FACE_EXAMPLES` (`landmarks`, `check_in`, `no_face`).
- **Criteria: a third state for a metric** (`criteria.MetricSpec`). `role = "scored" | "shown"` (default scored)
  and `at_least = { payload field = minimum }` (a reading counts only when the observation's own fields reach the
  minimums). `MetricSpec.votes` is the one question "can this move a verdict?" (`enabled and role == "scored" and
  weight > 0`). `Criteria.metrics_for(source)` (what a verdict reads) leaves shown metrics out;
  `Criteria.shown_for(source)` lists them; `Criteria.shown_types` are observation types only shown metrics read:
  they add no coverage, freshness or first day to their group. **The fingerprint (and so `rule_version`) covers
  what can decide a state**: shown metrics are not in it, and `role` / `at_least` are left out while at their
  defaults, so adding, retuning or removing a shown metric changes no hash; deleting a `role = "shown"` line (the
  metric then votes with its `weight`) does. Metrics of one obs type must share one `day_field`.
- **API (all additive, defaults keep old clients valid):** `MetricSeries.scored` and `DebugMetric.scored`
  (false = shown beside the record, no vote); `HistoryGroupKey` adds `camera`;
  `TaskObservationsResponse.face_signs`; `ContextCard.quieter_in: ("games" | "check_in")[] ≤ 2` and
  `FeelPlan.manner: string ≤ 240 | null` (the companion's words-only cue: an enum and one fixed sentence, never a
  number); `Course.summary` may be 900 characters (was 700).
- **Wording rule `face_talk`** (`wording.py`, in every `lint()`): Kaiku comments on the person's face or looks
  ("you look tired", "you weren't smiling"), or says it or a camera saw, watched or noticed them. "I can't see you /
  your face" is the honest answer and passes. **Port it to the Swift linter with the other rules.**
- Tests: `contracts/tests/test_face_signs.py` (payload bounds, no emotion or picture field, the three states, the
  rule version equal to the hash the file had before, the one line that makes a metric vote, the wording rule).


## Tap it back, the drum hold, and the head's audio topics (2026-11-14, additive, D51)
- **`obs.tap_back`** (`payloads.TapBack`, uplinkable, signal group `robot`): one game of "Tap it back" in the drum
  step. `levels[]` (`TapBackLevel`, 1 to 9): `level`, `target_bpm` (the song's tempo), `tapped_bpm` and `error_pct`
  (both or neither: null when she tapped too few to tell a tempo), `steadiness` (0–1, 1 = perfectly even),
  `taps`, `band` (`TapBackBand`: `perfect | great | nice | again`), `tries` (1 = first go), `beat`
  (`beat | half | double`: the beat level her tempo was compared at). Game: `levels_played`, `levels_passed`
  (levels whose band is not `again`), `error_pct` and `steadiness` (means over the levels with a tempo; null when
  none), `taps`, `rejected_taps?`, `duration_s`, `song` (`music` = generated, `beat` = the hub's own plain beat,
  `light` = no sound, the chest light only). Validators: a level with no tempo is `again`; the counts agree with the
  levels. Envelope `quality` as the drum's (share of triggers that were real taps). **Not `obs.drum_session`**: there
  the tempo is hers, here it is given, and the two must never meet in one baseline. **No `[[metric]]` reads it**
  (tested): a game, shown in the person's History only. Example: `registry.EXAMPLES["obs.tap_back"]`.
- **`cmd.head.drum: "hold" | "end"`** (optional): only for a head that runs its own ritual (the standalone
  firmware). `hold` = the hub runs the drum phase: stay in your drum step, no timer and no tap tones of your own,
  keep reporting taps, obey `eyes` and `pan_mode: sway` + `bpm`; re-sent at least every 5 s (the hub: every 3 s),
  the head takes its own timer back after 10 s without one. `end` = the drum phase is over. It means nothing
  outside the head's own drum step, and a hub-driven head (`kaiku_link`) ignores it.
- **`cmd.head.mic: "open" | "close"`** (optional): the head streams its microphone only while this is held:
  `open` again at least every 3 s (the hub: every 2 s), the head closes after 10 s without one; `close` at the end.
- **`cmd.head.show: "help" | "none"`** (optional; sent by the hub's crisis path only): `help` = the head shows the
  helpline's name and number and the emergency number on its own screen, from constants compiled into its firmware
  (`firmware/atech-head/kaiku_link/helpline.h`, checked against `config/kaiku.toml [safety]` by a test), until
  `none`, a new ritual on the head, or 10 minutes. Never a sound. Two words and no free text: the hub can send the
  head nothing to display (tested). Examples: `registry.HEAD_EXAMPLES`.
- **`raw.hub.trace`** (`payloads.HubTrace`, strict; source `hub`; topic `kaiku/v1/<home>/raw/hub/trace`; QoS 0, not
  retained; `raw.*` is never uplinkable): what Kaiku says and does, live, for the "Kaiku bot" tab of the person's
  own apps on the home network. `kind`: `said | heard | tool | session | game | music`. `text` (≤ 300): **only for
  `said`**, Kaiku's own words (a scripted line, or the Live voice's reply as its output transcription gives it).
  `tool` (≤ 40): only for `tool`, the name of the tool the voice called. `by`: for `said` how it was spoken
  (`script | live | cached_voice`); for `tool` who answered (`notebook | gemma | flash | argon | rule`), only when
  the cloud's result says so. `ms` (a tool call's duration), `ok`. `detail` (≤ 80), a machine word: session
  `open | close`; music `start | song | hush | stop`; game `level:<n> | your_turn | band:<perfect|great|nice|again>`.
  `bpm`: the tempo of a music `song` or a game `level`. **`heard` carries nothing but its kind** (she spoke; her
  words never travel on the bus), and the model validator refuses `text` on any kind but `said`, `tool` on any
  kind but `tool`, and a model's name as the `by` of a `said`. No field exists for a tool's arguments or result.
  Not stored: `tools/record.py` and `tools/replay.py` drop its `text`. Examples: `registry.EXAMPLES`,
  `registry.TRACE_EXAMPLES`. Tests: `hub/tests/test_trace.py`, `tools/tests/test_tools.py`.
- **Audio topics: NOT envelopes** (`topics.py`: `audio_topic`, `is_audio_topic`, `AUDIO_RATE_HZ` 16000,
  `AUDIO_FRAME_MS` 20, `AUDIO_FRAME_SAMPLES` 320, `AUDIO_FRAME_BYTES` 640, `AUDIO_STREAMS`):
  `kaiku/v1/<home>/audio/head/speaker` (hub → head: the music, the chimes, Kaiku's voice) and
  `kaiku/v1/<home>/audio/head/mic` (head → hub), and `kaiku/v1/<home>/audio/phone/mic` (the app → hub: a phone or
  Mac beside the robot standing in for the head's microphone, D56; same frames, same rule). One MQTT message = one frame = 20 ms of signed 16-bit
  little-endian mono at 16 kHz = 640 bytes, QoS 0, never retained, no JSON, no id, no timestamp. A zero-length
  message on the speaker topic = "drop what you have buffered, now". `audio` is not a message kind: no type maps to
  it, `validate()` rejects a frame, and nothing that handles messages may see one. `Bus.publish_audio(data, stream=)`
  sends (dropped silently while offline: late audio is noise; `Bus.audio_dropped` counts), `Bus.on_audio(stream,
  handler)` receives the bytes; `Bus._dispatch` routes these topics before any parsing, so they are never
  validated, logged or handed to an `on()` handler (tested on a real broker). **Every tool that walks topics must
  skip them** with `is_audio_topic` (`tools/record.py`, `tools/bus_tail.py`, `tools/replay.py` do; tested). The hub's
  uplink and local store take envelopes only, so audio cannot reach them.
- `raw.head.tap.src` already had `imu`: the head's own motion-sensor taps use it, with `force` and the head's own
  clock (`t_ms` of two boards cannot be compared; the hub takes one source per run of taps).
- Tests: `contracts/tests/test_tap_back_audio.py`.

## More of the day from Apple Health, and how a History value is read (2026-11-14, additive, D53)
- **`obs.wearable_daily`** (`payloads.WearableDaily`) gains seven optional fields, all default null, no
  `SCHEMA_VERSION` bump; existing fields keep their meaning:

  | field | bounds | meaning |
  |---|---|---|
  | `distance_km` | 0 to 300 | walking and running distance over the previous day, 00:00 to 00:00 local, in km, two decimals |
  | `daylight_min` | 0 to 1440 | time in daylight that day (Apple Watch only) |
  | `walking_hr_bpm` | above 20, below 250 | the day's average walking heart rate |
  | `sleep_deep_min`, `sleep_rem_min`, `sleep_core_min` | 0 to 1440 each | minutes in each stage of the night; all three absent when the night has no stages, all three present (0 allowed) when any staged sample exists |
  | `sleep_awake_min` | 0 to 1440 | minutes awake between first falling asleep and last waking; absent when none was recorded |

  One total or average a day: there is no field for a sample, a trace, a time of a stage or a place, and none
  for a sleep score (Apple gives apps none; `extra=forbid` rejects an invented one, tested). The model does not
  enforce "three stages together": that is the producer's rule, and a cloud that refused a day over it would lose
  the day's other numbers. Example: `registry.EXAMPLES["obs.wearable_daily"]`.
- **Criteria:** six `role = "shown"` metrics read these fields (`config/criteria.toml`); the type stays one that
  scored metrics read, so it is not in `Criteria.shown_types`. The rule version is unchanged (tested:
  `tests/test_wearable_health.py`).
- **`api.HistoryFormat = number | clock | percent | duration`** on `HistoryMeasure.format` and
  `HistoryValue.format`. `percent`: the value stays a share 0..1, the app shows it ×100 with "%", `decimals`
  applies to the percent number, `unit` says what it is a share of ("of the time") or is empty. `duration`: the
  value is minutes, the app shows "7 h 20 min" from 60 on and "45 min" below, `unit` is empty.
  `HistoryUsual.low/high` are in the measure's format. `HistorySession.values` holds up to 16 values.
- **Which day:** `WearableDaily.date` is the morning the summary was made. Sleep fields are the night that ended
  that morning; steps, distance, daylight, exercise, resting and walking heart rate and HRV are the day before,
  00:00 to 00:00 local. The rule engine files every field under `date`; the person's History puts the day-before
  fields on the day before (`cloud/AGENTS.md` → "Which day a Health number stands under"). No field was added for
  this: a `HistorySession` of such a measure carries the same envelope `id` with a `ts` at the end of that day.
  `sleep_regularity` is in the model and no Apple build sends it (the simulators do).

## What the model noted from pictures (2026-11-15, additive, D65)
- **`obs.vision_note`** (`payloads.VisionNote`, source `cloud`, group `adherence`, no vote): `task, device, model,
  frames_n, face_visible, expression (neutral|smiling|lowered|tense|unclear), gaze, posture, lighting, confidence,
  not_a_diagnosis: true, ref?`. Closed lists only: no free text and no picture field, extra fields are refused.
- **API:** `VisionLookRules` (in `CompanionSessionResponse.vision_look`, null = not offered) and `VisionLookResult`.
  The request of `POST /v1/vision/look` has no model on purpose: pictures must not pass through anything that could
  print them in a validation error.
