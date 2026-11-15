# Robot test plan: how to know each thing works

Two parts. **A** is checked by a program: it sends one command, waits for the proof on the robot's own message bus,
and prints PASS or FAIL. **B** is you, your voice and your hands, with one line of proof to look up after each step.
Do A first: if a part is off or a motor does not move, B cannot work.

Before either: the broker, the hub and the service run on the Mac (`make doctor`), the head and the sensor board
are powered and on the same Wi-Fi, and the phone is on the Kaiku bot page with Robot microphone on.

## A. Machine checks (`make robot-bench`)

```
make robot-bench                          # parts, turn, buzzer, camera, face-signs
make robot-bench ARGS="parts turn"        # only some
make robot-bench ARGS="arm"               # needs your hand: press the ear when it says so
make robot-bench ARGS="--with-sound turn-waits-for-speaker"
make robot-bench ARGS="--synthetic-face follow"
```

It prints one line per check: `PASS` (proved), `FAIL` (not), `LOOK` (no machine can check it: you must see or hear
it), `SKIP`. The run fails only on a FAIL. Do not run it in the middle of a conversation you care about: it turns
the head and switches the camera, and leaves the camera off.

| Step | What it sends | PASS means | What you must see or hear (LOOK) |
|---|---|---|---|
| `parts` | nothing | head, sensor board and hub each sent a heartbeat in the last 12 s; prints firmware version, `camera_ok`, the hub's `talk` and `mic_source` | — |
| `turn` | a turn left, then right | the head reported `moving` within 3 s and `still` after, both times | it turned to YOUR left first, then your right. Wrong way round: flip `[follow_track] sign` in `config/kaiku.toml` and restart the hub |
| `buzzer` | the `ok` chime | — | a short sound from the sensor board |
| `camera` | camera off, then on | off: no face and no distance numbers for 5 s. on: numbers back within 8 s | the camera's own light goes out, then comes on. It is left OFF at the end |
| `face-signs` | count for 5 s | one result within 12 s (coverage 0 = nobody in view, still a pass) | — |
| `turn-waits-for-speaker` (`--with-sound`) | 2 s of a quiet tone and a turn in the middle | the motor started only after the tone ended | the head stays still during the tone, then turns |
| `follow` (`--synthetic-face`) | a made-up face at the right edge | the hub asked the head to turn toward it | the head makes small turns (the head must be awake: in a talk or a check-in step; the hub will act on the made-up face) |
| `arm` | arms the drums, later ends the check-in | after YOUR press the head is in the drum step; after `end` it is at rest | wake the head first; press the ear within 20 s of the prompt |

There is no `ring` step any more. The ear ring is orange at rest and blue while the microphone streams; the head
(firmware 0.9.0, D66) ignores a colour command, so there is nothing for the bench to send. Look at the ring in
part B, step 2.

**This part is dated.** The last run on the real robot was on 2026-11-15 with head firmware 0.8.0 and the bench as
it then was (it still had the ring step): 8 passed, 0 failed, 9 to look at. Both turns reported moving within 0.2 s
and still after 0.65 s; camera off gave 0 messages in 5 s and on gave numbers after 2.3 s; the 5 s count came back
after 5.2 s with 26 frames looked at. The bench has not been run against firmware 0.9.0. Run it again before
relying on it.

## B. With your voice and hands

**Written for D66 (head firmware 0.9.0, 2026-11-15): a press opens a talk, and the check-in starts only when you
ask for it. This table is the plan, not a result: nothing of D66 has been tried by a person on the robot yet
(`docs/progress.md`, 2026-11-15 02:50 UTC). Steps 1 to 4, 9, 11 and 14 changed with D66.**

Proof commands are run on the Mac in the repo folder. `logs/hub.log` is the hub's own log.
Quick state at any time: `make robot-bench ARGS="parts"` (the hub line shows `talk` and `mic_source`).

