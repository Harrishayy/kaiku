# Junction submission text

> Ground truth for what we submit. The deadline is **Sunday 15 November 10:00**; the project must be set to
> FINAL. Evidence per claim: the pages in [`stack/`](stack/INDEX.md) and [`progress.md`](progress.md).
>
> Demo link: <https://harrish21raj--kaiku-web.us-east.modal.run/?id=aino>. Still to attach: public video (maximum
> 2:00, script in [`demo-narrative.md`](demo-narrative.md)), pitch deck (PDF), source link, Atech Discord post.

**Project name:** Kaiku

**Punchline** (188 of 200 characters): The clinic sees you every day, until treatment ends. Kaiku keeps you company after: a friend on your desk, a voice in your ear, and a record that shows your care team what changed and why.

**Challenges:** Aalto University, Beyond the Clinic (main) · Best Use of Gemini API · Best Use of Gemma ·
Best use of Modal · Meta, AI Glasses for Everyone, Everyday · Atech Real World Challenge · Arduino, Best use of UNO Q

## Description

> Paste-ready for the form (4905 of 5000 characters with `##` headings; one line per paragraph so the form does
> not break lines). It carries its own short technology and safety sections; the longer versions below are the
> evidence behind them and are not pasted.

### The problem
A TMS course for severe depression means about twenty clinic visits: for weeks, someone sees you almost every day. Then the visits end, and that view ends with them. The benefit often fades in the months that follow, and a further course can help if the change is noticed in time. At home, nobody is looking. One questionnaire or one wearable is a thin signal, and depression takes away the initiative it takes to open an app and report.

### Kaiku
**A companion that reaches out first, and a record a practitioner can read in a minute.** Kaiku is Finnish for "echo".

No clinic judges a patient from one measurement. Kaiku brings that principle home: four **signal groups** (check-ins and robot, walks and outings, apps, optional watch data) are each compared with the person's **own baseline**, and a fixed, readable rule combines them into one consensus.

### A day with Kaiku
- **Robot.** A small desk robot with one ear. Press it to talk. Ask, and a three-minute check-in follows: three turns of the ear for mood, energy and sleep, a guided breath, and a rhythm tapped on its head, inspired by research on improvisational music therapy. No typing, no screen.
- **Phone.** The day starts with a small chat, like meeting a friend on the street: short on an ordinary day, as long as you want on a hard one. A sad thing gets a gentle, curious reply, never "ok, anyway".
- **Play.** Five games of a minute or two (reaction time, symbol matching, effort choice) give numbers without a single question.
- **Walk.** With Meta glasses, Kaiku is a voice in your ear. Seeing is a separate choice, off by default: pictures go to that walk's conversation and nowhere else, so Kaiku can ask "Is that your favourite tree up there?" Nothing is stored.
- **Mac.** Two taps of a key bring Kaiku up in any app. Optionally it keeps the rhythm of the day as app categories, never titles, URLs or content.

A PHQ-9 anchors the record to a validated questionnaire. Every signal is its own opt-in, and nothing listens until you start a conversation.

### From many signals to one consensus

| Consensus | Rule |
|---|---|
| **Stable** | Enough data, nothing worse than usual, at least 21 days of record |
| **Watch** (worth a check-in) | One signal group worse than usual, or too little data (never shown as stable) |
| **Needs a call** | Two or more signal groups worse than usual |
| **Safety** | PHQ-9 item 9 or a crisis phrase: overrides everything, no model |

**No model decides a person's state.** The rule lives in one file, versioned by its hash. Disagreement between groups is displayed, not averaged away.

### The practitioner dashboard
One page shows who is worth a check-in. Opening a person shows trends against their usual, a review written by Gemma in which every statement links to the record behind it, routines that are emerging, and one week beside another. From there: acknowledge, flag for follow-up, or message the robot.

### Closed loop
Each suggested activity records how the person felt before, after and the next day, and a learner favours what has worked for them.

### Built with
- **Gemini Live API.** One interruptible voice on robot, iPhone, Mac and glasses. Its function calls move the robot's check-in, keep the consented notebook and ask Kaiku's mind how to meet a feeling.
- **Gemma 4.** Writes the practitioner review, answers questions to the record with citations and organises the notebook into a graph of routines. Code checks every citation and renders every number. Also run on our own vLLM on a Modal H100.
- **Modal.** API, dashboard, database, scheduled analytics and a parallel simulation of synthetic people in one app.
- **Meta Wearables Device Access Toolkit.** Voice and opt-in camera frames from Gen 2 glasses; a walk on real glasses sent 30 frames to Gemini Live.
- **Atech.** One ESP32 board with five modules: ear dial, tap sensor, neck motor, speaker, microphone. Its firmware runs the check-in alone or over MQTT.
- **Arduino UNO Q.** A camera read on the board (faces, distance, room light); only numbers leave it.
- **Lyria RealTime.** Live music for the robot's rhythm game.
- **Architecture.** One versioned message contract; every hardware part has a software twin.

