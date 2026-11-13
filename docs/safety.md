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
- Offline: the local script and numbers still show; the clinician is only notified once the uplink
  reconnects (queued with priority).
- State **Safety** comes only from `safety_flag`. The consensus rule (deterministic, no LLM) can at most produce
  **needs a call**; Gemma only writes the explanation and never changes a state.

## Changing the list
Add phrases freely; removing one needs a note in `docs/progress.md` with the reason. Review with a
clinician/mentor before the demo.
