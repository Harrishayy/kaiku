# apps/glasses-webapp — AGENTS.md

> Read the root `AGENTS.md` first. Owner D · kind app · **not built; not part of the entry.**

## Purpose
A placeholder for a web app on Meta Ray-Ban Display glasses. This folder holds this page only: no code was
written and nothing here runs. The glasses integration that exists is in the iPhone app
([`apps/apple/AGENTS.md`](../apple/AGENTS.md)): registration through Meta's Device Access Toolkit, Kaiku's voice
over Bluetooth on a walk, and the opt-in "Let Kaiku see" (D43). What has run on real glasses is in
[`docs/stack/meta-glasses.md`](../../docs/stack/meta-glasses.md).

## Consumes (topics/endpoints)
None.

## Emits (topics/endpoints)
None (`modules.toml` lists no message for this module).

## Invariants
- Nothing in the submission, the video or the docs may present this folder as a working app.
- If it is ever built, root rule 5 holds as for every surface: only `obs.*` is uplinked, a web app on the
  glasses has no camera or microphone and never "sees", and no observation is derived from a glasses picture (D43).

## Run standalone
Nothing to run.

## Run with sim
Nothing to run. The glasses walk is simulated by the iPhone app's mock glasses and by the sim's glasses twin
([`sim/AGENTS.md`](../../sim/AGENTS.md)).

## Config & env
None.

## Health signal
None.

## Tests
None.

## Known issues
Not built. Remove the folder and its `modules.toml` entry (`make agents && make test`) if it stays unused.
