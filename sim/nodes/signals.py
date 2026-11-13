"""Synthetic signals for sim nodes (pure functions, unit-tested)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class PpgSynth:
    """Finger PPG with respiratory sinus arrhythmia. Emits int ADC samples (~16000 ± 2000).

    hr_bpm: mean heart rate. rsa_ms: IBI modulation amplitude at the breathing rate.
    During paced breathing (6/min) RSA grows, so RMSSD rises — mirroring the real effect.
    """

    fs_hz: float = 100.0
    hr_bpm: float = 68.0
    rsa_ms: float = 40.0
    breath_bpm: float = 12.0
    noise: float = 120.0
    seed: int | None = None
    _t: float = 0.0
    _next_beat: float = 0.3
    _beats: list[float] = field(default_factory=list)
    _rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def _ibi(self, t: float) -> float:
        base = 60.0 / self.hr_bpm
        rsa = (self.rsa_ms / 1000.0) * math.sin(2 * math.pi * (self.breath_bpm / 60.0) * t)
        return max(0.35, base + rsa + self._rng.gauss(0, 0.012))

    def samples(self, n: int) -> list[int]:
        out = []
        dt = 1.0 / self.fs_hz
        for _ in range(n):
            while self._next_beat <= self._t + 1.0:  # schedule beats one second ahead
                self._beats.append(self._next_beat)
                self._next_beat += self._ibi(self._next_beat)
            self._beats = [b for b in self._beats if b > self._t - 1.0]
            v = 0.0
            for b in self._beats:
                d = self._t - b
                v += math.exp(-((d - 0.12) ** 2) / (2 * 0.045**2))          # systolic peak
                v += 0.35 * math.exp(-((d - 0.36) ** 2) / (2 * 0.07**2))    # dicrotic wave
            out.append(int(16000 + 2000 * v + self._rng.gauss(0, self.noise)))
            self._t += dt
        return out


def approach_curve(t: float, start_cm: float = 200.0, end_cm: float = 50.0, dur_s: float = 3.0) -> float:
    """Distance while someone walks up to the robot (smoothstep)."""
    x = min(max(t / dur_s, 0.0), 1.0)
    s = x * x * (3 - 2 * x)
    return start_cm + (end_cm - start_cm) * s


def daylight_lux(hour: float) -> float:
    """Rough indoor lux by hour of day (0 at night, ~300 midday)."""
    if hour < 7 or hour > 19:
        return 5.0
    return 5.0 + 300.0 * math.sin(math.pi * (hour - 7) / 12)
