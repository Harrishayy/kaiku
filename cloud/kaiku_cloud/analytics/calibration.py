"""Calibration harness: how well does the consensus rule tell "not feeling well" from "ok"?

    uv run python -m kaiku_cloud.analytics.calibration [--criteria A.toml] [--compare B.toml] [--n 40] [--json]
    make calibrate [CRITERIA=path] [COMPARE=path] [N=40]

Why this exists next to `make tune` (jobs/simulate.py): the tune cohort moves every signal by 4–5 of its own
day-to-day standard deviations, with noise equal to the criteria's own `min_mad` floors, on 45-day records.
That answers "does the rule work on the data it was tuned on". This harness asks the harder questions:

  - effect size is explicit (mild 1 SD, moderate 2 SD, marked 3 SD of the person's own day-to-day spread), and
    only some signals respond in each person;
  - people differ in how noisy they are relative to the `min_mad` floor (0.6x–1.6x), noise is autocorrelated and
    has outliers, dials are whole numbers, capture is partial;
  - labelled trajectories: stable, noisy-but-fine, weekday pattern, one broken sensor, a missing source, gradual
    decline, sudden drop, short dip, decline with fewer check-ins, recovery, a bad first fortnight, and short
    records (day 3 / 7 / 16).

Reported per trajectory: sensitivity at two levels ("flag" = at least one source worse, i.e. worth a check-in;
"call" = needs a call), false flags per person-week, day-level specificity, detection delay in days.

The generator is criteria-driven: one synthetic series per enabled `[[metric]]`, so a new metric block is
covered without touching this file. It works at the daily-series level (PatientData), not the event level;
event extraction is tested in test_analytics.py.

NOT clinical accuracy. Every number is a property of the rule under stated assumptions about a person, not a
measurement on people. Limits are listed in docs/validation.md.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from statistics import fmean, median
from typing import Any

from kaiku_contracts.criteria import Criteria, MetricSpec, load_criteria
from kaiku_contracts.sources import CONSENSUS_SOURCES

from .consensus import DayResult, replay
from .data import PatientData, Reading

START = date(2026, 9, 1)  # fixed: results are reproducible (a Tuesday; weekends fall on fixed indices)
EFFECTS = {"mild": 1.0, "moderate": 2.0, "marked": 3.0}  # shift in units of the person's own day-to-day SD
RESPOND_P = 0.7  # share of signals that move at all when this person is unwell
COOL_DOWN = 7  # days after an unwell period that are not scored as "fine"
DETECT_WINDOW = 21  # an unwell period counts as found if flagged within this many days of onset
PHQ_EVERY = 14
PHQ_POINTS_PER_SD = 3.0  # moderate (2 SD) decline ~ +6 points: about one reliable change on the PHQ-9
_SCALE_UNIT = re.compile(r"^\s*(\d+)\s*[–-]\s*(\d+)\s*$")  # "1–5": a whole-number dial


@dataclass(frozen=True)
class Trajectory:
    """A labelled course. severity(i) in 0..1 is the ground truth: 0 = this person's usual, 1 = fully unwell."""

    name: str
    days: int = 60
    severity: Callable[[int, int], float] = lambda i, onset: 0.0
    onset_range: tuple[int, int] | None = None
    noise: float = 1.0
    capture: float = 1.0
    outliers: float = 0.03
    weekend: bool = False  # signals shift on Saturday/Sunday although the person is fine
    broken_from: int | None = None  # one signal reads far off from this day on (a sensor, not the person)
    lose_source_from: int | None = None  # one source stops sending from this day on
    dropout: bool = False  # the daily check-in gets skipped more as severity rises
    phq: bool = True
    watch_p: float = 0.5  # share of people who wear a watch
    note: str = ""

    @property
    def unwell(self) -> bool:
        return self.onset_range is not None


def _ramp(length: int) -> Callable[[int, int], float]:
    return lambda i, onset: 0.0 if i < onset else min(1.0, (i - onset + 1) / length)


