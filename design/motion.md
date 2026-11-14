# Kaiku motion

How Kaiku moves, on every surface. Numbers live in [`tokens.json`](tokens.json) (`motion.*`) and
[`mascot.spec.json`](mascot.spec.json) (`blink`, `states`, `interactions`); this file explains them and sets the rules.
If a number here and in those files ever disagree, the JSON wins. Fix this file.

## Principles
- **Slow, soft, springy.** Character and UI motion is never faster than 300 ms (`motion.duration.fast`). Blinks
  (240 ms) are one exception because a real blink is that quick; **direct feedback** is the other: a press scales to
  0.97 (0.98 for rows/cards) within 100 ms and settles in ~180 ms, hover shades in 150 ms, so every tap is answered
  in the same frame. These three numbers are `motion.feedback` (`press` 100 · `release` 180 · `hover` 150:
  `KaikuTokens.Feedback.*`, `--k-dur-press|release|hover`); app code never types them.
- **Gentle overshoot, never a bounce-fest.** Use `overshoot` (`cubic-bezier(.34,1.36,.64,1)`) or
  `Spring.gentle` (response 0.55 s, damping 0.72) for arrivals, and `soft-in-out` for loops.
- **Nothing flashes.** No strobing, no colour flicker. Glow changes fade over at least 700 ms.
- **The mascot never looks sad or worried at the person.** No drooping-sad pose exists. Hard days get `cozy`.
- **Crisis screen: no motion at all.** No mascot, no transitions, no character copy (see `docs/safety.md`).

## Easings (`motion.easing`)
| name | curve | use |
|---|---|---|
| `gentle-out` | (.32, .72, 0, 1) | things arriving, sheets, cards, twitches |
| `soft-in-out` | (.45, 0, .25, 1) | every loop: breathing, bobbing, sway |
| `overshoot` | (.34, 1.36, .64, 1) | peek, pop-ins (the "springy" in springy) |
| `settle` | (.22, 1, .36, 1) | the ear-flick settle, dial release |

SwiftUI: `KaikuTokens.Easing.<name>(duration)` or `KaikuTokens.Spring.gentle`. CSS: `var(--k-ease-<name>)`.

## Durations (`motion.duration`)
`fast` 300 · `base` 450 · `slow` 700 · `blink` 240 · `ear-flick` 620 · `crossfade` 300 · `idle-breath` 4000 ·
`guide-breath` 10000 · `toast-hold` 2400 ms (how long a toast stays).

## Blink schedule (`mascot.spec.json` → `blink`)
- Lids (`lid-l`, `lid-r`) slide down to `translate [0, 28]` and back (`soft-in-out`), from the state's pose.
- **normal**: 240 ms, next blink after a uniformly random 3–7 s; 1 in 6 blinks is a **double blink** (second one
  140 ms after the first ends).
- **slow** (thinking, sleepy, cozy): 600 ms, every 5–9 s, never double.
- **none** (cheering, breathing): eyes stay as posed.
- Both lids move together. The robot eye display uses the same schedule and the same lid offsets.

## Breathing
- **Idle breath** (always on in `idle`, `listening`, `cozy`, `sleepy`): body scales `[1, 1] → [1.015, 1.025] → [1, 1]`
  over 4 s, pivot at the bottom centre (100, 176), so Kaiku rises rather than swelling from the middle.
- **Breath guide** (`breathing` state, Breathe with Kaiku): 6 breaths/min = 10 s cycle, 5 s in (scale to 1.08,
  glow brightens to 1.0) and 5 s out (back to 1.0, glow 0.55), `soft-in-out` both ways. Text cue "breathe in" /
  "breathe out" changes at 0 s and 5 s. If phone, Mac and robot are open together they share the cycle start
  (the session's `started_at`), so they breathe in sync.

## States (`mascot.spec.json` → `states`)
Each state has a **pose** (static values held for the whole state, also the Reduce Motion frame), **tracks**
(looping keyframes, keys at 0..1 of `duration`), a **blink** mode and optional **events**.

| state | when | what moves | duration |
|---|---|---|---|
| `idle` | default; ambient mood `stable` | idle breath, ear sways 3°, normal blinks | 4 s loop |
| `listening` | Tell Kaiku, voice dial, robot listening | head tilt −6°, ear up −26° with a twitch, eyes 1.06× | 3 s loop |
| `thinking` | waiting for the cloud / TTS | eyes look up-left, lids 6, ear rocks ±6°, glow pulses | 3.2 s loop |
| `happy` | after any finished interaction; `stable` + recent interaction | two soft hops with landing squash, smile, cheeks, sparkles | 1.4 s loop |
| `cheering` | end of a game | three hops (18 units), ear flaps, sparkles; 1–2 cycles then `happy` | 1.56 s loop |
| `breathing` | Breathe with Kaiku | breath guide (above), soft lids, no blink | 10 s loop |
| `sleepy` | after 23:00 local | half lids (14), ear droops +24°, glow 0.5, a "z" drifts up; yawns every 10–16 s | 3 s loop |
| `walking` | Live Activity / glasses card on a walk | feet show, bob twice per stride (~120 spm), ±2° waddle, ear bounces | 1 s loop |
| `cozy` | ambient mood `watch` / `needs_call`; "I'm here" | scarf on, content lids (7), relaxed ear +12°, warm glow, slow blink | 5 s loop |
| `speaking` | Kaiku talking (Talk tab, voice replies) | glow pulses with the voice, ear bobs ±5°; no mouth | 1.2 s loop |
| `peek` | notch / island / card edge | rises from below a clipping edge to `translate [0, 38]` (ear + eyes show), once, then holds | 700 ms once |

`peek` only moves the root; it **composes** with another state's pose for the other parts (01:10 notch =
`peek` + `sleepy`).

