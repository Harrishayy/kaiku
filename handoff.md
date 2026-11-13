# Kaiku — Agent Handoff & Build Plan (v2)

> **Audience:** any coding agent (Claude Code, Codex, Gemini CLI, Cursor, Muse Code) or human joining the team.
> **Event:** Junction 2026, Hype Areena, Espoo. Final submission **Sunday 15 Nov, 10:00 (Helsinki)**. Whole team at our table for peer review from 10:30.
> **This file is committed to a PUBLIC repo (MIT). Never paste API keys, Wi-Fi passwords, credit codes or tokens here.**

### Changelog
- **v2:** Name stays **Kaiku** (team decision; an earlier v2 draft said "Hexarp"). Reframed as a **multi-source state-estimation service**: three independent touchpoints (home robot, Meta glasses, laptop apps) each produce a verdict, and a deterministic **consensus engine** combines them on one dashboard. Weekly check-in replaced by a daily 3-question dial, a 2-minute laptop session, and PHQ-9 every 14 days. Interventions now scored immediately and next day. Contracts, modules, dashboard, demo, video and submission updated. Added: evidence bank, judges and track criteria, venue logistics, hardware build notes, claims checklist, final submission text (Appendix A).
- **v1:** Initial plan (single robot "Kaiku", weekly check-in, group corroboration).

---

## 0. Read this first (agents)

**If you are an agent starting fresh, do this in order:**

1. Read `AGENTS.md` (condensed rules + ground-truth map) and the `AGENTS.md` of the module you'll touch, then sections 0–6 of this file.
2. Check `docs/progress.md` (append-only log) for what is done, who owns what, and what is blocked.
3. Run `make setup && make doctor`. It reports what is installed, running and broken, incl. last data per source.
4. Pick ONE module (`modules.toml`, section 7). Work only inside that module folder plus its tests.
5. Before you finish: `make check`, run your module against the sims, update the ground truth you changed (module `AGENTS.md`, `modules.toml`, contracts, `config/criteria.toml`), append to `docs/progress.md` (template in section 18).

**Status (2026-11-13):** Phase 0 is built and v2 is implemented in code: contracts v2 + consensus source map, sims for all five twins (head, sensors, friendlink, glasses, laptop), tools, hub v2 ritual, cloud consensus v1 + simulation, Next.js web app. Quickstart: section 20. Agent context system: section 21.

**Golden rules — breaking these breaks the team:**

1. **Contracts are law.** Modules talk ONLY through the message contracts in `contracts/` (MQTT locally, HTTPS to the cloud). No module imports another module's code, except `contracts/`.
2. **Every module runs alone.** Each module has a `--sim` / mock mode and "Run standalone" instructions in its `AGENTS.md`. If it can't run without hardware or cloud, it isn't done.
3. **Adapters at the edges.** Device- or vendor-specific code lives in an adapter that converts to/from contract messages. Swapping hardware means writing a new adapter, nothing else.
4. **Contract changes are explicit.** Edit the pydantic models in `contracts/python/kaiku_contracts/` (`payloads.py`/`api.py`, an example in `registry.py`, the source mapping in `sources.py`), run `make contracts` (regenerates `contracts/schemas/` + `contracts/ts/`), bump `SCHEMA_VERSION` if breaking, update producers/consumers + `sim/`, log it in `docs/progress.md`. `make test` fails on stale generated files. Never silently change a payload shape.
5. **No raw media leaves the device that captured it.** Only derived numbers go to the cloud. Raw audio goes only to Gemini Live during a consented conversation. Camera frames (robot and laptop webcam) are processed in memory and never stored or transmitted. See section 12.
6. **The consensus rule and the crisis path are deterministic.** No LLM decides a patient's state or handles a crisis. Gemma only explains.
7. **Config, not code, for model IDs and endpoints.** Model names change. They live in `config/kaiku.toml` / env vars. Look them up in current docs (section 9.2) before writing code.
8. **Fail soft.** Timeouts and retry with backoff on every network call. Every node publishes a heartbeat. A dead node never crashes another node, and a missing source makes the consensus say "insufficient data", not "stable".
9. **Small, testable, logged.** Structured JSON logs to stdout. Unit tests for logic. Contract tests for every message a module emits.
10. **Hackathon rules.** All code is written during the event. All submissions are MIT licensed. Don't paste in code written before the event for this idea.

---

## 1. The product in one page

**Kaiku** helps people stay well at home after TMS (transcranial magnetic stimulation) treatment for depression. Target challenge: **Aalto University — Beyond the Clinic**.

**Core idea:** in hospital, a patient's state is never judged from one measurement; clinicians combine interviews, scales, observation and tests. Kaiku brings that principle home. **Three touchpoints each observe the person independently, and a dashboard combines them into one consensus answer about their current state, with the evidence behind it.**

**Why now:** a TMS course is ~20 clinic visits, 3–5 days a week, with clinicians seeing the patient almost daily. When visits end, that view disappears, and about half of responders lose the effect within 6–12 months. Worsening caught early can often be reversed with a booster course. One questionnaire or one wearable is too thin a signal to act on.

**Punchline (submitted):** "A friend on your desk, a voice in your ear, a quiet eye on your days. Kaiku notices how you're really doing after depression treatment, and tells your care team when it matters."

**Pitch line:** "Apps wait to be opened and voice assistants wait to be spoken to. Depression takes away that initiative, so Kaiku reaches out first." (Not "comes to you": the robot turns its head and starts the conversation but does not drive.)

### The three sources

| Source | What it is | What it measures | Cadence |
|---|---|---|---|
| **1. Home robot** | Small companion robot, moving head, animated eyes. Runs a ~3-min morning ritual | Self-report dial (mood, energy, sleep), resting HR + HRV pre/post breathing, drumming energy (tempo, force, duration, regularity), speech rate + pauses (local), get-up time, room light | Daily ritual + passive all day |
| **2. Meta AI glasses** | Audio-first walk companion (Ray-Ban Display Web App) | Outings, time outdoors, steps/activity on walks | Per walk |
| **3. Laptop apps** | 2-minute session + PHQ-9 | Voice features from a spoken prompt, webcam facial expressivity (local), reaction-time task; PHQ-9 total + item 9 | Session: daily-optional (target ≥3/week). PHQ-9: every 14 days |

### The consensus

Each source compares today with the person's own baseline and returns **better / as usual / worse** plus a **confidence**. The dashboard combines them:

| State | Rule |
|---|---|
| **Stable** | Sufficient sources report as usual or better |
| **Watch** | Exactly one source reports worse, or only one source has sufficient data |
| **Needs a call** | Two or more independent sources report worse |
| **Safety** | Any crisis trigger (overrides everything) |

Disagreement is shown, not hidden ("robot: worse — lower HRV, slower drumming; glasses: as usual — walking daily; laptop: worse — flatter voice").

### Interventions (features of the robot and glasses, not the centre of the pitch)

Guided breathing with chest glow, drumming → Lyria RealTime music, daylight-walk nudge (glasses), friend ping (LoRa lamp, stretch), iCBT exercise suggestion. Each is scored **immediately** (HRV and mood before vs after) and **next day** (mood, energy, activity); a bandit learner picks each person's next suggestion.

### Users

- **Person after TMS** (primary). Also: anyone at risk of depression (secondary, mention only).
- **Clinician** following patients between visits without extra workload.

### Tracks we submit to

Beyond the Clinic (main) · Best Use of Gemini API · Best Use of Gemma · Best Use of Modal · Meta "AI Glasses for Everyone, Everyday" · Atech Real World Challenge. (Junction allows one project to enter multiple challenges.)

---

## 2. Hard constraints

| Constraint | Detail |
|---|---|
| Deadline | FINAL submission Sun 10:00. Set project from DRAFT to FINAL by 09:30. Draft projects are not reviewed. |
| Video | Max 2:00, strictly enforced. Public link (YouTube/Vimeo). |
| Repo | Public, MIT. Organisers must be able to access the source. |
| Peer review | Whole team at the table Sun 10:30 onward. Not taking part = not eligible for the main prize. |
| Top 5 pitch | 3 min pitch (mic cut at time) + 3 min judge Q&A, on stage, can demo from own laptop. |
| Atech | Atech modules must be used in the live demo. Need public GitHub repo or exported Atech project, ~2-min video/live demo, and a summary post in Atech's Discord. Hardware is returned after final demos. |
| Meta | Shared glasses (10 Ray-Ban Display, 10 RBM Gen 2) at the Meta booth — book early. Must handle permissions, errors, performance trade-offs, connectivity and device state; consent and safe data practices part of the demo. |
| Modal | Needs a live, deployed app judges can use. 40% of score is how central and well-used Modal is. |
| Gemini | Credits for teams via the challenge form; Google-provided accounts restricted to participants 18+. |
| Hardware | **No servos** (blocked at the airport). DC motors (check if geared), Atech ESP32 modules, Arduino UNO Q, Joy-IT KY sensor kit, USB camera, 2× LilyGo ESP32 LoRa, Bambu P1S (very limited time). |
| Venue Wi-Fi | ~2,000 people. Assume it will be bad. Use a phone hotspot for the demo network. Every demo path needs an offline fallback. |
| Sleeping | Not allowed at the venue. Plan sleep shifts at the hotel/home. |
| Safety | Product touches depression. Crisis handling must be deterministic and visible (section 12). |

---

## 3. Judging — what each track rewards

