# demo — AGENTS.md

> Read the root `AGENTS.md` first. Owner D.

- The story, video script and wording live in `docs/demo-narrative.md` (one source). `demo_script.md` is the
  presenter's table checklist and `video_shotlist.md` the recording checklist; neither repeats the narrative.
- `make demo` (`scripts/demo.sh`): starts what is not running (broker, local API with the built dashboard), seeds
  Aino's sixteen-day record through the real routes (`cloud/kaiku_cloud/jobs/single_person.py`), prints the links.
  Idempotent; `KAIKU_DEMO_PORT`, `KAIKU_DEMO_MQTT_PORT`, `KAIKU_DB_PATH`, `KAIKU_DEMO_ONCE=1`.
- `make demo-reset` (`reset.sh`): clears the hub queue, drops simulated data on that API and seeds again so the
  record ends yesterday (< 30 s). Live recordings stay.
- `make live-day` (`scripts/live_day.py`): a good and a rough day on a throwaway copy, read back through the
  practitioner API; `ARGS="--url ... --kind good|rough"` posts one to a running local API.
- Rule: the demo only shows what runs. Claims are checked against `docs/track-readiness.md` §5.

## Recordings (gitignored: `demo/recordings/`)
No keys, no paid calls (`KAIKU_NO_DOTENV=1`, template LLM, text voice), with one exception: the three iPhone
conversation takes (below), which need the real model. The robot and web scripts start their own broker/cloud on
free ports with a temp DB, so they run beside other dev servers.
- `scripts/record_robot_demo.sh [OUT]` (default `demo/recordings/robot-sim`, ~3 min): broker :18832 + cloud :18010 +
  `seed_demo --reset` + head/sensors twins driven by `scripts/robot_demo_driver.py` (walk up → greeting → button dial
  ×3 → breathe → knock drum → suggestion → goodbye → leave; then glasses walk, laptop session, Mac hour, phone
  morning) + hub. Writes `bus.jsonl` (`tools/record.py`), `hub.log` (epoch-stamped), `markers.jsonl`, `cloud/*.json`
  (`/v1/me`, consensus, patients, constellation, memories, intelligence, companion session, one `ask_mind`).
- `scripts/record_web_demo.py --url <dashboard URL>` (Playwright video, ~100 s → `web-dashboard.mp4`, `-sheet.png`,
  `-steps.txt`): the one-viewport practitioner dashboard for one person (`--person`, default `aino`): default view,
  the Trends chart read day by day, Kaiku's review and agent trace, the knowledge graph maximised with a node
  picked, a day opened in the Daily account, a panel collapsed and one moved. Read-only unless `--allow-model`:
  writes are blocked and the insight is requested with `generate=false`, so it is safe against a service someone
  else is using. Controls are found by role or accessible name; a missing one prints `SKIP` and the take goes on.
  `scripts/record_web_demo.sh [OUT]` runs it against its own throwaway cloud seeded with the one person.
- `apps/apple/scripts/record_app_demo.sh ios|mac|mac-snap|post` (`apps/apple/AGENTS.md` → Recording a demo; the
  script's header and the top of `apps/apple/iOSUITests/DemoTourTests.swift` are current where that section is
  not): the iPhone flows as clips with chapter time codes; Mac video needs screen permission, `mac-snap` gives
  stills. `TESTS=method:clip`, `FRESH=1` (a new install: today's path at 0 of 4), `CLIPS=` (post only these).
  - **Conversation takes are typed and answered by the real model.** `testB_TodayPath` (Kaiku's invitation on
    Today → the check-in chat on an ordinary day → the suggestion → Lantern → the rotating game),
    `testD_Talk` (Talk as a call: two typed lines, Kaiku muted for one answer, the phone locked, her last line
    answered on the Lock Screen's bar, "End" there) and the extra `testH_CheckInHardDay` (a hard day, the lock at
    the end) type the person's lines through the Debug arguments `-kaikuTalkSay…` and show whatever Gemini Live
    answers. They need a private service with the key, its own record and its own ledger
    (`KAIKU_DB_PATH`, `KAIKU_SPEND_DB`, `KAIKU_BUDGET_TOTAL_USD`; seed it before it gets the key so the seeding
    jobs call no model): one Live session per take, about $0.12 to $0.24 each (2026-11-14). The recorder revokes
    the app's microphone and camera permission before every such take: the simulator's microphone is the Mac's.
  - On a service without a key the same flows are free and fall back to what a person would do there (the three
    dials; the one line of a Talk that cannot start).
  - `TEST_RUNNER_KAIKU_DEMO_ARGS="-kaikuTalkDemo live"` runs a flow on the scripted Live: for checking the taps
    and answering the simulator's "Allow Live Activities?" prompt before a real take. Its lines are hand-written
    layout text: never a clip, a GIF or a piece of the cut.
- `scripts/record_flow.py` (`uv run --with playwright python scripts/record_flow.py`, about 10 min, needs ffmpeg
  and gifsicle; no model, cloud or key): steps `docs/explainers/intelligence-flow.html` frame by frame, two takes
  at 1920×1080 (`--only video|fast` for one of them). The full take, at reading pace →
  `recordings/intelligence-flow.mp4` (seven scenes and the model table, about 4 min 10 s), `-steps.txt` (time code
  of every scene and hop), `-sheet.png` and `docs/media/intelligence-flow.gif` (scene 1, under 3 MB). The fast
  take (the page's own `?pace=fast`, every hop still travelled, about 70 s) → `recordings/intelligence-flow-fast.mp4`,
  `-fast-steps.txt`, `docs/media/intelligence-flow-all.gif` (every scene and hop, then the model table; 960 px,
  under 10 MB) and `-all-sheet.png` (frames of that GIF at every hop: look at it before the GIF ships).
  `--audit` records nothing: it checks that every text fits its box at every size and must be clean first.
- `scripts/record_gifs.py [name ...]` → the README GIFs in `docs/media/` from those clips (pieces listed in the
  script); `scripts/record_voice.py --url <service>` → `recordings/voice/*.wav`, the lines the app plays (cached
  lines are free, a new one is a capped TTS call); `draft_cut.py` (`uv run --with pillow python demo/draft_cut.py`)
  → `recordings/kaiku-draft-cut.mp4`: the pieces in the order of the narrative's shot table with their titles,
  Kaiku's voice where it speaks, and for every shot that still needs filming either its stand-in (a typed
  simulator take, the simulated glasses, the app's own renders: marked on screen) or a 2 s card; each is replaced
  by `recordings/shot-NN-*.mp4` when present. Narration by time code: `draft-cut-narration.md`.
- Which clip covers which shot of the narrative, what still needs a person with the devices and how to record it:
  `video_shotlist.md`.
