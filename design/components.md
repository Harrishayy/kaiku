# Kaiku components

One spec for the parts every surface shares (iPhone, Mac, web dashboard, robot display). Numbers are tokens from
[`tokens.json`](tokens.json); if a number here and there disagree, the JSON wins. Swift: `KaikuTokens.*`. CSS: `--k-*`.
Layout stress rules are in [`layout.md`](layout.md), motion in [`motion.md`](motion.md), words in `copy.json`.

## The five rules that stop drift
1. **Only token values.** No literal colour, font size, radius, gap, padding, shadow or duration in app code. No
   arithmetic on tokens (`Space.s5 - 4`, `spacing + 6`): pick the nearest step.
2. **One gap ladder.** `space.1` 4 (icon ↔ label, title ↔ detail) · `space.2` 8 (inside a control, chip rows) ·
   `space.3` 12 (items inside a card, card ↔ card in a group) · `space.4` 16 (card padding, page gutter on
   iPhone and narrow web, panel ↔ panel on the dashboard) · `space.5` 24 (section ↔ section, page gutter on Mac
   and desktop web) · `space.6` 32 (page top/bottom, hero blocks). 48 and 64 only for empty-page breathing room.
3. **One component per job.** A card is `KCard` / `.k-card`; a chip is `KChip` / `.k-chip`. A screen never redraws
   one from a rounded rectangle. Missing variant → add it to the component.
4. **Same structure on every screen.** Header (title, one line on what the page is for) → content in sections →
   every section has a section header → the same gap between sections on every tab.
5. **Every data view has four states**: loading, empty, error, content (see States).

## Type
`type.scale`, with the Apple Dynamic Type style each one scales with (`apple` key): `micro` 12 (caption2) ·
`caption` 13 · `footnote` 15 · `body` 17 · `callout` 19 · `title3` 22 · `title2` 28 · `title1` 34 (title) ·
`display` 44 (largeTitle). SwiftUI: `.kText(.body)`. Web person pages use the same sizes; the dashboard is denser:
labels and data at `caption`, panel titles and any paragraph a person reads (review text, notes) at `footnote`,
key numbers at `callout`, the page title at `title3`; nothing else (`var(--k-text-*-size)`).
- `micro` is for chart axes, table column heads, tab-bar labels and badges only. Never for sentences.
- Weights: 400 running text, 600 labels/titles/buttons, 700 only the page title. Display font (Fredoka) for page
  titles and big numbers on the web; mono (DM Mono) for numbers in tables, timestamps and ids.
- SF Symbols follow the text they sit next to: `Image(...).kText(.footnote, weight: .semibold)`, never
  `.font(.system(size: 13))`, so icons grow with Dynamic Type.

## Colour roles
| role | token | notes |
|---|---|---|
| page | `bg` | paper behind everything |
| card / panel | `surface` + 1 px `line` | nested or inset areas, inputs, secondary buttons: `surface-2` |
| text | `ink` · `ink-2` (secondary) · `muted` (meta) | `muted` only on `bg`/`surface`/`surface-2`, never on a soft fill |
| primary action | `clay` + `clay-ink` | one per view |
| category tones | `sky` (check-ins, calm) · `sage` (breath, garden, going well) · `honey` (warmth, walks) · `clay` (Kaiku, me) | icon in the tone ink on its `-soft` fill |
| focus | `focus` | 2 px ring, 2 px offset, every focusable element, both themes |
| crisis | `crisis*` | the crisis screen, and the `safety` state on the clinician dashboard. Nowhere else. |

**Text on a soft fill is `ink` (or `ink-2`).** The tone ink on its own soft fill is about 4.3–4.6:1 in light, fine
for icons and for text ≥ `callout` semibold, not for small labels. `design/tests` checks these pairs.

### Consensus states (one map, every surface)
| contract value | label (en) | ink token | fill token | shape cue |
|---|---|---|---|---|
| `stable` | Stable | `state-stable` (sage) | `state-stable-soft` | filled dot |
| `watch` | Worth a check-in | `state-watch` (honey) | `state-watch-soft` | half dot |
| `needs_call` | Needs a call | `state-needs-call` (clay) | `state-needs-call-soft` | ring dot |
| `safety` | Safety: call today | `state-safety` (crisis) | `state-safety-soft` | triangle |
| low coverage / verdict `insufficient` | Not enough data | `state-insufficient` (muted) | `state-insufficient-soft` | dashed outline |

