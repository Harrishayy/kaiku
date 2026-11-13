# Progress log (APPEND-ONLY)

Newest at the bottom. Never edit or delete old entries. One entry per work session, per module.

```
## 2026-11-14 03:40 — <agent or person> — <module>
- Did: <what changed, files>
- Verified: <tests run, sim/hardware checks>
- Contract changes: <none | details + version>
- Broken/blocked: <what, why>
- Next: <the next concrete step>
```

## Owners
A hardware/firmware · B hub/live · C cloud/ML/sim · D apps/demo/story (fill in names on the board).

---

## 2026-11-13 23:30 — Claude Code (setup agent) — all (Phase 0 + walking skeleton)
- Did: repo layout, AGENTS.md/CLAUDE.md/GEMINI.md, .mcp.json, Makefile, config/, contracts (pydantic → schemas + TS, shared Bus/config/jlog), sim nodes + keyboard, tools (tail/record/replay/doctor), hub (perception, ritual state machine, safety gate, uplink, cloud link, live adapters), cloud (FastAPI, SQLite, baselines/drift/corroboration/bandit, template + Gemma briefs, cohort eval, Modal app), apps/web (Next.js static export), docs, module READMEs, handoff.md updated (§16 quickstart).
- Verified: `make check` (ruff + 127 pytest incl. real-mosquitto integration); web typecheck + build + headless-browser check; end-to-end broker + cloud-local + seed + sims + hub: full ritual (greet→close), all obs uplinked, Aino amber / 7 others green, no errors in any log.
- Contract changes: initial v1. `type` fully qualified (D11). Added cmd.hub `start_ritual`/`say`; API models LiveEventsResponse, NodeHealthReport, HealthOverview.
- Broken/blocked: not deployed to Modal yet; Gemini Live / Lyria / vLLM paths untested against real services; all model IDs in config/kaiku.toml are `VERIFY-` placeholders; Atech adapter + camera are stubs pending spikes.
- Next: A — Atech + UNO Q spikes. B — verify Gemini Live/Lyria model IDs, live voice. C — `modal setup`, `make cloud-deploy`, Gemma serving. D — submit draft, book glasses, polish web, start glasses web app.

## 2026-11-14 00:30 — Claude Code (setup agent) — all (v2 migration, criteria, agent context)
- Did: v2 three-source consensus end to end (contracts v2 + `sources.py`; hub v2 ritual: dial ×3, before/after scores, spoken PHQ-9, phq9_due; glasses + laptop HTTPS twins; cloud consensus v1, live criteria override/preview, simulation with ablation; web /session /phq9 /me /consent /tune). Consensus criteria moved to `config/criteria.toml` (D19) with the first tuning pass (D20). One context file per module: `AGENTS.md` only, READMEs folded in, CLAUDE/GEMINI pointers removed, `.gemini/settings.json` (D21). `modules.toml` + `tools/agents_sync.py` enforce module docs, message flows and criteria producers.
- Verified: `make check` (lint + all Python tests incl. real-broker integration), web typecheck/test/build (13 routes), headless browser runs (web worker), full live run with pairing token on: 8 demo patients in intended states, live v2 ritual, 401 without token, live criteria preview.
- Contract changes: v2 types (see D17), `api.Criteria*`, criteria schema. Still `v: 1` (nothing deployed).
- Broken/blocked: nothing deployed to Modal; Gemini Live / Lyria / vLLM untested against real services; model IDs are `VERIFY-`; real-face expressivity untested; D20 lead-time vs precision trade-off needs a team decision; repo is private.
- Next: A — Atech/UNO Q spikes. B — real Gemini Live + Lyria. C — `modal deploy`, Gemma serving, tune with tester data. D — glasses web app, demo script, submission text (`docs/submission.md`).

## 2026-11-14 08:30 — Claude Code (workstream D) — design
- Did: new `design/` module (plan 02 §2–§3, D22–D23). Ground truth: `tokens.json` (paper/ink/clay/sage/sky/honey, warm-charcoal dark, crisis red only for crisis, glow-by-hour stops, radii, spacing, type Fredoka/Nunito/DM Mono + SF Pro Rounded, motion durations/easings/springs/blink/breath), `mascot.spec.json` (direction A "Pebble": named parts, pivots, clips, 10 states as pose + keyframe tracks + events, interactions, ambient-mood map, robot eye crop), `motion.md`. `gen.py` (stdlib) generates `mascot.svg`, `generated/tokens.css`, `generated/Tokens.swift` (`KaikuTokens`, swiftc-typechecked). `make design`; `design/tests` (freshness, named parts, spec consistency, AA contrast, motion budget) added to pytest testpaths; `modules.toml` + root AGENTS.md ground-truth row.
- Design artifact: https://claude.ai/artifact/BPXa6itqswDUpfzsdRE1MV (3 directions, all states animated from the spec, Reduce Motion toggle, tokens, Today / Weather check / Firefly / Breathe / Your days / Crisis, Dynamic Island + Lock Screen, Mac notch 01:10 + menu bar, receipt, /me, /clinician). Private until shared from its Share menu.
- Verified: `make check` green (220 passed), `gen.py --check` clean, artifact rendered in headless Chrome.
- Contract changes: none.
- Broken/blocked: none. Web/Apple have not adopted the tokens yet (their workstreams).
- Next: W imports `design/generated/tokens.css` + renders `mascot.svg` from the spec; A1 bundles `mascot.spec.json` + `Tokens.swift` in KaikuKit.

