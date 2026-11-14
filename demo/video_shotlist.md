# Video shot list (hard cap 2:00)

The shot table, timings, narration and per-shot fallbacks are in
[`docs/demo-narrative.md`](../docs/demo-narrative.md) ("The video (1:55)"). Do not copy it here: one source.
This page says which recording covers each shot and what still has to be filmed by hand.

Recording checklist:

- `make demo-reset` on the recording day, so the sixteen days end yesterday and today is empty.
- Dashboard shots carry the small caption "simulated record". Never show a home ID or the words used for fixtures.
- Narrate the state that is on screen. The record opens on needs a call (acknowledged); the first flag is on day 11.
- For the "following days" shot, record a real check-in and walk on a linked device, or run
  `make live-day ARGS="--url http://127.0.0.1:8000 --kind good"` and caption it as simulated.
- Export at 1:55 to 1:59.

## Clips that exist (`demo/recordings/`, gitignored; how to remake them: `demo/AGENTS.md`)

Every clip is a real run of the real app against a local service holding Aino's simulated record. Each clip has
`<clip>-sheet.png` (twelve frames) and `<clip>-steps.txt` (the time code of every chapter named below). iPhone
clips are the iPhone 17 Pro simulator at real speed, without sound, starting on the home screen as the app opens.

Three of them hold a conversation (marked **typed, real replies**): her lines are typed through a Debug launch
argument with the app's microphone permission revoked, and every answer is Gemini Live's own reply in that take,
from a private service with the model key. Nothing Kaiku says in them was written by anyone. The other clips
make no model calls.

| Clip | What the person does | Chapters (`-steps.txt`) |
|---|---|---|
| `iphone-1-first-run.mp4` (1:43) | Fresh install of a build with a configured service: welcome, what Kaiku is and is not, "Connected to your Kaiku service", the choices (turns "Keep our conversations" on), permissions (microphone, nudges), Kaiku's hello spoken in its voice, the practice dial, "You did it", Today. Recorded at 12:16, before the check-in became a chat; first run itself has not changed since. | `welcome` `what-kaiku-is` `nearby-service` `choices` `permissions` `hello-and-first-task` `you-did-it` `today` |
| `iphone-2-today-path.mp4` (6:53) **typed, real replies** | Today with Kaiku's one invitation and the path at 0 of 4; the first stop as a small chat on an ordinary day (three typed lines, Kaiku answers each and wraps it up itself: "Good to see you"); back on Today the stop is ticked; Kaiku's suggestion (a walk in this take: over a minute on the phone, no conversation because there is no microphone); Lantern played to its end screen; Seed shelf played to its end screen; "All done for today". | `today` `invitation` `check-in` `check-in-chat` `line-1` `line-2` `line-3` `check-in-end` `suggestion` `walking` `walk-summary` `lantern` `rotating-game` `all-done` |
| `iphone-2-today-path-dials.mp4` (5:51) | The take of 12:16, when the first stop was three dials. Kept only because the Seed shelf GIF is cut from it (the game has not changed). | `today` `weather-check` `suggestion` `breathing` `lantern` `rotating-game` `all-done` |
| `iphone-3-today-so-far.mp4` | Your days (now under the History tab): "Today, so far" (what was noticed, from which device, what is shared), "See every detail", the garden. | `your-days` `today-so-far` `what-kaiku-saw` |
| `iphone-4-talk.mp4` (1:32) **typed, real replies** | Talk is a call: it opens with the tab and Kaiku says hello; she types a line and Kaiku answers; she mutes Kaiku and the answer to her next line still comes as captions ("Kaiku is speaking · muted"); she locks the phone; her third line and Kaiku's answer arrive as the caption of the Lock Screen's bar; "End" on the bar; back in the app: "Call ended." and "Call Kaiku". | `talk` `call` `line-1` `mute-kaiku` `unmute-kaiku` `lock-screen` `end-on-lock-screen` `back-in-app` (the second `line-1` is her second line: the tour numbered it wrongly in this take) |
| `iphone-5-you-glasses-check.mp4` | You: opens the sharing choices, turns Walks off and on, opens Glasses check with no glasses connected, runs the self-test. | `you` `sharing-choices` `glasses-check` `self-test` |
| `iphone-7-glasses-walk-simulated.mp4` (1:58) | The walk with simulated glasses: Calm, Playful, Chatty tried where the walk starts (each shows its one line), Playful chosen; on the walk "Found one" starts the spotting game ("Bright things 1 of 3", then 2); the Dynamic Island shows the same count and takes the third find; the walk's summary. No conversation: the simulator has no microphone for it, and the walk screen says "Kaiku can't use the microphone". | `walk-start` `style-playful` `style-chatty` `style-calm` `style-chosen` `walking` `spotting-game` `island` `endwalk` `walk-summary` |
| `iphone-8-checkin-hard-day.mp4` (1:58) **typed, real replies** | Today, then the first stop on a hard day: four typed lines. Kaiku answers the first two by staying with what she said, answers "What do you think?" with one offer (sitting quietly together, or some space), and answers her thanks on the Lock Screen's bar after she has locked the phone; "End" on the bar. | `today` `check-in` `check-in-chat` `line-1` `line-2` `line-3` `lock-screen` `end-on-lock-screen` `back-in-app` |
| `web-dashboard.mp4` | The practitioner dashboard in one viewport: default view, reading days along the Trends chart, Kaiku's review and its agent trace, the knowledge graph maximised with a node selected, a day opened in the Daily account, a panel collapsed and another moved. Recorded from the public deployment with `--allow-model`: the review is the cached one written by Gemma. | `default-view` `trends-hover` `review` `gemma-reading` `agent-trace` `knowledge-graph` `graph-node` `daily-account` `reflections` `collapse-and-move` |
| `mac-snapshots/mac-*.png` | Stills of the Mac panes drawn by the app itself (not a screen recording: see below). | |

