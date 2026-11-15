# Plan 04 — Making the mind robust: skills, context, memory, graph, RAG, fine-tuned Gemma · ⏹ SUPERSEDED BY 08 (what was built is in `docs/progress.md`)

> Builds on [`03-intelligence.md`](03-intelligence.md) (one mind, many bodies; numbers decide, models talk).
> 03 says *what* the mind is; 04 says *how we make it good and keep it good*. Every item is tagged
> **MUST** (in the demo), **SHOULD** (if on schedule) or **STRETCH**, with a rough cost. Deadline Sun 10:00.
> Team answers folded in (2026-11-14): the track briefs as text live in `docs/tracks/*.md`; flagship = **Gemini 4 Argon**
> (`gemini-4-argon`); "Hydrogen" and "Carbon" are newer Gemini 4 names the team expects but **not yet in the Gemini
> API model list** (checked 2026-11-14) → config slots `flagship_alt_1/2 = "VERIFY-gemini-4-hydrogen|carbon"`,
> switch when docs list them; watch/sleep data is **collection only** — Kaiku never mentions it in conversation.

## ⚠️ Scope guard (team decision 2026-11-14 — overrides plans 02–04 where they conflict)

**Don't overengineer. Visible working results first.** Build thin vertical slices that each end in something we
can show; depth only after the slice works. If a feature isn't in the demo script, it's STRETCH.

**Build order — each step ends in a demo-able win:**
1. Robot sees you → turns head → says "hey there" (YOLO/MediaPipe + scripted TTS line). *Win: the greeting clip.*
2. Morning ritual over Gemini 3.8 Live with one shared persona + today card + existing tools. *Win: a real chat.*
3. iPhone app: mascot + weather check + Talk to Kaiku (same session endpoint). *Win: same Kaiku on the phone.*
4. Dashboard `/me` + `/clinician` showing the new sources from sims. *Win: consensus with 4 sources.*
5. Glasses walk via iPhone (mock first) + Dynamic Island walking Kaiku. *Win: the walk clip.*
6. Mac notch peek at night + usage rhythm. *Win: the 01:10 clip.*
7. Memory facts + open thread carried across surfaces. *Win: "the lake, like we said".*
Only then: anything below marked SHOULD/STRETCH.

**Cut or simplified now:**
| Item | Now |
|---|---|
| Skills | **4** (morning_ritual, weather_check, walk_companion, breathe), each = one `SKILL.md` + lines; no flow DSL — the existing ritual state machine is the flow |
| Context compiler | one function: persona + surface + today card (+ ≤ 3 memories). No tier budgets/caching machinery |
| Memory | facts + episodes + open thread in SQLite; recall = FTS5 + recency. **No embeddings** yet |
| Knowledge graph, "constellation" | **STRETCH** |
| RAG | ~10 vetted passages, keyword lookup, hand-off otherwise |
| Ask the record (clinician agent) | **STRETCH** |
| Fine-tuning | G1 on-device parser = **STRETCH** (only after steps 1–7); G2/G3 **cut** |
| ShieldGemma, routing table, circuit breakers, observability panel | **cut** — Live → scripted fallback, Gemma → template fallback (exists), plain JSON logs |
| Live Extended Thinking switching | cut (one Live model) |
| Nano Banana postcard, Lyria Clip tunes | STRETCH |
| Evals | ~20 scenarios, dry mode in `make test`; real judge run before the demo |

The rest of this file is the **reference design** for after the demo path works — not the to-do list.

## 0. Where robustness comes from (in priority order)

1. **Structure over prose** — skills are state machines with model "freedom zones", not long prompts.
2. **Small, assembled context** — the model sees a compiled, budgeted, versioned card, never raw data.
3. **Grounding** — every generated claim cites an ID (fact, memory, metric, document) that code verifies.
4. **Constrained outputs** — JSON schema / guided decoding everywhere except live audio.
5. **Fallback chains** — every model call has a cheaper model and then a template behind it.
6. **Evals as the gate** — nothing in persona/skills/context/model changes without the scorecard (03 §9).
7. **Then** learning: distil and fine-tune Gemma on what the evals say is good.

## 1. Skills — Kaiku's repertoire (MUST, ~3 h)

A **skill** is a packaged capability, like a skill for a coding agent: a folder the mind loads only when needed.

