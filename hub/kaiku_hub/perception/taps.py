"""Drum taps -> tempo, force, regularity (psychomotor energy proxy).

Consumes raw/head/tap events (t_ms device clock, force in g). If a future head streams raw accel,
add a high-pass + peak detector here that produces the same (t_ms, force) events. A knock switch (KY-031) has no
force: its taps carry force=None and the summary's force_mean is None (never a made-up value).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

PAUSE_MS = 2000  # intervals longer than this are pauses, not rhythm


@dataclass
class TapAnalyzer:
    refractory_ms: float = 80
    force_max_g: float = 4.0
    times: list[int] = field(default_factory=list)
    forces: list[float | None] = field(default_factory=list)

    def add(self, t_ms: int, force: float | None = None) -> bool:
        """Add a tap. Returns False if rejected by the refractory window (double-trigger)."""
        if self.times and 0 <= t_ms - self.times[-1] < self.refractory_ms:
            return False
        if self.times and t_ms < self.times[-1]:  # device clock reset: start a new run
            self.times.clear()
            self.forces.clear()
        self.times.append(int(t_ms))
        self.forces.append(None if force is None else float(force))
        return True

    @property
    def count(self) -> int:
        return len(self.times)

    def intervals(self) -> np.ndarray:
        if len(self.times) < 2:
            return np.array([])
        iv = np.diff(np.asarray(self.times, dtype=float))
        return iv[(iv > 0) & (iv <= PAUSE_MS)]

    def tempo_bpm(self) -> float:
        iv = self.intervals()
        return float(min(400.0, 60000.0 / np.median(iv))) if iv.size else 0.0

    def regularity(self) -> float:
        iv = self.intervals()
        if iv.size < 2:
            return 0.0
        cv = float(np.std(iv) / np.mean(iv))
        return float(np.clip(1.0 - cv, 0.0, 1.0))

    def force_mean(self) -> float | None:
        """Mean force 0-1, or None if any tap had no force (knock switch) or there are no taps."""
        if not self.forces or any(f is None for f in self.forces):
            return None
        return float(np.clip(np.mean(self.forces) / self.force_max_g, 0.0, 1.0))

    def summary(self, duration_s: float) -> dict:
        """Payload for obs.drum_session."""
        return {
            "tempo_bpm": round(self.tempo_bpm(), 1),
            "force_mean": None if (fm := self.force_mean()) is None else round(fm, 3),
            "duration_s": round(max(0.0, duration_s), 1),
            "regularity": round(self.regularity(), 3),
            "taps": self.count,
        }
