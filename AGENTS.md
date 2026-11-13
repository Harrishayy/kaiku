# AGENTS.md — rules for every coding agent (Claude Code, Codex, Gemini CLI, Cursor, Muse) and human

Kaiku helps people stay well at home after TMS depression treatment (Junction 2026, Aalto "Beyond the Clinic").
**Three independent sources** — home robot, Meta glasses, laptop apps — each give a verdict about the person's
state against their own baseline; a **deterministic consensus engine** combines them on one clinician dashboard.
`handoff.md` is the full plan; this file is the condensed law. Every module folder has its own `AGENTS.md`.
**Public MIT repo: never write API keys, tokens, Wi-Fi passwords or credit codes into any file.**

## Start here (in order)
1. Read this file, then the `AGENTS.md` of the module you will touch. **`AGENTS.md` is the only context file**:
   Claude Code (≥ 2.1.281) loads it natively, nested ones when it opens files in that folder; Gemini CLI via
   `.gemini/settings.json`; Codex and Cursor natively (Codex only loads root → launch dir, so open the module's
   `AGENTS.md` yourself). Never add `CLAUDE.md`/`GEMINI.md` (a `CLAUDE.md` stops Claude Code reading `AGENTS.md`).
2. Read the last ~10 entries of `docs/progress.md` (who owns what, what's broken).
3. `make setup && make doctor` — fix every ❌ before writing code.
4. Work only inside ONE module folder + its tests.
5. Before you stop: `make check` (lint + all tests + agents sync), run your module against the sims, update the
   ground-truth files you affected (table below), append an entry to `docs/progress.md`.

## Ground truth — where each fact lives (edit THERE, nowhere else)

| Fact | Ground truth | Generated / derived (never hand-edit) |
|---|---|---|
| Message types, payload fields, API shapes | `contracts/python/kaiku_contracts/` (`payloads.py`, `api.py`, `registry.py`) | `contracts/schemas/`, `contracts/ts/` via `make contracts` |
| Which obs type counts toward which source | `contracts/python/kaiku_contracts/sources.py` | `contracts/schemas/sources.json`, TS `SOURCE_OF` |
| Which modules exist, what each emits/consumes | `modules.toml` | module index below, via `make agents` |
| Everything about a module: purpose, interfaces, map, extension points, invariants, how to run/test | `<module>/AGENTS.md` (the module's only doc) | — |
| **How each data input decides state** (metrics, directions, weights, thresholds, source votes, state rule) | **`config/criteria.toml`** (validated by `kaiku_contracts/criteria.py`; tune via `make criteria`, `make tune`, `/tune/`) | rule version `consensus-v1+<hash>` |
| Model IDs, timings, perception thresholds, ports | `config/kaiku.toml` (+ env `KAIKU_<SECTION>_<KEY>`) | — |
| Crisis phrases + scripted message | `config/safety_phrases.toml` | — |
| Decisions and why | `docs/decisions.md` | — |
| Plan, story, schedule | `handoff.md` | — |
| What happened | `docs/progress.md` (append-only) | — |

**Sync rule (non-negotiable):** a change is not done until the ground truth that describes it is updated in the
same commit. Changed a module's interface → its `AGENTS.md` + `modules.toml`. Changed a message →
contracts + `make contracts` + every producer/consumer + sims. Changed a cross-cutting rule → this file. Never copy
facts between files — link to the ground truth instead. `make test` fails when generated files or the module
index are stale, when a module lacks its `AGENTS.md` sections or grows a README/CLAUDE/GEMINI file, or when an obs type has no producer or consumer.

## Golden rules
1. **Contracts are law.** Modules talk only via messages in `contracts/` (MQTT at home, HTTPS to the cloud).
   No module imports another module. The only shared Python package is `kaiku_contracts`
   (models, topics, `Bus`, config, JSON logging, source map). `sim/` and `tools/` are dev harnesses and may import.
2. **Every module runs alone** with a sim/mock mode and "Run standalone" instructions in its `AGENTS.md`.
3. **Adapters at the edges.** Vendor/device code lives in an adapter that converts to/from contract messages.
   New hardware or vendor = new adapter selected by config, nothing else changes.
4. **Contract changes are explicit:** edit the pydantic models, add an example in `registry.py`, map new obs types
   in `sources.py`, run `make contracts`, update producers/consumers/sims, note it in `docs/progress.md`.
   Breaking change → bump `SCHEMA_VERSION`.
5. **No raw media leaves the device that captured it.** Only `obs.*` is uplinked (the cloud rejects anything else).
   Raw audio only to Gemini Live during a consented robot conversation. Robot camera and laptop webcam are
   processed in memory, never stored or sent. Browser apps never hold the Gemini key.
6. **The consensus rule and the crisis path are deterministic.** No LLM decides a person's state or handles a
   crisis. Gemma only explains. See `docs/safety.md`.
7. **Config, not code,** for model IDs, endpoints, thresholds (`config/kaiku.toml`). Look model IDs up in current
   docs (geminiDocs MCP) — never guess. Placeholders are marked `VERIFY-`.
8. **Fail soft.** Timeouts + retry with backoff on every network call; every node heartbeats on `health/<node>`.
   A dead node, broker or cloud never crashes another node. A missing source makes the consensus say
   **"insufficient"**, never "stable".
9. **Small, testable, logged.** JSON logs via `kaiku_contracts.jlog`. Unit tests for logic, contract tests for
   every message a module emits. Never log secrets, audio, images, transcripts.
10. **Hackathon rules.** All code written during the event. MIT. No pre-event code for this idea.

## Adding / removing components
- **New module** (e.g. a 4th source, a new app): copy `docs/templates/module/AGENTS.template.md` into the new folder as `AGENTS.md`, fill it in,
  add a `[[module]]` entry to `modules.toml`, `make agents`, `make test`.
- **New signal from existing data:** add a `[[metric]]` block to `config/criteria.toml`. No code.
- **New consensus source:** add it in `sources.py` (+ map its obs types), a `[sources.<name>]` block + its
  `[[metric]]`s in `config/criteria.toml`, and a sim twin. The cloud's verdict/consensus code is source-agnostic.
- **New device/vendor:** a new adapter in the module that owns that edge (e.g. `hub/kaiku_hub/devices/`), selected
  by an env/config switch; give it a sim twin.
- **Remove anything:** delete the folder + its `modules.toml` entry, `make agents && make test`. Because nothing
  imports another module, the only breakage possible is message flow, which the checker reports.

## Module index
<!-- BEGIN MODULE INDEX (generated by `make agents` from modules.toml; do not edit by hand) -->

| module | path | owner | kind | removable | what |
|---|---|---|---|---|---|
| contracts | [`contracts/`](contracts/AGENTS.md) | all | library | no | Message envelope, payloads, topics, API models, consensus source map; shared Bus/config/jlog |
| hub | [`hub/`](hub/AGENTS.md) | B | node | no | Robot orchestrator: perception, ritual state machine, safety gate, Gemini Live / Lyria adapters, uplink |
| cloud | [`cloud/`](cloud/AGENTS.md) | C | service | no | Modal app: ingest, SQLite, baselines, per-source verdicts, consensus v1, bandit, Gemma explanations, simulation, web hosting |
| web | [`apps/web/`](apps/web/AGENTS.md) | D | app | yes | Next.js static export: clinician dashboard, /me, laptop /session, /phq9, /consent, /live, /health, /eval, /tune |
| glasses-webapp | [`apps/glasses-webapp/`](apps/glasses-webapp/AGENTS.md) | D | app | yes | Meta Ray-Ban Display web app: walk companion, reminder card, breathing guide, WebMCP tools |
| glasses-dat-android | [`apps/glasses-dat-android/`](apps/glasses-dat-android/AGENTS.md) | D | app | yes | Optional DAT camera app: daylight minutes on walks |
| atech-head | [`firmware/atech-head/`](firmware/atech-head/AGENTS.md) | A | firmware | yes | Head: eyes, IMU taps, ear encoder, pan motor, chest LEDs, purr |
| unoq-sensors | [`firmware/unoq-sensors/`](firmware/unoq-sensors/AGENTS.md) | A | firmware | yes | UNO Q: PPG, distance, light, hall, top button |
| friendlink | [`firmware/friendlink/`](firmware/friendlink/AGENTS.md) | A | firmware | yes | LoRa gateway + friend's lamp (serial to the hub's lora_serial adapter) |
| sim | [`sim/`](sim/AGENTS.md) | C | harness | yes | Twins of every hardware node + glasses/laptop sources; synthetic patients; cloud seeder |
| tools | [`tools/`](tools/AGENTS.md) | B | harness | yes | bus tail / record / replay, doctor, agents sync checker |
| config | [`config/`](config/AGENTS.md) | all | docs | no | criteria.toml (how each data input decides state), kaiku.toml (settings), safety phrases, mosquitto.conf |
| hardware | [`hardware/`](hardware/AGENTS.md) | A | docs | yes | CAD (with provenance), wiring, BOM |
| demo | [`demo/`](demo/AGENTS.md) | D | docs | yes | Live demo script, video shot list, reset script |
| docs | [`docs/`](docs/AGENTS.md) | all | docs | no | Progress log, decisions, safety, privacy, tracks, validation, submission text, templates |

<!-- END MODULE INDEX -->

## Message conventions (details: `contracts/AGENTS.md`)
- Envelope `{v, id (UUIDv7), ts (UTC ms Z), home_id, source, type, payload, quality?, sim}`;
  sources `head | sensors | hub | friendlink | glasses | laptop | cloud | sim`.
- `type` is fully qualified and decides the topic: `obs.drum_session` → `kaiku/v1/<home>/obs/drum_session`,
  `raw.head.tap` → `.../raw/head/tap`, `cmd.head` → `.../cmd/head`, `health` → `.../health/<source>`.
- Robot nodes use MQTT via `Bus.publish(type, payload)` (validates). Glasses and laptop apps `POST /v1/events`
  directly with the same envelope. Sims set `sim=true`; `source` stays the real node name.

## Commands (all in the Makefile — `make help`)
`make setup` · `make broker` · `make sim [NODES=head,sensors,friendlink,glasses,laptop]` · `make hub` ·
`make tail TOPIC=...` · `make record` / `make replay FILE=` · `make cloud-local` · `make seed` · `make web` ·
`make test` · `make check` · `make doctor` · `make contracts` · `make agents` · `make criteria` · `make tune` ·
`make cloud-deploy` · `make demo-reset`

## Tech rules
- Python ≥ 3.11 via **uv** only (`uv add --package <member> <dep>`; uv workspace: `contracts/python`, `hub`,
  `cloud`). Async MQTT = `aiomqtt`. Pydantic v2.
- Google: `google-genai` (Python) / `@google/genai` (TS). **Never** the legacy `google-generativeai`.
- Web apps are **Next.js** (App Router, TS, static export) served by the Modal cloud from one URL. Client-side
  fetching only; dynamic pages use query params (`/clinician/patient/?id=`), not `[id]` segments.
- Modal: one warm ASGI container (single SQLite writer). Check current Modal docs for parameter names.
- Wording in UI/explanations: "change from your usual", "worth a check-in", "consensus", "needs a call".
  Never "diagnosis", "relapse detected", "predicts relapse". Drum = "inspired by research on improvisational
  music therapy". Robot light is not light therapy. Glasses don't "see" unless the DAT camera app exists.

## Don'ts
- Don't edit another module's folder; leave its owner a `Broken/blocked` line in `docs/progress.md`.
- Don't commit `.env`, recordings with personal data, model weights, or `node_modules`.
- Don't hand-edit generated files (`contracts/schemas/`, `contracts/ts/`, the module index above).
- Don't add an AI co-author trailer to commits.
