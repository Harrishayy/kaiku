# Safety

Kaiku is a research prototype. **It is not a crisis service, not a medical device, and does not replace
clinicians.** Every screen and the pitch say so.

## Crisis path (deterministic — no LLM anywhere)
Triggers (all unit-tested in `hub/tests`):
1. PHQ-9 item 9 > 0 — laptop `/phq9` page or the robot's spoken PHQ-9 step (both modes obey this).
2. A phrase from `config/safety_phrases.toml` (en/fi/sv) in a live or text-mode utterance.
3. Manual: long-press (≥ 2 s) of the robot's top button (`raw.sensors.button id=top`).

Action, in order: stop the ritual → speak/display the pre-written script from `safety_phrases.toml`
verbatim → show **MIELI Crisis Helpline 09 2525 0111 (24/7)** and **112** → emit `obs.safety_flag`
on the priority uplink → consensus state **Safety** (overrides every source) with timestamp on the dashboard.

## Limits (say these out loud)
- The phrase list will miss things (sarcasm, indirect language, other languages, ASR errors) and will
  sometimes false-trigger. It is a safety net, not detection.
- Offline: the local script and numbers still show; a safety flag reaches the dashboard only after the uplink
  reconnects (queued with priority). This does not confirm a clinician has seen it or that an external call was made.
- **The robot on its own (D51).** When the hub runs on the robot with no screen of its own, the pre-written script
  is printed where nobody reads it and is never spoken: it is not sent to a voice model, by rule. What the person
  gets from the robot is: the conversation, its microphone and its speaker close at once, the ritual or game stops,
  and the hub asks the head to show the helpline's name and number and 112 (`cmd.head {show: "help"}`, text
  compiled into the firmware and checked against `config/kaiku.toml`). The flag still goes to the dashboard.
  **The robot as built has no display on its head (D54), so it cannot show that text** (its health message reports
  `help_screen: none`). A robot that talks must have the phone app beside it: its "I'm not OK" screen works on its
  own.
- State **Safety** comes only from `safety_flag`. The consensus rule (deterministic, no LLM) can at most produce
  **needs a call**; Gemma only writes the explanation and never changes a state.

## Seeing through the glasses (D43)
- Optional and off by default. When on, Gemini Live receives about one picture a second during a walk conversation.
  The model is told by context events when pictures start and stop, and `look_at_this` answers "cannot see"
  whenever no fresh frame was sent; it must not talk as if it sees otherwise.
- What it sees never decides anything: no state, no observation, no crisis trigger comes from a picture. The
  crisis path stays the phrase gate on the words the person says (on-device listener + input transcripts).
- It is not a navigation or hazard aid and must not be relied on for traffic, steps or obstacles. Surface rules
  forbid describing or identifying people in view. Pictures stop when the walk conversation is muted, paused,
  ended, or the app leaves the foreground (the Meta toolkit delivers raw frames only in the foreground).

## Camera during activities: face signs (D52)
- The counts of face movement (`obs.face_signs`) never enter the crisis path and never decide a state: they are
  shown and citable, not scored (`config/criteria.toml`, `role = "shown"`; tested on the seeded record: every
  verdict and state is the same with and without them).
- No model and no rule names an emotion from a face. Gemma's review is rejected if it does (`emotion_label`,
  `face_inference`), and it may cite a face record only beside a scored one.
- Kaiku never says it saw the person, never comments on a face or on how someone looks, and never brings up a
  camera. A clearly quieter face than the person's own usual can only make Kaiku's manner gentler (softer,
  shorter, asks less, offers nothing unasked), never with someone else in the room. Asked directly, it answers:
  "I can't see you. If Camera during activities is on, your device counts how the face moves: numbers only,
  never pictures, and you can switch it off."
- Limits: a quiet face has many ordinary reasons (concentration, tiredness, lighting, glasses, a cold, the
  angle of the phone). That is why it changes a manner and nothing else.

## What the model noted from pictures (D65)
- With the separate opt-in, Gemma looks at up to three pictures of a check-in and its note (`obs.vision_note`) is
  kept; the pictures are not. The note never enters the crisis path and never decides a state: no vote, no score.
- The note uses fixed words for what is visible (lowered, tense, smiling, resting). It is a model's description of a
  picture, wrong some of the time, and not proof of a feeling. Lighting, glasses, tiredness and concentration all
  change it. It is a reason to ask, never a conclusion.
- Kaiku never says a picture was looked at and never names a feeling from it; a lowered or tense note can only make
  its manner gentler.
- Describing expressions from pictures of a person is emotion recognition under the EU AI Act (high-risk in
  general). The lead accepted that risk on 2026-11-15 (D65). Not validated against people.

## Changing the list
Add phrases freely; removing one needs a note in `docs/progress.md` with the reason. Review with a
clinician/mentor before the demo.
