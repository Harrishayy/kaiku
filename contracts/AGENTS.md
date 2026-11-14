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
midpoint in min from local midnight, regularity, resting HR, HRV SDNN, steps, exercise, `device`).
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

