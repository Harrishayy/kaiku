# AGENTS.md — rules for every coding agent (Claude Code, Codex, Gemini CLI, Cursor, Muse) and human

Kaiku helps people stay well at home after TMS depression treatment (Junction 2026, Aalto "Beyond the Clinic").
**Signal groups** — check-ins/robot, walks/outings, apps and optional wearable data — each give a verdict against
the person's own baseline; a **deterministic consensus engine** combines them on one clinician dashboard.
**The product in one paragraph:** people who have finished treatment collect data on devices they already live with
(phone, Mac, watch, glasses, a small robot). Kaiku accumulates it at home into one trusted record, and the
**intelligence layer** is the product: it turns every input into what it means for this person (went outside, kept
the morning ritual, slept short, sounded low in the evening reflection), answers them with real emotional
attunement (a sad thing gets a gentle, curious reply, never "ok, anyway"), and shows the practitioner what changed
and why, so staying well after treatment does not depend on expensive clinic visits. With the person's own switch,
the phone or Mac camera also counts how the face moves during a game or a check-in (smiles, blinks, range of
expression): numbers made on the device, never a picture and never an emotion label, shown beside the record and
not part of the consensus (D52). Every module exists to feed
or express that layer; a new robot signal is done only when Gemma's review can cite it.
Groups are not proof of independent connected devices: actual envelope source and capture provenance stay visible.
`docs/plans/` holds the plans in order (`01-foundation.md` done, `08-product-integration.md` current); this file is the condensed law. Every module folder has its own `AGENTS.md`.
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
| Look: colours, type, spacing, motion, mascot geometry + states | `design/tokens.json`, `design/mascot.spec.json`, `design/motion.md` | `design/mascot.svg`, `design/generated/` via `make design` |
| Every line Kaiku says (en/fi/sv) + the one voice | `config/voice_lines.toml` + `config/kaiku.toml [voice]` | audio cache via `GET /v1/voice/{key}` |
| Decisions and why | `docs/decisions.md` | — |
| Plan, story, schedule | `docs/plans/NN-*.md` (newest number = current; done plans are marked ✅ DONE, never rewritten) | — |
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
   Raw audio only to Gemini Live during an active, consented companion conversation. Robot camera, laptop webcam and the
   phone or Mac camera during activities are processed in memory, never stored or sent. The camera during activities
   (opt-in, off by default, D52) yields only counts of face movement per task (`obs.face_signs`); nothing anywhere
   stores an emotion label, and those counts are shown and citable, not scored. From those same numbers the device
   may notice a visible expression cue (D60: lower, tense or brighter for a while against the person's own level in
   that task); it is recorded as a count and may put one fixed, quiet context sentence in front of Kaiku in a check-in. One exception for pictures (D43): with the separate opt-in "Let Kaiku
   see through the glasses during walks" (off by default), about one glasses camera frame a second goes from the
   iPhone straight to that same Gemini Live conversation while it is open and unmuted; frames are never stored,
   logged or sent to the Kaiku cloud, and no observation is derived from them. Browser apps never hold the Gemini key.
   On the robot the head and the hub are one body in two boxes (D51): only while a consented conversation is open,
   the head's microphone audio crosses the home network to the hub as unstored PCM frames (`audio/head/mic`) on its
   way to that same Gemini Live conversation, and generated music and Kaiku's voice cross the other way
   (`audio/head/speaker`); these frames are never stored, logged, recorded by a bus tool or uplinked. A phone or Mac
   beside the robot can stand in for the head's microphone (D56): with the app's "Robot microphone" switch on (off by
   default) and only while the hub holds the robot's microphone open, the same kind of frames go from the app to the
   hub (`audio/phone/mic`), under the same rules.
6. **The consensus rule and the crisis path are deterministic.** No LLM decides a person's state or handles a
   crisis. Gemma explains the verdict and organises permitted companion knowledge (D35); Gemini Live uses
   the prepared context for conversation and calls the shared mind only when needed. See `docs/safety.md`.
7. **Config, not code,** for model IDs, endpoints, thresholds (`config/kaiku.toml`). Look model IDs up in current
   docs (geminiDocs MCP) — never guess. Placeholders are marked `VERIFY-`.
8. **Fail soft.** Timeouts + retry with backoff on every network call; every node heartbeats on `health/<node>`.
   A dead node, broker or cloud never crashes another node. A missing source makes the consensus say
   **"insufficient"**, never "stable".
