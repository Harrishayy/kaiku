# Video shot list (hard cap 2:00)

The shot table, timings, narration and per-shot fallbacks are in
[`docs/demo-narrative.md`](../docs/demo-narrative.md) ("The video (1:55)"). Do not copy it here: one source.

Recording checklist:

- `make demo-reset` on the recording day, so the sixteen days end yesterday and today is empty.
- Dashboard shots carry the small caption "simulated record". Never show a home ID or the words used for fixtures.
- Narrate the state that is on screen. The record opens on needs a call (acknowledged); the first flag is on day 11.
- For the "following days" shot, record a real check-in and walk on a linked device, or run
  `make live-day ARGS="--url http://127.0.0.1:8000 --kind good"` and caption it as simulated.
- Export at 1:55 to 1:59. Screen recordings: `scripts/record_web_demo.sh` (see `demo/AGENTS.md`).
