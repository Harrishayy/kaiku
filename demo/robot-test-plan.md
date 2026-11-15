# Robot test plan: how to know each thing works

Two parts. **A** is checked by a program: it sends one command, waits for the proof on the robot's own message bus,
and prints PASS or FAIL. **B** is you, your voice and your hands, with one line of proof to look up after each step.
Do A first: if a part is off or a motor does not move, B cannot work.

Before either: the broker, the hub and the service run on the Mac (`make doctor`), the head and the sensor board
are powered and on the same Wi-Fi, and the phone is on the Kaiku bot page with Robot microphone on.

## A. Machine checks (`make robot-bench`)

```
make robot-bench                          # parts, ring, turn, buzzer, camera, face-signs
make robot-bench ARGS="parts turn"        # only some
make robot-bench ARGS="arm"               # needs your hand: press the ear when it says so
make robot-bench ARGS="--with-sound turn-waits-for-speaker"
make robot-bench ARGS="--synthetic-face follow"
```

It prints one line per check: `PASS` (proved), `FAIL` (not), `LOOK` (no machine can check it: you must see or hear
it), `SKIP`. The run fails only on a FAIL. Do not run it in the middle of a conversation you care about: it turns
the head, changes the ring and switches the camera, and leaves the camera off.

| Step | What it sends | PASS means | What you must see or hear (LOOK) |
|---|---|---|---|
| `parts` | nothing | head, sensor board and hub each sent a heartbeat in the last 12 s; prints firmware version, `camera_ok`, the hub's `talk` and `mic_source` | — |
| `ring` | ring colour white, green, orange, 2 s apart | — (firmware 0.8.0 sends nothing back) | the ear ring changes white → green → orange |
| `turn` | a turn left, then right | the head reported `moving` within 3 s and `still` after, both times | it turned to YOUR left first, then your right. Wrong way round: flip `[follow_track] sign` in `config/kaiku.toml` and restart the hub |
| `buzzer` | the `ok` chime | — | a short sound from the sensor board |
| `camera` | camera off, then on | off: no face and no distance numbers for 5 s. on: numbers back within 8 s | the camera's own light goes out, then comes on. It is left OFF at the end |
| `face-signs` | count for 5 s | one result within 12 s (coverage 0 = nobody in view, still a pass) | — |
| `turn-waits-for-speaker` (`--with-sound`) | 2 s of a quiet tone and a turn in the middle | the motor started only after the tone ended | the head stays still during the tone, then turns |
| `follow` (`--synthetic-face`) | a made-up face at the right edge | the hub asked the head to turn toward it | the head makes small turns (it needs an open check-in; the hub will act on the made-up face) |
| `arm` | arms the drums, later ends the check-in | after YOUR press the head is in the drum step; after `end` it is at rest | wake the head first; press the ear within 20 s of the prompt |

Run of 2026-11-15 on the real robot (head firmware 0.8.0): 8 passed, 0 failed, 9 to look at. Both turns reported
moving within 0.2 s and still after 0.65 s; camera off gave 0 messages in 5 s and on gave numbers after 2.3 s; the
5 s count came back after 5.2 s with 26 frames looked at.

## B. With your voice and hands

**As of D63 (2026-11-15). Re-check this table after the "talk first, check-in only on request" change: steps 1 to 4
and 11 are the ones it alters.**

Proof commands are run on the Mac in the repo folder. `logs/hub.log` is the hub's own log.
Quick state at any time: `make robot-bench ARGS="parts"` (the hub line shows `talk` and `mic_source`).

| # | Do or say | What must happen, and how soon | Proof |
|---|---|---|---|
| 1 | Press the ear once (head at rest). | It chirps and greets; the invitation is spoken at most every 5 minutes. | `parts`: head `step: greet` |
| 2 | Press the ear again within 60 s. | The conversation opens within about 3 s. | `rg '"follow_conversation"' logs/hub.log \| tail -1` says `opening`; `parts`: `talk: open` |
| 3 | Check the microphone. | The phone's line reads "Kaiku is listening through this device". | `parts`: `mic_source: phone` |
| 4 | Wait for "shall I have my camera on while we talk?" and say **yes** within 12 s. | She says "Camera on. Only numbers, never a picture.", the buzzer sounds, the camera's own light comes on, the ear ring turns green. Only then the mood question. She never asks about the camera again in this conversation. | `rg -c '"camera_choice"' logs/hub.log` went up by exactly 1; `rg '"camera_choice"' logs/hub.log \| tail -1` shows `"on": true` |
| 4b | (Another conversation) say **no**, or say nothing for 12 s. | "Okay, the camera stays off." No light, ring stays orange. | `"on": false`, or `rg '"camera_not_answered"' logs/hub.log \| tail -1` |
| 5 | Mood question: **say** your answer ("about a two"). | Within about 3 s the head moves to the energy question by itself. | `rg 'obs.self_report' logs/hub.log \| tail -1`; `parts`: head `step: energy` |
| 6 | Energy question: **turn the ear**, then press once. | The head moves to the sleep question. A second press within 0.7 s does nothing. | `parts`: head `step: sleep` |
| 7 | Say "let's play the drums." Do **not** press. | She asks you to press her ear. Nothing starts. After 20 s she says it did not start. | `rg '"activity_asked"\|"activity_not_confirmed"' logs/hub.log \| tail -2` |
| 8 | Say it again, then press the ear within 20 s. | The head goes straight to the drums and the rhythm game starts. | `rg '"activity_confirmed"' logs/hub.log \| tail -1`; `parts`: head `step: drum` |
| 9 | Say "make your light white." | The ring turns white (breathing while she listens). | you see it; `make robot-bench ARGS="ring"` proves the ring itself works |
| 10 | Say "turn your head left." | She says a short line, then the head turns to your left just after she stops speaking. Not during the rhythm game. | you see it; `turn` in part A proves the motor |
| 11 | With the camera on (step 4), move your face slowly to the edge of what the camera sees. | Within about 2 s one small turn toward you; again every 2 s while you stay at the edge. Never while she speaks. | you see it. If it turns AWAY: flip `[follow_track] sign`. If nothing after three tries: `rg '"follow_track"' logs/hub.log \| tail -1` says it gave up (the camera is not on the part that turns) |
| 12 | With the camera on, say "photo time." | "Photo time!", a chime, about 8 s of counting, "All done. No picture was kept, only a few numbers." | `rg 'obs.face_signs' logs/hub.log \| tail -1` |
| 12b | With the camera off (4b), say "photo time." | She says it needs the camera. Nothing is counted. | no new `obs.face_signs` line |
| 13 | With the camera on: smile clearly for 10 s, then keep a still, unsmiling face for the next 10 to 20 s. | She may ask one short open question about how you are. She does not mention your face or the camera. At most one such note every 90 s, three per conversation. | `rg '"expression_lower"' logs/hub.log \| tail -1` (the note was sent; whether she asks is hers to judge) |
| 14 | In any step, say "let's stop for today." | The head goes back to rest within about 3 s, the camera light goes out, the ring returns to orange. | `rg '"ritual_done"' logs/hub.log \| tail -1` says `ended_early`; `parts`: head `step: idle`, `talk: closed` |
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
