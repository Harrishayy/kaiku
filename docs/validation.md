# Validation (Phase 4)

Record sessions with Aalto mentors / testers here. No names without consent — use "Tester 1".

| # | who (role) | what they tried | quote | what we changed |
|---|---|---|---|---|
| 1 | Tester 1 (project lead) | Gen 2 registration through Meta AI | “Registered / connected” | Registration and connection remain separate from audio routing; real microphone/speaker acceptance is still required. |
| 2 | Tester 1 (project lead) | Open Talk on the installed iPhone | “theres no microphone button.” | Fixed the control being hidden until Live had already connected; added labelled start/mute/resume and failure states. |
| 3 | Tester 1 (project lead) | Start phone/glasses voice without a robot | “why do i need to connect to kaiku for voice?” | Separated companion API setup from robot hardware; added API service discovery and stable local demo profiles, removing QR-first setup. |
| 4 | Tester 1 (project lead) | Retry after a development launch command | “not updated on my phone” | A successful device launch is no longer treated as proof of app configuration or networking; final acceptance requires the installed UI and real service requests. |

## Calibration: how well does Kaiku tell "not feeling well" from "ok"? (2026-11-14, `consensus-v1+ef17c3f3`)

> Measured 14 Nov on `ef17c3f3`; the rule file has changed since (the current rule is `consensus-v1+db93b715`) and
> the numbers have not been measured again.

**Short answer.** On people: unknown. Nobody has used Kaiku while unwell, so there is no measured sensitivity or
specificity, and we claim none. What we can measure is how the rule behaves on labelled synthetic courses under
stated assumptions. There it rarely raises a false flag, finds a clear change in most cases within days, misses
most mild changes, and until this pass could say nothing at all about a person's first 16 days.

Reproduce: `make calibrate` (20 s; `N=`, `CRITERIA=`, `COMPARE=`). Code: `cloud/kaiku_cloud/analytics/calibration.py`.
Regression test with bounds: `cloud/tests/test_analytics.py::test_calibration_regression_thresholds`.

### What is simulated
One synthetic series per enabled `[[metric]]` in `config/criteria.toml`, 40 people per course, 60 days (or 16).
- A change is sized in units of the person's own day-to-day spread: mild 1 SD, moderate 2 SD, marked 3 SD.
  Only 70 % of a person's signals respond at all. Published links between phone or wearable signals and
  depressive symptoms are weak to moderate, so "mild" is probably the realistic case and "marked" the rare one.
- People are 0.6–1.6 times as noisy as the criteria's noise floors assume; noise carries over from day to day;
  3 % of readings are outliers; dials are whole numbers; glasses and app data arrive about every second day; half
  the people wear a watch; the PHQ-9 arrives every 14 days and moves about 3 points per SD.
- "Flag" = at least one signal group is worse (state watch or needs a call: worth a check-in).
  "Call" = two groups agree (needs a call). A change counts as found if flagged within 21 days of its start.

### Measured (40 synthetic people per row)
| people who are fine | false flags per person-week | false "needs a call" per person-week | fine days without a flag |
|---|---|---|---|
| stable | 0.04 | 0.00 | 97 % |
| noisy but fine | 0.10 | 0.00 | 95 % |
| weekday/weekend pattern | 0.07 | 0.00 | 97 % |
| one broken sensor | 0.11 | 0.00 | 92 % |
| one source goes silent | 0.07 | 0.01 | 93 % |

Mean 0.08 false flags per person-week: about one unneeded "worth a check-in" per person every three months.
A fine person has a 15 % chance of some flag in any 3-week window; flag sensitivity below has to be read against that.

