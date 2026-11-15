# apps/web — AGENTS.md (the one doc for this module)

> Read the root `AGENTS.md` first. Update this file in the same commit as any change to this module's routes,
> data flow, structure or invariants. Each fact lives here once.

## Purpose
The practitioner dashboard for Kaiku, owner **D**, kind app (`modules.toml` → `web`). The website is only for the
care team: `/` opens one person's record as a one-viewport dashboard of movable panels. Everything the person
does (check-ins, games, talking to Kaiku, consent) lives in the iPhone and Mac apps (`apps/apple`), not here. There
is no `/me`, `/session`, `/phq9` or `/clinician` page; the dashboard only reads recorded PHQ-9 results.
Internal team pages (`/health/`, `/eval/`, `/tune/`, `/debug/`) stay reachable from a quiet link row in the dashboard footer.
The look is `design/` (tokens, component spec, copy): this app reads those files and never copies or redraws them.
**Next.js 15 App Router + TypeScript, static export** (`output: 'export'`, `trailingSlash: true`) to `out/`, served by
the Modal cloud from the same origin as `/v1`.

| route | for | what |
|---|---|---|
| `/` (`?id=` picks a person; a compact switcher appears only when there is more than one) | practitioner | header strip (person, day of record and calibration stage, consensus in plain words, freshness) + panel grid + dock of collapsed panels. Default: Trends, Consensus now and Kaiku's review side by side; Daily account and the Knowledge graph (as its small overview) join on a viewport at least 1280 px wide and 800 px high (`lib/layout.ts → defaultLayout`), Routine waits first in the dock |
| `/health/` `/eval/` `/tune/` | team | node heartbeats (per home, under its home id), simulation, criteria tuning (admin token; `/tune/?admin=<token>` takes it once from the address, stores it and strips it from the URL), inside `TeamShell` |
| `/debug/` (`?id=<home>&date=<YYYY-MM-DD>`; no `date` = the home's today, no `id` = the first home the service lists) | team (developers) | one day of one home through the pipeline, answer first: see **Debug day** below |

### Panels (`lib/layout.ts` → `PANEL_IDS`)
| id | title | shows |
|---|---|---|
| `trends` | Trends | the course of change (phase chip + code-written summary) above one measure by day: value line, the person's usual range (dashed outline while the baseline is early), gaps for missing days, the consensus state for each day on the same axis, dated notes from the course (care action, PHQ-9, this measure's turning points; numbered with a key when labels would collide), hover/arrow-key reading; this week vs week before vs usual with the meaning in words; measure picker grouped by signal group, where a measure that is shown and not scored (`scored: false`: face signs D52, more of the day from Apple Health D53) is marked "shown, not scored" and is left out of the per-day count of measures away from usual (`daySignals`) |
| `consensus` | Consensus now | state, one-sentence meaning, calibration stage, each signal group's verdict with its evidence, last data, who actually sent the records (envelope `source`) and a "Simulated" marker; next steps; how to read it |
| `review` | Kaiku's review | Gemma's overview of the whole record first, then findings: meaning and what to consider up front, the code-rendered facts as a collapsible compact evidence list with this week / week before / usual and the cited records; second tab: the agent trace (step, actor, model, latency, cache, validator rejections, fallback) |
| `routine` | Routine | usual day by time of day, adherence this week, what helps with tries, interval and caveat |
| `graph` | Knowledge graph | the record as a map, drawn only from `insight.graph`: the person in the middle, the neighbourhoods the cloud declares (`graph.domains`, a fixed compass place each) around, and inside each a small tree (an activity with its routine on the same row, the measures it produces under it, then other measures, care actions, themes as counts). A day scrubber (default: the latest day with records; arrows, replay) lights what was recorded on that day and tones every measure against that day's usual; bars over the days count measures away, a strip shows the replayed consensus. Beside the map: what changed on the day (`graph.days[].changes`, each item focuses its node), or the node in focus (its day, a day-by-day strip, what links it to what in sentences, Show in Trends), a key, the privacy note. Links: each kind its own stroke; reported-to-help always drawn, the rest for the node in focus. Three sizes: wide (map + column), middle (overview of neighbourhoods, zoom into one, or all nodes), tile (nine-cell overview, zoom into one). See **Knowledge graph** below |
| `evidence` | Daily account | newest first: one line per day from `insight.days` (what was done as a line, mood / away from usual / reflection level / care team as chips), flagged-spell days tinted with the state tone; opening a day shows every measure against their usual and the records with sender; a compact reflections strip (level per day, counts, themes) only when the person shares, otherwise one calm line; conversation words never shown |
| `care` | Care actions & notes | record an action with a note; the record's action log |
| `ask` | Ask the record | grounded question and answer with citations |
| `coverage` | Coverage | completeness per signal group per day; what each group sent, by whom |

