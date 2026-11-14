# Kaiku app information architecture

What the iPhone, Mac and web `/me` builders implement. Each screen lists its components, states and copy keys.
Copy keys live in [`copy.json`](copy.json) (en + fi; never inline strings, never dev notes on screen). Look and motion come from
[`tokens.json`](tokens.json), [`mascot.spec.json`](mascot.spec.json), [`motion.md`](motion.md). Layout rules are in
[`layout.md`](layout.md). The published look book shows every screen below. Its link is in `docs/progress.md`.

## Rules for every screen
- **"I'm not OK" is on every screen** (`common.notok`). It's in the header on iPhone, at the bottom of the sidebar on
  Mac and on `/me`, and it opens **Crisis**. Onboarding is the only exception, and Help is one tap away there.
- **One primary action per screen**, plus a way out (`common.nottoday`, `common.back` or `game.enough`).
- **No dev text on screen**: no obs types, file names, config paths, "bandit", "spec" or version numbers. They go in
  code comments and this file.
- **Never show scores, grades, streaks, trends or anything about the person's state** (see `config/persona.md`
  hard limits). Numbers on screen are things they did ("24 min walk"), each with a plain sentence.
- Mascot state comes from `GET /v1/me → mascot.mood` through `mascot.spec.json → ambient_mood`, unless an
  interaction sets a transient state.

## Navigation
| | iPhone | Mac | Web `/me` |
|---|---|---|---|
| Tabs | Bottom tab bar: Today · Play · Talk · History · You (`tab.*`) | Sidebar, same five, same order | Single page: Today block, garden, receipt, pairing |
| Extra | Dynamic Island, Lock Screen Live Activity, widgets | Menu bar popover, notch island | — |

## Onboarding (first launch; no tab bar)
| Screen | Components | States | Copy keys |
|---|---|---|---|
| Welcome | mascot `happy` 190 pt, title, body, primary | — | `onb.welcome.*` |
| Pair | back, QR scanner frame, soft "paste link", toast | scanning · found (toast, auto-advance 1.2 s) · invalid code (banner + retry) | `onb.pair.*`, `err.retry` |
| Consent | list of switch rows, one per signal, primary | each switch on/off; all default off except check-ins + walks | `onb.consent.*`, `sig.<checkins,walks,voice,mac,watch>.{t,d}` |
| Notifications | permission card (bell), primary, ghost skip | before system prompt; denied → continue silently | `onb.notif.*`, `common.skip` |
| Meet Kaiku | mascot (tap = ear flick), practice dial (not recorded), primary | — | `onb.meet.*`, `wx.mood.*` |

## Today
| Screen | Components | States | Copy keys |
|---|---|---|---|
| Today | header (time greeting + not-OK), mascot + bubble, primary suggestion, ghost not-today, list rows (Weather check, Breathe), garden strip | mood idle/happy/cozy · suggestion from `/v1/nudge` · weather done (row shows check) · offline (sky banner) · loading (mascot `thinking`) | `today.greet.{morning,afternoon,evening,late}`, `today.suggest.*`, `today.cta.*`, `today.card.*`, `today.offline`, `common.nottoday` |
| Weather check | back + title, mascot (ear follows dial), 3 dials (1–5), primary | per dial default/focus/dragging/disabled; done → happy + `wx.thanks` | `wx.title`, `wx.{mood,energy,sleep}`, `wx.<item>.<1..5>`, `wx.done`, `wx.thanks` |

## Play
Every game goes **intro → play → gentle end**. The end screen has `game.again` and `game.enough`, plus Kaiku
`cheering` then `happy`. `common.nottoday` is on every intro. Nothing is scored on screen.

| Screen | What happens | Records (quietly) | Copy keys |
|---|---|---|---|
| Play | game cards (icon, title, one line, minutes), ordered with today's suggested game first | — | `play.*`, `game.<id>.{t,d}`, `game.time` |
| Firefly | fireflies glow for 1.5 s, moths drift. Tap fireflies, let moths go. 60 s. The end shows a jar of the fireflies caught, never a number | `obs.play_session {game:"firefly"}`: reaction median + IQR, lapses (> 800 ms), false taps | `ff.*`, `game.*` |
| Pebble path | Kaiku hops across 9 pebbles, then you tap the same path. Starts at 2 pebbles, adds 1 per success (max 9), ends after 2 misses. The end shows the path drawn as art | `play_session {game:"pebbles"}`: `span_max`, `accuracy` (correct taps / taps), `duration_s` (enum value pending in contracts) | `pb.*`, `game.*` |
| Tell Kaiku | prompt card, hold Kaiku up to 30 s (ring fills, ear up), release → thinking → thanks. "Type instead" opens the text field | on-device speech features only (rate, pauses, pitch variability); no audio, no transcript | `tell.*` |
| Breathe | Kaiku `breathing`, dashed ring, cue words, breath counter, stop. The end screen says thanks | `play_session {game:"breathe"}` (+ wearable HRV if paired) | `br.*` |
| Light hunt | walking Kaiku, minutes, 3 dots, "Found one", "End walk". Mirrors the glasses voice game | `obs.outing` | `lh.*`, `game.lighthunt.*` |

