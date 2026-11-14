<div align="center">

<img src="design/mascot.svg" width="132" alt="Kaiku, the mascot">

# Kaiku

**A friend on your desk, a voice in your ear, a clearer record for your care team.**

Kaiku (Finnish for "echo") helps people stay well at home after TMS treatment for depression.

**[Open the live demo](https://harrish21raj--kaiku-web.us-east.modal.run/?id=aino)** (a simulated record) ·
**[Pitch deck (PDF)](demo/deck/kaiku-deck.pdf)** · [Try it](#try-it) · [Is it any good?](#is-it-any-good)

<sub>Junction 2026 · Aalto University "Beyond the Clinic" · research prototype: not a medical device, not a crisis service · every record shown is simulated</sub>

</div>

<!-- VIDEO: add the public video link (maximum 2:00) next to the deck link once it exists. -->

<table align="center">
<tr>
<td align="center" valign="middle"><img src="docs/media/ios-today-path.gif" width="150" alt="iPhone app: today's path"><br><sub><b>iPhone</b><br>Today's path: weather dial, the Lantern game, the sky she lit</sub></td>
<td align="center" valign="middle"><img src="docs/media/web-dashboard.gif" width="400" alt="Web: the practitioner dashboard"><br><sub><b>Web</b><br>The practitioner dashboard on the public simulated record</sub></td>
<td align="center" valign="middle"><img src="docs/media/mac-app.gif" width="195" alt="Mac app screens"><br><sub><b>Mac</b><br>In-app renders of the real Mac screens, stepped through (not a screen capture)<!-- MAC-GIF-CAPTION --></sub></td>
</tr>
</table>

<p align="center"><sub>iPhone clips are recorded on the iPhone simulator against a local service holding the simulated record, with no model calls; the dashboard clip is the public deployment with its cached Gemma review.</sub></p>

## The problem and the idea

A TMS (transcranial magnetic stimulation) course means around twenty clinic visits, so for weeks someone sees
the person almost every day. When the course ends, that daily view ends with it, and the benefit can fade.
Depression also takes away the initiative to open an app and report; one questionnaire or one wearable is a
thin signal.

Kaiku reaches out first: a desk robot with a three-minute morning ritual, an iPhone and Mac app with short
games and a voice to talk to, and that same voice in the glasses on a walk. Each kind of everyday signal is
compared with the person's **own usual**, a fixed, readable rule combines them into one **consensus**, and a
practitioner sees on one page who is worth a check-in, and why.

## How it works

```mermaid
flowchart TD
  subgraph home["Devices at home"]
    phone["iPhone<br/>check-ins, games, talk, walks"]
    mac["Mac<br/>rhythm of the day"]
    glasses["Meta glasses<br/>voice on walks, through the iPhone"]
    robot["Desk robot<br/>dial, breath, drum"]
    watch["Watch, optional<br/>daily summary"]
  end
  phone --> obs
  mac --> obs
  glasses --> obs
  robot --> obs
  watch --> obs
  obs["Observations<br/>derived numbers only, each with its real device source"]
  obs --> verdict["Verdict per signal group<br/>each compared with the person's own baseline"]
  verdict --> consensus["Deterministic consensus<br/>one readable rule file, no model"]
  subgraph intel["Intelligence layer"]
    review["Gemma review, each finding checked by validators<br/>with the course of change, reflections and knowledge graph"]
    live["Gemini Live<br/>the voice that meets the feeling"]
  end
  consensus -->|"record and state"| review
  consensus -->|"a tone only, never scores"| live
  consensus -->|"state, set by code"| dash
  review --> dash["Practitioner dashboard"]
  live --> person["The person"]
```

- **Signal groups, not devices.** Check-ins and robot, walks and outings, apps, and an optional watch summary. Several can come from one phone, so every record keeps its real device source.
- **Code sets the state.** [`config/criteria.toml`](config/criteria.toml) is the whole rule, versioned by hash. No model decides a person's state or handles a crisis.
- **Models interpret and speak.** Gemma chooses evidence and words the practitioner review; code checks every citation and renders every number. Gemini Live speaks from a small prepared card (memories she chose to share, today's activities, a tone) and never sees scores or states ([D35](docs/decisions.md)).

| Consensus | When |
|---|---|
| **Stable** | Enough data, nothing worse than usual, and at least 21 days of record |
| **Watch** (worth a check-in) | One signal group worse than her usual, or too little data: shown as "not enough data", never as stable |
| **Needs a call** | Two or more signal groups worse than her usual |
| **Safety** | PHQ-9 item 9 or a crisis phrase; overrides everything, with a fixed script and no model |

## A companion, not a reporting machine

<table align="center">
<tr>
<td align="center" valign="top"><img src="docs/media/ios-checkin-chat.png" width="190" alt="iPhone: a hard-day check-in where Kaiku stays and offers one thing"><br><sub>A hard day: Kaiku stays and offers one thing</sub></td>
<td align="center" valign="top"><img src="docs/media/ios-today-invitation.png" width="190" alt="iPhone: Today with one invitation from Kaiku"><br><sub>Today: one invitation, from something she said</sub></td>
<td align="center" valign="top"><img src="docs/media/ios-walk-styles.png" width="190" alt="iPhone: the walk start with three walk styles"><br><sub>A walk: Calm, Playful or Chatty</sub></td>
</tr>
</table>

- **It notices and acts.** When what the person says, or how they say it, carries a clear feeling, the voice tells Kaiku's mind once (the `feel` tool, non-blocking, so the talk never stalls). The answer is a small plan: how to meet it (comfort, celebrate, explore, give space), whether to keep the chat brief or stay, one thing the record knows helps this person, and at most one offer per conversation. Good news gets gladness. A heavy day gets company before any suggestion.
- **The check-in is a small chat.** Today's first stop opens with Kaiku's hello, like meeting on the street. Answer by voice, by typing, or turn the three dials underneath; all three count. An ordinary day closes in a few turns; a really good or really hard one goes on as long as the person wants.
- **A suggestion comes as a card.** When Kaiku suggests a game, a journal entry, breathing or a walk, it makes a tool call that puts one card in the conversation. Nothing opens without the person's yes, and a no is final for that conversation.
- **One mind on every device.** A favourite place mentioned on a glasses walk is known to the phone, the Mac and the robot the next time ([tested](cloud/tests/test_walk.py)). Once a day Kaiku may bring one thing up on Today, chosen by rule and worded around her own words.
- **None of this sets the state.** The consensus stays code. The plan shapes a conversation; it never changes what the practitioner sees as the state.

**Where it stands:** shown with real Gemini Live replies to typed input on the iPhone simulator. An ordinary day
closed in three turns; on a hard day ("my cat died") Kaiku stayed, offered sitting quietly together once and
went on after the offer was taken. Not yet heard through a real microphone.

## The surfaces

### iPhone

<table align="center">
<tr>
<td align="center" valign="top"><img src="docs/media/ios-first-run.gif" width="170" alt="iPhone: first-run setup"><br><sub>First-run setup to Today (iPhone simulator)</sub></td>
<td align="center" valign="top"><img src="docs/media/ios-seed-shelf.gif" width="170" alt="iPhone: Seed shelf game"><br><sub>Seed shelf, a measured game</sub></td>
<td align="center" valign="top"><img src="docs/media/ios-talk.gif" width="170" alt="iPhone: Talk"><br><sub>Talk: a typed message and Kaiku's reply</sub></td>
<td align="center" valign="top"><img src="docs/media/ios-today-so-far.gif" width="170" alt="iPhone: Your days"><br><sub>Your days: "Today, so far" (what was noticed, from which device, what is shared)</sub></td>
</tr>
</table>

- **Three minutes a day.** Today's path is a small check-in chat with Kaiku, its one suggestion, the Lantern game and one more game in turn. Games end on what grew, never a time or a count; they are short activities inspired by research, not validated tests ([games](docs/validation.md#games)).
- **Talk is a call.** One voice everywhere: a Gemini Live call opened with a short-lived token from the cloud, so the app never holds the API key. Mute yourself or mute Kaiku, independently; the words of both keep coming as captions. The call goes on when the phone locks, with a bar on the Lock Screen and in the Dynamic Island (elapsed time, the last caption, mute, end), and ends by itself after three quiet minutes in the background. If the voice is unavailable Kaiku stays silent and shows text, never a synthesizer.
- **Her choices, her day.** Every signal has its own switch, set at first run and reversible. "Today, so far" lists what was noticed, from which device and what is shared. Readings queue on the phone until the cloud confirms them.

**Where it stands:** a signed build is installed on a real iPhone and found the service from the phone. On the
simulator, with typed input, a real call ran 4 min 48 s across a token renewal while locked, answered from the
Lock Screen caption, and was ended from the Lock Screen. A real microphone, Kaiku's voice while locked, and
Apple Health are not yet accepted on the device. [`apps/apple/AGENTS.md`](apps/apple/AGENTS.md)

### Mac

<p align="center"><img src="docs/media/mac-app.gif" width="560" alt="Mac app screens"><br><sub>In-app renders of the real Mac screens, stepped through (not a screen capture)<!-- MAC-GIF-CAPTION --></sub></p>

- **The same Kaiku on the desk.** One Swift package holds every screen and game; the Mac and iPhone targets are thin shells around it.
- **Rhythm, never content.** Opt-in and pausable: the frontmost app is mapped to a broad category on the Mac, and one message an hour carries minutes per category, late-night minutes, switches and breaks. Never window titles, URLs, keystrokes or screenshots; the contract rejects extra fields.
- **A quiet nudge from the notch.** After 01:00 while still active, or after 90 active minutes without a break, Kaiku peeks from the notch with one line: at most three a day, with a snooze.
- **Quick talk from any app.** A thin bar rests at the left edge of the screen. Hover and it becomes two buttons: start speaking, open Kaiku. Tap Control twice (or Option-Shift-Space) and it grows into a small popup with Kaiku and live captions, and the conversation starts at once without taking focus from the app in front. Mute yourself or mute Kaiku; the captions keep coming. Tuck the popup away and the call lives in the notch with its elapsed time.

<p align="center">
<img src="docs/media/mac-quick-talk-bar.png" width="200" alt="Mac quick talk: the bar on hover with two buttons">
<img src="docs/media/mac-quick-talk-popup.png" width="300" alt="Mac quick talk: the popup while Kaiku answers">
<img src="docs/media/mac-quick-talk-island.png" width="330" alt="Mac: the notch island showing a call">
<br><sub>Quick talk: the bar on hover, the popup, and the call in the notch. Rendered from the app's own views, not a screen capture.</sub></p>

**Where it stands:** the Mac target builds; a simulated late evening produced the peek and its hourly record
on a local service. Quick talk is unit-tested and rendered in every state, and both triggers were shown to need
no Accessibility or Input Monitoring permission; nobody has yet pressed the keys in the running app or spoken to
it. The clip above is rendered in-app, not captured from the screen. [`apps/apple/AGENTS.md`](apps/apple/AGENTS.md)

### Meta glasses walk

<table>
<tr>
<td align="center" width="230"><img src="docs/media/ios-glasses-check.gif" width="190" alt="iPhone: Glasses check"><br><sub>You → Glasses check and its self-test on the simulator with no glasses connected. Real-glasses footage is pending.</sub></td>
<td>

- **A voice in the ear, head up, hands free.** The iPhone registers with the glasses through Meta's Device Access Toolkit. Kaiku's voice travels over ordinary Bluetooth, so the conversation that started in the kitchen continues on the street.
- **The walk survives the glasses.** Glasses off or out of range: the walk continues on the phone, and the record says so.
- **Company, in the style she chooses.** Calm mostly listens and speaks up only when something worth it comes into view. Playful sets small spotting goals ("two more to find": the phone keeps the count, Kaiku only says it) and asks a little about her day. Chatty keeps the talk going. A sad sentence drops the game in any style.
- **It connects what it sees to what it knows.** Her outdoor favourites travel with the walk, so a view can become "Is that your favourite tree up there?". It asks rather than asserts, because a model cannot know it is that tree. A new favourite is kept only from her own words.
- **Seeing is a separate opt-in (D43).** With "Let Kaiku see through the glasses during walks" on (off by default), about one camera frame a second goes to that walk's Gemini Live conversation and nowhere else. With it off, Kaiku says it cannot see.

</td>
</tr>
</table>

**Where it stands:** registration and connection are confirmed on real Gen 2 glasses in Developer Mode. Voice
and seeing are proven with Meta's Mock Device Kit and real Gemini Live calls: stock landscape pictures as the
view (a dull road got no words in any style, a lone tree got the question above) and one three-minute walk on
the simulator with typed lines. Not yet on the real glasses; the five-minute test is [`docs/glasses-test.md`](docs/glasses-test.md). The integration lives in
the iPhone app ([`apps/apple/AGENTS.md`](apps/apple/AGENTS.md)); the two `apps/glasses-*` folders hold instructions only.

### Robot

No clip of the robot in this README yet.

- **It speaks first.** A three-minute morning ritual with no typing: three turns of an ear dial for mood, energy and sleep, one guided breath while the chest glows, and a short rhythm tapped on its head. The drum is inspired by research on improvisational music therapy; the chest light is not light therapy.
- **Ran on the hardware twin.** The whole hub-driven ritual, its crisis gate and the upload of derived numbers run against software twins of the head and sensors over real MQTT (`make sim`, `make hub`). The twins speak the same messages as the boards, and their records are marked simulated.
- **Ran on the boards.** The Atech head ran the full ritual by knob, without a laptop, on its standalone firmware (D44). Over MQTT its knob, button and screen eyes, and the UNO Q's knock drum, face camera and buzzer, were seen on the broker.

- **The head's ritual reaches the record.** In follow mode the hub shadows the standalone head: its dial answers become mood, energy and sleep check-ins and the knocks become a drum session, queued for the cloud and shown in the practitioner's daily account. The hub sends the head no commands, so the two never compete.

**Pending on the physical head:** follow mode is proven against a software twin of the standalone firmware; the
head's network code is built but not yet flashed, so nothing from the physical robot is on the dashboard yet.
The hub-driven ritual with a real microphone, speaker and motor has not run end to end, a crisis phrase cannot
yet stop the standalone head, and pulse stays "not measured" until the finger cradle passes its quality check.
Bring-up steps: [`hub/AGENTS.md`](hub/AGENTS.md). Module docs:
[`hub/`](hub/AGENTS.md) · [`firmware/atech-head/`](firmware/atech-head/AGENTS.md) · [`firmware/unoq-sensors/`](firmware/unoq-sensors/AGENTS.md) ·
[`sim/`](sim/AGENTS.md) · [network handover](docs/robot-network-handover.md)

### Practitioner dashboard

<p align="center"><a href="https://harrish21raj--kaiku-web.us-east.modal.run/?id=aino"><img src="docs/media/web-dashboard.gif" width="820" alt="The practitioner dashboard"></a><br><sub>The practitioner dashboard on the public simulated record · <a href="docs/media/web-dashboard.png">full-size still</a></sub></p>

- **One page, one person.** A header strip with the consensus in plain words, then nine movable panels: trends against her usual range, consensus now, Kaiku's review, routine, knowledge graph, daily account, care actions, ask the record, and coverage.
- **A review that can be checked.** Gemma writes the overview and findings; code renders the numbers, and each finding opens the records it cites. A second tab shows the agent trace: every step, whether a rule or a model ran it, validator rejections and fallbacks.
- **Honest about its sources.** Each signal group shows which device actually sent its records and a "Simulated" marker. Care actions are recorded in Kaiku and contact nobody. Conversation words are never shown.

**Where it stands:** live at the public link, read-only, with one simulated record. [`apps/web/AGENTS.md`](apps/web/AGENTS.md)

### Cloud on Modal

- **One deployed app.** A single warm container serves the API and the dashboard from one URL, with SQLite on a Modal Volume ([`cloud/app.py`](cloud/app.py)). It accepts derived observations only and rejects anything else.
- **Scheduled and parallel work.** The same file schedules a recompute every 15 minutes, a nightly run and a weekly brief, and fans a simulation of 72 synthetic people out over 8 shards with `.map()`.
- **Gemma, plainly placed.** Reviews run through Google's hosted API (`gemma-4-26b-a4b-it`). A separate scale-to-zero GPU app ([`cloud/gemma_app.py`](cloud/gemma_app.py)) answered one cold call on a Modal H100 and is not the default path.

**Where it stands:** the public URL was checked from outside (dashboard open, admin routes closed without a
token). [`cloud/AGENTS.md`](cloud/AGENTS.md)

## Try it

**Nothing to install:** open the [public simulated record](https://harrish21raj--kaiku-web.us-east.modal.run/?id=aino).
It is one authored person, Aino, read-only.

**On your machine:** needs macOS or Linux, [uv](https://docs.astral.sh/uv/), and Node 20 + pnpm for the
dashboard pages. mosquitto is only needed for the robot and its software twins. No API key is needed to see
the dashboard.

```bash
git clone https://github.com/Harrishayy/kaiku.git && cd kaiku
make setup     # Python + web dependencies, creates .env from .env.example
make doctor    # says what is missing and how to fix it
make demo      # broker + local API + dashboard + Aino's sixteen-day record; prints the links
```

`make demo` is safe to run twice: it reuses an API or broker that is already up and adds nothing the second
time. It stays in the foreground; Ctrl-C stops what it started. Logs are in `logs/demo/`.

| Then | Command |
|---|---|
| Open the practitioner dashboard | `http://127.0.0.1:8000/` (the link `make demo` prints) |
| See today's recordings move the reading | `make live-day` (a good day and a rough day, on a throwaway copy) |
| Start over (the record ends yesterday again) | `make demo-reset` (drops simulated data, keeps live recordings) |
| Use another port or database | `KAIKU_DEMO_PORT=8010 KAIKU_DB_PATH=/tmp/kaiku.sqlite make demo` |
| Run the robot ritual on software twins | `make sim` and `KAIKU_VOICE=text make hub` in two more terminals |
| See how the rule behaves on synthetic courses | `make calibrate` (about 20 s) |

**The person in the record.** Aino, 58, comes home after a TMS course. Her simulated record holds sixteen days
and always ends yesterday, so today is open for live recordings. The states are not written into the data: the
real rule reads it. Days 1 to 10 the baseline is forming, on day 11 the first signal group is worse (worth a
check-in), on day 12 the daily signals alone raise "needs a call", and on day 13 the care team rings and she
fills in a PHQ-9. [`cloud/tests/test_single_person.py`](cloud/tests/test_single_person.py) pins those states day by day.

### Link your own iPhone or Mac

The apps normally create their own home on first run. To add live recordings to Aino's simulated record
instead, pair with the account link that `make demo` prints (`http://<this-mac>:8000/?home=aino`):

```bash
# iPhone: builds, signs, installs and launches the app with that link
KAIKU_TEAM=<apple team id> apps/apple/scripts/run_on_iphone.sh aino

# Mac app: build it, then launch the built app with the link
cd apps/apple && xcodegen
xcodebuild -project Kaiku.xcodeproj -scheme "Kaiku Mac" -destination "platform=macOS" build
<build products>/Kaiku.app/Contents/MacOS/Kaiku -kaikuPairLink "http://127.0.0.1:8000/?home=aino"

# Robot hub and software twins (from the repo root, two terminals)
KAIKU_HOME_ID=aino make sim
KAIKU_HOME_ID=aino KAIKU_VOICE=text make hub
```

The iPhone script needs Xcode, xcodegen, an iPhone paired with Developer Mode on, and `make demo` on its
default port 8000, on the same network as the phone. Keep the phone unlocked: the link is passed when the app
launches (`--install-only` installs on a locked phone and does not pair). A check-in, a game or a walk recorded
today is then compared with her sixteen days. Details: [`apps/apple/AGENTS.md`](apps/apple/AGENTS.md).

## Is it any good?

**On people: unknown.** Nobody has used Kaiku while unwell, so there is no measured sensitivity or specificity,
and we claim none. What we can measure is how the rule behaves on labelled synthetic courses from our own
generator: 40 synthetic people per course, 60 days, rule `consensus-v1+ef17c3f3`. Assumptions and every limit
are in [`docs/validation.md`](docs/validation.md); reproduce with `make calibrate`.

| On synthetic courses | Mild change (1 SD) | Moderate (2 SD) | Marked (3 SD) |
|---|---|---|---|
| Flagged within 21 days (worth a check-in), average of six kinds of course | 68 % | 96 % | 99 % |
| Reaches "needs a call", same average | 21 % | 71 % | 86 % |
| Days to flag, sudden drop that stays | 5 | 2 | 2 |
| Days to flag, gradual decline over 14 days | 12 | 7.5 | 6 |

- **People who are fine:** a mean of 0.08 false flags per person-week, about one unneeded "worth a check-in" per person every three months, and 0.00 to 0.01 false "needs a call" per person-week. A fine person still has a 15 % chance of some flag in any 3-week window.
- **A new record:** "not enough data" for days 1 to 8, a first flag possible from day 11 against an early baseline labelled lower confidence, and never "stable" before day 21. A moderate dip on days 9 to 12 is found by day 16 in 57 % of synthetic people (marked 83 %, mild 15 %).
- **What is weak:** no clinical validation; the numbers describe the rule, not people. Mild change is mostly missed at the "needs a call" level. Skipped check-ins hide a decline: for a moderate one, "needs a call" falls from 90 % to 53 %. Without the PHQ-9, a moderate drop reaches "needs a call" in 57 % instead of 85 %. PHQ-9 is the only validated instrument here. The "what helps" learner ranks what coincides with good days, not what works.

| Part | Real today | Simulated or pending a physical test |
|---|---|---|
| Cloud, consensus, dashboard | Deployed on Modal and checked from outside; 973 Python tests passed at the last logged merge | Every record is authored and marked simulated; thresholds are engineering defaults |
| Gemma | Reviews through Google's hosted API on the simulated record; one cold call on a Modal H100 | Our own GPU is not the default path; no tuned weights |
| Gemini Live | Real Live calls with injected speech, typed turns (ordinary day, hard day, spotting game) and pictures as the walk's view | A spoken exchange on a real microphone |
| iPhone app | Signed build installed on a real iPhone; 309 Swift tests passed (11 skipped); a real typed call kept going while the simulator was locked | Microphone, Kaiku's voice while locked and Apple Health on the device |
| Mac app | Builds; a simulated late evening produced the notch peek and its hourly record; quick talk rendered in every state | Quick talk by real key presses and voice; a screen capture; real usage over days |
| Meta glasses | Registration and connection on real Gen 2 glasses (Developer Mode); a three-minute walk with Meta's mock glasses and real Live | Voice, head motion, walk styles and opt-in seeing on the real glasses: one filmed walk |
| Robot | Ritual by knob on the Atech board; knob, button, eyes, knock drum, face camera and buzzer seen over MQTT | Hub-driven ritual on the physical robot, its records on the dashboard, motor, pulse |
| People | Four logged sessions, all by the project lead | Testers outside the team; any clinical validation |

Sources: the dated audit [`docs/track-readiness.md`](docs/track-readiness.md) and the latest entries of [`docs/progress.md`](docs/progress.md).

## What each jury can click or see

| Challenge | What we show | Proof |
|---|---|---|
| **Aalto**<br>Beyond the Clinic | Sense, respond, learn: four signal groups against her own usual, a fixed consensus, a practitioner page, a learner that favours what she responded to. | [The public dashboard](https://harrish21raj--kaiku-web.us-east.modal.run/?id=aino) · calibration in [`docs/validation.md`](docs/validation.md) |
| **Gemini API** | Gemini Live is Kaiku's one voice on phone, Mac, glasses and robot, with tool calls that move a ritual and a walk. Short-lived tokens, TTS, embeddings. | Real Live call with injected speech and a picture; the Talk tab in the app |
| **Gemma** | Gemma 4 chooses evidence and words the review; code validates each finding and renders every number. | [Dashboard](https://harrish21raj--kaiku-web.us-east.modal.run/?id=aino) → Kaiku's review → Agent trace (10 steps) |
| **Modal** | API, dashboard and database served from one deployed app; scheduled analytics; a parallel simulation of synthetic people; a scale-to-zero GPU class for Gemma. | [The demo URL](https://harrish21raj--kaiku-web.us-east.modal.run/?id=aino) on slide 1 · one cold Gemma call on a Modal H100 (default stays the hosted API) |
| **Meta**<br>AI glasses | Audio-first walk companion through the Device Access Toolkit; opt-in seeing; the walk survives the glasses coming off. | Registration on real Gen 2 · You → Glasses check self-test · real walk pending |
| **Atech**<br>Real World | The robot's head on one 14-port board with eight modules, linked to the hub over MQTT. | [`firmware/atech-head`](firmware/atech-head/AGENTS.md) compiles; microphone and LED grid on the board · live loop pending |

As on slide 10 of the [deck](demo/deck/kaiku-deck.pdf). Since the deck was rendered, the head has also run the
ritual on the board with its standalone firmware (see [Robot](#robot)); the live loop to the dashboard is still pending.

## Safety and privacy

- **The crisis path is deterministic and contacts nobody.** A fixed phrase list, PHQ-9 item 9 or a long press on the robot's button shows a pre-written message with the MIELI Crisis Helpline 09 2525 0111 and 112 and sets "Safety" on the dashboard. It will miss indirect language. [`docs/safety.md`](docs/safety.md)
- **No raw media is stored.** Only derived numbers reach the record and the cloud rejects anything else. Audio goes to Gemini Live only during a conversation she started; Google can keep Live session state for up to 24 hours. [`docs/privacy.md`](docs/privacy.md)
- **The glasses-frames rule (D43).** Off by default. Frames may go to that walk's Gemini Live conversation and nowhere else; no state, observation or crisis trigger comes from a picture, and people in view are never described. [`docs/decisions.md`](docs/decisions.md)
- **Consent per signal.** One switch per signal, pausable, listed in "What Kaiku saw today". Conversation text is kept only after a separate opt-in, and practitioners never see conversations or the notebook.
- **A research prototype.** Not a medical device, not a crisis service, and no replacement for clinicians. It reports a change from a person's usual; a practitioner decides what that means.

## Repo map

Every module has one doc, its `AGENTS.md`. New here? Read the root [`AGENTS.md`](AGENTS.md) first.

| Module | What it is |
|---|---|
| [`contracts/`](contracts/AGENTS.md) | Message envelope, payloads, topics, API models, signal-group map: the only shared package |
| [`hub/`](hub/AGENTS.md) | Robot orchestrator: perception, ritual state machine, safety gate, Gemini Live adapter, uplink |
| [`cloud/`](cloud/AGENTS.md) | Modal app: ingest, SQLite, baselines, verdicts, consensus, learner, Gemma review and graph, simulation, web hosting |
| [`apps/web/`](apps/web/AGENTS.md) | Next.js practitioner dashboard |
| [`apps/apple/`](apps/apple/AGENTS.md) | SwiftUI iPhone and Mac apps: Today, Play, Talk, Your days, You; the glasses walk |
| [`apps/glasses-webapp/`](apps/glasses-webapp/AGENTS.md) | Instructions only for a glasses display web app; not part of the entry |
| [`apps/glasses-dat-android/`](apps/glasses-dat-android/AGENTS.md) | Instructions only for an optional Android camera app; not part of the entry |
| [`firmware/atech-head/`](firmware/atech-head/AGENTS.md) | Atech board: screen eyes, knob ear dial, chest LEDs, neck motor, speaker |
| [`firmware/unoq-sensors/`](firmware/unoq-sensors/AGENTS.md) | Arduino UNO Q: knock drum, camera (faces, distance), buzzer chimes, pulse sensor |
| [`firmware/friendlink/`](firmware/friendlink/AGENTS.md) | LoRa friend lamp, a stretch idea; not in the demo |
| [`sim/`](sim/AGENTS.md) | Software twins of every hardware node, synthetic people, cloud seeder |
| [`tools/`](tools/AGENTS.md) | Bus tail, record and replay, doctor, sync checkers, companion evals |
| [`config/`](config/AGENTS.md) | `criteria.toml` (the rule), `kaiku.toml` (settings), persona, voice lines, safety phrases |
| [`design/`](design/AGENTS.md) | Look ground truth: tokens, mascot spec and generated assets, motion |
| [`hardware/`](hardware/AGENTS.md) | CAD with provenance, wiring, bill of materials |
| [`demo/`](demo/AGENTS.md) | Table demo checklist, video shot list, deck, reset script |
| [`docs/`](docs/AGENTS.md) | Progress log, decisions, safety, privacy, tracks, validation, submission text |

## Team and licence

Built at Junction 2026 (Espoo, 13 to 15 November 2026) by **Harrish, Edwin and Xavier**.

[MIT](LICENSE). All code was written during the event. Third-party services, models and hardware keep their own
terms ([Gemini API](https://ai.google.dev/gemini-api/terms), [Gemma](https://ai.google.dev/gemma/terms), Modal,
the Meta Wearables platform, Atech). CAD provenance: [`hardware/AGENTS.md`](hardware/AGENTS.md).
