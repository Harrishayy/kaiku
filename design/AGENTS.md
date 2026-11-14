# design — AGENTS.md

> Read the root `AGENTS.md` first. Owner D · kind library.
> This is the module's only doc. Update it in the same commit as any change to the module's interface, structure
> or invariants (and `modules.toml` if what it emits/consumes changes). Each fact once — link, don't copy.

## Purpose
The single source of Kaiku's look (plan 02 §2–§3, D22–D23): colour, type, spacing and motion tokens, the mascot's
geometry and states, and the motion rules. Web, the Apple apps and the robot eye display consume what is here and
never redraw or re-pick by eye. The published design artifact (directions, mascot sheet, key screens) is linked from
`docs/progress.md`; this folder is what code reads.

## Boundaries
Data + a stdlib-only generator. Imports nothing from the repo (not even `kaiku_contracts`). Other modules read the
files; they never import `gen.py`.

## Consumes (topics/endpoints)
None. No bus, no HTTP.

## Emits (topics/endpoints)
None. Outputs are files: `generated/tokens.css`, `generated/Tokens.swift`, `mascot.svg`.

## Map
- `tokens.json` — **ground truth** for colours (light + warm-charcoal dark; `$semantic` aliases incl. consensus
  `state-*`, chart `series-*`/`chart-*`), glow-by-time-of-day stops, radii, spacing, sizes, elevation, type (web
  fonts + Apple rounded, each style's Dynamic Type `apple` style), motion durations/feedback/easings/springs,
  blink + breath numbers.
- `components.md` — the shared component spec: gap ladder, type and colour roles, the one consensus state →
  label/colour/shape map, chart style, radii/elevation, card/panel, buttons, chip, row, inputs,
  loading/empty/error/offline states, sheet, toast, icons, voice of copy, accessibility floor.
- `mascot.spec.json` — **ground truth** for the mascot: parts (ids, shapes, colour token refs, pivots, clips), blink
  modes, per-state pose + keyframe tracks + events, interactions, ambient-mood → state map, robot eye crop.
- `copy.json` — **ground truth** for on-screen UI copy (en + fi, same keys; `{name}`/`{n}` placeholders). Apps
  render keys, never inline strings or dev notes.
- `ia.md` — the app's information architecture: tabs (Today · Play · Talk · Your days · You), every screen with its
  components, states and copy keys, games (intro → play → gentle end, what each records), Mac/island/web extras.
- `layout.md` — overflow-proofing rules: stress case (fi + long name + 1.35× text + 320 pt), wrapping/truncation,
  scrolling, text scaling, safe areas.
- `motion.md` — how Kaiku moves: principles, easings, blink schedule, breathing, per-state table, haptics, Reduce
  Motion rules, robot parity.
- `gen.py` — stdlib generator; writes the three generated files below. `--check` for staleness, `--out` for a dir.
- `mascot.svg` — GENERATED. 200×200, every part a `<g id>` with `data-pivot` and CSS `transform-origin` set.
- `generated/tokens.css` — GENERATED. `--k-*` custom properties (incl. `--k-shadow-*`, `--k-state-*`,
  `--k-series-*`); dark via `prefers-color-scheme` and `data-theme`.
- `generated/Tokens.swift` — GENERATED. `KaikuTokens` (Colors, Radius, Space, Size, Elevation, TextStyle, Duration,
  Feedback, Easing, Spring, Blink, IdleBreath, GuideBreath, glowStops) + `.kaikuShadow(_:)` for SwiftUI on
  iOS + macOS.
- `tests/test_design.py` — freshness, named parts, spec consistency, AA contrast, motion budget.

## Extension points
- **New colour / size / duration:** add it to `tokens.json`, `make design`. It appears in CSS and Swift. Apple
  reads a copy: run `apps/apple/scripts/sync_design.sh` after (its `SyncFreshnessTests` fails until then).
- **New component or variant:** describe it in `components.md` first (tokens used, states), then build it once per
  platform.
- **New mascot part:** add it to `mascot.spec.json → parts` (id, pivot, shapes with token colours, optional
  `default.opacity`, optional `clip`), `make design`. Give it a pose in the states that use it.
- **New state:** add `states.<name>` (about, duration, loop, blink, pose, tracks; one track per part+prop), describe
  it in `motion.md`'s state table. Tests check parts, props, easings and key order.
- **New platform:** read `tokens.json` + `mascot.spec.json` directly, or add a renderer to `gen.py` + an output to
  `OUTPUTS` (and the freshness test covers it).

## Invariants
- `tokens.json` and `mascot.spec.json` are the only hand-edited sources. Never hand-edit `mascot.svg` or
  `generated/`; `make test` fails when they are stale.
- Light and dark palettes have exactly the same keys. Text colours (`ink`, `ink-2`, `muted`, `clay`, `sage`, `sky`,
  `honey`, `crisis`) keep ≥ 4.5:1 on `bg` and `surface` in both themes; `clay-ink` on `clay` too.
- **No red except `crisis`**, and `crisis` is only used on the crisis screen and for the `safety` state on the
  clinician dashboard.
- Chip/label text on a soft fill is `ink` or `ink-2` (≥ 4.5:1 on every `-soft` and on `surface-2`); a tone's own
  ink on its soft fill is for icons and large text only (≥ 3:1). Chart series colours keep ≥ 3:1 on `surface`.
- `motion.duration` never goes under 300 ms (blink excepted); the only faster numbers are `motion.feedback`
  (≤ 200 ms, direct press/hover feedback).
- Required part ids exist: body, shadow, eye-l, eye-r, lid-l, lid-r, ear, glow, mouth-happy, mouth-yawn, scarf, z.
- `copy.json` languages have identical keys and placeholders, and contain no clinical words. No screen shows dev
  text (obs types, file names, config paths).
- Every screen holds the `layout.md` stress case without clipping.
- All ten plan states exist (plus `speaking`). No state shows Kaiku sad or worried. Character motion ≥ 300 ms (blink excepted).
- Breath guide duration = 60000 / `guide-breath.breaths-per-minute`.
- Transform order per part: translate → rotate → scale about the part's pivot (see `mascot.spec.json`).

## Run standalone
```
make design                     # = uv run python design/gen.py
uv run python design/gen.py --check
open design/mascot.svg          # any browser
```

## Run with sim
Nothing to run against the sims; this module has no runtime. Consumers (web, Apple) render the outputs in their own
sim runs.

## Config & env
None. No `config/*.toml` keys, no env vars.

## Health signal
`uv run python design/gen.py --check` exits 0 and `uv run pytest design/tests` passes.

## Tests
`uv run pytest design/tests` (also part of `make test`): generated files fresh, generator writes to any dir, SVG has
every named part, states reference real parts/props/easings with keys 0..1, colour refs exist in both themes, AA
contrast for text tokens (incl. crisis button, chip text on soft fills, state and series colours), motion budget
(durations ≥ 300 ms, feedback ≤ 200 ms) and breath timing, semantic aliases resolve, copy tables in sync + no
clinical words.

## Known issues
- `mascot.svg` ids are global when inlined; inline it at most once per page or prefix ids when stamping copies.
- CSS `var()` inside SVG `style` works when the SVG is inlined; as `<img>` it uses the light fallbacks (no dark).
- Fonts: web uses Fredoka (display) + Nunito (body) + DM Mono (receipts/numbers) from Google Fonts; Apple uses
  SF Pro Rounded via `.rounded` design. The two families differ slightly by design.
- `copy.json` has no Swedish yet; the persona already speaks sv.
- `play_session` game `"pebbles"` is not in the contracts enum yet (backend adds it); fields in `ia.md`.
- `Tokens.swift` is type-checked with `swiftc -typecheck` by hand, not in CI.
