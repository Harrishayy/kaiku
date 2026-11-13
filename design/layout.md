# Kaiku layout rules (overflow-proofing)

Every screen must hold, with no clipping and no horizontal overflow, at the **stress case**: Finnish copy
(`copy.json → fi`, about 30–40% longer than English), the long first name "Annemarie-Kristiina", text at
**1.35×** (Dynamic Type XL / browser zoom), and a **320 pt** wide phone. The look book's **Stress test** toggle
applies all four at once. Check it before you call a screen done.

## Sizes
- Phone widths: design at 375 pt, must hold at 320 pt. Mac window min 720 × 480 pt; under 720 the sidebar turns
  into a top strip. Web `/me` goes to one column under 760 px.
- Screen side padding 18 pt (iPhone), 26 pt (Mac pane), at least 16 px on the web. Respect safe areas (status bar,
  home indicator, Dynamic Island, notch).
- Tap targets are at least 44 × 44 pt. Primary buttons are at least 52 pt tall and full width on iPhone.
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
- The screen body scrolls vertically (`ScrollView`). Children never shrink to fit (`flex-shrink: 0`, the
  `.scr > *` rule). Shrinking clipped the consent list in testing.
- Fixed elements: the tab bar, game fields and the crisis screen. Game screens fit their field into what's left
  between the header and the bottom bar. Crisis scrolls if it must, and its buttons stay full width.
- Horizontal scrolling only in content rails (postcards) and the dense clinician table. Never on the page.
- Bottom sheets: max 80% of the height, and the content inside scrolls.

## Colour and theme
- Only token colours. Light and dark are both designed. The Dynamic Island and the glasses card are black in both.
- Text-colour pairs meet 4.5:1 (enforced by `design/tests`). The crisis button uses `crisis` + `crisis-ink`.

## Motion
See [`motion.md`](motion.md). Layout changes never animate width or height except the notch island (it mirrors the
hardware notch growing).