### Knowledge graph (`panels/GraphPanel.tsx` + `lib/graph-layout.ts`)
The panel decides nothing: neighbourhoods, which node belongs where, what an activity produces, each node's
reading per day and the list of what changed all come from the cloud (`cloud/AGENTS.md` → Graph map). The browser
only places and words them.
- **Place.** `buildHoods()` groups nodes by `node.domain` into the declared neighbourhoods and orders each as a
  tree (`of`, `produces`, `about` edges); a node with an unknown domain goes to "Other records", never into a
  neighbourhood it was not declared in. `layoutMap()` is a pure function of the neighbourhoods and the panel
  size: three columns (west places mirrored so marks face the person, north and south in the middle with the
  person between them, east places on the right), one row per node, the row pitch shrinking from 24 to 16 px and
  the picture growing below that. No simulation, no randomness, no dependency: the same data and size give the
  same picture (tested, with no box overlapping another at four panel sizes).
- **Time.** `nodeOnDay()` reads `node.days` for the chosen date; a node with nothing that day is drawn empty and
  pale. Labels have the room the node's widest value ever leaves, so a label reads the same on every day.
- **Links.** `personPath()` routes every line to the person through the corridor beside the middle column and
  then level into the gap the person sits in (tested to cross no neighbourhood); `linkPath()` curves between two
  nodes. `linkLines()` writes the sentences for the node in focus; order in time is worded as order
  ("(order, not cause)", "(order in time, not proof of effect)"). A link dated on another day than the chosen
  one is drawn fainter.
- **Sizes.** By the panel's own width: ≥ 980 px wide = map + side column; 560–980 = overview cells first
  (`Overview | Nodes`), zoom into one neighbourhood; < 560 = nine compact cells, zoom into one neighbourhood,
  "Full map" maximises.
- **Keyboard.** The scrubber is one `role="slider"` stop (arrows, Home/End, PageUp/PageDown) with a spoken value;
  every node is a `role="button"` with an accessible name that includes its reading on the chosen day; a click
  does not move focus. Replay and transitions follow the dashboard's reduced-motion rule.

### Debug day (`/debug/`, team only)
For a developer wiring a device or checking a step: one local day of one home, top to bottom, answer first. It is
not a person-facing surface and not a view of the record for a practitioner. It is reachable, like the other team
pages, from the quiet "Debug day" link in the dashboard footer (`Dashboard.tsx`), and on a deployed service the
route behind it answers only with the admin token.