What was said in the three conversation takes is in `draft-cut-narration.md` (the hard day) and in each take's
`raw/<clip>.log` (`DEMO-SAID`, `DEMO-LOCK`).

## Shot by shot

| Narrative shot | Covered by | Still needed from a person |
|---|---|---|
| 0:00–0:10 kitchen table | nothing | Film it: appointment card, phone face down. |
| 0:10–0:17 first run | `iphone-1-first-run.mp4`: `what-kaiku-is` and `choices` | The simulator cannot find a service nearby, so the clip uses a build with a configured service (the connect step shows `127.0.0.1`: the cut skips it). For "found nearby" record it on the iPhone: recipe 1. |
| 0:17–0:33 the check-in on a hard day, then the Lock Screen | stand-in: `iphone-8-checkin-hard-day.mp4` from `line-1`, `line-3` and `lock-screen` (typed, real replies, silent) | Her real voice and Kaiku's: recipe 2. |
| 0:33–0:41 Lantern | `iphone-2-today-path.mp4` from `lantern` (the lantern lights, she touches, a star rises; the sky she lit just before `rotating-game`) | Covered. |
| 0:41–0:57 glasses outdoors | stand-in: `iphone-7-glasses-walk-simulated.mp4` (the styles, the count on the phone and in the island; simulated glasses, no conversation) | The walk itself, with "Is that your favourite tree up there?" and a spoken count: recipe 3. |
| 0:57–1:12 robot ritual | nothing (twin run: `scripts/record_robot_demo.sh`, data only, no picture) | Film the robot: recipe 4. |
| 1:12–1:20 Mac quick talk | stand-in: the three stills `docs/media/mac-quick-talk-*.png` (drawn by the app from seeded states: the words in them are layout text) | The agents' terminal has no Screen Recording permission, and nobody has pressed the keys yet. Record it: recipe 5. |
| 1:20–1:32 signal groups → one state, timeline | `web-dashboard.mp4`: `default-view` and `trends-hover` | Add the caption "simulated record". Retake after the dashboard's last polish (one command, below). |
| 1:32–1:45 Gemma's review, evidence, graph | `web-dashboard.mp4`: `review`, `agent-trace`, `knowledge-graph`, `graph-node` | Covered: the take shows the cached review written by Gemma. No cited record is opened in it. |
| 1:45–1:51 care action, following days | nothing (the take is read-only and blocks writes) | Record by hand on the dashboard: Care actions & notes → record a follow-up; then `make live-day` and reload. |
| 1:51–1:55 end card | nothing | Film robot, phone and glasses on the table. |

