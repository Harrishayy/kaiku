"""Small persistent hub state (JSON file): last arrival, pending nudge, suggested arm, ritual time.

Only derived values live here — never raw media or transcripts.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from kaiku_contracts.jlog import get_logger

log = get_logger("hub")


class HubState:
    def __init__(self, path: Path | None):
        self.path = path
        self.data: dict[str, Any] = {}
        if path and path.is_file():
            try:
                self.data = json.loads(path.read_text())
            except (OSError, ValueError) as e:
                log.warning("state_unreadable", str(e), path=str(path))

    def save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, default=str))
            tmp.replace(self.path)
        except OSError as e:
            log.warning("state_save_failed", str(e))

    # ---------------------------------------------------------------- presence
    @property
    def last_arrival(self) -> datetime | None:
        v = self.data.get("last_arrival")
        return datetime.fromisoformat(v) if v else None

    @last_arrival.setter
    def last_arrival(self, ts: datetime) -> None:
        self.data["last_arrival"] = ts.isoformat()
        self.save()

    # ---------------------------------------------------------------- rituals
    def ritual_done_on(self, day: date) -> bool:
        return self.data.get("last_ritual_date") == day.isoformat()

    def mark_ritual_done(self, day: date) -> None:
        self.data["last_ritual_date"] = day.isoformat()
        self.save()

    @property
    def ritual_time(self) -> str | None:
        return self.data.get("ritual_time")

    @ritual_time.setter
    def ritual_time(self, hhmm: str) -> None:
        self.data["ritual_time"] = hhmm
        self.save()

    # ---------------------------------------------------------------- nudges
    def take_suggested_arm(self) -> str | None:
        arm = self.data.pop("suggested_arm", None)
        if arm:
            self.save()
        return arm

    def suggest_arm(self, arm: str) -> None:
        self.data["suggested_arm"] = arm
        self.save()

    def set_pending_nudge(self, arm: str, accepted: bool, mood: int | None, energy: int | None, day: date) -> None:
        self.data["pending_nudge"] = {"arm": arm, "accepted": accepted, "mood": mood, "energy": energy,
                                      "date": day.isoformat()}
        self.save()

    def record_dial(self, day: date, mood: int | None = None, energy: int | None = None,
                    sleep: int | None = None) -> dict[str, Any] | None:
        """Store today's dial answers. If a nudge from an earlier day is pending, return its nudge_outcome."""
        today = {"date": day.isoformat(), "mood": mood, "energy": energy, "sleep": sleep}
        self.data["last_dial"] = today
        pending = self.data.get("pending_nudge")
        outcome = None
        if pending and pending.get("date") != day.isoformat() and (mood is not None or energy is not None):
            outcome = nudge_outcome(pending, mood, energy)
            self.data.pop("pending_nudge", None)
        self.save()
        return outcome

    def _today_dial(self, key: str, day: date | None = None) -> int | None:
        d = self.data.get("last_dial") or {}
        if day is not None and d.get("date") != day.isoformat():
            return None
        v = d.get(key)
        return int(v) if v is not None else None

    def today_mood(self, day: date) -> int | None:
        return self._today_dial("mood", day)

    def today_energy(self, day: date) -> int | None:
        return self._today_dial("energy", day)

    @property
    def last_mood(self) -> int | None:
        return self._today_dial("mood")

    # ---------------------------------------------------------------- PHQ-9 (spoken mode)
    @property
    def phq9_due(self) -> bool:
        return bool(self.data.get("phq9_due"))

    @phq9_due.setter
    def phq9_due(self, due: bool) -> None:
        self.data["phq9_due"] = bool(due)
        self.save()

    def phq9_done(self, day: date) -> None:
        self.data["phq9_due"] = False
        self.data["last_phq9_date"] = day.isoformat()
        self.save()

    def phq9_is_due(self, day: date, every_days: float) -> bool:
        """Due if the cloud/clinician asked (cmd.hub phq9_due) or the interval since the last one passed."""
        if self.phq9_due:
            return True
        last = self.data.get("last_phq9_date")
        return bool(last) and (day - date.fromisoformat(last)).days >= every_days


def nudge_outcome(pending: dict[str, Any], mood: int | None, energy: int | None) -> dict[str, Any]:
    """Next-day part of the reward in [0,1]: 0 if declined; else 0.5 + 0.125 x mean(mood/energy delta), clipped.
    (The cloud bandit blends this with the immediate intervention_response delta.)"""
    accepted = bool(pending.get("accepted"))
    deltas = [now - before for now, before in ((mood, pending.get("mood")), (energy, pending.get("energy")))
              if now is not None and before is not None]
    if not accepted:
        reward = 0.0
    else:
        delta = sum(deltas) / len(deltas) if deltas else 0.0
        reward = min(1.0, max(0.0, 0.5 + 0.125 * delta))
    next_day = {k: v for k, v in (("mood", mood), ("energy", energy)) if v is not None}
    return {"arm": pending["arm"], "accepted": accepted, "next_day": next_day, "reward": round(reward, 3)}
