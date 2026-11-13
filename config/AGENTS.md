# config — AGENTS.md (ground truth for settings)

> Read the root `AGENTS.md` first.

## What lives here
- **`criteria.toml` — HOW EACH DATA INPUT IS USED to decide a person's state** (the consensus criteria):
  per-metric obs/field/filter, daily aggregation, worse direction, weight, enabled, per-metric thresholds;
  per-source vote settings; how verdicts combine into states; direct rules (PHQ-9). Validated by
  `kaiku_contracts/criteria.py`. This is the file that changes most — see "Tuning" below.
- `kaiku.toml` — every other non-secret setting: home, model IDs (`VERIFY-` placeholders until looked up in
  current docs), MQTT, uplink, ritual timings + PHQ-9 mode, perception thresholds, music BPM range, safety numbers.
- `safety_phrases.toml` — crisis phrases (en/fi/sv) and the scripted message spoken/shown verbatim. No LLM.
- `mosquitto.conf` — dev/demo broker.

## Rules
- Secrets never go here (`.env` locally, Modal secret `kaiku-secrets` in the cloud).
- Any key can be overridden by env `KAIKU_<SECTION>_<KEY>` (only keys that exist in the file).
- Loaded only through `kaiku_contracts.config.load_config()` / `get()` — never parse this file yourself.
- `criteria.toml` is NOT overridable by env (one place, versioned by hash). Use `KAIKU_CRITERIA=<path>` to point
  at a candidate file.
- Adding a key: add it here with a comment, read it via `get(section, key, default)`, mention it in the owning
  module's `AGENTS.md` "Config & env".
- Safety phrases: add freely; removing one needs a reason in `docs/progress.md`.

## Tuning the consensus (criteria.toml)
1. Edit `config/criteria.toml` (toggle `enabled`, change `weight`, `worse_when`, per-metric `z_threshold`/`min_mad`,
   source `worse_min_weight`, `[state]` counts…). The header comment explains every step of the rule.
2. `make criteria` — validates (readable errors: unknown field, bad direction, missing source…) and prints the new
   rule version (`consensus-v1+<hash>` — every edit is traceable).
3. `make tune` (or `make tune CRITERIA=candidate.toml COMPARE=config/criteria.toml`) — simulation: per-state
   precision/recall, false needs_call per patient-month, lead time, lose-one-source ablation.
4. On a running cloud, without redeploying: the `/tune/` page (or `POST /v1/admin/criteria/preview` → who would
   change state; `PUT /v1/admin/criteria` → apply; `criteria: null` → back to the file). Export the result as
   TOML and commit it here — the file is the ground truth; a live override is temporary.
5. Log meaningful changes in `docs/decisions.md` (what changed, why, eval before/after).
- Adding a new signal: if its obs type/field already exists, just add a `[[metric]]` block. If it needs a new field
  or obs type, change contracts first (root rule 4), then add the block.