## Recipes for the shots that need hands

1. **iPhone first run (real phone).** Delete Kaiku from the phone. `make demo` on the Mac, same Wi-Fi. Control
   Centre → long-press Screen Recording → Microphone **on** → Start. Open Kaiku, go through setup: the service
   appears under "Nearby Kaiku services" → Connect; leave the choices as she would; allow the microphone and
   nudges; turn the practice dial; "Go to Today". Stop from the red pill. AirDrop the file to the Mac.
   (To land on Aino's record instead of a new one, install with `apps/apple/scripts/run_on_iphone.sh aino`.)
2. **The check-in on a hard day, in her real voice, ending on the Lock Screen (iPhone).** Needs `GEMINI_API_KEY`
   in `.env`, `make demo`, the microphone allowed for Kaiku; one paid Live call, which settles to the minutes
   used when it is ended. Screen recording with Microphone on. Today → the first stop → say the day is hard →
   let Kaiku answer → one more sentence → lock the phone → say one more thing → "End" on the Lock Screen's bar.
   Step by step, with what to expect: `video_making.md` G2.
3. **Glasses walk.** Follow `docs/glasses-test.md` exactly (the ten steps first, then "Walking together"). Two
   cameras: the iPhone screen recording (Microphone on; it records what the phone hears, not the glasses' speakers)
   and a second phone filming her putting the glasses on and the phone going into a pocket. For the cut: Playful
   chosen where the walk starts, a favourite named on one walk and recognised on the next, a spotting game counted
   aloud and on the card, the glasses off and on once, End walk after at least a minute. `video_making.md` G3.
   If the audio route was not accepted on the device, film Glasses check showing "connected" and say "voice over
   Bluetooth" (the narrative's fallback).
4. **Robot ritual.** `make broker`, `make hub`, the real board on the desk (`firmware/atech-head/AGENTS.md` for
   what has passed its bench). Film with a phone on a stand, 4K 30, landscape, room quiet: walk up → eyes open →
   three turns of the ear dial → chest glows for one breath → drum on the head → goodbye. Anything that runs on the
   twin gets the caption "simulated hardware".
5. **Quick talk on the Mac.** The built app is `apps/apple/build/QuickTalk/Kaiku.app`. QuickTime Player → New
   Screen Recording → Record Entire Screen (the bar is at the left edge, the island at the notch). A document in
   front, two taps of Control, "I'm not feeling too well", the captions of both, the chevron, the notch showing the
   call, Esc. Step by step: `video_making.md` G1. QuickTime does not record Kaiku's voice: the captions carry it.
   The menu bar popover (category minutes, breaks, the pause switch) is no longer a shot of the 1:55 video.

## README GIFs, Kaiku's voice, the draft cut

- `uv run python scripts/record_gifs.py [name ...]` → `docs/media/*.gif` (committed): `ios-first-run`,
  `ios-today-path`, `ios-seed-shelf`, `ios-talk`, `ios-checkin-hard-day`, `ios-today-so-far`, `ios-glasses-check`,
  `web-dashboard`, `mac-app`. Each is a few pieces of one clip; the pieces are picked by eye and listed at the top
  of the script. `ios-today-path`, `ios-talk` and `ios-checkin-hard-day` are cut from the three typed takes with
  real replies (2.0 to 2.3 MB each, 340 px wide). `ios-seed-shelf` still comes from the 12:16 take
  (`iphone-2-today-path-dials`). `mac-app` is the app's own renders of its panes until a real screen recording
  (`mac-tour.mp4`) exists.
- `uv run python scripts/record_voice.py --url <service>` → `demo/recordings/voice/*.wav`: the fixed lines the
  app plays, for the silent simulator clips (cached lines cost nothing; a new line is one capped TTS call). What
  Kaiku says in a conversation is a Live call's own audio and is not in any simulator clip.
- `uv run --with pillow python demo/draft_cut.py` → `recordings/kaiku-draft-cut.mp4` (1:49, with Kaiku's voice
  on its first-run hello) + `-sheet.png` + `-timeline.txt`. Filmed shots dropped into `recordings/` as
  `shot-01-cold-open.mp4`, `shot-03-voice.mp4`, `shot-05-glasses.mp4`, `shot-06-robot.mp4`, `shot-07-mac.mp4`,
  `shot-10-care-action.mp4`, `shot-11-end.mp4` replace their cards and stand-ins. Narration by time code, what
  each stand-in is and what the sound is: `draft-cut-narration.md`.
- The step-by-step guide for filming the remaining shots is the git-ignored `video_making.md` at the repo root
  (section G for everything added on 14 Nov evening).

## Known problems (2026-11-14 evening, iPhone 17 Pro simulator, build of commit 0dd2e25)

Seen while recording, with pictures in `recordings/bugs/1114-*`. None of it is in a published clip.

1. **A hidden conversation behind the check-in's end screen.** After "Up next" on the end screen the check-in
   stays on the Today tab's stack. Coming back to that tab shows "Good to see you" again and asks the service
   for a new conversation behind it, with no call bar on screen (seen: the service minted a Live session at that
   moment; by the code it would also open the microphone where that is allowed, which these takes could not
   show). Left a few seconds later, the session was never closed and kept its whole $0.60 reservation
   (`1114-hidden-check-in-session-ledger.txt`). The tour now goes back to Today instead of "Up next".
2. **After "End" on the Lock Screen the check-in says nothing about it.** Back in the app the chat is there with
   no call bar, no "Call ended" and no way on (`1114-checkin-after-end-on-lock-screen.png`). Talk says "Call
   ended." and offers "Call Kaiku".
3. **Kaiku went silent on a hard day** in the first of two takes: after its first answer it said nothing to two
   further typed lines (21 s each, the call bar never left "Microphone is off"), and five seconds after the phone
   was locked the line dropped ("Waking Kaiku up…", then "Kaiku can't talk right now"; the episode ended as
   `offline`). In the second take her lines spoke to Kaiku directly ("Is that silly, Kaiku?", "What do you
   think?") and every one was answered (`1114-checkin-hard-day-kaiku-silent-then-dropped.mp4`).
4. **"That's it" is below the fold** on the check-in when the service has no live voice: the three dials fill a
   6.3-inch screen and nothing shows that the page goes on; a drag that starts on a dial did not move it
   (`1114-checkin-thats-it-below-the-fold.png`).
5. The simulator asks about Live Activities twice on a fresh install ("Allow", and the next time "Always
   Allow"), on top of the Lock Screen's bar: two throwaway takes on the scripted Live answer both.
6. A straight apostrophe in a typed line (`-kaikuTalkSay`) reaches the app as shell quoting and is shown
   garbled; the tour's lines have none. A recording tool's problem, not the app's.
7. First run on the simulator never lists a service "nearby" (no Bonjour): the clip uses a build with a
   configured service, whose connect step shows `127.0.0.1` and the service URL. `testA_FirstRun` was not run
   again: it grants the microphone, and the simulator's microphone is the Mac's.
8. The simulator recording runs a few seconds ahead of the clock the test prints, and not steadily at the
   start: the GIFs and the cut use times picked by eye for the phone clips.
9. The terminal the agents use may not record the screen: no Mac video, and the Mac GIF is in-app renders
   (Talk and You are left out of it: their text field and switches are drawn as placeholders).
10. Nobody has listened to the voice file under the cut (`recordings/voice/welcome.hello.wav`).
11. The Talk and hard-day takes were built minutes before the call bar got its moving lines beside "Kaiku is
    speaking"; they show the still speaker icon there. The today-path take has the new one.
