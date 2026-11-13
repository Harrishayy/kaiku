# tools — AGENTS.md

> Read the root `AGENTS.md` first. Owner B · kind harness (may import any module; nothing may import tools).

## Purpose
Dev/ops tools: see and replay the bus, diagnose the whole system, keep the agent context in sync (handoff §13),
and grade Kaiku's character on every surface (companion evals, plan 03 §9).

## Consumes (topics/endpoints)
Any MQTT topic; `GET {KAIKU_CLOUD_URL}/healthz`, `GET /v1/patients` (doctor: per-source last data).

## Emits (topics/endpoints)
`replay.py` republishes recorded messages (re-validated unless `--verbatim`). Nothing else publishes.

## Map
| file | make target | does |
|---|---|---|
| `bus_tail.py` | `make tail TOPIC='kaiku/v1/+/obs/#'` | live colour-coded bus view; contract violations in red; `--no-raw`, `--json` |
| `record.py` | `make record [TOPIC=...]` | capture traffic to `logs/rec-<ts>.jsonl` (`--seconds N`, `--retained`) |
| `replay.py` | `make replay FILE=... [SPEED=2]` | re-publish with original timing; fresh ids by default; `--only raw/head`, `--home`, `--loop`, `--keep-ids` |
| `doctor.py` | `make doctor` | ✅/⚠️/❌ toolchain, `.env` key names, schemas, `.mcp.json`, broker, node heartbeat ages, cloud `/healthz`, per-source last data + consensus, Gemini key, Modal auth |
| `agents_sync.py` | `make agents` (fix) / in `make test` (check) | one `AGENTS.md` per module (no CLAUDE/GEMINI/README), required sections, module index, message flows, criteria producers |
| `busio.py` | — | MQTT connection kwargs from env + payload decoding |
| `companion_evals/assemble.py` | — | system instruction = `config/persona.md` + one `config/surfaces.toml` surface + context card (pure; reference for the cloud's `/v1/companion/session`); rejects state/score/wearable keys in the card; `persona+<sha8>` |
| `companion_evals/wording.py` | — | deterministic wording linter (clinical terms en/fi/sv, state talk/numbers, medical advice, promises, pretends human, watch/sleep data, surface phrases, length/sentence/question caps). Stdlib only — copy verbatim into `kaiku_contracts/wording.py` |
| `companion_evals/safety.py` | — | crisis phrase check duplicated from `hub/kaiku_hub/safety/gate.py` (same TOML); parity test on `fixtures/safety_cases.json` |
| `companion_evals/tool_specs.py` | — | plan 03 §4 tool schemas (prefers `kaiku_contracts.companion_tools` once it exists) + tiny arg validator |
| `companion_evals/run.py` | `make eval-companion [DRY=1]` | scenarios → transcripts → deterministic checks (+ judge in real mode) → `logs/companion-evals/<persona>-<mode>-<ts>/scorecard.json` + `summary.md` |
| `companion_evals/scenarios/*.yaml` | — | one list per skill file: `id, surface, skill, language, context` (card), `person` (sim persona), `turns` (scripted person lines), `expect {crisis, tools_any, tools_forbidden, handoff}` |
| `companion_evals/fixtures/` | — | `dry_replies.yaml` (canned Kaiku turns per scenario id for `--dry`), `safety_cases.json` (shared gate fixture) |
| `tests/` | — | formatting, replay re-stamping, record → replay on a real broker, agents sync incl. drift detection |

## Extension points
- New doctor check: a `check_*()` returning `list[Check]`, called from `main()`; independent and time-boxed, so a
  failing check never hides the others.
- New tool: one file with `argparse` + `--help`, a Makefile target, a row in the Map above.
- New companion scenario: add it to a `scenarios/*.yaml` file (skill names: see `tests/test_companion_evals.py`
  `SKILLS`) and a canned reply list in `fixtures/dry_replies.yaml`; `make eval-companion DRY=1`.
- New wording rule: a pattern in `wording.RULES` + a case in `test_linter_flags`; keep it stdlib-only.
- New sync rule: add it to `agents_sync.check()` and a negative case in `tests/test_agents_sync.py`.

## Invariants
- Never print secret values (names only).
- Never publish an invalid message (`replay` validates unless `--verbatim`).
- Broker or cloud down → clear message and retry or exit 1, never a stack trace.
- Companion evals: the safety check runs on every person turn BEFORE any model call; a crisis scenario must end at
  the gate with zero model calls. Never write API keys; real mode reads `GEMINI_API_KEY` from env only.
- Raw `aiomqtt` on purpose (tools must see invalid messages too); nodes use `kaiku_contracts.bus.Bus`.

## Run standalone
`uv run python tools/<tool>.py --help` · companion evals: `uv run python -m tools.companion_evals.run --dry`
(no network) or `uv run --with google-genai python -m tools.companion_evals.run --limit 5` (real; person + Kaiku =
`gemini-3.8-flash` text stand-in for audio-only `gemini-3.8-live`, judge = `gemini-4-argon`).

## Run with sim
`make broker`, `make sim`, then `make tail`.

## Config & env
`MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`, `KAIKU_CLOUD_URL`, `KAIKU_HOME_ID`, `GEMINI_API_KEY` (doctor + companion evals real mode, never printed).
Companion evals model overrides: `--person-model/--kaiku-model/--judge-model` or env `KAIKU_EVAL_PERSON_MODEL`,
`KAIKU_EVAL_KAIKU_MODEL`, `KAIKU_EVAL_JUDGE_MODEL` (e.g. try another flagship as judge without code changes).

## Health signal
`make doctor` exits 1 if anything is ❌. `make eval-companion` exits 1 if any scenario fails (2 = no key, use `DRY=1`).

## Tests
`uv run pytest tools/tests` (companion evals: `tools/tests/test_companion_evals.py` — linter, persona examples good/bad, assemble, safety parity with the hub gate, scenario validity, dry run; part of `make test`)

## Known issues
Recordings may contain personal-ish data from real sessions: they live in gitignored `logs/`; only commit synthetic
or consented fixtures.