| people who are not feeling well | size | flagged | needs a call | days to flag | days to call |
|---|---|---|---|---|---|
| gradual decline over 14 days | mild / moderate / marked | 78 / 100 / 100 % | 20 / 90 / 97 % | 12 / 7.5 / 6 | 13 / 13 / 10 |
| sudden drop that stays | mild / moderate / marked | 93 / 100 / 100 % | 33 / 85 / 97 % | 5 / 2 / 2 | 7 / 4 / 3 |
| short dip (4 days) | mild / moderate / marked | 38 / 88 / 95 % | 3 / 50 / 65 % | 3 / 2 / 2 | 3 / 3 / 2 |
| decline with fewer check-ins | mild / moderate / marked | 57 / 95 / 100 % | 10 / 53 / 82 % | 12 / 10 / 8 | 12 / 13 / 11 |
| drop, then recovery | mild / moderate / marked | 62 / 100 / 100 % | 33 / 75 / 90 % | 4 / 2 / 2 | 6 / 5 / 3 |
| drop without a questionnaire | mild / moderate / marked | 72 / 93 / 97 % | 23 / 57 / 70 % | 4 / 2 / 2 | 7 / 3 / 3 |

Averages: flagged 68 / 96 / 99 %, needs a call 21 / 71 / 86 % (mild / moderate / marked).
After a recovery the flag clears in a median of 4–5 days (the 3-of-5-days rule has to run out).

### A new person: days 3, 7, 10, 14, 16 (the demo point)
The audit finding was correct. The baseline needed 7 days and ended 7 days before the scored day, and a signal
needs 3 scored days, so **no signal group could give any verdict before day 17**. At day 16 the rule had never
scored anything; a dip on days 9–12 was invisible to it (15 % "found", all through the PHQ-9 alone).

What a practitioner sees now (40 synthetic people, moderate dip on days 9–12):

| day | person is fine | dip on days 9–12 |
|---|---|---|
| 3, 7 | "not enough data" for everyone | same |
| 10 | "not enough data" | 3 of 40 flagged |
| 12 | "not enough data" | 22 of 40 flagged |
| 14 | 1 of 40 flagged, others "not enough data" | 22 of 40 flagged |
| 16 | "not enough data" for everyone | 9 of 40 still flagged (recovering) |

Found by day 16: 15 % before, 57 % now (marked dip 83 %, mild 15 %); a drop that stays low from day 9:
55 % before, 95 % now. False flags in the first 16 days of a fine person: 0.01–0.02 per person-week.
A record is never "stable" before day 21.

**The rule for young records (both in `config/criteria.toml`):**
1. Days 1–8: nothing is compared. State watch, shown as "not enough data".
2. From day 9 a signal is compared with a provisional baseline: at least 5 days of data, ending 3 days before the
   scored day (`early_baseline_min_days = 5`, `early_baseline_lag_days = 3`). The usual 3-of-the-last-5-days
   persistence applies, so the first possible flag is day 11. Evidence lines say "(early baseline: N days, lower
   confidence)".
3. From day 15 the full baseline takes over signal by signal (7+ days, ending 7 days before the scored day).
4. Until day 21 a record can be flagged but never reads "stable" (`min_history_days_for_stable = 21`).

We tested wider thresholds for the early period and did not adopt them: the measured false-flag rate in the first
16 days is already lower than later on, and wider thresholds only cost sensitivity. `early_baseline_min_days = 0`
switches the provisional baseline off.

### What is weak, and what we cannot claim
- **No clinical validation.** The generator is ours. The numbers describe the rule, not people.
- **Noise floors were set from our own simulator.** Each `min_mad` equals the noise the earlier `make tune`
  generator uses, and that generator moves signals by 4–5 SD. `make tune` therefore reports near-perfect scores;
  it tests plumbing, not calibration. No threshold has an empirical basis in real day-to-day data yet.
- **Mild change is mostly missed** at the "needs a call" level (21 %), and short dips need three low days to count.
- **A bad first fortnight becomes "usual".** Someone who starts unwell is compared with that; only the absolute
  PHQ-9 ≥ 10 rule can see it. After TMS the first weeks are not a settled usual. The provisional baseline is
  weaker still: 5 days.
- **Skipping check-ins hides a decline.** Missing data is "insufficient", never "worse". With fewer check-ins,
  needs-a-call sensitivity falls from 90 % to 53 % and takes 10–13 days. Withdrawal is itself a sign; the rule
  does not use it.
- **The PHQ-9 carries a lot.** Without it, needs-a-call sensitivity for a moderate drop falls from 85 % to 57 %.
  The two "worse" groups can both be self-report (dial + questionnaire); the dashboard shows that caveat.
