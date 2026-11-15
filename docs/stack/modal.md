# Modal in Kaiku

> Part of [the stack pages](INDEX.md). Read from the code on 15 November 2026. Every claim names the file it
> comes from; what ran on Modal and what is only written are kept apart in [What has run](#what-has-run).
> Module doc: [`cloud/AGENTS.md`](../../cloud/AGENTS.md).

**In one paragraph.** Kaiku's whole cloud is Modal. One app, [`cloud/app.py`](../../cloud/app.py), is the API
that every device posts to, the practitioner dashboard, the database, the scheduled analytics and a parallel
simulation of synthetic people. A second app, [`cloud/gemma_app.py`](../../cloud/gemma_app.py), serves Gemma 4
on an H100 with vLLM and scales to zero. The public demo is that first app:
<https://harrish21raj--kaiku-web.us-east.modal.run/?id=aino> (one simulated record, read-only).

## What we use, and how

| Modal feature | Where | What it does for Kaiku |
|---|---|---|
| `modal.App` × 2 | `cloud/app.py`, `cloud/gemma_app.py` | `kaiku` (API, dashboard, jobs) and `kaiku-gemma` (GPU). Two apps so the API deploys without a GPU and Gemma costs nothing until called. |
| `modal.Image` | `app.py` `image` | `debian_slim` + FastAPI, pydantic, numpy, httpx, `google-genai`; the config folder, the two Python packages, the prompt files and the Next.js static export are added as local layers. |
| `@modal.asgi_app()` | `app.py` `web()` | The FastAPI app: ingest, consensus, companion mind, practitioner routes, and the dashboard mounted at `/`. |
| `min_containers=1, max_containers=1` + `@modal.concurrent(max_inputs=50)` | `web()` | Exactly one warm container taking up to 50 requests at once. SQLite has one writer, so one container is the design, not a shortcut. |
| `modal.Volume` | `kaiku-data` at `/data` | The SQLite database, the cached voice lines, walk postcards and the spend ledger. Committed after every write (below). |
| `modal.Secret` | `kaiku-secrets` | Gemini API key, the home token and the admin token. Attached only if it exists at deploy time, so a first deploy does not fail. |
| `modal.Period(minutes=15)` | `recompute()` | Recomputes the consensus for every person on a clock (it is also recomputed on every ingest), so the reading keeps up on a day when nothing arrives. |
| `modal.Cron("0 3 * * *", Europe/Helsinki)` | `nightly()` | Recompute, refresh the simulation, the daily reflection, then the mind's night work: graph rebuild, embedding backfill, Gemma's graph consolidation, reflection labels. |
| `modal.Cron("0 6 * * 1", Europe/Helsinki)` | `weekly()` | Monday's practitioner brief. |
| `Function.map()` | `simulate_shard.map(...)` | 72 synthetic people in 8 shards, each replaying the real consensus rule day by day. Feeds the `/eval` and `/tune` pages. |
| `@app.cls(gpu="H100")` + `@modal.enter()` + `@modal.method()` | `gemma_app.py` `Gemma` | vLLM's in-process engine holding `google/gemma-4-26B-A4B-it`; `min_containers=0`, `scaledown_window=300`. |
| A CPU-only function for weights | `gemma_app.py` `download()` | Pulls the gated weights into a Volume (`kaiku-hf-cache`) on 2 CPUs, so no GPU second is spent downloading. |
| `modal.Cls.from_name(...)` + `.spawn()` / `.get(timeout=)` | `cloud/kaiku_cloud/llm/gemma_vllm.py` | The API (or a laptop) calls the GPU class across apps with a deadline, and can leave a cold call running. |
| `Image.from_registry("nvidia/cuda:12.8.0-devel-…")` | `gemma_app.py` `vllm_image` | The CUDA *devel* base. Found the hard way: on `debian_slim` vLLM died at warm-up with "Could not find nvcc" (14 Nov). |
| `@app.local_entrypoint()` | `main()`, `smoke()` | `modal run app.py` runs the simulation; `make gemma-smoke` makes one cold GPU call and prints the time. |

Not used: Sandboxes, `modal.Dict`, `modal.Queue`, memory snapshots, a region pin, training jobs.

## Four things worth a closer look

### 1. One writer, kept honest by the platform

The record lives in SQLite on a Volume. That only works if exactly one process writes, so the whole app is built
around it:

- `web()` is pinned to one container (`min_containers=1, max_containers=1`), and input concurrency gives it
  throughput instead of replicas.
- The scheduled functions **do not mount the Volume**. Each one makes an authenticated HTTP call to the API
  container's own admin route (`_call_recompute`, `_call_admin` in `app.py`), so the cron jobs can never become
  a second writer.
- A middleware in [`cloud/kaiku_cloud/api/main.py`](../../cloud/kaiku_cloud/api/main.py) calls `volume.commit`
  after any request that changed the store. If the commit fails the request answers 503 "durable commit
  unavailable": the phone keeps the reading in its offline queue and sends it again, so a reading is never
  acknowledged and then lost.

### 2. The dashboard and the API are one URL

`make cloud-deploy` first builds the Next.js static export, then `modal deploy`. The export is added to the image
and mounted last, so `/v1/*` wins and everything else is the dashboard (D13). A judge, a phone and the robot's
hub all use the same address; there is no second host, no CORS and no separate front-end deploy to drift.

### 3. A simulation that fans out

The consensus rule is one readable file, [`config/criteria.toml`](../../config/criteria.toml), and the team
tunes it. To see what a change does, `/v1/eval` runs `run_eval(n_patients=72, shards=8, mapper=simulate_shard.map)`
([`jobs/simulate.py`](../../cloud/kaiku_cloud/jobs/simulate.py)): each shard builds 9 synthetic people over 45
days from 13 kinds of course and replays the **real** rule on each day, once in full and once with each signal
group removed. The result (precision and recall per state, false "needs a call" per person-month, lead time,
what each signal group adds) is cached per rule version and shown on `/eval` and beside the editor on `/tune`.
The module says in its first lines what this is not: clinical accuracy, since the generator is ours.

### 4. Gemma on our own GPU, behind one switch

`[gemma].provider` in [`config/kaiku.toml`](../../config/kaiku.toml) moves **every** text call Gemma makes
(practitioner review, record questions, the companion's mind, the nightly graph work) between Google's hosted
API and our Modal app. The GPU side is built for a product that is quiet most of the day:

- **Scale to zero, and say so.** A cold start took 215 to 235 seconds. The caller waits its own deadline
  (30 s for a review), then shows the deterministic text. It deliberately **does not cancel** the cold call,
  because that call is what boots the GPU; the next question inside the 300-second window is answered by Gemma.
  A warm call that times out is cancelled without stopping the container.
- **Costed before it runs.** Every GPU call first reserves an estimate in a spend ledger
  ([`kaiku_contracts/budget.py`](../../contracts/python/kaiku_contracts/budget.py)): cold is charged as
  240 s plus the idle tail, warm as the idle time since the last answer plus 30 s, at $4.50 an hour. Over the
  cap, the call is refused and the caller falls back.
- **Sized from a failure.** `max_model_len` is 16384 because 8192 refused the review's prompt.
- **A LoRA hook, unused.** `adapter_repo` loads an adapter beside the base weights. No adapter has been trained.

## What has run

| Date | What | Result |
|---|---|---|
| 14 Nov | API deployed in authenticated mode | Admin and patient routes answer 401 without a token |
| 14 Nov | Public demo seeded (own secret, own Volume, admin closed) | Checked from outside: dashboard 200, admin 401 |
| 14 Nov | `make gemma-smoke` on the H100 | One cold answer in 215 s, after the image got the CUDA toolkit |
| 15 Nov | `kaiku-gemma` redeployed; a local API with `provider=modal` on the simulated record | Cold start 235 s; practitioner review warm in 10.5 s and 5.2 s, accepted by every validator; a record question in 2.2 s |

## Is this the best we could have done?

**What fits the use case well.**

- A companion for one person at home is quiet for hours, then needs an answer in seconds. A warm CPU container
  for the record and a scale-to-zero GPU for reasoning is the shape of that load, and Modal gives both from two
  Python files.
- Health-adjacent data argues for the model running on infrastructure we control. The switch exists and passed
  the product's own checks on real calls, which is further than a slide.
- Schedules matter here more than in most apps: "no reading for three days" is itself a finding, and only a
  clock can raise it.

**What we would do next, in order.**

1. **Cut the cold start.** Four minutes is too long for a first question. A memory snapshot of the loaded engine,
   or the 12B model on an L40S, are the two candidates; neither was tried.
2. **Make the GPU the deployed default** and run every Gemma job on it, including the picture look (the vLLM app
   is text-only today, so pictures always use the hosted API, D65).
3. **Constrained decoding.** Output is JSON by instruction, then validated and retried. vLLM can guide decoding
   to a schema; that would remove a class of retries.
4. **Outgrow SQLite when there is more than one clinic.** One container is right for a pilot of tens of people.
5. **Use the fan-out for more.** 8 shards is small. The same `.map()` could sweep rule settings, and Sandboxes
   could run a rule a practitioner edits before it goes live.

## How it joins the rest

- **Devices → Modal.** The iPhone and Mac apps and the robot's hub post derived observations to `POST /v1/events`
  on the one container; it validates, stores, recomputes the consensus and commits.
- **Gemini Live → Modal → Gemma.** A device asks `POST /v1/companion/session` for a short-lived Live token and a
  small context card. When the voice calls a tool (`feel`, `recall`, `ask_mind`), the device forwards it to
  `POST /v1/companion/tool` here, where code runs the crisis gate first and Gemma reasons second
  ([Gemini](gemini.md), [Gemma](gemma.md)).
- **Modal → practitioner.** The dashboard served from `/` reads `/v1/patients/{id}/insight` for Gemma's review
  and its agent trace.
- **Robot and glasses.** Their numbers arrive through the hub and the iPhone like any other device
  ([Atech](atech.md), [Arduino UNO Q](arduino-uno-q.md), [Meta glasses](meta-glasses.md)).
