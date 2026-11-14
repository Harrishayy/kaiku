"""Synthetic patients across the four sources (all output `sim: true`, labelled SIMULATED in the UI).

A PatientSpec says which sources the person uses (`present`), which of them drift from `onset`
(`drift`), which show only a small half-weight change that should NOT tip that source's vote (`subtle`),
whether signals improve instead (`improving`), and an optional PHQ-9 item-9 day (`safety_day`).
`expected_state` is the ground truth the consensus rule should reach — used by the scenario tests and by
jobs/simulate.py. Event ids come from a seeded RNG (not the date), so re-seeding is idempotent.

Producers mirror reality: robot obs source "hub", glasses obs "glasses", laptop obs "laptop" (Mac app: screen
activity; games on the Mac/web), phone obs "phone" (wearable_daily; games on the iPhone).
The plan-02 signals (screen_activity, play_session, wearable_daily, the extended outing fields) draw from a SECOND
seeded RNG, so every plan-01 event — and its id — is unchanged (re-seeding stays idempotent).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from kaiku_contracts import validate

from ..analytics.bandit import enabled_arms
from ..settings import TZ

NUDGE_ARMS = enabled_arms()

CLINICAL_LAG_DAYS = 10  # when a clinician would otherwise notice (lead-time reference)
RAMP_DAYS = 7
ALL = frozenset({"robot", "glasses", "laptop", "wearable"})
NO_WATCH = frozenset({"robot", "glasses", "laptop"})


@dataclass(frozen=True)
class PatientSpec:
    home_id: str
    seed: int
    scenario: str
    days: int = 30
    present: frozenset[str] = ALL
    drift: frozenset[str] = frozenset()
    subtle: frozenset[str] = frozenset()  # only half-weight signals drift (e.g. cadence): visible, not a vote
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
    PatientSpec("demo-aino", 11, "robot+laptop+watch drift, glasses as usual (cadence a little lower)",
                drift=frozenset({"robot", "laptop", "wearable"}), subtle=frozenset({"glasses"}), onset=17,
                favourite_arm="daylight_walk"),
    PatientSpec("sim-eero", 12, "stable, no watch", present=NO_WATCH, favourite_arm="drum"),
    PatientSpec("sim-juho", 21, "noisy but fine", noise=1.6, p_miss=0.15, favourite_arm="breathe"),
    PatientSpec("sim-helmi", 13, "robot-only drift", drift=frozenset({"robot"}), onset=18, favourite_arm="friend_ping"),
    PatientSpec("sim-kaisa", 15, "low coverage (robot only)", present=frozenset({"robot"}), favourite_arm="breathe"),
    PatientSpec("sim-lauri", 16, "PHQ-9 item 9 positive", safety_day=27, favourite_arm="icbt_exercise"),
    PatientSpec("sim-mirja", 17, "recent outing decline", drift=frozenset({"glasses"}), onset=20, favourite_arm="drum"),
    PatientSpec("sim-onni", 18, "improving", improving=True, onset=12, favourite_arm="daylight_walk"),
)

# A demo opens after baseline collection, with mostly complete ordinary records. Keep the deliberately
# noisy and low-coverage examples for explicit edge-case review, rather than making every chart thin.
DEMO_PATIENTS = tuple(replace(p, days=45,
                             onset=p.onset + 15 if p.onset is not None else None,
                             safety_day=p.safety_day + 15 if p.safety_day is not None else None,
                             p_miss=p.p_miss if p.home_id == "sim-juho" else 0.0,
                             noise=p.noise if p.home_id == "sim-juho" else 0.6)
                      for p in DEMO_PATIENTS)


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
    r2 = random.Random(spec.seed * 7919 + 17)  # plan-02 signals only (keeps plan-01 events identical)
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
    b2 = {  # plan-02 baselines
        "late": r2.uniform(0, 5), "active": r2.uniform(260, 420), "comm": r2.uniform(45, 90),
        "ff_rt": r2.uniform(300, 360), "sleep": r2.uniform(400, 470), "mid": r2.uniform(150, 230),
        "rhr": r2.uniform(56, 68), "hrv": r2.uniform(35, 60), "steps": r2.uniform(5000, 9000),
        "cad": r2.uniform(100, 112), "sun": r2.uniform(0.5, 0.8),
    }
    events: list[dict[str, Any]] = []

    def emit(type_: str, payload: dict[str, Any], local_dt: datetime, source: str, r: random.Random = rng) -> None:
        env = validate({"id": str(_sim_id(r)), "ts": local_dt.astimezone(UTC), "home_id": spec.home_id,
                        "source": source, "type": type_, "payload": payload, "sim": True,
                        "quality": round(r.uniform(0.75, 0.98), 2)})
        # The demo mirrors currently supported capture. Preserve RNG consumption for reproducibility,
        # but never invent fitted light/force, validated pulse, retired browser tasks or glasses camera data.
        if type_ in {"obs.light_level", "obs.laptop_session", "obs.hrv_session", "obs.friend_link"}:
            return
        if type_ == "obs.intervention_response" and payload.get("activity") == "breathe":
            return
        row = env.model_dump(mode="json", exclude_none=True)
        if type_ == "obs.drum_session":
            row["payload"].pop("force_mean", None)
        if type_ == "obs.outing":
            for field in ("daylight_min", "cadence_spm", "gait_regularity", "head_up_ratio"):
                row["payload"].pop(field, None)
            row["payload"]["method"] = "steps"
        events.append(row)

    def ramp(i: int, source: str) -> float:
        if spec.onset is None or i < spec.onset or source not in spec.drift | spec.subtle:
            return 0.0
        return min(1.0, (i - spec.onset + 1) / RAMP_DAYS)

    prev_offer: str | None = None
    prev_activity = 0.0
    for i in range(spec.days):
        day = start + timedelta(days=i)
        rr, rl, rw = ramp(i, "robot"), ramp(i, "laptop"), ramp(i, "wearable")
        rg = 0.0 if "glasses" in spec.subtle else ramp(i, "glasses")
        rs = ramp(i, "glasses") if "glasses" in spec.subtle else 0.0  # subtle: cadence etc. only
        imp = min(1.0, (i - spec.onset + 1) / RAMP_DAYS) if spec.improving and spec.onset is not None and i >= spec.onset \
            else 0.0

        def g(sd: float) -> float:
            return rng.gauss(0, sd * n)

        def g2(sd: float) -> float:
            return r2.gauss(0, sd * n)

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
            cadence = _clip(b2["cad"] - 9 * rg - 8 * rs + 2 * imp + g2(2.0), 40, 160)
            daylight = _clip(minutes * b2["sun"] - 10 * rg + g2(3.0), 0, minutes)
            emit("obs.outing", {"minutes": round(minutes, 1), "steps": steps, "method": "dat_imu",
                                "cadence_spm": round(cadence, 1), "daylight_min": round(daylight, 1),
                                "gait_regularity": round(_clip(0.82 - 0.1 * (rg + rs) + g2(0.04), 0, 1), 3),
                                "head_up_ratio": round(_clip(0.62 - 0.15 * (rg + rs) + g2(0.05), 0, 1), 3)},
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

        # ---------------------------------------------------------------- plan 02: Mac usage rhythm + games (laptop)
        if "laptop" in spec.present:
            if r2.random() < 0.9:  # Mac used that day (blocks instead of hourly, to keep the simulation fast)
                late = max(0.0, r2.gauss(b2["late"], 4 * n) + 50 * rl)
                emit("obs.screen_activity", _screen_block(300, late, 0.0, late, r2), at(5 * 60), "laptop", r2)
                active = _clip(b2["active"] * (1 - 0.3 * rl) + 15 * imp + g2(30), 20, 900)
                comm = _clip(b2["comm"] * (1 - 0.55 * rl) + g2(8), 0, active)
                for end_min, period, share in ((13 * 60, 240, 0.4), (18 * 60, 300, 0.35), (23 * 60 + 55, 355, 0.25)):
                    emit("obs.screen_activity", _screen_block(period, active * share, comm * share, 0.0, r2),
                         at(end_min), "laptop", r2)
            if r2.random() < 0.5:
                dev = r2.choice(("phone", "mac", "web"))
                emit("obs.play_session", {
                    "game": "firefly", "device": dev, "duration_s": 60.0,
                    "reaction_ms_median": round(_clip(b2["ff_rt"] + 70 * rl - 10 * imp + g2(15), 150, 1500), 1),
                    "reaction_ms_iqr": round(_clip(55 + 25 * rl + g2(8), 5, 500), 1),
                    "lapses": int(_clip(round(1 + 2 * rl + g2(0.7)), 0, 30)),
                    "false_taps": int(_clip(round(0.5 + rl + g2(0.6)), 0, 30))},
                     at(20 * 60 + 40), "phone" if dev == "phone" else "laptop", r2)

        # ---------------------------------------------------------------- plan 02: watch summary (wearable, source 4)
        if "wearable" in spec.present and r2.random() < 0.92:
            emit("obs.wearable_daily", {
                "date": day.isoformat(),
                "sleep_min": round(_clip(b2["sleep"] - 70 * rw + 20 * imp + g2(25), 60, 900), 0),
                "sleep_midpoint_min": round(_clip(b2["mid"] + 80 * rw - 10 * imp + g2(15), -720, 720), 0),
                "sleep_regularity": round(_clip(0.8 - 0.2 * rw + g2(0.05), 0, 1), 2),
                "resting_hr_bpm": round(_clip(b2["rhr"] + 5 * rw - 2 * imp + g2(1.5), 35, 120), 1),
                "hrv_sdnn_ms": round(_clip(b2["hrv"] - 11 * rw + 4 * imp + g2(3.5), 5, 200), 1),
                "steps": int(_clip(b2["steps"] - 2800 * rw + 600 * imp + g2(700), 0, 60000)),
                "exercise_min": round(_clip(25 - 12 * rw + g2(8), 0, 300), 0),
                "device": "apple_watch"}, at(7 * 60 + 30), "phone", r2)

    events.sort(key=lambda e: e["ts"])
    return events


def _screen_block(period: float, active: float, comm: float, late: float, r: random.Random) -> dict[str, Any]:
    """One obs.screen_activity period; the other categories split the non-communication active minutes."""
    active = _clip(active, 0, period)
    comm = _clip(comm, 0, active)
    rest = active - comm
    split = {"work": 0.5, "social": 0.12, "video": 0.2, "news": 0.08, "games": 0.03, "other": 0.07}
    cats = {k: round(rest * v, 1) for k, v in split.items()}
    cats["communication"] = round(comm, 1)
    return {"period_min": float(period), "active_min": round(active, 1),
            "late_night_min": round(_clip(late, 0, period), 1), "category_min": cats,
            "switches_per_hour": round(_clip(r.gauss(16, 4), 0, 120), 1),
            "longest_stretch_min": round(min(active, _clip(r.gauss(35, 10), 0, period)), 1),
            "breaks": int(_clip(round(r.gauss(active / 60, 1)), 0, 60)), "paused": False}


SCENARIOS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("stable", {}),
    ("noisy", {"noise": 1.6, "p_miss": 0.15}),
    ("robot+laptop drift", {"drift": frozenset({"robot", "laptop"})}),
    ("robot+glasses drift", {"drift": frozenset({"robot", "glasses"})}),
    ("glasses+laptop drift", {"drift": frozenset({"glasses", "laptop"})}),  # robot steady: needs_call without it
    ("robot+wearable drift", {"drift": frozenset({"robot", "wearable"})}),
    ("robot-only drift", {"drift": frozenset({"robot"})}),
    ("wearable-only drift", {"drift": frozenset({"wearable"})}),
    ("laptop-only drift", {"drift": frozenset({"laptop"})}),
    ("low coverage", {"present": frozenset({"robot"})}),
    ("stable, no watch", {"present": NO_WATCH}),
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