| # | Do or say | What must happen, and how soon | Proof |
|---|---|---|---|
| 1 | Press the ear once (head at rest). | It chirps and greets: "Hello. Press my ear if you'd like to talk." The invitation is spoken at most every 5 minutes. | `parts`: head `step: greet` |
| 2 | Press the ear again within 60 s. | The conversation opens within about 3 s and the head rests in its talk step: no question, no check-in step. The ear ring goes from orange to blue while the microphone streams. | `rg '"follow_conversation"' logs/hub.log \| tail -1` says `opening`; `parts`: head `step: talk`, hub `talk: open` |
| 3 | Check the microphone. | The phone's line reads "Kaiku is listening through this device". | `parts`: `mic_source: phone` |
| 4 | Wait for "shall I have my camera on while we talk?" and say **yes** within 12 s. | She says "Camera on. Only numbers, never a picture.", the buzzer sounds and the camera's own light comes on (the ring does not change for the camera). Then one line, "I'm here. What's on your mind?", and she listens. She never asks about the camera again in this conversation. | `rg -c '"camera_choice"' logs/hub.log` went up by exactly 1; `rg '"camera_choice"' logs/hub.log \| tail -1` shows `"on": true` |
| 4b | (Another conversation) say **no**, or say nothing for 12 s. | "Okay, the camera stays off." No camera light. | `"on": false`, or `rg '"camera_not_answered"' logs/hub.log \| tail -1` |
| 4c | Talk about anything for a moment. Press the ear once while you do. | She answers what you said. The press starts nothing, and she does not ask the check-in's questions by herself. | `parts`: head still `step: talk` |
| 4d | Say "let's do the check-in." | The head goes to the mood question and says it itself. | `rg '"checkin_started"' logs/hub.log \| tail -1`; `parts`: head `step: mood` |
| 5 | Mood question: **say** your answer ("about a two"). | Within about 3 s the head moves to the energy question by itself. | `rg 'obs.self_report' logs/hub.log \| tail -1`; `parts`: head `step: energy` |
| 6 | Energy question: **turn the ear**, then press once. | The head moves to the sleep question. A second press within 0.7 s does nothing. | `parts`: head `step: sleep` |
| 7 | Say "let's play the drums." Do **not** press. | She asks you to press her ear. Nothing starts. After 20 s she says it did not start. | `rg '"activity_asked"\|"activity_not_confirmed"' logs/hub.log \| tail -2` |
| 8 | Say it again, then press the ear within 20 s. | The head goes straight to the drums and the rhythm game starts. | `rg '"activity_confirmed"' logs/hub.log \| tail -1`; `parts`: head `step: drum` |
| 9 | In a dial step, start talking about something else ("actually, I wanted to tell you about my sister"). | The check-in waits: the head goes back to its talk step and she talks with you without bringing the check-in up again. Say "let's continue" and the head returns to the step that waited. | `rg '"checkin_paused"\|"checkin_resumed"' logs/hub.log \| tail -2`; `parts`: head `step: talk`, then the step that waited |
| 9b | Say "make your light white." | Nothing changes: the ring's colour cannot be set (D66). It stays orange at rest and blue while the microphone streams. | you see it |
| 10 | Say "turn your head left." | She says a short line, then the head turns to your left just after she stops speaking. Not during the rhythm game. | you see it; `turn` in part A proves the motor |
| 11 | With the camera on (step 4), in the talk or in a check-in step, move your face slowly to the edge of what the camera sees. | Within about 2 s one short nudge toward you (full speed, about 150 ms; the head has no position sensor); again every 2 s while you stay at the edge. Never while she speaks, never in the rhythm game. | you see it. If it turns AWAY: flip `[follow_track] sign`. If nothing after three tries: `rg '"follow_track"' logs/hub.log \| tail -1` says it gave up (the camera is not on the part that turns) |
| 12 | With the camera on, say "photo time." | "Photo time!", a chime, about 8 s of counting, "All done. No picture was kept, only a few numbers." | `rg 'obs.face_signs' logs/hub.log \| tail -1` |
| 12b | With the camera off (4b), say "photo time." | She says it needs the camera. Nothing is counted. | no new `obs.face_signs` line |
| 13 | With the camera on: smile clearly for 10 s, then keep a still, unsmiling face for the next 10 to 20 s. | She may ask one short open question about how you are. She does not mention your face or the camera. At most one such note every 90 s, three per conversation. | `rg '"expression_lower"' logs/hub.log \| tail -1` (the note was sent; whether she asks is hers to judge) |
| 14 | In any step, say "let's stop for today." | The head goes back to rest within about 3 s, the camera light goes out, the microphone closes (the ring is orange again). | `rg '"ritual_done"' logs/hub.log \| tail -1` says `ended_early` (`skipped` when no check-in step was opened in this wake); `parts`: head `step: idle`, `talk: closed` |
| 15 | During all of it, open **Transcript** under Robot microphone on the phone. | Both sides appear as text, newest at the bottom, within about a second of being said. | you see it; your lines appear only while `mic_source: phone` |

If a step fails, note its number, the time, and the output of `make robot-bench ARGS="parts"`.

## C. On the iPhone: the visible-expression cue in the check-in chat

The app must have been started from the Mac with `-kaikuExpressionDebug YES` for the on-screen proof line.

| # | Do | What must happen | Proof |
|---|---|---|---|
| 1 | Open the check-in chat. When asked about the camera, choose "Keep it on". | The camera runs during the chat (the consent wording changed, so it asks once). | the system's camera dot |
| 2 | Talk normally for about 8 s. | Nothing. It is learning your resting face. | — |
| 3 | Hold a clearly lowered face (or a clear smile) for about 5 s. | The debug line on the check-in screen names the cue (`lower`, `tense` or `brighter`). | the debug line |
| 4 | Stay quiet for a moment. | Once both of you are quiet, Kaiku may ask one short open question. She never says she saw your face. | you hear it; at most one cue every 90 s, three per conversation |

Not on the Talk screen (no camera runs there) and not calibrated on the Mac.
