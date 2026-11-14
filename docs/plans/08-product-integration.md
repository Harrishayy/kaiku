# Plan 08 Product integration and acceptance

Current working checklist, requested 14 November 2026. This plan supersedes earlier demo priorities where they
conflict. Module instructions and configuration remain the ground truth for implementation.

## Scope guard

The release must support one coherent person journey: connect the service, choose permissions, talk or type,
complete an activity, retain permitted observations, and review meaningful evidence in the practitioner view.
A successful build or synthetic fixture is not physical-device acceptance. Missing capture stays missing.

## Experience

- [x] English-only native UI, session context and greetings; preserve multilingual crisis matching.
- [x] Compact microphone beside the composer, small avatar and usable message scrollback.
- [x] Accessible saved conversations with loading, empty, error and deletion states.
- [x] Setup readiness and explicit voice trial; no silent permission/capture activation.
- [x] Simplify Settings and keep consent controls together.
- [x] Separate unscored Pebbles practice from its measured rounds; meaningful completion recap.
- [x] Practitioner-only website navigation and compact chart/review/routine layout.
- [x] Remove repeated counter/banner/instruction text and per-panel nested scrolling.
- [x] Keep detailed measurements, historical capture and care actions available on demand.
- [ ] Accept real iPhone/Mac keyboard, text scaling, permissions, backgrounding and physical audio routes.

## Conversation integrity

- [x] Coalesce incremental/cumulative fragments, preserve original words and separate barge-in turns.
- [x] Distinguish provider audio completion from independent speaker transcription completion.
- [x] Add optional transcript completion metadata; older status remains unknown.
- [ ] Verify the final transcription-boundary repair against a real provider, including marker-free compatibility.
- [x] Test quiet company, activity consent, unclear speech and stop instructions without weakening safety checks.
- [x] Real synthetic assessment-request evaluation passes after correcting refusal wording.
- [ ] Establish reliable deeper-reasoning handoff for unresolved questions across both native surfaces; record
  context-only responses and provider fallbacks honestly instead of forcing unnecessary calls.

## Capture and evidence

- [x] Integrate Edwin's pushed UNO Q/Atech changes while preserving local app/cloud work.
- [x] Disable light observation/context and unsupported scoring in the current profile.
- [x] Remove invented force, unvalidated pulse, retired browser tasks, unavailable Friendlink/iCBT and unsupported
  glasses camera/IMU measurements from default generated records/suggestions.
- [x] Retain actual validated observations with capture time, quality, source and durable retry.
- [x] Connect consented robot microphone energy summaries to numeric speech observations; discard PCM.
- [x] Correct Health snapshot counting/date attribution and check-in signal-group attribution.
- [ ] Physical pulse/cradle, robot audio/echo, camera calibration and Atech root firmware acceptance.
- [ ] Actual Meta motion/HFP acceptance; no outdoor/location or emotion claim from motion/face presence alone.

## One person and intelligence

- [x] Reproducible change/improvement/missing/outlier batch with namespaced IDs and real-rule reports.
- [x] Extend general reference histories so displayed charts have established baseline collection.
- [ ] One cohesive 16-day record with mostly complete supported observations, believable activities and continuity.
- [ ] Surface emerging routines honestly when collection is shorter than the full usual-period window.
- [ ] Show Gemma's evidence-linked review and activity/routine graph without exposing private companion memories.
- [ ] Show understandable week-to-week comparisons with evidence links, rather than a wall of raw metrics.
- [ ] Accept the final integrated record in desktop, intermediate and narrow browser layouts.

## Task research

Short daily activities and longer standardised tasks serve different purposes. The validated three-minute PVT-B
measures behavioural alertness and used a specific timing protocol; a custom one-minute game does not inherit
that validation. See [the original PVT-B study](https://pmc.ncbi.nlm.nih.gov/articles/PMC3197786/).
Published THINC-it work combines reaction, working-memory and processing-speed tasks; it does not make an
arbitrary custom game a clinical instrument. See [THINC-it sensitivity to change](https://pmc.ncbi.nlm.nih.gov/articles/PMC7327547/).

Current activities provide participation, reaction timing and memory-span observations. Practice stays separate,
scored timing stays consistent, interrupted rounds are discarded, and changed devices/protocols must not be pooled
as equivalent. Future broader batteries need a named protocol, reliability/practice-effect checks and calibration.
Facial movement remains optional observational geometry, not a person's internal emotion or a new state vote.

## Acceptance evidence

Use the dated progress entries for final test counts and paths. Test authored fixtures through real API routes,
retry/restart/scope boundaries, native production controllers and the in-app browser. Include failures as well as
passes. No ambient media capture, provider-budget override or publication is implied by a software test.
