# Track readiness audit

Audit of the working tree on 14 November 2026 (branch `companion-apps`), read from code, not from earlier docs.
Briefs: `docs/tracks/*.pdf`. Final submission closes **Sunday 15 November 10:00**; drafts are not reviewed.
Status words: **met** (code and evidence exist), **partial** (built, but a named proof is missing), **not met**.
"Landing" marks work other workstreams were finishing during this audit: verify before FINAL.

## 1. Conditions every track shares (Junction guide)

| Requirement | Status | Evidence / smallest fix |
|---|---|---|
| Pitch video, **maximum 2:00**, public ("not a second longer") | not met | Not recorded. Script: `docs/demo-narrative.md` (1:55 cut). Export at 1:58. |
| Pitch deck (PDF) | not met | None in the repo. Also asked for by the Meta brief ("functional prototype and deck"). |
| Demo link and source link, MIT, source readable by organisers | partial | `LICENSE` present, repo public. No demo URL: nothing has been deployed (§2 Modal). |
| Project set to FINAL before the deadline | open | Lead. |
| Whole team present for peer review, Sunday 10:30–14:00 | open | Required for the main prize. |
| All code written at the event | met | First commit 13 Nov 20:17 UTC. |
| Team size 1–4 | not confirmed | Git history shows three authors; the module index names owners A–D. Confirm the roster. |

## 2. Requirements per track

### Aalto: Beyond the Clinic (main; four criteria, 25% each)

| Requirement | Status | Evidence | Smallest fix |
|---|---|---|---|
| Usefulness: could it help people stay well at home? | partial | Full loop runs on authored records: ingest → baseline → verdict → consensus → dashboard → care action (`cloud/kaiku_cloud/analytics/`, `cloud/kaiku_cloud/api/main.py`). No real-person data; thresholds are not clinically calibrated. | Say this in one sentence in the pitch and show the calibration evaluation (landing). |
| Ease of use: would someone recovering from depression use it daily? | partial | Robot starts the ritual; dial, breath, drum need no typing (`hub/kaiku_hub/rituals/`). Phone onboarding without QR or robot (`apps/apple/.../Screens/OnboardingFlow.swift`). | `docs/validation.md` holds only the project lead's sessions. Run three short sessions with booth mentors or other hackers and log what changed. |
| Smart sensing: clever use of home measurement | met in software | 19 enabled metrics across four signal groups, each against a personal median/MAD baseline (`config/criteria.toml`, `analytics/baseline.py`, `drift.py`). | The brief calls HRV / autonomic signals "very important". Robot pulse is disabled; the only autonomic input is the optional Apple Health daily summary. Show it if the watch data is real, otherwise do not mention HRV. |
| ...and learns what works for each person (closed loop) | met in software | Thompson-sampling learner over implemented activities with before/after and next-day outcome (`analytics/bandit.py`, `GET /v1/nudge`). | Show one suggestion changing after feedback. Call it "observed response", not efficacy. |
| Creativity: original and delightful | met | Robot with a drum for a head, mascot, Firefly and Pebbles games. | Games depth is landing: verify. |
| Audiences named in the brief (after TMS, at risk, clinicians without extra workload) | met | Person apps and one practitioner dashboard (`apps/web/` (dashboard being rebuilt: verify path)). | Keep "one glance, who needs a call" as the dashboard's first screen. |

### Best Use of Gemini API (no weights given; four things the submission "should clearly explain")

| Requirement | Status | Evidence | Smallest fix |
|---|---|---|---|
| Problem and why it matters | met | `docs/submission.md`. | — |
| How the API is integrated | met | Live voice with function calling on the robot (`hub/kaiku_hub/live/gemini_live.py`, `tools.py`) and natively in the apps (`apps/apple/KaikuKit/Sources/KaikuKit/Talk/`), short-lived tokens minted by the cloud (`mind/live_token.py`), TTS for fixed lines (`cloud/kaiku_cloud/voice.py`), embeddings for memory recall (`mind/memory.py`). | — |
| What is innovative or technically impressive | partial | Tool calls drive a physical ritual; one prepared context across robot, phone, Mac and glasses; a deterministic safety gate scans transcript fragments. Real-provider proof exists for the native Live path with injected audio. | Record one real spoken exchange on the phone or glasses with a tool call (`remember` or an activity) visible. |
| Why Gemini is essential | met | No-typing ritual and walk companion need low-latency speech with barge-in. | — |
| Lyria RealTime | partial | Adapter (`hub/kaiku_hub/live/lyria.py`) ran a whole ritual on 14 Nov evening with the real model, simulated taps and the sound into a file: first audio 1.3 to 1.8 s, the music followed a tempo change in about 4 s. Off by default; never played through a speaker in a room; BPM range still marked `VERIFY` in `config/kaiku.toml`. | Leave it out of the video unless it plays on the robot. Never list it as a working feature otherwise. |