## Talk
| Screen | Components | States | Copy keys |
|---|---|---|---|
| Talk | header, chat bubbles (me / Kaiku), hold-to-talk mascot with 30 s ring, hint | idle · listening (hold) · thinking · speaking (glow pulses, reply bubble) · mic denied → permission card, then the text field | `talk.*`, `perm.mic.*` |
| Talk, typing | bubbles, typing indicator (mini `thinking` + dots), composer (text field + mic + send icon) | empty · typing · sending · offline (queued, banner) | `talk.type`, `talk.send` |

## History
The one place where the person's own numbers are shown (`docs/decisions.md` D48): the exception to "never show
scores or trends" above. Plain numbers only: no colour for good or bad, no arrows, no "better" or "worse", no state
words, no streaks. Measure names, units and groups come from the service, not from `copy.json`.

| Screen | Components | States | Copy keys |
|---|---|---|---|
| History | header, Your days block (this week's 7 day buttons + row to Your days), then per group (Robot, Games, Walks and outings, Check-ins, Sleep and body, Mac): one card per measure (name, device, latest value + day, last 7 days as a small chart). Mac: two columns of cards | loading · nothing yet (one calm line with Kaiku `cozy`) · latest day simulated ("Simulated") · practice rounds only · offline (shows what it last had + when it was updated) | `tab.history`, `history.sub`, `history.empty*`, `history.fetched*`, `history.card.practice`, `common.simulated` |
| A measure | back + name, where it came from and how a day is made, segmented Day · Week · Month, period with earlier/later, the period's total or average + range + days, chart (bars for amounts, dots for levels, soft band = the person's usual range), month: week by week, sessions list (when, device, each session's numbers) | no records in the period · day picked on the chart · warm-up session · simulated | `history.range.*`, `history.perday.*`, `history.total`, `history.average*`, `history.spread`, `history.days`, `history.usual`, `history.byweek`, `history.sessions*`, `history.warmup` |

## Your days
Reached from History (its first block) and from Today's garden card; no longer a tab.
| Screen | Components | States | Copy keys |
|---|---|---|---|
| Your days | garden (sprout per interaction; rests after 3 quiet days, never wilts), week strip (7 day buttons), postcards row | day blank/good/hard/today · postcards empty state | `days.*`, `empty.postcards` |
| Mark a day (sheet) | bottom sheet: 3 choices + Done | selected choice | `days.sheet.title`, `days.{good,hard,clear}` |

## You
| Screen | Components | States | Copy keys |
|---|---|---|---|
| You | grouped list rows; "Pause everything" switch; Help row | pause on → every signal paused | `you.*` |
| What Kaiku remembers | list of memories with Delete; Forget everything | item deleted (toast) · empty state (cozy) | `mem.*`, `toast.deleted` |
| What Kaiku saw today | receipt (mono): one line + pause switch per signal; "never kept" + "shared as" footers | per-line on / paused (`saw.paused`) | `saw.*` |
| Voice and language | segmented: English · Suomi · Svenska; pace segmented; sample button | selected | `voice.*` |
| Quiet hours | two time boxes, weekend switch, sleepy Kaiku | — | `quiet.*` |
| Devices | device rows: robot, glasses, watch, Mac | connected · connecting · not set up (Set up button) · needs attention | `dev.*` |
| Help and crisis contacts | body + three call buttons (MIELI, 112, care team) | — | `help.*` |
| **Crisis** | plain surface, title, scripted text, three call buttons. **No mascot, no motion, no glow** | — | `crisis.*`, `help.*`; text = `config/safety_phrases.toml [script]` |

## Walk surfaces (iPhone only)
- **Dynamic Island compact**: leading = walking Kaiku, trailing = minutes. **Expanded**: Kaiku, `game.lighthunt.t`,
  `lh.find`, dots, minutes, buttons `lh.found` / `lh.end`.
- **Lock Screen Live Activity**: Kaiku, `lh.walking` (1 line, truncates), `lh.progress`, minutes.
- **Glasses card** (Meta Ray-Ban Display web app): walking Kaiku, `lh.find`, dots.

## Mac extras
- **Window**: sidebar (5 tabs + not-OK), pane = the iPhone screen at window width.
- **Menu bar popover**: greeting + suggestion, 3 quick actions, usage-rhythm switch, "pause for 1 hour",
  "What Kaiku saw today", "I'm not OK". Keys: `mac.pause1h*`, `sig.mac.*`, `you.saw`.
- **Notch island**: late-night peek at 01:10 (`peek` + `sleepy`, `mac.late`, `mac.goodnight`, `mac.five`); nudge
  (`mac.nudge`, `mac.nudge.yes`, `common.nottoday`, auto-hide 12 s); breathing slim state (`br.in`/`br.out`, n/6).
  Respects quiet hours, at most one peek per night.

## Web `/me`
Mascot + `me.hi` + `me.together`, primary Weather check, not-OK; "this week" sentences (`me.walks`,
`me.checkins`, `me.games`); garden; pairing QR (`me.pair*`); links to receipt and memories.

## Clinician `/clinician` (English only, not in copy.json)
Header (pseudonym, day after TMS, last data, last PHQ-9) → consensus chip + one sentence + rule version → four
source cards (robot, glasses, apps, wearable: verdict chip + up to 3 metrics with sparkline and usual band) →
evidence table (metric, source, today, usual median + range, z, direction) → AI summary card labelled
"written by AI, not a decision". Kaiku appears only as a 30 px icon.
