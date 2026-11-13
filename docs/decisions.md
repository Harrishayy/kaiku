# Decisions (ADR-style)

Format: `## D<n> — <title> (<date>, <who>)` · Decision · Why · Alternatives. Open questions D1–D9 and
their defaults are in docs/plans/01-foundation.md §12 — record the actual answer here when it's made.

## D10 — Pydantic models are the contract source of truth (2026-11-13)
- Decision: author contracts in `contracts/python/kaiku_contracts/` (pydantic v2); generate JSON Schema +
  TS with `make contracts`; a test fails when generated files are stale.
- Why: one place to edit, impossible for schema and code to drift; still gives non-Python modules schemas.
- Alternatives: hand-written JSON Schema + datamodel-codegen (two steps, drift-prone).

## D11 — Fully-qualified message `type` decides the topic (2026-11-13)
- Decision: `type` is `obs.<name>`, `raw.<source>.<stream>`, `cmd.<target>`, `health`, `log`.
- Why: unambiguous validation without the topic, and sims can publish `raw/head/*` while flagged `sim: true`.

## D12 — Shared kit lives in kaiku_contracts (2026-11-13)
- Decision: `Bus` (MQTT), config loader and JSON logging live in `kaiku_contracts`, the one package all
  modules may import. `sim/` and `tools/` are dev harnesses and may import modules.

## D13 — Web apps use Next.js static export (2026-11-13, team request)
- Decision: `apps/web` (and the glasses web app) are Next.js App Router + TS with `output: 'export'`,
  served as static files by the Modal FastAPI app (single public URL; Modal stays central for judging).
- Consequences: no server components fetching at request time, no API routes, dynamic pages via query
  params (`/clinician/patient/?id=aino`).

## D14 — Mosquitto broker on the hub laptop, anonymous on the demo LAN (2026-11-13)
- Decision: `config/mosquitto.conf` allows anonymous on :1883; switch to a password file for the demo
  hotspot if anyone else can join it.

## D15 — Glasses source turns "worse" on one drifting metric (2026-11-13)
- Decision: `[consensus.sources.glasses] worse_min_metrics = 1` (robot 2, laptop 1).
- Why: the glasses only measure outing minutes (+ steps), which are strongly correlated; requiring 2 would mean
  the glasses could never vote "worse". Tune with the simulation; change = new `rule_version`.

## D16 — Browser apps authenticate with a pairing link (2026-11-13)
- Decision: when `KAIKU_HOME_TOKEN` is set, every `POST /v1/events` needs `Authorization: Bearer <token>`. The
  laptop/glasses apps get it once via `?home=<id>&t=<token>` and keep it in localStorage. No Gemini or admin key
  ever reaches a browser.
- Alternatives: unauthenticated browser sources (v1 demo shortcut, removed); per-device OAuth (no time).

## D17 — v2: three-source consensus, name stays Kaiku (2026-11-13)
- Decision: adopt the v2 plan (robot, glasses, laptop → per-source verdicts → deterministic consensus v1 with
  states stable / watch / needs_call / safety) but keep the name Kaiku everywhere (packages, topics, env, docs).
- Contract changes: `obs.self_report` replaces `obs.mood_dial`; `obs.phq9` replaces `obs.checkin`; new
  `obs.laptop_session`, `obs.intervention_response`; `obs.outing`/`obs.nudge_outcome`/`obs.speech_features`
  reshaped; envelope source `laptop` replaces `checkin`; `cmd.hub.phq9_due`; API status → consensus. Still `v: 1`
  (nothing was deployed or stored yet).

## D18 — Module registry + per-module AGENTS.md as agent ground truth (2026-11-13)
- Decision: `modules.toml` lists every module and its message flows; every module folder carries
  `AGENTS.md` (+ `CLAUDE.md`, `GEMINI.md` pointers); `tools/agents_sync.py` enforces it in `make test`.