Per-source verdicts: `better` → "Better than usual" (sage) · `as_usual` → "As usual" (neutral, `surface-2`) ·
`worse` → "Change from usual" (honey) · `insufficient` → "Not enough data" (dashed). Never "worse", "decline",
"alert", "risk" or red for a verdict. Colour is never the only cue: every state has its label or its shape.
Labels are `copy.json → state.*` / `verdict.*`.
The person never sees a state name; their apps only change Kaiku's mood (`mascot.spec.json → ambient_mood`).

### Charts
- Series colours in order: `series-1` sky · `series-2` sage · `series-3` honey · `series-4` clay; a single
  series uses `chart-value` (ink-2). More than four series → small multiples, not more colours.
- The person's usual: band = `sky` at 16 % opacity, median = `chart-usual` 1 px dashed. Grid = `chart-grid` 1 px,
  horizontal only. Axis text `micro` in `muted`. Lines 2 px, round joins; points 3 px radius, 5 px on hover/focus.
- A point outside the usual band is marked with a `state-watch` ring, not a colour change of the line.
- Every chart has a title, a one-line plain reading ("Walks: fewer than usual this week"), a legend with direct
  labels where it fits, an empty state, and a text/table alternative (`<table>` or `aria-label` summary).
- Simulated data is always labelled "Simulated" with a `micro` chip (dashed outline).

## Shape
| thing | radius | notes |
|---|---|---|
| card, sheet, garden, game field | `radius.lg` 24 | person apps |
| dashboard panel, banner, input, button, bubble | `radius.md` 16 | bubble's tucked corner `radius.xs` |
| icon tile, segment, table row hover | `radius.sm` 10 | |
| progress track, checkbox, small marks | `radius.xs` 6 | |
| chip, pill, toast, avatar | `radius.pill` | |

Borders: 1 px `line` hairline; 1.5 px for a selected outline (clay). Elevation: `elevation.card` on plain surface
cards in the person apps; `elevation.raised` for toast, popover, sheet and a panel while it is dragged; tinted
cards and dashboard panels at rest have no shadow. Nothing else casts one.

## Components
**Screen / page.** Gutter `space.4` (iPhone, web < 760 px) or `space.5` (Mac, desktop web). Text column max
`size.content-max` 680; a multi-column pane max `size.pane-max` 1000. Section gap `space.5` on every tab root and
pushed screen (no per-screen override). Top padding `space.3` under the status bar, `space.5` on Mac.

**Header.** Tab root: date eyebrow (`caption`, clay, uppercase) + title (`title1`) + one line (`body`, `ink-2`) +
"I'm not OK" pill top right (iPhone) or in the sidebar (Mac). Pushed screen: back + title (`title3`) on one row.
Dashboard page: eyebrow (`micro` mono uppercase, muted) + title (`title2`, display font) + actions right.
Section header: icon tile 36 + title (`callout`) + optional line (`footnote`, muted). On the dashboard: `title3`
with no tile.

**Card / panel.** `surface`, 1 px `line`, padding `space.4`, inner gap `space.3`. Person apps: `radius.lg` +
`elevation.card`. Dashboard panel: `radius.md`, no shadow, header row (title `footnote` 600, move / maximise /
collapse tools 24 px with a pointer and 44 px on touch, `aria-expanded` on collapse), body scrolls inside; collapsed = header only; dragging =
`elevation.raised` + 2 px `focus` outline on the drop target; keyboard: handle focusable, arrows move, Esc cancels.
Tinted card: tone `-soft` fill, no border, no shadow.

**Buttons.** One primary per view.
| kind | fill / text | size |
|---|---|---|
| primary | `clay` / `clay-ink` | min height `size.button-min` 52, full width on iPhone; dashboard: 32 (`space.6`) with a pointer, 44 on touch |
| secondary | `surface-2` / `ink` | same |
| ghost | none / `clay` | min 44 |
| crisis | `crisis` / `crisis-ink` | crisis screen only, no press scale |
| icon | `surface-2` disc, `size.control` 40 visual, 44 hit area | needs an accessible label |

