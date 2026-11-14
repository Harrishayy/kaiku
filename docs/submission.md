# Junction submission text

> Ground truth for what we submit. The deadline is **Sunday 15 November 10:00**; the project must be set to
> FINAL. Every `[verify]` tag marks a claim that depended on work still landing on 14 November: confirm it runs,
> then delete the tag or the sentence. Evidence per claim: [`track-readiness.md`](track-readiness.md).
>
> Still to attach: public video (maximum 2:00, script in [`demo-narrative.md`](demo-narrative.md)), pitch deck
> (PDF), demo link (the Modal URL once deployed), source link, Atech Discord post.

**Project name:** Kaiku

**Punchline:** A friend on your desk, a voice in your ear, a clearer record for your care team.

**Challenges:** Aalto University, Beyond the Clinic (main) · Best Use of Gemini API · Best Use of Gemma ·
Best use of Modal · Meta, AI Glasses for Everyone, Everyday · Atech Real World Challenge

## Description

### The problem
TMS (transcranial magnetic stimulation) helps people with severe depression, but the effect often fades in the
months after treatment. A course means around twenty clinic visits, so for weeks someone sees the patient almost
every day. When the visits end, that view disappears. A further course can help if worsening is noticed in time,
but at home nobody is looking, one questionnaire or one wearable is a thin signal, and depression takes away
the initiative to open an app and report.

### What Kaiku is
Kaiku is a companion that reaches out first, and a record that a practitioner can read in a minute.

In a clinic nobody judges a patient from one measurement. Kaiku applies that at home: four **signal groups**
(check-ins and robot, walks and outings, apps, optional watch data) are each compared with the person's **own
baseline**, and a fixed, readable rule combines them into one consensus. Each observation keeps its real device
source; groups that come from the same phone are not presented as independent devices.

**A day with Kaiku**

- **Phone, first run.** The app finds the Kaiku service, and every signal is a separate opt-in. Nothing
  listens until the person starts a conversation. `[verify]`
- **Talk.** Kaiku speaks with one voice everywhere (Gemini Live). It remembers only what the person asks it
  to, and can be told to forget.
- **Play.** Firefly (reaction timing) and Pebbles (memory span) take about a minute. Measured rounds are kept
  separate from practice. These are short activities, not validated clinical tests. `[verify: added games]`
- **Walk.** With Meta Gen 2 glasses paired to the iPhone, Kaiku keeps company in the ear with the phone in a
  pocket. Registration goes through Meta's Device Access Toolkit and is explicit; the voice uses Bluetooth. If
  the glasses disconnect or come off, the walk continues on the phone. No camera is used.
- **Robot.** A small desk robot with animated eyes turns toward the person and offers a three-minute ritual:
  three turns of an ear dial for mood, energy and sleep; a guided breath with a glowing chest; a short rhythm
  tapped on its head, inspired by research on improvisational music therapy. No typing.
- **Mac.** Optional rhythm of the day: broad app categories, breaks and late-night minutes. Never window
  titles, URLs or content.
- **PHQ-9** every two weeks anchors the record to a validated questionnaire. `[verify: which surface asks it]`

### From observations to one consensus

| Consensus | Rule |
|---|---|
| **Stable** | Enough recent evidence, as usual or better |
| **Watch** | One group has changed from usual, or coverage is thin |
| **Needs a call** | Several groups, or a questionnaire threshold, meet the review rule |
| **Insufficient** | Not enough data or no baseline yet; never shown as stable |
| **Safety** | A deterministic safety trigger; overrides everything |

Thresholds, weights and freshness windows live in one file, `config/criteria.toml`, and the rule version is its
hash. No model decides a person's state. Disagreement between groups is displayed, not averaged away.

### The practitioner dashboard
One page shows who is worth a check-in. Opening a person shows trends, a review in which every statement links
to the record behind it, routines that are emerging, and one week beside another. `[verify]` A care action
(acknowledge, flag for follow-up, send a short message to the robot) is recorded in Kaiku; it
does not contact an outside service or book treatment.