- **Walks group flips on one signal** (`outing_min`). A phone left at home reads as fewer outings.
  A broken sensor costs about 0.11 false flags per person-week and stays flagged until someone looks.
- **Weekday patterns** are not modelled in the baseline (median of 14 days). Measured cost is small (0.07).
- **Partial days** count as full days: a half-captured day enters the baseline like any other.
- **Every added signal adds chances for a false flag**, because a group turns worse on a fixed weight sum.
- **The learner ("what helps") is confounded.** Its next-day score is measured against a fixed neutral 3, not
  against the day the activity was offered. Two activities with no effect, one offered on low days and one on
  good days, score 0.52 and 0.73. It ranks what coincides with good days. Do not present it as what works.
- Simulated (`sim: true`) and real observations are scored by the same rule and can mix in one baseline; the
  dashboard labels simulated records, the rule does not separate them.

### Design choices and where they come from (inspired by, not validated against)
- Personal baseline with median and MAD (x 1.4826) rather than mean and SD: robust to a few odd days
  (Leys et al., 2013, J Exp Soc Psychol). Threshold 1.5 robust SD on 3 of the last 5 days with data. We tested
  2 of 3 days: false flags rose from 0.06 to 0.16 per person-week, so we kept 3 of 5. Raising the threshold to
  2.0 halved false flags but cut mild-change detection from 67 % to 44 %; kept 1.5.
- PHQ-9 rise of 5 points as a direct trigger: the commonly used minimal clinically important change
  (Löwe et al., 2004, Med Care); PHQ-9 ≥ 10 is the standard cut-off (Kroenke, Spitzer, Williams, 2001).
- Signals: sleep timing and duration, activity and outings, phone/computer use, speech rate and pauses, reaction
  time. These follow digital-phenotyping work (Saeb et al., 2015, JMIR; Rohani et al., 2018, JMIR mHealth,
  review; Cummins et al., 2015, Speech Communication; Buyukdura et al., 2011, on psychomotor slowing). That
  literature reports weak to moderate group-level associations. It does not show that these signals detect a
  change in one person.

### Adding a signal (games, robot sensors)
1. Contracts first (root rule 4): the obs field must exist, or `make criteria` rejects the block by name.
2. Add the `[[metric]]` with `weight = 0`. It is charted and its drift is computed, but it never votes and cannot
   make its group look "sufficient". A block with no data yet changes no verdict (tested).
3. Set `min_mad` from real recordings of day-to-day spread, not from a guess. Practice effects (reaction time
   improves for weeks) will read as "better" and then as a false "worse" when they level off: use a longer
   `baseline_days` or keep the weight at 0 until the curve is flat.
4. Give it weight 0.5, run `make calibrate COMPARE=config/criteria.toml`, and keep it only if false flags per
   person-week did not rise.

### How to talk about calibration in the demo
"Kaiku compares each person with their own usual, signal by signal, and only speaks up when a change holds for
three of five days; two signal groups must agree before it says 'needs a call'. We have not tested it on
patients, so we do not quote an accuracy. In our own simulation, with assumptions we publish, it raises about one
unneeded check-in per person every three months, finds a clear change in about two days and a slow slide in about
a week, and misses most mild changes. In the first eight days it says 'not enough data'; from day 11 it can flag a
change against an early baseline and labels it as lower confidence; it never says 'stable' before three weeks.
The thresholds come from simulation and the research literature, and the next step is to set them from real
recordings with a clinical partner."


## Games

The lead's question: *are the games too simple, should they indicate more, and do they have to be short?*
Short answer: **keep them short, make them proper tasks, play them often, and read them only against the person's
own usual.** Everything below is "inspired by research". None of these games is a validated test, none is
diagnostic, and no number from them is ever shown to the person.

### What the first four games really measured (blunt)

