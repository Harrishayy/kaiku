# apps/glasses-dat-android — AGENTS.md

> Read the root `AGENTS.md` first. Owner D/B · kind app · optional (only with time + a compatible phone, D2/D3).

## Purpose
Device Access Toolkit app: sparse camera frames on walks → Gemini vision → `daylight_min` → `obs.outing`.

## Consumes (topics/endpoints)
Glasses camera via the DAT SDK.

## Emits (topics/endpoints)
`POST /v1/events`: `obs.outing {method: "dat_camera", daylight_min}` (source `glasses`).

## Invariants
Frames are processed and discarded; no faces stored; pause/stop on hinge close or removal. The Gemini key never
ships in the app: call it via the cloud, or a gitignored `local.properties` for local testing only.

## Run standalone
Android 10+, Android Studio, Kotlin 2.2+. `claude plugin marketplace add facebook/meta-wearables-dat-android`, then
`claude plugin install mwdat-android@mwdat-android-marketplace`. Developer Mode: Meta AI app → Settings → App Info →
tap App version 5×.

## Run with sim
Mock Device Kit + `make cloud-local`.

## Config & env
Cloud URL + pairing token; `local.properties` (gitignored).

## Health signal
An outing with `daylight_min` appears on the dashboard.

## Tests
Mock Device Kit session end to end.

## Known issues
Not started.
