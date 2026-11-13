# Kaiku

> *kaiku* — Finnish for "echo". Helping people stay well at home after TMS treatment for depression.

**A friend on your desk, a voice in your ear, a quiet eye on your days. Kaiku notices how you're really doing
after depression treatment, and tells your care team when it matters.**

A TMS course is about 20 clinic visits, 3–5 days a week, and clinicians see the patient almost daily. When the
visits end, that view disappears, and about half of responders lose the effect within 6–12 months. Worsening
caught early can often be reversed with a booster, but one questionnaire or one wearable is too thin a signal.

In hospital, a patient's state is never judged from one measurement. Kaiku brings that principle home:
**three independent sources** each compare today with the person's own baseline, and a **deterministic
consensus** combines them on one dashboard, with the evidence and any disagreement shown.

| Source | What it is | What it measures |
|---|---|---|
| Home robot | moving head, animated eyes, ~3-min morning ritual it starts itself | mood/energy/sleep dial, HR + HRV around guided breathing, drumming energy, speech pace, get-up time, room light |
| Meta AI glasses | audio-first walk companion (Ray-Ban Display web app) | outings, time outdoors, steps |
| Laptop | 2-minute session + PHQ-9 every 14 days | voice features, facial expressivity (in-browser), reaction time; PHQ-9 |

Consensus: **Stable** · **Watch** (one source worse, or only one source has enough data) · **Needs a call** (two or
more sources worse) · **Safety** (any crisis trigger). The rule is fixed and auditable; Gemma only explains it.

Built at **Junction 2026** (Espoo) for Aalto University's *Beyond the Clinic* challenge, plus the Gemini API,
Gemma, Modal, Meta AI Glasses and Atech tracks.

> Research prototype. Not a medical device, not a crisis service, and it does not diagnose or predict relapse.
> In Finland: MIELI Crisis Helpline 09 2525 0111 (24/7), emergencies 112.

## Architecture

```
 SOURCE 1: ROBOT (home LAN)                         SOURCE 2: GLASSES     SOURCE 3: LAPTOP
 head (Atech) ─┐                ┌─ Gemini Live      walk companion        /session  /phq9
 sensors (UNO Q)┼─ MQTT ─ hub ──┤  Lyria RealTime   (web app)             (features in browser)
 friend link ──┘        (Python)└─ HTTPS ──┐              │ HTTPS               │ HTTPS
                                           ▼              ▼                     ▼
                Modal: ingest → SQLite → baselines → per-source verdicts → CONSENSUS v1 → Gemma explanation
                       bandit · 15-min cron · .map simulation · hosts the Next.js dashboard
```

Every message is defined once in [`contracts/`](contracts/AGENTS.md) and validated on both ends. Every source has
a software twin in [`sim/`](sim/AGENTS.md), so the whole system runs on a laptop. Modules are listed in
[`modules.toml`](modules.toml) and can be added or removed without touching each other.

## Quickstart

Needs macOS or Linux, [uv](https://docs.astral.sh/uv/), Node ≥ 20 + pnpm, mosquitto.

```bash
git clone https://github.com/Harrishayy/kaiku.git && cd kaiku
make bootstrap ROLE=all   # installs what it can, prints what's left
make test

make broker               # terminal 1
make cloud-local          # terminal 2
make seed && make sim     # terminal 3: 8 simulated patients + twins of robot, glasses, laptop
make hub                  # terminal 4: the ritual runs when the sim person walks up
make web                  # http://localhost:3000/clinician/
```

`make help` lists every command. `make doctor` reports what's broken.

## Repository

| Path | What |
|---|---|
| [`docs/plans/`](docs/plans/) | plans in order: 01 foundation (done), 02 companion apps, 03 intelligence, 04 mind depth (current) — start here |
| [`AGENTS.md`](AGENTS.md) | rules for coding agents and humans; every module has its own `AGENTS.md` |
| [`modules.toml`](modules.toml) | module registry: what exists, who owns it, what it emits/consumes |
| `contracts/` | message envelope, payloads, topics, API models, shared MQTT `Bus` |
| `hub/` | orchestrator: perception, ritual state machine, safety gate, uplink, voice/music adapters |
| `cloud/` | Modal app: API, storage, per-source verdicts, consensus, bandit, Gemma explanations, simulation |
| `apps/web/` | Next.js: clinician dashboard, person view, laptop session, PHQ-9, live view, health, eval |
| `apps/glasses-webapp/` | Meta Ray-Ban Display web app (walks, breathing) |
| `firmware/` | Atech head, UNO Q sensors, LoRa friend link |
| `sim/`, `tools/` | twins of every source + demo patients; bus tail/record/replay, doctor, agents sync |
| `docs/` | progress log, decisions, safety, privacy, tracks |

## Tracks

See [`docs/tracks.md`](docs/tracks.md).

## Safety and privacy

Crisis handling is deterministic and never uses an LLM ([`docs/safety.md`](docs/safety.md)). Camera frames
and raw audio are never stored by us; only derived numbers leave the home ([`docs/privacy.md`](docs/privacy.md)).

## Licence

[MIT](LICENSE)
