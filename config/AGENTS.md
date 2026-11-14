# config — AGENTS.md (ground truth for settings)

> Read the root `AGENTS.md` first.

## What lives here
- **`criteria.toml` — HOW EACH DATA INPUT IS USED to decide a person's state** (the consensus criteria):
  per-metric obs/field/filter, daily aggregation, worse direction, weight, enabled, per-metric thresholds;
  per-source vote settings including `max_age_days` (stale data cannot vote); how verdicts combine into states; direct rules (PHQ-9). Validated by
  `kaiku_contracts/criteria.py`. This is the file that changes most — see "Tuning" below.
- `kaiku.toml` — every other non-secret setting: home, model IDs (`VERIFY-` placeholders until looked up in
  current docs), MQTT, uplink, ritual timings + PHQ-9 mode, perception thresholds, music BPM range, safety numbers.
- `persona.md` — **who Kaiku is** on every surface: values, how it speaks, hard limits, hand-off rules, per-language
  notes, good/bad example exchanges. Compiled into every system instruction (never a per-surface prompt);
  versioned `persona+<sha8>`. Every edit: `make eval-companion DRY=1` (+ a real pass) must not regress.
- `surfaces.toml` — per surface (`robot`, `glasses`, `iphone`, `mac`, `web`): body capabilities, allowed tools,
  activities, word/sentence/question caps (enforced by the wording linter), session length, proactive limits,
  extra rules, surface-only banned phrases. The header comment documents every key.
- `safety_phrases.toml` — crisis phrases (en/fi/sv) and the scripted message spoken/shown verbatim. No LLM.
- `voice_lines.toml` — every line Kaiku says on every surface, keyed (`greet.morning`, `walk.light_hunt.1`, …),
  en/fi/sv + optional `style`. Clients use keys, never their own wording; served by `GET /v1/voice[/{key}]`.
  The voice itself (one Gemini prebuilt voice + TTS model) is `kaiku.toml [voice]` (D27). Never a crisis line here.
  fi/sv are drafts: have a native speaker check them.
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

`mood`, `energy` and `sleep` include both ritual and ad-hoc check-ins across channels; activity before/after
ratings remain excluded. `[live]` sets the bounded session length, reconnect attempts and explicit robot
transcript opt-in (`hub_transcripts=false` by default).

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
- Optional `person_hard` on a metric: the gentle sentence the person sees in "Your days" on a day beyond their usual
  (wording rules apply; tested against the banned-word list). Nested payload fields use a dot
  (`category_min.communication`).
- Adding a new signal: if its obs type/field already exists, just add a `[[metric]]` block. If it needs a new field
  or obs type, change contracts first (root rule 4), then add the block.

## Model responsibilities
The active demonstration profile excludes light, force, unvalidated robot pulse, retired browser-task metrics
and unverified glasses IMU/daylight from scoring. See the enabled flags in `criteria.toml`; archive schemas remain
compatible. `[perception] light_enabled=false` also prevents hub light observation/context capture.
`[ritual] enabled_nudges` lists implemented activities only, excluding Friendlink/iCBT until those paths exist.
This product/demo release is English-only; native clients and live context request English and the greeting
language is English. Existing translation resources and multilingual deterministic safety phrases are retained.
`[perception] speech_window_s`, `speech_min_voiced_s` and `speech_clip_fraction` bound the hub's transient
energy-only speech summary and reject insufficient/clipped capture; no audio retention is introduced.
D35 in `docs/decisions.md` defines the division: Gemini Live for immediate voice from prepared context,
Gemma for bounded grounded reasoning and batch graph organisation, deterministic code for monitoring/safety.
`[mind]` selects primary reasoning and recent source-context horizon; `[gemma_hosted]` controls bounded output,
thinking, timeout and explanation cooldown. `[live]` controls session duration, context refresh and tool timeout.
Daily Health metrics use `day_field="date"` and `agg="last"` so corrections respect capture ordering.
`[local_api]` supplies the dev server's LAN bind address, port and non-secret Bonjour display name.
The approved spend ceilings are $25 overall and $23 per day (lead's additional $15 on 2026-11-14);
the shared ledger uses conservative estimates, not provider billing reconciliation.
`persona.md` → "How Kaiku makes someone comfortable" sets the warmth rules (reflect one specific thing first,
company before questions, anger heard not soothed, quiet allowed, softer at night, suggestions only when asked and
at most once, only this body's activities, warm goodbyes) and "Tools" forbids tool calls with missing arguments,
`record_dial` without a spoken 1–5 answer and `remember` without explicit permission.
`tools/companion_evals/scenarios/heart.yaml` covers them (good day, low mood, silence, anger, lonely at night,
stopping, asked-then-agreed activity, three crisis phrasings on the deterministic path).
`persona.md` → "Meeting the feeling" (reflect the specific thing and its feeling first, allow it, then one open
invitation or quiet; match energy; banned moves: pivot, empty sympathy, fixing, cheering, stacked questions),
"Morning and evening reflections" (openers that invite a feeling; a flat answer is received, not pushed) and
"Using what you already know" (the card's `open_thread` / `done_today` as one open door, in the person's own words,
never as something observed). `tools/companion_evals/scenarios/attunement.yaml` + `expect.attune`
(`run.check_attunement`) and the judge's `attunement` criterion test them; the examples must stay inside the
two-sentence, one-question caps because the model copies them.
`voice_lines.toml` `welcome.hello` / `welcome.done` are the app's first-run lines; a running service must be
restarted to serve new keys (the apps fall back to `/v1/voice/say` with the same words until then).
