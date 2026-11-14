# Demo narrative

One story, told three ways: the submitted video, the three-minute stage or table pitch, and the answers to judges.
The submitted video may not exceed **2:00** (Junction rules: "not a second longer"). The cut below runs 1:55.
The stage pitch for finalists is 3:00 plus 3:00 of questions; its extra beats are listed after the shot table.

Rules for every version:

- The person is **Aino**. Never put "demo", "test" or a home ID on screen. Her record is authored, so a small
  caption "simulated record" stays on every dashboard shot.
- Show only what runs on the day of recording. Each shot names its fallback.
- Say "change from her usual", "worth a check-in", "needs a call". Never "diagnosis", "relapse", "detects",
  "predicts" or "the glasses see".
- Before recording, open Aino's timeline and read what the consensus actually was on each day. With a 16-day
  record the rule cannot score anything before day 14 (`docs/track-readiness.md` §4, weak point 1). Narrate the
  state that is on screen, not the state the story would like.

## The video (1:55)

| Time | On screen | Say (one sentence) | Proves | Real or simulated |
|---|---|---|---|---|
| 0:00–0:10 | Morning, a kitchen table. A clinic appointment card with twenty dates crossed out. Aino's phone lies face down. | "For six weeks someone saw Aino almost every day; her TMS course ended, and now nobody does." | Aalto: usefulness. Gemini: the problem. | Acted. |
| 0:10–0:19 | iPhone, first run: Kaiku's service found nearby, a short list of choices each with its own switch, a voice trial. | "Setting up is a list of choices: every signal is opt-in, and nothing listens until she says so." | Aalto: ease of use. Meta: consent and trust. | Real app on a real iPhone. Verify the final onboarding build. |
| 0:19–0:33 | Talk tab. She says good morning; Kaiku answers aloud and mentions the walk by the lake. Caption: "Gemini Live. It remembers only what she asked it to." | No narration. Kaiku's own voice carries the shot. | Gemini: integration, why it is essential. | Real Live call. Fallback: none; without the real voice, cut the shot to 6 s of typed chat. |
| 0:33–0:42 | Firefly on the phone, thirty seconds of play, then the recap card. | "A one-minute game is also a reaction-time reading, compared only with her own usual." | Aalto: smart sensing, creativity. | Real app. |
| 0:42–0:57 | Outdoors. Gen 2 glasses on, phone going into a pocket. Kaiku's voice: "Found one. Two more to go." She takes the glasses off; the phone shows "the walk goes on with the phone". | "Outside, Kaiku moves to her glasses: head up, hands free, phone in her pocket." | Meta: wearable benefit, device-state handling, audio-first. | Real only if the audio route has been accepted on the device. Fallback: show registration and "connected" on the phone and say "voice over Bluetooth". |
| 0:57–1:12 | The robot on her desk. Eyes open, three turns of the ear dial, chest glows for a breath, she drums on its head. | "At home the robot speaks first: three turns of an ear, one breath, a drum, and no typing." | Atech: use of modules, live hardware. Aalto: ease, creativity. | Real board for whatever has passed its bench. Anything else is the hardware twin with the caption "simulated hardware". No music unless Lyria plays on the device. |
| 1:12–1:18 | Mac menu bar: category minutes and breaks, the pause switch. | "Her Mac adds rhythm only: breaks and late nights, never content." | Aalto: smart sensing. Privacy. | Real Mac app. |
| 1:18–1:31 | Dashboard: four signal-group chips, each with its verdict and its real device source, resolving to one state; the timeline with the dip. | "Each group is compared with her own baseline, and a fixed rule that anyone can read, not a model, combines them; missing data never reads as stable." | Aalto: clinician view. Modal: impact. | Real engine, simulated record. Shown from the deployed URL once it exists. |
| 1:31–1:45 | Practitioner view: Gemma's review with numbered evidence links, a click opening the cited record, the routine graph, first week beside latest week. | "For her practitioner, Gemma chooses the evidence and every sentence opens the record behind it; the numbers are written by code." | Gemma: impactful, well-executed open model. | Real Gemma call on the simulated record. Fallback: the deterministic summary, labelled as such. |
| 1:45–1:51 | The practitioner records a follow-up flag; the following days show walks and mood moving back toward usual. Caption: "observed, not proof of cause". | "One click records the follow-up, and the days that follow are there to compare." | Aalto: closed loop. | Real action route, simulated record. |
| 1:51–1:55 | Robot, phone and glasses on the table. "Kaiku". Small print: research prototype, not a medical device, record shown is simulated. | "Kaiku: a friend on your desk, a voice in your ear, a clearer record for your care team." | All. | — |

About 175 spoken words. Record the narration first and cut the pictures to it.

### Extra beats for the 3:00 pitch

