# Privacy

| Data | Where it goes | Stored? |
|---|---|---|
| Robot camera frames | processed in memory on the hub for face position only (`raw.hub.face`: x, y, size) | never; never transmitted |
| Laptop webcam frames (`/session`) | processed in the browser for a facial-expressivity number only | never; never transmitted |
| Microphone audio | streamed only to Gemini Live during an active, consented conversation | never by us |
| Speech | robot: rate + pauses as `obs.speech_features`; laptop session: rate, pauses, pitch variability in-browser in `obs.laptop_session` | features only, no transcripts |
| Reaction task | median / IQR / lapses in `obs.laptop_session` | numbers only |
| Glasses walks | minutes, steps (location from the paired phone, not stored as a track) in `obs.outing` | numbers only |
| Raw sensor streams (`raw/*`) | local MQTT on the home network | never uplinked (cloud rejects them) |
| Observations (`obs/*`) | uplinked to the Modal cloud | yes: derived numbers, ritual metadata |
| PHQ-9 | total, 9 item scores, item-9 flag (`obs.phq9`) | yes |
| Verdicts, consensus, explanations | computed in the cloud from derived numbers | yes |
| Clinician briefs | generated in the cloud from derived numbers | yes |

- The robot has a physical camera shutter and status LED; the camera is enabled only when someone is near.
- The `/consent` screen explains this table in plain language; the glasses app has its own "what is shared" screen.
- Browser apps never hold the Gemini key; they authenticate with a pairing token (D16).
- All demo data is synthetic and labelled SIMULATED (`sim: true`).
- No real patient data is used at the hackathon.
