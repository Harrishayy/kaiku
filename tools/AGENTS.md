# tools — AGENTS.md

> Read the root `AGENTS.md` first. Owner B · kind harness (may import any module; nothing may import tools).

## Purpose
Dev/ops tools: see and replay the bus, diagnose the whole system, keep the agent context in sync (handoff §13).

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
| `tests/` | — | formatting, replay re-stamping, record → replay on a real broker, agents sync incl. drift detection |

## Extension points
- New doctor check: a `check_*()` returning `list[Check]`, called from `main()`; independent and time-boxed, so a
  failing check never hides the others.
- New tool: one file with `argparse` + `--help`, a Makefile target, a row in the Map above.
- New sync rule: add it to `agents_sync.check()` and a negative case in `tests/test_agents_sync.py`.

## Invariants
- Never print secret values (names only).
- Never publish an invalid message (`replay` validates unless `--verbatim`).
- Broker or cloud down → clear message and retry or exit 1, never a stack trace.
- Raw `aiomqtt` on purpose (tools must see invalid messages too); nodes use `kaiku_contracts.bus.Bus`.

## Run standalone
`uv run python tools/<tool>.py --help`

## Run with sim
`make broker`, `make sim`, then `make tail`.

## Config & env
`MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`, `KAIKU_CLOUD_URL`, `KAIKU_HOME_ID`, `GEMINI_API_KEY` (doctor only, never printed).

## Health signal
`make doctor` exits 1 if anything is ❌.

## Tests
`uv run pytest tools/tests`

## Known issues
Recordings may contain personal-ish data from real sessions: they live in gitignored `logs/`; only commit synthetic
or consented fixtures.