```
skills/<name>/
  SKILL.md        # when to use (1 line, goes in the context card), goal, steps, freedom zones, hand-offs
  flow.toml       # deterministic steps: id, kind (say|ask|tool|activity|free), line_key, timeout, next
  lines.toml      # extra scripted lines (keys merge into config/voice_lines.toml namespace skill.<name>.*)
  scenarios.yaml  # eval scenarios for this skill (picked up by tools/companion_evals)
```

- **Progressive disclosure:** the context card lists only skill names + one-line "when to use" (≈ 15 tokens each).
  The model calls `use_skill(name)`; the device loads `SKILL.md` + the current step and injects it into the Live
  session as a context turn (**VERIFY** Live mid-session client-content API). Keeps the base prompt small and every
  skill independently testable.
- **Flow is the boss:** steps of kind `say`/`ask`/`tool`/`activity` are deterministic; only `free` steps let the
  model improvise, with a word cap and a purpose ("acknowledge what they said in ≤ 12 words"). Timeouts fall
  back to scripted lines. A skill can never call a tool it doesn't list.
- **Surface filter:** `surfaces.toml` says which skills each surface may offer.
- **Initial skills:** `morning_ritual` (robot) · `weather_check` (all) · `walk_companion` + `light_hunt` (glasses) ·
  `breathe` (all) · `drum_jam` (robot) · `wind_down` (night, Mac/iPhone/robot: dim, slow, no screens advice phrased
  gently) · `tiny_plan` (pick one small thing for today — *inspired by* behavioural activation; never called
  therapy) · `reconnect` (friend lamp / message someone) · `celebrate` (notice a small win) · `phq9_guide` (reads items
  verbatim; scoring is code) · `continue_thread` (§6). The crisis path is **not** a skill — it is the deterministic gate.
- Owned by a new `skills/` module (kind library); `tools/agents_sync.py` checks every skill has all four files,
  every `line_key` exists, every tool exists in the registry, every skill has ≥ 3 scenarios.

## 2. The context layer — a compiler, not a prompt (MUST, ~3 h)

`cloud/kaiku_cloud/mind/context.py` builds the system instruction + context turns from **tiers**, each with a token
budget, deterministic order and a hash. Logged per session as `ctx+<hash>` (content never logged).

| Tier | Content | Budget | Changes | Caching |
|---|---|---|---|---|
| T0 constitution | persona core, hard rules, safety hand-off text | 600 | per release | Gemini context cache / vLLM prefix cache |
| T1 surface | body, tools, skills list for this surface | 250 | per release | cached with T0 |
| T2 person | first name, language, preferences, top-5 graph facts (§4) | 200 | daily | per home per day |
| T3 today | time, weather word, what they did today on any surface, today's suggestion, open thread, tone cue | 200 | per session | — |
| T4 retrieved | top-3 memories / 1 document passage for the current intent | 250 | per turn (tool) | — |
| T5 live events | short bracketed sensor events: `[drumming started · lively]`, `[walk: 12 min]`, `[second person nearby]` | 40 each | real time | — |

Rules: no numbers about the person's state, ever; T5 events are produced by reflex-loop code from a fixed
vocabulary (so the model can react: "ooh, that's a lively beat!"); total ≤ 1.6 k tokens before conversation;
over budget → drop lowest-ranked T4 then T2 items, never T0/T1. Same compiler serves Live sessions, Gemma
text jobs and the evals — that is the unification.

## 3. Memory — four kinds (MUST core, SHOULD consolidation)

| Kind | Example | Written by | Stored |
|---|---|---|---|
| **Semantic** facts | "sister is called Maija", "likes the lake path" | `remember` tool, spoken confirmation ("want me to remember that?") | `memories` (+ embedding) |
| **Episodic** | "Tue 08:10 robot morning ritual, drum lively, ended happy" | device at session end (structured, no transcript) | `episodes` |
| **Procedural** "what helps" | "walks → better next-day mood (+0.6, n=5)" | bandit + intervention outcomes (numbers, deterministic) | existing tables |
| **Preferences** | "no talking before 9", "call me Ai", "Finnish" | settings + `remember(category=preference)` | `preferences` |

- **Write discipline:** only the six allowed categories; never health details beyond what the person frames as
  a plan or preference; "don't remember that" deletes the last memory; "stop remembering" disables writes.
- **Recall:** hybrid — BM25 (SQLite FTS5) + embedding cosine (EmbeddingGemma on Modal; fallback
  `gemini-embedding-2`) + recency decay + salience (times recalled), fused with reciprocal-rank fusion. Top 3.
- **Consolidation (SHOULD, nightly, Gemma 4 with JSON schema):** merge duplicates, expire stale plans, promote
  repeated episode patterns to facts ("walks most Tuesdays") — each change is a proposed diff applied by code,
  logged, reversible.
