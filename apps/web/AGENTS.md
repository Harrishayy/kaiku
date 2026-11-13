# apps/web — AGENTS.md (the one doc for this module)

> Read the root `AGENTS.md` first. Update this file in the same commit as any change to this module's routes,
> data flow, structure or invariants. Each fact lives here once.

## Purpose
The browser side of Kaiku, owner **D**, kind app (`modules.toml` → `web`): the person's own page (`/me`, with Kaiku the
mascot and the firefly game), the clinician dashboard, the **laptop source** (2-minute session + PHQ-9), the admin
criteria tuner, and internal team pages. The look is `design/` (tokens, mascot spec, copy, layout rules): this app reads
those files directly and never copies or redraws them.
**Next.js 15 App Router + TypeScript, static export** (`output: 'export'`, `trailingSlash: true`) to `out/`, served by
the Modal cloud from the same origin as `/v1`.

| route | for | what |
|---|---|---|
| `/me/` | person | ambient Kaiku (`/v1/me` mascot mood; `crisis` → crisis screen), greeting, weather check (3 × 1–5 → `obs.self_report` channel web), "I'm not OK", good & hard moments (7 d), garden, pairing QR + link (`?home=&t=`), suggestion, firefly link, what helps, What Kaiku remembers (delete one / all, remembering on/off), What Kaiku saw today (receipt), PHQ-9 due card. en/fi toggle. Never states, scores or trends |
| `/play/firefly/` | person | go/no-go game (60 s), gentle end with a jar, quietly posts `obs.play_session {game: firefly, device: web}` |
| `/clinician/` | clinician | ranked by consensus; chips "Safety: call today" / "Needs a call" / "Worth a check-in" / "Not enough data" (low coverage) / "Stable"; per-source verdict chips (Home robot, Glasses, Apps, Watch); SIMULATED |
| `/clinician/patient/?id=` | clinician | header (last data, last PHQ-9) → consensus chip + sentence + rule line + quick action → 4 source cards (≤ 3 metrics with sparkline + usual band; Watch says "No watch connected" when absent) → evidence table (metric, source, latest, usual median + range, z, direction; scrolls inside its card) → timeline by source → summary ("not a decision") → actions → PHQ-9 → what helps. Never memories |
| `/session/` | person | laptop source: consent → 30 s spoken prompt (+ optional webcam expressivity) → 60 s go/no-go → review numbers → send |
| `/phq9/` | person | standard wording, every 14 days; item 9 > 0 → fixed crisis panel + `safety_flag` first |
| `/consent/` | person | privacy in plain language (static) |
| `/tune/` | admin | edit consensus criteria, preview who would change state + simulation, apply live, reset, export TOML |
| `/live/` `/health/` `/eval/` | team | event stream, node heartbeats, simulation (incl. "losing one source"); with `/tune/` under the small **Team** menu, not in the person/clinician nav |
| `/checkin/` | — | v1 URL; client redirect to `/phq9/` keeping `?home=&t=` |

## Boundaries
May import `@contracts` (`../../contracts/ts/index.ts`, generated) + npm deps — nothing else from the repo. Never
hand-write a type that mirrors a contract model; a missing shape is a contract change (root rule 4).

