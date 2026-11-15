# docs — AGENTS.md

> Read the root `AGENTS.md` first.

| file | ground truth for | rule |
|---|---|---|
| `progress.md` | what happened, who's blocked | **append-only**, template at top |
| `decisions.md` | decisions + why | add `D<n>` entries; never rewrite history, supersede instead |
| `safety.md` | crisis path + its limits | change only with the safety owner; keep in sync with `config/safety_phrases.toml` |
| `privacy.md` | what data goes where | update whenever a module starts capturing/sending something new |
| `tracks.md` | track → what we show → proof today → where in repo | |
| `stack/` (`INDEX.md`, `gemini.md`, `gemma.md`, `modal.md`, `meta-glasses.md`, `atech.md`, `arduino-uno-q.md`) | one page per partner technology: what we use and how, what ran (dates, numbers), whether it was the right choice, how it joins the others | views written from the code (2026-11-15), not ground truth: facts live in the module `AGENTS.md` files, config and `decisions.md`; change a "what has run" row only after the run is in `progress.md` |
| `track-readiness.md` | dated audit: requirement → status → evidence per track, weak points, unsupported claims | point-in-time; re-run before FINAL, do not copy its facts elsewhere |
| `demo-narrative.md` | the 2:00 video script, 3:00 pitch beats, how to describe each service, judge Q&A | only what runs on recording day; `demo/` follows it |
| `robot-network-handover.md` | robot Wi-Fi/MQTT handover (Atech + UNO Q): what exists, verified vs not, traps | point-in-time (2026-11-14); details live in the module `AGENTS.md` files |
| `validation.md` | tester/mentor feedback | no names without consent |
| `submission.md` | Junction submission text | must match what actually runs before FINAL |
| `explainers/intelligence-flow.html` | interactive explainer of the intelligence layer: which model is called when and through which API, what crosses each gate and what stays behind, measured times | a view, not ground truth: one self-contained file (no build), point-in-time (payloads and timings measured 2026-11-14 on a simulated record, run counts on the page); change a number only after measuring it again; `scripts/record_flow.py` records it → `demo/recordings/intelligence-flow.mp4` and `-fast.mp4`, `media/intelligence-flow.gif` (scene 1), `media/intelligence-flow-all.gif` (every scene, fast); `scripts/record_flow.py --audit` must be clean before a change ships (every text in its box at every size, light and dark, with and without the web fonts); a scene marked `waiting` in the file is wired but hidden until its facts are measured |
| `templates/module/` | new-module `AGENTS.template.md` | named `*.template.md` so agents don't load it as instructions |
