# Draft cut: narration by time code

> **Superseded (15 Nov).** This is the narration of the 14 Nov draft cut. The video now follows the 1:58 script
> in `docs/demo-narrative.md`.

For `demo/recordings/kaiku-draft-cut.mp4` (1:48.8, 1920x1080, h264 + AAC), built by `demo/draft_cut.py` from the
clips in `demo/recordings/` (`uv run --with pillow python demo/draft_cut.py`; the exact pieces are in
`recordings/kaiku-draft-cut-timeline.txt`). The order is the shot table in `docs/demo-narrative.md` as it stands
on 14 Nov evening; the lines are that table's lines, changed only where the picture differs from the plan. Read
the state that is on screen; say "simulated record" over the dashboard. Every piece carries its own title (what
the judge is looking at) and a line saying where the picture comes from.

**What is still not filmed.** Four plain cards (2 s each, 8 s in all): 0:00–0:02 cold open, 1:03–1:05 the robot,
1:44.8–1:46.8 the care action, 1:46.8–1:48.8 the end card. Three shots play a **stand-in** instead of a card and
say so in clay capitals above the title:

| Time | Shot | Stand-in | What it is, exactly |
|---|---|---|---|
| 0:18.6–0:39.1 | 3: the check-in on a hard day, in her real voice | "STAND-IN: TYPED ON THE SIMULATOR, NOT HER VOICE YET" | One take on the iPhone simulator against a private service with the real model key. Her four lines are typed (microphone permission revoked); every answer is Gemini Live's own reply in that take; the last one arrives on the Lock Screen. Silent: the simulator records no sound. |
| 0:49.0–1:03.0 | 5: the glasses walk | "STAND-IN: SIMULATED GLASSES" | The walk on the simulator with simulated glasses and no microphone. There is no conversation in it and the walk screen says so ("Kaiku can't use the microphone"). What it shows is the app's own: the three styles, the spotting count on the phone and in the Dynamic Island. No model calls. |
| 1:05.0–1:12.5 | 7: quick talk on the Mac | "STAND-IN: RENDERED BY THE MAC APP, NOT A SCREEN CAPTURE" | The three stills from the README, drawn by the app from seeded states. The words inside them are layout text, not a model's reply: never narrate them as something Kaiku said. |

Each is replaced by its filmed shot when the file named in `cut()` is dropped into `demo/recordings/`
(`shot-01-cold-open.mp4`, `shot-03-voice.mp4`, `shot-05-glasses.mp4`, `shot-06-robot.mp4`, `shot-07-mac.mp4`,
`shot-10-care-action.mp4`, `shot-11-end.mp4`; lengths are set in `cut()`).

**Kaiku's voice** (the only sound in the cut):
- 0:09.6–0:18.3 "Hello. I'm Kaiku. It's really good to meet you." This is the line the app played in that take
  (`welcome.hello`, pre-rendered Gemini TTS, served from the voice cache), laid under the silent simulator
  recording at the moment the hello step appears. Nobody has listened to this file yet: listen before publishing.
- The check-in stand-in is silent on purpose. What Kaiku says there is a Gemini Live call's own audio, which a
  simulator recording does not hold; re-rendering the same words afterwards would be a second performance, not
  the call. The sound of that shot is the shot still to film.

Everything else is a real run of the real app or dashboard: the iPhone simulator against a local service with
the simulated record, and the public deployment's dashboard with its cached review written by Gemma
(1:12.5–1:44.8). Speeds are 1x to 3.2x and are listed in the timeline file; the piece with Kaiku's voice runs at 1x.

**The words on screen in the stand-in for shot 3** (so the narrator knows what is being read; nothing here is
written by us except her side):