### Best Use of Gemma ("most innovative and impactful use", "strong technical execution", "open models solving real-world problems")

| Requirement | Status | Evidence | Smallest fix |
|---|---|---|---|
| Innovative, impactful use | met | Gemma 4 selects evidence for the practitioner review while code renders every number (`cloud/kaiku_cloud/clinician_chat.py`); proposes graph merges that code validates (`mind/nightly.py`, `mind/graph.py`); answers the companion's deeper questions with verified citations (`mind/router.py`). | Review and trace API are landing: verify. |
| Strong technical execution | partial | Bounded retries, citation and banned-wording validation, deterministic fallback (`llm/explain.py`). Verified through the hosted API (`llm/gemma_hosted.py`, model `gemma-4-26b-a4b-it`), which the brief lists as an allowed access route. | Show the trace: evidence in → selection → validated → rendered. |
| Open model on our own infrastructure | partial | `cloud/gemma_app.py` (vLLM on an H100, scale to zero) is deployed and every Gemma call follows one switch (`[gemma].provider`, `llm/gemma.py`). On 15 Nov the practitioner review and a record question were answered by it and passed every check, on Aino's simulated record from a local API. The public demo stays on the hosted API; `ask_mind`, the nightly graph and the deployed API as caller have not run on the GPU. A cold start takes about four minutes, so the first call after a quiet spell shows the deterministic text. |
| Fine-tuning | not required | The brief does not mention it. See §6. | — |

### Best Use of Modal (effective use 40%, technical ambition 25%, impact 20%, demo 15%)

| Requirement | Status | Evidence | Smallest fix |
|---|---|---|---|
| Demo: "a live, deployed app the judges can actually use" | **not met** | No deployment is recorded anywhere; the current API runs on the LAN. | `make cloud-deploy`, seed the authored record, open the practitioner dashboard from a phone on mobile data. Set clinician and admin tokens in the Modal secret first: `/v1/admin/reset` and the criteria editor must not be open on a public URL. |
| Effective use: how central Modal is, "from GPU inference to Sandboxes, training and scaling out" | partial (code only) | `cloud/app.py`: one warm ASGI container, Volume with commit after writes, Secrets, 15-minute / nightly / weekly schedules, `.map()` over 8 shards of 72 synthetic people. `cloud/gemma_app.py`: GPU class, weights on a Volume. None of it has run on Modal. | Deploy both apps and run `make gemma-smoke` once. GPU inference is the first thing the criterion names. |
| Technical ambition | partial | Same as above, plus the simulation fan-out. | Show `/eval` from the deployed URL. |
| Impact on the main challenge | met once deployed | The dashboard and every ingest route are the Modal app. | — |

This is the track where the gap between code and proof is largest. Without a public URL the entry scores zero
on Demo and cannot evidence the 40% criterion.

### Meta: AI Glasses for Everyone, Everyday (four criteria, 25% each)