def _step(i: int, onset: int) -> float:
    return 1.0 if i >= onset else 0.0


def _dip(length: int) -> Callable[[int, int], float]:
    return lambda i, onset: 1.0 if onset <= i < onset + length else 0.0


def _recover(i: int, onset: int) -> float:
    """Sudden drop for 10 days, then a 5-day return to usual (e.g. after a care action)."""
    if i < onset:
        return 0.0
    return 1.0 if i < onset + 10 else max(0.0, 1.0 - (i - onset - 9) / 5)


def _bad_start(i: int, onset: int) -> float:
    """Unwell during the first fortnight (the baseline period), fine afterwards, then a sudden drop at onset."""
    return 1.0 if i < 14 or i >= onset else 0.0


FINE: tuple[Trajectory, ...] = (
    Trajectory("stable"),
    Trajectory("noisy but fine", noise=1.8, capture=0.8, outliers=0.10),
    Trajectory("weekday pattern, fine", weekend=True),
    Trajectory("one broken sensor, fine", broken_from=32),
    Trajectory("one source goes silent, fine", lose_source_from=35),
)
UNWELL: tuple[Trajectory, ...] = (
    Trajectory("gradual decline (14-day slide)", severity=_ramp(14), onset_range=(30, 38)),
    Trajectory("sudden drop, stays low", severity=_step, onset_range=(30, 38)),
    Trajectory("short dip (4 days)", severity=_dip(4), onset_range=(30, 45)),
    Trajectory("decline with fewer check-ins", severity=_ramp(14), onset_range=(30, 38), dropout=True),
    Trajectory("drop, then recovery", severity=_recover, onset_range=(30, 36)),
    Trajectory("bad first fortnight, later drop", severity=_bad_start, onset_range=(36, 42)),
    Trajectory("no questionnaire, sudden drop", severity=_step, onset_range=(30, 38), phq=False),
)
# The demo point: a 16-day record. Day numbers are 1-based in the names, 0-based in the code.
SHORT: tuple[Trajectory, ...] = (
    Trajectory("16 days, fine", days=16),
    Trajectory("16 days, dip on days 9–12", days=16, severity=_dip(4), onset_range=(8, 8)),
    Trajectory("16 days, low from day 9 on", days=16, severity=_step, onset_range=(8, 8)),
)


@dataclass
class Person:
    data: PatientData
    severity: list[float]
    onset: int | None
    has_watch: bool
    broken: str | None = None
    lost: str | None = None


def _sparse(m: MetricSpec, crit: Criteria) -> bool:
    """A metric that declares a smaller baseline_min_days than the default is captured on fewer days."""
    return m.baseline_min_days is not None and m.baseline_min_days < crit.defaults.baseline_min_days


