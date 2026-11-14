# Plan 06 — Gemini-first mind: escalation, graph memory, live context, real daily use · 🟡 CURRENT

> Builds on plans 03/04. The 04 Scope guard cut too much for the **Gemini API track**: the flagship is barely used
> day to day, nothing escalates when unsure, there's no graph, and Live doesn't see live sensor context. This plan
> fixes that **without** breaking the rules: numbers still decide state, safety stays deterministic, every model
> output is validated, every call has a fallback, and daily cost is capped in config.

## 1. Who talks to whom (the "mind loop")

```
person ⇄ Gemini 3.8 Live (voice, every surface)          fast, warm, embodied
              │ tool: ask_mind(question, kind)   ← when Live is unsure / needs facts / a care question
              ▼
        cloud mind (deterministic router)
              ├─ facts it can answer itself (memory, graph, today, care passages) → answer
              ├─ Gemini 3.8 Flash   (structured JSON + self-rated confidence)
              └─ Gemini 4 Argon     ← if Flash confidence < threshold, kind ∈ {care, conflict, emotional}, or Flash failed
              ▼
        validated answer (grounded IDs only) → back into the Live session as the tool result
```
- **Escalation is a deterministic rule**, logged per call (`route: memory|flash|argon|fallback`, latency, confidence).
- Argon answers carry `[mem:<id>]` / `[doc:<id>]` / `[kg:<id>]` tags; code verifies them and strips them before
  Live speaks. Unverifiable claim → Flash/scripted fallback ("I'm not sure — let's ask your nurse").
- Live stays the voice; Argon never speaks directly (latency). Budget: `config/kaiku.toml [budget] argon_per_home_day`.

## 2. Daily Gemini usage (real, useful, every day)

| When | Model | What | Calls/home/day |
|---|---|---|---|
| every conversation | **Gemini 3.8 Live** (native audio, affective, proactive) | robot ritual, glasses walk, app Talk | 2–6 |
| inside conversations | **3.8 Flash → 4 Argon** via `ask_mind` | facts, care questions, conflicting memories, hard moments | 1–5 |
| each session end | **3.8 Flash** (structured) | episode summary + *proposed* memories/graph edges from the tool log + Live output transcription (in memory only, discarded after; person confirms memories) — **needs team OK (§6)** | 2–6 |
| nightly | **4 Argon** | reflection: today's focus + opener (exists) · consolidation of the graph (merge/expire proposals as diffs) | 2 |
| nightly | **Gemini Embedding 2** | embed new memories / graph nodes for recall | few |
| after each walk | **Nano Banana 2 Lite** | walk postcard from stats only (minutes, light-hunt finds, weather word) — never photos | 0–1 |
| lines | **3.8 Flash TTS** | every scripted line in Kaiku's voice (cached); new personalised lines (name, focus) rendered nightly | few |
| drum | **Lyria RealTime** | groove following the drum tempo | 0–1 |
| weekly | **4 Argon** | clinician brief (grounded in metric IDs) + person's weekly letter (Gemma 4 draft → Argon review) | weekly |
| clinician on demand | **3.8 Flash function calling** | "ask the record" over read-only metric tools | on demand |
| nightly (sample) | **4 Argon judge** | grades 5 random synthetic scenarios per surface → drift alarm on the scorecard | 5–25 |

A **usage ledger** (`model_calls` table: ts, model, task, route, latency, ok, fallback — no content) feeds an
"Intelligence" card on `/health` and the submission: which Gemini models ran, how often, how fast, how often we
fell back.

## 3. Graph memory (the "knowledge graph", small and real)

SQLite `kg_nodes` / `kg_edges` (plan 04 §4) built by code from: confirmed memories (people, places, likes,
what_helps, plans), episodes (`did_on`, `went_to`), bandit outcomes (`helped`, weight = effect, evidence ids).
Entity linking/extraction proposals from Flash (structured) → applied by code. Recall = Gemini Embedding 2 search
over memory + node text → 1-hop expansion → rank → top 3 into the card and `ask_mind` answers.
Person-facing "Your constellation" (web + iPhone) shows people/places/activities that help — no health data.

## 4. Live context layer (T5) — Kaiku notices what's happening

Devices push short bracketed events into the open Live session from a fixed vocabulary:
`[drumming · lively]`, `[breathing · calmer heart]`, `[walk · 12 min · 2 green things]`, `[second person nearby]`,
`[it started raining]`. Produced by reflex code (hub perception, glasses IMU, phone), never raw numbers about
state. Lets Live react naturally ("ooh, lively today!"). Hub first, then iPhone/glasses.

## 5. Behaviour ↔ animation contract (all surfaces)

One table, `design/behaviour.md`, maps every runtime moment to a mascot state + motion + sound + haptic, and every
app implements it from that table: Talk listening/thinking/speaking (driven by the Live stream: input VAD →
`listening`, tool call in flight → `thinking`, audio out → `speaking`), `ask_mind` escalation → a slightly longer
"thinking" with a soft ear twitch, game end → `cheering`, after 23:00 → `sleepy`, ambient `cozy` on gentle days,
crisis → static. A QA pass (screenshots / screen recordings in the simulator + web) checks each row.

## 6. Decision needed from the team

**Session-end summaries:** to propose memories and graph edges automatically, the Live output/input transcription
of a session would be sent once to Gemini 3.8 Flash (in memory, never stored), and the person confirms each proposed
memory ("want me to remember that Maija is your sister?"). Same provider that already hears the audio; nothing
stored. Default if no answer: **off** — memories only via the in-conversation `remember` tool (works today).

## 7. Workstreams

| WS | Scope |
|---|---|
| **I4** cloud | ask_mind router + escalation + grounding; usage ledger + /health card data; graph tables + builder + Embedding 2 recall; nightly Argon consolidation + judge sample; weekly briefs; postcard endpoint (Nano Banana); budget caps; edge-case tests |
| **I5** hub | T5 live events + `ask_mind` handling + "thinking" body state during escalation |
| **QA** | behaviour.md + animation QA on web/iPhone/Mac after A2/A3 merge |
| web | "ask the record" panel, constellation, intelligence card (after I4) |
