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
`voice_lines.toml` `checkin.hello` and `checkin.dials.low|tired|mid|bright` are the apps' check-in chat lines
(Kaiku's hello when its live voice is not there; its one warm line for what was turned on the dials).
`voice_lines.toml` `welcome.hello` / `welcome.done` are the app's first-run lines; a running service must be
restarted to serve new keys (the apps fall back to `/v1/voice/say` with the same words until then).
`persona.md` → "Notice and act" (call `feel` once per clear shift and keep talking; use `recall` lightly; be glad
out loud for good news; when they are down, the one `may_offer` once, as a question, in a later turn, and a no is
final; `depth` brief or stay) and "Passing chat" (a check-in is a small conversation that closes itself on an
ordinary day and stays on a very good or very hard one; at most one check-in question, a number only if offered).
`tools/companion_evals/scenarios/act.yaml` covers them. `surfaces.toml` lists `feel` on every surface.
`[live] feel_scheduling` is the FunctionResponse scheduling the cloud returns for the non-blocking `feel` tool;
`[insight] reflection_label_at_episode_end` turns the one Gemma labelling call after an opted-in conversation on.

`persona.md` → "Walking together" (company, not a guide; quiet, playful and chatty in one paragraph each; connect
what is in view to what is theirs as a question; keep a favourite they point out; never claim to see with the
camera off; a feeling ends the game) is compiled only into walk prompts. `surfaces.toml`
`[surface.glasses.styles.quiet|playful|chatty]` holds each style's word limits and rules (the wording linter and
the prompt both use them; a walk on the phone uses the same tables); `activities` per surface is the list of
screens that surface really has, and `suggest_activity` is listed on `iphone` and `mac` only. `kaiku.toml [walk]`
sets the default style, how many outdoor favourites the card carries, and per style the walk's own clock
(`look_every_s`, `look_prompt`, `quiet_after_s`, `quiet_prompt`). `[live]`: `talk_max_minutes` and
`walk_max_minutes` (a call and a walk may run long), `token_minutes` (what one token and its reservation cover),
`idle_end_s` / `walk_idle_end_s` (when the device closes a conversation nobody is speaking in),
`proactive_audio_purposes` (the purposes whose Live setup lets the model leave an input unanswered: `["walk"]`,
for its own nudges; every other conversation always answers, D49; `persona.md` "How Kaiku speaks" and "Passing
chat" carry the matching line, eval `scenarios/answers.yaml`). `voice_lines.toml` `invite.*` are templates for the
daily invitation (`{topic}`, `{when}`, `{game}` are filled by the cloud; they are spoken with `POST /v1/voice/say`,
never fetched by key). Evals: `tools/companion_evals/scenarios/walk.yaml`, `cards.yaml` (D45).

`kaiku.toml [history]` is the catalogue of the person's History (`GET /v1/me/history`, D48): `default_days`,
`max_days`, `sessions_per_measure`, `session_values`, `usual_scale`, the seven group titles, one
`[[history.measure]]` per measure shown (`key`, `group`, plain `title`, `unit`, optional `format` = `"clock"`,
`"percent"` or `"duration"` (D53, below) and `decimals`; a `key` that is a criteria metric takes that metric's reading rules, otherwise `obs`, `field`, `agg`
and an optional `where` name a stored reading no metric scores), `[history.session]` (the numbers of one session
per observation type: `[payload field, title, unit, decimals, format?]`) and `[history.session_label]`. Titles
are for the person: plain words, no clinical terms, no direction words, and never a questionnaire, a flag or an
engagement level (tested). The camera's counts of face movement (D52) have a group of their own, `camera`
("Camera during activities"): numbers with plain titles, never a feeling word, never in another group (tested).
`kaiku.toml [debug_day]` belongs to the developers' day view
(`GET /v1/debug/day`): list and id caps (`changed_max`: items of "changed since the day before" in the consensus
fact), the three numbers behind the code's own `reading`, `timeout_s`, `max_output_tokens`, `cooldown_s`, the
read's `prompt` (part of the cache digest: editing it retires kept reads and kept failed asks) and `retry_note`
(what the model is told on the one corrective retry).

`kaiku.toml [graph]` declares the practitioner's knowledge graph as a map (`cloud/kaiku_cloud/graph_map.py`): the
per-day window (`days`), the windows of the order links (`follow_days`, `back_days`, `together`),
`[graph.produces]` (activity → the observation types or metric names a session of it yields), `[graph.about]`
(reflection theme → the node it sits beside) and one `[[graph.domain]]` per part of life (`id`, `label`, `short`,
a compass `place`, and what belongs to it: `activities`, `obs`, `measures`, `themes`, `topics`, `kinds`). It
decides where a node is drawn, never a state. A new metric, activity or theme needs a neighbourhood here (tested
in `cloud/tests/test_graph_map.py`).

`kaiku.toml [live]` `settle_min_minutes` (a Live reservation never settles below this many started minutes) and
`settle_grace_s` (seconds added when the cloud itself sees a conversation end, while the goodbye is still being
spoken) belong to the settlement of Live budget reservations (D46).

An activity agreed in one place (D50; `cloud/kaiku_cloud/mind/agree.py`, `stream.py`). `kaiku.toml [agree]`:
`max_open`, `keep`, `clock_slack_s`, `screen_days`, and the word lists the person's own words are read with
(`yes`, `ask`, `hedge`, `no`: regular expressions matched as whole words; a hedge or a no wins over a yes; `ask`
is what counts as their own initiative on an extra-gentle day). `[agree.names]` is how each activity is called in
the sentence, `[agree.where]` how the voice says where it put it, `[[agree.done_by]]` which observation (type
and payload fields) completes which kind. `kaiku.toml [stream]`: `heartbeat_s`, `retry_ms`, `replay`, `queue`,
`max_listeners`, `hide_types` (observation types a `day` event never names). `[local_api] graceful_shutdown_s`:
how long `make cloud-local` waits for open streams when it stops or reloads. `voice_lines.toml` `agreed.robot |
glasses | iphone | mac | plain` are templates like `invite.*` (`{activity}` is filled by the cloud; never fetched
by key). `surfaces.toml` lists `agree_activity` on every surface; `persona.md` has its line under "Tools" and one
sentence in "How Kaiku makes someone comfortable". Evals: `tools/companion_evals/scenarios/agree.yaml`.
`kaiku.toml` is read once per process: a running service needs a restart to see a changed word list.

**Face signs (D52).** `criteria.toml` has a third state for a metric beside scored and switched off:
`role = "shown"` (computed, compared with the person's own usual, charted and citable; never a vote, never what
makes a group sufficient, and not part of the rule version hash) and `at_least = { field = minimum }` (a reading
counts only when the observation's own fields reach the minimums). The seven `face_*` metrics read
`obs.face_signs`, each tied to ONE method and one kind of task (the table is in `cloud/AGENTS.md` → "Face signs"),
all shown; the comment above them argues every direction, floor and
weight. To let one vote: delete its `role = "shown"` line (the rule version changes; re-set its `min_mad` from
recordings first). The old `expressivity` metric (retired browser task) stays switched off and is not reused.
`kaiku.toml`: `[history]` group `camera` with its measures and the per-session numbers of `obs.face_signs`;
`[graph.produces]` lists the face metrics under games and check-ins; `[insight].max_shown_evidence` (records of
shown measures the review may read on top of `max_evidence`); `[debug_day].face_event_facts`; `[face_cue]`
(`enabled`, `z`, `min_baseline_days`, and which metrics stand for `games` and `check_in`): when the companion
goes a little gentler after a face that was clearly quieter than the person's own usual. `persona.md` → "Hard
limits": Kaiku never sees the person, never comments on a face or looks, never brings up a camera, and has one
plain answer when asked. Evals: `tools/companion_evals/scenarios/face.yaml`. A criteria file that names a type a
running API does not know breaks that API until it is restarted (`cloud/AGENTS.md` → "Known trap").
A face reading needs `coverage` 0.6, 20 s and half the frames its method takes in 20 s (`at_least.samples` 300
for `arkit_blendshapes` at 30 looks a second, 150 for `vision_landmarks` at 15).

**More of the day from Apple Health (D53).** `criteria.toml` has six more `role = "shown"` metrics on
`obs.wearable_daily`: `day_distance`, `day_daylight`, `walking_hr`, `deep_sleep`, `rem_sleep`, `awake_night`.
The comment above them argues each direction, floor and weight and says plainly that none is validated here;
`sleep_core_min` is stored and read by no metric. The five watch metrics that vote and `[sources.wearable]` are
untouched, and the rule version stays the same (shown metrics are not in the hash). `kaiku.toml`: the
`sleep_body` measures of `[history]` in the order a person reads a night and a day (sleep, its stages, time
awake, heart, steps, distance, daylight, exercise); `format = "duration"` on measures in minutes that regularly
pass an hour (the app shows "7 h 20 min", `unit` empty) and `format = "percent"` on shares of time (the value
stays 0..1, `unit = "of the time"`, `decimals` counts the percent's); a measure on an index from 0 to 1 that
is not a share of time stays a number with `unit = "out of 1"`; `[history] session_values` = 16, the contract's
own limit, so no row is cut short (tested); `day_offset = -1` on the seven measures of a Health summary that are
the day before's (heart numbers, steps, distance, daylight, exercise), which puts each on the day it is of in
History and nowhere else (the night's measures and the rule keep the summary's date; a session row lists the
numbers that share its measure's `day_offset`); `[graph.produces] sleep` and the `movement` domain list the new
measures;
`[insight].max_shown_evidence` = 12, shared by every shown measure.


## Tap it back and the robot's own audio (2026-11-14, additive, D51)
`kaiku.toml [tap_back]` is the whole game (hub `perception/tap_back.py`, `rituals/tap_back.py`): `mode`
(`auto` = the game when generated music is really open, else free drumming exactly as before · `free` = always free
drumming · `tap_back` = always the game, with the hub's own beat or the chest light alone when there is no generated
song), the three levels (`level_bpm`, `level_vary_bpm` = how far a level's tempo moves from day to day,
`level_taps`), how long the song plays (`listen_s`, `replay_listen_s`, `song_wait_s`), when her turn ends
(`first_tap_s`, `idle_end_s`, `turn_s`), `cue_clear_s` (the margin after the cue before a tap counts: the head sends
no tap while its speaker plays or about 0.3 s after), `min_taps`, the bands (`perfect_pct`, `great_pct`, `nice_pct`,
percent of the song's tempo; `steady_min`: below it perfect and great drop one band; `half_double`: tapping every
second beat or twice per beat counts as the beat), `retries` (how often "again" replays a level), `word_s` and
`result_s` (room for spoken words and a breath after the band), `hold_every_s` (follow mode: how often the head is
re-told `drum: hold`), `max_s`. Changing a number changes the game; no code. The lines are in the hub
(`rituals/tap_back.py`), checked by `kaiku_contracts.wording` with the robot's caps.
`[music]`: `out = "head" | "speaker" | "file"` (default `head`: the drum music and its chimes are sent to the robot
head's own speaker as PCM frames on the bus, and the hub needs no sound device; `speaker` = this machine's sound
card; `file` or `KAIKU_MUSIC_FILE=<path.wav>` = a WAV on the wall clock), `head_lead_ms` (how far ahead of real time
frames are sent, at most 120), `head_gain` (headroom after the down-mix). `[voice] audio = "auto" | "head" | "local"`
(default `auto`): where Kaiku's Live voice and the scripted lines are heard and where the person is listened to:
`head` = the head's speaker and microphone over the bus, `local` = this machine's sound card, `auto` = the head when
a real head (not a sim twin) is alive on the bus as a conversation opens, and always when this machine has no sound
card. `[live]
mic_gap_end_s` (default 1.0): the head sends no microphone frames while it speaks; after this long without one the
Live server is told the stream paused (never filled with silence). Env: `KAIKU_MUSIC_OUT`, `KAIKU_VOICE_AUDIO`,
`KAIKU_TAP_BACK_MODE`, ...
`[hub] follow_offer_every_s` (default 300): on a head that runs its own ritual, Kaiku's spoken invitation at the
head's greeting is said at most this often (that head greets a face about once a minute). `[hub] trace` (default
true): the hub publishes `raw.hub.trace` on the home broker for the apps' "Kaiku bot" tab (Kaiku's own lines, tool
names, game cues, music, conversation open/close; never the person's words; never stored or uplinked); `false` =
nothing is published.
`[history]`: two measures in group `robot`, `tap_back_songs` ("Tap it back: songs on the beat", the day's highest)
and `tap_back_timing` ("Tap it back: timing", percent from the song's tempo, the day's average), and the per-session
numbers of `obs.tap_back`. `[graph]`: `obs.tap_back` is listed under the morning ritual. **No `[[metric]]` in
`criteria.toml` reads `obs.tap_back`** (tested in `contracts/tests/test_tap_back_audio.py`): it is a game, and a
tempo she was given is not her own tempo (D51).
