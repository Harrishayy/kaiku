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
No keys, no paid calls (`KAIKU_NO_DOTENV=1`, template LLM, text voice). Both scripts start their own broker/cloud on
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
- `apps/apple/scripts/record_app_demo.sh ios|mac|mac-snap|post` (`apps/apple/AGENTS.md` → Recording a demo): the
  five iPhone flows as clips with chapter time codes; Mac video needs screen permission, `mac-snap` gives stills.
- Which clip covers which shot of the narrative, what still needs a person with the devices and how to record it:
  `video_shotlist.md`.
