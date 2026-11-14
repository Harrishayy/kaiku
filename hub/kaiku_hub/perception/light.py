"""Room light -> windowed mean lux (curtains-closed days show up as low daytime lux)."""

from __future__ import annotations

from datetime import datetime, timedelta

from kaiku_contracts.config import get


class LightAggregator:
    def __init__(self, window_min: float = 60):
        self.window = timedelta(minutes=window_min)
        self.window_min = window_min
        self._start: datetime | None = None
        self._values: list[float] = []
        self._last: datetime | None = None
        self._quality: list[float] = []
        self.closed_at: datetime | None = None
        self.closed_quality: float | None = None

    def add(self, lux: float, now: datetime, quality: float | None = None) -> dict | None:
        """Returns an obs.light_level payload when a window closes."""
        if self._last is not None and now <= self._last:
            return None
        if quality is not None and quality < float(get("perception", "quality_min", 0.5)):
            return None
        out = None
        if self._start is not None and now - self._start >= self.window and self._values:
            out = {"lux_est": round(sum(self._values) / len(self._values), 1), "window_min": self.window_min}
            self.closed_at = self._last
            self.closed_quality = min(self._quality) if self._quality else None
            self._values = []
            self._quality = []
            self._start = None
        if self._start is None:
            self._start = now
        self._last = now
        if quality is not None:
            self._quality.append(quality)
        self._values.append(max(0.0, float(lux)))
        return out