def simulate_person(traj: Trajectory, crit: Criteria, seed: int, effect: float = 2.0, home_id: str = "cal"
                    ) -> Person:
    """One synthetic person-record as PatientData. Deterministic for (trajectory, criteria metric names, seed)."""
    rng = random.Random(f"{traj.name}|{seed}")
    onset = rng.randint(*traj.onset_range) if traj.onset_range else None
    sev = [traj.severity(i, onset) if onset is not None else 0.0 for i in range(traj.days)]
    has_watch = rng.random() < traj.watch_p
    sources = [s for s in crit.active_sources() if crit.metrics_for(s) and (s != "wearable" or has_watch)]
    metrics = [m for s in sources for m in crit.metrics_for(s) if m.weight > 0]
    lost = rng.choice(sources) if traj.lose_source_from is not None else None
    broken = rng.choice(metrics).name if traj.broken_from is not None and metrics else None

    series: dict[str, dict[date, float]] = {}
    source_days: dict[str, dict[date, list[float]]] = {s: {} for s in CONSENSUS_SOURCES}
    captured: dict[str, set[int]] = {}
    for s in sources:
        p = min(0.95, crit.sources[s].expected_per_week / 7 * 1.15) * traj.capture
        days_s = set()
        for i in range(traj.days):
            if lost == s and i >= (traj.lose_source_from or 0):
                continue
            p_i = p * (1 - 0.7 * sev[i]) if traj.dropout and crit.sources[s].expected_per_week >= 7 else p
            if rng.random() < p_i:
                days_s.add(i)
                source_days[s][START + timedelta(days=i)] = [0.9]
        captured[s] = days_s

    for s in sources:
        for m in crit.metrics_for(s):
            floor = float(crit.param(m, "min_mad")) or 1.0
            sd = floor * rng.uniform(0.6, 1.6) * traj.noise  # this person's own day-to-day spread
            sign = 1.0 if m.worse_when == "up" else -1.0
            load = effect * rng.uniform(0.6, 1.4) if rng.random() < RESPOND_P else 0.0
            wk = rng.choice((-1.5, 0.0, 1.5)) * sd if traj.weekend else 0.0
            scale = _SCALE_UNIT.match(m.unit)
            lo, hi = (float(scale.group(1)), float(scale.group(2))) if scale else (None, None)
            base = rng.uniform(lo + 0.55 * (hi - lo), lo + 0.8 * (hi - lo)) if scale else 0.0
            p_metric = 0.6 if _sparse(m, crit) else 0.97
            out: dict[date, float] = {}
            ar = 0.0
            for i in range(traj.days):
                ar = 0.3 * ar + rng.gauss(0, sd) * 0.954  # AR(1), rho 0.3, stationary SD = sd
                noise = ar * (3.0 if rng.random() < traj.outliers else 1.0)
                day = START + timedelta(days=i)
                v = base + noise + sign * load * sd * sev[i] + (wk if day.weekday() >= 5 else 0.0)
                if broken == m.name and i >= (traj.broken_from or 0):
                    v = base + sign * 6.0 * sd
                if scale:
                    v = float(min(hi, max(lo, round(v))))
                if i in captured[s] and rng.random() < p_metric:
                    out[day] = v
            if out:
                series[m.name] = out

    rules: dict[str, list[Reading]] = {}
    phq_rules = [r for r in crit.rules if r.enabled and r.obs == "obs.phq9" and r.source in sources]
    if traj.phq and phq_rules:
        base = rng.uniform(3, 7)
        first = rng.randrange(PHQ_EVERY)
        pts = []
        for i in range(first, traj.days, PHQ_EVERY):
            day = START + timedelta(days=i)
            total = min(27.0, max(0.0, round(base + PHQ_POINTS_PER_SD * effect * sev[i] + rng.gauss(0, 1.5))))
            pts.append(Reading(datetime.combine(day, time(19), UTC), day, total))
            source_days[phq_rules[0].source].setdefault(day, [0.9])
        for r in phq_rules:
            rules[r.name] = pts

    data = PatientData(home_id=home_id, series=series, source_days=source_days, last_data_at={},
                       rule_readings=rules, safety_flags=[], acks=[], last_activity_at=None, sim=True,
                       first_day=START)
    return Person(data, sev, onset, has_watch, broken, lost)


def run_person(p: Person, crit: Criteria) -> dict[int, DayResult]:
    end = START + timedelta(days=len(p.severity) - 1)
    res = replay(p.data, crit, end, now=datetime.combine(end, time(23, 59), UTC))
    return {(r.day - START).days: r for r in res}


def _flag(r: DayResult) -> bool:
    return r.state == "needs_call" or any(v.verdict == "worse" for v in r.verdicts)


