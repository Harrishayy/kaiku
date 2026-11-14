# Draft cut: narration by time code

For `demo/recordings/kaiku-draft-cut.mp4` (1:57, 1920x1080, h264 + AAC), built by `demo/draft_cut.py` from the
clips in `demo/recordings/` (`uv run --with pillow python demo/draft_cut.py`; the exact pieces are in
`recordings/kaiku-draft-cut-timeline.txt`). The lines are the ones in `docs/demo-narrative.md`, moved to where
their pictures are in this cut and changed only where the picture differs from the plan. Read the state that is
on screen; say "simulated record" over the dashboard. Every piece carries its own title (what the judge is
looking at) and a line saying where the picture comes from.

**Placeholder cards** (plain, 2 s each, 14 s in all): 0:00–0:02, 0:32.6–0:34.6, 1:11.2–1:13.2, 1:16.8–1:20.8,
1:53–1:57. Each is replaced by its filmed shot when the file named on the card is dropped into
`demo/recordings/` (`shot-01-cold-open.mp4` … `shot-11-end.mp4`; lengths are set in `cut()`).

**Kaiku's voice** (the only sound in the cut; leave room for it in the narration):
- 0:16.1–0:24.8 "Hello. I'm Kaiku. It's really good to meet you." This is the line the app played in that
  take (`welcome.hello`, pre-rendered Gemini TTS, served from the voice cache), laid under the silent simulator
  recording at the moment the hello step appears.
- 0:39.5–0:50.2 "Thank you for telling me. I'm listening." Added sound: in this take Talk is on its typed path
  without a live voice and shows the reply as text; the same words were rendered in Kaiku's voice by the
  service (`POST /v1/voice/say`, one paid TTS call, about $0.02) and laid under it. The piece says so on
  screen. Cut this piece once the real conversation (shot 3) is filmed.
Nobody has listened to these two files yet: listen before publishing.

Everything else is a real run of the real app or dashboard: the iPhone simulator against a local service with
the simulated record and no model calls (0:02–0:32.6, 0:34.6–1:11.2, 1:13.2–1:16.8), and the public
deployment's dashboard with its cached review written by Gemma (1:20.8–1:53). Speeds are 1x to 4.5x and are
listed in the timeline file; pieces with Kaiku's voice run at 1x.

| Time | On screen | Say |
|---|---|---|
| 0:00–0:02 | CARD: cold open (kitchen table, appointment card) | "For six weeks someone saw Aino almost every day; her TMS course ended, and now nobody does." (the filmed shot runs 10 s; until then start the line here and let it run over first run) |
| 0:02–0:15.5 | iPhone first run: what Kaiku is, what it is not, the choices with a switch each, permissions asked from their own rows | "Setting up is a list of choices: every signal is opt-in, and nothing listens until she says so." |
| 0:15.5–0:25.1 | Kaiku's hello, in its voice | No narration: Kaiku speaks. |
| 0:25.1–0:32.6 | The practice dial, "You did it", Today's path | (silence, or) "One practice check-in, and she is on today's path." |
| 0:32.6–0:34.6 | CARD: a conversation on a real iPhone (Gemini Live) | No narration: Kaiku's own voice carries the real shot (14 s in the plan). |
| 0:34.6–0:49.6 | Talk: she types "I walked to the lake today."; Kaiku answers | No narration over the reply (0:39.5–0:50.2). This is the plan's fallback, not the shot. |
| 0:49.6–1:11.2 | Today's path, the weather dials, Lantern (the flame lights, she touches, a star rises), the sky she lit, Seed shelf, "All done for today" | "A two-minute game is also a reaction-time reading, compared only with her own usual." (The plan says Firefly and one minute; the picture is Lantern.) |
| 1:11.2–1:13.2 | CARD: walk with the glasses | "Outside, Kaiku moves to her glasses: head up, hands free, phone in her pocket." (the filmed shot runs 15 s) |
| 1:13.2–1:16.8 | Your days → "Today, so far" | Not in the plan. Let the glasses line run over it, or: "She can see what was noticed today, and what is shared." |
| 1:16.8–1:18.8 | CARD: the robot ritual | "At home the robot speaks first: three turns of an ear, one breath, a drum, and no typing." (the filmed shot runs 15 s) |
| 1:18.8–1:20.8 | CARD: Mac menu bar | "Her Mac adds rhythm only: breaks and late nights, never content." |
| 1:20.8–1:31.8 | Dashboard, simulated record: the status sentence, signal groups, the Trends chart read day by day | "Each group is compared with her own baseline, and a fixed rule that anyone can read, not a model, combines them; missing data never reads as stable." |
| 1:31.8–1:53 | Kaiku's review: Gemma's reading of the whole record, the agent trace; the knowledge graph with a node picked; the Daily account with the reflections strip | "For her practitioner, Gemma chooses the evidence and points to the record behind every sentence; the numbers are written by code." (No cited record is opened in this take.) |
| 1:53–1:55 | CARD: the follow-up (care action) | "One click records the follow-up, and the days that follow are there to compare." |
| 1:55–1:57 | CARD: end card | "Kaiku: a friend on your desk, a voice in your ear, a clearer record for your care team." |

When the filmed shots replace their cards at the planned lengths (10 + 14 + 15 + 15 + 6 + 6 + 4 s = 70 s), the
builder stops with "longer than 1:58": shorten the phone pieces (first run to 9 s, games to 9 s), empty `TALK`
and `DAYS`, and bring the dashboard to about 27 s. The total must stay under 2:00.