9. **Small, testable, logged.** JSON logs via `kaiku_contracts.jlog`. Unit tests for logic, contract tests for
   every message a module emits. Never log secrets, audio, images, transcripts.
10. **Don't overengineer; visible results first.** Smallest end-to-end slice that works, then depth. If it isn't in
    the demo path (`docs/plans/04-mind-depth.md` → Scope guard), it's STRETCH.
11. **Hackathon rules.** All code written during the event. MIT. No pre-event code for this idea.

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
| cloud | [`cloud/`](cloud/AGENTS.md) | C | service | no | Modal app: ingest, SQLite, baselines, per-source verdicts, consensus v1, bandit, Gemma reasoning and graph organisation, simulation, web hosting |
| web | [`apps/web/`](apps/web/AGENTS.md) | D | app | yes | Next.js practitioner dashboard (one viewport, movable panels): consensus, trends, Gemma review and agent trace, knowledge graph, routine, evidence, care actions, ask, coverage; team health/eval/tune/debug day |
| glasses-webapp | [`apps/glasses-webapp/`](apps/glasses-webapp/AGENTS.md) | D | app | yes | Meta Ray-Ban Display web app: walk companion, reminder card, breathing guide, WebMCP tools |
| glasses-dat-android | [`apps/glasses-dat-android/`](apps/glasses-dat-android/AGENTS.md) | D | app | yes | Optional DAT camera app: daylight minutes on walks |
| apple | [`apps/apple/`](apps/apple/AGENTS.md) | A | app | yes | SwiftUI iPhone + Mac apps (KaikuKit): Today, Play (games), Talk, History (your own numbers by day and week, with Your days), Kaiku bot (the home robot's bus, live, read-only), You; mascot, offline queue, crisis; iPhone: notifications, Live Activities, widget, Siri, HealthKit, glasses walk |
| atech-head | [`firmware/atech-head/`](firmware/atech-head/AGENTS.md) | A | firmware | yes | Atech board: display eyes, knob ear dial, lid button, pan motor (power-on home, optional hall), speaker, taps from the orientation sensor (standalone); standalone ritual or MQTT firmware (D44); MQTT on the LAN |
| unoq-sensors | [`firmware/unoq-sensors/`](firmware/unoq-sensors/AGENTS.md) | A | firmware | yes | UNO Q: buzzer chimes, camera (faces, distance, room light, pulse); KY-031 knock, KY-039/KY-053, KY-035 hall and KY-054 light not fitted (D35, D54, D55) |
| friendlink | [`firmware/friendlink/`](firmware/friendlink/AGENTS.md) | A | firmware | yes | LoRa gateway + friend's lamp (serial to the hub's lora_serial adapter) |
| sim | [`sim/`](sim/AGENTS.md) | C | harness | yes | Twins of every hardware node + glasses/laptop/phone sources; synthetic patients; cloud seeder |
| tools | [`tools/`](tools/AGENTS.md) | B | harness | yes | bus tail / record / replay, local API discovery, doctor, agents sync checker, electronics bench checker, companion evals (persona/wording/safety scorecard) |
| config | [`config/`](config/AGENTS.md) | all | docs | no | criteria.toml (how each data input decides state), kaiku.toml (settings), persona.md + surfaces.toml (who Kaiku is, per body), voice lines, safety phrases, mosquitto.conf |
| design | [`design/`](design/AGENTS.md) | D | library | no | Look ground truth: tokens.json, mascot.spec.json (+ generated mascot.svg, tokens.css, Tokens.swift), motion.md |
| hardware | [`hardware/`](hardware/AGENTS.md) | A | docs | yes | CAD (with provenance), wiring, BOM |
| demo | [`demo/`](demo/AGENTS.md) | D | docs | yes | Live demo script, video shot list, reset script |
| docs | [`docs/`](docs/AGENTS.md) | all | docs | no | Progress log, decisions, safety, privacy, tracks, validation, submission text, templates |

<!-- END MODULE INDEX -->

## Message conventions (details: `contracts/AGENTS.md`)
- Envelope `{v, id (UUIDv7), ts (UTC ms Z), home_id, source, type, payload, quality?, sim}`;
  sources `head | sensors | hub | friendlink | glasses | laptop | phone | cloud | sim`.
