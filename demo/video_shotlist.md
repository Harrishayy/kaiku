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

Every clip is a real run of the real app against a local service holding Aino's simulated record, with no
model calls: where Kaiku's voice would play, its words are on screen. Each clip has `<clip>-sheet.png` (twelve
frames) and `<clip>-steps.txt` (the time code of every chapter named below). iPhone clips are the iPhone 17 Pro
simulator at real speed, without sound, starting on the home screen as the app opens.

| Clip | What the person does | Chapters (`-steps.txt`) |
|---|---|---|
| `iphone-1-first-run.mp4` | Fresh install: welcome, what Kaiku is and is not, "Continue without connecting" (the simulator finds no service nearby), the choices (turns "Keep our conversations" on), permissions (microphone, nudges), Kaiku's hello, the practice dial, "You did it", Today. | `welcome` `what-kaiku-is` `nearby-service` `choices` `permissions` `hello-and-first-task` `you-did-it` `today` |
| `iphone-2-today-path.mp4` (6:15) | Today's path from 0 of 4 to "All done for today": three weather dials, Kaiku's suggestion (a one-minute walk on the phone in this take), Lantern played to its end screen, Seed shelf played to its end screen. | `today` `weather-check` `suggestion` `walking` `walk-summary` `lantern` `rotating-game` `all-done` |
| `iphone-3-today-so-far.mp4` | Your days: "Today, so far" (what was noticed, from which device, what is shared), "See every detail", the garden. | `your-days` `today-so-far` `what-kaiku-saw` |
| `iphone-4-talk.mp4` | Talk: taps the one voice control, the app says in words why the voice is not there, she types instead and gets the short scripted reply. | `talk` `voice-state` `typing` `reply` |
| `iphone-5-you-glasses-check.mp4` | You: opens the sharing choices, turns Walks off and on, opens Glasses check with no glasses connected, runs the self-test. | `you` `sharing-choices` `glasses-check` `self-test` |
| `web-dashboard.mp4` | The practitioner dashboard in one viewport: default view, reading days along the Trends chart, Kaiku's review and its agent trace, the knowledge graph maximised with a node selected, a day opened in the Daily account, a panel collapsed and another moved. Recorded from the public deployment with `--allow-model`: the review is the cached one written by Gemma. | `default-view` `trends-hover` `review` `gemma-reading` `agent-trace` `knowledge-graph` `graph-node` `daily-account` `reflections` `collapse-and-move` |
| `mac-snapshots/mac-*.png` | Stills of the Mac panes drawn by the app itself (not a screen recording: see below). | |

## Shot by shot

| Narrative shot | Covered by | Still needed from a person |
|---|---|---|
| 0:00–0:10 kitchen table | nothing | Film it: appointment card, phone face down. |
| 0:10–0:19 first run | `iphone-1-first-run.mp4`: `nearby-service` → `choices` → `permissions` → `hello-and-first-task` | The simulator cannot find the service nearby, so the clip continues without connecting. For "found nearby" record it on the iPhone: recipe 1. |
| 0:19–0:33 Talk, Kaiku's voice | fallback only: `iphone-4-talk.mp4` from `typing` (6 s of typed chat) | The real voice: recipe 2. |
| 0:33–0:42 a game as a reading | `iphone-2-today-path.mp4` from `lantern` (the lantern lights, she touches, a star rises; end screen at the next chapter) | The narrative names Firefly; today's path now leads with Lantern, which is the reaction-time game. Say "Lantern", or record Firefly from Play (`TESTS=testF_Firefly:iphone-6-firefly`). |
| 0:42–0:57 glasses outdoors | fallback only: `iphone-5-you-glasses-check.mp4` from `glasses-check` (states with nothing connected) | The walk itself: recipe 3. |
| 0:57–1:12 robot ritual | nothing (twin run: `scripts/record_robot_demo.sh`, data only, no picture) | Film the robot: recipe 4. |
| 1:12–1:18 Mac menu bar | stills in `mac-snapshots/` | The agents' terminal has no Screen Recording permission. Record it: recipe 5. |
| 1:18–1:31 signal groups → one state, timeline | `web-dashboard.mp4`: `default-view` and `trends-hover` | Add the caption "simulated record". Retake after the dashboard's last polish (one command, below). |
| 1:31–1:45 Gemma's review, evidence, graph | `web-dashboard.mp4`: `review`, `agent-trace`, `knowledge-graph`, `graph-node` | Covered: the take shows the cached review written by Gemma. No cited record is opened in it. |
| 1:45–1:51 care action, following days | nothing (the take is read-only and blocks writes) | Record by hand on the dashboard: Care actions & notes → record a follow-up; then `make live-day` and reload. |
| 1:51–1:55 end card | nothing | Film robot, phone and glasses on the table. |

