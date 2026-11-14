# apps/web — AGENTS.md (the one doc for this module)

> Read the root `AGENTS.md` first. Update this file in the same commit as any change to this module's routes,
> data flow, structure or invariants. Each fact lives here once.

## Purpose
The practitioner dashboard for Kaiku, owner **D**, kind app (`modules.toml` → `web`). The website is only for the
care team: `/` opens one person's record as a one-viewport dashboard of movable panels. Everything the person
does (check-ins, games, PHQ-9, talking to Kaiku, consent) lives in the iPhone and Mac apps (`apps/apple`), not here.
Internal team pages (`/health/`, `/eval/`, `/tune/`) stay reachable from a quiet link row in the dashboard footer.
The look is `design/` (tokens, component spec, copy): this app reads those files and never copies or redraws them.
**Next.js 15 App Router + TypeScript, static export** (`output: 'export'`, `trailingSlash: true`) to `out/`, served by
the Modal cloud from the same origin as `/v1`.

| route | for | what |
|---|---|---|
| `/` (`?id=` picks a person; a compact switcher appears only when there is more than one) | practitioner | header strip (person, day of record and calibration stage, consensus in plain words, freshness) + panel grid + dock of collapsed panels. Default: Trends, Consensus now and Kaiku's review side by side; Daily account and Routine join from 800 px height |
| `/health/` `/eval/` `/tune/` | team | node heartbeats, simulation, criteria tuning (admin token), inside `TeamShell` |

### Panels (`lib/layout.ts` → `PANEL_IDS`)
| id | title | shows |
|---|---|---|
| `trends` | Trends | the course of change (phase chip + code-written summary) above one measure by day: value line, the person's usual range (dashed outline while the baseline is early), gaps for missing days, the consensus state for each day on the same axis, dated notes from the course (care action, PHQ-9, this measure's turning points; numbered with a key when labels would collide), hover/arrow-key reading; this week vs week before vs usual with the meaning in words; measure picker grouped by signal group |
| `consensus` | Consensus now | state, one-sentence meaning, calibration stage, each signal group's verdict with its evidence, last data, who actually sent the records (envelope `source`) and a "Simulated" marker; next steps; how to read it |
| `review` | Kaiku's review | Gemma's overview of the whole record first, then findings: meaning and what to consider up front, the code-rendered facts as a collapsible compact evidence list with this week / week before / usual and the cited records; second tab: the agent trace (step, actor, model, latency, cache, validator rejections, fallback) |
| `routine` | Routine | usual day by time of day, adherence this week, what helps with tries, interval and caveat |
| `graph` | Knowledge graph | default: what was learned (`layer: learned`): the person in the middle, activities / routines / care actions on one side, the measures a learned link touches on the other, capped to what fits the panel ("+N more" opens the maximised view), the strongest links labelled inline; select a node or link for its evidence; "Show all measures" opens the full layered tree |
| `evidence` | Daily account | newest first: one line per day from `insight.days` (what was done as a line, mood / away from usual / reflection level / care team as chips), flagged-spell days tinted with the state tone; opening a day shows every measure against their usual and the records with sender; a compact reflections strip (level per day, counts, themes) only when the person shares, otherwise one calm line; conversation words never shown |
| `care` | Care actions & notes | record an action with a note; the record's action log |
| `ask` | Ask the record | grounded question and answer with citations |
| `coverage` | Coverage | completeness per signal group per day; what each group sent, by whom |

## Boundaries
May import `@contracts` (`../../contracts/ts/index.ts`, generated) and `@design/*` + npm deps — nothing else from
the repo. Never hand-write a type that mirrors a contract model; a missing shape is a contract change (root rule 4).
`Deep<T>` in `lib/insight.ts` only marks the as-served shape (defaults present) of contract types.

## Consumes (topics/endpoints)
`GET /v1/patients` · `GET /v1/patients/{id}/consensus` · `GET /v1/patients/{id}/timeline?days=60` ·
`GET /v1/patients/{id}/insight` (first with `?generate=false`: rule-based, fast; then without: the generated review
upgrades the Review and trace in place) · `GET /v1/patients/{id}/week` · `GET /v1/patients/{id}/graph` ·
`GET /v1/patients/{id}/phq9` · `GET /v1/events?home_id=&limit=1000` (evidence by day) ·
team: `GET /v1/health` · `GET /healthz` · `GET /v1/eval` · `GET /v1/admin/criteria` · `POST /v1/admin/criteria/preview`.
If `/insight` is unavailable, `lib/insight.ts` derives the same panel shapes from consensus, timeline, week, graph
and events and the Review panel says so (no trace, no state history, no action log in that mode).

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
  health/ eval/ tune/   team pages wrapped in components/TeamShell.tsx
components/dash/
  Dashboard.tsx     shell: header facts, grid, dock, layout state (localStorage, try/catch), person switcher, care access
  Panel.tsx         the one card: grip (drag, arrow keys, Home), maximise (Esc restores), collapse
  kit.tsx           the one Chip, ToneMark, Busy / EmptyState / Problem, Provenance, SimMark
  Chart.tsx         the one chart style (TrendChart + ChartLegend)
  data.ts           useRecord(): all fetching for one record; panels degrade one by one
  panels/*.tsx      one file per panel
components/  Mascot.tsx (brand mark from design/mascot.spec.json) · TeamShell.tsx · ui.tsx (team pages; chips and buttons are the dashboard's Chip / d-btn)
lib/
  layout.ts         panel order, dock, slots(n) tiling of a 12 × 12 grid, viewport-aware default, saved-layout repair
  insight.ts        meaningOf() (every number against the person's usual), day signals, record stage, fallback derivations
  evidence.ts       one plain sentence per observation, grouped by day; dayChips() / dayValence() for the daily account
  graph-layout.ts   learnedView() (learned layer, routines folded into activities) + layered tree (one row per node)
  labels.ts         state / verdict labels from design/copy.json + the one state → tone map
  clinician.ts format.ts chart-domain.ts   units, dates, consensus sentence
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
- The frontend never decides a state. State, verdicts, day-by-day state history and early-baseline flags come from
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
  tab-scoped care-team token and the admin token for `/tune/`, nothing else.
- Every panel has loading, empty and error states; a cloud outage never white-screens.
- `/tune/` never changes the ground truth: `config/criteria.toml` is it.

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

## Config & env
`NEXT_PUBLIC_KAIKU_API` (dev only; empty = same origin). Layout is saved per browser under
`kaiku.dashboard.layout.v5`; the practitioner's initials for actions under `kaiku.dashboard.by`.

## Health signal
None of its own (a static site). The dashboard header shows data freshness and a "connection lost" chip when a
poll fails; `/health/` shows node heartbeats.

## Tests
`pnpm typecheck` · `pnpm lint` (typecheck + `tools/ui_copy_check.py`) · `pnpm test` (`node --test`: grid tiling,
layout repair, meaning wording, record stage, comparison, fallback review, evidence sentences, graph rows, scope
and token guards) · `pnpm build`.

## Known issues
- With all nine panels open on a 720-high screen each side tile is about 240 px tall and the panel area scrolls.
- Annotation labels above the chart can touch on phone-width screens.