| part | shows |
|---|---|
| bar (sticky) | home (any id; listed homes complete), previous / day / next / Today, today and simulated marks, auto-refresh (today only, 10 s, off by default), Ask Gemma (off by default, off again when the day or home changes; after an ask the read shows that ask's model calls, time and estimated cost from the ledger), Refresh; the day in one line (each step opens its section); what the last refresh brought; the home's timezone, the day's bounds in UTC, when the cloud computed it, a link to the raw JSON. Changing the day keeps the previous one on screen, dimmed, until the next answers |
| Result | consensus: state (dashboard label + raw value), the rule alone, held, agreement, day before, since, acknowledged, rule version, reasons, what changed since the day before. Read of the day: the reading word (decided by code), who wrote it (Gemma with model and cached / new call, or code with the fallback reason), validator rejections by category, then summary, what moved, what is missing, what would change tomorrow, rule check (three claims per part until "Show all"); each claim lists its cited facts (detail + numbers on the toggle) and a fact's name jumps to its metric, verdict, envelope or the consensus |
| Signal-group verdicts | verdict (+ the day before), confidence against its minimum, how many of the group's scored metrics are usable that day (a count the page makes from the metrics; it explains an insufficient verdict whose confidence is fine), worse weight and better weight each against its threshold, rules fired, days with data, last data; a row opens its evidence |
| Metrics | every criteria metric: value (`partial` = today's running total), readings, baseline median / spread / days (`early`), z, worse z against its threshold, direction, status, worse days toward a flag, weight, scored or observe-only. Flagged first by default; every column sorts; filters by text, group, status, role, "with a value"; a row opens the envelopes the cloud lists behind it |
| Events | a strip by local time with one lane per device (robot = hub / head / sensors / friendlink, phone, Mac, glasses, watch = wearable records whoever sent them, cloud; any other sender gets its own lane) and "nothing arrived from X today" for silent ones; then every envelope: local time, lane + envelope `source`, type, quality, sim, compact payload (opens to all fields), the metrics it counted toward; filters by lane, type, text. Marks: `new` / `arrived hh:mm:ss` (while watching), `stamped MM-DD` (listed for this day, stamped outside it), `counts on another day` |
| Companion conversations | start → end, surface, purpose, minutes / billed, how it ended, tools (arrows only while the conversation is open: the cloud keeps one of each after upload), whether words were kept; each `feel` call as enums (heard: kind, valence, energy, tone, via; plan: stance, depth, offer). No words: the route sends none |
| Model calls | totals per model (calls, failed, fallback, latency, slowest, estimated cost over the calls that have one), then every call with failures first and the slowest marked |

States: loading; the route closed (401 / 403: "a local, team-only page"; the page sends the admin token `/tune/`
stored, if any); a cloud without the route (bare 404); an unknown home (lists the homes the service has); a day
that has not happened (422, the service's words); a day without data; a failed refresh keeps the last answer.

## Boundaries
May import `@contracts` (`../../contracts/ts/index.ts`, generated) and `@design/*` + npm deps — nothing else from
the repo. Never hand-write a type that mirrors a contract model; a missing shape is a contract change (root rule 4).
`Deep<T>` in `lib/insight.ts` only marks the as-served shape (defaults present) of contract types.

## Consumes (topics/endpoints)
`GET /v1/patients` · `GET /v1/patients/{id}/consensus` · `GET /v1/patients/{id}/timeline?days=60` ·
`GET /v1/patients/{id}/insight` (first with `?generate=false`: rule-based, fast; then without: the generated review
upgrades the Review and trace in place) · `GET /v1/patients/{id}/week` · `GET /v1/patients/{id}/graph` ·
`GET /v1/patients/{id}/phq9` · `GET /v1/events?home_id=&limit=1000` (evidence by day) ·
team: `GET /v1/health` · `GET /healthz` · `GET /v1/eval` · `GET /v1/admin/criteria` · `POST /v1/admin/criteria/preview` ·
`GET /v1/debug/day?home_id=&date=&generate=` (`DebugDay`; `/debug/` only).
If `/insight` is unavailable, `lib/insight.ts` derives the same panel shapes from consensus, timeline, week, graph
and events and the Review panel says so (no trace, no state history, no action log in that mode). In that mode
only, the browser itself words two things, labelled `by: 'template'`: the better / worse / similar tone of this
week against the week before (similar within half of the usual band's half-width, or within 5 % of the usual value
when there is no band) and the certainty label of "what helps" (fewer than 5 tries "early", fewer than 12
"building"). The four constants are named at the top of `lib/insight.ts` (`FALLBACK_*`); no endpoint serves them,
and they differ from the cloud's own (`help_early_tries`, `help_consistent_tries` in its config). No state or
verdict is decided there.

## Emits (topics/endpoints)
- `POST /v1/patients/{id}/actions` (`ActionRequest`: acknowledge | send_message | flag_booster | flag_icbt_referral).
- `POST /v1/patients/{id}/ask` (`ClinicianAskRequest` → `ClinicianAskResponse` with `RecordCitation`s).
- admin: `PUT /v1/admin/criteria` (`CriteriaUpdate`; `criteria: null` = reset to file).
- No `obs.*` at all: the browser no longer produces observations.

## Map
```
app/
  layout.tsx        tokens.css + globals.css + dashboard.css, fonts from tokens; no shared chrome
  page.tsx          `/` → <Dashboard>
  dashboard.css     every dashboard style (`.dash`, `d-*`); token values only (tested)
  globals.css       base + the team pages' styles only
  health/ eval/ tune/ debug/   team pages wrapped in components/TeamShell.tsx
components/dash/
  Dashboard.tsx     shell: header facts, grid, dock, layout state (localStorage, try/catch), person switcher, care access
  Panel.tsx         the one card: grip (drag, arrow keys, Home), maximise (Esc restores), collapse
  kit.tsx           the one Chip, ToneMark, Busy / EmptyState / Problem, Provenance, SimMark
  Chart.tsx         the one chart style (TrendChart + ChartLegend)
  data.ts           useRecord(): all fetching for one record; panels degrade one by one
  panels/*.tsx      one file per panel
components/  Mascot.tsx (brand mark from design/mascot.spec.json) · TeamShell.tsx · ui.tsx (team pages; chips and buttons are the dashboard's Chip / d-btn). No icon set: the dashboard uses text, chips and shape marks
components/debug/
  DebugView.tsx     `/debug/` shell: home and day in the address bar, the bar, section state, jump-to-row, closed / unknown-home states
  useDebugDay.ts    the one fetch: free load, Gemma only on request, 10 s poll for today, what a refresh brought
  ResultSection.tsx VerdictsSection.tsx MetricsSection.tsx EventsSection.tsx CallsSection.tsx   one file per step
  bits.tsx          Section (collapsible), Against (value vs threshold), Tag, the shared event rows
lib/
  layout.ts         panel order, dock, slots(n) tiling of a 12 × 12 grid, viewport-aware default, saved-layout repair
  insight.ts        meaningOf() (every number against the person's usual), day signals, record stage, fallback derivations
  evidence.ts       one plain sentence per observation, grouped by day; dayChips() / dayValence() for the daily account
  graph-layout.ts   the Knowledge graph, pure: buildHoods() (neighbourhood trees), nodeOnDay() / hoodOnDay() / hoodNotable()
                    (a day's look and counts), layoutMap() / layoutHood() (deterministic placement), personPath() /
                    linkPath() (routes), linkLines() (sentences), rowLabel() / hoodCaption() (text that fits)
  labels.ts         state / verdict labels from design/copy.json + the one state → tone map
  clinician.ts format.ts chart-domain.ts   units, dates, consensus sentence
  debug.ts          `/debug/` only: sorting, filters, device lanes, citation targets, model-call totals, refresh diff (no decisions)
  api.ts credentials.ts params.ts criteria.ts mascot.ts
tests/              node --test (pure libs + scope/wording/token guards)
```

## Extension points
- **New panel:** add the id + title in `lib/layout.ts`, a file in `components/dash/panels/`, a case in
  `Dashboard.tsx → body()`. Slots, dock, drag, keyboard move and persistence need no change.
- **New measure / signal group / obs type:** nothing here; charts, pickers, coverage and evidence are driven by the
  timeline series and the generated `SOURCE_OF` / `SOURCE_LABELS`. A new obs type reads better with a case in
  `lib/evidence.ts → describeObs` (unknown types still list under "Other records").
- **New state or verdict wording:** `design/copy.json` (`state.*`, `verdict.*`), then `lib/labels.ts` if the tone changes.

## Invariants
- The website is practitioner-only. No person-facing route, no observation capture, no camera or microphone.
- One viewport at ≥ 1100 × 600: the page never scrolls; panels scroll inside themselves; with many panels open the
  panel area scrolls while the main panel stays in view. Below that the panels stack and the page scrolls.
- Panels cannot overlap: `slots(n)` tiles the grid exactly (tested). Moving only reorders, collapsing only docks.
- The frontend never decides a state (its only thresholds of its own are the fallback's wording constants, see
  Consumes). State, verdicts, day-by-day state history and early-baseline flags come from
  the cloud; low coverage always reads "Not enough data", never "Stable". A record on an early baseline says so
  in the header, the consensus panel, the chart band and the tooltip.
- Every number is shown with its meaning against the person's own usual (`meaningOf`). "What helps" always shows
  tries and the interval, never certainty wording.
- Provenance is the envelope `source` (who sent the record), with a discreet "Simulated" marker. Internal home ids
  are never rendered; "(SIMULATED)" tags in cloud prose are stripped (`cleanText`).
- Wording: "change from usual", "worth a check-in", "consensus", "needs a call"; never diagnosis / relapse.
  State and verdict labels come only from `design/copy.json`.
- Look: only `--k-*` tokens in `dashboard.css` (tested: no literal colours or font sizes); one card, one chip, one
  chart style; state tone by colour **and** shape; visible focus; reduced motion honoured.
- No hard-coded person data. Conversations and private memories are never shown.
- Static export only: no API routes, server actions or runtime server fetching. Credentials in the browser: the
  tab-scoped care-team token (sessionStorage `kaiku.clinician`, pasted under "Care team access", never in a link)
  and the admin token for `/tune/` (localStorage `kaiku.admin`; pasted on the page, or given once as
  `/tune/?admin=<token>`, which is stored and removed from the address at once but has by then been in the address
  bar and the browser history; `/debug/` sends that same stored token to `/v1/debug/`), nothing else. The website
  holds no person credential: `lib/credentials.ts` gives a person's own routes no token.
- Every panel has loading, empty and error states; a cloud outage never white-screens.
- `/tune/` never changes the ground truth: `config/criteria.toml` is it.
- `/debug/` decides nothing: every state, verdict, reading, status, flag and sentence is the one `GET /v1/debug/day`
  served; `lib/debug.ts` only sorts, filters, totals and diffs. Its one relation of its own is "value ≥ threshold"
  beside two served numbers. No fixture or sample data is shipped with it (tested).
- `/debug/` never spends without being asked: every load and every poll sends `generate=false`; `generate=true`
  goes out once when the Ask Gemma switch goes on and once per manual Refresh while it is on, never from
  auto-refresh. A Gemma read on screen is kept across polls and says when the day's digest has moved on.
- Home ids are shown only on team pages: `/debug/` shows and takes one (it is the page's address) and `/health/`
  lists each reporting home under its id. The dashboard never renders one. `/debug/` shows no words from a
  conversation and uses the `--k-*` tokens only (tested), in its own block of `globals.css`.

## Run standalone
```bash
cd apps/web && pnpm install
pnpm dev      # http://localhost:3000 — without a backend the dashboard shows its "service is not answering" state
pnpm build    # static export → out/
```

## Run with sim
```bash
make cloud-local                      # API on :8000 (serves apps/web/out at /)
uv run python -m kaiku_cloud.jobs.single_person --out /tmp/kaiku-seed --url http://127.0.0.1:8000   # the 16-day record
make web                              # http://localhost:3000/
```
Debug day against the same service: `http://localhost:3000/debug/?id=aino` (today), `&date=YYYY-MM-DD` for a
past day; from the static export it is `http://127.0.0.1:8000/debug/?id=aino` after `make web-build`.

## Config & env
`NEXT_PUBLIC_KAIKU_API` (dev only; empty = same origin). Layout is saved per browser under
`kaiku.dashboard.layout.v6`; the practitioner's initials for actions under `kaiku.dashboard.by`; which `/debug/`
sections are open under `kaiku.debug.sections.v1`.

## Health signal
None of its own (a static site). The dashboard header shows data freshness and a "connection lost" chip when a
poll fails; `/health/` shows node heartbeats.

## Tests
`pnpm typecheck` · `pnpm lint` (typecheck + `tools/ui_copy_check.py`) · `pnpm test` (`node --test`: grid tiling,
layout repair, meaning wording, record stage, comparison, fallback review, evidence sentences, scope and token
guards; `tests/graph.test.ts`: neighbourhood trees, the fallback grouping, the same picture every time with no
overlap at four panel sizes, lines to the person that cross no neighbourhood, a day's looks and counts, link
sentences without causal words, captions and labels that fit, the privacy note; `tests/debug.test.ts`: the
`/debug/` helpers and its scope guard) · `pnpm build`.

## Known issues
- With all nine panels open on a 720-high screen each side tile is about 240 px tall and the panel area scrolls.
- Annotation labels above the chart can touch on phone-width screens.
- Knowledge graph: the map is sized for one screen of about 50 nodes; more rows than fit at the smallest pitch
  make the picture taller and the panel scrolls. As the main panel (about 680 px wide) "Nodes" cuts long labels
  (the full name is in the tooltip and in the column once selected); values are never cut. A link between two
  nodes in different neighbourhoods (drawn only for the node in focus) can pass over the dimmed rows of a third.
  The map has been checked in a browser at 1440 × 900 and 1280 × 720 with the seeded person only.
- `/debug/` at 1280 px wide truncates long metric labels (the full label and unit are in the tooltip, the criteria
  name is always whole); below 1000 px the result stacks and the bar stops being sticky.