## Recipes for the shots that need hands

1. **iPhone first run (real phone).** Delete Kaiku from the phone. `make demo` on the Mac, same Wi-Fi. Control
   Centre → long-press Screen Recording → Microphone **on** → Start. Open Kaiku, go through setup: the service
   appears under "Nearby Kaiku services" → Connect; leave the choices as she would; allow the microphone and
   nudges; turn the practice dial; "Go to Today". Stop from the red pill. AirDrop the file to the Mac.
   (To land on Aino's record instead of a new one, install with `apps/apple/scripts/run_on_iphone.sh aino`.)
2. **Kaiku's real voice (iPhone, then Mac).** Needs `GEMINI_API_KEY` in `.env` and `make demo`; each
   conversation is a paid Live call (limit 5 minutes). iPhone: screen recording with Microphone on, as above; Talk →
   "Talk with Kaiku" → say "Good morning, Kaiku." → let it answer → interrupt it once → mute. Mac: QuickTime Player →
   File → New Screen Recording → Options → Microphone: MacBook Microphone → record the Kaiku window only. Kaiku's
   own voice is not in a QuickTime recording unless a loopback device is installed: film the Mac with the phone, or
   use the iPhone take for sound.
3. **Glasses walk.** Follow `docs/glasses-test.md` exactly (5 minutes, real Ray-Ban Meta). Two cameras: the iPhone
   screen recording (Microphone on; it records what the phone hears, not the glasses' speakers) and a second phone
   filming her putting the glasses on and the phone going into a pocket. Walk at least one full minute, say the
   three sentences, take the glasses off and on once, End walk, then show Your days → "Today, so far".
   If the audio route was not accepted on the device, film Glasses check showing "connected" and say "voice over
   Bluetooth" (the narrative's fallback).
4. **Robot ritual.** `make broker`, `make hub`, the real board on the desk (`firmware/atech-head/AGENTS.md` for
   what has passed its bench). Film with a phone on a stand, 4K 30, landscape, room quiet: walk up → eyes open →
   three turns of the ear dial → chest glows for one breath → drum on the head → goodbye. Anything that runs on the
   twin gets the caption "simulated hardware".
5. **Mac menu bar and island.** QuickTime Player → New Screen Recording → "Record Selected Portion" around the menu
   bar and the Kaiku popover. Open the popover (category minutes, breaks, the pause switch), flip pause on and off.
   Or give Terminal Screen Recording + Accessibility permission (System Settings → Privacy & Security) and run
   `KAIKU_TEST_CLOUD=<service> apps/apple/scripts/record_app_demo.sh mac && apps/apple/scripts/record_app_demo.sh post`.

## Draft cut

`uv run --with pillow python demo/draft_cut.py` → `recordings/kaiku-draft-cut.mp4` (1:51) + `-sheet.png` +
`-timeline.txt`; narration by time code and the list of placeholder seconds: `draft-cut-narration.md`.

## Known problems (2026-11-14, iPhone 17 Pro simulator, build 7421f1c)

Checked on screen and gone: the Talk hang on tapping the message field, the doubled voice-unavailable message,
today's path losing a finished stop, the "Mac" label on iPhone games, the Motion prompt on "Your choices", "That
was my voice" without a voice, raw JSON in Glasses check, the typed service link in setup ("Continue without
connecting" is the main button). Still there (frames in `recordings/bugs/after-fix-*.png`):

1. Scrolled content still runs under the clock and Dynamic Island (Your days, What Kaiku saw today, You, Glasses
   check, the longer setup steps).
2. Talk with the keyboard open leaves about one line of conversation visible: the reply is cut off under the
   voice button.
3. Seed shelf's end picture is three bare lines ("Look at all those sprouts" with no sprouts) when the frame was
   taken, four seconds after the round.
4. What Kaiku saw today still lists its rows in a monospaced face.
5. Glasses check self-test says "Played through Speaker" on a service without a voice (not checked whether a
   cached line really played).
6. Recorder: chapter codes in `iphone-1-first-run-steps.txt` run about 6 to 9 s late (the simulator recording's
   first seconds are not steady); the other clips are within about 2 s.
