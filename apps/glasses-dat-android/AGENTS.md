# apps/glasses-dat-android — AGENTS.md

> Read the root `AGENTS.md` first. Owner D · kind app · **not built; not part of the entry.**

## Purpose
A placeholder for an Android app on Meta's Device Access Toolkit. This folder holds this page only: no code was
written and nothing here runs. The glasses integration that exists is in the iPhone app
([`apps/apple/AGENTS.md`](../apple/AGENTS.md)); what has run on real glasses is in
[`docs/stack/meta-glasses.md`](../../docs/stack/meta-glasses.md).

An earlier version of this page planned to estimate daylight minutes from camera frames. That design is withdrawn:
since D43 no observation is derived from a glasses picture (root rule 5). Frames go only to an open, unmuted Gemini
Live walk conversation with the person's opt-in, and are never stored or sent to the Kaiku cloud.

## Consumes (topics/endpoints)
None.

## Emits (topics/endpoints)
None (`modules.toml` lists no message for this module).

## Invariants
- Nothing in the submission, the video or the docs may present this folder as a working app.
- If it is ever built, root rule 5 holds as on the iPhone: no frame is stored or uplinked and no observation is
  derived from a frame; the Gemini key never ships in an app.

## Run standalone
Nothing to run.

## Run with sim
Nothing to run.

## Config & env
None.

## Health signal
None.

## Tests
None.

## Known issues
Not built. Remove the folder and its `modules.toml` entry (`make agents && make test`) if it stays unused.