Radius `radius.md` (dashboard: `radius.sm`). Label `callout` 600 (dashboard: `caption` 600), wraps, never
truncates. Press: scale 0.97 in
`feedback.press`, settle in `feedback.release`; hover shade in `feedback.hover`. Disabled: 42 % opacity, no
shadow, no hover. Loading: label stays, spinner replaces the leading icon, button disabled.

**Chip.** Pill, `caption` 600 (`micro` on the dashboard), padding `space.1` × `space.2`, text `ink` on a `-soft`
fill, or `ink-2` on `bg` with a 1 px `line`. Optional leading dot/icon. Not tappable unless it looks like a button
(then min 44 hit area). One component, used for sources, minutes, states, "Simulated".

**List row.** Icon tile 36 (`radius.sm`) + title (`body` 600) + detail (`footnote`, muted) + trailing chevron /
value / switch. Min height `size.row-min` 56 (dense dashboard rows: 44). Padding `space.4` × `space.3`. Hairline
between rows, inset to the text column. The whole row is the target.

**Inputs.** Height ≥ 44, `radius.md`, `surface-2` fill (dashboard: `bg` fill + 1 px `line`), `body` text, a
visible label above (`footnote` 600), help/error below (`footnote`; error text says what to do, in `ink`, with an
icon, not red). Focus ring as above.

**States** (same wording keys everywhere).
| state | person apps | dashboard |
|---|---|---|
| loading | Kaiku `thinking` (96) + `common.loading`; skeletons never flash under 300 ms | skeleton blocks in the panel's shape, `surface-2`, no shimmer under Reduce Motion |
| empty | Kaiku `cozy` (96, or 40 inline in a card) + one sentence + optional secondary button | one sentence + what will fill it ("No walks in this period.") in `muted`, centred in the panel |
| error | card: `err.title` + `err.body` + `err.retry` (secondary) | inline in the panel: what failed in plain words + "Try again"; the rest of the page keeps working |
| offline | sky banner (`sky-soft`, icon, `footnote`) at the top of the screen | same banner under the page header |
| partial data | — | "Not enough data" chip (dashed) + the days covered; never drawn as zero |

**Sheet / modal.** `surface`, top corners `radius.lg`, max 80 % height, content scrolls inside, grab handle on
iPhone, close button top right on Mac and web, Esc closes, focus is trapped and returns to the opener. Title
`title3`. Destructive confirmations use the system dialog on Apple and name the thing ("Forget everything Kaiku
remembers?").

**Toast.** Bottom centre, pill, `ink` fill with `bg` text, `footnote` 600, `elevation.raised`, shows for
`duration.toast-hold`, one at a time, announced politely to screen readers. Never for errors that need an action.

**Tabs / segmented.** Track `surface-2`, `radius.md`, 4 px inset; selected segment `surface` + 1.5 px clay
outline, `radius.sm`; each segment ≥ 44 tall. Stacks vertically when labels do not fit.

## Icons
SF Symbols on Apple (filled variants, weight semibold); the web uses the same set of shapes from
`apps/web/components/Icon.tsx` at 24 (`size.icon`), 1.75 px stroke, `currentColor`. Decorative icons are hidden
from assistive tech; an icon-only control always has a label.

## Voice of copy
Kaiku speaks in the first person, short and warm, to the person: "I can't reach the cloud right now. I'll keep
your check-ins safe here." The dashboard speaks to a practitioner: plain, specific, no character voice, no
exclamation marks. Never on any surface: build words ("service", "endpoint", "configured", "demo", "Developer
Mode", "transcript" → "the words of your talks"), clinical verdict words (see `design/tests`), or blame
("failed", "invalid" → say what to do next). Sentence case everywhere. Buttons are verbs.

## Accessibility floor
AA contrast (tests), 44 pt targets, Dynamic Type to the largest size without clipping (`layout.md` stress case),
VoiceOver label + trait on every control, state never by colour alone, Reduce Motion honoured (`motion.md`),
keyboard reachability and a visible focus ring for everything on Mac and web.
