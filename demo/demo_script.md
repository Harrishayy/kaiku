# Live table demo

The script, the shot table, the per-service wording and the judges' questions live in ONE place:
[`docs/demo-narrative.md`](../docs/demo-narrative.md). This page only holds what the presenter does at the table.

## Before (T-10 min)

1. `make doctor`, then `make demo` (or `make demo-reset` if the record was seeded on an earlier day: it must end
   yesterday). Open the dashboard link it prints; Aino is selected.
2. Read what is on screen and narrate that, not the plan. Today the record opens on **needs a call, acknowledged**,
   with the first worse group on day 11 and several from day 12 (`make live-day` prints the same reading).
3. Devices that will record live are linked to Aino's record (README, "Link your own iPhone or Mac").
4. Fallbacks ready in a second terminal: `KAIKU_VOICE=text KAIKU_LLM=template`; the hardware twins (`make sim`).

## During

- Record one thing live (a phone check-in, a game, a walk) and refresh the dashboard: the new day sits next to
  her usual and her hard days. A good day clears the worse groups; a rough one keeps them. One day never flips a
  state by itself in either direction beyond what three-of-five days allow: say so.
- Say "signal groups", "change from her usual", "worth a check-in", "needs a call". Say "simulated record" when
  the dashboard is on screen. Say which robot parts ran on the real board today and which on the twin.
- What is true on 15 Nov, and how far it goes (README, "Is it any good?"):
  - The dashboard is deployed on Modal; every record on it is simulated.
  - Tap it back (a short song from Lyria at a set tempo, tapped back) played once through the head's speaker on
    the board. Her drumming does not make or change the music.
  - The glasses' opt-in seeing ran on one real walk: 30 frames reached that walk's Gemini Live conversation and
    Kaiku heard the wearer. Kaiku's replies have not yet been heard in the glasses.
  - Gemma answered a review and a record question from our own GPU on Modal once; the default path is the hosted
    API.
  - On the robot a press of the ear opens a talk; that newest flow has not been tried by a person on the robot,
    and a phone or Mac stands in for the head's microphone.
- Do not claim: robot pulse or HRV, the robot's records on the dashboard, a friend lamp, a glasses display app,
  Finnish speech, eyes, a chest light or a button on the robot, Gemma on our own GPU as the default.

## If something fails

No network: everything above runs on the laptop. Voice lag: `KAIKU_VOICE=text`. A device drops out: keep
going; the dashboard shows that group as not enough data, never as stable.