**Mac notch island** (layout: `layout.md` → Mac notch island): collapsed → peek → expanded is ONE spring on the
same shape (`Spring.island`: response 0.8 s, damping 0.82): the band widens to notch + wings and the body grows down and out of the
notch — never a fade between windows. A beat later (150 ms) Kaiku drops into the body on a slower spring
(`Spring.islandDrop`: response 1.1 s, damping 0.78), clipped by the shape, keeping its state (`sleepy` at 01:10: z's, slow blink,
yawns). Auto-hides after 20 s (hovering holds it). Reduce Motion: crossfade (`crossfade`), Kaiku just appears.

**Ambient mood** (`GET /v1/me` → `mascot.mood`) maps to a state through `mascot.spec.json → ambient_mood`.
`safety` has no mascot: the crisis screen replaces everything.

## Interactions (`mascot.spec.json` → `interactions`)
- **Tap** → ear flick: rotate `0 → −28 → 10 → −4 → 0` over 620 ms (`settle`), added on top of the current ear angle,
  plus a tiny sound (optional, respects silent mode). Ignore taps while a flick is running.
- **Weather check dial** → the ear follows the dial: value 1..5 (the `obs.self_report` range) maps linearly to
  −32..+32°, 16° per step, animated with `Spring.gentle`. One haptic tick per step.
- **Look** → eyes follow the cursor on Mac / device tilt on iPhone (CoreMotion, small): max translate (4, 3),
  `Spring.gentle`, returns to centre after 2 s still.
- **Time of day** → glow colour and intensity interpolate between `tokens.json → glow.stops` by local hour
  (wraps at 24). Re-evaluate once a minute; transition 700 ms.

## Haptics (iPhone; Mac uses `NSHapticFeedbackManager` where a trackpad exists)
| moment | iOS | macOS |
|---|---|---|
| dial passes a whole step | `UIImpactFeedbackGenerator(style: .light)` | `.alignment` |
| interaction finished (check-in sent, breathe done, game over) | `UINotificationFeedbackGenerator .success` | `.levelChange` |
| tap Kaiku | `.soft` impact, intensity 0.5 | none |
| breath guide turn (in ↔ out) | `.soft` impact, intensity 0.3 (only if the person turned it on) | none |
| crisis button | none (no playful feedback) | none |

## Game feedback (every interaction answered in ≤ 100 ms)
| moment | what you see | sound | haptic (iPhone) |
|---|---|---|---|
| firefly caught | ring + 8 sparks burst (350 ms), a glow dot arcs into the jar (800 ms), Kaiku smiles | bright two-note chime | rigid 0.6 |
| moth tapped | the moth wobbles and drifts off in a soft dust puff (550 ms); never red | low soft puff | soft 0.45 |
| firefly missed | it sinks and fades with a 4-dot trail (700 ms) | — | — |
| pebble right | ripple ring, the pebble glows, Kaiku hops onto it (450 ms arc + landing squash) | next note up (pentatonic) | rigid 0.6 |
| pebble wrong | gentle shake (450 ms) + "Let's try that one again" | low two-step | soft 0.45 |
| dial step | knob springs to the stop, ear turns | tiny tick | light |
| breath turn | ring restarts, cue word cross-fades, glow swells/settles | very soft tone | soft 0.3 (if on) |

Sounds are synthesised soft sine tones (no bundled audio), quiet, behind You → Little sounds, the iPhone silent
switch (ambient session) and the system mute. Never on the crisis screen. Every game opens with a one-screen
intro that shows a tiny looping demo of what to do; progress is a thin line/dots, never a number.

Lantern (reaction game): the flame is the thing to react to, so it appears at once — one small warm shape, at
most once every 1.5 s, never the screen; its halo still swells in over 700 ms. This is the only immediate onset.

## Reduce Motion
When `prefers-reduced-motion: reduce` (web, `--k-motion: 0`) or `accessibilityReduceMotion` (SwiftUI):
1. **No tracks, no blinks, no events.** Each state shows its pose only.
2. **State changes cross-fade** (300 ms opacity) between poses instead of animating parts.
3. **Breath guide**: Kaiku stays still; the glow cross-fades between 0.55 and 1.0 every 5 s and the text cue
   carries the rhythm. Haptic cue stays if on.
4. **Ear on the dial**: still follows the value (it is direct manipulation, not decoration), but without spring.
5. **Peek**: appears in its final pose with a 300 ms fade.
6. Cursor/tilt following is off.
7. Game feedback keeps its meaning without movement: no sparks, shakes, hops, wobbles or press scaling; the caught
   firefly fades in at the jar, rings and glows only change opacity, intro demos show one still frame.

## Robot parity
The head's eye display draws `eye-l`, `eye-r`, `lid-l`, `lid-r` from the spec (crop `robot_eye_display.crop`), with
the same lid offsets and blink schedule. The physical ear is the dial; the chest LEDs follow `glow.stops`. When the
robot turns its head, apps showing Kaiku play the same `look` toward that side (both follow the same event).