@dataclass
class Cell:
    """Scores for one trajectory (x effect size)."""

    trajectory: str
    effect: str | None
    n: int = 0
    fine_days: int = 0
    fine_flag_days: int = 0
    false_flags: int = 0
    false_calls: int = 0
    thin_days: int = 0
    scored_days: int = 0
    episodes: int = 0
    found_flag: int = 0
    found_call: int = 0
    delays_flag: list[int] = field(default_factory=list)
    delays_call: list[int] = field(default_factory=list)
    clear_days: list[int] = field(default_factory=list)
    final: dict[str, int] = field(default_factory=dict)

    def add(self, p: Person, res: dict[int, DayResult]) -> None:
        self.n += 1
        sev = p.severity
        last_unwell = -10**6
        prev_flag = prev_call = False
        for i in sorted(res):
            r = res[i]
            if sev[i] > 0:
                last_unwell = i
            fine = sev[i] == 0 and i - last_unwell > COOL_DOWN
            flag, call = _flag(r), r.state == "needs_call"
            self.scored_days += 1
            self.thin_days += r.agreement == "low_coverage"
            if fine:
                self.fine_days += 1
                self.fine_flag_days += flag
                self.false_flags += flag and not prev_flag
                self.false_calls += call and not prev_call
            prev_flag, prev_call = flag, call
        last = res[max(res)]
        self.final[last.state] = self.final.get(last.state, 0) + 1
        if p.onset is None:
            return
        self.episodes += 1
        unwell = [i for i in res if sev[i] > 0 and i >= p.onset]
        if not unwell:
            return
        until = min(max(unwell) + 3, p.onset + DETECT_WINDOW)
        window = [i for i in sorted(res) if p.onset <= i <= until]
        first_flag = next((i for i in window if _flag(res[i])), None)
        first_call = next((i for i in window if res[i].state == "needs_call"), None)
        if first_flag is not None:
            self.found_flag += 1
            self.delays_flag.append(first_flag - p.onset)
        if first_call is not None:
            self.found_call += 1
            self.delays_call.append(first_call - p.onset)
        back = max(unwell) + 1  # first day back at the person's usual
        if first_flag is not None and back in res:
            clear = next((i for i in sorted(res) if i >= back and not _flag(res[i])), None)
            if clear is not None:
                self.clear_days.append(clear - back)

    def summary(self) -> dict[str, Any]:
        weeks = self.fine_days / 7
        return {
            "trajectory": self.trajectory, "effect": self.effect, "people": self.n,
            "false_flags_per_person_week": round(self.false_flags / weeks, 3) if weeks else None,
            "false_calls_per_person_week": round(self.false_calls / weeks, 3) if weeks else None,
            "specificity_days": round(1 - self.fine_flag_days / self.fine_days, 3) if self.fine_days else None,
            "thin_data_days": round(self.thin_days / self.scored_days, 3) if self.scored_days else None,
            "sensitivity_flag": round(self.found_flag / self.episodes, 3) if self.episodes else None,
            "sensitivity_call": round(self.found_call / self.episodes, 3) if self.episodes else None,
            "delay_flag_days": float(median(self.delays_flag)) if self.delays_flag else None,
            "delay_call_days": float(median(self.delays_call)) if self.delays_call else None,
            "days_to_clear": float(median(self.clear_days)) if self.clear_days else None,
            "final_state": dict(sorted(self.final.items())),
        }


def run_cell(traj: Trajectory, crit: Criteria, n: int, effect: str | None, seed: int = 0) -> Cell:
    cell = Cell(traj.name, effect)
    for k in range(n):
        p = simulate_person(traj, crit, seed * 100_000 + k, EFFECTS[effect] if effect else 0.0)
        cell.add(p, run_person(p, crit))
    return cell


