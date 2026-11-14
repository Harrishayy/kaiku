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
- Do not claim: a deployed URL before it exists, robot pulse or HRV, music from drumming, a glasses camera or
  display app, Finnish speech, a friend lamp, Gemma on our own GPU (it runs through the hosted API today).

## If something fails

No network: everything above runs on the laptop. Voice lag: `KAIKU_VOICE=text`. A device drops out: keep
going; the dashboard shows that group as not enough data, never as stable.