### Closed loop
Suggested activities (breathing, drumming, a walk) record how the person felt before and after and how the
next day went. A learner then favours what has worked for that person. Missing feedback stays missing, and an
observed response is not evidence of treatment effect.

## Technologies used

- **Gemini Live API.** Real-time voice with interruption and function calling on the robot, iPhone, Mac and
  glasses. Tool calls move the robot's ritual and write to the consented notebook. Clients receive a
  short-lived token from the cloud and never hold the API key.
- **Gemini TTS and embeddings.** One consistent voice for fixed lines; semantic recall of the person's own
  notes.
- **Gemma 4.** Chooses evidence for the practitioner review, proposes how to organise the notebook into a
  graph of activities and routines, and answers the companion's deeper questions. Code checks every citation and
  renders every number. Run through the hosted API in this prototype. A Modal GPU deployment is implemented and
  has not been run, so we do not claim that data stays on our own infrastructure.
- **Modal.** The API, dashboard, database volume, scheduled analytics and a parallel simulation of synthetic
  people are written as one Modal app, with a separate scale-to-zero GPU app for Gemma. `[verify: state the
  public URL here once deployed; until then say "implemented, running locally"]`
- **Meta Wearables Device Access Toolkit** (iOS). Registration, device session and head motion from Gen 2
  glasses, in Developer Mode. Registration and connection confirmed on real glasses. `[verify: motion and audio
  on the device]`
- **Atech.** One 14-port ESP32 board with eight modules: screen, encoder, button, two LED grids, motor,
  speaker, microphone. The firmware compiles and parts have run on the board. `[verify: live link to the hub]`
- **Arduino UNO Q.** Knock sensor, buzzer and camera for face position, processed on the board.
- **Architecture.** One versioned message contract (MQTT at home, HTTPS to the cloud). Every hardware part has
  a software twin, so each piece can be developed, replaced or removed on its own. SwiftUI apps, Next.js
  dashboard, FastAPI, SQLite.

### For the Gemini challenge: the four questions
1. **Problem.** People lose the benefit of treatment at home without anyone noticing, and cannot be expected to
   type reports while their energy is lowest.
2. **Integration.** Live sessions on four surfaces, bootstrapped by the cloud with a small prepared context;
   validated function calls; TTS; embeddings.
3. **What is new.** The voice has hands: its tool calls advance a physical ritual and a walk, while measurement
   and safety stay in deterministic code that the model cannot override.
4. **Why Gemini.** A check-in without typing needs low-latency speech that can be interrupted and can act.
   Without Live there is no ritual and no walk companion.

## Safety, privacy and limits

- **Research prototype.** Not a medical device and not a crisis service. Kaiku reports change from a person's
  usual; it does not diagnose.
- **All records shown are authored and labelled as simulated.** Thresholds have not been calibrated on
  patients, and the activities are not validated instruments. `[verify: one line on the calibration evaluation
  against simulated trajectories]`
- **Crisis path without AI.** A fixed phrase list, PHQ-9 item 9 or a long press on the robot's button shows a
  pre-written message with the MIELI Crisis Helpline (09 2525 0111) and 112, and sets a safety state on the
  dashboard. It does not call anyone and it will miss indirect language.
- **Derived numbers only.** The cloud rejects raw audio and images. Camera frames are processed in memory.
  During a conversation the person started, audio is streamed to Gemini Live. Conversation text is stored only
  after a separate opt-in and is never shown to practitioners.
- **Hardware honesty.** Robot pulse, room light and tap force are not measured in this build. The music adapter
  (Lyria RealTime) is not part of the demo.

## What's next
A pilot with a neuromodulation unit: compare the consensus with clinician assessment for eight to twelve weeks
after a TMS course, measure how often people complete the ritual, and calibrate the thresholds on real data.
Then the EU medical-device pathway.