| Track | Criteria (weights) | What we show |
|---|---|---|
| **Beyond the Clinic** (Aalto) | Usefulness 25%: could it help people stay well at home? · Ease of use 25%: would someone recovering from depression use it every day? · Smart sensing 25%: clever use of what can be measured at home, and learning what works per person · Creativity 25% | Multi-source consensus; 3-min no-typing ritual; robot starts the interaction; drumming as both intervention and sensor; immediate + next-day intervention scoring |
| **Gemini API** | Meaningful, innovative, technically impressive; "beyond simply adding an LLM"; explain problem, integration, why Gemini matters | Live API real-time voice with function calling driving a physical ritual; Lyria RealTime steered by drumming |
| **Gemma** | Innovative, impactful use of open models; strong execution | Gemma 4 served by us on Modal to explain consensus from private health data; open weights = data stays on our infra |
| **Modal** | Effective use 40% · Technical ambition 25% · Impact 20% · Demo 15% (live deployed app) | API, storage, cron analytics, GPU Gemma, `.map()` consensus-accuracy simulation, dashboard hosting |
| **Meta glasses** | Creativity/use case · Technical execution · Real-world value/feasibility · UX: input, accessibility, trust (25% each) | Audio-first walk companion, consent built in, permission/error/connectivity handling, plausible pilot path |
| **Atech** | Real-world validation (tested with users/experts/real data) · Real-world impact · Use of Atech · Working demo & storytelling (25% each); bonus for combining modules / connecting to AI and APIs | Robot running live on Atech modules, connected to Gemini/Lyria; recorded feedback from Aalto mentors + testers |

**Grand jury (top 5 → overall winner):** Kia Kanninen (Founders House; wants a problem worth solving, not an easy feature), Daksh Raghuvanshi (AfterQuery RL; wants teams who can explain exactly why their system fails and whose metric holds when attacked), Otto Söderlund (Supercell AI; real user problem, something people come back to), Timo Ahopelto (Lifeline Ventures, founded CRF Health in electronic patient-reported outcomes; Oura investor), Umar Noor (Google DeepMind; prototype → real-world impact), Hubertus van der Drift (Context.dev; speed, pragmatism, one unique insight), Arturs Polis (Verda; hard challenges, path to production and scale).
**Main event criteria (peer review):** innovation, impact (share of affected people helped), implementation (realistic, viable, feasible).

**Implication for the pitch:** lead with the problem and the multi-source insight; show the failure modes honestly (coverage, disagreement, false alarms measured by the simulation); show a real path (pilot, iCBT, booster).

---

## 4. Evidence bank (use these exact claims; don't inflate)

| Claim | Source |
|---|---|
| Among rTMS responders, 66.5% sustained response at 3 months, 52.9% at 6, 46.3% at 12; maintenance treatment predicted better durability | Senova et al., Brain Stimulation 2019 meta-analysis — https://pubmed.ncbi.nlm.nih.gov/30344109/ |
| In one durability study, 32 of 38 patients whose symptoms worsened regained benefit when TMS was re-introduced | Janicak et al., Brain Stimulation 2010 — https://scholars.duke.edu/individual/pub782098 |
| HUS TMS course is usually 3–5 days a week, ~20 times; the frequent visits may themselves support recovery | HUS rTMS referral guide — https://www.hus.fi/en/node/6912 |
| Relapse predictors include disrupted sleep, reduced sociability, physical activity, mood, prosody and cognition; symptoms are individual subsets | RADAR-MDD protocol — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6379954/ ; RADAR-CNS analysis — https://arxiv.org/pdf/2212.10540v1 |
| Improvisational music therapy added to standard care improved depression, anxiety and functioning at 3 months (n=79, Finland) | Erkkilä et al., Br J Psychiatry 2011 (University of Jyväskylä) |
| A robot coach kept people tracking ~51 days vs ~36 (same software on computer) vs ~27 (paper) | Kidd & Breazeal, MIT (Autom) — https://www.media.mit.edu/publications/robots-at-home-understanding-long-term-human-robot-interaction/ |
| Mielenterveystalo internet therapy: any doctor in Finland can refer; usually starts within a week; registry study found depression iCBT comparable to 20 face-to-face sessions | https://www.mielenterveystalo.fi/en/what-internet-therapy |
| Kanta PHR is not currently being developed; wellbeing apps can't save new data now — don't build on it | https://www.kanta.fi/en/list-of-applications |
| Mental health was the most common cause of disability pensions under 55 in Finland in 2025 | Ilmarinen via European Pensions |
| Depression-related sickness absences are longer and explain most total days | Finnish Institute of Occupational Health 2025 |
| Germany: 30 of 63 listed DiGA target mental disorders (Oct 2026); deprexis is MDR class I | JMIR Human Factors 2026; deprexis.com |
| MIELI Crisis Helpline, Finnish, 24/7: 09 2525 0111; emergencies 112 | https://mieli.fi/en/ |

**Do not claim:** that Kaiku diagnoses, predicts or detects relapse; that the drumming is music therapy (say "inspired by"); that the robot's LEDs are light therapy; that the glasses see or measure daylight unless the DAT camera app is built; any accuracy number that isn't from our own simulation or test.

---

## 5. System architecture

### 5.1 Nodes

| Node | Runs on | Role | Talks via |
|---|---|---|---|
| `head` | Atech ESP32 modules | Eyes (display), IMU (taps + pan angle), pan motor, ear rotary encoder, chest LEDs, vibration "purr" | MQTT over Wi-Fi (or Atech API + hub adapter) |
| `sensors` | Arduino UNO Q (MCU sketch + Python relay) | KY-039 pulse via KY-053 ADC, KY-054 light, KY-050 ultrasonic, KY-035 hall (pan homing), top button | MQTT over Wi-Fi |
| `hub` | **Laptop by default** (UNO Q Linux is a stretch goal) | Ritual state machine, perception (taps→drum, PPG→HRV, distance→presence, speech features), face detection, Gemini Live, Lyria, safety gate, cloud uplink | MQTT (local) + HTTPS/WSS (cloud, Google) |
| `friendlink` | 2× LilyGo LoRa | Gateway (USB to hub) + friend's lamp/button (stretch) | Serial ↔ hub adapter, LoRa between boards |
| `cloud` | Modal | Ingest API, storage, per-source verdicts, **consensus engine**, bandit, Gemma explanations, simulation, hosts web app | HTTPS |
| `web` | Browser (served from Modal) | Clinician dashboard, person view, **laptop session**, PHQ-9, live view, health, eval | HTTPS |
| `glasses-webapp` | Meta Ray-Ban Display (Web App) | Walk companion, ritual reminder card, WebMCP voice tools | HTTPS to cloud |
| `glasses-dat` (optional) | Android/iOS app + DAT SDK | Camera frames → daylight/nature minutes, mic | HTTPS to cloud |

**Why the hub runs on a laptop:** on the UNO Q, App Lab runs Python in a container that may not see USB devices (camera, LilyGo serial) reliably, and a laptop gives reliable audio for Gemini Live. The hub is plain Python and can move to the UNO Q later without code changes, because everything talks MQTT.

### 5.2 Diagram

```
 SOURCE 1: HOME ROBOT                        SOURCE 2: GLASSES          SOURCE 3: LAPTOP
 ┌──────────────── home LAN / hotspot ─────────────┐   ┌──────────────┐   ┌─────────────────────┐
 │ head (Atech) ──raw──►┐                          │   │ MRBD Web App │   │ /session (webcam,   │
 │ sensors (UNO Q) ─raw─┤  MQTT   ┌─────────────┐  │   │ walk tracker │   │  mic, reaction task)│
 │ friendlink ─serial───┼────────►│     HUB     │◄─┼─► Gemini Live     │ /phq9 (every 14 d)  │
 │                      └─cmd────◄│  (Python)   │◄─┼─► Lyria RealTime  │ features computed   │
 │                                └──────┬──────┘  │   └──────┬───────┘   │ in the browser      │
 └───────────────────────────────────────┼─────────┘          │           └─────────┬───────────┘
                          obs/* derived  │ HTTPS               │ HTTPS               │ HTTPS
                                         ▼                     ▼                     ▼
 ┌──────────────────────────────────────── MODAL ─────────────────────────────────────────────┐
 │ FastAPI ingest → SQLite (Volume) → baselines → per-source verdicts → CONSENSUS (rule v1)   │
 │ bandit (nudges) │ Gemma 4 via vLLM on GPU (explanations only) │ simulation (.map) │ static │
 └──────────────────────────────────────────────┬─────────────────────────────────────────────┘
                                                ▼
              Dashboard: consensus header · three source cards · disagreement · evidence · actions
```

### 5.3 Reference sequence: one morning ritual

