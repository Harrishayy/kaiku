# Privacy

| Data | Where it goes | Stored? |
|---|---|---|
| Robot camera frames (USB camera in the head, read on the UNO Q, D32) | processed in memory on the UNO Q (or the hub laptop's camera) into face position (`raw.hub.face`: x, y, size) and a distance estimate. Only as backups: mean room luminance and the mean green of the forehead patch (`raw.sensors.ppg`) | never; frames never written, logged or transmitted; the camera mic is never opened |
| Robot pulse (KY-039 in the lid cradle, via KY-053) | 100 Hz light samples on the local bus only during the breathing step (`raw.sensors.ppg`) → HR / HRV numbers in `obs.hrv_session` | samples never uplinked; numbers only |
| Robot knob, button, knock drum, light, hall | dial values 1–5, press/tap timing, KY-054 light level, head-at-front edge → `obs.self_report`, `obs.drum_session`, `obs.light_level` | numbers only |
| Laptop webcam frames (`/session`) | processed in the browser for a facial-expressivity number only | never; never transmitted |
| Microphone audio | streamed only to Gemini Live during an active, consented conversation | never by us |
| Speech | robot: rate + pauses as `obs.speech_features`; laptop session: rate, pauses, pitch variability in-browser in `obs.laptop_session` | features only, no transcripts |
| Reaction task | median / IQR / lapses in `obs.laptop_session` | numbers only |
| Glasses walks | minutes, steps (location from the paired phone, not stored as a track) in `obs.outing` | numbers only |
| Glasses IMU (DAT SDK, beta) | cadence, gait regularity, head-up ratio computed on the iPhone; raw motion never leaves it | numbers only |
| Glasses camera (DAT, optional) | sparse frames → daylight minutes on the iPhone, frames discarded immediately | never; never transmitted |
| Glasses mic / spoken answers | on-device speech recognition parses a dial value; speech features during "Tell Kaiku" | no audio, no transcript; numbers only |
| Mac usage rhythm (opt-in, pausable) | frontmost app's **bundle id → broad category on the Mac**, idle time; hourly `obs.screen_activity` (minutes per category, late-night minutes, switches, longest stretch, breaks) | numbers only. **Never** window titles, URLs, keystrokes, screenshots or content (the contract rejects extra fields) |
| Games (firefly, breathe, tell) | reaction / speech / HR features computed on the device in `obs.play_session` | numbers only |
| Watch / Apple Health (optional) | daily summary on the iPhone: sleep minutes + midpoint + regularity, resting HR, HRV, steps, exercise (`obs.wearable_daily`) | daily aggregates only; no raw samples, no location |
| Weather check on phone / Mac / web | three dial values (`obs.self_report`, `channel`) | numbers only |
| Kaiku's notebook (memories) | short facts the person chose to tell Kaiku (`remember`: name, people, places, likes, what helps, plans, preference) in the cloud SQLite | yes, until the person deletes them ("What Kaiku remembers": delete one / all, "don't remember things"); plans expire after 7 days. **Never** health details (refused by rule), never shown to clinicians |
| Episodes | one row per conversation: surface, intent, start/end, tool names, how it ended | yes; **no transcript, no audio** |
| Open thread | one short topic to pick up next time on any device ("the walk by the lake"), expires after 3 days | yes |
| Kaiku's voice (`/v1/voice`) | fixed script text → Gemini TTS in the cloud | rendered audio of the script only (no personal data) |
| Raw sensor streams (`raw/*`) | local MQTT on the home network | never uplinked (cloud rejects them) |
| Observations (`obs/*`) | uplinked to the Modal cloud | yes: derived numbers, ritual metadata |
| PHQ-9 | total, 9 item scores, item-9 flag (`obs.phq9`) | yes |
| Verdicts, consensus, explanations | computed in the cloud from derived numbers | yes |
| Clinician briefs | generated in the cloud from derived numbers | yes |

- The robot has a physical camera shutter and status LED; the camera is enabled only when someone is near.
- The `/consent` screen explains this table in plain language; the glasses app has its own "what is shared" screen.
- Every plan-02 signal is opt-in per signal, pausable (Mac menu bar), and listed in "What Kaiku saw today".
- A missing source (no watch, no Mac) is simply not counted; it never makes the consensus look worse.
- Browser apps never hold the Gemini key; they authenticate with a pairing token (D16).
- **Memory (plan 03 §6):** Kaiku only keeps what the person tells it and agrees to. "Don't remember that" deletes
  the newest memory; "don't remember things" (or the switch on `/me`) stops all writes until turned back on.
  Categories outside the list, and any text naming medication, treatment, therapy, sleep/heart data, diagnoses or
  similar, are refused. A crisis phrase in any tool call stores nothing and raises the deterministic safety path.
  Clinician routes never read memories, episodes or threads (tested). The model only sees ≤ 3 memories, a name,
  routines and the open thread in the context card — never the consensus state, scores or watch data (`tone`
  `steady|gentle|extra-gentle` is the only soft cue).
- All demo data is synthetic and labelled SIMULATED (`sim: true`).
- No real patient data is used at the hackathon.