def early_days(crit: Criteria, n: int, seed: int = 0) -> dict[str, Any]:
    """What a new person's record can say on day 3, 7, 10 and 16, and the first day any source can vote."""
    out: dict[str, Any] = {}
    fine, dip = SHORT[0], SHORT[1]
    first_vote: list[int] = []
    for label, traj in (("fine", fine), ("dip days 9–12 (moderate)", dip)):
        counts: dict[int, dict[str, int]] = {d: {} for d in (3, 7, 10, 12, 14, 16)}
        flagged_ever = 0
        for k in range(n):
            p = simulate_person(traj, crit, seed * 100_000 + k, EFFECTS["moderate"])
            res = run_person(p, crit)
            for d, c in counts.items():
                r = res[d - 1]
                seen = "flagged" if _flag(r) else "not enough data" if r.agreement == "low_coverage" else r.state
                c[seen] = c.get(seen, 0) + 1
            flagged_ever += any(_flag(r) for r in res.values())
            if traj is fine:
                v = next((i + 1 for i in sorted(res)
                          if any(x.verdict != "insufficient" for x in res[i].verdicts)), None)
                if v is not None:
                    first_vote.append(v)
        out[label] = {"practitioner_sees_on_day": {str(d): dict(sorted(c.items())) for d, c in counts.items()},
                      "ever_flagged": round(flagged_ever / n, 3)}
    out["first_day_any_source_can_vote"] = float(median(first_vote)) if first_vote else None
    out["people_with_a_voting_source_by_day_16"] = round(len(first_vote) / n, 3)
    return out


def chance_flag(crit: Criteria, n: int, seed: int = 0) -> float:
    """Share of FINE people flagged at least once in a window as long as the detection window: the level that
    "sensitivity (flag)" has to beat. A sensitivity near this number is no detection at all."""
    hit = 0
    for k in range(n):
        res = run_person(simulate_person(FINE[0], crit, seed * 100_000 + k), crit)
        hit += any(_flag(res[i]) for i in range(34, 34 + DETECT_WINDOW + 1) if i in res)
    return round(hit / n, 3)


def single_metric_flippers(crit: Criteria) -> dict[str, list[str]]:
    """Per source: metrics that can turn the source "worse" on their own (weight >= worse_min_weight)."""
    return {s: [m.name for m in crit.metrics_for(s) if m.weight >= crit.sources[s].worse_min_weight]
            for s in crit.active_sources()}


def bandit_confounding(n: int = 400, seed: int = 0) -> dict[str, float]:
    """Two activities with NO true effect. One happens to be offered on low days, the other on good days.

    Returns the learner's mean reward for each: the gap is pure confounding by the day's level
    (the next-day score is measured against a fixed neutral 3, not against the day the nudge was offered)."""
    from .bandit import posteriors

    rng = random.Random(seed)
    outcomes = []
    mood = 3.5
    for _ in range(n):
        mood = 3.5 + 0.7 * (mood - 3.5) + rng.gauss(0, 0.6)  # slow-moving mood, no effect of any activity
        arm = "breathe" if mood < 3.5 else "drum"
        nxt = 3.5 + 0.7 * (mood - 3.5) + rng.gauss(0, 0.6)
        outcomes.append({"arm": arm, "accepted": True, "next_day": {"mood": min(5, max(1, round(nxt)))}})
    post = posteriors(outcomes)
    return {a: round(post[a][0] / (post[a][0] + post[a][1]), 3) for a in ("breathe", "drum")}


def run_calibration(crit: Criteria | None = None, n: int = 40, seed: int = 0,
                    effects: tuple[str, ...] = ("mild", "moderate", "marked")) -> dict[str, Any]:
    crit = crit or load_criteria()
    fine = [run_cell(t, crit, n, None, seed).summary() for t in FINE]
    unwell = [run_cell(t, crit, n, e, seed).summary() for e in effects for t in UNWELL]
    short = [run_cell(t, crit, n, "moderate" if t.unwell else None, seed).summary() for t in SHORT]
    fa = [c["false_flags_per_person_week"] for c in fine if c["false_flags_per_person_week"] is not None]
    headline: dict[str, Any] = {"false_flags_per_person_week_fine": round(fmean(fa), 3) if fa else None}
    headline["chance_flag_in_detect_window"] = chance_flag(crit, n, seed)
    for e in effects:
        cells = [c for c in unwell if c["effect"] == e]
        headline[f"sensitivity_flag_{e}"] = round(fmean(c["sensitivity_flag"] for c in cells), 3)
        headline[f"sensitivity_call_{e}"] = round(fmean(c["sensitivity_call"] for c in cells), 3)
    return {"rule_version": crit.rule_version, "people_per_cell": n, "seed": seed, "sim": True,
            "assumptions": {"effect_sd": {e: EFFECTS[e] for e in effects}, "signals_that_respond": RESPOND_P,
                            "person_noise_vs_floor": [0.6, 1.6], "autocorrelation": 0.3,
                            "phq9_every_days": PHQ_EVERY, "detect_window_days": DETECT_WINDOW},
            "headline": headline, "fine": fine, "unwell": unwell, "short_history": short,
            "early_days": early_days(crit, n, seed), "single_metric_flippers": single_metric_flippers(crit),
            "bandit_no_effect_arms": bandit_confounding(seed=seed)}