| Requirement | Status | Evidence | Smallest fix |
|---|---|---|---|
| Uses Meta AI glasses; DAT mobile integrations and audio-first count equally | partial | Real DAT adapter: configure → registration through Meta AI → device session → Motion (`apps/apple/iOS/DATGlasses.swift`, MWDAT 1.0.1). Registration and "connected" confirmed on the lead's Gen 2. Motion has not run against real glasses. | One real 5-minute walk with screen recording. |
| "First-person field of view enables new or better interactions" | partial | Opt-in camera (D43): with "Let Kaiku see" on, about one glasses frame a second goes to the walk's Gemini Live conversation, so Kaiku can answer "what am I looking at?". Proven with Mock Device Kit and a real Live call on an injected picture; not yet on the real glasses (`docs/glasses-test.md`). Without it, the first-person value is audio in the ear, head up, hands free, and head motion (cadence, regularity, head-up ratio) from the glasses IMU. | Say this plainly; never say the glasses "see". If Motion does not deliver samples on the real device, drop the head-motion claim and keep the audio companion. |
| Functional prototype **and deck** | partial | Prototype yes; deck missing. | Deck with one glasses slide: problem, audience, wearable benefit, pilot path. |
| Handles permissions | met | Explicit setup action that does not open the microphone (`DATGlasses.register()`); `Info.plist` has `NSBluetoothAlwaysUsageDescription` and `bluetooth-central`, which the DAT docs require for the BLE link. | — |
| Handles errors, connectivity, device state changes | met in code | Session states map to searching / set-up needed / motion unavailable / lost; a mid-walk drop tells the companion and the walk continues on the phone (`Walk/WalkModel.swift:178`, `Walk/WalkView.swift:104`). Tested with the mock adapter (`-kaikuGlassesDropAfter`). | Film taking the glasses off mid-walk. |
| Performance trade-offs | partial | 30 Hz motion batched in sixes; HFP is mono 8/16 kHz, chosen because it is the only route that gives the glasses microphone (`Voice/TalkAudio.swift`). | Have the sentence ready; it is in `docs/demo-narrative.md`. |
| Inclusive interaction for all abilities | partial | Audio-first, nothing to type, works without a display. Only 22 accessibility annotations in KaikuKit. | VoiceOver pass over Walk and Talk; fix unlabeled buttons. |
| Consent and safe data practices in the demo | partial | Registration is explicit; only derived numbers are saved; transcripts are opt-in. No dedicated "what is shared" screen was found in the Apple sources. | Onboarding consent is landing: verify it names the glasses microphone. |
| Plausible path to adoption or pilot | partial | Stated as one signal group in an Aalto / neuromodulation-unit pilot. | Add the DAT facts: this build runs in Developer Mode (`MetaAppID` 0, no attestation); a pilot needs a Developer Center project, client token, universal link and an invite-only release channel; Motion is beta and not available in production channels. |

DAT conditions checked in the wearables docs (v1.0): registration and all permission grants happen in the Meta
AI app; Developer Mode allows only one third-party app registered at a time; microphone and speaker access is
standard Bluetooth (HFP), not a DAT capability; the Motion capability is beta, development and beta channels only.
`apps/glasses-webapp/` and `apps/glasses-dat-android/` contain instructions only. They are not part of the entry.

### Atech Real World (four criteria, 25% each; bonus for several modules and AI/API connection)

| Requirement | Status | Evidence | Smallest fix |
|---|---|---|---|
| Minimum: Atech modules in the demo with a real-world solution | partial | Eight module instances on the 14-port board (`firmware/atech-head/project.yaml`): speaker, TFT eyes, encoder, DC motor, microphone, button, two LED grids. Full firmware compiles. | See "live demo". |
| Minimum: link to a summary / post shared in Atech's Discord | not met | Not done. | Post the repo link with three sentences and a photo. |
| Submission: live demo on the hardware | not met yet | Benches run on the board so far: microphone, LED grid on port 14. Motor, display, speaker and knob fixes build but still need a run; the MQTT link bench has not run; port 11 does not light its grid. | Smallest honest live loop: knob turn → `raw.head.*` over MQTT → hub → dashboard record, with eyes and chest LEDs responding. Everything else is optional. |
| Submission: public repo, ~2-minute video | partial | Repo yes; video pending. | The video must show the real board. |
| Real-world validation: "tested with real users, experts or real-world data" | **not met** | Only the lead's own sessions are logged. | Three people try the dial and drum at the table; one Aalto mentor comments. Log in `docs/validation.md`. |
| Real-world impact: a real user and problem | met | Person after TMS; initiative loss. | — |
| Use of Atech: hardware **and AI platform** | partial | `atech` CLI validate/build flow and `pip install atech` are used; firmware logic is hand-written in `kaiku_link/`. | Say which parts the platform generated and which were written by hand. |
| Bonus | met when live | Several modules, plus Gemini Live and the cloud. | — |

## 3. Gaps ranked by judging impact

