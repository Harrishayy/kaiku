# Junction submission text

> Ground truth for what we submit. Before FINAL, check every claim against what actually runs and soften the rest
> (docs/plans/01-foundation.md §15). The product name is **Kaiku**.

**Project name:** Kaiku

**Punchline:** A friend on your desk, a voice in your ear, a quiet eye on your days. Kaiku notices how you're really doing after depression treatment, and tells your care team when it matters.

## Description

### The problem
TMS (transcranial magnetic stimulation) helps people with severe depression, but the effect often fades: in a meta-analysis, only about half of initial responders still responded 6–12 months later. Treatment means ~20 clinic visits, 3–5 days a week, with clinicians seeing the patient almost daily. When the visits end, that view disappears. Worsening caught early can often be reversed with a booster course, but at home nobody notices in time, and one questionnaire or wearable is too thin a signal to act on.

### Our approach
In hospital, a patient's state is never judged from one measurement: clinicians combine interviews, scales, observation and tests. **Kaiku brings that principle home.** Three touchpoints each observe the person independently, and a dashboard combines them into **one consensus answer about their current state**, with the evidence behind it.

#### 1. Home robot
A small companion robot with a moving head and animated eyes. Each morning it turns to find you and runs a ~3-minute ritual:
- **Ear dial:** rate mood, energy and last night's sleep with three turns. No typing.
- **Pulse sensor:** finger on its chest for resting heart rate and HRV, then a guided breathing exercise with a glowing chest, then HRV again.
- **Drumming:** tap its head and Google's Lyria RealTime turns your rhythm into music that follows you, inspired by a Finnish randomised trial of improvisational music therapy for depression. Tempo, force and duration also track energy, no questions asked.
- **Voice:** speech rate and pauses from the conversation, computed locally.
- **Passive:** get-up time and room light from presence and light sensors.

*Apps wait to be opened and voice assistants wait to be spoken to. Depression takes away that initiative, so Kaiku reaches out first.*

#### 2. Meta AI glasses
An audio-first walk companion on Ray-Ban Display glasses encourages daylight walks and logs time outdoors, capturing life beyond the living room.

#### 3. Laptop apps
- **2-minute session:** a spoken prompt and a short reaction task. Voice and webcam facial expressivity are analysed on the laptop; only derived numbers are kept.
- **PHQ-9 every two weeks:** the standard clinical cadence, anchoring everything to a validated scale.

### From three readings to one consensus
Each source compares today with the person's **own baseline** and returns a verdict (*better / as usual / worse*) plus a confidence based on how much good data it has.

| Consensus | Rule |
|---|---|
| **Stable** | Sources report as usual or better |
| **Watch** | One source reports worse |
| **Needs a call** | Two or more independent sources report worse |

The rule is fixed and auditable; Gemma (an open-weights model) only writes the plain-language explanation. **Disagreement is shown, not hidden**, e.g. "robot: worse (lower HRV, slower drumming); glasses: as usual (walking daily); laptop: worse (flatter voice)." The signals mirror those that European studies such as RADAR-MDD link to relapse: sleep, activity, mood and speech.

### The dashboard
- **Clinicians:** a list ranked by consensus, each person's three source cards, trends against baseline and the evidence for every flag. From there they can flag someone for a booster TMS session or a referral to Finland's national internet therapy (Mielenterveystalo). No extra workload between visits.
- **The person:** the same picture in plain language, and which activities have helped them most.

### Closed loop
Each activity (breathing, drumming, a walk, a friend ping) is scored immediately (HRV and mood before vs after) and next day; a bandit learner picks each person's next suggestion.

### Technology
- **Gemini Live API:** real-time Finnish/English voice with function calling driving the ritual.
- **Lyria RealTime:** music steered live by drumming.
- **Gemma 4 on Modal:** served on GPU for explanations, keeping health reasoning on infrastructure we control.
- **Modal:** ingest API, storage, scheduled analytics, model serving, consensus-accuracy simulation on synthetic patients, dashboard hosting.
- **Robot:** Atech modules and Arduino UNO Q: animated eyes, IMU tap detection, DC-motor head, ear encoder, pulse, light and distance sensors.
- **Glasses:** Meta Ray-Ban Display Web App.
- **Architecture:** one versioned message contract (MQTT at home, HTTPS to cloud); each touchpoint can be swapped independently.

### Safety and privacy
- **Only derived numbers leave the home.** Camera frames are never stored.
- **Deterministic crisis path.** A positive PHQ-9 item 9 or crisis language triggers a fixed response with no AI: MIELI's 24/7 crisis line (09 2525 0111) and 112 are shown, and the clinician is alerted.
- **Not diagnostic.** Kaiku reports change, not diagnoses. Demo history is synthetic and labelled.

### What's next
A pilot with Aalto and a neuromodulation unit to validate the consensus against clinician assessments, then the EU medical-device pathway and reimbursement routes such as Germany's DiGA.
