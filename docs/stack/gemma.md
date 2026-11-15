# Gemma in Kaiku

> Part of [the stack pages](INDEX.md). Read from the code on 15 November 2026. Every record used in the runs
> below is simulated. Module doc: [`cloud/AGENTS.md`](../../cloud/AGENTS.md); the decision behind the split of
> work between models is D35 in [`decisions.md`](../decisions.md).

**In one paragraph.** Gemma 4 (`gemma-4-26b-a4b-it`) is the model that reasons over a person's record. It does
eight jobs, from the practitioner's review to the answer behind the voice's hardest questions. In every one of
them it is given facts that code wrote, it answers in a small structure, and code checks the answer before
anyone sees it. Gemma never sets a person's state, never handles a crisis and never writes a number onto the
practitioner's page. We think this is the honest way to use an open model near health data: let it do the
part only a language model can do (choose what matters and say what it might mean), and make everything it
says checkable.

## Two ways to reach the same model

| Route | How | Status |
|---|---|---|
| **Hosted** (default) | `gemma-4-26b-a4b-it` through the Gemini API's `generateContent`, called from [`llm/gemma_hosted.py`](../../cloud/kaiku_cloud/llm/gemma_hosted.py) with `temperature 0.2` and minimal thinking | Verified on every job below |
| **Our own GPU** | `google/gemma-4-26B-A4B-it` in vLLM on a Modal H100, [`cloud/gemma_app.py`](../../cloud/gemma_app.py), reached by [`llm/gemma_vllm.py`](../../cloud/kaiku_cloud/llm/gemma_vllm.py) | Verified for the review and a record question (15 Nov); see [Modal](modal.md) |

One switch, `[gemma].provider` in [`config/kaiku.toml`](../../config/kaiku.toml), moves every text job between
them ([`llm/gemma.py`](../../cloud/kaiku_cloud/llm/gemma.py)). There is no silent switch from one provider to
the other: when Gemma cannot answer, each job falls back to its own deterministic text and says so.

## The eight jobs

| # | Job | Gemma is given | Gemma returns | Code then |
|---|---|---|---|---|
| 1 | **Practitioner review** ([`insight.py`](../../cloud/kaiku_cloud/insight.py), `GET /v1/patients/{id}/insight`) | Up to 60 scored and 12 shown-only records, each a line written by code: id, label, detail, direction, whether it lasted | An overview and findings: a theme, the ids it cites, what it might mean, one thing to consider | Runs more than a dozen kinds of check, renders every fact and number itself from the cited records, and adds a finding for any signal group Gemma left out |
| 2 | **Ask this record** ([`clinician_chat.py`](../../cloud/kaiku_cloud/clinician_chat.py), `POST /v1/patients/{id}/ask`) | The practitioner's question (marked as untrusted data) and the evidence list | Only `{"cites": [ids]}` | Checks every id exists and prints the facts itself. **Gemma's prose is never shown.** |
| 3 | **The companion's mind** ([`mind/router.py`](../../cloud/kaiku_cloud/mind/router.py), behind the voice's `ask_mind` tool) | The question and a short list of facts in words: no digits, no states, no health detail | An answer of at most 400 characters, a confidence, the fact ids it used | Rejects digits, state words, clinical wording and uncited answers; when two notes disagree the answer must ask and cite both |
| 4 | **Nightly knowledge graph** ([`mind/nightly.py`](../../cloud/kaiku_cloud/mind/nightly.py)) | The notebook's nodes (id, type, label), only if the person lets Kaiku remember | Proposed `merge` and `expire` changes | Accepts at most 10: same type only, people merge only on a name match, only plans expire. Memories themselves are never edited by a model |
| 5 | **Tone of a reflection** ([`mind/affect.py`](../../cloud/kaiku_cloud/mind/affect.py)) | The person's own lines from a conversation they chose to keep | Closed lists only: valence, up to three themes, up to two tones, energy | Keeps the rule's label when the answer is invalid. A crisis conversation is never labelled |
| 6 | **A look at a few pictures** ([`vision.py`](../../cloud/kaiku_cloud/vision.py), `POST /v1/vision/look`, D65) | At most 3 small JPEGs from a check-in, with a second opt-in | Six fields from closed word lists (for example resting, smiling, lowered or tense expression) | Stores only the note (`obs.vision_note`), shown and citable, never scored. The pictures are never written anywhere. No other model stands in |
| 7 | **Consensus in words** ([`llm/explain.py`](../../cloud/kaiku_cloud/llm/explain.py), off unless switched on) | The consensus as JSON | Only an order of signal groups and which measures to focus on | Renders the sentence from a template. Provider prose never reaches the output |
| 8 | **The team's read of one day** ([`debug_day.py`](../../cloud/kaiku_cloud/debug_day.py), admin only) | The day's reading and its facts | Summary, what moved, what is missing, tomorrow, a check of the rule | Every number must appear in a cited fact, **in its own role**; code fills any line Gemma left out |

