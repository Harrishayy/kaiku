# <module> — AGENTS.md

> Read the root `AGENTS.md` first. Owner <A/B/C/D> · kind <library|node|service|app|firmware|harness|docs>.
> This is the module's only doc. Update it in the same commit as any change to the module's interface, structure
> or invariants (and `modules.toml` if what it emits/consumes changes). Each fact once — link, don't copy.

## Purpose
What it is and why, in a paragraph.

## Boundaries
What it may import (`kaiku_contracts` + third-party only; never another module).

## Consumes (topics/endpoints)
Topics / endpoints it reads, and what for.

## Emits (topics/endpoints)
Topics / endpoints it produces, and when.

## Map
One line per important file or folder.

## Extension points
How to add / swap / remove a piece (adapter, step, metric, route…) without touching anything else.

## Invariants
What must stay true (break these and something else breaks).

## Run standalone
Commands, with no other module running.

## Run with sim
Commands, against the sims.

## Config & env
Keys in `config/*.toml` and env vars it reads.

## Health signal
How you can tell it's alive and well.

## Tests
How to run them and what they cover.

## Known issues
Gaps, gotchas, things that cost someone an hour.