| She types | Kaiku answers (Gemini Live, this take) |
|---|---|
| "It has been a hard day. My mother would have turned ninety today, and I miss her more than I expected." | "Your mother's ninetieth birthday. Missing her like this sounds so heavy and it's been a really hard few days. I'm here." |
| "I do not really know what to do with the evening. What do you think?" | "Would sitting quietly together for a minute help today, or would you prefer just some space?" |
| on the Lock Screen: "Thank you for staying with me, Kaiku." | "Of course. I'm right here whenever you need me, and there's no rush to do anything else tonight." |

(The take also has a second exchange, about the cardamom buns, which the cut skips.)

| Time | On screen | Say |
|---|---|---|
| 0:00–0:02 | CARD: cold open (kitchen table, appointment card) | "For six weeks someone saw Aino almost every day; her TMS course ended, and now nobody does." (the filmed shot runs 10 s; until then start the line here and let it run over first run) |
| 0:02–0:09 | iPhone first run: what Kaiku is and is not, the choices with a switch each | "Setting up is a list of choices: every signal is opt-in, and nothing listens until she says so." (The plan also shows the service found nearby; the simulator cannot, see the shot list.) |
| 0:09–0:18.6 | Kaiku's hello, in its voice | No narration: Kaiku speaks. Not in the plan; it is the only place the cut has Kaiku's voice. Drop it when shot 3 is filmed. |
| 0:18.6–0:39.1 | STAND-IN: the check-in as a small chat on a hard day; Kaiku stays; it offers one thing, once; the phone locks and the call goes on as a bar on the Lock Screen, where her last line is answered | No narration (the plan: Kaiku's own voice carries the shot). Caption from the plan: "Gemini Live. It notices, and acts once." Until it is filmed the piece is silent. |
| 0:39.1–0:49.0 | Lantern: the flame lights, she touches, a star rises; then the sky she lit | "A one-minute game is also a reaction-time reading, compared only with her own usual." |
| 0:49.0–1:03.0 | STAND-IN: the walk's three styles, Playful chosen; "Bright things 1 of 3", then 2; the same count in the Dynamic Island | "Outside, Kaiku moves to her glasses: head up, hands free, and it connects what is in view to what she has told it." Say this only over the filmed shot. Over the stand-in say what it shows: "A walk starts with how Kaiku should walk with her, and a small spotting game is counted on the phone." |
| 1:03.0–1:05.0 | CARD: the robot ritual | "At home the robot speaks first: three turns of an ear, one breath, a drum, and no typing." (the filmed shot runs 15 s) |
| 1:05.0–1:12.5 | STAND-IN: quick talk as the app draws it: the bar and its two buttons, the popup, the notch | "On her Mac, two taps and Kaiku is there; the Mac itself adds only the rhythm of her day, never content." |
| 1:12.5–1:23.6 | Dashboard, simulated record: the status sentence, signal groups, the Trends chart read day by day | "Each group is compared with her own baseline, and a fixed rule that anyone can read, not a model, combines them; missing data never reads as stable." |
| 1:23.6–1:44.8 | Kaiku's review: Gemma's reading of the whole record, the agent trace; the knowledge graph with a node picked; the Daily account | "For her practitioner, Gemma chooses the evidence and points to the record behind every sentence; the numbers are written by code." (No cited record is opened in this take.) |
| 1:44.8–1:46.8 | CARD: the follow-up (care action) | "One click records the follow-up, and the days that follow are there to compare." |
| 1:46.8–1:48.8 | CARD: end card | "Kaiku: a friend on your desk, a voice in your ear, a clearer record for your care team." |

**When the filmed shots come in.** At their planned lengths (10 + 16 + 16 + 15 + 8 + 6 + 4 = 75 s) the builder
stops with "longer than 1:58": the clip pieces may then total 43 s at most. Remove the hello piece from
`FIRST_RUN` (first run is then 7 s, as planned), keep `LANTERN` at 8 to 10 s, and bring `DASHBOARD` down to about
25 s by raising its speeds. The total must stay under 2:00.

Not in this cut any more, because the shot table no longer has them: the Talk tab (its clip and GIF exist:
`iphone-4-talk.mp4`), Seed shelf, "All done for today", and Your days.
