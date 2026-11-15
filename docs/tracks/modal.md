# Best use of Modal (Modal) — tech challenge

Brief as given on the Junction 2026 challenge page, copied 15 November 2026. The credit redemption code and its
link are left out (public repository); they are on the challenge page in the Junction app.

## The challenge
Take your Junction project from laptop to production AI on Modal.

Every Junction team is building with AI, and most hit the same wall: the model runs on a laptop, but too slowly,
not on a GPU, and not behind a URL the judges can open. Modal gets you past that wall. Use Modal to power the
project you're already building for your main Junction challenge: serve an open model on a GPU, run your agent's
code in secure Sandboxes, fine-tune a model on your own data, or fan out a big batch job, all in plain Python with
no Dockerfiles, Kubernetes or YAML.

We're looking for the most ambitious working AI system built on Modal, where Modal does the heavy lifting and the
team spends its 48 hours on the problem. Inference, agents, sandboxes and training: your whole AI stack on one
platform.

## Insight
Modal was built so that a single developer can do what used to take a platform team. Best use of Modal is a tech
challenge, so you compete in it on top of your main challenge: use Modal to power the project you're already
building and you can enter. The same project can enter other tech challenges too.

## What Modal brings
- $100 in Modal credits per participant for CPUs and GPUs, billed per second and scaling to zero when idle; valid
  for one year from redemption. GPUs: T4, L4, A10, L40S, A100 (40 and 80 GB), RTX PRO 6000, H100, H200, B200, B300.
- Python SDK and CLI (`pip install modal`); JavaScript and Go SDKs for Sandboxes. Decorate a function, `modal run`
  executes it in the cloud; `modal deploy` makes it an autoscaling web endpoint with a public URL.
- Sandboxes: secure, on-demand containers for agents, code interpreters and evals.
- Web endpoints (FastAPI, WebSockets, WebRTC) with autoscaling and public URLs.
- Volumes, Dicts and Queues for model weights, datasets and shared state.
- Modal Dojo: open-source library for fine-tuning and RL post-training open models on Modal GPUs.
- Starter examples: LLM serving with vLLM and SGLang, speech-to-text, text-to-speech, vision, RAG, agents, RL.
- Mentors from Modal engineering and Developer Relations at the booth and on the Junction Discord.

## Judging criteria
| Criterion | Weight | Question |
|---|---|---|
| Effective use of Modal | 40% | How central Modal is to the project and how well you use it, from GPU inference to Sandboxes, training and scaling out. |
| Technical ambition | 25% | How hard the build is and how far you pushed it in 48 hours. |
| Impact | 20% | How well it solves a real problem from your main challenge. |
| Demo | 15% | A live, deployed app the judges can actually use. |

## Prizes
1st team: $2000 in cash and $3000 in Modal credits.