# ------------------------------------------------------------------ CLI (make calibrate)
def _f(v: Any, w: int = 6) -> str:
    return f"{'—':>{w}}" if v is None else f"{v:>{w}.2f}" if isinstance(v, float) else f"{v!s:>{w}}"


def render(r: dict[str, Any]) -> str:
    out = [f"calibration of {r['rule_version']}  ({r['people_per_cell']} synthetic people per row; "
           "not clinical accuracy)", "",
           "People who are fine — how often does the rule raise a flag anyway?",
           f"  {'trajectory':34} {'flags/wk':>8} {'calls/wk':>8} {'spec.':>6} {'thin':>6}  final state"]
    for c in r["fine"] + [c for c in r["short_history"] if c["effect"] is None]:
        out.append(f"  {c['trajectory']:34} {_f(c['false_flags_per_person_week'], 8)} "
                   f"{_f(c['false_calls_per_person_week'], 8)} {_f(c['specificity_days'])} "
                   f"{_f(c['thin_data_days'])}  {c['final_state']}")
    out += ["", "People who are not feeling well — is it found, and how fast?  (flag = worth a check-in, "
            "call = needs a call)",
            f"  {'trajectory':34} {'effect':>8} {'flag':>6} {'call':>6} {'delay':>6} {'d.call':>6} {'clear':>6}"]
    for c in r["unwell"] + [c for c in r["short_history"] if c["effect"] is not None]:
        out.append(f"  {c['trajectory']:34} {c['effect']:>8} {_f(c['sensitivity_flag'])} "
                   f"{_f(c['sensitivity_call'])} {_f(c['delay_flag_days'])} {_f(c['delay_call_days'])} "
                   f"{_f(c['days_to_clear'])}")
    e = r["early_days"]
    out += ["", f"New person: first day any source can vote = {e['first_day_any_source_can_vote']} "
            f"(share with a voting source by day 16: {e['people_with_a_voting_source_by_day_16']})"]
    for label in [k for k in e if isinstance(e[k], dict)]:
        out.append(f"  {label}: ever flagged by day 16 = {e[label]['ever_flagged']}")
        for d, c in e[label]["practitioner_sees_on_day"].items():
            out.append(f"    day {d:>2}: {c}")
    out += ["", f"Signals that can turn a source worse on their own: {r['single_metric_flippers']}",
            f"Learner, two activities with no real effect (mean reward): {r['bandit_no_effect_arms']}",
            "", "headline: " + json.dumps(r["headline"])]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Calibration of the consensus rule on labelled synthetic courses.")
    ap.add_argument("--criteria", help="criteria TOML (default: $KAIKU_CRITERIA or config/criteria.toml)")
    ap.add_argument("--compare", help="second criteria TOML: print both")
    ap.add_argument("--n", type=int, default=40, help="synthetic people per trajectory")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        crits = [load_criteria(a.criteria) if a.criteria else load_criteria()]
        if a.compare:
            crits.append(load_criteria(a.compare))
    except Exception as e:  # FileNotFoundError / ValidationError / TOML error
        print(f"invalid criteria: {e}", file=sys.stderr)
        return 2
    results = [run_calibration(c, a.n, a.seed) for c in crits]
    if a.json:
        print(json.dumps(results[0] if len(results) == 1 else results, indent=1))
    else:
        print("\n\n".join(render(r) for r in results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
