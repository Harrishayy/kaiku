# docs — AGENTS.md

> Read the root `AGENTS.md` first.

| file | ground truth for | rule |
|---|---|---|
| `progress.md` | what happened, who's blocked | **append-only**, template at top |
| `decisions.md` | decisions + why | add `D<n>` entries; never rewrite history, supersede instead |
| `safety.md` | crisis path + its limits | change only with the safety owner; keep in sync with `config/safety_phrases.toml` |
| `privacy.md` | what data goes where | update whenever a module starts capturing/sending something new |
| `tracks.md` | track → what we show → proof today → where in repo | |
| `track-readiness.md` | dated audit: requirement → status → evidence per track, weak points, unsupported claims | point-in-time; re-run before FINAL, do not copy its facts elsewhere |
| `demo-narrative.md` | the 2:00 video script, 3:00 pitch beats, how to describe each service, judge Q&A | only what runs on recording day; `demo/` follows it |
| `robot-network-handover.md` | robot Wi-Fi/MQTT handover (Atech + UNO Q): what exists, verified vs not, traps | point-in-time (2026-11-14); details live in the module `AGENTS.md` files |
| `validation.md` | tester/mentor feedback | no names without consent |
| `submission.md` | Junction submission text | must match what actually runs before FINAL |
| `templates/module/` | new-module `AGENTS.template.md` | named `*.template.md` so agents don't load it as instructions |