- `type` is fully qualified and decides the topic: `obs.drum_session` → `kaiku/v1/<home>/obs/drum_session`,
  `raw.head.tap` → `.../raw/head/tap`, `cmd.head` → `.../cmd/head`, `health` → `.../health/<source>`.
- Robot nodes use MQTT via `Bus.publish(type, payload)` (validates). Glasses, laptop/Mac and phone apps
  `POST /v1/events` directly with the same envelope. Sims set `sim=true`; `source` stays the real node name.

## Commands (all in the Makefile — `make help`)
`make setup` · `make broker` · `make sim [NODES=head,sensors,friendlink,glasses,laptop]` · `make hub` ·
`make tail TOPIC=...` · `make record` / `make replay FILE=` · `make cloud-local` · `make seed` · `make web` ·
`make test` · `make check` · `make doctor` · `make contracts` · `make agents` · `make criteria` · `make tune` ·
`make cloud-deploy` · `make voice-prerender` · `make demo-reset` · `make design` · `make eval-companion [DRY=1]` ·
`make e2e-intelligence` (real model calls: Live, TTS, mind, graph) · `make drum-music [SPEAKER=1]` (real Lyria
RealTime through a whole ritual with simulated taps) · `make tap-back [BEAT=1]` (the Tap it back game with real Lyria through the head twin) ·
`make head-voice` (one real Live exchange through the head's speaker and microphone, no sound device) · head firmware: `make atech-setup`, `make atech-standalone [FLASH=1]`,
`make atech-mqtt [FLASH=1]`, `make atech-bench PART=<bench folder>`, `make head-audio ARGS='bench --host <broker>'`
(the head's speaker and microphone over MQTT, no hub, no model), `make head-audio-test` (its audio logic on this computer)

## Tech rules
- Python ≥ 3.11 via **uv** only (`uv add --package <member> <dep>`; uv workspace: `contracts/python`, `hub`,
  `cloud`). Async MQTT = `aiomqtt`. Pydantic v2.
- Google: `google-genai` (Python) / `@google/genai` (TS). **Never** the legacy `google-generativeai`.
- Web apps are **Next.js** (App Router, TS, static export) served by the Modal cloud from one URL. Client-side
  fetching only; dynamic pages use query params (`/clinician/patient/?id=`), not `[id]` segments.
- Modal: one warm ASGI container (single SQLite writer). Check current Modal docs for parameter names.
- **English first.** Every surface must work fully in English before any fi/sv work; untranslated or draft
  fi/sv copy never blocks or delays an English fix.
- **Who uses what.** The website is the practitioner dashboard only (one viewport, panels). Everything the person
  does (onboarding, Today, Play, Talk, walks, History) lives in the iPhone/Mac apps and on the robot.
- **Show the intelligence.** A practitioner must be able to see what Gemma concluded and why (review, cited
  evidence, agent trace, knowledge graph, routine, period comparison): `GET /v1/patients/{id}/insight`.
- **Real over plausible.** No hand-written model output, no hard-coded patient data in a UI, no claim in docs or
  copy that the code or a physical test has not shown. Seeded records go through the real routes and rules.
- Wording in UI/explanations: "change from your usual", "worth a check-in", "consensus", "needs a call".
  Never "diagnosis", "relapse detected", "predicts relapse". Drum = "inspired by research on improvisational
  music therapy". Tap it back is a rhythm game, not a test: its words are "perfect / great / nice / not quite", never a score. Robot light is not light therapy. Kaiku "can see" only during a walk with "Let Kaiku see" on and frames flowing (the walk screen shows it); everywhere
  else the glasses are a voice in the ear and never "see".
  Face signs (D52): say "face signs", "movements of the face", "shown, not scored"; never "emotion detected" or
  "looked sad", and Kaiku never says it saw the person's face.
  Visible expression cues (D60): say "visible sign: lower / tense / brighter expression", "a reason to ask, not a
  finding"; never "sad", never a feeling named for the person.

## Don'ts
- Don't edit another module's folder; leave its owner a `Broken/blocked` line in `docs/progress.md`.
- Don't commit `.env`, recordings with personal data, model weights, or `node_modules`.
- Don't hand-edit generated files (`contracts/schemas/`, `contracts/ts/`, the module index above).
- Don't add an AI co-author trailer to commits.
