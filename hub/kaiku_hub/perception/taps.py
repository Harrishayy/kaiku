"""Drum taps -> tempo, force, regularity, energy and change over the session (psychomotor energy proxy).

Consumes raw/head/tap events (t_ms device clock, force in g). If a future head streams raw accel,
add a high-pass + peak detector here that produces the same (t_ms, force) events. A knock switch (KY-031) has no
force: its taps carry force=None and the summary's force_mean is None (never a made-up value).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

PAUSE_MS = 2000  # intervals longer than this are pauses, not rhythm
MAX_TEMPO_BPM = 400.0  # contract ceiling; faster drumming is reported as 400 with halved quality


@dataclass
class TapAnalyzer:
    refractory_ms: float = 80
    force_max_g: float = 4.0
    times: list[int] = field(default_factory=list)
    forces: list[float | None] = field(default_factory=list)
    rejected: int = 0  # double-triggers inside the refractory window (switch bounce, or drumming faster than we resolve)

    def add(self, t_ms: int, force: float | None = None) -> bool:
        """Add a tap. Returns False if rejected by the refractory window (double-trigger)."""
        if self.times and 0 <= t_ms - self.times[-1] < self.refractory_ms:
            self.rejected += 1
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

    def recent_tempo_bpm(self, taps: int = 8) -> float:
        """Tempo of the last few taps: what the music and the sway follow. The session's own tempo (`tempo_bpm`,
        the median of every interval) moves only once half the session is at the new speed: in a real run on
        2026-11-14 the music changed 10 s after she sped up. 0.0 until two intervals exist."""
        return self._tempo_of(self.times[-taps:]) or 0.0

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

    def _tempo_of(self, times: list[int]) -> float | None:
        iv = np.diff(np.asarray(times, dtype=float)) if len(times) >= 3 else np.array([])
        iv = iv[(iv > 0) & (iv <= PAUSE_MS)]
        return float(min(400.0, 60000.0 / np.median(iv))) if iv.size >= 2 else None

    def tempo_start_end(self) -> tuple[float | None, float | None]:
        """Tempo of the first and the last third of the taps: how the drumming changed over the session.
        None when a third has fewer than 3 taps (too little to call a tempo)."""
        n = len(self.times)
        if n < 9:
            return None, None
        k = n // 3
        return self._tempo_of(self.times[:k + 1]), self._tempo_of(self.times[-(k + 1):])

    def pauses(self) -> int:
        """Gaps longer than PAUSE_MS inside the session (the person stopped and started again)."""
        return int((np.diff(np.asarray(self.times, dtype=float)) > PAUSE_MS).sum()) if len(self.times) > 1 else 0

    def quality(self) -> float:
        """Share of raw triggers that were real taps, scaled down for very short sessions (< 8 taps).
        Low = bouncing switch, motor vibration or drumming faster than the sensor resolves: tempo is then a floor."""
        if not self.times:
            return 0.0
        kept = self.count / (self.count + self.rejected)
        iv = self.intervals()
        capped = 0.5 if iv.size and 60000.0 / float(np.median(iv)) > MAX_TEMPO_BPM else 1.0  # tempo_bpm is a floor
        return float(round(kept * min(1.0, self.count / 8) * capped, 3))

    def summary(self, duration_s: float) -> dict:
        """Payload for obs.drum_session. Optional fields stay out when they can't be computed (never made up)."""
        dur = max(0.0, duration_s)
        start, end = self.tempo_start_end()
        out = {
            "tempo_bpm": round(self.tempo_bpm(), 1),
            "force_mean": None if (fm := self.force_mean()) is None else round(fm, 3),
            "duration_s": round(dur, 1),
            "regularity": round(self.regularity(), 3),
            "taps": self.count,
            "tempo_start_bpm": None if start is None else round(start, 1),
            "tempo_end_bpm": None if end is None else round(end, 1),
            "taps_per_s": round(self.count / dur, 2) if dur >= 1.0 else None,
            "pauses": self.pauses(),
            "rejected_taps": self.rejected,
        }
        return out