- Why: any agent (Claude Code, Codex, Gemini CLI, Cursor) gets the same module context on entry, and drift
  between code and docs fails the build instead of silently confusing the next agent.

## D19 — Consensus criteria are data, not code (2026-11-13, team request)
- Decision: every parameter that decides how a data input is used (metric definition, filter, daily aggregation,
  worse direction, weight, enabled, per-metric thresholds; source vote settings; state combination; direct rules
  such as PHQ-9) lives in `config/criteria.toml`, validated by `kaiku_contracts/criteria.py`. Rule version =
  `<name>+<hash>`, so every tuning is traceable. Live override + preview on the cloud (`/tune/`), offline
  comparison with `make tune`.
- Why: the criteria will change constantly during the hackathon; tuning must not need code changes or deploys,
  and a bad edit must fail validation with a readable message instead of silently changing behaviour.

## D20 — First criteria tuning pass (2026-11-13, simulation, 40 synthetic patients)
- Change: glasses `outing_min`/`steps` `missing = "skip"` (was "zero"); robot `worse_min_weight = 2.5` (was 2.0).
- Why: counting walk-free days as 0 minutes made the glasses source "worse" on ordinary quiet days (most false alarms).
- Current numbers (`make tune`, `consensus-v1+4936eb40`, cohort incl. a glasses+laptop-only drift scenario):
  needs_call precision 1.00, recall 0.76, false needs_call 0.00 per patient-month, **median lead time 2.0 days**.
- The open trade-off (same cohort) — pick consciously, re-run `make tune` after changing:

  | variant | needs_call precision | recall | false / patient-month | lead (days) |
  |---|---|---|---|---|
  | robot 2.5 (current) | 1.00 | 0.76 | 0.00 | 2.0 |
  | robot 2.0 | 0.90 | 0.76 | 0.06 | 2.0 |
  | robot 2.0 + z 1.75 | 0.98 | 0.61 | 0.03 | 3.5 |
  | robot 2.5 + drift 2 of 4 days | 0.69 | 0.88 | 0.25 | 4.5 |

  Earlier calls cost false alarms; the clinical story ("caught early, a booster can rescue it") argues for lead
  time, the "no extra clinician workload" story for precision. Decide with mentors (Phase 4).
- Caveat: synthetic patients from our own generator — this tunes the rule against our assumptions, not real
  people. Re-tune once tester data exists; record each pass as a new D-entry.

## D21 — One context file: AGENTS.md (2026-11-13, team request; supersedes the pointer files in D18)
- Decision: each module has exactly one doc, `AGENTS.md` (module README content folded in, one section per fact).
  No `CLAUDE.md`, `GEMINI.md` or module `README.md` anywhere; the root `README.md` stays as the public project page.
- How each tool finds it: Claude Code ≥ 2.1.281 reads `AGENTS.md` natively (root at start, nested when it opens
  files in that folder) — but only when no `CLAUDE.md` exists, so a `CLAUDE.md` would actively break it. Gemini CLI:
  `.gemini/settings.json` `context.fileName = ["AGENTS.md"]`. Codex reads root → launch directory (open the module's
  `AGENTS.md` when launched at the root). Cursor: reads `AGENTS.md`; nested loading unverified.
- Enforced by `tools/agents_sync.py` in `make test`.

## D22 — One companion character, Kaiku, on every surface (2026-11-14, team request)
- The mascot is the robot's own face (eyes, single ear, chest glow), drawn from one spec in `design/`. Transient
  states are local to each interaction; the ambient mood comes from the cloud as a pure function of state and
  never looks sad or worried at the person. Details: `docs/plans/02-companion-apps.md` §2.

## D23 — Design direction: warm, simple, quiet (2026-11-14)
- Cream / ink-brown / clay accent / sage / sky, rounded type, no red outside the crisis screen, Reduce Motion respected.
  Tokens live in `design/tokens.json`; CSS and Swift are generated from it.

