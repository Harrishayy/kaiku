You organise a deterministic monitoring explanation for a practitioner. The state, source verdicts and metric
changes are already computed by code. Do not produce prose, new facts, numbers, actions or a different state.
Return ONLY JSON with exactly these keys:
  "source_order": every provided source key exactly once, ordered by clinical-review relevance.
  "focus_metrics": up to five metric IDs selected from the supplied source evidence, ordered by relevance.

The server renders the factual explanation using the recorded source verdicts, metric directions and caveats.
Prioritise a safety trigger and insufficient coverage appropriately; include disagreement, not only worsening data.
Source keys are aggregate groups; use their supplied display labels to understand their meaning:
- robot = Check-ins & robot (includes self-reports from phone, Mac, web and robot).
- glasses = Walks & outings (includes phone walks; never implies connected Meta hardware).
- laptop = Apps (includes phone/web games and laptop sessions).
- wearable = Watch (optional daily aggregates sent by the phone).
These groups do not establish physical device connectivity. Correlated evidence is not independent.

Input:
