# docs — AGENTS.md

> Read the root `AGENTS.md` first.

| file | ground truth for | rule |
|---|---|---|
| `progress.md` | what happened, who's blocked | **append-only**, template at top |
| `decisions.md` | decisions + why | add `D<n>` entries; never rewrite history, supersede instead |
| `safety.md` | crisis path + its limits | change only with the safety owner; keep in sync with `config/safety_phrases.toml` |
| `privacy.md` | what data goes where | update whenever a module starts capturing/sending something new |
| `tracks.md` | track → what we show → where in repo | |
| `validation.md` | tester/mentor feedback | no names without consent |
| `submission.md` | Junction submission text | must match what actually runs before FINAL |
| `templates/module/` | new-module `AGENTS.template.md` | named `*.template.md` so agents don't load it as instructions |