- Person controls everything in "What Kaiku remembers" (see / delete / pause). Clinicians never see memories.

## 4. Personal knowledge graph (SHOULD, ~3 h) — small, honest, useful

One person's notebook is < 500 facts, so the graph is **for linking and explaining, not for scale**. SQLite tables
`kg_nodes(id, type, label, created, last_seen)` and `kg_edges(src, rel, dst, weight, evidence_ids, updated)`.

- **Node types:** person(self), people, place, activity, thing_that_helps, time_pattern, plan.
- **Edges:** `likes`, `knows`, `went_to`, `did_on`, `helped` (weight = effect size from the bandit, evidence = the
  outcome rows), `planned`, `usually_at`.
- **Built by code** from tool calls (`remember` with category → node + edge), episodes (did_on, went_to), and the
  bandit (helped). Gemma only proposes entity links during consolidation ("lake path" ≡ "the lake") as a schema'd
  diff code applies.
- **Graph-expanded recall (GraphRAG-lite):** seed nodes from the hybrid search hits → 1-hop expansion → rank by
  edge weight × recency → the T2/T4 lines. This is what lets the glasses say *"Maija's lake path again? Last time
  that walk put you in a good mood the next day."* — every clause backed by an edge with evidence IDs.
- **Person-facing view (SHOULD):** "Your constellation" on `/me` and iPhone — a soft, animated graph of the things
  and people that help you (no health data). Strong demo moment, cheap with the data already structured.
- **Clinician side (separate, numbers only):** the *intervention → outcome* subgraph (no personal facts) feeds the
  "what helps" panel.

## 5. RAG over vetted knowledge (MUST small, ~2 h)

When the person asks "what's a booster session?" or "is it normal to feel tired after TMS?", Kaiku must not make
things up.
- **Corpus:** `knowledge/` — ~20–40 short passages we write in our own words from public sources (TMS aftercare,
  booster sessions, sleep routines, how to reach the clinic, Finnish crisis lines), each with `id`, `source_url`,
  `reviewed_by`, `lang`. No copied text. Clinic-specific passages are placeholders marked `CLINIC-`.
- **Tool:** `look_up(question)` → top passage(s) by hybrid search → the model must answer *only* from them and say
  "your care team can tell you more"; no passage above threshold → scripted "that's a good one for your nurse —
  want me to remind you to ask?" (+ `tiny_plan`).
- **Grounding check (text surfaces):** generated text carries `[doc:<id>]` tags; code verifies IDs exist and strips
  them before display. Live audio: evals measure faithfulness on the same questions.
- **Clinician "ask the record" (SHOULD, strong for the Gemini API track):** Gemini 3.8 Flash with function calling
  over a **read-only metrics API** (`get_series(metric, days)`, `get_consensus_history`, `get_phq9`,
  `get_interventions`) answers "how has sleep been since the booster?" with numbers + a chart spec; every number
  must come from a tool result (checked). Never sees memories.

## 6. Cross-surface continuity — the "one mind" moment (SHOULD, ~1.5 h)

At session end a device writes an **open thread** if one exists (from the skill flow, e.g. `tiny_plan` chose
"walk to the lake", or the person said "let's talk later"): `{thread_id, skill, topic_key, created, expires}` —
structured, no transcript. T3 of the next session on *any* surface carries it, and the `continue_thread` skill
picks it up: robot at 08:15 "maybe the lake later?" → glasses at 11:00 "the lake, like we said — nice." → Mac
at 23:40 "you made it to the lake today. Rest well." Demo-able in 30 s, and it's the clearest proof of one mind.

## 7. Fine-tuning Gemma — distil the flagship into a private Kaiku (SHOULD core, STRETCH extras)

Principle: **Gemini 4 Argon teaches, the eval judge filters, Gemma learns, the same judge proves it.** Synthetic
data only — no real person's words are ever training data.

