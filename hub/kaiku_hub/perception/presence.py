"""Distance -> presence episodes. Arrival (confirmed near for `confirm_s`) yields an obs.presence payload.

first_of_day: first arrival on a new local calendar day after >= `first_of_day_after_h` hours away
(a get-up-time proxy).
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

import numpy as np


class PresenceTracker:
    def __init__(
        self,
        near_cm: float = 80,
        first_of_day_after_h: float = 4,
        confirm_s: float = 1.0,
        hysteresis_cm: float = 20,
        last_arrival: datetime | None = None,
    ):
        self.near_cm = near_cm
        self.after = timedelta(hours=first_of_day_after_h)
        self.confirm = timedelta(seconds=confirm_s)
        self.hysteresis_cm = hysteresis_cm
        self.last_arrival = last_arrival
        self.present = False
        self.arrived_at: datetime | None = None
        self._window: deque[float] = deque(maxlen=5)
        self._near_since: datetime | None = None
        self._far_since: datetime | None = None

    @property
    def distance(self) -> float | None:
        return float(np.median(self._window)) if self._window else None

    def update(self, cm: float, now: datetime) -> dict | None:
        """Feed one distance reading. Returns an obs.presence payload on confirmed arrival."""
        self._window.append(cm)
        d = self.distance
        assert d is not None
        if not self.present:
            if d < self.near_cm:
                self._near_since = self._near_since or now
                if now - self._near_since >= self.confirm:
                    return self._arrive(d, now)
            else:
                self._near_since = None
        else:
            if d > self.near_cm + self.hysteresis_cm:
                self._far_since = self._far_since or now
                if now - self._far_since >= self.confirm:
                    self.present = False
                    self._far_since = None
                    self._near_since = None
            else:
                self._far_since = None
        return None

    def _arrive(self, d: float, now: datetime) -> dict:
        prev = self.last_arrival
        first = prev is None or (now.astimezone().date() != prev.astimezone().date() and now - prev >= self.after)
        dwell = (now - self._near_since).total_seconds() if self._near_since else 0.0
        self.present = True
        self.arrived_at = now
        self.last_arrival = now
        return {"distance_cm": round(d, 1), "first_of_day": first, "dwell_s": round(dwell, 1)}