## 2026-11-14 — Claude Code (workstream I2) — config + tools (persona + companion evals)
- Did: `config/persona.md` (character bible, hard limits, hand-offs, en/fi/sv notes, 10 good/bad examples tagged with linter codes) and `config/surfaces.toml` (robot/glasses/iphone/mac/web: body, tools, activities, word/sentence caps, proactive limits, rules). `tools/companion_evals/`: `assemble.py` (reference system-instruction builder for the cloud; context card rejects state/score/wearable keys), `wording.py` (stdlib-only linter, incl. team decision "never mention watch/sleep data"), `safety.py` (hub gate duplicate + parity test), `tool_specs.py`, `run.py` (`--dry` canned replies; real mode person/Kaiku = gemini-3.8-flash text stand-in, judge = gemini-4-argon, IDs checked in Gemini docs, overridable by flag/env), 25 scenarios (morning_ritual, weather_check, walk_companion, breathe, look_up/hand-off, watch data, crisis en/fi/sv). `make eval-companion [DRY=1]`. PyYAML added to the root dev group.
- Verified: `make check`; dry run 25/25 pass (persona+<sha8> in scorecard); tests prove the linter flags every Bad persona example and the gate fires before any model call. No real pass yet (no key in this environment).
- Contract changes: none. `tool_specs.py` is a stand-in until `kaiku_contracts/companion_tools.py` (I1) lands; it is preferred automatically.
- Broken/blocked: none. I1 should port `assemble.py` + `wording.py` (copy verbatim to `kaiku_contracts/wording.py`) and keep the card key rules.
- Next: real pass with a key (`make eval-companion ARGS="--limit 5"`), add scenarios for remaining skills, record results in `docs/validation.md`.

## 2026-11-14 10:00 — Claude Code (workstream B) — contracts, cloud, sim, config (plan 02 §10)
- Did: plan-02 contract changes end to end. Contracts: envelope source `phone`; `SelfReport.channel`; `Outing`
  `dat_imu` + `cadence_spm`/`gait_regularity`/`head_up_ratio`; new `obs.screen_activity`, `obs.play_session`,
  `obs.wearable_daily`; 4th consensus source `wearable` + `SOURCE_LABELS` (laptop = "Apps"); `MeResponse.mascot`,
  `highlights`, `garden`; `VoiceLinesResponse`; criteria nested fields + `person_hard`. Cloud: `companion.py`
  (mascot/highlights/garden), `voice.py` + `GET /v1/voice`, `GET /v1/voice/{line_key}` (Gemini TTS
  `gemini-3.8-flash-tts`, voice `Sulafat`, disk cache, 503 + hint without a key), `make voice-prerender`,
  `google-genai` dep, template labels for 4 sources. Config: `[sources.wearable]` + 11 half-weight metrics (D29),
  `config/voice_lines.toml` (33 lines en/fi/sv), `kaiku.toml [voice]` + verified model IDs in `[models]`. Sims:
  laptop twin posts screen_activity + firefly, new `phone_sim` (watch summary, weather check, firefly, `--no-watch`),
  glasses twin posts the extended outing; synth: 4th source, Aino drifts robot+apps+watch with a sub-threshold
  cadence dip, Eero has no watch, 3 new eval scenarios (second RNG keeps plan-01 events/ids identical).
  Tools: `modules.toml [planned_producers]` lets the checker accept obs types whose real producer (apps/apple) is
  still being built; it fails once a real module emits them.
- Verified: `make check` green (lint + 233 tests); `make tune` (D29: needs_call P 0.97 / R 0.90, 0.03 false per
  patient-month, lead 6 d); local cloud + `make seed`: all 8 demo patients in intended states; `/v1/me?home_id=demo-aino`
  → mascot cozy/`needs_call.offer`, good + gentle hard highlights, garden 42 plants; `/v1/voice` 503 + hint without a key.
- Contract changes: additive (see above + `contracts/AGENTS.md`); `SCHEMA_VERSION` unchanged (nothing deployed).
- Broken/blocked: hub (owner B/live) doesn't pass `[voice].name` to Gemini Live yet, so the robot's voice may differ
  from the apps' until it does. `/v1/voice` not yet exercised against the real TTS API (no key here). fi/sv voice lines
  need a native-speaker read. Web `lib/format.ts` still labels `laptop` "Laptop" and has no `wearable` label (W: use
  `SOURCE_LABELS` from `contracts/ts`).
- Next: A1/A2/A3 + W build against these types and the local cloud; remove `[planned_producers]` lines as each real
  producer lands; pre-render voice once a key is set; decide wearable weights with tester data.