1. **Public deployment: done (14 Nov).** https://harrish21raj--kaiku-web.us-east.modal.run/?id=aino serves the dashboard with one seeded, simulated record in read-only demo mode; admin routes need a token. Still open for Modal: the Gemma GPU class has answered one smoke call only and is not in the default path.
2. **No video and no deck.** Both are submission conditions; the video limit is 2:00, not 3:00.
3. **README contradicts the code** in the Gemma, Meta and overview sections (§5). A judge who opens the repo first reads claims the product does not support.
4. **No validation beyond the team.** Atech weighs it 25%; Aalto's "would someone actually use it" needs it too.
5. **Atech live loop on real hardware** has not run end to end, and the Discord post is a minimum requirement.
6. **Glasses proof is registration only.** One filmed real walk (voice in the glasses, glasses removed, walk continues) covers four Meta requirements at once.
7. **Gemma on our own GPU is proven for two paths only** (the review and a record question, 15 Nov, local API). The public demo uses the hosted API; say "production runs it on our own GPU, the demo you are looking at uses Google's API".
8. **The authored 16-day record and the consensus rule.** See §4, weak point 1: check what the timeline really shows for the dip days before narrating it.
9. **Autonomic sensing.** The Aalto brief highlights HRV; robot pulse is disabled. Show Apple Health data only if real.
10. **Track PDFs in a public repo** contain the venue Wi-Fi password, a credit redemption code and mentor e-mail addresses (`docs/tracks/guide.pdf`, `modal.pdf`, `atech.pdf`). Root `AGENTS.md` forbids exactly this. Remove or replace with links before FINAL.

## 4. How each service is built, and what is real

| Service | How it works | Real today | Simulated or pending |
|---|---|---|---|
| Robot hub (`hub/`) | A Python process on a laptop. It listens to the robot's parts over MQTT, runs the morning ritual as a state machine, holds the Gemini Live call, checks every utterance against the crisis list, and uploads only derived numbers with retry. | Runs against hardware twins with real MQTT; real Gemini Live with injected audio. | No run with the physical robot's microphone, speaker or motor. |
| Firmware (`firmware/`) | Atech ESP32 board drives eyes, knob, button, LEDs, motor and speaker; an Arduino UNO Q reads knock, pulse and camera. Both speak the same MQTT messages as their twins. | UNO Q: buzzer, knock and camera benches pass on the board; sketch compiles. Atech: full firmware compiles; microphone and one LED grid seen working. | Pulse (no heartbeat found outside the cradle), Atech link to the hub, motor/display/speaker runs. Friendlink has no firmware. |
| iPhone and Mac apps (`apps/apple/`) | One SwiftUI codebase: Today, Play, Talk, History (since 14 Nov evening; it holds Your days), You. Games and check-ins post observations straight to the cloud through a durable outbox; Talk is a Gemini Live call with a token from the cloud; the Mac adds app-category rhythm. | Signed build installed on a real iPhone; discovery and `/v1/me` seen from the phone. 116 Swift tests pass. | Physical microphone, HealthKit and backgrounding acceptance. |
| Glasses (`apps/apple/iOS/DATGlasses.swift`) | The iPhone registers with Meta AI through DAT, opens a device session and reads head motion; the voice travels over ordinary Bluetooth to the same Live conversation. | Registration and connection on a real Gen 2. | Motion samples and audio routing on the real device. No camera. |
| Cloud and consensus (`cloud/`) | FastAPI + SQLite. Each observation is validated, grouped by measured day, compared with the person's own median/MAD baseline, turned into a per-group verdict, then combined by a fixed rule read from `config/criteria.toml`. | 636 Python tests; real HTTP pipeline; runs on the LAN. | Not deployed. Thresholds are engineering defaults, not clinically calibrated. |
| Intelligence | Gemini Live speaks from a small prepared context. Gemma 4 picks evidence, proposes graph changes and answers deeper questions; code validates citations and renders numbers. No model sets a state or handles a crisis. | Hosted Gemma and native Live verified with real provider calls on synthetic input. | One native run did not call the reasoning tool; no private GPU run. |
| Dashboard (`apps/web/`) | Static Next.js pages served by the same API: ranked list, per-person trends, evidence-linked review, routines, week comparison, care actions. | Browser-verified against the LAN API. | Person-facing web pages are being retired (landing). |

### Weak points a sharp judge will probe

