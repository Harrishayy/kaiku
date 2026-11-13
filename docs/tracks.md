# Track mapping

| Track | What we show | Where in repo |
|---|---|---|
| Aalto — Beyond the Clinic (main) | three independent sources → deterministic consensus; 3-min no-typing ritual; immediate + next-day intervention scoring | everything |
| Best Use of Gemini API | Gemini Live voice with function-calling tools; Lyria RealTime music following the drum | `hub/kaiku_hub/live/` |
| Best Use of Gemma | Gemma 4 on Modal explains the consensus from private data (explains only, never decides) | `cloud/kaiku_cloud/llm/` |
| Best Use of Modal | API + web + DB volume + 15-min/nightly cron + GPU Gemma + `.map` consensus simulation (with lose-one-source ablation) on one live URL | `cloud/app.py` |
| Meta AI Glasses | Source 2: audio-first walk companion, consent + permission/error/connectivity handling, WebMCP tools | `apps/glasses-webapp/` |
| Atech Real World | Atech ESP32 head: eyes, IMU taps, ear encoder, pan motor, chest LEDs | `firmware/atech-head/` |
