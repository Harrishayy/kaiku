# Demo narrative

One story, told three ways: the submitted video, the three-minute stage or table pitch, and the answers to judges.
The submitted video may not exceed **2:00** (Junction rules: "not a second longer"). The cut below runs 1:58.
The stage pitch for finalists is 3:00 plus 3:00 of questions; its extra beats are listed after the shot table.

Rules for every version:

- The person in the video is **Harrish** (storyboard, 15 Nov): every device is linked to his record, today's takes
  are real and the sixteen earlier days are simulated, so "earlier days simulated" stays on every dashboard shot.
  The public demo link and the pitch beats below still use **Aino**, whose whole record is authored ("simulated
  record"). Never put "demo", "test" or a home ID on screen.
- Show only what runs on the day of recording. Each shot names its fallback.
- Say "change from her usual", "worth a check-in", "needs a call". Never "diagnosis", "relapse", "detects",
  "predicts" or "the glasses see".
- Before recording, open Aino's timeline and read what the consensus actually was on each day. With a 16-day
  record the rule cannot flag anything before day 11 and never reads Stable before day 21 (the baseline window in
  `config/criteria.toml`). Narrate the state that is on screen, not the state the story would like.

## The video (1:58)

Written on 15 November to go with the team-internal storyboard. The storyboard owns layouts, file names and how to film; this
section owns the words, the on-screen text and what each second has to prove. Scene times are the storyboard's:
118 seconds, two spare. The briefs the "Proves" column quotes are in `docs/tracks/*.md`.

How to read it: **VO** is a recorded narration line (`narration/NN.m4a`), **LIVE** is sound from the take itself
(Harrish and Kaiku's real voice, knocks, music) and is never re-voiced. Where a VO sits over LIVE sound, the take
drops to about 20 % under it. **Swap** is what to say and show if the step did not work on the day; pick the swap
before recording the narration, because each swap line is cut to the same length.

### Beat by beat

| Time | Picture | Sound | On screen | Proves | Swap if it fails |
|---|---|---|---|---|---|
| 0:00–0:04 | Harrish, chest up, into the lens. Hard cut in on his first word. | LIVE: "After my last TMS session, the daily visits just stopped." | Lower corner, small: "After TMS treatment for depression". Held through 0:00–0:12: "Spoken by the team; not a patient". | Aalto: the audience and the problem. Gemini: "what problem you're solving". | — |
| 0:04–0:08 | Edwin, same framing. Cut on the breath, no fade. | LIVE: "The effect can fade, and at home nobody is looking." | — | Aalto: usefulness. | — |
| 0:08–0:12 | Xavier, same framing. Hold half a second of silence after his last word. | LIVE: "And a low week is when you stop opening apps." | — | Aalto: ease of use ("would someone recovering actually use it every day?"). Atech: a real user, a real problem. | — |
| 0:12–0:20 | The table from above. Nothing moves until the robot's light comes on at "speaks first". | VO 01: "Kaiku listens through what you already own: phone, Mac, glasses, Apple Health. Plus one small companion that speaks first." | Title "Kaiku". A label lands on each device on its word: "iPhone", "Mac", "Meta glasses", "Apple Health", then "the robot: Atech + Arduino UNO Q". | Aalto: "a laptop and a phone are enough". Atech and Arduino: the hardware is named in the first twenty seconds. | Robot light does not come on: keep the shot, the label still lands. |
| 0:20–0:28 | Robot, layout A. Full video for two seconds, then it shrinks and the rail comes in. Harrish wakes it the way it wakes today (D66: a press) and it greets him. | LIVE, no VO: Kaiku's greeting. Harrish: "Hi Kaiku. Bit tired today, honestly." Kaiku's answer, cut on its first full sentence. | Captions of both voices. Rail label: "Voice: Gemini Live, on the head's own speaker". Chip: "Atech board: ear dial, neck motor, speaker". | Gemini: integration, one voice on a physical body. Atech: several modules, AI as the brain, running on the hardware. Aalto: ease, it starts the conversation. | Head microphone silent: the phone beside the robot is its microphone (D56); add the caption "microphone: the phone beside it". |
| 0:28–0:36 | He slides out of its picture. The face-x dot crosses the shaded edge, `cmd.head` fires, the head turns, the dot comes back. | VO 02: "Step out of its view, and it turns to find you. Only a number leaves the camera, never a picture." Motor sound left in under the VO. | Rail: "face x" with the live dot. Chip: "Arduino UNO Q: finds the face on the board, sends a number". Corner: "Pictures saved by a demo switch for this video. The product keeps none." only if the robot-camera inset is shown. | Arduino: on-device vision, sensing the real world and making something move (50 % of that track). Atech: a model in a loop with a sensor and an actuator. Aalto: smart sensing. Privacy for every track. | Head does not turn: this beat becomes the three dial turns. VO 02b, same length: "Three turns of its ear say how he is today. No screen, no typing, and it takes ten seconds." Rail shows the three dial values. |
| 0:36–0:50 | The drum. Four seconds of knocks alone, then the VO. Each knock leaves the video on the frame the hand lands and becomes a tick. | LIVE knocks 0:36–0:40. VO 03 from 0:40: "Every knock becomes a tempo. The music follows his hands, and one small record goes to the cloud." Music up for the last two seconds. | Tempo strip, "– BPM" becoming the measured number. Chip: `obs.tap_back` when music played (then it was the game Tap it back), `obs.drum_session` only for free drumming without music (see "decide" 5). Small: "inspired by research on improvisational music therapy". "Music: Lyria RealTime" only if it is heard in the room. | Aalto: creativity, sensory stimulation that adapts, sensing without a questionnaire. Gemini: Lyria RealTime, if heard. Atech: storytelling on live hardware. | No music in the room: VO 03b: "Every knock becomes a tempo. No questionnaire, just his hands, and one small record goes to the cloud." No Lyria label. |
| 0:50–0:56 | The rail folds into the dashboard row that this drum session created. | VO 04: "Seconds later, it is on his record." | The row's own time and tempo. Small: "today: real · earlier days: simulated". | Aalto: clinician view. The whole path is real, from a hand to a record. | Row not there: cut straight to the glasses and give the six seconds to the drum. |
| 0:56–0:59 | Helper shot: glasses on, phone into the pocket, he walks off. | VO 05 starts: "Outside, Kaiku moves to his glasses." | "Meta Ray-Ban glasses, through Meta's Device Access Toolkit". | Meta: a wearable benefit beyond a phone screen: head up, hands free. | — |
| 0:59–1:07 | His point of view, full screen, then it shrinks (layout B). One picture a second lifts off and lands in the strip. Boxes on the chips and on the robot. | VO 05 goes on: "With his say-so, one picture a second goes to the conversation. Kaiku keeps none." | Counter from the phone: "Kaiku can see · N pictures sent, none saved". "Boxes drawn with Gemini on this clip". "Seeing is his choice, off by default". | Meta: the first-person view enables the interaction; consent and safe data practice; trust. Gemini: live pictures and voice in one conversation. | Seeing did not work on the day: do not say "see". VO 05b: "Outside, Kaiku moves to his glasses: head up, hands free, the same conversation in his ear." Show "connected" on the phone and the walk. |
| 1:07–1:14 | Two cases at real speed. He picks up the chips; then looks at the robot. The graph links what is in view to what he once told Kaiku. | LIVE, no VO: "Kaiku, I'm about to grab these." Kaiku's real reply. "And what about this one?" Kaiku's real reply about its own favourite robot. Hold the last second for the laugh. | Captions of the real replies only (the storyboard's example lines never ship). Graph: "likes: chips" to "chips in view"; "likes: Kaiku, the robot" to "Kaiku robot in view". | Meta: creativity and use case, what a first-person view adds. Gemini: memory he chose to share, joined to what is in view. Aalto: delight. | Only one case worked: play that one and end the scene at 1:11; the dashboard gets the three seconds. |
| 1:14–1:21 | iPhone, layout C: Today's check-in. | LIVE, no VO: "Honestly, today has been a hard day." Kaiku stays with it, then offers one thing. Cut on the offer. | "Gemini Live. It notices, and offers one thing, once." If the suggestion card shows: "chosen from what has helped him before". | Aalto: everyday companion, the right thing at the right moment, the loop (sense, respond, learn). Gemini: emotional attunement, not "ok, anyway". | Live call fails: the typed check-in with real replies, captioned "typed". Never the scripted layout states. |
| 1:21–1:26 | Mac, a document open. Two taps of Control, Kaiku grows from the edge of the screen. | VO 06: "On the Mac, two taps of Control and Kaiku is there." Then LIVE: "I'm not feeling too well." under the cut. | Keys "⌃ ⌃" for half a second. "The Mac adds the rhythm of his day, never content." | Aalto: ease of use. Gemini: one voice everywhere. | Rendered stills, captioned "rendered". |
| 1:26–1:40 | Layout D, the map from the intelligence explainer. One node lights per sentence: Gemini, Gemma, the rule, the crisis path. | VO 07: "Each model has one job. Gemini speaks. Gemma, an open model we can host ourselves, picks the evidence. The state is a fixed rule, and a crisis is never left to a model." | Under Gemma: "Gemma 4 · answered from our own GPU on Modal · this demo: Google's API". Under the rule: `config/criteria.toml`. Bottom line: "Pictures and sound are used, then gone. Kaiku keeps numbers only." | Gemma: an open model with a real job, checked by code. Modal: GPU inference of an open model. Gemini: more than "adding an LLM". Trust, for Aalto and Meta. | — |
| 1:40–1:54 | Layout E, the practitioner page on Harrish's record. A click on one sentence of the review opens the record behind it. | VO 08: "It all lands on one page for his psychiatrist: the drum, the walk, the check-in, and sleep and steps from Apple Health. What changed from his usual, and the record behind every sentence." | "Earlier days simulated". The state exactly as the page shows it ("needs a call"). "Consensus: a fixed rule, not a model". If recorded from the deployed service: "served from Modal". | Aalto: clinician view without extra workload, smart sensing against his own baseline. Gemma: evidence with citations. Modal: the deployed app. | No Apple Health data from today: drop "and sleep and steps from Apple Health" from the line and from the page. |
| 1:54–1:58 | The table again, robot's light on. | VO 09: "Kaiku. A friend on your desk, a clearer record for your care team." | "Kaiku". One line: "Gemini Live · Gemma · Modal · Meta glasses · Atech · Arduino UNO Q". Small print: "Research prototype, not a medical device. Opening lines are spoken by the team. Earlier days in the record are simulated." The demo link. | Every track is named once before the video ends. | — |

About 210 spoken words: 30 in the three opening clips, 180 of narration. Record the narration first and cut to it.

### Rhythm

- **No shot runs longer than eight seconds without something changing**: a label landing, the video shrinking, a
  dot crossing a line, a new voice. The three longest holds are the drum (the ticks carry it), the glasses view (one
  picture a second carries it) and the dashboard (the click at about 1:47 carries it).
- **Three times Kaiku speaks for itself with no narrator** (0:20, 1:07, 1:14). They are the proof that the voice is
  real; do not talk over them.
- **One laugh**, at 1:12, when Kaiku recognises itself. Leave a full second after it before the phone scene.
- **Sound bridges every scene change**: the last knock rings into "Seconds later"; the door and street noise start
  under the end of VO 04; Harrish's "hard day" starts on the cut, before the phone has settled in its layout.
- The narrator is one calm voice all the way through. The energy comes from the cuts and from Kaiku, not from
  reading faster.

### What each judge has to see

| Track | Their criterion | Where in the video |
|---|---|---|
| Aalto | Usefulness | 0:00–0:12 the problem in the team's words; 1:40 the page a psychiatrist reads. |
| Aalto | Ease of use | 0:20 the robot starts; 0:36 a drum instead of a questionnaire; 1:21 two taps on the Mac. |
| Aalto | Smart sensing, learns what works | 0:28 a face as a number; 0:36 tempo; 1:14 one suggestion; 1:40 "changed from his usual". |
| Aalto | Creativity | 0:36 the drum; 1:07 the robot recognising itself. |
| Meta | Use case, first-person view | 0:59–1:14: what is in view joined to what he has told Kaiku. |
| Meta | Input, accessibility, trust | 0:56 voice only, hands free; 0:59 "his choice, off by default", the counter, "keeps none". |
| Meta | Execution, feasibility | 0:56 the toolkit label; real replies at 1:07. Device-state handling is not in the cut: it goes in the deck. |
| Gemini | Integration, why Gemini | 0:20, 1:07, 1:14, 1:21: one live voice on four bodies; pictures and memory in one conversation; music if heard. |
| Gemma | Impactful use of an open model | 1:26 its one job; 1:47 a sentence opening the record it cited. |
| Atech | Use of Atech, working demo | 0:12 named; 0:20–0:50 dial, motor, speaker and taps on the real board. |
| Atech | Validation, impact | Only the opening lines. Validation with people outside the team is not in the video; see below. |
| Arduino | Hardware and on-device vision (50 %) | 0:28 the UNO Q finds the face and the head turns. |
| Modal | Effective use, demo | 1:26 Gemma on the GPU; 1:40 and the end card only if the page is recorded from the deployed service. |

### Before the narration is recorded, decide

1. **Line 05 says "Kaiku keeps none", not the storyboard's "Nothing is saved".** The takes are filmed with the demo
   switch that saves pictures, so the sentence has to be about the product. Change it back only if the glasses take
   is filmed without the switch.
2. **Which lines are swaps** (02 or 02b, 03 or 03b, 05 or 05b, 08 with or without Apple Health). Record both
   versions of each; it costs one minute and saves a re-record.
3. **Where the dashboard is recorded from.** On the Mac's local service the Modal judges see Modal only as a label
   at 1:26. Recording 1:40–1:54 from the deployed service, with Harrish's record on it, is the only way the video
   shows "a live, deployed app". If there is no time, the end card carries the public link and says whose record it
   opens.
4. **"Chosen from what has helped him before"** (1:14) goes on screen only if the suggestion in that take did come
   from his record. Otherwise leave the caption at "offers one thing, once".
5. **Line 03 needs the team's decision.** On the robot as built (the head runs its own steps, the hub follows) the
   hub plays no music for free drumming. With music on, the drum step is the game Tap it back: Kaiku plays a short
   song at a set tempo, he taps it back, and the record is `obs.tap_back`; the music does not follow his hands.
   With music off, his free drumming is recorded as `obs.drum_session` with his tempo and there is no music. So
   "Every knock becomes a tempo. The music follows his hands" is true of neither take as it stands: either film the
   game and say what it is (for example "Kaiku plays a beat, and he taps it back"), or film free drumming and use
   line 03b. The chip follows the take.

### Asked for by the briefs and not answered by a video

- Arduino: the project must also be published on the Arduino Project Hub with the tag "Junction Finland 2026".
- Atech: a link to a summary or post in Atech's Discord; evidence of use by people outside the team (25 %).
- Meta: a deck, with the pilot path and what happens when the glasses come off or disconnect.
- Modal: a deployed link a judge can open.

### Extra beats for the 3:00 pitch

The pitch is given live on Aino's simulated record at the public link; clips of Harrish from the video may be
played inside it. Each beat names the video scene it follows.

- **After the three opening lines (15 s):** "TMS works, and the effect often fades. A second course can help if
  someone notices in time. At home nobody is looking, and depression takes away the initiative to open an app."
  Use the response-durability figure only with its citation on the slide.
- **After the model map, 1:26–1:40 (20 s):** show `config/criteria.toml` for three seconds, then the calibration
  evaluation on simulated trajectories (`docs/validation.md`). "This is the whole rule. We test it against
  simulated people; it has never been calibrated on patients, and that is the pilot."
- **On the practitioner page, Aino's record (15 s):** the learner. "Each suggestion is scored right after and the
  next day, and Kaiku offers Aino what has worked for her." Show the Routine panel's "what helps" with its tries
  and interval.
- **After the Mac scene (15 to 20 s): how one sentence travels.** The explainer
  (`docs/explainers/intelligence-flow.html`, recorded as `demo/recordings/intelligence-flow.mp4`; time codes of
  every hop in `intelligence-flow-steps.txt`): zoom out from "I'm not feeling too well" to the map, her voice
  straight to Gemini Live, the `feel` call to Kaiku's rules, the plan back, the reply. "Her voice goes to the
  voice model and nowhere else. Kaiku's own mind decides how to meet her in milliseconds, by rule, and the voice
  never sees a score." Its numbers were measured on a simulated record with a test client and a synthetic voice:
  say "measured on our bench", not "in the app".
- **After the robot scene (10 s): agreed in one place.** She says "Can we play the lantern game later?" to the
  robot; the phone on the table shows the card at once. Shown so far from posted tool calls on the simulator and
  one real typed walk; film it only after it has worked on the real devices. On Aino's record the day is
  extra-gentle, so only her own ask is kept: a plain "yes" to an offer keeps nothing there.
- **Drum music (optional):** with the hub's music on, the drum step is the game Tap it back: Lyria RealTime plays
  a short song at a set tempo and she taps it back. The sound reaches the head's own speaker as audio frames over
  the home network (D51); the game played once that way on the real head on 15 Nov. Music that follows her own
  tempo in free drumming has run only on 14 Nov with simulated taps and sound into a file, and not on a head that
  runs its own steps.
- **Close (10 s):** pilot with a neuromodulation unit; the consensus compared with clinician assessments.

## How to talk about each service

**Robot.** People with depression stop opening apps, so the robot is a thing on the desk that needs no screen.
A press of its ear opens a talk; the check-in (a dial, a breath and a drum) runs only when she asks for it (D66).
The head runs those steps itself as a fixed sequence and the hub on the laptop follows it (D44); Gemini supplies
the voice and can only move the sequence through a small set of checked commands, and an activity asked for in
words starts only on her own press (D58). The camera stays closed until she says yes (D61), so the ear wakes the
robot; a face woke it once, on 14 Nov, before that rule. Be exact about hardware: which parts ran on the real
board, and which ran on the software twin that speaks the same messages. D58 and D66 have not yet been tried by a
person on the robot.

**Atech head.** One 14-port board carries five modules: an encoder as an ear dial, an orientation sensor that
feels taps with their force, a motor for the neck, a speaker and a microphone. There is no screen, no light grid
and no button on the robot as built (D54, D55). The head's own microphone returns silence, so a phone beside the
robot stands in for it (D56). The Atech tools validate
and build the project; our own small library connects it to the home network. The same messages come from the
twin, so the rest of the system never needed the hardware to exist.

**iPhone and Mac.** The apps are the low-effort surface. The check-in is a small chat with Kaiku, short on an
ordinary day and as long as she wants on a hard or a very good one; she can also just turn three dials. Talk is
a call: she can mute herself or mute Kaiku, the captions keep coming, and on the phone the call goes on behind
the Lock Screen. When Kaiku suggests a game or a journal entry it puts a card in the conversation; nothing opens
without her yes. On the Mac two taps of a key bring Kaiku up from the edge of the screen without leaving the
app she is in. Every reading waits in a queue on the device until the cloud confirms it, so a dead network
loses nothing. The Mac contributes only the shape of the day: categories, breaks and late nights.

**The companion that notices.** When what she says carries a clear feeling, the voice tells Kaiku's mind once.
Code answers with a small plan: comfort, celebrate, explore or give space; keep it brief or stay; one thing the
record says helps her; at most one offer per conversation. The same mind serves the phone, the Mac, the
glasses and the robot, so something said on a walk is known on the phone the next day, and once a day Kaiku may
bring one thing up itself. None of it changes the practitioner's state: that stays the fixed rule.

**Glasses.** A walk is the one activity where a phone in the hand works against you. The iPhone registers
with the glasses through Meta's Device Access Toolkit and reads head motion; Kaiku's voice travels over normal
Bluetooth, so the same conversation continues from the kitchen to the street. She chooses how Kaiku walks with
her: calm, playful or chatty. Seeing is a separate choice that is off by default: with it on, about one picture
a second goes to that walk's conversation and nowhere else, nothing is stored, and no reading is derived from a
picture. Kaiku then connects what is in view to what she has told it, as a question, and keeps a spotting
game's count on the phone. Say "Kaiku can see" only for a walk with that choice on. If the glasses disconnect or
come off, the walk continues on the phone and the record says so.

**Cloud and consensus.** One service receives every reading, refuses anything that is not a derived number,
and compares each one with that person's own recent history. Each signal group gets a verdict: as usual,
better, worse or not enough data. A fixed rule in one readable file combines them. Too little data produces
"insufficient", never "stable". No model is involved in the state.

**Gemma.** Gemma has eight jobs where an open model earns its place (the list is in `docs/stack/gemma.md`),
among them writing the practitioner's review, choosing which recorded evidence answers a practitioner's
question, tidying the companion's notebook into a graph of activities and routines, and answering the
companion's harder questions. In each it proposes and code checks: citations must exist, numbers are rendered
from the database, forbidden wording is rejected. The public demo runs it through Google's hosted API; on
15 Nov the review and a record question also ran on our own vLLM on a Modal H100. Say both, and do not say the
data stays on our servers.

**Gemini.** Gemini Live is Kaiku's voice on every surface, with interruption and tool calls. It speaks from a
small card the cloud prepares (a few memories she chose to share, today's activities, a tone) and never sees
scores or consensus states. Fixed lines are rendered once by Gemini TTS so Kaiku always has the same voice;
if the voice is unavailable Kaiku stays silent and shows text.

**Dashboard.** A practitioner opens one page, sees who is worth a check-in, and can reach the evidence in one
click. It shows trends, the review with links, routines that are emerging, and one week beside another.
Care actions are recorded in Kaiku; they do not contact anyone.

**Modal.** Say only what has run. It is deployed (the public link opens Aino's record): one always-on container serves the API and the dashboard
with its database on a volume, schedules recompute every 15 minutes and nightly, a fan-out simulates 72 people
in parallel, and a separate GPU class serves Gemma and costs nothing while idle (verified on 15 Nov from a
local API for the review and a record question; the public demo uses the hosted API).

## Ten questions, honest answers

1. **How is it calibrated?** Against each person's own history: a median and spread over two weeks, lagged by
   a week so a slow slide does not become the new normal. The thresholds are engineering defaults in
   `config/criteria.toml`. They have been tested against simulated trajectories, not against patients.
2. **What is validated?** PHQ-9 is a validated questionnaire. Nothing else is. The games are not clinical
   instruments, the consensus has not been compared with clinician ratings, and every record shown is authored.
3. **Why a fixed rule instead of a model for the state?** A practitioner has to be able to ask why and get
   the same answer tomorrow. The rule is versioned by hash, every input is visible, and a wrong threshold can be
   changed in one file and replayed.
4. **Then why Gemma at all?** A page of metrics is the workload the brief asks us not to add. Gemma reads the
   record and points to the five items that matter; it cannot change a number or a state. An open model also
   leaves the option of running it inside a hospital's own infrastructure, which the hosted demo does not do yet.
5. **What happens in a crisis?** A fixed phrase list or PHQ-9 item 9 stops everything, gives a pre-written
   message with the MIELI helpline 09 2525 0111 and 112, and sets a safety state on the dashboard. No model is
   involved. The apps show the message; the robot as built has no screen and no button, so it cannot show it
   (`docs/safety.md`). It will miss indirect language and it does not call anyone. Kaiku is not a crisis
   service.
6. **What leaves the home?** Derived numbers only; the cloud rejects anything else. Camera frames are
   processed in memory. The exceptions are the voice and, only if she turns it on, the glasses' view: during
   a conversation she started, audio goes to Gemini Live, and on a walk with "Let Kaiku see" on about one
   picture a second goes to that same conversation and nowhere else. Conversation text is kept only if she turns that on, and practitioners never see it.
7. **Why a robot and not just an app?** Initiative. An app waits behind a screen; the robot is on the desk, one
   press of its ear wakes it and it speaks first (with the camera on, after her yes, it also turns to keep her in
   view). It
   also makes the check-in physical: a turn, a breath, a rhythm.
8. **Are the signal groups independent?** No, and the dashboard does not pretend so. Several can come from
   one phone. Each record keeps its real device source, and disagreement between groups is displayed.
9. **What do the glasses add over earbuds?** She already wears them, the microphones are tuned to the
   wearer's voice, and through the toolkit the app knows when they are on, off or out of range and can read
   head motion. Earbuds give audio only.
10. **What would the pilot measure?** Whether the consensus agrees with clinician assessment over eight to
    twelve weeks after a TMS course, how often people complete the ritual, and how many check-ins a
    practitioner is asked to make per person.
