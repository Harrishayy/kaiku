"""Consensus-accuracy simulation on synthetic patients with known ground truth (shown on /eval; drives tuning).

Per patient: replay the rule day by day under a given Criteria and compare with the scenario's truth
(synth.PatientSpec.truth_on).
- per_state: day-level precision/recall for every state (ramp-up days after onset are not scored)
- needs_call episodes: first transition into needs_call on/after onset for a needs_call-truth patient = hit;
  any other transition into needs_call = false alert. Lead time = clinical_day − first hit day.
- ablation: needs_call episode precision/recall with each source removed — the honest answer to
  "what happens when a source is missing?" (a two-source drift becomes a watch).
NOT clinical accuracy: the generator is ours. Shards are independent → Modal `.map` (cloud/app.py).

Offline tuning (what `make tune` runs):
    python -m kaiku_cloud.jobs.simulate --criteria config/criteria.toml [--compare candidate.toml] [--n 40]
Exits 2 if a criteria file is invalid.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

from kaiku_contracts.api import EvalResult, StateScore
from kaiku_contracts.criteria import Criteria, load_criteria
from kaiku_contracts.sources import CONSENSUS_SOURCES

from ..analytics.consensus import replay
from ..analytics.data import build
from .synth import cohort, generate

END = date(2026, 11, 1)  # fixed so results are reproducible
WARMUP = 21  # days of history before scoring starts (baseline + lag)
STATES = ("stable", "watch", "needs_call", "safety")


def _states(events: list[dict[str, Any]], home_id: str, crit: Criteria, days: int,
            exclude: frozenset[str] = frozenset()) -> list[str]:
    data = build(home_id, events, crit, exclude_sources=exclude)
    res = replay(data, crit, END, now=datetime.combine(END, datetime.max.time(), UTC))
    by_day = {r.day: r.state for r in res}
    start = END - timedelta(days=days - 1)
    return [by_day.get(start + timedelta(days=i), "watch") for i in range(days)]


def run_shard(args: tuple[int, int, dict[str, Any]]) -> list[dict[str, Any]]:
    """args = (seed, n_patients, criteria as JSON dict). One outcome dict per patient (full + per removed source)."""
    seed, n, crit_json = args
    crit = Criteria.model_validate(crit_json)
    out = []
    for spec in cohort(n, seed):
        events = generate(spec, end=END)
        out.append({
            "scenario": spec.scenario, "onset": spec.onset, "clinical_day": spec.clinical_day,
            "truth": [spec.truth_on(i) for i in range(spec.days)], "expected": spec.expected_state,
            "states": _states(events, spec.home_id, crit, spec.days),
            "ablation": {s: _states(events, spec.home_id, crit, spec.days, frozenset({s})) for s in CONSENSUS_SOURCES},
        })
    return out


def _episodes(o: dict[str, Any], states: list[str]) -> tuple[int, int, int | None]:
    """(hit 0/1, false alerts, first hit day) for needs_call."""
    starts = [i for i in range(WARMUP, len(states)) if states[i] == "needs_call" and states[i - 1] != "needs_call"]
    is_target = o["expected"] == "needs_call" and o["onset"] is not None
    hits = [i for i in starts if is_target and i >= o["onset"]]
    false = len(starts) - (1 if hits else 0)
    return (1 if hits else 0), false, (hits[0] if hits else None)


def _score(tp: int, fp: int, fn: int) -> StateScore:
    return StateScore(precision=round(tp / (tp + fp), 3) if tp + fp else None,
                      recall=round(tp / (tp + fn), 3) if tp + fn else None)


def _needs_call_score(outcomes: list[dict[str, Any]], key: Callable[[dict[str, Any]], list[str]]) -> StateScore:
    tp = fp = targets = 0
    for o in outcomes:
        hit, false, _ = _episodes(o, key(o))
        tp += hit
        fp += false
        targets += o["expected"] == "needs_call"
    return StateScore(precision=round(tp / (tp + fp), 3) if tp + fp else None,
                      recall=round(tp / targets, 3) if targets else None)


def aggregate(outcomes: list[dict[str, Any]], rule_version: str) -> EvalResult:
    per_state: dict[str, StateScore] = {}
    for st in STATES:
        tp = fp = fn = 0
        for o in outcomes:
            for i in range(WARMUP, len(o["states"])):
                truth, pred = o["truth"][i], o["states"][i]
                if truth is None:
                    continue
                tp += truth == st and pred == st
                fp += truth != st and pred == st
                fn += truth == st and pred != st
        per_state[st] = _score(tp, fp, fn)
    false_total = monitored = 0
    leads: list[float] = []
    for o in outcomes:
        _, false, first = _episodes(o, o["states"])
        false_total += false
        monitored += len(o["states"]) - WARMUP
        if first is not None and o["clinical_day"] is not None:
            leads.append(o["clinical_day"] - first)
    ablation = {s: _needs_call_score(outcomes, lambda o, s=s: o["ablation"][s]) for s in CONSENSUS_SOURCES}
    return EvalResult(
        n_patients=len(outcomes), rule_version=rule_version, per_state=per_state,
        false_needs_call_per_patient_month=round(false_total / (monitored / 30), 3) if monitored else 0.0,
        median_lead_time_days=float(median(leads)) if leads else None, ablation=ablation,
        generated_at=datetime.now(UTC), sim=True,
    )


def run_eval(n_patients: int = 36, shards: int = 4, mapper: Callable[[list], Iterable] | None = None,
             seed: int = 7, criteria: Criteria | None = None) -> EvalResult:
    """mapper(list_of_shard_args) -> iterable of shard results. Locally: in-process. On Modal: Function.map."""
    crit = criteria or load_criteria()
    crit_json = crit.model_dump(mode="json", by_alias=True)
    per = max(1, n_patients // shards)
    shard_args = [(seed + s, per, crit_json) for s in range(shards)]
    results = mapper(shard_args) if mapper else map(run_shard, shard_args)
    return aggregate([o for shard in results for o in shard], crit.rule_version)


# ------------------------------------------------------------------ CLI (make tune)
def _fmt(v: float | None) -> str:
    return "  —  " if v is None else f"{v:5.3f}"


def _rows(r: EvalResult) -> list[tuple[str, float | None]]:
    rows: list[tuple[str, float | None]] = []
    for st, sc in r.per_state.items():
        rows += [(f"{st} precision", sc.precision), (f"{st} recall", sc.recall)]
    rows += [("false needs_call / patient-month", r.false_needs_call_per_patient_month),
             ("median lead time (days)", r.median_lead_time_days)]
    for src, sc in r.ablation.items():
        rows += [(f"without {src}: needs_call precision", sc.precision), (f"without {src}: needs_call recall", sc.recall)]
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Simulate the consensus under a criteria file (synthetic patients).")
    ap.add_argument("--criteria", help="criteria TOML (default: $KAIKU_CRITERIA or config/criteria.toml)")
    ap.add_argument("--compare", help="second criteria TOML: print a side-by-side diff")
    ap.add_argument("--n", type=int, default=36, help="synthetic patients (spread over the scenarios)")
    ap.add_argument("--json", action="store_true", help="print EvalResult JSON instead of a table")
    a = ap.parse_args(argv)
    try:
        base = load_criteria(a.criteria) if a.criteria else load_criteria()
        cand = load_criteria(a.compare) if a.compare else None
    except Exception as e:  # FileNotFoundError / ValidationError / TOML error
        print(f"invalid criteria: {e}", file=sys.stderr)
        return 2
    r1 = run_eval(n_patients=a.n, shards=1, criteria=base)
    r2 = run_eval(n_patients=a.n, shards=1, criteria=cand) if cand else None
    if a.json:
        print(r1.model_dump_json(indent=1) if r2 is None else
              '{"base": ' + r1.model_dump_json() + ', "candidate": ' + r2.model_dump_json() + "}")
        return 0
    print(f"synthetic patients: {r1.n_patients}  (not clinical accuracy)")
    if r2 is None:
        print(f"{'metric':42} {r1.rule_version}")
        for name, v in _rows(r1):
            print(f"{name:42} {_fmt(v)}")
    else:
        print(f"{'metric':42} {r1.rule_version:>24} {r2.rule_version:>24}   change")
        for (name, v1), (_, v2) in zip(_rows(r1), _rows(r2), strict=True):
            delta = "" if v1 is None or v2 is None or v1 == v2 else f"{v2 - v1:+.3f}"
            print(f"{name:42} {_fmt(v1):>24} {_fmt(v2):>24}   {delta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