1. **"Sixteen days: where does the baseline come from?"** The rule uses a 14-day window that ends 7 days before the scored day and needs 7 usable days. On a 16-day record nothing can be scored before day 14. A dip on days 9–12 is visible in trends and in the first-week / latest-week comparison, but the rule could not have raised "needs a call" on those days. On day 14 the last five readings include days 10–12, so a group can turn "worse" two days after the dip ended. Honest answer: "Early in a record Kaiku says *insufficient* and shows the evidence; it does not guess. The rule needs three weeks to speak." Never narrate a flag the timeline does not show.
2. **"Is any of this validated?"** No. Every person in the dashboard is authored data. Thresholds, weights and games are uncalibrated; PHQ-9 is the only validated instrument. The calibration evaluation measures the rule against simulated trajectories, which tests the software, not clinical accuracy.
3. **"Are the four groups independent?"** No. Mood dial, games and steps can all come from one phone. That is why they are called signal groups and each record keeps its real device source.
4. **"Does the robot work?"** Parts do. Say which benches passed; show the twin for the rest and label it.
5. **"What happens in a crisis?"** A fixed phrase list, PHQ-9 item 9 or a long button press shows a pre-written script with MIELI 09 2525 0111 and 112 and sets a safety flag on the dashboard. It contacts nobody. The list misses indirect language.
6. **"Does private data stay on your infrastructure?"** No. Gemma runs through Google's hosted API and conversation audio goes to Gemini Live; Live session state can persist at the provider for up to 24 hours. Only authored records were sent in the proofs.
7. **"Does the care action do anything?"** It records the flag and can queue a message for the robot. It does not page a clinician, send SMS or book treatment. Recovery after an action in the record is an observed association.
8. **"Why should Modal care?"** Until it is deployed, it should not. After: one container serves the product, schedules run the analytics, `.map()` runs the simulation, a GPU class serves Gemma at zero idle cost.

## 5. Claims the code does not support

Fixed in this pass (files owned by docs): `docs/tracks.md`, `docs/submission.md`, `docs/tracks/INDEX.md`.

`README.md` (owner: demo-data workstream). Replace, do not soften:

| README says | Code says | Replace with |
|---|---|---|
| "tells your care team when it matters" | No outbound notification exists. | "a clearer record for your care team" |
| "Three independent sources" (five places) | Four signal groups; several can share one phone. | "signal groups, each with its real device source" |
| Robot "greets them in Finnish"; Live "in Finnish and English" | English only (D40). | "greets them" |
| "finger on the chest for heart rate and HRV"; "HR + HRV around guided breathing" | Robot pulse disabled; no heartbeat found on the bench. | "guided breathing with a glowing chest" |
| "Lyria RealTime turns the rhythm into music" | Adapter only; not accepted on a device. | Remove, or "optional music adapter, not in the demo" |
| "drumming tempo/force", "IMU tap detection" | Knock switch; no force, no IMU module on the board. | "tap timing and tempo" |
| "get-up time, room light", "time outdoors", "daylight" | Light disabled; first interaction is not wake time; no outdoor or daylight measure. | "first interaction time, outings and steps" |
| Laptop "voice features, facial expressivity" as a source | Browser tasks retired from scoring. | "games and check-ins on phone and Mac; optional Mac rhythm" |
| Meta: "Ray-Ban Display web app (WebMCP tools)", "glanceable cards", "what is shared screen", Android DAT daylight app | Those folders hold instructions only. The integration is the iPhone DAT adapter with Gen 2 audio. | The Meta row in `docs/tracks.md` |
| Gemma "runs on our own Modal GPU ... never goes to a third-party API" | Runs through Google's hosted API. | The Gemma row in `docs/tracks.md` |
| Modal "One public URL the judges can open" | Deployed and seeded (simulated record): https://harrish21raj--kaiku-web.us-east.modal.run/?id=aino | Say the record is simulated |
| "a lamp that glows at a friend's home", "a message to a friend", LoRa friend link | No friendlink firmware; removed from suggestions. | Remove |
| "Catches change early enough for a booster or a referral" | No evidence of lead time. | "shows change from a person's usual so a clinician can decide to check in" |
| "Day 23 (simulated)", `/me/`, `/session/`, `/phq9/` page table | Record is 16 days; person web pages are being retired. | Practitioner dashboard only (verify) |
| Atech "Live demo on the hardware ✅" | Not yet run end to end. | Tick only after it runs |