1. `sensors` → `raw/sensors/distance` → hub `perception.presence` → `obs/presence` (`first_of_day` = get-up proxy).
2. Hub enters `GREET` → `cmd/head {eyes: wide, pan_mode: track}`; `perception.face` (camera, local, only when someone is close) → pan targets.
3. Gemini Live session opens (voice). `DIAL`: three questions (mood, energy, last night's sleep), each answered by turning the ear → `obs/self_report` ×3.
4. `BREATHE`: 30 s PPG → HRV pre; `cmd/head {chest: breathe, bpm: 6}` for ~60–90 s; 30 s PPG → HRV post → `obs/hrv_session` and `obs/intervention_response` (activity `breathe`).
5. `DRUM`: `raw/head/tap` → `perception.taps` → `live.lyria` steering + `cmd/head {pan_mode: sway, bpm}` → `obs/drum_session`; quick mood dial after → `obs/intervention_response` (activity `drum`).
6. `PHQ9` step (only when due, every 14 days, if spoken mode enabled) → `obs/phq9`.
7. `NUDGE`: `GET /v1/nudge` → spoken suggestion → `obs/nudge_offered`; next day → `obs/nudge_outcome`.
8. Throughout: `perception.speech` computes speech rate and pauses from the local mic → `obs/speech_features`.
9. Uplink batches `obs/*` → `POST /v1/events`. Cloud updates baselines → verdicts → consensus → dashboard.
10. Any time: safety gate trigger → crisis script locally → `obs/safety_flag` on the priority lane → dashboard state **Safety**.

### 5.4 Ports & adapters (plug-and-play)

- **Core logic** (`hub/.../rituals`, `perception`, `cloud/analytics`) depends only on `kaiku_contracts`.
- **Adapters** isolate vendors/devices: `devices/atech_adapter.py`, `devices/lora_serial.py`, `devices/camera.py`, `live/gemini_live.py`, `live/lyria.py`, `cloud/llm/gemma_*.py`.
- **Every adapter has a sim twin** with the identical interface in `sim/` (e.g. `sim/nodes/head_sim.py` publishes the same topics; `--keyboard` maps keys to taps/ear turns).
- **Selection by config:** `KAIKU_HEAD=atech|sim`, `KAIKU_SENSORS=unoq|sim`, `KAIKU_VOICE=gemini|text|off`, `KAIKU_MUSIC=lyria|local|off`, `KAIKU_LLM=gemma_modal|gemma_hosted|template`.
- **Source independence:** each of the three sources can be absent; the consensus degrades gracefully (section 6.4).

---

## 6. Contracts (source of truth)

### 6.1 Envelope (every message)

```json
{
  "v": 1,
  "id": "018f6c2e-...-uuid7",
  "ts": "2026-11-14T08:12:03.120Z",
  "home_id": "demo-aino",
  "source": "head | sensors | hub | friendlink | glasses | laptop | cloud | sim",
  "type": "obs.drum_session",
  "payload": { },
  "quality": 0.92,
  "sim": false
}
```

- `id`: UUIDv7, idempotency key; cloud ignores duplicates.
- `ts`: UTC ISO-8601 with milliseconds, set by the producer.
- `quality` (0–1, optional): signal-quality estimate; analytics ignore readings below the configured threshold.
- `sim: true` on anything from `sim/`. Dashboard shows a "SIMULATED" badge. Sims keep the real node name as `source`.
- `type` is fully qualified and decides the topic: `obs.<name>`, `raw.<source>.<stream>`, `cmd.<target>`, `health`, `log` (D11). Use `topic_for(env)`.
- Every model is `extra="forbid"`: unknown fields are contract violations.

```python
class Envelope(BaseModel, Generic[P]):
    v: Literal[1] = 1
    id: UUID
    ts: datetime
    home_id: str
    source: Literal["head","sensors","hub","friendlink","glasses","laptop","cloud","sim"]
    type: str
    payload: P
    quality: float | None = Field(default=None, ge=0, le=1)
    sim: bool = False
```

**Source mapping for consensus** (`contracts/python/kaiku_contracts/sources.py`, by message type; exported as `contracts/schemas/sources.json` and TS `SOURCE_OF`): `robot` = obs produced by `hub` from `head`/`sensors`; `glasses` = obs from `glasses`; `laptop` = obs from `laptop`. PHQ-9 counts toward `laptop` regardless of where it was completed (spoken on the robot or on the laptop) and is also shown separately as the clinical anchor.

### 6.2 MQTT topics

```
kaiku/v1/<home_id>/raw/<source>/<stream>    # local high-rate data. NEVER uplinked.
kaiku/v1/<home_id>/obs/<type>               # derived observations. Uplinked to cloud.
kaiku/v1/<home_id>/cmd/<target>             # commands to a node (head, sensors, hub, friendlink)
kaiku/v1/<home_id>/health/<node>            # retained heartbeat, every 5 s
kaiku/v1/<home_id>/log/<node>               # optional mirrored warnings/errors
```

QoS: `raw` 0, `obs` 1, `cmd` 1, `health` 1 + retained. Broker: mosquitto on the hub host, port 1883, LAN only, user/password from env. Health payload: `{status: "ok|degraded|down", version, uptime_s, last_error, details{}}`.
Glasses and laptop apps do not use MQTT; they `POST /v1/events` directly with the same envelope.

### 6.3 Observations (`obs/<type>`) — uplinked

| type | payload (units) | producer | consensus source |
|---|---|---|---|
| `presence` | `distance_cm`, `first_of_day: bool`, `dwell_s` | hub | robot |
| `self_report` | `item: mood|energy|sleep`, `value: 1–5`, `context: ritual|adhoc|post_activity` | hub (ear dial) | robot |
| `hrv_session` | `hr_bpm`, `rmssd_pre_ms`, `rmssd_post_ms`, `duration_s`, `breath_bpm` | hub | robot |
| `drum_session` | `tempo_bpm`, `force_mean` (0–1), `duration_s`, `regularity` (0–1), `taps` | hub | robot |
| `speech_features` | `syllables_per_s` or `wpm`, `pause_ratio`, `duration_s` | hub | robot |
| `light_level` | `lux_est`, `window_min` | hub | robot |
| `ritual` | `step`, `status: started|completed|skipped|aborted`, `duration_s` | hub | (adherence only) |
| `outing` | `minutes`, `steps?`, `method: location|steps|dat_camera`, `daylight_min?` (DAT only) | glasses | glasses |
| `laptop_session` | `speech_rate`, `pause_ratio`, `pitch_variability`, `expressivity_index` (0–1), `reaction_ms_median`, `reaction_ms_iqr`, `lapses`, `duration_s` | laptop | laptop |
| `phq9` | `total` (0–27), `items[9]`, `item9_positive: bool`, `mode: spoken|laptop` | hub / laptop | laptop (+ anchor) |
| `intervention_response` | `activity: breathe|drum|walk|friend_ping|icbt`, `pre{rmssd_ms?, mood?}`, `post{...}`, `delta{...}` | hub / glasses | (learner) |
| `nudge_offered` | `arm`, `reason` | hub | (learner) |
| `nudge_outcome` | `arm`, `accepted: bool`, `next_day{mood, energy, activity}`, `reward` | hub / cloud | (learner) |
| `friend_link` | `direction: sent|received`, `ack: bool` | hub | robot (sociability) |
| `safety_flag` | `trigger: phq9_item9|phrase|manual`, `severity: high`, `handled_locally: bool` | hub / laptop | **overrides** |

### 6.4 Cloud-derived objects (API only, not MQTT)

```json
// source_verdict
{ "home_id": "demo-aino", "source": "robot|glasses|laptop",
  "verdict": "better|as_usual|worse|insufficient",
  "confidence": 0.0-1.0,
  "evidence": [ { "metric": "rmssd_pre_ms", "z": -2.1, "direction": "down", "days": 4 } ],
  "computed_at": "..." }

// consensus
{ "home_id": "demo-aino", "state": "stable|watch|needs_call|safety",
  "rule_version": "consensus-v1",
  "sources": [ <source_verdict>, ... ],
  "agreement": "agree|disagree|low_coverage",
  "explanation": { "text": "...", "by": "gemma|template", "model": "<id>" },
  "acknowledged_by": null, "computed_at": "..." }
```

**Consensus rule v1 (deterministic, in `cloud/analytics/consensus.py`, unit-tested):**
1. **Baselines:** per person, per metric: rolling median + MAD over the last 14 days (minimum 7 days of data; otherwise the metric is `insufficient`).
2. **Metric deviation:** robust z = (today − median) / (1.4826 × MAD). Direction-aware (e.g. lower HRV, slower drumming, later get-up, less light, fewer outings, lower dial scores, slower reactions, more pauses, lower expressivity = "worse"). A metric is **drifting** if |z| ≥ 1.5 in the "worse" direction on ≥ 3 of the last 5 available days.
3. **Source verdict:** `worse` if ≥ 2 of the source's metrics are drifting (laptop: ≥ 1 drifting metric, or PHQ-9 rose ≥ 5 points vs previous, or PHQ-9 ≥ 10). `better` if ≥ 2 metrics improved by the same criteria and none worse. Else `as_usual`.
4. **Confidence:** fraction of expected data received in the window × mean quality. `< 0.4` → `insufficient` (excluded from the vote).
5. **State:** `safety` if any open safety flag; else `needs_call` if ≥ 2 sufficient sources are `worse`; else `watch` if exactly 1 is `worse` **or** only 1 source is sufficient; else `stable`.
6. **Hysteresis:** `needs_call` stays until a clinician acknowledges or 3 consecutive days compute `stable`.
7. **Independence caveat:** dial self-report (robot) and PHQ-9 (laptop) are both self-report; show this caveat in the explanation when they are the only two worse sources.
**Everything above is data, not code:** metrics (obs + field + filter, daily aggregation, worse direction, weight, enabled, per-metric thresholds), source vote settings, the state rule and the PHQ-9 rules all live in **`config/criteria.toml`** (validated by `kaiku_contracts/criteria.py`, D19). The rule version is `consensus-v1+<hash>`, so every edit is traceable. Tune with `make criteria` (validate), `make tune` (simulation, compare two files), or live on the cloud via `/tune/` (preview who changes state, apply, reset). See `config/AGENTS.md` → Tuning.

### 6.5 Raw local streams (`raw/<source>/<stream>`) — never uplinked

| stream | payload | rate |
|---|---|---|
| `raw/head/tap` | `t_ms`, `force` (peak accel, g), `src: imu|knock` | per event |
| `raw/head/ear` | `value`, `delta`, `pressed` | per event |
| `raw/head/pan` | `deg`, `homed: bool`, `moving: bool` | 10 Hz |
| `raw/sensors/ppg` | `t0_ms`, `fs_hz`, `samples: int[]` | batches of 25 @ 100–250 Hz |
| `raw/sensors/distance` | `cm` | 5–10 Hz |
| `raw/sensors/light` | `raw`, `lux_est` | 0.1 Hz |
| `raw/sensors/button` | `id`, `pressed` | per event |
| `raw/sensors/hall` | `at_home: bool` | per event |
| `raw/hub/face` | `x_norm` (−1..1), `y_norm`, `size`, `confidence` (no images, ever) | 5–10 Hz |

### 6.6 Commands (`cmd/<target>`)

| target | payload |
|---|---|
| `head` | `{eyes: neutral|happy|sleepy|wide|listening|thinking|soft, look?: {x,y}}` |
| `head` | `{pan: {target_deg, speed}}` · `{pan_mode: track|still|sway, bpm?}` · `{home: true}` |
| `head` | `{chest: off|breathe|glow|pulse, bpm?, color?}` · `{purr: {ms}}` |
| `sensors` | `{ppg: start|stop}` · `{camera_enable: bool}` |
| `friendlink` | `{ping: {pattern}}` |
| `hub` | `{suggest_nudge: {arm}}` · `{set_ritual_time: "08:30"}` · `{clinician_message: {text}}` · `{phq9_due: true}` |

Cloud→hub delivery: poll `GET /v1/commands` (fallback) or WSS `/v1/stream/<home_id>`; hub republishes on `cmd/hub`.

### 6.7 Cloud HTTP API (Modal, FastAPI)

| method & path | purpose |
|---|---|
| `POST /v1/events` | Batch of envelopes (obs only). Idempotent by `id`. Auth: `Authorization: Bearer <home token>` (hub, glasses, laptop) |
| `GET /v1/commands?home_id&since` · `WS /v1/stream/{home_id}` | Commands to the hub |
| `GET /v1/nudge?home_id` | Bandit's next arm + reason |
| `GET /v1/patients` | Clinician list ranked by consensus state, with last activity per source |
| `GET /v1/patients/{id}/consensus` | Current consensus object incl. source verdicts + explanation |
| `GET /v1/patients/{id}/timeline?metrics=` | Time series with baseline bands, per source |
| `GET /v1/patients/{id}/phq9` | PHQ-9 history |
| `POST /v1/patients/{id}/actions` | `flag_booster | flag_icbt_referral | acknowledge | send_message` (logged; no external systems) |
| `GET /v1/me?home_id` | Person-facing view: plain-language state, what has helped (bandit stats) |
| `POST /v1/admin/recompute` | Recompute now (demo button) |
| `GET /v1/eval` | Simulation metrics |
| `GET /v1/events?home_id&since&limit` | Recent observations for `/live` |
| `PUT /v1/health/{home_id}` · `GET /v1/health` | Hub reports node heartbeats + uplink lag; `/health` page reads all homes |
| `POST /v1/admin/reset` | Delete SIMULATED data only (re-seed anchors history to today) |
| `GET /healthz` | Liveness + versions |

Models: `contracts/python/kaiku_contracts/api.py` (TS in `contracts/ts/`). **Auth (pairing token, D16):** when `KAIKU_HOME_TOKEN` is set, every `POST /v1/events` needs `Authorization: Bearer <token>` (hub, glasses, laptop). Browser apps receive it once via a pairing link (`/session/?home=demo-aino&t=<token>`), keep it in localStorage and never hold the Gemini key. Admin routes need `KAIKU_ADMIN_TOKEN` when set. Clinician read routes are open for the demo — harden after the event.

### 6.8 Versioning

- Additive change → no bump; update schemas, sims, progress log.
- Breaking change → bump `v`; cloud accepts old + new for the rest of the event.
- Every module validates what it emits against the schema in tests.

---

## 7. Module specs

Owners: **A** hardware/firmware · **B** hub/live · **C** cloud/ML/sim · **D** apps/demo/story.

### 7.1 `contracts/` (all, Phase 0, first hour)
- Pydantic models are the source of truth (D10); JSON Schemas for envelope, every obs/raw/cmd type, `source_verdict`, `consensus` and all API models are generated, plus TS (`json-schema-to-typescript`); `topic_for(env)`; `validate(msg)`; `sources.py` mapping. Also the shared kit: `Bus` (MQTT), config loader, JSON logging.
- **Done when:** `make test-contracts` passes; a sample of every type round-trips JSON ⇄ pydantic ⇄ TS.

### 7.2 Bus + `tools/` (B, Phase 0)
- mosquitto; `tools/bus_tail.py`, `record.py`, `replay.py`, `doctor.py`.
- **Done when:** `make broker && make tail` shows sim traffic; record → replay reproduces it.

### 7.3 `sim/` (C, Phase 0)
- `nodes/head_sim.py`, `nodes/sensors_sim.py` (realistic PPG with HRV, taps at a chosen tempo, distance approach curve), `nodes/glasses_sim.py`, `nodes/laptop_sim.py`. `--keyboard`: `t` tap, `[`/`]` ear, `e` press ear, `p` arrive/leave, `s` start ritual, `x` long-press (manual safety), `f` friend button, `w` glasses walk, `l` laptop session, `9` laptop PHQ-9 (breathing is driven by the hub).
- `patients/`: 30-day trajectories for 8 patients: **Aino** (stable 14 days, then robot + laptop drift from ~day 18 while glasses stay "as usual" → disagreement → needs_call), one stable, one noisy-but-fine, one robot-only drift (→ watch), one low-coverage (→ watch, low_coverage), one PHQ-9 item 9 positive (→ safety), others varied.
- `seed_demo.py` posts history with `sim: true`.
- **Done when:** with only sims + broker + cloud, the dashboard shows all states including disagreement and low coverage.

### 7.4 `hub/` (B, Phases 0–2)
- `bus.py`: async MQTT (e.g. `aiomqtt`), validates on publish/subscribe.
- `perception/`
  - `taps.py`: if raw accel provided: high-pass, peak detect at ≥ 200 Hz; 80 ms refractory; else consume `raw/head/tap`. Tempo = median inter-tap interval; force = mean peak; regularity = 1 − CV of intervals. Ignore taps during pan motor accel/decel.
  - `hrv.py`: band-pass PPG (~0.7–3.5 Hz), peak detection, IBI cleaning, RMSSD; quality gate (< 70% clean beats → reject). Test with recorded fixtures.
  - `presence.py`, `light.py`: smoothing, first-of-day logic, hourly aggregation.
  - `face.py`: lightweight local face detector → `raw/hub/face` only; camera enabled only when presence < threshold; never writes frames.
  - `speech.py`: from local mic, energy/VAD-based pause ratio and rate estimate; no transcripts stored.
- `live/`
  - `gemini_live.py`: Live API voice session; tools: `record_dial(item, value)`, `start_breathing`, `start_drum`, `start_phq9`, `suggest_nudge`, `send_friend_ping`, `end_ritual`. Finnish + English. Model ID from config (look it up via Gemini docs MCP/skill).
  - `lyria.py`: Lyria RealTime; tempo → BPM (clamp to the API range, currently documented as 60–200), force → density/brightness, mood → base prompt. Always resend the full generation config when updating (partial updates reset other fields). Local click per tap for immediacy.
  - `local_audio.py`: offline fallback (pre-recorded lines, local loop).
- `rituals/`: explicit state machine `IDLE → GREET → DIAL(mood, energy, sleep) → BREATHE → DRUM → [PHQ9 if due & spoken] → NUDGE → CLOSE`; each step `enter/handle/exit` + timeout; skippable; emits `obs/ritual`.
- `safety/`: section 12. Runs first on transcripts and PHQ-9 answers.
- `uplink.py`: batch every 2 s, SQLite offline queue, backoff, priority lane for `safety_flag`.
- **Done when:** with sims, a full ritual completes by voice (or text mode), all robot obs types are produced and uplinked, and it survives broker restart and cloud outage.

### 7.5 `firmware/atech-head/` (A, Phase 3)
- Build via atech.dev (Chrome/Edge, WebSerial) and/or exported PlatformIO; `pip install atech` for agent work. **VERIFY** in Atech docs: display size/driver, IMU model and max sample rate, motor driver module, whether exported firmware can run custom C++ (MQTT client).
- Animated eyes; tap detection (IMU primary, KY-031 knock sensor backup); ear encoder (KY-040 if the Atech knob is busy); pan control (DC motor + gyro integration + hall homing); chest LEDs; purr (eccentric weight on spare motor).
- Publishes `raw/head/*`, subscribes `cmd/head`, heartbeat `health/head`.
- If Atech can't run MQTT: expose its native Wi-Fi/BLE API + `hub/.../devices/atech_adapter.py`.
- **Done when:** real taps/ear/pan on the bus; `cmd/head` drives eyes/pan/chest; homing works after power cycle.

### 7.6 `firmware/unoq-sensors/` (A, Phase 3)
- App Lab app: MCU sketch reads KY-053 (ADS1115, 16-bit) for KY-039 PPG at ≥ 100 Hz, KY-054 light, KY-050 ultrasonic (**5 V echo → KY-051 level shifter or divider before any 3.3 V pin**; the kit leaflet mislabels it "KY-052"), KY-035 hall, button; Python side relays to MQTT via Bridge RPC.
- **Done when:** PPG batches at a stable rate; distance/light/button events visible; `health/sensors` ok.

### 7.7 `firmware/friendlink/` (A, stretch)
- Gateway LilyGo: serial protocol (`PING <pattern>`, `ACK`) ↔ LoRa. Lamp LilyGo: LED glow + button ack. Hub adapter `devices/lora_serial.py`.
- **Done when:** antenna button on robot → lamp glows in < 3 s; ack returns.

### 7.8 `cloud/` (C, Phases 1 & 4)
- `app.py`: Modal App: ASGI FastAPI (one warm container so SQLite has one writer), Volume for DB, static web assets, scheduled job (recompute every 15 min + nightly), GPU class for Gemma, `.map()` simulation.
- `analytics/`: `baseline.py`, `drift.py`, `verdict.py` (per source), `consensus.py` (rule v1, section 6.4), `bandit.py` (Thompson sampling over `breathe | drum | daylight_walk | friend_ping | icbt_exercise`; reward = 0.5 × normalised immediate delta + 0.5 × next-day mood/energy delta, clipped; cold start uniform).
- `llm/`: `gemma_vllm.py` (Gemma 4 via vLLM on GPU; start with the smallest instruct variant that writes valid JSON, e.g. E4B on L4/L40S; **VERIFY** HF model IDs, licence/token, vLLM support; weights cached in a Volume), `gemma_hosted.py` (fallback: hosted Gemma via AI Studio or Featherless), `template.py` (no-LLM fallback), `explain.py` (input = consensus object + top evidence; output = strict JSON `{headline, per_source[], disagreement_note?, suggested_actions[], caveats}`; validated; retry once; banned-words post-check: diagnose, relapse detected, predicts, etc.).
- `jobs/simulate.py`: N synthetic patients with known onset; run analytics; report per-state precision/recall, false "needs_call" per patient-month, median lead time, effect of losing one source. Shown on `/eval`. Also the honest answer to "why does it fail?".
- **Done when:** `modal deploy` gives a public URL; seeded demo shows every state; `/eval` has numbers; `/healthz` green.

### 7.9 `apps/web/` (D, Phases 1–2)
One **Next.js** (App Router + TS) app, static export (`output: 'export'`, `trailingSlash: true`) served by Modal (D13). Client-side fetching only; dynamic pages use query params (`/clinician/patient/?id=aino`), not `[id]` segments:
- `/clinician`: list ranked by state (Safety, Needs a call, Watch, Stable), coverage badges.
- `/clinician/patient/?id=`: **consensus header** (state, rule version, last computed); **three source cards** (verdict, confidence, top evidence, last data time); **disagreement callout** when sources disagree; Gemma explanation (labelled "explanation, not a decision"); timelines with baseline bands; PHQ-9 chart; intervention history ("what helps"); actions: flag booster, flag iCBT referral, acknowledge.
- `/me`: person view in plain language: "how the last week looked", what has helped, next suggestion. No alarming wording.
- `/session`: **laptop 2-minute session**: consent check → spoken prompt (~30 s, e.g. describe your morning) → speech features in-browser → webcam facial expressivity in-browser (face-landmark model; **VERIFY** library choice) → reaction task (~60 s; simple reaction time with occasional no-go trials) → post `obs/laptop_session`. Camera and mic indicators visible; nothing recorded.
- `/phq9`: standard PHQ-9 wording; item 9 handled by the safety rule; scheduled every 14 days (banner when due).
- `/consent`, `/live` (demo event stream), `/health` (node heartbeats, uplink lag, errors), `/eval`.
- **Done when:** works with seeded and live data; "SIMULATED" badges visible.

### 7.10 `apps/glasses-webapp/` (D, Phase 5)
- Meta Ray-Ban Display Web App (HTML/CSS/JS on the glasses display). Available: display, Neural Band + cap-touch input, motion/orientation (incl. step detection), location from the paired phone, local storage, TTS. **No camera or mic access.**
- **Next.js** static export (D13), using the Meta Web App plugin skills and UI Toolkit (`@wearables-ui-toolkit/mrbd`, `@wearables-ui-toolkit/icons`). Watch the < 300 KB first-load budget.
- Features: walk companion (start/stop, timer, steps, outdoor minutes via location), ritual reminder card, breathing guide, WebMCP tools (`start_walk`, `end_walk`, `log_mood`) so the wearer can use voice via Meta AI.
- Trust UX (Meta criteria): permission prompts explained, offline handling (queue in local storage), clear "what is shared" screen, battery-aware.
- Constraints: 600×600 responsive, D-pad focus navigation, < 300 KB first load and < 15 requests, 30 Hz panel, HTTPS hosting only.
- Install on glasses: QR via the Simulator's "View on Glasses QR" or the plugin publish skill (deep link `fb-viewapp://web_app_deep_link?appName=<name>&appUrl=<https-url>`), or Meta AI app → Devices → Display Glasses settings → App connections → Web apps → Add.
- **Done when:** runs in the MRBD Simulator and on real Display glasses; posts `obs/outing` and `obs/intervention_response` (walk) to the cloud.

### 7.11 `apps/glasses-dat-*` (optional)
- Only with time + compatible phone: DAT app; sparse camera frames on walks → Gemini vision → `daylight_min`, `nature` → `obs/outing` with `method: dat_camera`. Frames discarded; no faces stored; handle pause/stop on hinge close/removal. Mock Device Kit when glasses unavailable.

---

## 8. Robot hardware build notes

- **Form:** tabletop robot with a pan head on a yoke over a boxy body (renders in `hardware/cad/`). **Moving head, no wheels** (safer at crowded tables, always at eye level, less printing). The rover variant is a "v2" slide only.
- **Mapping:**

| Part | Function |
|---|---|
| Eye band | Atech display with animated eyes |
| Dot between eyes | USB camera (face position only), physical slider shutter + status LED |
| Holes under eyes | Microphones (if audio runs on the robot; default is hub laptop USB mic hidden in body) |
| Left orange ear | Rotary encoder = dial ("turn my ear") |
| Right ear / green visor | Drum surface; IMU in head under the visor; knock sensor backup |
| Antenna ball | LoRa friend-link button (stretch) |
| Orange top button | Push-to-talk / long-press "I'm not OK" (manual safety trigger) |
| Chest window | Translucent panel + LEDs (breathing glow); KY-039 finger cradle on the frame (shields ambient light) |
| Bar above chest | KY-050 ultrasonic (presence/distance) |
| Side vents | Speaker |
| Base | UNO Q, Atech base board, power bank; rear USB slot |

- **Motion without servos:** pan = DC gearmotor + printed gear on the turntable ring; angle from IMU gyro integration between homings; homing via magnet on turntable + KY-035 hall (or KY-025 reed) at centre; optional KY-040 geared to pan shaft. Nod (optional) via a small cam, no position control. "Purr" = eccentric weight on a spare motor. If motors are not geared → printed reduction.
- **Printing:** scale ~70%; 0.28 mm layers, 2 walls, 5–10% infill (visor/yoke 30%+ infill, people hit them); print head, yoke, turntable gear, top plate first; body can be white foam board with printed top plate if printer time runs out. Slice everything and check real times before committing slots.
- **Tap tuning:** record 3 logs (soft taps, hard taps, pan-only motion) before choosing thresholds. Add foam under the visor if taps knock the pan gear out of mesh.
- **Skip from the KY kit:** flame, line-tracking, magic light cup, 7-colour flash LED, BMP280.
- **Provenance:** the CAD renders were made before the event. Ask organisers whether pre-made CAD is acceptable (rules prohibit pre-written code and projects related to an existing company); disclose in `hardware/cad/README.md`. If not acceptable, redraw simplified geometry during the event.

---

## 9. Toolchain & agent setup

`scripts/bootstrap.sh <role>` automates what it can and prints what's left. Roles: `all | hub | cloud | web | firmware | glasses-web | glasses-dat`.

### 9.1 Everyone

| Tool | Install | Verify |
|---|---|---|
| git, make | system | `git --version` |
| Python ≥ 3.11 + **uv** | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `uv --version` |
| Node ≥ 20 + pnpm | nvm / `corepack enable` | `node -v && pnpm -v` |
| mosquitto (+ clients) | `brew install mosquitto` / `apt install mosquitto mosquitto-clients` | `mosquitto_sub -h localhost -t '#' -v` |
| Chrome or Edge | Atech WebSerial flashing + MRBD Simulator | — |

### 9.2 Agent knowledge: docs MCP servers, skills, plugins

Restart the agent session after installing (most agents load MCP servers/skills only at startup).

**Google Gemini (Gemini API, Live API, Lyria) — hub/live, cloud/llm hosted fallback, laptop session if using Gemini**
```bash
npx skills add google-gemini/gemini-skills --list
npx skills add google-gemini/gemini-skills --skill gemini-api-dev
npx skills add google-gemini/gemini-skills --skill gemini-live-api-dev
#   add --global for all projects; if a global skill is ignored, install per project

claude mcp add --transport http geminiDocs https://gemini-api-docs-mcp.dev   # Claude Code
codex mcp add geminiDocs --url https://gemini-api-docs-mcp.dev                # Codex
npx add-mcp "https://gemini-api-docs-mcp.dev"                                  # auto-detect agents
# llms.txt: https://ai.google.dev/gemini-api/docs/llms.txt ; any page as markdown: append .md.txt
```
Rules (also in AGENTS.md): current `google-genai` (Python) / `@google/genai` (TS) SDK only, never legacy `google-generativeai`; Interactions API for new text work unless a feature needs `generateContent`; look up current model names before coding; Live API and Lyria model IDs in `config/kaiku.toml` (Lyria docs currently show `models/lyria-realtime-exp`).

**Meta Wearables — Web Apps (Ray-Ban Display) — apps/glasses-webapp**
```bash
claude mcp add --transport http wearables --scope project https://mcp.developer.meta.com/wearables
codex mcp add wearables --url https://mcp.developer.meta.com/wearables
# Tools: search_webapps_docs (+ DAT docs search). No auth needed.

# Web App AI plugin — inside a Claude Code session:
#   /plugin marketplace add https://github.com/meta/meta-wearables-webapp
#   /plugin install meta-wearables-webapp@meta-wearables
# Codex:     codex plugin marketplace add https://github.com/meta/meta-wearables-webapp  (then /plugins → Meta Wearables → install)
# Any tool:  git clone https://github.com/meta/meta-wearables-webapp && ./install-skills.sh claude|cursor|agents|all
#            (Gemini CLI / Windsurf / Devin: ./install-skills.sh agents → AGENTS.md)
```
Skills: `ai-glasses-webapp-build`, `-ui`, `-device`, `-webmcp`, `-test`, `-optimize-performance`, `-publish` (Vercel; any HTTPS host works).
Simulator: https://chromewebstore.google.com/detail/jpjlmmodokemlepklkdbimceggpbjcll
Markdown docs: `https://wearables.developer.meta.com/wearables-docs/docs-markdown/develop/webapps.md` (same pattern for other pages).
Device setup: glasses software v125+, Meta AI app v272+; Developer Mode: Meta AI app → Settings → App Info → tap App version 5× → Enable.

**Meta Wearables — Device Access Toolkit — apps/glasses-dat-* (optional)**
```bash
claude plugin marketplace add facebook/meta-wearables-dat-android
claude plugin install mwdat-android@mwdat-android-marketplace
claude plugin marketplace add facebook/meta-wearables-dat-ios
claude plugin install mwdat-ios@mwdat-ios-marketplace
codex plugin marketplace add facebook/meta-wearables-dat-android
codex plugin add mwdat-android@mwdat-android-marketplace
# If not loaded in the current session: read AGENTS.md at the root of the DAT repo.
# Repos also linked as github.com/meta/meta-wearables-dat-android / -ios.
```
Requirements: iOS 17.2+ with Xcode 26.4+, or Android 10+ with Android Studio Flamingo+ and Kotlin 2.2+. Supported: Ray-Ban Meta Gen 1/2, Ray-Ban Display, Oakley Meta and others. Developer Mode as above. Mock Device Kit without hardware.

**Modal — cloud**
```bash
uv tool install modal      # or: pip install modal
modal setup                # browser auth
modal token info           # verify
# Credits: redeem via the "Best use of Modal" challenge page (code there, not here).
# Docs: https://modal.com/docs ; examples (vLLM/SGLang serving etc.): https://github.com/modal-labs/modal-examples
```
No official Modal agent skill found. Agents: read the relevant Modal docs and the vLLM example before writing `cloud/llm/gemma_vllm.py`; check whether `https://modal.com/llms.txt` exists. Don't rely on third-party community skills for API details.

**Gemma — cloud/llm**
- Gemma 4 (Apache 2.0): E2B, E4B, 26B MoE, 31B Dense; MedGemma variants exist. **VERIFY** HF repo IDs and token needs; `HF_TOKEN` in a Modal secret. Docs: https://ai.google.dev/gemma/docs

**Atech — firmware/atech-head**
- Account at https://atech.dev (redeem the Junction code from the challenge page/Discord); `pip install atech`; docs https://atech.dev/docs; examples https://github.com/atechdotdev. Chrome/Edge only for flashing; data USB cable; on Linux add user to `dialout`. Kits are first come, first served at the Atech roundtable (5th floor); engineers on site including night shift.

**Arduino UNO Q — firmware/unoq-sensors**
- Arduino App Lab (sketch + Python + Bridge RPC between MCU and Linux). Also reachable via SSH/adb with the App Lab CLI. App Lab Python is containerised and may not see USB devices — keep USB-dependent code in the hub on the laptop.
- Joy-IT KY sensor examples: https://sensorkit.joy-it.net

**Project rule files (done, see section 21):** root + per-module `AGENTS.md` (the only context file; no `CLAUDE.md`/`GEMINI.md`) · `.gemini/settings.json` (`context.fileName = AGENTS.md`) · `modules.toml` (module registry) · `.mcp.json` with `wearables` and `geminiDocs`.

### 9.3 Secrets & config

`.env.example` (names only):
```
GEMINI_API_KEY=
KAIKU_HOME_ID=demo-aino
KAIKU_HOME_TOKEN=
KAIKU_ADMIN_TOKEN=
KAIKU_CLOUD_URL=
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USER=
MQTT_PASS=
HF_TOKEN=
KAIKU_HEAD=sim          # atech | sim
KAIKU_SENSORS=sim       # unoq | sim
KAIKU_VOICE=gemini      # gemini | text | off
KAIKU_MUSIC=lyria       # lyria | local | off
KAIKU_LLM=gemma_modal   # gemma_modal | gemma_hosted | template
KAIKU_PHQ9_MODE=laptop  # laptop | spoken | both
KAIKU_DEMO_MODE=1
```
- Cloud: `modal secret create kaiku-secrets GEMINI_API_KEY=... HF_TOKEN=... KAIKU_HOME_TOKEN=...`
- `.env` gitignored; optional `gitleaks` pre-commit.
- `config/kaiku.toml`: model IDs, `[consensus]` + `[consensus.sources.<name>]` thresholds, ritual timings + `phq9_mode`, languages, ports. Env `KAIKU_<SECTION>_<KEY>` overrides any key.
- The browser apps (laptop, glasses) never hold the Gemini key; anything needing Gemini goes through the cloud API.

### 9.4 `make doctor`

✅/⚠️/❌ with fix hints: tool versions; `.env` keys present (never print values); broker reachable; each node's heartbeat age; cloud `/healthz`; Gemini key valid (cheap call); Modal auth; MCP servers configured (best effort); last event time per source (robot/glasses/laptop).

---

## 10. Execution plan

Times are targets (Helsinki). Each phase ends demoable; never start a phase with the previous one broken.

### Phase 0 — Foundations (Fri night, ~2 h) — ALL
- [x] Repo (MIT), layout (section 11), one `AGENTS.md` per module, `modules.toml`, `.mcp.json`, Makefile, `.env.example`, `config/kaiku.toml`. **Repo is still private — make it public before submission.**
- [x] `contracts/` incl. `source_verdict` + `consensus`. **Everyone: skim `contracts/schemas/examples.json` and object now.**
- [x] mosquitto config; tools; all five sims (head, sensors, friendlink, glasses, laptop).
- [ ] Junction **draft submitted by 23:59 Fri** (done if Appendix A text is in). Book Meta glasses. Collect Atech kit. Claim Gemini + Modal credits.
- [ ] Spikes (45 min each, results in `docs/decisions.md`): A: Atech IMU + one motor + MQTT feasibility · B: Gemini Live voice round-trip + Lyria BPM changes · C: Modal deploy + Gemma loads (or hosted fallback) · D: MRBD Web App template in Simulator; which glasses/phone we have; in-browser face-landmark library choice.
- [ ] Start head print.
- **Exit:** `make sim && make tail` shows traffic from all sources.

### Phase 1 — Walking skeleton (by Sat ~06:00)
- [ ] C: ingest + store + baselines + verdicts + **consensus v1** + `/v1/patients` + `/healthz` deployed; `seed_demo.py` → all states visible.
- [ ] D: `/clinician` list + patient page (consensus header + 3 source cards + disagreement callout) on seeded data; `/live`.
- [ ] B: hub uplinks sim obs; ritual state machine in text mode.
- [ ] A: real tap from Atech IMU reaches the bus.
- **Exit (M1):** physical tap → `obs/drum_session` → robot source card updates on the deployed dashboard.

### Phase 2 — Three live sources (by Sat ~12:00)
- [ ] B: Gemini Live voice with tools; 3-question dial; Lyria drum loop; HRV from sim PPG; safety gate + crisis script; `intervention_response` pre/post.
- [ ] A: eyes, ear encoder, chest LEDs, pan with homing on hardware.
- [ ] D: `/session` (laptop source live: speech + expressivity + reaction) and `/phq9`; `/health`.
- **Exit (M2):** full robot ritual end-to-end on real head + sim sensors, and a real laptop session, both feeding the consensus.

### Phase 3 — Real sensors (Sat afternoon)
- [ ] A: UNO Q sensor node; camera face tracking; friend link (stretch).
- [ ] B: per-node switch sim → real; verify fail-soft (unplug any node).
- [ ] Modal workshop Sat 13:30 (check Discord for room).
- **Exit:** ritual on all-real hardware; unplugging any node leaves the rest working and the consensus shows reduced coverage.

### Phase 4 — Intelligence & proof (Sat afternoon/evening)
- [ ] C: bandit, Gemma explanations (vLLM; hosted/template fallbacks), simulation on Modal → `/eval` (incl. "lose one source" ablation).
- [ ] D: `/me` person view; PHQ-9 chart; actions; eval page.
- [ ] Validation (Atech + Aalto): 20 min with Aalto mentors (Ilmoniemi/Lioumis group) + 3–5 testers; record quotes and observations in `docs/validation.md`.
- [ ] Optional: "Can It Be a Company?" with Kiuas (Sat 14:30, Loft 4th floor) for the business story.
- **Exit (M3):** Aino → needs_call with disagreement shown and a sensible explanation; eval numbers on screen.

### Phase 5 — Glasses (Sat evening, parallel)
- [ ] D: MRBD Web App (walk companion, reminder card, breathing, WebMCP) deployed over HTTPS; on real glasses.
- [ ] Optional DAT camera → daylight minutes.
- **Exit:** a real walk shows up as the glasses source card updating.

### Phase 6 — Demo hardening (Sat 22:00 feature freeze → Sun 09:30)
- [ ] `KAIKU_DEMO_MODE=1`: seeded history, accelerated clock option, `demo/reset.sh` < 30 s.
- [ ] Offline fallback rehearsed: ritual runs locally (`local_audio`, `template` explanation, consensus computed from cached data).
- [ ] Film video (Sat evening light), edit ≤ 1:59; pitch deck PDF; README; final submission text checked against what runs (section 15).
- [ ] Atech Discord post; submission FINAL by 09:30.

---

## 11. Repository layout

```
kaiku/
├── AGENTS.md                         # root rules + ground-truth map + generated module index (only context file)
├── .gemini/settings.json             # points Gemini CLI at AGENTS.md
├── modules.toml                      # module registry: path, owner, kind, emits/consumes, removable (GT)
├── handoff.md  README.md  LICENSE (MIT)
├── Makefile   .env.example   .mcp.json   pyproject.toml / uv.lock (uv workspace)   conftest.py (broker fixture)
├── config/        kaiku.toml ([consensus] etc.), safety_phrases.toml, mosquitto.conf
├── contracts/
│   ├── python/kaiku_contracts/   # pydantic (EDIT HERE), registry, sources.py, api.py, topics, Bus, config, jlog
│   ├── schemas/  ts/             # GENERATED by `make contracts`
│   └── tests/
├── tools/         bus_tail, record, replay, doctor, agents_sync
├── sim/
│   ├── run.py                    # make sim NODES=head,sensors,friendlink,glasses,laptop [ARGS=--keyboard]
│   ├── nodes/                    # head_sim, sensors_sim, friendlink_sim (MQTT); glasses_sim, laptop_sim (HTTPS)
│   ├── patients/                 # 8 scenario patients (Aino + 7) via kaiku_cloud.jobs.synth
│   └── seed_demo.py
├── hub/kaiku_hub/                # main, settings, bus, uplink, cloudlink, devices/, perception/, live/, rituals/, safety/
├── cloud/
│   ├── app.py                    # Modal: ASGI, Volume, cron (15 min + nightly), GPU Gemma, .map simulation
│   └── kaiku_cloud/              # api/, store/, analytics/ (baseline, drift, verdict, consensus, bandit), llm/ (explain, gemma_*, template), jobs/ (synth, simulate, nightly)
├── apps/
│   ├── web/                      # Next.js: /clinician /clinician/patient /me /session /phq9 /consent /live /health /eval
│   ├── glasses-webapp/           # MRBD Web App (Next.js static export)
│   └── glasses-dat-android/      # optional
├── firmware/      atech-head/  unoq-sensors/  friendlink/
├── hardware/      cad/ (README with provenance)  wiring.md  bom.md
├── demo/          demo_script.md  video_shotlist.md  reset.sh
├── docs/          progress.md (append-only)  decisions.md  validation.md  safety.md  privacy.md  tracks.md  submission.md  templates/module/
├── scripts/       bootstrap.sh
└── logs/          # gitignored
```

Every module folder has exactly one doc, `AGENTS.md`, with: `Purpose` · `Boundaries` · `Consumes` · `Emits` · `Map` · `Extension points` · `Invariants` · `Run standalone` · `Run with sim` · `Config & env` · `Health signal` · `Tests` · `Known issues` (D21). No module `README.md`, `CLAUDE.md` or `GEMINI.md`. `make test` enforces this; the root `README.md` is the public project page.

---

## 12. Safety, privacy & claims (non-negotiable)

**Crisis path (deterministic; `hub/safety` and `apps/web/phq9`):**
- Triggers: PHQ-9 item 9 > 0 (spoken or laptop); crisis phrases in the live transcript (`config/safety_phrases.toml`, fi/en/sv); long-press on the robot's top button.
- Response, in order: stop the ritual/session; calm pre-written message (spoken by robot or shown on screen, never generated); show **MIELI Crisis Helpline 09 2525 0111 (Finnish, 24/7)** and **112** for emergencies; emit `obs/safety_flag` on the priority lane; dashboard state **Safety** with timestamp.
- No LLM in this path. Unit tests for every trigger. `docs/safety.md` states the phrase list will miss things and that Kaiku does not replace crisis services or clinicians.

**Privacy:**
- Robot camera and laptop webcam: processed in memory for face position / expressivity only; never stored or transmitted; camera on only when needed; visible indicators; robot has a physical shutter.
- Audio: streamed to Gemini Live only during an active, consented robot conversation; laptop session audio analysed in the browser; only derived features uploaded; no transcripts stored.
- Cloud stores derived numbers, ritual metadata, PHQ-9 scores, verdicts, consensus, explanations. Demo data is synthetic and labelled.
- Consent screen (`/consent`) explains all of the above; Meta glasses app has its own "what is shared" screen.

**Claims wording (UI, pitch, explanations, submission):**
- Say "change from your usual", "worth a check-in", "consensus", "needs a call". Never "diagnosis", "relapse detected", "predicts relapse".
- Drumming: "inspired by research on improvisational music therapy".
- Robot light is not light therapy. Glasses don't "see" anything unless the DAT camera app is built.
- Monitoring for clinical decisions would likely make this an EU MDR medical device (likely Class IIa); the prototype is a research demo.

---

## 13. Debugging & isolation playbook

### 13.1 Make targets

| target | does |
|---|---|
| `make bootstrap ROLE=...` | install toolchain for a role |
| `make broker` | start mosquitto |
| `make sim` | all sims (`make sim NODES=head,sensors,friendlink,glasses,laptop`) |
| `make hub` | run hub |
| `make cloud-dev` / `make cloud-deploy` | `modal serve` / `modal deploy` |
| `make web` | dev server for apps/web |
| `make tail TOPIC='kaiku/v1/+/obs/#'` | live bus view |
| `make record` / `make replay FILE=` | capture/replay bus traffic |
| `make test` | contracts + unit + contract tests |
| `make doctor` | health report |
| `make demo-reset` | reset demo state |
| `make setup` / `make env` | `uv sync` + web deps / create `.env` |
| `make contracts` / `make agents` | regenerate schemas + TS / module index + agent files, then check sync |
| `make cloud-local` / `make seed [ARGS=--reset]` | cloud on :8000 without Modal / seed SIMULATED patients |
| `make web-build` | static-export the Next.js app to `apps/web/out` |
| `make check` | lint + all tests + sync checks (run before pushing) |

### 13.2 Locate a fault in < 2 minutes
1. `make doctor` → which node/source is not ✅?
2. Health topics → stale heartbeat = that node.
3. Raw topics → data arriving? No: firmware/adapter. Yes: perception.
4. Obs topics → produced? No: hub perception/rituals. Yes but not on dashboard: uplink/cloud (`/healthz`, Modal logs).
5. Dashboard state looks wrong → `GET /v1/patients/{id}/consensus` → check source verdicts and evidence → re-run `consensus.py` on that patient's data in a unit test.
6. Reproduce with `make replay FILE=...` against only the suspect module; turn it into a failing test; fix; keep the recording as a fixture.

### 13.3 Common failures

| symptom | likely module | check |
|---|---|---|
| No taps | head firmware / IMU threshold | `raw/head/tap`; retune from 3 recordings |
| Phantom taps while head moves | perception/taps | high-pass; ignore during motor accel/decel |
| HRV nonsense | sensors PPG / hrv.py | `quality` gate; finger cradle shading; stable sample rate |
| Head drifts off-centre | head pan | hall homing; gyro bias calibration at boot |
| Voice lag | live/gemini_live | hotspot; `KAIKU_VOICE=text` fallback |
| Music doesn't follow | live/lyria | BPM clamp; resend full config; local click still works |
| Laptop source "insufficient" | apps/web/session or data window | sessions per week; confidence formula; seeded history |
| Everything "watch" | consensus coverage | only one source sufficient → check uplink of the others |
| Dashboard stale | uplink / cloud | uplink queue size in `health/hub`; `/healthz`; Modal logs |
| No explanation | cloud/llm | GPU cold start → `gemma_hosted` or `template` |

### 13.4 Logging
JSON lines to stdout: `{"ts","node","level","event","msg",...}`. Never log secrets, raw audio, images or transcripts.

---

## 14. Demo & video

### 14.1 Live table demo (~3 min, one presenter, robot + laptop + glasses on the table)
1. **0:00 Problem (20 s):** half of TMS responders lose the effect within a year; when the visits stop, clinicians lose their view; one signal is too thin.
2. **0:20 The hospital principle (10 s):** clinicians never judge from one measurement. Neither do we: three independent sources.
3. **0:30 Source 1, robot (50 s):** head finds the judge's face; "turn my ear" (mood, energy, sleep); finger on chest (breathing glow, HRV); "drum on my head" (music follows, head sways).
4. **1:20 Sources 2 and 3 (20 s):** glasses walk card; 30-second laptop session snippet.
5. **1:40 Consensus (40 s):** the judge's data lands live on the robot card. Switch to Aino (SIMULATED 30 days): robot worse + laptop worse, glasses as usual → **Needs a call**, disagreement shown, Gemma explanation, PHQ-9 trend; click "flag for booster".
6. **2:20 Proof & path (40 s):** `/eval` numbers (alert precision, lead time, losing one source); pilot with Aalto + a neuromodulation unit; iCBT referral route; tech stack in one sentence.

### 14.2 Top-5 stage pitch (3 min + 3 min Q&A)
Same beats; open with the punchline; one live robot moment; end on the consensus screen. Prepare answers: false alarms (simulation + two-source rule), disagreement handling, privacy (derived numbers only), why a robot (initiative + Autom adherence evidence), regulation (research demo now, MDR path later), who pays (wellbeing services counties / HUS during the post-TMS window), how it fails (coverage gaps, self-report correlation, sensor noise).

### 14.3 Video (≤ 2:00)
| time | shot |
|---|---|
| 0:00–0:10 | Dark Finnish morning. "About half of TMS responders lose the effect within a year." |
| 0:10–0:15 | "Hospitals never judge from one measurement. Neither does Kaiku." |
| 0:15–0:45 | Robot ritual: head turns to her, ear dial ×3, finger on chest + breathing glow (HRV overlay), drumming + sway |
| 0:45–0:58 | Glasses walk (outdoor minutes counter, "what is shared" screen) |
| 0:58–1:08 | Laptop 2-minute session (indicators on, "nothing recorded") |
| 1:08–1:35 | Dashboard: three source cards, Day 23 (SIMULATED) robot + laptop worse, glasses as usual → Needs a call; explanation; flag booster |
| 1:35–1:50 | Eval numbers + architecture frame (Gemini Live, Lyria, Gemma on Modal, Atech, UNO Q, Meta) |
| 1:50–2:00 | Punchline + "Kaiku" |

---

## 15. Submission

- **Project name:** Kaiku
- **Punchline (178/200):** "A friend on your desk, a voice in your ear, a quiet eye on your days. Kaiku notices how you're really doing after depression treatment, and tells your care team when it matters."
- **Description:** Appendix A (4,997/5,000; if the form rejects it, delete the sentence starting "The signals mirror those…"). Keep a copy in `docs/submission.md`.
- **Before FINAL, remove or soften anything not running:** laptop reaction task / webcam expressivity; robot speech features; bandit; consensus-accuracy simulation; Gemma on Modal GPU (say "hosted Gemma" if fallback used); glasses app; specific sensors. Add real numbers (simulation, tester/mentor feedback) if available.

**Checklist:**
- [ ] Name, punchline, description
- [ ] Challenges: Beyond the Clinic + Gemini + Gemma + Modal + Meta + Atech
- [ ] Technologies used
- [ ] Video ≤ 2:00, public link
- [ ] Demo URL (Modal) + public source repo (MIT); source publicity set
- [ ] Credit preference, pitch deck PDF
- [ ] Team phone numbers + Discord usernames
- [ ] Atech: Discord summary post; repo or exported Atech project
- [ ] Set to FINAL before 10:00 Sun (target 09:30)
- [ ] Whole team at the table 10:30

---

## 16. Venue & schedule (Sat–Sun)

- **Hype Areena**, Vanha Jorvaksentie 3, Espoo (metro Kivenlahti). Hacking areas 3rd and 5th floors. Arduino Hardware Lab, 3D printers and drone area on the 5th floor.
- **Booths:** 3rd floor — Google DeepMind (#3), Verda, MariaDB, Cala, etc.; NVIDIA, OpenAI roundtables. 5th floor — Meta (#2), Modal (#4), Aalto University (#11), Atech roundtable (#1), Ignite Next × Intel, Exa.
- **Saturday:** Cala 11:00 · Submissions open 12:00 · Intel 12:00 (Hardware Lab) · Hostinger keynote 13:00 · **Modal 13:30** · Kiuas "Can It Be a Company?" 14:30 (Loft) · Exa 16:30 · Context 17:30 · Maria01 18:00. Check Discord for rooms (guide lists both the 2nd-floor registration area and the 4th-floor Loft).
- **Sunday:** **10:00 final submission** · 10:30–13:00 peer review (be present 10:30–14:00) · 14:00 ceremony · 14:15 top 5 pitches · 15:10 challenge winners · 15:50 Junction winner.
- Meta: teams with the best submissions may be invited to a Meta AI forum on Wed 18 Nov.

---

## 17. Open decisions (defaults if nobody answers in 30 min)

| # | question | default |
|---|---|---|
| D1 | Where does conversation audio run? | Hub laptop with USB mic + speaker hidden in the robot body; Atech audio only if a spike proves reliable streaming |
| D2 | Which glasses do we get? | Display → Web App first; RBM Gen 2 only → DAT app or show glasses as roadmap |
| D3 | Android or iOS for DAT? | Android if a compatible phone exists |
| D4 | Hub host | Laptop; UNO Q Linux is a stretch |
| D5 | Gemma size | Smallest instruct variant producing valid JSON explanations |
| D6 | Can Atech firmware run MQTT? | If not → `atech_adapter.py` |
| D7 | Motors geared? | If not → printed reduction for pan |
| D8 | Pre-event CAD | Ask organisers; disclose; redraw if needed |
| D9 | Robot language | Finnish greeting + English conversation; switch via config |
| D10 | PHQ-9 mode | Laptop by default; spoken on robot if time (both obey the item-9 rule) |
| D11 | Laptop expressivity library | In-browser face-landmark model chosen in D's spike; if none works in time, drop expressivity and keep voice + reaction |
| D12 | Consensus thresholds | Values in section 6.4, tuned with the simulation; record final values + rule version |
| D13 | Robot character name | None (service is Kaiku); optional later |

| D14 | Broker auth | Anonymous on the demo LAN; password file if others can join the hotspot |
| D15 | Glasses "worse" threshold | `worse_min_metrics = 1` for glasses (its 1–2 metrics are correlated); tune with simulation |
| D16 | Browser auth | Pairing link with home token (`?home=&t=`) → Bearer; no keys in browsers |

Record decisions in `docs/decisions.md` (D10–D13 already there: pydantic GT, qualified types, shared kit, Next.js).

---

## 18. `docs/progress.md` entry template (append-only)

```
## 2026-11-14 03:40 — <agent or person> — <module>
- Did: <what changed, files>
- Verified: <tests run, sim/hardware checks>
- Contract changes: <none | details + version>
- Broken/blocked: <what, why>
- Next: <the next concrete step>
```

---

## 19. Reference links

- Junction 2026: https://2026.hackjunction.com · Platform: https://hackjunction.app
- Gemini coding agents: https://ai.google.dev/gemini-api/docs/coding-agents · llms.txt: https://ai.google.dev/gemini-api/docs/llms.txt · skills: https://github.com/google-gemini/gemini-skills
- Lyria RealTime: https://ai.google.dev/gemini-api/docs/realtime-music-generation
- Gemma: https://ai.google.dev/gemma/docs
- Modal: https://modal.com/docs · https://github.com/modal-labs/modal-examples
- Meta Wearables: https://wearables.developer.meta.com/
  - Web Apps: https://wearables.developer.meta.com/docs/develop/webapps · setup: /docs/develop/webapps/setup/ · docs MCP: /docs/develop/webapps/wearables-documentation-mcp/
  - UI Toolkit: https://wearables.developer.meta.com/docs/develop/webapps/design/getting-started/what-is-the-toolkit/
  - DAT: https://wearables.developer.meta.com/docs/develop/dat/getting-started-toolkit
  - Repos: https://github.com/meta/meta-wearables-webapp · https://github.com/meta/meta-wearables-dat-ios · https://github.com/meta/meta-wearables-dat-android (also github.com/facebook/…)
  - Simulator: https://chromewebstore.google.com/detail/jpjlmmodokemlepklkdbimceggpbjcll
  - Docs MCP endpoint: https://mcp.developer.meta.com/wearables
- Atech: https://atech.dev · https://atech.dev/docs · https://github.com/atechdotdev
- Joy-IT sensor kit: https://sensorkit.joy-it.net
- MIELI: https://mieli.fi/en/
- Evidence links: section 4.

---

## Appendix A — Submission description (as entered)

```markdown
## The problem
TMS (transcranial magnetic stimulation) helps people with severe depression, but the effect often fades: in a meta-analysis, only about half of initial responders still responded 6–12 months later. Treatment means ~20 clinic visits, 3–5 days a week, with clinicians seeing the patient almost daily. When the visits end, that view disappears. Worsening caught early can often be reversed with a booster course, but at home nobody notices in time, and one questionnaire or wearable is too thin a signal to act on.

## Our approach
In hospital, a patient's state is never judged from one measurement: clinicians combine interviews, scales, observation and tests. **Kaiku brings that principle home.** Three touchpoints each observe the person independently, and a dashboard combines them into **one consensus answer about their current state**, with the evidence behind it.

### 1. Home robot
A small companion robot with a moving head and animated eyes. Each morning it turns to find you and runs a ~3-minute ritual:
- **Ear dial:** rate mood, energy and last night's sleep with three turns. No typing.
- **Pulse sensor:** finger on its chest for resting heart rate and HRV, then a guided breathing exercise with a glowing chest, then HRV again.
- **Drumming:** tap its head and Google's Lyria RealTime turns your rhythm into music that follows you, inspired by a Finnish randomised trial of improvisational music therapy for depression. Tempo, force and duration also track energy, no questions asked.
- **Voice:** speech rate and pauses from the conversation, computed locally.
- **Passive:** get-up time and room light from presence and light sensors.

*Apps wait to be opened and voice assistants wait to be spoken to. Depression takes away that initiative, so Kaiku reaches out first.*

### 2. Meta AI glasses
An audio-first walk companion on Ray-Ban Display glasses encourages daylight walks and logs time outdoors, capturing life beyond the living room.

### 3. Laptop apps
- **2-minute session:** a spoken prompt and a short reaction task. Voice and webcam facial expressivity are analysed on the laptop; only derived numbers are kept.
- **PHQ-9 every two weeks:** the standard clinical cadence, anchoring everything to a validated scale.

## From three readings to one consensus
Each source compares today with the person's **own baseline** and returns a verdict (*better / as usual / worse*) plus a confidence based on how much good data it has.

| Consensus | Rule |
|---|---|
| **Stable** | Sources report as usual or better |
| **Watch** | One source reports worse |
| **Needs a call** | Two or more independent sources report worse |

The rule is fixed and auditable; Gemma (an open-weights model) only writes the plain-language explanation. **Disagreement is shown, not hidden**, e.g. "robot: worse (lower HRV, slower drumming); glasses: as usual (walking daily); laptop: worse (flatter voice)." The signals mirror those that European studies such as RADAR-MDD link to relapse: sleep, activity, mood and speech.

## The dashboard
- **Clinicians:** a list ranked by consensus, each person's three source cards, trends against baseline and the evidence for every flag. From there they can flag someone for a booster TMS session or a referral to Finland's national internet therapy (Mielenterveystalo). No extra workload between visits.
- **The person:** the same picture in plain language, and which activities have helped them most.

## Closed loop
Each activity (breathing, drumming, a walk, a friend ping) is scored immediately (HRV and mood before vs after) and next day; a bandit learner picks each person's next suggestion.

## Technology
- **Gemini Live API:** real-time Finnish/English voice with function calling driving the ritual.
- **Lyria RealTime:** music steered live by drumming.
- **Gemma 4 on Modal:** served on GPU for explanations, keeping health reasoning on infrastructure we control.
- **Modal:** ingest API, storage, scheduled analytics, model serving, consensus-accuracy simulation on synthetic patients, dashboard hosting.
- **Robot:** Atech modules and Arduino UNO Q: animated eyes, IMU tap detection, DC-motor head, ear encoder, pulse, light and distance sensors.
- **Glasses:** Meta Ray-Ban Display Web App.
- **Architecture:** one versioned message contract (MQTT at home, HTTPS to cloud); each touchpoint can be swapped independently.

## Safety and privacy
- **Only derived numbers leave the home.** Camera frames are never stored.
- **Deterministic crisis path.** A positive PHQ-9 item 9 or crisis language triggers a fixed response with no AI: MIELI's 24/7 crisis line (09 2525 0111) and 112 are shown, and the clinician is alerted.
- **Not diagnostic.** Kaiku reports change, not diagnoses. Demo history is synthetic and labelled.

## What's next
A pilot with Aalto and a neuromodulation unit to validate the consensus against clinician assessments, then the EU medical-device pathway and reimbursement routes such as Germany's DiGA.
```

---

## 20. Quickstart (10 minutes, no hardware, no cloud account)

```bash
git clone https://github.com/Harrishayy/kaiku.git && cd kaiku
make bootstrap ROLE=all     # or hub|cloud|web|firmware|glasses-web|glasses-dat; prints what's left by hand
make test

make broker                 # terminal 1: mosquitto
make cloud-local            # terminal 2: cloud API on :8000 (SQLite in logs/)
make seed && make sim       # terminal 3: 8 SIMULATED patients, then all five twins (robot, glasses, laptop)
make hub                    # terminal 4: ritual runs when the sim person walks up
make tail TOPIC='kaiku/v1/+/obs/#'
make web                    # http://localhost:3000/clinician/
```

## 21. Agent context system (how every agent stays in sync)

- **Root `AGENTS.md`**: cross-cutting rules, the ground-truth map (which file owns which fact), the sync rule, and a module index generated from `modules.toml`.
- **`<module>/AGENTS.md`**: the module's only doc: purpose, interfaces, file map, extension points (how to add/swap/remove a piece), invariants, how to run/test, known issues. Claude Code (≥ 2.1.281) loads it natively when it opens files in that folder; Gemini CLI via `.gemini/settings.json`; Codex/Cursor natively. No `CLAUDE.md`/`GEMINI.md`/module `README.md` anywhere (a `CLAUDE.md` would stop Claude Code reading `AGENTS.md`).
- **`modules.toml`**: which modules exist, owner, kind, emits/consumes, removable.
- **Sync rule:** a change isn't done until the ground truth describing it is updated in the same commit. `make test` (via `tools/agents_sync.py`) fails when a module lacks `AGENTS.md` or its sections, grows a README/CLAUDE/GEMINI file, references a message type that doesn't exist, when an obs type has no producer or no consumer, or when the module index is stale. `make agents` fixes the generated parts.
- **Add a component:** copy `docs/templates/module/AGENTS.template.md`, add a `[[module]]` entry, `make agents`. **Remove one:** delete the folder + entry; nothing imports it, so the checker shows exactly which message flows lose a producer/consumer.