## Consumes (topics/endpoints)
`GET /v1/patients` · `GET /v1/patients/{id}/consensus` · `GET /v1/patients/{id}/timeline` (series named by
`config/criteria.toml`) · `GET /v1/patients/{id}/phq9` (PHQ-9 is charted from here, never a timeline series) ·
`GET /v1/me?home_id=` · `GET /v1/me/memories?home_id=` · `GET /v1/events?home_id=&since=&limit=` (also /me's receipt) · `GET /v1/health` · `GET /v1/eval` · `GET /healthz` ·
admin: `GET /v1/admin/criteria`, `POST /v1/admin/criteria/preview?eval=1`.

## Emits (topics/endpoints)
- `POST /v1/events`, all `source: "laptop"`, built with `lib/envelope.ts` (UUIDv7, UTC ms `Z`): `obs.laptop_session`,
  `obs.phq9 {mode: "laptop"}`, `obs.safety_flag` (`phq9_item9` | `manual`, `handled_locally: true`),
  `obs.self_report {context: adhoc, channel: web}` (weather check), `obs.play_session {game: firefly, device: web}`.
- `DELETE /v1/me/memories/{id}?home_id=` · `DELETE /v1/me/memories?home_id=` · `PUT /v1/me/memory_settings?home_id=`.
- `POST /v1/patients/{id}/actions` (flag_booster | flag_icbt_referral | acknowledge | send_message).
- admin: `PUT /v1/admin/criteria` (`CriteriaUpdate`; `criteria: null` = reset to file).
- Never audio, images or transcripts.

## Map
```
app/<route>/page.tsx          server shell (metadata) + a 'use client' component next to it
  clinician/PatientList.tsx · clinician/patient/PatientDetail.tsx · me/MeView.tsx · play/firefly/FireflyGame.tsx
  session/SessionFlow.tsx · phq9/Phq9Flow.tsx · tune/TuneView.tsx · consent/page.tsx · checkin/Redirect.tsx · live/ health/ eval/
  layout.tsx (imports design/generated/tokens.css + fonts, LangProvider, nav + footer: MIELI 09 2525 0111, 112)
  page.tsx (landing) · kaiku.css (design-system classes k-*, .ui em sizing with --ts) · globals.css (base + older
  pages; legacy names mapped onto --k-* tokens)
components/
  Mascot.tsx        <Mascot state compose size still ear label>: renders design/mascot.spec.json (all states, blink,
                    events, tap = ear flick, glow by hour from tokens.json, Reduce Motion = pose + cross-fade)
  CrisisScreen.tsx  person crisis screen (no mascot/motion) + useCrisis (obs.safety_flag manual, once)
  Garden.tsx · QrCode.tsx (qrcode-generator, client-side) · Icon.tsx (look book line icons) · Nav.tsx (For you ·
                    Clinician · Team menu)
  ui.tsx            StateChip, VerdictChip, AgreementBadge, DeviceIndicator, Loading/ErrorBox/Empty/StaleNote (older pages)
  SourceCard.tsx    one consensus source card with sparklines, data-driven (works for any future source)
  TimelineChart.tsx generic MetricSeries chart (label/unit/source/worse_when from the cloud) + Phq9Chart
  CrisisPanel.tsx   FIXED crisis text (mirrors config/safety_phrases.toml [script]) — never generated
  NotOkButton.tsx   manual safety trigger · Nav.tsx
lib/
  copy.ts         pure copy lookup (merge design + web tables, en fallback, never a key on screen), greetKey, nameFromHome
  copy-web.json   web-only keys design/copy.json lacks (en + fi; design wins on a shared key)
  i18n.tsx        LangProvider/useCopy: ?lang= → localStorage kaiku.lang → browser → en
  mascot.ts       spec types, cssValue, ambientState (mood → state via spec), glowAt (tokens glow.stops)
  saw.ts          today's events → receipt lines (counts/minutes only), togetherDays
  qr.ts           qrPath, pairingUrl · clinician.ts consensusChip/verdictChip, evidenceRows, cardSeries, sparkline
  api.ts          fetch wrapper (timeout, ApiError with raw `detail`), detailLines (FastAPI 422 → "path: msg"),
                  useApi (poll, keeps last good data), postEvents (Bearer pairing token)
  envelope.ts     uuidv7 + makeEnvelope (typed by @contracts PayloadByType)
  pairing.ts      pure ?home= / ?t= parsing · params.ts: usePairing, useAdminToken (localStorage, stripped from URL)
  format.ts       ALL wording: state/verdict/source/action/activity labels, ranking, describe() for /live
  criteria.ts     /tune/ helpers: groupBySource (via SOURCE_OF), setIn, diffPaths, normalizeCriteria, criteriaToToml
  metrics.ts      pure math: reaction stats, go/no-go schedule, expressivity index, pitch + semitone SD
  speech.ts       Web Audio speech task (pace, pauses, pitch variability)
  expressivity.ts lazy MediaPipe FaceLandmarker (pinned CDN 0.10.35); blendshapes in memory → index; null on failure
tests/lib.test.ts · tests/design.test.ts  node --test over the pure lib functions
```

## Extension points
- **New route:** `app/<route>/page.tsx` + client component; fetch with `useApi('/v1/...')`; add to `components/Nav.tsx`
  and the landing list; add new endpoints to the `web` entry in `modules.toml`. Dynamic data via query params, never
  `[id]` segments.
- **4th consensus source / new metric / new rule:** nothing to change — source cards, list badges, timelines and
  `/tune/` all render whatever the cloud returns (`CONSENSUS_SOURCES`, `SOURCE_OF`, `MetricSeries`, `Criteria`).
  Optionally add a display name/blurb in `lib/format.ts` (`SOURCE_LABELS`, `SOURCE_BLURB`) and a field hint in
  `tune/TuneView.tsx` (`HINT`, keyed by criteria field name).
- **New session task:** a step in `session/SessionFlow.tsx`, pure math in `lib/metrics.ts` + test, and the field in
  `LaptopSession` in contracts first.
- **Swap the face model:** only `lib/expressivity.ts` (keep `startExpressivity(video) → stop(): index | null`).
  **Drop the webcam part:** delete it and its use in `SpeakStep`; send `expressivity_index: null` (D11).

## Invariants
- **design/ is the ground truth for look and copy.** Colours/type/motion only from `--k-*` tokens
  (`design/generated/tokens.css`, imported, not copied); the mascot only via `<Mascot>` from `mascot.spec.json`; person
  UI strings only via `useCopy().t(key)` from `design/copy.json` (+ `lib/copy-web.json`). No dev text on screen
  (`tools/ui_copy_check.py`). Clinician pages are English only (not in copy.json, per `design/ia.md`).
- Overflow (`design/layout.md`): every page holds at 320 px, fi copy, 1.35× text, light and dark, with no horizontal page
  scroll; only the evidence table scrolls inside its card. Text-holding flex/grid children get `min-width: 0`.
- /me never shows states, scores or trends; the person's memories are never shown on clinician pages.
- Static export only: no API routes, server actions, runtime server fetching or `next/headers`.
- No raw media leaves the browser; only `LaptopSession` numbers are sent, after the person has seen them. Camera/mic
  indicators are visible whenever a device is on.
- Crisis path is deterministic: PHQ-9 item 9 > 0 or "I'm not OK" → fixed `CrisisPanel` immediately, then
  `obs.safety_flag` before anything else. A PHQ-9 is sent only when all 9 items are answered (never invented).
  Crisis text changes only together with `config/safety_phrases.toml`.
- "insufficient" is always shown as **not enough data**, never as fine; missing sources stay visible.
- Wording: "change from your usual", "worth a check-in", "consensus", "needs a call"; never diagnosis / relapse
  detected / predicts. Explanations are labelled "an explanation, not a decision".
- Data-driven: no metric, rule or source names hard-coded in components; the frontend never decides a state.
- `/tune/` never changes the ground truth: `config/criteria.toml` is it. Apply = a live, reversible cloud override;
  Export TOML produces text to paste into the file and commit. Apply and Reset always ask for confirmation.
- Talks to the system only over the cloud HTTP API: no MQTT, no hub access, no Gemini calls. The only credentials
  in the browser are the pairing token (person pages) and the admin token (`/tune/`); both are stripped from the URL
  after first load, and the admin token is only sent to `/v1/admin/*`.
- Every page has loading, error (with retry) and empty states; a cloud outage never white-screens.

## Run standalone
```bash
cd apps/web && pnpm install
pnpm dev      # http://localhost:3000 — without a backend, pages show "cannot reach the cloud" states
pnpm build    # static export → out/
```

## Run with sim
```bash
make cloud-local   # API on :8000
make seed          # every consensus state, SIMULATED
make web           # http://localhost:3000/clinician/
```
Person pages: pair once with `/session/?home=demo-aino&t=<KAIKU_HOME_TOKEN>`. Tuning: open
`/tune/?admin=<KAIKU_ADMIN_TOKEN>` once (a local cloud without an admin token accepts requests without one).
`/tune/` flow: edit → **Preview** (who would change state + simulation, current vs candidate; nothing saved) →
**Apply live** (confirm) → **Export TOML** → paste into `config/criteria.toml` → `make criteria && make tune` → commit.
**Reset to file** drops the live override.

## Config & env
- `NEXT_PUBLIC_KAIKU_API` — API base (default same origin; `make web` sets `http://localhost:8000`).
- `NEXT_PUBLIC_KAIKU_HOME_ID` — default home for demo pages (default `demo-aino`).
- Browser storage (localStorage, try/catch): `kaiku.home`, `kaiku.token` (pairing), `kaiku.admin` (`/tune/`).

## Health signal
`/health/` shows cloud `/healthz` and every node heartbeat. Polling pages keep the last good data with a
"connection lost" note; one-shot pages show a retryable error.

## Tests
`pnpm typecheck && pnpm test && pnpm build` (`make test` runs the typecheck when `node_modules` exists).
Unit tests: copy parity/fallback/no clinical words, mascot mood map + glow, receipt lines, QR + pairing link, clinician
wording/evidence rows/sparkline, UUIDv7/envelope, speech pause ratio, pitch + semitone SD, reaction stats + schedule, expressivity index,
pairing parsing, criteria grouping/setIn/diffPaths/normalize/TOML export.

## Known issues
- Highlights, what-helps labels and suggestion reasons are English sentences from the cloud: in Finnish /me shows the
  kind of moment ("Hyvä hetki") and local labels instead. Web-only copy keys should move into `design/copy.json`.
- The weather check uses 1–5 segmented buttons, not the iPhone's rotary dial (the mascot's ear still follows the value).
- "What Kaiku saw today" has no per-signal pause switches yet (no endpoint).
- Clinician pages and `/tune/` have no login beyond the admin token (demo only). PHQ-9 is English only.
- Speech rate and expressivity are rough browser estimates (energy peaks; blendshape variability) — fine for change
  from one's own usual, not absolute values. MediaPipe loads from jsdelivr on first use; offline it is skipped (`null`).
- Live view polls every 2 s (no WebSocket).
- Export TOML drops the comments of `config/criteria.toml` — keep the file's header when pasting.
- Gotcha: `contracts/ts` lives outside the app — `experimental.externalDir` + the `@contracts` alias make it work;
  `contracts/ts/index.ts` has small runtime exports (`CONSENSUS_SOURCES`, `SOURCE_OF`, `topicFor`).
- Gotcha: Node's test runner strips types but needs explicit `.ts` extensions on relative imports inside `lib/`.
- Gotcha: a dangling symlink in this folder makes `next build` fail with ENOENT.
- Gotcha: query params are only readable after mount (`useQueryParam`/`usePairing`/`useAdminToken` return `undefined`
  first) — render `<Loading />` until then, and call all hooks before any early return.
- Gotcha: the criteria JSON keys are `metric` / `rule` (aliases); `normalizeCriteria` also accepts `metrics` / `rules`
  in case a Python path serialises without `by_alias`.
