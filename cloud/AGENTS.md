# cloud — AGENTS.md

> Read the root `AGENTS.md` first. Owner C · kind service. Update this file in the same commit as any change to this
> module's interface, structure or invariants.

## Purpose
The Modal service. It ingests `obs.*` from all four sources (robot via the hub; glasses, laptop/Mac and phone apps
directly; the watch summary comes from the phone), keeps them in SQLite, computes per-source verdicts and the deterministic **consensus** (stable / watch /
needs_call / safety), explains it (deterministic facts with optional hosted Gemma/Gemma Modal evidence prioritisation — the explanation never
changes the state), learns which nudge helps (bandit), runs the consensus-accuracy simulation, and serves the
Next.js export. How each input is used is defined in `config/criteria.toml` (see "Tuning the consensus").
It also serves the person-facing companion (`/v1/me` mascot, highlights, garden), Kaiku's one voice
(`/v1/voice`, Gemini TTS, cached) and the **companion mind** (`mind/`): the session bootstrap every surface calls
before opening Gemini Live, the tool endpoint, and Kaiku's notebook (memories, episodes, open thread).

## Boundaries
May import `kaiku_contracts` + fastapi, numpy, httpx, modal, google-genai (voice only, lazily) — never hub, apps, sim or tools. Request/response shapes
are `kaiku_contracts.api`: change them there (contract change), never ad hoc here. `sim/patients` and
`sim/seed_demo.py` import `kaiku_cloud.jobs.synth` (sim is a harness); never the reverse.

## Consumes (topics/endpoints)
- `POST /v1/events` — `{events: [Envelope]}` of `obs.*` only (max 500), idempotent by `id`. From hub, glasses
  (`source: glasses`), laptop/Mac (`source: laptop`) and phone (`source: phone`).
- `PUT /v1/health/{home_id}` — `NodeHealthReport` from each hub.
- `POST /v1/companion/tool` — `CompanionToolCall` a device forwards from the model (see Emits).
- `POST /v1/companion/episode` — `EpisodeIn`: one finished session (or one run offline); idempotent by `id`.
- `POST /v1/patients/{id}/actions` — `{action: flag_booster|flag_icbt_referral|acknowledge|send_message, note?, by?, ts?}`;
  `ts` = when it really happened (default now, 422 if in the future), returned in `PatientInsight.actions`.

