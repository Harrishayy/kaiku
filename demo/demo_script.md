# Live table demo (~3 min, one presenter, robot + laptop + glasses on the table)

Pre-flight (T-10 min): phone hotspot on · `make doctor` all ✅ (incl. per-source last data) · `make demo-reset` ·
dashboard open on `/clinician/` · laptop `/session/` open via the pairing link · robot homed ·
backup: `KAIKU_VOICE=text KAIKU_MUSIC=local KAIKU_LLM=template` ready in a second terminal.

1. **0:00 Problem (20 s):** half of TMS responders lose the effect within a year; when the visits stop, clinicians
   lose their view; one signal is too thin.
2. **0:20 The hospital principle (10 s):** clinicians never judge from one measurement. Neither do we: three
   independent sources.
3. **0:30 Source 1, robot (50 s):** head finds the judge's face; "turn my ear" (mood, energy, sleep); finger on chest
   (breathing glow, HRV); "drum on my head" (music follows, head sways).
4. **1:20 Sources 2 and 3 (20 s):** glasses walk card; 30-second laptop session snippet.
5. **1:40 Consensus (40 s):** the judge's data lands live on the robot card. Switch to Aino (SIMULATED 30 days):
   robot worse + laptop worse, glasses as usual → **Needs a call**, disagreement shown, explanation (Gemma or
   template — say which), PHQ-9 trend; click "flag for booster".
6. **2:20 Proof & path (40 s):** `/eval` numbers (alert precision, lead time, losing one source — synthetic patients);
   pilot with Aalto + a neuromodulation unit; iCBT referral route; tech stack in one sentence.

Fallbacks: no Wi-Fi → everything local (`make cloud-local`, `KAIKU_CLOUD_URL=http://localhost:8000`,
`KAIKU_LLM=template`); voice lag → `KAIKU_VOICE=text`; a node dies → keep going, the consensus shows reduced coverage.
Wording: "change from your usual", "worth a check-in", "needs a call" — never "diagnosis" or "relapse detected".
Q&A prep: handoff §14.2.