### Safety, privacy and limits
- **Only derived numbers are kept.** The record takes no raw audio or images; camera frames are processed in memory and never saved. Audio reaches Gemini Live only during a conversation the person started.
- **Crisis path without AI.** PHQ-9 item 9 or a crisis phrase shows a fixed message with the MIELI Crisis Helpline (09 2525 0111) and 112, and raises a safety state on the dashboard.
- **Research prototype.** Not a medical device. Kaiku reports change from a person's usual; it does not diagnose. Every record shown is simulated and labelled; thresholds are not yet calibrated on patients, and the physical robot's data is not yet on the dashboard.

## Technologies used (in full)

- **Gemini Live API.** Real-time voice with interruption and function calling on the robot, iPhone, Mac and
  glasses, with opt-in pictures from the glasses on a walk. Tool calls move the robot's ritual, write to the
  consented notebook, tell Kaiku's mind about a feeling (non-blocking), put an activity card in the
  conversation and keep a spotting game's count. Clients receive a
  short-lived token from the cloud and never hold the API key.
- **Gemini TTS and embeddings.** One consistent voice for fixed lines; semantic recall of the person's own
  notes.
- **Gemma 4.** Chooses evidence for the practitioner review, answers questions to the record with citations,
  proposes how to organise the notebook into a graph of activities and routines, and answers the companion's
  deeper questions. Code checks every citation and renders every number. Google's hosted API is the default
  route; the review and a record question have also been answered by our own vLLM on a Modal H100 (15 Nov).
  The default is hosted, so we do not claim that data stays on our own infrastructure.
- **Modal.** The API, dashboard, database volume, scheduled analytics and a parallel simulation of synthetic
  people are one deployed Modal app at the demo link above, with a separate scale-to-zero GPU app for Gemma.
- **Meta Wearables Device Access Toolkit** (iOS). Registration, device session, audio and opt-in camera frames
  from Gen 2 glasses, in Developer Mode. On real glasses: registration, a self-test (speaker, microphone, one
  camera frame) and a walk that sent 30 frames to Gemini Live and heard the wearer. Head motion and Kaiku's
  replies heard in the glasses are not yet shown on the device.
- **Atech.** One 14-port ESP32 board with five modules: ear dial, orientation sensor for taps, neck motor,
  speaker, microphone. Its own firmware runs the check-in by knob with no laptop and speaks MQTT with the hub.
  On the board: taps, the motor both ways, and a Gemini Live conversation through its speaker with a phone as
  the microphone (the head's own microphone returns silence so far).
- **Arduino UNO Q.** A USB camera read on the board (faces, distance, room light), only numbers leaving it, and
  a buzzer for chimes.
- **Architecture.** One versioned message contract (MQTT at home, HTTPS to the cloud). Every hardware part has
  a software twin, so each piece can be developed, replaced or removed on its own. SwiftUI apps, Next.js
  dashboard, FastAPI, SQLite.

### For the Gemini challenge: the four questions
1. **Problem.** People lose the benefit of treatment at home without anyone noticing, and cannot be expected to
   type reports while their energy is lowest.
2. **Integration.** Live sessions on four surfaces, bootstrapped by the cloud with a small prepared context;
   validated function calls; TTS; embeddings.
3. **What is new.** The voice has hands and a mind behind it: its tool calls advance a physical ritual and a
   walk, and one call tells Kaiku's mind what it heard so code can answer how to meet it for this person. One
   mind serves four surfaces. Measurement and safety stay in deterministic code that the model cannot override.
4. **Why Gemini.** A check-in without typing needs low-latency speech that can be interrupted and can act.
   Without Live there is no ritual and no walk companion.

## Safety, privacy and limits

- **Research prototype.** Not a medical device and not a crisis service. Kaiku reports change from a person's
  usual; it does not diagnose.
- **All records shown are authored and labelled as simulated.** Thresholds have not been calibrated on
  patients, and the activities are not validated instruments. How the rule behaves on labelled synthetic
  courses is in [`validation.md`](validation.md).
- **Crisis path without AI.** A fixed phrase list or PHQ-9 item 9 shows a pre-written message with the MIELI
  Crisis Helpline (09 2525 0111) and 112, and sets a safety state on the dashboard. On the robot the
  conversation closes at once and the flag is raised; the robot as built has no screen and no button, so the
  message is shown by the phone app beside it. It does not call anyone and it will miss indirect language.
- **Derived numbers only.** The cloud rejects raw audio and images. Camera frames are processed in memory.
  During a conversation the person started, audio is streamed to Gemini Live. Conversation text is stored only
  after a separate opt-in and is never shown to practitioners.
- **Hardware honesty.** Robot pulse is not measured in this build. Nothing from the physical robot has been
  shown on the dashboard yet, and its newest flow (a press opens a talk) has not been tried by a person on the
  robot. The rhythm game Tap it back has played through the head's speaker once (15 Nov); its
  music comes from Lyria RealTime, proven end to end against the head's software twin.

## What's next
A pilot with a neuromodulation unit: compare the consensus with clinician assessment for eight to twelve weeks
after a TMS course, measure how often people complete the ritual, and calibrate the thresholds on real data.
Then the EU medical-device pathway.
