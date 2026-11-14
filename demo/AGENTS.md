# demo — AGENTS.md

> Read the root `AGENTS.md` first. Owner D.

- `demo_script.md` — live table demo (ground truth for what we show and say; wording rules in root AGENTS.md).
- `video_shotlist.md` — ≤ 2:00 video plan.
- `reset.sh` — resets demo state in < 30 s against `KAIKU_CLOUD_URL` (clears hub queue, `seed_demo --reset`).
- Rule: the demo only shows what runs. Before FINAL, compare `docs/submission.md` against what works and soften
  anything that doesn't (handoff §15).

## Recordings (gitignored: `demo/recordings/`)
No keys, no paid calls (`KAIKU_NO_DOTENV=1`, template LLM, text voice). Both scripts start their own broker/cloud on
free ports with a temp DB, so they run beside other dev servers.
- `scripts/record_robot_demo.sh [OUT]` (default `demo/recordings/robot-sim`, ~3 min): broker :18832 + cloud :18010 +
  `seed_demo --reset` + head/sensors twins driven by `scripts/robot_demo_driver.py` (walk up → greeting → button dial
  ×3 → breathe → knock drum → suggestion → goodbye → leave; then glasses walk, laptop session, Mac hour, phone
  morning) + hub. Writes `bus.jsonl` (`tools/record.py`), `hub.log` (epoch-stamped), `markers.jsonl`, `cloud/*.json`
  (`/v1/me`, consensus, patients, constellation, memories, intelligence, companion session, one `ask_mind`).
- `scripts/record_web_demo.sh [OUT] [--only web-me,...]` (~1 min; needs `apps/web/out`, else runs `make web-build`):
  Playwright (pinned 1.58.0) → `web-me.mp4`, `web-clinician.mp4`, `web-patient.mp4`, `web-firefly.mp4` via ffmpeg.