- **After the cold open (15 s):** "TMS works, and the effect often fades. A second course can help if someone
  notices in time. At home nobody is looking, and depression takes away the initiative to open an app." Use the
  response-durability figure only with its citation on the slide.
- **After the consensus (20 s):** show `config/criteria.toml` for three seconds, then the calibration
  evaluation on simulated trajectories. "This is the whole rule. We test it against simulated people; it has
  never been calibrated on patients, and that is the pilot."
- **After the care action (15 s):** the learner. "Each suggestion is scored right after and the next day, and
  Kaiku offers Aino what has worked for her."
- **Close (10 s):** pilot with a neuromodulation unit; the consensus compared with clinician assessments.

## How to talk about each service

**Robot.** People with depression stop opening apps, so the robot starts the conversation. It turns toward
whoever walks up and offers a three-minute ritual made of a dial, a breath and a drum. The laptop next to it
runs the ritual as a fixed sequence; Gemini supplies the voice and can only move the sequence through a small
set of checked commands. Be exact about hardware: which parts ran on the real board today, and which ran on
the software twin that speaks the same messages.

**Atech head.** One 14-port board carries eight modules: a screen for eyes, an encoder as an ear, a lid
button, two LED grids in the chest, a motor for the neck, a speaker and a microphone. The Atech tools validate
and build the project; our own small library connects it to the home network. The same messages come from the
twin, so the rest of the system never needed the hardware to exist.

**iPhone and Mac.** The apps are the low-effort surface: a weather-style check-in, two short games, a talk
tab and a private "your days" view. Every reading waits in a queue on the device until the cloud confirms it,
so a dead network loses nothing. The Mac contributes only the shape of the day: categories, breaks and late
nights.

**Glasses.** A walk is the one activity where a phone in the hand works against you. The iPhone registers
with the glasses through Meta's Device Access Toolkit and reads head motion; Kaiku's voice travels over normal
Bluetooth, so the same conversation continues from the kitchen to the street. No camera is used and the
glasses do not see anything. If they disconnect or come off, the walk continues on the phone and the record
says so.

**Cloud and consensus.** One service receives every reading, refuses anything that is not a derived number,
and compares each one with that person's own recent history. Each signal group gets a verdict: as usual,
better, worse or not enough data. A fixed rule in one readable file combines them. Too little data produces
"insufficient", never "stable". No model is involved in the state.

**Gemma.** Gemma has three jobs where an open model earns its place: choosing which recorded evidence
answers a practitioner's question, tidying the companion's notebook into a graph of activities and routines,
and answering the companion's harder questions. In all three it proposes and code checks: citations must
exist, numbers are rendered from the database, forbidden wording is rejected. Today it runs through Google's
hosted API; say that, and do not say the data stays on our servers.

**Gemini.** Gemini Live is Kaiku's voice on every surface, with interruption and tool calls. It speaks from a
small card the cloud prepares (a few memories she chose to share, today's activities, a tone) and never sees
scores or consensus states. Fixed lines are rendered once by Gemini TTS so Kaiku always has the same voice;
if the voice is unavailable Kaiku stays silent and shows text.

**Dashboard.** A practitioner opens one page, sees who is worth a check-in, and can reach the evidence in one
click. It shows trends, the review with links, routines that are emerging, and one week beside another.
Care actions are recorded in Kaiku; they do not contact anyone.

**Modal.** Say only what has run. Once deployed: one always-on container serves the API and the dashboard
with its database on a volume, schedules recompute every 15 minutes and nightly, a fan-out simulates 72 people
in parallel, and a separate GPU class serves Gemma and costs nothing while idle.

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
5. **What happens in a crisis?** A fixed phrase list, PHQ-9 item 9, or a long press on the robot's button
   stops everything, shows a pre-written message with the MIELI helpline 09 2525 0111 and 112, and sets a
   safety state on the dashboard. No model is involved. It will miss indirect language and it does not call
   anyone. Kaiku is not a crisis service.
6. **What leaves the home?** Derived numbers only; the cloud rejects anything else. Camera frames are
   processed in memory. The exception is the voice: during a conversation she started, audio goes to Gemini
   Live. Conversation text is kept only if she turns that on, and practitioners never see it.
7. **Why a robot and not just an app?** Initiative. An app waits; the robot looks up when she walks past. It
   also makes the check-in physical: a turn, a breath, a rhythm.
8. **Are the signal groups independent?** No, and the dashboard does not pretend so. Several can come from
   one phone. Each record keeps its real device source, and disagreement between groups is displayed.
9. **What do the glasses add over earbuds?** She already wears them, the microphones are tuned to the
   wearer's voice, and through the toolkit the app knows when they are on, off or out of range and can read
   head motion. Earbuds give audio only.
10. **What would the pilot measure?** Whether the consensus agrees with clinician assessment over eight to
    twelve weeks after a TMS course, how often people complete the ritual, and how many check-ins a
    practitioner is asked to make per person.
