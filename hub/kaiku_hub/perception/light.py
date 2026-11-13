"""Room light -> windowed mean lux (curtains-closed days show up as low daytime lux)."""

from __future__ import annotations

from datetime import datetime, timedelta


class LightAggregator:
    def __init__(self, window_min: float = 60):
        self.window = timedelta(minutes=window_min)
        self.window_min = window_min
        self._start: datetime | None = None
        self._values: list[float] = []

    def add(self, lux: float, now: datetime) -> dict | None:
        """Returns an obs.light_level payload when a window closes."""
        out = None
        if self._start is not None and now - self._start >= self.window and self._values:
            out = {"lux_est": round(sum(self._values) / len(self._values), 1), "window_min": self.window_min}
            self._values = []
            self._start = None
        if self._start is None:
            self._start = now
        self._values.append(max(0.0, float(lux)))
        return out
