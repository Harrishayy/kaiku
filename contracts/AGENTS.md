# contracts — AGENTS.md

> Read the root `AGENTS.md` first. This module is the ground truth for every message in Kaiku. Owner: all (agree
> changes in the team) · kind library. Any change here is a contract change: follow root rule 4 and update every
> producer and consumer in the same commit.

## Purpose
The only package every other module may import (`kaiku_contracts`): message models, topics, validation, the
consensus source map, the criteria schema, and a tiny shared kit (MQTT `Bus`, config loader, JSON logging).
Pydantic v2 models are authoritative; JSON Schema and TypeScript are generated from them for non-Python modules.

## Boundaries
Imports only pydantic (+ `aiomqtt`, lazily, inside `bus.py`). Never imports hub, cloud, sim, tools or apps.
Business logic (perception, analytics, the consensus itself) does not belong here.

## Consumes (topics/endpoints)
Nothing (library).

## Emits (topics/endpoints)
Defines all of them. The topic is derived from the fully-qualified `type`:

| type | topic | QoS | retained |
|---|---|---|---|
| `obs.<name>` | `kaiku/v1/<home>/obs/<name>` | 1 | no |
| `raw.<source>.<stream>` | `kaiku/v1/<home>/raw/<source>/<stream>` | 0 | no |
| `cmd.<target>` | `kaiku/v1/<home>/cmd/<target>` | 1 | no |
| `health` | `kaiku/v1/<home>/health/<envelope.source>` | 1 | yes |
| `log` | `kaiku/v1/<home>/log/<envelope.source>` | 0 | no |

Only `obs.*` may be uplinked (`UPLINKABLE`). Glasses, laptop/Mac and phone apps send the same envelopes over
`POST /v1/events`.

Plan 02 additions (all computed on the device; only derived numbers): envelope source `phone` ·
`obs.self_report.channel` (`robot|phone|mac|web|glasses_voice`, default `robot`; always the robot source's daily
dial) · `obs.outing` `method: dat_imu` + `cadence_spm`, `gait_regularity`, `head_up_ratio` ·
`obs.screen_activity` (Mac usage rhythm: `period_min`, `active_min`, `late_night_min`, `category_min{work,
communication, social, video, news, games, other}`, `switches_per_hour`, `longest_stretch_min`, `breaks`, `paused`;
no titles/URLs/keystrokes — `extra=forbid` rejects them) · `obs.play_session` (`game: firefly|breathe|tell`,
`device: phone|mac|web`, reaction/speech/HR features) · `obs.wearable_daily` (`date` = the morning; sleep, sleep
midpoint in min from local midnight, regularity, resting HR, HRV SDNN, steps, exercise, `device`).
API: `MeResponse.mascot {mood: idle|happy|cozy|crisis, line_key}`, `highlights [{date, kind: good|hard, text,
source}]`, `garden {plants, resting}`; `VoiceLinesResponse` (`GET /v1/voice`).
Generated references: `schemas/index.json` (type → schema, topic, model), `schemas/examples.json` (one example per
type), `schemas/sources.json` (obs type → consensus source).

## Map
```
python/kaiku_contracts/
  envelope.py   Envelope, Source, make(), uuid7()           sources: head|sensors|hub|friendlink|glasses|laptop|phone|cloud|sim
  payloads.py   every payload model (obs/raw/cmd/health/log)
  registry.py   type -> model (OBS/RAW/CMD), UPLINKABLE, validate(), EXAMPLES (one per type, required)
  sources.py    obs type -> consensus source (robot|glasses|laptop|wearable) or learner|adherence|override;
                SOURCE_LABELS (laptop is shown as "Apps", wearable as "Watch")
  criteria.py   schema + loader for config/criteria.toml; rule_version = name + hash; nested fields
                (`category_min.communication`); per-metric `person_hard` sentence for /me
  api.py        cloud HTTP models: Consensus, SourceVerdict, Explanation, PatientSummary, Timeline, PHQ-9, Me (+ Mascot,
                Highlight, Garden), VoiceLinesResponse, Eval, Criteria*
  topics.py     topic(), topic_for(), parse_topic(), QoS/retain
  bus.py        async MQTT client: validates both ways, reconnects, heartbeat + last-will
  config.py     config/kaiku.toml + KAIKU_<SECTION>_<KEY> env overrides, .env loader
  jlog.py       JSON-lines logging
  export.py     writes schemas/ + ts/index.ts (make contracts); --check for tests
schemas/  ts/   GENERATED — never edit by hand
tests/          round trips, rejections, topics, source map, criteria validation, bus on a real broker, stale schemas,
                test_plan02.py (new types, bounds, no content fields)
```

## Extension points
- **New obs type:** model in `payloads.py` → register in `registry.py` (`OBS` + an `EXAMPLES` entry) → map it in
  `sources.py` → `make contracts` → a producer and a consumer in `modules.toml` (the checker insists) → sims.
- **New consensus source:** add to `ConsensusSource`/`CONSENSUS_SOURCES`, map its obs types, add `[sources.<name>]`
  + metrics in `config/criteria.toml`. Cloud verdict/consensus code is source-agnostic.
- **New criteria knob:** a field in `criteria.py` with a default + description (existing files stay valid), used in
  cloud analytics, explained in the `config/criteria.toml` header.
- **New API field:** additive optional fields need no version bump; removing/renaming = breaking → bump `SCHEMA_VERSION`.

## Invariants
- `extra="forbid"` on every model: an unknown field is a contract violation, on purpose.
- Every registered type has an example; every obs type has a consensus role (tests enforce both).
- `type` is fully qualified and decides the topic — never build topics by hand (`topic_for(env)`).
- Sims keep the real `source` (e.g. `head`) and set `sim: true`.
- `obs.phq9` validates its own consistency (total = sum(items), item9_positive = items[8] > 0).
- Generated files are committed and must be current (`make test` fails otherwise).

## Run standalone
```python
from kaiku_contracts import make, validate, topic_for, to_json
env = make("obs.self_report", {"item": "mood", "value": 4}, source="hub")   # validates; raises ContractError
topic_for(env)  # 'kaiku/v1/demo-aino/obs/self_report'

from kaiku_contracts.bus import Bus
async with Bus("head", sim=True) as bus:
    await bus.publish("raw.head.tap", {"t_ms": 10, "force": 1.7})
```
Non-Python (firmware, glasses): read `schemas/` or `ts/` and publish JSON matching the envelope; generate the UUIDv7
on the device (or let the hub adapter fill it).

## Run with sim
`make sim` uses these models; `make tail` validates every message live and shows violations in red.

## Config & env
`MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`, `KAIKU_HOME_ID` (Bus defaults) · `KAIKU_CONFIG` (another
`kaiku.toml`) · `KAIKU_CRITERIA` (another criteria file) · `KAIKU_<SECTION>_<KEY>` overrides any `kaiku.toml` key.

## Health signal
`Bus` publishes `health/<node>` every 5 s (retained) and a `down` last-will on disconnect.

## Tests
`make test-contracts`

## Known issues
`make contracts` needs Node for the TS step; commit `schemas/` + `ts/` together with the model change.