## Emits (topics/endpoints)
| route | returns |
|---|---|
| `GET /healthz` | `Healthz` |
| `GET /v1/discovery` | Public `APIDiscoveryResponse`: API service identity, schema, demo/authenticated/unconfigured mode, auth requirement and protocol capabilities; no home IDs or credentials. Bonjour `_kaiku-api._tcp` identifies this service independently from a robot. |
| `GET /v1/patients` | `PatientsResponse` ranked safety › needs_call › watch › stable, with per-source badges |
| `GET /v1/patients/{id}/consensus` | `Consensus`: state, rule_version, one `SourceVerdict` per source (4), agreement, `Explanation` |
| `GET /v1/patients/{id}/timeline?metrics=&days=30` | `TimelineResponse`: `series[]` with `source`, `worse_when`, baseline band |
| `GET /v1/patients/{id}/phq9` | `Phq9History` + `next_due` |
| `GET /v1/me?home_id=` | `MeResponse` — person view: plain-language summary, what helps, next suggestion, `mascot`, `highlights` (7 days), `garden` |
| `GET /v1/voice?lang=en\|fi\|sv` | `VoiceLinesResponse`: every keyed line as text (captions/offline) |
| `GET /v1/voice/{line_key}?lang=` | `audio/wav` in Kaiku's voice (cached on disk); 404 unknown key; **503 + JSON `{detail, reason, hint}`** when TTS is unavailable and nothing is cached |
| `POST /v1/voice/say` | `VoiceSayRequest {text ≤ 400, lang}` → `audio/wav`, same voice, cached by text hash (home token); 422 on a crisis phrase (never voiced); 503 + hint without TTS |
| `GET /v1/nudge?home_id=` | `NudgeResponse` (Thompson sampling) |
| `GET /v1/commands?home_id=&since=` · `WS /v1/stream/{home_id}?token=` | `cmd.hub` envelopes (clinician_message, phq9_due); pending until explicit acknowledgement |
| `POST /v1/commands/{id}/ack?home_id=` | `CommandAckResult`; idempotent acknowledgement after device application; unknown/foreign ID 404 |
| `GET /v1/events?home_id=&since=&limit=` | `LiveEventsResponse` (newest first) |
| `GET /v1/health` | `HealthOverview` |
| `GET /v1/eval` | `EvalResult` (per-state precision/recall, false needs_call per patient-month, lead time, ablation) |
| `POST /v1/admin/recompute?eval=true` · `POST /v1/admin/reset[?home_id=]` | recompute (+ simulation) · delete simulated data (of one home when `home_id` is given; live recordings always stay) |
| `GET /v1/admin/criteria` · `PUT /v1/admin/criteria` · `POST /v1/admin/criteria/preview?eval=1` | criteria in effect · apply/reset a live override · dry-run (`CriteriaResponse` / `CriteriaPreview`) |
| `POST /v1/companion/session` | `CompanionSessionResponse {session_id, model, voice, system_instruction, tools[], context_card, persona_version, safety_phrases_version, live_token\|null, live_setup}` (home token). `live_setup` = Kaiku's recommended Live setup (persona, voice, tools, `[live]` automatic VAD + barge-in, transcriptions); the token locks only the model (`fieldMask: model`), so devices add resumption / compression / tool behaviour |
| `POST /v1/companion/tool` | `CompanionToolResult {ok, executor, result, error, crisis}` — crisis check first, then surface + schema, then the effect |
| `POST /v1/companion/episode` | `EpisodeResult`; 422 if the thread topic is refused or the id belongs to another home |
| `GET /v1/me/memories?home_id=` | `MemoriesResponse` ("What Kaiku remembers", newest first, expired plans dropped) |
| `DELETE /v1/me/memories/{id}?home_id=` · `DELETE /v1/me/memories?home_id=` | `DeletedResponse` (404 if not that home's) |
| `GET /v1/me/transcripts?home_id=` | `TranscriptsResponse` — opt-in conversation transcripts, newest first (D33) |
| `DELETE /v1/me/transcripts/{episode_id}?home_id=` · `DELETE /v1/me/transcripts?home_id=` | `DeletedResponse` (404 if not that home's) |
| `PUT /v1/me/memory_settings?home_id=` | `MemorySettings {remember}` — false = no memory writes |
| `POST /v1/companion/tool` `feel` | `result` = `FeelPlan` (stance, depth, reflect_hint, recall, may_offer, follow_up_saved, scheduling): how to meet a noticed feeling for this person, decided by code — see "Notice and act" |
| `POST /v1/companion/tool` `ask_mind` | `result` = `MindAnswer` (route memory › gemma › Gemini fallback tiers › scripted fallback; grounded cites, tags stripped) — see "Gemma-primary mind" |
| `GET /v1/me/constellation?home_id=` | `ConstellationResponse`: people/places/likes/what helps/plans/activities + edges (no health data, scores, states, evidence ids) |
| `GET /v1/me/week?home_id=` · `GET /v1/patients/{id}/week` | `WeekSummary` (D34): routines (daily / most days / a weekday rhythm, usual time, this week kept/partly/slipped), `going_well`, `worth_a_look` — by code (`week.py`); person wording never has states/scores/z; care team adds metric drift, verdicts, bandit, safety flags, PHQ-9 cadence; both get `sources` (the one record: what robot / apps / glasses / watch added per day, counts only); care team gets `next_steps` (fixed rules: call today on safety, check-in call on needs_call, template-suggested booster/iCBT with their action, PHQ-9 due, slipped routine, best response, disagreeing sources) |
| `GET /v1/me/graph?home_id=` · `GET /v1/patients/{id}/graph` | `KnowledgeGraph` ("What Kaiku has learned"): graph.py nodes + obs-only activities + routine nodes, evidence counts, detail. Care team: empty + `shared: false` unless the person shares; then only me/activity/routine (free-text helpers can contain private names/places) (`withheld` lists the rest) |
| `GET /v1/me/sharing?home_id=` · `PUT /v1/me/sharing?home_id=` | `CareSharing {share_with_care_team}` — default **off** (D34) |
| `POST /v1/companion/postcard` · `GET /v1/me/postcards/{id}` | `PostcardResponse {id, url, cached, model}` (Nano Banana 2 Lite, cached) · the image; **503 + `{detail, reason, hint}`** without a key / over the daily cap |
| `GET /v1/health/intelligence?days=7` | `IntelligenceHealth`: per day/model/task calls, ok, fallbacks, p50/p95 ms; ask_mind `routes`; fallback rate |
| `GET /v1/patients/{id}/tasks?days=7` | `TaskObservationsResponse`: latest 100 `obs.play_session` envelopes within 1–30 days, newest first; aggregate-only reaction/speech and optional local camera features with device/method/coverage/samples/source/quality/sim provenance; clinician/admin only |
| `POST /v1/patients/{id}/ask` | `ClinicianAskResponse` — clinician/admin only, grounded Gemma record question with verifiable `RecordCitation` entries and human-unit details; explicit template fallback, evidence/question cache and cooldown |
| `GET /v1/patients/{id}/insight?generate=true` | `PatientInsight`: the intelligence layer in one care-team payload — `review` (Gemma findings, each citing `evidence` ids; numbers rendered by code), `trace` (steps that really ran), `comparison` (this week / week before / usual), `routine` (routines + what helps with interval), `graph` (permitted nodes/edges), `coverage`. `generate=false` never calls a model. See "Practitioner insight" |
| `GET /v1/patients/{id}/brief` | `ClinicianBrief` (latest `POST /v1/admin/weekly` while it still matches this week's state and rule version; otherwise the template). Never reads the notebook |
| `POST /v1/admin/reflect` · `POST /v1/admin/nightly-mind?home_id=` · `POST /v1/admin/weekly?home_id=` | daily focus · graph rebuild + Embedding 2 backfill + Gemma validated consolidation diffs + pre-render list · weekly briefs |
| emits `obs.safety_flag` | `{trigger: phrase, handled_locally: false}` (source `cloud`) when a crisis phrase arrives in a tool call |
| `/` | static Next.js export (`apps/web/out`) when built; `/v1/*` and `/healthz` always win |

All models: `contracts/python/kaiku_contracts/api.py` (TS: `contracts/ts`). Interactive docs at `/docs`.

Discovery advertises protocol support, not model readiness or a robot connection. Only explicit credential-free
demo mode permits a new installation-generated home to bootstrap without provisioning; no seed or enrollment
endpoint is needed. Its first observation establishes monitoring. Authenticated mode still requires the home's
existing credential, and unconfigured mode keeps private/paid routes closed. Live bootstrap still enforces
provider availability, budget and session duration; discovery never supplies a Live token.

Timeline series = the enabled `[[metric]]` blocks of `config/criteria.toml` (each with `metric`, `label`, `unit`,
`source`, `worse_when`). PHQ-9 is charted from `/v1/patients/{id}/phq9`.

## Map
```
app.py                    Modal: one ASGI container (single SQLite writer), Volume, 15-min recompute, nightly
                          simulation (.map over simulate_shard); optional Gemma vLLM runs in separate gemma_app.py
                          Image installs API/analytics runtime dependencies explicitly, including NumPy;
                          explicitly copies non-Python explanation prompts and config/persona/voice/safety assets.
                          tests/test_deployment.py stages a Python-only image and verifies real API startup offline.
kaiku_cloud/
  settings.py             env (DB path, tokens, LLM), config/kaiku.toml [ritual] accessors, TZ from criteria
  service.py              use-cases: effective criteria (file|override), recompute, preview, consensus (+LLM cache),
                          timeline, phq9, me, nudge
  clinician_chat.py       clinician-only record questions from deterministic consensus + observed timelines/routines;
                          first/latest seven-day comparisons, Gemma citation selection, verified fact rendering,
                          cache + cooldown; never private mind tables
  companion.py            /v1/me mascot (pure fn of state), highlights (good moments + criteria `person_hard`),
                          garden (interactions in 14 days, resting after 3 quiet days) — pure functions
  voice.py                config/voice_lines.toml + Gemini TTS (Interactions API) + disk cache; `python -m
                          kaiku_cloud.voice` pre-renders (`make voice-prerender`)
  mind/                   companion mind (plan 03 §3–§6; scope guard steps 2, 3, 7)
    assemble.py           persona.md + surfaces.toml surface + context card -> system instruction (pure; the evals
                          import this file, so they test what is served); persona+<sha8>
    card.py               build_card(): time of day, name, done today (any surface), suggestion, phq9_due, ≤ 3
                          memories, routines, open thread, tone cue (stable steady · watch gentle · needs_call/safety
                          extra-gentle · no data / low_coverage steady). Never state words, numbers or watch data
    memory.py             notebook rules: categories, health-detail refusal, dedupe, "don't remember that", remember
                          off, plans expire (7 d), recall (FTS5 bm25 + porter + recency), routines (≥ 3 completed
                          sessions of one intent on one weekday in 35 d), open thread (3 d, one at a time)
    session.py            start_session (episode opened), run_tool (crisis -> safety_flag, nothing stored), end_session
                          (closes episode, closes the thread of the same skill, opens follow_up), record_episode
    router.py             ask_mind: exact memory/graph/today → hosted Gemma → Flash/Argon fallback; grounding
                          (cite ids verified + stripped), conflict → ask, prompt hygiene (`clean_fact`), Argon budget
    graph.py              kg_nodes/kg_edges built by code (memories, episodes, bandit `helped`), Embedding 2 index +
                          recall (cosine, FTS fallback, 1-hop), conflicts, consolidation diffs, constellation
    brief.py              weekly clinician brief (flagship, metric-id grounded, template fallback)
    postcard.py           walk postcard (fixed style prompt from stats; disk cache; daily cap)
    nightly.py            POST /v1/admin/nightly-mind
    live_token.py         Live setup (REST camelCase; VAD knobs `config/kaiku.toml [live]`) + ephemeral token with
                          only the model locked (`bidiGenerateContentSetup` + `fieldMask: model`; uses=1, configured session duration / 1 min to start);
                          None without GEMINI_API_KEY, over budget or on any error; app tokens reserve the full configured duration; robot uses its own metered server adapter
  insight.py              GET /v1/patients/{id}/insight: evidence + recorded direction per record, Gemma findings →
                          per-finding validators → code-rendered facts, completeness guard, cache/cooldown, trace;
                          week comparison, help intervals, permitted graph, coverage (all deterministic)
  course.py               the course of change by code: per measure first day away from usual, furthest day, back in
                          range / still away; care actions + PHQ-9 on one timeline; phase; learned graph links
  account.py              generic citable records for any obs type no metric covers, reflection overview (shared
                          only), the per-day plain-language account
  mind/affect.py          reflection summaries (level, tone, energy, themes; never words): rules at episode end,
                          Gemma relabel after the episode and nightly, the reading the companion reported
                          (`heard`), deleted with the transcript; context-card line
  mind/feel.py            the `feel` tool: register a noticed feeling, decide in code how to help (stance, depth,
                          recall, one offer), save the follow-up thread; no model call
  week.py                 D34 dashboard: routines from obs (+ episodes for the person / when shared), going well /
                          worth a look (drift_for per metric, verdicts, bandit, safety, PHQ-9), graph view + sharing
  api/dashboard.py        /v1/me/week|graph|sharing, /v1/patients/{id}/week|graph (registered by main.py)
  api/auth.py             fail-closed home/clinician/admin authorization, explicit credential-free demo mode
  api/main.py             FastAPI routes (handoff §6.7); static web mounted LAST so /v1/* always wins
  store/db.py             ALL SQL lives here (events, homes, explanations, commands, actions, node_health, kv,
                          memories + memories_fts, episodes, threads)
  analytics/
    metrics.py            generic daily extraction from Criteria [[metric]] (field / @count / @local_minutes,
                          where filters, agg, missing=zero). NO metric is defined in code
    data.py               PatientData under a Criteria: series, per-source coverage, [[rule]] readings (pure)
    baseline.py           median + MAD; scale = max(1.4826·MAD, min_mad); window ends a lag before the scored day
    drift.py              robust z, direction-aware, every threshold via crit.param(metric, …)
    verdict.py            per source: weighted drifting vs worse_min_weight, [[rule]] triggers, confidence
    consensus.py          [state] rule + day-by-day replay (hysteresis) + correlated-family caveat / count-as-one
    bandit.py             Thompson sampling; reward = 0.5 immediate (intervention_response) + 0.5 next day
  llm/
    ledger.py             usage ledger `model_calls` (no content) + /v1/health/intelligence summary
    explain.py            Consensus → Explanation; LLM JSON validated, retried once, banned words → template
    template.py           deterministic explanation (default, always available)
    gemma.py              THE provider switch: `[gemma].provider` hosted|modal → every Gemma call; model_name()
    gemma_hosted.py       hosted Gemma adapter       gemma_vllm.py   Modal GPU adapter     prompts/explain.md
  jobs/
    single_person.py      Aino's sixteen authored days: export (`--out`) or seed a local demo API through the real
                          routes (`--url`, `--reset` = this person's simulated data only); idempotent; the day-12
                          care call is logged with its own `ts`; the eight-profile cohort is separate
    synth.py              synthetic patients: DEMO_PATIENTS (8, pinned by tests) + evaluation cohort (13 scenarios
                          incl. glasses+laptop-only drift, watch drift, no watch), all with known ground truth;
                          plan-02 signals use a second RNG so plan-01 events/ids are unchanged
    simulate.py           per-state precision/recall, false needs_call / patient-month, lead time, ablation;
                          CLI for offline tuning (`make tune`)
    nightly.py            recompute all (+ simulation) inside the API process
tests/                    test_analytics.py (rule, verdicts, hysteresis, scenarios, LLM fallback), test_api.py,
                          test_companion.py (mascot, garden, highlights, voice 404/503/cache),
                          test_week.py (routines, week wording, sharing gate, graph evidence),
                          test_mind.py (session, tools, memory rules, thread across surfaces, routines, tone, token)
```

## Extension points
- **Add / retune / disable a metric or rule:** edit `config/criteria.toml` only (see "Tuning the consensus").
  Drift, verdicts, timeline and simulation pick it up with no code change. A field the extractor can't read yet
  (new derived field) is a contracts change in `kaiku_contracts/criteria.py` first.
- **Add a consensus source:** map its obs types in `kaiku_contracts/sources.py` (contract change), add
  `[sources.<name>]` + `[[metric]]` blocks to `config/criteria.toml`, extend `jobs/synth.py`.
  `verdict.py` / `consensus.py` are source-agnostic — no change.
- **Move Gemma to our Modal GPU:** deploy `gemma_app.py`, then set `[gemma].provider = "modal"` (or
  `KAIKU_GEMMA_PROVIDER=modal`). Review, record questions, ask_mind, nightly graph organisation and the `auto`
  explanation chain all follow; `model`/trace fields then name the HF repo (+ adapter). No call site picks a provider.
- **Swap / add an LLM:** write `generate(prompt) -> str` (raise `LlmUnavailable` when it can't answer), register it
  in `llm/explain.py:BACKENDS` under the `KAIKU_LLM` value. The template stays the fallback.
- **New route:** add the response model to `kaiku_contracts/api.py` first, then the route; list it in `modules.toml`.
- **Remove:** the bandit, LLM adapters and simulation can each be deleted without touching the consensus.

## Invariants
- The consensus is deterministic and fully determined by (events, actions, Criteria). **Gemma explains; it never
  decides or changes `state`.** `safety` only comes from `obs.safety_flag`; analytics can at most produce `needs_call`.
- No metric names, directions, weights or thresholds in analytics code (synth scenario assertions aside).
- Thin data is never "stable": < 2 sufficient sources → `watch` with `agreement: low_coverage`.
- Only `obs.*` is accepted; duplicates by envelope `id` are ignored. Every protected route fails closed unless
  explicitly running credential-free demo mode. Home credentials are scoped to one home; mixed-home ingestion is
  rejected before any write. Clinician/admin roles cannot use private `/v1/me` or companion routes.
- Commands are durable until the hub explicitly acknowledges successful application; polling, WebSocket delivery
  and lost HTTP responses never consume a command. Repeated acknowledgements are safe.
  Episode completion/thread closure and follow-up opening have durable per-episode phase markers shared by
  Live end_session and device completion uploads; retries cannot replace a newer cross-device thread.
- A source older than its `criteria.sources.<source>.max_age_days` is insufficient with zero confidence.
  Reads refresh summaries when the local date changes. Future-dated input never advances the scoring day.
  Daily snapshots use the configured metric `day_field`; capture time orders `agg=last`, including offline uploads.
- **Memories, episodes, threads and transcripts are person-facing only**: no clinician route reads them (tested).
  Transcripts (D33) exist only when the device sent one (person's opt-in) and are dropped whole if the outcome is
  `crisis` or any turn matches a crisis phrase; never logged (only a turn count). Crisis is irreversible across retries
  and removes any prior transcript. Explicit deletions leave tombstones so queued uploads cannot resurrect them.
  Training export requires a reviewed episode allowlist and separate training consent:
  `python -m kaiku_cloud.jobs.transcripts_export OUT.jsonl --reviewed-episodes ids.json --salt RANDOM_SALT`.
  Regex redaction is assistive, not guaranteed anonymization; retention consent alone never authorizes export. The context card never contains the consensus state, scores, numbers or wearable data; tone is the
  only cue. A crisis phrase in a tool call stores nothing, raises `obs.safety_flag` and returns the scripted message.
- **ask_mind never decides state and never stores anything.** Code verifies every cite id; an unknown id, a missing
  cite (except `emotional`), bad wording or a pick between conflicting notes → next tier or the scripted line.
  Prompts carry only the question + facts that pass `router.clean_fact` (no digits, state words, wearable/health
  words). The graph, vectors, constellation and ledger are person-facing / contentless; no clinician route reads them,
  **except** `GET /v1/patients/{id}/graph` and the episode part of `/week`, and only while the person has
  `share_with_care_team` on (default off, D34): observed activities and routines; never free-text helpers, people, places, likes,
  plans, memories list, episodes or transcripts (tested in `test_week.py`).
- Every paid call (app Live reservation, Flash, Argon, Embedding 2, image) goes through `kaiku_contracts.budget` (guard + metered) and
  writes a `model_calls` row; `BudgetExceeded` = unavailable → fallback.
  TTS retries and Live token minting reserve each attempt before contacting the provider; admission failure stays
  unavailable. The shared mind's provider retries/fallbacks share `[live].mind_timeout_s` with a five-second response
  margin, so each later tier receives only the remaining wait rather than starting a fresh full timeout.
  Exact local notebook matches precede paid query embeddings and reasoning, after conflict/consolidation checks.
  Stateless Gemini Interactions text, image and TTS calls set `store=False`; this does not disable provider-side
  processing/abuse retention or Gemini Live session-resumption retention.
- One SQLite writer: on Modal the API runs as exactly one container; jobs call the API instead of opening the DB.
- No diagnostic wording anywhere (banned-word check on every explanation; tests cover every demo patient, every
  voice line and every `person_hard` sentence).
- The mascot never looks sad or worried at the person; `safety` → mood `crisis`, `line_key: null` (clients show the
  scripted screen from `config/safety_phrases.toml`). The crisis message is never synthesised by `/v1/voice`.
- A source with no data (e.g. no watch) is `insufficient` and not counted — it can never make anyone look worse.

## Tuning the consensus
Ground truth for HOW every data input is used: **`config/criteria.toml`** (schema + validation:
`contracts/python/kaiku_contracts/criteria.py`). Never put a metric definition, direction, weight or threshold in
cloud code — read it from the `Criteria` object (`crit.metrics_for`, `crit.rules_for`, `crit.param`, `crit.sources`,
`crit.state`). The rule version shown everywhere is `crit.rule_version` (name + hash), so every edit is traceable.

The loop:
1. **Offline:** edit a copy of `config/criteria.toml`, then
   `uv run python -m kaiku_cloud.jobs.simulate --compare my.toml` (`make tune CRITERIA=my.toml`) — side-by-side
   per-state precision/recall, false needs_call per patient-month, lead time and the lose-one-source ablation.
   Exits 2 if the file is invalid.
2. **Preview on real (seeded or live) patients:** `POST /v1/admin/criteria/preview` with `api.CriteriaUpdate`
   (`?eval=1` adds the simulation) → `api.CriteriaPreview`: who would change state/verdicts. Nothing is saved.
3. **Apply live, no redeploy:** `PUT /v1/admin/criteria` stores a validated override in the DB and recomputes everyone;
   `{"criteria": null}` resets to the file. `GET /v1/admin/criteria` shows what's in effect (`origin: file|override`).
   Invalid criteria → 422 with the validation message. Admin token applies when `KAIKU_ADMIN_TOKEN` is set.
4. **Make it permanent:** copy the values into `config/criteria.toml`, commit, note the new rule version + the
   simulation numbers in `docs/decisions.md`.
Effective criteria are loaded once per recompute; the file is re-read when its mtime changes (local dev, no
restart). A live override wins over the file until reset. The demo scenarios are pinned by tests — if a tuning
change flips one, decide deliberately (fix the scenario or the criteria).
Current numbers and the open lead-time vs precision trade-off: `docs/decisions.md` (latest tuning D-entry).

## Run standalone
```bash
make cloud-local                 # uvicorn on :8000, DB at logs/kaiku.sqlite
make seed                        # 8 simulated patients covering every state (prints state per patient)
open http://localhost:8000/docs
```
On Modal (`modal setup` once):
```bash
make cloud-dev                   # modal serve (temporary URL, hot reload)
make cloud-deploy                # builds the web app, then modal deploy → public URL
KAIKU_CLOUD_URL=https://<url> make seed
cd cloud && uv run modal run app.py   # simulation fanned out with .map
```
`web` runs as exactly one container (single SQLite writer); DB on its app-specific Volume (`kaiku-data` for the
default app), committed after each
write request. A 15-minute schedule and a nightly cron (03:00 Helsinki, + simulation) call `/v1/admin/recompute`.

## Run with sim
```bash
make cloud-local & make seed                 # history for all states
make broker & make sim & make hub            # live robot data lands on demo-aino's robot card
```
Demo patients (`jobs/synth.py`): `demo-aino` needs_call (robot + apps + watch worse — later sleep midpoint, more
late-night minutes; glasses as usual with a sub-threshold cadence dip → disagree) · `sim-eero` stable, **no watch** · `sim-juho` noisy → stable · `sim-helmi` robot-only → watch · `sim-kaisa` robot only → watch
(low_coverage) · `sim-lauri` PHQ-9 item 9 → safety · `sim-mirja` glasses-only → watch · `sim-onni` improving → stable.

## Config & env
| var | default | meaning |
|---|---|---|
| `KAIKU_DB_PATH` | `logs/kaiku.sqlite` (`/data/kaiku.sqlite` on Modal) | SQLite file |
| `KAIKU_HOME_TOKEN` + `KAIKU_HOME_ID` | unset / `demo-aino` | legacy pairing token bound to exactly one home; all personal reads, writes and paid voice requests send Bearer |
| `KAIKU_HOME_TOKENS` | `{}` | JSON object mapping home IDs to distinct pairing credentials; never store values in repo files |
| `KAIKU_CLINICIAN_TOKEN` | unset → role disabled | Bearer for patient dashboards/actions, event monitoring and health/evaluation; cannot access personal notebook/transcripts |
| `KAIKU_DEMO_MODE` | unset → fail closed | `1` permits unauthenticated local synthetic demos only when no credentials are configured; `make cloud-local` opts in explicitly |
| `KAIKU_ADMIN_TOKEN` | unset → role disabled | distinct Bearer for `/v1/admin/*` and care dashboards/actions; cannot read private person routes |
| `KAIKU_LLM` | `template` | `template` · `gemma_hosted` (needs `GEMINI_API_KEY` + `[models].gemma_hosted`) · `gemma_modal` |
| `KAIKU_WEB_DIR` | `apps/web/out` if present | static site to serve |
| `KAIKU_MODAL_SECRET` | `kaiku-secrets` | Modal secret to attach (deploy still works if missing) |
| `KAIKU_MODAL_APP` | `kaiku` | deployed API app identity; use a distinct identity for staging |
| `KAIKU_MODAL_VOLUME` | `<KAIKU_MODAL_APP>-data` | persistent API state, voice/postcard caches and spend ledger; override only for deliberate state reuse |
| `KAIKU_GEMMA_REPO` | `[models].gemma_hf_repo` | HF repo for the vLLM class |
| `KAIKU_CRITERIA` | `config/criteria.toml` | consensus criteria file (re-read on change) |
| `GEMINI_API_KEY` | unset → voice serves cache only (503 + hint on a miss) | Gemini TTS for `/v1/voice` |
| `KAIKU_VOICE_CACHE` | `[voice].cache_dir` (`logs/voice_cache`; `/data/voice_cache` on Modal) | rendered audio |
| `GEMINI_API_KEY` (mind) | unset → `live_token: null` | mints Gemini Live ephemeral tokens for `/v1/companion/session` |
| `[week]` in `config/kaiku.toml` | see file | routine thresholds (usual weeks, daily/most-days share, kept/partly ratios, sleep shift, helped_min) for `week.py` |
| `KAIKU_VOICE_LINES` | `config/voice_lines.toml` | keyed script (re-read on change) |

Consensus criteria: `config/criteria.toml` (`KAIKU_CRITERIA` points elsewhere; live overrides live in the DB).
PHQ-9 cadence/mode: `config/kaiku.toml [ritual] phq9_every_days`, `phq9_mode` (spoken|both → the cloud queues
`cmd.hub {phq9_due}` for the hub).
Modal secret: `modal secret create kaiku-secrets KAIKU_HOME_TOKEN=... KAIKU_ADMIN_TOKEN=... GEMINI_API_KEY=... HF_TOKEN=...`

## Health signal
`GET /healthz` validates SQLite and the effective criteria schema, returning HTTP 503/degraded if either is invalid;
otherwise `{status, version, schema_version, db, llm, time}`. It performs no paid model probe. JSON-lines logs on stdout (`modal app logs kaiku`).

## Tests
```bash
uv run pytest cloud/tests   # rule table, hysteresis, acknowledge, low coverage, correlated caveat / count-as-one,
                            # criteria edits alone change outcomes, every demo patient's state, LLM fallback +
                            # banned words, bandit, simulation + tuning CLI, every API route incl. criteria + auth
uv run python -m kaiku_cloud.jobs.simulate [--criteria A.toml] [--compare B.toml] [--n 40]   # offline tuning
make e2e-intelligence       # REAL calls (cents; needs .env GEMINI_API_KEY [+ ADC], or KAIKU_ENV_FILE=): temp cloud +
                            # seed → session token → Live typed/spoken (VAD)/barge-in → TTS keyed + say → ask_mind
                            # → nightly-mind graph → constellation. Exit 2 = no key (unit tests stay offline)
```

## Known issues
Current demo capture is deliberately narrower than the archived contract vocabulary. `jobs/synth.py` no longer
fabricates light, force, pulse summaries, Friendlink, retired browser sessions or unverified glasses camera/IMU
fields. Outings use `method=steps`; supported games/Mac rhythm/ratings/Health remain. Enabled monitoring metrics
are defined only in `config/criteria.toml`; retired/unverified metrics are disabled there, not given fake zeroes.
`jobs/demo_story.py --out <dir>` exports reproducible, globally namespaced synthetic events and a report derived
by the real rule/week engine for sustained change, improvement, missing coverage and one poor task. It never
opens an existing database or calls a provider. Retries deduplicate and story IDs cannot collide with the demo cohort.
Week records deduplicate corrected Health snapshots by measured date, count only measured sleep/step days, and
attribute app ratings to the shared check-in group. Specific improving metrics precede generic kept-routine
messages in bounded care summaries. Outing duration does not prove outdoor location.
This release returns English context even to a client with a saved legacy locale. Gemma corrective prompts
include a bounded rejection category, without retaining model text in validation telemetry.
`[ritual] enabled_nudges` excludes unimplemented Friendlink/iCBT paths from suggestions; historical outcomes remain
readable but cannot cause an unavailable activity to be selected.
- Baseline windows use Europe/Helsinki calendar days (`[defaults] timezone` in criteria.toml).
- `gemma_vllm` / the `Gemma` class have not run on a verified real GPU deploy. Configured Gemma IDs are concrete;
  gated weight access, vLLM compatibility, cold/warm latency and GPU cancellation still need separate acceptance.
- Simulation numbers come from our own generator (`jobs/synth.py`): they show the method and its failure modes
  (see the ablation), not clinical validity.
- Every demo patient's end state is a test (`test_demo_patient_lands_in_intended_state`). If a rule or generator
  change flips one, fix the scenario deliberately — the live demo depends on it.
- Re-seeding on a later day is a no-op (ids don't depend on the date): `make seed ARGS=--reset` re-anchors to today.
- `homes.summary` rows written by v1 code are ignored and recomputed on first read.
- `/v1/voice` + `/v1/voice/say`: verified with real calls (`make e2e-intelligence`, platform/ADC TTS path).
- Companion: Live model/voice come from `config/kaiku.toml [models].gemini_live` / `[voice].name`. Ephemeral tokens
  need `GEMINI_API_KEY` (a Developer API feature; ADC can't mint them). Verified 2026-11-14 with real calls: token
  with `live_setup` as the setup frame → typed turn, spoken turn (automatic VAD), tool call, barge-in (`interrupted`).
  `enableAffectiveDialog` makes constrained sessions fail (1007 on the first turn), so `[live].affective_dialog=false`.
  The REST field is `bidiGenerateContentSetup` (`liveConnectConstraints` is the SDK name; REST answers 400 — the old
  code always failed soft to null).
  `forget` and `ask_mind` are in the registry on every surface but not yet in `config/surfaces.toml` tool lists (the
  prompt lists the served tools, so they are described anyway; owner of config/persona.md + surfaces.toml: add an
  "ask_mind when unsure" line).
- Plan 06 paths (Flash/Argon JSON for ask_mind, Embedding 2, Nano Banana 2 Lite image) are tested with a mocked SDK
  client only; no real call has been made from this build env (no key). The image `response_format` shape
  (`{"type": "image", "aspect_ratio": "4:3"}`) follows the May-2026 Interactions docs.
- The nightly Argon judge over eval scenarios is skipped in the cloud (scenarios live in tools/, which the cloud may
  not import) — run `make eval-companion`.
- The synth emits screen activity in 4 blocks a day (not hourly) to keep `make tune` fast; the real Mac app is hourly.

## Intelligence wiring (2026-11-14)
- **One key:** `GEMINI_API_KEY` in the repo `.env` (template: `.env.example`). `make cloud-local` loads it via
  `kaiku_cloud.api.local`; tests and `make smoke` use `kaiku_cloud.api.main` and never read `.env` (no paid calls).
  `make doctor` checks the key and that every model ID in `config/kaiku.toml [models]` is visible to it (free lookups).
- **Gemini text:** `llm/gemini.py` (Interactions API) — tiers `fast` (`gemini_fast`) and `flagship` (`gemini_flagship`).
- **Explanations:** `KAIKU_LLM=auto` → hosted Gemma → Gemini fast → template. `gemma_modal` only when selected.
- **Gemma on Modal:** separate scale-to-zero app `kaiku-gemma` (`cloud/gemma_app.py`): `make gemma-download` (CPU,
  weights → Volume), `make gemma-deploy` (no container starts), `make gemma-smoke` (one cold call). GPU/scale-down in
  `config/kaiku.toml [gemma_modal]`.
- **Daily reflection:** `mind/reflect.py` — the flagship picks today's focus from fixed options (validated; rule
  fallback); runs in the nightly job and `POST /v1/admin/reflect`; sessions only read the cached plan (card `focus`).
- **Live through the mind:** every surface opens Gemini Live with what `POST /v1/companion/session` returns
  (persona + surface + context card + tools; ephemeral `live_token` for apps); cloud tools go to `/v1/companion/tool`.

## Gemma-primary mind (plan 06 §1–§3, integrated 2026-11-14)
- **ask_mind routing** (`mind/router.py`, one ledger outcome row `ask_mind.route` per question):

  | case | route |
  |---|---|
  | kind fact/memory/plan, exactly one strong memory hit (≥ half the question's content words), or "what did I do today" | `memory` (code, no model) |
  | any other kind/question | hosted Gemma JSON `{answer, confidence, cites}`, validation and one corrective retry |
  | Gemma unavailable/invalid | explicit Gemini fallback chain below |
  | Flash confidence < `[mind].escalate_below` (0.6), Flash failed/invalid | → Argon |
  | fallback kind care / emotional, or conflicting notes | Argon first, then Flash |
  | Argon over `[budget].argon_per_home_day` (20, local day) or spend cap | Flash only |
  | nothing valid | scripted line (care: best approved `[care_passages]` passage; conflict: "which is right?") |
- **Graph** (`mind/graph.py`): rebuilt by code on every memory write/delete, ask_mind, constellation and nightly; node
  statuses (merged/expired) come only from validated diffs. Recall uses Embedding 2 vectors when a key + vectors
  exist (memory vectors on write, nightly backfill), else FTS5; the context card uses it too (FTS path = the old rule).
- **Ledger** (`llm/ledger.py`): `model_calls(ts, home_id, model, task, route, latency_ms, ok, fallback)`; written by
  gemini.py (text/embed/image), gemma adapters, the router, explain/reflect/brief fallbacks.
- Config: `config/kaiku.toml [mind]` (escalate_below, embedding/image model, postcard_dir), `[budget]`
  (argon_per_home_day, images_per_home_day + the spend caps), `[care_passages]`.

## Integration hardening (2026-11-14)
- `CompanionSessionResponse.max_session_seconds` is enforced by clients. Token expiry is an authorization/resumption
  limit, not proof the provider terminates an established stream. App admission reserves an estimated full session
  in the spend ledger and records `live_reservation` in intelligence health; unused reservations remain conservative.
- Successful robot bootstrap deliberately returns no ephemeral token: the robot uses its existing server-side key
  and budget meter once. A failed/unauthorized bootstrap must block robot voice. Other surfaces require a token.
- `resume_session_id` reuses an existing open same-home/surface episode and returns the remaining original duration;
  unknown, foreign, closed and expired sessions return 422. Tool calls cannot mutate another home's/surface's episode.
- Hosted Gemma collects non-thought text parts, rejects incomplete responses and validates complete JSON, enums and
  prohibited wording; validation failures get a corrective retry then deterministic fallback, with content-free logs.
- `tests/test_runtime_integrations.py` drives production HTTP routes and SQLite across restarts: role/tenant isolation,
  real phone envelopes, stale/offline/future inputs, command acknowledgement, monotonic crisis/deletion, resume scope,
  wearable snapshots and Live admission budgets. Provider transport is mocked only for deterministic budget tests.

- Gemma-primary routing is selected by `[mind].primary`; `[gemma_hosted]` controls output cap and timeout.
  `source_facts` rebuilds grounded, source-labelled recent activity presence on every tool request using
  `[mind].source_context_days`. It never sends raw metrics, scores, consensus state or transcripts to the model.
  Source presence does not prove physical device connectivity or tell how the person feels. All generated answers
  retain citation/wording/conflict validation and must not invent numerical measurements.
- `context_refresh_seconds` from `[live]` lets active clients poll for new input and ask the mind to interpret it;
  cloud context is fresh at that tool call. No unsolicited cloud push or guaranteed model availability is implied.
- Actual hosted Gemma was verified through production ingestion + companion tool routes with synthetic phone input:
  `route=gemma`, model `gemma-4-26b-a4b-it`, a validated source citation; with configured minimal thinking the response took about two seconds, and a clinician explanation about six seconds.
  Reasoning calls still use a separate bounded timeout while voice capture remains live.
- Durable volume commits are awaited before a successful mutation response; commit failures return 503. SQLite
  idempotency/tombstones let event and episode queues retry without duplicate or resurrected records.

- Hosted Gemma's configurable `thinking_level` uses the documented `minimal`/`high` API switch. `minimal` is the
  default for short grounded JSON responses so hidden reasoning cannot exhaust the response token budget.
  API reference verified: https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api (Thinking).

- Gemma also organises the private graph in the existing nightly/admin job: clean confirmed nodes → structured
  merge/expire proposals → deterministic home/type/person checks → node status changes. Source memories are never
  rewritten. Unchanged cleaned node sets reuse a cached result, so observation ingestion and ordinary Live turns
  make no organisation model call. Bootstrap reads the organised graph without requiring embeddings; merged/expired
  nodes are excluded. Its bounded `source_context` contains at most one recent fact per actual input source, marks
  synthetic observations, and is withheld when others are present. Gemini Live can use that prepared context directly.
- Clinician explanation caching ignores arrival timestamps, keys on semantic evidence/rule/model selection, and
  serializes each home's generation. `[gemma_hosted].explanation_cooldown_s` bounds regeneration and retries after
  provider failures; changed evidence during cooldown uses the current deterministic explanation, never stale prose.

- Clinician record chat (`POST /v1/patients/{id}/ask`) reads deterministic consensus, numeric observation
  timelines and OBS-only routines. It never reads memories, episodes, transcripts or personal sharing. Gemma selects one to eight validated
  citation IDs. Every displayed fact, unit, source label and comparison direction is rendered by code; unsolicited
  model prose is discarded. Unknown or malformed selections fall back explicitly to the deterministic summary. Citation details format durations as hours/minutes, clock offsets as HH:mm,
  ratios as percentages and steps as whole counts; raw value/unit/date/baseline also accompany metric citations.
  Question text is neither logged nor stored; cache keys hash question+evidence, and a configurable per-home cooldown
  bounds new generations. Gemini Live is not involved in clinician record chat.
- The persistence hook also awaits commits for GET routes that update cached summaries/explanations/usage and for
  voice cache reads/renders, so derived model-call accounting is not lost merely because the HTTP verb was GET.

## Optional task capture inspection (2026-11-14)
- The task endpoint reads only validated `obs.play_session` envelopes, excludes future/old records, and preserves
  the producer's method, capture coverage, sample count and quality alongside the existing task measurements.
  Raw audio, video, frames and task transcripts remain invalid payload fields and are never retained.
- Facial movement features from MediaPipe and Vision remain separate uncalibrated observational methods. They
  add no criteria metric, baseline pooling or state vote. Their presence does not establish mood or wellbeing.
- Clinician record-chat citations may describe task participation and usable-face coverage/sample provenance;
  expressivity and movement index values are excluded from the model's evidence. `task:<event UUID>` citations
  link back to the aggregate inspection record. Camera opt-in and on-device capture are implemented by app owners.
- `tests/test_task_observations.py` covers web/phone round trips, roles/home isolation, newest-first/date/100-row
  bounds, optional/zero-face metadata, raw-media rejection, unchanged analytic inputs and bounded model evidence.

## Verified practitioner facts (2026-11-14)
- Practitioner chat now asks Gemma only to rank relevant supplied citation IDs. The server renders selected records
  verbatim from deterministic evidence, with explicit latest-versus-personal-usual direction and source-group label.
  Unsolicited model prose is discarded, even if it cites real evidence: a valid citation cannot justify a reversed
  direction. Task questions retain coverage and explicit unknown capture; no camera index interpretation is added.
- Consensus explanations use the same boundary: Gemma orders known sources and prioritises supplied metric IDs;
  the template renders source verdicts, recorded directions, caveats and scripted actions. `by=gemma` means model
  prioritisation, not model-authored factual claims. Source-group labels do not prove physical device connectivity.
- Whole minutes, steps and clock offsets round ties toward positive infinity, matching browser Math.round,
  including negative clock offsets. Semantic cache versions invalidate older generated prose. Content-free
  practitioner fallback categories distinguish provider unavailability, invalid JSON and invalid/unknown citations.

## Early collection and a coherent authored record (2026-11-14)
- `uv run python -m kaiku_cloud.jobs.single_person --out /private/tmp/kaiku-aino` exports sixteen consecutive
  days for `aino`: 225 validated `sim=true` observations plus derived week/graph/consensus JSON. Add
  `--url http://127.0.0.1:18061` to seed an explicitly selected local API whose discovery mode is `demo`.
  Nonlocal/credential-bearing/ambiguous URLs and non-demo services are refused. Only `--reset` deletes anything, and only this person's simulated observations (`POST /v1/admin/reset?home_id=`); it never
  changes the eight-profile default cohort or calls a model. Stable IDs make repeated loading idempotent.
- The record uses phone check-ins and step-based outings, robot interaction/ritual/knock timing, native Firefly
  and Pebbles, Mac category totals and optional Apple Watch aggregates. It fabricates no light, force, pulse,
  retired laptop session, facial movement or daylight capture. All simulation provenance remains in envelopes.
  Confirmed fictional notebook facts, four finished conversation episodes and one walk continuation provide
  companion continuity. No audio, transcript or camera frame is invented or stored. The authored person explicitly
  shares the permitted activity/routine graph; private people/places/preferences stay outside care responses.
- The same record closes the feedback loop through 15 enabled walk/breathe/drum offers, 13 accepted and two
  declined outcomes, and 13 explicit mood/energy before/after responses. Accepted next-day outcomes match the
  following morning's actual authored ratings and outing minutes; declines have no invented next-day feedback.
  No reward override, HRV or pulse is supplied. The existing learner derives a walk mean reward of 0.68 versus
  breathing 0.396 and drumming 0.354, while Thompson exploration remains enabled. The permitted shared graph
  derives its `helped` walk edge from those observations, not a forced memory or state assignment. These are
  reported activity responses and preferences, not evidence of causal treatment efficacy.
- `help_stats.tries` counts completed/declined nudge outcomes when an activity has them; otherwise it counts
  immediate response records. The two feedback halves are never added as separate tries. Existing contracts
  have no attempt-link field, so mixed unlinked responses are not claimed as additional distinct attempts;
  their immediate-effect contribution and posterior/reward maths are unchanged. The authored case therefore
  displays nine walk attempts and three each for breathing/drumming, with nine pieces of walk outcome evidence
  on the shared learned edge. Regression tests cover paired halves, declines, either missing half and mixed
  unlinked feedback without inventing exact pairing.
- Early routine frequency uses the actual collection horizon before the latest seven days, bounded by
  `[week].usual_weeks`, with the configured minimum occurrences still required. Short histories say
  `Emerging pattern` and show the observed numerator/denominator; they do not claim an established long-term
  usual. Graph routine evidence counts actual recorded activity days rather than extrapolated historical weeks.
- Practitioner review evidence includes the record span and days with observations, emerging routines, and
  first/latest seven-day window medians when both windows have at least three observed days. A cross-input
  context fact connects recorded mood/energy/outing changes without attributing cause; task timing comparisons
  retain a practice-effect caveat. Gemma prioritises supported patterns and at most two routines for broad reviews;
  every displayed claim still comes from verified server facts. A complete sixteen-day capture does not force a
  stable consensus while the person's baseline is forming. `tests/test_single_person.py` exercises contract
  validation, repeat seeding through actual API routes, private-table isolation, honest early routines/graph counts
  and verified review selection alongside the existing week/practitioner suites.

## Modal deployment isolation and private inference boundary (2026-11-14)
- Modal's Python-source copy does not include Markdown prompts. The image explicitly packages
  `kaiku_cloud/llm/prompts` at `/root/kaiku_cloud/llm/prompts`, alongside the existing full `/root/config` copy
  (settings, criteria, persona/surfaces, voice lines and safety phrases). A deployment regression builds a
  temporary Python-only package tree, applies the image's actual explicit asset copies, imports the real API
  outside the checkout and verifies `/healthz`. This reproduces and prevents the missing `explain.md` startup
  failure found on the first protected deployment; Python dependency checks alone cannot establish startup.
- API deployments default to `<app-name>-data`, preserving `kaiku` → `kaiku-data`. A staging app named
  `kaiku-staging` therefore uses `kaiku-staging-data`; changing only the secret must never be used as data
  isolation. `KAIKU_MODAL_VOLUME` permits deliberate reuse, and is carried into the image environment. Tests
  evaluate the actual default/staging/explicit-volume configuration without contacting Modal.
- For an authenticated pilot, configure a distinct secret containing per-home `KAIKU_HOME_TOKENS`, separate
  clinician/admin credentials and the provider credential; keep `KAIKU_DEMO_MODE` unset or `0`. New homes need
  provisioned credentials: public discovery never issues them. Missing secrets still allow a fail-closed API
  deployment and do not establish a working voice service. Build the static export before deployment. Acceptance
  must independently verify authenticated ingestion, home/role isolation, browser HTTPS, retained writes after
  restart and model/voice capability; `/healthz` checks SQLite/criteria rather than paid provider readiness.
- `KAIKU_LLM` selects consensus-explanation generation only. Hosted Gemma remains the configured companion
  primary (`[mind].primary`); practitioner chat and nightly graph proposals explicitly use hosted Gemma.
  `KAIKU_LLM=gemma_modal` neither deploys `gemma_app.py` nor makes the whole service private. The optional GPU
  app must be deployed separately, and no self-hosted, fine-tuned or always-warm capability is implied.
- The GPU explanation adapter admits/reserves its estimate before dispatch, uses `spawn()` and bounded
  `FunctionCall.get(timeout=remaining_deadline)`, and requests best-effort `cancel(terminate_containers=False)`
  after a result timeout. Cancellation does not refund the reservation or guarantee immediate cost cessation.
  Lookup/submission/cancellation still depend on the Modal control plane; the bound applies to the result wait.
  Content-free ledger rows retain success/failure and latency, and surfaced adapter errors contain only an
  exception class. The implementation follows the official
  [FunctionCall get/cancel reference](https://modal.com/docs/sdk/py/latest/FunctionCall), checked 2026-11-14.
  Mocked tests cover remaining wait time, timeout/cancellation failure, spend rejection and invalid deadlines;
  they start no GPU and make no provider request.

## Practitioner insight (2026-11-14)
- `GET /v1/patients/{id}/insight` (`insight.py`) is the one payload a dashboard needs to show the intelligence
  layer. Load with `generate=false` (cached review or template, no model, ~50 ms), then call again without it
  (one Gemma call, ~10 s hosted; cached by evidence hash afterwards).
- **Review.** Evidence = the record-chat citations plus `week:<metric>` and `helps:<activity>`, each with a
  code-computed direction (better/worse/similar/unknown) and a `sustained` flag (rule engine: source verdict
  worse, metric drifting, routine slipped). Gemma returns findings `{theme, cites, meaning, consider}`. Code
  rejects a finding one by one, by content-free category shown in the trace: `invalid_shape`, `unknown_citation`,
  `numbers_in_prose` (any digit), `wording` (banned terms, wording linter, state talk), `causal_claim`,
  `direction_mismatch` (theme vs recorded direction; `change` needs a sustained record, so a week-to-week dip
  inside the usual range can never be called a change from usual), `duplicate`. Titles, facts, numbers and the
  headline are rendered by code. A signal group with a sustained change that no accepted finding covers gets its
  deterministic finding appended (`by: template`), and the trace says so. Nothing valid after one corrective
  retry, no key, an outage or a timeout → the deterministic template with `fallback_reason`.
- **Freshness.** The cache key hashes the shortlisted evidence + model + `REVIEW_VERSION`; any new observation that
  changes a cited fact retires the prose. Inside `[insight].cooldown_s` changed evidence shows the template
  (`fallback_reason: cooldown`), never the older review.
- **Residual limit.** Direction is verified at better/worse level per cited record; the exact wording of the
  model's two sentences is not fact-checked beyond that, which is why the verified facts are printed beside them.
- **Trace** rows are built from the execution that produced the response (latency, model, cache hit, counts,
  rejection categories). No prompt, question, record text or model text is stored in it or in the ledger.
- **Graph** needs no sharing switch: it is built from observations the care team already sees (signal groups,
  measures, activities, routines, reported responses). Sharing only adds conversation *counts* per activity.
  The private notebook graph (`kg_*`), memories, transcripts are not read (tested with poisoned accessors).
- **Stored briefs** are served only while week, state and rule version still match the current consensus.
- Deployed services (`KAIKU_MODAL_APP` set by `app.py`): `/v1/admin/*` always needs the admin credential, also in
  demo mode; a deployed demo may keep `KAIKU_ADMIN_TOKEN` so the scheduled jobs work while reads stay open.
  Local behaviour is unchanged (`tests/test_deployment.py`).
- Fine-tuning: `[gemma_modal].adapter_repo` lets `gemma_app.py` serve a LoRA adapter (vLLM `enable_lora` +
  `LoRARequest`). No adapter exists and the GPU path has not been run; the hook is not a fine-tune.
- `tests/test_insight.py`: template completeness, validator categories, completeness guard, cache + invalidation,
  outage/invalid fallbacks, missing sources, one-day record, role isolation + private tables, provider switch,
  stale brief, and a storage audit posting every registered `obs.*` example through ingest → events API → coverage.

## Early records and calibration (2026-11-14)
- **Provisional early baseline** (`analytics/drift.baseline_of`, `Baseline.early`): while a metric has no full
  baseline, criteria `[defaults].early_baseline_min_days` / `early_baseline_lag_days` (5 days, lag 3) give a
  provisional one from about day 9. Evidence summaries built on it end "(early baseline: N days, lower confidence)".
  Set `early_baseline_min_days = 0` to switch it off. Thresholds live only in `config/criteria.toml`.
- **Never stable while young:** fewer calendar days than `[state].min_history_days_for_stable` (21) → `watch` /
  `low_coverage` at best, in the day-by-day replay too.
- **Weight-0 metrics are observe-only:** charted and compared, never a vote and never what makes a source sufficient.
- **Evidence direction** comes from the days that voted: `MetricDrift.z_flag` / `flag_direction` (not the latest
  day). `week.py` prints and sorts by `z_flag` when set.
- `make calibrate [CRITERIA=] [COMPARE=] [N=]` (`analytics/calibration.py`): labelled synthetic courses → how well
  the rule separates "not well" from "ok", early-day behaviour, single-metric flippers. Owner: calibration.
- **How the API says it:** `TimelinePoint.early`; `MetricComparison.early_baseline` + `baseline_days`;
  `PeriodComparison`/`DataCoverage` `.early_baseline` + `.day_of_record`; `PatientReview.early_record`;
  `LearnedRoutine.early_record` + `.caveat`; `PatientInsight.day_of_record`, `.min_history_days_for_stable`,
  `.early_record`, `.state_history[] {date, state, agreement, early}` (the consensus replay, last 45 days at most)
  and `.actions[]` (care-action log). The review headline adds "Day N of the record: early baseline, lower
  confidence." and Gemma is given the same flag.
- **What helps is a reported response, not an effect.** The learner is confounded on short records (calibration:
  two no-effect activities scored 0.52 and 0.73). `HelpEffect` always carries `tries`, a 90% interval and
  `certainty`; `consistent` is impossible on an early record; findings that say an activity works / is effective /
  proven are rejected (`overclaim`), causal wording too (`causal_claim`).

## Integration follow-ups (2026-11-14)
- **Suggestions follow capability** (`service.nudge_arms`): drumming is offered only to a home with at least one
  observation whose envelope source is `hub`/`head`/`sensors`. Applies to `/v1/nudge`, `/v1/me`, the context card
  and the `suggest_nudge` tool; old reward rows cannot bring it back.
- **`remember` guard** (`mind/session.py`, `memory.grounded`): inside a conversation (a `session_id` of an open
  episode) the call must carry `said`, the person's own words, and at least half of the fact's content words must
  occur in it; otherwise nothing is stored and the tool result tells the model to ask first. The cloud never hears
  the audio, so `said` is the model's own quotation: this stops facts the model cannot tie to words, not a model
  that misquotes. Calls without a session (the app's own save button, seeding) are unchanged.
- **Next steps and explanations suggest care-process steps only** (check-in call, ask about sleep and evenings,
  a message before the call, PHQ-9, a slipped routine). Code never suggests a booster, iCBT or any treatment;
  `flag_booster` / `flag_icbt_referral` remain actions a practitioner may log by their own decision.
- **Incomplete day** (`service.patient_data`): today's value of a `sum`/`count` metric is neither scored nor
  charted until the local day is over. Snapshot metrics (`agg = last`, e.g. watch steps) are not covered: the
  payload does not say whether a snapshot is final.
- **Provenance is a flag**: `Consensus.simulated`, `PatientSummary.sim`, `RecordCitation.simulated`,
  `DataCoverage.simulated`, per-type `simulated` counts. Headlines and evidence text no longer contain the word.

## The record as a story (2026-11-14)
- `PatientInsight.course` (`course.py`): `{phase: settling|steady|dip|recovering|recovered, summary, events[]
  {date, kind: onset|lowest|care_action|phq9|back_in_range|still_away, group, metric_id, label, text}}`. A day is
  "away" when its worse-signed z against that day's baseline reaches the metric's own `z_threshold` and it does not
  print the same as the usual. Onset needs a second away day within the next two scored days; back in range needs
  the last two scored days in range. `[insight].course_days` (28) is the look-back. Order in time only. The phase
  is `recovered` only when the consensus is `stable` on an established baseline; a young record is `settling` or
  `recovering`. With an early baseline, "back in range" can partly be the baseline absorbing the dip: the summary
  says lower confidence.
- **Review** (`insight.py`): Gemma receives the course as `course:summary` + `course:<kind>:<metric>` records and
  returns `overview {text, cites}` (`PatientReview.overview`, `.overview_cites`) plus findings. Added checks:
  `filler` (overall, vitality, interconnected, well-being, areas, may impact, daily life …), `generic` (names no
  cited measure and no order/timing word), `thin` (restates one fact), more causal words (driver, trigger …).
  An overview must cite a `course:` record and use a sequence word when a course exists; a rejected overview is
  dropped (trace step `overview`) while valid findings stay. `reflect:` and `obs:` records are supporting cites:
  they never decide a finding's theme.
- **Facts** are one plain sentence each ("Mood dial 3 of 5 this week, down from 4 of 5 the week before and below
  their usual 4 of 5; away from usual on 3 of the last 5 scored days."). Dates print as "9 Nov" everywhere a
  practitioner reads them; source verdicts read "Sustained change from their usual." etc.
- **Graph layers**: every node/edge has `layer: learned|structure`. Learned: `moved_first`, `followed` (order,
  not cause), `moved_together` (away on the same days, different groups), `kept_through` / `slipped_during`
  (routine days while measures were away), `after` (care action → what came back, at most six), `helped`
  (attempts + certainty), `keeps`, `talked_about`, and `shared_topic` count nodes. With sharing on, notebook
  categories appear as counts only ("People in their notebook · 3"): never a name, place or sentence.
- **Reflections** (`mind/affect.py`): per finished conversation `{valence: low|neutral|bright, themes ≤ 3 of a
  fixed list, declined}` in `kv affect:<home>`. Text is read only when the device sent a transcript (the person's
  opt-in); otherwise only `declined` from the outcome. Crisis conversations get none. Rules at episode end;
  `POST /v1/admin/nightly-mind` lets Gemma relabel from the stored transcript (validated enums, else the rule
  label stays). Deleting a transcript deletes its summary. The keyword rules are crude (a "rough day, but a good
  walk" can read bright) until the nightly relabel has run.
  The person's companion always gets it: `ContextCard.last_reflection {when, valence, themes, declined}`,
  `.recent_reflection` (one line) and `.today_facts[]` (their own ratings in everyday words, e.g. "a short
  night": never a number, never watch data), all rendered into the card prompt. The care team gets counts only,
  and only while the person shares: `PatientInsight.reflections`, the `reflect:recent` record, `talked_about`
  graph nodes and the reflection part of `days`.
- **Daily account**: `PatientInsight.days[] {date, text, parts[]}`, newest first, 14 days: what was done, mood in
  their own rating, which measures were away from usual, reflection level (shared), care actions.

## How a robot signal reaches the intelligence layer
1. Firmware publishes `raw.<node>.<stream>` on the home MQTT bus (never uplinked).
2. The hub turns it into one derived observation per session/day: `Bus.publish("obs.<name>", payload)`.
3. Contracts (the only cloud-side step): a pydantic payload in `payloads.py`, an entry + example in
   `registry.py`, a line in `sources.py` (`"obs.<name>": "robot"`, or `"adherence"` for no vote), `make contracts`.
4. The hub uplinks it: `POST /v1/events`. The cloud validates, stores it with source/quality/sim, and it is
   readable at `GET /v1/events` and counted in `PatientInsight.coverage`.
5. With no cloud code it becomes a citable record `obs:<name>` (`account.generic_records`: days recorded, who
   sent it, the latest payload's numbers / yes-no / short enums), is sent to Gemma, can be cited in findings,
   and sits in the graph under its signal group. Add a display name in `insight.OBS_LABEL` if the type name
   reads badly.
6. To make it count toward the verdict, the course and week comparison: add a `[[metric]]` block in
   `config/criteria.toml` (still no code). It then gets a personal usual, onset / back-in-range events and
   `moved_first` / `followed` links like every other measure.
7. Pulse is reported honestly: with a robot but no `obs.hrv_session`, the record says "Not measured".
Tested end to end with a made-up registered type in `tests/test_course.py`.
- Reflections, round three: `ReflectionOverview.days[] {date, part, valence, themes, declined}` (14 days) and a
  fortnight `summary` ("sounded low in 3 of 3 between 7 Nov and 9 Nov; lighter since the evening of 9 Nov. Themes:
  sleep, being alone, then outdoors, friends."); counts stay 7-day. `CourseEvent.kind` adds `reflection_low` /
  `reflection_lighter` (shared only; supporting cites, they never decide a finding's theme). A bare "not now" is
  `declined` with no valence. `days[].parts` say which side of usual each flagged measure was on ("drum tempo below
  usual") and name a missing daily routine ("no walk", "morning ritual skipped"). The nightly Gemma relabel is
  capped by `[insight].reflection_labels_per_night`. `jobs/single_person.py` seeds eleven short reflections
  (`REFLECTIONS`) through the episode route; their labels come from the labeller and are pinned by test.

## One coherent statement (2026-11-14, after the judge-style review)
- `PatientInsight.status_line` (code): when the state was raised (first day of the current run in the rule's own
  replay), who acknowledged it and when, how many measures are back since the low point, and WHY the state still
  shows (groups still changed over the last scored days / held for `hysteresis_stable_days` / young record cannot be
  as usual before `min_history_days_for_stable`). For `safety` it says Kaiku showed the crisis numbers and contacts
  nobody. A UI should show this line beside the state badge and the course phase.
- `Course.low_date`, `.moved`, `.back`; `PeriodComparison.since_low`, `.back_in_range[]`, `.still_away[]`; the
  comparison `summary` leads with the low-point sentence and says the week medians still include the low days.
- A `still_away` event always quotes a day that was away ("last below their usual on …; within usual on …, one day
  so far" when the latest day is in range); a day that prints the same as the usual is never "away".
- Provenance is one value: `Consensus.simulated` = `DataCoverage.simulated` = every `RecordCitation.simulated` =
  "the record contains simulated observations" (envelope `sim`); per-type counts say how many.
- `service.display_name(home_id, started)`: a home whose id is an installation id is shown as
  "New record · started 14 Nov", never an id fragment. The notebook's first name is not used: care routes do not
  read the notebook.
- Seeded story (`jobs/single_person.py`): signals move on day 9, the consensus raises "needs a call" on day 12 from
  daily signals alone, the care team rings on day 13 (`CARE_DAY`), the PHQ-9 that evening confirms, measures
  come back from day 13-14. Pinned in `tests/test_single_person.py` and `tests/test_followups.py`.
- Reconciled truth for the model: the review evidence carries `status:line`, `course:back` and `course:still_away`,
  and every measure in the course has `now: back within usual | still away from usual`. New validator categories:
  `contradiction` (a measure said to be away when the course has it back, the reverse, or both in one text; a
  clause about the rule still flagging is not an "away" claim; a word that maps to measures on both sides is not
  judged) and `directive` (a consider line that tells someone to increase / reduce / do more of an activity). A
  rejected overview is null: show `course.summary` in its place (trace step `overview`, `rejected`).
- Time-of-day measures read "later / earlier than usual" in consensus evidence, week items and day lines.

## Notice and act (2026-11-14): detect, register with the mind, act
Kaiku is a companion, not a reporting machine. The voice model is the only part that hears the person; the mind
decides in code what to do about it.
- **Tool `feel`** (cloud, all surfaces, `behavior: NON_BLOCKING`): args `kind` (`sad_news | good_news | flat |
  angry | worried | lonely | proud | relief | other`), `heard {valence, energy?, tone[≤2]?, via: voice|text}`,
  `about?` (topic, ≤ 80), `said?` (the person's own words, ≤ 300). `session.run_tool` runs the crisis gate on every
  argument first: a crisis phrase never reaches `feel`, and a crisis drops the conversation's summary and timeline.
- **Register** (`mind/feel.py`): the moment joins `kv feel:<home>` (per conversation: enums, whether the one offer
  was made). While the person lets Kaiku remember things it is also kept as `heard` on the conversation's
  `affect` row; with remembering off the timeline lives for the conversation only (dropped at `end_session` /
  episode). `said` is never stored. A topic becomes the open thread ("their good news: …" / "something hard: …",
  skill `weather_check`, one per conversation) only when remembering is on, the topic is contained in `said`
  (`memory.grounded`, the `remember` guard) and it is not a health detail.
- **Plan** (`feel.plan_from`, pure; result model `FeelPlan`): `stance` (`comfort | celebrate | steady | explore |
  give_space`), `depth` (`brief | stay`), `reflect_hint`, `recall`, `may_offer`, `offer_note`, `offer_activity`,
  `follow_up_saved`, `scheduling`.
  - depth is `stay` for news, an upset or very glad voice (low + tearful/high energy, bright + high energy), a low
    or flat moment when talks sounded low or flat on ≥ 3 of the last 7 days, a second strong moment in the same
    conversation, or a long/asking `said`; otherwise `brief`.
  - recall is one of: what they told Kaiku helps, a person they mentioned, the plan they were hoping for (good
    news), "the talk yesterday evening sounded hard too", their own "a short night" rating. Nothing when the record
    has nothing.
  - may_offer is the suggestion with the best recorded response for this person (`service.best_response`:
    posterior mean, arms this home can do, tried ≥ `help_early_tries` first) with how sure that is in words, else
    "sitting quietly together". Once per conversation; never for good news or anger; only the quiet on an
    extra-gentle day.
  - a heavy few days are named in `reflect_hint` only when the record shows them. The practitioner flag stays with
    the rule engine: nothing here reads or changes the consensus.
- **Latency**: no model call; `feel.prepare` computes the helper and today's own ratings when the session starts
  (`kv feel-prep:<home>`, 30 min), so the handler is a few small reads (median well under 300 ms, tested).
- **Live**: `live_setup` declares `feel` with `behavior: NON_BLOCKING` (asynchronous function calling; the Live
  tools guide lists it as supported on `gemini-3.8-live`) and the result carries `scheduling`
  (`[live].feel_scheduling`, default `WHEN_IDLE`). Real sessions on 2026-11-14: the model calls `feel` before it
  speaks; with `WHEN_IDLE` it then answers using the plan, with `SILENT` it said nothing that turn. A client that
  declares it blocking gets the same result after the round trip. `CompanionTool.behavior` tells clients.
- **After the conversation**: a talk that sounded low or flat (`affect.last_was_low`) makes the next card `gentle`
  when it was `steady`, and `service.suggest` (card, `/v1/nudge`, `/v1/me`) returns the best recorded suggestion
  instead of a Thompson draw. Good news is the next card's `open_thread`.
- **Check-in as a passing chat**: `CompanionSessionRequest.purpose` (`talk | check_in | walk | ritual`, optional;
  `intent` is unchanged). With a purpose the response carries `chat_shape {purpose, depth, open_items}` and the card
  `purpose`, `chat_depth`, `open_items` (dials not answered today; morning: sleep first). For `check_in` the
  instruction gets a section "The shape of this conversation" (`assemble.render_shape`): brief = greet, one open
  question, a warm close within about four exchanges; stay when the last talk was hard or the week heavy; at most
  one open item woven in, `record_dial` only for a number the person offers, never a scale.
- **Tone as an observation** (never a state): from their words `tone[≤2]` of `flat | tense | tearful | irritable |
  warm | playful | calm` and `energy low|medium|high` (keyword rules; one Gemma call after an opted-in episode,
  `[insight].reflection_label_at_episode_end`, validated enums, labelled once; nightly relabel as before); as
  reported by the model in the conversation `heard {valence, energy, tone, provenance: model_heard | model_read,
  moments}`. Shown, only while the person shares: `reflections.days[].tone/energy/heard`, `reflections.tone_summary`,
  the day account ("evening reflection low (sleep), words tense, voice flat and quiet"), `reflection_low/lighter`
  course events, the `reflect:recent` record. The companion's card: `last_reflection.tone/energy/heard`.
  "Forget everything" (`forget all`, `DELETE /v1/me/memories`) also removes the reported readings.
- **Limits**: `heard` is what a model says it heard; `via` is its own claim (typed text in a Live session was
  labelled `voice` in the real run). Affective dialog stays off (`[live].affective_dialog`): the Live guide lists
  it for `gemini-3.8-live`, real sessions closed with 1007.
- **The plan does not hinge on the model's label**: `feel.read_kind` reads news from the person's own words
  (`LOSS` / `WIN` cue lists on `said` + `about`, only when how it sounded does not contradict it), so "My sister
  cancelled again…" gets `comfort` + `stay` whether the model called it `sad_news`, `other` or `flat`. Depth also
  uses valence + energy, tone, repeated low days, an earlier moment in the conversation and how much they said.
- **Only observed facts about today** (a real check-in opened "You've been out already today" with nothing
  recorded): the cause was `router.source_facts` saying "reported an outing recently" for yesterday's outing next
  to the persona's example line of that exact sentence. Now: source facts always say when in words (`today |
  yesterday | earlier this week`); every instruction carries "What you may say as fact" (`assemble.render_grounding`):
  quoted lines are examples of how to speak and never facts, yesterday is not today, "nothing is recorded for today
  yet" when `done_today`/`today_facts`/today's source facts are empty, and no weather unless the card has it. The
  check-in shape says to open with a plain greeting when "Today" lists nothing.
- **`remember` guard** (`memory.grounded`): more than half of the fact's content words must be in the person's own
  words, and every name, day or number in it must be too. Good news the model wants to keep is stored only then.
- Tests: `tests/test_feel.py`. Evals: `tools/companion_evals/scenarios/act.yaml`.

