# apps/glasses-webapp — AGENTS.md

> Read the root `AGENTS.md` first. Owner D · kind app · Phase 5 · source 2 of 3 ("glasses") in the consensus.

## Purpose
Meta Ray-Ban Display web app: audio-first walk companion (start/stop, timer, steps, outdoor minutes via the paired
phone's location), ritual reminder card, breathing guide, WebMCP tools (`start_walk`, `end_walk`, `log_mood`).
Web Apps have **no camera or mic** — never claim the glasses "see" anything (daylight needs the optional DAT app).

## Consumes (topics/endpoints)
`GET /v1/nudge?home_id=` (today's suggestion).

## Emits (topics/endpoints)
`POST /v1/events` (source `glasses`, Bearer pairing token): `obs.outing {minutes, steps?, method: location|steps}`
and `obs.intervention_response {activity: "walk"}`. No MQTT.

## Map
Not scaffolded yet. Stack (D13): Next.js static export, using the Meta Web App plugin skills (`ai-glasses-webapp-*`)
for device APIs, UI Toolkit (`@wearables-ui-toolkit/mrbd`), WebMCP and performance. Types from `contracts/ts` via
the `@contracts` alias, as in `apps/web`.

## Invariants
- 600×600, D-pad focus navigation, **< 300 KB first load and < 15 requests**, 30 Hz, HTTPS only.
- Pairing link `?home=&t=` → localStorage (try/catch) → `Authorization: Bearer`. No Gemini or admin key, ever.
- Trust UX (Meta judging): explain permissions before asking, offline queue in local storage, a "what is shared"
  screen, battery-aware, clear device/connectivity/error state.

## Run standalone
Scaffold here (`pnpm create next-app@15 . --ts --app --no-tailwind`, or copy `apps/web`'s config), `pnpm dev`, open
in the MRBD Simulator Chrome extension (https://chromewebstore.google.com/detail/jpjlmmodokemlepklkdbimceggpbjcll).
On glasses: the Simulator's "View on Glasses QR", or Meta AI app → Devices → Display Glasses → App connections → Web apps.

## Run with sim
`make cloud-local && make seed`, then `NEXT_PUBLIC_KAIKU_API=http://localhost:8000 pnpm dev`.

## Config & env
`NEXT_PUBLIC_KAIKU_API`; pairing link `?home=<id>&t=<token>`.

## Health signal
A walk updates the glasses source card on the dashboard.

## Tests
Runs in the Simulator and on real Display glasses; check first-load size in the `next build` output.

## Known issues
Not started. Agent setup: the `wearables` MCP is in `.mcp.json`; install the `meta-wearables-webapp` plugin (handoff §9.2).