| Track | Base | Task | Data | Method | Where it runs after | Win we can show |
|---|---|---|---|---|---|---|
| **G1 on-device parser** (SHOULD, ~3 h) | Gemma 3n E2B/E4B (**VERIFY** a Gemma 4 on-device size) | spoken answer → `{item, value, confidence}`; memory-candidate extraction; "is this a command (stop/pause)?" | ~5 k synthetic utterances (en/fi/sv, hesitations, sarcasm, "dunno") generated by Argon, labels verified by a second Argon pass + rules | QLoRA, 1 GPU on Modal, < 1 h | iPhone/Mac on device (LiteRT-LM / MLX — **VERIFY** conversion path) | accuracy & latency vs base and vs cloud; **transcript never leaves the phone** |
| **G2 Kaiku voice** (STRETCH, ~3 h) | Gemma 4 `26b-a4b-it` or `31b-it` | weekly letter, nudge phrasing, consolidation diffs | eval-harness transcripts that scored ≥ 4.5 by the judge + Argon-written letters from synthetic patient timelines | LoRA SFT on Modal (multi-GPU if 31B) | Modal vLLM (LoRA adapter hot-loaded) | judge score + wording-linter violations before/after; cheaper than Argon |
| **G3 preference tuning** (STRETCH) | G2 output | prefer brief/warm/grounded over verbose/clinical | judge-ranked pairs | DPO | Modal | win-rate vs G2 |

- New module **`trainer/`** (kind harness, removable): `gen_data.py` (Argon/3.8 Flash generation with JSON schema),
  `filter.py` (judge + linter + dedupe), `train_modal.py` (Modal app; HF `transformers` + `peft` + `trl` — **VERIFY**
  current Gemma fine-tuning guide on ai.google.dev), `eval.py` (reuses `tools/companion_evals`), `export.py`.
  Datasets + adapters go to a Modal volume / HF private repo — **not git**. Model cards in `trainer/cards/`.
- Gemma licence: accept terms on HF with a team account; note in `docs/decisions.md`.
- Story for judges: *"A frontier model teaches a tiny open model to understand you, so the understanding can live
  on your own phone."*

## 8. Model routing, fallbacks, cost (MUST, ~1 h)

Deterministic routing table in `config/kaiku.toml [routing]` (never an LLM router):

| Task | 1st | 2nd | Last resort |
|---|---|---|---|
| live voice | `gemini-3.8-live` | `gemini-3.8-live-extended-thinking` for flagged intents | scripted flow + TTS cache |
| clinician explanation | Gemma 4 on Modal (vLLM, guided JSON) | hosted Gemma via Gemini API | template (exists) |
| weekly letter / nudge phrasing | G2 adapter → Gemma 4 | hosted Gemma | script lines |
| ask the record | `gemini-3.8-flash` | `gemini-3.6-flash` | "here are the charts" (no text) |
| consolidation / graph links | Gemma 4 | skip tonight | — |
| eval judge / data teacher | `gemini-4-argon` | `flagship_alt_*` when verified | `gemini-3.8-flash` (marked lower-trust) |

Every call: timeout, retry with backoff, circuit breaker per provider, result cache keyed by `(task, ctx hash)`.

## 9. Observability without content (MUST, ~1 h)

Per call/session trace row: surface, skill, step, model, versions (`persona+`, `ctx+`, `criteria+`), tokens,
latency, tools called, linter hits, grounding failures, fallback used. **No text.** `/health` gains an
"intelligence" panel (p50/p95 latency, fallback rate, linter hits/day). Evals compare across versions.

## 10. What makes this genuinely new (for the pitch)

1. **Consensus-gated companion:** the character's tone is shaped by a deterministic, multi-source consensus it
   can't see the numbers of — warmth adapts, judgement never comes from the model.
2. **One mind, many bodies:** a robot, glasses, phone and laptop that share memory, threads and voice in real time.
3. **Privacy by distillation:** a frontier model teaches an on-device Gemma so understanding happens on your phone.
4. **Evidence-carrying words:** every sentence Kaiku writes cites the fact, memory or measurement behind it.

## 11. Workstreams added (run after WS-B merges; I2 is already running)

| WS | Scope | Tier |
|---|---|---|
| **I1** mind | `cloud/kaiku_cloud/mind/`: context compiler (§2), memory + hybrid recall (§3), graph (§4), RAG + `knowledge/` (§5), threads (§6), routing/fallbacks (§8), traces (§9), bootstrap endpoint (03 §3) | MUST/SHOULD |
| **I2** evals | (running) + per-skill scenarios, grounding/faithfulness metrics, scorecard by version | MUST |
| **I5** skills | `skills/` module: 11 skills × 4 files, checker rules | MUST |
| **I4** trainer | `trainer/`: G1 first, then G2 if time | SHOULD/STRETCH |
| **I6** ask-the-record | cloud tool API + `/clinician` panel | SHOULD |

Order: I5 + I1 together (I1 reads skill names from I5's files; stub until merged) → I4 once I2's harness exists
(it needs the judge) → I6 last.