## D24 — Native SwiftUI multiplatform app for iPhone + Mac; cloud SQLite stays the one database (2026-11-14)
- Why native, not a web wrapper: the Meta DAT SDK (glasses camera/mic/IMU/speech), HealthKit (watch data),
  ActivityKit (Dynamic Island) and macOS frontmost-app sensing are native-only. One XcodeGen project with a
  shared `KaikuKit` package keeps iPhone and Mac identical. Sync = every device pairs to the same `home_id`.

## D25 — Fourth, optional consensus source `wearable` (2026-11-14)
- HealthKit daily summary (sleep, resting HR, HRV, steps) from Apple Watch or any watch writing to Apple Health.
  Optional: a missing source is "insufficient" and simply not counted, so people without a watch lose nothing.

## D26 — Laptop usage rhythm, not content (2026-11-14, supersedes the "track content consumed" idea)
- The Mac app records minutes by broad category from the frontmost app's bundle id, late-night minutes, switches,
  stretches and breaks. No titles, URLs, keystrokes or screenshots; opt-in per signal, pausable, shown in "What
  Kaiku saw today". Written fresh at the event; no code from any earlier personal project (hackathon rule 10).

## D27 — Unified voice and script (2026-11-14)
- One Gemini prebuilt voice (`config/kaiku.toml [voice]`) and one keyed script (`config/voice_lines.toml`) for robot,
  apps and glasses; cloud `GET /v1/voice/{line_key}` serves cached audio. Crisis text stays scripted.

## D28 — Plans live in `docs/plans/NN-*.md` (2026-11-14)
- `handoff.md` became `docs/plans/01-foundation.md` (✅ DONE, kept as reference). New plans get the next number;
  done plans are marked, never rewritten. The "Hexarp" draft was dropped; the name is Kaiku.

## D29 — Plan-02 signals in the criteria, conservative; second tuning pass (2026-11-14, workstream B, simulation)
- Change: `[sources.wearable]` (expected 7/week, `worse_min_weight = 1.0`: two half-weight watch signals must drift
  together) and 11 new metrics, **all `weight = 0.5`**: wearable `watch_sleep`↓, `sleep_midpoint`↑ (later),
  `resting_hr`↑, `hrv_sdnn`↓, `daily_steps`↓; apps `late_night`↑, `active_min`↓, `communication_min`↓
  (`category_min.communication`, nested fields now supported), `firefly_reaction`↑; glasses `cadence`↓,
  `daylight_min`↓. Optional `person_hard` sentences drive the gentle "hard day" notes on `/me`.
- Cohort: 13 scenarios (adds robot+watch drift, watch-only drift, stable without a watch); demo Aino now drifts on
  robot + apps + watch, with a sub-threshold glasses cadence dip (glasses stay "as usual" → disagree).
- Numbers (`make tune`, 40 synthetic patients):

  | metric | D20 `consensus-v1+4936eb40` (3 sources) | D29 `consensus-v1+6763c8eb` (4 sources) |
  |---|---|---|
  | needs_call precision / recall | 1.00 / 0.76 | 0.97 / 0.90 |
  | false needs_call per patient-month | 0.00 | 0.03 |
  | median lead time (days) | 2.0 | 6.0 |
  | stable precision / recall | 1.00 / 0.98 | 0.97 / 0.98 |
  | watch precision / recall | 0.80 / 1.00 | 0.89 / 0.90 |
  | ablation needs_call recall without robot / glasses / laptop / wearable | 0.33 / 0.33 / 0.33 / — | 0.17 / 0.50 / 0.50 / 0.67 |

- Reading: a fourth independent source buys recall and lead time (+4 days) at a small false-alarm cost (0.03 per
  patient-month). People without a watch lose nothing (scenario "stable, no watch" stays stable). Weights stay at
  0.5 until tester data exists; raise them one at a time with `make tune`.
- Caveat as D20: our own generator, not clinical validity. The rule version above is the file at this commit.