`demo/demo_script.md` and `demo/video_shotlist.md` repeat the same stale claims (three independent sources, HRV,
"Aino (SIMULATED 30 days)", `/session/`, iCBT route, "music follows"). Replace both with
`docs/demo-narrative.md`.

The web consent page carried the same "three independent sources, and tells your care team" sentence. It was
removed with the other person-facing web pages while this audit ran; confirm no replacement repeats it.

Unsourced figure: "only about half of initial responders still responded 6–12 months later" names "a
meta-analysis" without a reference. Put the citation in the deck or cut the number.

## 6. Should Gemma be fine-tuned?

**The briefs.** The Gemma brief does not mention fine-tuning. The Modal brief names it twice ("fine-tune a model
on your own data", Modal Dojo) as one of four ways to use the platform, alongside GPU inference, which is not
done yet either.

**What a fine-tune would be for.** Not personal baselines or memories; those must stay retrieved data. The one
defensible target is structured reliability on a small model: given an evidence list, return valid
evidence-selection JSON or a valid graph-diff, citing only IDs that exist, and refuse out-of-scope requests in
the fixed wording. A tuned 4B-class model could replace the hosted 26B model on those two tasks and run on a
small GPU.

**Options today.** Gemma 4 is published in E2B, E4B, 26B-A4B and 31B sizes (a 12B repo is referenced in
`config/kaiku.toml`; confirm it before relying on it). Unsloth documents LoRA on E4B at roughly 17 GB of VRAM and
QLoRA on 31B at about 22 GB, so an L4 or L40S on Modal is enough for E4B. A few hundred examples and one or two
epochs take well under an hour and a few dollars of credit. Serving: vLLM loads LoRA adapters beside the base
model, so `cloud/gemma_app.py` could serve base and adapter from one class. vLLM adapter support for Gemma 4
specifically was not confirmed in this audit.

**Is synthetic training data honest?** For this target, yes, if it is described correctly. The labels are not
clinical judgements; they are outputs that already pass the deterministic validators (existing citation IDs,
schema, banned wording). That is distillation of a format, and the same validators stay in place after tuning.
It would be dishonest to imply the model learned anything about depression, or to report results on anything but
held-out synthetic cases split by scenario.

**Recommendation for the time left.** Do not put a fine-tune on the critical path.

1. Deploy the API on Modal and record the URL (worth more than any model work).
2. Deploy `gemma_app.py`, run the one smoke call, and optionally route the practitioner review to it for the demo.
3. Only if both are done with four or more hours left: a 90-minute timeboxed E4B LoRA on Modal, with an evaluation
   written first: schema-valid rate and citation-valid rate on about 50 held-out synthetic cases, base E4B versus
   tuned E4B versus hosted 26B. Ship the adapter only if it beats base E4B; otherwise report the numbers as a
   negative result.

**What could be claimed.** With step 3: "a LoRA adapter trained on Modal from synthetic, validator-labelled
records raised schema-valid output from X% to Y% on N held-out synthetic cases". Without it: "prompt, bounded
retry and code validation; no tuned weights", which is what `docs/submission.md` says now.

## 7. Not confirmed

- Junction Hackerpack contents and any event-specific Gemma credits or access rules (not in the repo).
- Whether partner judges watch the 2-minute video, visit the table, or both, for each tech challenge.
- Team roster against the 1–4 limit.
- The citation behind the "about half of responders" figure.
- vLLM LoRA serving for Gemma 4, and the 12B Gemma 4 repository.
- Everything marked "landing": practitioner-only web, richer games, robot sensor features and local raw store,
  Gemma review and trace API, calibration evaluation, onboarding, and the 16-day record with a dip.

Sources for §6: [Unsloth Gemma 4 fine-tuning guide](https://unsloth.ai/docs/models/gemma-4/train),
[Google Gemma tuning](https://ai.google.dev/gemma/docs/tune),
[Modal fine-tuning example](https://modal.com/docs/examples/llm-finetuning.md),
[Modal fine-tuning overview](https://modal.com/use-cases/fine-tuning).
DAT facts: [build an iOS integration](https://wearables.developer.meta.com/docs/develop/dat/build-integration-ios),
[permissions and registration](https://wearables.developer.meta.com/docs/develop/dat/permissions-requests),
[microphones and speakers](https://wearables.developer.meta.com/docs/develop/dat/microphones-and-speakers),
[motion](https://wearables.developer.meta.com/docs/develop/dat/motion).
