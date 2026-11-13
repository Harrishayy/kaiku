"""Synthetic patients across the three sources (all output `sim: true`, labelled SIMULATED in the UI).

A PatientSpec says which sources the person uses (`present`), which of them drift from `onset`
(`drift`), whether robot signals improve instead (`improving`), and an optional PHQ-9 item-9 day (`safety_day`).
`expected_state` is the ground truth the consensus rule should reach — used by the scenario tests and by
jobs/simulate.py. Event ids come from a seeded RNG (not the date), so re-seeding is idempotent.

Producers mirror reality: robot obs source "hub", glasses obs "glasses", laptop obs "laptop".
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from kaiku_contracts import validate
from kaiku_contracts.payloads import NUDGE_ARMS

from ..settings import TZ

CLINICAL_LAG_DAYS = 10  # when a clinician would otherwise notice (lead-time reference)
RAMP_DAYS = 7
ALL = frozenset({"robot", "glasses", "laptop"})


@dataclass(frozen=True)
class PatientSpec:
    home_id: str
    seed: int
    scenario: str
    days: int = 30
    present: frozenset[str] = ALL
    drift: frozenset[str] = frozenset()
    onset: int | None = None  # 0-based day index where drift/improvement starts
    improving: bool = False
    safety_day: int | None = None
    noise: float = 1.0
    p_miss: float = 0.05
    favourite_arm: str = "daylight_walk"

    @property
    def clinical_day(self) -> int | None:
        return None if self.onset is None or not self.drift else self.onset + CLINICAL_LAG_DAYS

    @property
    def expected_state(self) -> str:
        """Ground truth at the end of the trajectory."""
        if self.safety_day is not None:
            return "safety"
        drifting = len(self.drift & self.present)
        if drifting >= 2:
            return "needs_call"
        if drifting == 1 or len(self.present) < 2:
            return "watch"
        return "stable"

    def truth_on(self, i: int, grace: int = 5) -> str | None:
        """Ground truth on day i (None = ambiguous ramp-up window, not scored)."""
        if self.safety_day is not None and i >= self.safety_day:
            return "safety"
        if len(self.present) < 2:
            return "watch"
        if self.onset is not None and self.drift and i >= self.onset:
            return None if i < self.onset + grace else self.expected_state
        return "stable"


DEMO_PATIENTS: tuple[PatientSpec, ...] = (
    PatientSpec("demo-aino", 11, "robot+laptop drift, glasses as usual", drift=frozenset({"robot", "laptop"}),
                onset=17, favourite_arm="daylight_walk"),
    PatientSpec("sim-eero", 12, "stable", favourite_arm="drum"),
    PatientSpec("sim-juho", 21, "noisy but fine", noise=1.6, p_miss=0.15, favourite_arm="breathe"),
    PatientSpec("sim-helmi", 13, "robot-only drift", drift=frozenset({"robot"}), onset=18, favourite_arm="friend_ping"),
    PatientSpec("sim-kaisa", 15, "low coverage (robot only)", present=frozenset({"robot"}), favourite_arm="breathe"),
    PatientSpec("sim-lauri", 16, "PHQ-9 item 9 positive", safety_day=27, favourite_arm="icbt_exercise"),
    PatientSpec("sim-mirja", 17, "glasses-only drift", drift=frozenset({"glasses"}), onset=17, favourite_arm="drum"),
    PatientSpec("sim-onni", 18, "improving", improving=True, onset=12, favourite_arm="daylight_walk"),
)


def _sim_id(rng: random.Random) -> UUID:
    return UUID(int=rng.getrandbits(128), version=4)


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _phq_items(total: int, item9: int, rng: random.Random) -> list[int]:
    items = [0] * 9
    items[8] = item9
    left = max(0, total - item9)
    while left > 0:
        k = rng.randrange(8)
        if items[k] < 3:
            items[k] += 1
            left -= 1
        elif all(items[j] == 3 for j in range(8)):
            break
    return items


def generate(spec: PatientSpec, end: date | None = None) -> list[dict[str, Any]]:
    """Validated obs envelopes (json-mode dicts) for `spec.days` days ending on `end` (default YESTERDAY, Helsinki).

    Yesterday, not today: today's simulated morning could still be in the future, and live data from the hub and
    apps should be the newest thing on the dashboard. Deterministic (no dependence on the time of day)."""
    rng = random.Random(spec.seed)
    end = end or (datetime.now(TZ).date() - timedelta(days=1))
    start = end - timedelta(days=spec.days - 1)
    n = spec.noise
    b = {  # individual baselines
        "mood": rng.uniform(3.4, 4.0), "energy": rng.uniform(3.2, 3.9), "sleep": rng.uniform(3.3, 4.0),
        "rmssd": rng.uniform(30, 48), "hr": rng.uniform(58, 72), "tempo": rng.uniform(92, 112),
        "force": rng.uniform(0.5, 0.65), "getup": rng.uniform(6.5 * 60, 8 * 60), "light": rng.uniform(200, 320),
        "syll": rng.uniform(3.8, 4.6), "pause": rng.uniform(0.15, 0.24), "outing": rng.uniform(30, 50),
        "lt_syll": rng.uniform(3.6, 4.4), "lt_pause": rng.uniform(0.16, 0.26), "pitch": rng.uniform(2.2, 3.2),
        "expr": rng.uniform(0.5, 0.7), "rt": rng.uniform(280, 340), "phq9": rng.randint(3, 6),
    }
    events: list[dict[str, Any]] = []

    def emit(type_: str, payload: dict[str, Any], local_dt: datetime, source: str) -> None:
        env = validate({"id": str(_sim_id(rng)), "ts": local_dt.astimezone(UTC), "home_id": spec.home_id,
                        "source": source, "type": type_, "payload": payload, "sim": True,
                        "quality": round(rng.uniform(0.75, 0.98), 2)})
        events.append(env.model_dump(mode="json", exclude_none=True))

    def ramp(i: int, source: str) -> float:
        if spec.onset is None or i < spec.onset or source not in spec.drift:
            return 0.0
        return min(1.0, (i - spec.onset + 1) / RAMP_DAYS)

    prev_offer: str | None = None
    prev_activity = 0.0
    for i in range(spec.days):
        day = start + timedelta(days=i)
        rr, rg, rl = ramp(i, "robot"), ramp(i, "glasses"), ramp(i, "laptop")
        imp = min(1.0, (i - spec.onset + 1) / RAMP_DAYS) if spec.improving and spec.onset is not None and i >= spec.onset \
            else 0.0

        def g(sd: float) -> float:
            return rng.gauss(0, sd * n)

        def at(minutes: float, day: date = day) -> datetime:
            minutes = _clip(minutes, 0, 23 * 60 + 59)
            return datetime.combine(day, time(int(minutes // 60), int(minutes % 60)), TZ)

        mood = int(round(_clip(b["mood"] - 1.6 * rr + 0.9 * imp + g(0.4), 1, 5)))
        energy = int(round(_clip(b["energy"] - 1.5 * rr + 0.9 * imp + g(0.4), 1, 5)))
        outing_today = 0.0

        # ---------------------------------------------------------------- robot (source 1)
        if "robot" in spec.present:
            if prev_offer is not None:  # yesterday's nudge, scored with today's dial
                fav = prev_offer == spec.favourite_arm
                accepted = rng.random() < (0.8 if fav else 0.35) * (1 - 0.4 * rr)
                emit("obs.nudge_outcome", {"arm": prev_offer, "accepted": accepted,
                                           "next_day": {"mood": mood, "energy": energy,
                                                        "activity": round(prev_activity, 1)}}, at(6 * 60), "hub")
                prev_offer = None
            light = _clip(b["light"] - 150 * rr + 60 * imp + g(30), 5, 2000)
            emit("obs.light_level", {"lux_est": round(light, 1), "window_min": 60.0}, at(12 * 60), "hub")
            if rng.random() >= spec.p_miss + 0.2 * rr:
                getup = b["getup"] + 80 * rr - 30 * imp + g(15)
                emit("obs.presence", {"distance_cm": round(_clip(55 + g(8), 20, 150), 1), "first_of_day": True,
                                      "dwell_s": round(_clip(20 + g(6), 3, 120), 1)}, at(getup), "hub")
                t0 = getup + 10 + abs(g(10))
                sleep = int(round(_clip(b["sleep"] - 1.5 * rr + 0.8 * imp + g(0.4), 1, 5)))
                for k, (item, v) in enumerate((("mood", mood), ("energy", energy), ("sleep", sleep))):
                    emit("obs.self_report", {"item": item, "value": v, "context": "ritual"}, at(t0 + 1 + k * 0.2), "hub")
                rm_pre = _clip(b["rmssd"] - 14 * rr + 8 * imp + g(3), 8, 120)
                rm_post = rm_pre * rng.uniform(1.05, 1.3)
                emit("obs.hrv_session", {"hr_bpm": round(_clip(b["hr"] + 7 * rr - 3 * imp + g(2), 40, 130), 1),
                                         "rmssd_pre_ms": round(rm_pre, 1), "rmssd_post_ms": round(rm_post, 1),
                                         "duration_s": 90.0, "breath_bpm": 6.0}, at(t0 + 3), "hub")
                emit("obs.intervention_response", {"activity": "breathe", "pre": {"rmssd_ms": round(rm_pre, 1)},
                                                   "post": {"rmssd_ms": round(rm_post, 1)},
                                                   "delta": {"rmssd_ms": round(rm_post - rm_pre, 1)}}, at(t0 + 4), "hub")
                taps = int(_clip(70 - 30 * rr + 15 * imp + g(8), 1, 300))
                emit("obs.drum_session", {"tempo_bpm": round(_clip(b["tempo"] - 25 * rr + 12 * imp + g(5), 30, 220), 1),
                                          "force_mean": round(_clip(b["force"] - 0.2 * rr + 0.1 * imp + g(0.04), 0, 1), 3),
                                          "duration_s": round(_clip(45 - 15 * rr + g(5), 5, 90), 1),
                                          "regularity": round(_clip(0.8 - 0.2 * rr + g(0.05), 0, 1), 3),
                                          "taps": taps}, at(t0 + 5), "hub")
                post = int(_clip(mood + (1 if rng.random() < 0.4 else 0), 1, 5))
                emit("obs.intervention_response", {"activity": "drum", "pre": {"mood": mood}, "post": {"mood": post},
                                                   "delta": {"mood": float(post - mood)}}, at(t0 + 6), "hub")
                emit("obs.speech_features", {"syllables_per_s": round(_clip(b["syll"] - 0.9 * rr + 0.3 * imp + g(0.2), 0.5, 8), 2),
                                             "pause_ratio": round(_clip(b["pause"] + 0.14 * rr - 0.04 * imp + g(0.03), 0, 1), 3),
                                             "duration_s": 30.0}, at(t0 + 6.5), "hub")
                weights = [3 if a == spec.favourite_arm else 1 for a in NUDGE_ARMS]
                arm = rng.choices(NUDGE_ARMS, weights=weights)[0]
                emit("obs.nudge_offered", {"arm": arm, "reason": "Suggested by the learner from past outcomes."},
                     at(t0 + 7), "hub")
                prev_offer = arm
                emit("obs.ritual", {"step": "close", "status": "completed", "duration_s": round(180 + g(30), 1)},
                     at(t0 + 8), "hub")
                if rng.random() < 0.15 * (1 - rr):
                    emit("obs.friend_link", {"direction": "sent", "ack": True}, at(t0 + 9), "hub")

        # ---------------------------------------------------------------- glasses (source 2)
        if "glasses" in spec.present and rng.random() < 0.65 - 0.3 * rg:
            minutes = _clip(b["outing"] - 25 * rg + 8 * imp + g(8), 2, 240)
            outing_today = minutes
            steps = int(_clip(minutes * rng.uniform(90, 110) - 900 * rg + g(150), 0, 40000))
            emit("obs.outing", {"minutes": round(minutes, 1), "steps": steps, "method": "location"},
                 at(15 * 60 + g(60)), "glasses")
            if rng.random() < 0.5:
                pre = int(_clip(mood, 1, 5))
                post = int(_clip(pre + (1 if rng.random() < 0.5 - 0.3 * rg else 0), 1, 5))
                emit("obs.intervention_response", {"activity": "walk", "pre": {"mood": pre}, "post": {"mood": post},
                                                   "delta": {"mood": float(post - pre)}}, at(15 * 60 + 50), "glasses")
        prev_activity = outing_today

        # ---------------------------------------------------------------- laptop (source 3)
        if "laptop" in spec.present:
            if rng.random() < 0.7:
                emit("obs.laptop_session", {
                    "speech_rate": round(_clip(b["lt_syll"] - 0.8 * rl + g(0.18), 0.5, 8), 2),
                    "pause_ratio": round(_clip(b["lt_pause"] + 0.12 * rl + g(0.025), 0, 1), 3),
                    "pitch_variability": round(_clip(b["pitch"] - 0.9 * rl + g(0.2), 0, 10), 2),
                    "expressivity_index": round(_clip(b["expr"] - 0.2 * rl + g(0.04), 0, 1), 3),
                    "reaction_ms_median": round(_clip(b["rt"] + 80 * rl + g(15), 150, 1500), 1),
                    "reaction_ms_iqr": round(_clip(60 + 30 * rl + g(8), 5, 500), 1),
                    "lapses": int(_clip(round(1 + 3 * rl + g(0.7)), 0, 30)),
                    "duration_s": round(_clip(120 + g(8), 60, 200), 1)}, at(20 * 60 + g(30)), "laptop")
            phq_day = i % 14 == 1
            if phq_day or (spec.safety_day is not None and i == spec.safety_day):
                item9 = 1 if spec.safety_day is not None and i == spec.safety_day else 0
                total = int(round(_clip(b["phq9"] + 10 * rl + 6 * item9 + g(1.0), item9, 27)))
                emit("obs.phq9", {"total": total, "items": _phq_items(total, item9, rng), "item9_positive": bool(item9),
                                  "mode": "laptop"}, at(19 * 60), "laptop")
                if item9:
                    emit("obs.safety_flag", {"trigger": "phq9_item9", "severity": "high", "handled_locally": True},
                         at(19 * 60 + 1), "laptop")

    events.sort(key=lambda e: e["ts"])
    return events


SCENARIOS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("stable", {}),
    ("noisy", {"noise": 1.6, "p_miss": 0.15}),
    ("robot+laptop drift", {"drift": frozenset({"robot", "laptop"})}),
    ("robot+glasses drift", {"drift": frozenset({"robot", "glasses"})}),
    ("glasses+laptop drift", {"drift": frozenset({"glasses", "laptop"})}),  # robot steady: needs_call without it
    ("robot-only drift", {"drift": frozenset({"robot"})}),
    ("laptop-only drift", {"drift": frozenset({"laptop"})}),
    ("low coverage", {"present": frozenset({"robot"})}),
    ("improving", {"improving": True}),
    ("safety", {}),
)


def cohort(n: int, seed: int, days: int = 45) -> list[PatientSpec]:
    """Mixed evaluation cohort cycling through SCENARIOS with random onsets."""
    rng = random.Random(seed)
    out = []
    for k in range(n):
        name, kw = SCENARIOS[k % len(SCENARIOS)]
        onset = rng.randint(22, days - 12) if (kw.get("drift") or kw.get("improving")) else None
        safety_day = rng.randint(25, days - 3) if name == "safety" else None
        out.append(PatientSpec(f"eval-{seed}-{k}", seed * 1000 + k, name, days=days, onset=onset,
                               safety_day=safety_day, favourite_arm=rng.choice(NUDGE_ARMS), **kw))
    return out