| game | what it claimed | what it measured | fed the consensus? |
|---|---|---|---|
| Breathe | — | nothing (duration). It is something to do, not a reading. Keep it as that. | no |
| Firefly | go/no-go reaction time | reaction + **finding the firefly + moving the finger or mouse to it**: targets appear at random places, up to three at once, and fade in over 0.3 s, so the "reaction time" is mostly search and travel, and differs between touch, mouse and Space (Space catches the oldest firefly, skipping the no-go decision). About ten moths a game is too few to count wrong taps. No practice, no balance, no validity check. | yes: `firefly_reaction` (0.5), the most confounded number we had |
| Pebble path | spatial span (Corsi-style) | a real paradigm with a staircase, but one path per length and "two misses anywhere ends it", so a session's span is good to about ± 1 pebble | no |
| Tell Kaiku | speech rate, pauses | 30 s of free talk: the numbers depend on what was said; pitch was never computed | no |

So only one game number reached the consensus, and it was the weakest one. Firefly stays as free play (it is the
most fun); it is no longer in Today's path. Pebble path now reports its rounds and joins the rotation.

### Short or long?

Short. The evidence for brief, repeated tasks is better than for one long sitting:

- Perzl, Riedl & Thomas (2024, *Assessment* 31(6):1270–1291, [doi](https://doi.org/10.1177/10731911231213845)):
  46 adults, one test a day for two weeks on their phones. Reliable and valid state measures needed only a
  **30-second** reaction-time test (PVT) and **90 seconds** of digit–symbol substitution.
- Sliwinski et al. (2018, *Assessment* 25(1):14–30, [PubMed](https://pubmed.ncbi.nlm.nih.gov/27084835/)): brief
  smartphone tests in daily life, 219 adults. Averages over many sessions were very reliable between people
  (≥ 0.97); a single occasion much less so (0.41–0.53 of reliable within-person variation). **One session is
  noise; a run of days is a signal** — which is exactly how `config/criteria.toml` reads a metric (3 of 5 days
  beyond the person's own 14-day baseline).
- Basner, Mollicone & Dinges (2011, *Acta Astronautica*, [PMC3197786](https://pmc.ncbi.nlm.nih.gov/articles/PMC3197786)):
  a 3-minute reaction-time test with 1–4 s waits tracked the 10-minute original; response speed (1/RT) was the
  most sensitive outcome; answers under 100 ms are false starts. (Shown for sleep loss, not for depression.)
- Practice effects are real: Paolillo et al. (2024, *JMIR* 26:e51978, [link](https://www.jmir.org/2024/1/e51978/))
  saw people get better on four of eight phone tests over five sessions, and scores differed by phone model.

Long sessions (THINC-it needs 10–15 minutes: McIntyre et al. 2017, *J Clin Psychiatry* 78(7):873–881,
[link](https://www.psychiatrist.com/jcp/thinc-it-validation-for-mdd)) fit a clinic visit, not a daily habit for
someone whose energy is low. So: about 90 seconds a game, two games a day, the same reaction game daily.

Why the person's own baseline and not norms: phones add tens of milliseconds that differ by model, a mouse is
not a finger, and age and habit move these numbers far more between people than mood moves them within one
person. There are no norms for our versions anyway. A change from *your* usual is the only honest reading.

### Which tasks, and what we built

| task family | evidence in depression | built? |
|---|---|---|
| Simple reaction time / vigilance (PVT) | slowing and variability go with low mood, poor sleep and fatigue; the best-studied brief repeatable task (above) | **Lantern**: one lantern, a wait of 1.5–4 s nobody can predict (each wait equally often), touch when the flame appears. 3 practice + 24 lights ≈ 90 s. Sends median, IQR, CV, response speed, lapses (≥ 500 ms or missed), early taps. Daily. |
| Digit–symbol substitution | sensitive to change in many conditions including depression, but not specific to one function (Jaeger 2018, *J Clin Psychopharmacol*, [PMC6291255](https://pmc.ncbi.nlm.nih.gov/articles/PMC6291255/)) | **Seed shelf**: nine seed marks ↔ pots 1–9, a new pairing every session (so the key cannot be learned by heart), each mark equally often, 4 practice + 90 s. Sends right answers per minute, accuracy, time per answer. |
| Spatial span | working memory is among the functions affected | **Pebble path** (kept): now also sends rounds, input and validity. |
| Effort for reward (motivation, anhedonia) | people with depression chose the harder, better-paid option less often (Treadway et al. 2012, *J Abnorm Psychol*, [PMC3730492](https://pmc.ncbi.nlm.nih.gov/articles/PMC3730492)) | **Watering**: easy plant (4 taps, 1 flower) or hard plant (a 2.5 s or 5 s watering at the person's own tapping pace, 2–5 flowers); 8 rounds, every reward × both efforts, sides balanced. Sends share of hard choices and tapping pace. |
| Emotional bias (faces, words) | early change in a face-based bias task went with later response to medication (Browning et al. 2019, *Eur Neuropsychopharmacol* 29(1):66–75, [doi](https://doi.org/10.1016/j.euroneuro.2018.11.1102)) | **Not built, on purpose.** It needs validated face or word sets in Finnish, Swedish and English, and it would show sad or hostile material every day to someone recovering. The right next step with a clinical partner, not a hackathon wrapper. |
| Go/no-go, Stroop, n-back | used in batteries; need more trials than 90 s gives for a stable error rate | not built (Firefly stays as play) |
| Speech features, mood check-ins | covered by Tell Kaiku / Talk and the weather check | unchanged |

How they are wrapped so they don't feel like a test: Kaiku's world (a lantern at night that fills the sky with
stars, a seed shelf that grows sprouts, a flower bed), practice inside the game, a wrong answer only wobbles, and
the end shows what grew — never a time, a count or "slow". Today's path = weather check → Kaiku's suggestion →
Lantern → one of seed shelf / pebble path / watering in turn: about three minutes of games.

### How the numbers are used (and guarded)

- Each session is one `obs.play_session` with the summary, the trial count, the valid count, how it was answered
  (touch / pointer / keyboard), the device, and the per-trial record (`rt_ms` + `trial_codes`); full trial detail
  stays in a file on the device.
- The first three sessions of a game on a device are **warm-up** and never count. A doubtful session (too few
  usable trials, many early taps, mashing, app left mid-game) is sent with quality 0.2 and skipped.
- Metrics (`lantern_speed`, `lantern_variability`, `seeds_throughput`, `pebble_span`, `watering_effort`) count
  toward the Apps group with low weights, a stricter threshold (z 2.0), at least five baseline days, and never
  toward "better" (getting better at a game is practice). One game alone cannot change the Apps verdict.

### Limits (do not over-claim)

- Not validated: no study has compared these versions with the original tasks, in anyone, let alone after TMS.
- The reaction-time evidence is mostly from sleep loss and healthy adults; in depression the link is real on
  average but modest, and slowing also comes from a bad night, a cold, medication, or a new phone.
- Watering pays in flowers, not money, and has 8 choices where the original task has dozens: a coarse signal
  (steps of one eighth). It has the lowest weight for that reason.
- Phone and Mac timing differs; a person who switches device or from finger to keyboard will shift. The input is
  recorded but not corrected for.
- Meta-analyses of sham-controlled TMS trials report mixed or no clear change in thinking tests from the
  treatment itself (Mutz & Kiebs 2023, *European Psychiatry*; Fu et al. 2025, *J Affect Disord* — read from
  their abstracts only), so a change in a game says something about the day or the week, not about TMS "working".
- Sources above were checked from abstracts or open full text on 2026-11-14; effect sizes were not re-derived.
- A game result alone never raises "needs a call", and no game ever handles safety.

### Tap it back (the robot's rhythm game, D51)

The robot plays a short song at a set tempo, goes quiet, and she taps the beat back from memory; three levels a
day (about 100 bpm, clearly faster, then slow with more taps). It is **inspired by research on timing**: hearing
a beat and then keeping it going without it is the "synchronise, then continue" tapping task used in laboratory
work on timing (Wing & Kristofferson 1973; reviewed in Repp 2005, *Psychonomic Bulletin & Review*; named from
memory, not re-read on 2026-11-14). **It is not that task and not a validated test.**

- What is measured: the median gap between her taps as a tempo, its distance from the song's tempo in percent,
  and how even the gaps were. The laboratory task uses a metronome, dozens of taps and millisecond timing; ours
  uses a generated song, 8 to 12 taps, and tap times from a knock switch or a motion sensor sent over Wi-Fi.
- What it is for: something pleasant to do with the robot that ends on a warm word. The bands (perfect, great,
  nice) are our own cut-offs (4 %, 8 %, 15 %), chosen to feel fair, not taken from any study.
- How it is used: shown to the person in History as numbers. **Not scored**: no metric reads it, it moves no
  verdict, and it is kept apart from free drumming, whose tempo is her own (D51).
- Shown so far: the game end to end with the real music model through a simulated head (bands as tapped: 1.5 %,
  6.9 %, 22 % then 3.1 %). Not shown: a person playing it, the real speaker and tap sensors, whether people can
  hear the tempo of a generated song in 8 seconds, or whether anyone enjoys it.

## Face signs (camera during activities, D52)
With the person's opt-in, the phone or Mac counts movements of the face while a game or the check-in chat runs
(`obs.face_signs`). Nothing here is validated. This section says what the idea is inspired by, what we chose
because of it, and what we cannot claim.

### What the research says (read from abstracts and summaries on 2026-11-14, not re-derived)
- **Less facial movement went with higher symptom severity, in clinical interviews.** In adults followed during
  treatment for depression, sessions with higher severity had fewer affiliative facial actions (action units 12
  and 15; AU 12 is the smile), more of a non-affiliative one (AU 14) and smaller, slower head movement, in both
  manual and automatic coding (Girard, Cohn, Mahoor, Mavadati, Hammal & Rosenwald 2014, *Image and Vision
  Computing* 32(10):641–647, [doi](https://doi.org/10.1016/j.imavis.2013.12.007)). An earlier study from the
  same group reported moderate concurrent validity with depression for facial actions and for vocal prosody
  (Cohn et al. 2009, *ACII 2009*, [doi](https://doi.org/10.1109/ACII.2009.5349358)). Both used recorded
  clinical interviews, not a game on a phone.
- **A face does not show what a person feels.** A review of the evidence found that facial movements are not
  reliably diagnostic of emotional states: the same movement goes with different feelings, and the same feeling
  with different movements, across people and situations (Barrett, Adolphs, Marsella, Martinez & Pollak 2019,
  *Psychological Science in the Public Interest* 20(1):1–68, [doi](https://doi.org/10.1177/1529100619832930)).
- **Blink rate** rose with time on task in studies of fatigue, and also depends on what the task asks of the
  eyes (Stern, Boyer & Schroeder 1994, "Blink rate: a possible measure of fatigue", *Human Factors* 36(2)). We
  found no source we could check for blink rate and low mood, so none is cited and the blink metric would not
  vote even if the others did.

### What we built because of it
| Choice | Why |
|---|---|
| Counts of movement (`smile_share`, `expression_range`, `blinks_per_min`, …), never an emotion label | Barrett et al. 2019; the contract has no field for a label and the review rejects one |
| Compared only with the same person's own earlier sessions, on the same method and the same kind of task | Girard et al. followed the same people across sessions; ARKit blendshapes and Vision landmarks are different instruments; a talking face moves for that reason |
| Shown and citable, not scored | the evidence is from interviews, not games; there are no recordings of day-to-day spread, so every spread floor is argued, not measured |
| A reading needs one usable face in 60 % of the frames, 20 s of sampling, and half the frames its method takes in 20 s (300 at the phone's 30 looks a second, 150 at the landmark method's 15) | a thin capture is missing evidence, not a low number |
| A livelier face than usual is never read as "better" | the face is not a wellbeing meter |
| Apple's on-device face tracking, no model of our own | no weights to ship or audit, explainable coefficients; an emotion classifier (and a YOLO-family model under AGPL-3.0 in an MIT repository) was the alternative we decided against |

### What we cannot claim
- That any of these counts says something about how a person is, in this setting or any other. Not tried.
- That a game on a phone brings out the movements a clinical interview does. A person concentrating on a screen
  smiles little on any day.
- That the numbers are stable: lighting, glasses, a beard, the angle of the phone and the device's own tracking
  all move them. Head movement has no fixed scale across methods and gets no usual.
- Real captures. The record that shows them is authored and labelled SIMULATED; its quiet days were written in.
- Before a face metric may vote: recordings of real spread per method, a floor re-set from them, and a check
  against a scored outcome. Until then it is a line on a chart that a practitioner may ask about.

## More of the day from Apple Health (D53)
`obs.wearable_daily` now also carries the day's walking and running distance, time in daylight, the average
walking heart rate, the minutes of deep, REM and core sleep, and the minutes awake in the night. Nothing here is
validated. Six of them are measures that are shown beside the record and do not vote (`role = "shown"`); core
sleep is stored and listed in History only.

### What the research says (read from abstracts and summaries on 2026-11-14, not re-derived)
- **Daylight.** In a cross-sectional analysis of 86,772 adults who wore a light sensor for a week, more light in
  the daytime went with a lower risk of major depressive disorder, and more light at night with a higher one
  (Burns et al. 2023, *Nature Mental Health* 1:853–862, [doi](https://doi.org/10.1038/s44220-023-00135-8)).
  Cross-sectional: it cannot say which way the link runs, and a person who is low may simply go out less. The
  watch's "time in daylight" is Apple's own estimate; we found no public description of how it is computed.
- **Sleep stages and waking in the night.** A meta-analysis of sleep-laboratory studies found disturbed sleep
  continuity in most mental disorders, and changes in sleep depth and REM sleep in affective disorders among
  others (Baglioni et al. 2016, *Psychological Bulletin* 142:969–990,
  [doi](https://doi.org/10.1037/bul0000053)). That is polysomnography in a laboratory, between groups of people.
  A watch estimates stages from its own sensors: Apple's own paper ("Estimating Sleep Stages from Apple
  Watch") compares its four states (awake, core, deep, REM) with polysomnography; we did not read its accuracy
  tables and quote no figure.
- **Distance walked and walking heart rate.** Distance is the same walking the step count already measures,
  reported in kilometres; we did not look for separate evidence and cite none. We found no source we could
  check for the average walking heart rate and low mood, so none is cited.
- **No sleep score.** Apple shows a sleep score in its own apps and gives other apps no type to read it
  (`HealthSync.swift` reads sleep analysis samples only). Kaiku sends the stages and the time awake and does not
  compute a score of its own: a single number would hide which part of the night changed, and nobody here could
  check it.

### What we built because of it
| Choice | Why |
|---|---|
| Shown and citable, not scored | the evidence is between groups, in laboratories or with research-grade sensors; none of it is about one person's watch from day to day |
| Compared only with the same person's own earlier days | a watch's stage estimate has its own bias; the same watch on the same wrist is at least the same instrument |
| Spread floors are argued, not measured (0.4 km, 10 min of daylight, 3 bpm, 10 / 12 / 8 min of deep sleep, REM and time awake) | no recordings of real day-to-day spread; each floor only stops an unusually even fortnight from turning a small difference into a large one |
| Less REM sleep is charted as "below usual" and carries no weight | the sleep-laboratory literature on low mood describes more REM pressure, not fewer REM minutes (Baglioni et al. 2016), and a watch's nightly REM minutes are not that measure; the direction on the chart is a convention, not a claim |
| More daylight, more distance, more deep sleep than usual is never read as "better" | these are not wellbeing meters |
| The five watch measures that vote are untouched | the rule version stays `consensus-v1+db93b715`; a verdict is the same with and without the new fields (tested) |

### What we cannot claim
- That any of these numbers says something about how a person is. Not tried.
- That a watch's deep or REM minutes equal a sleep laboratory's. They are estimates, and they are absent on any
  night the watch was not worn or did not stage.
- That "time in daylight" measures the light that matters for mood. We do not know how the watch decides it,
  so we do not know what it misses (a covered wrist in a Finnish November, for one, is untested).
- Real data. The record that shows them is authored and labelled SIMULATED; its harder days were written in.
- Before one of them may vote: real spread per person, floors re-set from it, and a check against a scored
  outcome.
