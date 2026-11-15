# Kaiku layout rules (overflow-proofing)

Every screen must hold, with no clipping and no horizontal overflow, at the **stress case**: Finnish copy
(`copy.json → fi`, about 30–40% longer than English), the long first name "Annemarie-Kristiina", text at
**1.35×** (Dynamic Type XL / browser zoom), and a **320 pt** wide phone. The look book's **Stress test** toggle
applies all four at once. Check it before you call a screen done.

## Sizes
- Phone widths: design at 375 pt, must hold at 320 pt. Mac window min 720 × 480 pt; under 720 the sidebar turns
  into a top strip. (The web dashboard has its own layout rules: `apps/web/AGENTS.md`.)
- Screen side padding `space.4` 16 pt (iPhone, web under 760 px), `space.5` 24 pt (Mac pane, desktop web). Respect
  safe areas (status bar, home indicator, Dynamic Island, notch). Text columns cap at `size.content-max` (680),
  multi-column panes at `size.pane-max` (1000).
- Every gap is a `space.*` step, never token arithmetic. The gap ladder and component sizes are in
  [`components.md`](components.md).
- Tap targets are at least 44 × 44 pt (`size.tap-min`). Primary buttons are at least 52 pt tall
  (`size.button-min`) and full width on iPhone.
- Running text is at most about 38 em wide (`.ui p`). Wide panes cap their text columns.

## Text scaling
- All app text scales with Dynamic Type (`KaikuTokens.TextStyle` sizes × the system scale). On web, use `em`
  inside the `.ui` container with `--ts`.
- These don't scale: tab bar labels (system behaviour, 10.5 pt, up to 2 lines), the Dynamic Island, the
  menu bar and the mascot. The mascot keeps its point size, and layouts never depend on text fitting next to it at XL.
- At scale ≥ 1.2, side-by-side "mascot + bubble" layouts **stack** (mascot above, bubble full width).
- Line heights: 1.15 for display text, 1.4 for body.

## Wrapping and truncation
- **Default: wrap.** Titles, buttons, list rows, chips, dial labels and bubbles all wrap. Buttons grow taller,
  never wider than their container. Use `hyphens: auto` with the right `lang` on every app container (Finnish
  needs it), and `overflow-wrap: break-word` as the fallback.
- **Truncate with an ellipsis only here:** the Lock Screen Live Activity title (1 line), URLs, file names, and
  device names longer than 2 lines. Never truncate a person's name, crisis text, consent text or a button label.
- **Clamp** tab bar labels to 2 lines. Nothing else is clamped.
- Every flex/grid child that holds text gets `min-width: 0` (SwiftUI: `.layoutPriority` + `.fixedSize(horizontal:
  false, vertical: true)`), so long words wrap instead of pushing the layout wider.
- Trailing accessories in rows (switch, chevron, short value) are `flex: none`, and the text column takes the
  rest. If a trailing value is longer than one or two words, move it under the title instead (game cards do this
  for minutes).
- Headers: title and "I'm not OK" share a row and wrap onto two rows when the title needs the room. The pill
  never shrinks.
- Composer: the text field takes the width, and actions are 40 pt icon buttons (send, mic) with accessible labels.

## Scrolling
- **One viewport first.** Every app screen and game fits without scrolling at the default Mac window (980 × 720)
  and on a 6.1–6.3″ iPhone at default text size: compact headers (title + pill on one row), two columns on the
  Mac pane (≥ 600 pt), section gap `space.5` (24 pt) on every screen, no giant empty areas. Scrolling is the fallback only (accessibility
  text sizes, iPhone SE, the 720 × 480 minimum window) and never bounces when the content fits.
- The screen body is still a vertical `ScrollView` for that fallback. Children never shrink to fit (`flex-shrink: 0`,
  the `.scr > *` rule). Shrinking clipped the consent list in testing.
- Fixed elements: the tab bar, game fields and the crisis screen. Game screens fit their field into what's left
  between the header and the bottom bar. Crisis scrolls if it must, and its buttons stay full width.
- Horizontal scrolling only in content rails (postcards) and the dense clinician table. Never on the page.
- Bottom sheets: max 80% of the height, and the content inside scrolls.

## Colour and theme
- Only token colours. Light and dark are both designed. The Dynamic Island and the glasses card are black in both.
- Colour roles: `bg` paper behind everything, `surface` cards with a `line` hairline, `clay` = the one primary
  action, soft fills by category (`sky-soft` check-ins/calm, `sage-soft` breath/garden/going well, `honey-soft`
  fireflies/sun/warmth, `clay-soft` Kaiku's ear/voice and "me"). Icon tiles are the tone's ink on its soft fill;
  tinted cards are borderless. Game scenes: `night-*` + `firefly` + `moth` (Firefly, dark in both themes, text
  `night-ink`), `pond-*` + `pebble*` (Pebble path).
- Text-colour pairs meet 4.5:1 (enforced by `design/tests`). The crisis button uses `crisis` + `crisis-ink`.

## Mac notch island
ONE black shape that grows out of the notch, part of the menu bar, never on top of it (geometry:
`MacIslandGeometry` from `NSScreen.auxiliaryTopLeftArea` / `auxiliaryTopRightArea` + `safeAreaInsets.top` on the
screen with the notch, else the main screen; silhouette: `MacIslandShape`; inner layout: `MacIslandLayout`).
- **Window**: one panel at level statusBar + 1, top edge at the top of the screen, centred on the notch.
  Mouse-through except inside the drawn shape (collapsed: only the notch, a click → hello).
- **Menu bar band** (top of screen → menu-bar height): never wider than the notch + a wing of at most 60 pt each
  side (clamped to the free gap), so it never covers menu titles or status items. Collapsed idle = exactly the
  notch (invisible); while Kaiku is out the wings show tiny glyphs (Kaiku left, the time right).
- **Body**: just below the menu bar the shape flares out through concave shoulders (12 pt) into the wide body
  (10 pt convex top corners, 30 pt bottom corners). Content rect: peek 440 × 172 pt, expanded 460 × 188 pt. Pure
  black, no stroke or border; a soft shadow under the bottom edge only. Without a notch: no band, the body is a
  pill 6 pt below the menu bar at the top centre.
- **Content lives inside the body** (clipped to the shape), two columns with 18 pt padding: Kaiku left, vertically
  centred, **124 pt** (peek) / **128 pt** (expanded), its floating z's (light `mascot-body` ink at 1.6× on black)
  inside; text + buttons right. Line `body` (17 pt) semibold, wraps; buttons capsules, `footnote` semibold, ≥ 34 pt
  tall, wrap to a new row; first = primary.
- Text uses the dark-mode tokens in both appearances.

## Motion
See [`motion.md`](motion.md). Layout changes never animate width or height except the notch island (it mirrors the
hardware notch growing).
