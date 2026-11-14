# cloud — AGENTS.md

> Read the root `AGENTS.md` first. Owner C · kind service. Update this file in the same commit as any change to this
> module's interface, structure or invariants.

## Purpose
The Modal service. It ingests `obs.*` from all four sources (robot via the hub; glasses, laptop/Mac and phone apps
directly; the watch summary comes from the phone), keeps them in SQLite, computes per-source verdicts and the deterministic **consensus** (stable / watch /
needs_call / safety), explains it (template, hosted Gemma, or Gemma 4 on a Modal GPU — the explanation never
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
- `POST /v1/patients/{id}/actions` — `{action: flag_booster|flag_icbt_referral|acknowledge|send_message, note?, by?}`.

## Emits (topics/endpoints)
| route | returns |
|---|---|
| `GET /healthz` | `Healthz` |
| `GET /v1/patients` | `PatientsResponse` ranked safety › needs_call › watch › stable, with per-source badges |
| `GET /v1/patients/{id}/consensus` | `Consensus`: state, rule_version, one `SourceVerdict` per source (4), agreement, `Explanation` |
| `GET /v1/patients/{id}/timeline?metrics=&days=30` | `TimelineResponse`: `series[]` with `source`, `worse_when`, baseline band |
| `GET /v1/patients/{id}/phq9` | `Phq9History` + `next_due` |
| `GET /v1/me?home_id=` | `MeResponse` — person view: plain-language summary, what helps, next suggestion, `mascot`, `highlights` (7 days), `garden` |
| `GET /v1/voice?lang=en\|fi\|sv` | `VoiceLinesResponse`: every keyed line as text (captions/offline) |
| `GET /v1/voice/{line_key}?lang=` | `audio/wav` in Kaiku's voice (cached on disk); 404 unknown key; **503 + JSON `{detail, reason, hint}`** when TTS is unavailable and nothing is cached |
| `GET /v1/nudge?home_id=` | `NudgeResponse` (Thompson sampling) |
| `GET /v1/commands?home_id=&since=` · `WS /v1/stream/{home_id}?token=` | `cmd.hub` envelopes (clinician_message, phq9_due); delivered once |
| `GET /v1/events?home_id=&since=&limit=` | `LiveEventsResponse` (newest first) |
| `GET /v1/health` | `HealthOverview` |
| `GET /v1/eval` | `EvalResult` (per-state precision/recall, false needs_call per patient-month, lead time, ablation) |
| `POST /v1/admin/recompute?eval=true` · `POST /v1/admin/reset` | recompute (+ simulation) · delete simulated data |
| `GET /v1/admin/criteria` · `PUT /v1/admin/criteria` · `POST /v1/admin/criteria/preview?eval=1` | criteria in effect · apply/reset a live override · dry-run (`CriteriaResponse` / `CriteriaPreview`) |
| `POST /v1/companion/session` | `CompanionSessionResponse {session_id, model, voice, system_instruction, tools[], context_card, persona_version, safety_phrases_version, live_token\|null}` (home token) |
| `POST /v1/companion/tool` | `CompanionToolResult {ok, executor, result, error, crisis}` — crisis check first, then surface + schema, then the effect |
| `POST /v1/companion/episode` | `EpisodeResult`; 422 if the thread topic is refused or the id belongs to another home |
| `GET /v1/me/memories?home_id=` | `MemoriesResponse` ("What Kaiku remembers", newest first, expired plans dropped) |
| `DELETE /v1/me/memories/{id}?home_id=` · `DELETE /v1/me/memories?home_id=` | `DeletedResponse` (404 if not that home's) |
| `PUT /v1/me/memory_settings?home_id=` | `MemorySettings {remember}` — false = no memory writes |
| `POST /v1/companion/tool` `ask_mind` | `result` = `MindAnswer` (route memory › flash › argon › fallback; grounded cites, tags stripped) — see "Gemini-first mind" |
| `GET /v1/me/constellation?home_id=` | `ConstellationResponse`: people/places/likes/what helps/plans/activities + edges (no health data, scores, states, evidence ids) |
| `POST /v1/companion/postcard` · `GET /v1/me/postcards/{id}` | `PostcardResponse {id, url, cached, model}` (Nano Banana 2 Lite, cached) · the image; **503 + `{detail, reason, hint}`** without a key / over the daily cap |
| `GET /v1/health/intelligence?days=7` | `IntelligenceHealth`: per day/model/task calls, ok, fallbacks, p50/p95 ms; ask_mind `routes`; fallback rate |
| `GET /v1/patients/{id}/brief` | `ClinicianBrief` (latest `POST /v1/admin/weekly`; template until then). Never reads the notebook |
| `POST /v1/admin/reflect` · `POST /v1/admin/nightly-mind?home_id=` · `POST /v1/admin/weekly?home_id=` | daily focus · graph rebuild + Embedding 2 backfill + validated consolidation diffs + pre-render list · weekly briefs |
| emits `obs.safety_flag` | `{trigger: phrase, handled_locally: false}` (source `cloud`) when a crisis phrase arrives in a tool call |
| `/` | static Next.js export (`apps/web/out`) when built; `/v1/*` and `/healthz` always win |

All models: `contracts/python/kaiku_contracts/api.py` (TS: `contracts/ts`). Interactive docs at `/docs`.

Timeline series = the enabled `[[metric]]` blocks of `config/criteria.toml` (each with `metric`, `label`, `unit`,
`source`, `worse_when`). PHQ-9 is charted from `/v1/patients/{id}/phq9`.

## Map
```
app.py                    Modal: one ASGI container (single SQLite writer), Volume, 15-min recompute, nightly
                          simulation (.map over simulate_shard), Gemma vLLM GPU class when KAIKU_LLM=gemma_modal
kaiku_cloud/
  settings.py             env (DB path, tokens, LLM), config/kaiku.toml [ritual] accessors, TZ from criteria
  service.py              use-cases: effective criteria (file|override), recompute, preview, consensus (+LLM cache),
                          timeline, phq9, me, nudge
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
    router.py             ask_mind: deterministic route (memory/graph/today) → Flash JSON → Argon escalation; grounding
                          (cite ids verified + stripped), conflict → ask, prompt hygiene (`clean_fact`), Argon budget
    graph.py              kg_nodes/kg_edges built by code (memories, episodes, bandit `helped`), Embedding 2 index +
                          recall (cosine, FTS fallback, 1-hop), conflicts, consolidation diffs, constellation
    brief.py              weekly clinician brief (flagship, metric-id grounded, template fallback)
    postcard.py           walk postcard (fixed style prompt from stats; disk cache; daily cap)
    nightly.py            POST /v1/admin/nightly-mind
    live_token.py         Gemini Live ephemeral token (REST v1beta auth_tokens, uses=1, 30 min / 1 min to start);
                          None without GEMINI_API_KEY or on any error
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
    gemma_hosted.py       hosted Gemma adapter       gemma_vllm.py   Modal GPU adapter     prompts/explain.md
  jobs/
    synth.py              synthetic patients: DEMO_PATIENTS (8, pinned by tests) + evaluation cohort (13 scenarios
                          incl. glasses+laptop-only drift, watch drift, no watch), all with known ground truth;
                          plan-02 signals use a second RNG so plan-01 events/ids are unchanged
    simulate.py           per-state precision/recall, false needs_call / patient-month, lead time, ablation;
                          CLI for offline tuning (`make tune`)
    nightly.py            recompute all (+ simulation) inside the API process
tests/                    test_analytics.py (rule, verdicts, hysteresis, scenarios, LLM fallback), test_api.py,
                          test_companion.py (mascot, garden, highlights, voice 404/503/cache),
                          test_mind.py (session, tools, memory rules, thread across surfaces, routines, tone, token)
```

## Extension points
- **Add / retune / disable a metric or rule:** edit `config/criteria.toml` only (see "Tuning the consensus").
  Drift, verdicts, timeline and simulation pick it up with no code change. A field the extractor can't read yet
  (new derived field) is a contracts change in `kaiku_contracts/criteria.py` first.
- **Add a consensus source:** map its obs types in `kaiku_contracts/sources.py` (contract change), add
  `[sources.<name>]` + `[[metric]]` blocks to `config/criteria.toml`, extend `jobs/synth.py`.
  `verdict.py` / `consensus.py` are source-agnostic — no change.
- **Swap / add an LLM:** write `generate(prompt) -> str` (raise `LlmUnavailable` when it can't answer), register it
  in `llm/explain.py:BACKENDS` under the `KAIKU_LLM` value. The template stays the fallback.
- **New route:** add the response model to `kaiku_contracts/api.py` first, then the route; list it in `modules.toml`.
- **Remove:** the bandit, LLM adapters and simulation can each be deleted without touching the consensus.

## Invariants
- The consensus is deterministic and fully determined by (events, actions, Criteria). **Gemma explains; it never
  decides or changes `state`.** `safety` only comes from `obs.safety_flag`; analytics can at most produce `needs_call`.
- No metric names, directions, weights or thresholds in analytics code (synth scenario assertions aside).
- Thin data is never "stable": < 2 sufficient sources → `watch` with `agreement: low_coverage`.
- Only `obs.*` is accepted; duplicates by envelope `id` are ignored. With `KAIKU_HOME_TOKEN` set, every
  `POST /v1/events` needs `Authorization: Bearer <token>` (hub, glasses, laptop alike).
- **Memories, episodes and threads are person-facing only**: no clinician route reads them (tested). Episodes hold
  no transcript. The context card never contains the consensus state, scores, numbers or wearable data; tone is the
  only cue. A crisis phrase in a tool call stores nothing, raises `obs.safety_flag` and returns the scripted message.
- **ask_mind never decides state and never stores anything.** Code verifies every cite id; an unknown id, a missing
  cite (except `emotional`), bad wording or a pick between conflicting notes → next tier or the scripted line.
  Prompts carry only the question + facts that pass `router.clean_fact` (no digits, state words, wearable/health
  words). The graph, vectors, constellation and ledger are person-facing / contentless; no clinician route reads them.
- Every paid call (Flash, Argon, Embedding 2, image) goes through `kaiku_contracts.budget` (guard + metered) and
  writes a `model_calls` row; `BudgetExceeded` = unavailable → fallback.
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
`web` runs as exactly one container (single SQLite writer); DB on the `kaiku-data` Volume, committed after each
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
| `KAIKU_HOME_TOKEN` | unset → auth off | pairing token: `Bearer` on `POST /v1/events` (every source), `/v1/commands`, `PUT /v1/health`; browser apps get it from their `?t=` link |
| `KAIKU_ADMIN_TOKEN` | unset → open | Bearer token for `/v1/admin/*` |
| `KAIKU_LLM` | `template` | `template` · `gemma_hosted` (needs `GEMINI_API_KEY` + `[models].gemma_hosted`) · `gemma_modal` |
| `KAIKU_WEB_DIR` | `apps/web/out` if present | static site to serve |
| `KAIKU_MODAL_SECRET` | `kaiku-secrets` | Modal secret to attach (deploy still works if missing) |
| `KAIKU_GEMMA_REPO` | `[models].gemma_hf_repo` | HF repo for the vLLM class |
| `KAIKU_CRITERIA` | `config/criteria.toml` | consensus criteria file (re-read on change) |
| `GEMINI_API_KEY` | unset → voice serves cache only (503 + hint on a miss) | Gemini TTS for `/v1/voice` |
| `KAIKU_VOICE_CACHE` | `[voice].cache_dir` (`logs/voice_cache`; `/data/voice_cache` on Modal) | rendered audio |
| `GEMINI_API_KEY` (mind) | unset → `live_token: null` | mints Gemini Live ephemeral tokens for `/v1/companion/session` |
| `KAIKU_VOICE_LINES` | `config/voice_lines.toml` | keyed script (re-read on change) |

Consensus criteria: `config/criteria.toml` (`KAIKU_CRITERIA` points elsewhere; live overrides live in the DB).
PHQ-9 cadence/mode: `config/kaiku.toml [ritual] phq9_every_days`, `phq9_mode` (spoken|both → the cloud queues
`cmd.hub {phq9_due}` for the hub).
Modal secret: `modal secret create kaiku-secrets KAIKU_HOME_TOKEN=... KAIKU_ADMIN_TOKEN=... GEMINI_API_KEY=... HF_TOKEN=...`

## Health signal
`GET /healthz` → `{status, version, schema_version, db, llm, time}`. JSON-lines logs on stdout (`modal app logs kaiku`).

## Tests
```bash
uv run pytest cloud/tests   # rule table, hysteresis, acknowledge, low coverage, correlated caveat / count-as-one,
                            # criteria edits alone change outcomes, every demo patient's state, LLM fallback +
                            # banned words, bandit, simulation + tuning CLI, every API route incl. criteria + auth
uv run python -m kaiku_cloud.jobs.simulate [--criteria A.toml] [--compare B.toml] [--n 40]   # offline tuning
```

## Known issues
- Clinician routes (`/v1/patients*`, actions, `/v1/me`) have no auth (demo). Don't put real patient data in it.
- One shared `KAIKU_HOME_TOKEN` for all homes (demo); per-home pairing tokens are a post-event task.
- Baseline windows use Europe/Helsinki calendar days (`[defaults] timezone` in criteria.toml).
- `gemma_vllm` / the `Gemma` class have not run on a real GPU deploy yet; model IDs are VERIFY placeholders.
- Simulation numbers come from our own generator (`jobs/synth.py`): they show the method and its failure modes
  (see the ablation), not clinical validity.
- Every demo patient's end state is a test (`test_demo_patient_lands_in_intended_state`). If a rule or generator
  change flips one, fix the scenario deliberately — the live demo depends on it.
- Re-seeding on a later day is a no-op (ids don't depend on the date): `make seed ARGS=--reset` re-anchors to today.
- `homes.summary` rows written by v1 code are ignored and recomputed on first read.
- `/v1/voice` has not been called against the live TTS API yet (no key in the build env); the response parser
  handles both `output_audio` and `steps[].content[]`. Pre-render once a key is available.
- Companion: Live model/voice come from `config/kaiku.toml [models].gemini_live` / `[voice].name`. The ephemeral token
  call follows the current docs but has not run against the real API here (no key); it fails soft to null.
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

## Gemini-first mind (plan 06 §1–§3, workstream I4)
- **ask_mind routing** (`mind/router.py`, one ledger outcome row `ask_mind.route` per question):

  | case | route |
  |---|---|
  | kind fact/memory/plan, exactly one strong memory hit (≥ half the question's content words), or "what did I do today" | `memory` (code, no model) |
  | otherwise | Flash JSON `{answer, confidence, cites}` |
  | Flash confidence < `[mind].escalate_below` (0.6), Flash failed/invalid | → Argon |
  | kind care / emotional, or conflicting notes | Argon first, then Flash |
  | Argon over `[budget].argon_per_home_day` (20, local day) or spend cap | Flash only |
  | nothing valid | scripted line (care: best approved `[care_passages]` passage; conflict: "which is right?") |
- **Graph** (`mind/graph.py`): rebuilt by code on every memory write/delete, ask_mind, constellation and nightly; node
  statuses (merged/expired) come only from validated diffs. Recall uses Embedding 2 vectors when a key + vectors
  exist (memory vectors on write, nightly backfill), else FTS5; the context card uses it too (FTS path = the old rule).
- **Ledger** (`llm/ledger.py`): `model_calls(ts, home_id, model, task, route, latency_ms, ok, fallback)`; written by
  gemini.py (text/embed/image), gemma adapters, the router, explain/reflect/brief fallbacks.
- Config: `config/kaiku.toml [mind]` (escalate_below, embedding/image model, postcard_dir), `[budget]`
  (argon_per_home_day, images_per_home_day + the spend caps), `[care_passages]`.
