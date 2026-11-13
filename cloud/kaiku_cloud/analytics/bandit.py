"""Thompson sampling (Beta) over nudge arms, learned per person (handoff §7.8).

reward(outcome) = 0.5 × immediate + 0.5 × next_day, each normalised to 0..1 and clipped (handoff v2 §7.8):
  immediate  mean before→after effect of that activity (obs.intervention_response): HRV delta / 20 ms and
             mood/energy delta / 2, averaged, mapped from −1..1 to 0..1.
  next_day   the outcome's `reward` (the hub sends a next-day-only reward), else next-day mood/energy
             (obs.nudge_outcome.next_day) relative to the neutral 3, mapped to 0..1.
A missing half is dropped (the other counts fully). A declined nudge scores 0. Cold start = uniform Beta(1,1).
"""

from __future__ import annotations

import random
from collections import defaultdict
from statistics import fmean
from typing import Any

from kaiku_contracts.payloads import NUDGE_ARMS

ARM_LABEL = {
    "breathe": "A slow breathing round",
    "drum": "A short drumming session",
    "daylight_walk": "A daylight walk",
    "friend_ping": "Pinging a friend",
    "icbt_exercise": "An iCBT exercise",
}
ARM_ACTIVITY = {"breathe": "breathe", "drum": "drum", "daylight_walk": "walk", "friend_ping": "friend_ping",
                "icbt_exercise": "icbt"}
ACTIVITY_LABEL = {"breathe": "Guided breathing", "drum": "Drumming", "walk": "Walks", "friend_ping": "Friend ping",
                  "icbt": "iCBT exercise"}


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def immediate_effect(resp: dict[str, Any]) -> float | None:
    """One intervention_response → effect in −1..1 (None if no usable delta)."""
    d = resp.get("delta") or {}
    parts = []
    if d.get("rmssd_ms") is not None:
        parts.append(_clip(d["rmssd_ms"] / 20.0))
    for k in ("mood", "energy"):
        if d.get(k) is not None:
            parts.append(_clip(d[k] / 2.0))
    return fmean(parts) if parts else None


def immediate_by_activity(responses: list[dict[str, Any]]) -> dict[str, float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for r in responses:
        e = immediate_effect(r)
        if e is not None:
            acc[r["activity"]].append(e)
    return {a: fmean(v) for a, v in acc.items()}


def reward_of(outcome: dict[str, Any], immediate: dict[str, float] | None = None) -> float:
    """0.5 × immediate effect + 0.5 × next-day effect (both 0..1); a missing half is dropped, not assumed.

    next-day = outcome.reward when the hub sent one (the hub's reward is next-day only), else derived from
    outcome.next_day mood/energy vs the neutral 3. immediate = mean before→after delta of that activity.
    """
    if not outcome.get("accepted"):
        return 0.0
    parts: list[float] = []
    imm = (immediate or {}).get(ARM_ACTIVITY.get(outcome.get("arm", ""), ""))
    if imm is not None:
        parts.append((_clip(imm) + 1) / 2)
    if outcome.get("reward") is not None:
        parts.append(float(_clip(outcome["reward"], 0.0, 1.0)))
    else:
        nd = outcome.get("next_day") or {}
        vals = [(nd[k] - 3) / 2 for k in ("mood", "energy") if nd.get(k) is not None]
        if vals:
            parts.append((_clip(fmean(vals)) + 1) / 2)
    return round(fmean(parts), 3) if parts else 0.5


def posteriors(outcomes: list[dict[str, Any]], responses: list[dict[str, Any]] | None = None
               ) -> dict[str, tuple[float, float, int]]:
    imm = immediate_by_activity(responses or [])
    post = {a: [1.0, 1.0, 0] for a in NUDGE_ARMS}
    for p in outcomes:
        if p.get("arm") in post:
            r = reward_of(p, imm)
            post[p["arm"]][0] += r
            post[p["arm"]][1] += 1 - r
            post[p["arm"]][2] += 1
    return {a: (v[0], v[1], int(v[2])) for a, v in post.items()}


def choose(outcomes: list[dict[str, Any]], responses: list[dict[str, Any]] | None = None,
           rng: random.Random | None = None, draws: int = 2000) -> dict[str, Any]:
    rng = rng or random.Random()
    post = posteriors(outcomes, responses)
    sample = {a: rng.betavariate(al, be) for a, (al, be, _) in post.items()}
    arm = max(sample, key=sample.get)  # type: ignore[arg-type]
    wins = dict.fromkeys(NUDGE_ARMS, 0)
    for _ in range(draws):
        s = {a: rng.betavariate(al, be) for a, (al, be, _) in post.items()}
        wins[max(s, key=s.get)] += 1  # type: ignore[arg-type]
    probs = {a: round(w / draws, 3) for a, w in wins.items()}
    al, be, n = post[arm]
    if n == 0:
        reason = "Still learning what helps you, so trying a range of ideas."
    else:
        reason = f"{ARM_LABEL[arm]} has worked well for you on about {round(al - 1)} of {n} recent tries."
    return {"arm": arm, "reason": reason, "probs": probs}


def help_stats(outcomes: list[dict[str, Any]], responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per activity: how often tried (responses + nudges) and the mean reward. Sorted best first."""
    imm = immediate_by_activity(responses)
    post = posteriors(outcomes, responses)
    tries: dict[str, int] = defaultdict(int)
    for r in responses:
        tries[r["activity"]] += 1
    rows = []
    for arm, (al, _be, n) in post.items():
        act = ARM_ACTIVITY[arm]
        total = n + tries.get(act, 0)
        if total == 0:
            continue
        mean = round((al - 1) / n, 3) if n else (round((imm[act] + 1) / 2, 3) if act in imm else None)
        rows.append({"activity": act, "label": ACTIVITY_LABEL[act], "tries": total, "mean_effect": mean})
    return sorted(rows, key=lambda r: -(r["mean_effect"] or 0))