## What the checks look like

The review is the job a practitioner reads, so it has the strictest checks. A finding is rejected, by category,
when it:

- cites an id that is not in the evidence;
- contains any digit, or a number, month or weekday written as a word (code prints those);
- uses clinical or state wording, or claims a cause, or overclaims;
- names an emotion, or infers a feeling from a face;
- tells the practitioner what to do (the "consider" line must be a question);
- is generic, thin, a duplicate, or built only on records that have no vote;
- contradicts which measures are back to usual and which are still away;
- gives a theme that does not fit the direction the record shows.

Gemma gets one retry with the list of categories it tripped. Whatever survives is shown with the provider's
name; whatever does not is replaced by the deterministic finding, and the page says which it was. Two of these
checks exist because of real failures on real calls: dates in prose (14 Nov), and a day read cut off at 1,200
tokens.

## The agent trace

The dashboard's review panel has a second tab, "Agent trace". It lists the ten steps behind the page
(`retrieve`, `consensus`, `compare`, `course`, `select`, `interpret`, `overview`, `validate`, `graph`,
`render`), and for each: whether **code, Gemma or a template** did it, the model, the time it took, whether it
came from cache, and how many answers were rejected in which category. Counts and categories only; never the
record's content. The `consensus` step reads "No model takes part". A practitioner, or a judge, can see exactly
where a model was involved and where it was overruled.

## What Gemma may not do, and where that is enforced

| Rule | Enforced by |
|---|---|
| **No state.** The consensus is `analytics/consensus.py` reading [`config/criteria.toml`](../../config/criteria.toml) | State-word validators in the review and the mind; the headline and status line are code; an explanation cannot change the state |
| **No crisis handling.** | The phrase gate runs on every tool argument before any model is reached (`mind/session.py`); test `test_crisis_never_reaches_gemma` |
| **No numbers of its own** on the practitioner's page | The digit check; code renders every fact |
| **No emotion from a face.** | `emotion_label` and `face_inference` checks; the picture note is closed word lists |
| **No edits to her memories.** | The graph validator accepts status changes only |

## What has run

| Date | What (simulated record, real model calls) | Result |
|---|---|---|
| 14 Nov | Hosted: `ask_mind` | 2.2 s (2.3 s median over 5 later runs) |
| 14 Nov | Hosted: record question | 6.2 s, 13 citations |
| 14 Nov | Hosted: nightly graph | 1.9 s, one merge accepted |
| 14 Nov | Hosted: practitioner review | 18.1 s median over 8 reviews (9.6 to 23.4 s), as measured for `explainers/intelligence-flow.html`; not logged in `progress.md` |
| 15 Nov | Own GPU: practitioner review | 10.5 s and 5.2 s warm, accepted by every check |
| 15 Nov | Own GPU: record question | 2.2 s |
| 15 Nov | Hosted: picture look on three drawn faces | 4.1 s; the database held one note and no picture bytes |

Tests, in [`cloud/tests/`](../../cloud/tests/): `test_insight.py` (each validator, cache, fallbacks, the
provider switch), `test_mind_router.py`, `test_gemma_primary.py` (Gemma first, crisis never reaches it),
`test_gemma_vllm.py` (deadline, cancel, budget, a cold call left running), `test_clinician_chat.py` (prose never
shown), `test_debug_day.py`, `test_vision.py` (no picture in the database, the logs or the answers).

## Is this the best we could have done?

**Why Gemma, and why this size.** The work is structured reasoning over a few dozen short facts, not open
conversation, which is what a mid-sized open model is good at. An open model is also the only kind we can move
onto our own GPU, and for a record like this that matters more than a few points of fluency. The rule for
size was "the smallest instruct variant that returns valid JSON" (plan 01, D5); 26B-A4B is what we chose and
measured, and the 12B model on a cheaper GPU is configured as the next thing to try.

**Why validators and not trust.** A practitioner cannot act on "the model thinks". Every sentence on the page
either cites records they can open or was written by code. This also made Gemma replaceable in both
directions: the same checks guard the hosted model, our GPU and any future tuned model.

## How it joins the rest

- **Gemini Live → Gemma.** The voice is the only part that hears the person. When a question needs the record,
  it calls `ask_mind`; the cloud tries her own notebook first (no model), then Gemma, then Gemini as a fallback,
  then a fixed line ([Gemini](gemini.md)).
- **Devices → Gemma.** Everything Gemma reads arrived as a derived observation from the phone, the Mac, the
  glasses walk or the robot, already turned into verdicts by the deterministic rule.
- **Gemma → practitioner.** The review, its citations and the trace are one route, served by the same
  [Modal](modal.md) app as the dashboard.
